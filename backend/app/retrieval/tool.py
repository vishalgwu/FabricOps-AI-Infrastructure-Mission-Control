"""search_docs: a bounded, read-only internal tool over the document index.

It takes only a query string and a result count. It returns text as untrusted data and has no
way to change tools, permissions, hosts or system instructions.
"""
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from app.retrieval.index import DocumentIndex
from app.retrieval.models import DocHit, DocSearchInput, DocSearchResult
from app.tools.models import ToolStatus

TOOL_NAME = "search_docs"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DocSearchTool:
    def __init__(self, index: DocumentIndex, clock: Callable[[], datetime] = _now):
        self._index = index
        self._clock = clock

    def search_docs(self, query: str, top_k: int = 5) -> DocSearchResult:
        return self.call({"query": query, "top_k": top_k})

    def call(self, args: dict[str, Any]) -> DocSearchResult:
        now = self._clock()
        try:
            inp = DocSearchInput.model_validate(args)
        except ValidationError as exc:
            msg = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
            return DocSearchResult(status=ToolStatus.REJECTED, parameters=_safe(args), collected_at=now,
                                   hits=[], citation_ids=[], error_code="invalid_arguments",
                                   message=f"invalid arguments: {msg}")
        # Only current document versions are searchable through the tool.
        found = self._index.search(inp.query, inp.top_k)
        params = inp.model_dump()
        if not found:
            return DocSearchResult(status=ToolStatus.NO_DATA, parameters=params, collected_at=now, hits=[],
                                   citation_ids=[], error_code="no_match",
                                   message="no relevant documentation found; do not cite any document")
        hits = [DocHit(chunk=c, score=s, matched_terms=m) for c, s, m in found]
        return DocSearchResult(status=ToolStatus.OK, parameters=params, collected_at=now, hits=hits,
                               citation_ids=[h.chunk.id for h in hits])


def _safe(args: dict[str, Any]) -> dict[str, Any]:
    return {str(k): (v if isinstance(v, (int, float, bool)) or v is None else str(v)[:200])
            for k, v in list(args.items())[:10]}
