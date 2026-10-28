"""v2 durable storage: SQLite (WAL) + content-addressed blob store.

Layout inside a project directory:
  framebound.sqlite3, blobs/sha256/<2>/<rest>, exports/<snapshot>/, backups/
Frozen records (contracts, clip revisions, evaluations, packets) are insert-only:
updates raise FrozenRevisionError. Mutable records use expected_version preconditions;
mismatch raises StaleRevisionError (surfaces as 409 stale_revision).
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import sqlite3
from pathlib import Path

from . import domain as D

MIGRATION_VERSION = 3


class StaleRevisionError(ValueError):
    pass


class FrozenRevisionError(ValueError):
    pass


class ConflictError(ValueError):
    pass


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS provider_grants(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
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
CREATE TABLE IF NOT EXISTS reviewer_pairings(code_sha TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reviewer_sessions(token_sha TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS motion_guides(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS reference_approvals(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS registrations(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS edit_masks(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS compiled_briefs(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS world_traces(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS transition_traces(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
"""

# Evidence-bearing entities are append-only: corrections arrive as superseding
# records, never in-place edits. Only projects, correction_tasks and jobs are
# mutable, and only through expected-version transitions.
FROZEN_TABLES = {"assets", "character_revisions", "contract_revisions", "clip_revisions",
                 "frame_instances", "annotation_revisions", "evaluations", "attempts",
                 "review_packets", "review_events", "export_snapshots", "registrations",
                 "edit_masks",
                 "compiled_briefs", "world_traces", "transition_traces"}


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
    elif int(row["v"]) < MIGRATION_VERSION:
        # v1 -> v2: new authority tables arrive via CREATE IF NOT EXISTS above;
        # no existing record is rewritten. Bump the version marker only.
        con.execute("UPDATE meta SET v=? WHERE k='migration_version'", (str(MIGRATION_VERSION),))
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
    tmp = dest.parent / f".tmp-{digest}-{os.getpid()}-{secrets.token_hex(4)}"
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
        "MotionGuide": "motion_guides", "ReferenceApproval": "reference_approvals", "Run": "runs",
            "EditMask": "edit_masks", "CompiledBrief": "compiled_briefs", "WorldTrace": "world_traces",
            "TransitionTrace": "transition_traces",
        "Registration": "registrations", "ProviderGrant": "provider_grants",
    }
    return mapping[type(model).__name__]


def table_for(model: D.Strict) -> str:
    return _table_for(model)


def stage(con: sqlite3.Connection, model: D.Strict) -> None:
    """Stage an INSERT inside the caller's transaction (no commit)."""
    table = _table_for(model)
    try:
        con.execute(f"INSERT INTO {table}(id, data) VALUES(?, ?)",
                    (model.id, model.model_dump_json()))
    except sqlite3.IntegrityError as e:
        raise ConflictError(f"duplicate id {model.id} in {table}: {e}") from e


def insert(con: sqlite3.Connection, model: D.Strict) -> int:
    stage(con, model)
    con.commit()
    return 1


def stage_identical(con: sqlite3.Connection, model: D.Strict,
                    generated_fields: tuple[str, ...] = ()) -> bool:
    """Insert immutable input, or replay only the identical semantic payload."""
    table = table_for(model)
    row = con.execute(f"SELECT data FROM {table} WHERE id=?", (model.id,)).fetchone()
    if row is None:
        stage(con, model)
        return True
    old = type(model).model_validate_json(row['data']).model_dump(mode='json')
    new = model.model_dump(mode='json')
    for field in generated_fields:
        old.pop(field, None)
        new.pop(field, None)
    if old != new:
        raise ConflictError(f"{table}/{model.id}: identifier already bound to different inputs")
    return False


@contextlib.contextmanager
def atomic(con: sqlite3.Connection):
    """Use-case-owned transaction: all staged writes commit together.

    Storage helpers commit eagerly by default for single-record convenience;
    multi-record use cases must stage() inside this block so a mid-way failure
    rolls back instead of leaving partial issue/task or revision rows.
    """
    try:
        yield con
    except Exception:
        con.rollback()
        raise
    else:
        con.commit()


def get(con: sqlite3.Connection, table: str, rid: str) -> tuple[dict, int]:
    row = con.execute(f"SELECT data, version FROM {table} WHERE id=?", (rid,)).fetchone()
    if row is None:
        raise KeyError(f"{rid} not found in {table}")
    return json.loads(row["data"]), row["version"]


def stage_update(con: sqlite3.Connection, table: str, model: D.Strict, expected_version: int) -> int:
    """Stage an expected-version UPDATE inside the caller's transaction (no commit)."""
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
    return expected_version + 1


def update_mutable(con: sqlite3.Connection, table: str, model: D.Strict, expected_version: int) -> int:
    nv = stage_update(con, table, model, expected_version)
    con.commit()
    return nv
    """Optimistic concurrency: only when version matches; else StaleRevisionError (409)."""
    nv = stage_update(con, table, model, expected_version)
    con.commit()
    return nv


def create_job_idempotent(con: sqlite3.Connection, job: D.Job) -> tuple[D.Job, bool]:
    """Returns (job, created). Same key + same payload returns the original job.

    Same key + different payload is a conflict, never a silent reuse. A lost
    race on the unique index re-reads the winner instead of failing the retry.
    """
    row = con.execute(
        "SELECT data FROM jobs WHERE json_extract(data, '$.idempotency_key')=?", (job.idempotency_key,)
    ).fetchone()
    if row is not None:
        existing = D.Job.model_validate_json(row["data"])
        if existing.payload_sha256 != job.payload_sha256:
            raise ConflictError(
                f"idempotency key {job.idempotency_key} already used with a different payload")
        return existing, False
    try:
        insert(con, job)
    except ConflictError:
        row = con.execute(
            "SELECT data FROM jobs WHERE json_extract(data, '$.idempotency_key')=?", (job.idempotency_key,)
        ).fetchone()
        if row is None:
            raise
        existing = D.Job.model_validate_json(row["data"])
        if existing.payload_sha256 != job.payload_sha256:
            raise ConflictError(
                f"idempotency key {job.idempotency_key} already used with a different payload")
        return existing, False
    return job, True


def count(con: sqlite3.Connection, table: str) -> int:
    return con.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
