import json
import sqlite3
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import build_proposal_service
from app.domain.fixture_loader import load_all_fixtures
from app.llm.mock import MockProvider
from app.llm.provider import TransientProviderError
from app.main import create_app
from app.retrieval.index import load_corpus
from app.schemas.common import RunStatus
from app.schemas.domain import Run
from app.services.services import RunService
from app.storage.db import Database
from app.storage.repositories import EvidenceRepository, IncidentRepository, RunRepository
from app.workflow.engine import InvestigationWorkflow, WorkflowLimits

BACKEND = Path(__file__).resolve().parents[1]
SCENARIOS = {
    "inference_slowdown": ["gpu-h07"],
    "link_instability": ["net-h01"],
    "stale_telemetry": ["gpu-h21"],
}


def answer(req):
    """A valid model answer built from IDs found in the prompt (run IDs are not known up front)."""
    body = json.loads(req.user.split("<evidence_package>\n", 1)[1].rsplit("\n</evidence_package>", 1)[0])
    affected = body["incident"]["affected_hosts"]
    metric_ids = [e["id"] for e in body["evidence"] if e["host_id"] in affected and e["source_type"] == "metric"]
    docs = [d["id"] for d in body["documents"]][:1]
    return {
        "observations": [{"statement": "A metric on the affected host moved away from its peers.",
                          "evidence_ids": metric_ids[:2]}],
        "hypotheses": [{"statement": "A resource or link problem on the affected host is suspected.",
                        "supporting_evidence_ids": metric_ids[:1], "opposing_evidence_ids": [],
                        "counterevidence": [], "confidence": "medium", "uncertainty": "cause not isolated",
                        "citations": docs}],
        "missing_evidence": [],
        "next_test": {"description": "Read the host's recent logs and compare with peers.",
                      "target_scope": affected, "risk_class": "read_only_diagnostic"},
        "abstain": False, "abstain_reason": "", "limitations": [], "document_citations": docs,
    }


def make(tmp_path, *script, limits=None, **kw):
    provider = MockProvider(*(script or (answer,)))
    app = create_app(str(tmp_path / "wf.db"), provider=provider, workflow_limits=limits, **kw)
    return TestClient(app), provider, app


def new_incident(client, scenario="inference_slowdown", hosts=None):
    body = {"title": f"{scenario} test", "description": "Responses are slow on the affected host.",
            "scenario_type": scenario, "severity": "high", "affected_hosts": hosts or SCENARIOS[scenario]}
    return client.post("/api/incidents", json=body).json()


def start(client, incident, key=None):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post(f"/api/incidents/{incident['id']}/runs", headers=headers)


def finished(client, run_id):
    return client.get(f"/api/runs/{run_id}").json()


def events(client, run_id, after=0):
    return client.get(f"/api/runs/{run_id}/events?after_seq={after}").json()["events"]


def stage_names(evs, kind="stage_completed"):
    return [json.loads(e["detail"])["stage"] for e in evs if e["event_type"] == kind]


STAGES = ["load_incident", "validate_scope", "collect_telemetry", "check_freshness", "persist_evidence",
          "retrieve_docs", "investigate", "apply_policy", "persist_report"]


# ---- normal workflow reaches a valid terminal state ----

@pytest.mark.parametrize("scenario", ["inference_slowdown", "link_instability"])
def test_normal_run_completes_and_persists_everything(tmp_path, scenario):
    client, provider, app = make(tmp_path)
    inc = new_incident(client, scenario)
    r = start(client, inc)
    assert r.status_code == 202 and r.json()["status"] == "CREATED"
    run = finished(client, r.json()["id"])
    assert run["status"] == "COMPLETE" and run["error_code"] is None and run["finished_at"]
    assert run["model_id"] == "mock-model-1" and run["prompt_version"] == "investigator-v1"
    assert provider.calls == 1  # the model is called exactly once
    evs = events(client, run["id"])
    assert stage_names(evs) == STAGES and stage_names(evs, "stage_failed") == []
    assert [e["seq"] for e in evs] == sorted(e["seq"] for e in evs)
    transitions = [(e["from_status"], e["to_status"]) for e in evs if e["event_type"] == "status_changed"]
    assert transitions == [("CREATED", "RUNNING"), ("RUNNING", "COMPLETE")]
    report = client.get(f"/api/runs/{run['id']}/report").json()
    assert report["run_id"] == run["id"] and report["observations"] and report["hypotheses"]
    assert not report["insufficient_evidence"]
    stored = EvidenceRepository(app.state.db).list_for_run(run["id"])
    assert stored and all(e.run_id == run["id"] and e.synthetic for e in stored)


