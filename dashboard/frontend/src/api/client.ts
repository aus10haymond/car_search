// ── Types ─────────────────────────────────────────────────────────────────────

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
}

export interface RunRequest {
  profile_ids: string[]
  dry_run: boolean
  no_llm: boolean
  backend: 'ollama' | 'api' | null
  force_email: boolean
  no_email: boolean
  debug: boolean
}

export interface JobStatus {
  job_id: string
  status: 'pending' | 'running' | 'complete' | 'failed' | 'cancelled'
  started_at: string
  finished_at: string | null
  profile_ids: string[]
  exit_code: number | null
}

export interface LogEvent {
  ts?: string
  level?: string
  msg?: string
  type?: 'done' | 'error'
  status?: string
  exit_code?: number | null
}

export interface ComponentStatus {
  status: 'ok' | 'warning' | 'error' | 'not_configured'
  [key: string]: unknown
}

export interface SetupStatus {
  profiles:   ComponentStatus
  ollama:     ComponentStatus
  anthropic:  ComponentStatus
  gmail:      ComponentStatus
  playwright: ComponentStatus
}

export interface RunRecord {
  run_id:           string
  run_at:           string
  listings_found:   number
  listings_saved:   number
  llm_backend:      string
  llm_model:        string
  duration_seconds: number
}

export interface AllTimeStats {
  total_runs:        number
  total_unique_vins: number
  model_latest: { make: string; model: string; avg_price: number; min_price: number; count: number; run_at: string }[]
  cheapest: { year: number; make: string; model: string; trim: string; price: number; run_at: string } | null
}

export interface TrendPoint { date: string; avg: number; min: number }
export type TrendData = Record<string, TrendPoint[]>

export interface DocFile {
  filename:         string
  size_bytes:       number
  matched_profiles: string[]
}

export interface ScheduleStatus {
  enabled:        boolean
  interval_hours: number
  profile_ids:    string[]
  next_run_at:    string | null
  last_run_at:    string | null
  last_job_id:    string | null
  last_status:    string | null
  running_job:    { job_id: string; status: string; started_at: string } | null
  task_alive:     boolean
}

export interface ScheduleRequest {
  enabled:        boolean
  interval_hours: number
  profile_ids:    string[]
}

export interface ResendResult {
  profile_id:    string
  profile_label: string
  sent:          boolean
  error:         string | null
}

export interface ResendResponse {
  results: ResendResult[]
}

export type Settings = Record<string, unknown>

// ── Base URL detection ────────────────────────────────────────────────────────
//
// In a normal browser (dev Vite proxy or production served from :8000), relative
// paths work fine.  Inside the Tauri webview the origin is tauri://localhost or
// http://tauri.localhost (WebView2 on Windows), so relative paths resolve against
// the webview's custom protocol — not the FastAPI backend.  Detect and fix.

function getApiBase(): string {
  if (typeof window === 'undefined') return ''
  const { protocol, hostname } = window.location
  if (protocol === 'tauri:' || hostname === 'tauri.localhost') {
    return 'http://127.0.0.1:8000'
  }
  return ''
}

export const API_BASE = getApiBase()

// ── Helpers ───────────────────────────────────────────────────────────────────

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 10_000)
  let res: Response
  try {
    res = await fetch(API_BASE + path, {
      headers: { 'Content-Type': 'application/json', ...init?.headers },
      signal: controller.signal,
      ...init,
    })
  } catch (err) {
    clearTimeout(timer)
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error('Request timed out — is the backend running?')
    }
    throw err
  }
  clearTimeout(timer)
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  // 204 No Content
  if (res.status === 204) return undefined as unknown as T
  return res.json()
}

// ── Profiles ──────────────────────────────────────────────────────────────────

export const api = {
  profiles: {
    list:   ()                          => request<Profile[]>('/profiles'),
    create: (p: Profile)                => request<Profile>('/profiles', { method: 'POST', body: JSON.stringify(p) }),
    update: (id: string, p: Profile)    => request<Profile>(`/profiles/${id}`, { method: 'PUT', body: JSON.stringify(p) }),
    delete: (id: string)                => request<void>(`/profiles/${id}`, { method: 'DELETE' }),
  },

  runs: {
    start:        (req: RunRequest)              => request<{ job_id: string }>('/runs', { method: 'POST', body: JSON.stringify(req) }),
    status:       (jobId: string)               => request<JobStatus>(`/runs/${jobId}/status`),
    emailPreview: (jobId: string)               => request<{ html: string }>(`/runs/${jobId}/email-preview`),
    cancel:       (jobId: string)               => request<{ job_id: string; status: string }>(`/runs/${jobId}`, { method: 'DELETE' }),
    streamUrl:    (jobId: string)               => `${API_BASE}/runs/${jobId}/stream`,
    resendEmail:  (profile_ids: string[])       => request<ResendResponse>('/runs/resend-email', { method: 'POST', body: JSON.stringify({ profile_ids }) }),
  },

  schedule: {
    get:    ()                       => request<ScheduleStatus>('/schedule'),
    update: (req: ScheduleRequest)   => request<ScheduleStatus>('/schedule', { method: 'POST', body: JSON.stringify(req) }),
  },

  history: {
    runs:   ()                          => request<RunRecord[]>('/history/runs'),
    stats:  ()                          => request<AllTimeStats>('/history/stats'),
    trends: (days: number, profileId?: string) => {
      const qs = profileId ? `?days=${days}&profile_id=${profileId}` : `?days=${days}`
      return request<TrendData>(`/history/trends${qs}`)
    },
  },

  setup: {
    status: () => request<SetupStatus>('/setup/status'),
    installPlaywrightUrl: () => '/setup/install-playwright',
    gmailOauthUrl:        () => '/setup/gmail-oauth',
  },

  settings: {
    get:   ()                           => request<Settings>('/settings'),
    patch: (changes: Partial<Settings>) => request<{ saved: string[] }>('/settings', { method: 'PATCH', body: JSON.stringify(changes) }),
  },

  docs: {
    list:   ()                                        => request<DocFile[]>('/docs'),
    get:    (filename: string)                        => request<{ filename: string; content: string }>(`/docs/${filename}`),
    put:    (filename: string, content: string)       => request<DocFile>(`/docs/${filename}`, { method: 'PUT', body: JSON.stringify({ content }) }),
    delete: (filename: string)                        => request<void>(`/docs/${filename}`, { method: 'DELETE' }),
  },
}
