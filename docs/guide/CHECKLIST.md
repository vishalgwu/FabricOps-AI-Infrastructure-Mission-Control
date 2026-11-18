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

-   [ ] Phase 10: evaluation
-   [ ] Phase 11: security and reliability
-   [ ] Phase 12: release and demo

## Final proof

-   [x] Fresh-clone setup succeeds (backend tests, frontend build and lint; re-prove in Phase 12)
-   [ ] All automated tests pass
-   [ ] Three scenarios demonstrated
-   [x] Stale telemetry abstention demonstrated
-   [x] Evidence citations resolve (server-checked and openable in the UI)
-   [x] Approval decision persists
-   [x] No production remediation exists
-   [ ] README matches verified implementation
