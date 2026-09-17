# Spec: Genesis Markdown/40-Memory/Vector Store.md
"""Layer four: *what else is like this?*

The other four layers each answer a different question and none of them answers
this one. The graph holds what the system believes and refuses to compute
similarity on purpose -- a graph built from embedding distance shows what
resembles what, where the graph shows what *justifies* what. Both are useful;
they are not the same store, and this is the other one.

Four rules from the note are structural here rather than conventional.

**The source text is stored, not just the vector.** Re-embedding on a model
change must not require re-deriving the text from whatever produced it, because
by then that thing has moved on.

**The embedding model is versioned per row, and a mismatch is never averaged.**
Cosine between vectors from two different models is a number with no meaning,
and it looks exactly like a good score. :meth:`VectorStore.search` therefore
filters to the current model in SQL and reports what it skipped
(:meth:`stale`), which is what [[Memory Consolidation]] pass 7 re-embeds. The
alternative -- refusing to search at all until a re-embed finishes -- makes a
model upgrade an outage.

**Namespace filtering happens before scoring.** An agent must not *see* results
outside its declared namespaces ([[Agent Contract]]), so the filter is a WHERE
clause and not a post-filter on a ranked list. Post-filtering leaks: the top-k
is chosen across everything and then trimmed, so what an agent gets back
depends on memories it was never allowed to read.

**Nothing untrusted and nothing secret is embedded.** :class:`~genesis.mcp.fence.Fenced`
already carries ``embeddable = False`` so the answer travels with the content;
a fenced object handed to :meth:`write` is refused rather than unwrapped.
Secrets are scrubbed with the same redactor the log uses -- one implementation,
because two redactors is one redactor and one leak.

**There is no fallback embedder, deliberately.** A hash-based or random
"embedding" would make every acceptance criterion here pass while returning
nonsense, and nonsense that scores 0.83 is worse than an empty result. With no
model present the store raises ``degraded`` and says which file is missing.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence

from genesis.errors import DegradedError, FatalError
from genesis.memory.db import connect, transaction

__all__ = [
    "Embedder",
    "Hit",
    "OnnxEmbedder",
    "SCHEMA",
    "VectorStore",
    "embedder_for",
]

#: Content kinds, from the note's "what gets embedded" table. Open-ended like
#: the Episodic Log's, but these are the ones with writers today.
KINDS = (
    "idea", "thesis", "lesson", "journal", "research", "brief",
    "catalyst", "markup", "strategy", "note",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS vec_chunk (
    -- The content hash. Writing the same text into the same namespace twice is
    -- one row, which is the cheap half of deduplication; the expensive half is
    -- near-duplicate detection at write time, below.
    id         TEXT PRIMARY KEY,
    namespace  TEXT NOT NULL,
    kind       TEXT NOT NULL,
    -- The record that owns the content: an idea id, a note path, a markup spec.
    -- Like the graph, this store points rather than becoming a second source
    -- of truth for text that already has an owner.
    ref        TEXT,
    text       TEXT NOT NULL,
    -- Versioned per row. Mixed-model vectors in one index produce silently
    -- wrong results, which the note calls the worst kind.
    model      TEXT NOT NULL,
    dim        INTEGER NOT NULL,
    vec        BLOB NOT NULL,
    meta       TEXT NOT NULL DEFAULT '{}',
    created    TEXT NOT NULL
);
-- Namespace and model lead the index because both are WHERE clauses on every
-- search: the first for authorisation, the second for correctness.
CREATE INDEX IF NOT EXISTS vec_chunk_ns ON vec_chunk (namespace, model, kind);
CREATE INDEX IF NOT EXISTS vec_chunk_ref ON vec_chunk (ref);
"""

#: bge asks for this prefix on the *query* side only; passages are embedded
#: bare. Omitting it costs a few points of recall and is invisible, which is
#: why it lives in code rather than in a caller's memory.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

#: Above this cosine, two chunks in the same namespace are the same thought
#: said twice. The note's example is a daily brief whose phrasing appears 200
#: times; that is what this number is for.
NEAR_DUPLICATE = 0.98


