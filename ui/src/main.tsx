// Spec: Genesis Markdown/60-UI/UI Stack.md
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { SurfaceBoundary } from './components/SurfaceBoundary'
import './styles/global.css'

const root = document.getElementById('root')
if (!root) throw new Error('#root missing')

createRoot(root).render(
  <StrictMode>
    <SurfaceBoundary>
      <App />
    </SurfaceBoundary>
  </StrictMode>,
)
