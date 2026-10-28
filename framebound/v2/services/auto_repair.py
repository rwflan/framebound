"""Durable, bounded native-pixel repair; all authority comes from reviewed controls."""
import hashlib
import json
from pathlib import Path

from filelock import FileLock, Timeout
from PIL import Image
from .. import domain as D, storage as S
from ..media.canonical import canonical_pixels, load_native_image
from .animation_context import digest, image_in, resolve_in
from .errors import InvalidInput

DETERMINISTIC_OPERATORS=('translate','protected_restore')

def _delta(spec):
    return [sum(op.dx for op in spec.ops),sum(op.dy for op in spec.ops)]



def _load(con,table,rid,model):
    data,version=S.get(con,table,rid)
    return model.model_validate(data),version


def derive_policy(project_dir,contract,task=None):
    con=S.connect(project_dir)
    try:return resolve_in(con,project_dir,contract)[0].policy.model_dump()
    finally:con.close()


def compile_plan(project_dir,contract_id):
    con=S.connect(project_dir)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            contract,_=_load(con,'contract_revisions',contract_id,D.ClipContractRevision)
            plan,_=resolve_in(con,project_dir,contract)
            S.stage_identical(con,plan)
        return plan.model_dump()
    finally:con.close()


def _translate_pixels(base,dx,dy):
    out=Image.new('RGBA',base.size)
    # Refuse clipping, including partially transparent edge pixels.
    bbox=base.getchannel('A').getbbox()
    if bbox and (bbox[0]+dx<0 or bbox[1]+dy<0 or bbox[2]+dx>base.width or bbox[3]+dy>base.height):
        raise InvalidInput('translation would clip source pixels')
    out.alpha_composite(base,(dx,dy))
    return out


def _restore_pixels(base,damaged,allowed):
    if base.size!=damaged.size or len(allowed)!=base.width*base.height:
        raise InvalidInput('protected restore needs exact native dimensions and scope')
    bp,dp=base.tobytes(),damaged.tobytes()
    return Image.frombytes('RGBA',base.size,b''.join(dp[i*4:i*4+4] if a else bp[i*4:i*4+4] for i,a in enumerate(allowed)))


def _authorized(project,operation_id,operator):
    if not operation_id:raise InvalidInput('stored authorized operation required; caller masks/budgets confer no authority')
    con=S.connect(project)
    try:
        op,_=_load(con,'authorized_operations',operation_id,D.AuthorizedOperation)
        run,_=_load(con,'runs',op.run_id,D.Run)
        rev,_=_load(con,'clip_revisions',op.input_revision_id,D.ClipRevision)
        contract,_=_load(con,'contract_revisions',rev.contract_revision_id,D.ClipContractRevision)
        plan,context=resolve_in(con,project,contract)
        if (op.operator!=operator or op.compiled_plan_id!=plan.id or op.status not in ('reserved','rendered')
            or run.status!='running' or op.id not in run.operation_ids or run.current_revision_id!=op.input_revision_id
            or op.scope_sha256!=plan.controls[op.slot].scope_sha256):
            raise InvalidInput('stale, foreign or completed automatic operation')
        from .evidence import verify_evidence_in
        ev,_=_load(con,'evaluations',op.input_evaluation_id,D.Evaluation)
        valid,problems=verify_evidence_in(con,project,op.input_revision_id,ev)
        if not valid or ev.evidence_manifest_sha256!=op.input_evidence_sha256:
            raise InvalidInput('operation evidence is stale: '+str(problems))
        return op,plan,context
    finally:con.close()


