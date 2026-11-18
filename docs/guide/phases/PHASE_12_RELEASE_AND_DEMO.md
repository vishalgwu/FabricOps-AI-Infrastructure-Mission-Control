# Phase 12 --- Documentation, Reproducible Release and Demo

## Goal

Make the project easy for another engineer or recruiter to understand,
run, inspect and evaluate.

## README content

-   Problem and intended user.
-   What FabricOps does and does not do.
-   Architecture diagram.
-   Technology stack.
-   Prerequisites.
-   Exact installation and startup commands.
-   Environment variable setup.
-   Synthetic data disclaimer.
-   API overview.
-   Test and evaluation commands.
-   Screenshots or short demo recording.
-   Known limitations.
-   Security limitations.
-   Future work.

## Five-minute demo script

1.  Open the incident dashboard and explain that data is synthetic.
2.  Submit the inference slowdown incident.
3.  Show collected metrics and timestamps.
4.  Show retrieved documentation and citations.
5.  Show hypotheses with supporting and opposing evidence.
6.  Show a bounded next diagnostic proposal.
7.  Demonstrate the stale telemetry case and correct abstention.
8.  Demonstrate an approval-required proposal and persisted decision.
9.  Refresh/reopen history to prove persistence.
10. Show evaluation results and explain limitations.

## Fresh-clone test

Use a clean clone or separate directory. Follow only README
instructions. Do not rely on undocumented local files.

## AI coding prompt

"Implement only Phase 12. Review the application against all acceptance
gates. Update README and architecture documentation to match actual
behavior. Add exact setup, run, test and evaluation commands. Prepare a
five-minute demo script. Verify a fresh clone. Do not claim features
that are not implemented or tests that were not run."

## Acceptance

-   [x] Fresh clone works from documented instructions.
-   [x] Tests and evaluation commands work.
-   [x] Demo scenarios are reproducible.
-   [x] Synthetic data is clearly labelled.
-   [x] Known limitations are documented.
-   [x] Git history contains meaningful milestone commits.
-   [x] Final release describes only verified functionality.
