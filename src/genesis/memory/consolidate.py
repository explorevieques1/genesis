# Spec: Genesis Markdown/40-Memory/Memory Consolidation.md
"""The nightly pass that keeps memory useful rather than merely large.

Without it memory grows monotonically and retrieval quality falls: the system
remembers more and knows less. It is the organism's sleep -- the one place
where nothing is perceived and nothing is acted on, and the day's intake is
sorted instead.

**Every pass is isolated.** A pass that raises is skipped, logged, and retried
tomorrow; its transaction rolls back, so there is no half-merged entity. The
system runs correctly on un-consolidated memory -- it just retrieves less well
-- and that is the property that makes it safe to let a pass fail. A
consolidation bug must never take down trading.

**Integrity checks alert, they never repair.** A pass that quietly fixes an
inconsistency hides the bug that caused it, and in the ledger's case hides it
behind money.

Two of the note's eight passes are deliberately not built, and saying which is
the point of this paragraph rather than leaving it to be discovered:

*Pass 3, promote observations to beliefs.* `graph.py` states the reason: it
needs a corpus of repeated observations this system has not accumulated, and a
belief promoted from three observations is worse than no belief. The
``belief`` entity type exists so this has somewhere to write when it arrives.

*Pass 5's write-back half, absorb Obsidian edits.* The read half is here --
edited notes are detected and re-embedded, so your correction reaches
retrieval the next day. Reconciling an edited thesis back into the graph
*while preserving "your edit always wins"* needs a per-note version history
that does not exist yet; building the merge before the history is how the
version that loses becomes unrecoverable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from genesis.ids import new_id

__all__ = ["PassResult", "Consolidation", "Consolidator"]

@dataclass
class PassResult:
    name: str
    ok: bool
    detail: str
    changed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"pass": self.name, "ok": self.ok, "detail": self.detail, "changed": self.changed}


@dataclass
class Consolidation:
    """What one night's run did. The shape the digest and the UI read."""

    started: str
    finished: str
    passes: list[PassResult] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(p.ok for p in self.passes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started": self.started,
            "finished": self.finished,
            "ok": self.ok,
            "passes": [p.to_dict() for p in self.passes],
            "alerts": self.alerts,
        }


