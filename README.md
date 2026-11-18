# FabricOps — AI Infrastructure Mission Control

FabricOps is an independent portfolio project. It shows how an AI copilot could help engineers investigate failures in infrastructure that runs AI workloads: it gathers evidence, asks a language model for hypotheses, checks every claim against that evidence, and recommends a safe next diagnostic step for a human to review.

> **Disclaimer.** FabricOps is not affiliated with, endorsed by, or a product of any hardware or infrastructure vendor. It makes no claim of production accuracy.
>
> **Synthetic-data policy.** All incidents, telemetry, configuration and runbooks in this repository are synthetic and labelled as such. No real customer, vendor or production data is used. Live telemetry connectors and real remediation are out of scope.

## The idea

When inference slows down or a hardware link becomes unstable, engineers piece together telemetry, configuration and documentation by hand. FabricOps brings that evidence into one persistent investigation. An investigation ends in one of three ways:

- a **supported recommendation**: observations and hypotheses with cited evidence, and a bounded next test;
- an **abstention**: an explicit list of the evidence that is missing. It never claims a cause it cannot support;
- a **failure** with a typed error code, when something went wrong.

Risky proposals pause for **human approval**. FabricOps only *proposes*: there is no code anywhere that executes remediation.

Three synthetic scenarios are built in: **inference slowdown** (one host, healthy peers), **isolated link instability** (one host, healthy peers), and **stale or missing telemetry** (must abstain). The full specification is in [docs/mvp.md](docs/mvp.md).

## Status

This is a work in progress. The backend and the UI are built (Phases 00 to 09). Evaluation, hardening and release work (Phases 10 to 12) are not.

| Phase | What | State |
|---|---|---|
| 00 | Repository audit | Done ([baseline audit](docs/project/BASELINE_AUDIT.md)) |
| 01 | Runnable backend and frontend skeleton | Done |
| 02 | Domain schemas, synthetic fixtures, separate answer keys | Done |
| 03 | SQLite persistence, incident and run API, run state machine | Done |
| 04 | Typed read-only telemetry tools | Done |
| 05 | Versioned document retrieval with citations | Done |
| 06 | LLM investigator behind a provider interface | Done, but see below |
| 07 | Bounded, idempotent investigation workflow | Done |
| 08 | Deterministic policy, hashed proposals, approvals | Done |
| 09 | Mission-control UI and history | Done, but see below |
| 10 | Evaluation with reported results | **Not started** |
| 11 | Security and reliability hardening | **Not started** |
| 12 | Release, demo script, fresh-clone proof | **Not started** |

**What has been verified:** 286 automated backend tests and 64 frontend tests pass, and the frontend type-checks, builds and lints. The UI was driven in a real browser against the real backend: creating an incident, starting an investigation, opening an evidence record and a cited runbook passage, approving a proposal, reloading the page (state came back from the server), the abstained state, run history, and an unknown run. The stale-telemetry scenario abstains in about a second, and a missing API key produces a clear error rather than a crash. Earlier (Phase 00 to 08) a fresh clone from GitHub installed and passed the tests.

**What has not been verified:** the real Claude adapter has **never been run against the live API**. Every model response in the tests is a mock, so the end-to-end path "real model → validated report" is unproven, and the request shape (structured output, effort, refusal fallbacks) was written from the SDK documentation and tested only against a fake client. Please try it once with your own key before relying on it. The scenarios that need the model (inference slowdown, link instability) have only been run with scripted mock answers, including in the browser check above (the model was a scripted stand-in; everything else was real). The page layout was checked by measuring it at desktop and phone widths, not by looking at screenshots, because the browser pane could not capture them. There is no evaluation of answer quality yet (Phase 10).

## How it works

```
POST /api/incidents/{id}/runs  (returns 202 at once; work runs in the background)
        |
  load incident -> validate host scope and limits -> collect telemetry (read-only tools)
        -> check freshness -> persist evidence -> retrieve documents
        -> investigator (one model call, after a server-side abstention gate)
        -> apply policy to the suggested next step -> persist report
        |
  COMPLETE | ABSTAINED | WAITING_APPROVAL | FAILED | CANCELLED
```

The trusted backend, not the model, decides what is allowed:

