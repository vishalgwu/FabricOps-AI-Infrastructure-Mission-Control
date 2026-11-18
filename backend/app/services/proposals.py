"""Proposals and approval decisions. Authorization is decided here, in backend code.

Nothing in this module executes a proposal. An approval is only a recorded human decision.
"""
import json
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from app.core.errors import ConflictError, ForbiddenError, NotFoundError, UnauthenticatedError
from app.policy.policy import check_scope, classify, compute_proposal_hash, evidence_digest
from app.schemas.common import ApprovalStatus, RiskClass, RunStatus
from app.schemas.domain import ApprovalDecision, DecisionKind, InvestigationReport, Proposal
from app.storage.repositories import (
    EvidenceRepository,
    ProposalRepository,
    RunRepository,
)

log = logging.getLogger("fabricops.proposals")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ProposalService:
    def __init__(
        self,
        proposals: ProposalRepository,
        evidence: EvidenceRepository,
        runs: RunRepository,
        reviewers: frozenset[str],
        approval_ttl: timedelta = timedelta(hours=24),
        clock: Callable[[], datetime] = _now,
    ):
        self._proposals, self._evidence, self._runs = proposals, evidence, runs
        self._reviewers, self._ttl, self._clock = reviewers, approval_ttl, clock

    # ---- creating proposals (called by the workflow, never by the model) ----

    def _build(self, *, proposal_id: str, version: int, run_id: str, description: str, parameters: dict,
               target_scope: list[str], advisory: RiskClass | None, evidence_ids: list[str],
               affected_hosts: list[str]) -> Proposal:
        check_scope(target_scope, affected_hosts)
        decision = classify(description, advisory)
        digests = {}
        for eid in sorted(set(evidence_ids)):
            rec = self._evidence.get(eid)
            if rec is None or rec.run_id != run_id:
                raise ConflictError("unknown_evidence", f"evidence '{eid}' does not belong to run '{run_id}'")
            digests[eid] = evidence_digest(rec)
        now = self._clock()
        return Proposal(
            id=proposal_id, run_id=run_id, version=version, description=description, parameters=parameters,
            target_scope=sorted(target_scope), risk_class=decision.risk_class,
            approval_status=ApprovalStatus.PENDING if decision.requires_approval else ApprovalStatus.NOT_REQUIRED,
            proposal_hash=compute_proposal_hash(
                run_id=run_id, version=version, description=description, parameters=parameters,
                target_scope=target_scope, risk_class=decision.risk_class, evidence_digests=digests),
            expires_at=now + self._ttl if decision.requires_approval else None,
            evidence_ids=sorted(digests), policy_reasons=list(decision.reasons),
        )

    def create_for_run(self, report: InvestigationReport, affected_hosts: list[str]) -> Proposal | None:
        """Turn the report's suggested next test into a stored proposal, classified by policy."""
        test = report.proposed_next_test
        if test is None:
            return None
        proposal = self._build(
            proposal_id=f"prop_{uuid.uuid4().hex[:12]}", version=1, run_id=report.run_id,
            description=test.description, parameters=dict(test.parameters), target_scope=test.target_scope,
            advisory=test.advisory_risk_class, evidence_ids=test.evidence_ids, affected_hosts=affected_hosts)
        self._proposals.add(proposal, self._clock())
        self._runs.add_event(report.run_id, "proposal_created", json.dumps({
            "proposal_id": proposal.id, "version": proposal.version, "risk_class": proposal.risk_class.value,
            "approval_status": proposal.approval_status.value, "proposal_hash": proposal.proposal_hash}))
        return proposal

    def revise(self, proposal_id: str, affected_hosts: list[str], *, description: str | None = None,
               parameters: dict | None = None, target_scope: list[str] | None = None,
               evidence_ids: list[str] | None = None) -> Proposal:
        """Create version N+1 with a new hash. The old version becomes EXPIRED, so an approval of it
        cannot be reused for the changed proposal."""
        current = self.get(proposal_id)
        new = self._build(
            proposal_id=proposal_id, version=current.version + 1, run_id=current.run_id,
            description=current.description if description is None else description,
            parameters=current.parameters if parameters is None else parameters,
            target_scope=current.target_scope if target_scope is None else target_scope,
            advisory=None, evidence_ids=current.evidence_ids if evidence_ids is None else evidence_ids,
            affected_hosts=affected_hosts)
        if not self._proposals.add_revision(current, new, self._clock()):
            raise ConflictError("proposal_changed", "the proposal was revised by someone else; reload it")
        self._runs.add_event(current.run_id, "proposal_revised", json.dumps({
            "proposal_id": proposal_id, "version": new.version, "proposal_hash": new.proposal_hash,
            "approval_status": new.approval_status.value}))
        return new

    # ---- reading ----

    def get(self, proposal_id: str) -> Proposal:
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise NotFoundError(f"proposal '{proposal_id}' not found")
        return self._expire_if_due(proposal)

    def latest_for_run(self, run_id: str) -> list[Proposal]:
        return [self._expire_if_due(p) for p in self._proposals.latest_for_run(run_id)]

    def decision_for(self, proposal: Proposal) -> ApprovalDecision | None:
        return self._proposals.decision_for(proposal.id, proposal.proposal_hash)

    def _expire_if_due(self, p: Proposal) -> Proposal:
        if p.approval_status == ApprovalStatus.PENDING and p.expires_at and self._clock() >= p.expires_at:
            if self._proposals.set_status(p.id, p.version, ApprovalStatus.PENDING, ApprovalStatus.EXPIRED):
                self._runs.add_event(p.run_id, "proposal_expired", json.dumps(
                    {"proposal_id": p.id, "version": p.version}))
                self._settle_run(p.run_id, RunStatus.CANCELLED, "approval_expired")
            return self._proposals.get(p.id, p.version) or p
        return p

    # ---- deciding ----

    def authorize(self, actor: str | None) -> str:
        if not actor:
            raise UnauthenticatedError("a reviewer identity is required (header X-Demo-Reviewer)")
        if actor not in self._reviewers:
            raise ForbiddenError(f"'{actor}' is not an authorised reviewer")
        return actor

    def decide(self, proposal_id: str, actor: str | None, decision: DecisionKind, proposal_hash: str,
               reason: str) -> tuple[Proposal, ApprovalDecision, bool]:
        """Record an approve/reject decision. Returns (proposal, decision, created).

        Idempotent: repeating the same decision returns the stored one. The decision is bound to
        the exact proposal hash and version the reviewer was shown.
        """
        actor = self.authorize(actor)
        proposal = self.get(proposal_id)  # also applies expiry
        if proposal.proposal_hash != proposal_hash:
            raise ConflictError("proposal_changed",
                                "the proposal has changed since it was shown; review the current version")
        existing = self._proposals.decision_for(proposal.id, proposal.proposal_hash)
        if existing is not None:
            if existing.decision != decision:
                raise ConflictError("already_decided", f"this proposal was already {existing.decision.value}")
            self._settle_run(proposal.run_id, RunStatus.COMPLETE, None)  # heal a crash between the two writes
            return proposal, existing, False
        if proposal.approval_status == ApprovalStatus.NOT_REQUIRED:
            raise ConflictError("approval_not_required", "this proposal is read-only and needs no approval")
        if proposal.approval_status == ApprovalStatus.EXPIRED:
            raise ConflictError("proposal_expired", "this proposal has expired; no decision can be recorded")
        new_status = ApprovalStatus.APPROVED if decision == DecisionKind.APPROVED else ApprovalStatus.REJECTED
        record = ApprovalDecision(id=f"dec_{uuid.uuid4().hex[:12]}", proposal_id=proposal.id,
                                  proposal_hash=proposal.proposal_hash, actor=actor, decision=decision,
                                  reason=reason, created_at=self._clock())
        if not self._proposals.record_decision(record, proposal.version, new_status):
            # Lost a race: someone decided first. Report their decision if it matches, else conflict.
            existing = self._proposals.decision_for(proposal.id, proposal.proposal_hash)
            if existing is not None and existing.decision == decision:
                return self.get(proposal_id), existing, False
            raise ConflictError("already_decided", "this proposal was decided or changed at the same time")
        self._runs.add_event(proposal.run_id, "approval_decision", json.dumps({
            "proposal_id": proposal.id, "version": proposal.version, "proposal_hash": proposal.proposal_hash,
            "decision": decision.value, "actor": actor, "reason": reason}))
        # Approving or rejecting finishes the human step. Nothing is executed either way.
        self._settle_run(proposal.run_id, RunStatus.COMPLETE, None)
        return self.get(proposal_id), record, True

    def _settle_run(self, run_id: str, target: RunStatus, error_code: str | None) -> None:
        run = self._runs.get(run_id)
        if run is not None and run.status == RunStatus.WAITING_APPROVAL:
            self._runs.transition(run_id, RunStatus.WAITING_APPROVAL, target, self._clock(), True, error_code)
