"""Repositories: the only code that writes SQL for incidents, runs and run events."""
import json
import sqlite3
from datetime import datetime, timezone

from app.schemas.common import ApprovalStatus, RunStatus
from app.schemas.domain import (
    ApprovalDecision,
    EvidenceRecord,
    Incident,
    InvestigationReport,
    Proposal,
    Run,
)
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


_RUN_FIELDS = ("id", "incident_id", "status", "started_at", "finished_at", "model_id",
               "prompt_version", "error_code")
ACTIVE_STATUSES = (RunStatus.CREATED.value, RunStatus.RUNNING.value, RunStatus.WAITING_APPROVAL.value)


def _run(row: sqlite3.Row) -> Run:
    return Run(**{k: row[k] for k in _RUN_FIELDS})


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
            self._insert(conn, run, None)

    def _insert(self, conn: sqlite3.Connection, run: Run, key: str | None) -> None:
        conn.execute(
            "INSERT INTO runs (id, incident_id, status, started_at, finished_at, model_id,"
            " prompt_version, error_code, idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run.id, run.incident_id, run.status.value, _iso(run.started_at),
             _iso(run.finished_at) if run.finished_at else None, run.model_id, run.prompt_version,
             run.error_code, key),
        )
        self._event(conn, run.id, "run_created", None, run.status.value, None, run.started_at)

    def create_or_get(self, run: Run, key: str | None) -> tuple[Run, bool]:
        """Atomically start a run, or return the existing one. Returns (run, created).

        Order: same idempotency key -> that run; else an in-flight run for the incident -> that
        run; else insert. BEGIN IMMEDIATE takes the write lock first, so two concurrent starts
        cannot both insert.
        """
        with self._db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if key is not None:
                row = conn.execute("SELECT * FROM runs WHERE incident_id = ? AND idempotency_key = ?",
                                   (run.incident_id, key)).fetchone()
                if row:
                    return _run(row), False
            marks = ",".join("?" for _ in ACTIVE_STATUSES)
            row = conn.execute(
                f"SELECT * FROM runs WHERE incident_id = ? AND status IN ({marks})"
                " ORDER BY started_at DESC LIMIT 1", (run.incident_id, *ACTIVE_STATUSES)).fetchone()
            if row:
                return _run(row), False
            self._insert(conn, run, key)
            return run, True

    def get(self, run_id: str) -> Run | None:
        with self._db.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _run(row) if row else None

    def list_recent(self, limit: int, offset: int) -> tuple[list[tuple[Run, str, str]], int]:
        """Newest runs first, with each run's incident title and scenario type."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT r.*, i.title AS incident_title, i.scenario_type AS scenario_type FROM runs r"
                " JOIN incidents i ON i.id = r.incident_id ORDER BY r.started_at DESC, r.id LIMIT ? OFFSET ?",
                (limit, offset)).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        return [(_run(r), r["incident_title"], r["scenario_type"]) for r in rows], total

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

    def fail_interrupted(self) -> list[str]:
        """Close runs that were queued or running when the server stopped (they can never finish).

        Waiting-for-approval runs are left alone: their state is fully stored and a human can still decide.
        Returns the IDs that were closed. Safe to call when nothing needs closing.
        """
        now = datetime.now(timezone.utc)
        message = json.dumps({"code": "interrupted", "message":
                              "The server stopped while this investigation was running. Start a new one."})
        with self._db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute("SELECT id FROM runs WHERE status IN (?, ?)",
                                (RunStatus.CREATED.value, RunStatus.RUNNING.value)).fetchall()
            ids = [r["id"] for r in rows]
            for run_id in ids:
                conn.execute("UPDATE runs SET status = ?, finished_at = ?, error_code = ? WHERE id = ?",
                             (RunStatus.FAILED.value, _iso(now), "interrupted", run_id))
                self._event(conn, run_id, "stage_failed", None, None, message, now)
                self._event(conn, run_id, "status_changed", "RUNNING", RunStatus.FAILED.value, "interrupted", now)
        return ids

    def record_model_metadata(self, run_id: str, model_id: str | None, prompt_version: str | None) -> None:
        """Remember which model and prompt version produced this run's analysis."""
        with self._db.connect() as conn:
            conn.execute("UPDATE runs SET model_id = ?, prompt_version = ? WHERE id = ?",
                         (model_id, prompt_version, run_id))

    def add_event(self, run_id: str, event_type: str, detail: str | None = None) -> None:
        with self._db.connect() as conn:
            self._event(conn, run_id, event_type, None, None, detail, datetime.now(timezone.utc))

    def events(self, run_id: str, after_seq: int = 0) -> list[dict]:
        """Ordered events with seq > after_seq, so a reconnecting client can resume where it left off."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT seq, event_type, from_status, to_status, detail, created_at"
                " FROM run_events WHERE run_id = ? AND seq > ? ORDER BY seq",
                (run_id, after_seq),
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


def _proposal(row: sqlite3.Row) -> Proposal:
    data = {k: row[k] for k in ("id", "version", "run_id", "description", "risk_class", "approval_status",
                                "proposal_hash", "expires_at")}
    data["parameters"] = json.loads(row["parameters"])
    data["target_scope"] = json.loads(row["target_scope"])
    data["evidence_ids"] = json.loads(row["evidence_ids"])
    data["policy_reasons"] = json.loads(row["policy_reasons"])
    return Proposal(**data)


def _decision(row: sqlite3.Row) -> ApprovalDecision:
    return ApprovalDecision(**{k: row[k] for k in row.keys()})


class ProposalRepository:
    """Versioned proposals and the approval decisions bound to them."""

    def __init__(self, db: Database):
        self._db = db

    def add(self, p: Proposal, created_at: datetime) -> None:
        with self._db.connect() as conn:
            self._insert(conn, p, created_at)

    @staticmethod
    def _insert(conn: sqlite3.Connection, p: Proposal, created_at: datetime) -> None:
        conn.execute(
            "INSERT INTO proposals (id, version, run_id, description, parameters, target_scope, risk_class,"
            " approval_status, proposal_hash, expires_at, created_at, evidence_ids, policy_reasons)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (p.id, p.version, p.run_id, p.description, json.dumps(p.parameters), json.dumps(p.target_scope),
             p.risk_class.value, p.approval_status.value, p.proposal_hash,
             _iso(p.expires_at) if p.expires_at else None, _iso(created_at),
             json.dumps(p.evidence_ids), json.dumps(p.policy_reasons)),
        )

    def add_revision(self, previous: Proposal, new: Proposal, created_at: datetime) -> bool:
        """Atomically supersede `previous` (it becomes EXPIRED, so its approval can never be reused)
        and store the new version. Returns False if `previous` was no longer the latest version."""
        with self._db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            latest = conn.execute("SELECT MAX(version) FROM proposals WHERE id = ?", (previous.id,)).fetchone()[0]
            if latest != previous.version:
                return False
            conn.execute("UPDATE proposals SET approval_status = ? WHERE id = ? AND version = ?",
                         (ApprovalStatus.EXPIRED.value, previous.id, previous.version))
            self._insert(conn, new, created_at)
            return True

    def get(self, proposal_id: str, version: int | None = None) -> Proposal | None:
        """The given version, or the latest one."""
        with self._db.connect() as conn:
            if version is None:
                row = conn.execute("SELECT * FROM proposals WHERE id = ? ORDER BY version DESC LIMIT 1",
                                   (proposal_id,)).fetchone()
            else:
                row = conn.execute("SELECT * FROM proposals WHERE id = ? AND version = ?",
                                   (proposal_id, version)).fetchone()
        return _proposal(row) if row else None

    def latest_for_run(self, run_id: str) -> list[Proposal]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT p.* FROM proposals p WHERE p.run_id = ? AND p.version ="
                " (SELECT MAX(version) FROM proposals WHERE id = p.id) ORDER BY p.created_at, p.id",
                (run_id,)).fetchall()
        return [_proposal(r) for r in rows]

    def set_status(self, proposal_id: str, version: int, expected: ApprovalStatus, new: ApprovalStatus) -> bool:
        with self._db.connect() as conn:
            cur = conn.execute(
                "UPDATE proposals SET approval_status = ? WHERE id = ? AND version = ? AND approval_status = ?",
                (new.value, proposal_id, version, expected.value))
            return cur.rowcount == 1

    def decision_for(self, proposal_id: str, proposal_hash: str) -> ApprovalDecision | None:
        with self._db.connect() as conn:
            row = conn.execute("SELECT * FROM approval_decisions WHERE proposal_id = ? AND proposal_hash = ?",
                               (proposal_id, proposal_hash)).fetchone()
        return _decision(row) if row else None

    def record_decision(self, d: ApprovalDecision, version: int, new_status: ApprovalStatus) -> bool:
        """Atomically store the decision AND move the proposal PENDING -> APPROVED/REJECTED.

        Returns False (and stores nothing) if the proposal is not PENDING at that version any more.
        """
        with self._db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "UPDATE proposals SET approval_status = ? WHERE id = ? AND version = ? AND proposal_hash = ?"
                " AND approval_status = ?",
                (new_status.value, d.proposal_id, version, d.proposal_hash, ApprovalStatus.PENDING.value))
            if cur.rowcount != 1:
                return False
            conn.execute(
                "INSERT INTO approval_decisions (id, proposal_id, proposal_hash, actor, decision, reason, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (d.id, d.proposal_id, d.proposal_hash, d.actor, d.decision.value, d.reason, _iso(d.created_at)))
            return True
