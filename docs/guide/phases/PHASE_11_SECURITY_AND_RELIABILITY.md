# Phase 11 --- Security and Reliability Review

## Goal

Harden the local demo and verify that untrusted content cannot control
the application.

## Threats to test

-   Prompt injection in logs or documents.
-   Unknown host IDs.
-   Oversized time windows or result sets.
-   Malformed model output.
-   Fabricated evidence references.
-   Secret leakage in logs or frontend.
-   Duplicate run requests.
-   Invalid state transitions.
-   Unauthorized approval attempts.
-   Expired or modified proposals.
-   Database errors and provider timeouts.

## Required controls

-   Strict input validation.
-   Tool allowlist.
-   Host and time-range scope limits.
-   Output size limits.
-   Server-side policy enforcement.
-   Secret redaction.
-   Safe error messages.
-   Bounded retries/timeouts.
-   Persistent state transitions.
-   No arbitrary shell, URL, or file tools.
-   No remediation execution.

## AI coding prompt

"Perform a security and reliability review against Phase 11. First
inspect the code and produce a threat checklist. Then fix only confirmed
issues in small changes. Add regression tests for each fix. Do not add
real infrastructure connectors or execution capabilities. Report
unresolved risks honestly."

## Acceptance

-   [ ] Prompt injection cannot expand tool permissions.
-   [ ] Unknown hosts and oversized requests are rejected.
-   [ ] Secrets are not logged or exposed to frontend.
-   [ ] Unauthorized approvals fail server-side.
-   [ ] Changed/expired proposals cannot reuse approval.
-   [ ] Provider/tool failures are visible and bounded.
-   [ ] No remediation execution path exists.
