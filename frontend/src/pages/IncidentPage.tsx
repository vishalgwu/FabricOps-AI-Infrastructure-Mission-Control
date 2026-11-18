import { useState } from 'react'
import { ApiError, api } from '../api/client'
import { Empty, ErrorBox, Loading, Section, StatusBadge, SyntheticTag } from '../components/Common'
import { SCENARIO_LABELS, formatDuration, formatTime } from '../format'
import { toApiError, useLoad } from '../hooks'
import { links, navigate } from '../router'

export default function IncidentPage({ incidentId }: { incidentId: string }) {
  const incident = useLoad((signal) => api.getIncident(incidentId, signal), incidentId)
  const runs = useLoad((signal) => api.listIncidentRuns(incidentId, signal), `runs-${incidentId}`)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [existing, setExisting] = useState<string | null>(null)

  if (incident.result.state === 'loading') return <Loading what="the incident" />
  if (incident.result.state === 'error') {
    return incident.result.error.status === 404 ? (
      <div className="state state-error" role="alert">
        <p>No incident with the ID <code>{incidentId}</code> exists.</p>
        <a href={links.incidents()}>Back to incidents</a>
      </div>
    ) : (
      <ErrorBox error={incident.result.error} onRetry={incident.reload} />
    )
  }
  const i = incident.result.data

  const start = async () => {
    setBusy(true)
    setError(null)
    setExisting(null)
    try {
      // A fresh key per click. A double click or a refresh cannot start two investigations: the
      // backend returns the run already in flight instead.
      const { run, created } = await api.startRun(i.id, crypto.randomUUID())
      if (created) navigate(links.run(run.id))
      else {
        setExisting(run.id)
        runs.reload()
      }
    } catch (err) {
      setError(toApiError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <h2>
        {i.title} {i.synthetic ? <SyntheticTag /> : null}
      </h2>
      <dl className="facts">
        <dt>Scenario</dt>
        <dd>{SCENARIO_LABELS[i.scenario_type]}</dd>
        <dt>Severity</dt>
        <dd>{i.severity}</dd>
        <dt>Affected hosts</dt>
        <dd>{i.affected_hosts.join(', ')}</dd>
        <dt>Created</dt>
        <dd>{formatTime(i.created_at)}</dd>
        <dt>ID</dt>
        <dd><code>{i.id}</code></dd>
      </dl>
      <p className="incident-description">{i.description}</p>

      <Section id="start" title="Investigate" hint="Collects read-only telemetry and documentation, then asks for hypotheses. Stale or missing data ends in an abstention instead of a guess.">
        <button type="button" disabled={busy} onClick={() => void start()}>
          {busy ? 'Starting…' : 'Start investigation'}
        </button>
        {existing ? (
          <p className="callout callout-wait" role="status">
            An investigation is already in progress for this incident, so a new one was not started.{' '}
            <a href={links.run(existing)}>Open it</a>
          </p>
        ) : null}
        {error ? <ErrorBox error={error} /> : null}
      </Section>

      <Section id="runs" title="Investigations of this incident">
        {runs.result.state === 'loading' ? <Loading what="runs" /> : null}
        {runs.result.state === 'error' ? <ErrorBox error={runs.result.error} onRetry={runs.reload} /> : null}
        {runs.result.state === 'ready' && runs.result.data.length === 0 ? <Empty>None yet.</Empty> : null}
        {runs.result.state === 'ready' && runs.result.data.length > 0 ? (
          <ul className="plain">
            {runs.result.data.map((r) => (
              <li key={r.id}>
                <a href={links.run(r.id)}>
                  <code>{r.id}</code>
                </a>{' '}
                <StatusBadge status={r.status} /> started {formatTime(r.started_at)}
                {r.finished_at ? <> · {formatDuration(r.started_at, r.finished_at)}</> : null}
              </li>
            ))}
          </ul>
        ) : null}
      </Section>
    </div>
  )
}
