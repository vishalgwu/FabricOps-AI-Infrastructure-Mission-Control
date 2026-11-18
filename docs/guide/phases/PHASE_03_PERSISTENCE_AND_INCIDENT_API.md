# Phase 03 --- Persistence and Incident API

## Goal

Save incidents and investigation records so they survive browser and
backend restarts.

## Storage

Use SQLite for the local MVP. Keep database access behind
repository/service interfaces so storage can change later.

## Minimum tables

-   incidents
-   runs
-   evidence
-   investigation_reports
-   proposals
-   approval_decisions
-   run_events

Use migrations or a repeatable schema initialization strategy. Add
indexes for IDs and common lookup fields.

## API endpoints

Implement and document: - `POST /api/incidents` - `GET /api/incidents` -
`GET /api/incidents/{incident_id}` -
`GET /api/incidents/{incident_id}/runs` - `GET /api/runs/{run_id}`

Validate all incoming data on the server. Generate immutable IDs. Use
consistent error responses.

## Run state

Implement the states in `02_ARCHITECTURE.md` and reject invalid
transitions.

## AI coding prompt

"Implement only Phase 03. Add SQLite persistence and repository/service
layers for incidents and runs. Implement the incident CRUD endpoints and
run read endpoints. Add tests proving records survive closing and
reopening the database. Enforce valid state transitions. Do not add LLM
calls or remediation."

## Acceptance

-   [x] Create/list/read incident endpoints work.
-   [x] IDs are stable and immutable.
-   [x] Restart persistence test passes.
-   [x] Invalid state transitions are rejected.
-   [x] API validation errors are clear.
-   [x] Database access is not embedded directly in route handlers.

## Suggested commit

`feat: persist incidents and expose incident API`
