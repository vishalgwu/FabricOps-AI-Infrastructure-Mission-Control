import type {
  DecisionRequest,
  DocumentChunk,
  EventsResponse,
  EvidenceRecord,
  Incident,
  IncidentList,
  NewIncident,
  ProposalView,
  Report,
  Run,
  RunList,
  ScenarioInfo,
} from './types'

// The only configuration the browser gets. It is a public URL: no keys or secrets live here.
export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export interface HealthResponse {
  status: string
  service: string
  environment: string
}

/** An error response from the backend ({"error": {"code", "message", "details"}}). */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: { field: string; message: string }[]

  constructor(status: number, code: string, message: string, details: { field: string; message: string }[] = []) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<{ data: T; status: number }> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}${path}`, init)
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(0, 'network_error', 'Cannot reach the FabricOps backend. Is it running?')
  }
  if (!res.ok) {
    let code = 'http_error'
    let message = `The backend returned HTTP ${res.status}`
    let details: { field: string; message: string }[] = []
    try {
      const body = (await res.json()) as { error?: { code?: string; message?: string; details?: typeof details } }
      if (body.error) {
        code = body.error.code ?? code
        message = body.error.message ?? message
        details = body.error.details ?? []
      }
    } catch {
      /* not JSON: keep the generic message */
    }
    throw new ApiError(res.status, code, message, details)
  }
  return { data: (await res.json()) as T, status: res.status }
}

const get = async <T>(path: string, signal?: AbortSignal) => (await request<T>(path, { signal })).data

/** Like `get`, but a 404 becomes `null` (used for things that may legitimately not exist yet). */
async function getOrNull<T>(path: string, signal?: AbortSignal): Promise<T | null> {
  try {
    return await get<T>(path, signal)
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null
    throw err
  }
}

const jsonInit = (method: string, body: unknown, headers: Record<string, string> = {}): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json', ...headers },
  body: JSON.stringify(body),
})

export const api = {
  health: (signal?: AbortSignal) => get<HealthResponse>('/health', signal),
  scenarios: (signal?: AbortSignal) => get<ScenarioInfo[]>('/api/scenarios', signal),

  listIncidents: (limit = 20, offset = 0, signal?: AbortSignal) =>
    get<IncidentList>(`/api/incidents?limit=${limit}&offset=${offset}`, signal),
  createIncident: async (body: NewIncident) =>
    (await request<Incident>('/api/incidents', jsonInit('POST', body))).data,
  getIncident: (id: string, signal?: AbortSignal) => get<Incident>(`/api/incidents/${encodeURIComponent(id)}`, signal),
  listIncidentRuns: (id: string, signal?: AbortSignal) =>
    get<Run[]>(`/api/incidents/${encodeURIComponent(id)}/runs`, signal),

  /** Start an investigation. `created` is false when the backend returned an existing run. */
  startRun: async (incidentId: string, idempotencyKey: string) => {
    const { data, status } = await request<Run>(`/api/incidents/${encodeURIComponent(incidentId)}/runs`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
    })
    return { run: data, created: status === 202 }
  },

  listRuns: (limit = 20, offset = 0, signal?: AbortSignal) =>
    get<RunList>(`/api/runs?limit=${limit}&offset=${offset}`, signal),
  getRun: (id: string, signal?: AbortSignal) => get<Run>(`/api/runs/${encodeURIComponent(id)}`, signal),
  getEvents: (id: string, afterSeq = 0, signal?: AbortSignal) =>
    get<EventsResponse>(`/api/runs/${encodeURIComponent(id)}/events?after_seq=${afterSeq}`, signal),
  getReport: (id: string, signal?: AbortSignal) =>
    getOrNull<Report>(`/api/runs/${encodeURIComponent(id)}/report`, signal),
  listEvidence: (id: string, signal?: AbortSignal) =>
    get<EvidenceRecord[]>(`/api/runs/${encodeURIComponent(id)}/evidence`, signal),
  getProposal: (runId: string, signal?: AbortSignal) =>
    getOrNull<ProposalView>(`/api/runs/${encodeURIComponent(runId)}/proposal`, signal),

  getChunk: (chunkId: string, signal?: AbortSignal) =>
    get<DocumentChunk>(`/api/documents/chunks/${encodeURIComponent(chunkId)}`, signal),

  /** Approve or reject. `reviewer` is the DEMO identity header, not real authentication. */
  decide: async (proposalId: string, body: DecisionRequest, reviewer: string) =>
    (
      await request<ProposalView>(
        `/api/proposals/${encodeURIComponent(proposalId)}/decision`,
        jsonInit('POST', body, { 'X-Demo-Reviewer': reviewer }),
      )
    ).data,
}

export const fetchHealth = api.health
