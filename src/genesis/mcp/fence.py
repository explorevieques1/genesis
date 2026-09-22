# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""Untrusted content is data, never instruction.

MCP Gateway.md: *"All content from web, news, social, or any third-party MCP is
data, never instruction."* Everything in this module exists to make that true
mechanically, because the alternative -- asking a model nicely, in a prompt --
is the thing prompt injection is *for*.

Five rules in the note. Four are here; the fifth is Phase 4's.

1. **Every external result is wrapped before it reaches a model.** :func:`wrap`.
2. Every agent prompt states the rule. Phase 4, in Agent Contract's prompt
   structure -- and note that it is rule *two*, not rule one. The prompt is the
   reminder; the wrapping is the mechanism.
3. **Untrusted content is never embedded verbatim** into the Vector Store.
   Phase 4/8, enforced there; :attr:`Fenced.embeddable` carries the answer so
   the store never has to work it out.
4. **A detected injection attempt is logged, flagged on the record, and lowers
   the source's trust score.** :func:`scan` and :class:`TrustLedger`.
5. **SSRF guard on any fetch.** :func:`check_url`.

**The escape problem, and why there is no nonce.**
A fence made of text can be forged with text. Content containing
``</untrusted>`` would close the wrapper early and everything after it would
read as instruction -- the injection this module exists to stop, achieved by
typing the defence's own syntax. Two defences were available:

*A per-call random nonce in the tag.* Forgery becomes infeasible, but only if
the reader knows which nonce is authoritative, and a static agent prompt cannot
know a per-call value. It moves the problem into prompt coordination, where it
is harder to test.

*Neutralising fence markup in the content.* Deterministic, testable in one
assertion, needs no cooperation from the reader. :func:`neutralize` does this,
and it is why :func:`wrap` cannot be broken out of by its input.

The second is chosen because it is a reflex: it cannot be argued with, it needs
nothing from the model, and a test can prove it holds for arbitrary input.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Iterable
from urllib.parse import urlsplit

__all__ = [
    "Fenced",
    "TrustLedger",
    "UnsafeUrlError",
    "check_url",
    "neutralize",
    "scan",
    "text_of",
    "wrap",
]

# --------------------------------------------------------------------------
# Wrapping
# --------------------------------------------------------------------------

#: Anything that looks like our fence, in any casing, with or without a slash.
#: Deliberately broad: a partial or malformed tag is still an attempt to
#: confuse a reader about where the quoted region ends.
_FENCE_MARKUP = re.compile(r"</?\s*untrusted\b[^>]*>?", re.IGNORECASE)

#: What a neutralised tag becomes. Visible on purpose -- a reader (human or
#: model) should be able to see that something tried to close the fence, and
#: :func:`scan` counts it as evidence.
_DEFANGED = "[fence-markup-removed]"


def neutralize(text: str) -> str:
    """Strip fence markup from content so it cannot close its own wrapper."""
    return _FENCE_MARKUP.sub(_DEFANGED, text)


@dataclass(frozen=True)
class Fenced:
    """Untrusted content, wrapped, with what we noticed about it attached."""

    text: str
    source: str
    retrieved: datetime
    #: Injection patterns that fired. Empty is the ordinary case.
    flags: tuple[str, ...] = ()
    url: str | None = None

    @property
    def suspicious(self) -> bool:
        return bool(self.flags)

    @property
    def embeddable(self) -> bool:
        """Rule 3. Never verbatim into the Vector Store -- summarise first.

        Always False. The property exists so the answer travels with the
        content rather than being re-derived by whoever is about to store it,
        which is where it would eventually be got wrong.
        """
        return False


def wrap(
    content: str,
    *,
    source: str,
    url: str | None = None,
    retrieved: datetime | None = None,
) -> Fenced:
    """Wrap third-party text so a model reads it as quoted data.

    Scanning happens on the *original* text, before neutralising, so an attempt
    to close the fence is recorded rather than quietly cleaned away.
    """
    flags = scan(content)
    body = neutralize(content)
    when = retrieved or datetime.now(UTC)
    stamp = when.isoformat(timespec="seconds").replace("+00:00", "Z")

    attrs = f'source="{_attr(source)}" retrieved="{stamp}"'
    if url:
        attrs += f' url="{_attr(url)}"'
    if flags:
        # Said out loud in the payload, not only in the log. Whoever reads this
        # should know the text tried something before they read what it said.
        attrs += ' warning="injection-patterns-detected"'

    return Fenced(
        text=f"<untrusted {attrs}>\n{body}\n</untrusted>",
        source=source,
        retrieved=when,
        flags=flags,
        url=url,
    )


def _attr(value: str) -> str:
    """Attribute values cannot break out of their own quotes either."""
    return neutralize(value).replace('"', "&quot;").replace("\n", " ")[:200]


