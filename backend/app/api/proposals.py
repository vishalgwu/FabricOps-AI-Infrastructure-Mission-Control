from typing import Literal

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_proposal_service, get_run_service
from app.core.errors import NotFoundError
from app.schemas.domain import ApprovalDecision, DecisionKind, Proposal
from app.services.proposals import ProposalService
from app.services.services import RunService

router = APIRouter(prefix="/api")


class ProposalView(BaseModel):
    proposal: Proposal
    decision: ApprovalDecision | None
    # Always false: the MVP has no execution adapter. Approval is only a recorded human decision.
    execution_enabled: Literal[False] = False


class DecisionRequest(BaseModel):
    """The reviewer must send back the hash of the exact proposal they were shown."""

    model_config = ConfigDict(extra="forbid")

    decision: DecisionKind
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=1000, pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$")


def _view(svc: ProposalService, p: Proposal) -> ProposalView:
    return ProposalView(proposal=p, decision=svc.decision_for(p))


@router.get("/proposals/{proposal_id}", response_model=ProposalView)
def get_proposal(proposal_id: str, svc: ProposalService = Depends(get_proposal_service)):
    return _view(svc, svc.get(proposal_id))


@router.get("/runs/{run_id}/proposal", response_model=ProposalView)
def get_run_proposal(run_id: str, runs: RunService = Depends(get_run_service),
                     svc: ProposalService = Depends(get_proposal_service)):
    runs.get(run_id)
    found = svc.latest_for_run(run_id)
    if not found:
        raise NotFoundError(f"run '{run_id}' has no proposal")
    return _view(svc, found[-1])


@router.post("/proposals/{proposal_id}/decision", response_model=ProposalView)
def decide(
    proposal_id: str,
    body: DecisionRequest,
    response: Response,
    x_demo_reviewer: str | None = Header(default=None, max_length=100),
    svc: ProposalService = Depends(get_proposal_service),
):
    """Approve or reject a proposal. DEMO identity: the `X-Demo-Reviewer` header must name an authorised
    demo reviewer. This is not production authentication. Nothing is executed either way.

    Idempotent: repeating the same decision returns it again (200); the first one is 201.
    """
    proposal, decision, created = svc.decide(proposal_id, x_demo_reviewer, body.decision, body.proposal_hash,
                                             body.reason)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return ProposalView(proposal=proposal, decision=decision)
