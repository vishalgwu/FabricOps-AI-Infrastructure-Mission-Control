import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import build_proposal_service
from app.core.errors import ConflictError, ForbiddenError, UnauthenticatedError
from app.llm.mock import MockProvider
from app.main import create_app
from app.policy.policy import PolicyViolation, check_scope, classify, compute_proposal_hash
from app.schemas.common import ApprovalStatus, RiskClass, RunStatus
from app.schemas.domain import DecisionKind
from app.storage.db import Database
from app.storage.repositories import ProposalRepository

BACKEND = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 3, 10, 14, 0, tzinfo=timezone.utc)
REVIEWER = {"X-Demo-Reviewer": "demo-reviewer"}
READ_ONLY_TEXT = "Read the host's recent logs and compare with peers."
CONTROLLED_TEXT = "Halve batch_size on gpu-h07 only and compare latency with gpu-h08 for 15 minutes."


class FakeClock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


def answer_with(description, risk="controlled_test", scope=None, next_test=True):
    def build(req):
        body = json.loads(req.user.split("<evidence_package>\n", 1)[1].rsplit("\n</evidence_package>", 1)[0])
        affected = body["incident"]["affected_hosts"]
        ids = [e["id"] for e in body["evidence"] if e["host_id"] in affected and e["source_type"] == "metric"]
        return {
            "observations": [{"statement": "A metric on the affected host differs from its peers.",
                              "evidence_ids": ids[:2]}],
            "hypotheses": [{"statement": "A resource problem on the affected host is suspected.",
                            "supporting_evidence_ids": ids[:1], "opposing_evidence_ids": [], "counterevidence": [],
                            "confidence": "medium", "uncertainty": "cause not isolated", "citations": []}],
            "missing_evidence": [],
            "next_test": {"description": description, "target_scope": scope or affected, "risk_class": risk}
            if next_test else None,
            "abstain": False, "abstain_reason": "", "limitations": [], "document_citations": [],
        }
    return build


def make(tmp_path, answer, clock=None, reviewers=None):
    clock = clock or FakeClock()
    app = create_app(str(tmp_path / "p.db"), provider=MockProvider(answer), clock=clock, reviewers=reviewers)
    return TestClient(app), app, clock


def run_incident(client, scenario="inference_slowdown", hosts=("gpu-h07",)):
    inc = client.post("/api/incidents", json={
        "title": "t", "description": "Responses are slow on the affected host.", "scenario_type": scenario,
        "severity": "high", "affected_hosts": list(hosts)}).json()
    run = client.post(f"/api/incidents/{inc['id']}/runs").json()
    return inc, client.get(f"/api/runs/{run['id']}").json()


def proposal_of(client, run_id):
    return client.get(f"/api/runs/{run_id}/proposal").json()


def decide(client, proposal, decision="approved", headers=REVIEWER, **over):
    body = {"decision": decision, "proposal_hash": proposal["proposal"]["proposal_hash"], "reason": "looks right"}
    body.update(over)
    return client.post(f"/api/proposals/{proposal['proposal']['id']}/decision", json=body, headers=headers)


@pytest.fixture
def waiting(tmp_path):
    client, app, clock = make(tmp_path, answer_with(CONTROLLED_TEXT))
    _, run = run_incident(client)
    assert run["status"] == "WAITING_APPROVAL"
    return client, app, clock, run, proposal_of(client, run["id"])


# ---------------- classification is deterministic and independent of the model ----------------

@pytest.mark.parametrize("text", [
    "Read the NIC log on net-h01 for retrain events.", "Compare error counters with peers over the last hour.",
    "Check the link configuration against the peers.", "Inspect and review the serving log for eviction messages."])
def test_read_only_wording(text):
    d = classify(text)
    assert d.risk_class == RiskClass.READ_ONLY_DIAGNOSTIC and not d.requires_approval


