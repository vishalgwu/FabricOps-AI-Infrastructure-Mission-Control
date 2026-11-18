"""Phase 11 regression tests. Each test pins a weakness that was found by probing the code, or a control the
security review relies on (docs/security/THREAT_REVIEW.md names these tests)."""
import io
import json
import logging
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.logging import RedactingFormatter, configure_logging, redact, register_secrets
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.investigator import Investigator
from app.llm.mock import MockProvider
from app.llm.provider import ProviderRequest, TransientProviderError
from app.main import create_app
from app.schemas.common import RunStatus
from app.services.services import RunService
from app.storage.db import Database
from app.storage.repositories import IncidentRepository, RunRepository
from app.workflow.engine import WorkflowLimits

BACKEND = Path(__file__).resolve().parents[1]
BODY = {"title": "Latency on gpu-h07", "description": "p95 latency rising", "scenario_type": "inference_slowdown",
        "severity": "high", "affected_hosts": ["gpu-h07"]}
HEADERS = ("x-content-type-options", "cache-control", "x-frame-options", "referrer-policy")


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(str(tmp_path / "sec.db"), provider=MockProvider({})), raise_server_exceptions=False)


@pytest.fixture
def restore_logging():
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers, root.level = handlers, level


# ---------------------------------------------------------------- oversized and malformed input

@pytest.mark.parametrize("path", ["/api/incidents?offset={n}", "/api/runs?offset={n}", "/api/runs/run_x/events?after_seq={n}"])
def test_huge_integers_are_rejected_not_a_500(client, path):
    """Found by probing: 10**30 reached SQLite and produced HTTP 500."""
    r = client.get(path.format(n=10**30))
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_the_largest_allowed_integer_still_works(client):
    inc = client.post("/api/incidents", json=BODY).json()
    run = client.post(f"/api/incidents/{inc['id']}/runs").json()
    assert client.get(f"/api/incidents?offset={2**31 - 1}").status_code == 200
    assert client.get(f"/api/runs/{run['id']}/events?after_seq={2**31 - 1}").status_code == 200


@pytest.mark.parametrize("field,value", [("title", "a\u0000b"), ("title", "two\nlines"), ("title", "bell\u0007"),
                                         ("description", "nul\u0000here"), ("description", "esc\u001b[31m")])
def test_control_characters_are_rejected_in_text_fields(client, field, value):
    r = client.post("/api/incidents", json={**BODY, field: value})
    assert r.status_code == 422 and field in {d["field"] for d in r.json()["error"]["details"]}


def test_line_breaks_are_fine_in_a_description(client):
    assert client.post("/api/incidents", json={**BODY, "description": "line one\nline two\twith a tab"}).status_code == 201


def test_decision_reason_rejects_control_characters(client):
    r = client.post("/api/proposals/prop_x/decision", headers={"X-Demo-Reviewer": "demo-reviewer"},
                    json={"decision": "approved", "proposal_hash": "a" * 64, "reason": "ok\u0000"})
    assert r.status_code == 422


def test_hostile_ids_are_just_not_found(client):
    for path in ("/api/incidents/%27%20OR%201%3D1--", "/api/runs/%27%3B%20DROP%20TABLE%20runs%3B--",
                 "/api/documents/chunks/..%2F..%2Fetc%2Fpasswd", "/api/proposals/%00"):
        assert client.get(path).status_code in (404, 422), path
    # and the tables are still there
    assert client.post("/api/incidents", json=BODY).status_code == 201
    assert client.get("/api/runs").status_code == 200


# ---------------------------------------------------------------- request size limit

