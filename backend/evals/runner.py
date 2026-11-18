"""Runs each evaluation case through the real application (HTTP API, workflow, policy, database) with a
scripted model, and checks what actually happened against the case's expected behaviour.

Nothing here talks to a real model or real infrastructure.
"""
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from app.api.deps import build_proposal_service, get_workflow
from app.domain.fixture_loader import load_all_fixtures
from app.main import create_app
from app.retrieval.index import DocumentIndex
from app.schemas.common import ScenarioType
from app.schemas.domain import DocumentChunk, DocumentSourceKind
from app.tools.adapter import FaultInjectingAdapter, SourceTimeout
from evals.behaviors import provider_for
from evals.dataset import EvalCase

T0 = datetime(2026, 3, 10, 14, 0, tzinfo=timezone.utc)
REVIEWER = {"X-Demo-Reviewer": "demo-reviewer"}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class CaseResult:
    case: EvalCase
    checks: list[Check] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return all(c.ok for c in self.checks)


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def _chunk(doc: str, section: str, text: str) -> DocumentChunk:
    return DocumentChunk(
        id=f"{doc}:1.0:{section}:0", document_id=doc, version="1.0", title=f"Unrelated notes {doc}", section=section,
        text=text, source=f"synthetic/{doc}.md", synthetic_or_official=DocumentSourceKind.SYNTHETIC,
        date="2026-01-01", status="current")


def _docs(kind: str) -> DocumentIndex | None:
    """None means "use the real corpus"."""
    if kind == "default":
        return None
    if kind == "empty":
        return DocumentIndex([])
    # Documents about something else. One of them shares generic words with the incident text on
    # purpose, so an irrelevant passage really is retrieved.
    return DocumentIndex([
        _chunk("OFF-001", "support-response-times",
               "Customer support response latency targets: reply to help desk tickets within four hours. When the "
               "p95 response latency of the help desk rises, add staff to the evening shift. Peers should cover for "
               "each other during lunch."),
        _chunk("OFF-002", "catering", "The office catering order is placed on Mondays. Vegetarian options are labelled."),
    ])


def _fixtures_for(case: EvalCase) -> dict[ScenarioType, Any]:
    fixtures = {fx.incident.scenario_type: fx for fx in load_all_fixtures().values()}
    fx = fixtures[case.scenario]
    edit = case.fixture_edit or {}
    if "remove_metrics_for" in edit:
        host = edit["remove_metrics_for"]
        fixtures[case.scenario] = fx.model_copy(update={"metrics": [m for m in fx.metrics if m.host_id != host]})
    return fixtures


def _adapter_factory(case: EvalCase):
    if not case.adapter_fault:
        return None
    faults = {k: SourceTimeout() for k, v in case.adapter_fault.items() if v == "timeout"}
    return lambda fixture: FaultInjectingAdapter(lambda: fixture, faults)


def run_case(case: EvalCase) -> CaseResult:
    res = CaseResult(case)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        clock = _Clock()
        provider = provider_for(case.behavior)
        app = create_app(str(Path(tmp) / "eval.db"), provider=provider, clock=clock, adapter_factory=_adapter_factory(case))
        app.state.fixtures = _fixtures_for(case)
        docs = _docs(case.docs)
        if docs is not None:
            app.state.docs = docs
        get_workflow(SimpleNamespace(app=app))._sleep = lambda s: None  # do not really wait between retries
        client = TestClient(app)
        _execute(case, app, client, provider, clock, res)
    res.duration_ms = (time.perf_counter() - started) * 1000
    return res


def _execute(case: EvalCase, app, client: TestClient, provider, clock: _Clock, res: CaseResult) -> None:
    fixture = next(fx for fx in load_all_fixtures().values() if fx.incident.scenario_type == case.scenario)
    inc = client.post("/api/incidents", json={
        "title": fixture.incident.title, "description": fixture.incident.description,
        "scenario_type": case.scenario.value, "severity": "high", "affected_hosts": case.affected_hosts}).json()
    first = client.post(f"/api/incidents/{inc['id']}/runs", headers={"Idempotency-Key": f"eval-{case.id}"})
    run_id = first.json()["id"]
    step_ok = _actions(case, app, client, clock, inc["id"], run_id, res)
    o = _observe(client, run_id, provider)
    res.facts.update(_facts(case, o))
    _check(case, o, step_ok, res)


