# Phase 04 --- Typed Read-Only Telemetry Tools

## Goal

Give the investigation workflow a small, safe set of tools to retrieve
fixture data.

## Tools

Implement functions with validated inputs and outputs: -
`read_metrics(host_id, time_window)` -
`read_logs(host_id, time_range, limit)` - `read_config(host_id)`

Use fixture adapters only. Do not connect to real infrastructure.

## Tool contract

Every result should include: - Tool name - Validated parameters - Host
scope - Collection time - Evidence IDs - Success/error status -
Source/provenance - Observation timestamp(s)

Differentiate: - Valid reading of zero - No data found - Stale data -
Tool timeout/failure - Permission/host scope rejection - Malformed
source data

Bound host IDs, time windows, result counts, and response sizes. Do not
expose shell, arbitrary URLs, or unrestricted file access as tools.

## AI coding prompt

"Implement only Phase 04. Build typed, read-only telemetry tools over
the synthetic fixture adapter. Validate host IDs, time windows and
result limits. Persist evidence with provenance and observed/ingested
timestamps. Ensure tool failure is not represented as a zero reading.
Add tests for unknown host, stale data, timeout simulation, malformed
fixture and scope boundaries. No shell execution and no real
infrastructure connector."

## Acceptance

-   [ ] All tools are read-only.
-   [ ] Inputs and outputs are schema validated.
-   [ ] Unknown hosts and excessive ranges are rejected.
-   [ ] Evidence IDs are stable within a run.
-   [ ] Tool failures are distinct from valid empty/zero readings.
-   [ ] Tests cover expected and failure paths.

## Suggested commit

`feat: add scoped read-only telemetry tools`
