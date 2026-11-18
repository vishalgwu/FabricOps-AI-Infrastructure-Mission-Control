import json

import pytest
from fastapi.testclient import TestClient

from app.llm.mock import MockProvider
from app.main import create_app

READ_ONLY = "Read the host's recent logs and compare with peers."


def answer(req):
    body = json.loads(req.user.split("<evidence_package>\n", 1)[1].rsplit("\n</evidence_package>", 1)[0])
    affected = body["incident"]["affected_hosts"]
    ids = [e["id"] for e in body["evidence"] if e["host_id"] in affected and e["source_type"] == "metric"]
    docs = [d["id"] for d in body["documents"]][:1]
    return {
        "observations": [{"statement": "A metric on the affected host differs from its peers.",
                          "evidence_ids": ids[:2]}],
        "hypotheses": [{"statement": "A resource problem on the affected host is suspected.",
                        "supporting_evidence_ids": ids[:1], "opposing_evidence_ids": [], "counterevidence": [],
                        "confidence": "medium", "uncertainty": "cause not isolated", "citations": docs}],
        "missing_evidence": [],
        "next_test": {"description": READ_ONLY, "target_scope": affected, "risk_class": "read_only_diagnostic"},
        "abstain": False, "abstain_reason": "", "limitations": [], "document_citations": docs,
    }


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(str(tmp_path / "ui.db"), provider=MockProvider(answer)))


def run_one(client, scenario="inference_slowdown", hosts=("gpu-h07",), title="t"):
    inc = client.post("/api/incidents", json={
        "title": title, "description": "Responses are slow on the affected host.", "scenario_type": scenario,
        "severity": "high", "affected_hosts": list(hosts)}).json()
    run = client.post(f"/api/incidents/{inc['id']}/runs").json()
    return inc, client.get(f"/api/runs/{run['id']}").json()


# ---- scenarios ----

def test_scenarios_are_listed_with_hosts_and_a_suggested_incident(client):
    r = client.get("/api/scenarios")
    assert r.status_code == 200
    items = r.json()
    assert [s["scenario_type"] for s in items] == ["inference_slowdown", "link_instability", "stale_telemetry"]
    s1 = items[0]
    assert s1["synthetic"] is True and s1["suggested_affected_hosts"] == ["gpu-h07"]
    assert {h["id"] for h in s1["hosts"]} == {"gpu-h07", "gpu-h08", "gpu-h09"}
    assert s1["title"] and s1["description"]


def test_scenario_listing_never_leaks_the_answer_key(client):
    blob = client.get("/api/scenarios").text.lower()
    for forbidden in ("expected_status", "must_abstain", "acceptable_hypothesis_themes", "forbidden"):
        assert forbidden not in blob


# ---- run history ----

def test_run_history_lists_runs_newest_first_with_incident_context(client):
    _, a = run_one(client, title="first")
    _, b = run_one(client, "stale_telemetry", ("gpu-h21",), title="second")
    r = client.get("/api/runs").json()
    assert r["total"] == 2 and [i["id"] for i in r["items"]] == [b["id"], a["id"]]
    top = r["items"][0]
    assert top["incident_title"] == "second" and top["scenario_type"] == "stale_telemetry"
    assert top["status"] == "ABSTAINED" and r["items"][1]["status"] == "COMPLETE"


def test_run_history_pagination_and_empty_state(client):
    assert client.get("/api/runs").json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
    for n in range(3):
        run_one(client, title=f"t{n}")
    page = client.get("/api/runs?limit=2&offset=2").json()
    assert page["total"] == 3 and len(page["items"]) == 1
    assert client.get("/api/runs?limit=0").status_code == 422
    assert client.get("/api/runs?offset=-1").status_code == 422


# ---- evidence ----

def test_evidence_list_and_single_resolve_to_stored_records(client):
    _, run = run_one(client)
    evidence = client.get(f"/api/runs/{run['id']}/evidence").json()
    assert evidence and all(e["run_id"] == run["id"] and e["synthetic"] for e in evidence)
    assert all(e["host_id"] and e["observed_at"] and e["ingested_at"] and e["tool_name"] for e in evidence)
    one = client.get(f"/api/runs/{run['id']}/evidence/{evidence[0]['id']}")
    assert one.status_code == 200 and one.json() == evidence[0]


