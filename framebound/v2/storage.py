"""v2 durable storage: SQLite (WAL) + content-addressed blob store.

Layout inside a project directory:
  framebound.sqlite3, blobs/sha256/<2>/<rest>, exports/<snapshot>/, backups/
Frozen records (contracts, clip revisions, evaluations, packets) are insert-only:
updates raise FrozenRevisionError. Mutable records use expected_version preconditions;
mismatch raises StaleRevisionError (surfaces as 409 stale_revision).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from . import domain as D

MIGRATION_VERSION = 1


class StaleRevisionError(ValueError):
    pass


class FrozenRevisionError(ValueError):
    pass


class ConflictError(ValueError):
    pass


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS character_revisions(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS contract_revisions(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS clip_revisions(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS frame_instances(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS annotation_revisions(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS evaluations(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS review_packets(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS review_events(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS correction_tasks(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS export_snapshots(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_idempotency ON jobs(json_extract(data, '$.idempotency_key'));
"""

FROZEN_TABLES = {"contract_revisions", "clip_revisions", "evaluations", "review_packets"}


def connect(project_dir: str | Path) -> sqlite3.Connection:
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "blobs" / "sha256").mkdir(parents=True, exist_ok=True)
    (project_dir / "exports").mkdir(parents=True, exist_ok=True)
    (project_dir / "backups").mkdir(parents=True, exist_ok=True)
    db = project_dir / "framebound.sqlite3"
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA_SQL)
    row = con.execute("SELECT v FROM meta WHERE k='migration_version'").fetchone()
    if row is None:
        con.execute("INSERT INTO meta(k, v) VALUES('migration_version', ?)", (str(MIGRATION_VERSION),))
        con.commit()
    return con


def blob_path(project_dir: str | Path, digest: str) -> Path:
    return Path(project_dir) / "blobs" / "sha256" / digest[:2] / digest[2:]


def store_blob(project_dir: str | Path, data: bytes) -> str:
    """Atomic content-addressed write: temp file, hash, rename. Returns hex digest."""
    digest = hashlib.sha256(data).hexdigest()
    dest = blob_path(project_dir, digest)
    if dest.is_file():
        return digest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".tmp-{digest}"
    tmp.write_bytes(data)
    tmp.rename(dest)
    return digest


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _table_for(model: D.Strict) -> str:
    mapping = {
        "Project": "projects", "Asset": "assets", "CharacterRevision": "character_revisions",
        "ClipContractRevision": "contract_revisions", "ClipRevision": "clip_revisions",
        "FrameInstance": "frame_instances", "AnnotationRevision": "annotation_revisions",
        "Evaluation": "evaluations", "Attempt": "attempts", "ReviewPacket": "review_packets",
        "ReviewEvent": "review_events", "CorrectionTask": "correction_tasks",
        "Job": "jobs", "ExportSnapshot": "export_snapshots",
    }
    return mapping[type(model).__name__]


def insert(con: sqlite3.Connection, model: D.Strict) -> int:
    table = _table_for(model)
    payload = model.model_dump_json()
    try:
        con.execute(f"INSERT INTO {table}(id, data) VALUES(?, ?)", (model.id, payload))
    except sqlite3.IntegrityError as e:
        raise ConflictError(f"duplicate id {model.id} in {table}: {e}") from e
    con.commit()
    return 1


def get(con: sqlite3.Connection, table: str, rid: str) -> tuple[dict, int]:
    row = con.execute(f"SELECT data, version FROM {table} WHERE id=?", (rid,)).fetchone()
    if row is None:
        raise KeyError(f"{rid} not found in {table}")
    return json.loads(row["data"]), row["version"]


def update_mutable(con: sqlite3.Connection, table: str, model: D.Strict, expected_version: int) -> int:
    """Optimistic concurrency: only when version matches; else StaleRevisionError (409)."""
    if table in FROZEN_TABLES:
        raise FrozenRevisionError(f"{table} is append-only; create a new revision instead of updating {model.id}")
    cur = con.execute(
        f"UPDATE {table} SET data=?, version=version+1 WHERE id=? AND version=?",
        (model.model_dump_json(), model.id, expected_version),
    )
    if cur.rowcount == 0:
        row = con.execute(f"SELECT version FROM {table} WHERE id=?", (model.id,)).fetchone()
        if row is None:
            raise KeyError(f"{model.id} not found in {table}")
        raise StaleRevisionError(
            f"stale_revision: {table}/{model.id} at version {row['version']}, writer expected {expected_version}"
        )
    con.commit()
    return expected_version + 1


def create_job_idempotent(con: sqlite3.Connection, job: D.Job) -> tuple[D.Job, bool]:
    """Returns (job, created). Repeating the same idempotency key returns the original job."""
    row = con.execute(
        "SELECT data FROM jobs WHERE json_extract(data, '$.idempotency_key')=?", (job.idempotency_key,)
    ).fetchone()
    if row is not None:
        return D.Job.model_validate_json(row["data"]), False
    insert(con, job)
    return job, True


def count(con: sqlite3.Connection, table: str) -> int:
    return con.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
