"""Generate a bounded item correction while preserving all pixels outside its ROI.

Native generated patches are only downsampled, never enlarged. Reassembly does
not imply semantic acceptance; the normal observation and transition gates run
again against the resulting pixels.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
from PIL import Image,ImageOps
import numpy as np
from framebound.v3.character_consistency import Observation,measurements,image_digest,repair_plan,evaluate_frame,digest
from framebound.v3.intake import keyed,framing
from scripts.build_movement_demo import send,save,extract_image
from scripts.refine_character_demo import initialize,load_config,generation_png,safe_observe,calibrated_scale


def patch_box(image,points,pad):
    xs=[p[0]*image.width/1000 for p in points];ys=[p[1]*image.height/1000 for p in points]
    cx,cy=(min(xs)+max(xs))/2,(min(ys)+max(ys))/2
    width=max(xs)-min(xs)+2*pad;height=max(ys)-min(ys)+2*pad
    width=max(width,height*1.5);height=width/1.5
    if width>image.width or height>image.height:raise ValueError('No bounded patch fits the source')
    x=max(0,min(image.width-int(width),int(cx-width/2)));y=max(0,min(image.height-int(height),int(cy-height/2)))
    return (x,y,x+int(width),y+int(height))


def assemble(source,patch,box):
    width,height=box[2]-box[0],box[3]-box[1]
    if patch.width<width or patch.height<height:raise ValueError('Patch lacks native resolution; never upscale')
    if abs(patch.width/patch.height-width/height)>.015:raise ValueError('Patch aspect differs from requested region')
    out=source.copy();out.paste(patch.resize((width,height),Image.Resampling.LANCZOS),box[:2]);return out


def extract_patch(native):
    # This is an internal crop with intentional arm/lash crossings at its edge,
    # never a standalone intake or a source-framing acceptance. Reuse the same
    # declared-key unmatting operator in a temporary extraction surround, then
    # discard that surround. The complete reconstructed source is checked later.
    rgb=np.asarray(native.convert('RGB')).astype(int)
    reserved=(np.max(np.abs(rgb-np.array([255,0,255])),axis=2)<=70)
    if reserved.mean()<.1:raise ValueError('Patch lacks the explicitly reserved magenta backing')
    margin=max(64,max(native.size)//12)
    surrounded=ImageOps.expand(native,border=margin,fill=(255,0,255,255))
    extracted,evidence=keyed(surrounded)
    evidence=dict(evidence,scope='Internal declared-key crop extraction only; no intake, framing or semantic acceptance',temporary_extraction_surround=margin)
    return extracted.crop((margin,margin,margin+native.width,margin+native.height)),evidence


def repair(root,state,frame_id,item_id):
    config,brief,manifest,public=load_config(root);policy=initialize(root);row=state['frames'][frame_id]
    source=Image.open(row['image']).convert('RGBA');obs=Observation.model_validate(row['observation'])
    if obs.image_sha256!=image_digest(source):raise ValueError('Stale patch observation')
    item=obs.items[item_id];authority=policy.master.items[item_id]
    if not item.rigid_span or not authority.rigid_span or any(p.visibility!='visible' for p in [*item.rigid_span,*authority.rigid_span,item.grip,authority.grip]):raise ValueError('Visible rigid component endpoints and grip required')
    report=evaluate_frame(policy,obs,image_sha256=image_digest(source),frame_id=frame_id,pixel_scale=row['pixel_scale'])
    tasks=[t for t in repair_plan(policy,obs,report)['tasks'] if t['code']=='item_scale_drift' and t['feature']==item_id]
    from framebound.v3.transition_consistency import evaluate as evaluate_transitions,repair_tasks
    hashes={fid:image_digest(Image.open(entry['image']).convert('RGBA')) for fid,entry in state['frames'].items()}
    transitions=evaluate_transitions(policy,state.get('transitions'),hashes)
    tasks.extend(t for t in repair_tasks(transitions,frame_id) if t.get('item_id')==item_id and t['feature'] in ('item.orientation','item.grip','item.topology','item.texture','item.palette'))
    if not tasks:raise ValueError('A measured item scale or visible item transition failure is required')
    for task in tasks:
        if task['code']!='item_scale_drift':continue
        change=1/task['observed']-1
        task['instruction']=('Increase' if change>0 else 'Reduce')+' ONLY the current rigid handle length by '+str(round(abs(change)*100,1))+' percent around the FIXED grip centre, aiming for the exact canonical ratio 1.0. Keep hand size, pose, strand thickness and all other artwork unchanged.'
    padding=2.0 if any(t['code']=='transition_changed' for t in tasks) else .65
    head=measurements(obs,policy.scale_reference)['head_px'];box=patch_box(source,[p.xy for p in [*item.rigid_span,item.grip]],head*padding)
    reference=Image.open(config['master_image']).convert('RGBA');ref_head=measurements(policy.master,policy.scale_reference)['head_px'];refbox=patch_box(reference,[p.xy for p in [*authority.rigid_span,authority.grip]],ref_head*padding)
    prompt='Edit image TWO, an exact native grip-region crop. Image ONE is the canonical item/grip design. Correct ONLY the declared item defects, keeping grip centre, hand/forearm anatomy, physical dimensions (except explicit size corrections), surface detail, brown palette and gold fittings. '+json.dumps(tasks)+' Keep the same exact crop composition and alignment. Keep the fixed fist centre and crop size. For a grip-direction correction orient the active/lash collar out of the THUMB/INDEX side, the pommel from LITTLE-FINGER/PALM HEEL, never swap those functional ends. Let one compact coil hang from the active collar. Never infer correct direction merely because the coil is below the fist. Only shorten the rigid component when an explicit numeric size task requests it. Active/lash end stays at thumb/index side; pommel stays at little-finger side. One handle and ONE strand only. For a grip correction REMOVE every old coil and dangling tail first, then redraw ONE compact coil hanging from the TOP active collar beside the same fist. Use a clear neutral hammer grip with thumb uppermost and handle almost vertical, active collar ABOVE thumb/index, pommel BELOW little finger. Preserve the arm location and action; rotate only the wrist as needed. Never leave an old coil at the butt end or add a second strand. Preserve strand path at crop edges so it reconnects to the unchanged source. Uniform magenta outside art, no shadow, text, border, guide or other subject. Never zoom the crop or change scale to conceal the correction.'
    op='item-patch-'+frame_id+'-'+digest([image_digest(source),box,prompt])[:16]
    raw=send(root,op,'muse-image-1.0',prompt,[generation_png(reference.crop(refbox)),generation_png(source.crop(box))],image_size='1536x1024')
    native=Image.open(io.BytesIO(extract_image(raw))).convert('RGBA');patch,extraction=extract_patch(native);candidate=assemble(source,patch,box)
    # Check the complete reconstructed native source window before letterboxing.
    dimensions=row['source_framing']['source_dimensions'];offset=((source.width-dimensions[0])//2,source.height-dimensions[1]);sourcebox=(*offset,offset[0]+dimensions[0],offset[1]+dimensions[1])
    gate=framing(candidate.crop(sourcebox),minimum_subject_span=brief.get('minimum_subject_span',1100))
    provenance=dict(operation=op,source_sha256=image_digest(source),source_roi=list(box),generated_patch_dimensions=list(native.size),resample='downsample-only LANCZOS',native_patch_sha256=image_digest(native),extraction=extraction,framing=gate,human_approval=False)
    save(root/'private'/(op+'-patch.json'),provenance)
    if not gate['eligible']:raise ValueError('Reassembled source framing failed')
    path=root/'private'/(op+'.png');candidate.save(path)
    proposed=safe_observe(root,frame_id,candidate,reference,config,phase='bounded-item-patch-'+config['policy_version']);scale=calibrated_scale(policy,proposed,row['format_scale']);checked=evaluate_frame(policy,proposed,image_sha256=image_digest(candidate),frame_id=frame_id,pixel_scale=scale)
    proposed_state=json.loads(json.dumps(state));proposed_state['frames'][frame_id].update(image=str(path),image_sha256=image_digest(candidate),pixel_scale=scale,observation=proposed.model_dump(mode='json'),report=checked,patch=provenance)
    from scripts.review_character_transitions import review
    review(root,proposed_state,only=frame_id);save(root/('item-patch-state-'+frame_id+'.json'),proposed_state)
    print(frame_id,checked['issues'],flush=True)
    return proposed_state


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True,type=Path);p.add_argument('--state',required=True,type=Path);p.add_argument('--frame',required=True);p.add_argument('--item',required=True);a=p.parse_args();repair(a.root,json.loads(a.state.read_text()),a.frame,a.item)