class Embedder(Protocol):
    """Anything that turns text into unit vectors of a known model."""

    model: str
    dim: int

    def encode(self, texts: Sequence[str], *, query: bool = False) -> Any: ...


@dataclass(frozen=True)
class Hit:
    """One retrieved chunk. ``score`` is cosine, so 1.0 is identical."""

    id: str
    kind: str
    namespace: str
    ref: str | None
    text: str
    score: float
    created: str
    meta: dict[str, Any]


class OnnxEmbedder:
    """`bge-small-en-v1.5` on CPU via onnxruntime, per the embedding tier.

    Local because the embedding tier is the one tier the machine can actually
    serve (LLM Model Tiers: no GPU, so nothing *generative* runs local -- a
    33M-parameter encoder is a different proposition from a 70B decoder).

    The session is built on first use, not in ``__init__``: the daemon
    constructs a lot of things at start-up and paying 200 ms of ONNX
    initialisation for a path that may never be taken is the kind of cost that
    shows up as "the daemon takes a while to come up" and is never traced back.
    """

    #: CLS pooling, which is what bge was trained with. Mean pooling on a bge
    #: checkpoint quietly loses a few points of retrieval quality.
    def __init__(self, model_dir: Path | str, *, model: str = "bge-small-en-v1.5") -> None:
        self.dir = Path(model_dir).expanduser()
        self.model = model
        self.dim = 384
        self._session: Any = None
        self._tokenizer: Any = None

    @property
    def onnx_path(self) -> Path:
        return self.dir / "model.onnx"

    @property
    def tokenizer_path(self) -> Path:
        return self.dir / "tokenizer.json"

    def available(self) -> bool:
        return self.onnx_path.exists() and self.tokenizer_path.exists()

    def _load(self) -> None:
        if self._session is not None:
            return
        if not self.available():
            raise DegradedError(
                f"the embedding model is not installed — expected "
                f"{self.onnx_path} and {self.tokenizer_path}. Fetch it with "
                f"`genesis memory install-embedder`.",
                spoken_summary="I can't search memory by meaning — the embedding model isn't installed.",
            )
        try:
            import onnxruntime  # noqa: PLC0415
            from tokenizers import Tokenizer  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - both are core deps
            raise DegradedError(f"the embedding runtime is unavailable: {exc}") from exc

        self._tokenizer = Tokenizer.from_file(str(self.tokenizer_path))
        self._tokenizer.enable_truncation(max_length=512)
        self._tokenizer.enable_padding()
        opts = onnxruntime.SessionOptions()
        opts.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
        # One thread. This runs beside a daemon, a UI and an order manager, and
        # a batch embed that saturates every core makes the rest of the system
        # jittery for a job that is never urgent.
        opts.intra_op_num_threads = 1
        self._session = onnxruntime.InferenceSession(
            str(self.onnx_path), opts, providers=["CPUExecutionProvider"]
        )

    def encode(self, texts: Sequence[str], *, query: bool = False) -> Any:
        """Unit-normalised CLS embeddings, one row per text."""
        import numpy as np  # noqa: PLC0415

        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        self._load()
        prepared = [QUERY_PREFIX + t if query else t for t in texts]
        encodings = self._tokenizer.encode_batch(prepared)
        ids = np.array([e.ids for e in encodings], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        names = {i.name for i in self._session.get_inputs()}
        if "token_type_ids" in names:
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = self._session.run(None, {k: v for k, v in feed.items() if k in names})[0]
        cls = hidden[:, 0, :]
        norms = np.linalg.norm(cls, axis=1, keepdims=True)
        # A zero vector would divide to NaN and then score as a match against
        # everything, which is the failure mode that looks like a good result.
        norms[norms == 0] = 1.0
        return (cls / norms).astype(np.float32)


def embedder_for(config: Any) -> OnnxEmbedder:
    """The embedder the config's embedding tier names.

    Model files live beside the databases rather than in the repo: they are
    large, machine-local, and regenerable, which is the same reason the market
    store lives there.
    """
    tier = config.llm.embedding
    name = tier.model or "bge-small-en-v1.5"
    root = Path(config.memory.db_path).expanduser().parent / "models" / name
    return OnnxEmbedder(root, model=name)


class VectorStore:
    """Semantic recall over what the system has written and read."""

    def __init__(
        self,
        path: Path | str,
        embedder: Embedder,
        *,
        redact: Any = None,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        self.path = Path(path).expanduser()
        self.embedder = embedder
        #: The log's redactor, passed in rather than imported, so the store
        #: never has to know how secrets are discovered.
        self._redact = redact or (lambda s: s)
        self._conn = conn or connect(self.path)
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------

    def write(
        self,
        text: Any,
        *,
        kind: str,
        namespace: str,
        ref: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> str | None:
        """Embed and store one chunk. Returns its id, or ``None`` if skipped.

        ``None`` is the deduplication answer -- the same thought is already in
        there -- and is deliberately not an error: the consolidator re-walks
        content it has already seen every night and a skip is the expected
        outcome, not a problem to report.
        """
        if kind not in KINDS:
            raise FatalError(f"unknown chunk kind {kind!r} — see Vector Store.md")
        # Rule 3, and the reason `embeddable` is a property on the fence rather
        # than a judgement at the call site. A summary of this may be embedded;
        # the content itself never is, however clean it looks.
        if hasattr(text, "embeddable"):
            if not text.embeddable:
                raise FatalError(
                    "fenced content is never embedded verbatim — summarise it "
                    "first and embed the summary (MCP Gateway.md rule 3)"
                )
            text = text.text
        body = self._redact(str(text)).strip()
        if not body:
            return None

        chunk_id = hashlib.sha256(f"{namespace}\x00{kind}\x00{body}".encode()).hexdigest()[:32]
        if self._conn.execute(
            "SELECT 1 FROM vec_chunk WHERE id = ? AND model = ?", (chunk_id, self.embedder.model)
        ).fetchone():
            return None

        vec = self.embedder.encode([body])[0]
        if self._near_duplicate(vec, namespace=namespace, kind=kind):
            return None

        now = datetime.now(UTC).isoformat()
        with transaction(self._conn) as tx:
            tx.execute(
                "INSERT OR REPLACE INTO vec_chunk (id, namespace, kind, ref, text, "
                "model, dim, vec, meta, created) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    chunk_id, namespace, kind, ref, body, self.embedder.model,
                    int(self.embedder.dim), vec.tobytes(),
                    json.dumps(meta or {}, default=str), now,
                ),
            )
        return chunk_id

    def _near_duplicate(self, vec: Any, *, namespace: str, kind: str) -> bool:
        import numpy as np  # noqa: PLC0415

        rows = self._conn.execute(
            "SELECT vec FROM vec_chunk WHERE namespace = ? AND kind = ? AND model = ?",
            (namespace, kind, self.embedder.model),
        ).fetchall()
        if not rows:
            return False
        matrix = np.frombuffer(b"".join(r["vec"] for r in rows), dtype=np.float32)
        matrix = matrix.reshape(len(rows), -1)
        return bool((matrix @ vec).max() >= NEAR_DUPLICATE)

    # ------------------------------------------------------------------
    # read
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        namespaces: Sequence[str],
        kinds: Sequence[str] = (),
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[Hit]:
        """Nearest chunks within ``namespaces``, current model only.

        ``namespaces`` is required and has no default. A default would be
        either "everything" -- which is the leak the note's pre-scoring rule
        exists to prevent -- or "nothing", which fails silently.
        """
        import numpy as np  # noqa: PLC0415

        if not namespaces:
            raise FatalError(
                "a vector search must name its namespaces — filtering happens "
                "before scoring (Vector Store.md)"
            )
        clauses = [
            f"namespace IN ({','.join('?' for _ in namespaces)})",
            "model = ?",
        ]
        params: list[Any] = [*namespaces, self.embedder.model]
        if kinds:
            clauses.append(f"kind IN ({','.join('?' for _ in kinds)})")
            params += list(kinds)
        rows = self._conn.execute(
            f"SELECT * FROM vec_chunk WHERE {' AND '.join(clauses)}", params
        ).fetchall()
        if not rows:
            return []

        wanted = self.embedder.encode([query], query=True)[0]
        matrix = np.frombuffer(b"".join(r["vec"] for r in rows), dtype=np.float32)
        matrix = matrix.reshape(len(rows), -1)
        scores = matrix @ wanted
        order = np.argsort(-scores)[: max(int(limit), 0)]
        hits = []
        for i in order:
            score = float(scores[i])
            if score < min_score:
                break
            row = rows[int(i)]
            hits.append(
                Hit(
                    id=row["id"], kind=row["kind"], namespace=row["namespace"],
                    ref=row["ref"], text=row["text"], score=score,
                    created=row["created"], meta=json.loads(row["meta"]),
                )
            )
        return hits

    def stale(self) -> dict[str, int]:
        """Rows embedded by a model that is no longer the configured one.

        The count, not the rows: this exists so the nightly re-embed knows
        there is work and the operator can see a number, and a model change is
        the one event that makes every row in here stale at once.
        """
        return {
            r["model"]: r["n"]
            for r in self._conn.execute(
                "SELECT model, COUNT(*) AS n FROM vec_chunk WHERE model != ? GROUP BY model",
                (self.embedder.model,),
            )
        }

    def reembed(self, *, batch: int = 32) -> int:
        """Re-embed stale rows with the current model. Returns how many moved.

        The old rows are deleted only after the new vector is written, in one
        transaction per batch, so an interrupted re-embed leaves a store that
        is part old and part new -- both searchable by their own model, neither
        mixed with the other -- rather than a hole.
        """
        moved = 0
        while True:
            rows = self._conn.execute(
                "SELECT * FROM vec_chunk WHERE model != ? LIMIT ?",
                (self.embedder.model, int(batch)),
            ).fetchall()
            if not rows:
                return moved
            vecs = self.embedder.encode([r["text"] for r in rows])
            now = datetime.now(UTC).isoformat()
            with transaction(self._conn) as tx:
                for row, vec in zip(rows, vecs, strict=True):
                    tx.execute(
                        "INSERT OR REPLACE INTO vec_chunk (id, namespace, kind, ref, "
                        "text, model, dim, vec, meta, created) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (
                            row["id"], row["namespace"], row["kind"], row["ref"],
                            row["text"], self.embedder.model, int(self.embedder.dim),
                            vec.tobytes(), row["meta"], now,
                        ),
                    )
            moved += len(rows)

    def counts(self) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n, COUNT(DISTINCT namespace) AS ns FROM vec_chunk"
        ).fetchone()
        return {
            "chunks": row["n"],
            "namespaces": row["ns"],
            "model": self.embedder.model,
            "stale": self.stale(),
        }

    def forget(self, *, ref: str) -> int:
        """Drop every chunk owned by one record.

        Needed because this store is a projection: when the thing that owns the
        text is deleted or superseded, its chunks are not history, they are
        stale copies that would keep surfacing.
        """
        with transaction(self._conn) as tx:
            cur = tx.execute("DELETE FROM vec_chunk WHERE ref = ?", (ref,))
        return cur.rowcount or 0


def chunks_of(text: str, *, max_chars: int = 1_200) -> Iterable[str]:
    """Split long text on paragraph boundaries, per the note's chunking column.

    Section-level for notes and briefs, which in markdown means paragraphs and
    headings -- not a sliding window. A window splits a sentence across two
    chunks and both halves then retrieve badly.
    """
    para: list[str] = []
    size = 0
    for block in (b.strip() for b in text.split("\n\n")):
        if not block:
            continue
        if size + len(block) > max_chars and para:
            yield "\n\n".join(para)
            para, size = [], 0
        para.append(block)
        size += len(block)
    if para:
        yield "\n\n".join(para)
