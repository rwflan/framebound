"""Resume a bounded private refinement run and publish only through existing gates."""
import argparse
import copy
import fcntl
import json
from pathlib import Path
from PIL import Image
from scripts.build_movement_demo import save
from scripts.refine_character_demo import initialize,load_config,pairs_for,repair
from scripts.review_character_transitions import review
from scripts.publish_character_demo import publish
from framebound.v3.character_consistency import digest,evaluate_sequence,image_digest


def continue_run(root,state_path,run_id,max_generations,publish_preview=False):
    root=Path(root);ledger_path=root/('refinement-run-'+run_id+'.json')
    with (root/'private'/('refinement-run-'+run_id+'.lock')).open('a+b') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else dict(max_generations=max_generations,attempts=[],status='running')
        if ledger['max_generations']!=max_generations:raise ValueError('Frozen refinement budget differs; do not reset consumed work')
        config,brief,manifest,_=load_config(root);policy=initialize(root)
        state=json.loads(state_path.read_text());ids=[p['id'] for p in brief['poses']]
        pending=next((a for a in reversed(ledger['attempts']) if a['status']=='pending'),None)
        if pending:
            fid=pending['frame'];target=root/('repair-state-'+fid+'.json')
            if target.exists():
                try:
                    retained=json.loads(target.read_text());record=retained['frames'][fid]
                    already_assessed=(not record.get('pending_operation') and (record.get('image_sha256')!=pending['input_sha256'] or len(record.get('attempts',[]))>len(state['frames'][fid].get('attempts',[]))))
                    result=retained if already_assessed else repair(root,only=fid,max_new_attempts=1)
                    state['frames'][fid]=result['frames'][fid];state['transitions']=result.get('transitions',state.get('transitions',[]));save(state_path,state);pending['status']='assessed';ledger['status']='running';save(ledger_path,ledger)
                except Exception as error:
                    pending['error_type']=type(error).__name__;save(ledger_path,ledger);return
        for _ in range(max_generations+1):
            # Reuse retained pair evidence and only assess changed or missing sources.
            review(root,state);save(state_path,state)
            rows=[state['frames'][fid] for fid in ids]
            report=evaluate_sequence(policy,[r['observation'] for r in rows],[image_digest(Image.open(r['image'])) for r in rows],ids,[r['pixel_scale'] for r in rows],pairs_for(manifest),images=[Image.open(r['image']).convert('RGBA') for r in rows],transition_review=state.get('transitions'))
            save(root/('refinement-audit-'+run_id+'.json'),report)
            if publish_preview:
                try:
                    result=publish(root,state,preview=True);ledger.update(status='published_preview',revision=result['revision']);save(ledger_path,ledger);return
                except ValueError as error:ledger['publication_withheld']=str(error)
            if len(ledger['attempts'])>=max_generations:break
            priority=[]
            for fid,frame in zip(ids,report['frames']):
                failures=[i for i in frame['issues'] if i['status']=='fail']
                if failures and not state['frames'][fid].get('blocked_generation_operation'):
                    critical=sum(i['code'] in ('feature_changed','item_owner_changed','item_design_changed','render_fidelity_changed') for i in failures)
                    used=sum(row['frame']==fid for row in ledger['attempts'])
                    priority.append((used,-critical,-len(failures),fid))
            if not priority:
                for item in report.get('transition_results',[]):
                    if item['status']=='fail':
                        for fid in item['frames']:
                            if fid!='idle-neutral' and not state['frames'][fid].get('blocked_generation_operation'):
                                priority.append((sum(r['frame']==fid for r in ledger['attempts']),-1,-1,fid))
            if not priority:ledger['status']='measurement_recovery_required';break
            fid=min(priority)[-1];attempt=dict(frame=fid,status='committed',input_sha256=state['frames'][fid]['image_sha256'],prior_attempts=len(state['frames'][fid].get('attempts',[])))
            ledger['attempts'].append(attempt);save(ledger_path,ledger)
            target=root/('repair-state-'+fid+'.json');snapshot=copy.deepcopy(state);snapshot['policy_sha256']=digest(policy.model_dump(mode='json'));save(target,snapshot)
            try:
                result=repair(root,only=fid,max_new_attempts=1);state['frames'][fid]=result['frames'][fid];state['transitions']=result.get('transitions',state.get('transitions',[]));save(state_path,state);attempt['status']='assessed'
            except Exception as error:
                attempt.update(status='pending',error_type=type(error).__name__)
                # The provider worker owns transport resumption. Do not generate
                # another image to replace an in-flight or unknown operation here.
                ledger['status']='provider_recovery_pending';save(ledger_path,ledger);return
            save(ledger_path,ledger)
        if ledger['status']=='running':ledger['status']='bounded_refinement_complete_with_findings'
        save(ledger_path,ledger)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True,type=Path);p.add_argument('--state',required=True,type=Path);p.add_argument('--run-id',required=True);p.add_argument('--max-generations',type=int,default=12);p.add_argument('--publish-preview',action='store_true');a=p.parse_args()
    if a.max_generations<1 or not a.run_id.replace('-','').isalnum():p.error('Positive bounded budget and simple run ID required')
    continue_run(a.root,a.state,a.run_id,a.max_generations,a.publish_preview)
