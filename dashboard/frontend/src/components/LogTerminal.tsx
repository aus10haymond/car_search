import { useEffect, useRef, useState } from 'react'
import type { LogEvent } from '../api/client'
import { api } from '../api/client'

interface Props {
  jobId: string | null
  onDone?: (status: string, exitCode: number | null) => void
}

const LEVEL_CLASS: Record<string, string> = {
  WARNING: 'text-amber-400',
  ERROR:   'text-red-400',
  INFO:    'text-green-300',
}

export function LogTerminal({ jobId, onDone }: Props) {
  const [lines, setLines]         = useState<LogEvent[]>([])
  const [done, setDone]           = useState<{ status: string; exitCode: number | null } | null>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const containerRef = useRef<HTMLDivElement>(null)
  const bottomRef    = useRef<HTMLDivElement>(null)

  // Reset when jobId changes
  useEffect(() => {
    setLines([])
    setDone(null)
    setAutoScroll(true)
  }, [jobId])

  // SSE connection
  useEffect(() => {
    if (!jobId) return
    const es = new EventSource(api.runs.streamUrl(jobId))

    es.onmessage = (e) => {
      const event: LogEvent = JSON.parse(e.data)
      if (event.type === 'done') {
        setDone({ status: event.status ?? 'unknown', exitCode: event.exit_code ?? null })
        onDone?.(event.status ?? 'unknown', event.exit_code ?? null)
        es.close()
      } else {
        setLines(prev => [...prev, event])
      }
    }

    es.onerror = () => es.close()
    return () => es.close()
  }, [jobId, onDone])

  // Auto-scroll
  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines, autoScroll])

  const handleScroll = () => {
    const el = containerRef.current
    if (!el) return
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 20
    setAutoScroll(atBottom)
  }

  if (!jobId) return null

  return (
    <div className="rounded-lg overflow-hidden border border-gray-700 bg-gray-900 font-mono text-sm">
      <div className="flex items-center justify-between px-3 py-1.5 bg-gray-800 border-b border-gray-700">
        <span className="text-gray-400 text-xs">Run log</span>
        {!done && (
          <span className="flex items-center gap-1.5 text-xs text-emerald-400">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            Running
          </span>
        )}
        {done && (
          <span className={`text-xs font-semibold ${done.status === 'complete' ? 'text-emerald-400' : 'text-red-400'}`}>
            {done.status === 'complete' ? '✓ Complete' : `✗ ${done.status}`}
            {done.exitCode != null && ` (exit ${done.exitCode})`}
          </span>
        )}
      </div>

      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="h-80 overflow-y-auto p-3 space-y-0.5"
      >
        {lines.map((line, i) => (
          <div key={i} className="leading-5">
            {line.ts && <span className="text-gray-500 mr-2">{line.ts}</span>}
            <span className={LEVEL_CLASS[line.level ?? ''] ?? 'text-gray-200'}>
              {line.msg}
            </span>
          </div>
        ))}
        {lines.length === 0 && !done && (
          <span className="text-gray-500 italic">Waiting for output…</span>
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
