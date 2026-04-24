import { useState, useEffect, createContext, useContext } from 'react'
import { api, type AuthUser, getToken, setToken, clearToken } from './api/client'
import LoginPage from './pages/LoginPage'
import AdminPage from './pages/AdminPage'
import UserPage from './pages/UserPage'

// ── Auth context ──────────────────────────────────────────────────────────────

interface AuthCtx {
  user: AuthUser | null
  login: (token: string, user: AuthUser) => void
  logout: () => void
}

const AuthContext = createContext<AuthCtx>({ user: null, login: () => {}, logout: () => {} })
export const useAuth = () => useContext(AuthContext)

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!getToken()) { setLoading(false); return }
    api.auth.me()
      .then(u => setUser(u))
      .catch(() => clearToken())
      .finally(() => setLoading(false))
  }, [])

  const login = (token: string, u: AuthUser) => {
    setToken(token)
    setUser(u)
  }

  const logout = () => {
    clearToken()
    setUser(null)
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-gray-400 text-sm">Loading…</div>
      </div>
    )
  }

  return (
    <AuthContext.Provider value={{ user, login, logout }}>
      {!user
        ? <LoginPage />
        : user.role === 'admin'
          ? <AdminPage />
          : <UserPage />
      }
    </AuthContext.Provider>
  )
}
