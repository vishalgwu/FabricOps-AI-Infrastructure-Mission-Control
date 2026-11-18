# Phase 09 --- Mission-Control UI and History

## Goal

Build a simple interface that exposes the actual investigation, evidence
and uncertainty.

## Pages/components

1.  Incident list and incident creation.
2.  Incident detail.
3.  Start investigation control.
4.  Run status and stage timeline.
5.  Evidence viewer.
6.  Hypothesis and counterevidence panel.
7.  Documentation citation viewer.
8.  Missing evidence and abstention explanation.
9.  Proposed next test and risk status.
10. Approval/rejection panel for the demo.
11. Run history.

## UX requirements

-   Clearly label synthetic data.
-   Distinguish observations from hypotheses.
-   Show evidence timestamps and host IDs.
-   Make citations clickable and resolvable.
-   Show loading, empty, failed, cancelled, abstained and waiting
    states.
-   Do not display a model confidence score as if it were calibrated
    truth.
-   Do not display hidden chain-of-thought.
-   Refresh must restore persisted state.
-   UI controls are not security boundaries; backend endpoints must
    validate every action.

## AI coding prompt

"Implement only Phase 09. Connect the React TypeScript UI to the real
FastAPI endpoints. Build incident intake, run timeline, evidence,
report, citations, proposal status and history views. Include
loading/error/empty/abstained states. Label all fixture data synthetic.
Do not use mocked success responses in the integrated workflow. Ensure
refresh loads persisted server state."

## Acceptance

-   [ ] User can create and view an incident.
-   [ ] User can start and inspect a run.
-   [ ] Evidence and citations resolve to actual records.
-   [ ] UI distinguishes facts, hypotheses and limitations.
-   [ ] Refresh preserves state.
-   [ ] Proposal decisions match backend state.
-   [ ] No secret appears in browser assets or network responses.
