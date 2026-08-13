import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import App from './App'
import PublicDemoPage from './pages/PublicDemoPage'
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/inter/400-italic.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import './index.css'
import {
  startSystemDataEpochMonitor,
  synchronizeSystemDataEpoch,
} from './utils/systemDataEpoch'

function Root() {
  return (
    <Routes>
      <Route path="/demo/:shareId" element={<PublicDemoPage />} />
      <Route path="*" element={<AuthProvider><App /></AuthProvider>} />
    </Routes>
  )
}

function bootstrap() {
  ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <BrowserRouter>
        <Root />
      </BrowserRouter>
    </React.StrictMode>,
  )
  if (!window.location.pathname.startsWith('/demo/')) {
    synchronizeSystemDataEpoch().then((changed) => {
      if (changed) window.location.reload()
    })
    startSystemDataEpochMonitor()
  }
}

bootstrap()
