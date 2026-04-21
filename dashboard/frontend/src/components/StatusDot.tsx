type DotStatus = 'ok' | 'warning' | 'error' | 'not_configured' | 'loading'

const COLOURS: Record<DotStatus, string> = {
  ok:             'bg-emerald-500',
  warning:        'bg-amber-400',
  error:          'bg-red-500',
  not_configured: 'bg-gray-400',
  loading:        'bg-gray-300 animate-pulse',
}

interface Props {
  status: DotStatus
  label?: string
  size?: 'sm' | 'md'
}

export function StatusDot({ status, label, size = 'md' }: Props) {
  const dot = size === 'sm' ? 'w-2 h-2' : 'w-2.5 h-2.5'
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`${dot} rounded-full flex-shrink-0 ${COLOURS[status]}`} />
      {label && <span className="text-sm text-gray-600">{label}</span>}
    </span>
  )
}
