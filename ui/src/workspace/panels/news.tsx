// Spec: Genesis Markdown/60-UI/News.md
//
// NW — the news module. Headlines you scroll and open, an article you read in
// place, and Genesis reading it with you.
//
// Three things on screen, like a TradingView news pane plus an analyst:
//
//   1. **Headlines** — what the collector has stored, newest first, filterable.
//      It does not poll (UI Stack §9). It reloads when the collector or the
//      analyst finishes a task on the event stream, and when you press refresh.
//   2. **Reader** — the article text, read once by the daemon and cached, with
//      the original one click away. **AI summary** hands the article to the
//      news analyst: summary, insights, trade ideas with an invalidation.
//   3. **Briefs** — multi-story summaries, written on request or by a workflow
//      (the Sunday-evening weekend brief), each listing the stories it read.
//
// Everything here is tier 4: third-party text and a model's reading of it.
// Trade ideas are directions in words — no size, no stop, no target — because
// a language model never computes those (Safety Invariants #3).

import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  api, type NewsAnalysis, type NewsArticle, type NewsBrief, type TradeIdea,
} from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Empty, Loading } from '@/components/States'
import { Caveats, Chip } from '@/components/Primitives'
import { useGenesis } from '@/store/useGenesis'

const NEWS_AGENTS = new Set(['news-collector', 'news-catalyst'])
const WINDOWS = [
  { label: '24h', hours: 24 },
  { label: '3d', hours: 72 },
  { label: '7d', hours: 168 },
  { label: 'all', hours: 0 },
]
const BRIEF_WINDOWS = [
  { label: 'last 24h', hours: 24 },
  { label: 'weekend (64h)', hours: 64 },
  { label: 'last week', hours: 168 },
]

