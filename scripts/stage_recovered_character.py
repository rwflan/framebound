"""Assess a retained authorized recovery without silently accepting its artwork."""
import argparse
import json
from pathlib import Path
from PIL import Image
from scripts.build_movement_demo import save
from scripts.build_individual_demo import decode
from scripts.refine_character_demo import load_config,initialize,safe_observe,calibrated_scale
from framebound.v3.character_consistency import image_digest,evaluate_frame,digest


def stage(root,state_path,frame_id,operation):
    config,brief,manifest,public=load_config(root);policy=initialize(root);state=json.loads(state_path.read_text())
    folder=root/'private'/operation;link=json.loads((folder/'recovery.json').read_text());receipt=json.loads((folder/'receipt.json').read_text());raw=(folder/'response.json').read_bytes()
    import hashlib
    if receipt['response_sha256']!=hashlib.sha256(raw).hexdigest():raise ValueError('Recovery receipt digest mismatch')
    parent=root/'private'/link['recovery_of']/'request.json'
    if not parent.exists() or link.get('parent_request_sha256')!=hashlib.sha256(parent.read_bytes()).hexdigest():raise ValueError('Recovery parent commitment mismatch')
    record=state['frames'][frame_id]
    blocked=record.get('blocked_generation_operation')
    if blocked!=link['recovery_of'] and link['recovery_of'] not in record.get('historical_unknown_operations',[]):raise ValueError('Recovery does not match blocked frame')
    history=record.setdefault('historical_unknown_operations',[])
    if link['recovery_of'] not in history:history.append(link['recovery_of'])
    record.pop('blocked_generation_operation',None);record['recovered_by']=operation
    try:native,source_gate=decode(raw,brief.get('minimum_subject_span',1100))
    except ValueError as error:
        record.setdefault('recovery_candidates',[]).append(dict(operation=operation,recovery_of=link['recovery_of'],intake_rejected=str(error)))
        record['recovery_candidate_status']='intake_rejected';state['policy_sha256']=digest(policy.model_dump(mode='json'));save(state_path,state)
        print(frame_id,'provider recovery complete; artwork rejected at intake:',str(error),flush=True)
        return state
    image=Image.new('RGBA',tuple(manifest['canvas']));image.alpha_composite(native,((image.width-native.width)//2,image.height-native.height))
    path=root/'private'/(operation+'-frame.png');image.save(path)
    record=state['frames'][frame_id]
    blocked=record.get('blocked_generation_operation')
    if blocked!=link['recovery_of'] and link['recovery_of'] not in record.get('historical_unknown_operations',[]):raise ValueError('Recovery does not match blocked frame')
    history=record.setdefault('historical_unknown_operations',[])
    if link['recovery_of'] not in history:history.append(link['recovery_of'])
    record.pop('blocked_generation_operation',None);record['recovered_by']=operation
    record.setdefault('recovery_candidates',[]).append(dict(operation=operation,image=str(path),source_framing=source_gate,recovery_of=link['recovery_of']))
    save(state_path,state)
    if source_gate['framing']['eligible']:
        reference=Image.open(config['master_image']).convert('RGBA');obs=safe_observe(root,frame_id,image,reference,config,phase='authorized-recovery-'+config['policy_version']);scale=calibrated_scale(policy,obs,1920/native.height)
        report=evaluate_frame(policy,obs,image_sha256=image_digest(image),frame_id=frame_id,pixel_scale=scale)
        candidate=dict(image=str(path),image_sha256=image_digest(image),observation=obs.model_dump(mode='json'),report=report,source_framing=source_gate,pixel_scale=scale,format_scale=1920/native.height,recovery_of=link['recovery_of'],operation=operation,attempts=[],historical_unknown_operations=history,
                       render_lineage=dict(pristine_sha256=config['pristine_render_sha256'],current_sha256=image_digest(image),recursive_depth=0,scope='whole_frame',parent_sha256s=[record['image_sha256']]))
        # A replacement is a draft. Publication must independently pass all gates.
        state['frames'][frame_id]=candidate
        print(frame_id,'assessed',[(i['code'],i['feature']) for i in report['issues']],flush=True)
    else:print(frame_id,'recovered response; original source framing rejected',source_gate['framing']['reasons'],flush=True)
    state['policy_sha256']=digest(policy.model_dump(mode='json'));save(state_path,state)
    return state


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True,type=Path);p.add_argument('--state',required=True,type=Path);p.add_argument('--frame',required=True);p.add_argument('--operation',required=True);a=p.parse_args();stage(a.root,a.state,a.frame,a.operation)
