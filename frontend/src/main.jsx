import React, { lazy, Suspense } from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import App from './App'
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

const PublicDemoPage = lazy(() => import('./pages/PublicDemoPage'))

class PublicDemoErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="flex min-h-screen items-center justify-center bg-cloud-100 px-6 text-center">
        <div>
          <p className="text-sm font-medium text-ink-body">演示页加载失败</p>
          <button className="btn-secondary mt-4" onClick={() => window.location.reload()}>
            重新加载
          </button>
        </div>
      </div>
    )
  }
}

function Root() {
  return (
    <Routes>
      <Route
        path="/demo/:shareId"
        element={(
          <PublicDemoErrorBoundary>
            <Suspense fallback={<div className="flex min-h-screen items-center justify-center bg-cloud-100"><div className="skeleton h-6 w-36" /></div>}>
              <PublicDemoPage />
            </Suspense>
          </PublicDemoErrorBoundary>
        )}
      />
      <Route path="*" element={<AuthProvider><App /></AuthProvider>} />
    </Routes>
  )
}

async function bootstrap() {
  const isDemoRoute = window.location.pathname.startsWith('/demo/')
  if (!isDemoRoute) {
    const changed = await synchronizeSystemDataEpoch()
    if (changed) {
      window.location.reload()
      return
    }
  }

  ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <BrowserRouter>
        <Root />
      </BrowserRouter>
    </React.StrictMode>,
  )
  if (!isDemoRoute) startSystemDataEpochMonitor()
}

void bootstrap()
