// Spec: Genesis Markdown/60-UI/UI Stack.md  §2 Frame — React + TypeScript + Vite
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwind from '@tailwindcss/vite'
import { spawn } from 'node:child_process'
import { mkdirSync, openSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, URL } from 'node:url'

const DAEMON = 'http://127.0.0.1:8765'

// `npm run dev` with no daemon is a dead UI, so start one. If something is
// already listening on 8765 we leave it alone -- that is `./genesis up` or the
// trader's own `genesis serve`, and killing it on vite exit would be rude.
//
// Prefer `./genesis up`: its daemon outlives vite. This fallback dies with vite.
// Neither watches Python -- every restart re-boots ~15 MCP servers, so backend
// edits land on `./genesis reload`, not on save. Output goes to a log file so
// MCP server banners stay out of the vite terminal.
function genesisDaemon(): Plugin {
  return {
    name: 'genesis-daemon',
    apply: 'serve',
    async configureServer(server) {
      const alive = await fetch(`${DAEMON}/v1/health`).then(
        (r) => r.ok,
        () => false,
      )
      if (alive) return

      const log = server.config.logger
      const root = fileURLToPath(new URL('..', import.meta.url))
      const bin = fileURLToPath(new URL('../.venv/bin/genesis', import.meta.url))
      const logDir = join(homedir(), '.genesis', 'logs')
      mkdirSync(logDir, { recursive: true })
      const out = openSync(join(logDir, 'serve.log'), 'a')

      const child = spawn(bin, ['serve'], { cwd: root, stdio: ['ignore', out, out] })
      child.on('error', (err) => log.error(`genesis serve failed to start: ${err.message}`))
      log.info('genesis: daemon starting in background — `./genesis logs` to follow')

      const stop = () => child.kill('SIGTERM')
      process.on('exit', stop)
      server.httpServer?.on('close', stop)
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwind(), genesisDaemon()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: { port: 5273 },
})
