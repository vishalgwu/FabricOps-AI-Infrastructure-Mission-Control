"""The versioned evaluation dataset (backend/data/evals/dataset.v1.json) and its schema.

Expected outcomes live only here, in data/evals. They are read by the evaluation code and by tests,
never by the application and never placed in a model prompt.
"""
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.common import ScenarioType, StrictModel

DATASET_PATH = Path(__file__).resolve().parents[1] / "data" / "evals" / "dataset.v1.json"


class Action(StrictModel):
    """A step a human (or the clock) takes after the investigation, to exercise the approval gate."""

    do: Literal["approve", "revise", "decide", "decide_as", "decide_with_original_hash", "advance_clock", "start_again"]
    decision: Literal["approved", "rejected"] | None = None
    actor: str | None = None
    description: str | None = None
    hours: float | None = None
    expect_status: int | None = None
    expect_code: str | None = None
    expect_same_run: bool | None = None


class RetrieveExpect(StrictModel):
    host: str
    metric: str


class SourcesExpect(StrictModel):
    host: str
    metric: str
    sources: list[str]


class ToolStatusExpect(StrictModel):
    tool: str
    host: str
    status: str


class ProposalExpect(StrictModel):
    risk_class: str
    approval_status: str
    scope: list[str]


class Expected(StrictModel):
    run_status: str | None = None
    error_code: str | None = None
    model_calls: int | None = None
    report: Literal["present", "absent"] | None = None
    insufficient_evidence: bool | None = None
    missing_evidence_contains: list[str] = []
    evidence: Literal["none", "some"] | None = None
    no_metric_evidence: bool = False
    tool_statuses: list[ToolStatusExpect] = []
    proposal: Literal["none"] | ProposalExpect | None = None
    citations: Literal["none", "some"] | None = None
    citations_valid: bool | None = None
    must_retrieve: list[RetrieveExpect] = []
    both_sources_present: SourcesExpect | None = None
    prompt_contains: list[str] = []
    injection_only_in_evidence: str | None = None
    retrieved_chunks: Literal["none", "irrelevant_retrieved"] | None = None
    doc_search_status: str | None = None
    failed_stage: str | None = None
    proposal_versions: dict[str, str] = {}
    latest_proposal_has_decision: bool | None = None
    run_count: int | None = None
    # Flags that say which metric a case counts toward.
    fabricated_ids: bool = False
    scope_violation_blocked: bool = False
    risky_paused: bool = False
    risky_blocked: bool = False
    schema_invalid: bool = False
    # A weakness that the system does NOT catch today. The case asserts today's behaviour, and the
    # report lists it, so it cannot be forgotten and a future fix shows up as a change.
    known_gap: str | None = None


class EvalCase(StrictModel):
    id: str = Field(pattern=r"^E\d{2}$")
    title: str
    covers: str
    scenario: ScenarioType
    affected_hosts: list[str]
    behavior: str
    docs: Literal["default", "off_topic", "empty"] = "default"
    fixture_edit: dict[str, str] | None = None
    adapter_fault: dict[str, str] | None = None
    actions: list[Action] = []
    expected: Expected


class Dataset(StrictModel):
    dataset_version: str
    synthetic: Literal[True]
    note: str
    cases: list[EvalCase]

    @model_validator(mode="after")
    def _unique_ids(self) -> "Dataset":
        ids = [c.id for c in self.cases]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate case IDs")
        return self


def load_dataset(path: Path = DATASET_PATH) -> Dataset:
    return Dataset.model_validate(json.loads(path.read_text(encoding="utf-8")))
