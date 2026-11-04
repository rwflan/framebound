"""Reassess retained repairs and atomically publish a truthful playable revision."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from framebound.v3.character_consistency import image_digest,measurements,evaluate_frame,evaluate_sequence,digest
from scripts.refine_character_demo import initialize,load_config,safe_observe,calibrated_scale,rank_report,pairs_for
from scripts.build_movement_demo import save


def collect(root,pools):
    config,brief,manifest,public=load_config(root);policy=initialize(root)
    reference=Image.open(config['master_image']).convert('RGBA')
    state_path=root/'cohort.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else dict(policy_sha256=digest(policy.model_dump(mode='json')),frames={},evaluated={})
    if state['policy_sha256']!=digest(policy.model_dump(mode='json')):raise ValueError('Cohort uses another frozen policy')
    for slot,pose in enumerate(brief['poses']):
        fid=pose['id'];paths={str(public/config['source_revision']/f'framework-{slot}.png'):manifest['source_pixel_scales']['framework'][slot]}
        for pool in pools:
            for file in pool.glob('repair-state*.json'):
                source=json.loads(file.read_text());row=source.get('frames',{}).get(fid,{})
                if row.get('image'):paths[row['image']]=row.get('format_scale',manifest['source_pixel_scales']['framework'][slot])
                for attempt in row.get('attempts',[]):
                    if attempt.get('image') and attempt.get('source_framing',{}).get('framing',{}).get('eligible'):
                        paths[attempt['image']]=max(max(s) for s in manifest['source_dimensions'])/attempt['source_framing']['source_dimensions'][1]
        for path,format_scale in paths.items():
            image=Image.open(path).convert('RGBA');sha=image_digest(image);key=fid+':'+sha
            if key in state['evaluated']:continue
            observation=policy.master.model_copy(update={'frame_id':fid}) if sha==policy.master.image_sha256 else safe_observe(root,fid,image,reference,config,phase='measurement-'+config['policy_version'])
            scale=calibrated_scale(policy,observation,format_scale)
            report=evaluate_frame(policy,observation,image_sha256=sha,frame_id=fid,pixel_scale=scale)
            entry=dict(image=path,image_sha256=sha,pixel_scale=scale,report=report,observation=observation.model_dump(mode='json'))
            state['evaluated'][key]=entry
            old=state['frames'].get(fid)
            if old is None or rank_report(report)<rank_report(old['report']):state['frames'][fid]=entry
            save(state_path,state)
        print(fid,'remaining',len(state['frames'][fid]['report']['issues']),flush=True)
    return state


def publish(root,state,*,preview=False):
    from framebound.v3.character_consistency import Observation
    config,brief,manifest,public=load_config(root);policy=initialize(root)
    rows=[state['frames'][p['id']] for p in brief['poses']]
    report=evaluate_sequence(policy,[r['observation'] for r in rows],[r['image_sha256'] for r in rows],[p['id'] for p in brief['poses']],
        [r['pixel_scale'] for r in rows],pairs_for(manifest),images=[Image.open(r['image']).convert('RGBA') for r in rows],transition_review=state.get('transitions'))
    blocked=set(config.get('preview_blocking_features',[]))
    blocked_ids=set(config.get('preview_blocking_frame_ids',[p['id'] for p in brief['poses']]))
    blocked_codes=set(config.get('preview_blocking_codes',[]))|{'stale_cohort_context'}
    violations=[issue for frame in report['frames'] for issue in frame['issues'] if (issue['feature'] in blocked or issue['code'] in blocked_codes) and issue.get('frame_id') in blocked_ids]
    transition_issues=[r for r in report.get('transition_results',[]) if r['status']!='pass']
    profile_issues=report.get('torso_profile_issues',[])
    if policy.pristine_render_sha256 and any(issue['feature']=='rendering.clarity' for frame in report['frames'] for issue in frame['issues']):raise ValueError('Publication withheld: original rendering fidelity is failed or unmeasured')
    if transition_issues or profile_issues:raise ValueError('Publication withheld: declared transition or torso-shape continuity gates remain')
    if violations:raise ValueError('Preview withheld by visible body/item findings: '+str(sorted({i['feature'] for i in violations})))
    if not report['passed'] and not preview:raise ValueError('Delivery withheld: character/temporal gates remain')
    report_sha=digest(report);save(root/('playable-audit-'+report_sha[:16]+'.json'),report)
    publication_recipe=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    revision=digest([report_sha,[r['image_sha256'] for r in rows],publication_recipe])[:16]
    output=public/revision;output.mkdir(exist_ok=True)
    old=public/config['source_revision'];bounds=[];offsets=[];changed=0
    for slot,row in enumerate(rows):
        control=old/f'direct-{slot}.png';target=output/f'direct-{slot}.png'
        if not target.exists():shutil.copyfile(control,target)
        if hashlib.sha256(control.read_bytes()).digest()!=hashlib.sha256(target.read_bytes()).digest():raise ValueError('Control changed')
        image=Image.open(row['image']).convert('RGBA')
        if image.size!=tuple(manifest['canvas']) or image_digest(image)!=row['image_sha256']:raise ValueError('Stale candidate pixels')
        framework_path=output/f'framework-{slot}.png'
        if framework_path.exists():
            if image_digest(Image.open(framework_path))!=row['image_sha256']:raise ValueError('Revision collision')
        else:image.save(framework_path)
        changed+=image_digest(Image.open(old/f'framework-{slot}.png'))!=row['image_sha256']
        obs=Observation.model_validate(row['observation']);pelvis=obs.points.get('pelvis');box=image.getbbox()
        if not box:raise ValueError('Empty candidate')
        dx=manifest['canvas'][0]/2-pelvis.xy[0]*image.width/1000 if pelvis and pelvis.visibility=='visible' else 0
        dy=manifest['ground_y']-box[3]
        offsets.append([dx,dy])
        factor=row['pixel_scale'];cx=manifest['canvas'][0]/2;ground=manifest['ground_y']
        bounds.append([cx+(box[0]+dx-cx)*factor,ground+(box[1]+dy-ground)*factor,cx+(box[2]+dx-cx)*factor,ground+(box[3]+dy-ground)*factor])
        direct=Image.open(control);b=direct.getbbox();factor=manifest['source_pixel_scales']['direct'][slot]
        bounds.append([cx+(b[0]-cx)*factor,ground+(b[1]-ground)*factor,cx+(b[2]-cx)*factor,ground+(b[3]-ground)*factor])
    if not changed:raise ValueError('No regenerated candidate selected; refusing unchanged publication')
    actor=[min(b[0] for b in bounds),min(b[1] for b in bounds),max(b[2] for b in bounds),max(b[3] for b in bounds)]
    half=max(manifest['canvas'][0]/2-actor[0],actor[2]-manifest['canvas'][0]/2)
    render_height=min(640.,632*manifest['canvas'][1]/max(1,manifest['ground_y']-actor[1]),468*manifest['canvas'][1]/max(1,half))
    def visible_pass(fid):
        obs=Observation.model_validate(state['frames'][fid]['observation'])
        body=('body.upper_arm_bulk','body.forearm_bulk','body.thigh_bulk')
        item_checks=('design','palette','scale','attachment','material','topology','proportions','configuration')
        return bool(obs.measurement_sources.get('cohort_review')) and all(name in obs.features and obs.features[name].status=='match' for name in body) and all(rule.id in obs.items and all(name in obs.items[rule.id].features and obs.items[rule.id].features[name].status=='match' for name in item_checks) for rule in policy.items)
    manifest=copy.deepcopy(manifest)
    manifest.update(revision=revision,source_pixel_scales=dict(direct=manifest['source_pixel_scales']['direct'],framework=[r['pixel_scale'] for r in rows]),
        source_offsets=dict(framework=offsets),actor_bounds=actor,render_height=render_height,publication_recipe_sha256=publication_recipe,
        quality=dict(render_fidelity=dict(total=len(rows) if policy.pristine_render_sha256 else 0,passed=sum(Observation.model_validate(r['observation']).features.get('rendering.clarity').status=='match' for r in rows if Observation.model_validate(r['observation']).features.get('rendering.clarity'))),transition_checks=dict(total=len(report.get('transition_results',[])),passed=sum(r['status']=='pass' for r in report.get('transition_results',[]))),torso_pairs=dict(total=len(policy.torso_profile_pairs),passed=len(policy.torso_profile_pairs)-len(report.get('torso_profile_issues',[]))),status='checks_passed' if report['passed'] else 'refining',failed_frames=sum(not f['passed'] for f in report['frames']),temporal_findings=len(report['temporal_issues']),
                     report_sha256=report_sha,human_approval=False,regenerated_frames=changed,
                     frames_with_failures=sum(any(i['status']=='fail' for i in f['issues']) for f in report['frames']),
                     unmeasured_frames=sum(any(i['status']=='unmeasured' for i in f['issues']) for f in report['frames']),
                     visible_review=dict(status='passed',states=config.get('cohort_review_states',[]),frames=len(blocked_ids)) if blocked and blocked_ids and all(visible_pass(fid) for fid in blocked_ids) else None),
        comparison='Frozen Direct Muse control; source-bound Framebound repairs with recorded scale and baseline registration. Automated findings remain separate from approval.')
    previous=public/'manifest.json'
    if previous.exists():save(root/'previous-live-manifest.json',json.loads(previous.read_text()))
    save(root/('live-manifest-'+revision+'.json'),manifest)
    save(previous,manifest)
    print('LIVE',revision,'regenerated',changed,'status',manifest['quality']['status'],flush=True)
    return manifest


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--pool',type=Path,action='append',default=[]);p.add_argument('--preview',action='store_true');p.add_argument('--watch',action='store_true');p.add_argument('--interval',type=float,default=15);p.add_argument('--cycles',type=int,default=120)
    args=p.parse_args()
    if args.interval<1 or args.cycles<1:p.error('Positive bounded polling interval/cycles required')
    import time
    previous=None
    for cycle in range(args.cycles if args.watch else 1):
        snapshot=digest([(str(file),file.stat().st_mtime_ns) for pool in args.pool for file in sorted(pool.glob('repair-state*.json'))])
        if snapshot!=previous:
            state=collect(args.root,args.pool)
            config,brief,manifest,public=load_config(args.root)
            for name in config.get('cohort_review_states',[]):
                from scripts.review_character_sequence import review
                state,_=review(args.root,state,manifest['states'][name]['frames'])
            publish(args.root,state,preview=args.preview);previous=snapshot
        if args.watch and cycle+1<args.cycles:time.sleep(args.interval)

if __name__=='__main__':main()