def _execute(project,op,plan,context):
    con=S.connect(project)
    try:
        _,source=image_in(con,project,op.input_asset_id)
        control=plan.controls[op.slot]
        _,base=image_in(con,project,control.baseline_asset_id,control.baseline_byte_sha256)
        if source.size!=base.size:raise InvalidInput('unsupported native size; explicit source calibration required')
        if op.operator=='translate':
            dx,dy=_delta(op.transform)
            if max(abs(dx),abs(dy))>plan.policy.translation_budget_px:raise InvalidInput('translation exceeds approved budget')
            out=_translate_pixels(source,dx,dy)
        elif op.operator=='protected_restore':
            out=_restore_pixels(base,source,context['allowed_mask'][op.slot])
        else:raise InvalidInput('redraw requires the bounded specialist controller')
        before,after=canonical_pixels(base),canonical_pixels(out)
        allowed=context['allowed_mask'][op.slot]
        if any(before[i*4:i*4+4]!=after[i*4:i*4+4] for i,a in enumerate(allowed) if not a):
            raise InvalidInput('operator changes pixels outside approved support')
    finally:con.close()
    from .provenance import write_derived
    return write_derived(project,op.output_asset_id,out,list(dict.fromkeys([op.input_asset_id,control.baseline_asset_id])),
        {'operator':op.operator,'transform':op.transform.model_dump(),'compiled_plan_id':plan.id,'scope_sha256':op.scope_sha256},operation_id=op.id)


def execute_translate(project_dir,baseline_asset_id,dx,dy,new_asset_id,budget_px=None,*,operation_id=None):
    op,plan,ctx=_authorized(project_dir,operation_id,'translate')
    if (baseline_asset_id,new_asset_id,[dx,dy])!=(op.input_asset_id,op.output_asset_id,_delta(op.transform)):
        raise InvalidInput('caller differs from stored operation')
    return _execute(project_dir,op,plan,ctx)


def execute_protected_restore(project_dir,baseline_asset_id,damaged_asset_id,allowed_mask,new_asset_id,*,operation_id=None):
    op,plan,ctx=_authorized(project_dir,operation_id,'protected_restore')
    if (baseline_asset_id,damaged_asset_id,new_asset_id)!=(plan.controls[op.slot].baseline_asset_id,op.input_asset_id,op.output_asset_id) or allowed_mask!=ctx['allowed_mask'][op.slot]:
        raise InvalidInput('caller differs from stored operation')
    return _execute(project_dir,op,plan,ctx)


def _evaluation(project,revision):
    from . import clips
    env=clips.evaluate(project,revision)
    con=S.connect(project)
    try:return _load(con,'evaluations',env.artifacts[0]['id'],D.Evaluation)[0]
    finally:con.close()


def technically_ready(ev):
    return ev.technical_status==D.TechnicalStatus.PASS and ev.coverage_status==D.CoverageStatus.COMPLETE


def _run_result(run):
    return {'run_id':run.id,'status':run.status,'revision_id':run.current_revision_id,
            'compiled_plan_id':run.compiled_plan_id,'local_attempts_used':run.local_attempts_used,
            'compute_steps_used':run.compute_steps_used,'operation_ids':run.operation_ids,
            'blocker':run.halt_reason,**(run.result or {})}


def get_run(project_dir,run_id):
    con=S.connect(project_dir)
    try:
        run,_=_load(con,'runs',run_id,D.Run)
        if run.kind!='animation':raise InvalidInput('not an animation run')
        return _run_result(run)
    finally:con.close()


def start_run(project_dir,revision_id,idempotency_key=None):
    con=S.connect(project_dir)
    try:
        rev,_=_load(con,'clip_revisions',revision_id,D.ClipRevision)
        contract,_=_load(con,'contract_revisions',rev.contract_revision_id,D.ClipContractRevision)
        plan,_=resolve_in(con,project_dir,contract)
        key=idempotency_key or 'automatic:'+revision_id
        rid='animation-'+digest(key)[:32]
        identity=digest({'revision':rev.model_dump(mode='json'),'plan':plan.id})
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            try:
                old,_=_load(con,'runs',rid,D.Run)
                if old.kind!='animation' or old.input_sha256!=identity:raise S.ConflictError('work key already bound to different inputs')
                return _run_result(old)
            except KeyError:pass
            S.stage_identical(con,plan)
            run=D.Run(id=rid,kind='animation',baseline_revision_id=revision_id,current_revision_id=revision_id,
                compiled_plan_id=plan.id,idempotency_key=key,input_sha256=identity)
            S.stage(con,run)
        return _run_result(run)
    finally:con.close()


