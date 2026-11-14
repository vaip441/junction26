import { EmptyState } from '../common/EmptyState'

/** How the market resolves, and the phrases the terminal searches the web with for it. */
export function RulesPanel({ rules, queries }: { rules: string; queries: string[] | null }) {
  if (!rules && !queries?.length) return <EmptyState title="No rules given" />
  return (
    <div className="flex flex-col gap-3 p-3">
      {rules && <p className="whitespace-pre-line text-xs leading-relaxed text-muted">{rules}</p>}
      {queries && queries.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-faint">What it searches the web for</span>
          <div className="flex flex-wrap gap-1.5">
            {queries.map((q) => (
              <span key={q} className="rounded border border-line bg-bg px-2 py-0.5 text-xs text-text">
                {q}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
