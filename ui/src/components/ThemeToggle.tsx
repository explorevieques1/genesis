// Spec: Genesis Markdown/60-UI/UI Stack.md §4 Chrome
//
// Operator preference, not system state — so it lives here and in localStorage,
// not in the Genesis store or the token layer's data-approval/halted/tier flags.
// The token layer keys off `data-theme='light'` (tokens.css); everything else is
// already semantic (`var(--ink)`, `var(--bg-panel)`) and needs no change.

import { memo, useCallback, useState } from 'react'

type Theme = 'dark' | 'light'
const KEY = 'genesis-theme'

function read(): Theme {
  try {
    return localStorage.getItem(KEY) === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

function apply(theme: Theme) {
  if (theme === 'light') document.documentElement.dataset.theme = 'light'
  else delete document.documentElement.dataset.theme
}

// Run before first paint to avoid a dark flash on a light-preferring operator.
apply(read())

export const ThemeToggle = memo(function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(read)

  const toggle = useCallback(() => {
    setTheme((prev) => {
      const next: Theme = prev === 'dark' ? 'light' : 'dark'
      try {
        localStorage.setItem(KEY, next)
      } catch {
        /* private mode — the toggle still works for this session */
      }
      apply(next)
      return next
    })
  }, [])

  return (
    <button
      className="flex items-center hairline-l"
      onClick={toggle}
      title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      style={{
        padding: '0 11px',
        flexShrink: 0,
        color: 'var(--ink-faint)',
        fontSize: 'var(--fs-base)',
        lineHeight: 1,
      }}
    >
      {theme === 'dark' ? '☀' : '☾'}
    </button>
  )
})
