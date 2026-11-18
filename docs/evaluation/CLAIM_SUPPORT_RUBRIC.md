# Claim-Support Review Rubric

Automated checks can tell whether an evidence ID *exists*. They cannot tell whether the evidence
*supports* the claim it is attached to. A model can cite a real record that says nothing relevant, and
the system would accept it. This rubric is how a person checks that, on a small sample.

**Status: no review has been done yet.** It needs real model output, which needs an API key. Until a
review sheet is filled in, FabricOps makes no claim about whether its model's claims are supported.

## When to do it

1. Run the optional live smoke test (it makes real, billed requests):
   ```bash
   cd backend
   .venv/Scripts/python -m evals.live
   ```
   It runs each built-in scenario once and writes `backend/evals/live_runs/<time>-review-sheet.md`
   (git-ignored) listing every claim with the evidence IDs it cites.
2. Open each run in the UI (or the API), and click through every evidence ID in the review sheet.
3. Rate every claim using the scale below.
4. Count the ratings and record them in the table at the bottom of this file, with the date, the model
   ID and the prompt version. Re-do it whenever the prompt or model changes.

Review at least every claim in at least one run of each scenario (about 6 to 15 claims per run). It is
a small sample on purpose; it is a spot check, not a benchmark.

## Rating scale

Rate each claim on its own. Look only at the evidence it cites, not at what you know is "really" going on.

| Rating | Meaning |
|---|---|
| **S: Supported** | The cited records, read as stored, show what the claim says. Numbers, hosts and time ranges match. |
| **P: Partly supported** | Some of the claim is shown, but part is not (wrong number, wrong host, a detail that is not in the evidence, an overstated size). |
| **U: Unsupported** | The cited records do not show the claim, show the opposite, or the claim is about something no record covers. |
| **N: Not checkable** | The claim is too vague to test (for example "things look unusual"). Vague claims are a quality problem, so count them separately. |

## Rules of thumb

**Observations** (statements of fact) must match the records exactly.
- Check the host. A claim about gpu-h07 that cites a gpu-h08 record is U.
- Check the value and unit (`96 percent`, not `96 ms`) and the time (`observed_at`). A reading from hours ago described as "now" is P or U.
- A claim of "peers are normal" needs peer records cited. If none are cited it is at best P.
- A null or missing value is *unknown*. A claim that treats it as zero is U.

**Hypotheses** (explanations) are not facts, so rate whether they are *reasonable and honestly framed*:
- S if the supporting records plausibly fit the explanation **and** the hypothesis is worded as a suspicion, lists counterevidence, and does not claim certainty.
- P if the evidence fits but the wording overreaches ("is causing", "confirms").
- U if the cited evidence has no bearing on the explanation, or a cause is asserted that nothing shows.
- Correlation is not cause. "Latency rose and KV-cache use rose" supports "KV-cache pressure is a suspected contributor"; it does not support "KV-cache pressure caused the slowdown".

**Citations to documents:** open the passage. S only if the passage actually says what it is cited for. A real passage about a different topic is U (this is the case the system cannot catch on its own; see case E27 in the evaluation report).

**Contradictions:** if two sources disagree, a claim that quietly picks one is P at best. The report should say they disagree.

**Missing evidence:** the missing-evidence list on an abstention should name something that is actually missing. Rate it S if every item is true of the stored evidence.

## Worked example (an illustration, not a real review)

This uses the scripted example answer for the inference-slowdown scenario. The evidence values come
from the fixture: `kv_cache_used_pct` on gpu-h07 was 96 percent at 14:00Z; peers were near 54 percent.

| Claim | Cited | Rating | Why |
|---|---|---|---|
| "kv_cache_used_pct on gpu-h07 reached 96% while peers stayed near 54%." | gpu-h07 kv_cache record, gpu-h08 kv_cache record | **S** | Both records show those values, for the right hosts, at the same time. |
| "p95 latency on gpu-h07 rose to 950 ms." | gpu-h07 request_latency_p95 record | **S** | The record's latest value is 950 ms. |
| "The slowdown was caused by KV-cache exhaustion." | gpu-h07 kv_cache record | **U** | The record shows high cache use, not a cause. Certainty is also not allowed (the system rejects this wording outright). |
| "KV-cache pressure is a suspected contributor." (hypothesis; lists the memory-source disagreement as counterevidence) | gpu-h07 kv_cache and latency records | **S** | Fits the evidence, framed as a suspicion, shows what argues against it. |
| "Latency is typical for this time of day." | gpu-h08 latency record | **U** | No record covers time-of-day patterns. |

## Results log

Fill in after each review. Leave blank until a review has actually been done.

| Date | Model ID | Prompt version | Runs reviewed | Claims | S | P | U | N | Reviewer | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | |

Do not summarise this table as an accuracy rate in the README without also stating the number of claims
reviewed; with a few dozen claims, one rating changes the percentage a lot.
