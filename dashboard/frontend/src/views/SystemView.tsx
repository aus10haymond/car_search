import { useEffect, useRef, useState } from 'react'
import { api, API_BASE } from '../api/client'
import type { SetupStatus } from '../api/client'
import { StatusDot } from '../components/StatusDot'

// ── TerminalPanel ─────────────────────────────────────────────────────────────

interface TerminalPanelProps {
  title: string
  subtitle?: string
  logsUrl: string
  running: boolean
  onStart?: () => Promise<void>
  onStop?: () => Promise<void>
}

function TerminalPanel({ title, subtitle, logsUrl, running, onStart, onStop }: TerminalPanelProps) {
  const [lines, setLines] = useState<string[]>([])
  const [autoScroll, setAutoScroll] = useState(true)
  const [busy, setBusy] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setLines([])
    const es = new EventSource(API_BASE + logsUrl)
    es.onmessage = (e) => {
      const { msg } = JSON.parse(e.data) as { msg: string }
      if (msg) setLines(prev => [...prev.slice(-499), msg])
    }
    es.onerror = () => es.close()
    return () => es.close()
  }, [logsUrl])

  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines, autoScroll])

  const handleScroll = () => {
    const el = containerRef.current
    if (!el) return
    setAutoScroll(el.scrollTop + el.clientHeight >= el.scrollHeight - 20)
  }

  const act = async (fn: () => Promise<void>) => {
    setBusy(true)
    try { await fn() } finally { setBusy(false) }
  }

  return (
    <div className="rounded-lg overflow-hidden border border-gray-700 bg-gray-900 flex flex-col">
      {/* Title bar */}
      <div className="flex items-center justify-between px-3 py-2 bg-gray-800 border-b border-gray-700">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
            running ? 'bg-emerald-400 animate-pulse' : 'bg-gray-500'
          }`} />
          <span className="text-sm font-medium text-gray-200 truncate">{title}</span>
          {subtitle && (
            <span className="text-xs text-gray-500 truncate hidden sm:block">{subtitle}</span>
          )}
          <span className={`text-xs px-1.5 py-0.5 rounded flex-shrink-0 ${
            running ? 'bg-emerald-900 text-emerald-300' : 'bg-gray-700 text-gray-400'
          }`}>
            {running ? 'Running' : 'Stopped'}
          </span>
        </div>
        <div className="flex gap-2 ml-2 flex-shrink-0">
          {onStart && !running && (
            <button
              onClick={() => act(onStart)}
              disabled={busy}
              className="px-2.5 py-1 text-xs bg-emerald-600 text-white rounded hover:bg-emerald-700 disabled:opacity-50"
            >
              {busy ? 'Starting…' : 'Start'}
            </button>
          )}
          {onStop && running && (
            <button
              onClick={() => act(onStop)}
              disabled={busy}
              className="px-2.5 py-1 text-xs bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50"
            >
              {busy ? 'Stopping…' : 'Stop'}
            </button>
          )}
        </div>
      </div>

      {/* Log output */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="h-64 overflow-y-auto p-3 font-mono text-xs text-gray-300 space-y-0.5"
      >
        {lines.length === 0 ? (
          <span className="text-gray-500 italic">No output yet…</span>
        ) : (
          lines.map((l, i) => (
            <div key={i} className="leading-5 break-all whitespace-pre-wrap">{l}</div>
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {!autoScroll && (
        <div className="text-center py-1 bg-gray-800 border-t border-gray-700">
          <button
            onClick={() => { setAutoScroll(true); bottomRef.current?.scrollIntoView() }}
            className="text-xs text-indigo-400 hover:text-indigo-300"
          >
            ↓ Jump to bottom
          </button>
        </div>
      )}
    </div>
  )
}

// ── Setup status cards (unchanged from SetupView) ─────────────────────────────

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

function ActionCard({ name, info }: { name: StatusKey; info: SetupStatus[StatusKey] }) {
  const [lines, setLines] = useState<string[]>([])
  const [running, setRunning] = useState(false)
  const [done, setDone] = useState(false)

  const runSse = async (endpoint: string) => {
    setLines([]); setRunning(true); setDone(false)
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
      setRunning(false); setDone(true)
    }
  }

  let actionBtn: React.ReactNode = null
  if (name === 'playwright' && info.status !== 'ok') {
    actionBtn = (
      <button onClick={() => runSse('/setup/install-playwright')} disabled={running}
        className="mt-2 px-3 py-1 text-xs bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50">
        {running ? 'Installing…' : 'Install Chromium'}
      </button>
    )
  }
  if (name === 'gmail' && info.status !== 'ok') {
    actionBtn = (
      <button onClick={() => runSse('/setup/gmail-oauth')} disabled={running}
        className="mt-2 px-3 py-1 text-xs bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50">
        {running ? 'Running…' : 'Run OAuth setup'}
      </button>
    )
  }

  const details = Object.entries(info).filter(([k]) => k !== 'status').map(([k, v]) => `${k}: ${v}`)

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
          info.status === 'ok'      ? 'bg-emerald-100 text-emerald-700' :
          info.status === 'warning' ? 'bg-amber-100 text-amber-700'    :
          info.status === 'error'   ? 'bg-red-100 text-red-700'        :
                                      'bg-gray-100 text-gray-500'
        }`}>{info.status}</span>
      </div>
      {details.length > 0 && (
        <ul className="mt-2 space-y-0.5">
          {details.map(d => <li key={d} className="text-xs text-gray-500">{d}</li>)}
        </ul>
      )}
      {actionBtn}
      {done && lines.length > 0 && <div className="mt-1 text-xs text-emerald-600">Done</div>}
      <SseTerminal lines={lines} />
    </div>
  )
}

