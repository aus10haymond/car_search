import { useEffect, useState, useCallback } from 'react'
import { api } from '../api/client'
import type { Profile, RunRequest, ResendResult } from '../api/client'
import { LogTerminal } from '../components/LogTerminal'
import { EmailPreview } from '../components/EmailPreview'

type Backend = 'auto' | 'ollama' | 'api' | 'cerebras' | 'none'

interface RunViewProps {
  onActiveJobChange?: (active: boolean) => void
}

export function RunView({ onActiveJobChange }: RunViewProps) {
  const [profiles, setProfiles]           = useState<Profile[]>([])
  const [selected, setSelected]           = useState<Set<string>>(new Set())
  const [backend, setBackend]             = useState<Backend>('auto')
  const [noLlm, setNoLlm]                = useState(false)
  const [forceEmail, setForceEmail]       = useState(false)
  const [noEmail, setNoEmail]             = useState(false)
  const [debug, setDebug]                 = useState(false)
  const [jobId, setJobId]                 = useState<string | null>(null)
  const [running, setRunning]             = useState(false)
  const [previewHtml, setPreviewHtml]     = useState<string | null>(null)
  const [error, setError]                 = useState<string | null>(null)
  const [resending, setResending]         = useState(false)
  const [resendResults, setResendResults] = useState<ResendResult[] | null>(null)

  useEffect(() => {
    api.profiles.list().then(setProfiles).catch(console.error)
  }, [])

  const toggleProfile = (id: string) =>
    setSelected(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })

  const startRun = async (dryRun: boolean) => {
    setError(null)
    setPreviewHtml(null)
    setJobId(null)
    const req: RunRequest = {
      profile_ids: selected.size ? [...selected] : profiles.map(p => p.profile_id),
      dry_run: dryRun,
      no_llm: noLlm || backend === 'none',
      backend: backend === 'ollama' ? 'ollama' : backend === 'api' ? 'api' : backend === 'cerebras' ? 'cerebras' : null,
      force_email: forceEmail,
      no_email: noEmail || dryRun,
      debug,
    }
    try {
      const { job_id } = await api.runs.start(req)
      setJobId(job_id)
      setRunning(true)
      onActiveJobChange?.(true)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to start run')
    }
  }

  const handleDone = useCallback(async (status: string, _exitCode: number | null) => {
    setRunning(false)
    onActiveJobChange?.(false)
    if (status === 'complete' && jobId) {
      // If this was a dry run, fetch email preview
      try {
        const { html } = await api.runs.emailPreview(jobId)
        setPreviewHtml(html)
      } catch {
        // Not a dry run or preview not available — that's fine
      }
    }
  }, [jobId])

  const cancel = async () => {
    if (!jobId) return
    try { await api.runs.cancel(jobId) } catch { /* ignore */ }
    setRunning(false)
  }

  const resendEmail = async () => {
    setResendResults(null)
    setError(null)
    setResending(true)
    try {
      const profileIds = selected.size ? [...selected] : profiles.map(p => p.profile_id)
      const { results } = await api.runs.resendEmail(profileIds)
      setResendResults(results)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Resend failed')
    } finally {
      setResending(false)
    }
  }

  const allSelected = profiles.length > 0 && selected.size === 0
  const btnBase = 'px-4 py-2 rounded-md text-sm font-medium transition-colors disabled:opacity-50'

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-gray-900">Run</h1>

      {/* Profile selector */}
      <section>
        <h2 className="text-sm font-medium text-gray-700 mb-2">
          Profiles
          {allSelected && <span className="ml-2 text-xs text-gray-400">(all)</span>}
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {profiles.map(p => {
            const active = selected.has(p.profile_id)
            return (
              <button key={p.profile_id} type="button"
                onClick={() => toggleProfile(p.profile_id)}
                className={`text-left px-4 py-3 rounded-lg border-2 transition-colors ${
                  active
                    ? 'border-indigo-500 bg-indigo-50'
                    : 'border-gray-200 bg-white hover:border-gray-300'
                }`}
              >
                <div className="font-medium text-sm text-gray-900">{p.label}</div>
                <div className="text-xs text-gray-500 mt-0.5">
                  {p.vehicles.map(v => v.join(' ')).join(' · ')}
                </div>
              </button>
            )
          })}
        </div>
        {selected.size > 0 && (
          <button onClick={() => setSelected(new Set())} className="mt-2 text-xs text-gray-400 hover:text-gray-600">
            Clear selection (run all)
          </button>
        )}
      </section>

      {/* Options */}
      <section className="bg-white border border-gray-200 rounded-lg px-5 py-4 space-y-4">
        <h2 className="text-sm font-medium text-gray-700">Options</h2>

        <div>
          <label className="block text-xs text-gray-500 mb-1.5">LLM backend</label>
          <div className="flex gap-2 flex-wrap">
            {(['auto', 'ollama', 'cerebras', 'api', 'none'] as Backend[]).map(b => (
              <button key={b} type="button" onClick={() => setBackend(b)}
                className={`px-3 py-1 rounded-full text-sm border transition-colors ${
                  backend === b
                    ? 'bg-indigo-600 text-white border-indigo-600'
                    : 'bg-white text-gray-600 border-gray-300 hover:border-indigo-400'
                }`}
              >
                {b === 'auto' ? 'Auto (Ollama → Anthropic)' : b === 'none' ? 'No LLM' : b === 'api' ? 'Anthropic' : b === 'cerebras' ? 'Cerebras' : b.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap gap-x-6 gap-y-2">
          {[
            [noLlm,       setNoLlm,       'Skip LLM'],
            [forceEmail,  setForceEmail,  'Force email'],
            [noEmail,     setNoEmail,     'Suppress email'],
            [debug,       setDebug,       'Debug logging'],
          ].map(([val, setter, label]) => (
            <label key={label as string} className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
              <input type="checkbox" checked={val as boolean}
                onChange={e => (setter as (v: boolean) => void)(e.target.checked)} />
              {label as string}
            </label>
          ))}
        </div>
      </section>

      {/* Action buttons */}
      <div className="flex flex-wrap gap-3">
        <button onClick={() => startRun(false)} disabled={running}
          className={`${btnBase} bg-indigo-600 text-white hover:bg-indigo-700`}>
          ▶ Run now
        </button>
        <button onClick={() => startRun(true)} disabled={running}
          className={`${btnBase} bg-white border border-gray-300 text-gray-700 hover:bg-gray-50`}>
          👁 Dry run + preview
        </button>
        <button onClick={resendEmail} disabled={running || resending}
          className={`${btnBase} bg-white border border-gray-300 text-gray-700 hover:bg-gray-50`}>
          {resending ? 'Sending…' : '✉ Resend last email'}
        </button>
        {running && (
          <button onClick={cancel}
            className={`${btnBase} bg-red-50 border border-red-300 text-red-700 hover:bg-red-100`}>
            ✕ Cancel
          </button>
        )}
      </div>

      {error && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-3">{error}</div>
      )}

      {resendResults && (
        <div className="rounded-lg border border-gray-200 bg-white divide-y divide-gray-100">
          <div className="px-4 py-2 text-xs font-medium text-gray-500 uppercase tracking-wide">
            Resend results
          </div>
          {resendResults.map(r => (
            <div key={r.profile_id} className="flex items-center justify-between px-4 py-3 text-sm">
              <span className="font-medium text-gray-800">{r.profile_label}</span>
              {r.sent
                ? <span className="text-green-700 bg-green-50 border border-green-200 rounded px-2 py-0.5 text-xs">Sent</span>
                : <span className="text-red-700 text-xs">{r.error ?? 'Failed'}</span>
              }
            </div>
          ))}
        </div>
      )}

      {/* Live log */}
      <LogTerminal jobId={jobId} onDone={handleDone} />

      {/* Email preview */}
      {previewHtml && <EmailPreview html={previewHtml} />}
    </div>
  )
}
