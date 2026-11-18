import { useState } from 'react'
import { api } from '../api/client'
import { Empty, ErrorBox, Loading, Pager, StatusBadge } from '../components/Common'
import { SCENARIO_LABELS, formatDuration, formatTime } from '../format'
import { useLoad } from '../hooks'
import { links } from '../router'

const PAGE = 15

export default function HistoryPage() {
  const [offset, setOffset] = useState(0)
  const { result, reload } = useLoad((signal) => api.listRuns(PAGE, offset, signal), `history-${offset}`)
  return (
    <div>
      <h2>Run history</h2>
      <p className="hint">Every investigation, newest first. This is read from the database, so it survives restarts.</p>
      {result.state === 'loading' ? <Loading what="run history" /> : null}
      {result.state === 'error' ? <ErrorBox error={result.error} onRetry={reload} /> : null}
      {result.state === 'ready' && result.data.items.length === 0 ? (
        <Empty>
          No investigations have been run yet. <a href={links.incidents()}>Create an incident</a> to start one.
        </Empty>
      ) : null}
      {result.state === 'ready' && result.data.items.length > 0 ? (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Status</th>
                  <th>Incident</th>
                  <th>Scenario</th>
                  <th>Started</th>
                  <th>Took</th>
                </tr>
              </thead>
              <tbody>
                {result.data.items.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <a href={links.run(r.id)}>
                        <code>{r.id}</code>
                      </a>
                    </td>
                    <td>
                      <StatusBadge status={r.status} />
                    </td>
                    <td>
                      <a href={links.incident(r.incident_id)}>{r.incident_title}</a>
                    </td>
                    <td>{SCENARIO_LABELS[r.scenario_type]}</td>
                    <td>{formatTime(r.started_at)}</td>
                    <td>{formatDuration(r.started_at, r.finished_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager offset={offset} limit={PAGE} total={result.data.total} onChange={setOffset} />
        </>
      ) : null}
    </div>
  )
}
