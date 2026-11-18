"""Server-side validation of the model's answer. The model is never trusted."""
import re

from app.llm.package import EvidencePackage
from app.llm.schema import ModelInvestigation
from app.schemas.common import RiskClass, Severity
from app.schemas.domain import Hypothesis, InvestigationReport, Observation, ProposedTest

# Wording that presents a guess as established fact (invariant: hypotheses are never facts).
_CERTAINTY = re.compile(
    r"\b(root cause is|root cause was|definitely|certainly caused|proven|it is confirmed|confirmed that|"
    r"has been confirmed|conclusively)\b",
    re.IGNORECASE,
)
# Shell/command syntax is never a valid diagnostic proposal.
_COMMANDISH = re.compile(r"(`|\$\(|&&|\|\||;\s*\w|\bsudo\b|\bsystemctl\b|\brm\s+-|\bkubectl\b|\bssh\b)")


class InvestigationRejected(Exception):
    """The model's answer failed validation. `errors` lists every problem found."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def validate_investigation(raw: ModelInvestigation, pkg: EvidencePackage) -> InvestigationReport:
    errors: list[str] = []
    evidence_ids, chunk_ids = pkg.evidence_ids, pkg.chunk_ids
    hosts, affected = set(pkg.allowed_hosts), set(pkg.incident.affected_hosts)

    def check_evidence(where: str, ids: list[str]) -> None:
        for i in ids:
            if i not in evidence_ids:
                errors.append(f"{where}: unknown evidence ID '{i}'")

    def check_chunks(where: str, ids: list[str]) -> None:
        for i in ids:
            if i not in chunk_ids:
                errors.append(f"{where}: unknown document chunk ID '{i}'")

    for n, o in enumerate(raw.observations):
        if not o.evidence_ids:
            errors.append(f"observations[{n}]: an observation must cite at least one evidence ID")
        check_evidence(f"observations[{n}]", o.evidence_ids)
    for n, h in enumerate(raw.hypotheses):
        if not h.supporting_evidence_ids:
            errors.append(f"hypotheses[{n}]: a hypothesis must cite supporting evidence")
        check_evidence(f"hypotheses[{n}].supporting_evidence_ids", h.supporting_evidence_ids)
        check_evidence(f"hypotheses[{n}].opposing_evidence_ids", h.opposing_evidence_ids)
        check_chunks(f"hypotheses[{n}].citations", h.citations)
        if _CERTAINTY.search(h.statement):
            errors.append(f"hypotheses[{n}]: states a hypothesis as established fact")
    check_chunks("document_citations", raw.document_citations)

    nt = raw.next_test
    if nt is not None:
        if nt.risk_class == RiskClass.WRITE_OR_DEPLOY:
            errors.append("next_test: write_or_deploy actions are not supported proposals")
        if _COMMANDISH.search(nt.description):
            errors.append("next_test: description contains command or shell syntax")
        if not nt.target_scope:
            errors.append("next_test: target_scope must name at least one host")
        for h in nt.target_scope:
            if h not in hosts:
                errors.append(f"next_test: host '{h}' is outside the allowed scope")
            elif h not in affected:
                errors.append(f"next_test: host '{h}' is a comparison peer, not an affected host")

    if raw.abstain:
        if raw.hypotheses:
            errors.append("abstain is true but hypotheses were given")
        if not raw.missing_evidence:
            errors.append("abstain is true but missing_evidence is empty")
        if not raw.abstain_reason.strip():
            errors.append("abstain is true but abstain_reason is empty")
        if nt is not None:
            errors.append("abstain is true but a next_test was proposed")
    else:
        if not raw.observations:
            errors.append("a non-abstaining answer needs at least one observation")
        if not raw.hypotheses:
            errors.append("a non-abstaining answer needs at least one hypothesis (otherwise abstain)")

    if errors:
        raise InvestigationRejected(errors)

    citations = sorted(set(raw.document_citations) | {c for h in raw.hypotheses for c in h.citations})
    limitations = list(raw.limitations)
    if raw.abstain:
        limitations.insert(0, f"Abstained: {raw.abstain_reason.strip()}")
    limitations.append("All data is synthetic. This is a hypothesis for a human to review, not a diagnosis.")
    return InvestigationReport(
        run_id=pkg.run_id,
        severity=Severity.UNKNOWN if raw.abstain else pkg.incident.severity,
        insufficient_evidence=raw.abstain,
        observations=[Observation(text=o.statement, evidence_ids=o.evidence_ids) for o in raw.observations],
        hypotheses=[
            Hypothesis(
                statement=h.statement, confidence=h.confidence,
                supporting_evidence_ids=h.supporting_evidence_ids,
                counterevidence=h.counterevidence
                + [f"opposing evidence: {i}" for i in h.opposing_evidence_ids]
                + ([f"uncertainty: {h.uncertainty}"] if h.uncertainty.strip() else []),
                citations=h.citations,
            )
            for h in raw.hypotheses
        ],
        citations=citations,
        missing_evidence=raw.missing_evidence,
        proposed_next_test=None if nt is None else ProposedTest(
            description=nt.description, target_scope=nt.target_scope, advisory_risk_class=nt.risk_class,
            evidence_ids=sorted({i for o in raw.observations for i in o.evidence_ids})),
        limitations=limitations,
    )
