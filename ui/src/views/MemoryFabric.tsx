// Spec: Genesis Markdown/40-Memory/Memory Fabric.md
//
// The five layers, each with a distinct job, and the live read/write traffic
// across them.
//
// "Why five and not one" is the note's own argument and it is the organising idea
// of this view: each layer answers a *different question*, and conflating them
// makes all of them worse. So the question is what labels each layer here, not
// the store technology.
//
// Two invariants the view makes visible rather than merely stating:
//   - The ledger must never be approximate, and the vector store must never be
//     authoritative. Both are marked.
//   - Single-writer namespaces. The writer column names exactly one agent per
//     namespace, which is what prevents two agents disagreeing about a fact and
//     both being "right".

import { memo, useMemo } from 'react'
import { useGenesis } from '@/store/useGenesis'
import { MEMORY_LAYERS, AGENTS_BY_ID } from '@/data/roster'
import { ago } from '@/lib/format'
import type { MemoryLayerId } from '@/types/events'

const AUTHORITY: Record<MemoryLayerId, { note: string; tone: 'strict' | 'soft' | null }> = {
  working: { note: 'Rolls off. Never the record of anything.', tone: 'soft' },
  episodic: { note: 'Append-only. Every state transition is written here in the same transaction as the transition itself.', tone: 'strict' },
  graph: { note: 'What we believe. Consolidated nightly; your edit always wins.', tone: null },
  vector: { note: 'Never authoritative. Similarity is a pointer, not a fact.', tone: 'soft' },
  ledger: { note: 'Never approximate. Double-entry, reconciled daily; a mismatch is fatal with no small exception.', tone: 'strict' },
}

export const MemoryFabric = memo(function MemoryFabric({ now }: { now: number }) {
  const memory = useGenesis((s) => s.memory)
  const edges = useGenesis((s) => s.edges)
  const select = useGenesis((s) => s.select)

  const memEdges = useMemo(
    () => Object.values(edges).filter((e) => e.kind === 'memory').sort((a, b) => b.lastAt - a.lastAt),
    [edges],
  )

  const byLayer = useMemo(() => {
    const m = new Map<string, typeof memEdges>()
    for (const e of memEdges) {
      const k = e.layer ?? 'unknown'
      m.set(k, [...(m.get(k) ?? []), e])
    }
    return m
  }, [memEdges])

  return (
    <div className="scroll-y h-full min-h-0" style={{ padding: 12 }}>
      <div className="label" style={{ marginBottom: 8 }}>memory fabric — five layers, five questions</div>

      <div className="flex flex-col gap-2">
        {MEMORY_LAYERS.map((layer) => {
          const rt = memory[layer.id]
          const auth = AUTHORITY[layer.id]
          const hot = rt.lastReadAt !== null && now - rt.lastReadAt < 5000
          const interactions = byLayer.get(layer.id) ?? []
          return (
            <div
              key={layer.id}
              className="panel"
              style={{
                padding: '8px 10px',
                borderColor: hot ? 'var(--edge-memory)' : 'var(--hairline)',
                borderLeft: `2px solid ${auth.tone === 'strict' ? 'var(--spinal)' : auth.tone === 'soft' ? 'var(--state-blocked)' : 'var(--edge-memory)'}`,
              }}
            >
              <div className="flex items-baseline gap-2">
                <span style={{ fontSize: 'var(--fs-base)', fontWeight: 600 }}>{layer.name}</span>
                <span className="num" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-ghost)' }}>
                  {layer.store}
                </span>
                <span className="num ml-auto flex gap-3" style={{ fontSize: 'var(--fs-micro)' }}>
                  <span style={{ color: rt.reads ? 'var(--phase-perceiving)' : 'var(--ink-ghost)' }}>
                    ◇ {rt.reads} read{rt.reads === 1 ? '' : 's'}
                    {rt.lastReadAt && <span style={{ color: 'var(--ink-ghost)' }}> · {ago(now - rt.lastReadAt)}</span>}
                  </span>
                  <span style={{ color: rt.writes ? 'var(--phase-acting)' : 'var(--ink-ghost)' }}>
                    ▲ {rt.writes} write{rt.writes === 1 ? '' : 's'}
                  </span>
                </span>
              </div>

              <div style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink-dim)', marginTop: 3 }}>
                {layer.question}
              </div>
              <div style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)', marginTop: 2 }}>
                {auth.note} <span style={{ color: 'var(--ink-ghost)' }}>· {layer.lifetime}</span>
              </div>

              {/* Read traffic is a fading bar rather than a running total, because
                  a memory edge means "one agent read what another wrote" — a
                  moment, not an accumulation. */}
              <div style={{ height: 2, background: 'var(--bg-inset)', marginTop: 6 }}>
                <div
                  style={{
                    height: '100%',
                    width: `${Math.min(100, rt.reads * 4)}%`,
                    background: 'var(--edge-memory)',
                    opacity: hot ? 1 : 0.4,
                  }}
                />
              </div>

              {interactions.length > 0 && (
                <div style={{ marginTop: 6 }}>
                  <div className="label">observed reads — writer → reader</div>
                  {interactions.slice(0, 6).map((e) => (
                    <button
                      key={e.id}
                      onClick={() => select({ agentId: e.target })}
                      className="w-full text-left num truncate"
                      style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-dim)' }}
                    >
                      <span style={{ color: 'var(--phase-acting)' }}>
                        {AGENTS_BY_ID.get(e.source)?.name ?? e.source}
                      </span>
                      <span style={{ color: 'var(--ink-ghost)' }}> → </span>
                      <span style={{ color: 'var(--phase-perceiving)' }}>
                        {AGENTS_BY_ID.get(e.target)?.name ?? e.target}
                      </span>
                      <span style={{ color: 'var(--ink-ghost)' }}> · {e.namespace} ×{e.count} · {ago(now - e.lastAt)}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div
        className="panel"
        style={{ marginTop: 10, padding: '8px 10px', fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)' }}
      >
        <div className="label" style={{ marginBottom: 3 }}>why a memory edge matters</div>
        Agents never call each other. A memory edge is the *other* way information moves: one agent
        wrote, and hours later another read. Coordination through the bus is intended; coordination
        through memory side-effects is usually the bug you are hunting — which is why this edge class
        is drawn separately rather than merged into the causal graph.
      </div>
    </div>
  )
})
