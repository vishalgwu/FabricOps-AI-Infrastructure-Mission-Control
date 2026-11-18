import { useState } from 'react'
import { ApiError, api } from '../api/client'
import type { ScenarioInfo, Severity } from '../api/types'
import { Empty, ErrorBox, Loading, Pager, Section, SyntheticTag } from '../components/Common'
import { SCENARIO_LABELS, formatTime } from '../format'
import { toApiError, useLoad } from '../hooks'
import { links, navigate } from '../router'

const PAGE = 10
const SEVERITIES: Severity[] = ['unknown', 'low', 'medium', 'high', 'critical']

export default function IncidentsPage() {
  const [offset, setOffset] = useState(0)
  const { result, reload } = useLoad((signal) => api.listIncidents(PAGE, offset, signal), `incidents-${offset}`)
  return (
    <div>
      <h2>Incidents</h2>
      <IncidentForm />
      <Section id="list" title="Existing incidents">
        {result.state === 'loading' ? <Loading what="incidents" /> : null}
        {result.state === 'error' ? <ErrorBox error={result.error} onRetry={reload} /> : null}
        {result.state === 'ready' && result.data.items.length === 0 ? (
          <Empty>No incidents yet. Create one above to start an investigation.</Empty>
        ) : null}
        {result.state === 'ready' && result.data.items.length > 0 ? (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Incident</th>
                    <th>Scenario</th>
                    <th>Severity</th>
                    <th>Affected hosts</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {result.data.items.map((i) => (
                    <tr key={i.id}>
                      <td>
                        <a href={links.incident(i.id)}>{i.title}</a> {i.synthetic ? <SyntheticTag /> : null}
                      </td>
                      <td>{SCENARIO_LABELS[i.scenario_type]}</td>
                      <td>{i.severity}</td>
                      <td>{i.affected_hosts.join(', ')}</td>
                      <td>{formatTime(i.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager offset={offset} limit={PAGE} total={result.data.total} onChange={setOffset} />
          </>
        ) : null}
      </Section>
    </div>
  )
}

function IncidentForm() {
  const scenarios = useLoad((signal) => api.scenarios(signal), 'scenarios')
  if (scenarios.result.state === 'loading') return <Loading what="the scenario list" />
  if (scenarios.result.state === 'error') return <ErrorBox error={scenarios.result.error} onRetry={scenarios.reload} />
  if (scenarios.result.data.length === 0) return <Empty>The backend has no scenarios to offer.</Empty>
  return <IncidentFormBody scenarios={scenarios.result.data} />
}

function IncidentFormBody({ scenarios }: { scenarios: ScenarioInfo[] }) {
  // Start from the first scenario's suggested incident; choosing another one re-fills the form.
  const [scenario, setScenario] = useState<ScenarioInfo>(scenarios[0])
  const [title, setTitle] = useState(scenarios[0].title)
  const [description, setDescription] = useState(scenarios[0].description)
  const [severity, setSeverity] = useState<Severity>(scenarios[0].severity)
  const [hosts, setHosts] = useState<string[]>(scenarios[0].suggested_affected_hosts)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  const choose = (s: ScenarioInfo) => {
    setScenario(s)
    setTitle(s.title)
    setDescription(s.description)
    setSeverity(s.severity)
    setHosts(s.suggested_affected_hosts)
    setError(null)
  }

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const incident = await api.createIncident({
        title, description, scenario_type: scenario.scenario_type, severity, affected_hosts: hosts,
      })
      navigate(links.incident(incident.id))
    } catch (err) {
      setError(toApiError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Section id="new" title="Create an incident" hint="Pick one of the built-in synthetic scenarios. The telemetry for it comes from fabricated fixtures.">
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <label>
          Scenario
          <select
            value={scenario.scenario_type}
            onChange={(e) => {
              const next = scenarios.find((s) => s.scenario_type === e.target.value)
              if (next) choose(next)
            }}
          >
            {scenarios.map((s) => (
              <option key={s.scenario_type} value={s.scenario_type}>
                {SCENARIO_LABELS[s.scenario_type]}
              </option>
            ))}
          </select>
        </label>
        <label>
          Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label>
          Description
          <textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <label>
          Severity
          <select value={severity} onChange={(e) => setSeverity(e.target.value as Severity)}>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <fieldset>
          <legend>Affected hosts</legend>
          {scenario.hosts.map((h) => (
            <label key={h.id} className="check">
              <input
                type="checkbox"
                checked={hosts.includes(h.id)}
                onChange={(e) => setHosts(e.target.checked ? [...hosts, h.id] : hosts.filter((x) => x !== h.id))}
              />
              {h.id} <span className="hint">({h.role})</span>
            </label>
          ))}
        </fieldset>
        <button type="submit" disabled={busy || !title.trim() || !description.trim() || hosts.length === 0}>
          {busy ? 'Creating…' : 'Create incident'}
        </button>
        {error ? (
          <div className="state state-error" role="alert">
            <p>{error.message}</p>
            {error.details.length > 0 ? (
              <ul>
                {error.details.map((d) => (
                  <li key={d.field + d.message}>
                    {d.field}: {d.message}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </form>
    </Section>
  )
}