// ── SystemView ────────────────────────────────────────────────────────────────

interface SystemStatus {
  backend: { running: boolean; pid: number }
  ngrok:   { running: boolean; domain: string }
}

export function SystemView() {
  const [sysStatus, setSysStatus]   = useState<SystemStatus | null>(null)
  const [setupStatus, setSetupStatus] = useState<SetupStatus | null>(null)
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState<string | null>(null)

  const loadSetup = async () => {
    setLoading(true); setError(null)
    try { setSetupStatus(await api.setup.status()) }
    catch (e: unknown) { setError(e instanceof Error ? e.message : 'Failed') }
    finally { setLoading(false) }
  }

  const pollSystem = async () => {
    try { setSysStatus(await api.system.status()) } catch { /* ignore */ }
  }

  useEffect(() => {
    loadSetup()
    pollSystem()
    const id = setInterval(pollSystem, 5_000)
    return () => clearInterval(id)
  }, [])

  const startNgrok = async () => {
    await api.system.ngrokStart()
    setSysStatus(s => s ? { ...s, ngrok: { ...s.ngrok, running: true } } : s)
  }

  const stopNgrok = async () => {
    await api.system.ngrokStop()
    setSysStatus(s => s ? { ...s, ngrok: { ...s.ngrok, running: false } } : s)
  }

  const allOk = setupStatus &&
    (Object.values(setupStatus) as { status: string }[]).every(
      v => v.status === 'ok' || v.status === 'not_configured'
    )

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">System</h1>
          <p className="text-xs text-gray-400 mt-0.5">Process management and system health</p>
        </div>
        <button onClick={loadSetup} disabled={loading}
          className="px-3 py-1.5 text-xs border border-gray-200 rounded hover:bg-gray-50 disabled:opacity-50">
          {loading ? 'Checking…' : '↻ Refresh'}
        </button>
      </div>

      {/* Process terminals */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <TerminalPanel
          title="Backend Server"
          subtitle={sysStatus ? `PID ${sysStatus.backend.pid}` : undefined}
          logsUrl="/system/backend/logs"
          running={sysStatus?.backend.running ?? true}
        />
        <TerminalPanel
          title="ngrok Tunnel"
          subtitle={sysStatus?.ngrok.domain}
          logsUrl="/system/ngrok/logs"
          running={sysStatus?.ngrok.running ?? false}
          onStart={startNgrok}
          onStop={stopNgrok}
        />
      </div>

      {/* Component health */}
      <div>
        <h2 className="text-sm font-medium text-gray-700 mb-3">Component Health</h2>

        {error && (
          <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-3 mb-3">{error}</div>
        )}
        {allOk && (
          <div className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded p-3 mb-3">
            All systems ready.
          </div>
        )}
        {loading && !setupStatus && (
          <div className="text-sm text-gray-400 py-8 text-center">Checking…</div>
        )}
        {setupStatus && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {(Object.keys(LABELS) as StatusKey[]).map(key => (
              <ActionCard key={key} name={key} info={setupStatus[key]} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