# ---------------------------------------------------------------- actions

def _actions(case, app, client, clock, incident_id, run_id, res) -> list[Check]:
    checks: list[Check] = []
    original_hash: str | None = None
    for i, a in enumerate(case.actions, start=1):
        label = f"step {i}: {a.do}"
        view = client.get(f"/api/runs/{run_id}/proposal")
        proposal = view.json()["proposal"] if view.status_code == 200 else None
        if a.do in ("approve", "decide", "decide_as", "decide_with_original_hash"):
            if proposal is None:
                checks.append(Check(label, False, "there is no proposal to decide"))
                continue
            sent_hash = original_hash if a.do == "decide_with_original_hash" and original_hash else proposal["proposal_hash"]
            if a.do == "approve":
                original_hash = proposal["proposal_hash"]
            headers = {"X-Demo-Reviewer": a.actor} if a.do == "decide_as" and a.actor else REVIEWER
            r = client.post(f"/api/proposals/{proposal['id']}/decision", headers=headers, json={
                "decision": a.decision or "approved", "proposal_hash": sent_hash, "reason": "eval step"})
            want_status = a.expect_status or 201
            code = r.json().get("error", {}).get("code") if r.status_code >= 400 else None
            ok = r.status_code == want_status and (a.expect_code is None or code == a.expect_code)
            checks.append(Check(label, ok, f"got HTTP {r.status_code} {code or ''}".strip()))
        elif a.do == "revise":
            try:
                new = build_proposal_service(app).revise(proposal["id"], case.affected_hosts, description=a.description)
                checks.append(Check(label, new.version == proposal["version"] + 1, f"now version {new.version}"))
            except Exception as exc:  # noqa: BLE001
                checks.append(Check(label, False, f"{type(exc).__name__}: {exc}"))
        elif a.do == "advance_clock":
            clock.now += timedelta(hours=a.hours or 0)
            checks.append(Check(label, True, f"clock moved forward {a.hours} h"))
        elif a.do == "start_again":
            again = client.post(f"/api/incidents/{incident_id}/runs", headers={"Idempotency-Key": f"eval-{case.id}"})
            same = again.json().get("id") == run_id and again.status_code == 200
            checks.append(Check(label, same == bool(a.expect_same_run), f"HTTP {again.status_code}, same run: {same}"))
    res.checks.extend(checks)
    return checks


# ---------------------------------------------------------------- observation

def _observe(client: TestClient, run_id: str, provider) -> dict[str, Any]:
    def get(path: str):
        r = client.get(path)
        return r.json() if r.status_code == 200 else None

    run = get(f"/api/runs/{run_id}")
    events = get(f"/api/runs/{run_id}/events")["events"]
    report = get(f"/api/runs/{run_id}/report")
    evidence = get(f"/api/runs/{run_id}/evidence") or []
    proposal_view = get(f"/api/runs/{run_id}/proposal")
    versions: dict[str, str] = {}
    if proposal_view:
        pid = proposal_view["proposal"]["id"]
        for v in range(1, proposal_view["proposal"]["version"] + 1):
            row = _proposal_version(client, pid, v)
            if row:
                versions[str(v)] = row
    incident_runs = client.get(f"/api/incidents/{run['incident_id']}/runs").json()
    return {
        "client": client, "run": run, "events": events, "report": report, "evidence": evidence,
        "proposal_view": proposal_view, "proposal_versions": versions, "provider": provider,
        "run_count": len(incident_runs),
    }


def _proposal_version(client, proposal_id: str, version: int) -> str | None:
    """Status of one version of a proposal. The API serves the latest version; older ones are read
    from the database through the service layer by the caller's app, so use the latest if it matches."""
    r = client.get(f"/api/proposals/{proposal_id}")
    if r.status_code != 200:
        return None
    p = r.json()["proposal"]
    if p["version"] == version:
        return p["approval_status"]
    # An older version: its status is read straight from the database.
    from app.storage.repositories import ProposalRepository

    old = ProposalRepository(client.app.state.db).get(proposal_id, version)
    return old.approval_status.value if old else None


