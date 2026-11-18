"""Deterministic proposal policy. Plain Python rules: no model call, no randomness.

The model may SUGGEST a next step and label its risk. The label is advisory and can only ever
raise the class chosen here, never lower it. Nothing in this module (or anywhere in the MVP)
executes a proposal: there is no execution adapter.
"""
import hashlib
import json
import re
from dataclasses import dataclass

from app.schemas.common import RiskClass
from app.schemas.domain import EvidenceRecord

_SEVERITY = {RiskClass.READ_ONLY_DIAGNOSTIC: 0, RiskClass.CONTROLLED_TEST: 1, RiskClass.WRITE_OR_DEPLOY: 2}

# Anything that changes, restarts, deploys or removes something. Matched on whole words, so
# over-classification (for example "do not restart") is the safe direction.
_WRITE = re.compile(
    r"\b(restart\w*|reboot\w*|redeploy\w*|deploy\w*|roll[- ]?back|rollout|scal(?:e|es|ed|ing)|drain\w*|"
    r"cordon\w*|delet\w*|remov\w*|kill\w*|terminat\w*|shut[- ]?down|power[- ]?cycl\w*|upgrad\w*|"
    r"downgrad\w*|patch\w*|flash\w*|reset\w*|wip\w*|format\w*|failover|migrat\w*|appl(?:y|ies|ied|ying)|"
    r"install\w*|uninstall\w*|enabl(?:e|es|ed|ing)|disabl(?:e|es|ed|ing)|overwrit\w*|rewrit\w*|"
    r"updat(?:e|es|ed|ing)|commit\w*|rotat\w*|purg\w*|clear\w*|evict)\b",
    re.IGNORECASE,
)
# Command or shell syntax is write-class no matter what words surround it.
_COMMANDISH = re.compile(r"(`|\$\(|&&|\|\||;\s*\w|\bsudo\b|\bsystemctl\b|\bkubectl\b|\bssh\b|\brm\s+-)")
# A small, reversible experiment on one scoped host.
_CONTROLLED = re.compile(
    r"\b(reduc\w*|increas\w*|halv\w*|doubl\w*|lower\w*|rais\w*|adjust\w*|modif\w*|chang\w*|tun(?:e|es|ed|ing)|"
    r"throttl\w*|swap\w*|replac\w*|reseat\w*|shift\w*|reroute\w*|set|controlled\s+test|experiment\w*|canary|"
    r"batch_size|max_sequence_length|traffic)\b",
    re.IGNORECASE,
)
# Read-only verbs. A proposal is read-only only if it uses one of these and nothing above.
_READ = re.compile(
    r"\b(read|check|compar\w*|review\w*|inspect\w*|quer(?:y|ies|ied)|list\w*|collect\w*|gather\w*|verif\w*|"
    r"monitor\w*|observ\w*|examin\w*|analy[sz]\w*|look|confirm\w*|capture\w*|trace\w*|audit\w*)\b",
    re.IGNORECASE,
)


class PolicyViolation(Exception):
    """The proposal breaks a hard rule (for example it targets a host outside the incident)."""


@dataclass(frozen=True)
class PolicyDecision:
    risk_class: RiskClass
    requires_approval: bool
    reasons: tuple[str, ...]


def classify(description: str, advisory: RiskClass | None = None) -> PolicyDecision:
    """Choose the risk class from the proposal's wording. `advisory` is the model's own claim."""
    reasons: list[str] = []
    write = _WRITE.search(description) or _COMMANDISH.search(description)
    if write:
        server = RiskClass.WRITE_OR_DEPLOY
        reasons.append(f"wording indicates a change, restart, deployment or command: '{write.group(0)}'")
    elif m := _CONTROLLED.search(description):
        server = RiskClass.CONTROLLED_TEST
        reasons.append(f"wording indicates an experiment that could affect the host: '{m.group(0)}'")
    elif _READ.search(description):
        server = RiskClass.READ_ONLY_DIAGNOSTIC
        reasons.append("wording only reads or compares existing data")
    else:
        server = RiskClass.CONTROLLED_TEST  # unrecognised wording is never assumed safe
        reasons.append("wording was not recognised as read-only, so it is treated as a controlled test")

    final = server
    if advisory is not None and _SEVERITY[advisory] > _SEVERITY[server]:
        final = advisory  # the model may be more cautious than the server, never less
        reasons.append(f"the model labelled it {advisory.value}, which is stricter, so that label is kept")
    elif advisory is not None and _SEVERITY[advisory] < _SEVERITY[server]:
        reasons.append(f"the model labelled it {advisory.value}; the server overrode that label")
    return PolicyDecision(final, final != RiskClass.READ_ONLY_DIAGNOSTIC, tuple(reasons))


def check_scope(target_scope: list[str], affected_hosts: list[str]) -> None:
    """Defence in depth (the investigator already checks this): only affected hosts may be targeted."""
    bad = sorted(set(target_scope) - set(affected_hosts))
    if not target_scope or bad:
        raise PolicyViolation(f"target scope {target_scope} must be non-empty and within the affected hosts "
                              f"{affected_hosts}" + (f" (not allowed: {bad})" if bad else ""))


def evidence_digest(rec: EvidenceRecord) -> str:
    body = {"id": rec.id, "observed_at": rec.observed_at.isoformat(), "payload": rec.payload}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def compute_proposal_hash(
    *, run_id: str, version: int, description: str, parameters: dict, target_scope: list[str],
    risk_class: RiskClass, evidence_digests: dict[str, str],
) -> str:
    """A fingerprint of everything an approval is meant to cover. If any part changes (the text,
    the parameters, the scope, the risk class, or the content of the evidence it rests on), the
    hash changes and an earlier approval no longer applies."""
    canonical = {
        "run_id": run_id, "version": version, "description": description,
        "parameters": parameters, "target_scope": sorted(target_scope), "risk_class": risk_class.value,
        "evidence": sorted(evidence_digests.items()),
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