def test_every_evidence_id_cited_in_the_report_resolves(client):
    _, run = run_one(client)
    report = client.get(f"/api/runs/{run['id']}/report").json()
    cited = {i for o in report["observations"] for i in o["evidence_ids"]}
    cited |= {i for h in report["hypotheses"] for i in h["supporting_evidence_ids"]}
    assert cited
    for eid in cited:
        assert client.get(f"/api/runs/{run['id']}/evidence/{eid}").status_code == 200


def test_every_citation_in_the_report_resolves_to_a_document_chunk(client):
    _, run = run_one(client)
    report = client.get(f"/api/runs/{run['id']}/report").json()
    assert report["citations"]
    for cid in report["citations"]:
        chunk = client.get(f"/api/documents/chunks/{cid}")
        assert chunk.status_code == 200
        c = chunk.json()
        assert c["id"] == cid and c["source"] and c["version"] and c["text"] and c["status"] == "current"


def test_evidence_of_another_run_does_not_resolve(client):
    _, a = run_one(client, title="a")
    _, b = run_one(client, "link_instability", ("net-h01",), title="b")
    ev_a = client.get(f"/api/runs/{a['id']}/evidence").json()[0]["id"]
    r = client.get(f"/api/runs/{b['id']}/evidence/{ev_a}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_unknown_run_evidence_and_chunk_are_404(client):
    assert client.get("/api/runs/run_missing/evidence").status_code == 404
    assert client.get("/api/runs/run_missing/evidence/ev_x").status_code == 404
    _, run = run_one(client)
    assert client.get(f"/api/runs/{run['id']}/evidence/ev_missing").status_code == 404
    assert client.get("/api/documents/chunks/RB-FAKE-999:1.0:x:0").status_code == 404


def test_run_with_no_evidence_returns_an_empty_list(client):
    _, run = run_one(client, "stale_telemetry", ("gpu-h21",))
    assert run["status"] == "ABSTAINED"
    assert client.get(f"/api/runs/{run['id']}/evidence").json() == []


def test_superseded_document_chunks_still_resolve_but_are_flagged(client):
    old = client.get("/api/documents/chunks/RB-KV-001:1.0:recommended-action:0")
    assert old.status_code == 200 and old.json()["status"] == "superseded" and old.json()["version"] == "1.0"


def test_new_routes_are_in_the_openapi_schema(client):
    paths = set(client.get("/openapi.json").json()["paths"])
    assert {"/api/scenarios", "/api/runs", "/api/runs/{run_id}/evidence",
            "/api/runs/{run_id}/evidence/{evidence_id}", "/api/documents/chunks/{chunk_id}"} <= paths


def test_no_secret_appears_in_any_response(tmp_path, monkeypatch):
    """Phase 09 acceptance: no secret in network responses. Put a recognisable key in the backend's
    environment, run a whole investigation, read every endpoint, and look for it."""
    from app.core.config import get_settings

    secret = "sk-ant-TOPSECRET-0123456789"
    monkeypatch.setenv("FABRICOPS_LLM_API_KEY", secret)
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    get_settings.cache_clear()
    try:
        assert get_settings().llm_api_key.get_secret_value() == secret  # it really is loaded
        client = TestClient(create_app(str(tmp_path / "s.db"), provider=MockProvider(answer)))
        inc, run = run_one(client)
        urls = ["/health", "/openapi.json", "/api/scenarios", "/api/incidents", f"/api/incidents/{inc['id']}",
                f"/api/incidents/{inc['id']}/runs", "/api/runs", f"/api/runs/{run['id']}",
                f"/api/runs/{run['id']}/events", f"/api/runs/{run['id']}/report",
                f"/api/runs/{run['id']}/evidence", f"/api/runs/{run['id']}/proposal",
                "/api/documents/chunks/RB-KV-001:2.0:symptoms:0", "/api/runs/run_missing", "/api/incidents/inc_x"]
        for url in urls:
            r = client.get(url)
            assert secret not in r.text and "TOPSECRET" not in r.text, url
            assert not any(secret in v for v in r.headers.values()), url
        for key in ("sk-ant", "api_key", "LLM_API_KEY"):
            assert key.lower() not in client.get(f"/api/runs/{run['id']}/events").text.lower()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
