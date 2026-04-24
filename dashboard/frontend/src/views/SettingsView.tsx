import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Settings } from '../api/client'
import { useTheme } from '../hooks/useTheme'
import type { ThemePreference } from '../hooks/useTheme'

const inputCls = 'block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500'

const GROUPS: { title: string; keys: (keyof Settings)[] }[] = [
  {
    title: 'Search behaviour',
    keys: ['zip_code', 'max_pages_per_search', 'request_delay_seconds', 'page_timeout_seconds', 'headless'],
  },
  {
    title: 'Scheduling',
    keys: ['check_interval_hours'],
  },
  {
    title: 'Payment calculator',
    keys: ['down_payment', 'interest_rate', 'loan_term_months'],
  },
  {
    title: 'Email',
    keys: ['send_email', 'email_from_name'],
  },
  {
    title: 'LLM — NVIDIA NIM',
    keys: ['nvidia_enabled', 'nvidia_model', 'nvidia_max_tokens'],
  },
  {
    title: 'LLM — Cerebras',
    keys: ['cerebras_enabled', 'cerebras_model', 'cerebras_max_tokens'],
  },
  {
    title: 'LLM — Anthropic',
    keys: ['anthropic_enabled', 'anthropic_model', 'anthropic_max_tokens'],
  },
  {
    title: 'LLM — Ollama',
    keys: ['ollama_enabled', 'ollama_timeout', 'ollama_ref_doc_max_chars', 'ollama_preferred_models'],
  },
  {
    title: 'Secrets',
    keys: ['NVIDIA_API_KEY', 'ANTHROPIC_API_KEY', 'CEREBRAS_API_KEY', 'OLLAMA_NETWORK_HOST', 'OLLAMA_NETWORK_HOST_2', 'GMAIL_SENDER', 'GMAIL_CLIENT_ID', 'GMAIL_CLIENT_SECRET'],
  },
  {
    title: 'Paths',
    keys: ['output_dir', 'vehicle_reference_dir', 'db_path', 'log_file'],
  },
]

const SECRET_KEYS = new Set(['NVIDIA_API_KEY', 'ANTHROPIC_API_KEY', 'CEREBRAS_API_KEY', 'OLLAMA_NETWORK_HOST', 'OLLAMA_NETWORK_HOST_2', 'GMAIL_SENDER', 'GMAIL_CLIENT_ID', 'GMAIL_CLIENT_SECRET'])

const BOOL_KEYS = new Set(['headless', 'send_email', 'nvidia_enabled', 'cerebras_enabled', 'anthropic_enabled', 'ollama_enabled'])
const NUM_KEYS  = new Set(['max_pages_per_search', 'request_delay_seconds', 'page_timeout_seconds', 'check_interval_hours',
  'down_payment', 'interest_rate', 'loan_term_months',
  'nvidia_max_tokens', 'cerebras_max_tokens', 'anthropic_max_tokens',
  'ollama_timeout', 'ollama_ref_doc_max_chars'])
const LIST_KEYS = new Set(['ollama_preferred_models'])

const LABELS: Partial<Record<keyof Settings, string>> = {
  zip_code:                'Zip code',
  max_pages_per_search:    'Max pages per search',
  request_delay_seconds:   'Request delay (seconds)',
  page_timeout_seconds:    'Page timeout (seconds)',
  headless:                'Headless browser',
  check_interval_hours:    'Check interval (hours)',
  down_payment:            'Down payment ($)',
  interest_rate:           'Interest rate (%)',
  loan_term_months:        'Loan term (months)',
  send_email:              'Send emails',
  email_from_name:         'From name',
  nvidia_enabled:          'NVIDIA NIM enabled',
  nvidia_model:            'NVIDIA model',
  nvidia_max_tokens:       'Max tokens',
  cerebras_enabled:        'Cerebras enabled',
  cerebras_model:          'Cerebras model',
  cerebras_max_tokens:     'Max tokens',
  anthropic_enabled:       'Anthropic enabled',
  anthropic_model:         'Anthropic model',
  anthropic_max_tokens:    'Max tokens',
  ollama_enabled:          'Ollama enabled',
  ollama_timeout:          'Ollama timeout (seconds)',
  ollama_ref_doc_max_chars:'Ref doc max chars',
  ollama_preferred_models: 'Preferred models (comma-separated)',
  output_dir:              'Output directory',
  vehicle_reference_dir:   'Vehicle reference directory',
  db_path:                 'Database path',
  log_file:                'Log file path',
}

