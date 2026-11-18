# Five-Minute Demo Script

Everything shown is synthetic. This script works **without an API key** by using the scripted demo model
(`FABRICOPS_LLM_PROVIDER=demo`), which is a fixed script, **not an AI**. If you have a key, the same clicks work
with the real model; its wording will differ, and the first two rules below still hold.

**Two rules for whoever presents this**
1. Say out loud, early, that the data is fabricated and, in demo mode, that the "model" is a script. The UI says it too (the dark banner on every page, and a grey "Scripted demo model" box on every run it produced).
2. Do not claim the answers show how good an AI is. What this demo shows is the **system around the model**: evidence handling, abstention, validation, policy and approval.

## Before you start (2 minutes, once)

Follow the README quick start, then start both servers with the demo model:

```bash
# terminal 1: backend (macOS/Linux; on Windows use .venv\Scripts\python and the PowerShell line in the README)
cd backend
FABRICOPS_LLM_PROVIDER=demo .venv/bin/python -m uvicorn app.main:app --port 8000

# terminal 2: frontend
cd frontend
npm run dev
```

Open <http://localhost:5173>. To reset to an empty state, stop the backend and delete `backend/data/fabricops.db`.

Pre-flight: the top right says "Backend ok". The Incidents page opens with a "Create an incident" form already filled in.

## The script

| Time | Do | Say | You should see |
|---|---|---|---|
| 0:00 | Open **Incidents**. Point at the banner. | "All of this is synthetic: fabricated telemetry and runbooks. FabricOps only proposes next steps. It has no way to run anything." | The dark banner; the form pre-filled with *Inference latency rising on gpu-h07*. |
| 0:30 | Click **Create incident**, then **Start investigation**. | "One click collects read-only telemetry, finds the matching runbook, and asks for hypotheses." | The run page; stages tick off in about a second. |
| 1:00 | Scroll to **Evidence collected**. Click the ID in a `kv_cache_used_pct` row. | "These are the actual records the tools returned, with the host and when each reading was observed, kept separate from when we collected it." | The side panel: host, *Observed at* (2026-03-10, the fixture's time) and *Collected at* (today), the stored payload. |
| 1:30 | Click the `RB-KV-001:2.0:…` chip under **Hypotheses**. | "A citation is not decoration: it opens the exact runbook passage, version and source. An ID that does not exist would show as an error here." | The passage, `Version 2.0`, source file, a "synthetic runbook" tag. |
| 2:00 | Read **Facts from the evidence**, then **Hypotheses**. | "Facts are what the records show. The hypothesis is worded as a suspicion and lists what argues against it, including two memory sources that disagree. The stated confidence is labelled not calibrated." | Separate sections; the amber *Counterevidence and unknowns* box; the "Scripted demo model" note. |
| 2:30 | Look at **Proposed next step**. | "A bounded test on one host only. The backend, not the model, set this risk class. A change like this needs a human." | *Controlled test*, *Waiting for a decision*, target host `gpu-h07`, and "Nothing is executed". |
| 3:00 | Go to **Incidents**, pick **Stale or missing telemetry** in the scenario box, **Create incident**, **Start investigation**. | "Now the same thing with data that is 4 hours old and a peer with none." | An *Abstained* run in about a second, "No model call was made". |
| 3:30 | Read **What is missing**. | "It does not guess. It says which host is stale, and that there is no peer to compare against. The model was never even called." | The two missing-evidence lines; no hypotheses section. |
| 3:45 | Back on the inference run (Run history). Type a reason, click **Approve**. | "Approval is tied to this exact proposal's fingerprint. Change anything and it no longer applies. And approving only records a decision." | *Approved by demo-reviewer*, the run becomes *Complete*, the form disappears. |
| 4:15 | Press refresh. Then stop the backend, start it again, refresh again. | "Everything came back from the database, including the decision." | Same page, same decision, same history. (Runs that were mid-flight when a server stops are marked failed at startup rather than hanging.) |
| 4:30 | Open **Run history**, then in a terminal run `cd backend && .venv/bin/python -m evals`. Show `docs/evaluation/EVAL_REPORT.md`. | "29 cases, each with its expected behaviour written down outside the model's input. All pass. This measures the safeguards, not a model. The sample is tiny and I wrote it, so read the counts, not a percentage." | `Cases where every check passed: 29/29`, and the report's "Read this first" section. |
| 4:50 | Close. | "What it cannot do yet: it has not run against the real model here, nothing checks a cited passage is relevant, and there is no login. Those are in the README and the security review." | |

## If you have an API key

Set `FABRICOPS_LLM_API_KEY` (or `ANTHROPIC_API_KEY`) instead of `FABRICOPS_LLM_PROVIDER=demo`, and run the same script. The
"Scripted demo model" box will not appear. Wording, observations and the proposal will differ and may be rejected by the
validator (the run then shows *Failed* with the reason), which is also worth showing. This path has not been run by the
project's author; see the README.

## Reproducibility notes

- The demo model is deterministic: the same fixture gives the same analysis, with numbers filled in from the stored evidence.
- Incident, run and evidence IDs are different each time; the content is not.
- Timestamps in evidence are the fixture's (2026-03-10). "Collected" times are the current time.
- Both servers must be running for the UI to work. The label at the top right shows the backend's state.

## If something goes wrong

| Symptom | Cause and fix |
|---|---|
| "Backend unreachable" | Backend not running, or not on port 8000. Start it, or set `VITE_API_BASE_URL` in `frontend/.env` and restart the frontend. |
| The run ends *Failed* with "no API credentials" | You did not set `FABRICOPS_LLM_PROVIDER=demo` (or a key) in the backend's environment. Restart the backend with it. |
| Start button says an investigation is already in progress | A run for that incident is waiting for approval. Open it, or decide it. |
| Approve is greyed out | The reason box is empty. |
| A stale-telemetry run abstains but the others fail | Same as the credentials row: only the stale scenario works with no model configured. |
