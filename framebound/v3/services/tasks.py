"""Immutable reference-free registration and generation inputs, shared by transports."""
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

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


def backup_database(project_dir, name):
    """Caller holds the schema writer lock; copy committed WAL state atomically."""
    backup = Path(project_dir) / 'backups' / name
    if backup.exists():
        return
    reader = sqlite3.connect(str(Path(project_dir) / 'framebound.sqlite3'))
    temporary = backup.with_name(f'.agent-v3-{uuid.uuid4().hex}.sqlite3')
    target = sqlite3.connect(str(temporary))
    try:
        reader.backup(target)
        target.close()
        temporary.replace(backup)
    finally:
        target.close()
        reader.close()
        temporary.unlink(missing_ok=True)


def _connect(project_dir):
    # Back up the entire pre-v3 database, including WAL, before adding v3 tables.
    con = S.connect(project_dir)
    try:
        con.execute('BEGIN IMMEDIATE')
        exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone()
        if not exists:
            backup = Path(project_dir) / 'backups' / 'before-agent-v3.sqlite3'
            if not backup.exists():
                backup_database(project_dir, backup.name)
            con.execute(f'CREATE TABLE {TABLE}(id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        con.commit()
        return con
    except Exception:
        con.close()
        raise


def _negotiate(spec):
    # Negotiate only methods with actual declared inputs; persist gaps unchanged.
    requested = [('media', 'media', True), ('timing', 'timing', True)]
    requested += [(r.id, r.check, r.required) for r in spec.requirements]
    from ..evaluate import supported_families, validate_observations
    try:
        validate_observations(spec)
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc
    families = supported_families(spec)
    if spec.profile == 'fixed-subject-v1':
        requested += [(f'profile-{family}', family, True)
                      for family in ('feature', 'appearance', 'contact', 'continuity', 'moving')]
        if spec.loop:
            requested.append(('profile-loop', 'loop', True))
    out = []
    for rid, check, required in requested:
        supported = check in {'media', 'timing'} or check in families
        out.append(NegotiatedRequirement(
            id=rid, check=check, required=required,
            applicability='supported' if supported else 'unsupported',
            method={'media': 'declared-regions-v2:media', 'timing': 'declared-regions-v2:timing'}.get(check, 'declared-regions-v2' if check in families else 'none'),
            limitation=('Establishes structural validity only; animation quality is not verified.'
                        if check in {'media', 'timing'} else 'Only task-authored regions, colors and event bounds are measured; arbitrary anatomy and prose action correctness are not established.' if supported else 'No usable task-authored measurement is available for this requirement.'),
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
                return old.model_dump(mode='json', exclude_unset=True)
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
        return _get(con, task_id).model_dump(mode='json', exclude_unset=True)
    finally:
        con.close()


def compile_inputs(project_dir: str, task_id: str) -> dict:
    record = get(project_dir, task_id)
    con = S.connect(project_dir)
    assets = []
    try:
        for binding in record['spec']['inputs']:
            asset, _ = S.get(con, 'assets', binding['asset_id'])
            blob = S.blob_path(project_dir, asset['byte_sha256'])
            if not blob.is_file() or S.sha256_bytes(blob.read_bytes()) != asset['byte_sha256']:
                raise InvalidInput(f"input asset {binding['asset_id']} is unavailable or corrupt")
            assets.append({'id': binding['asset_id'], 'role': binding['role'],
                           'byte_sha256': asset['byte_sha256'],
                           'pixel_sha256': asset.get('pixel_sha256'),
                           'width': asset.get('width'), 'height': asset.get('height'),
                           'blob_path': str(blob.relative_to(Path(project_dir))),
                           'http_path': f"/api/asset/{binding['asset_id']}"})
    except KeyError as exc:
        raise InvalidInput(f'missing task input: {exc}') from exc
    finally:
        con.close()
    return {'schema_version': '3.0', 'task_id': task_id,
            'spec_sha256': record['spec_sha256'], 'assets': assets, 'intent': record['spec']['intent'],
            'spec': record['spec'], 'requirements': record['requirements'],
            'execution': 'external_agent', 'provider_execution_authorized': False,
            'creative_status': 'unreviewed', 'animation_quality_verified': False,
            'capability_gaps': [r for r in record['requirements'] if r['applicability'] != 'supported']}
