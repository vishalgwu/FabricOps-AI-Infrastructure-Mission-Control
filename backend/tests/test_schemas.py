import json
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.fixture_loader import FIXTURE_DIR, load_all_fixtures
from app.schemas.common import ApprovalStatus, RiskClass
from app.schemas.domain import (
    Hypothesis,
    InvestigationReport,
    MetricSample,
    Proposal,
)
from app.schemas.fixtures import ScenarioFixture

BACKEND = Path(__file__).resolve().parents[1]
EVAL_DIR = BACKEND / "data" / "evals"


@pytest.fixture(scope="module")
def fixtures():
    return load_all_fixtures()


def raw(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def sample(**over) -> dict:
    base = {
        "host_id": "h1", "source": "x-synthetic", "metric": "kv_cache_used_pct", "value": 50.0,
        "unit": "percent", "observed_at": "2026-03-10T14:00:00Z",
    }
    base.update(over)
    return base


# ---- fixtures load ----

def test_three_scenarios_load(fixtures):
    assert set(fixtures) == {"s1_inference_slowdown", "s2_link_instability", "s3_stale_telemetry"}


def test_all_fixtures_labelled_synthetic(fixtures):
    for fx in fixtures.values():
        assert fx.synthetic is True and "SYNTHETIC" in fx.data_notice
        assert fx.incident.synthetic is True
        assert all(h.synthetic for h in fx.hosts)


def test_all_timestamps_are_utc(fixtures):
    for fx in fixtures.values():
        for m in fx.metrics:
            assert m.observed_at.utcoffset() == timedelta(0)


def test_s1_has_peer_comparison_contradiction_and_injection(fixtures):
    fx = fixtures["s1_inference_slowdown"]
    assert {m.host_id for m in fx.metrics} == {"gpu-h07", "gpu-h08", "gpu-h09"}
    mem_sources = {m.source for m in fx.metrics if m.metric == "gpu_memory_used" and m.host_id == "gpu-h07"}
    assert len(mem_sources) == 2  # contradictory readings
    assert any("IGNORE ALL PREVIOUS INSTRUCTIONS" in r.message for r in fx.logs)


def test_s2_isolates_one_host_with_peers(fixtures):
    fx = fixtures["s2_link_instability"]
    assert fx.incident.affected_hosts == ["net-h01"]
    assert len({m.host_id for m in fx.metrics}) == 4


def test_s3_is_stale_and_has_nulls_and_missing_sources(fixtures):
    fx = fixtures["s3_stale_telemetry"]
    newest = max(m.observed_at for m in fx.metrics)
    assert fx.reference_time - newest > timedelta(hours=4)
    nulls = [m for m in fx.metrics if m.metric == "kv_cache_used_pct"]
    assert nulls and all(m.value is None for m in nulls)  # null, never 0
    assert not any(m.host_id == "gpu-h22" for m in fx.metrics)  # peer has no data
    assert fx.configs == []


def test_empty_evidence_is_allowed():
    data = raw("s3_stale_telemetry.json")
    data["metrics"], data["logs"], data["configs"] = [], [], []
    fx = ScenarioFixture.model_validate(data)
    assert fx.metrics == []


# ---- invalid data is rejected with useful errors ----

def test_unlabelled_fixture_rejected():
    data = raw("s1_inference_slowdown.json")
    data["synthetic"] = False
    with pytest.raises(ValidationError, match="synthetic"):
        ScenarioFixture.model_validate(data)


def test_unknown_host_rejected():
    data = raw("s1_inference_slowdown.json")
    data["metrics"].append(sample(host_id="ghost-host"))
    with pytest.raises(ValidationError, match="unknown host.*ghost-host"):
        ScenarioFixture.model_validate(data)


def test_unknown_affected_host_rejected():
    data = raw("s1_inference_slowdown.json")
    data["incident"]["affected_hosts"] = ["nope"]
    with pytest.raises(ValidationError, match="unknown host.*nope"):
        ScenarioFixture.model_validate(data)


def test_invalid_unit_rejected():
    with pytest.raises(ValidationError, match="must use unit 'percent'"):
        MetricSample.model_validate(sample(unit="ms"))


def test_unknown_unit_rejected():
    with pytest.raises(ValidationError):
        MetricSample.model_validate(sample(unit="furlongs"))


def test_unknown_metric_rejected():
    with pytest.raises(ValidationError, match="unknown metric"):
        MetricSample.model_validate(sample(metric="vibes"))


def test_missing_timestamp_rejected():
    s = sample()
    del s["observed_at"]
    with pytest.raises(ValidationError, match="observed_at"):
        MetricSample.model_validate(s)


def test_naive_timestamp_rejected():
    with pytest.raises(ValidationError, match="timezone"):
        MetricSample.model_validate(sample(observed_at="2026-03-10T14:00:00"))


def test_non_utc_offset_is_normalised_to_utc():
    s = MetricSample.model_validate(sample(observed_at="2026-03-10T16:00:00+02:00"))
    assert s.observed_at.isoformat() == "2026-03-10T14:00:00+00:00"


@pytest.mark.parametrize("value", [-1.0, 101.0, float("inf")])
def test_out_of_range_values_rejected(value):
    with pytest.raises(ValidationError):
        MetricSample.model_validate(sample(value=value))


def test_missing_value_field_rejected_but_null_allowed():
    s = sample()
    del s["value"]
    with pytest.raises(ValidationError, match="value"):
        MetricSample.model_validate(s)  # absent field is an error...
    assert MetricSample.model_validate(sample(value=None)).value is None  # ...explicit null is not 0


def test_unknown_field_rejected():
    with pytest.raises(ValidationError, match="Extra inputs"):
        MetricSample.model_validate(sample(valeu=1))


# ---- report / proposal rules ----

def test_abstaining_report_rules():
    base = dict(run_id="r1", severity="unknown", insufficient_evidence=True, observations=[],
                hypotheses=[], citations=[], missing_evidence=[], proposed_next_test=None, limitations=[])
    with pytest.raises(ValidationError, match="list the missing evidence"):
        InvestigationReport.model_validate(base)
    ok = InvestigationReport.model_validate({**base, "missing_evidence": ["fresh metrics for gpu-h21"]})
    assert ok.insufficient_evidence


def test_abstaining_report_cannot_have_hypotheses():
    hyp = Hypothesis(statement="s", confidence="low", supporting_evidence_ids=["E1"], counterevidence=[])
    with pytest.raises(ValidationError, match="must not contain hypotheses"):
        InvestigationReport(run_id="r1", severity="unknown", insufficient_evidence=True, observations=[],
                            hypotheses=[hyp], citations=[], missing_evidence=["x"],
                            proposed_next_test=None, limitations=[])


def test_hypothesis_requires_supporting_evidence():
    with pytest.raises(ValidationError):
        Hypothesis(statement="s", confidence="low", supporting_evidence_ids=[], counterevidence=[])


def test_write_or_deploy_never_not_required():
    kwargs = dict(id="P1", run_id="r1", version=1, description="d", target_scope=["h1"],
                  proposal_hash="a" * 64)
    with pytest.raises(ValidationError, match="can never have approval_status"):
        Proposal(**kwargs, risk_class=RiskClass.WRITE_OR_DEPLOY, approval_status=ApprovalStatus.NOT_REQUIRED)
    assert Proposal(**kwargs, risk_class=RiskClass.WRITE_OR_DEPLOY, approval_status=ApprovalStatus.PENDING)


def test_proposal_hash_format():
    with pytest.raises(ValidationError, match="SHA-256"):
        Proposal(id="P1", run_id="r1", version=1, description="d", target_scope=["h1"],
                 risk_class=RiskClass.READ_ONLY_DIAGNOSTIC, approval_status=ApprovalStatus.NOT_REQUIRED,
                 proposal_hash="short")


# ---- answer key separation ----

def test_answer_keys_exist_for_every_scenario(fixtures):
    for sid in fixtures:
        key = json.loads((EVAL_DIR / f"{sid}.expected.json").read_text(encoding="utf-8"))
        assert key["scenario_id"] == sid and key["synthetic"] is True


def test_runtime_fixtures_contain_no_expected_outcomes():
    for path in FIXTURE_DIR.glob("*.json"):
        text = path.read_text(encoding="utf-8").lower()
        assert "expected_status" not in text and "must_abstain" not in text


def test_runtime_code_never_reads_the_answer_key():
    for path in (BACKEND / "app").rglob("*.py"):
        code = path.read_text(encoding="utf-8")
        assert "evals" not in code.replace("data/evals/", "").replace("(the answer key)", ""), path


def test_fixture_dir_does_not_contain_answer_keys():
    assert not list(FIXTURE_DIR.glob("*expected*"))
