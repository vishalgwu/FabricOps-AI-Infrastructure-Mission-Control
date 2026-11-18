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
| Phase 03: SQLite persistence and incident API | Done: incidents, runs and run events persist; run state machine enforced; 57 backend tests pass |
| Phase 04: read-only telemetry tools | Done: `read_metrics`, `read_logs`, `read_config` over the fixture adapter; 102 backend tests pass |
| Phase 05: versioned document retrieval | Done: synthetic runbook corpus, chunker, BM25 lexical search, bounded `search_docs`; 141 backend tests pass |
| Phase 06: LLM investigator | Done and tested with a mock provider only; the real Claude adapter has not been run against the live API; 188 backend tests pass |
| Phase 07: controlled workflow | Done: fixed 8-stage workflow with limits, background start, idempotent runs, replayable events; 215 backend tests pass (mock provider only) |
| Phase 08: deterministic policy and approvals | Done: backend policy, hashed and versioned proposals, demo-reviewer approve/reject, expiry; 264 backend tests pass |
| UI, evaluation | Not started |

Only the skeleton, data contract and persistence exist: a health endpoint, a status page, validated schemas, synthetic fixtures, and a stored incident API. There is still no investigation capability (an investigation can be started and runs end to end against the synthetic fixtures; no live model call has been made yet). There is no investigation capability yet. Nothing here should be read as a working system until the matching phase in the build guide is accepted.

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

API (backend on port 8000; interactive docs at `/docs`):

| Method and path | Purpose |
|---|---|
| `GET /health` | Service status |
| `POST /api/incidents` | Create an incident (server generates `id` and `created_at`; always synthetic) |
| `GET /api/incidents?limit=&offset=` | List incidents, newest first |
| `GET /api/incidents/{id}` | Read one incident |
| `GET /api/incidents/{id}/runs` | List runs for an incident |
| `POST /api/incidents/{id}/runs` | Start an investigation (202, runs in the background). Optional `Idempotency-Key` header. A repeat or an in-flight run returns the existing run (200) |
| `GET /api/runs/{id}` | Read one run |
| `GET /api/runs/{id}/events?after_seq=` | Ordered stage and state events; pass the last `seq` seen to resume after a refresh |
| `GET /api/runs/{id}/report` | The validated investigation report (404 until one exists) |
| `GET /api/runs/{id}/proposal`, `GET /api/proposals/{id}` | The suggested next step with its risk class, hash, approval status and decision. `execution_enabled` is always `false` |
| `POST /api/proposals/{id}/decision` | Approve or reject (demo reviewer header `X-Demo-Reviewer`); body carries the proposal hash the reviewer saw |

Errors share one shape: `{"error": {"code", "message", "details": [{"field", "message"}]}}`. There are no update or delete routes, so IDs and incidents are immutable. The run state machine is enforced in the service layer.

Persistence: SQLite at `backend/data/fabricops.db` (git-ignored; override with `FABRICOPS_DATABASE_PATH`). The schema is created automatically on first use. Known limitation: affected host IDs are format-checked but not yet validated against a host registry.

Telemetry tools (`backend/app/tools/`): exactly three read-only tools, with every input validated and bounded (host IDs, 1 to 720 minute windows, log ranges of at most 24 hours, at most 100 logs). Unknown hosts, out-of-scope hosts and unregistered tool names are rejected. Each result reports a status that keeps these cases apart: `ok` (a reading of 0 is still `ok`), `no_data`, `stale` (judged by observation time, not ingestion time), `timeout`, `error`, `rejected` and `malformed`. Failures never carry readings. Evidence records get deterministic IDs per run and are stored with source, host, and separate observed and ingested timestamps. Log text is marked `untrusted_data`. The tools are not exposed over HTTP; the workflow will call them in Phase 07.

Document retrieval (`backend/app/retrieval/`, corpus in `backend/data/docs/`): a manifest lists each document with its ID, version, date, source path, classification (`synthetic` or `official`) and status (`current` or `superseded`). Documents are split at headings and paragraph boundaries into chunks with stable IDs of the form `RB-KV-001:2.0:symptoms:0`; the version is part of the ID, so a citation pins an exact version. Search is a plain BM25 lexical baseline with no embeddings or vector database. `search_docs(query, top_k)` returns ranked chunks with scores and metadata, or an explicit `no_data` / `no_match` result that tells the caller not to cite anything. Only current versions are searchable through the tool. Every hit is marked `untrusted_data`: document text can never change tools, hosts or permissions. The corpus is five short synthetic runbooks written for this project (no vendor documentation is copied); one deliberately contains injection text, and one is a superseded version that contradicts the current one. Known limitation: very short queries can match weakly (for example a single common word); the two-term matching rule and score floor reduce this but are tuned on a tiny curated set.