function when(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime()
  if (ms < 3.6e6) return `${Math.max(1, Math.round(ms / 6e4))}m`
  if (ms < 48 * 3.6e6) return `${Math.round(ms / 3.6e6)}h`
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function fullTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

const DIRECTION_TONE: Record<string, 'good' | 'bad' | 'warn' | 'neutral'> = {
  bullish: 'good', bearish: 'bad', mixed: 'warn', neutral: 'neutral',
}

/** Reload when a news agent finishes something — pushed, not polled. */
function useNewsEvents(onDone: () => void) {
  const latest = useRef(onDone)
  latest.current = onDone
  useEffect(() => useGenesis.subscribe((s, prev) => {
    const e = s.events[0] as { event: string; data: { agent?: string } } | undefined
    if (!e || e === prev.events[0]) return
    if (e.event === 'task.completed' && NEWS_AGENTS.has(String(e.data?.agent))) latest.current()
  }), [])
}

/** One pane at a time below this width — a list and a reader side by side need room. */
function useNarrow(ref: React.RefObject<HTMLDivElement | null>, below = 620): boolean {
  const [narrow, setNarrow] = useState(false)
  useEffect(() => {
    if (!ref.current) return
    const observer = new ResizeObserver(([entry]) => setNarrow(entry.contentRect.width < below))
    observer.observe(ref.current)
    return () => observer.disconnect()
  }, [ref, below])
  return narrow
}

export function NewsPanel({ params }: { params?: { brief?: string } }) {
  // Opened on a specific brief — the feed clicking through to the thing an
  // automation wrote, rather than dropping the reader at the top of the list.
  const [tab, setTab] = useState<'headlines' | 'briefs'>(params?.brief ? 'briefs' : 'headlines')
  const [openArticle, setOpenArticle] = useState<string | null>(null)
  const [openBrief, setOpenBrief] = useState<string | null>(params?.brief ?? null)
  const root = useRef<HTMLDivElement>(null)
  const narrow = useNarrow(root)

  const selected = tab === 'headlines' ? openArticle : openBrief
  const showList = !narrow || !selected
  const showReader = !narrow || !!selected

  return (
    <div ref={root} className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-2 hairline-b" style={{ padding: '4px 8px', flexShrink: 0 }}>
        {(['headlines', 'briefs'] as const).map((t) => (
          <button key={t} className="btn-ghost" data-active={t === tab} onClick={() => setTab(t)}>{t}</button>
        ))}
        <span style={{ flex: 1 }} />
        {narrow && selected && (
          <button className="btn-ghost" onClick={() => (tab === 'headlines' ? setOpenArticle(null) : setOpenBrief(null))}>
            ← list
          </button>
        )}
        <Chip tone="warn" title="Third-party text and a model's reading of it — never a number Genesis knows">tier 4</Chip>
      </div>
      <div className="flex min-h-0" style={{ flex: 1 }}>
        {tab === 'headlines' ? (
          <>
            {showList && (
              <Pane width={narrow ? '100%' : '42%'} border={!narrow}>
                <Headlines selected={openArticle} onOpen={setOpenArticle} />
              </Pane>
            )}
            {showReader && (
              <Pane>
                {openArticle
                  ? <Reader key={openArticle} id={openArticle} />
                  : <Empty hint="Pick a headline to read it here, then ask Genesis for a summary.">no story open</Empty>}
              </Pane>
            )}
          </>
        ) : (
          <>
            {showList && (
              <Pane width={narrow ? '100%' : '36%'} border={!narrow}>
                <Briefs selected={openBrief} onOpen={setOpenBrief} />
              </Pane>
            )}
            {showReader && (
              <Pane>
                {openBrief
                  ? <BriefReader key={openBrief} id={openBrief} onArticle={(id) => { setOpenArticle(id); setTab('headlines') }} />
                  : <Empty hint="Write a brief, or automate one — Workflow builder → News → “Write news brief”.">no brief open</Empty>}
              </Pane>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function Pane({ children, width, border }: { children: ReactNode; width?: string; border?: boolean }) {
  return (
    <div
      className="flex flex-col min-h-0 scroll-y"
      style={{ width, flex: width ? 'none' : 1, borderRight: border ? '1px solid var(--hairline)' : undefined }}
    >
      {children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// headlines

function Headlines({ selected, onOpen }: { selected: string | null; onOpen: (id: string) => void }) {
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const [symbols, setSymbols] = useState('')
  const [hours, setHours] = useState(72)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const { state, reload } = useRead(
    () => api.news({ hours: hours || undefined, q: query || undefined, symbols: symbols || undefined, limit: 300 }),
    [hours, query, symbols],
  )
  useNewsEvents(reload)

  const refresh = async () => {
    setBusy(true)
    setNote(null)
    try {
      const run = await api.newsCollect()
      setNote(`${run.new} new from ${run.sources} sources${run.errors.length ? ` · ${run.errors.length} failed` : ''}`)
      reload()
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const apply = () => {
    // A token that looks like a ticker filters by symbol; anything else searches text.
    const text = draft.trim()
    if (/^[A-Z^][A-Z0-9.=^-]{0,9}(,\s*[A-Z^][A-Z0-9.=^-]{0,9})*$/.test(text)) {
      setSymbols(text.replace(/\s/g, ''))
      setQuery('')
    } else {
      setSymbols('')
      setQuery(text)
    }
  }

  let body: ReactNode
  if (state.status === 'loading') body = <Loading rows={8} label="headlines" />
  else if (state.status !== 'ready') body = <Absent reason={state.reason} onRetry={reload} />
  else if (!state.data.articles.length) {
    body = (
      <Empty hint={query || symbols
        ? 'Nothing stored matches. Refresh collects fresh headlines for the market and your watchlists.'
        : 'The collector runs every 15 minutes while the daemon is up. Press refresh to collect now.'}>
        no stories
      </Empty>
    )
  } else {
    body = state.data.articles.map((a) => (
      <HeadlineRow key={a.id} article={a} selected={a.id === selected} onOpen={() => onOpen(a.id)} />
    ))
  }

  return (
    <>
      <div className="flex flex-col gap-1 hairline-b" style={{ padding: 6, flexShrink: 0 }}>
        <div className="flex items-center gap-1">
          <input
            className="field"
            placeholder="search, or NVDA, TSLA"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') apply() }}
            onBlur={() => { if (!draft.trim()) { setQuery(''); setSymbols('') } }}
            style={{ flex: 1, minWidth: 0 }}
          />
          <button className="btn" onClick={refresh} disabled={busy} title="Collect fresh headlines now">
            {busy ? 'collecting…' : 'refresh'}
          </button>
        </div>
        <div className="flex items-center gap-1">
          {WINDOWS.map((w) => (
            <button key={w.label} className="btn-ghost" data-active={w.hours === hours} onClick={() => setHours(w.hours)}>
              {w.label}
            </button>
          ))}
          <span style={{ flex: 1 }} />
          {note && <span className="label" style={{ textTransform: 'none', letterSpacing: 0 }}>{note}</span>}
        </div>
      </div>
      <div className="flex flex-col">{body}</div>
    </>
  )
}

function HeadlineRow({ article, selected, onOpen }: { article: NewsArticle; selected: boolean; onOpen: () => void }) {
  return (
    <button
      onClick={onOpen}
      className="hairline-b"
      style={{
        all: 'unset', cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: 3,
        padding: '7px 10px', borderBottom: '1px solid var(--hairline)',
        background: selected ? 'var(--bg-inset)' : undefined,
        borderLeft: `2px solid ${selected ? 'var(--core)' : 'transparent'}`,
      }}
    >
      <span style={{ color: 'var(--ink)', fontSize: 'var(--fs-sm)', lineHeight: 1.35 }}>{article.title}</span>
      <span className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}>
        <span className="label" style={{ textTransform: 'none', letterSpacing: 0 }}>
          {when(article.published)} · {article.publisher}
        </span>
        {article.symbols.slice(0, 4).map((s) => <Chip key={s}>{s}</Chip>)}
        {article.analysis_at && <Chip tone="core" title="Genesis has summarised this">AI</Chip>}
      </span>
    </button>
  )
}

// ---------------------------------------------------------------------------
// the reader

function Reader({ id }: { id: string }) {
  const { state, reload } = useRead(() => api.newsArticle(id), [id])
  const [analysis, setAnalysis] = useState<NewsAnalysis | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (state.status === 'loading') return <Loading rows={10} label="reading the article" />
  if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />
  const a = state.data.article
  const shown = analysis ?? a.analysis ?? null

  const summarise = async () => {
    setBusy(true)
    setError(null)
    try {
      setAnalysis((await api.newsSummarise(id)).analysis)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const paragraphs = (a.body || '').split(/\n{2,}/).filter(Boolean)

  return (
    <article className="flex flex-col gap-3" style={{ padding: '10px 14px 24px', maxWidth: 760 }}>
      <header className="flex flex-col gap-2">
        <h2 style={{ margin: 0, fontSize: 'var(--fs-lg, 17px)', lineHeight: 1.3, color: 'var(--ink)' }}>{a.title}</h2>
        <div className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}>
          <span className="label" style={{ textTransform: 'none', letterSpacing: 0 }}>
            {a.publisher} · {fullTime(a.published)}
          </span>
          {a.symbols.map((s) => <Chip key={s}>{s}</Chip>)}
        </div>
        <div className="flex items-center gap-2">
          <button className="btn" data-active={!!shown} onClick={summarise} disabled={busy}>
            {busy ? 'Genesis is reading…' : shown ? 'summarise again' : 'AI summary'}
          </button>
          <a className="btn-ghost" href={a.url} target="_blank" rel="noreferrer noopener">open original ↗</a>
        </div>
        {error && <Caveats items={[error]} />}
      </header>

      {shown && <AnalysisCard analysis={shown} />}

      {paragraphs.length ? (
        <div className="flex flex-col gap-2" style={{ color: 'var(--ink-dim)', lineHeight: 1.6, fontSize: 'var(--fs-sm)' }}>
          {paragraphs.map((p, i) => <p key={i} style={{ margin: 0 }}>{p}</p>)}
        </div>
      ) : (
        <>
          <Caveats tone="info" items={['This page would not give up its text (a paywall or a block). The feed’s summary is below — open the original to read it all.']} />
          {a.summary && <p style={{ margin: 0, color: 'var(--ink-dim)', lineHeight: 1.6 }}>{a.summary}</p>}
        </>
      )}
    </article>
  )
}

function AnalysisCard({ analysis }: { analysis: NewsAnalysis }) {
  return (
    <section
      className="flex flex-col gap-2"
      style={{ padding: 10, background: 'var(--bg-inset)', border: '1px solid var(--hairline)', borderLeft: '2px solid var(--core)', borderRadius: 'var(--r-sm)' }}
    >
      <div className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}>
        <span className="label" style={{ color: 'var(--core)' }}>genesis read</span>
        <Chip tone={DIRECTION_TONE[analysis.direction] ?? 'neutral'}>{analysis.direction}</Chip>
        <Chip>{analysis.magnitude} impact</Chip>
        {analysis.horizon && <Chip>{analysis.horizon}</Chip>}
        <Chip>{analysis.kind}</Chip>
        {analysis.symbols.map((s) => <Chip key={s}>{s}</Chip>)}
      </div>
      {analysis.injection && (
        <Caveats items={['This page tried to give the model instructions. They were not followed — treat the article with suspicion.']} />
      )}
      <p style={{ margin: 0, color: 'var(--ink)', lineHeight: 1.55 }}>{analysis.summary}</p>
      <Bullets title="key points" items={analysis.key_points} />
      <Bullets title="insights" items={analysis.insights} />
      <Ideas ideas={analysis.trade_ideas} />
      <Bullets title="risks" items={analysis.risks} />
      <span className="label" style={{ textTransform: 'none', letterSpacing: 0 }}>
        {analysis.model} · read {analysis.read} · confidence {Math.round(analysis.confidence * 100)}%
        {analysis.degraded ? ' · degraded' : ''}
      </span>
    </section>
  )
}

function Bullets({ title, items }: { title: string; items: string[] }) {
  if (!items?.length) return null
  return (
    <div className="flex flex-col gap-1">
      <span className="label">{title}</span>
      <ul style={{ margin: 0, paddingLeft: 16, color: 'var(--ink-dim)', lineHeight: 1.5, fontSize: 'var(--fs-sm)' }}>
        {items.map((item, i) => <li key={i}>{item}</li>)}
      </ul>
    </div>
  )
}

function Ideas({ ideas }: { ideas: TradeIdea[] }) {
  if (!ideas?.length) return null
  return (
    <div className="flex flex-col gap-1">
      <span className="label" title="Directions in words. No size, stop or target — a model never computes those.">trade ideas</span>
      {ideas.map((idea, i) => (
        <div key={i} className="flex flex-col gap-1" style={{ padding: '6px 8px', border: '1px solid var(--hairline)', borderRadius: 'var(--r-sm)' }}>
          <div className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}>
            <Chip tone={idea.bias === 'long' ? 'good' : idea.bias === 'short' ? 'bad' : 'neutral'}>{idea.bias}</Chip>
            {idea.symbols.map((s) => <Chip key={s}>{s}</Chip>)}
            <span style={{ color: 'var(--ink)', fontSize: 'var(--fs-sm)' }}>{idea.idea}</span>
          </div>
          {idea.rationale && <span style={{ color: 'var(--ink-dim)', fontSize: 'var(--fs-tiny)' }}>{idea.rationale}</span>}
          {idea.invalidation && (
            <span style={{ color: 'var(--ink-faint)', fontSize: 'var(--fs-tiny)' }}>wrong if: {idea.invalidation}</span>
          )}
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// briefs

function Briefs({ selected, onOpen }: { selected: string | null; onOpen: (id: string) => void }) {
  const { state, reload } = useRead(() => api.newsBriefs(), [])
  const [hours, setHours] = useState(24)
  const [focus, setFocus] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useNewsEvents(reload)

  const write = async () => {
    setBusy(true)
    setError(null)
    try {
      const { brief } = await api.newsBriefNow({ hours, focus: focus.trim() || undefined, refresh: true })
      reload()
      onOpen(brief.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="flex flex-col gap-1 hairline-b" style={{ padding: 6, flexShrink: 0 }}>
        <div className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}>
          {BRIEF_WINDOWS.map((w) => (
            <button key={w.hours} className="btn-ghost" data-active={w.hours === hours} onClick={() => setHours(w.hours)}>
              {w.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1">
          <input
            className="field"
            placeholder="focus (optional) — e.g. semis, the Fed"
            value={focus}
            onChange={(e) => setFocus(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !busy) write() }}
            style={{ flex: 1, minWidth: 0 }}
          />
          <button className="btn" onClick={write} disabled={busy}>{busy ? 'writing…' : 'write brief'}</button>
        </div>
        {busy && <span className="label" style={{ textTransform: 'none', letterSpacing: 0 }}>collecting, picking the stories that matter, reading them — about a minute</span>}
        {error && <Caveats items={[error]} />}
      </div>
      {state.status === 'loading' ? <Loading rows={4} label="briefs" />
        : state.status !== 'ready' ? <Absent reason={state.reason} onRetry={reload} />
          : !state.data.briefs.length ? <Empty hint="Write one above, or schedule one in the Workflow builder.">no briefs yet</Empty>
            : state.data.briefs.map((b) => (
              <button
                key={b.id}
                onClick={() => onOpen(b.id)}
                style={{
                  all: 'unset', cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: 2,
                  padding: '7px 10px', borderBottom: '1px solid var(--hairline)',
                  background: b.id === selected ? 'var(--bg-inset)' : undefined,
                  borderLeft: `2px solid ${b.id === selected ? 'var(--core)' : 'transparent'}`,
                }}
              >
                <span style={{ color: 'var(--ink)', fontSize: 'var(--fs-sm)' }}>{b.title}</span>
                <span className="label" style={{ textTransform: 'none', letterSpacing: 0 }}>
                  {fullTime(b.created)} · last {b.hours}h · {b.requested_by}
                </span>
              </button>
            ))}
    </>
  )
}

function BriefReader({ id, onArticle }: { id: string; onArticle: (articleId: string) => void }) {
  const { state, reload } = useRead(() => api.newsBrief(id), [id])
  if (state.status === 'loading') return <Loading rows={10} label="brief" />
  if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />
  const brief: NewsBrief = state.data.brief
  const b = brief.body

  return (
    <article className="flex flex-col gap-3" style={{ padding: '10px 14px 24px', maxWidth: 760 }}>
      <header className="flex flex-col gap-1">
        <h2 style={{ margin: 0, fontSize: 'var(--fs-lg, 17px)', color: 'var(--ink)' }}>{brief.title}</h2>
        <span className="label" style={{ textTransform: 'none', letterSpacing: 0 }}>
          {fullTime(brief.created)} · {b.articles.length} of {b.considered} stories read · {b.model}
          {b.focus ? ` · focus: ${b.focus}` : ''}
          {b.degraded ? ' · degraded' : ''}
        </span>
      </header>
      {b.flags.length > 0 && <Caveats items={['One or more articles tried to instruct the model. Nothing they said was followed.']} />}
      <p style={{ margin: 0, color: 'var(--ink)', lineHeight: 1.6 }}>{b.overview}</p>

      {b.stories.length > 0 && (
        <div className="flex flex-col gap-2">
          <span className="label">what happened</span>
          {b.stories.map((s, i) => (
            <div key={i} className="flex flex-col gap-1" style={{ paddingLeft: 8, borderLeft: '2px solid var(--hairline)' }}>
              <div className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}>
                <button className="btn-ghost" style={{ color: 'var(--ink)', textAlign: 'left' }} onClick={() => onArticle(s.article_id)} title="Open the story">
                  {s.headline}
                </button>
                <Chip tone={DIRECTION_TONE[s.direction] ?? 'neutral'}>{s.direction}</Chip>
                {s.symbols.map((x) => <Chip key={x}>{x}</Chip>)}
              </div>
              {s.what_happened && <span style={{ color: 'var(--ink-dim)', fontSize: 'var(--fs-sm)', lineHeight: 1.5 }}>{s.what_happened}</span>}
              {s.why_it_matters && <span style={{ color: 'var(--ink-faint)', fontSize: 'var(--fs-tiny)', lineHeight: 1.5 }}>why it matters: {s.why_it_matters}</span>}
            </div>
          ))}
        </div>
      )}

      <Bullets title="themes" items={b.themes} />
      <Bullets title="watch next" items={b.watch} />
      <Ideas ideas={b.trade_ideas} />
      <Bullets title="risks" items={b.risks} />

      <div className="flex flex-col gap-1">
        <span className="label">sources</span>
        {b.articles.map((a) => (
          <span key={a.id} style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink-faint)' }}>
            [{a.n}] <button className="btn-ghost" onClick={() => onArticle(a.id)}>{a.title}</button> — {a.publisher}
            {!a.read && ' (feed summary only)'} · <a href={a.url} target="_blank" rel="noreferrer noopener">original ↗</a>
          </span>
        ))}
      </div>
    </article>
  )
}