def test_stale_telemetry_reaches_abstained_without_a_model_call(tmp_path):
    client, provider, _ = make(tmp_path)
    inc = new_incident(client, "stale_telemetry")
    run = finished(client, start(client, inc).json()["id"])
    assert run["status"] == "ABSTAINED" and run["error_code"] is None
    assert provider.calls == 0 and run["model_id"] is None and run["prompt_version"] is None
    report = client.get(f"/api/runs/{run['id']}/report").json()
    assert report["insufficient_evidence"] and report["hypotheses"] == [] and report["missing_evidence"]
    fresh = next(json.loads(e["detail"]) for e in events(client, run["id"])
                 if e["event_type"] == "stage_completed" and json.loads(e["detail"])["stage"] == "check_freshness")
    assert fresh["all_fresh"] is False and fresh["metrics_status_by_host"]["gpu-h21"] == "stale"


def test_model_abstention_reaches_abstained(tmp_path):
    abstain = {"observations": [], "hypotheses": [], "missing_evidence": ["a decisive metric"], "next_test": None,
               "abstain": True, "abstain_reason": "Contradictory evidence.", "limitations": [],
               "document_citations": []}
    client, provider, _ = make(tmp_path, abstain)
    run = finished(client, start(client, new_incident(client)).json()["id"])
    assert run["status"] == "ABSTAINED" and provider.calls == 1


# ---- failures reach FAILED with safe details ----

def failure_codes(client, run_id):
    return [json.loads(e["detail"]) for e in events(client, run_id) if e["event_type"] == "stage_failed"]


def test_bad_model_output_fails_with_a_typed_error_and_no_report(tmp_path):
    invented = lambda req: {**answer(req), "observations": [{"statement": "x", "evidence_ids": ["ev_invented"]}]}
    client, _, _ = make(tmp_path, invented)
    run = finished(client, start(client, new_incident(client)).json()["id"])
    assert run["status"] == "FAILED" and run["error_code"] == "model_output_rejected"
    assert client.get(f"/api/runs/{run['id']}/report").status_code == 404
    failed = failure_codes(client, run["id"])
    assert failed[0]["stage"] == "investigate" and "ev_invented" in failed[0]["message"]
    assert "persist_report" not in stage_names(events(client, run["id"]))  # a failed run never "succeeds"
    assert run["model_id"] == "mock-model-1"  # the failed attempt is still attributed


def build_workflow(app):
    """Force the app's lazily built workflow into existence so a test can adjust its clock/sleep."""
    from types import SimpleNamespace

    from app.api.deps import get_workflow

    return get_workflow(SimpleNamespace(app=app))


def test_provider_outage_is_retried_then_fails(tmp_path):
    sleeps = []
    client, provider, app = make(tmp_path, TransientProviderError("503 upstream"))
    build_workflow(app)._sleep = sleeps.append
    run = finished(client, start(client, new_incident(client)).json()["id"])
    assert run["status"] == "FAILED" and run["error_code"] == "provider_unavailable"
    assert provider.calls == 3 and len(sleeps) == 2  # bounded retries


def test_unknown_host_scope_fails_before_any_tool_call(tmp_path):
    client, provider, app = make(tmp_path)
    inc = new_incident(client, "inference_slowdown", ["gpu-h99"])
    run = finished(client, start(client, inc).json()["id"])
    assert run["status"] == "FAILED" and run["error_code"] == "invalid_host_scope"
    assert provider.calls == 0 and EvidenceRepository(app.state.db).list_for_run(run["id"]) == []
    assert failure_codes(client, run["id"])[0]["stage"] == "validate_scope"


