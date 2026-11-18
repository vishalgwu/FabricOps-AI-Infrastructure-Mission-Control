"""Read-only lookups the UI needs: the available synthetic scenarios, and document chunks (so a
citation shown in a report can be opened and checked)."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_docs, get_fixtures
from app.core.errors import NotFoundError
from app.retrieval.index import DocumentIndex
from app.schemas.common import ScenarioType, Severity
from app.schemas.domain import DocumentChunk, Host
from app.schemas.fixtures import ScenarioFixture

router = APIRouter(prefix="/api")


class ScenarioInfo(BaseModel):
    scenario_type: ScenarioType
    title: str
    description: str
    severity: Severity
    hosts: list[Host]
    suggested_affected_hosts: list[str]
    synthetic: bool = True


@router.get("/scenarios", response_model=list[ScenarioInfo])
def list_scenarios(fixtures: dict[ScenarioType, ScenarioFixture] = Depends(get_fixtures)):
    """The built-in synthetic scenarios, with a suggested incident to pre-fill the intake form."""
    order = list(ScenarioType)
    return [
        ScenarioInfo(
            scenario_type=fx.incident.scenario_type, title=fx.incident.title,
            description=fx.incident.description, severity=fx.incident.severity, hosts=fx.hosts,
            suggested_affected_hosts=fx.incident.affected_hosts)
        for fx in sorted(fixtures.values(), key=lambda f: order.index(f.incident.scenario_type))
    ]


@router.get("/documents/chunks/{chunk_id}", response_model=DocumentChunk)
def get_document_chunk(chunk_id: str, docs: DocumentIndex = Depends(get_docs)):
    """Resolve a citation ID to the exact passage, source and version it points at.
    Superseded versions resolve too (flagged by `status`), so an old citation stays checkable."""
    chunk = docs.get_chunk(chunk_id)
    if chunk is None:
        raise NotFoundError(f"document chunk '{chunk_id}' not found")
    return chunk

