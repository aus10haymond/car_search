import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { RunRecord, AllTimeStats, TrendData } from '../api/client'

// Simple inline SVG line chart
function MiniChart({ points, color = '#6366f1' }: { points: { x: number; y: number }[]; color?: string }) {
  if (points.length < 2) return <span className="text-xs text-gray-400">Not enough data</span>
  const W = 300, H = 80, PAD = 4
  const xs = points.map(p => p.x)
  const ys = points.map(p => p.y)
  const minX = Math.min(...xs), maxX = Math.max(...xs)
  const minY = Math.min(...ys), maxY = Math.max(...ys)
  const scaleX = (x: number) => PAD + ((x - minX) / (maxX - minX || 1)) * (W - PAD * 2)
  const scaleY = (y: number) => H - PAD - ((y - minY) / (maxY - minY || 1)) * (H - PAD * 2)
  const d = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(p.x)} ${scaleY(p.y)}`).join(' ')
  return (
    <svg width={W} height={H} className="w-full" viewBox={`0 0 ${W} ${H}`}>
      <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
      {points.map((p, i) => (
        <circle key={i} cx={scaleX(p.x)} cy={scaleY(p.y)} r="3" fill={color} />
      ))}
    </svg>
  )
}

const MODEL_COLORS = ['#6366f1','#10b981','#f59e0b','#ef4444','#8b5cf6','#06b6d4']

export function HistoryView() {
  const [runs, setRuns]       = useState<RunRecord[]>([])
  const [stats, setStats]     = useState<AllTimeStats | null>(null)
  const [trends, setTrends]   = useState<TrendData>({})
  const [days, setDays]       = useState(60)
  const [page, setPage]       = useState(0)
  const PAGE_SIZE = 20

  useEffect(() => {
    api.history.runs().then(setRuns).catch(console.error)
    api.history.stats().then(setStats).catch(console.error)
  }, [])

  useEffect(() => {
    api.history.trends(days).then(setTrends).catch(console.error)
  }, [days])

  const pageRuns   = runs.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const totalPages = Math.ceil(runs.length / PAGE_SIZE)

  const fmtDate = (iso: string) => new Date(iso).toLocaleString()
  const fmtDur  = (s: number) => s >= 60 ? `${Math.round(s / 60)}m` : `${Math.round(s)}s`

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-gray-900">History</h1>

      {/* Metric cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          ['Total runs',    stats?.total_runs ?? '—'],
          ['Unique VINs',   stats?.total_unique_vins ?? '—'],
          ['Models tracked', stats?.model_latest.length ?? '—'],
          ['Cheapest ever',  stats?.cheapest ? `$${stats.cheapest.price.toLocaleString()}` : '—'],
        ].map(([label, value]) => (
          <div key={label as string} className="bg-white border border-gray-200 rounded-lg p-4 text-center">
            <div className="text-2xl font-bold text-gray-900">{value}</div>
            <div className="text-xs text-gray-500 mt-1">{label as string}</div>
          </div>
        ))}
      </div>

      {stats?.cheapest && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm text-amber-800">
          <strong>Cheapest ever: </strong>
          {stats.cheapest.year} {stats.cheapest.make} {stats.cheapest.model} {stats.cheapest.trim} —{' '}
          ${stats.cheapest.price.toLocaleString()} · seen {stats.cheapest.run_at.slice(0, 10)}
        </div>
      )}

      {/* Runs table */}
      <section>
        <h2 className="text-sm font-medium text-gray-700 mb-2">Runs ({runs.length})</h2>
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <table className="min-w-full text-sm divide-y divide-gray-100">
            <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
              <tr>
                {['Date', 'Saved / Found', 'LLM', 'Model', 'Duration'].map(h => (
                  <th key={h} className="px-4 py-2 text-left font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {pageRuns.map(r => (
                <tr key={r.run_id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 text-gray-600">{fmtDate(r.run_at)}</td>
                  <td className="px-4 py-2">
                    <span className="font-medium">{r.listings_saved}</span>
                    <span className="text-gray-400"> / {r.listings_found}</span>
                  </td>
                  <td className="px-4 py-2 text-gray-600">{r.llm_backend || '—'}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs max-w-[180px] truncate">{r.llm_model || '—'}</td>
                  <td className="px-4 py-2 text-gray-600">{fmtDur(r.duration_seconds)}</td>
                </tr>
              ))}
              {runs.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">No runs yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-4 mt-3 text-sm">
            <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
              className="px-3 py-1 border border-gray-200 rounded hover:bg-gray-50 disabled:opacity-40">← Prev</button>
            <span className="text-gray-500">{page + 1} / {totalPages}</span>
            <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page === totalPages - 1}
              className="px-3 py-1 border border-gray-200 rounded hover:bg-gray-50 disabled:opacity-40">Next →</button>
          </div>
        )}
      </section>

      {/* Price trends */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-medium text-gray-700">Price trends</h2>
          <div className="flex gap-1">
            {[30, 60, 90].map(d => (
              <button key={d} onClick={() => setDays(d)}
                className={`px-3 py-1 text-xs rounded border transition-colors ${
                  days === d ? 'bg-indigo-600 text-white border-indigo-600' : 'border-gray-200 text-gray-600 hover:border-gray-300'
                }`}
              >{d}d</button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {Object.entries(trends).map(([model, pts], idx) => {
            const color = MODEL_COLORS[idx % MODEL_COLORS.length]
            const avgPoints = pts.map((p, i) => ({ x: i, y: p.avg }))
            const latest = pts.at(-1)
            return (
              <div key={model} className="bg-white border border-gray-200 rounded-lg p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-gray-800">{model}</span>
                  {latest && (
                    <span className="text-xs text-gray-500">
                      avg ${latest.avg.toLocaleString()} · best ${latest.min.toLocaleString()}
                    </span>
                  )}
                </div>
                <MiniChart points={avgPoints} color={color} />
                <div className="flex justify-between text-xs text-gray-400 mt-1">
                  <span>{pts.at(0)?.date}</span>
                  <span>{pts.at(-1)?.date}</span>
                </div>
              </div>
            )
          })}
          {Object.keys(trends).length === 0 && (
            <div className="col-span-2 text-center py-10 text-gray-400 border-2 border-dashed border-gray-200 rounded-lg">
              No trend data for the last {days} days
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
