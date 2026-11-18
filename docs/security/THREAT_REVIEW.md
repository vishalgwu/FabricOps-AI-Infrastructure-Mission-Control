# Security and Reliability Review (Phase 11)

Scope: the local demo of FabricOps (backend, frontend, evaluation tooling). Date of review: 2026-11-18.
FabricOps is a portfolio project that runs on synthetic data on one machine. This review asks "can untrusted
content or a hostile client control the application, leak a secret, or leave it in a broken state?". It is not a
penetration test and not a statement that the application is safe to put on the internet. **It is not.** See the
unresolved risks at the end.

## How the review was done

1. Read the code against the Phase 11 threat list and required controls.
2. **Probed** each suspected weakness against the running code instead of guessing (a script that sent hostile input and
   read what came back).
3. Fixed only what the probes confirmed, in small changes, each with a regression test.
4. Ran `pip-audit` and `npm audit` on the dependencies.
5. Checked the fixes again over real HTTP against a real server (restart recovery, headers, 413, redaction).

## Findings that were confirmed and fixed

| # | Finding (confirmed by probe) | Fix | Regression tests |
|---|---|---|---|
| 1 | A huge integer in `offset` or `after_seq` (for example 10^30) reached SQLite and produced **HTTP 500**. | Upper bound of 2^31-1 on both parameters; out-of-range values get a 422. | `tests/test_security_hardening.py::test_huge_integers_are_rejected_not_a_500`, `tests/test_security_hardening.py::test_the_largest_allowed_integer_still_works` |
| 2 | **Secrets leaked into logs** in three ways: exception tracebacks were not redacted at all, a dict of headers (`{'x-api-key': 'sk-ant-...'}`) slipped past the key-value pattern, and a bare `sk-ant-...` key was not recognised. uvicorn's own log lines bypassed the filter. | Redaction now runs on the final formatted text (message, arguments and traceback), covers quoted `key: value` forms and provider key shapes, also removes the exact configured API key whatever its format, and uvicorn's loggers go through the same handler. | `tests/test_security_hardening.py::test_redaction_removes_secrets_in_many_shapes`, `tests/test_security_hardening.py::test_redaction_does_not_mangle_ordinary_log_text`, `tests/test_security_hardening.py::test_the_log_handler_redacts_tracebacks_and_other_loggers`, `tests/test_security_hardening.py::test_the_configured_api_key_is_registered_for_redaction` |
| 3 | An unexpected error returned a bare "Internal Server Error" (inconsistent with the API's error shape), and the server's own traceback logging was unredacted. A database error (`database is locked`) was a 500. | Middleware catches unexpected errors, logs them through the redacting formatter, and returns the standard envelope with no detail (500 `internal_error`, or 503 `database_unavailable` for database errors). | `tests/test_security_hardening.py::test_an_unexpected_error_gives_a_safe_envelope_and_a_redacted_log`, `tests/test_security_hardening.py::test_a_database_error_is_a_503_not_a_500`, `tests/test_security_hardening.py::test_known_errors_keep_their_own_envelopes` |
| 4 | There was **no request size limit**: a 3 MB body was read and validated in full. | Bodies over 64 KiB (configurable) get 413 before the application reads them, for declared lengths and for chunked uploads. The 413 carries CORS headers so the browser can read it. | `tests/test_security_hardening.py::test_a_body_over_the_limit_is_refused_before_it_is_read`, `tests/test_security_hardening.py::test_a_chunked_body_over_the_limit_is_refused_too`, `tests/test_security_hardening.py::test_the_limit_is_configurable_and_a_normal_request_passes`, `tests/test_security_hardening.py::test_the_413_carries_cors_headers_so_the_browser_can_read_it` |
| 5 | **A run stuck `RUNNING` after a server stop stayed that way forever**, and because one active run per incident is allowed, it blocked starting a new one. | On startup, runs that were queued or running are closed as `FAILED` with code `interrupted` and a plain explanation in their events. Runs waiting for approval are left alone (their state is fully stored). | `tests/test_security_hardening.py::test_runs_interrupted_by_a_restart_are_closed_and_say_why`, `tests/test_security_hardening.py::test_recovery_unblocks_starting_a_new_run_and_is_idempotent`, `tests/test_security_hardening.py::test_startup_recovery_does_not_touch_the_database_at_import_time` |
| 6 | **The 120 s run limit was not enforced on the model call.** Three attempts at the configured 120 s timeout plus backoff could run for over six minutes. | The remaining run time is passed down: no attempt starts after it runs out, each attempt's timeout is capped to it, and retries do not pause past it. The run ends `FAILED` with `run_timeout`. | `tests/test_security_hardening.py::test_no_attempt_starts_once_the_time_limit_has_passed`, `tests/test_security_hardening.py::test_each_attempt_is_capped_to_the_time_left_and_retries_stop_when_it_runs_out`, `tests/test_security_hardening.py::test_the_anthropic_adapter_never_waits_longer_than_the_run_has_left`, `tests/test_security_hardening.py::test_a_run_ends_failed_with_run_timeout_instead_of_retrying_past_its_limit` |
| 7 | Responses carried no hardening headers. | Every response (success, error, 404, 413, 422) now sends `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`. | `tests/test_security_hardening.py::test_security_headers_are_on_every_kind_of_response` |
| 8 | A NUL or other control character was accepted in an incident title or description (and a decision reason). | Titles are single-line plain text; descriptions allow line breaks and tabs but no other control characters; reasons allow none. | `tests/test_security_hardening.py::test_control_characters_are_rejected_in_text_fields`, `tests/test_security_hardening.py::test_decision_reason_rejects_control_characters` |
| 9 | In the browser, `crypto.randomUUID` is missing on plain http (for example opening the app from another machine), so "Start investigation" failed. | A key generator that falls back to random bytes and always satisfies the backend's key format. | `frontend/src/idempotency.test.ts` (4 tests) |
| 10 | The dev dependency `pytest` 8.4.2 had a published advisory (fixed in 9.0.3). | The constraint is now `pytest>=9.0.3,<10`; the full suite passes on 9.2. | `pip-audit`: no known vulnerabilities after the change |

## Threat checklist (the Phase 11 list)

| Threat | Control | Status | Evidence |
|---|---|---|---|
| Prompt injection in logs | Log text reaches the model only as quoted data inside the evidence, marked untrusted. The model cannot choose tools, hosts or commands; its answer is validated and any out-of-scope or command-like proposal is refused. | Mitigated (content can still be misleading, see risks) | `tests/test_investigator.py::test_obeying_injected_log_text_is_rejected`, `tests/test_telemetry_tools.py::test_unregistered_tools_rejected`; evaluation cases E11 and E12 |
| Prompt injection in documents | Retrieved text is untrusted data and cannot change tool lists, scopes or permissions. | Mitigated | `tests/test_retrieval.py::test_injected_document_text_is_returned_only_as_labelled_untrusted_data`, `tests/test_retrieval.py::test_retrieving_injection_does_not_change_telemetry_permissions` |
| Unknown host IDs | Host IDs are format-checked, must exist in the scenario inventory, and must be in the run's scope. | Mitigated | `tests/test_telemetry_tools.py::test_unknown_host_rejected`, `tests/test_telemetry_tools.py::test_out_of_scope_host_rejected`, `tests/test_telemetry_tools.py::test_malicious_host_ids_rejected` |
| Oversized time windows or result sets | Windows, ranges, log counts, samples, evidence records, document chunks and model output are all capped. | Mitigated | `tests/test_telemetry_tools.py::test_excessive_or_invalid_windows_rejected`, `tests/test_workflow.py::test_tool_call_limit_stops_the_run_before_any_work` |
| Oversized requests | 64 KiB body limit; bounded query parameters; bounded field lengths. | Fixed in this phase (findings 1, 4) | see findings |
| Malformed model output | Strict schema; invalid output fails the run and is not retried. | Mitigated | `tests/test_investigator.py::test_malformed_output_is_a_failure` |
| Fabricated evidence references | Every evidence and document ID must exist in this run. | Mitigated | `tests/test_investigator.py::test_invented_evidence_id_is_rejected`; evaluation cases E08 and E13 |
| Secret leakage in logs or frontend | Redaction on the final log text; configured key registered; the browser bundle and every API response are checked for keys. | Fixed in this phase (finding 2) | `tests/test_ui_endpoints.py::test_no_secret_appears_in_any_response`, `tests/test_investigator.py::test_api_key_stays_server_side`, `tests/test_security_hardening.py::test_no_real_looking_keys_are_in_tracked_files`, `tests/test_security_hardening.py::test_no_env_files_or_databases_are_tracked`; `frontend/src/security.test.ts` |
| Duplicate run requests | Database-enforced idempotency and one active run per incident; a run executes at most once. | Mitigated | `tests/test_workflow.py::test_concurrent_starts_create_exactly_one_run`, `tests/test_workflow.py::test_same_idempotency_key_returns_the_same_run`, `tests/test_workflow.py::test_execute_is_idempotent_and_runs_once_even_under_a_race` |
| Invalid state transitions | One transition table, enforced with compare-and-swap in the database. | Mitigated | `tests/test_persistence_api.py::test_invalid_transitions_rejected`, `tests/test_persistence_api.py::test_terminal_states_have_no_exits` |
| Unauthorized approval attempts | Reviewer must be on a server-side allow list; the actor cannot be set in the body; checks happen in the service, not the UI. | Mitigated for the demo identity (see risks) | `tests/test_policy_approvals.py::test_decisions_need_an_authorised_reviewer`, `tests/test_policy_approvals.py::test_the_actor_cannot_be_claimed_in_the_request_body` |
| Expired or modified proposals | Decisions bind to a hash and version; expiry cancels the run; a revision expires the old version. | Mitigated | `tests/test_policy_approvals.py::test_revising_a_proposal_invalidates_the_old_approval`, `tests/test_policy_approvals.py::test_pending_proposals_expire_and_cancel_the_run`, `tests/test_policy_approvals.py::test_deciding_after_expiry_fails_even_without_a_prior_read`, `tests/test_policy_approvals.py::test_concurrent_decisions_record_exactly_one` |
| Database errors | Safe 503, a 30 s wait for competing writers, and recovery of interrupted runs at startup. | Fixed in this phase (findings 3, 5) | see findings |
| Provider timeouts | Per-attempt timeout capped by the run's remaining time; at most 3 attempts; every failure is a typed, visible run outcome. | Fixed in this phase (finding 6) | `tests/test_investigator.py::test_retries_are_bounded`, `tests/test_workflow.py::test_provider_that_cannot_be_created_is_a_clear_configuration_failure` |

## Required controls (the Phase 11 list)

| Control | Where |
|---|---|
| Strict input validation | Pydantic models with `extra="forbid"`, length and pattern limits, control-character checks |
| Tool allowlist | Exactly three read-only telemetry tools plus `search_docs`; unregistered names are refused (`tests/test_telemetry_tools.py::test_unregistered_tools_rejected`) |
| Host and time-range scope limits | `TelemetryTools` and `WorkflowLimits` |
| Output size limits | Request bodies, model output, evidence records, document chunks |
| Server-side policy enforcement | `app/policy`, `app/services/proposals.py` |
| Secret redaction | `app/core/logging.py` |
| Safe error messages | Error envelope; `internal_error` and `database_unavailable` carry no detail |
| Bounded retries and timeouts | `Investigator`, `WorkflowLimits`, the provider timeout |
| Persistent state transitions | `RunRepository.transition`, `fail_interrupted` |
| No arbitrary shell, URL or file tools | `tests/test_telemetry_tools.py::test_tool_modules_have_no_dangerous_imports` |
| No remediation execution | `tests/test_policy_approvals.py::test_no_execution_adapter_exists_anywhere_in_the_app` |

## Checked and found fine

SQL injection and path traversal in IDs (parameterised queries; hostile IDs return 404; `tests/test_security_hardening.py::test_hostile_ids_are_just_not_found`).
CORS (only the configured origins, only GET and POST, no credentials).
Rendering of model, log and document text in the UI (React escapes it; a test forbids `dangerouslySetInnerHTML` and friends).
No route can update or delete an incident (`tests/test_persistence_api.py::test_no_update_or_delete_routes`).
Runtime Python dependencies and the npm dependencies had no known vulnerabilities at review time.

## Unresolved risks (read these)

1. **There is no authentication.** Anyone who can reach the API can create incidents, start runs, and, by sending the `X-Demo-Reviewer` header, approve or reject proposals. The reviewer list is a demo stand-in. Run the backend on localhost only. Do not expose it to a network.
2. **There is no rate limiting or quota.** A client can create unlimited incidents and runs, which grows the database and, with a real API key configured, causes billed model calls. Partly limited by one active run per incident, workflow limits and the 64 KiB body cap, but not solved.
3. **No TLS, and no CSP or HSTS from the app.** The API sends basic hardening headers. A Content-Security-Policy and TLS for the static frontend must come from whatever serves it. Slow-client and connection-level protection (timeouts, header limits) are uvicorn defaults; use a reverse proxy for anything beyond local use.
4. **Prompt injection cannot expand what the system does, but it can still influence what the model says.** A malicious log line could nudge the wording or emphasis of a hypothesis. The defences are labelling, evidence links and human review, not prevention. Whether a cited passage is relevant to a claim is not machine-checked (evaluation case E27).
5. **The risk policy is keyword-based.** It errs toward requiring approval, but unusual wording can be misclassified (for example a proposal that says "check" and then names a mutating action using words the rules do not list could be rated read-only). The real backstop is that **nothing is ever executed**: there is no execution path to abuse.
6. **The real model path is still unproven.** Nothing in this review exercised a live Claude call.
7. **Single-process assumption.** Startup recovery closes every queued or running run, which is correct for one local server but would wrongly close another worker's runs in a multi-worker deployment. Background work runs in-process.
8. **Log redaction is pattern-based.** It removes known key shapes and the configured key, but a secret in an unrecognised format coming from another system's exception text would not be caught.
9. **The database is an unencrypted local SQLite file** with default permissions. It holds only synthetic data. `backend/evals/live_runs/` (git-ignored) may hold real model output if the live smoke test is run.
10. **Dependencies are version-ranged, not locked,** so a future advisory is not pinned or detected automatically. Re-run `pip-audit` and `npm audit` periodically.
11. **Time limits are cooperative.** The model call is now bounded by the run's remaining time, but a blocking call elsewhere (for example a locked database) is only bounded by its own timeout (30 s for SQLite).

## How to re-run the checks

```bash
cd backend
.venv/Scripts/python -m pytest -q                 # includes tests/test_security_hardening.py
.venv/Scripts/python -m pip install pip-audit && .venv/Scripts/python -m pip_audit
cd ../frontend && npm test && npm audit
```
