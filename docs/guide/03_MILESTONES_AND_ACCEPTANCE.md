# 03 --- Milestones and Acceptance Gates

Do phases in order. A phase is complete only when its acceptance checks
pass.

  -----------------------------------------------------------------------
  Milestone               Phases                  Result
  ----------------------- ----------------------- -----------------------
  A --- Foundation        00--02                  Repository, app
                                                  skeleton, schemas and
                                                  fixtures

  B --- Investigation     03--06                  Telemetry tools, RAG,
  engine                                          LLM analysis and
                                                  workflow

  C --- Safe user         07--09                  Policy, API/UI
  experience                                      integration and history

  D --- Quality and       10--12                  Evaluation, hardening,
  release                                         docs and demo
  -----------------------------------------------------------------------

## Phase gates

### Gate 0 --- Repository understood

-   Existing files and branches inspected.
-   No existing work overwritten.
-   Baseline documented.

### Gate 1 --- Runnable skeleton

-   Backend starts.
-   Health endpoint responds.
-   Frontend starts.
-   `.env.example` exists.
-   No secrets committed.

### Gate 2 --- Data and fixtures

-   Three scenarios load.
-   Pydantic rejects malformed data.
-   Timestamps and units are explicit.
-   Fixtures are labelled synthetic.
-   Expected answers are stored separately from runtime inputs.

### Gate 3 --- Telemetry tools

-   Tools are typed and read-only.
-   Unknown hosts are rejected.
-   Time ranges and response sizes are bounded.
-   Tool errors differ from valid zero readings.
-   Every result has provenance and timestamps.

### Gate 4 --- Retrieval

-   Chunks preserve source/version/section.
-   Search returns stable chunk IDs.
-   No-match behavior is tested.
-   Retrieved text cannot change system permissions.

### Gate 5 --- LLM investigation

-   Structured output validates.
-   Unknown evidence IDs are rejected.
-   Stale/missing evidence causes abstention.
-   Model/provider and prompt versions are recorded.
-   API failures are handled.

### Gate 6 --- Workflow and policy

-   Run states persist.
-   Workflow has limits on steps, tool calls, time and output.
-   Risky proposals pause.
-   No remediation can execute.
-   Approval is tied to a proposal version/hash.

### Gate 7 --- UI and history

-   UI displays actual backend data.
-   Citations open their evidence/source.
-   Refresh preserves state.
-   Run history survives backend restart.
-   Error, loading, empty and abstained states are visible.

### Gate 8 --- Evaluation and release

-   Automated tests cover all scenarios.
-   Critical safety tests pass.
-   Results include sample counts and limitations.
-   Fresh clone setup works.
-   Demo uses clearly labelled synthetic data.

## Final acceptance checklist

-   [x] Fresh clone setup is documented and reproducible. (Windows only)
-   [x] Three synthetic scenarios load and validate.
-   [x] Incidents and runs persist across restarts.
-   [x] Typed read-only tools return real fixture records.
-   [x] Every evidence record has provenance and timestamps.
-   [x] Retrieval returns versioned source chunks.
-   [x] LLM outputs use a validated schema. (verified with a mock, a fake client and the scripted demo model; the real model was not run)
-   [x] Unsupported evidence IDs are rejected.
-   [x] Stale/missing telemetry causes abstention.
-   [x] Risk policy is deterministic and server-side.
-   [x] No production remediation is possible.
-   [x] UI shows actual persisted state.
-   [x] Evaluation results are reproducible.
-   [x] README explains limitations honestly.

See [../ACCEPTANCE_REVIEW.md](../ACCEPTANCE_REVIEW.md) for the line-by-line review and its caveats.