class Consolidator:
    """Runs the passes. Every collaborator is optional.

    Optional because this runs in whatever process the daemon gives it and a
    night where the vector store has no model installed should still merge
    entities and check the ledger. A pass with nothing to work on reports
    ``skipped`` rather than failing, so the report distinguishes *"did not
    run"* from *"ran and found nothing"*.
    """

    def __init__(
        self,
        *,
        episodic: Any = None,
        graph: Any = None,
        ledger: Any = None,
        vectors: Any = None,
        working: Any = None,
        digest: Any = None,
        vault_path: Path | None = None,
        clock: Callable[[], datetime] | None = None,
        level_tolerance: Decimal = Decimal("0.05"),
        decay_days: int = 180,
    ) -> None:
        self.episodic = episodic
        self.graph = graph
        self.ledger = ledger
        self.vectors = vectors
        self.working = working
        self.digest = digest
        self.vault_path = vault_path
        self.clock = clock or (lambda: datetime.now(UTC))
        self.level_tolerance = level_tolerance
        self.decay_days = decay_days
        self.trace_id = ""

    # ------------------------------------------------------------------

    def run(self) -> Consolidation:
        started = self.clock()
        self.trace_id = new_id("trace")
        report = Consolidation(started=started.isoformat(), finished="")

        for name, fn in (
            ("roll-off-working", self._roll_off_working),
            ("merge-entities", self._merge_entities),
            ("weaken-and-retire", self._weaken_and_retire),
            ("absorb-vault-edits", self._absorb_vault_edits),
            ("compact-episodic", self._compact_episodic),
            ("reembed", self._reembed),
            ("integrity", self._integrity),
        ):
            try:
                report.passes.append(fn())
            except Exception as exc:  # noqa: BLE001 - a failed pass is skipped, not fatal
                report.passes.append(PassResult(name, False, f"{type(exc).__name__}: {exc}"))

        report.alerts = [
            p.detail for p in report.passes if not p.ok or p.name == "integrity" and p.changed
        ]
        report.finished = self.clock().isoformat()
        self._log("memory.consolidated", report.to_dict(), summary=self._summary(report))
        return report

    def _summary(self, report: Consolidation) -> str:
        did = ", ".join(f"{p.name} {p.changed}" for p in report.passes if p.ok and p.changed)
        failed = [p.name for p in report.passes if not p.ok]
        parts = [did or "nothing to do"]
        if failed:
            parts.append(f"skipped: {', '.join(failed)}")
        return "; ".join(parts)

    def _log(self, kind: str, payload: dict[str, Any], *, summary: str = "") -> None:
        if self.episodic is None:
            return
        try:
            self.episodic.append(
                actor="consolidator", kind=kind, trace_id=self.trace_id,
                summary=summary or None, payload=payload,
            )
        except Exception:  # noqa: BLE001 - the report is not worth failing the run
            pass

    # ------------------------------------------------------------------
    # 1. roll off working memory
    # ------------------------------------------------------------------

    def _roll_off_working(self) -> PassResult:
        if self.working is None or self.episodic is None:
            return PassResult("roll-off-working", True, "skipped: no working memory in this process")
        snapshot = self.working.snapshot()
        turns = snapshot.get("turns") or []
        if not turns:
            return PassResult("roll-off-working", True, "nothing in working memory")
        self.episodic.append(
            actor="consolidator", kind="working.rolled_off", trace_id=self.trace_id,
            summary=f"{len(turns)} turns rolled into the episodic log",
            payload={"snapshot": snapshot},
        )
        # The transient is discarded only after it is durable. `restore` with a
        # summary is how Working Memory re-opens with continuity rather than
        # empty -- the illusion is manufactured, per Biological Design.
        self.working.restore(summary=f"{len(turns)} turns from before consolidation")
        return PassResult("roll-off-working", True, f"{len(turns)} turns summarised", len(turns))

    # ------------------------------------------------------------------
    # 2. merge duplicate entities
    # ------------------------------------------------------------------

    def _merge_entities(self) -> PassResult:
        """Levels within a tick tolerance on one symbol become one level.

        Merging is recognition, not deletion: the loser is superseded, both
        keys stay queryable, and the touch counts sum. Theses and setups are
        the note's other two cases and both need a similarity judgement over
        phrasing -- that is the vector store's job and it is not wired to this
        pass yet, so this does the one case that is pure arithmetic.
        """
        if self.graph is None:
            return PassResult("merge-entities", True, "skipped: no graph")
        levels = self.graph.entities(type_="level", limit=5_000)
        by_symbol: dict[str, list[Any]] = {}
        for e in levels:
            symbol = str(e.data.get("symbol") or e.key.split(":")[0])
            by_symbol.setdefault(symbol, []).append(e)

        merged = 0
        for group in by_symbol.values():
            priced = []
            for e in group:
                try:
                    priced.append((Decimal(str(e.data["price"])), e))
                except (KeyError, ArithmeticError, TypeError, ValueError):
                    continue  # a level with no price is not a duplicate of anything
            priced.sort(key=lambda pair: pair[0])
            keep: tuple[Decimal, Any] | None = None
            for price, entity in priced:
                if keep is not None and abs(price - keep[0]) <= self.level_tolerance:
                    self._merge_level(keep[1], entity)
                    merged += 1
                    continue
                keep = (price, entity)
        return PassResult("merge-entities", True, f"{merged} duplicate level(s) merged", merged)

    def _merge_level(self, keep: Any, drop: Any) -> None:
        touches = int(keep.data.get("touches", 0)) + int(drop.data.get("touches", 0))
        aliases = list(keep.data.get("aliases") or []) + [drop.key]
        data = {**keep.data, "touches": touches, "aliases": sorted(set(aliases))}
        self.graph.upsert(
            "level", keep.key, label=keep.label, namespace=keep.namespace,
            ref=keep.ref, data=data,
        )
        self.graph.supersede(drop.id, keep.id, namespace="consolidator")

    # ------------------------------------------------------------------
    # 4. weaken and retire
    # ------------------------------------------------------------------

    def _weaken_and_retire(self) -> PassResult:
        """A belief nobody has confirmed in six months is not knowledge.

        Status lives in the entity's ``data`` because it is a property of the
        belief, not of the graph: ``active -> weakening -> retired`` for
        beliefs, and ``active -> expired`` for an idea past its timeframe.
        Nothing is deleted -- a retired belief is evidence about how the system
        reasons, which is exactly what [[Agent — Insight Miner]] reads.
        """
        if self.graph is None:
            return PassResult("weaken-and-retire", True, "skipped: no graph")
        now = self.clock()
        cutoff = (now - timedelta(days=self.decay_days)).isoformat()
        changed = 0

        for belief in self.graph.entities(type_="belief", limit=5_000):
            status = belief.data.get("status", "active")
            if status == "retired":
                continue
            confirmed = belief.data.get("last_confirmed") or belief.updated
            contradicted = len(self.graph.edges_of(belief.id, kinds=("contradicts",)))
            confirms = len(self.graph.edges_of(belief.id, kinds=("confirms",)))
            new_status = status
            if confirmed < cutoff:
                new_status = "retired" if status == "weakening" else "weakening"
            elif contradicted > confirms:
                new_status = "weakening"
            if new_status != status:
                self._set_status(belief, new_status, confirms=confirms, contradicts=contradicted)
                changed += 1

        for idea in self.graph.entities(type_="idea", limit=5_000):
            if idea.data.get("status") in ("expired", "taken", "invalidated"):
                continue
            expires = idea.data.get("expires_at") or idea.data.get("timeframe_end")
            if expires and str(expires) < now.isoformat():
                self._set_status(idea, "expired")
                changed += 1

        return PassResult("weaken-and-retire", True, f"{changed} entity status change(s)", changed)

    def _set_status(self, entity: Any, status: str, **extra: Any) -> None:
        data = {**entity.data, "status": status, "status_changed": self.clock().isoformat(), **extra}
        self.graph.upsert(
            entity.type, entity.key, label=entity.label, namespace=entity.namespace,
            ref=entity.ref, data=data,
        )

    # ------------------------------------------------------------------
    # 5. absorb your Obsidian edits (read half)
    # ------------------------------------------------------------------

    def _absorb_vault_edits(self) -> PassResult:
        """Notes you edited since the last pass, back into retrieval.

        Your edit always wins, which this half gets for free: the file is the
        source and nothing here writes to the vault.
        """
        if self.vault_path is None or self.vectors is None:
            return PassResult("absorb-vault-edits", True, "skipped: no vault or no vector store")
        root = Path(self.vault_path).expanduser()
        if not root.is_dir():
            return PassResult("absorb-vault-edits", True, f"skipped: {root} is not a directory")

        since = self._last_run_at()
        from genesis.memory.vectors import chunks_of

        touched = written = 0
        for path in sorted(root.rglob("*.md")):
            mtime = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            if since and mtime <= since:
                continue
            touched += 1
            ref = str(path.relative_to(root))
            self.vectors.forget(ref=ref)  # the old chunks are stale copies, not history
            for chunk in chunks_of(path.read_text(encoding="utf-8", errors="replace")):
                if self.vectors.write(chunk, kind="note", namespace="vault", ref=ref):
                    written += 1
        return PassResult(
            "absorb-vault-edits", True,
            f"{touched} edited note(s), {written} chunk(s) embedded", written,
        )

    def _last_run_at(self) -> datetime | None:
        if self.episodic is None:
            return None
        rows = self.episodic.by_kind("memory.consolidated", limit=1)
        if not rows:
            return None
        try:
            return datetime.fromisoformat(rows[0].ts)
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # 6. compact the episodic log
    # ------------------------------------------------------------------

    def _compact_episodic(self) -> PassResult:
        """Collapse repetitive process rows into one summary row.

        **The classification is [[Agent — Digest]]'s, not a second copy here.**
        It already implements the note's never-collapsible list properly --
        decisions by kind, plus anything a journal entry or a lesson references
        -- and two implementations of "may this row be collapsed?" is one
        implementation and one silent data loss.

        What this pass adds is durability: the digest reports what it *would*
        collapse, and this writes that finding into the log as the summary row
        that stands in for the detail.

        **Nothing is deleted.** The log's `BEFORE DELETE` trigger makes that
        structural rather than a promise, so compaction here means writing a
        summary and leaving the rows where they are -- Memory Fabric's
        "summarised, never deleted", in code.
        """
        if self.digest is None or self.episodic is None:
            return PassResult("compact-episodic", True, "skipped: no digest or no episodic log")
        result = self.digest.compress(days=1)
        if result.get("error"):
            return PassResult("compact-episodic", False, str(result["error"]))
        collapsible = int(result.get("collapsible", 0))
        if not collapsible:
            return PassResult(
                "compact-episodic", True,
                f"nothing collapsible in {result.get('examined', 0)} row(s)",
            )
        self.episodic.append(
            actor="consolidator", kind="episodic.compacted", trace_id=self.trace_id,
            summary=(
                f"{collapsible} routine rows stand behind this summary; "
                f"{result.get('preserved', 0)} decisions preserved"
            ),
            payload=result,
        )
        return PassResult(
            "compact-episodic", True,
            f"{collapsible} row(s) summarised, {result.get('preserved', 0)} preserved",
            collapsible,
        )

    # ------------------------------------------------------------------
    # 7. re-embed what changed
    # ------------------------------------------------------------------

    def _reembed(self) -> PassResult:
        if self.vectors is None:
            return PassResult("reembed", True, "skipped: no vector store")
        stale = self.vectors.stale()
        if not stale:
            return PassResult("reembed", True, "every vector is on the current model")
        moved = self.vectors.reembed()
        return PassResult("reembed", True, f"{moved} vector(s) re-embedded from {stale}", moved)

    # ------------------------------------------------------------------
    # 8. integrity checks -- alert, never repair
    # ------------------------------------------------------------------

    def _integrity(self) -> PassResult:
        problems: list[str] = []
        checked = 0

        if self.ledger is not None:
            checked += 1
            verdict = self.ledger.verify()
            if not verdict["consistent"]:
                problems.append(
                    f"ledger: {len(verdict['orphan_fills'])} orphan fill(s), "
                    f"{len(verdict['unbalanced_events'])} unbalanced event(s)"
                )
            # Rebuilt positions against stored. This is the ledger half of
            # proprioception; the broker half is the accountant's 16:15 pass.
            rebuilt = self.ledger.rebuild()
            stored = self.ledger.stored_positions()
            for key, pos in rebuilt.items():
                held = stored.get(key)
                if held is None or held.qty != pos.qty:
                    problems.append(
                        f"position drift {key[1]}: fills say {pos.qty}, "
                        f"stored says {held.qty if held else 'nothing'}"
                    )
            for row in self.ledger.connection.execute(
                "SELECT COUNT(*) AS n FROM fills WHERE approval_id IS NULL OR approval_id = ''"
            ):
                if row["n"]:
                    problems.append(f"{row['n']} fill(s) with no approval_id — Safety Invariants §1")

        if self.graph is not None:
            checked += 1
            for row in self.graph.conn.execute(
                "SELECT COUNT(*) AS n FROM kg_edge e WHERE "
                "NOT EXISTS (SELECT 1 FROM kg_entity WHERE id = e.src) OR "
                "NOT EXISTS (SELECT 1 FROM kg_entity WHERE id = e.dst)"
            ):
                if row["n"]:
                    problems.append(f"{row['n']} dangling graph edge(s)")

        if not checked:
            return PassResult("integrity", True, "skipped: nothing to check")
        if problems:
            self._log("integrity.failed", {"problems": problems},
                      summary="consolidation integrity check failed")
            return PassResult("integrity", False, "; ".join(problems), len(problems))
        return PassResult("integrity", True, f"{checked} store(s) consistent")
