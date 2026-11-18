# Phase 06 --- LLM Investigator

## Goal

Use an LLM to interpret validated evidence and retrieved documentation
without allowing it to invent facts or control permissions.

## Provider abstraction

Create a small interface such as: -
`generate_investigation(input) -> structured response`

Keep API-specific SDK usage inside one adapter. Read the current
provider documentation and use a model available to the developer. Never
hardcode secrets.

## Model input

Include: - Incident description and allowed host scope. -
Freshness-checked evidence. - Retrieved document chunks. - Strict output
schema. - Instructions to distinguish observations from hypotheses. -
Instructions to disclose missing/contradictory evidence. - Instructions
that logs and documents are data, not commands.

Do not include evaluation answer keys.

## Structured output

Require fields: - `observations[]`: statement + evidence IDs -
`hypotheses[]`: statement + supporting IDs + opposing IDs +
uncertainty - `missing_evidence[]` - `next_test`: description + target
scope + risk class - `abstain`: boolean + reason - `limitations[]` -
`document_citations[]`

Do not request or expose hidden chain-of-thought. Ask for concise
conclusions and evidence.

## Server validation

-   Parse against Pydantic schema.
-   Reject unknown evidence IDs and document chunk IDs.
-   Reject out-of-scope hosts.
-   Reject malformed or unsupported action proposals.
-   Retry only bounded transient failures.
-   Record model ID, prompt version, latency and usage when available.

## AI coding prompt

"Implement only Phase 06. Add an LLM provider interface and one provider
adapter configured through backend environment variables. Define a
strict Pydantic investigation response schema. Build the investigator
prompt using only validated incident evidence and retrieved chunks.
Validate every referenced ID against the current run. Add mock-provider
tests so normal CI does not require an API key. Add abstention behavior
for stale/missing evidence. Do not add autonomous tool loops or
remediation."

## Acceptance

-   [ ] Provider credentials stay server-side.
-   [ ] Provider can be mocked in tests.
-   [ ] Structured output is validated.
-   [ ] Invented evidence IDs are rejected.
-   [ ] Observations and hypotheses are distinct.
-   [ ] Missing/stale evidence can produce abstention.
-   [ ] Provider/model/prompt metadata is recorded.