def _centroid(image):
    points=[(i%image.width,i//image.width) for i,a in enumerate(image.getchannel('A').tobytes()) if a>=128]
    if not points:raise InvalidInput('empty silhouette has no measurable translation')
    return tuple(sum(p[i] for p in points)/len(points) for i in (0,1))


def _choose(con,project,rev,contract,plan,ev):
    by_id={c.id:c for c in contract.constraints}
    for result in sorted(ev.results,key=lambda r:(r.constraint_id,r.scope)):
        # ERROR/UNMEASURED must never be treated as a measurable repair target.
        if result.outcome!=D.CheckOutcome.FAIL:continue
        constraint=by_id.get(result.constraint_id)
        if constraint is None:continue
        if constraint.check=='repair_protection':
            operator='protected_restore'
            from .animation_context import resolve_in
            _,ctx=resolve_in(con,project,contract)
            slots=[]
            for slot,fid in enumerate(rev.frame_instance_ids):
                fi,_=_load(con,'frame_instances',fid,D.FrameInstance)
                _,image=image_in(con,project,fi.asset_id)
                raw=canonical_pixels(image);base=ctx['baseline'][slot]
                if len(raw)!=len(base):continue
                if any(base[i*4:i*4+4]!=raw[i*4:i*4+4] for i,a in enumerate(ctx['allowed_mask'][slot]) if not a):slots.append(slot)
            if not slots:continue
            slot=slots[0];delta=[0,0]
        elif constraint.check=='native_registration' and result.scope.startswith('slot '):
            operator='translate';slot=int(result.scope.split()[1])
            fi,_=_load(con,'frame_instances',rev.frame_instance_ids[slot],D.FrameInstance)
            _,source=image_in(con,project,fi.asset_id)
            _,reference=image_in(con,project,plan.controls[slot].baseline_asset_id)
            if source.size!=reference.size:continue
            a,b=_centroid(source),_centroid(reference)
            raw=[b[i]-a[i] for i in (0,1)]
            if any(abs(v-round(v))>1e-8 for v in raw):continue
            delta=[round(v) for v in raw]
            if delta==[0,0] or max(map(abs,delta))>plan.policy.translation_budget_px:continue
        else:continue
        if operator not in plan.policy.operators:continue
        fi,_=_load(con,'frame_instances',rev.frame_instance_ids[slot],D.FrameInstance)
        return result,slot,fi,operator,delta
    return None


def _checkpoint(name):
    """Crash-test barrier. Production callers cannot supply execution hooks."""


def step_run(project_dir,run_id):
    try:
        with FileLock(str(Path(project_dir)/'.animation-worker.lock'),timeout=0):
            return _step_locked(project_dir,run_id)
    except Timeout:
        return {'run_id':run_id,'status':'busy','blocker':'another local animation worker owns this project'}


def _step_locked(project,run_id):
    from . import clips,packets
    from .authz import Actor
    con=S.connect(project)
    try:
        run,version=_load(con,'runs',run_id,D.Run)
        if run.kind!='animation':raise InvalidInput('not an animation run')
        if run.status!='running':return _run_result(run)
        rev,_=_load(con,'clip_revisions',run.current_revision_id,D.ClipRevision)
        contract,_=_load(con,'contract_revisions',rev.contract_revision_id,D.ClipContractRevision)
        plan,context=resolve_in(con,project,contract)
        if plan.id!=run.compiled_plan_id:raise InvalidInput('compiled authority changed')
        pending=None
        for oid in run.operation_ids:
            operation,_=_load(con,'authorized_operations',oid,D.AuthorizedOperation)
            if operation.status not in ('committed','failed'):pending=operation;break
    finally:con.close()
    ev=_evaluation(project,rev.id)
    con=S.connect(project)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            run,version=_load(con,'runs',run_id,D.Run)
            if technically_ready(ev):
                _,current_ev,_=clips.compute_evaluation_in(con,project,rev.id)
                if current_ev.evidence_manifest_sha256!=ev.evidence_manifest_sha256:
                    raise InvalidInput('evidence changed before ready comparison')
                packet_id='packet-'+run.id
                packets.create_packet(project,packet_id,rev.id,ev.id,'Automatic repair comparison',
                    run.baseline_revision_id if run.baseline_revision_id!=rev.id else None,connection=con)
                run.status='technically_ready';run.result={'evaluation_id':ev.id,'packet_id':packet_id,'acceptance':'unreviewed'}
                S.stage_update(con,'runs',run,version)
                return _run_result(run)
            if pending is None:
                choice=_choose(con,project,rev,contract,plan,ev)
                if choice is None:
                    run.status='blocked';run.halt_reason='no authorized deterministic operator for measured faults; unsupported or unmeasured checks need explicit input'
                    run.result={'evaluation_id':ev.id,'faults':[r.model_dump(mode='json') for r in ev.results if r.outcome!='pass']}
                    S.stage_update(con,'runs',run,version);return _run_result(run)
                result,slot,fi,operator,delta=choice
                consumed=[D.AuthorizedOperation.model_validate_json(r['data']) for r in con.execute('SELECT data FROM authorized_operations')]
                used=[o for o in consumed if o.compiled_plan_id==plan.id and o.slot==slot]
                if len(used)>=plan.policy.max_local_attempts or sum(o.compiled_plan_id==plan.id for o in consumed)>=plan.policy.max_compute_steps:
                    run.status='blocked';run.halt_reason='approved stable-target attempt or compute grant exhausted'
                    S.stage_update(con,'runs',run,version);return _run_result(run)
                # Composed translation is bounded across all selected ancestors.
                ancestry={rev.id};cursor=rev
                while cursor.parent_revision_id:
                    if cursor.parent_revision_id in ancestry:raise InvalidInput('cyclic revision ancestry')
                    ancestry.add(cursor.parent_revision_id);cursor,_=_load(con,'clip_revisions',cursor.parent_revision_id,D.ClipRevision)
                total=[delta[i]+sum(_delta(o.transform)[i] for o in consumed if o.slot==slot and o.output_revision_id in ancestry and o.status=='committed') for i in (0,1)]
                if max(map(abs,total))>plan.policy.translation_budget_px:
                    run.status='blocked';run.halt_reason='composed translation exceeds approved budget'
                    S.stage_update(con,'runs',run,version);return _run_result(run)
                identity=digest([plan.id,ev.evidence_manifest_sha256,result.constraint_id,result.scope,slot,operator])[:32]
                oid='operation-'+identity;taskid='task-'+identity
                event=D.ReviewEvent(id='machine-'+identity,actor_type='system',actor_id='automatic-repair',action='machine_fault',
                    clip_revision_id=rev.id,category=result.constraint_id,note=result.reason)
                S.stage_identical(con,event,('created_at',))
                task=D.CorrectionTask(id=taskid,source_issue_event_id=event.id,baseline_revision_id=rev.id,baseline_evaluation_id=ev.id,
                    origin='machine',repair_operator=operator,desired_outcome=result.reason,scope=json.dumps({'slot':slot,'constraint_id':result.constraint_id,'scope':result.scope}),status=D.CorrectionStatus.ATTEMPTING)
                if con.execute('SELECT id FROM authorized_operations WHERE id=?',(oid,)).fetchone():
                    run.status='blocked';run.halt_reason='identical fault already attempted under the stable target grant'
                    S.stage_update(con,'runs',run,version);return _run_result(run)
                S.stage_identical(con,task,('created_at',))
                pending=D.AuthorizedOperation(id=oid,run_id=run.id,compiled_plan_id=plan.id,input_revision_id=rev.id,
                    input_evaluation_id=ev.id,input_evidence_sha256=ev.evidence_manifest_sha256,target_constraint_id=result.constraint_id,
                    task_id=taskid,slot=slot,operator=operator,input_asset_id=fi.asset_id,output_asset_id='asset-'+identity,
                    output_revision_id='revision-'+identity,scope_sha256=plan.controls[slot].scope_sha256,
                    transform=D.TransformSpec(ops=[D.TransformOp(dx=delta[0],dy=delta[1])]))
                S.stage(con,pending);run.operation_ids.append(oid);run.local_attempts_used+=1;run.compute_steps_used+=1
                S.stage_update(con,'runs',run,version)
    finally:con.close()
    _checkpoint('reserved')
    try:
        op,plan,ctx=_authorized(project,pending.id,pending.operator)
        _execute(project,op,plan,ctx)
        _checkpoint('rendered')
        con=S.connect(project)
        try:
            exists=con.execute('SELECT id FROM clip_revisions WHERE id=?',(op.output_revision_id,)).fetchone()
        finally:con.close()
        if not exists:
            clips.register_candidate(project,op.input_revision_id,op.output_revision_id,{op.slot:op.output_asset_id},'automatic:'+op.operator)
        candidate=_evaluation(project,op.output_revision_id)
        _checkpoint('evaluated')
        base={(r.constraint_id,r.scope):r for r in ev.results};new={(r.constraint_id,r.scope):r for r in candidate.results}
        regressions=[k for k,r in base.items() if r.outcome=='pass' and new[k].outcome!='pass']
        improved=[k for k,r in base.items() if r.outcome=='fail' and new[k].outcome=='pass']
        progressed=bool(improved) and not regressions and all(new[k].outcome not in ('error','unmeasured') for k,r in base.items() if r.outcome in ('pass','fail'))
        con=S.connect(project)
        try:
            with S.atomic(con):
                con.execute('BEGIN IMMEDIATE')
                run,version=_load(con,'runs',run_id,D.Run)
                current,_=resolve_in(con,project,contract)
                _,current_ev,_=clips.compute_evaluation_in(con,project,op.input_revision_id)
                if current.id!=plan.id or current_ev.evidence_manifest_sha256!=op.input_evidence_sha256 or run.current_revision_id!=op.input_revision_id:
                    raise InvalidInput('authority or baseline changed before automatic publication')
                stored,ov=_load(con,'authorized_operations',op.id,D.AuthorizedOperation)
                stored.status='committed' if progressed else 'failed';stored.evaluation_id=candidate.id
                stored.error=None if progressed else f'no measured progress or regression: {regressions}'
                S.stage_update(con,'authorized_operations',stored,ov)
                attempt=D.Attempt(id='attempt-'+op.id,baseline_revision_id=op.input_revision_id,brief_id=plan.id,provider='deterministic',
                    request_sha256=digest(op.model_dump(mode='json')),candidate_asset_ids=[op.output_asset_id],cost='zero provider dispatches',
                    targeted_issue_ids=[op.task_id],result='internal_progress' if progressed else 'no_progress')
                S.stage_identical(con,attempt)
                task,tv=_load(con,'correction_tasks',op.task_id,D.CorrectionTask)
                task.attempt_ids=[attempt.id];task.status=D.CorrectionStatus.RESOLVED if progressed else D.CorrectionStatus.BLOCKED
                S.stage_update(con,'correction_tasks',task,tv)
                if progressed:run.current_revision_id=op.output_revision_id
                else:run.status='blocked';run.halt_reason=stored.error
                run.result={'evaluation_id':candidate.id,'internal_progress':progressed,'acceptance':'unreviewed'}
                S.stage_update(con,'runs',run,version)
        finally:con.close()
        _checkpoint('committed')
        return get_run(project,run_id)
    except InvalidInput as exc:
        con=S.connect(project)
        try:
            with S.atomic(con):
                run,version=_load(con,'runs',run_id,D.Run);run.status='blocked';run.halt_reason=str(exc)
                S.stage_update(con,'runs',run,version)
                op,ov=_load(con,'authorized_operations',pending.id,D.AuthorizedOperation);op.status='failed';op.error=str(exc)
                S.stage_update(con,'authorized_operations',op,ov)
        finally:con.close()
        return get_run(project,run_id)


def open_machine_tasks(project_dir,revision_id):
    result=run_automatic(project_dir,revision_id)
    con=S.connect(project_dir)
    try:return [json.loads(r['data']) for r in con.execute('SELECT data FROM correction_tasks') if json.loads(r['data']).get('origin')=='machine']
    finally:con.close()


def construct_redraw_request(project_dir,task_id,slot,*,operation_id=None):
    if not operation_id:raise InvalidInput('redraw requires a stored bounded authorized operation')
    raise InvalidInput('scoped specialist execution is not enabled for this operation')


def run_automatic(project_dir,revision_id,idempotency_key=None):
    try:result=start_run(project_dir,revision_id,idempotency_key)
    except InvalidInput as exc:return {'status':'blocked','revision_id':revision_id,'blocker':str(exc)}
    # One call may finish a bounded local run. Every step is independently resumable.
    for _ in range(257):
        if result['status']!='running':return result
        result=step_run(project_dir,result['run_id'])
    raise InvalidInput('automatic compute hard ceiling reached')
