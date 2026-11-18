# Runbook RB-KV-001: KV-cache memory pressure on inference hosts

> SYNTHETIC RUNBOOK: written for the FabricOps demo. It is not vendor documentation and makes no claim of real-world accuracy.

## Symptoms

Response latency on a single serving host rises over tens of minutes while peer hosts stay flat. Throughput in requests per second falls at the same time. GPU utilization is high. The `kv_cache_used_pct` metric climbs toward its ceiling, and the serving log reports a rising KV-cache eviction rate with requests being re-prefilled.

These symptoms are consistent with KV-cache memory pressure, but they do not prove it. Long sequences, an oversized batch size, or a change in traffic mix can produce the same pattern.

## What to compare

Compare the affected host with healthy peers that serve the same model. Check `kv_cache_used_pct`, `gpu_memory_used`, `request_latency_p95` and the serving configuration (`batch_size`, `max_sequence_length`). A host whose batch size is larger than its peers is a stronger candidate than one with identical configuration.

If two telemetry sources disagree about memory use, record the disagreement and resolve it before drawing a conclusion.

## Controlled test

Propose a controlled test on the affected host only: reduce `batch_size` by half, hold traffic steady, and watch `kv_cache_used_pct` and `request_latency_p95` for at least fifteen minutes. Compare against an untouched peer. If latency recovers, KV-cache pressure becomes a better supported explanation. If nothing changes, the hypothesis is weakened.

Do not restart the serving process as a first step. A restart destroys the evidence and is a write action that needs approval.

## Limits of this runbook

This runbook covers a single affected host. If several hosts show the same pattern at once, look for a shared cause such as a traffic change or a deployment before assuming memory pressure.
