// Spec: Genesis Markdown/00-Meta/Conventions.md · 00-Meta/Vault Map.md
//
// `DNA` — the genome: the vault and the prompts every organ was built from.
//
// Biological Design puts DNA on the organ map as "system prompts **and** this
// vault". It is the one row that is not a component, so this panel does not
// show a thing Genesis has — it shows the instruction set Genesis was built
// from, and whether the record of that transcription still tells the truth.
//
// Three readings, in the order that matters:
//   drift       the body map lying about the code. First, because a spec that
//               lies is worse than no spec (CLAUDE.md hard rule 6).
//   expression  every note by status — what is built, building, still spec.
//   prompts     the other half of the genome, which had no surface at all.
//
// It shows, and it cannot act. There is no button here that edits a note or a
// prompt, and that absence is the design rather than an unfinished feature:
// an organism that can rewrite its own genome can rewrite Safety Invariants.
// The genome is edited in a file, by a person, and committed — git is the
// germ line.

import { useState } from 'react'
import { api, type DnaNote } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Loading } from '@/components/States'

const STATUS_GLYPH: Record<DnaNote['status'], string> = {
  built: '●', building: '◐', spec: '○', none: '·',
}
const STATUS_COLOR: Record<DnaNote['status'], string> = {
  built: 'var(--verdict-pass)',
  building: 'var(--state-blocked)',
  spec: 'var(--ink-ghost)',
  none: 'var(--ink-faint)',
}

type View = 'expression' | 'prompts'

