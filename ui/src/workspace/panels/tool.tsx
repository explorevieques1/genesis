// Spec: Genesis Markdown/60-UI/Terminal.md · 30-MCP/MCP Gateway.md
//
// One panel for every tool in the catalogue.
//
// There are 131 declared tools across 17 servers, and there will be more. A
// hand-written panel per tool is 131 files that rot the moment a server
// renames an argument — so this renders its form from the tool's own JSON
// Schema, fetched from the live gateway. A new MCP server becomes usable with
// no UI change at all, which is the property that makes the catalogue worth
// having.
//
// **What it will not do.** It does not guess at fields the schema does not
// describe, it does not submit when the gateway says the tool is not callable,
// and it does not pretty-print a failure into something that looks like data.
// A tool that returns nothing renders as "returned nothing", never as an empty
// table — `Widget Catalog`'s rule that stale or absent data must *look* absent.

import { useCallback, useMemo, useState } from 'react'
import { api, type JsonSchemaField, type McpCallResult } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Empty, Loading } from '@/components/States'
import { Chip, PanelBody, Section } from '@/components/Primitives'

/** The panel id encodes the tool: `tool:sec-edgar.get_company_facts`. */
export function toolPanelId(toolId: string): string {
  return `tool:${toolId}`
}

type Values = Record<string, string>

/**
 * What kind of control one schema field gets.
 *
 * Deliberately four kinds. JSON Schema can express far more than this, and a
 * form that tried to cover all of it would be a schema-form library — a
 * dependency, for a handful of tools that take a ticker and a date. Anything
 * unrecognised falls to `json`, which is a textarea and an honest one: the
 * person can type exactly what the server wants, and the label tells them the
 * type they are typing.
 */
export function kindOf(field: JsonSchemaField): 'enum' | 'boolean' | 'number' | 'text' | 'json' {
  if (field.enum?.length) return 'enum'
  const type = Array.isArray(field.type) ? field.type[0] : field.type
  if (type === 'boolean') return 'boolean'
  if (type === 'number' || type === 'integer') return 'number'
  if (type === 'string' || type === undefined) return 'text'
  return 'json'
}

/**
 * Form strings back into the types the server declared.
 *
 * Every input is a string — that is what a DOM input is — and a server that
 * asked for a number gets a number. An empty optional field is *omitted*
 * rather than sent as `""`, because those mean different things to an MCP
 * server: absent is "use your default", empty string is "use this empty
 * string", and sending the second where the first was meant is a silent wrong
 * answer.
 */
function coerce(
  values: Values,
  properties: Record<string, JsonSchemaField>,
): { args: Record<string, unknown>; bad: string[] } {
  const args: Record<string, unknown> = {}
  const bad: string[] = []
  for (const [name, field] of Object.entries(properties)) {
    const raw = values[name]
    if (raw === undefined || raw === '') continue
    switch (kindOf(field)) {
      case 'boolean':
        args[name] = raw === 'true'
        break
      case 'number': {
        const parsed = Number(raw)
        if (Number.isNaN(parsed)) bad.push(`${name} is not a number`)
        else args[name] = parsed
        break
      }
      case 'json':
        try {
          args[name] = JSON.parse(raw)
        } catch {
          bad.push(`${name} is not valid JSON`)
        }
        break
      default:
        args[name] = raw
    }
  }
  return { args, bad }
}

/**
 * Props are Dockview's `params`, typed narrowly rather than as
 * `IDockviewPanelProps`: the panel registry is a `Record<PanelId,
 * ComponentType<Record<string, unknown>>>`, and a component demanding the full
 * Dockview prop set does not fit it. All this panel needs is which tool it is.
 */
