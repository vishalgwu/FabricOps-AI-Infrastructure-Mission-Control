import pytest
from fastapi.testclient import TestClient

from app.core.errors import InvalidTransitionError
from app.domain.run_state import ALLOWED_TRANSITIONS, check_transition
from app.main import create_app
from app.schemas.common import TERMINAL_RUN_STATUSES, RunStatus
from app.services.services import RunService
from app.storage.db import Database
from app.storage.repositories import IncidentRepository, RunRepository

BODY = {
    "title": "Latency on gpu-h07",
    "description": "p95 latency rising",
    "scenario_type": "inference_slowdown",
    "severity": "high",
    "affected_hosts": ["gpu-h07"],
}


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def client(db_path):
    return TestClient(create_app(db_path))


def run_service(db_path: str) -> RunService:
    db = Database(db_path)
    return RunService(RunRepository(db), IncidentRepository(db))


# ---- API: create / list / read ----

def test_create_incident(client):
    r = client.post("/api/incidents", json=BODY)
    assert r.status_code == 201
    body = r.json()
    assert body["id"].startswith("inc_") and body["synthetic"] is True
    assert body["created_at"].endswith("Z") or body["created_at"].endswith("+00:00")


def test_get_and_list_incidents(client):
    a = client.post("/api/incidents", json=BODY).json()
    b = client.post("/api/incidents", json={**BODY, "title": "Second"}).json()
    assert client.get(f"/api/incidents/{a['id']}").json() == a
    listing = client.get("/api/incidents").json()
    assert listing["total"] == 2
    assert {i["id"] for i in listing["items"]} == {a["id"], b["id"]}


def test_list_pagination(client):
    for n in range(5):
        client.post("/api/incidents", json={**BODY, "title": f"t{n}"})
    page = client.get("/api/incidents?limit=2&offset=4").json()
    assert page["total"] == 5 and len(page["items"]) == 1
    assert client.get("/api/incidents?limit=0").status_code == 422


def test_unknown_incident_is_404_with_envelope(client):
    r = client.get("/api/incidents/inc_missing")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
    assert client.get("/api/incidents/inc_missing/runs").status_code == 404
    assert client.get("/api/runs/run_missing").status_code == 404


# ---- IDs are stable and immutable ----

def test_client_cannot_set_id_or_timestamp(client):
    r = client.post("/api/incidents", json={**BODY, "id": "inc_mine", "created_at": "2020-01-01T00:00:00Z"})
    assert r.status_code == 422
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert {"id", "created_at"} <= fields


def test_ids_are_unique_and_stable_across_reads(client):
    ids = {client.post("/api/incidents", json=BODY).json()["id"] for _ in range(20)}
    assert len(ids) == 20
    first = next(iter(ids))
    assert client.get(f"/api/incidents/{first}").json()["id"] == first


def test_no_update_or_delete_routes(client):
    inc = client.post("/api/incidents", json=BODY).json()
    for method in ("put", "patch", "delete"):
        r = client.request(method.upper(), f"/api/incidents/{inc['id']}", json={"title": "x"})
        assert r.status_code == 405
        assert r.json()["error"]["code"] == "method_not_allowed"
    assert client.get(f"/api/incidents/{inc['id']}").json()["title"] == BODY["title"]


# ---- validation errors are clear ----

def test_validation_error_envelope(client):
    r = client.post("/api/incidents", json={"title": "", "scenario_type": "nope", "affected_hosts": []})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error"
    fields = {d["field"] for d in err["details"]}
    assert {"title", "description", "scenario_type", "affected_hosts"} <= fields
    assert all(d["message"] for d in err["details"])


def test_invalid_host_id_rejected(client):
    r = client.post("/api/incidents", json={**BODY, "affected_hosts": ["bad host; rm -rf /"]})
    assert r.status_code == 422
    assert "invalid host id" in r.json()["error"]["details"][0]["message"]


def test_incident_with_no_runs_returns_empty_list(client):
    inc = client.post("/api/incidents", json=BODY).json()
    assert client.get(f"/api/incidents/{inc['id']}/runs").json() == []


# ---- restart persistence ----

