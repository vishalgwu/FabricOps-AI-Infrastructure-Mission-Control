import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import App from '../App'
import { apiError, incident, installFetch, run, scenarios } from '../test/fakeApi'
import HistoryPage from './HistoryPage'
import IncidentPage from './IncidentPage'
import IncidentsPage from './IncidentsPage'

const list = (items = [incident()], total = items.length) => ({ body: { items, total, limit: 10, offset: 0 } })

describe('IncidentsPage', () => {
  it('shows an empty state when there are no incidents', async () => {
    installFetch([[/GET \/api\/scenarios/, { body: scenarios() }], [/GET \/api\/incidents\?/, list([])]])
    render(<IncidentsPage />)
    expect(await screen.findByText(/No incidents yet/)).toBeTruthy()
  })

  it('lists incidents with a synthetic label and a link to each', async () => {
    installFetch([[/GET \/api\/scenarios/, { body: scenarios() }], [/GET \/api\/incidents\?/, list()]])
    render(<IncidentsPage />)
    const link = await screen.findByRole('link', { name: 'Latency on gpu-h07' })
    expect(link.getAttribute('href')).toBe('#/incidents/inc_1')
    expect(screen.getAllByText('synthetic').length).toBeGreaterThan(0)
    expect(screen.getByText('Inference slowdown', { selector: 'td' })).toBeTruthy()
  })

  it('shows an error with a retry when the list cannot be loaded', async () => {
    let fail = true
    installFetch([
      [/GET \/api\/scenarios/, { body: scenarios() }],
      [/GET \/api\/incidents\?/, () => (fail ? apiError(500, 'internal_error', 'database is down') : list())],
    ])
    render(<IncidentsPage />)
    expect((await screen.findByRole('alert')).textContent).toMatch(/database is down/)
    fail = false
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('link', { name: 'Latency on gpu-h07' })).toBeTruthy()
  })

  it('pre-fills the form from the first scenario and creates the incident through the API', async () => {
    const calls = installFetch([
      [/GET \/api\/scenarios/, { body: scenarios() }],
      [/GET \/api\/incidents\?/, list([])],
      [/POST \/api\/incidents$/, { status: 201, body: incident({ id: 'inc_new' }) }],
    ])
    render(<IncidentsPage />)
    const title = (await screen.findByLabelText('Title')) as HTMLInputElement
    expect(title.value).toBe('Inference latency rising on gpu-h07')
    expect((screen.getByLabelText(/gpu-h07/) as HTMLInputElement).checked).toBe(true)
    expect((screen.getByLabelText(/gpu-h08/) as HTMLInputElement).checked).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Create incident' }))
    await waitFor(() => expect(window.location.hash).toBe('#/incidents/inc_new'))
    expect(calls.find((c) => c.method === 'POST')!.body).toEqual({
      title: 'Inference latency rising on gpu-h07', description: 'p95 latency is up.',
      scenario_type: 'inference_slowdown', severity: 'high', affected_hosts: ['gpu-h07'],
    })
  })

  it('re-fills the form when another scenario is chosen', async () => {
    installFetch([[/GET \/api\/scenarios/, { body: scenarios() }], [/GET \/api\/incidents\?/, list([])]])
    render(<IncidentsPage />)
    fireEvent.change(await screen.findByLabelText('Scenario'), { target: { value: 'stale_telemetry' } })
    expect((screen.getByLabelText('Title') as HTMLInputElement).value).toBe('Slow responses on gpu-h21')
    expect(screen.getByLabelText(/gpu-h21/)).toBeTruthy()
    expect(screen.queryByLabelText(/gpu-h07/)).toBeNull()
  })

  it('shows the backend validation errors next to the form and stays on the page', async () => {
    installFetch([
      [/GET \/api\/scenarios/, { body: scenarios() }],
      [/GET \/api\/incidents\?/, list([])],
      [/POST \/api\/incidents$/, apiError(422, 'validation_error', 'Request validation failed', [{ field: 'affected_hosts', message: 'invalid host id(s)' }])],
    ])
    render(<IncidentsPage />)
    await screen.findByLabelText('Title')
    fireEvent.click(screen.getByRole('button', { name: 'Create incident' }))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/affected_hosts: invalid host id/)
    expect(window.location.hash).toBe('')
  })

  it('cannot submit without an affected host', async () => {
    installFetch([[/GET \/api\/scenarios/, { body: scenarios() }], [/GET \/api\/incidents\?/, list([])]])
    render(<IncidentsPage />)
    fireEvent.click(await screen.findByLabelText(/gpu-h07/))
    expect((screen.getByRole('button', { name: 'Create incident' }) as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('IncidentPage', () => {
  const base = [
    [/GET \/api\/incidents\/inc_1$/, { body: incident() }],
    [/GET \/api\/incidents\/inc_1\/runs$/, { body: [run({ id: 'run_old', status: 'ABSTAINED' })] }],
  ] as Array<[RegExp, { body: unknown }]>

  it('shows the incident, labels it synthetic, and lists earlier investigations', async () => {
    installFetch(base)
    render(<IncidentPage incidentId="inc_1" />)
    expect(await screen.findByRole('heading', { name: /Latency on gpu-h07/ })).toBeTruthy()
    expect(screen.getAllByText('synthetic').length).toBeGreaterThan(0)
    expect(await screen.findByRole('link', { name: 'run_old' })).toBeTruthy()
    expect(screen.getByText('Abstained')).toBeTruthy()
  })

  it('starts an investigation with a fresh idempotency key and opens the new run', async () => {
    vi.stubGlobal('crypto', { randomUUID: () => 'uuid-1' })
    const calls = installFetch([...base, [/POST \/api\/incidents\/inc_1\/runs$/, { status: 202, body: run({ id: 'run_new', status: 'CREATED' }) }]])
    render(<IncidentPage incidentId="inc_1" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Start investigation' }))
    await waitFor(() => expect(window.location.hash).toBe('#/runs/run_new'))
    expect(calls.find((c) => c.method === 'POST')!.headers['Idempotency-Key']).toBe('uuid-1')
  })

  it('does not navigate away when the backend says an investigation is already running', async () => {
    vi.stubGlobal('crypto', { randomUUID: () => 'uuid-2' })
    installFetch([...base, [/POST \/api\/incidents\/inc_1\/runs$/, { status: 200, body: run({ id: 'run_busy', status: 'RUNNING' }) }]])
    render(<IncidentPage incidentId="inc_1" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Start investigation' }))
    const note = await screen.findByText(/already in progress/)
    expect(within(note.closest('p') as HTMLElement).getByRole('link', { name: 'Open it' }).getAttribute('href')).toBe('#/runs/run_busy')
    expect(window.location.hash).toBe('')
  })

  it('shows the backend error if starting fails', async () => {
    vi.stubGlobal('crypto', { randomUUID: () => 'uuid-3' })
    installFetch([...base, [/POST \/api\/incidents\/inc_1\/runs$/, apiError(500, 'internal_error', 'could not start')]])
    render(<IncidentPage incidentId="inc_1" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Start investigation' }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/could not start/)
  })

  it('shows a clear message for an incident that does not exist', async () => {
    installFetch([[/incidents\/inc_x$/, apiError(404, 'not_found', 'nope')], [/runs$/, apiError(404, 'not_found', 'nope')]])
    render(<IncidentPage incidentId="inc_x" />)
    expect((await screen.findByRole('alert')).textContent).toMatch(/No incident with the ID/)
  })
})

describe('HistoryPage', () => {
  const summary = (id: string, status: 'COMPLETE' | 'FAILED') => ({ ...run({ id, status }), incident_title: `Incident for ${id}`, scenario_type: 'link_instability' as const })

  it('shows an empty state with a way forward', async () => {
    installFetch([[/GET \/api\/runs\?/, { body: { items: [], total: 0, limit: 15, offset: 0 } }]])
    render(<HistoryPage />)
    expect(await screen.findByText(/No investigations have been run yet/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Create an incident' })).toBeTruthy()
  })

  it('lists runs with status, incident and scenario, newest first as the server returns them', async () => {
    installFetch([[/GET \/api\/runs\?/, { body: { items: [summary('run_b', 'FAILED'), summary('run_a', 'COMPLETE')], total: 2, limit: 15, offset: 0 } }]])
    render(<HistoryPage />)
    const rows = within(await screen.findByRole('table')).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByText('Failed')).toBeTruthy()
    expect(within(rows[0]).getByRole('link', { name: 'Incident for run_b' })).toBeTruthy()
    expect(within(rows[1]).getByText('Link instability')).toBeTruthy()
  })

  it('pages through older runs', async () => {
    const calls = installFetch([[/GET \/api\/runs\?/, (c) => ({ body: { items: [summary(c.path.includes('offset=15') ? 'run_old' : 'run_new', 'COMPLETE')], total: 20, limit: 15, offset: 0 } })]])
    render(<HistoryPage />)
    await screen.findByRole('link', { name: 'run_new' })
    fireEvent.click(screen.getByRole('button', { name: 'Older' }))
    expect(await screen.findByRole('link', { name: 'run_old' })).toBeTruthy()
    expect(calls.some((c) => c.path.includes('offset=15'))).toBe(true)
  })

  it('shows an error with retry', async () => {
    installFetch([[/GET \/api\/runs\?/, apiError(500, 'internal_error', 'broken')]])
    render(<HistoryPage />)
    expect((await screen.findByRole('alert')).textContent).toMatch(/broken/)
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
  })
})

describe('App shell', () => {
  const routes: Array<[RegExp, { body: unknown }]> = [
    [/GET \/health/, { body: { status: 'ok', service: 'FabricOps', environment: 'local' } }],
    [/GET \/api\/scenarios/, { body: scenarios() }],
    [/GET \/api\/incidents\?/, list([])],
    [/GET \/api\/runs\?/, { body: { items: [], total: 0, limit: 15, offset: 0 } }],
  ]

  it('labels all data as synthetic on every page and navigates by URL', async () => {
    installFetch(routes)
    render(<App />)
    expect(screen.getByRole('note').textContent).toMatch(/All data shown is synthetic/)
    await screen.findByText(/No incidents yet/)
    window.location.hash = '#/history'
    expect(await screen.findByText(/Run history/, { selector: 'h2' })).toBeTruthy()
    expect(screen.getByRole('note').textContent).toMatch(/synthetic/)
    window.location.hash = '#/about'
    expect(await screen.findByText(/About FabricOps/)).toBeTruthy()
    expect(screen.getByRole('note')).toBeTruthy()
  })

  it('shows the backend health and marks the current page', async () => {
    installFetch(routes)
    render(<App />)
    expect(await screen.findByText(/Backend ok \(local\)/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Incidents' }).getAttribute('aria-current')).toBe('page')
  })

  it('says so plainly when the backend is down', async () => {
    vi.stubGlobal('fetch', async () => {
      throw new TypeError('Failed to fetch')
    })
    render(<App />)
    expect((await screen.findAllByRole('alert')).some((a) => /Backend unreachable/.test(a.textContent ?? ''))).toBe(true)
  })

  it('shows a not-found page for an unknown address', async () => {
    installFetch(routes)
    window.location.hash = '#/nowhere'
    render(<App />)
    expect(await screen.findByText(/There is no page at/)).toBeTruthy()
  })
})