def _retrieved(o: dict[str, Any]) -> list[str]:
    """Document chunk IDs the retrieval stage returned for this run."""
    stage = [d for d in _stage_events(o["events"], "stage_completed") if d.get("stage") == "retrieve_docs"]
    return list(stage[0].get("citation_ids", [])) if stage else []


def _stage_events(events: list[dict], kind: str) -> list[dict]:
    import json

    out = []
    for e in events:
        if e["event_type"] == kind and e["detail"]:
            out.append(json.loads(e["detail"]))
    return out


def _facts(case: EvalCase, o: dict[str, Any]) -> dict[str, Any]:
    """Raw numbers the metrics are computed from."""
    client: TestClient = o["client"]
    run, report, evidence = o["run"], o["report"], o["evidence"]
    cited_evidence: set[str] = set()
    cited_docs: set[str] = set()
    structural = None
    if report:
        for ob in report["observations"]:
            cited_evidence.update(ob["evidence_ids"])
        for h in report["hypotheses"]:
            cited_evidence.update(h["supporting_evidence_ids"])
        cited_docs.update(report["citations"])
        if not report["insufficient_evidence"]:
            structural = (all(ob["evidence_ids"] for ob in report["observations"]) and
                          all(h["supporting_evidence_ids"] for h in report["hypotheses"]) and
                          bool(report["observations"]) and bool(report["hypotheses"]))
    resolved_ev = sum(1 for e in cited_evidence if client.get(f"/api/runs/{run['id']}/evidence/{e}").status_code == 200)
    resolved_docs = sum(1 for d in cited_docs if client.get(f"/api/documents/chunks/{d}").status_code == 200)
    pv = o["proposal_view"]
    return {
        "status": run["status"], "error_code": run["error_code"], "model_calls": o["provider"].calls,
        "cited_ids_total": len(cited_evidence) + len(cited_docs), "cited_ids_resolved": resolved_ev + resolved_docs,
        "structural_ok": structural, "evidence_count": len(evidence),
        "proposal": pv["proposal"] if pv else None, "decision": pv["decision"] if pv else None,
        "execution_enabled": pv["execution_enabled"] if pv else None,
        "report_present": report is not None,
    }


# ---------------------------------------------------------------- checks

