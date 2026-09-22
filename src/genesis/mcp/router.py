# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""Which handful of tools an agent is shown for the task in front of it.

MCP Gateway.md calls this *"the single most important design decision in the
gateway"*, and the reason is not ergonomics. With two hundred tools registered,
putting every schema in context makes reasoning **worse** — the agent starts
picking defensible-but-wrong tools — so adding a useful server actively harms
the system. The router is what makes "unlimited MCP servers" a capability
rather than a slogan: the catalogue grows, the agent's view does not.

**Deterministic, not model-backed.** This was the open decision in the build
plan and it resolves the way Biological Design §reflex arc resolves everything:
selection runs on *every* call, must never hallucinate a tool that does not
exist, and lexical ranking over a catalogue we wrote the capability names for is
a solved problem. A model here would add a network hop, a failure mode and a
nondeterminism to the one component whose output must be reproducible for an
eval to mean anything. If the eval says the reflex is not good enough, a model
tier goes *in front* of it — it does not replace it.

Three things the ranker knows that a bare keyword search would not:

``capability`` outranks ``description``
    We chose the capability names. ``market-data.ohlcv`` is a deliberate,
    stable description of what a tool is *for*; a server's own prose is
    marketing written by somebody else, and matching it too eagerly is how
    ``get_quote`` loses to a news tool whose blurb happens to say "quote".

Namespaces are a signal
    A task that says "news" should surface all of ``news.*`` even where no
    individual word matches, because the agent asked for a *kind* of tool.

A source that keeps serving injections gets buried
    :class:`~genesis.mcp.fence.TrustLedger` lowers a server's score on every
    detection, and that score multiplies here. Rule 4 of the fence says trust
    is lowered; this is the place where lowering it *does* something. It never
    reaches zero-and-vanish: a buried tool is still reachable through
    :meth:`ToolRouter.search`, because silently removing a source would let one
    injection amputate a capability.

The escape hatch, and why it is capped
-------------------------------------
No ranker is right every time. ``toolSearch`` lets an agent that has discovered
it needs something ask for it mid-task. It is **capped per reply**
(:class:`SearchBudget`) because an uncapped search tool is a loop: an agent that
cannot find what it wants searches again with a rephrasing, forever, and the cap
converts an infinite loop into a bounded failure that says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable, Sequence

from genesis.mcp.spec import ToolSpec

if TYPE_CHECKING:  # pragma: no cover - typing only
    from genesis.mcp.fence import TrustLedger
    from genesis.mcp.registry import ToolRegistry

__all__ = [
    "DEFAULT_LIMIT",
    "Selection",
    "SearchBudget",
    "SearchBudgetExhausted",
    "ToolRouter",
    "tokenize",
]

#: How many tools an agent sees per task. MCP Gateway.md says "~8" and means
#: it: the number is a context-rot budget, not a capacity limit. Raising it is
#: the cheap thing to do when selection looks wrong, and it is almost always
#: the wrong fix — a bad selection at k=8 is a ranking bug, and hiding it at
#: k=25 costs every agent reasoning quality on every task.
DEFAULT_LIMIT = 8

#: Words that appear in half the catalogue and in every task description. They
#: carry no signal and, worse, they carry *misleading* signal: nearly every
#: server's blurb contains "data", so a task mentioning data would rank the
#: whole catalogue equally and hand the tie-break the entire decision.
_STOPWORDS = frozenset(
    """
    a about all also an and any are as at be been but by can could do does for
    from get gets give go had has have how i if in into is it its just like
    make may me my need needs no not of on one only or our out over please
    should so some such than that the their them then there these they this
    those to up use used using want was we were what when where which who will
    with would you your data info information tool tools server result results
    return returns value values api call calls
    """.split()
)

_TOKEN = re.compile(r"[a-z0-9]+")

#: ``8-K`` -> ``8k``, ``10-Q`` -> ``10q``. Splitting on the hyphen produces
#: ``8`` and ``k``, both of which the length filter then drops — so the most
#: specific word in "pull the 8-K" would contribute nothing, and a filings
#: query would rank on the word "pull". Form names are the vocabulary of an
#: entire server here; they are not an edge case.
_FORM_NAME = re.compile(r"(\d)-([a-z])")

