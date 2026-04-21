import { useEffect, useRef, useState } from 'react'
import { api, API_BASE } from '../api/client'
import type { SetupStatus } from '../api/client'
import { StatusDot } from '../components/StatusDot'

type StatusKey = keyof SetupStatus

const LABELS: Record<StatusKey, string> = {
  profiles:   'Profiles',
  ollama:     'Ollama',
  anthropic:  'Anthropic API',
  gmail:      'Gmail',
  playwright: 'Playwright / Chromium',
}

const DESCRIPTIONS: Record<StatusKey, string> = {
  profiles:   'profiles.yaml exists and has at least one profile',
  ollama:     'Ollama is running and a model is available',
  anthropic:  'ANTHROPIC_API_KEY is set in .env',
  gmail:      'Gmail OAuth token is present and valid',
  playwright: 'Playwright Chromium browser is installed',
}

function SseTerminal({ lines }: { lines: string[] }) {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [lines])

  if (lines.length === 0) return null

  return (
    <div className="mt-3 bg-gray-900 rounded-md p-3 font-mono text-xs text-gray-200 max-h-52 overflow-y-auto">
      {lines.map((l, i) => <div key={i}>{l}</div>)}
      <div ref={endRef} />
    </div>
  )
}

interface ActionCardProps {
  name: StatusKey
  info: SetupStatus[StatusKey]
}

function ActionCard({ name, info }: ActionCardProps) {
  const [lines, setLines] = useState<string[]>([])
  const [running, setRunning] = useState(false)
  const [done, setDone] = useState(false)

  const runSse = async (endpoint: string) => {
    setLines([])
    setRunning(true)
    setDone(false)
    try {
      const resp = await fetch(API_BASE + endpoint, { method: 'POST' })
      if (!resp.body) throw new Error('No response body')
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      while (true) {
        const { value, done: d } = await reader.read()
        if (d) break
        buf += decoder.decode(value, { stream: true })
        const parts = buf.split('\n\n')
        buf = parts.pop() ?? ''
        for (const part of parts) {
          const dataLine = part.split('\n').find(l => l.startsWith('data:'))
          if (dataLine) setLines(prev => [...prev, dataLine.slice(5).trim()])
        }
      }
    } catch (e) {
      setLines(prev => [...prev, `Error: ${e}`])
    } finally {
      setRunning(false)
      setDone(true)
    }
  }

  let actionBtn: React.ReactNode = null
  if (name === 'playwright' && info.status !== 'ok') {
    actionBtn = (
      <button
        onClick={() => runSse('/setup/install-playwright')}
        disabled={running}
        className="mt-2 px-3 py-1 text-xs bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
      >
        {running ? 'Installing…' : 'Install Chromium'}
      </button>
    )
  }
  if (name === 'gmail' && info.status !== 'ok') {
    actionBtn = (
      <button
        onClick={() => runSse('/setup/gmail-oauth')}
        disabled={running}
        className="mt-2 px-3 py-1 text-xs bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
      >
        {running ? 'Running…' : 'Run OAuth setup'}
      </button>
    )
  }

  // Extract useful detail fields (everything except `status`)
  const details = Object.entries(info)
    .filter(([k]) => k !== 'status')
    .map(([k, v]) => `${k}: ${v}`)

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <StatusDot status={info.status} />
          <div>
            <div className="text-sm font-medium text-gray-900">{LABELS[name]}</div>
            <div className="text-xs text-gray-400 mt-0.5">{DESCRIPTIONS[name]}</div>
          </div>
        </div>
        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
          info.status === 'ok'             ? 'bg-emerald-100 text-emerald-700' :
          info.status === 'warning'        ? 'bg-amber-100 text-amber-700'    :
          info.status === 'error'          ? 'bg-red-100 text-red-700'        :
                                             'bg-gray-100 text-gray-500'
        }`}>
          {info.status}
        </span>
      </div>

      {details.length > 0 && (
        <ul className="mt-2 space-y-0.5">
          {details.map(d => (
            <li key={d} className="text-xs text-gray-500">{d}</li>
          ))}
        </ul>
      )}

      {actionBtn}
      {done && lines.length > 0 && <div className="mt-1 text-xs text-emerald-600">Done</div>}
      <SseTerminal lines={lines} />
    </div>
  )
}

export function SetupView() {
  const [status, setStatus] = useState<SetupStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]   = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const s = await api.setup.status()
      setStatus(s)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load setup status')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const allOk = status && (Object.values(status) as { status: string }[]).every(v => v.status === 'ok' || v.status === 'not_configured')

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Setup</h1>
          <p className="text-xs text-gray-400 mt-0.5">System health and one-time configuration steps</p>
        </div>
        <button onClick={load} disabled={loading}
          className="px-3 py-1.5 text-xs border border-gray-200 rounded hover:bg-gray-50 disabled:opacity-50">
          {loading ? 'Checking…' : '↻ Refresh'}
        </button>
      </div>

      {error && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-3">{error}</div>
      )}

      {allOk && (
        <div className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded p-3">
          All systems ready.
        </div>
      )}

      {loading && !status && (
        <div className="text-sm text-gray-400 py-8 text-center">Checking…</div>
      )}

      {status && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {(Object.keys(LABELS) as StatusKey[]).map(key => (
            <ActionCard key={key} name={key} info={status[key]} />
          ))}
        </div>
      )}
    </div>
  )
}
