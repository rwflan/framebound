"""Frozen, scope-enforced specialist requests. No embedded general-purpose model."""
import json
from PIL import Image
from .. import domain as D,storage as S
from ..media.canonical import load_native_image
from .animation_context import digest,image_in,resolve_in
from .errors import InvalidInput


def compile_redraw(project,op,plan,context):
    from .briefs import compile_reference_brief,load_compiled_brief
    if not plan.policy.generation_allowed or 'scoped_redraw' not in plan.policy.operators:
        raise InvalidInput('specialist generation is not approved')
    if not any(context['allowed_mask'][op.slot]):raise InvalidInput('redraw has no approved editable pixels')
    standard=compile_reference_brief(project,plan.contract_revision_id,op.slot)
    cb=load_compiled_brief(project,standard['compiled_brief_id'])
    bundle=dict(cb.brief)
    bundle['automatic_operation_id']=op.id
    bundle['instruction']+='\nRepair the measured fault under the attached source and control masks. '+op.target_constraint_id+'. '
    bundle['instruction']+='Editable and protected images are controls; exterior/protected pixels are restored by the framework after generation.'
    bundle['repair_controls']={'source_asset_id':op.input_asset_id,'compiled_plan_id':plan.id,'scope_sha256':op.scope_sha256,
        'editable_mask_asset_id':plan.controls[op.slot].editable_mask_asset_id,'protected_mask_asset_id':plan.controls[op.slot].protected_mask_asset_id}
    sha=digest(bundle)
    # CompiledBrief digests use the existing canonical JSON convention.
    import hashlib
    sha=hashlib.sha256(json.dumps(bundle,sort_keys=True).encode()).hexdigest()
    frozen=cb.model_copy(update={'id':'redraw-brief-'+sha[:24],'brief_digest':sha,'brief':bundle})
    con=S.connect(project)
    try:
        with S.atomic(con):S.stage_identical(con,frozen)
    finally:con.close()
    return {**bundle,'compiled_brief_id':frozen.id}


def validate_job_in(con,project,job,*,sending=False,reservation_included=False):
    oid=job.request_brief.get('automatic_operation_id')
    if not oid:return
    op=D.AuthorizedOperation.model_validate(S.get(con,'authorized_operations',oid)[0])
    run=D.Run.model_validate(S.get(con,'runs',op.run_id)[0])
    rev=D.ClipRevision.model_validate(S.get(con,'clip_revisions',op.input_revision_id)[0])
    contract=D.ClipContractRevision.model_validate(S.get(con,'contract_revisions',rev.contract_revision_id)[0])
    plan,_=resolve_in(con,project,contract)
    if (op.operator!='scoped_redraw' or op.status not in ('reserved','awaiting_provider')
        or run.status not in ('running','awaiting_provider') or run.current_revision_id!=op.input_revision_id
        or plan.id!=op.compiled_plan_id or not plan.policy.generation_allowed
        or job.idempotency_key!=op.id+':redraw' or (sending and op.job_id!=job.id)):
        raise InvalidInput('redraw operation is stale, foreign or outside frozen authority')
    if job.provider!='image' or job.offline!=run.provider_offline:
        raise InvalidInput('redraw job provider/offline authority changed')
    if sending:
        from .clips import compute_evaluation_in
        _,baseline,_=compute_evaluation_in(con,project,rev.id)
        if baseline.evidence_manifest_sha256!=op.input_evidence_sha256:raise InvalidInput('redraw baseline evidence is stale')
        count=0
        for row in con.execute('SELECT data FROM authorized_operations'):
            prior=D.AuthorizedOperation.model_validate_json(row['data'])
            if prior.job_id and D.CompiledAnimationPlan.model_validate(S.get(con,'compiled_animation_plans',prior.compiled_plan_id)[0]).reference_approval_id==plan.reference_approval_id:
                count+=S.get(con,'jobs',prior.job_id)[0].get('dispatch_count',0)
        if (count>plan.policy.max_provider_dispatches if reservation_included else count>=plan.policy.max_provider_dispatches):raise InvalidInput('approved animation provider dispatch grant exhausted')


def progress_redraw(project,op,plan,context):
    from . import jobs as J
    from .auto_repair import _restore_pixels
    con=S.connect(project)
    try:run=D.Run.model_validate(S.get(con,'runs',op.run_id)[0])
    finally:con.close()
    brief=compile_redraw(project,op,plan,context)
    envelope=J.submit_generation(project,brief,[],op.id+':redraw',offline=run.provider_offline,
        max_attempts=min(10,plan.policy.max_provider_dispatches),provider_settings=run.provider_settings or None)
    jid=envelope.artifacts[0]['id']
    con=S.connect(project)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            operation,version=S.get(con,'authorized_operations',op.id);operation=D.AuthorizedOperation.model_validate(operation)
            if operation.job_id not in (None,jid):raise InvalidInput('redraw already has a different job')
            operation.job_id=jid;operation.status='awaiting_provider';S.stage_update(con,'authorized_operations',operation,version)
            current,rv=S.get(con,'runs',run.id);current=D.Run.model_validate(current)
            current.status='awaiting_provider';current.result={'job_id':jid,'operation_id':op.id,'acceptance':'unreviewed'}
            S.stage_update(con,'runs',current,rv)
        job=D.Job.model_validate(S.get(con,'jobs',jid)[0])
        if job.status in (D.JobStatus.FAILED,D.JobStatus.CANCELLED):raise InvalidInput('redraw provider failed: '+str(job.error))
        if job.status!=D.JobStatus.SUCCEEDED:return False
        if not job.output_asset_ids:raise InvalidInput('redraw completed without pixels')
        aid=job.output_asset_ids[-1]
        _,source=image_in(con,project,op.input_asset_id)
        asset=D.Asset.model_validate(S.get(con,'assets',aid)[0])
        raw=S.blob_path(project,asset.byte_sha256).read_bytes()
        try:generated=load_native_image(raw)
        except ValueError:generated=None
    finally:con.close()
    if generated is None or generated.size!=source.size:
        from .animation_context import calibrate_source
        asset=calibrate_source(project,plan.contract_revision_id,aid,'native-'+op.id);aid=asset.id
        generated=load_native_image(S.blob_path(project,asset.byte_sha256))
    if generated.size!=source.size:raise InvalidInput('specialist output differs from approved native canvas')
    output=_restore_pixels(source,generated,context['allowed_mask'][op.slot])
    from .provenance import write_derived
    write_derived(project,op.output_asset_id,output,list(dict.fromkeys([op.input_asset_id,aid,plan.controls[op.slot].baseline_asset_id])),
        {'operator':'scoped_redraw','job_id':jid,'compiled_plan_id':plan.id,'scope_sha256':op.scope_sha256},operation_id=op.id)
    return True
