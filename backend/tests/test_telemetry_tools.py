import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.domain.fixture_loader import FIXTURE_DIR, load_all_fixtures
from app.schemas.fixtures import ScenarioFixture
from app.services.services import IncidentService, RunService
from app.storage.db import Database
from app.storage.repositories import EvidenceRepository, IncidentRepository, RunRepository
from app.tools.adapter import (
    FaultInjectingAdapter,
    FixtureAdapter,
    SourceError,
    SourceTimeout,
)
from app.tools.models import MAX_LOG_LIMIT, MAX_WINDOW_MINUTES, ToolStatus
from app.tools.telemetry import TOOL_NAMES, TelemetryTools

FIXED_NOW = datetime(2026, 3, 10, 14, 0, 30, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def fixtures():
    return load_all_fixtures()


def tools_for(fixture, run_id="run_t1", repo=None, **kw):
    return TelemetryTools(FixtureAdapter.from_fixture(fixture), run_id, repo, clock=lambda: FIXED_NOW, **kw)


def whole_day(fixture):
    end = fixture.reference_time
    return {"start": (end - timedelta(hours=6)).isoformat(), "end": end.isoformat()}


# ---- happy paths ----

def test_read_metrics_ok_with_provenance(fixtures):
    r = tools_for(fixtures["s1_inference_slowdown"]).read_metrics("gpu-h07", 60)
    assert r.status == ToolStatus.OK and r.has_readings
    assert r.tool_name == "read_metrics" and r.host_scope == ["gpu-h07", "gpu-h08", "gpu-h09"]
    assert r.parameters == {"host_id": "gpu-h07", "time_window_minutes": 60, "metrics": None}
    assert r.collected_at == FIXED_NOW and r.as_of == fixtures["s1_inference_slowdown"].reference_time
    assert r.evidence_ids == [rec.id for rec in r.records] and len(r.evidence_ids) == 6
    assert set(r.provenance) == {"serving-metrics-synthetic", "dcgm-synthetic", "node-agent-synthetic"}
    assert r.freshness.age_seconds == 0 and r.observed_to == r.as_of
    for rec in r.records:
        assert rec.synthetic and rec.observed_at != rec.ingested_at  # observed vs ingested kept apart
        assert rec.payload["unit"] and rec.payload["source"]


def test_metric_filter_and_values(fixtures):
    r = tools_for(fixtures["s1_inference_slowdown"]).read_metrics("gpu-h07", 60, ["kv_cache_used_pct"])
    assert len(r.records) == 1
    p = r.records[0].payload
    assert p["unit"] == "percent" and p["latest_value"] == 96.0 and p["sample_count"] == 13


def test_contradictory_sources_are_both_returned(fixtures):
    r = tools_for(fixtures["s1_inference_slowdown"]).read_metrics("gpu-h07", 60, ["gpu_memory_used"])
    latest = {rec.payload["source"]: rec.payload["latest_value"] for rec in r.records}
    assert latest["dcgm-synthetic"] != latest["node-agent-synthetic"]


def test_read_logs_and_untrusted_marking(fixtures):
    fx = fixtures["s1_inference_slowdown"]
    r = tools_for(fx).read_logs("gpu-h07", whole_day(fx))
    assert r.status == ToolStatus.OK and len(r.records) == 2
    assert all(rec.payload["content_trust"] == "untrusted_data" for rec in r.records)
    assert any("IGNORE ALL PREVIOUS INSTRUCTIONS" in rec.payload["message"] for rec in r.records)
    assert r.records[0].observed_at >= r.records[1].observed_at  # newest first


def test_log_limit_truncates_and_flags(fixtures):
    fx = fixtures["s1_inference_slowdown"]
    r = tools_for(fx).read_logs("gpu-h07", whole_day(fx), limit=1)
    assert len(r.records) == 1 and r.truncated is True


def test_read_config(fixtures):
    r = tools_for(fixtures["s1_inference_slowdown"]).read_config("gpu-h07")
    assert r.status == ToolStatus.OK
    assert r.records[0].payload["settings"]["batch_size"] == 64


# ---- zero vs no data vs stale vs failure ----

def test_valid_zero_reading_is_ok_not_missing(fixtures):
    r = tools_for(fixtures["s2_link_instability"]).read_metrics("net-h02", 60, ["link_retrain_count"])
    assert r.status == ToolStatus.OK
    assert r.records[0].payload["latest_value"] == 0.0 and r.records[0].payload["null_count"] == 0


def test_stale_data_is_distinct(fixtures):
    r = tools_for(fixtures["s3_stale_telemetry"]).read_metrics("gpu-h21", 60)
    assert r.status == ToolStatus.STALE and r.error_code == "stale_data"
    assert r.records == [] and r.evidence_ids == []  # no fake zeros
    assert r.freshness.age_seconds > 4 * 3600 and "4h45m" in r.message


def test_stale_data_inside_a_wide_window_returns_readings_but_flags_stale(fixtures):
    r = tools_for(fixtures["s3_stale_telemetry"]).read_metrics("gpu-h21", 720, ["request_latency_p95"])
    assert r.status == ToolStatus.STALE and len(r.records) == 1
    assert r.freshness.age_seconds > r.freshness.threshold_seconds


def test_all_null_readings_are_no_data_not_zero(fixtures):
    r = tools_for(fixtures["s3_stale_telemetry"]).read_metrics("gpu-h21", 720, ["kv_cache_used_pct"])
    assert r.status == ToolStatus.NO_DATA
    p = r.records[0].payload
    assert p["latest_value"] is None and p["null_count"] == 13 and p["min"] is None
    assert all(s["value"] is None for s in p["samples"])


def test_no_data_for_host_without_metrics(fixtures):
    r = tools_for(fixtures["s3_stale_telemetry"]).read_metrics("gpu-h22", 60)
    assert r.status == ToolStatus.NO_DATA and r.records == [] and r.error_code == "no_data"


def test_no_config_is_no_data(fixtures):
    r = tools_for(fixtures["s3_stale_telemetry"]).read_config("gpu-h21")
    assert r.status == ToolStatus.NO_DATA


def test_no_logs_in_range_is_no_data(fixtures):
    fx = fixtures["s2_link_instability"]
    far_past = {"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T01:00:00Z"}
    assert tools_for(fx).read_logs("net-h01", far_past).status == ToolStatus.NO_DATA


def test_stale_config(fixtures):
    fx = fixtures["s1_inference_slowdown"]
    r = tools_for(fx, config_max_age=timedelta(hours=1)).read_config("gpu-h07")
    assert r.status == ToolStatus.STALE and len(r.records) == 1


def test_freshness_uses_observed_not_ingested_time(fixtures):
    fx = fixtures["s1_inference_slowdown"]
    raw = json.loads((FIXTURE_DIR / "s1_inference_slowdown.json").read_text(encoding="utf-8"))
    for m in raw["metrics"]:
        m["ingested_at"] = "2026-03-10T13:59:59Z"  # ingested "just now"...
        m["observed_at"] = "2026-03-10T08:00:00Z"  # ...but observed long ago
    old = ScenarioFixture.model_validate(raw)
    r = tools_for(old).read_metrics("gpu-h07", 720)
    assert r.status == ToolStatus.STALE
    assert fx  # original unaffected


# ---- failures are never readings ----

@pytest.mark.parametrize(
    "fault,status,code",
    [(SourceTimeout(), ToolStatus.TIMEOUT, "source_timeout"), (SourceError("db down"), ToolStatus.ERROR, "source_error")],
)
def test_source_failures_are_distinct_and_empty(fixtures, fault, status, code):
    fx = fixtures["s1_inference_slowdown"]
    t = TelemetryTools(FaultInjectingAdapter(lambda: fx, {"metrics": fault, "logs": fault, "configs": fault}),
                       "run_t1", clock=lambda: FIXED_NOW)
    for r in (t.read_metrics("gpu-h07", 60), t.read_logs("gpu-h07", whole_day(fx)), t.read_config("gpu-h07")):
        assert r.status == status and r.error_code == code
        assert r.records == [] and r.evidence_ids == [] and not r.has_readings


def test_malformed_source_data(fixtures):
    def bad_loader():
        return ScenarioFixture.model_validate({"synthetic": True})  # missing everything

    t = TelemetryTools(FixtureAdapter(bad_loader), "run_t1", clock=lambda: FIXED_NOW)
    r = t.read_metrics("gpu-h07", 60)
    assert r.status == ToolStatus.MALFORMED and r.error_code == "malformed_source" and r.records == []


def test_malformed_record_inside_fixture_file(tmp_path):
    raw = json.loads((FIXTURE_DIR / "s2_link_instability.json").read_text(encoding="utf-8"))
    raw["metrics"][0]["unit"] = "ms"  # wrong unit for link_error_count
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    from app.domain.fixture_loader import load_fixture

    t = TelemetryTools(FixtureAdapter(lambda: load_fixture(path)), "run_t1", clock=lambda: FIXED_NOW)
    assert t.read_config("net-h01").status == ToolStatus.MALFORMED


# ---- scope and bounds ----

def test_unknown_host_rejected(fixtures):
    r = tools_for(fixtures["s1_inference_slowdown"]).read_metrics("ghost-host", 60)
    assert r.status == ToolStatus.REJECTED and r.error_code == "unknown_host" and r.records == []


def test_out_of_scope_host_rejected(fixtures):
    t = tools_for(fixtures["s2_link_instability"], allowed_hosts={"net-h01"})
    assert t.read_metrics("net-h01", 60).status == ToolStatus.OK
    r = t.read_metrics("net-h02", 60)
    assert r.status == ToolStatus.REJECTED and r.error_code == "out_of_scope"
    assert r.host_scope == ["net-h01"] and r.records == []


@pytest.mark.parametrize("host", ["../etc/passwd", "h1; rm -rf /", "http://evil.example", "", "a" * 65, "h 1"])
def test_malicious_host_ids_rejected(fixtures, host):
    r = tools_for(fixtures["s1_inference_slowdown"]).read_metrics(host, 60)
    assert r.status == ToolStatus.REJECTED and r.error_code == "invalid_arguments"


@pytest.mark.parametrize("minutes", [0, -5, MAX_WINDOW_MINUTES + 1, 10**9])
def test_excessive_or_invalid_windows_rejected(fixtures, minutes):
    r = tools_for(fixtures["s1_inference_slowdown"]).read_metrics("gpu-h07", minutes)
    assert r.status == ToolStatus.REJECTED and "time_window_minutes" in r.message


def test_invalid_time_ranges_rejected(fixtures):
    t = tools_for(fixtures["s1_inference_slowdown"])
    backwards = {"start": "2026-03-10T14:00:00Z", "end": "2026-03-10T13:00:00Z"}
    too_long = {"start": "2026-03-01T00:00:00Z", "end": "2026-03-10T00:00:00Z"}
    naive = {"start": "2026-03-10T13:00:00", "end": "2026-03-10T14:00:00"}
    for rng in (backwards, too_long, naive):
        assert t.read_logs("gpu-h07", rng).status == ToolStatus.REJECTED


@pytest.mark.parametrize("limit", [0, MAX_LOG_LIMIT + 1, -1])
def test_log_limit_bounds(fixtures, limit):
    fx = fixtures["s1_inference_slowdown"]
    assert tools_for(fx).read_logs("gpu-h07", whole_day(fx), limit=limit).status == ToolStatus.REJECTED


def test_unknown_metric_filter_and_extra_args_rejected(fixtures):
    t = tools_for(fixtures["s1_inference_slowdown"])
    assert t.read_metrics("gpu-h07", 60, ["vibes"]).status == ToolStatus.REJECTED
    r = t.call("read_metrics", {"host_id": "gpu-h07", "time_window_minutes": 60, "path": "/etc/passwd"})
    assert r.status == ToolStatus.REJECTED and "path" in r.message


def test_unregistered_tools_rejected(fixtures):
    t = tools_for(fixtures["s1_inference_slowdown"])
    for name in ("run_shell", "fetch_url", "read_file", "restart_host", "READ_METRICS", ""):
        r = t.call(name, {"host_id": "gpu-h07"})
        assert r.status == ToolStatus.REJECTED and r.error_code == "unknown_tool"


# ---- read-only ----

def test_exactly_three_read_only_tools():
    assert TOOL_NAMES == ("read_metrics", "read_logs", "read_config")


def test_tool_modules_have_no_dangerous_imports():
    root = Path(__file__).resolve().parents[1] / "app" / "tools"
    banned = ("subprocess", "os.system", "socket", "urllib", "requests", "httpx", "shutil", "eval(", "exec(")
    for f in root.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        for b in banned:
            assert b not in text, f"{f.name} contains {b}"


def test_adapter_has_no_write_methods():
    public = [n for n in dir(FixtureAdapter) if not n.startswith("_")]
    assert sorted(public) == ["as_of", "from_fixture", "known_hosts", "configs_for", "logs_for", "metrics_for"] or \
        set(public) == {"as_of", "from_fixture", "known_hosts", "configs_for", "logs_for", "metrics_for"}


def test_tools_do_not_mutate_fixture_data(fixtures):
    fx = fixtures["s1_inference_slowdown"]
    before = fx.model_dump_json()
    t = tools_for(fx)
    t.read_metrics("gpu-h07", 60)
    t.read_logs("gpu-h07", whole_day(fx))
    t.read_config("gpu-h07")
    assert fx.model_dump_json() == before


# ---- evidence persistence and stable IDs ----

@pytest.fixture
def stored(tmp_path, fixtures):
    db = Database(str(tmp_path / "ev.db"))
    inc = IncidentService(IncidentRepository(db)).create(
        "t", "d", fixtures["s1_inference_slowdown"].incident.scenario_type,
        fixtures["s1_inference_slowdown"].incident.severity, ["gpu-h07"])
    run = RunService(RunRepository(db), IncidentRepository(db)).create(inc.id)
    return db, run


def test_evidence_ids_are_stable_within_a_run_and_idempotent(stored, fixtures):
    db, run = stored
    repo = EvidenceRepository(db)
    t = tools_for(fixtures["s1_inference_slowdown"], run.id, repo)
    first = t.read_metrics("gpu-h07", 60)
    second = t.read_metrics("gpu-h07", 60)
    assert first.evidence_ids == second.evidence_ids
    assert len(set(first.evidence_ids)) == len(first.evidence_ids)
    assert len(repo.list_for_run(run.id)) == len(first.evidence_ids)  # no duplicates stored


def test_evidence_ids_differ_between_runs_and_hosts(stored, fixtures):
    fx = fixtures["s1_inference_slowdown"]
    a = tools_for(fx, "run_a").read_metrics("gpu-h07", 60).evidence_ids
    b = tools_for(fx, "run_b").read_metrics("gpu-h07", 60).evidence_ids
    c = tools_for(fx, "run_a").read_metrics("gpu-h08", 60).evidence_ids
    assert not set(a) & set(b) and not set(a) & set(c)


def test_evidence_persists_with_provenance_and_timestamps(stored, fixtures):
    db, run = stored
    repo = EvidenceRepository(db)
    r = tools_for(fixtures["s1_inference_slowdown"], run.id, repo).read_metrics("gpu-h07", 60, ["kv_cache_used_pct"])
    reopened = EvidenceRepository(Database(db.path))  # new object, same file
    saved = reopened.get(r.evidence_ids[0])
    assert saved == r.records[0]
    assert saved.run_id == run.id and saved.tool_name == "read_metrics" and saved.host_id == "gpu-h07"
    assert saved.observed_at.tzinfo is not None and saved.ingested_at == FIXED_NOW and saved.synthetic is True


def test_failures_and_rejections_persist_no_evidence(stored, fixtures):
    db, run = stored
    repo = EvidenceRepository(db)
    t = tools_for(fixtures["s1_inference_slowdown"], run.id, repo)
    t.read_metrics("ghost", 60)
    t.read_metrics("gpu-h07", 99999)
    assert repo.list_for_run(run.id) == []