def test_records_survive_closing_and_reopening_the_database(db_path):
    first = TestClient(create_app(db_path))
    inc = first.post("/api/incidents", json=BODY).json()
    run = run_service(db_path).create(inc["id"])
    run_service(db_path).transition(run.id, RunStatus.RUNNING)
    del first  # "restart": drop the app and every connection

    second = TestClient(create_app(db_path))  # a brand new app object on the same file
    assert second.get(f"/api/incidents/{inc['id']}").json() == inc
    assert second.get("/api/incidents").json()["total"] == 1
    runs = second.get(f"/api/incidents/{inc['id']}/runs").json()
    assert [r["id"] for r in runs] == [run.id] and runs[0]["status"] == "RUNNING"
    assert second.get(f"/api/runs/{run.id}").json()["status"] == "RUNNING"
    events = run_service(db_path).events(run.id)
    assert [e["to_status"] for e in events] == ["CREATED", "RUNNING"]


def test_schema_init_is_repeatable(db_path):
    for _ in range(3):
        db = Database(db_path)
        with db.connect() as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"incidents", "runs", "evidence", "investigation_reports", "proposals",
            "approval_decisions", "run_events"} <= tables


def test_database_file_not_created_until_used(tmp_path):
    path = tmp_path / "lazy.db"
    create_app(str(path))
    assert not path.exists()


# ---- run state machine ----

def test_valid_lifecycle_and_finished_at(db_path):
    inc = TestClient(create_app(db_path)).post("/api/incidents", json=BODY).json()
    svc = run_service(db_path)
    run = svc.create(inc["id"])
    assert run.status == RunStatus.CREATED and run.finished_at is None
    svc.transition(run.id, RunStatus.RUNNING)
    svc.transition(run.id, RunStatus.WAITING_APPROVAL)
    done = svc.transition(run.id, RunStatus.COMPLETE)
    assert done.status == RunStatus.COMPLETE and done.finished_at is not None


def test_invalid_transitions_rejected(db_path):
    inc = TestClient(create_app(db_path)).post("/api/incidents", json=BODY).json()
    svc = run_service(db_path)
    run = svc.create(inc["id"])
    with pytest.raises(InvalidTransitionError, match="CREATED to COMPLETE"):
        svc.transition(run.id, RunStatus.COMPLETE)  # cannot skip RUNNING
    assert svc.get(run.id).status == RunStatus.CREATED  # unchanged
    svc.transition(run.id, RunStatus.RUNNING)
    svc.transition(run.id, RunStatus.ABSTAINED)
    with pytest.raises(InvalidTransitionError, match="terminal"):
        svc.transition(run.id, RunStatus.RUNNING)  # terminal states are final


@pytest.mark.parametrize("terminal", sorted(TERMINAL_RUN_STATUSES, key=lambda s: s.value))
def test_terminal_states_have_no_exits(terminal):
    for target in RunStatus:
        with pytest.raises(InvalidTransitionError):
            check_transition(terminal, target)


def test_every_status_is_in_the_transition_table():
    assert set(ALLOWED_TRANSITIONS) == set(RunStatus)


def test_stale_transition_is_rejected_not_overwritten(db_path):
    inc = TestClient(create_app(db_path)).post("/api/incidents", json=BODY).json()
    svc = run_service(db_path)
    run = svc.create(inc["id"])
    svc.transition(run.id, RunStatus.RUNNING)
    # A writer that still believes the run is CREATED loses the compare-and-swap.
    repo = RunRepository(Database(db_path))
    from datetime import datetime, timezone

    assert repo.transition(run.id, RunStatus.CREATED, RunStatus.CANCELLED,
                           datetime.now(timezone.utc), True) is False
    assert svc.get(run.id).status == RunStatus.RUNNING


def test_run_for_unknown_incident_rejected(db_path):
    from app.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        run_service(db_path).create("inc_missing")


# ---- route handlers do not embed database access ----

def test_route_modules_contain_no_sql_or_sqlite():
    from pathlib import Path

    for f in (Path(__file__).resolve().parents[1] / "app" / "api").glob("*.py"):
        text = f.read_text(encoding="utf-8").lower()
        assert "sqlite3" not in text and "select " not in text and "insert into" not in text, f
