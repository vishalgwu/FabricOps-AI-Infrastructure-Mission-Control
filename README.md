# FabricOps — AI Infrastructure Mission Control

FabricOps is an independent portfolio project. It shows how an AI copilot could help engineers investigate failures in infrastructure that runs AI workloads.

> **Disclaimer.** FabricOps is not affiliated with, endorsed by, or a product of any hardware or infrastructure vendor. It makes no claim of production accuracy.
>
> **Synthetic-data policy.** All incidents, telemetry, configuration and runbooks in this repository are synthetic and labeled as such. No real customer, vendor or production data is used. Live telemetry connectors and real remediation are out of scope.

## The idea

When inference slows down or a hardware link becomes unstable, engineers have to piece together telemetry, configuration and technical documentation by hand. FabricOps brings that evidence into one persistent investigation and proposes a next diagnostic step that the engineer can review.

An investigation ends in one of two ways:

- a **supported recommendation**, with cited evidence and a bounded next test, or
- an **abstention**: an explicit request for the missing evidence. It never claims a root cause it cannot support.

Risky proposals pause for **human approval**. In the MVP, FabricOps only *proposes* actions; it never executes remediation.

## What a demo looks like

1. **Pick an incident.** For example: model responses have slowed down and telemetry suggests KV-cache memory pressure.
2. **Follow the investigation.** The dashboard shows which signals were checked, what they suggest, and what is missing.
3. **Review the proposed next step.** The copilot suggests a controlled experiment to test the suspected cause. If evidence is thin it says so, and higher-risk proposals wait for approval.

Three scenarios are planned: inference slowdown, isolated link instability, and stale or missing telemetry. See [docs/mvp.md](docs/mvp.md) for the specification.

## Scope

FabricOps is the **general investigation platform**:

- incident intake
- typed, read-only telemetry tools
- document retrieval with citations
- model-backed investigation with validated, evidence-linked output
- deterministic policy gates and approval workflow
- durable investigation history and reports
- evaluation of whether conclusions are supported by evidence

**Not in scope:** the KV-cache performance benchmarking study (a separate project; FabricOps may later ingest a versioned benchmark report), unattended production remediation, live production telemetry connectors, and multi-agent orchestration.

## Status

| Area | Status |
|---|---|
| Repository and project specification | In progress (Step 1 of 14) |
| Visual prototype (scripted, synthetic) | **Unverified** — not in this repository; will be recovered and reviewed before any UI is reimplemented |
| Fixtures, tools, retrieval, agent runtime, UI, approvals, evaluation | Not started |

No application code, tests, or deployment exist yet. Nothing here should be read as a working system until the matching step in the roadmap is accepted.

## Roadmap

A 14-step build plan in four milestones:

- **A (Steps 1–4):** specification, runnable scaffold, synthetic fixtures, durable intake
- **B (Steps 5–8):** tools, retrieval, model reasoning, bounded resumable workflow
- **C (Steps 9–11):** approvals, mission-control UI, history and observable runs
- **D (Steps 12–14):** evaluation, hardening, reproducible release

## Planned stack (not yet installed)

TypeScript with the eve agent runtime, a web client for the UI, schema-validated tools, local persistent storage behind an adapter, AI Gateway model selection, and a versioned local document corpus. The stack is confirmed at Step 2.
