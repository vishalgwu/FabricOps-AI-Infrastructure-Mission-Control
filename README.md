# FabricOps — AI Infrastructure Mission Control

FabricOps is an independent portfolio project. It shows how an AI copilot could help engineers investigate failures in infrastructure that runs AI workloads.

> **Disclaimer.** FabricOps is not affiliated with, endorsed by, or a product of any hardware or infrastructure vendor. It makes no claim of production accuracy.
>
> **Synthetic-data policy.** All incidents, telemetry, configuration and runbooks in this repository are synthetic and labeled as such. No real customer, vendor or production data is used. Live telemetry connectors and real remediation are out of scope.

## The idea

When inference slows down or a hardware link becomes unstable, engineers have to piece together telemetry, configuration and technical documentation by hand. FabricOps brings that evidence into one persistent investigation and proposes a next diagnostic step that the engineer can review.

An investigation ends in one of two ways:

- a **supported recommendation**, with cited evidence and a bounded next test, or
- an **abstention**: an explicit request for the missing evidence. It never claims a root cause it cannot support.

Risky proposals pause for **human approval**. In the MVP, FabricOps only *proposes* actions; it never executes remediation.

## What a demo looks like

1. **Pick an incident.** For example: model responses have slowed down and telemetry suggests KV-cache memory pressure.
2. **Follow the investigation.** The dashboard shows which signals were checked, what they suggest, and what is missing.
3. **Review the proposed next step.** The copilot suggests a controlled experiment to test the suspected cause. If evidence is thin it says so, and higher-risk proposals wait for approval.

Three scenarios are planned: inference slowdown, isolated link instability, and stale or missing telemetry. See [docs/mvp.md](docs/mvp.md) for the specification.

## Scope

FabricOps is the **general investigation platform**:

- incident intake
- typed, read-only telemetry tools
- document retrieval with citations
- model-backed investigation with validated, evidence-linked output
- deterministic policy gates and approval workflow
- durable investigation history and reports
- evaluation of whether conclusions are supported by evidence

**Not in scope:** the KV-cache performance benchmarking study (a separate project; FabricOps may later ingest a versioned benchmark report), unattended production remediation, live production telemetry connectors, and multi-agent orchestration.

## Status

| Area | Status |
|---|---|
| Repository and project specification | Specification written; build guide added under `docs/guide/` |
| Visual prototype | None exists. An earlier README mentioned one by mistake; the UI will be built from scratch in Phase 09 |
| Phase 01: runnable backend and frontend skeleton | Done: FastAPI `/health`, React status page, tests |
| Phase 02: domain schemas and synthetic fixtures | Done: Pydantic models, 3 scenario fixtures, separate answer keys, validation tests |
| Tools, retrieval, investigator, workflow, approvals, evaluation | Not started |

Only the skeleton and the data contract exist: a health endpoint, a status page, validated schemas and synthetic fixtures. There is no investigation capability yet. Nothing here should be read as a working system until the matching phase in the build guide is accepted.

## Roadmap

A 13-phase build plan (Phases 00–12) in four milestones. Each phase has its own acceptance checklist in [docs/guide/phases](docs/guide/phases); progress is tracked in [docs/guide/CHECKLIST.md](docs/guide/CHECKLIST.md).

- **A (Phases 00–02):** repository audit, runnable scaffold, schemas and synthetic fixtures
- **B (Phases 03–06):** persistence and incident API, telemetry tools, retrieval, LLM investigator
- **C (Phases 07–09):** controlled workflow, policy and approvals, UI and history
- **D (Phases 10–12):** evaluation, security and reliability, release and demo

## Stack

Python 3.11+ with FastAPI and Pydantic, SQLite for persistence, React + TypeScript + Vite for the UI, Pytest for backend tests, lexical retrieval for the first RAG version, and an LLM provider adapter behind one interface.

## Quick start

Prerequisites: Python 3.11+ and Node 20+.

Backend (from `backend/`):

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # on macOS/Linux: .venv/bin/python
.venv/Scripts/python -m uvicorn app.main:app --port 8000
.venv/Scripts/python -m pytest
```

Frontend (from `frontend/`, with the backend running):

```bash
npm install
npm run dev      # http://localhost:5173
npm run build
npm run lint
```

Data: scenario fixtures live in `backend/data/fixtures/` and are validated by `app/schemas`. The evaluation answer keys live separately in `backend/data/evals/` and are never read by runtime code (a test enforces this).

Configuration: see [.env.example](.env.example). Copy values into `backend/.env` and `frontend/.env`; real `.env` files are git-ignored. `GET http://localhost:8000/health` returns the service status.

Known limitation: `npm audit` reports a high-severity ReDoS advisory in `picomatch`, a transitive dev/build-time dependency of Vite. It is not shipped to browsers; revisit when Vite publishes a fix.

## Documentation

- [docs/mvp.md](docs/mvp.md): MVP specification, scenarios and investigation output contract
- [docs/guide/01_AI_CODING_RULES.md](docs/guide/01_AI_CODING_RULES.md): rules for AI coding assistants working on this repo
- [docs/guide/02_ARCHITECTURE.md](docs/guide/02_ARCHITECTURE.md): target architecture, entities, run state machine
- [docs/guide/03_MILESTONES_AND_ACCEPTANCE.md](docs/guide/03_MILESTONES_AND_ACCEPTANCE.md): phase gates and final acceptance checklist
- [docs/guide/phases](docs/guide/phases): per-phase build instructions
- [docs/FabricOps_Complete_Project_and_GenAI_Roadmap.pdf](docs/FabricOps_Complete_Project_and_GenAI_Roadmap.pdf): original roadmap (earlier 14-step plan, superseded by the phases above)
