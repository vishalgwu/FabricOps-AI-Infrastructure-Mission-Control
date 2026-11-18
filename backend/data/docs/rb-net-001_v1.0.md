# Runbook RB-NET-001: Isolated link instability

> SYNTHETIC RUNBOOK: written for the FabricOps demo. It is not vendor documentation and makes no claim of real-world accuracy.

## Symptoms

One host reports rising `link_error_count` and repeated `link_retrain_count` events, with packet loss and higher network latency. Other hosts on the same fabric report normal counters.

## Scope the problem first

Compare the affected host with its peers over the same time window. If peers are healthy, treat the problem as isolated to the affected host and its own link. Do not generalize to the whole fabric, and do not run tests against healthy peers.

## Read-only diagnostics

Start with read-only checks on the affected host: read the error and retrain counters over time, read the link configuration (`link_speed_gbps`, `fec_mode`, `mtu`) and compare it with peers, and read the NIC log for retrain events. A configuration that differs from the peers is worth noting.

## Escalation

Physical causes such as a marginal cable, a connector or a transceiver are common for a single-host link problem, but counters alone cannot confirm them. Recommend a physical inspection or a controlled swap only as a proposal for a human to approve. Do not change link settings automatically.