export function ToolPanel({ params }: { params?: { toolId?: string } }) {
  const toolId = String(params?.toolId ?? '')
  // The first read of any tool builds the gateway on the daemon — seventeen
  // servers, tens of seconds. Labelled so the wait reads as work rather than
  // as a hang.
  const schema = useRead(() => api.mcpTool(toolId), [toolId])
  const [values, setValues] = useState<Values>({})
  const [result, setResult] = useState<McpCallResult | null>(null)
  const [running, setRunning] = useState(false)

  const tool = schema.state.status === 'ready' ? schema.state.data.tool : null
  const properties = useMemo(
    () => tool?.input_schema?.properties ?? {},
    [tool],
  )
  const required = useMemo(
    () => new Set(tool?.input_schema?.required ?? []),
    [tool],
  )

  const missing = useMemo(
    () => [...required].filter((name) => !values[name]?.trim()),
    [required, values],
  )

  const run = useCallback(async () => {
    if (!tool) return
    const { args, bad } = coerce(values, properties)
    if (bad.length) {
      setResult({ ok: false, reason: bad.join(' · ') })
      return
    }
    setRunning(true)
    try {
      setResult(await api.mcpCall(tool.id, args))
    } catch (error) {
      setResult({ ok: false, reason: error instanceof Error ? error.message : String(error) })
    } finally {
      setRunning(false)
    }
  }, [tool, values, properties])

  if (!toolId) return <Absent reason="this panel was opened without a tool" />
  if (schema.state.status === 'loading') {
    return <Loading rows={5} label={`${toolId} — connecting to its server`} />
  }
  if (schema.state.status !== 'ready' || !tool) {
    return (
      <Absent
        reason={schema.state.reason ?? `could not describe ${toolId}`}
        onRetry={schema.reload}
      />
    )
  }

  const fields = Object.entries(properties)

  return (
    <PanelBody>
      <div className="flex items-baseline gap-2" style={{ flexWrap: 'wrap' }}>
        <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink)' }}>{tool.id}</span>
        <Chip tone="neutral">{tool.capability}</Chip>
        <Chip tone={tool.trust === 'trusted' ? 'good' : 'neutral'}>{tool.trust}</Chip>
        <Chip tone="neutral">{`tier ${tool.tier}`}</Chip>
      </div>
      {tool.description && (
        <div style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink-dim)', marginTop: 4 }}>
          {tool.description}
        </div>
      )}

      <Section title="arguments">
        {fields.length === 0 ? (
          <Empty hint="this tool takes no arguments">nothing to fill in</Empty>
        ) : (
          <div style={{ display: 'grid', gap: 6 }}>
            {fields.map(([name, field]) => (
              <Field
                key={name}
                name={name}
                field={field}
                required={required.has(name)}
                value={values[name] ?? ''}
                onChange={(next) => setValues((v) => ({ ...v, [name]: next }))}
                onSubmit={() => { if (tool.callable && !missing.length) void run() }}
              />
            ))}
          </div>
        )}

        <div className="flex items-center gap-2" style={{ marginTop: 8 }}>
          <button
            className="btn"
            disabled={!tool.callable || running || missing.length > 0}
            onClick={() => void run()}
          >
            {running ? 'running…' : 'run'}
          </button>
          {/* Why the button is dead, always. A disabled control with no
              explanation is the thing that makes a surface feel broken. */}
          {!tool.callable && (
            <span className="label" style={{ color: 'var(--state-blocked)', textTransform: 'none' }}>
              {tool.refusal}
            </span>
          )}
          {tool.callable && missing.length > 0 && (
            <span className="label" style={{ color: 'var(--ink-faint)', textTransform: 'none' }}>
              needs {missing.join(', ')}
            </span>
          )}
        </div>
      </Section>

      {result && <Result result={result} />}
    </PanelBody>
  )
}

