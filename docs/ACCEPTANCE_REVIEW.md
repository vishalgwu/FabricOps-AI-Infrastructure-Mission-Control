# Acceptance Review (Phase 12)

A review of the application against every gate in
[guide/03_MILESTONES_AND_ACCEPTANCE.md](guide/03_MILESTONES_AND_ACCEPTANCE.md) and the Phase 12 acceptance list.
Each line says **Met**, **Met with a caveat**, or **Not met**, and points at the evidence. Nothing is marked Met without
something that was actually run.

The one caveat that touches many lines: **the real Claude model has never been called.** Wherever a line depends on model
behaviour, it was verified with a scripted model, a mock, or a fake client. That is said in each place.

## Gate 0: repository understood

| Item | Status | Evidence |
|---|---|---|
| Existing files and branches inspected | Met | [project/BASELINE_AUDIT.md](project/BASELINE_AUDIT.md) |
| No existing work overwritten | Met | Git history: every phase is an additive commit |
| Baseline documented | Met | The same audit |

## Gate 1: runnable skeleton

| Item | Status | Evidence |
|---|---|---|
| Backend starts | Met | Run in the fresh-clone check; `uvicorn app.main:app` |
| Health endpoint responds | Met | `GET /health`; `tests/test_health.py` |
| Frontend starts | Met | `npm run dev` in the fresh-clone check |
| `.env.example` exists | Met | [../.env.example](../.env.example), lists every setting |
| No secrets committed | Met | `tests/test_security_hardening.py::test_no_real_looking_keys_are_in_tracked_files`, `::test_no_env_files_or_databases_are_tracked` |

## Gate 2: data and fixtures

| Item | Status | Evidence |
|---|---|---|
| Three scenarios load | Met | `tests/test_schemas.py::test_three_scenarios_load` |
| Pydantic rejects malformed data | Met | `tests/test_schemas.py` (unit, timestamp, unknown-host, missing-field cases) |
| Timestamps and units explicit | Met | One unit per metric; UTC-only timestamps (`tests/test_schemas.py::test_naive_timestamp_rejected`) |
| Fixtures labelled synthetic | Met | `tests/test_schemas.py::test_all_fixtures_labelled_synthetic` |
| Expected answers stored separately | Met | `backend/data/evals/`; `tests/test_schemas.py::test_runtime_code_never_reads_the_answer_key` |

## Gate 3: telemetry tools

| Item | Status | Evidence |
|---|---|---|
| Tools are typed and read-only | Met | `tests/test_telemetry_tools.py::test_exactly_three_read_only_tools`, `::test_adapter_has_no_write_methods` |
| Unknown hosts rejected | Met | `::test_unknown_host_rejected`, `::test_out_of_scope_host_rejected` |
| Time ranges and response sizes bounded | Met | `::test_excessive_or_invalid_windows_rejected`, `::test_log_limit_truncates_and_flags` |
| Tool errors differ from valid zero readings | Met | `::test_valid_zero_reading_is_ok_not_missing`, `::test_source_failures_are_distinct_and_empty` |
| Every result has provenance and timestamps | Met | `::test_read_metrics_ok_with_provenance` |

## Gate 4: retrieval

| Item | Status | Evidence |
|---|---|---|
| Chunks preserve source, version, section | Met | `tests/test_retrieval.py::test_every_chunk_resolves_to_source_and_version` |
| Stable chunk IDs | Met | `::test_chunk_ids_are_stable_across_reloads` |
| No-match behaviour tested | Met | `::test_no_match_is_explicit_and_empty` |
| Retrieved text cannot change permissions | Met | `::test_retrieving_injection_does_not_change_telemetry_permissions` |

Caveat: retrieval is a lexical baseline tested on a handful of curated queries. Citation *relevance* is not machine-checked (evaluation case E27).

## Gate 5: LLM investigation

| Item | Status | Evidence |
|---|---|---|
| Structured output validates | Met with a caveat | `tests/test_investigator.py` (schema, strict parsing). Verified with a mock, a fake client and the scripted demo model; **not with the real model** |
| Unknown evidence IDs rejected | Met | `::test_invented_evidence_id_is_rejected`; evaluation cases E08, E13 |
| Stale or missing evidence causes abstention | Met | Evaluation cases E03, E04, E10; the model is not called |
| Model, provider and prompt versions recorded | Met | `::test_valid_answer_completes_with_metadata`; run `model_id` and `prompt_version` |
| API failures handled | Met with a caveat | `::test_transient_failures_are_retried_with_backoff`, `::test_anthropic_provider_maps_sdk_errors`; against SDK error classes built by hand, not a live outage |

