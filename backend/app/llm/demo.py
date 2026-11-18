"""A SCRIPTED demo model. It is not an AI.

It exists so the whole application can be demonstrated, and a fresh clone verified, without an API
key. It reads the evidence package exactly as a real model would receive it and returns a fixed
style of answer, with the numbers and IDs filled in from that evidence. The answer then goes through
the same validation, policy and approval pipeline as a real model's answer would.

Every answer says so in its limitations, the run records the model ID `scripted-demo-1`, and the UI
shows a banner on runs it produced. Select it with FABRICOPS_LLM_PROVIDER=demo. It is never the default.
"""
import json
from typing import Any

from app.llm.provider import ProviderRequest, ProviderResponse

DEMO_MODEL_ID = "scripted-demo-1"
DEMO_NOTICE = ("This answer was written by a fixed script (the demo model), not by an AI. It exists so the "
               "application can be demonstrated without an API key.")


def _package(req: ProviderRequest) -> dict[str, Any]:
    return json.loads(req.user.split("<evidence_package>\n", 1)[1].rsplit("\n</evidence_package>", 1)[0])


def _latest(evidence: list[dict], host: str, metric: str) -> dict | None:
    """The first evidence record for this host and metric (preferring the main source)."""
    found = [e for e in evidence if e["host_id"] == host and e["payload"].get("metric") == metric]
    return sorted(found, key=lambda e: e["payload"].get("source", ""))[0] if found else None


def _value(rec: dict | None) -> str:
    if rec is None or rec["payload"].get("latest_value") is None:
        return "no value"
    v = rec["payload"]["latest_value"]
    return f"{v:g} {rec['payload'].get('unit', '')}".strip()


def _peers(records: list[dict]) -> str:
    return ", ".join(f"{r['host_id']} {_value(r)}" for r in records) or "no reading"


def _answer(pkg: dict) -> dict[str, Any]:
    ev = pkg["evidence"]
    affected = pkg["incident"]["affected_hosts"]
    host = affected[0]
    peers = [h for h in pkg["allowed_hosts"] if h not in affected]
    docs = pkg["documents"]
    limitations = [DEMO_NOTICE]
    if any("ignore all previous instructions" in str(e["payload"].get("message", "")).lower() for e in ev):
        limitations.append("A log line contained instruction-like text. It was treated as data and not followed.")
    sources = {e["payload"].get("source") for e in ev
               if e["host_id"] == host and e["payload"].get("metric") == "gpu_memory_used"}
    disagree = len(sources) > 1

    if _latest(ev, host, "kv_cache_used_pct"):  # the inference-slowdown scenario
        kv, lat = _latest(ev, host, "kv_cache_used_pct"), _latest(ev, host, "request_latency_p95")
        peer_kv = [r for p in peers if (r := _latest(ev, p, "kv_cache_used_pct"))]
        peer_lat = [r for p in peers if (r := _latest(ev, p, "request_latency_p95"))]
        cite = [d["id"] for d in docs if d["document_id"] == "RB-KV-001"][:1]
        compare = peers[0] if peers else host
        return {
            "observations": [
                {"statement": f"kv_cache_used_pct on {host} was {_value(kv)} at its latest reading; "
                              f"peers were at {_peers(peer_kv)}.",
                 "evidence_ids": [kv["id"]] + [r["id"] for r in peer_kv]},
                {"statement": f"request_latency_p95 on {host} was {_value(lat)}; "
                              f"peers were at {_peers(peer_lat)}.",
                 "evidence_ids": ([lat["id"]] if lat else []) + [r["id"] for r in peer_lat]},
            ],
            "hypotheses": [{
                "statement": f"KV-cache memory pressure on {host} is a suspected contributor to the slowdown.",
                "supporting_evidence_ids": [kv["id"]] + ([lat["id"]] if lat else []),
                "opposing_evidence_ids": [r["id"] for r in peer_kv],
                "counterevidence": (["Two telemetry sources disagree about gpu_memory_used on this host; "
                                     "the disagreement is unresolved."] if disagree else [])
                + ["High cache use and high latency rose together, which does not show that one caused the other."],
                "confidence": "medium",
                "uncertainty": "Batch size, sequence length and traffic mix have not been separated.",
                "citations": cite}],
            "missing_evidence": [],
            "next_test": {
                "description": f"Halve batch_size on {host} only and compare latency with {compare} for 15 minutes.",
                "target_scope": [host], "risk_class": "controlled_test"},
            "abstain": False, "abstain_reason": "", "limitations": limitations, "document_citations": cite,
        }

    err = _latest(ev, host, "link_error_count")
    if err:  # the link-instability scenario
        peer_err = [r for p in peers if (r := _latest(ev, p, "link_error_count"))]
        retrain = _latest(ev, host, "link_retrain_count")
        cite = [d["id"] for d in docs if d["document_id"] == "RB-NET-001"][:1]
        return {
            "observations": [
                {"statement": f"link_error_count on {host} was {_value(err)}; peers were at "
                              f"{_peers(peer_err)}.",
                 "evidence_ids": [err["id"]] + [r["id"] for r in peer_err]},
                *([{"statement": f"link_retrain_count on {host} was {_value(retrain)}.",
                    "evidence_ids": [retrain["id"]]}] if retrain else []),
            ],
            "hypotheses": [{
                "statement": f"An isolated link problem on {host} is suspected. The peers look healthy.",
                "supporting_evidence_ids": [err["id"]] + ([retrain["id"]] if retrain else []),
                "opposing_evidence_ids": [],
                "counterevidence": ["Counters alone cannot show whether the cause is a cable, a connector, a "
                                    "transceiver or a setting."],
                "confidence": "medium", "uncertainty": "The physical cause is unknown.", "citations": cite}],
            "missing_evidence": [],
            "next_test": {
                "description": f"Read the NIC log on {host} for retrain events and compare its link configuration "
                               "with its peers.",
                "target_scope": [host], "risk_class": "read_only_diagnostic"},
            "abstain": False, "abstain_reason": "", "limitations": limitations, "document_citations": cite,
        }

    # Nothing it knows how to read: say so rather than invent something.
    return {"observations": [], "hypotheses": [],
            "missing_evidence": ["The demo model only understands the built-in scenarios."],
            "next_test": None, "abstain": True,
            "abstain_reason": "The demo model has no script for this evidence.",
            "limitations": limitations, "document_citations": []}


class ScriptedDemoProvider:
    name = "demo"

    def __init__(self) -> None:
        self.requests: list[ProviderRequest] = []

    @property
    def calls(self) -> int:
        return len(self.requests)

    def generate_investigation(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        return ProviderResponse(text=json.dumps(_answer(_package(request))), model_id=DEMO_MODEL_ID, latency_ms=1.0,
                                usage={}, request_id=None)