@pytest.mark.parametrize("text", [
    CONTROLLED_TEXT, "Swap the cable on net-h01 and compare error counters.", "Adjust max_sequence_length on gpu-h07.",
    "Throttle new requests to gpu-h07 for ten minutes.", "Run a controlled test on one host."])
def test_controlled_wording(text):
    d = classify(text)
    assert d.risk_class == RiskClass.CONTROLLED_TEST and d.requires_approval


@pytest.mark.parametrize("text", [
    "Restart the serving process on gpu-h07.", "Reboot the host and watch latency.", "Deploy the previous release.",
    "Roll back the configuration change.", "Drain the node, then upgrade the firmware.", "Delete the cache directory.",
    "Run `systemctl restart inference`.", "Power cycle the switch.", "Disable the exporter and re-enable it."])
def test_write_wording(text):
    d = classify(text)
    assert d.risk_class == RiskClass.WRITE_OR_DEPLOY and d.requires_approval


def test_unrecognised_wording_is_never_assumed_safe():
    assert classify("Ponder the situation.").risk_class == RiskClass.CONTROLLED_TEST


def test_the_models_label_can_raise_the_class_but_never_lower_it():
    lowered = classify("Restart the serving process on gpu-h07.", RiskClass.READ_ONLY_DIAGNOSTIC)
    assert lowered.risk_class == RiskClass.WRITE_OR_DEPLOY and any("overrode" in r for r in lowered.reasons)
    raised = classify(READ_ONLY_TEXT, RiskClass.CONTROLLED_TEST)
    assert raised.risk_class == RiskClass.CONTROLLED_TEST and raised.requires_approval
    same = classify(READ_ONLY_TEXT, RiskClass.READ_ONLY_DIAGNOSTIC)
    assert same.risk_class == RiskClass.READ_ONLY_DIAGNOSTIC


def test_policy_is_deterministic_and_has_no_model_dependency():
    assert classify(CONTROLLED_TEXT, RiskClass.CONTROLLED_TEST) == classify(CONTROLLED_TEXT, RiskClass.CONTROLLED_TEST)
    imports = [ln for ln in (BACKEND / "app" / "policy" / "policy.py").read_text(encoding="utf-8").splitlines()
               if ln.startswith(("import ", "from "))]
    for ln in imports:
        for banned in ("app.llm", "anthropic", "random", "openai", "requests", "httpx"):
            assert banned not in ln, ln


def test_scope_must_stay_within_affected_hosts():
    check_scope(["gpu-h07"], ["gpu-h07"])
    for scope in ([], ["gpu-h08"], ["gpu-h07", "gpu-h08"]):
        with pytest.raises(PolicyViolation):
            check_scope(scope, ["gpu-h07"])


# ---------------- hashing ----------------

BASE = dict(run_id="r1", version=1, description="d", parameters={"a": 1}, target_scope=["h1"],
            risk_class=RiskClass.CONTROLLED_TEST, evidence_digests={"e1": "x"})


def test_hash_is_stable_and_covers_every_material_field():
    h = compute_proposal_hash(**BASE)
    assert h == compute_proposal_hash(**BASE) and len(h) == 64
    assert compute_proposal_hash(**{**BASE, "target_scope": ["h1"]}) == h
    for change in ({"description": "d2"}, {"parameters": {"a": 2}}, {"target_scope": ["h2"]}, {"version": 2},
                   {"risk_class": RiskClass.WRITE_OR_DEPLOY}, {"evidence_digests": {"e1": "y"}},
                   {"evidence_digests": {"e1": "x", "e2": "z"}}, {"run_id": "r2"}):
        assert compute_proposal_hash(**{**BASE, **change}) != h, change


# ---------------- workflow integration ----------------

def test_read_only_proposal_needs_no_approval(tmp_path):
    client, _, _ = make(tmp_path, answer_with(READ_ONLY_TEXT, "read_only_diagnostic"))
    _, run = run_incident(client)
    assert run["status"] == "COMPLETE"
    view = proposal_of(client, run["id"])
    p = view["proposal"]
    assert p["risk_class"] == "read_only_diagnostic" and p["approval_status"] == "not_required"
    assert p["expires_at"] is None and view["execution_enabled"] is False
    r = decide(client, view)
    assert r.status_code == 409 and r.json()["error"]["code"] == "approval_not_required"