def workflow_with(app, docs=None, provider_factory=None):
    from app.api import deps

    wf = InvestigationWorkflow(
        app.state.db, {fx.incident.scenario_type: fx for fx in load_all_fixtures().values()},
        docs or load_corpus(), provider_factory or (lambda: MockProvider(answer)), build_proposal_service(app))
    app.dependency_overrides[deps.get_workflow] = lambda: wf
    return wf


def test_unexpected_errors_are_hidden_from_the_user(tmp_path):
    class ExplodingIndex:
        def search(self, *args, **kwargs):
            raise RuntimeError("secret-connection-string://user:hunter2@db")

    app = create_app(str(tmp_path / "wf.db"))
    client = TestClient(app)
    workflow_with(app, docs=ExplodingIndex())
    run = finished(client, start(client, new_incident(client)).json()["id"])
    assert run["status"] == "FAILED" and run["error_code"] == "internal_error"
    blob = json.dumps(events(client, run["id"])) + json.dumps(run)
    assert "hunter2" not in blob and "secret-connection-string" not in blob and "Traceback" not in blob
    assert "see server logs" in blob


def test_provider_that_cannot_be_created_is_a_clear_configuration_failure(tmp_path):
    def boom():
        raise RuntimeError("secret-connection-string://user:hunter2@db")

    app = create_app(str(tmp_path / "wf.db"))
    client = TestClient(app)
    workflow_with(app, provider_factory=boom)
    run = finished(client, start(client, new_incident(client)).json()["id"])
    assert run["status"] == "FAILED" and run["error_code"] == "provider_not_configured"
    blob = json.dumps(events(client, run["id"]))
    assert "hunter2" not in blob and "RuntimeError" in blob  # the type is shown, the message is not


def test_the_provider_is_never_built_for_a_run_that_abstains(tmp_path):
    built = []
    app = create_app(str(tmp_path / "wf.db"))
    client = TestClient(app)
    workflow_with(app, provider_factory=lambda: built.append(1) or MockProvider(answer))
    stale = finished(client, start(client, new_incident(client, "stale_telemetry")).json()["id"])
    assert stale["status"] == "ABSTAINED" and built == []
    ok = finished(client, start(client, new_incident(client)).json()["id"])
    assert ok["status"] == "COMPLETE" and built == [1]


def test_run_time_limit(tmp_path):
    ticks = iter(range(0, 10_000))
    client, provider, app = make(tmp_path, limits=WorkflowLimits(max_run_seconds=3))
    build_workflow(app)._monotonic = lambda: float(next(ticks))  # every check advances the clock by 1s
    run = finished(client, start(client, new_incident(client)).json()["id"])
    assert run["status"] == "FAILED" and run["error_code"] == "run_timeout" and provider.calls == 0


# ---- limits stop excessive work ----

def test_tool_call_limit_stops_the_run_before_any_work(tmp_path):
    client, provider, app = make(tmp_path, limits=WorkflowLimits(max_tool_calls=3))
    run = finished(client, start(client, new_incident(client)).json()["id"])
    assert run["status"] == "FAILED" and run["error_code"] == "limit_exceeded"
    assert provider.calls == 0 and EvidenceRepository(app.state.db).list_for_run(run["id"]) == []
    assert "collect_telemetry" not in stage_names(events(client, run["id"]), "stage_started")


def test_host_count_limit(tmp_path):
    client, provider, _ = make(tmp_path, limits=WorkflowLimits(max_hosts=2))
    run = finished(client, start(client, new_incident(client)).json()["id"])
    assert run["error_code"] == "limit_exceeded" and provider.calls == 0


def test_evidence_record_limit(tmp_path):
    client, provider, _ = make(tmp_path, limits=WorkflowLimits(max_evidence_records=2))
    run = finished(client, start(client, new_incident(client)).json()["id"])
    assert run["status"] == "FAILED" and run["error_code"] == "limit_exceeded" and provider.calls == 0
    assert "evidence records" in failure_codes(client, run["id"])[0]["message"]