def text_of(content: Any) -> str:
    """Flatten an MCP content payload to text.

    Servers return a list of typed blocks. Anything that is not text is
    described rather than dropped -- an agent that silently receives less than
    the server sent is an agent reasoning about a truncated world.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, Iterable):
        return str(content)

    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(str(text))
        else:
            kind = getattr(block, "type", type(block).__name__)
            parts.append(f"[non-text content: {kind}]")
    return "\n".join(parts)


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------

#: Patterns that are evidence, not proof. A news article legitimately about
#: prompt injection would trip several, which is why the consequence is a flag
#: and a lowered trust score rather than a refusal: dropping the content would
#: hand any attacker a censorship tool, and the fence already holds without it.
_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("override-instructions", re.compile(
        r"\b(ignore|disregard|forget|override)\b.{0,40}\b"
        r"(previous|prior|above|earlier|all)\b.{0,20}\b"
        r"(instruction|prompt|rule|direction|context)",
        re.IGNORECASE | re.DOTALL)),
    ("identity-reassignment", re.compile(
        r"\byou\s+are\s+(now|actually)\b|\bnew\s+(persona|identity|role)\b",
        re.IGNORECASE)),
    ("system-prompt-probe", re.compile(
        r"\b(system\s+prompt|your\s+instructions|initial\s+prompt)\b",
        re.IGNORECASE)),
    ("fence-escape", re.compile(r"</?\s*untrusted\b", re.IGNORECASE)),
    ("role-markup", re.compile(
        r"^\s*(system|assistant|human)\s*:|<\|im_(start|end)\|>|\[/?INST\]",
        re.IGNORECASE | re.MULTILINE)),
    ("tool-invocation", re.compile(
        r"<(tool_use|function_calls|invoke)\b|\bcall\s+the\s+\w+\s+tool\b",
        re.IGNORECASE)),
    # The money one. Any third-party text steering trading or moving funds is
    # flagged regardless of how politely it is phrased.
    ("trade-instruction", re.compile(
        r"\b(place|submit|execute|send)\b.{0,20}\b(order|trade|buy|sell)\b|"
        r"\b(transfer|withdraw|wire)\b.{0,20}\b(funds|money|balance|account)\b",
        re.IGNORECASE | re.DOTALL)),
    ("credential-probe", re.compile(
        r"\b(api[_\s-]?key|secret[_\s-]?key|password|token|credential)s?\b.{0,30}"
        r"\b(reveal|show|print|send|output|share)\b|"
        r"\b(reveal|show|print|send|output|share)\b.{0,30}"
        r"\b(api[_\s-]?key|secret[_\s-]?key|password|token|credential)s?\b",
        re.IGNORECASE | re.DOTALL)),
)


def scan(text: str) -> tuple[str, ...]:
    """Which injection patterns fired. Cheap, deterministic, no model.

    A reflex in the Biological Design sense: it runs on every untrusted result,
    in microseconds, and cannot be talked out of firing by the text it is
    reading.
    """
    return tuple(name for name, pattern in _INJECTION_PATTERNS if pattern.search(text))


# --------------------------------------------------------------------------
# Trust
# --------------------------------------------------------------------------


@dataclass
class TrustLedger:
    """How much a source has earned. Rule 4's "trust score is lowered".

    Starts at 1.0 and only ever falls within a session. Sources do not recover
    by waiting: a site that served one injection is not cleaner an hour later,
    and a decay-back-to-trusted would let a patient attacker amortise attempts.
    Recovery is a deliberate act -- :meth:`reset` -- which is a person deciding,
    not a timer.

    In-memory for now. Persisting across restarts belongs with the Knowledge
    Graph in Phase 8, where a source's history is a first-class thing rather
    than a number this class is guessing at.
    """

    scores: dict[str, float] = field(default_factory=dict)
    #: What one detection costs. Four strikes and a source is at 0.2, which is
    #: low enough for a ranker to bury it without it vanishing unexplained.
    penalty: float = 0.2
    floor: float = 0.0

    def __post_init__(self) -> None:
        self._lock = threading.Lock()

    def score(self, source: str) -> float:
        with self._lock:
            return self.scores.get(source, 1.0)

    def penalise(self, source: str, flags: Iterable[str]) -> float:
        """Lower a source's score once per detection event, not once per flag.

        Per-flag would punish a single elaborate attempt eight times and a
        subtle one once, ranking the subtle attacker as the more trustworthy of
        the two.
        """
        if not tuple(flags):
            return self.score(source)
        with self._lock:
            current = self.scores.get(source, 1.0)
            new = max(self.floor, round(current - self.penalty, 4))
            self.scores[source] = new
            return new

    def reset(self, source: str) -> None:
        with self._lock:
            self.scores.pop(source, None)

    def suspect(self, threshold: float = 0.6) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(s for s, v in self.scores.items() if v < threshold))


# --------------------------------------------------------------------------
# SSRF
# --------------------------------------------------------------------------


class UnsafeUrlError(ValueError):
    """A URL that must not be fetched. Rule 5."""


_ALLOWED_SCHEMES = frozenset({"http", "https"})


def check_url(url: str, *, resolve: bool = True) -> str:
    """Reject anything that could reach inside the machine or the network.

    The gateway validates *arguments* before dispatch, which is the part it can
    actually enforce. A server's own redirect-following is beyond our reach --
    which is precisely why a fetch server is a named, allow-listed tool with a
    tier rather than a general capability, and why the note pairs this rule with
    "no redirects to private ranges" as a property to demand of the server.

    ``resolve`` does a DNS lookup, so a hostname that points at 127.0.0.1 or a
    metadata endpoint is caught rather than merely a literal address. It costs a
    lookup on the call path; a name that resolves inward is the entire attack.
    """
    parts = urlsplit(url.strip())

    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(
            f"scheme {parts.scheme or '(none)'!r} is not fetchable — "
            f"file, gopher, data and friends are how a fetch becomes a read"
        )
    if not parts.hostname:
        raise UnsafeUrlError(f"no host in {url!r}")

    host = parts.hostname
    candidates: list[str] = [host]
    if resolve and not _is_ip(host):
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise UnsafeUrlError(f"{host!r} does not resolve: {exc}") from exc
        candidates.extend(info[4][0] for info in infos)

    for candidate in candidates:
        if not _is_ip(candidate):
            continue
        address = ipaddress.ip_address(candidate)
        if not address.is_global or address.is_private:
            raise UnsafeUrlError(
                f"{url!r} resolves to {address}, which is not a public address"
            )
    return url


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True