export function DnaPanel() {
  const dna = useRead(() => api.dna(), [])
  const [view, setView] = useState<View>('expression')
  const [open, setOpen] = useState<string | null>(null)

  // `useRead` strips `available` off a ready body — it is the envelope's
  // discriminant, not payload — so testing `body.available` here was testing
  // `undefined` and would have reported a vault that is plainly on disk as
  // missing. The status is the discriminant.
  if (dna.state.status === 'loading') return <Loading rows={6} />
  if (dna.state.status !== 'ready') return <Absent reason={dna.state.reason} onRetry={dna.reload} />
  const body = dna.state.data

  const { counts } = body

  return (
    <div className="scroll-y h-full" style={{ padding: 'var(--s-5) var(--s-6)', background: 'var(--bg-void)' }}>
      <div style={{ maxWidth: 860 }}>
        <p style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink-dim)', marginBottom: 'var(--s-4)' }}>
          The instruction set every organ was built from — this vault and the prompts. Read only:
          a gene is edited in a file and committed, never from here.
        </p>

        <div className="flex items-baseline gap-4" style={{ marginBottom: 'var(--s-4)' }}>
          <Count glyph="●" n={counts.built} label="built" color={STATUS_COLOR.built} />
          <Count glyph="◐" n={counts.building} label="building" color={STATUS_COLOR.building} />
          <Count glyph="○" n={counts.spec} label="spec" color={STATUS_COLOR.spec} />
          <Count glyph="·" n={counts.none} label="no status" color={STATUS_COLOR.none} />
        </div>

        {/* Transcription first: a note that lies about its code makes the
            system reason confidently about itself and be wrong. */}
        <Heading>Transcription</Heading>
        {body.honest ? (
          <div className="label" style={{ color: 'var(--verdict-pass)', marginBottom: 'var(--s-4)' }}>
            ✓ the body map is honest — every spec pointer is answered
          </div>
        ) : (
          <div style={{ marginBottom: 'var(--s-4)' }}>
            {body.drift.map((f, i) => (
              <div key={`${f.kind}-${f.note}-${i}`} style={{ marginBottom: 'var(--s-2)' }}>
                <div className="flex items-baseline gap-2">
                  <span>{f.glyph}</span>
                  <span className="num" style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink)' }}>{f.note}</span>
                  <span className="label" style={{ color: 'var(--state-blocked)' }}>{f.kind}</span>
                </div>
                <div className="label" style={{ paddingLeft: 'var(--s-5)', color: 'var(--ink-faint)', textTransform: 'none', letterSpacing: 0 }}>
                  {f.detail}
                  {f.files.map((p) => <div key={p}>+ {p}</div>)}
                </div>
              </div>
            ))}
            <div className="label" style={{ color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0 }}>
              Repair with <span className="num">genesis dna check --fix</span> — it only ever writes what the code already proves.
            </div>
          </div>
        )}

        {Object.keys(body.collisions).length > 0 && (
          <div style={{ marginBottom: 'var(--s-4)' }}>
            {Object.entries(body.collisions).map(([name, paths]) => (
              <div key={name} className="label" style={{ color: 'var(--state-blocked)', textTransform: 'none', letterSpacing: 0 }}>
                ⚠ <span className="num">[[{name}]]</span> resolves two ways: {paths.join(' · ')}
              </div>
            ))}
          </div>
        )}

        <div className="flex gap-3" style={{ marginBottom: 'var(--s-3)' }}>
          <Tab active={view === 'expression'} onClick={() => setView('expression')}>
            Expression · {body.sections.reduce((n, s) => n + s.notes.length, 0)} notes
          </Tab>
          <Tab active={view === 'prompts'} onClick={() => setView('prompts')}>
            Prompts · {body.prompts.length}
          </Tab>
        </div>

        {view === 'expression' && body.sections.map((section) => (
          <div key={section.section} style={{ marginBottom: 'var(--s-4)' }}>
            <div className="label" style={{ marginBottom: 'var(--s-1)' }}>{section.section}</div>
            {section.notes.map((note) => (
              <div key={note.rel}>
                <button
                  type="button"
                  onClick={() => setOpen(open === note.rel ? null : note.rel)}
                  className="flex items-baseline gap-2"
                  style={{ background: 'none', border: 0, padding: 0, cursor: 'pointer', textAlign: 'left', width: '100%' }}
                >
                  <span style={{ color: STATUS_COLOR[note.status] }}>{STATUS_GLYPH[note.status]}</span>
                  <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink)' }}>{note.name}</span>
                  <span className="label" style={{ color: 'var(--ink-ghost)' }}>
                    {note.implemented_by.length > 0 ? `${note.implemented_by.length} file${note.implemented_by.length > 1 ? 's' : ''}` : ''}
                  </span>
                </button>
                {open === note.rel && (
                  <div className="label" style={{ paddingLeft: 'var(--s-5)', paddingBottom: 'var(--s-2)', color: 'var(--ink-faint)', textTransform: 'none', letterSpacing: 0 }}>
                    <div className="num">{note.rel}</div>
                    {note.implemented_by.map((p) => <div key={p}>→ {p}</div>)}
                    {note.pointing_at_it.map((p) => <div key={`b-${p}`}>← {p}</div>)}
                    {note.implemented_by.length === 0 && note.pointing_at_it.length === 0 && (
                      <div>no code — a principle, an index, or not built yet</div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        ))}

        {view === 'prompts' && (
          <div>
            <p className="label" style={{ color: 'var(--ink-faint)', textTransform: 'none', letterSpacing: 0, marginBottom: 'var(--s-2)' }}>
              Every module-level prompt under the agents, the orchestrator and the voice loop — read with
              a syntax walk, never by importing. ~{body.prompts.reduce((n, p) => n + p.est_tokens, 0)} tokens
              in total, estimated at four characters to a token.
            </p>
            {body.prompts.map((p) => (
              <div key={`${p.file}:${p.line}`} style={{ marginBottom: 'var(--s-2)' }}>
                <div className="flex items-baseline gap-2">
                  <span className="num" style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink)' }}>{p.est_tokens} tok</span>
                  <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink)' }}>{p.name}</span>
                  <span className="label" style={{ color: 'var(--ink-ghost)' }}>{p.file}:{p.line}</span>
                </div>
                <div className="label" style={{ paddingLeft: 'var(--s-5)', color: 'var(--ink-faint)', textTransform: 'none', letterSpacing: 0 }}>
                  {p.opening}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function Count({ glyph, n, label, color }: { glyph: string; n: number; label: string; color: string }) {
  return (
    <div className="flex items-baseline gap-1">
      <span style={{ color }}>{glyph}</span>
      <span className="num" style={{ fontSize: 'var(--fs-md)', color: 'var(--ink)' }}>{n}</span>
      <span className="label" style={{ color: 'var(--ink-faint)' }}>{label}</span>
    </div>
  )
}

function Tab({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="label"
      style={{
        background: 'none', border: 0, padding: 0, cursor: 'pointer',
        color: active ? 'var(--ink)' : 'var(--ink-ghost)',
        borderBottom: active ? '1px solid var(--ink)' : '1px solid transparent',
      }}
    >
      {children}
    </button>
  )
}

function Heading({ children }: { children: React.ReactNode }) {
  return (
    <div className="label" style={{ color: 'var(--ink-dim)', marginBottom: 'var(--s-2)' }}>{children}</div>
  )
}
