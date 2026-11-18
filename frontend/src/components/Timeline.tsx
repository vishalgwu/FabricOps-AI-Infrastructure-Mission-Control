import type { RunEvent } from '../api/types'
import { STAGE_LABELS, foldStages, formatTime } from '../format'

const MARK = { started: 'In progress', completed: 'Done', failed: 'Failed' } as const

export function Timeline({ events }: { events: RunEvent[] }) {
  const rows = foldStages(events)
  if (rows.length === 0) return <p className="state state-empty">No stages have started yet.</p>
  return (
    <ol className="timeline" aria-label="Investigation stages">
      {rows.map((r) => (
        <li key={r.stage} className={`stage stage-${r.state}`}>
          <span className="stage-mark">{MARK[r.state]}</span>
          <span className="stage-name">{STAGE_LABELS[r.stage] ?? r.stage}</span>
          <time className="stage-time">{formatTime(r.time)}</time>
          {r.state === 'failed' && r.detail ? <span className="stage-detail">{r.detail}</span> : null}
        </li>
      ))}
    </ol>
  )
}
