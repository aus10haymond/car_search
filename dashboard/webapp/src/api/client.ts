// ── Types ─────────────────────────────────────────────────────────────────────

export interface AuthUser {
  username: string
  role: 'admin' | 'user'
  profile_id: string | null
}

export interface LoginResponse extends AuthUser {
  access_token: string
  token_type: string
}

export interface Profile {
  profile_id: string
  label: string
  vehicles: [string, string][]
  max_price: number | null
  max_mileage: number
  min_year: number
  max_year: number
  email_to: string[]
  fuel_type_filters: (string | null)[]
  model_preference: string[]
  reference_doc_path: string | null
  excluded_trim_keywords: string[]
  excluded_years: number[]
  show_financing: boolean
  down_payment: number | null
  email_only_on_new_or_drops: boolean
}

export interface DocFile {
  filename: string
  size_bytes: number
  matched_profiles: string[]
}

export interface PortalUser {
  username: string
  role: 'admin' | 'user'
  profile_id: string | null
}

export type Settings = Record<string, unknown>

// ── Token storage ─────────────────────────────────────────────────────────────

const TOKEN_KEY = 'autospy_portal_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

// ── HTTP helpers ──────────────────────────────────────────────────────────────

async function request<T>(path: string, init?: RequestInit, timeoutMs = 30_000): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  let res: Response
  try {
    res = await fetch(path, {
      ...init,
      headers: { ...headers, ...init?.headers },
      signal: controller.signal,
    })
  } catch (err) {
    clearTimeout(timer)
    if (err instanceof DOMException && err.name === 'AbortError')
      throw new Error('Request timed out — is the backend running?')
    throw err
  }
  clearTimeout(timer)

  if (res.status === 401) {
    clearToken()
    window.location.reload()
    throw new Error('Session expired')
  }

  if (!res.ok) {
    const body = await res.text()
    let detail = body
    try {
      detail = JSON.parse(body)?.detail ?? body
    } catch {}
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }

  if (res.status === 204) return undefined as unknown as T
  return res.json()
}

// ── Portal API ────────────────────────────────────────────────────────────────

export const api = {
  auth: {
    setupRequired: () => request<{ required: boolean }>('/portal/auth/setup-required'),
    setup: (username: string, password: string) =>
      request<{ message: string }>('/portal/auth/setup', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      }),
    login: (username: string, password: string) =>
      request<LoginResponse>('/portal/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      }),
    me: () => request<AuthUser>('/portal/auth/me'),
  },

  profiles: {
    list: () => request<Profile[]>('/portal/profiles'),
    create: (p: Profile) =>
      request<Profile>('/portal/profiles', { method: 'POST', body: JSON.stringify(p) }),
    update: (id: string, p: Profile) =>
      request<Profile>(`/portal/profiles/${id}`, { method: 'PUT', body: JSON.stringify(p) }),
    delete: (id: string) =>
      request<void>(`/portal/profiles/${id}`, { method: 'DELETE' }),
  },

  docs: {
    list: () => request<DocFile[]>('/portal/docs'),
    get: (filename: string) =>
      request<{ filename: string; content: string }>(`/portal/docs/${filename}`),
    put: (filename: string, content: string) =>
      request<DocFile>(`/portal/docs/${filename}`, {
        method: 'PUT',
        body: JSON.stringify({ content }),
      }),
    delete: (filename: string) =>
      request<void>(`/portal/docs/${filename}`, { method: 'DELETE' }),
    generate: (make: string, model: string, yearStart: number, yearEnd: number, notes: string) =>
      request<{ content: string }>('/portal/docs/generate', {
        method: 'POST',
        body: JSON.stringify({ make, model, year_start: yearStart, year_end: yearEnd, notes }),
      }, 120_000),
  },

  settings: {
    get: () => request<Settings>('/portal/settings'),
    patch: (changes: Partial<Settings>) =>
      request<{ saved: string[] }>('/portal/settings', {
        method: 'PATCH',
        body: JSON.stringify(changes),
      }),
  },

  users: {
    list: () => request<PortalUser[]>('/portal/users'),
    create: (username: string, password: string, role: string, profile_id: string | null) =>
      request<PortalUser>('/portal/users', {
        method: 'POST',
        body: JSON.stringify({ username, password, role, profile_id }),
      }),
    delete: (username: string) =>
      request<void>(`/portal/users/${username}`, { method: 'DELETE' }),
    changePassword: (username: string, password: string) =>
      request<{ message: string }>(`/portal/users/${username}/password`, {
        method: 'PUT',
        body: JSON.stringify({ password }),
      }),
    assignProfile: (username: string, profile_id: string | null) =>
      request<{ message: string }>(`/portal/users/${username}/profile`, {
        method: 'PUT',
        body: JSON.stringify({ profile_id }),
      }),
  },
}