def test_document_chunk_limit(tmp_path):
    client, _, _ = make(tmp_path, limits=WorkflowLimits(max_document_chunks=1))
    run = finished(client, start(client, new_incident(client)).json()["id"])
    docs = next(json.loads(e["detail"]) for e in events(client, run["id"])
                if e["event_type"] == "stage_completed" and json.loads(e["detail"])["stage"] == "retrieve_docs")
    assert run["status"] == "COMPLETE" and len(docs["citation_ids"]) == 1


def test_model_output_size_limit(tmp_path):
    client, _, _ = make(tmp_path, limits=WorkflowLimits(max_output_chars=50))
    run = finished(client, start(client, new_incident(client)).json()["id"])
    assert run["status"] == "FAILED" and run["error_code"] == "output_too_large"


def test_limits_reject_inconsistent_configuration():
    with pytest.raises(ValueError):
        WorkflowLimits(metrics_window_minutes=500, max_time_range_minutes=120)


# ---- duplicate starts do not create duplicate runs ----

def test_same_idempotency_key_returns_the_same_run(tmp_path):
    client, provider, _ = make(tmp_path)
    inc = new_incident(client)
    a = start(client, inc, "click-1")
    b = start(client, inc, "click-1")
    assert a.status_code == 202 and b.status_code == 200 and a.json()["id"] == b.json()["id"]
    assert provider.calls == 1 and len(client.get(f"/api/incidents/{inc['id']}/runs").json()) == 1


def test_replayed_key_after_completion_does_not_rerun(tmp_path):
    client, provider, _ = make(tmp_path)
    inc = new_incident(client)
    first = start(client, inc, "k").json()
    assert finished(client, first["id"])["status"] == "COMPLETE"
    again = start(client, inc, "k")
    assert again.status_code == 200 and again.json()["id"] == first["id"] and provider.calls == 1


def test_a_new_key_after_completion_starts_a_new_run(tmp_path):
    client, provider, _ = make(tmp_path)
    inc = new_incident(client)
    a = start(client, inc, "k1").json()
    b = start(client, inc, "k2")
    assert b.status_code == 202 and b.json()["id"] != a["id"] and provider.calls == 2


def test_in_flight_run_is_returned_instead_of_starting_another(tmp_path):
    client, provider, app = make(tmp_path)
    inc = new_incident(client)
    stuck = RunService(RunRepository(app.state.db), IncidentRepository(app.state.db)).create(inc["id"])  # CREATED
    r = start(client, inc)  # no key: refresh/double-click
    assert r.status_code == 200 and r.json()["id"] == stuck.id and provider.calls == 0


def test_concurrent_starts_create_exactly_one_run(tmp_path):
    client, _, app = make(tmp_path)
    inc = new_incident(client)
    db = app.state.db
    results, errors = [], []

    def go(key):
        try:
            svc = RunService(RunRepository(db), IncidentRepository(db))
            results.append(svc.start(inc["id"], key))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    for keys in ([None] * 10, [f"k{i}" for i in range(10)], ["same"] * 10):
        results.clear()
        threads = [threading.Thread(target=go, args=(k,)) for k in keys]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert not errors, errors
        assert len({run.id for run, _ in results}) == 1 and sum(created for _, created in results) <= 1
        # finish this run so the next batch can start a fresh one
        run_id = results[0][0].id
        svc = RunService(RunRepository(db), IncidentRepository(db))
        if svc.get(run_id).status == RunStatus.CREATED:
            svc.transition(run_id, RunStatus.CANCELLED)
    assert len(RunRepository(db).list_for_incident(inc["id"])) == 3


