"""SQLite access. A fresh connection is opened per operation, so it is safe across request threads.

The schema is created with `CREATE TABLE IF NOT EXISTS` (repeatable) and versioned via
`PRAGMA user_version`, so a later phase can add a numbered migration step.
"""
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id             TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    description    TEXT NOT NULL,
    scenario_type  TEXT NOT NULL,
    severity       TEXT NOT NULL,
    affected_hosts TEXT NOT NULL,      -- JSON array
    created_at     TEXT NOT NULL,      -- UTC ISO 8601
    synthetic      INTEGER NOT NULL CHECK (synthetic IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_incidents_created ON incidents (created_at DESC, id);

CREATE TABLE IF NOT EXISTS runs (
    id             TEXT PRIMARY KEY,
    incident_id    TEXT NOT NULL REFERENCES incidents (id),
    status         TEXT NOT NULL,
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    model_id       TEXT,
    prompt_version TEXT,
    error_code     TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_incident ON runs (incident_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs (status);

CREATE TABLE IF NOT EXISTS evidence (
    id          TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES runs (id),
    source_type TEXT NOT NULL,
    host_id     TEXT NOT NULL,
    tool_name   TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    payload     TEXT NOT NULL,         -- JSON
    synthetic   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_run ON evidence (run_id);

CREATE TABLE IF NOT EXISTS investigation_reports (
    run_id     TEXT PRIMARY KEY REFERENCES runs (id),
    report     TEXT NOT NULL,          -- JSON
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
    id              TEXT NOT NULL,
    version         INTEGER NOT NULL,
    run_id          TEXT NOT NULL REFERENCES runs (id),
    description     TEXT NOT NULL,
    parameters      TEXT NOT NULL,     -- JSON
    target_scope    TEXT NOT NULL,     -- JSON array
    risk_class      TEXT NOT NULL,
    approval_status TEXT NOT NULL,
    proposal_hash   TEXT NOT NULL,
    expires_at      TEXT,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (id, version)
);
CREATE INDEX IF NOT EXISTS idx_proposals_run ON proposals (run_id);

CREATE TABLE IF NOT EXISTS approval_decisions (
    id            TEXT PRIMARY KEY,
    proposal_id   TEXT NOT NULL,
    proposal_hash TEXT NOT NULL,
    actor         TEXT NOT NULL,
    decision      TEXT NOT NULL,
    reason        TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_proposal ON approval_decisions (proposal_id);

CREATE TABLE IF NOT EXISTS run_events (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL REFERENCES runs (id),
    event_type  TEXT NOT NULL,
    from_status TEXT,
    to_status   TEXT,
    detail      TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_run ON run_events (run_id, seq);
"""


class Database:
    """Holds the database path. Nothing touches the disk until the first `connect()`."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._ready = False
        self._lock = threading.Lock()

    def _ensure_schema(self) -> None:
        with self._lock:
            if self._ready:
                return
            if self.path != ":memory:":
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            conn = self._open()
            try:
                conn.executescript(_SCHEMA)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                conn.commit()
            finally:
                conn.close()
            self._ready = True

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection; commit on success, roll back on error, always close."""
        self._ensure_schema()
        conn = self._open()
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
