import { useState, useEffect } from 'react'
import { api } from '../api/client'
import { useAuth } from '../App'

export default function LoginPage() {
  const { login } = useAuth()
  const [mode, setMode] = useState<'checking' | 'setup' | 'login'>('checking')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    api.auth.setupRequired()
      .then(r => setMode(r.required ? 'setup' : 'login'))
      .catch(() => setMode('login'))
  }, [])

  const handleSetup = async (e: React.FormEvent) => {
    e.preventDefault()
    if (password !== confirm) { setError('Passwords do not match'); return }
    setError(null); setSubmitting(true)
    try {
      await api.auth.setup(username, password)
      // Auto-login after setup
      const res = await api.auth.login(username, password)
      login(res.access_token, { username: res.username, role: res.role, profile_id: res.profile_id })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Setup failed')
    } finally {
      setSubmitting(false)
    }
  }

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null); setSubmitting(true)
    try {
      const res = await api.auth.login(username, password)
      login(res.access_token, { username: res.username, role: res.role, profile_id: res.profile_id })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setSubmitting(false)
    }
  }

  const inputCls = 'block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500'

  if (mode === 'checking') {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-gray-400 text-sm">Connecting…</div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        {/* Logo / heading */}
        <div className="text-center mb-8">
          <img src="/autospy-logo.svg" alt="Autospy" className="w-12 h-12 mb-4" />
          <h1 className="text-2xl font-bold text-gray-900">Autospy Portal</h1>
          <p className="text-sm text-gray-500 mt-1">
            {mode === 'setup' ? 'Create your admin account to get started' : 'Sign in to your account'}
          </p>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          {mode === 'setup' && (
            <div className="mb-4 p-3 bg-indigo-50 border border-indigo-200 rounded-lg text-xs text-indigo-800">
              No accounts exist yet. Create the admin account below.
            </div>
          )}

          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
              {error}
            </div>
          )}

          <form onSubmit={mode === 'setup' ? handleSetup : handleLogin} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
              <input
                className={inputCls} required autoFocus
                value={username} onChange={e => setUsername(e.target.value)}
                autoComplete="username"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
              <input
                type="password" className={inputCls} required
                value={password} onChange={e => setPassword(e.target.value)}
                autoComplete={mode === 'setup' ? 'new-password' : 'current-password'}
                minLength={mode === 'setup' ? 8 : undefined}
              />
              {mode === 'setup' && (
                <p className="text-xs text-gray-400 mt-0.5">At least 8 characters</p>
              )}
            </div>

            {mode === 'setup' && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Confirm password</label>
                <input
                  type="password" className={inputCls} required
                  value={confirm} onChange={e => setConfirm(e.target.value)}
                  autoComplete="new-password"
                />
              </div>
            )}

            <button
              type="submit" disabled={submitting}
              className="w-full bg-indigo-600 text-white rounded-md py-2 text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
            >
              {submitting
                ? (mode === 'setup' ? 'Creating account…' : 'Signing in…')
                : (mode === 'setup' ? 'Create admin account' : 'Sign in')}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
