import { describe, expect, it, vi } from 'vitest'
import { apiError, incident, installFetch, run } from '../test/fakeApi'
import { ApiError, api } from './client'

describe('api client', () => {
  it('turns the backend error envelope into an ApiError with code, message and field details', async () => {
    installFetch([[/POST \/api\/incidents$/, apiError(422, 'validation_error', 'Request validation failed', [{ field: 'title', message: 'too short' }])]])
    const err = await api
      .createIncident({ title: '', description: 'd', scenario_type: 'inference_slowdown', severity: 'high', affected_hosts: ['h'] })
      .catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    const e = err as ApiError
    expect([e.status, e.code, e.message]).toEqual([422, 'validation_error', 'Request validation failed'])
    expect(e.details).toEqual([{ field: 'title', message: 'too short' }])
  })

  it('falls back to a generic message when the error body is not JSON', async () => {
    vi.stubGlobal('fetch', async () => new Response('<html>Bad gateway</html>', { status: 502 }))
    const e = (await api.getRun('run_1').catch((x: unknown) => x)) as ApiError
    expect(e.status).toBe(502)
    expect(e.message).toMatch(/HTTP 502/)
  })

  it('reports an unreachable backend as a network_error', async () => {
    vi.stubGlobal('fetch', async () => {
      throw new TypeError('Failed to fetch')
    })
    const e = (await api.listRuns().catch((x: unknown) => x)) as ApiError
    expect(e.code).toBe('network_error')
    expect(e.message).toMatch(/Cannot reach the FabricOps backend/)
  })

  it('treats 404 as "nothing there yet" for the report and the proposal, but not other failures', async () => {
    installFetch([
      [/\/report$/, apiError(404, 'not_found', 'none')],
      [/\/proposal$/, apiError(500, 'internal_error', 'boom')],
    ])
    expect(await api.getReport('run_1')).toBeNull()
    await expect(api.getProposal('run_1')).rejects.toMatchObject({ status: 500 })
  })

  it('starts a run with an Idempotency-Key and reports whether a new run was created', async () => {
    const calls = installFetch([
      [/POST \/api\/incidents\/inc_1\/runs$/, (c) => (c.headers['Idempotency-Key'] === 'k-new' ? { status: 202, body: run({ status: 'CREATED' }) } : { status: 200, body: run() })],
    ])
    expect((await api.startRun('inc_1', 'k-new')).created).toBe(true)
    expect((await api.startRun('inc_1', 'k-old')).created).toBe(false)
    expect(calls[0].headers['Idempotency-Key']).toBe('k-new')
  })

  it('sends the demo reviewer as a header and the proposal hash in the body', async () => {
    const calls = installFetch([[/decision$/, { status: 201, body: {} }]])
    await api.decide('prop_1', { decision: 'rejected', proposal_hash: 'f'.repeat(64), reason: 'no' }, 'alice')
    expect(calls[0].headers['X-Demo-Reviewer']).toBe('alice')
    expect(calls[0].body).toEqual({ decision: 'rejected', proposal_hash: 'f'.repeat(64), reason: 'no' })
  })

  it('encodes IDs that contain colons or slashes', async () => {
    const calls = installFetch([[/./, { body: {} }]])
    await api.getChunk('RB-KV-001:2.0:symptoms:0')
    await api.getIncident('a/b')
    expect(calls[0].path).toBe('/api/documents/chunks/RB-KV-001%3A2.0%3Asymptoms%3A0')
    expect(calls[1].path).toBe('/api/incidents/a%2Fb')
  })

  it('reads incidents with paging parameters', async () => {
    const calls = installFetch([[/./, { body: { items: [incident()], total: 1, limit: 5, offset: 10 } }]])
    const page = await api.listIncidents(5, 10)
    expect(calls[0].path).toBe('/api/incidents?limit=5&offset=10')
    expect(page.items[0].id).toBe('inc_1')
  })
})
