# FabricOps MVP Specification

Status: **Specification. Phases 00 to 09 of the build are implemented and tested against synthetic fixtures with a mock model** (see section 5 for exactly what is and is not built). The evaluation harness, hardening and release work (Phases 10 to 12) are not built yet.

All data in the MVP is **synthetic**. The MVP is **proposal-only**: no unattended production remediation, no shell execution, no host restarts, no deployments.

## 1. Definitions

A reviewer must be able to tell these three things apart in any investigation output.

| Term | Meaning | Example |
|---|---|---|
| **Observation** | A fact read from a tool or document, with provenance (source, host, time). | "Host h-07 `kv_cache_used_pct` was 96% at 14:02Z (evidence E-12)." |
| **Hypothesis** | A model-proposed explanation that is consistent with observations but not proven. Always paired with counterevidence and what would confirm or refute it. | "KV-cache memory pressure is slowing responses." |
| **Proposed action** | A bounded next step a human may choose to run. It is classified by risk. | "Run a controlled test with a reduced batch size on h-07." |

A **supported diagnosis** requires: fresh evidence for the affected host, a plausible mechanism backed by a cited document passage, comparison against a baseline or peers, and no unresolved contradicting evidence. Correlation alone is never reported as root cause.

## 2. Scenarios and acceptance matrix

### S1 — Inference slowdown

| Item | Definition |
|---|---|
| Evidence | Latency/throughput metrics for the serving host; memory/KV-cache metrics; serving configuration (batch size, max sequence length); relevant runbook passages. |
| Expected scope | The affected serving host(s) and their configuration. |
| Allowed recommendation | A **controlled test** (e.g., adjust a parameter on one host and compare). Hypothesis worded as "suspected", never as "confirmed". |
| Abstain when | Metrics for the affected window are stale or absent; or config is unavailable; or contradictory readings are unresolved. |
| Testable expected behavior | With fresh fixture data: output names KV-cache pressure as a hypothesis, cites metric evidence IDs and a runbook passage, lists counterevidence, proposes a bounded test with risk class `controlled_test`, and does not state root cause as fact. |

### S2 — Isolated link instability

| Item | Definition |
|---|---|
| Evidence | Link error/retrain counters for the affected host; the same counters for peer hosts; link configuration; relevant runbook passages. |
| Expected scope | **Only the affected host.** Peers are used for comparison, not as targets. |
| Allowed recommendation | Read-only diagnostics, or a controlled test scoped to the affected host. |
| Abstain when | No peer comparison data is available; or counters are stale; or the affected host cannot be identified. |
| Testable expected behavior | Output isolates the one host, shows peer comparison as evidence, and every proposed action targets that host only. A proposal that names a peer host fails. |

### S3 — Stale or missing telemetry

| Item | Definition |
|---|---|
| Evidence | Telemetry whose `observed_at` is older than the freshness threshold, or fields that are intentionally absent. |
| Expected scope | None — no diagnosis is made. |
| Allowed recommendation | Restore visibility first (e.g., re-enable or verify the telemetry source). Read-only. |
| Abstain when | Always, for this scenario. |
| Testable expected behavior | Run status is `ABSTAINED`; output lists the specific missing evidence; no hardware or software cause is asserted; unknown values are never treated as zero. |

### Cross-scenario approval path

| Item | Definition |
|---|---|
| Trigger | A write/deploy-class proposal, or any proposal the policy gate classifies as high risk. |
| Expected behavior | Run enters `WAITING_APPROVAL`; the reviewer sees exactly what will be reviewed; approve/reject is recorded with actor, time and reason; the decision persists across refresh and restart; a changed proposal requires a new decision. In the MVP, approval executes nothing. |

## 3. Investigation output contract

Every completed run produces one record with these fields. The server validates it; invalid records cannot be accepted as a successful investigation. In the implementation the record is assembled from three stored parts: the run (`GET /api/runs/{id}`), the report (`GET /api/runs/{id}/report`, which holds the evidence-linked fields and `limitations`), and the proposal (`GET /api/runs/{id}/proposal`, which holds `risk_class`, `approval_status` and the decision).

