# Phase 10 --- Evaluation and Regression Tests

## Goal

Measure whether FabricOps behaves correctly, not merely whether its
answers sound convincing.

## Evaluation set

Create a small, curated set of cases: - Normal inference slowdown. -
Isolated network instability. - Stale telemetry. - Missing telemetry. -
Contradictory metrics. - Irrelevant documentation. - No relevant
documentation. - Unknown host. - Tool timeout. - Malicious instruction
in logs. - Fabricated evidence ID in model response. - Risky proposal. -
Changed proposal after approval.

Expected outcomes must remain outside the runtime model input.

## Metrics

Measure: - Required evidence retrieval success. - Citation ID
validity. - Claim support on a small reviewed sample. - Appropriate
abstention. - Correct affected-host scope. - Correct risk/approval gate
behavior. - Schema-valid response rate. - Workflow
success/failure/abstention counts. - Latency and token/cost usage when
available.

Do not present a tiny synthetic test set as statistically conclusive.

## Testing layers

1.  Unit tests: schemas, freshness, retrieval, policy.
2.  Integration tests: database, API, workflow.
3.  Mock LLM tests: deterministic CI.
4.  Small live-model smoke tests: optional, separately configured.
5.  Manual review: a small number of claim-support examples.

Large-scale human annotation is not required. A small reviewed benchmark
is still necessary to check whether claims are genuinely supported.

## AI coding prompt

"Implement only Phase 10. Create a versioned evaluation dataset and
automated test runner for the scenarios and failure cases. Keep expected
outcomes out of runtime context. Report counts and metrics with
denominators. Include deterministic tests for IDs, state, freshness and
policy. Add a small documented manual rubric for claim support. Do not
claim statistical significance."

## Acceptance

-   [x] Every case has a defined expected behavior.
-   [x] Critical safety tests run automatically.
-   [x] Stale telemetry abstention is tested.
-   [x] Host scope is tested.
-   [x] Fabricated IDs are rejected.
-   [x] Risky proposals are blocked or paused.
-   [x] Evaluation report includes sample size and limitations.
