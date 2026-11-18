import type { ApprovalStatus, RiskClass, RunEvent, RunStatus, ScenarioType } from './api/types'

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toISOString().replace('T', ' ').replace(/\.\d+Z$/, 'Z')
}

export function formatDuration(startIso: string, endIso: string | null): string {
  if (!endIso) return '—'
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime()
  if (!Number.isFinite(ms) || ms < 0) return '—'
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`
}

export const shortHash = (hash: string): string => hash.slice(0, 12)

export const SCENARIO_LABELS: Record<ScenarioType, string> = {
  inference_slowdown: 'Inference slowdown',
  link_instability: 'Link instability',
  stale_telemetry: 'Stale or missing telemetry',
}

export const RISK_LABELS: Record<RiskClass, string> = {
  read_only_diagnostic: 'Read-only diagnostic',
  controlled_test: 'Controlled test',
  write_or_deploy: 'Write or deploy (never executed)',
}

export const APPROVAL_LABELS: Record<ApprovalStatus, string> = {
  not_required: 'No approval needed',
  pending: 'Waiting for a decision',
  approved: 'Approved',
  rejected: 'Rejected',
  expired: 'Expired',
}

export interface StatusInfo {
  label: string
  tone: 'progress' | 'wait' | 'good' | 'neutral' | 'bad'
}

export const STATUS_INFO: Record<RunStatus, StatusInfo> = {
  CREATED: { label: 'Queued', tone: 'progress' },
  RUNNING: { label: 'Running', tone: 'progress' },
  WAITING_APPROVAL: { label: 'Waiting for approval', tone: 'wait' },
  COMPLETE: { label: 'Complete', tone: 'good' },
  ABSTAINED: { label: 'Abstained', tone: 'neutral' },
  FAILED: { label: 'Failed', tone: 'bad' },
  CANCELLED: { label: 'Cancelled', tone: 'bad' },
}

/** The backend's scripted demo model (FABRICOPS_LLM_PROVIDER=demo). It is a fixed script, not an AI. */
export const isScriptedDemo = (modelId: string | null): boolean => !!modelId && modelId.startsWith('scripted-demo')

export const isActive = (s: RunStatus): boolean => s === 'CREATED' || s === 'RUNNING'

export const STAGE_LABELS: Record<string, string> = {
  load_incident: 'Load incident',
  validate_scope: 'Validate host scope and limits',
  collect_telemetry: 'Collect telemetry (read-only tools)',
  check_freshness: 'Check freshness',
  persist_evidence: 'Store evidence',
  retrieve_docs: 'Retrieve documentation',
  investigate: 'Investigate',
  apply_policy: 'Apply approval policy',
  persist_report: 'Store report',
}

export interface StageRow {
  stage: string
  state: 'started' | 'completed' | 'failed'
  time: string
  detail?: string
}

function parseDetail(detail: string | null): Record<string, unknown> {
  if (!detail) return {}
  try {
    const v: unknown = JSON.parse(detail)
    return v && typeof v === 'object' ? (v as Record<string, unknown>) : {}
  } catch {
    return {}
  }
}

/** Fold the raw event stream into one row per stage, in the order stages began. */
export function foldStages(events: RunEvent[]): StageRow[] {
  const rows: StageRow[] = []
  for (const e of events) {
    if (!e.event_type.startsWith('stage_')) continue
    const d = parseDetail(e.detail)
    const stage = typeof d.stage === 'string' ? d.stage : undefined
    if (!stage) continue
    const state = e.event_type === 'stage_started' ? 'started' : e.event_type === 'stage_completed' ? 'completed' : 'failed'
    const existing = rows.find((r) => r.stage === stage)
    const message = typeof d.message === 'string' ? d.message : undefined
    if (existing) {
      existing.state = state
      existing.time = e.created_at
      if (message) existing.detail = message
    } else {
      rows.push({ stage, state, time: e.created_at, detail: message })
    }
  }
  return rows
}

/** The reason a run failed or was cancelled, taken from its last stage_failed event. */
export function failureReason(events: RunEvent[]): { code: string; message: string } | null {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].event_type !== 'stage_failed') continue
    const d = parseDetail(events[i].detail)
    return {
      code: typeof d.code === 'string' ? d.code : 'unknown',
      message: typeof d.message === 'string' ? d.message : 'No further detail was recorded.',
    }
  }
  return null
}