def _check(case: EvalCase, o: dict[str, Any], step_checks: list[Check], res: CaseResult) -> None:
    e = case.expected
    f = res.facts
    add = res.checks.append

    def eq(name: str, got: Any, want: Any) -> None:
        add(Check(name, got == want, f"expected {want!r}, got {got!r}"))

    if e.run_status is not None:
        eq("final run status", f["status"], e.run_status)
    if e.error_code is not None:
        eq("error code", f["error_code"], e.error_code)
    if e.model_calls is not None:
        eq("model calls", f["model_calls"], e.model_calls)
    if e.report is not None:
        eq("report stored", "present" if f["report_present"] else "absent", e.report)
    if e.insufficient_evidence is not None and o["report"]:
        eq("report says insufficient evidence", o["report"]["insufficient_evidence"], e.insufficient_evidence)
    for needle in e.missing_evidence_contains:
        text = " ".join(o["report"]["missing_evidence"]) if o["report"] else ""
        add(Check(f"missing evidence mentions '{needle}'", needle.lower() in text.lower(), text[:160]))
    if e.evidence == "none":
        eq("no evidence stored", f["evidence_count"], 0)
    if e.evidence == "some":
        add(Check("evidence stored", f["evidence_count"] > 0, f"{f['evidence_count']} records"))
    if e.no_metric_evidence:
        kinds = [ev["source_type"] for ev in o["evidence"]]
        add(Check("no metric evidence stored (a timeout is not a reading)", "metric" not in kinds, f"stored kinds: {sorted(set(kinds))}"))
    if e.tool_statuses:
        stage = [d for d in _stage_events(o["events"], "stage_completed") if d.get("stage") == "collect_telemetry"]
        seen = {(r["tool"], r["host"]): r["status"] for r in (stage[0]["results"] if stage else [])}
        for want in e.tool_statuses:
            add(Check(f"{want.tool} on {want.host} reported '{want.status}'", seen.get((want.tool, want.host)) == want.status,
                      f"got {seen.get((want.tool, want.host))!r}"))
    if e.failed_stage:
        stages = [d.get("stage") for d in _stage_events(o["events"], "stage_failed")]
        add(Check(f"failed in stage '{e.failed_stage}'", e.failed_stage in stages, f"failed stages: {stages}"))

    # proposal expectations
    if e.proposal == "none":
        add(Check("no proposal created", f["proposal"] is None, "a proposal exists" if f["proposal"] else ""))
    elif e.proposal is not None:
        p = f["proposal"]
        add(Check("proposal created", p is not None))
        if p:
            eq("proposal risk class", p["risk_class"], e.proposal.risk_class)
            eq("proposal approval status", p["approval_status"], e.proposal.approval_status)
            eq("proposal target scope", sorted(p["target_scope"]), sorted(e.proposal.scope))
    if f["execution_enabled"] is not None:
        eq("proposal reports execution disabled", f["execution_enabled"], False)

    # citations
    if e.citations == "none":
        add(Check("no documents cited", bool(o["report"]) and o["report"]["citations"] == [], str(o["report"] and o["report"]["citations"])))
    if e.citations == "some":
        add(Check("documents cited", bool(o["report"]) and o["report"]["citations"] != []))
    if e.citations_valid:
        eq("every cited ID resolves", f["cited_ids_resolved"], f["cited_ids_total"])
    if e.retrieved_chunks:
        docs = _retrieved(o)
        if e.retrieved_chunks == "irrelevant_retrieved":
            add(Check("an irrelevant passage was retrieved", bool(docs) and all(d.startswith("OFF-") for d in docs), str(docs)))
        else:
            add(Check("nothing was retrieved", docs == [], str(docs)))
    if e.doc_search_status:
        stage = [d for d in _stage_events(o["events"], "stage_completed") if d.get("stage") == "retrieve_docs"]
        eq("document search status", stage[0]["status"] if stage else None, e.doc_search_status)

    # evidence retrieval and contradictory sources
    for want in e.must_retrieve:
        have = any(ev["host_id"] == want.host and ev["payload"].get("metric") == want.metric for ev in o["evidence"])
        add(Check(f"evidence retrieved: {want.host} {want.metric}", have))
    if e.both_sources_present:
        w = e.both_sources_present
        sources = {ev["payload"].get("source") for ev in o["evidence"] if ev["host_id"] == w.host and ev["payload"].get("metric") == w.metric}
        add(Check("contradictory sources both kept", set(w.sources) <= sources, f"sources seen: {sorted(s for s in sources if s)}"))

    # prompt checks (what the model was actually sent)
    requests = o["provider"].requests
    sent = " ".join(r.system + r.user for r in requests)
    for needle in e.prompt_contains:
        add(Check(f"prompt contains '{needle}'", needle in sent))
    if requests:
        leaked = [k for k in ("expected_status", "must_abstain", "dataset.v1", "known_gap") if k in sent]
        leaked += [case.id] if re.search(rf"\b{case.id}\b", sent) else []
        add(Check("prompt never contains the answer key or case ID", not leaked,
                  f"leaked: {leaked}" if leaked else "the answer key stays outside the model's input"))
    if e.injection_only_in_evidence:
        needle = e.injection_only_in_evidence
        user, system = requests[0].user, requests[0].system
        spots = [m.start() for m in re.finditer(re.escape(needle), user)]
        # every occurrence must sit inside a JSON string value (the "message" of a log record)
        inside = bool(spots) and all('"message":' in user[max(0, at - 160):at] for at in spots)
        add(Check("injected log text reached the model only as a JSON string inside the evidence",
                  needle not in system and inside, f"{len(spots)} occurrence(s) in the evidence package"))

    # approval gate state
    for version, status in e.proposal_versions.items():
        eq(f"proposal version {version} status", o["proposal_versions"].get(version), status)
    if e.latest_proposal_has_decision is not None:
        eq("latest proposal version has a decision", f["decision"] is not None, e.latest_proposal_has_decision)
    if e.run_count is not None:
        eq("runs created for the incident", o["run_count"], e.run_count)
    res.facts["step_checks_ok"] = all(c.ok for c in step_checks)