- **Tools.** Exactly three read-only telemetry tools plus `search_docs`. Every input is validated and bounded; unknown hosts, out-of-scope hosts and unregistered tool names are rejected. Results say whether a reading is `ok`, `no_data`, `stale` (judged by observation time), a `timeout`, an `error`, `rejected` or `malformed`. A missing value is never treated as zero.
- **Abstention gate.** If an affected host has no fresh metrics, or no peer has any to compare against, the run abstains *before* the model is called (and the model client is not even created).
- **Model output is never trusted.** It is parsed against a strict schema; every evidence ID and document chunk ID must exist in this run; proposed hosts must be affected hosts, not peers; shell-like or write/deploy proposals and hypotheses worded as established fact are rejected. Log and document text reaches the model only as quoted data and is marked untrusted.
- **Policy.** Plain Python rules classify the next step as `read_only_diagnostic`, `controlled_test` or `write_or_deploy` from its wording. Unrecognised wording is never assumed safe, and the model's own label can only make the class stricter. Anything above read-only parks the run in `WAITING_APPROVAL`.
- **Approvals.** Each proposal has a version and a SHA-256 hash over its text, parameters, scope, risk class and the content of its evidence. A decision must carry that hash, so an approval cannot be reused after any change. Proposals expire (24 hours by default). Decisions are idempotent and stored with actor, time, reason and hash. Approving or rejecting only records a decision.
- **Reliability.** Stage events are stored in order and can be replayed after a refresh. Duplicate starts are blocked in the database. A run can execute only once. Failures end as `FAILED` with a typed code and a safe message; unexpected errors are logged on the server and shown only as `internal_error`.

## Quick start

Prerequisites: Python 3.11+ and Node 20+.

Backend (from `backend/`):

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # on macOS/Linux use .venv/bin/python
.venv/Scripts/python -m pytest
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

Frontend (from `frontend/`, with the backend running):

```bash
npm install
npm run dev      # http://localhost:5173
npm test         # 64 tests (vitest, jsdom)
npm run build    # type-check and production build
npm run lint
```

Interactive API docs are at `http://localhost:8000/docs`.

### Use the UI

Open `http://localhost:5173` with the backend running.

1. **Incidents:** pick a built-in scenario (the form is pre-filled from it) and create an incident.
2. **Start investigation** on the incident page. The run page updates by itself while it works.
3. **Read the result.** Facts from the evidence, hypotheses (with what supports and what argues against them), limitations, and what is missing are shown separately. Click any evidence or documentation ID to open the actual stored record or runbook passage; an ID that does not resolve is flagged, not hidden.
4. **Review the proposed next step.** It shows the policy-assigned risk class and, when approval is needed, a form for the demo reviewer. Approving or rejecting only records a decision.
5. **Run history** lists every investigation. A page refresh reloads everything from the server.

Without an API key the stale-telemetry scenario still works (it abstains before the model is needed); the other two end with a clear "no API credentials" failure.

### Try an investigation from the command line

The stale-telemetry scenario needs no API key. From any shell:

```bash
API=http://localhost:8000
INC=$(curl -s -X POST $API/api/incidents -H "Content-Type: application/json" -d '{
  "title": "Slow responses on gpu-h21",
  "description": "Users report slow responses on gpu-h21. The dashboard shows no recent data.",
  "scenario_type": "stale_telemetry", "severity": "unknown", "affected_hosts": ["gpu-h21"]}' | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
RUN=$(curl -s -X POST $API/api/incidents/$INC/runs -H "Idempotency-Key: demo-1" | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
sleep 2
curl -s $API/api/runs/$RUN            # status: ABSTAINED
curl -s $API/api/runs/$RUN/report     # lists exactly what evidence is missing
curl -s $API/api/runs/$RUN/events     # every stage, in order
```

The other two scenarios (`inference_slowdown` with host `gpu-h07`, `link_instability` with host `net-h01`) call the model, so they need `FABRICOPS_LLM_API_KEY` (or `ANTHROPIC_API_KEY`) in `backend/.env`. Without a key the run ends `FAILED` with a message naming the missing setting.

## API

| Method and path | Purpose |
|---|---|
| `GET /health` | Service status |
| `POST /api/incidents` | Create an incident (server generates `id` and `created_at`; always synthetic) |
| `GET /api/incidents?limit=&offset=` | List incidents, newest first |
| `GET /api/incidents/{id}` | Read one incident |
| `GET /api/incidents/{id}/runs` | List runs for an incident |
| `POST /api/incidents/{id}/runs` | Start an investigation (202). Optional `Idempotency-Key` header. A repeat, or an investigation already in flight, returns the existing run (200) |
| `GET /api/runs?limit=&offset=` | Run history across all incidents, newest first |
| `GET /api/runs/{id}` | Read one run |
| `GET /api/runs/{id}/events?after_seq=` | Ordered events; pass the last `seq` seen to resume after a refresh |
| `GET /api/runs/{id}/report` | The validated report (404 until one exists) |
| `GET /api/runs/{id}/evidence`, `GET /api/runs/{id}/evidence/{evidence_id}` | The evidence records collected for the run; an ID from another run does not resolve |
| `GET /api/documents/chunks/{chunk_id}` | Resolve a citation to its passage, source and version (superseded versions resolve, flagged) |
| `GET /api/scenarios` | The built-in synthetic scenarios, for the incident form |
| `GET /api/runs/{id}/proposal`, `GET /api/proposals/{id}` | The suggested next step: risk class, hash, approval status, decision. `execution_enabled` is always `false` |
| `POST /api/proposals/{id}/decision` | Approve or reject. Needs the `X-Demo-Reviewer` header and the proposal hash the reviewer saw |