function FieldInput({
  k, value, original, onChange,
}: {
  k: keyof Settings
  value: unknown
  original: unknown
  onChange: (key: keyof Settings, v: unknown) => void
}) {
  const isSecret = SECRET_KEYS.has(k)
  const isDirty  = value !== original

  if (BOOL_KEYS.has(k)) {
    return (
      <label className={`inline-flex items-center gap-2 text-sm cursor-pointer ${isDirty ? 'font-medium text-indigo-700' : 'text-gray-700'}`}>
        <input type="checkbox" checked={Boolean(value)} onChange={e => onChange(k, e.target.checked)} />
        {value ? 'Yes' : 'No'}
      </label>
    )
  }

  if (LIST_KEYS.has(k)) {
    const listVal = Array.isArray(value) ? (value as string[]).join(', ') : String(value ?? '')
    return (
      <input
        className={`${inputCls} ${isDirty ? 'border-indigo-400 ring-1 ring-indigo-300' : ''}`}
        value={listVal}
        placeholder="model1, model2"
        onChange={e => onChange(k, e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
      />
    )
  }

  if (isSecret) {
    return (
      <input
        type="password"
        className={`${inputCls} ${isDirty ? 'border-indigo-400 ring-1 ring-indigo-300' : ''}`}
        value={value === '***' ? '' : (value as string) ?? ''}
        placeholder={original === '***' ? '(set — leave blank to keep)' : 'Not set'}
        onChange={e => onChange(k, e.target.value || null)}
      />
    )
  }

  if (NUM_KEYS.has(k)) {
    return (
      <input
        type="number"
        className={`${inputCls} ${isDirty ? 'border-indigo-400 ring-1 ring-indigo-300' : ''}`}
        value={value as number ?? ''}
        onChange={e => onChange(k, e.target.value === '' ? null : Number(e.target.value))}
      />
    )
  }

  return (
    <input
      type="text"
      className={`${inputCls} ${isDirty ? 'border-indigo-400 ring-1 ring-indigo-300' : ''}`}
      value={value as string ?? ''}
      onChange={e => onChange(k, e.target.value)}
    />
  )
}

const THEME_OPTIONS: { value: ThemePreference; label: string; icon: string }[] = [
  { value: 'light',  label: 'Light',  icon: '☀️' },
  { value: 'dark',   label: 'Dark',   icon: '🌙' },
  { value: 'system', label: 'System', icon: '💻' },
]

export function SettingsView() {
  const { preference, setTheme } = useTheme()
  const [original, setOriginal] = useState<Settings | null>(null)
  const [draft, setDraft]       = useState<Settings | null>(null)
  const [saving, setSaving]     = useState(false)
  const [saved, setSaved]       = useState(false)
  const [error, setError]       = useState<string | null>(null)

  useEffect(() => {
    api.settings.get()
      .then(s => { setOriginal(s); setDraft(s) })
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load settings'))
  }, [])

  const handleChange = (k: keyof Settings, v: unknown) => {
    setDraft(d => d ? { ...d, [k]: v } : d)
    setSaved(false)
  }

  const handleSave = async () => {
    if (!draft || !original) return
    setSaving(true)
    setError(null)
    try {
      // Send only changed keys (skip secrets with empty string = no-change)
      const patch: Partial<Settings> = {}
      for (const k of Object.keys(draft) as (keyof Settings)[]) {
        const isSecret = SECRET_KEYS.has(k)
        if (isSecret && (draft[k] === null || draft[k] === '')) continue
        if (draft[k] !== original[k]) {
          (patch as Record<string, unknown>)[k] = draft[k]
        }
      }
      if (Object.keys(patch).length === 0) { setSaved(true); setTimeout(() => setSaved(false), 2000); return }
      await api.settings.patch(patch)
      const fresh = await api.settings.get()
      setOriginal(fresh)
      setDraft(fresh)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const dirtyCount = draft && original
    ? Object.keys(draft).filter(k => {
        if (SECRET_KEYS.has(k as keyof Settings) && (draft[k as keyof Settings] === null || draft[k as keyof Settings] === '')) return false
        return draft[k as keyof Settings] !== original[k as keyof Settings]
      }).length
    : 0

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Settings</h1>
          <p className="text-xs text-gray-400 mt-0.5">Stored in dashboard_settings.json. Secrets are write-only.</p>
        </div>
        <div className="flex items-center gap-3">
          {saved && <span className="text-xs text-emerald-600">✓ Saved</span>}
          {dirtyCount > 0 && !saved && (
            <span className="text-xs text-amber-500">{dirtyCount} unsaved {dirtyCount === 1 ? 'change' : 'changes'}</span>
          )}
          <button onClick={handleSave} disabled={saving || !draft}
            className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700 disabled:opacity-40">
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>

      {error && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-3 flex justify-between">
          {error}
          <button onClick={() => setError(null)} className="ml-2 font-bold">×</button>
        </div>
      )}

      {!draft && !error && (
        <div className="text-sm text-gray-400 text-center py-8">Loading…</div>
      )}

      {/* Appearance — local preference, not saved to the backend */}
      <section className="bg-white border border-gray-200 rounded-lg px-5 py-4">
        <h2 className="text-sm font-medium text-gray-700 mb-3 pb-2 border-b border-gray-100">Appearance</h2>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-2">Theme</label>
          <div className="flex gap-2">
            {THEME_OPTIONS.map(opt => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setTheme(opt.value)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm border transition-colors ${
                  preference === opt.value
                    ? 'bg-indigo-600 text-white border-indigo-600'
                    : 'bg-white text-gray-600 border-gray-300 hover:border-indigo-400'
                }`}
              >
                <span>{opt.icon}</span>
                {opt.label}
              </button>
            ))}
          </div>
          <p className="text-xs text-gray-400 mt-2">Stored locally in the browser — not synced to the server.</p>
        </div>
      </section>

      {draft && GROUPS.map(group => {
        const visibleKeys = group.keys.filter(k => k in draft)
        if (visibleKeys.length === 0) return null
        return (
          <section key={group.title} className="bg-white border border-gray-200 rounded-lg px-5 py-4">
            <h2 className="text-sm font-medium text-gray-700 mb-3 pb-2 border-b border-gray-100">{group.title}</h2>
            <div className="space-y-3">
              {visibleKeys.map(k => (
                <div key={k}>
                  <label className="block text-xs font-medium text-gray-500 mb-1">
                    {LABELS[k] ?? k}
                  </label>
                  <FieldInput
                    k={k}
                    value={draft[k]}
                    original={original?.[k]}
                    onChange={handleChange}
                  />
                </div>
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}