#: Field weights. The spread matters more than the absolute numbers: a
#: capability hit must beat *several* description hits, or a tool with a
#: verbose blurb outranks the tool that is literally named after what was
#: asked for.
_W_CAPABILITY = 4.0
_W_NAME = 2.5
_W_DESCRIPTION = 1.0
#: Awarded once when the task names a whole namespace ("news", "vault").
_W_NAMESPACE = 3.0


#: Words ending in ``s`` that are not plurals. The list is short because the
#: suffix rules below catch most of them (``-ss``, ``-us``, ``-is``); these are
#: the ones that slip through, and ``news`` is the expensive one — it is a
#: capability namespace, so folding it to ``new`` silently disconnects every
#: task that says "news" from every tool under ``news.*``.
_NOT_PLURAL = frozenset({"news", "gas", "bars", "as", "its", "this"})
_KEEP_SUFFIX = ("ss", "us", "is", "os")


def tokenize(text: str) -> tuple[str, ...]:
    """Lowercase alphanumeric words, stopwords dropped, plurals folded.

    Plural folding is a single trailing ``s`` and nothing cleverer, guarded by
    a handful of exceptions. A real stemmer would be worse here, not better: it
    collapses ``quotes`` and ``quoting``, which we want, and also ``analysis``
    and ``series``, which are capability names we wrote and must match exactly.
    The cheap rule wins because the vocabulary on one side of the comparison is
    ours.
    """
    out: list[str] = []
    for raw in _TOKEN.findall(_FORM_NAME.sub(r"\1\2", text.lower())):
        word = raw
        if (
            len(raw) > 3
            and raw.endswith("s")
            and raw not in _NOT_PLURAL
            and not raw.endswith(_KEEP_SUFFIX)
        ):
            word = raw[:-1]
        if word in _STOPWORDS or len(word) < 2:
            continue
        out.append(word)
    return tuple(out)


@dataclass(frozen=True)
class Selection:
    """What the router chose, and enough to explain why.

    ``matched`` is the field that matters operationally. ``False`` means no
    token in the task touched any tool the agent can reach, and the tools below
    are a deterministic fallback rather than a decision. An agent that cannot
    tell those two cases apart will present a guess as a choice — and a
    selection log that cannot say "I had nothing to go on" is a log that
    invents a rationale after the fact.
    """

    tools: tuple[ToolSpec, ...]
    #: Every tool the agent could have been shown, before ranking. The
    #: denominator for "did the router actually narrow anything".
    considered: int
    #: Score per chosen tool id, highest first. Read by evals and by the log.
    scores: tuple[tuple[str, float], ...] = ()
    matched: bool = True

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(spec.id for spec in self.tools)

    def __len__(self) -> int:
        return len(self.tools)

    def __iter__(self):  # pragma: no cover - trivial
        return iter(self.tools)


class SearchBudgetExhausted(RuntimeError):
    """``toolSearch`` was called more times in one reply than allowed.

    Deliberately not a :class:`~genesis.errors.GenesisError`: this is not a
    failure of the system, it is the cap doing its job, and the agent should
    see it as an answer ("stop searching, decide with what you have") rather
    than as something the Task Bus might usefully retry.
    """


@dataclass
class SearchBudget:
    """One reply's worth of ``toolSearch`` calls.

    Created per reply, never shared. A budget that outlived a reply would be a
    rate limit on the *agent* rather than a loop breaker on the *reply*, and
    those cap different things: an agent legitimately searches once per task,
    forever; it never legitimately searches four times for the same task.
    """

    limit: int = 3
    used: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def spend(self) -> None:
        if self.used >= self.limit:
            raise SearchBudgetExhausted(
                f"toolSearch is capped at {self.limit} calls per reply. "
                f"Decide with the tools already selected, or report that none fit."
            )
        self.used += 1


