import { vi } from 'vitest'
import type {
  ApprovalDecision,
  DocumentChunk,
  EvidenceRecord,
  Incident,
  Proposal,
  ProposalView,
  Report,
  Run,
  RunEvent,
  ScenarioInfo,
} from '../api/types'

export interface Call {
  method: string
  path: string
  headers: Record<string, string>
  body: unknown
}

export interface Reply {
  status?: number
  body?: unknown
}

export type Handler = (call: Call) => Reply | Promise<Reply>

/**
 * Replace fetch with a fake that answers API-shaped JSON. Routes are matched in order on
 * "METHOD /path?query". Anything unmatched is answered with 599 so a test notices.
 */
export function installFetch(routes: Array<[RegExp, Handler | Reply]>): Call[] {
  const calls: Call[] = []
  vi.stubGlobal('fetch', async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input))
    const call: Call = {
      method: (init.method ?? 'GET').toUpperCase(),
      path: url.pathname + url.search,
      headers: Object.fromEntries(Object.entries((init.headers ?? {}) as Record<string, string>)),
      body: typeof init.body === 'string' ? JSON.parse(init.body) : undefined,
    }
    calls.push(call)
    const key = `${call.method} ${call.path}`
    const route = routes.find(([re]) => re.test(key))
    if (!route) return new Response(JSON.stringify({ error: { code: 'unmatched', message: key, details: [] } }), { status: 599 })
    const reply = typeof route[1] === 'function' ? await route[1](call) : route[1]
    return new Response(JSON.stringify(reply.body ?? {}), { status: reply.status ?? 200, headers: { 'Content-Type': 'application/json' } })
  })
  return calls
}

export const apiError = (status: number, code: string, message: string, details: { field: string; message: string }[] = []): Reply => ({
  status,
  body: { error: { code, message, details } },
})

// ---- builders ----

export const incident = (over: Partial<Incident> = {}): Incident => ({
  id: 'inc_1', title: 'Latency on gpu-h07', description: 'p95 latency rising', scenario_type: 'inference_slowdown',
  severity: 'high', affected_hosts: ['gpu-h07'], created_at: '2026-03-10T14:00:00Z', synthetic: true, ...over,
})

export const run = (over: Partial<Run> = {}): Run => ({
  id: 'run_1', incident_id: 'inc_1', status: 'COMPLETE', started_at: '2026-03-10T14:00:00Z',
  finished_at: '2026-03-10T14:00:02Z', model_id: 'mock-model-1', prompt_version: 'investigator-v1', error_code: null, ...over,
})

export const evidence = (over: Partial<EvidenceRecord> = {}): EvidenceRecord => ({
  id: 'ev_1', run_id: 'run_1', source_type: 'metric', host_id: 'gpu-h07', tool_name: 'read_metrics',
  observed_at: '2026-03-10T14:00:00Z', ingested_at: '2026-03-10T14:00:30Z',
  payload: { metric: 'kv_cache_used_pct', unit: 'percent', source: 'dcgm-synthetic', latest_value: 96 }, synthetic: true, ...over,
})

export const report = (over: Partial<Report> = {}): Report => ({
  run_id: 'run_1', severity: 'high', insufficient_evidence: false,
  observations: [{ text: 'KV-cache use on gpu-h07 reached 96%.', evidence_ids: ['ev_1'] }],
  hypotheses: [{
    statement: 'KV-cache pressure is a suspected contributor.', confidence: 'high', supporting_evidence_ids: ['ev_1'],
    counterevidence: ['Two memory sources disagree.'], citations: ['RB-KV-001:2.0:symptoms:0'],
  }],
  citations: ['RB-KV-001:2.0:symptoms:0'], missing_evidence: [], proposed_next_test: null,
  limitations: ['All data is synthetic.'], ...over,
})

export const chunk = (over: Partial<DocumentChunk> = {}): DocumentChunk => ({
  id: 'RB-KV-001:2.0:symptoms:0', document_id: 'RB-KV-001', version: '2.0', title: 'Runbook: KV-cache memory pressure',
  section: 'Symptoms', text: 'Latency rises on one host while peers stay flat.', source: 'data/docs/rb-kv-001_v2.0.md',
  synthetic_or_official: 'synthetic', date: '2026-02-01', status: 'current', ...over,
})

export const proposal = (over: Partial<Proposal> = {}): Proposal => ({
  id: 'prop_1', run_id: 'run_1', version: 1, description: 'Halve batch_size on gpu-h07 and compare latency.',
  parameters: {}, target_scope: ['gpu-h07'], risk_class: 'controlled_test', approval_status: 'pending',
  proposal_hash: 'a'.repeat(64), expires_at: '2026-03-11T14:00:00Z', evidence_ids: ['ev_1'],
  policy_reasons: ['wording indicates an experiment'], ...over,
})

export const decision = (over: Partial<ApprovalDecision> = {}): ApprovalDecision => ({
  id: 'dec_1', proposal_id: 'prop_1', proposal_hash: 'a'.repeat(64), actor: 'demo-reviewer', decision: 'approved',
  reason: 'Looks safe.', created_at: '2026-03-10T15:00:00Z', ...over,
})

export const proposalView = (p: Partial<Proposal> = {}, d: ApprovalDecision | null = null): ProposalView => ({
  proposal: proposal(p), decision: d, execution_enabled: false,
})

export const event = (seq: number, type: string, detail: Record<string, unknown> | null = null, over: Partial<RunEvent> = {}): RunEvent => ({
  seq, event_type: type, from_status: null, to_status: null, detail: detail ? JSON.stringify(detail) : null,
  created_at: '2026-03-10T14:00:01Z', ...over,
})

export const stageEvents = (names: string[], startSeq = 1): RunEvent[] =>
  names.flatMap((stage, i) => [
    event(startSeq + i * 2, 'stage_started', { stage }),
    event(startSeq + i * 2 + 1, 'stage_completed', { stage }),
  ])

export const scenarios = (): ScenarioInfo[] => [
  {
    scenario_type: 'inference_slowdown', title: 'Inference latency rising on gpu-h07', description: 'p95 latency is up.',
    severity: 'high', synthetic: true, suggested_affected_hosts: ['gpu-h07'],
    hosts: [{ id: 'gpu-h07', role: 'gpu_inference', synthetic: true }, { id: 'gpu-h08', role: 'gpu_inference', synthetic: true }],
  },
  {
    scenario_type: 'stale_telemetry', title: 'Slow responses on gpu-h21', description: 'No recent data.',
    severity: 'unknown', synthetic: true, suggested_affected_hosts: ['gpu-h21'],
    hosts: [{ id: 'gpu-h21', role: 'gpu_inference', synthetic: true }],
  },
]
