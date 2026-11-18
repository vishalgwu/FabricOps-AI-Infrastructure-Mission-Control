"""The strict structure the model must return, plus the JSON schema sent to the provider.

The provider's JSON schema is only a request to the model. The server never trusts it:
every response is re-parsed against `ModelInvestigation` and then checked by the validator.
"""
from typing import Any

from pydantic import Field

from app.schemas.common import Confidence, RiskClass, StrictModel


class ModelObservation(StrictModel):
    statement: str = Field(min_length=1)
    evidence_ids: list[str]


class ModelHypothesis(StrictModel):
    statement: str = Field(min_length=1)
    supporting_evidence_ids: list[str]
    opposing_evidence_ids: list[str]
    counterevidence: list[str]       # short statements of what argues against it
    confidence: Confidence
    uncertainty: str                 # what remains unknown
    citations: list[str]             # document chunk IDs


class ModelNextTest(StrictModel):
    description: str = Field(min_length=1)
    target_scope: list[str]
    risk_class: RiskClass


class ModelInvestigation(StrictModel):
    observations: list[ModelObservation]
    hypotheses: list[ModelHypothesis]
    missing_evidence: list[str]
    next_test: ModelNextTest | None
    abstain: bool
    abstain_reason: str
    limitations: list[str]
    document_citations: list[str]


_STR = {"type": "string"}
_STR_LIST = {"type": "array", "items": _STR}


def response_json_schema() -> dict[str, Any]:
    """Hand-written schema (plain features only). `write_or_deploy` is deliberately not offered."""

    def obj(props: dict[str, Any]) -> dict[str, Any]:
        return {"type": "object", "properties": props, "required": list(props),
                "additionalProperties": False}

    return obj({
        "observations": {"type": "array", "items": obj({"statement": _STR, "evidence_ids": _STR_LIST})},
        "hypotheses": {"type": "array", "items": obj({
            "statement": _STR,
            "supporting_evidence_ids": _STR_LIST,
            "opposing_evidence_ids": _STR_LIST,
            "counterevidence": _STR_LIST,
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "uncertainty": _STR,
            "citations": _STR_LIST,
        })},
        "missing_evidence": _STR_LIST,
        "next_test": {"anyOf": [
            obj({"description": _STR, "target_scope": _STR_LIST,
                 "risk_class": {"type": "string", "enum": ["read_only_diagnostic", "controlled_test"]}}),
            {"type": "null"},
        ]},
        "abstain": {"type": "boolean"},
        "abstain_reason": _STR,
        "limitations": _STR_LIST,
        "document_citations": _STR_LIST,
    })