def test_a_body_over_the_limit_is_refused_before_it_is_read(client):
    big = {**BODY, "description": "d" * (3 * 1024 * 1024)}
    r = client.post("/api/incidents", json=big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "request_too_large"


def test_a_chunked_body_over_the_limit_is_refused_too(client):
    def chunks():
        for _ in range(40):
            yield b"x" * 4096  # 160 KB with no Content-Length

    r = client.post("/api/incidents", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_the_limit_is_configurable_and_a_normal_request_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("FABRICOPS_MAX_REQUEST_BYTES", "400")
    get_settings.cache_clear()
    try:
        c = TestClient(create_app(str(tmp_path / "s.db")))
        assert c.post("/api/incidents", json=BODY).status_code == 201
        assert c.post("/api/incidents", json={**BODY, "description": "d" * 500}).status_code == 413
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_the_413_carries_cors_headers_so_the_browser_can_read_it(client):
    r = client.post("/api/incidents", json={**BODY, "description": "d" * 200000}, headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 413 and r.headers["access-control-allow-origin"] == "http://localhost:5173"


# ---------------------------------------------------------------- safe errors and headers

def test_security_headers_are_on_every_kind_of_response(client):
    inc = client.post("/api/incidents", json=BODY)
    responses = [client.get("/health"), inc, client.get("/api/incidents/inc_missing"), client.post("/api/incidents", json={}),
                 client.post("/api/incidents", json={**BODY, "description": "d" * 200000}), client.delete("/api/incidents/x")]
    for r in responses:
        for h in HEADERS:
            assert h in r.headers, (r.status_code, h)
        assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"


def _capture_http_log():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter("%(levelname)s %(message)s"))
    logging.getLogger("fabricops.http").addHandler(handler)
    return stream, handler


def test_an_unexpected_error_gives_a_safe_envelope_and_a_redacted_log(client, monkeypatch):
    import app.api.incidents as routes

    def boom(self, incident_id):
        raise RuntimeError("db url postgres://admin:hunter2@db/prod api_key=sk-ant-LEAKYSECRET123456")

    monkeypatch.setattr(routes.IncidentService, "get", boom)
    stream, handler = _capture_http_log()
    try:
        r = client.get("/api/incidents/inc_1", headers={"Origin": "http://localhost:5173"})
    finally:
        logging.getLogger("fabricops.http").removeHandler(handler)
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "internal_error", "message": "An unexpected error occurred.", "details": []}}
    assert "hunter2" not in r.text and "LEAKYSECRET" not in r.text and "RuntimeError" not in r.text
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    logged = stream.getvalue()
    assert "Traceback" in logged and "RuntimeError" in logged  # the operator still gets the traceback...
    assert "LEAKYSECRET" not in logged and "sk-ant" not in logged  # ...with the secret removed


def test_a_database_error_is_a_503_not_a_500(client, monkeypatch):
    import app.api.incidents as routes

    def locked(self, incident_id):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(routes.IncidentService, "get", locked)
    r = client.get("/api/incidents/inc_1")
    assert r.status_code == 503 and r.json()["error"]["code"] == "database_unavailable"
    assert "locked" not in r.text


def test_known_errors_keep_their_own_envelopes(client):
    assert client.get("/api/incidents/inc_missing").json()["error"]["code"] == "not_found"
    assert client.get("/api/runs?limit=0").json()["error"]["code"] == "validation_error"
    assert client.post("/api/proposals/p/decision", json={"decision": "approved", "proposal_hash": "a" * 64,
                                                          "reason": "x"}).json()["error"]["code"] == "unauthenticated"


# ---------------------------------------------------------------- secret redaction

@pytest.mark.parametrize("text,secret", [
    ("failed: api_key=sk-ant-SECRETVALUE123456 while calling", "SECRETVALUE123456"),
    ("headers: {'x-api-key': 'sk-ant-HEADERSECRET999999', 'accept': 'json'}", "HEADERSECRET999999"),
    ('payload {"api_key": "plainsecretvalue777", "n": 1}', "plainsecretvalue777"),
    ("raw token sk-ant-api03-RAWTOKENVALUE000000 appeared", "RAWTOKENVALUE000000"),
    ("sent Authorization: Bearer abcdefghijklmnop1234", "abcdefghijklmnop1234"),
    ("password: correcthorsebattery", "correcthorsebattery"),
    ("GET /x?token=urlsecret12345&a=1", "urlsecret12345"),
    ("openai-style sk-proj1234567890abcdefgh in a message", "proj1234567890abcdefgh"),
])
def test_redaction_removes_secrets_in_many_shapes(text, secret):
    assert secret not in redact(text)


def test_redaction_does_not_mangle_ordinary_log_text():
    for text in ("usage: {'input_tokens': 11, 'output_tokens': 7}", "max_tokens=8000 reached", "token count is 5",
                 "run run_abc123 moved to FAILED", "the key metric is kv_cache_used_pct", "skills and sketches"):
        assert redact(text) == text


def test_registered_secrets_are_redacted_whatever_their_format():
    register_secrets(["my-very-custom-credential-42"])
    assert "my-very-custom-credential-42" not in redact("calling with my-very-custom-credential-42 now")
    register_secrets(["short", None, ""])  # trivial values are ignored, so ordinary words survive
    assert redact("a short note") == "a short note"


def test_the_log_handler_redacts_tracebacks_and_other_loggers(restore_logging):
    configure_logging("INFO", secrets=["customformat-credential-9"])
    stream = io.StringIO()
    logging.getLogger().handlers[0].stream = stream
    log = logging.getLogger("anything.else")
    try:
        raise ValueError("bad credential customformat-credential-9 and api_key=sk-ant-TBSECRET1234567")
    except ValueError:
        log.exception("provider call failed")
    logging.getLogger("uvicorn.error").error("uvicorn says token=uvicornsecret12345")
    out = stream.getvalue()
    assert "Traceback" in out and "ValueError" in out
    for leaked in ("customformat-credential-9", "TBSECRET1234567", "uvicornsecret12345"):
        assert leaked not in out
    assert logging.getLogger("uvicorn.error").propagate is True and logging.getLogger("uvicorn.error").handlers == []