def test_controlled_proposal_parks_the_run_until_a_human_decides(waiting):
    client, _, clock, run, view = waiting
    p = view["proposal"]
    assert p["risk_class"] == "controlled_test" and p["approval_status"] == "pending"
    assert p["version"] == 1 and len(p["proposal_hash"]) == 64 and p["target_scope"] == ["gpu-h07"]
    assert p["evidence_ids"] and p["policy_reasons"] and p["run_id"] == run["id"]
    assert datetime.fromisoformat(p["expires_at"].replace("Z", "+00:00")) == clock.now + timedelta(hours=24)
    assert view["decision"] is None and view["execution_enabled"] is False
    evs = client.get(f"/api/runs/{run['id']}/events").json()["events"]
    policy = next(json.loads(e["detail"]) for e in evs if e["event_type"] == "stage_completed"
                  and json.loads(e["detail"])["stage"] == "apply_policy")
    assert policy["approval_status"] == "pending" and policy["executed"] is False
    assert any(e["event_type"] == "proposal_created" for e in evs)
    assert [e["to_status"] for e in evs if e["event_type"] == "status_changed"] == ["RUNNING", "WAITING_APPROVAL"]
    assert client.get(f"/api/runs/{run['id']}/report").status_code == 200


def test_a_model_that_mislabels_a_restart_as_read_only_is_overridden(tmp_path):
    client, _, _ = make(tmp_path, answer_with("Restart the serving process on gpu-h07.", "read_only_diagnostic"))
    _, run = run_incident(client)
    p = proposal_of(client, run["id"])["proposal"]
    assert run["status"] == "WAITING_APPROVAL"
    assert p["risk_class"] == "write_or_deploy" and p["approval_status"] == "pending"
    assert any("overrode" in r for r in p["policy_reasons"])


def test_write_class_labelled_by_the_model_is_rejected_before_policy(tmp_path):
    client, _, _ = make(tmp_path, answer_with("Restart gpu-h07.", "write_or_deploy"))
    _, run = run_incident(client)
    assert run["status"] == "FAILED" and run["error_code"] == "model_output_rejected"


def test_no_proposal_when_the_model_suggests_none_or_abstains(tmp_path):
    client, _, _ = make(tmp_path, answer_with("x", next_test=False))
    _, run = run_incident(client)
    assert run["status"] == "COMPLETE"
    assert client.get(f"/api/runs/{run['id']}/proposal").status_code == 404
    _, stale = run_incident(client, "stale_telemetry", ("gpu-h21",))
    assert stale["status"] == "ABSTAINED" and client.get(f"/api/runs/{stale['id']}/proposal").status_code == 404


# ---------------- authorisation ----------------

