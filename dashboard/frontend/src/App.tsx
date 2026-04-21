import { useEffect, useState } from 'react'
import { NavLink, Routes, Route, Navigate } from 'react-router-dom'
import { api } from './api/client'
import type { SetupStatus } from './api/client'
import { StatusDot } from './components/StatusDot'
import { RunView }      from './views/RunView'
import { ProfilesView } from './views/ProfilesView'
import { HistoryView }  from './views/HistoryView'
import { DocsView }     from './views/DocsView'
import { SetupView }    from './views/SetupView'
import { SettingsView } from './views/SettingsView'

const NAV = [
  { to: '/run',      label: 'Run' },
  { to: '/profiles', label: 'Profiles' },
  { to: '/history',  label: 'History' },
  { to: '/docs',     label: 'Docs' },
  { to: '/setup',    label: 'Setup' },
  { to: '/settings', label: 'Settings' },
]

export default function App() {
  const [setupStatus, setSetupStatus] = useState<SetupStatus | null>(null)
  const [lastRun, setLastRun]         = useState<string | null>(null)
  const [activeJob, setActiveJob]     = useState(false)

  // Poll setup status every 30s for status bar dots
  useEffect(() => {
    const poll = async () => {
      try {
        const s = await api.setup.status()
        setSetupStatus(s)
      } catch { /* backend may not be up yet */ }
    }
    poll()
    const id = setInterval(poll, 30_000)
    return () => clearInterval(id)
  }, [])

  // Refresh last run time from history whenever a job finishes
  useEffect(() => {
    api.history.runs()
      .then(runs => {
        if (runs.length > 0) {
          setLastRun(new Date(runs[0].run_at).toLocaleString())
        }
      })
      .catch(() => {})
  }, [activeJob])

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">
      {/* Sidebar */}
      <aside className="w-52 flex-shrink-0 bg-white border-r border-gray-200 flex flex-col">
        <div className="px-5 py-5 border-b border-gray-100">
          <div className="text-base font-semibold text-gray-900">Car Search</div>
          <div className="text-xs text-gray-400 mt-0.5">Admin Dashboard</div>
        </div>

        <nav className="flex-1 py-3 space-y-0.5 px-2 overflow-y-auto">
          {NAV.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center px-3 py-2 rounded-md text-sm transition-colors ${
                  isActive
                    ? 'bg-indigo-50 text-indigo-700 font-medium'
                    : 'text-gray-600 hover:bg-gray-100'
                }`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Mini status in sidebar footer */}
        {setupStatus && (
          <div className="px-4 py-3 border-t border-gray-100 space-y-1">
            <div className="flex items-center gap-2 text-xs text-gray-500">
              <StatusDot status={setupStatus.ollama.status} size="sm" />
              Ollama
            </div>
            <div className="flex items-center gap-2 text-xs text-gray-500">
              <StatusDot status={setupStatus.gmail.status} size="sm" />
              Gmail
            </div>
          </div>
        )}
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <main className="flex-1 overflow-y-auto p-6">
          <Routes>
            <Route path="/" element={<Navigate to="/run" replace />} />
            <Route path="/run"      element={<RunView onActiveJobChange={setActiveJob} />} />
            <Route path="/profiles" element={<ProfilesView />} />
            <Route path="/history"  element={<HistoryView />} />
            <Route path="/docs"     element={<DocsView />} />
            <Route path="/setup"    element={<SetupView />} />
            <Route path="/settings" element={<SettingsView />} />
          </Routes>
        </main>

        {/* Status bar */}
        <footer className="border-t border-gray-200 bg-white px-5 py-2 flex items-center gap-6 text-xs text-gray-400">
          {activeJob ? (
            <span className="flex items-center gap-1.5 text-indigo-600 font-medium">
              <span className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse" />
              Job running…
            </span>
          ) : (
            <span>Last run: {lastRun ?? '—'}</span>
          )}

          {setupStatus && (
            <>
              <span className="flex items-center gap-1.5">
                <StatusDot status={setupStatus.ollama.status} size="sm" />
                Ollama
              </span>
              <span className="flex items-center gap-1.5">
                <StatusDot status={setupStatus.gmail.status} size="sm" />
                Gmail
              </span>
            </>
          )}
        </footer>
      </div>
    </div>
  )
}
