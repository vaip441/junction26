import type { ReactNode } from 'react'

/** Every empty or waiting state says what it is doing, in words. */
export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-1 p-6 text-center">
      <p className="text-balance text-sm font-medium text-muted">{title}</p>
      {children && <p className="max-w-xs text-balance text-xs text-faint">{children}</p>}
    </div>
  )
}
