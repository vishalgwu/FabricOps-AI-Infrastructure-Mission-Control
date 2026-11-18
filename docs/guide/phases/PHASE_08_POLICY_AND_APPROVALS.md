# Phase 08 --- Deterministic Policy and Approval

## Goal

Make sure the model cannot authorize risky actions.

## Proposal categories

-   `READ_ONLY_DIAGNOSTIC`: a safe read-only investigation step.
-   `CONTROLLED_TEST_PROPOSAL`: a proposed test that could affect a
    scoped environment.
-   `WRITE_OR_DEPLOY`: any change, restart, deployment, or remediation
    class.

The MVP may describe these categories, but it must not execute them.
Write/deploy proposals are always blocked from execution.

## Policy behavior

-   Backend code classifies proposal risk.
-   High-risk proposals enter `WAITING_APPROVAL` or a blocked state.
-   Approval requires an authorized actor in the application model.
-   Store proposal ID, version/hash, target scope, parameters, evidence
    references, expiry, actor, time and reason.
-   If proposal parameters or material evidence change, invalidate the
    previous approval.
-   Approve/reject operations must be idempotent.
-   Rejection must not trigger execution.

For a local portfolio demo, a clearly labelled demo reviewer identity
may be used, but do not claim production authentication.

## AI coding prompt

"Implement only Phase 08. Add a deterministic backend policy module and
persisted proposal/decision records. The model may suggest a proposal
but cannot decide authorization. Require approval for designated
controlled-test proposals and block all write/deploy execution. Bind
decisions to proposal hash/version and expiry. Add tests for
unauthorized, expired, changed, duplicate and rejected proposals. There
must be no execution adapter."

## Acceptance

-   [ ] Policy is independent of LLM output.
-   [ ] High-risk proposals cannot auto-approve.
-   [ ] Approvals bind to proposal hash/version.
-   [ ] Expired or changed proposals cannot reuse approval.
-   [ ] Decisions persist after restart.
-   [ ] No action execution code exists.