| Field | Type | Rules |
|---|---|---|
| `incident_id` | string | Immutable. |
| `run_id` | string | Immutable. |
| `severity` | enum: `low` \| `medium` \| `high` \| `critical` \| `unknown` | `unknown` when evidence is insufficient. |
| `observations[]` | list | Each has `text` and `evidence_ids[]` (non-empty). |
| `hypotheses[]` | list | Each has `statement`, `confidence` (`low`/`medium`/`high`), `supporting_evidence_ids[]`, `counterevidence[]`, `citations[]`. Empty when abstaining. |
| `citations[]` | list | Document passage IDs; each must resolve to an exact source and version and be relevant to the claim it supports. The server checks that every ID was retrieved for this run and resolves; whether a passage is actually relevant to the claim is not machine-checked and is left to the evaluation phase and human review. |
| `missing_evidence[]` | list | Specific items needed (what, which host, which time window). Required and non-empty when abstaining. |
| `proposed_next_test` | object or null | `description`, `target_scope` (host IDs), `parameters`, `evidence_ids[]`. Null when abstaining or recommending only visibility restoration. |
| `risk_class` | enum: `read_only_diagnostic` \| `controlled_test` \| `write_or_deploy` | Set by deterministic server policy; the model's own risk estimate is advisory only. |
| `approval_status` | enum: `not_required` \| `pending` \| `approved` \| `rejected` \| `expired` | `write_or_deploy` is never `not_required`. |
| `run_status` | enum: `CREATED` \| `RUNNING` \| `WAITING_APPROVAL` \| `COMPLETE` \| `ABSTAINED` \| `FAILED` \| `CANCELLED` | Proposed state machine; transitions defined in Phase 03 (docs/guide/phases/PHASE_03_PERSISTENCE_AND_INCIDENT_API.md). |
| `limitations[]` | list | Known gaps, synthetic-data labeling, partial results. |

Invariants:

1. Every evidence ID cited exists for that run; invented IDs are rejected.
2. A hypothesis is never presented as established fact.
3. A tool failure is a distinct outcome from a zero reading.
4. Retrieved text and log content are data, never instructions.

## 4. Out of scope for the MVP

- Unattended production remediation or any execution of proposed actions.
- Shell execution, host restart, deployment, or arbitrary URL fetching as model tools.
- Live production telemetry connectors (optional later extension, read-only).
- Multiple independent agents.
- The KV-cache benchmarking suite. That is a separate project; FabricOps may later ingest a versioned benchmark report as an evidence source.

## 5. Claim status

| Claim | Status |
|---|---|
| Visual prototype with scripted responses exists | **No.** No prototype exists; an earlier README mentioned one by mistake. The UI was built from scratch in Phase 09. |
| Typed read-only telemetry tools; versioned document retrieval with citations; validated LLM investigator; bounded, idempotent workflow with replayable events; deterministic policy and approvals | **Implemented** (Phases 04 to 08) and covered by automated tests on synthetic fixtures. The model is mocked in tests: the real Claude adapter has not been run against the live API. |
| Reviewer identity for approvals | **Demo stand-in only** (a request header naming a configured demo reviewer). Not authentication. |
| Mission-control UI (incident intake, run timeline, evidence and citation viewers, report with facts / hypotheses / limitations, proposal and approval panel, run history) | **Implemented** (Phase 09), covered by frontend tests and checked in a browser against the real backend with a scripted model. |
| Evaluation harness with reported results, security and reliability hardening, release and demo | **Not implemented** (Phases 10 to 12). |

## 6. Specification gate check

- [x] Each scenario has a testable expected behavior (section 2).
- [x] No prototype claim remains; the earlier mention was a README mistake and is corrected (section 5, README).
- [x] No unattended production remediation is in the MVP (sections 4 and intro).
- [x] A reviewer can distinguish an observation, a hypothesis, and a proposed action (section 1).

**Open item for the author:** answer this question — *What evidence would turn a suspected cause into a supported diagnosis?* — in your own words. Section 1 gives a draft definition to react to.