def test_execute_is_idempotent_and_runs_once_even_under_a_race(tmp_path):
    client, provider, app = make(tmp_path)
    inc = new_incident(client)
    svc = RunService(RunRepository(app.state.db), IncidentRepository(app.state.db))
    run = svc.create(inc["id"])
    wf = build_workflow(app)
    outs = []
    threads = [threading.Thread(target=lambda: outs.append(wf.execute(run.id))) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert provider.calls == 1 and svc.get(run.id).status == RunStatus.COMPLETE
    assert wf.execute(run.id).status == RunStatus.COMPLETE and provider.calls == 1  # no re-execution
    assert [e["to_status"] for e in svc.events(run.id) if e["event_type"] == "status_changed"] == ["RUNNING", "COMPLETE"]


def test_idempotency_key_and_incident_validation(tmp_path):
    client, _, _ = make(tmp_path)
    inc = new_incident(client)
    assert start(client, inc, "bad key!").status_code == 422
    assert start(client, inc, "x" * 65).status_code == 422
    assert client.post("/api/incidents/inc_missing/runs").status_code == 404


# ---- events replay after refresh / reconnect / restart ----

def test_events_replay_and_resume(tmp_path):
    client, _, _ = make(tmp_path)
    run = finished(client, start(client, new_incident(client)).json()["id"])
    full = client.get(f"/api/runs/{run['id']}/events").json()
    assert full["run_id"] == run["id"] and full["last_seq"] == full["events"][-1]["seq"]
    cut = full["events"][4]["seq"]
    tail = events(client, run["id"], cut)
    assert tail == [e for e in full["events"] if e["seq"] > cut]  # resume exactly where it left off
    assert client.get(f"/api/runs/{run['id']}/events?after_seq={full['last_seq']}").json()["events"] == []
    assert client.get(f"/api/runs/{run['id']}/events?after_seq=-1").status_code == 422
    assert client.get("/api/runs/run_missing/events").status_code == 404


def test_run_events_and_report_survive_a_restart(tmp_path):
    client, _, _ = make(tmp_path)
    run = finished(client, start(client, new_incident(client)).json()["id"])
    before = events(client, run["id"])
    reopened = TestClient(create_app(str(tmp_path / "wf.db")))  # new app, same database file, no provider
    assert events(reopened, run["id"]) == before
    assert finished(reopened, run["id"]) == run
    assert reopened.get(f"/api/runs/{run['id']}/report").status_code == 200


def test_report_404_for_unknown_or_unfinished_run(tmp_path):
    client, _, app = make(tmp_path)
    inc = new_incident(client)
    stuck = RunService(RunRepository(app.state.db), IncidentRepository(app.state.db)).create(inc["id"])
    assert client.get(f"/api/runs/{stuck.id}/report").status_code == 404
    assert client.get("/api/runs/run_missing/report").status_code == 404


# ---- no remediation, no agent loop ----

def test_workflow_has_no_execution_or_agent_loop():
    text = (BACKEND / "app" / "workflow" / "engine.py").read_text(encoding="utf-8")
    for banned in ("subprocess", "os.system", "eval(", "exec(", "while True", "socket", "urllib", "requests"):
        assert banned not in text, banned
    assert text.count("investigator.investigate(") == 1  # one model call site, no loop around it


def test_schema_migration_from_v1_database(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE incidents (id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
            scenario_type TEXT NOT NULL, severity TEXT NOT NULL, affected_hosts TEXT NOT NULL,
            created_at TEXT NOT NULL, synthetic INTEGER NOT NULL);
        CREATE TABLE runs (id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, status TEXT NOT NULL,
            started_at TEXT NOT NULL, finished_at TEXT, model_id TEXT, prompt_version TEXT, error_code TEXT);
        INSERT INTO incidents VALUES ('inc_old','t','d','inference_slowdown','high','["gpu-h07"]','2026-01-01T00:00:00.000000Z',1);
        INSERT INTO runs VALUES ('run_old','inc_old','COMPLETE','2026-01-01T00:00:00.000000Z',NULL,NULL,NULL,NULL);
        PRAGMA user_version = 1;""")
    conn.commit()
    conn.close()
    db = Database(str(path))
    runs = RunRepository(db)
    assert runs.get("run_old").status == RunStatus.COMPLETE  # old data still readable
    new = Run(id="run_new", incident_id="inc_old", status=RunStatus.CREATED,
              started_at=runs.get("run_old").started_at)
    assert runs.create_or_get(new, "key-1") == (new, True)
    assert runs.create_or_get(new, "key-1")[1] is False
    with db.connect() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 3
