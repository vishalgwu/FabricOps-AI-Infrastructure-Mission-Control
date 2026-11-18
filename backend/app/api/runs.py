from fastapi import APIRouter, Depends

from app.api.deps import get_run_service
from app.schemas.domain import Run
from app.services.services import RunService

router = APIRouter(prefix="/api")


@router.get("/runs/{run_id}", response_model=Run)
def get_run(run_id: str, svc: RunService = Depends(get_run_service)):
    return svc.get(run_id)
