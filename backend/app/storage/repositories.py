"""Repositories: the only code that writes SQL for incidents, runs and run events."""
import json
import sqlite3
from datetime import datetime, timezone

from app.schemas.common import RunStatus
from app.schemas.domain import EvidenceRecord, Incident, InvestigationReport, Run
from app.storage.db import Database


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _incident(row: sqlite3.Row) -> Incident:
    return Incident(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        scenario_type=row["scenario_type"],
        severity=row["severity"],
        affected_hosts=json.loads(row["affected_hosts"]),
        created_at=row["created_at"],
        synthetic=bool(row["synthetic"]),
    )


def _run(row: sqlite3.Row) -> Run:
    return Run(**{k: row[k] for k in row.keys()})


class IncidentRepository:
    def __init__(self, db: Database):
        self._db = db

    def add(self, incident: Incident) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO incidents (id, title, description, scenario_type, severity,"
                " affected_hosts, created_at, synthetic) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    incident.id,
                    incident.title,
                    incident.description,
                    incident.scenario_type.value,
                    incident.severity.value,
                    json.dumps(incident.affected_hosts),
                    _iso(incident.created_at),
                    int(incident.synthetic),
                ),
            )

    def get(self, incident_id: str) -> Incident | None:
        with self._db.connect() as conn:
            row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        return _incident(row) if row else None

    def list(self, limit: int, offset: int) -> tuple[list[Incident], int]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM incidents ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
        return [_incident(r) for r in rows], total


class RunRepository:
    def __init__(self, db: Database):
        self._db = db

    def add(self, run: Run) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO runs (id, incident_id, status, started_at, finished_at, model_id,"
                " prompt_version, error_code) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.id,
                    run.incident_id,
                    run.status.value,
                    _iso(run.started_at),
                    _iso(run.finished_at) if run.finished_at else None,
                    run.model_id,
                    run.prompt_version,
                    run.error_code,
                ),
            )
            self._event(conn, run.id, "run_created", None, run.status.value, None, run.started_at)

    def get(self, run_id: str) -> Run | None:
        with self._db.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _run(row) if row else None

    def list_for_incident(self, incident_id: str) -> list[Run]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE incident_id = ? ORDER BY started_at DESC, id", (incident_id,)
            ).fetchall()
        return [_run(r) for r in rows]

    def transition(
        self,
        run_id: str,
        expected: RunStatus,
        target: RunStatus,
        now: datetime,
        finished: bool,
        error_code: str | None = None,
    ) -> bool:
        """Compare-and-swap: only updates if the stored status is still `expected`.

        Returns False if another writer changed the status first.
        """
        with self._db.connect() as conn:
            cur = conn.execute(
                "UPDATE runs SET status = ?, finished_at = ?, error_code = COALESCE(?, error_code)"
                " WHERE id = ? AND status = ?",
                (target.value, _iso(now) if finished else None, error_code, run_id, expected.value),
            )
            if cur.rowcount != 1:
                return False
            self._event(conn, run_id, "status_changed", expected.value, target.value, error_code, now)
            return True

    def record_model_metadata(self, run_id: str, model_id: str | None, prompt_version: str | None) -> None:
        """Remember which model and prompt version produced this run's analysis."""
        with self._db.connect() as conn:
            conn.execute("UPDATE runs SET model_id = ?, prompt_version = ? WHERE id = ?",
                         (model_id, prompt_version, run_id))

    def events(self, run_id: str) -> list[dict]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT seq, event_type, from_status, to_status, detail, created_at"
                " FROM run_events WHERE run_id = ? ORDER BY seq",
                (run_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _event(conn, run_id, event_type, from_status, to_status, detail, now) -> None:
        conn.execute(
            "INSERT INTO run_events (run_id, event_type, from_status, to_status, detail, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, event_type, from_status, to_status, detail, _iso(now)),
        )


class EvidenceRepository:
    """Stores evidence collected by tools. IDs are deterministic, so re-saving is a no-op."""

    def __init__(self, db: Database):
        self._db = db

    def add_many(self, records: list[EvidenceRecord]) -> None:
        with self._db.connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO evidence (id, run_id, source_type, host_id, tool_name,"
                " observed_at, ingested_at, payload, synthetic) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (r.id, r.run_id, r.source_type, r.host_id, r.tool_name, _iso(r.observed_at),
                     _iso(r.ingested_at), json.dumps(r.payload), int(r.synthetic))
                    for r in records
                ],
            )

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        with self._db.connect() as conn:
            row = conn.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
        return _evidence(row) if row else None

    def list_for_run(self, run_id: str) -> list[EvidenceRecord]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence WHERE run_id = ? ORDER BY observed_at, id", (run_id,)
            ).fetchall()
        return [_evidence(r) for r in rows]


def _evidence(row: sqlite3.Row) -> EvidenceRecord:
    data = {k: row[k] for k in row.keys()}
    data["payload"] = json.loads(data["payload"])
    data["synthetic"] = bool(data["synthetic"])
    return EvidenceRecord(**data)


class ReportRepository:
    """Stores the validated investigation report for a run (one per run)."""

    def __init__(self, db: Database):
        self._db = db

    def save(self, report: InvestigationReport) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO investigation_reports (run_id, report, created_at) VALUES (?, ?, ?)",
                (report.run_id, report.model_dump_json(), _iso(datetime.now(timezone.utc))),
            )

    def get(self, run_id: str) -> InvestigationReport | None:
        with self._db.connect() as conn:
            row = conn.execute("SELECT report FROM investigation_reports WHERE run_id = ?", (run_id,)).fetchone()
        return InvestigationReport.model_validate_json(row["report"]) if row else None
