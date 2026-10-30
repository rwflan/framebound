"""Immutable reference-free registration and generation inputs, shared by transports."""
import hashlib
import json
from pathlib import Path
import sqlite3

from ...v2 import storage as S
from ...v2.services.errors import InvalidInput
from ..domain import NegotiatedRequirement, TaskRecord, TaskSpec

TABLE = 'agent_task_specs'


def migration_report(project_dir: str) -> dict:
    """Read-only inventory; opening a report must never initialize/migrate a project."""
    db = Path(project_dir) / 'framebound.sqlite3'
    if not db.is_file():
        return {'schema_version': '3.0', 'mode': 'dry-run', 'mutated': False,
                'needs_migration': True, 'legacy_records_reinterpreted': False}
    con = sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)
    try:
        exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone()
        return {'schema_version': '3.0', 'mode': 'dry-run', 'mutated': False,
                'needs_migration': not bool(exists), 'legacy_records_reinterpreted': False}
    finally:
        con.close()


def _connect(project_dir):
    # Back up the entire pre-v3 database, including WAL, before adding v3 tables.
    con = S.connect(project_dir)
    try:
        con.execute('BEGIN IMMEDIATE')
        exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone()
        if not exists:
            backup = Path(project_dir) / 'backups' / 'before-agent-v3.sqlite3'
            if not backup.exists():
                reader = sqlite3.connect(str(Path(project_dir) / 'framebound.sqlite3'))
                target = sqlite3.connect(str(backup))
                try:
                    reader.backup(target)
                finally:
                    target.close()
                    reader.close()
            con.execute(f'CREATE TABLE {TABLE}(id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        con.commit()
        return con
    except Exception:
        con.close()
        raise


def _negotiate(spec):
    # Structural checks are the only currently established reference-free capability.
    requested = [('media', 'media', True), ('timing', 'timing', True)]
    requested += [(r.id, r.check, r.required) for r in spec.requirements]
    if spec.profile == 'fixed-subject-v1':
        requested += [('profile-feature', 'feature_continuity', True),
                      ('profile-action', 'action_correctness', True),
                      ('profile-temporal', 'temporal_consistency', True)]
    out = []
    for rid, check, required in requested:
        supported = check in {'media', 'timing'}
        out.append(NegotiatedRequirement(
            id=rid, check=check, required=required,
            applicability='supported' if supported else 'unsupported',
            method='native-media-v1' if supported else 'none',
            limitation=('Establishes structural validity only; animation quality is not verified.'
                        if supported else 'No validated reference-free evaluator is available for this requirement.'),
            ways_forward=[] if supported else ['Obtain independently reviewed annotations and a validated evaluator.',
                        'Create a new specification revision with a recorded scope change.']))
    if len({r.id for r in out}) != len(out):
        raise InvalidInput('requirement IDs collide with profile requirements: use a unique ID')
    return out


def create(project_dir: str, payload: dict) -> dict:
    spec = TaskSpec.model_validate(payload)
    con = _connect(project_dir)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            S.get(con, 'projects', spec.project_id)
            for binding in spec.inputs:
                asset, _ = S.get(con, 'assets', binding.asset_id)
                blob = S.blob_path(project_dir, asset['byte_sha256'])
                if not blob.is_file() or S.sha256_bytes(blob.read_bytes()) != asset['byte_sha256']:
                    raise InvalidInput(f'input asset {binding.asset_id} is unavailable or corrupt')
            if spec.supersedes:
                parent = _get(con, spec.supersedes)
                if (parent.spec.project_id, parent.spec.animation_id) != (spec.project_id, spec.animation_id):
                    raise InvalidInput('a specification revision must belong to the same project and animation')
            existing = con.execute(f'SELECT data FROM {TABLE} WHERE id=?', (spec.id,)).fetchone()
            if existing:
                old = TaskRecord.model_validate_json(existing['data'])
                if old.spec.model_dump(exclude={'created_at'}) != spec.model_dump(exclude={'created_at'}):
                    raise S.ConflictError('task ID already bound to a different immutable specification')
                return old.model_dump(mode='json')
            digest = hashlib.sha256(json.dumps(spec.model_dump(mode='json'), sort_keys=True,
                                               separators=(',', ':')).encode()).hexdigest()
            record = TaskRecord(id=spec.id, spec=spec, requirements=_negotiate(spec), spec_sha256=digest)
            con.execute(f'INSERT INTO {TABLE}(id,data) VALUES(?,?)', (record.id, record.model_dump_json()))
        return record.model_dump(mode='json')
    except KeyError as exc:
        raise InvalidInput(f'missing task prerequisite: {exc}') from exc
    finally:
        con.close()


def _get(con, task_id):
    row = con.execute(f'SELECT data FROM {TABLE} WHERE id=?', (task_id,)).fetchone()
    if not row:
        raise InvalidInput(f'unknown task {task_id}')
    return TaskRecord.model_validate_json(row['data'])


def get(project_dir: str, task_id: str) -> dict:
    con = _connect(project_dir)
    try:
        return _get(con, task_id).model_dump(mode='json')
    finally:
        con.close()


def compile_inputs(project_dir: str, task_id: str) -> dict:
    record = get(project_dir, task_id)
    con = S.connect(project_dir)
    try:
        for binding in record['spec']['inputs']:
            asset, _ = S.get(con, 'assets', binding['asset_id'])
            blob = S.blob_path(project_dir, asset['byte_sha256'])
            if not blob.is_file() or S.sha256_bytes(blob.read_bytes()) != asset['byte_sha256']:
                raise InvalidInput(f"input asset {binding['asset_id']} is unavailable or corrupt")
    finally:
        con.close()
    return {'schema_version': '3.0', 'task_id': task_id,
            'spec_sha256': record['spec_sha256'], 'intent': record['spec']['intent'],
            'spec': record['spec'], 'requirements': record['requirements'],
            'execution': 'external_agent', 'provider_execution_authorized': False,
            'creative_status': 'unreviewed', 'animation_quality_verified': False,
            'capability_gaps': [r for r in record['requirements'] if r['applicability'] != 'supported']}
