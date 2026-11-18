# FabricOps Master Progress Checklist

Update this file as phases are completed. Only check an item after
verifying it.

## Planning

-   [ ] Read project spec (docs/mvp.md)
-   [x] Audit repository
-   [x] Confirm architecture and stack

## Foundation

-   [x] Phase 01: runnable backend/frontend
-   [x] Phase 02: schemas and synthetic fixtures
-   [x] Phase 03: persistence and incident API

## Investigation engine

-   [x] Phase 04: telemetry tools
-   [x] Phase 05: document retrieval and citations
-   [x] Phase 06: LLM investigator (mock-tested; real adapter not yet run live)
-   [x] Phase 07: controlled workflow

## Safe experience

-   [x] Phase 08: deterministic policy and approvals
-   [x] Phase 09: frontend and history

## Quality and release

-   [x] Phase 10: evaluation (scripted model; claim-support review and live smoke test not yet run)
-   [x] Phase 11: security and reliability (hardened for a local demo; unresolved risks are listed in docs/security/THREAT_REVIEW.md)
-   [x] Phase 12: release and demo (clean-clone check on Windows only; see docs/RELEASE_NOTES.md)

## Final proof

-   [x] Fresh-clone setup succeeds (clean clone, README commands only, Windows; see docs/RELEASE_NOTES.md)
-   [x] All automated tests pass (backend and frontend; re-confirm in Phase 12)
-   [x] Three scenarios demonstrated (inference and link with the scripted demo model, not a real model)
-   [x] Stale telemetry abstention demonstrated
-   [x] Evidence citations resolve (server-checked and openable in the UI)
-   [x] Approval decision persists
-   [x] No production remediation exists
-   [x] README matches verified implementation (test counts, links and images are checked by tests/test_release.py)
