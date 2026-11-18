# Phase 07 --- Controlled Investigation Workflow

## Goal

Orchestrate the investigation as a bounded sequence, not an unrestricted
agent loop.

## Workflow

1.  Load incident.
2.  Validate host scope.
3.  Check freshness.
4.  Collect metrics/logs/config through typed tools.
5.  Persist evidence.
6.  Retrieve approved documentation.
7.  Call investigator once with a bounded evidence package.
8.  Validate model output and referenced IDs.
9.  Apply policy.
10. Persist report and run events.
11. Return final run status.

## Limits

Set explicit limits for: - Number of tool calls. - Maximum host count. -
Time range. - Maximum evidence records. - Maximum document chunks. - LLM
timeout and bounded retries. - Maximum output size. - Maximum run
duration.

## Reliability

Persist stage events. A client refresh must read the existing run; it
must not start the investigation again. Use idempotency keys or run IDs
to avoid duplicate starts.

## AI coding prompt

"Implement only Phase 07. Create a deterministic, bounded workflow that
executes the documented stages. Persist ordered events and state
transitions. Add limits, timeout handling and idempotent start behavior.
A failed stage must not report success. Do not create multiple agents or
unrestricted recursive tool calling."

## Acceptance

-   [ ] Normal workflow reaches a valid terminal state.
-   [ ] Stale/missing data reaches ABSTAINED.
-   [ ] Failures reach FAILED with safe error details.
-   [ ] Limits stop excessive work.
-   [ ] Duplicate start requests do not create duplicate runs.
-   [ ] Events replay after refresh/reconnect.
-   [ ] No automatic remediation exists.