## Gate 6: workflow and policy

| Item | Status | Evidence |
|---|---|---|
| Run states persist | Met | `tests/test_persistence_api.py::test_records_survive_closing_and_reopening_the_database` |
| Limits on steps, tool calls, time and output | Met | `tests/test_workflow.py` limit tests; the model call is also capped by the run's remaining time (`tests/test_security_hardening.py`). Steps are a fixed sequence, not a loop |
| Risky proposals pause | Met | Evaluation case E14; `tests/test_policy_approvals.py` |
| No remediation can execute | Met | `tests/test_policy_approvals.py::test_no_execution_adapter_exists_anywhere_in_the_app` |
| Approval tied to proposal version and hash | Met | `::test_revising_a_proposal_invalidates_the_old_approval` |

## Gate 7: UI and history

| Item | Status | Evidence |
|---|---|---|
| UI displays actual backend data | Met | Frontend tests against API-shaped responses; driven in a browser against the real backend |
| Citations open their evidence or source | Met | `frontend/src/pages/RunPage.test.tsx`; `tests/test_ui_endpoints.py` |
| Refresh preserves state | Met | `RunPage.test.tsx` (fresh mount); reload checked in a browser |
| Run history survives a backend restart | Met | `tests/test_security_hardening.py::test_runs_interrupted_by_a_restart_are_closed_and_say_why`; restart checked on a real server |
| Error, loading, empty and abstained states visible | Met | `RunPage.test.tsx`, `Incidents.test.tsx` |

## Gate 8: evaluation and release

| Item | Status | Evidence |
|---|---|---|
| Automated tests cover all scenarios | Met with a caveat | 29 evaluation cases across all three scenarios. The inference and link scenarios use a scripted model |
| Critical safety tests pass | Met | `python -m evals`: every critical metric at full count |
| Results include sample counts and limitations | Met | [evaluation/EVAL_REPORT.md](evaluation/EVAL_REPORT.md) |
| Fresh clone setup works | Met | See [RELEASE_NOTES.md](RELEASE_NOTES.md), "Fresh-clone verification" |
| Demo uses clearly labelled synthetic data | Met | Banner on every page; "synthetic" tags; the demo model is labelled on every run it produces |

## Final acceptance checklist (from the guide)

| Item | Status |
|---|---|
| Fresh clone setup is documented and reproducible | Met (see release notes) |
| Three synthetic scenarios load and validate | Met |
| Incidents and runs persist across restarts | Met |
| Typed read-only tools return real fixture records | Met |
| Every evidence record has provenance and timestamps | Met |
| Retrieval returns versioned source chunks | Met |
| LLM outputs use a validated schema | Met with a caveat (real model not run) |
| Unsupported evidence IDs are rejected | Met |
| Stale or missing telemetry causes abstention | Met |
| Risk policy is deterministic and server-side | Met |
| No production remediation is possible | Met |
| UI shows actual persisted state | Met |
| Evaluation results are reproducible | Met (`python -m evals --check-report`; a test fails if the report is stale) |
| README explains limitations honestly | Met |

## Phase 12 acceptance

| Item | Status | Evidence |
|---|---|---|
| Fresh clone works from documented instructions | Met | Release notes |
| Tests and evaluation commands work | Met | Same check |
| Demo scenarios are reproducible | Met | The demo model is deterministic; evaluation cases E28 and E29 run it end to end; the demo script was followed in the fresh-clone check |
| Synthetic data is clearly labelled | Met | See Gate 8 |
| Known limitations are documented | Met | README, security review |
| Git history contains meaningful milestone commits | Met | One commit per phase; see release notes |
| Final release describes only verified functionality | Met | [RELEASE_NOTES.md](RELEASE_NOTES.md) separates verified from not verified |

## Not met, or not verified

- The real Anthropic path (live request shape, refusal fallbacks, real answers) has not been exercised.
- No manual claim-support review has been done, so there is no statement about whether a real model's claims are supported.
- Latency and token cost have never been measured on a real run.
- No authentication or rate limiting (documented, out of scope for a local demo).
- The Python lock file was generated and tested on Windows only.