def test_decisions_need_an_authorised_reviewer(waiting):
    client, _, _, _, view = waiting
    r = decide(client, view, headers={})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"
    r = decide(client, view, headers={"X-Demo-Reviewer": "mallory"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert proposal_of(client, view["proposal"]["run_id"])["proposal"]["approval_status"] == "pending"


def test_the_actor_cannot_be_claimed_in_the_request_body(waiting):
    client, _, _, _, view = waiting
    assert decide(client, view, actor="demo-reviewer", headers={}).status_code == 422


def test_reviewers_come_from_backend_configuration(tmp_path):
    client, _, _ = make(tmp_path, answer_with(CONTROLLED_TEXT), reviewers=frozenset({"alice"}))
    _, run = run_incident(client)
    view = proposal_of(client, run["id"])
    assert decide(client, view, headers=REVIEWER).status_code == 403
    assert decide(client, view, headers={"X-Demo-Reviewer": "alice"}).status_code == 201


# ---------------- approve / reject ----------------

def test_approval_is_recorded_bound_to_the_hash_and_executes_nothing(waiting):
    client, app, clock, run, view = waiting
    clock.now += timedelta(hours=1)
    r = decide(client, view, "approved", reason="Safe to try on one host.")
    assert r.status_code == 201
    body = r.json()
    d, p = body["decision"], body["proposal"]
    assert p["approval_status"] == "approved" and body["execution_enabled"] is False
    assert (d["actor"], d["decision"], d["reason"]) == ("demo-reviewer", "approved", "Safe to try on one host.")
    assert d["proposal_hash"] == view["proposal"]["proposal_hash"] and d["proposal_id"] == p["id"]
    assert datetime.fromisoformat(d["created_at"].replace("Z", "+00:00")) == clock.now
    assert client.get(f"/api/runs/{run['id']}").json()["status"] == "COMPLETE"
    evs = client.get(f"/api/runs/{run['id']}/events").json()["events"]
    assert any(e["event_type"] == "approval_decision" for e in evs)
    assert not any("exec" in e["event_type"] for e in evs)


def test_rejection_is_recorded_and_triggers_nothing(waiting):
    client, _, _, run, view = waiting
    r = decide(client, view, "rejected", reason="Too risky right now.")
    assert r.status_code == 201 and r.json()["proposal"]["approval_status"] == "rejected"
    assert r.json()["execution_enabled"] is False
    assert client.get(f"/api/runs/{run['id']}").json()["status"] == "COMPLETE"
    assert client.get(f"/api/runs/{run['id']}/report").status_code == 200  # the analysis is still there


def test_write_class_proposals_can_be_decided_but_never_run(tmp_path):
    client, _, _ = make(tmp_path, answer_with("Restart the serving process on gpu-h07.", "controlled_test"))
    _, run = run_incident(client)
    view = proposal_of(client, run["id"])
    assert decide(client, view, "approved").json()["execution_enabled"] is False


def test_repeating_a_decision_is_idempotent(waiting):
    client, app, _, run, view = waiting
    first = decide(client, view, "approved")
    again = decide(client, view, "approved")
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["decision"]["id"] == again.json()["decision"]["id"]
    with app.state.db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM approval_decisions").fetchone()[0] == 1
    evs = client.get(f"/api/runs/{run['id']}/events").json()["events"]
    assert [e["event_type"] for e in evs].count("approval_decision") == 1
    assert [e["to_status"] for e in evs if e["event_type"] == "status_changed"].count("COMPLETE") == 1


def test_a_conflicting_second_decision_is_refused(waiting):
    client, _, _, _, view = waiting
    assert decide(client, view, "approved").status_code == 201
    r = decide(client, view, "rejected")
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_decided"
    assert proposal_of(client, view["proposal"]["run_id"])["proposal"]["approval_status"] == "approved"


def test_a_decision_for_a_different_hash_is_refused(waiting):
    client, _, _, _, view = waiting
    r = decide(client, view, proposal_hash="0" * 64)
    assert r.status_code == 409 and r.json()["error"]["code"] == "proposal_changed"
    assert decide(client, view, proposal_hash="not-a-hash").status_code == 422
    assert decide(client, view, reason="").status_code == 422
    assert client.post("/api/proposals/prop_missing/decision", headers=REVIEWER,
                       json={"decision": "approved", "proposal_hash": "0" * 64, "reason": "x"}).status_code == 404


def test_concurrent_decisions_record_exactly_one(waiting):
    client, app, _, _, view = waiting
    p = view["proposal"]
    results = []

    def go(decision):
        svc = build_proposal_service(app)
        try:
            results.append(svc.decide(p["id"], "demo-reviewer", decision, p["proposal_hash"], "race")[2:])
        except ConflictError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=go, args=(DecisionKind.APPROVED if i % 2 else DecisionKind.REJECTED,))
               for i in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    with app.state.db.connect() as c:
        rows = c.execute("SELECT decision FROM approval_decisions").fetchall()
    assert len(rows) == 1
    created = [r for r in results if isinstance(r, tuple) and r[0] is True]
    assert len(created) == 1
    winner = rows[0][0]
    assert all(r in ("already_decided",) or isinstance(r, tuple) for r in results)
    assert client.get(f"/api/proposals/{p['id']}").json()["proposal"]["approval_status"] == winner


# ---------------- expiry ----------------

def test_pending_proposals_expire_and_cancel_the_run(waiting):
    client, _, clock, run, view = waiting
    clock.now += timedelta(hours=23)
    assert client.get(f"/api/proposals/{view['proposal']['id']}").json()["proposal"]["approval_status"] == "pending"
    clock.now += timedelta(hours=2)
    got = client.get(f"/api/proposals/{view['proposal']['id']}").json()
    assert got["proposal"]["approval_status"] == "expired"
    cancelled = client.get(f"/api/runs/{run['id']}").json()
    assert cancelled["status"] == "CANCELLED" and cancelled["error_code"] == "approval_expired"
    r = decide(client, view)
    assert r.status_code == 409 and r.json()["error"]["code"] == "proposal_expired"


def test_deciding_after_expiry_fails_even_without_a_prior_read(waiting):
    client, _, clock, run, view = waiting
    clock.now += timedelta(hours=25)
    r = decide(client, view)
    assert r.status_code == 409 and r.json()["error"]["code"] == "proposal_expired"
    assert client.get(f"/api/runs/{run['id']}").json()["status"] == "CANCELLED"


def test_a_decision_made_in_time_stands_after_the_expiry_time(waiting):
    client, _, clock, run, view = waiting
    clock.now += timedelta(hours=1)
    assert decide(client, view).status_code == 201
    clock.now += timedelta(days=3)
    got = client.get(f"/api/proposals/{view['proposal']['id']}").json()
    assert got["proposal"]["approval_status"] == "approved"
    assert client.get(f"/api/runs/{run['id']}").json()["status"] == "COMPLETE"


# ---------------- changed proposals cannot reuse an approval ----------------

def test_revising_a_proposal_invalidates_the_old_approval(waiting):
    client, app, _, run, view = waiting
    old = view["proposal"]
    assert decide(client, view).status_code == 201
    svc = build_proposal_service(app)
    new = svc.revise(old["id"], ["gpu-h07"], description="Halve batch_size on gpu-h07 and watch for 30 minutes.")
    assert new.version == 2 and new.proposal_hash != old["proposal_hash"]
    assert new.approval_status == ApprovalStatus.PENDING and svc.decision_for(new) is None
    assert ProposalRepository(app.state.db).get(old["id"], 1).approval_status == ApprovalStatus.EXPIRED
    stale = decide(client, view)  # the reviewer still holds the old hash
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "proposal_changed"
    fresh = client.get(f"/api/proposals/{old['id']}").json()
    assert fresh["proposal"]["version"] == 2 and fresh["decision"] is None
    ok = decide(client, fresh)
    assert ok.status_code == 201 and ok.json()["decision"]["proposal_hash"] == new.proposal_hash


def test_a_revision_that_changes_only_the_evidence_changes_the_hash(waiting):
    _, app, _, _, view = waiting
    svc = build_proposal_service(app)
    old = svc.get(view["proposal"]["id"])
    fewer = svc.revise(old.id, ["gpu-h07"], evidence_ids=old.evidence_ids[:1])
    assert fewer.proposal_hash != old.proposal_hash and fewer.evidence_ids == old.evidence_ids[:1]


def test_a_revision_cannot_widen_the_scope_or_cite_foreign_evidence(waiting):
    _, app, _, _, view = waiting
    svc = build_proposal_service(app)
    pid = view["proposal"]["id"]
    with pytest.raises(PolicyViolation):
        svc.revise(pid, ["gpu-h07"], target_scope=["gpu-h07", "gpu-h08"])
    with pytest.raises(ConflictError, match="does not belong"):
        svc.revise(pid, ["gpu-h07"], evidence_ids=["ev_not_this_run"])
    assert svc.get(pid).version == 1  # failed revisions leave the proposal untouched


def test_authorisation_checks_in_the_service():
    class Dummy:
        pass

    svc = build_proposal_service.__globals__["ProposalService"](Dummy(), Dummy(), Dummy(), frozenset({"a"}))
    assert svc.authorize("a") == "a"
    with pytest.raises(UnauthenticatedError):
        svc.authorize(None)
    with pytest.raises(ForbiddenError):
        svc.authorize("b")


# ---------------- persistence ----------------

def test_proposals_and_decisions_survive_a_restart(tmp_path):
    client, _, clock = make(tmp_path, answer_with(CONTROLLED_TEXT))
    _, run = run_incident(client)
    view = proposal_of(client, run["id"])
    decided = decide(client, view, "rejected", reason="not now").json()
    reopened = TestClient(create_app(str(tmp_path / "p.db"), clock=clock))  # new app, same file, no provider
    again = reopened.get(f"/api/proposals/{view['proposal']['id']}").json()
    assert again["proposal"] == decided["proposal"] and again["decision"] == decided["decision"]
    assert reopened.get(f"/api/runs/{run['id']}/proposal").json() == again
    replay = decide(reopened, view, "rejected", reason="not now")
    assert replay.status_code == 200 and replay.json()["decision"]["id"] == decided["decision"]["id"]


def test_schema_migration_from_v2_database(tmp_path):
    path = tmp_path / "v2.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE proposals (id TEXT NOT NULL, version INTEGER NOT NULL, run_id TEXT NOT NULL,
            description TEXT NOT NULL, parameters TEXT NOT NULL, target_scope TEXT NOT NULL, risk_class TEXT NOT NULL,
            approval_status TEXT NOT NULL, proposal_hash TEXT NOT NULL, expires_at TEXT, created_at TEXT NOT NULL,
            PRIMARY KEY (id, version));
        INSERT INTO proposals VALUES ('prop_old', 1, 'run_old', 'Read logs', '{}', '["h1"]', 'read_only_diagnostic',
            'not_required', '%s', NULL, '2026-01-01T00:00:00.000000Z');
        PRAGMA user_version = 2;""" % ("a" * 64))
    conn.commit()
    conn.close()
    repo = ProposalRepository(Database(str(path)))
    old = repo.get("prop_old")
    assert old.evidence_ids == [] and old.policy_reasons == [] and old.approval_status == ApprovalStatus.NOT_REQUIRED


# ---------------- there is no execution code ----------------

def test_no_execution_adapter_exists_anywhere_in_the_app():
    banned = ("subprocess", "os.system", "os.popen", "paramiko", "import fabric", "from fabric ", "import socket", "import urllib", "import requests", "import httpx",
              "eval(", "exec(", "shell=True")
    for f in (BACKEND / "app").rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        for word in banned:
            assert word not in text, f"{f.relative_to(BACKEND)} contains {word}"
    import re

    for f in (BACKEND / "app").rglob("*.py"):  # no function that could run a proposal, whatever its docs say
        assert not re.search(r"def\s+\w*(remediat|execute_proposal|apply_proposal|run_command)\w*",
                             f.read_text(encoding="utf-8")), f
    modules = {p.stem for p in (BACKEND / "app").rglob("*.py")}
    assert not {"executor", "remediation", "runner", "actions"} & modules


def test_the_only_state_a_decision_changes_is_recorded_state(waiting):
    client, app, _, run, view = waiting
    with app.state.db.connect() as c:
        before = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("incidents", "evidence", "investigation_reports", "proposals")}
    decide(client, view, "approved")
    with app.state.db.connect() as c:
        after = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in before}
    assert before == after  # approving added a decision row and a status change, nothing else
    assert RunStatus.COMPLETE.value == client.get(f"/api/runs/{run['id']}").json()["status"]
