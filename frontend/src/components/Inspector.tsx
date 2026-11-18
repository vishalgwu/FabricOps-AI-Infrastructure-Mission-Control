import { useEffect, useRef } from 'react'
import { api } from '../api/client'
import type { EvidenceRecord } from '../api/types'
import { formatTime } from '../format'
import { useLoad } from '../hooks'
import { ErrorBox, Loading, SyntheticTag } from './Common'

export type Selection = { kind: 'evidence'; id: string } | { kind: 'citation'; id: string } | null

/** Clickable chip for an evidence ID or a document citation ID. */
export function RefChip({
  kind,
  id,
  selected,
  onSelect,
}: {
  kind: 'evidence' | 'citation'
  id: string
  selected: Selection
  onSelect: (s: Selection) => void
}) {
  const active = selected?.kind === kind && selected.id === id
  return (
    <button
      type="button"
      className={`chip chip-${kind}${active ? ' chip-active' : ''}`}
      aria-pressed={active}
      aria-label={`${kind === 'evidence' ? 'Evidence' : 'Documentation passage'} ${id}`}
      onClick={() => onSelect(active ? null : { kind, id })}
    >
      {id}
    </button>
  )
}

/** Shows the record behind a chip. Evidence is looked up in the run's stored records; citations are
 *  fetched from the backend. An ID that does not resolve is shown as a problem, never hidden. */
export function Inspector({
  selection,
  evidence,
  onClose,
}: {
  selection: Selection
  evidence: EvidenceRecord[]
  onClose: () => void
}) {
  const ref = useRef<HTMLElement>(null)
  const shown = selection ? `${selection.kind}:${selection.id}` : ''
  useEffect(() => {
    // On narrow screens the panel sits below the content: bring it into view when something is picked.
    if (shown) ref.current?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
  }, [shown])
  if (!selection) return null
  return (
    <aside className="inspector" aria-label="Details" ref={ref}>
      <div className="inspector-head">
        <h3>{selection.kind === 'evidence' ? 'Evidence record' : 'Documentation passage'}</h3>
        <button type="button" onClick={onClose}>
          Close
        </button>
      </div>
      {selection.kind === 'evidence' ? (
        <EvidenceDetail record={evidence.find((e) => e.id === selection.id)} id={selection.id} />
      ) : (
        <CitationDetail id={selection.id} />
      )}
    </aside>
  )
}

export function EvidenceDetail({ record, id }: { record: EvidenceRecord | undefined; id: string }) {
  if (!record) {
    return (
      <p className="state state-error" role="alert">
        Evidence <code>{id}</code> does not resolve to any record stored for this run.
      </p>
    )
  }
  return (
    <div>
      <dl className="facts">
        <dt>ID</dt>
        <dd><code>{record.id}</code> {record.synthetic ? <SyntheticTag /> : null}</dd>
        <dt>Host</dt>
        <dd>{record.host_id}</dd>
        <dt>Source</dt>
        <dd>{record.source_type} (read by <code>{record.tool_name}</code>)</dd>
        <dt>Observed at</dt>
        <dd>{formatTime(record.observed_at)}</dd>
        <dt>Collected at</dt>
        <dd>{formatTime(record.ingested_at)}</dd>
      </dl>
      {record.source_type === 'log' ? (
        <p className="hint">Log text is untrusted data written by other systems. It is shown as plain text and was never treated as an instruction.</p>
      ) : null}
      <pre className="payload" tabIndex={0}>{JSON.stringify(record.payload, null, 2)}</pre>
    </div>
  )
}

export function CitationDetail({ id }: { id: string }) {
  const { result, reload } = useLoad((signal) => api.getChunk(id, signal), id)
  if (result.state === 'loading') return <Loading what="the passage" />
  if (result.state === 'error') {
    return result.error.status === 404 ? (
      <p className="state state-error" role="alert">
        Citation <code>{id}</code> does not resolve to any document passage.
      </p>
    ) : (
      <ErrorBox error={result.error} onRetry={reload} />
    )
  }
  const c = result.data
  return (
    <div>
      <dl className="facts">
        <dt>Document</dt>
        <dd>{c.title} ({c.document_id})</dd>
        <dt>Version</dt>
        <dd>
          {c.version} {c.date ? <>({c.date})</> : null}{' '}
          {c.status === 'superseded' ? <span className="tag tag-warn">superseded</span> : null}
        </dd>
        <dt>Section</dt>
        <dd>{c.section}</dd>
        <dt>Source</dt>
        <dd><code>{c.source}</code> {c.synthetic_or_official === 'synthetic' ? <SyntheticTag label="synthetic runbook" /> : null}</dd>
      </dl>
      {c.status === 'superseded' ? (
        <p className="state state-error" role="alert">This version has been replaced; its advice may be out of date.</p>
      ) : null}
      <blockquote className="passage">{c.text}</blockquote>
      <p className="hint">Documentation text is reference material, not an instruction to FabricOps.</p>
    </div>
  )
}
