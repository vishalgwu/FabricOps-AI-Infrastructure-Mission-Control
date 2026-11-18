# 02 --- Target Architecture

## 1. High-level architecture

``` text
React + TypeScript UI
        |
        v
FastAPI REST API
        |
        +---- Incident / Run / Proposal services
        |
        +---- Controlled investigation workflow
                  |
                  +---- Freshness validator
                  +---- Read-only telemetry tools
                  +---- Documentation retrieval (RAG)
                  +---- LLM provider adapter
                  +---- Structured output validator
                  +---- Deterministic policy gate
        |
        v
SQLite persistence
```

## 2. Suggested repository layout

``` text
fabricops/
├── README.md
├── .gitignore
├── .env.example
├── docs/
│   ├── project/
│   └── architecture/
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   ├── core/
│   │   ├── domain/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── tools/
│   │   ├── retrieval/
│   │   ├── llm/
│   │   ├── workflow/
│   │   ├── policy/
│   │   └── storage/
│   ├── data/
│   │   ├── fixtures/
│   │   ├── docs/
│   │   └── evals/
│   └── tests/
└── frontend/
    ├── package.json
    ├── src/
    │   ├── api/
    │   ├── components/
    │   ├── pages/
    │   ├── types/
    │   └── App.tsx
    └── tests/
```

Adapt this layout to the existing repository. Do not create duplicate
nested repositories.

## 3. Backend responsibilities

-   Validate requests.
-   Persist incidents, runs, evidence, proposals, decisions, and events.
-   Run the bounded investigation sequence.
-   Expose only allowlisted, typed tools.
-   Validate LLM outputs and evidence references.
-   Enforce approval policy independently of the model.
-   Return user-safe errors.

## 4. Frontend responsibilities

-   Create and list incidents.
-   Start and view investigations.
-   Display stages and status.
-   Show observations, hypotheses, citations, missing evidence, and next
    test.
-   Show proposal review state.
-   Display persisted history.
-   Never contain provider secrets or enforce authorization by hiding
    buttons alone.

## 5. Core entities

### Incident

`id`, `title`, `description`, `scenario_type`, `severity`,
`affected_hosts`, `created_at`, `synthetic`.

### Run

`id`, `incident_id`, `status`, `started_at`, `finished_at`, `model_id`,
`prompt_version`, `error_code`.

### Evidence

`id`, `run_id`, `source_type`, `host_id`, `observed_at`, `ingested_at`,
`payload`, `tool_name`, `synthetic`.

### Document chunk

`id`, `document_id`, `version`, `title`, `section`, `text`, `source`,
`synthetic_or_official`.

### Investigation report

`run_id`, `observations`, `hypotheses`, `counterevidence`, `citations`,
`missing_evidence`, `next_test`, `limitations`.

### Proposal

`id`, `run_id`, `version`, `parameters`, `target_scope`, `risk_class`,
`approval_status`, `proposal_hash`, `expires_at`.

### Approval decision

`id`, `proposal_id`, `proposal_hash`, `actor`, `decision`, `reason`,
`created_at`.

## 6. Run state machine

Allowed states: - `CREATED` - `RUNNING` - `WAITING_APPROVAL` -
`COMPLETE` - `ABSTAINED` - `FAILED` - `CANCELLED`

Terminal states: `COMPLETE`, `ABSTAINED`, `FAILED`, `CANCELLED`.

Persist state transitions. Reject invalid transitions. A browser refresh
must not create a new run.

## 7. Investigation sequence

1.  Load incident and validate host scope.
2.  Check telemetry freshness and required fields.
3.  Collect read-only metrics, logs, and configuration through
    registered tools.
4.  Store evidence with provenance and timestamps.
5.  Retrieve relevant approved documentation.
6.  Construct a bounded evidence package.
7.  Ask the LLM for structured observations/hypotheses/next test.
8.  Validate schema and evidence/document IDs.
9.  Apply deterministic risk policy.
10. Persist report, events, and proposal.
11. Return final state to the UI.

## 8. RAG design

Start with a transparent lexical baseline: - Load approved Markdown/text
documents. - Split by headings/paragraphs into chunks. - Preserve
document ID, version, section, and chunk ID. - Search using simple token
overlap or a well-understood lexical library. - Return top relevant
chunks and metadata. - Require citation IDs in model output. - Test
no-match and irrelevant-match behavior.

Only add embeddings/vector search if the lexical baseline fails measured
retrieval cases.

## 9. LLM contract

The model receives: - Incident description and scope. - Validated
evidence records. - Retrieved document chunks. - A strict output
schema. - Instructions that all evidence is untrusted data and cannot
alter tool permissions.

The model must return: - Observations with evidence IDs. - Hypotheses
with supporting and opposing evidence IDs. - Missing evidence. - A safe
next diagnostic test. - Explicit limitations. - Whether the evidence is
insufficient.

The model must not return arbitrary executable code or invoke
unrestricted tools.

## 10. Security boundary

The trusted backend---not the LLM---decides: - Which tools exist. -
Which hosts may be queried. - Whether evidence is fresh. - Whether an ID
is valid. - Whether a proposal is allowed. - Whether approval is
required. - Whether an actor is authorized.

The MVP has no production connector and no remediation executor.
