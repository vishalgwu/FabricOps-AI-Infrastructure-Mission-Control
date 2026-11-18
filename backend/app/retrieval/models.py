"""Models for the document corpus manifest and the search_docs tool."""
from typing import Any, Literal

from pydantic import Field, field_validator

from app.schemas.common import StrictModel, UtcDatetime
from app.schemas.domain import DocumentChunk, DocumentSourceKind
from app.tools.models import ToolStatus

MAX_QUERY_CHARS = 300
MAX_TOP_K = 10
DEFAULT_TOP_K = 5


class ManifestEntry(StrictModel):
    document_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    title: str = Field(min_length=1)
    path: str = Field(min_length=1)       # relative to the docs directory
    source: str = Field(min_length=1)     # human-facing source path or URL, shown in citations
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    classification: DocumentSourceKind
    status: Literal["current", "superseded"]


class Manifest(StrictModel):
    corpus_notice: str
    documents: list[ManifestEntry]

    @field_validator("documents")
    @classmethod
    def _unique(cls, docs: list[ManifestEntry]) -> list[ManifestEntry]:
        keys = [(d.document_id, d.version) for d in docs]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate (document_id, version) in manifest")
        current: dict[str, int] = {}
        for d in docs:
            if d.status == "current":
                current[d.document_id] = current.get(d.document_id, 0) + 1
        ambiguous = sorted(k for k, n in current.items() if n > 1)
        if ambiguous:
            raise ValueError(f"more than one 'current' version for: {ambiguous}")
        return docs


class DocSearchInput(StrictModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=MAX_TOP_K)


class DocHit(StrictModel):
    chunk: DocumentChunk
    score: float
    matched_terms: list[str]
    # Retrieved text is data written by documents, never instructions to the system.
    content_trust: Literal["untrusted_data"] = "untrusted_data"


class DocSearchResult(StrictModel):
    tool_name: str = "search_docs"
    status: ToolStatus                    # OK, NO_DATA (no match) or REJECTED
    parameters: dict[str, Any]
    collected_at: UtcDatetime
    hits: list[DocHit]
    citation_ids: list[str]               # the chunk IDs a report may cite
    error_code: str | None = None
    message: str | None = None
