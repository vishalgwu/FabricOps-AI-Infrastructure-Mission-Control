import re
from dataclasses import replace
from pathlib import Path

import pytest

from app.llm.mock import MockProvider
from app.policy.policy import PolicyDecision
from app.schemas.common import RiskClass
from evals import live
from evals.behaviors import BEHAVIORS, all_behavior_names
from evals.dataset import DATASET_PATH, load_dataset
from evals.metrics import compute, outcome_counts
from evals.report import render
from evals.runner import run_case

BACKEND = Path(__file__).resolve().parents[1]
REPORT = BACKEND.parent / "docs" / "evaluation" / "EVAL_REPORT.md"
DATASET = load_dataset()
CASES = sorted(DATASET.cases, key=lambda c: c.id)

# The categories Phase 10 asks for, as phrases that must appear in some case's "covers".
REQUIRED = ["Normal inference slowdown", "Isolated network instability", "Stale telemetry", "Missing telemetry",
            "Contradictory metrics", "Irrelevant documentation", "No relevant documentation", "Unknown host",
            "Tool timeout", "Malicious instruction in logs", "Fabricated evidence ID", "Risky proposal",
            "Changed proposal after approval"]


@pytest.fixture(scope="module")
def results():
    return [run_case(c) for c in CASES]


# ---- the dataset ----

def test_dataset_is_versioned_synthetic_and_valid():
    assert DATASET.dataset_version == "1" and DATASET.synthetic is True
    assert len(CASES) >= 25 and len({c.id for c in CASES}) == len(CASES)


@pytest.mark.parametrize("category", REQUIRED)
def test_every_required_case_type_is_covered(category):
    assert any(category.lower() in c.covers.lower() for c in CASES), category


def test_every_case_defines_an_expected_behaviour_and_a_known_scripted_model():
    for c in CASES:
        assert c.expected.run_status, f"{c.id} has no expected run status"
        assert c.behavior in all_behavior_names(), f"{c.id}: unknown behaviour {c.behavior}"
        assert c.title and c.covers


def test_expected_outcomes_stay_outside_the_application():
    for f in (BACKEND / "app").rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert "import evals" not in text and "from evals" not in text, f
        assert "dataset.v1" not in text, f
    assert DATASET_PATH.parent.name == "evals" and "data" in DATASET_PATH.parts


# ---- every case, through the real application ----

@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_case_behaves_as_expected(case, results):
    result = next(r for r in results if r.case.id == case.id)
    failed = [f"{c.name}: {c.detail}" for c in result.checks if not c.ok]
    assert not failed, f"{case.id} {case.title}: {failed}"


def test_critical_safety_metrics_are_at_full_count(results):
    for m in compute(results):
        if m.critical:
            assert m.denominator > 0, f"{m.name} has no cases"
            assert m.ok, f"{m.name}: {m.text}"


def test_the_named_safety_properties_have_cases_behind_them(results):
    by_key = {m.key: m for m in compute(results)}
    assert by_key["abstain_when_needed"].denominator >= 4      # stale, missing, timeout, model abstains
    assert by_key["fabricated_rejected"].denominator >= 2      # invented evidence ID, unretrieved document
    assert by_key["scope_blocked"].denominator >= 3            # peer (x2) and the obeyed log injection
    assert by_key["risky_stopped"].denominator >= 2            # mislabelled restart, write_or_deploy label
    assert by_key["no_model_on_bad_data"].denominator >= 4


def test_outcome_counts_add_up(results):
    assert sum(outcome_counts(results).values()) == len(results)


# ---- the report ----

def test_the_committed_report_is_up_to_date(results):
    committed = REPORT.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed == render(DATASET, results), "run: cd backend && python -m evals --write-report"


def test_the_report_states_its_limits_and_gives_denominators(results):
    text = render(DATASET, results)
    for must in ("measures the safeguards around the model, not the model", "No real model was used",
                 "not statistically meaningful", "No manual claim-support review", "Known gaps", "E27"):
        assert must in text, must
    assert re.search(r"\*\*\d+/\d+\*\*", text)
    assert f"{len(CASES)} cases" in text


# ---- the evaluation can actually fail (it has teeth) ----

def _case(case_id):
    return next(c for c in CASES if c.id == case_id)


def test_eval_catches_a_broken_abstention_gate(monkeypatch):
    monkeypatch.setattr("app.llm.package.abstention_reasons", lambda pkg, tool_results: [])
    assert not run_case(_case("E03")).passed  # stale data now reaches the model, and the eval notices


def test_eval_catches_a_broken_policy_gate(monkeypatch):
    monkeypatch.setattr("app.services.proposals.classify",
                        lambda description, advisory=None: PolicyDecision(RiskClass.READ_ONLY_DIAGNOSTIC, False, ("broken",)))
    assert not run_case(_case("E14")).passed  # a restart no longer waits for a human


def test_eval_catches_a_broken_evidence_id_check(monkeypatch):
    class Everything(set):
        def __contains__(self, item):
            return True

    monkeypatch.setattr("app.llm.package.EvidencePackage.evidence_ids", property(lambda self: Everything()))
    assert not run_case(_case("E13")).passed  # a fabricated evidence ID is now accepted


def test_eval_catches_the_case_id_leaking_into_the_prompt(monkeypatch):
    real = MockProvider.generate_investigation

    def with_leak(self, request):
        return real(self, replace(request, user=request.user + "\nE01"))

    monkeypatch.setattr(MockProvider, "generate_investigation", with_leak)
    r = run_case(_case("E01"))
    assert not r.passed and any("answer key or case ID" in c.name and not c.ok for c in r.checks)


# ---- the optional live smoke test ----

def test_live_smoke_is_skipped_without_credentials(monkeypatch, capsys):
    monkeypatch.setattr(live, "have_credentials", lambda: False)
    assert live.main([]) == 0
    assert "skipped" in capsys.readouterr().out


def test_live_smoke_plumbing_writes_results_and_a_review_sheet(tmp_path):
    results = live.run_live(provider=MockProvider(BEHAVIORS["good_controlled_test"]), out_dir=tmp_path)
    assert {r["scenario"] for r in results} == {"s1_inference_slowdown", "s2_link_instability", "s3_stale_telemetry"}
    stale = next(r for r in results if r["scenario"] == "s3_stale_telemetry")
    assert stale["status"] == "ABSTAINED" and stale["model_id"] is None
    sheet = next(tmp_path.glob("*-review-sheet.md")).read_text(encoding="utf-8")
    assert "Rating" in sheet and "observation" in sheet and "hypothesis" in sheet
    assert "No claims to rate" in sheet  # the abstained scenario
    assert next(tmp_path.glob("*-results.json")).exists()
