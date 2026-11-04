"""Cohort audit/repair driver. The Direct Muse control is never regenerated."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from PIL import Image

from framebound.v3.character_consistency import Policy, Observation, digest, image_digest, measurements, evaluate_sequence, evaluate_frame, repair_plan
from scripts.character_gate_adapter import observe, png
from scripts.build_movement_demo import save, send, extract_image
from scripts.build_individual_demo import decode
from framebound.v3.character_observations import ObservationInvalid
from framebound.v3.intake import framing


def generation_png(image):
    # The provider sees the declared technical matte, never an implicit black
    # rendering of transparent source pixels. Originals remain unchanged.
    backing=Image.new('RGBA',image.size,(255,0,255,255))
    backing.alpha_composite(image.convert('RGBA'))
    return png(backing.convert('RGB'))


def load_config(root):
    config=json.loads((root/'config.json').read_text())
    source=Path(config['source_root'])
    brief=json.loads((source/'brief.json').read_text())
    public=Path(config['publish_root'])
    manifest=json.loads((public/'manifest.json').read_text())
    # Starting pixels and control bindings are frozen independently of later publications.
    frozen=root/'start-manifest.json'
    if not frozen.exists():save(frozen,manifest)
    manifest=json.loads(frozen.read_text())
    return config,brief,manifest,public


def initialize(root):
    config,brief,manifest,public=load_config(root)
    anchor=Image.open(config['master_image']).convert('RGBA')
    policy_path=root/('policy-'+config.get('policy_version','v1')+'.json')
    if not policy_path.exists():
        if config.get('master_observation'):
            observation=Observation.model_validate_json(Path(config['master_observation']).read_text())
            observation=enrich_geometry(root,anchor,observation,config)
        else:
            observation=observe(root,'master',anchor,anchor,config['features'],config['items'],config['description'],phase='anchor-'+config.get('policy_version','v1'))
        policy=Policy(request_sha256=digest(config['description']),master=observation,required_features=config['features'],items=config['items'],scale_reference=('face_top','face_chin') if config.get('pose_runtime') else ('head_top','chin'),expected_geometry_recipe=observation.measurement_sources.get('geometry_recipe_sha256'))
        save(policy_path,policy.model_dump(mode='json'))
    return Policy.model_validate_json(policy_path.read_text())


def pairs_for(manifest):
    pairs=[]
    for state,spec in manifest['states'].items():
        slots=spec['frames']
        pairs.extend(zip(slots,slots[1:]))
        if spec.get('loop') and len(slots)>1:pairs.append((slots[-1],slots[0]))
    # The movement engine advances these separate states in one authored jump.
    for left,right in [('jump','apex'),('apex','fall')]:
        if left in manifest['states'] and right in manifest['states']:
            pairs.append((manifest['states'][left]['frames'][-1],manifest['states'][right]['frames'][0]))
    return list(dict.fromkeys(pairs))


def audit(root, *, round_id='initial', candidates=None, calibrate=False):
    config,brief,manifest,public=load_config(root)
    policy=initialize(root)
    reference=Image.open(config['master_image']).convert('RGBA')
    images=[];observations=[];ids=[];scales=[]
    for i,pose in enumerate(brief['poses']):
        path=Path(candidates[pose['id']]['image']) if candidates and pose['id'] in candidates else public/config['source_revision']/f'framework-{i}.png'
        image=Image.open(path).convert('RGBA')
        if image_digest(image)==policy.master.image_sha256:
            observation=policy.master.model_copy(update={'frame_id':pose['id']})
        else:
            observation=safe_observe(root,pose['id'],image,reference,config,phase='measurement-'+config.get('policy_version','v1'))
        value=manifest['source_pixel_scales']['framework'][i]
        if candidates and pose['id'] in candidates:value=candidates[pose['id']].get('pixel_scale',value)
        if calibrate:
            native=measurements(observation,policy.scale_reference).get('head_px')
            master=measurements(policy.master,policy.scale_reference).get('head_px')
            if native and master:
                correction=master/(native*value)
                if .6<=correction<=1.6:value*=correction
        images.append(image);observations.append(observation);ids.append(pose['id']);scales.append(value)
        print(round_id,pose['id'],'observed',flush=True)
    report=evaluate_sequence(policy,observations,[image_digest(im) for im in images],ids,scales,pairs_for(manifest))
    save(root/(round_id+'-audit.json'),report)
    save(root/(round_id+'-observations.json'),[o.model_dump(mode='json') for o in observations])
    print(round_id,'passed',report['passed'],'frame failures',sum(not f['passed'] for f in report['frames']),'temporal',len(report['temporal_issues']),flush=True)
    return report,observations,images,scales



def safe_observe(root,frame_id,image,reference,config,*,phase):
    # Reuse completed, source-bound semantic observations before dispatch.
    # Recompute geometry using the current pinned recipe independently.
    for path in Path(root).glob('private/registered-observation-'+frame_id+'-*.json'):
        cached=Observation.model_validate_json(path.read_text())
        if cached.image_sha256==image_digest(image) and all(f in cached.features for f in config['features']):
            return enrich_geometry(root,image,cached,config)
    cached_root=config.get('observation_cache_root')
    if cached_root:
        cached_config=json.loads((Path(cached_root)/'config.json').read_text())
        if image_digest(Image.open(cached_config['master_image']))!=image_digest(reference):
            raise ValueError('Observation cache uses another identity reference')
        for path in Path(cached_root).glob('private/registered-observation-*.json'):
            cached=Observation.model_validate_json(path.read_text())
            if cached.image_sha256==image_digest(image) and cached.frame_id==frame_id and all(f in cached.features for f in config['features']):
                return enrich_geometry(root,image,cached,config)
    if config.get('registered_semantic_views'):
        return registered_observe(root,frame_id,image,reference,config,phase)
    for attempt in range(3):
        suffix='' if attempt==0 else '-format-recovery-'+str(attempt)
        try:
            observed=observe(root,frame_id,image,reference,config['features'],config['items'],config['description'],phase=phase+suffix,geometry_external=bool(config.get('pose_runtime')))
            return enrich_geometry(root,image,observed,config)
        except ObservationInvalid:
            if attempt==2:raise
    raise RuntimeError('unreachable')




def registered_observe(root,frame_id,image,reference,config,phase):
    from framebound.v3.character_consistency import Point
    # Obtain source-bound geometry first, then compare appearances at the same
    # facial reference scale. Coordinates are mapped back through a retained
    # invertible crop/scale/pad transform, never guessed or fitted by silhouette.
    placeholder=Observation(image_sha256=image_digest(image),frame_id=frame_id,execution_id='geometry-only',raw_sha256='0'*64,
        width=image.width,height=image.height,points={},features={},items={},limitation='Geometry-only stage, not appearance acceptance')
    geometry=enrich_geometry(root,image,placeholder,config)
    rp=root/'reference-geometry.json'
    if not rp.exists():
        ref=placeholder.model_copy(update={'image_sha256':image_digest(reference),'frame_id':'reference','width':reference.width,'height':reference.height})
        ref=enrich_geometry(root,reference,ref,config);save(rp,ref.model_dump(mode='json'))
    ref=Observation.model_validate_json(rp.read_text())
    scale_keys=('face_top','face_chin')
    head=measurements(geometry,scale_keys).get('head_px');refhead=measurements(ref,scale_keys).get('head_px')
    factor=refhead/head if head and refhead else 1.
    if not .4<=factor<=3.:factor=1.
    box=image.getbbox();refbox=reference.getbbox()
    content=image.crop(box);content=content.resize((max(1,round(content.width*factor)),max(1,round(content.height*factor))),Image.Resampling.LANCZOS)
    refcontent=reference.crop(refbox)
    width=max(content.width,refcontent.width)+64;height=max(content.height,refcontent.height)+64
    current_view=Image.new('RGBA',(width,height));master_view=Image.new('RGBA',(width,height))
    offset=((width-content.width)//2,height-content.height-32);ref_offset=((width-refcontent.width)//2,height-refcontent.height-32)
    current_view.alpha_composite(content,offset);master_view.alpha_composite(refcontent,ref_offset)
    description=config['description']+' The two comparison images have been uniformly registered to the same face size. Judge INTRINSIC proportions and visible design, not the original source pixel density. Articulation may change projected silhouette height, never body volume or segment lengths.'
    for attempt in range(3):
        try:
            obs=observe(root,frame_id,current_view,master_view,config['features'],config['items'],description,
                phase=phase+'-registered'+('' if attempt==0 else '-format-recovery-'+str(attempt)),geometry_external=True)
            break
        except ObservationInvalid:
            if attempt==2:raise
    data=obs.model_dump(mode='json')
    def source_point(p):
        if p is None or p['visibility']!='visible':return p
        x=(p['xy'][0]*width/1000-offset[0])/factor+box[0]
        y=(p['xy'][1]*height/1000-offset[1])/factor+box[1]
        if not 0<=x<image.width or not 0<=y<image.height:return dict(xy=None,visibility='uncertain',evidence='Mapped item point lies outside original source')
        p['xy']=[x/image.width*1000,y/image.height*1000];return p
    for item in data['items'].values():
        item['grip']=source_point(item.get('grip'))
        if item.get('rigid_span'):item['rigid_span']=[source_point(p) for p in item['rigid_span']]
    data.update(image_sha256=image_digest(image),width=image.width,height=image.height,points={**{k:source_point(v) for k,v in data['points'].items()},**{k:v.model_dump(mode='json') for k,v in geometry.points.items()}},
        measurement_sources=dict(geometry.measurement_sources,semantic_view=dict(scale=factor,crop=list(box),offset=list(offset),view_dimensions=[width,height],view_sha256=obs.image_sha256)))
    result=Observation.model_validate(data)
    save(root/'private'/('registered-observation-'+frame_id+'-'+image_digest(image)[:16]+'.json'),result.model_dump(mode='json'))
    return result

def enrich_geometry(root,image,observation,config):
    if not config.get('pose_runtime'):return observation
    import subprocess
    from framebound.v3.character_consistency import Point
    from framebound.v3.pose_measurement import JOINTS
    key=image_digest(image)
    implementation=hashlib.sha256((Path(__file__).parents[1]/'framebound/v3/pose_measurement.py').read_bytes()).hexdigest()
    backend=config.get('geometry_backend','v1')
    if backend in ('material-v2','torso-v3'):
        implementation=hashlib.sha256((implementation+(Path(__file__).parents[1]/'framebound/v3/material_geometry.py').read_text()).encode()).hexdigest()
    if backend=='torso-v3':
        implementation=hashlib.sha256((implementation+(Path(__file__).parents[1]/'framebound/v3/torso_geometry.py').read_text()).encode()).hexdigest()
    geometry_key=key+'-'+implementation[:12]
    path=root/'private'/('geometry-'+geometry_key+'.json')
    artifact=root/'private'/('geometry-'+geometry_key+'.png')
    if not path.exists():
        image.save(artifact)
        subprocess.run([config['pose_runtime'],str(Path(__file__).with_name('measure_character_geometry.py')),'--image',str(artifact),'--models',config['pose_models'],'--output',str(path),'--backend',backend],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    result=json.loads(path.read_text())
    data=observation.model_dump(mode='json')
    for name,point in result['points'].items():data['points'][name]=point
    for name in ('head_left','head_right'):data['points'][name]=dict(xy=None,visibility='uncertain',evidence='Skull width behind hair/profile is not a supported numeric measurement')
    data['measurement_sources']=dict(geometry_recipe_sha256=result['recipe_sha256'],geometry_artifact_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),recipe=result['recipe'],semantic_raw_sha256=observation.raw_sha256)
    data['limitation']+=' Numeric landmarks are image-space pose estimates and rendered-material cross-sections; never hidden anatomy or physical 3D truth.'
    enriched=Observation.model_validate(data)
    save(root/'private'/('enriched-'+observation.frame_id+'-'+key[:16]+'-'+result['recipe_sha256'][:12]+'.json'),enriched.model_dump(mode='json'))
    return enriched

def calibrated_scale(policy,observation,format_scale):
    head=measurements(observation,policy.scale_reference).get('head_px');master=measurements(policy.master,policy.scale_reference).get('head_px')
    if not head or not master:return format_scale
    correction=master/(head*format_scale)
    return format_scale*correction if .6<=correction<=1.6 else format_scale



def rank_report(report):
    critical=sum(i['code'] in {'item_owner_changed','item_design_changed','item_detached','unexpected_item'} or (i['code']=='feature_changed' and i['feature']=='face.identity') for i in report['issues'])
    unknown=sum(i['status']=='unmeasured' for i in report['issues'])
    numeric=sum(abs(i['observed']-1) for i in report['issues'] if isinstance(i['observed'],(float,int)) and isinstance(i['expected'],list))
    return (critical,unknown,len(report['issues']),numeric)

def repair(root, *, only=None, max_new_attempts=None):
    config,brief,manifest,public=load_config(root)
    policy=initialize(root);policy_sha=digest(policy.model_dump(mode='json'))
    reference=Image.open(config['master_image']).convert('RGBA')
    state_path=root/('repair-state-'+only+'.json' if only else 'repair-state.json')
    if only and not state_path.exists() and (root/'repair-state.json').exists():
        previous=json.loads((root/'repair-state.json').read_text())
        if previous.get('policy_sha256')==policy_sha:save(state_path,previous)
    state=json.loads(state_path.read_text()) if state_path.exists() else dict(policy_sha256=policy_sha,frames={})
    if state['policy_sha256']!=policy_sha:raise ValueError('Repair state belongs to a different frozen policy')
    head=measurements(policy.master,policy.scale_reference)['head_px']
    top=policy.master.points[policy.scale_reference[0]].xy;chin=policy.master.points[policy.scale_reference[1]].xy
    centre=(top[0]*reference.width/1000, (top[1]+chin[1])*reference.height/2000)
    face=reference.crop((max(0,int(centre[0]-head)),max(0,int(centre[1]-head)),min(reference.width,int(centre[0]+head)),min(reference.height,int(centre[1]+head))))
    item=policy.master.items[config['items'][0]['id']];grip=item.grip.xy
    gx,gy=grip[0]*reference.width/1000,grip[1]*reference.height/1000
    item_reference=reference.crop((max(0,int(gx-2*head)),max(0,int(gy-head)),min(reference.width,int(gx+head)),min(reference.height,int(gy+3*head))))
    for slot,pose in enumerate(brief['poses']):
        fid=pose['id']
        if only and fid!=only:continue
        record=state['frames'].setdefault(fid,dict(image=str(public/config['source_revision']/f'framework-{slot}.png'),attempts=[]))
        image=Image.open(record['image']).convert('RGBA')
        if image_digest(image)==policy.master.image_sha256:observation=policy.master.model_copy(update={'frame_id':fid})
        else:observation=safe_observe(root,fid,image,reference,config,phase='measurement-'+config.get('policy_version','v1'))
        format_scale=record.get('format_scale',manifest['source_pixel_scales']['framework'][slot])
        scale=calibrated_scale(policy,observation,format_scale)
        report=evaluate_frame(policy,observation,image_sha256=image_digest(image),frame_id=fid,pixel_scale=scale)
        record.update(pixel_scale=scale,report=report,observation=observation.model_dump(mode='json'))
        save(state_path,state)
        if config.get('candidate_pool_root') and not report['passed'] and not record.get('pool_checked'):
            pool=Path(config['candidate_pool_root'])
            for path in sorted(pool.glob('private/repair-'+fid+'-*.png')):
                raw_path=pool/'private'/path.stem/'response.json'
                if not raw_path.exists():continue
                source,source_gate=decode(raw_path.read_bytes(),brief.get('minimum_subject_span',1100))
                if not source_gate['framing']['eligible']:continue
                proposed_image=Image.open(path).convert('RGBA')
                proposed=safe_observe(root,fid,proposed_image,reference,config,phase='measurement-'+config.get('policy_version','v1'))
                proposed_format=max(max(size) for size in manifest['source_dimensions'])/source.height
                proposed_scale=calibrated_scale(policy,proposed,proposed_format)
                checked=evaluate_frame(policy,proposed,image_sha256=image_digest(proposed_image),frame_id=fid,pixel_scale=proposed_scale)
                if rank_report(checked)<rank_report(report):
                    image,observation,report,scale=proposed_image,proposed,checked,proposed_scale
                    format_scale=proposed_format
                    record.update(image=str(path),format_scale=format_scale,pixel_scale=scale,report=report,observation=observation.model_dump(mode='json'),source_framing=source_gate,prior_policy_candidate=True)
                    save(state_path,state)
                print(fid,'rechecked retained candidate',path.stem,'remaining gates',len(report['issues']),flush=True)
                if report['passed']:break
            record['pool_checked']=True;save(state_path,state)
        stop=config.get('max_rounds',8)
        if max_new_attempts is not None:stop=min(stop,len(record['attempts'])+max_new_attempts)
        for attempt in range(len(record['attempts']),stop):
            if report['passed']:break
            target=copy.deepcopy(report['issues'])
            constraints=dict(measured=measurements(observation,policy.scale_reference),reference=measurements(policy.master,policy.scale_reference),failures=target)
            plan=repair_plan(policy,observation,report)
            # Recover missing measurements independently; redrawing must not
            # change a valid pose merely to expose deliberately hidden anatomy.
            measured=[task for task,issue in zip(plan['tasks'],report['issues']) if issue['status']!='unmeasured']
            semantic=[task for task in measured if task['code'] in {'item_owner_changed','item_design_changed','item_detached','unexpected_item','feature_changed'}]
            item_repairs=[task for task in measured if task['code'].startswith('item_')]
            plan['tasks']=semantic or item_repairs or measured[:1]
            if not plan['tasks']:
                print(fid,'WITHHELD: measurement recovery required; no speculative redraw',flush=True)
                break
            from PIL import ImageDraw
            dimensions=record.get('source_framing',{}).get('source_dimensions')
            if not dimensions:
                dimensions=[1920,1280] if format_scale>1.1 else [1280,1920]
            source_offset=((image.width-dimensions[0])//2,image.height-dimensions[1])
            source_box=(*source_offset,source_offset[0]+dimensions[0],source_offset[1]+dimensions[1])
            edit_target=image.crop(source_box)
            annotated=edit_target.copy();drawing=ImageDraw.Draw(annotated)
            for task in plan['tasks']:
                if task['source_roi']:
                    box=task['source_roi'];box=[box[0]-source_offset[0],box[1]-source_offset[1],box[2]-source_offset[0],box[3]-source_offset[1]]
                    drawing.rectangle(box,outline='#00bfff',width=5);drawing.text((max(0,box[0]),max(0,box[1])),task['feature'],fill='#00bfff')
            prompt=('EDIT IMAGE 4. Preserve its EXACT pose, framing, figure placement, canvas, identity, costume and all already-correct details. This is a local correction, NOT a new illustration and NOT a new pose. Image 1 is the immutable character authority, image 2 its face, image 3 its item, image 4 the current edit target, image 5 the diagnostic overlay (never draw the marks).\n'
                +'Requested action to preserve: '+pose['instruction']+'\nFrozen design: '+config['description']
                +'\nMake ONLY these measured corrections, treating percentages as changes to the CURRENT drawing: '+json.dumps(plan['tasks'])
                +'\nPreserve every declared item and its frame-specific anatomical owner or mount: '+json.dumps(config['items'])+'. No duplicate, redesign or undeclared transfer. Keep limb segment lengths and widths consistent with the reference while articulating naturally. Do not shrink the whole body to fix a single part. Keep generous uniform magenta margins, no floor/shadow/labels/guide marks. Return the same image orientation and same pose.')
            size=record.get('next_size','1536x1024' if dimensions[0]>dimensions[1] else '1024x1536')
            if config.get('focused_item_edit') and any(task['code'].startswith('item_') for task in plan['tasks']):
                prompt=('Edit the SECOND image. The FIRST image defines the exact character and item design. Keep the second image action pose, face, body, costume, canvas, cape and hair. Correct the visible item ONLY: '+json.dumps(config['items'])+' The item must have the same construction, thickness, rigid component and proportions as image one. Show one item, firmly connected to its declared anatomical hand or mount. For this pose: '+pose['instruction']+' '+config.get('item_pose_constraints',{}).get(fid,'')+' No second grip, duplicate item, loose trailing loop, additional handle, guide marks, text, floor or shadows. Full silhouette inside the canvas with at least 8 percent magenta margin. Uniform RGB(255,0,255) backing everywhere outside the artwork. Return one full-resolution complete character in the same pose. The compact coil can rotate with the hand but cannot turn into a different weapon.')
                mounts=[]
                for rule in policy.items:
                    anchor=rule.anchor_by_frame.get(fid,rule.anchor)
                    landmark=observation.points.get(anchor)
                    if landmark and landmark.visibility=='visible':
                        px=landmark.xy[0]*image.width/1000-source_offset[0];py=landmark.xy[1]*image.height/1000-source_offset[1]
                        mounts.append(dict(item=rule.id,anchor=anchor,target_pixel=[round(px),round(py)],canvas=list(edit_target.size)))
                        drawing.ellipse((px-18,py-18,px+18,py+18),outline='#00bfff',width=5)
                        drawing.text((max(0,px-90),max(0,py-40)),'ITEM GRIP HERE',fill='#00bfff')
                prompt+=' The THIRD image is a diagnostic only: the blue ring identifies the actual required grip or mount. Transfer the item to that location and leave the other hand EMPTY. Never draw the ring or labels. Target coordinates on image TWO: '+json.dumps(mounts)
                generation_images=[generation_png(reference),generation_png(edit_target),generation_png(annotated)]
            else:
                generation_images=[generation_png(im) for im in (reference,face,item_reference,edit_target,annotated)]
            op='edit-'+fid+'-'+str(attempt)+'-'+digest([policy_sha,image_digest(image),size,prompt,[hashlib.sha256(b).hexdigest() for b in generation_images]])[:12]
            pending=record.get('pending_operation')
            if pending and pending!=op and not (root/'private'/pending/'response.json').exists():
                raise RuntimeError('Unresolved provider acceptance for '+pending+'; reconciliation required before a different request')
            record['pending_operation']=op;save(state_path,state)
            raw=send(root,op,'muse-image-1.0',prompt,generation_images,image_size=size)
            record.pop('pending_operation',None);save(state_path,state)
            try:
                candidate,gate=decode(raw,brief.get('minimum_subject_span',1100))
            except ValueError as error:
                record['attempts'].append(dict(operation=op,response_sha256=hashlib.sha256(raw).hexdigest(),rejected=str(error)))
                save(state_path,state);continue
            row=dict(operation=op,response_sha256=hashlib.sha256(raw).hexdigest(),source_framing=gate)
            if not gate['framing']['eligible']:
                if size=='1024x1536' and set(gate['framing']['unsafe_edges'])&{'left','right'}:record['next_size']='1536x1024'
                row['rejected']='original framing failed';record['attempts'].append(row);save(state_path,state);continue
            canvas=Image.new('RGBA',tuple(manifest['canvas']));offset=((canvas.width-candidate.width)//2,canvas.height-candidate.height)
            canvas.alpha_composite(candidate,offset)
            path=root/'private'/(op+'.png');canvas.save(path)
            proposed=safe_observe(root,fid,canvas,reference,config,phase='measurement-'+config.get('policy_version','v1'))
            proposed_format=max(max(size) for size in manifest['source_dimensions'])/candidate.height
            proposed_scale=calibrated_scale(policy,proposed,proposed_format)
            checked=evaluate_frame(policy,proposed,image_sha256=image_digest(canvas),frame_id=fid,pixel_scale=proposed_scale)
            row.update(image=str(path),report=checked,pixel_scale=proposed_scale)
            record['attempts'].append(row)
            # No aggregate aesthetic score can waive a failed gate. Keep the
            # best bounded candidate for continued repair, publish only all-pass.
            if rank_report(checked)<rank_report(report):
                image,observation,report,scale=canvas,proposed,checked,proposed_scale
                format_scale=proposed_format
                record.update(image=str(path),format_scale=format_scale,pixel_scale=scale,report=report,observation=observation.model_dump(mode='json'),source_framing=gate)
            save(state_path,state)
            print(fid,'attempt',attempt,'remaining gates',len(report['issues']),flush=True)
        if not report['passed']:print(fid,'WITHHELD',len(report['issues']),'gates remain',flush=True)
        else:print(fid,'ALL FRAME GATES PASSED',flush=True)
    return state

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--calibrate',action='store_true');parser.add_argument('--round',default='initial');parser.add_argument('--repair',action='store_true');parser.add_argument('--only');parser.add_argument('--max-new-attempts',type=int)
    args=parser.parse_args()
    if args.max_new_attempts is not None and args.max_new_attempts<1:parser.error('Positive new-attempt bound required')
    if args.repair:repair(args.root,only=args.only,max_new_attempts=args.max_new_attempts)
    else:audit(args.root,round_id=args.round,calibrate=args.calibrate)


if __name__=='__main__':main()
