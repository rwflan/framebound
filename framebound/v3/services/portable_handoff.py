"""Self-contained continuation for a parent agent without project/MCP access."""
import io
import json
from pathlib import Path
import zipfile

from pydantic import Field,model_validator

from ...v2 import storage as S
from ...v2.domain import Strict
from ...v2.services.assets import import_asset
from ...v2.services.errors import InvalidInput
from . import loop,tasks,interventions as I
from ..evaluate import digest


class ResponseFrame(Strict):
    asset_id: str | None = None
    file: str | None = None
    rights: str = 'unknown'
    source_kind: str = Field(default='generated',pattern='^(original|procedural|generated|derived|imported)$')

    @model_validator(mode='after')
    def one_input(self):
        if bool(self.asset_id)==bool(self.file):raise ValueError('each response frame names an unchanged asset ID or a new local PNG file')
        return self


class Response(Strict):
    revision_id: str = Field(min_length=1,max_length=90)
    frames: list[ResponseFrame] = Field(min_length=1,max_length=512)
    generation_metadata: dict | None = None


def archive(project,feedback_id):
    con=loop.connect(project)
    try:
        con.execute('BEGIN')
        bundle=loop.get_in(con,'agent_feedback',feedback_id);run=loop.get_in(con,'agent_runs',bundle['run_id'])
        if run.get('feedback_id',f"feedback:{run['current_revision_id']}")!=feedback_id or run['current_revision_id']!=bundle['baseline_revision_id']:
            raise S.StaleRevisionError('saved instructions are stale; fetch/rebase current feedback before packaging')
        task_ids={bundle['task_id'],run['task_id']};specs={tid:tasks._get(con,tid).model_dump(mode='json',exclude_unset=True) for tid in task_ids}
        revision_ids={bundle['baseline_revision_id']}
        if run.get('edit_baseline_revision_id'):revision_ids.add(run['edit_baseline_revision_id'])
        revisions={rid:loop.get_in(con,'agent_clip_revisions',rid) for rid in revision_ids}
        aids={aid for rev in revisions.values() for aid in rev['frame_asset_ids']}
        for task in specs.values():
            aids.update(i['asset_id'] for i in task['spec']['inputs'])
            aids.update((task['spec'].get('source_correspondence') or {}).get('frame_asset_ids',[]))
        assets={};blobs={};total=0
        for aid in sorted(aids):
            asset,_=S.get(con,'assets',aid);path=S.blob_path(project,asset['byte_sha256'])
            if not path.is_file() or S.sha256_bytes(path.read_bytes())!=asset['byte_sha256']:
                raise InvalidInput(f'cannot package unavailable evidence asset {aid}; recover it first')
            rel=f"assets/{asset['byte_sha256']}.png"
            assets[aid]=dict(record=asset,file=rel)
            if rel not in blobs:
                data=path.read_bytes();total+=len(data)
                if total>134217728:raise InvalidInput('portable handoff exceeds the 128 MiB pixel budget; use authorized project access instead')
                blobs[rel]=data
        evaluation=loop.get_in(con,'agent_evaluations',bundle['evaluation_id'])
        # Whitelist revision fields: generation metadata and hidden provider settings are not part of a handoff.
        portable_revisions={rid:{k:r[k] for k in ('id','task_id','frame_asset_ids','frame_instance_ids','parent_revision_id')} for rid,r in revisions.items()}
        manifest=dict(format='framebound-handoff-1.0',feedback=bundle,feedback_digest=digest(bundle),
            task_specs=specs,evaluation=evaluation,revisions=portable_revisions,assets=assets,
            current_task_id=run['task_id'],limits=run['limits'],remaining_submissions=run['limits']['max_submissions']-len(run['submission_ids']),
            import_operation='agent-handoff-import',rights_semantics='Asset origin/rights records are retained; this transfer grants neither provider execution authority nor training rights.')
        text=I.render(bundle,portable=True)
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json',json.dumps(manifest,sort_keys=True,indent=2))
            archive.writestr('instructions.txt',text)
            for rel,data in blobs.items():archive.writestr(rel,data)
        return output.getvalue()
    finally:con.close()


def import_response(project,manifest_path,response_path):
    manifest_path=Path(manifest_path).resolve();manifest=json.loads(manifest_path.read_text())
    if manifest.get('format')!='framebound-handoff-1.0':raise InvalidInput('unsupported portable handoff format')
    response_path=Path(response_path).resolve();response=Response.model_validate_json(response_path.read_text())
    bundle=manifest['feedback'];con=loop.connect(project)
    try:
        saved=loop.get_in(con,'agent_feedback',bundle['id']);run=loop.get_in(con,'agent_runs',bundle['run_id'])
        if digest(saved)!=manifest.get('feedback_digest') or saved!=bundle:raise InvalidInput('portable feedback differs from the saved durable bundle')
        existing=con.execute('SELECT data FROM agent_clip_revisions WHERE id=?',(response.revision_id,)).fetchone()
        replay=json.loads(existing['data']) if existing else None
        is_replay=bool(replay and replay['run_id']==run['id'] and replay.get('targeted_feedback_id')==bundle['id'])
        if not is_replay and (run['current_revision_id']!=bundle['baseline_revision_id'] or run.get('feedback_id',f"feedback:{run['current_revision_id']}")!=bundle['id']):
            raise S.StaleRevisionError('portable instructions are stale; export a current handoff instead of silently retargeting')
        if not is_replay and run['lifecycle'] in {'cancelled','blocked'}:raise InvalidInput('run is stopped; portable import cannot override its limits')
        task=tasks._get(con,replay['task_id'] if is_replay else run['task_id'])
        for tid,record in manifest['task_specs'].items():
            if tasks._get(con,tid).model_dump(mode='json',exclude_unset=True)!=record:raise InvalidInput('portable task specification differs from frozen project state')
    finally:con.close()
    if len(response.frames)!=len(task.spec.timing.holds):raise InvalidInput('portable response must contain the complete ordered native frame list')
    assets=[];imports=[]
    for index,frame in enumerate(response.frames):
        if frame.asset_id:
            if frame.asset_id not in manifest['assets']:raise InvalidInput('unchanged asset ID was not included in this handoff')
            assets.append(frame.asset_id);continue
        image=(response_path.parent/frame.file).resolve()
        if not image.is_relative_to(response_path.parent) or not image.is_file():raise InvalidInput('response frame file is missing or outside the returned directory')
        aid='handoff-'+digest(dict(revision=response.revision_id,slot=index,sha=S.sha256_bytes(image.read_bytes())))[:24]
        imports.append((image,aid,frame.source_kind,frame.rights));assets.append(aid)
    for path,aid,kind,rights in imports:import_asset(project,str(path),aid,source_kind=kind,rights=rights)
    return loop.submit(project,run['id'],response.revision_id,assets,parent_revision_id=bundle['baseline_revision_id'],
                       feedback_id=bundle['id'],generation_metadata=response.generation_metadata)


def export_archive(project,feedback_id,destination):
    data=archive(project,feedback_id);path=Path(destination)
    with path.open('xb') as output:output.write(data)
    return dict(ok=True,archive=str(path.resolve()),feedback_id=feedback_id)