function Field({
  name, field, required, value, onChange, onSubmit,
}: {
  name: string
  field: JsonSchemaField
  required: boolean
  value: string
  onChange: (next: string) => void
  onSubmit: () => void
}) {
  const kind = kindOf(field)
  const label = (
    <label
      className="label"
      style={{ color: required ? 'var(--ink-dim)' : 'var(--ink-ghost)', textTransform: 'none' }}
      title={field.description}
    >
      {name}
      {required && <span style={{ color: 'var(--core)' }}> *</span>}
      <span style={{ color: 'var(--ink-ghost)' }}>
        {' '}
        {Array.isArray(field.type) ? field.type.join('|') : (field.type ?? 'string')}
      </span>
    </label>
  )

  const shared = {
    value,
    onChange: (e: { target: { value: string } }) => onChange(e.target.value),
    onKeyDown: (e: React.KeyboardEvent) => { if (e.key === 'Enter') onSubmit() },
    style: {
      background: 'var(--bg-void)', border: '1px solid var(--hairline)',
      color: 'var(--ink)', padding: '3px 6px', fontSize: 'var(--fs-sm)',
      fontFamily: 'inherit', width: '100%',
    },
  }

  return (
    <div style={{ display: 'grid', gap: 2 }}>
      {label}
      {kind === 'enum' ? (
        <select {...shared}>
          <option value="">—</option>
          {field.enum!.map((option) => (
            <option key={String(option)} value={String(option)}>{String(option)}</option>
          ))}
        </select>
      ) : kind === 'boolean' ? (
        <select {...shared}>
          <option value="">—</option>
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      ) : kind === 'json' ? (
        <textarea {...shared} rows={3} placeholder="JSON" />
      ) : (
        <input {...shared} placeholder={field.description ?? ''} />
      )}
    </div>
  )
}

/**
 * What came back.
 *
 * An array of flat objects becomes a table because that is what most MCP tools
 * return and a table is what a person can read. Everything else is shown as
 * formatted JSON rather than coerced into a shape it is not — a wrong table is
 * worse than honest JSON.
 */
function Result({ result }: { result: McpCallResult }) {
  const rows = useMemo(() => tabular(result.content), [result.content])

  if (!result.ok) {
    return (
      <Section title="result">
        <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--state-down)' }}>
          {result.reason ?? 'the call failed and said nothing about why'}
        </div>
      </Section>
    )
  }

  return (
    <Section
      title="result"
      actions={
        // Provenance a person should see. Fenced means third-party text was
        // wrapped on the way out; it is still worth reading, and it is worth
        // knowing that is what you are reading.
        <span className="label" style={{ color: 'var(--ink-ghost)' }}>
          {[
            result.latency_ms !== undefined ? `${Math.round(result.latency_ms)} ms` : null,
            result.fenced ? 'fenced — third-party text' : null,
          ].filter(Boolean).join(' · ')}
        </span>
      }
    >
      {rows ? (
        <div className="scroll-x">
          <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 'var(--fs-tiny)' }}>
            <thead>
              <tr>
                {rows.columns.map((column) => (
                  <th
                    key={column}
                    className="label"
                    style={{ textAlign: 'left', padding: '2px 6px', borderBottom: '1px solid var(--hairline)' }}
                  >
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.rows.map((row, index) => (
                <tr key={index}>
                  {rows.columns.map((column) => (
                    <td key={column} style={{ padding: '2px 6px', color: 'var(--ink-dim)', whiteSpace: 'nowrap' }}>
                      {row[column] === undefined || row[column] === null ? '—' : String(row[column])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : result.content === null || result.content === undefined || result.content === '' ? (
        <Empty hint="the call succeeded">returned nothing</Empty>
      ) : (
        <pre
          className="scroll-y"
          style={{
            margin: 0, maxHeight: 320, fontSize: 'var(--fs-tiny)',
            color: 'var(--ink-dim)', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
          }}
        >
          {typeof result.content === 'string'
            ? result.content
            : JSON.stringify(result.content, null, 2)}
        </pre>
      )}
    </Section>
  )
}

/** An array of flat objects, or `null` if it is anything else. */
function tabular(content: unknown): { columns: string[]; rows: Record<string, unknown>[] } | null {
  if (!Array.isArray(content) || content.length === 0) return null
  const rows = content as unknown[]
  if (!rows.every((row) => row !== null && typeof row === 'object' && !Array.isArray(row))) return null
  const records = rows as Record<string, unknown>[]
  // A nested value would render as "[object Object]", which is worse than the
  // JSON it came from -- so anything with structure inside it stays JSON.
  if (records.some((row) => Object.values(row).some((v) => v !== null && typeof v === 'object'))) {
    return null
  }
  const columns: string[] = []
  for (const row of records) {
    for (const key of Object.keys(row)) if (!columns.includes(key)) columns.push(key)
  }
  return { columns, rows: records }
}
