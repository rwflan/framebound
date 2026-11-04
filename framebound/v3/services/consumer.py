"""Knowledge-guided external-harness animation, without a training prerequisite.

Generation belongs to the caller. This service never sends a provider request,
guesses alpha from a matte, or turns structural checks into artistic approval.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile

from PIL import Image

from ...v2 import storage as S
from ...v2.media.canonical import load_native_image
from ...v2.services.assets import import_asset
from ...v2.services.errors import InvalidInput
from ...v2.services.projects import create_project
from ..intake import inspect, framing
from . import loop, tasks


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _next(run, count):
    if run['lifecycle'] == 'completed':
        return {'tool': 'export_generated_animation', 'arguments': {'run_id': run['id']}}
    if run['lifecycle'] in {'blocked', 'cancelled'}:
        return {'tool': 'get_generated_animation', 'arguments': {'run_id': run['id']},
                'instruction': 'Stop generation: ' + str(run.get('stop_reason'))}
    columns = next((n for n in (3,4,6,2,1) if count % n == 0 and count // n <= 24), 1)
    arguments = {'run_id': run['id'], 'revision_id': '<stable unique revision id>',
                 'sheet_path': '<absolute path to generated alpha PNG pose screen>',
                 'columns': columns, 'rows': count // columns}
    if run['current_revision_id']:
        arguments.update(parent_revision_id=run['current_revision_id'],
                         feedback_id=run['feedback']['id'])
    return {'tool': 'submit_animation_sheet', 'arguments': arguments,
            'instruction': 'Generate the whole pose screen in one request using the compiled brief and current saved feedback. If the generator returns opaque backing, segment the whole screen once using your harness, retaining its original and receipt. Submit actual alpha, never erase guessed background colors. Keep every pose in its declared cell and preserve the frozen shared camera.'}


def create(project, request):
    """Freeze a task, start its existing bounded run and compile generation inputs."""
    allowed = {'id', 'project_id', 'intent', 'subjects', 'appearance', 'canvas', 'holds',
               'ticks_per_second', 'loop', 'inputs', 'preserve', 'requirements',
               'region_observations', 'temporal_observations', 'profile', 'character_consistency'}
    if set(request) - allowed:
        raise InvalidInput('Unknown animation settings: ' + ', '.join(sorted(set(request) - allowed)))
    aid = request.get('id')
    if not isinstance(aid, str) or not 1 <= len(aid) <= 60:
        raise InvalidInput('Provide a stable animation id of 1–60 characters')
    project_id = request.get('project_id', 'animations')
    create_project(project, {'id': project_id})
    spec = dict(id='animation:' + aid, project_id=project_id, animation_id=aid,
                intent=request.get('intent'), subjects=request.get('subjects'),
                appearance=request.get('appearance', ''),
                canvas=request.get('canvas', {'width': 256, 'height': 256}),
                timing={'holds': request.get('holds', [2] * 6),
                        'ticks_per_second': request.get('ticks_per_second', 12)},
                loop=request.get('loop', True), inputs=request.get('inputs', []),
                preserve=request.get('preserve', []), allowed_changes=['full_clip'],
                profile=request.get('profile', 'structural-v1'),
                requirements=request.get('requirements', []),
                region_observations=request.get('region_observations', []),
                temporal_observations=request.get('temporal_observations', []))
    if request.get('character_consistency') is not None:spec['character_consistency']=request['character_consistency']
    tasks.create(project, spec)
    loop.start(project, spec['id'], 'animation:' + aid)
    run = loop.get(project, 'animation:' + aid)
    return dict(run=run, generation=tasks.compile_inputs(project, spec['id']),
                training_required=False, provider_dispatch=False,
                next_action=_next(run, len(spec['timing']['holds'])))


def submit_sheet(project, run_id, revision_id, sheet_path, columns=3, rows=2,
                 parent_revision_id=None, feedback_id=None, original_sheet_path=None):
    """Cut a declared full-screen grid and apply ONE common canvas transform."""
    if not isinstance(revision_id, str) or not 1 <= len(revision_id) <= 60:
        raise InvalidInput('Sheet revision id must contain 1–60 characters')
    if type(columns) is not int or type(rows) is not int or not 1 <= columns <= 24 or not 1 <= rows <= 24:
        raise InvalidInput('Declare a bounded integer grid')
    run = loop.get(project, run_id)
    spec = tasks.get(project, run['task_id'])['spec']
    if columns * rows != len(spec['timing']['holds']):
        raise InvalidInput('Grid cell count must equal the frozen authored hold count')
    source = Path(sheet_path)
    if not source.is_file() or source.stat().st_size > 32 * 1024 * 1024:
        raise InvalidInput('Provide a PNG file no larger than 32 MiB')
    raw = source.read_bytes()
    image = load_native_image(raw)
    source_sha = S.store_blob(project, raw)
    originals = [source_sha]
    if original_sheet_path:
        original = Path(original_sheet_path)
        if not original.is_file() or original.stat().st_size > 32 * 1024 * 1024:
            raise InvalidInput('Original source is unavailable or exceeds 32 MiB')
        # Preserve original pixels; attribution remains an external assertion.
        load_native_image(original.read_bytes())
        originals.append(S.store_blob(project, original.read_bytes()))
    if image.width % columns or image.height % rows:
        raise InvalidInput('Sheet dimensions must divide exactly by the declared grid')
    cw, ch = image.width // columns, image.height // rows
    target = (spec['canvas']['width'], spec['canvas']['height'])
    if cw * target[1] != ch * target[0]:
        raise InvalidInput('Every cell must share the frozen canvas aspect ratio; no per-pose fitting')
    crops = [image.crop(((i % columns) * cw, (i // columns) * ch,
                         (i % columns + 1) * cw, (i // columns + 1) * ch))
             for i in range(columns * rows)]
    checks = []
    for crop in crops:
        check = inspect(crop)
        check['source_framing'] = framing(crop)
        check['eligible'] = check['eligible'] and check['source_framing']['eligible']
        check['reasons'].extend(check['source_framing']['reasons'])
        checks.append(check)
    if not all(check['eligible'] for check in checks):
        return dict(status='intake_blocked', source_sha256=source_sha, frames=checks,
                    submitted=False, provider_dispatch=False,
                    next_action='Use one whole-screen segmentation in your harness when alpha is missing; retain the source and receipt. Clipped or scenic output needs an explicitly new generation, not inferred erasure. No mask or image retry is dispatched by Framebound.')
    frames = [crop.resize(target, Image.Resampling.LANCZOS) if crop.size != target else crop for crop in crops]
    if not all(inspect(frame)['eligible'] for frame in frames):
        raise InvalidInput('Common canvas transform failed native alpha intake')
    ids, transformations = [], []
    for i, frame in enumerate(frames):
        encoded = io.BytesIO(); frame.save(encoded, format='PNG')
        sha = S.store_blob(project, encoded.getvalue())
        asset_id = 'sheet-' + _hash([run_id, revision_id, i])[:48]
        import_asset(project, str(S.blob_path(project, sha)), asset_id, source_kind='derived')
        ids.append(asset_id)
        transformations.append(dict(operation=f'row-major declared-grid crop {i}; source cell {cw}x{ch}; common canvas {target[0]}x{target[1]}; no per-pose fitting',
                                    input_sha256=source_sha, output_sha256=sha))
    # Local processing is observed; the generator's identity/prompt/receipt are
    # not. Do not invent a GenerationEvent or hash a specification as a prompt.
    metadata = {'sheet_derivation': dict(
        policy='declared-alpha-grid-v1', source_sha256=source_sha,
        original_output_sha256=list(dict.fromkeys(originals)), output_asset_ids=ids,
        columns=columns, rows=rows, transformations=transformations, source_framing=[c["source_framing"] for c in checks],
        provider_execution_verified=False, generation_attribution='unknown')}
    feedback = loop.submit(project, run_id, revision_id, ids,
                           parent_revision_id=parent_revision_id, feedback_id=feedback_id,
                           generation_metadata=metadata)
    return dict(status='submitted', source_sha256=source_sha, frame_asset_ids=ids,
                feedback=feedback, animation=get(project, run_id))


def get(project, run_id):
    run = loop.get(project, run_id)
    generation = tasks.compile_inputs(project, run['task_id'])
    return dict(run=run, eligibility=loop.eligibility(project, run_id),
                generation=generation,
                training_required=False, provider_dispatch=False,
                next_action=_next(run, len(generation['spec']['timing']['holds'])))


def export(project, run_id):
    gate = loop.eligibility(project, run_id)
    if not gate['eligible']:
        raise InvalidInput('Output policy is not satisfied: ' + '; '.join(gate['reasons']))
    bundle = loop.revision_get(project, gate['revision_id'])
    revision = bundle['revision']
    spec = tasks.get(project, revision['task_id'])['spec']
    con = S.connect(project)
    try:
        bindings = [S.get(con, 'assets', aid)[0] for aid in revision['frame_asset_ids']]
    finally:
        con.close()
    # Content-addressed destination cannot traverse based on caller names.
    destination = Path(project) / 'animation-exports' / _hash([run_id, gate['revision_id'], gate['evidence_digest']])
    destination.mkdir(parents=True, exist_ok=True)
    files, frames = [], []
    for i, binding in enumerate(bindings):
        raw = S.blob_path(project, binding['byte_sha256']).read_bytes()
        frames.append(load_native_image(raw))
        name = f'frame-{i:03d}.png'
        _publish(destination / name, raw)
        files.append(dict(file=name, sha256=hashlib.sha256(raw).hexdigest()))
    width = spec['canvas']['width'] * len(frames)
    if width > 32768:
        raise InvalidInput('Export strip exceeds supported width')
    sheet = Image.new('RGBA', (width, spec['canvas']['height']))
    for i, frame in enumerate(frames):
        sheet.paste(frame, (i * frame.width, 0))
    encoded = io.BytesIO(); sheet.save(encoded, format='PNG')
    _publish(destination / 'spritesheet.png', encoded.getvalue())
    files.append(dict(file='spritesheet.png', sha256=hashlib.sha256(encoded.getvalue()).hexdigest()))
    manifest = dict(schema_version='framebound-animation-1.0', run_id=run_id,
                    revision_id=gate['revision_id'], canvas=spec['canvas'], timing=spec['timing'],
                    loop=spec['loop'], files=files, eligibility=gate,
                    creative_status=gate['creative_status'], animation_quality_verified=False)
    _publish(destination / 'manifest.json', json.dumps(manifest, sort_keys=True, indent=2).encode())
    return dict(destination=str(destination.resolve()), manifest=manifest,
                manifest_path=str((destination / 'manifest.json').resolve()))


def _publish(path, raw):
    # Publish a complete file without replacing an existing immutable artifact.
    # A crashed writer leaves only an unreferenced temporary, never a torn output.
    fd, temporary = tempfile.mkstemp(prefix='.publishing-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise S.ConflictError('Immutable animation export differs from recorded output')
    finally:
        Path(temporary).unlink(missing_ok=True)
