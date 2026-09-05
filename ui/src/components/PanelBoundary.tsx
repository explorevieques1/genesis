// Spec: Genesis Markdown/60-UI/UI Stack.md §6 Degradation
//
// One panel's blast radius is one panel.
//
// The note's governing constraint is that *"the UI failing must never hide
// risk"*. The concrete version inside a dock is this: a charting library that
// throws on a malformed series must not blank the workspace that also contains
// the risk gauges. React's default behaviour is the opposite — an uncaught
// error in any component unmounts the whole tree — so without a boundary here,
// one bad series takes down the safety numbers beside it.
//
// The boundary reports rather than retries silently. A panel that failed says
// what threw, because the person looking at it is usually the person who can
// fix it, and "something went wrong" wastes their time.

import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  name: string
  children: ReactNode
}

interface State {
  error: Error | null
}

export class PanelBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Logged with the panel name so a console full of React noise still says
    // which of eight panels was the one that died.
    console.error(`[panel:${this.props.name}] ${error.message}`, info.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="flex flex-col h-full gap-2 p-3 scroll-y">
        <div className="label" style={{ color: 'var(--state-down)' }}>
          panel failed
        </div>
        <div
          className="num"
          style={{
            fontSize: 'var(--fs-tiny)',
            color: 'var(--ink-dim)',
            lineHeight: 1.6,
            wordBreak: 'break-word',
          }}
        >
          {error.message}
        </div>
        <div className="label" style={{ color: 'var(--ink-ghost)' }}>
          {this.props.name} · the rest of this workspace is unaffected
        </div>
        <button
          className="btn"
          style={{ alignSelf: 'flex-start', marginTop: 4 }}
          onClick={() => this.setState({ error: null })}
        >
          try again
        </button>
      </div>
    )
  }
}
