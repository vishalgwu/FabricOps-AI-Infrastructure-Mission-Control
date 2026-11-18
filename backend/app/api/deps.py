"""FastAPI dependencies: build services from the app's Database."""
from fastapi import Depends, Request

from app.services.services import IncidentService, RunService
from app.storage.db import Database
from app.storage.repositories import IncidentRepository, RunRepository


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_incident_service(db: Database = Depends(get_db)) -> IncidentService:
    return IncidentService(IncidentRepository(db))


def get_run_service(db: Database = Depends(get_db)) -> RunService:
    return RunService(RunRepository(db), IncidentRepository(db))
