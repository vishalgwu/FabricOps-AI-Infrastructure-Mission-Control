# Phase 01 --- Project Foundation and Local Skeleton

## Goal

Create a clean, runnable backend and frontend without implementing AI
behavior yet.

## Backend

Use FastAPI, Pydantic, and a test framework. Create: - Application entry
point. - Configuration/settings module. - Health endpoint such as
`GET /health`. - CORS configuration for the local frontend. - Dependency
and environment configuration. - Basic logging with secret redaction.

## Frontend

Use React + TypeScript + Vite. Create: - App shell. - Basic
navigation. - API base URL configuration. - A simple health status
display.

## Environment

Create `.env.example` containing placeholders, not real credentials.
Ensure `.env`, databases, caches, and build artifacts are ignored by
Git.

## Suggested commands

Backend commands depend on the selected package manager. Document exact
commands after creating `pyproject.toml`. Frontend commands must match
actual `package.json` scripts. Do not assume scripts exist.

## AI coding prompt

"Implement only Phase 01. First inspect the repository. Scaffold a
minimal FastAPI backend and React TypeScript Vite frontend. Add a health
endpoint and a frontend health check. Add tests, `.env.example`, and
`.gitignore`. Do not add an LLM, RAG, agent framework, database,
authentication, or telemetry integration yet. Run the tests and report
exact results."

## Acceptance

-   [ ] Backend starts locally.
-   [ ] `GET /health` returns a successful response.
-   [ ] Frontend starts locally.
-   [ ] Frontend can call backend health endpoint.
-   [ ] No secrets are committed.
-   [ ] Setup commands are documented.
-   [ ] At least one backend test passes.

## Suggested commit

`feat: scaffold FabricOps backend and frontend`
