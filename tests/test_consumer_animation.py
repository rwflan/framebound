"""Public harness journey uses real local artifacts; fixtures are not learned art."""
import asyncio
import hashlib
import json

from PIL import Image, ImageDraw
import pytest

from framebound.v2 import storage as S
from framebound.v2.mcp.server import build_server
from framebound.v2.services.errors import InvalidInput
from framebound.v3.services import consumer, failures, loop


def sheet(tmp_path, columns=3, rows=2, scale=1, opaque=False):
    cell = 32 * scale
    image = Image.new('RGBA', (cell * columns, cell * rows), (255,255,255,255) if opaque else (0,0,0,0))
    draw = ImageDraw.Draw(image)
    for i in range(columns * rows):
        x, y = (i % columns) * cell, (i // columns) * cell
        draw.ellipse((x + 8 * scale, y + 6 * scale, x + 24 * scale, y + 26 * scale), fill=(20+i,80,140,255))
    path = tmp_path / ('opaque.png' if opaque else 'sheet.png')
    image.save(path)
    return path


def create(tmp_path, holds=None):
    return consumer.create(str(tmp_path), dict(id='walk', intent='A subject walks in place',
        subjects='one original stylised creature', canvas=dict(width=32, height=32), holds=holds or [2]*6))


@pytest.mark.parametrize('columns,rows', [(3,2),(4,3),(6,4)])
def test_no_training_full_screen_to_native_export_and_exact_replay(tmp_path, columns, rows):
    count = columns * rows
    started = create(tmp_path, [2]*count)
    assert started['training_required'] is False
    assert started['provider_dispatch'] is False
    assert started['generation']['execution'] == 'external_agent'
    image = sheet(tmp_path, columns, rows, scale=2)
    result = consumer.submit_sheet(str(tmp_path), 'animation:walk', 'take-1', str(image), columns, rows)
    assert result['status'] == 'submitted'
    assert result['animation']['eligibility']['eligible']
    assert consumer.submit_sheet(str(tmp_path), 'animation:walk', 'take-1', str(image), columns, rows) == result
    output = consumer.export(str(tmp_path), 'animation:walk')
    manifest = json.loads(open(output['manifest_path']).read())
    assert manifest['timing']['holds'] == [2]*count
    assert manifest['animation_quality_verified'] is False
    assert manifest['creative_status'] != 'approved'
    for entry in manifest['files']:
        raw = (tmp_path / 'animation-exports' / output['destination'].split('/')[-1] / entry['file']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry['sha256']
    assert Image.open(output['destination'] + '/frame-000.png').size == (32,32)
    assert consumer.export(str(tmp_path), 'animation:walk') == output
    revision = loop.revision_get(str(tmp_path), 'take-1')['revision']
    event = revision['generation_metadata']['sheet_derivation']
    assert event['generation_attribution'] == 'unknown'
    assert event['provider_execution_verified'] is False
    assert event['original_output_sha256'] == [hashlib.sha256(image.read_bytes()).hexdigest()]
    assert all('common canvas 32x32' in t['operation'] for t in event['transformations'])


def test_opaque_requires_whole_screen_segmentation_without_submission(tmp_path):
    create(tmp_path)
    source = sheet(tmp_path, opaque=True)
    result = consumer.submit_sheet(str(tmp_path), 'animation:walk', 'opaque', str(source))
    assert result['status'] == 'intake_blocked'
    assert result['submitted'] is False
    assert loop.get(str(tmp_path), 'animation:walk')['submission_ids'] == []
    assert S.blob_path(str(tmp_path), result['source_sha256']).read_bytes() == source.read_bytes()
    with pytest.raises(InvalidInput, match='No evaluated revision'):
        consumer.export(str(tmp_path), 'animation:walk')


def test_frozen_grid_and_task_identity_are_not_silently_changed(tmp_path):
    create(tmp_path)
    assert create(tmp_path)['run']['id'] == 'animation:walk'
    with pytest.raises(S.ConflictError):
        create(tmp_path, [3]*6)
    with pytest.raises(InvalidInput, match='hold count'):
        consumer.submit_sheet(str(tmp_path), 'animation:walk', 'bad-grid', str(sheet(tmp_path)), 2, 2)


def test_unknown_parent_attempt_stays_blocked_and_never_dispatches(tmp_path):
    create(tmp_path)
    failures.record(str(tmp_path), 'animation:walk', dict(id='attempt', kind='provider_failure',
                    reason='Connection lost before provider acknowledgement', outcome_known=False))
    with pytest.raises(InvalidInput, match='blocked'):
        consumer.submit_sheet(str(tmp_path), 'animation:walk', 'new', str(sheet(tmp_path)))
    assert loop.get(str(tmp_path), 'animation:walk')['submission_ids'] == []


def test_mcp_registers_consumer_tools(tmp_path):
    server = build_server(str(tmp_path))
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {'create_animation','submit_animation_sheet','get_generated_animation','export_generated_animation'} <= names


def test_actual_mcp_tool_calls_complete_public_journey(tmp_path):
    server = build_server(str(tmp_path))
    path = sheet(tmp_path)
    async def journey():
        started = await server.call_tool('create_animation', {'request': dict(id='walk',
            intent='Walk through a complete cycle', subjects='one original creature',
            canvas=dict(width=32,height=32))})
        assert not started.is_error
        submitted = await server.call_tool('submit_animation_sheet', dict(run_id='animation:walk',
            revision_id='mcp-take', sheet_path=str(path)))
        assert not submitted.is_error
        exported = await server.call_tool('export_generated_animation', {'run_id':'animation:walk'})
        assert not exported.is_error
        return exported
    result = asyncio.run(journey())
    assert json.loads(result.content[0].text)['manifest']['timing']['holds'] == [2]*6
