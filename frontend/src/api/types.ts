// Shapes returned by the FabricOps backend. Kept in step with backend/app/schemas.

export type RunStatus =
  | 'CREATED'
  | 'RUNNING'
  | 'WAITING_APPROVAL'
  | 'COMPLETE'
  | 'ABSTAINED'
  | 'FAILED'
  | 'CANCELLED'

export type ScenarioType = 'inference_slowdown' | 'link_instability' | 'stale_telemetry'
export type Severity = 'low' | 'medium' | 'high' | 'critical' | 'unknown'
export type RiskClass = 'read_only_diagnostic' | 'controlled_test' | 'write_or_deploy'
export type ApprovalStatus = 'not_required' | 'pending' | 'approved' | 'rejected' | 'expired'

export interface Incident {
  id: string
  title: string
  description: string
  scenario_type: ScenarioType
  severity: Severity
  affected_hosts: string[]
  created_at: string
  synthetic: boolean
}

export interface IncidentList {
  items: Incident[]
  total: number
  limit: number
  offset: number
}

export interface NewIncident {
  title: string
  description: string
  scenario_type: ScenarioType
  severity: Severity
  affected_hosts: string[]
}

export interface ScenarioInfo {
  scenario_type: ScenarioType
  title: string
  description: string
  severity: Severity
  hosts: { id: string; role: string; synthetic: boolean }[]
  suggested_affected_hosts: string[]
  synthetic: boolean
}

export interface Run {
  id: string
  incident_id: string
  status: RunStatus
  started_at: string
  finished_at: string | null
  model_id: string | null
  prompt_version: string | null
  error_code: string | null
}

export interface RunSummary extends Run {
  incident_title: string
  scenario_type: ScenarioType
}

export interface RunList {
  items: RunSummary[]
  total: number
  limit: number
  offset: number
}

export interface RunEvent {
  seq: number
  event_type: string
  from_status: string | null
  to_status: string | null
  detail: string | null
  created_at: string
}

export interface EventsResponse {
  run_id: string
  events: RunEvent[]
  last_seq: number
}

export interface EvidenceRecord {
  id: string
  run_id: string
  source_type: 'metric' | 'log' | 'config'
  host_id: string
  tool_name: string
  observed_at: string
  ingested_at: string
  payload: Record<string, unknown>
  synthetic: boolean
}

export interface DocumentChunk {
  id: string
  document_id: string
  version: string
  title: string
  section: string
  text: string
  source: string
  synthetic_or_official: 'synthetic' | 'official'
  date: string | null
  status: 'current' | 'superseded'
}

export interface Observation {
  text: string
  evidence_ids: string[]
}

export interface Hypothesis {
  statement: string
  confidence: 'low' | 'medium' | 'high'
  supporting_evidence_ids: string[]
  counterevidence: string[]
  citations: string[]
}

export interface ProposedTest {
  description: string
  target_scope: string[]
  parameters: Record<string, string | number | boolean>
  evidence_ids: string[]
}

export interface Report {
  run_id: string
  severity: Severity
  insufficient_evidence: boolean
  observations: Observation[]
  hypotheses: Hypothesis[]
  citations: string[]
  missing_evidence: string[]
  proposed_next_test: ProposedTest | null
  limitations: string[]
}

export interface Proposal {
  id: string
  run_id: string
  version: number
  description: string
  parameters: Record<string, string | number | boolean>
  target_scope: string[]
  risk_class: RiskClass
  approval_status: ApprovalStatus
  proposal_hash: string
  expires_at: string | null
  evidence_ids: string[]
  policy_reasons: string[]
}

export interface ApprovalDecision {
  id: string
  proposal_id: string
  proposal_hash: string
  actor: string
  decision: 'approved' | 'rejected'
  reason: string
  created_at: string
}

export interface ProposalView {
  proposal: Proposal
  decision: ApprovalDecision | null
  execution_enabled: false
}

export interface DecisionRequest {
  decision: 'approved' | 'rejected'
  proposal_hash: string
  reason: string
}
