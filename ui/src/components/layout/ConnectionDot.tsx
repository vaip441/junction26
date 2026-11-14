import { useStore } from '../../state/store'

const LOOK = {
  live: { dot: 'bg-up', label: 'live' },
  connecting: { dot: 'bg-muted animate-pulse', label: 'connecting' },
  reconnecting: { dot: 'bg-madeup animate-pulse', label: 'reconnecting' },
} as const

export function ConnectionDot() {
  const status = useStore((s) => s.stream)
  const look = LOOK[status]
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted" title={`stream ${look.label}`}>
      <span className={`h-2 w-2 rounded-full ${look.dot}`} />
      {look.label}
    </span>
  )
}
