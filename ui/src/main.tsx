import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './app/App'
import { presentation } from './lib/presentation'
import './styles/index.css'

// presentation mode scales the type for a projector (see styles/index.css)
document.documentElement.classList.toggle('presentation', presentation)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