def test_the_configured_api_key_is_registered_for_redaction(tmp_path, monkeypatch, restore_logging):
    monkeypatch.setenv("FABRICOPS_LLM_API_KEY", "configured-key-in-an-odd-format-1")
    get_settings.cache_clear()
    try:
        create_app(str(tmp_path / "s.db"))
        assert "configured-key-in-an-odd-format-1" not in redact("provider said configured-key-in-an-odd-format-1")
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


# ---------------------------------------------------------------- restart recovery

def _make_runs(db_path: str):
    db = Database(db_path)
    incidents = IncidentRepository(db)
    runs = RunRepository(db)
    from app.services.services import IncidentService

    inc = IncidentService(incidents).create("t", "d", "inference_slowdown", "high", ["gpu-h07"])
    svc = RunService(runs, incidents)
    made = {}
    for name in ("created", "running", "waiting", "complete"):
        if name != "created":
            # only one active run per incident is allowed, so use a separate incident for each
            inc = IncidentService(incidents).create(name, "d", "inference_slowdown", "high", ["gpu-h07"])
        run = svc.create(inc.id)
        made[name] = run.id
    svc.transition(made["running"], RunStatus.RUNNING)
    svc.transition(made["waiting"], RunStatus.RUNNING)
    svc.transition(made["waiting"], RunStatus.WAITING_APPROVAL)
    svc.transition(made["complete"], RunStatus.RUNNING)
    svc.transition(made["complete"], RunStatus.COMPLETE)
    return made, inc


def test_runs_interrupted_by_a_restart_are_closed_and_say_why(tmp_path):
    """Found by review: a run that was RUNNING when the server stopped stayed RUNNING forever (and blocked new starts)."""
    path = str(tmp_path / "rec.db")
    made, _ = _make_runs(path)
    app = create_app(path, provider=MockProvider({}))
    with TestClient(app) as client:  # entering the context runs the startup hook
        status = {name: client.get(f"/api/runs/{rid}").json() for name, rid in made.items()}
        assert status["created"]["status"] == "FAILED" and status["created"]["error_code"] == "interrupted"
        assert status["running"]["status"] == "FAILED" and status["running"]["finished_at"]
        assert status["waiting"]["status"] == "WAITING_APPROVAL"   # fully stored, a human can still decide
        assert status["complete"]["status"] == "COMPLETE"
        events = client.get(f"/api/runs/{made['running']}/events").json()["events"]
        failed = [json.loads(e["detail"]) for e in events if e["event_type"] == "stage_failed"]
        assert failed and failed[-1]["code"] == "interrupted" and "Start a new one" in failed[-1]["message"]
        assert events[-1]["to_status"] == "FAILED"


def test_recovery_unblocks_starting_a_new_run_and_is_idempotent(tmp_path):
    path = str(tmp_path / "rec2.db")
    made, _ = _make_runs(path)
    db = Database(path)
    repo = RunRepository(db)
    assert sorted(repo.fail_interrupted()) == sorted([made["created"], made["running"]])
    assert repo.fail_interrupted() == []  # nothing left to close
    svc = RunService(repo, IncidentRepository(db))
    inc_id = repo.get(made["running"]).incident_id
    run, created = svc.start(inc_id)
    assert created and run.id != made["running"]  # no longer blocked by the dead run


def test_startup_recovery_does_not_touch_the_database_at_import_time(tmp_path):
    path = tmp_path / "never.db"
    create_app(str(path))
    assert not path.exists()  # the hook runs only when the server starts, not when the app object is built


# ---------------------------------------------------------------- the model call cannot outlive the run

def _investigator_package():
    """An evidence package for the inference-slowdown scenario, built the way the workflow builds it."""
    from datetime import datetime, timedelta, timezone

    from app.domain.fixture_loader import load_all_fixtures
    from app.llm.package import build_package
    from app.tools.adapter import FixtureAdapter
    from app.tools.telemetry import TelemetryTools

    fx = load_all_fixtures()["s1_inference_slowdown"]
    tools = TelemetryTools(FixtureAdapter.from_fixture(fx), "run_sec", clock=lambda: datetime(2026, 3, 10, 14, 0, 30, tzinfo=timezone.utc))
    hosts = [h.id for h in fx.hosts]
    results = [tools.read_metrics(h, 60) for h in hosts]
    return build_package("run_sec", fx.incident, hosts, results, None, fx.reference_time + timedelta(seconds=0))


def test_no_attempt_starts_once_the_time_limit_has_passed():
    pkg = _investigator_package()
    provider = MockProvider(TransientProviderError("503"))
    out = Investigator(provider, sleep=lambda s: None).investigate(pkg, time_left=lambda: 0.0)
    assert out.status == RunStatus.FAILED and out.error_code == "run_timeout" and provider.calls == 0


