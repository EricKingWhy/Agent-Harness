import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { initTheme } from './lib/theme'
import { initDensity } from './lib/density'
import './index.css'
import App from './App.tsx'

// Paint 前解析主题 + 密度（localStorage → 默认值），避免首帧闪错主题/档位
initTheme()
initDensity()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