LLM investigator (`backend/app/llm/`): given an evidence package (this run's tool results plus retrieved document chunks), it returns a validated report or an honest abstention. Provider code sits behind one interface; `anthropic_provider.py` is the only file that imports the Anthropic SDK, and `MockProvider` lets tests and CI run with no API key. Set `FABRICOPS_LLM_API_KEY` (or `ANTHROPIC_API_KEY`) in `backend/.env`; the key stays on the backend and the browser never sees it. Default model: `claude-opus-5-5` (`FABRICOPS_LLM_MODEL`). Install the SDK with `pip install -e ".[llm]"`. The model gets one request, no tools and no loop.

- Before any model call, the server abstains if an affected host has no fresh metrics, or no peer has fresh metrics to compare against (stale telemetry never reaches the model).
- The model's answer is parsed against a strict schema, then every evidence ID and document chunk ID is checked against this run, proposed hosts must be affected hosts (not peers), `write_or_deploy` and shell-like proposals are rejected, and hypotheses worded as established fact are rejected. Invalid answers fail the run; only transient provider errors (rate limit, timeout, 5xx) are retried, at most 3 attempts.
- Model ID, prompt version (`investigator-v1`), latency, token usage and attempts are recorded.
- Server-side refusal fallbacks are on by default (`FABRICOPS_LLM_ENABLE_FALLBACKS`). Known limitation: this and the real adapter's request shape are written from the SDK documentation and unit-tested against a fake client only.

Workflow (`backend/app/workflow/`): a fixed sequence, not an agent loop: load incident, validate host scope, collect telemetry (typed tools), check freshness, persist evidence, retrieve documents, call the investigator once, persist the report. Explicit limits (`WorkflowLimits`): tool calls (12), hosts (8), metrics time range (60 of at most 120 minutes), evidence records (200), document chunks (5), model output size, model retries (3), and total run time (120 s). Limits that can be known up front are checked before any work starts. Every stage writes `stage_started` / `stage_completed` / `stage_failed` events; a failed stage ends the run as `FAILED` with a typed `error_code` (for example `invalid_host_scope`, `limit_exceeded`, `run_timeout`, `model_output_rejected`) and a safe message. Unexpected errors are logged on the server and shown only as `internal_error`. Stale or missing telemetry ends as `ABSTAINED`. Duplicate starts are prevented in the database (one run per incident and idempotency key, one in-flight run per incident), and a run can only be executed once. Nothing in the workflow executes anything on a host. Incidents are matched to a synthetic scenario fixture by `scenario_type`.

Policy and approvals (`backend/app/policy/`, `backend/app/services/proposals.py`): the model may suggest one next step, but plain Python rules decide its risk class from the wording: `read_only_diagnostic`, `controlled_test` or `write_or_deploy` (restart, deploy, delete, command syntax and similar). Unrecognised wording is treated as a controlled test, never as safe. The model's own label can only make the class stricter, never looser. Read-only proposals need no approval and the run completes. Controlled-test and write/deploy proposals park the run in `WAITING_APPROVAL`. Each proposal has a version and a SHA-256 hash covering its text, parameters, scope, risk class and the content of the evidence it cites. A decision must carry that hash, so an approval cannot be reused if anything changed; revising a proposal creates a new version, expires the old one and needs a fresh decision. Proposals expire (24 hours by default; `FABRICOPS_APPROVAL_TTL_MINUTES`); an expired one cancels the run. Decisions are idempotent and stored with actor, time, reason and hash, and survive restarts. Approving or rejecting only records the human decision. There is no execution adapter in the codebase, and a test scans for one.

Demo identity only: reviewers are the names in `FABRICOPS_DEMO_REVIEWERS` (default `demo-reviewer`), sent in the `X-Demo-Reviewer` header. Anyone who can reach the API can send that header, so this is a labelled demo stand-in and not authentication. Real login is out of scope for the MVP.

Known limitations: if the server stops mid-run, that run stays `RUNNING` (recovery is Phase 11). Background work uses FastAPI's in-process background tasks, which suits a single local server, not a multi-worker deployment. Wording-based classification is a conservative keyword rule set tuned on a small set of examples; it errs toward requiring approval and can misjudge unusual phrasing.

Configuration: see [.env.example](.env.example). Copy values into `backend/.env` and `frontend/.env`; real `.env` files are git-ignored. `GET http://localhost:8000/health` returns the service status.

Known limitation: `npm audit` reports a high-severity ReDoS advisory in `picomatch`, a transitive dev/build-time dependency of Vite. It is not shipped to browsers; revisit when Vite publishes a fix.

## Documentation

- [docs/mvp.md](docs/mvp.md): MVP specification, scenarios and investigation output contract
- [docs/guide/01_AI_CODING_RULES.md](docs/guide/01_AI_CODING_RULES.md): rules for AI coding assistants working on this repo
- [docs/guide/02_ARCHITECTURE.md](docs/guide/02_ARCHITECTURE.md): target architecture, entities, run state machine
- [docs/guide/03_MILESTONES_AND_ACCEPTANCE.md](docs/guide/03_MILESTONES_AND_ACCEPTANCE.md): phase gates and final acceptance checklist
- [docs/guide/phases](docs/guide/phases): per-phase build instructions
- [docs/FabricOps_Complete_Project_and_GenAI_Roadmap.pdf](docs/FabricOps_Complete_Project_and_GenAI_Roadmap.pdf): original roadmap (earlier 14-step plan, superseded by the phases above)
