import type { ReactNode } from 'react'
import { ApiError } from '../api/client'
import type { RunStatus } from '../api/types'
import { STATUS_INFO } from '../format'

export function SyntheticBanner() {
  return (
    <div className="banner" role="note">
      <strong>All data shown is synthetic.</strong> Incidents, telemetry, configuration and runbooks are fabricated for
      this demo. FabricOps only proposes next steps; it never changes anything.
    </div>
  )
}

export function SyntheticTag({ label = 'synthetic' }: { label?: string }) {
  return <span className="tag tag-synthetic">{label}</span>
}

export function StatusBadge({ status }: { status: RunStatus }) {
  const info = STATUS_INFO[status]
  return <span className={`badge badge-${info.tone}`}>{info.label}</span>
}

export function Loading({ what }: { what: string }) {
  return (
    <p className="state state-loading" role="status">
      Loading {what}…
    </p>
  )
}

export function ErrorBox({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  return (
    <div className="state state-error" role="alert">
      <p>
        <strong>Something went wrong.</strong> {error.message}
        {error.code !== 'network_error' && error.code !== 'unexpected' ? <> (code: {error.code})</> : null}
      </p>
      {onRetry ? (
        <button type="button" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="state state-empty">{children}</p>
}

export function Section({ title, hint, children, id }: { title: string; hint?: string; children: ReactNode; id?: string }) {
  return (
    <section className="section" aria-labelledby={id}>
      <h3 id={id}>{title}</h3>
      {hint ? <p className="hint">{hint}</p> : null}
      {children}
    </section>
  )
}

export function Pager({
  offset,
  limit,
  total,
  onChange,
}: {
  offset: number
  limit: number
  total: number
  onChange: (offset: number) => void
}) {
  if (total <= limit) return null
  return (
    <nav className="pager" aria-label="Pagination">
      <button type="button" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
        Newer
      </button>
      <span>
        {offset + 1}–{Math.min(offset + limit, total)} of {total}
      </span>
      <button type="button" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>
        Older
      </button>
    </nav>
  )
}
