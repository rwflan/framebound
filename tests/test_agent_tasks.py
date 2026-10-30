import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from framebound.v2 import storage as S
from framebound.v2.api.app import create_app
from framebound.v2.services.projects import create_project
from framebound.v3.services import tasks


def spec(**changes):
    return dict(id='task', project_id='p', animation_id='walk', intent='Walk to the right',
                subjects='one character', canvas={'width': 32, 'height': 32},
                timing={'holds': [3, 3]}, **changes)


def test_reference_free_public_persistence_and_immutable_policy(tmp_path):
    project = str(tmp_path)
    create_project(project, {'id': 'p'})
    record = tasks.create(project, spec())
    assert tasks.get(project, 'task') == record
    assert tasks.create(project, spec()) == record
    assert record['spec']['inputs'] == []
    assert record['animation_quality_verified'] is False
    with pytest.raises(S.ConflictError):
        tasks.create(project, spec(limits={'max_submissions': 100}))
    revised = spec(supersedes='task', change_reason='new budget')
    revised['id'] = 'task-2'
    assert tasks.create(project, revised)['spec']['supersedes'] == 'task'
    compiled = tasks.compile_inputs(project, 'task')
    assert compiled['provider_execution_authorized'] is False
    con = S.connect(project)
    try:
        assert S.count(con, 'reference_approvals') == 0
        assert S.count(con, 'motion_guides') == 0
        assert S.count(con, 'review_events') == 0
    finally:
        con.close()


def test_dry_run_and_backup(tmp_path):
    project = str(tmp_path / 'new')
    assert tasks.migration_report(project)['needs_migration']
    assert not (tmp_path / 'new').exists()
    create_project(project, {'id': 'p'})
    assert tasks.migration_report(project)['needs_migration']
    tasks.create(project, spec())
    assert not tasks.migration_report(project)['needs_migration']
    backup = sqlite3.connect(str(tmp_path / 'new/backups/before-agent-v3.sqlite3'))
    try:
        assert backup.execute('SELECT count(*) FROM projects').fetchone()[0] == 1
        assert backup.execute("SELECT count(*) FROM sqlite_master WHERE name='agent_task_specs'").fetchone()[0] == 0
    finally:
        backup.close()


def test_quality_requirements_remain_explicitly_unsupported(tmp_path):
    create_project(str(tmp_path), {'id': 'p'})
    record = tasks.create(str(tmp_path), spec(profile='fixed-subject-v1'))
    assert len([r for r in record['requirements'] if r['required'] and r['applicability'] == 'unsupported']) == 6
    assert tasks.compile_inputs(str(tmp_path), 'task')['capability_gaps']


def test_http_task_route(tmp_path):
    create_project(str(tmp_path), {'id': 'p'})
    client = TestClient(create_app(str(tmp_path)))
    response = client.post('/v3/tasks', json=spec())
    assert response.status_code == 200, response.text
    assert client.get('/v3/tasks/task').json() == response.json()
    assert client.get('/v3/tasks/task/inputs').json()['creative_status'] == 'unreviewed'


def test_identity_only_and_missing_input_fail_closed(tmp_path):
    from PIL import Image
    from framebound.v2.services.assets import import_asset
    from framebound.v2.services.errors import InvalidInput
    create_project(str(tmp_path), {'id': 'p'})
    image = tmp_path / 'identity.png'
    Image.new('RGBA', (32, 32), 'red').save(image)
    import_asset(str(tmp_path), str(image), 'identity')
    binding = {'asset_id': 'identity', 'role': 'identity', 'provenance': 'original artist image',
               'designated_by': 'parent-agent', 'basis': 'user supplied appearance input'}
    record = tasks.create(str(tmp_path), spec(inputs=[binding]))
    assert record['spec']['inputs'][0]['role'] == 'identity'
    compiled = tasks.compile_inputs(str(tmp_path), 'task')
    assert compiled['assets'][0]['byte_sha256'] == S.sha256_bytes(image.read_bytes())
    assert (tmp_path / compiled['assets'][0]['blob_path']).is_file()
    image_blob = S.blob_path(str(tmp_path), tasks.S.sha256_bytes(image.read_bytes()))
    image_blob.unlink()
    with pytest.raises(InvalidInput, match='unavailable or corrupt'):
        tasks.compile_inputs(str(tmp_path), 'task')
    payload = spec(inputs=[binding]); payload['id'] = 'missing'
    with pytest.raises(InvalidInput, match='unavailable or corrupt'):
        tasks.create(str(tmp_path), payload)


def test_cli_and_mcp_use_shared_task_service(tmp_path):
    import asyncio
    import subprocess
    import sys
    from framebound.v2.mcp.server import build_server
    create_project(str(tmp_path), {'id': 'p'})
    path = tmp_path / 'task.json'; path.write_text(json.dumps(spec()))
    result = subprocess.run([sys.executable, '-m', 'framebound', 'task-create',
                            '--project', str(tmp_path), '--spec', str(path)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['id'] == 'task'
    server = build_server(str(tmp_path))
    tools = asyncio.run(server.list_tools())
    assert {'task_create', 'task_get', 'task_compile_inputs'} <= {t.name for t in tools}


def test_older_v3_record_keeps_its_original_fields_and_digest(tmp_path):
    from framebound.v3.evaluate import digest
    create_project(str(tmp_path), {'id':'p'})
    original=tasks.create(str(tmp_path),spec())
    # Represent the v1 negotiator's pre-extension serialized task shape.
    original['spec'].pop('region_observations'); original['spec'].pop('temporal_observations')
    original['spec'].pop('source_correspondence',None);original['spec'].pop('scene',None)
    original['spec']['limits'].pop('max_evaluation_pixels')
    original['spec']['limits'].pop('max_measurement_pixels')
    original['spec_sha256']=digest(original['spec'])
    original['evaluator_version']='task-negotiator-v1'
    con=tasks._connect(str(tmp_path))
    con.execute('UPDATE agent_task_specs SET data=? WHERE id=?',(json.dumps(original),'task'));con.commit();con.close()
    loaded=tasks.get(str(tmp_path),'task')
    assert loaded==original
    assert digest(loaded['spec'])==loaded['spec_sha256']
    client=TestClient(create_app(str(tmp_path)))
    assert client.get('/v3/tasks/task').json()==original
