# FabricOps v0.1.0: release notes

A local, synthetic-data demo of an evidence-grounded infrastructure investigation assistant. This release describes only
what was verified, how it was verified, and what was not. For how to run it, see the [README](../README.md).

**It is not safe to expose to a network** (no authentication, no rate limiting) and **the real Claude model has never been
called by this project's author.**

## What is in the release

- A FastAPI backend: incidents, background investigation runs, a fixed bounded workflow, read-only telemetry tools, versioned runbook retrieval with citations, a validated model investigator, deterministic risk policy, hashed and versioned proposals, demo approvals, replayable run events, SQLite persistence.
- A React UI: incident intake, run timeline, evidence and citation viewers, report (facts, hypotheses with counterevidence, limitations), proposal and approval panel, run history.
- Three synthetic scenarios (inference slowdown, isolated link instability, stale telemetry) and five synthetic runbooks.
- A **scripted demo model** (not an AI) so everything can be tried without an API key, labelled as such wherever it appears.
- An evaluation of the safeguards (29 cases), a security and reliability review (10 issues found and fixed), an architecture document, a five-minute demo script, and lock files for both languages.

## Verified

| Claim | How it was verified |
|---|---|
| 403 backend tests pass | `pytest -q` in `backend/` |
| 70 frontend tests pass; the frontend type-checks, builds and lints | `npm test`, `npm run build`, `npm run lint` in `frontend/` |
| 29 evaluation cases pass and the critical safety metrics are at full count | `python -m evals`; a test fails if `docs/evaluation/EVAL_REPORT.md` is stale |
| Both lock files satisfy the declared version ranges | `tests/test_release.py` |
| Dependencies had no known vulnerabilities | `pip-audit` and `npm audit`, 2026-11-18 |
| Stale or missing telemetry abstains without calling a model | Evaluation cases E03, E04, E10; run on a live server |
| Invented evidence or document IDs are refused | Evaluation cases E08, E13; unit tests |
| Out-of-scope and command-like proposals are refused; risky ones wait for a human | Evaluation cases E12, E14 to E17; unit tests |
| Approvals bind to a proposal's hash, expire, and survive a restart | `tests/test_policy_approvals.py`; a restart on a real server |
| No execution path exists | `tests/test_policy_approvals.py::test_no_execution_adapter_exists_anywhere_in_the_app` |
| The UI works against the real backend | Driven in a browser: create incident, start run, open evidence and a cited passage, approve, refresh, abstained state, history |
| The demo scenarios are reproducible | The demo model is deterministic; evaluation cases E28 and E29 run it end to end; the demo script was followed in the fresh-clone check |

### Fresh-clone verification

Done on 2026-11-18, on Windows 11 with Python 3.13.5 and Node 24, from a **clean `git clone` of the release commit into an empty directory**, following only the README. The only deviation: the README's `.venv/bin/python` lines were run as `.venv/Scripts/python`, which the README notes for Windows.

| Step (from the README) | Result |
|---|---|
| `python -m venv .venv`, `pip install -r requirements-lock.txt`, `pip install -e . --no-deps` | Installed the 36 pinned packages |
| `pytest -q` | 403 passed |
| `python -m evals --check-report` | 29/29 cases passed; the committed report matches |
| `npm ci`, `npm test`, `npm run build`, `npm run lint` | 70 tests passed; build and lint clean; 0 vulnerabilities |
| Start the backend with `FABRICOPS_LLM_PROVIDER=demo`, then `npm run dev` | Both started; the UI showed "Backend ok" |
| The README's `curl` block, verbatim | Run reached ABSTAINED in about a second; the report listed the stale host and the missing baseline; 21 events |
| The demo script, in a browser, against this clone | Followed steps 1 to 10: the incident form was pre-filled; the run reached *Waiting for approval* with the scripted-model notice, *Controlled test* risk and "Nothing is executed"; an evidence record showed *Observed at* 2026-03-10 and *Collected at* the current time; the citation opened runbook RB-KV-001 version 2.0; the stale scenario abstained with no model call; approving recorded the decision and completed the run; after stopping and restarting the backend, the decision, the 19 evidence rows and all 3 runs were still there |

Not covered by this check: Linux and macOS, other Python or Node versions, and any use of a real API key.

## Not verified (read this)

- **The real model.** The Anthropic adapter, its request shape (structured output, effort, refusal fallbacks) and the quality of real answers were never exercised. The adapter is tested only against a fake client. The optional live smoke test (`python -m evals.live`) exists and was not run.
- **Claim support.** No manual review of whether a model's claims are supported by the evidence has been done. The rubric exists; its results log is empty.
- **Latency and token cost** of real runs.
- **Other platforms.** Developed and tested on Windows with Python 3.13 and Node 24. The Python lock file was generated there. Linux and macOS were not tried.
- **Anything about scale:** large inputs, many concurrent users, long uptime.

## Known limitations and security limitations

Listed in full in the README ([known limitations](../README.md#known-limitations), [security limitations](../README.md#security-limitations)) and in [security/THREAT_REVIEW.md](security/THREAT_REVIEW.md). The headline ones: no authentication, no rate limiting, keyword-based risk policy, citation relevance not machine-checked, single-process assumption.

## History

One milestone commit per phase on `main`:

| Phase | Commit | What |
|---|---|---|
| 00 | `87145b9`, `d325cbc` | Repository audit; branch agreed |
| 01 | `87477bd` | Backend and frontend skeleton |
| 02 | `5656ea4` | Schemas and synthetic fixtures |
| 03 | `81b2e5b` | SQLite persistence, incident API, run state machine |
| 04 | `913998c` | Read-only telemetry tools |
| 05 | `a0e3e22` | Versioned retrieval and citations |
| 06 | `e88782d` | Validated LLM investigator |
| 07 | `75f7744` | Bounded, idempotent workflow |
| 08 | `cd5e404` | Policy, proposals, approvals |
| audit | `2fd3d81` | Cross-check of phases 00 to 08; fixes; README rewrite |
| 09 | `ab93089` | Mission-control UI |
| 10 | `33b2426` | Evaluation |
| 11 | `769269e` | Security and reliability review |
| 12 | `62ec003`, `f55717e` (this release is tagged `v0.1.0`) | Documentation, lock files, demo script, demo model, fresh-clone verification |
