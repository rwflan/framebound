"""Read-only approved controls shared by evaluation and automatic execution."""
import hashlib
import json

from .. import domain as D, storage as S
from ..media.canonical import load_native_image, canonical_pixels
from .errors import InvalidInput


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def image_in(con, project, aid, expected=None):
    asset=D.Asset.model_validate(S.get(con,'assets',aid)[0])
    raw=S.blob_path(project,asset.byte_sha256).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=asset.byte_sha256 or (expected and expected!=asset.byte_sha256):
        raise InvalidInput(f'approved control bytes changed: {aid}')
    return asset,load_native_image(raw)


def resolve_in(con, project, contract):
    from .approvals import approval_for_contract
    guide=D.MotionGuide.model_validate(S.get(con,'motion_guides',contract.references['motion_guide_revision'])[0])
    if guide.repair_policy is None:
        raise InvalidInput('contract guide has no human-approved automatic repair policy')
    approval=approval_for_contract(project,contract,con)
    policy=contract.repair_policy or guide.repair_policy
    ceiling=guide.repair_policy
    if (not set(policy.operators)<=set(ceiling.operators)
        or policy.translation_budget_px>ceiling.translation_budget_px
        or policy.max_local_attempts>ceiling.max_local_attempts
        or policy.max_compute_steps>ceiling.max_compute_steps
        or policy.max_provider_dispatches>ceiling.max_provider_dispatches
        or (policy.generation_allowed and not ceiling.generation_allowed)):
        raise InvalidInput('contract cannot widen the approved repair policy')
    policy=policy.model_copy(update={'translation_budget_px':min(policy.translation_budget_px,
                                    contract.allowed_transforms.rigid_translation_budget_px)})
    controls=[];baseline=[];allowed=[];protected=[]
    by_phase={e.phase:e for e in guide.entries}
    w,h=contract.canvas.width,contract.canvas.height
    for phase in contract.phase_schedule:
        entry=by_phase.get(phase.phase)
        if entry is None:raise InvalidInput(f'missing approved phase {phase.phase}')
        asset,image=image_in(con,project,entry.asset_id,approval.asset_hashes.get(entry.asset_id))
        if image.size!=(w,h):raise InvalidInput('approved phase dimensions differ from native canvas')
        if entry.asset_id not in approval.asset_hashes:raise InvalidInput('phase absent from approval')
        masks=[];hashes=[]
        for aid,default in ((entry.editable_mask_asset_id,0),(entry.protected_mask_asset_id,0)):
            if aid:
                if aid not in approval.asset_hashes:raise InvalidInput('control mask absent from human approval')
                ma,mi=image_in(con,project,aid,approval.asset_hashes[aid])
                if mi.size!=(w,h):raise InvalidInput('control mask differs from native canvas')
                masks.append(bytes(int(v>127) for v in mi.convert('L').tobytes()));hashes.append(ma.byte_sha256)
            else:masks.append(bytes([default])*(w*h));hashes.append(None)
        effective=bytes(a and not p for a,p in zip(*masks))
        scope=hashlib.sha256(effective+masks[1]+canonical_pixels(image)).hexdigest()
        controls.append(D.FrameControl(slot=phase.slot,phase=phase.phase,baseline_asset_id=asset.id,
            baseline_byte_sha256=asset.byte_sha256,editable_mask_asset_id=entry.editable_mask_asset_id,
            editable_mask_byte_sha256=hashes[0],protected_mask_asset_id=entry.protected_mask_asset_id,
            protected_mask_byte_sha256=hashes[1],scope_sha256=scope))
        baseline.append(canonical_pixels(image));allowed.append(effective);protected.append(masks[1])
    from ..checks.evaluate import _matrix
    inputs={'contract':contract.model_dump(mode='json'),'guide':guide.model_dump(mode='json'),
            'approval':approval.model_dump(mode='json'),'controls':[c.model_dump() for c in controls]}
    identity=digest(inputs)
    plan=D.CompiledAnimationPlan(id='animation-plan-'+identity[:32],contract_revision_id=contract.id,
        reference_approval_id=approval.id,inputs_sha256=identity,policy=policy,
        source_calibration=guide.source_calibration,controls=controls,
        required_matrix=[list(x) for x in _matrix(contract)])
    context={'baseline':baseline,'allowed_mask':allowed,'protected_mask':protected,
        'repaired_slots':list(range(len(controls))),
        'baseline_byte_sha256':[c.baseline_byte_sha256 for c in controls],
        'support_id':identity,'task_id':None,'mask_id':None}
    return plan,context


def calibrate_source(project, contract_id, source_asset_id, output_asset_id):
    """One approved family crop/scale; never fit individual poses to their bounds."""
    import io
    from PIL import Image,ImageOps
    con=S.connect(project)
    try:
        contract=D.ClipContractRevision.model_validate(S.get(con,'contract_revisions',contract_id)[0])
        plan,_=resolve_in(con,project,contract)
        calibration=plan.source_calibration
        if calibration is None:raise InvalidInput('no approved source calibration')
        asset=D.Asset.model_validate(S.get(con,'assets',source_asset_id)[0])
        raw=S.blob_path(project,asset.byte_sha256).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=asset.byte_sha256:raise InvalidInput('source bytes changed')
        image=Image.open(io.BytesIO(raw))
        if image.format not in calibration.formats or image.size!=(calibration.source_width,calibration.source_height):
            raise InvalidInput('source format or dimensions outside fixed calibration')
        if image.getexif().get(274,1)!=1:raise InvalidInput('oriented sources need explicit preprocessing')
        image=ImageOps.exif_transpose(image).convert('RGBA').crop(tuple(calibration.crop))
        target=(contract.canvas.width,contract.canvas.height)
        if image.width*target[1]!=image.height*target[0]:raise InvalidInput('calibration must use uniform scale')
        image=image.resize(target,Image.Resampling.NEAREST)
    finally:con.close()
    from .provenance import write_derived
    return write_derived(project,output_asset_id,image,[source_asset_id],
        {'operator':'source_calibration','compiled_plan_id':plan.id,'calibration':calibration.model_dump()})
