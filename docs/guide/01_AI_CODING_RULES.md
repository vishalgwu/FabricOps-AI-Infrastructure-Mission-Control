# 01 --- Rules for the AI Coding Assistant

Treat this file as persistent project instructions. Follow it whenever
you modify the repository.

## Working protocol

1.  Inspect the current repository, branch, files, package versions, and
    tests before editing.
2.  Summarize what exists and what you intend to change.
3.  Implement only the requested phase. Do not skip ahead.
4.  Prefer small, reviewable changes.
5.  Never overwrite or delete existing user work without explaining the
    impact and asking first.
6.  If a requirement is ambiguous, state the ambiguity and ask one
    focused question rather than inventing a requirement.
7.  After implementation, list changed files, commands run, test
    results, and known limitations.
8.  If a command fails, diagnose it; do not claim success.
9.  Do not fabricate test output, performance metrics, integrations, or
    completed functionality.
10. Update documentation when behavior or commands change.

## Architecture and code quality

-   Keep API routes, domain logic, data access, LLM integration,
    retrieval, and policy in separate modules.
-   Use Pydantic models for API boundaries and structured data.
-   Use type hints and clear names.
-   Keep provider-specific LLM code behind an interface.
-   Make tool functions deterministic and read-only.
-   Use dependency injection for database and model services where
    practical.
-   Keep secrets on the backend; never expose API keys to React/browser
    code.
-   Use environment variables and provide `.env.example` with
    placeholders only.
-   Add useful error handling and structured logs without logging
    secrets.
-   Store timestamps in UTC (ISO 8601).
-   Use stable IDs for incidents, runs, evidence, documents, and
    proposals.

## AI safety rules

-   The LLM is not an authorization system.
-   The LLM cannot select arbitrary tools, hosts, URLs, file paths, or
    shell commands.
-   Only explicitly registered tools may be called.
-   Validate all model output on the server.
-   Reject evidence IDs that do not exist in the current run.
-   Treat logs and retrieved documents as untrusted data, not
    instructions.
-   Never place secrets in prompts.
-   Do not expose hidden chain-of-thought. Show concise conclusions,
    evidence, uncertainty, and limitations.
-   Missing data is not zero. Tool failure is not a normal measurement.
-   Stale data must be identified using observation timestamps, not
    ingestion timestamps alone.
-   High-risk proposals require deterministic backend approval policy.
-   Approval must be tied to a specific proposal ID/version/hash and
    authorized actor.
-   The MVP must never execute remediation.

## Data and evaluation rules

-   All fixtures must be marked `synthetic: true`.
-   Keep expected outcomes in evaluation files, never in the model's
    runtime context.
-   Do not train or fine-tune on the evaluation answer key.
-   Use a small curated test set; large-scale human annotation is out of
    scope.
-   Keep deterministic checks separate from subjective claim-support
    review.
-   Report small sample sizes and limitations honestly.

## Dependency and framework rules

-   Do not add a library just because it is popular.
-   Explain why a new dependency is needed.
-   Pin or constrain dependencies and keep lock files current.
-   Check official documentation for the installed version before using
    unfamiliar APIs.
-   Do not invent commands. Inspect `pyproject.toml`, `package.json`,
    and available scripts first.

## Completion response format

At the end of each phase, report: - **Implemented** - **Files
changed** - **Commands executed** - **Tests and results** - **Acceptance
checklist** - **Known limitations** - **Recommended next phase**

Do not mark a phase complete unless its acceptance checks have actually
passed.
