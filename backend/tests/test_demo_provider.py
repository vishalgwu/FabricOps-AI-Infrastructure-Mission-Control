import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.llm.demo import DEMO_MODEL_ID, ScriptedDemoProvider, _answer
from app.llm.factory import create_provider
from app.llm.provider import ProviderRequest
from app.main import create_app


@pytest.fixture
def demo_client(tmp_path, monkeypatch):
    """The real app, configured the way a person trying it without an API key would configure it."""
    monkeypatch.setenv("FABRICOPS_LLM_PROVIDER", "demo")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()
    yield TestClient(create_app(str(tmp_path / "demo.db")))
    monkeypatch.undo()
    get_settings.cache_clear()


def run(client, scenario, hosts):
    # Use the scenario's own suggested incident, as the UI form does, so the runbook search finds its runbook.
    info = next(s for s in client.get("/api/scenarios").json() if s["scenario_type"] == scenario)
    inc = client.post("/api/incidents", json={
        "title": info["title"], "description": info["description"],
        "scenario_type": scenario, "severity": info["severity"], "affected_hosts": hosts}).json()
    started = client.post(f"/api/incidents/{inc['id']}/runs").json()
    return client.get(f"/api/runs/{started['id']}").json()


def test_the_demo_model_is_opt_in_never_the_default():
    assert Settings().llm_provider == "anthropic"
    assert isinstance(create_provider(Settings(llm_provider="demo")), ScriptedDemoProvider)
    assert create_provider(Settings(llm_provider="demo")).name == "demo"


def test_inference_slowdown_runs_end_to_end_with_the_demo_model(demo_client):
    r = run(demo_client, "inference_slowdown", ["gpu-h07"])
    assert r["status"] == "WAITING_APPROVAL" and r["model_id"] == DEMO_MODEL_ID and r["prompt_version"] == "investigator-v1"
    report = demo_client.get(f"/api/runs/{r['id']}/report").json()
    text = " ".join(o["text"] for o in report["observations"])
    assert "96 percent" in text and "54 percent" in text and "950 ms" in text  # numbers come from the evidence
    hyp = report["hypotheses"][0]
    assert "suspected" in hyp["statement"]
    assert any(c.startswith("opposing evidence:") for c in hyp["counterevidence"])
    assert any("disagree" in c for c in hyp["counterevidence"])
    assert report["citations"] and report["citations"][0].startswith("RB-KV-001:2.0:")
    prop = demo_client.get(f"/api/runs/{r['id']}/proposal").json()["proposal"]
    assert prop["risk_class"] == "controlled_test" and prop["approval_status"] == "pending" and prop["target_scope"] == ["gpu-h07"]


def test_the_demo_answer_always_says_it_is_a_script_not_an_ai(demo_client):
    for scenario, hosts in (("inference_slowdown", ["gpu-h07"]), ("link_instability", ["net-h01"])):
        r = run(demo_client, scenario, hosts)
        limitations = " ".join(demo_client.get(f"/api/runs/{r['id']}/report").json()["limitations"])
        assert "not by an AI" in limitations and "fixed script" in limitations


def test_the_log_injection_in_the_scenario_is_noted_as_data(demo_client):
    r = run(demo_client, "inference_slowdown", ["gpu-h07"])
    limitations = " ".join(demo_client.get(f"/api/runs/{r['id']}/report").json()["limitations"])
    assert "instruction-like text" in limitations and "treated as data" in limitations


def test_link_instability_runs_end_to_end_with_a_read_only_proposal(demo_client):
    r = run(demo_client, "link_instability", ["net-h01"])
    assert r["status"] == "COMPLETE" and r["model_id"] == DEMO_MODEL_ID
    prop = demo_client.get(f"/api/runs/{r['id']}/proposal").json()["proposal"]
    assert prop["risk_class"] == "read_only_diagnostic" and prop["approval_status"] == "not_required"
    assert prop["target_scope"] == ["net-h01"]


def test_stale_telemetry_still_abstains_before_the_demo_model_is_used(demo_client):
    r = run(demo_client, "stale_telemetry", ["gpu-h21"])
    assert r["status"] == "ABSTAINED" and r["model_id"] is None  # no model of any kind was called


def test_the_demo_model_goes_through_the_same_validation_as_a_real_one(demo_client):
    r = run(demo_client, "inference_slowdown", ["gpu-h07"])
    report = demo_client.get(f"/api/runs/{r['id']}/report").json()
    evidence = {e["id"] for e in demo_client.get(f"/api/runs/{r['id']}/evidence").json()}
    cited = {i for o in report["observations"] for i in o["evidence_ids"]}
    assert cited and cited <= evidence
    for cid in report["citations"]:
        assert demo_client.get(f"/api/documents/chunks/{cid}").status_code == 200


def test_the_numbers_in_the_text_follow_the_evidence_not_a_template():
    def rec(eid, host, metric, value, source="dcgm-synthetic"):
        return {"id": eid, "host_id": host, "source_type": "metric",
                "payload": {"metric": metric, "latest_value": value, "unit": "percent", "source": source}}

    pkg = {"incident": {"affected_hosts": ["h1"]}, "allowed_hosts": ["h1", "h2"], "documents": [],
           "evidence": [rec("e1", "h1", "kv_cache_used_pct", 71.5), rec("e2", "h2", "kv_cache_used_pct", 12)]}
    answer = _answer(pkg)
    assert "71.5 percent" in answer["observations"][0]["statement"] and "12 percent" in answer["observations"][0]["statement"]
    assert answer["observations"][0]["evidence_ids"] == ["e1", "e2"]
    assert answer["next_test"]["target_scope"] == ["h1"]


def test_unrecognised_evidence_makes_the_demo_model_abstain_rather_than_invent():
    pkg = {"incident": {"affected_hosts": ["h1"]}, "allowed_hosts": ["h1"], "documents": [],
           "evidence": [{"id": "e1", "host_id": "h1", "source_type": "metric",
                         "payload": {"metric": "packet_loss", "latest_value": 1, "unit": "percent", "source": "x"}}]}
    answer = _answer(pkg)
    assert answer["abstain"] is True and answer["hypotheses"] == [] and answer["next_test"] is None
    assert answer["missing_evidence"]


def test_the_provider_records_its_calls_and_labels_its_model():
    provider = ScriptedDemoProvider()
    body = {"incident": {"affected_hosts": ["h1"]}, "allowed_hosts": ["h1"], "documents": [], "evidence": []}
    user = "<evidence_package>\n" + json.dumps(body) + "\n</evidence_package>"
    out = provider.generate_investigation(ProviderRequest(system="s", user=user, json_schema={}, max_tokens=10))
    assert provider.calls == 1 and out.model_id == "scripted-demo-1" and json.loads(out.text)["abstain"] is True
