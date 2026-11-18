# Runbook RB-TEL-001: Stale or missing telemetry

> SYNTHETIC RUNBOOK: written for the FabricOps demo. It is not vendor documentation and makes no claim of real-world accuracy.

## When telemetry cannot be trusted

Telemetry is stale when its observation time is older than the freshness threshold, regardless of when it was ingested. Telemetry is missing when a source returns nothing, or returns null values. A null value means unknown. It does not mean zero.

## What to do first

Do not diagnose a hardware or software cause from stale or missing data. State which evidence is missing: which host, which metric, and which time window. Recommend restoring visibility first, for example verifying that the metrics exporter on the host is running and that the monitoring pipeline is delivering data.

## Peers and baselines

If the peer hosts have no data either, there is no baseline for comparison, and the investigation should stop at the visibility problem. A comparison between a host with data and a host without data is not a comparison.

## After visibility returns

Re-run the investigation with fresh data. The earlier abstention remains part of the record.
