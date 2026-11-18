"""The evidence package: the ONLY information the model is given about an incident.

It is built from this run's tool results and retrieved document chunks. It never contains the
evaluation answer keys, secrets, or anything the tools did not return.
"""
from dataclasses import dataclass, field
from datetime import datetime

from app.retrieval.models import DocSearchResult
from app.schemas.domain import EvidenceRecord, Incident
from app.tools.models import ToolResult, ToolStatus


@dataclass
class EvidencePackage:
    run_id: str
    incident: Incident
    allowed_hosts: list[str]
    as_of: datetime
    evidence: list[EvidenceRecord]
    tool_calls: list[dict]            # one summary per tool call, including failures and gaps
    documents: list[dict]             # retrieved chunks (untrusted data)
    abstention_reasons: list[str] = field(default_factory=list)  # deterministic, computed by server

    @property
    def evidence_ids(self) -> set[str]:
        return {e.id for e in self.evidence}

    @property
    def chunk_ids(self) -> set[str]:
        return {d["id"] for d in self.documents}


def build_package(
    run_id: str,
    incident: Incident,
    allowed_hosts: list[str],
    tool_results: list[ToolResult],
    doc_result: DocSearchResult | None,
    as_of: datetime,
) -> EvidencePackage:
    evidence: dict[str, EvidenceRecord] = {}
    calls: list[dict] = []
    for r in tool_results:
        for rec in r.records:
            if rec.run_id == run_id:  # evidence from any other run is never included
                evidence[rec.id] = rec
        calls.append({
            "tool": r.tool_name,
            "host_id": r.parameters.get("host_id"),
            "status": r.status.value,
            "message": r.message,
            "newest_observation_age_seconds": r.freshness.age_seconds if r.freshness else None,
            "evidence_ids": [e for e in r.evidence_ids if e in evidence],
        })
    documents = []
    if doc_result is not None:
        for h in doc_result.hits:
            c = h.chunk
            documents.append({"id": c.id, "document_id": c.document_id, "version": c.version,
                              "section": c.section, "source": c.source, "text": c.text})
    pkg = EvidencePackage(
        run_id=run_id, incident=incident, allowed_hosts=sorted(allowed_hosts), as_of=as_of,
        evidence=sorted(evidence.values(), key=lambda e: (e.host_id, e.source_type, e.id)),
        tool_calls=calls, documents=documents,
    )
    pkg.abstention_reasons = abstention_reasons(pkg, tool_results)
    return pkg


def abstention_reasons(pkg: EvidencePackage, tool_results: list[ToolResult]) -> list[str]:
    """Server-side gate: if the evidence is not good enough, the model is never asked to guess.

    Each affected host needs fresh metrics (`ok`). If the incident has other in-scope hosts,
    at least one of them needs fresh metrics too, so there is something to compare against.
    """
    metrics = {r.parameters.get("host_id"): r for r in tool_results if r.tool_name == "read_metrics"}
    reasons: list[str] = []

    def describe(host: str) -> str:
        r = metrics.get(host)
        if r is None:
            return f"no metrics were collected for host '{host}'"
        detail = f": {r.message}" if r.message else ""
        return f"metrics for host '{host}' are {r.status.value}{detail}"

    for host in pkg.incident.affected_hosts:
        r = metrics.get(host)
        if r is None or r.status != ToolStatus.OK:
            reasons.append(describe(host))
    peers = [h for h in pkg.allowed_hosts if h not in pkg.incident.affected_hosts]
    if peers and not any(metrics.get(h) is not None and metrics[h].status == ToolStatus.OK for h in peers):
        reasons.append("no peer host has fresh metrics, so there is no baseline to compare against")
    return reasons
