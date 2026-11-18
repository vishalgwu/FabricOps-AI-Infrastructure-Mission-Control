# Runbook RB-KV-001: KV-cache memory pressure on inference hosts (SUPERSEDED)

> SYNTHETIC RUNBOOK: written for the FabricOps demo. This version is superseded by version 2.0 and is kept to test version handling.

## Symptoms

When latency rises on a serving host and `kv_cache_used_pct` is high, the cause is KV-cache memory pressure.

## Recommended action

Restart the serving process on the affected host immediately. This clears the cache and restores latency. No comparison with peers is needed.