@dataclass(frozen=True)
class _Indexed:
    """One tool, pre-tokenized. Built once at start-up, read on every call."""

    spec: ToolSpec
    capability: frozenset[str]
    name: frozenset[str]
    description: frozenset[str]
    #: Curated synonyms. Scored at capability weight because they are ours.
    keywords: frozenset[str]
    namespace: str


class ToolRouter:
    """Ranks the catalogue against a task description.

    The index is built once from a registry and reused, which is what makes the
    acceptance criterion reachable: *adding 50 tools changes latency by <10%*.
    Scoring is linear in the number of *query* tokens and the size of the
    candidate set, not in the size of the catalogue — the per-call cost of a
    server nobody's task mentions is one dictionary lookup that misses.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        trust: TrustLedger | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> None:
        self._registry = registry
        self._trust = trust
        self.limit = limit
        self._index: dict[str, _Indexed] = {}
        #: Document frequency per description token, used to damp the words
        #: that half the catalogue shares. See :meth:`_score`.
        self._df: dict[str, int] = {}
        self._indexed_size = -1

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def _ensure_index(self) -> dict[str, _Indexed]:
        """Rebuild only if the catalogue changed size.

        The registry is built once on one thread and read from many afterwards
        — it says so itself — so this is a cheap guard against the one case
        that does happen: a test that registers more tools into a registry a
        router already saw.
        """
        if len(self._registry) != self._indexed_size:
            self._index = {
                spec.id: _index_one(spec) for spec in self._registry
            }
            df: dict[str, int] = {}
            for entry in self._index.values():
                for token in entry.description:
                    df[token] = df.get(token, 0) + 1
            self._df = df
            self._indexed_size = len(self._registry)
        return self._index

    # ------------------------------------------------------------------
    # Selecting
    # ------------------------------------------------------------------

    def select(
        self,
        task: str,
        candidates: Iterable[ToolSpec],
        *,
        task_type: str = "",
        limit: int | None = None,
    ) -> Selection:
        """The ~8 tools worth showing for this task, best first.

        ``candidates`` is the agent's allow-listed surface and nothing wider.
        Ranking the whole catalogue and filtering afterwards would be the same
        answer at higher cost — and would leak the existence of tools an agent
        may not call into a log it can see.
        """
        limit = self.limit if limit is None else limit
        pool = tuple(candidates)
        index = self._ensure_index()

        # The task type is a real signal — "news scan" and "risk review" reach
        # for different halves of the catalogue — and it is short, so it is
        # weighted by repetition rather than by a separate coefficient.
        query = tokenize(f"{task_type} {task_type} {task}")
        if not query:
            return self._unranked(pool, limit)

        scored: list[tuple[float, int, str, ToolSpec]] = []
        for spec in pool:
            entry = index.get(spec.id) or _index_one(spec)
            score = self._score(query, entry)
            if score > 0:
                # Sort key, in order: score, source tier, capability
                # specificity, then id.
                #
                # The third is the interesting one. When two tools of one
                # server tie — which happens constantly, because a server's
                # keywords are true of all of it — the tie must not fall to
                # alphabetical order, or "what time is it" reaches
                # `time.convert` because c sorts before n. A shorter capability
                # leaf is the plainer, more general tool: `time.now` over
                # `time.convert`, `filings.recent` over
                # `filings.material-event`, `papers.search` over
                # `papers.download`. The rule that makes this right rather than
                # merely convenient is that a *specialised* tool should have
                # had to earn its place with a word naming its specialisation —
                # if nothing in the task said "convert", the task did not ask
                # to convert.
                #
                # id remains last so the whole ordering stays total, and the
                # same catalogue and task produce the same eight tools on every
                # run. That determinism is what makes the selection eval mean
                # anything.
                leaf = entry.spec.capability.rpartition(".")[2]
                scored.append(
                    (-score, entry.spec.tier, len(leaf), entry.spec.id, spec)
                )

        if not scored:
            return self._unranked(pool, limit)

        scored.sort()
        chosen = scored[:limit]
        return Selection(
            tools=tuple(item[4] for item in chosen),
            considered=len(pool),
            scores=tuple((item[3], round(-item[0], 3)) for item in chosen),
        )

    def search(
        self,
        query: str,
        candidates: Iterable[ToolSpec],
        *,
        budget: SearchBudget | None = None,
        limit: int = 5,
    ) -> Selection:
        """The ``toolSearch`` escape hatch: same ranking, agent-initiated.

        Spends a unit of the reply's budget *before* ranking, so an exhausted
        budget costs nothing and a search that finds nothing still counts. A
        cap that only charged for successful searches would not cap the loop it
        exists to break — the loop is made of failures.
        """
        if budget is not None:
            budget.spend()
        return self.select(query, candidates, limit=limit)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score(self, query: Sequence[str], entry: _Indexed) -> float:
        """Best field wins per token, then the source's trust scales the total.

        Best-field rather than sum-of-fields: a tool whose description repeats
        its own capability would otherwise score twice for saying one thing,
        which rewards verbosity in somebody else's prose.

        **Description matches are damped by how common the word is; capability,
        name and keyword matches are not.** The asymmetry is the point. We
        wrote the capability names and the keywords, so a match there is a
        match against a deliberate statement about what a tool is for. A
        description is a vendor's blurb, and forty servers whose blurbs all say
        "records, documents, reports and data" would otherwise each collect a
        point for sharing vocabulary with everything — which is not evidence,
        it is noise with a score attached.
        """
        total = 0.0
        for token in query:
            if token in entry.capability or token in entry.keywords:
                total += _W_CAPABILITY
            elif token in entry.name:
                total += _W_NAME
            elif token in entry.description:
                total += _W_DESCRIPTION * self._idf(token)
            if token == entry.namespace:
                total += _W_NAMESPACE

        if total <= 0:
            return 0.0

        # Rule 4 of the fence, made operative. A server at 0.2 still ranks —
        # last — because a capability that vanishes after one injection is a
        # capability an attacker can delete.
        if self._trust is not None:
            total *= self._trust.score(entry.spec.server)
        return total

    def _idf(self, token: str) -> float:
        """How much a description hit on this word is worth, in [0.2, 1.0].

        A word in one description is worth a full point; a word in a third of
        the catalogue is worth almost nothing. Clamped at the top so a rare
        word in a blurb can never outrank a capability match — the field
        ordering is a design decision and must not be reachable by statistics.
        """
        total = self._indexed_size
        if total <= 0:
            return 1.0
        frequency = self._df.get(token, 0) / total
        if frequency <= 0.02:
            return 1.0
        return max(0.2, 1.0 - frequency * 4)

    def _unranked(self, pool: Sequence[ToolSpec], limit: int) -> Selection:
        """No signal in the task. Say so, and hand back a stable prefix.

        Returning nothing would be more honest and less useful — an agent with
        zero tools cannot act at all. Returning everything would be the context
        rot this module exists to prevent. A capped, deterministic, low-tier-
        first prefix is the compromise, and ``matched=False`` is the part that
        stops it being read as a decision.
        """
        ordered = sorted(pool, key=lambda s: (s.tier, s.id))[:limit]
        return Selection(
            tools=tuple(ordered), considered=len(pool), matched=False
        )


def _index_one(spec: ToolSpec) -> _Indexed:
    capability_tokens = set(tokenize(spec.capability.replace(".", " ")))
    return _Indexed(
        spec=spec,
        capability=frozenset(capability_tokens),
        name=frozenset(tokenize(spec.name)),
        # Capped: a server that ships three paragraphs per tool would otherwise
        # dominate the index by sheer surface area, and everything past the
        # first sentence or two is examples and caveats.
        description=frozenset(tokenize(spec.description)[:40]),
        keywords=frozenset(tokenize(" ".join(spec.keywords))),
        # Folded through the same tokenizer as the query. Comparing a raw
        # namespace against folded query tokens is a mismatch that only shows
        # up for the namespaces the folder happens to touch — which is the
        # worst kind, because the other twenty work.
        namespace=next(iter(tokenize(spec.capability.partition(".")[0])), ""),
    )