def test_each_attempt_is_capped_to_the_time_left_and_retries_stop_when_it_runs_out():
    pkg = _investigator_package()
    provider = MockProvider(TransientProviderError("503"))
    left = iter([10.0, 9.0, 8.0, 0.2, 0.2, 0.2])  # time left at each check: attempt 1, its pause check, attempt 2, ...
    sleeps = []
    out = Investigator(provider, max_attempts=5, sleep=sleeps.append).investigate(pkg, time_left=lambda: next(left))
    assert out.status == RunStatus.FAILED and out.error_code == "run_timeout"
    assert [r.timeout_seconds for r in provider.requests][:2] == [10.0, 8.0]
    assert provider.calls < 5 and all(s <= 2.0 for s in sleeps)


def test_without_a_deadline_behaviour_is_unchanged():
    pkg = _investigator_package()
    provider = MockProvider(TransientProviderError("503"))
    out = Investigator(provider, max_attempts=3, sleep=lambda s: None).investigate(pkg)
    assert out.error_code == "provider_unavailable" and provider.calls == 3
    assert all(r.timeout_seconds is None for r in provider.requests)


def test_the_anthropic_adapter_never_waits_longer_than_the_run_has_left():
    from types import SimpleNamespace

    from app.core.config import Settings

    seen = {}

    class Messages:
        def create(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(stop_reason="end_turn", stop_details=None, model="m", usage=None,
                                   content=[SimpleNamespace(type="text", text="{}")])

    client = SimpleNamespace(messages=Messages(), beta=SimpleNamespace(messages=Messages()))
    p = AnthropicProvider(Settings(llm_timeout_seconds=120.0, llm_enable_fallbacks=False), client=client)
    base = dict(system="s", user="u", json_schema={}, max_tokens=10)
    p.generate_investigation(ProviderRequest(**base, timeout_seconds=7.5))
    assert seen["timeout"] == 7.5
    p.generate_investigation(ProviderRequest(**base, timeout_seconds=999.0))
    assert seen["timeout"] == 120.0  # the configured ceiling still applies
    p.generate_investigation(ProviderRequest(**base))
    assert seen["timeout"] == 120.0


def test_a_run_ends_failed_with_run_timeout_instead_of_retrying_past_its_limit(tmp_path):
    from types import SimpleNamespace

    from app.api.deps import get_workflow

    provider = MockProvider(TransientProviderError("503 upstream"))
    app = create_app(str(tmp_path / "t.db"), provider=provider, workflow_limits=WorkflowLimits(max_run_seconds=5))
    wf = get_workflow(SimpleNamespace(app=app))
    wf._sleep = lambda s: None
    clock = {"t": 0.0}

    def advancing():
        clock["t"] += 2.0   # every look at the clock costs two "seconds"
        return clock["t"]

    wf._monotonic = advancing
    client = TestClient(app)
    inc = client.post("/api/incidents", json=BODY).json()
    started = client.post(f"/api/incidents/{inc['id']}/runs").json()
    run = client.get(f"/api/runs/{started['id']}").json()
    assert run["status"] == "FAILED" and run["error_code"] == "run_timeout"
    assert provider.calls < 3


# ---------------------------------------------------------------- repository hygiene

def _tracked_files():
    import subprocess

    root = BACKEND.parent
    try:
        out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not available")
    return [root / line for line in out.splitlines() if line]


def test_no_env_files_or_databases_are_tracked():
    bad = [p.name for p in _tracked_files() if p.name == ".env" or (p.name.startswith(".env.") and p.name != ".env.example")
           or p.suffix in (".db", ".sqlite", ".sqlite3", ".pem", ".key")]
    assert bad == []


def test_no_real_looking_keys_are_in_tracked_files():
    pattern = __import__("re").compile(r"sk-ant-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----")
    marker = __import__("re").compile(r"(?i)secret|fake|dummy|example|leak|invent|rawtoken")
    for path in _tracked_files():
        if path.suffix in (".png", ".pdf", ".ico", ".lock") or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for m in pattern.finditer(text):
            # Test files contain obviously fake keys on purpose; a real key would not carry such a marker.
            assert marker.search(m.group(0)), f"{path} contains something that looks like a real key"


def test_the_threat_review_names_only_tests_that_exist():
    doc = (BACKEND.parent / "docs" / "security" / "THREAT_REVIEW.md").read_text(encoding="utf-8")
    refs = __import__("re").findall(r"`(tests/[a-z_]+\.py)::([A-Za-z0-9_]+)`", doc)
    assert len(refs) >= 20
    for file, name in refs:
        assert f"def {name}(" in (BACKEND / file).read_text(encoding="utf-8"), f"{file}::{name} does not exist"
