// Spec: Genesis Markdown/60-UI/UI Stack.md §6 · Genesis Markdown/10-Architecture/Error Handling And Degradation.md
//
// > The UI failing must never hide risk.
//
// A wedged renderer, a lost WebGL context or a thrown error inside the graph must
// degrade to something that still shows position, heat, approval mode and the
// kill switch. So this boundary does NOT render a blank apology page: it renders
// the safety floor and the kill switch, and says plainly that the rest of the
// surface is gone.
//
// The failure this exists against is the one where the UI quietly went blind and
// the operator could not tell.

import { Component, type ErrorInfo, type ReactNode } from 'react'
import { SafetyFloor } from './SafetyFloor'
import { KillSwitch } from './KillSwitch'
import { useGenesis } from '@/store/useGenesis'

interface State { error: Error | null }

export class SurfaceBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Dropping a tier is logged, never silent — a UI that quietly went blind is
    // exactly the failure the ladder exists against.
    useGenesis.getState().setTier('degraded', `render error: ${error.message}`)
    console.error('[ui.tier_changed] surface failed, degrading', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return <DegradedSurface message={this.state.error.message} />
  }
}

function DegradedSurface({ message }: { message: string }) {
  const now = Date.now()
  return (
    <div className="flex flex-col h-full" style={{ background: 'var(--bg-void)' }}>
      <div className="flex hairline-b" style={{ flexShrink: 0 }}>
        <div className="flex-1 min-w-0 overflow-x-auto">
          <SafetyFloor now={now} />
        </div>
        <KillSwitch />
      </div>
      <div style={{ padding: 16, maxWidth: 620 }}>
        <div
          className="label"
          style={{ color: 'var(--state-degraded)', fontSize: 'var(--fs-sm)', letterSpacing: '0.16em' }}
        >
          surface degraded
        </div>
        <p style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink-dim)', marginTop: 6 }}>
          The graph and panels failed to render. The values above are the last received and are
          marked stale once they age — they are not being refreshed by this view.
        </p>
        <p style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)', marginTop: 6 }}>
          The kill switch does not depend on this surface: it goes direct to its own process over
          HTTP, and the hotkey lives in the native host.
        </p>
        <pre
          className="num"
          style={{
            marginTop: 10, padding: 8, background: 'var(--bg-inset)',
            border: '1px solid var(--hairline)', borderRadius: 'var(--r-sm)',
            fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)', whiteSpace: 'pre-wrap',
          }}
        >
          {message}
        </pre>
      </div>
    </div>
  )
}
