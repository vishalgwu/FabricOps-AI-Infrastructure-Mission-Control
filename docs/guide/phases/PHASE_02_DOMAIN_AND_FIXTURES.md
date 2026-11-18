# Phase 02 --- Domain Schemas and Synthetic Incident Fixtures

## Goal

Define the data contract before building tools or connecting an LLM.

## Required schemas

Create validated models for: - Incident - Host - MetricSample -
LogRecord - HostConfiguration - EvidenceRecord - DocumentChunk -
Hypothesis - InvestigationReport - Proposal - ApprovalDecision - Run and
RunStatus

## Data requirements

-   Use explicit units (milliseconds, percent, bytes, requests/second).
-   Store timestamps in UTC ISO 8601.
-   Keep `observed_at` separate from `ingested_at`.
-   Preserve host ID and source.
-   Unknown values remain null/unknown; never silently convert missing
    values to zero.
-   Mark all demo fixtures `synthetic: true`.

## Three fixtures

1.  Inference slowdown: affected GPU host and healthy comparison
    host(s).
2.  Isolated network instability: one affected host and healthy peers.
3.  Stale/missing telemetry: old timestamps, absent fields, or missing
    source records.

Include edge cases: - Empty evidence. - Contradictory readings. -
Invalid units. - Unknown host. - Missing timestamp. - Logs containing
malicious instruction-like text.

## Evaluation answer key

Store expected outcomes in a separate evaluation directory. Do not load
the answer key into the agent context.

## AI coding prompt

"Implement only Phase 02. Create Pydantic domain schemas and clearly
synthetic JSON fixtures for the three scenarios. Add validation tests
for missing fields, invalid units, timestamps, unknown hosts, and absent
data. Keep expected outcomes separate from runtime fixture data. Do not
implement the LLM or UI features."

## Acceptance

-   [x] All three fixtures load through validation.
-   [x] Invalid data is rejected with useful errors.
-   [x] Units and timestamps are explicit.
-   [x] Synthetic provenance is visible.
-   [x] Evaluation answer key is separate.
-   [x] Tests cover malformed and missing data.

## Suggested commit

`feat: define incident schemas and synthetic fixtures`