Errors share one shape: `{"error": {"code", "message", "details": [{"field", "message"}]}}`. There are no update or delete routes, so incidents are immutable. While a run waits for approval, a new start request returns that run rather than starting another.

## Configuration

Copy the relevant block of [.env.example](.env.example) to `backend/.env` and `frontend/.env`. Real `.env` files are git-ignored. Run the backend from `backend/` so it finds its `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `FABRICOPS_DATABASE_PATH` | `backend/data/fabricops.db` | SQLite file (created on first use) |
| `FABRICOPS_CORS_ORIGINS` | local Vite origins | Browser origins allowed to call the API |
| `FABRICOPS_LLM_PROVIDER` | `anthropic` | `anthropic` or `mock` |
| `FABRICOPS_LLM_API_KEY` | unset | Falls back to `ANTHROPIC_API_KEY`. Backend only |
| `FABRICOPS_LLM_MODEL` | `claude-opus-5-5` | Model used for investigations |
| `FABRICOPS_LLM_EFFORT`, `_MAX_TOKENS`, `_TIMEOUT_SECONDS`, `_MAX_ATTEMPTS`, `_ENABLE_FALLBACKS` | `high`, 8000, 120, 3, `true` | Model request settings. Retries are for transient errors only |
| `FABRICOPS_DEMO_REVIEWERS` | `demo-reviewer` | Names allowed to approve or reject (comma-separated) |
| `FABRICOPS_APPROVAL_TTL_MINUTES` | 1440 | How long a pending proposal can be decided |

Workflow limits (tool calls, hosts, time range, evidence records, document chunks, output size, run time) are defined in `WorkflowLimits` in `backend/app/workflow/engine.py`.

## Project layout

```
backend/
  app/
    api/         HTTP routes (no SQL here)       services/   incident, run and proposal logic
    storage/     SQLite schema and repositories  workflow/   the bounded investigation sequence
    schemas/     Pydantic domain models          llm/        provider interface, prompt, validator, investigator
    tools/       read-only telemetry tools       policy/     deterministic risk classification and hashing
    retrieval/   chunker, BM25 index, search     domain/     fixture loader, run state machine
  data/
    fixtures/    three synthetic scenarios       docs/       synthetic runbooks and manifest
    evals/       answer keys (never read at runtime)
  tests/         286 tests
frontend/        React + TypeScript + Vite: src/api (typed client), src/pages, src/components, tests beside the code (64 tests)
docs/            specification, build guide, per-phase instructions, baseline audit
```

## Known limitations

- **The real model path is unproven** (see Status). No answer-quality evaluation exists yet.
- **UI scope:** it polls (every second while a run is active, every 10 seconds while one waits for approval) rather than streaming, uses hash routing, and shows every evidence record for a run in one table. There is no sign-in. Chart and trend views are out of scope.
- **Approval identity is a demo stand-in.** Reviewers are names in a request header; anyone who can reach the API can send one. It is not authentication, and the API as a whole has no authentication.
- **A server stop mid-run leaves that run `RUNNING`.** Recovery is planned for Phase 11. Background work uses in-process tasks, which suits one local server, not several workers.
- **Policy classification is keyword-based**, tuned on a small set of examples. It errs toward requiring approval and can misjudge unusual phrasing. Whether a cited passage is actually *relevant* to a claim is not machine-checked; only that it exists and was retrieved for the run.
- **Retrieval is a lexical baseline** tested on a handful of curated queries; very short queries can match weakly.
- **Incidents draw their data from the fixture matching their scenario type**; there is no live telemetry connector by design. Host IDs are checked against the scenario's inventory when a run starts, not when the incident is created.
- **Dependencies:** Python dependencies are version-ranged but there is no lock file yet (Phase 12). `npm audit` currently reports no vulnerabilities.

## Documentation

- [docs/mvp.md](docs/mvp.md): MVP specification, scenarios and the investigation output contract
- [docs/guide/CHECKLIST.md](docs/guide/CHECKLIST.md): progress checklist
- [docs/guide/01_AI_CODING_RULES.md](docs/guide/01_AI_CODING_RULES.md): rules for AI coding assistants working on this repository
- [docs/guide/02_ARCHITECTURE.md](docs/guide/02_ARCHITECTURE.md): target architecture, entities, run state machine
- [docs/guide/03_MILESTONES_AND_ACCEPTANCE.md](docs/guide/03_MILESTONES_AND_ACCEPTANCE.md): phase gates and final acceptance checklist
- [docs/guide/phases](docs/guide/phases): per-phase build instructions
- [docs/project/BASELINE_AUDIT.md](docs/project/BASELINE_AUDIT.md): the Phase 00 starting-point snapshot
- [docs/FabricOps_Complete_Project_and_GenAI_Roadmap.pdf](docs/FabricOps_Complete_Project_and_GenAI_Roadmap.pdf): the original roadmap (an earlier 14-step plan, superseded by the phases above)
