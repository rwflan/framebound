"""Validate moved v3 snapshots from packaged records/pixels, without the source project."""
import json
from pathlib import Path

from PIL import Image

from ...v3.domain import TaskRecord
from ...v3 import evaluate as E
from .snapshot import _h
from .validate import _check_coco


def validate(snap,manifest):
    issues=[]
    try:
        required={'agent-tasks-v3','honest-label-sources-v1','optional-input-closure-v1'}
        if not required<=set(manifest.get('reader_capabilities',[])) or set(manifest.get('reader_capabilities',[]))-required-{'source-correspondence-v1','declared-color-camera-tracks-v1','explicit-human-preferences-v1','feedback-groups-v2','pre-submission-feedback-v1','revision-provenance-v1'}:issues.append('unsupported reader capabilities')
        listed=manifest['files']
        for rel,expected in listed.items():
            p=snap/rel
            if not p.resolve().is_relative_to(snap.resolve()) or Path(rel).is_absolute() or p.is_symlink():
                issues.append('unsafe package path '+rel);continue
            if not p.is_file() or _h(p.read_bytes())!=expected:issues.append('missing or corrupt file '+rel)
        actual={str(p.relative_to(snap)) for p in snap.rglob('*') if p.is_file()}
        if actual-set(listed)-{'manifest.json','COMPLETE'}:issues.append('unmanifested snapshot files')
        complete=json.loads((snap/'COMPLETE').read_text())
        if (complete.get('manifest_sha256')!=_h((snap/'manifest.json').read_bytes()) or
            any(complete.get(k)!=manifest.get(k) for k in ('snapshot','inputs_digest','dataset_version'))):
            issues.append('COMPLETE marker differs from immutable manifest')
        def load(rel):return [json.loads(line) for line in (snap/rel).read_text().splitlines() if line.strip()]
        tables=('runs','revisions','tasks','evaluations','feedback','events','interventions','completions','frames','registrations','assets','provider_sources','source_records','preferences','provenance')
        graph={}
        for table in tables:
            values=[] if table in {'source_records','preferences','provenance'} and not (snap/f'closure/{table}.jsonl').is_file() else load(f'closure/{table}.jsonl')
            graph[table]={v['id']:v for v in values}
            if len(values)!=len(graph[table]):issues.append('duplicate closure identity '+table)
        from ...v3.provenance import parse, RevisionProvenance, blob_hashes
        attributed = {rid: parse(rev.get('generation_metadata')) for rid,rev in graph['revisions'].items()}
        if any(attributed.values()) and 'revision-provenance-v1' not in manifest['reader_capabilities']:
            issues.append('provenance reader capability missing')
        if set(graph['provenance']) != {rid for rid,value in attributed.items() if value}:
            issues.append('provenance closure membership differs')
        for rid,record in graph['provenance'].items():
            value = RevisionProvenance.model_validate(record['attribution'])
            if value != attributed.get(rid): issues.append('revision attribution differs '+rid)
            task = graph['tasks'][graph['revisions'][rid]['task_id']]
            if value.style_board != TaskRecord.model_validate(task).spec.style_board:
                issues.append('provenance style board differs '+rid)
            for sha in blob_hashes(value):
                p = snap/'closure/provenance_blobs'/sha
                if not p.is_file() or _h(p.read_bytes()) != sha: issues.append('provenance blob missing or corrupt '+sha)
            for event in value.generations:
                if event.evidence_source == 'provider_response':
                    provider=graph['provider_sources'].get(event.provider_job_id,{})
                    job=provider.get('metadata',{})
                    sha=provider.get('artifact_hashes',{}).get('response_artifact')
                    if (not provider.get('available') or job.get('origin')!='live' or job.get('status')!='succeeded'
                            or not set(event.output_asset_ids)<=set(job.get('output_asset_ids',[]))
                            or sha not in event.receipt_sha256):
                        issues.append('local provider provenance lacks matching job '+rid)
                    else:
                        receipt=json.loads((snap/'closure/provenance_blobs'/sha).read_text()).get('payload',{})
                        if (receipt.get('model')!=event.requested_model or receipt.get('observed_model')!=event.observed_model
                                or receipt.get('observed_version')!=event.observed_version
                                or receipt.get('response_id')!=event.response_id or receipt.get('prompt_sha256')!=event.prompt_sha256
                                or receipt.get('conditioning_sha256')!=[r.byte_sha256 for r in event.conditioning]
                                or receipt.get('output_bytes_sha256') not in event.original_output_sha256):
                            issues.append('local provider provenance differs from receipt '+rid)
                for ref in event.conditioning:
                    asset = graph['assets'].get(ref.asset_id)
                    if not asset or asset['byte_sha256'] != ref.byte_sha256: issues.append('provenance conditioning differs '+rid)
        asset_files=json.loads((snap/'closure/asset_files.json').read_text())
        withheld={r['asset_id']:r['reason'] for r in json.loads((snap/'closure/withheld.json').read_text())}
        for aid,asset in graph['assets'].items():
            if aid in asset_files:
                path=snap/asset_files[aid]
                if asset_files[aid]!=f"closure/blobs/{asset['byte_sha256']}":issues.append('asset path is not content-addressed '+aid)
                if asset['rights'] not in manifest['policy']['rights_allow']:issues.append('restricted pixels included '+aid)
                if not path.is_file() or _h(path.read_bytes())!=asset['byte_sha256']:issues.append('asset hash differs '+aid)
                else:
                    from ..media.canonical import load_native_image,canonical_pixels,pixel_sha256
                    image=load_native_image(path)
                    if pixel_sha256(canonical_pixels(image))!=asset['pixel_sha256']:issues.append('canonical pixel hash differs '+aid)
            elif aid not in withheld:issues.append('asset unresolved without withheld reason '+aid)
            if asset.get('source_job_id') and asset['source_job_id'] not in graph['provider_sources']:issues.append('provider source not recorded as available or missing '+aid)
            for parent in asset.get('parent_asset_ids',[]):
                if parent not in graph['assets']:issues.append('derivation parent missing '+aid)
        if set(asset_files)|set(withheld)!=set(graph['assets']):issues.append('asset closure contains unbound identities')
        for tid,task in graph['tasks'].items():
            parsed=TaskRecord.model_validate(task)
            if E.digest(task['spec'])!=task['spec_sha256']:issues.append('frozen task digest differs '+tid)
            for binding in task['spec']['inputs']:
                if binding['asset_id'] not in graph['assets']:issues.append('optional input missing '+tid)
            source=task['spec'].get('source_correspondence')
            if source:
                from ...v3 import correspondence as C
                C.validate(parsed.spec)
                if tid not in graph['source_records']:issues.append('source designation record missing '+tid)
                else:
                    record=graph['source_records'][tid]
                    for key in ('frame_asset_ids','timing','loop','designated_by','designation_basis','provenance'):
                        if record[key]!=source[key]:issues.append('source designation reinterprets original binding '+tid)
                for aid in source['frame_asset_ids']:
                    if aid not in graph['assets']:issues.append('known-good source pixels absent from closure '+tid)
            if parsed.spec.scene:
                from ...v3 import scene as SC
                SC.validate(parsed.spec)
            parent=task['spec'].get('supersedes')
            if parent and parent not in graph['tasks']:issues.append('task predecessor missing '+tid)
        for run in graph['runs'].values():
            if run['task_id'] not in graph['tasks']:issues.append('current run task missing from closure')
        for rid,revision in graph['revisions'].items():
            task=graph['tasks'][revision['task_id']];spec=TaskRecord.model_validate(task).spec
            run=graph['runs'][revision['run_id']]
            if rid not in run['submission_ids']:issues.append('revision missing from ordered run '+rid)
            if len(revision['frame_instance_ids'])!=len(spec.timing.holds):issues.append('frame count differs from task '+rid)
            evaluation=graph['evaluations'][f'evaluation:{rid}']
            if evaluation['task_id']!=task['id'] or evaluation['revision_id']!=rid:issues.append('evaluation binding differs '+rid)
            if E.digest(evaluation['evidence'])!=evaluation['evidence_digest']:issues.append('evidence digest differs '+rid)
            if evaluation['evidence']['results']!=evaluation['results']:issues.append('results differ from evidence '+rid)
            if evaluation['evidence']['spec']!=task['spec']:issues.append('evidence reinterprets the frozen task '+rid)
            images=[];available=True
            for slot,fid in enumerate(revision['frame_instance_ids']):
                frame=graph['frames'][fid];aid=frame['asset_id'];reg=graph['registrations'][frame['registration_id']]
                if frame['clip_revision_id']!=rid or frame['slot']!=slot or frame['hold_ticks']!=spec.timing.holds[slot]:issues.append('frame timing/lineage differs '+fid)
                if aid!=revision['frame_asset_ids'][slot] or reg['frame_instance_id']!=fid:issues.append('frame/registration asset binding differs '+fid)
                evidence_asset=evaluation['evidence']['assets'][slot]
                if evidence_asset['id']!=aid or evidence_asset['byte_sha256']!=graph['assets'][aid]['byte_sha256']:issues.append('evaluation asset binding differs '+fid)
                if aid in asset_files:
                    from ..media.canonical import load_native_image
                    images.append(load_native_image(snap/asset_files[aid]))
                else:images.append(None);available=False
            if available:
                measured,_,_=E.evaluate(spec,images,evaluation['evidence']['assets'],evaluation['evidence']['presented_holds'])
                saved={r['id']:r for r in evaluation['results']}
                for measured_result in measured:
                    actual_result=saved.get(measured_result['id'])
                    if not actual_result or any(actual_result.get(k)!=v for k,v in measured_result.items() if k!='evidence_method'):issues.append('packaged measurement does not reproduce '+rid+'/'+measured_result['id'])
            if spec.scene and available:
                from ...v3 import scene as SC
                measured,scene_evidence=SC.evaluate(spec,images)
                stored={r['id']:r for r in evaluation['results']}
                for result in measured:
                    if stored.get(result['id'])!=result:issues.append('tracked scene measurement does not reproduce '+rid)
                saved_scene=evaluation['evidence'].get('scene',{})
                if any(saved_scene.get(k)!=value for k,value in scene_evidence.items() if k!='source_sha256'):
                    issues.append('scene evaluator method/assumptions differ '+rid)
                if len(saved_scene.get('source_sha256',''))!=64:issues.append('scene evaluator implementation identity missing '+rid)
            if spec.source_correspondence:
                from ...v3 import correspondence as C
                source_evidence=evaluation['evidence'].get('source_correspondence')
                if not source_evidence:issues.append('source fidelity evidence missing '+rid)
                else:
                    for aid,record in zip(spec.source_correspondence.frame_asset_ids,source_evidence['assets']):
                        if record['id']!=aid or record['byte_sha256']!=graph['assets'][aid]['byte_sha256']:
                            issues.append('source asset evidence binding differs '+rid)
                    if len(source_evidence['assets'])!=len(spec.source_correspondence.frame_asset_ids):issues.append('source asset evidence incomplete '+rid)
                    sources=[];source_available=True
                    for aid in spec.source_correspondence.frame_asset_ids:
                        if aid not in asset_files:sources.append(None);source_available=False
                        else:sources.append(load_native_image(snap/asset_files[aid]))
                    if available and source_available:
                        measured,source_manifest=C.evaluate(spec,images,sources,source_evidence['assets'])
                        stored={r['id']:r for r in evaluation['results']}
                        for result in measured:
                            if stored.get(result['id'])!=result:issues.append('source anchor fidelity does not reproduce '+rid)
                        for key,value in source_manifest.items():
                            if source_evidence.get(key)!=value:issues.append('source correspondence evidence differs '+rid)
            for result in evaluation['results']:
                if result['family']!='edit_preservation':continue
                baseline=graph['revisions'][result['baseline_revision_id']]
                for slot in result['slots']:
                    left=baseline['frame_asset_ids'][slot];right=revision['frame_asset_ids'][slot]
                    if left not in asset_files or right not in asset_files:continue
                    import numpy as np
                    from ..media.canonical import load_native_image
                    left_image=load_native_image(snap/asset_files[left]);right_image=load_native_image(snap/asset_files[right])
                    if left_image.size!=right_image.size:continue
                    support=np.zeros((left_image.height,left_image.width),dtype=bool)
                    for gid in result['grant_ids']:
                        grant=graph['interventions'][gid]
                        if not grant['authorize_edit_scope']:issues.append('preservation uses a mark without explicit authority')
                        if slot in grant['slots']:
                            roi=grant['roi'] or dict(left=0,top=0,right=left_image.width,bottom=left_image.height)
                            support[roi['top']:roi['bottom'],roi['left']:roi['right']]=True
                    changed=int(np.sum(np.any(np.asarray(left_image)!=np.asarray(right_image),axis=2)&~support))
                    if changed!=result['observed'] or result['outcome']!=('pass' if changed==0 else 'fail'):issues.append('preservation result does not reproduce '+rid)
            required=[r for r in evaluation['results'] if r['required']]
            status=('error' if any(r['outcome']=='error' for r in required) else 'fail' if any(r['outcome']=='fail' for r in required) else 'incomplete' if any(r['outcome']=='unmeasured' for r in required) else 'pass')
            coverage='partial' if any(r['outcome'] in {'unmeasured','error'} for r in required) else 'complete'
            if status!=evaluation['technical_status'] or coverage!=evaluation['coverage']:issues.append('technical status/coverage does not follow evidence '+rid)
            for r in task['requirements']:
                if r['required'] and not any(result['required'] and result['family']==r['check'] for result in evaluation['results']):issues.append('required matrix omitted '+rid+'/'+r['id'])
            parent=revision.get('parent_revision_id')
            if parent and (parent not in graph['revisions'] or revision['targeted_feedback_id'] not in graph['feedback']):issues.append('repair parent/feedback not portable '+rid)
            if revision.get('targeted_feedback_id') and (revision['targeted_feedback_id'] not in graph['feedback'] or graph['feedback'][revision['targeted_feedback_id']]['baseline_revision_id']!=parent):issues.append('submission feedback binding differs '+rid)
            if parent and graph['feedback'][revision['targeted_feedback_id']]['baseline_revision_id']!=parent:issues.append('repair targets a different feedback baseline '+rid)
        for bundle in graph['feedback'].values():
            if bundle.get('bundle_version',1)>=2:
                from ...v3.feedback import groups
                if json.loads(json.dumps(groups(bundle)))!=bundle.get('correction_groups'):issues.append('correction grouping differs from saved targets')
            if bundle['baseline_revision_id'] is None:
                if 'pre-submission-feedback-v1' not in manifest['reader_capabilities'] or bundle['evaluation_id'] is not None or bundle['evidence_digest'] is not None or bundle['targets'] or bundle['technical_status']!='unevaluated':issues.append('pre-submission feedback invents evaluation evidence '+bundle['id'])
                if not bundle.get('external_failure_event_id'):issues.append('pre-submission feedback lacks its actual failure report '+bundle['id'])
            else:
                evaluation=graph['evaluations'][bundle['evaluation_id']]
                if evaluation['revision_id']!=bundle['baseline_revision_id'] or evaluation['evidence_digest']!=bundle['evidence_digest']:issues.append('feedback evidence binding differs '+bundle['id'])
            if bundle.get('external_failure_event_id'):
                event=graph['events'].get(bundle['external_failure_event_id'],{})
                report=bundle.get('external_failure',{})
                if event.get('source')!='external_agent' or event.get('run_id')!=bundle['run_id'] or event.get('revision_id')!=bundle['baseline_revision_id'] or event.get('evidence_task_id',event.get('task_id'))!=bundle['task_id'] or event.get('report')!={k:v for k,v in report.items() if k!='observation_source'}:issues.append('external failure provenance differs '+bundle['id'])
            if bundle['spec_sha256']!=graph['tasks'][bundle['task_id']]['spec_sha256']:issues.append('feedback task digest differs '+bundle['id'])
            if bundle.get('next_task_id') and (bundle['next_task_id'] not in graph['tasks'] or bundle.get('next_spec_sha256')!=graph['tasks'][bundle['next_task_id']]['spec_sha256']):issues.append('revised task handoff not portable')
            for target in bundle['targets']:
                for asset in target['evidence_assets']:
                    if asset['id'] not in graph['assets'] or asset['byte_sha256']!=graph['assets'][asset['id']]['byte_sha256']:issues.append('feedback asset missing or changed '+bundle['id'])
        members=load('membership.jsonl');member_by_id={m['frame_instance_id']:m for m in members}
        if set(member_by_id)!=set(graph['frames']):issues.append('membership differs from full trajectory frame closure')
        from .agent_snapshot import _families
        expected_families=_families(graph,snap,asset_files)
        for family in set(expected_families.values()):
            members_in_family=[rid for rid,value in expected_families.items() if value==family]
            if len({manifest['families'].get(rid) for rid in members_in_family})>1:issues.append('related packaged lineage/pixels split across family identities')
        split_families={};split_pixels={}
        for folder,view in [('hf','human_accepted'),('automatically_verified','automatically_verified'),('research','research')]:
            view_rows=load(folder+'/metadata.jsonl')
            if len(view_rows)!=sum(m['view']==view for m in members):issues.append('label view count differs '+view)
            for row in view_rows:
                member=member_by_id[row['frame_instance_id']]
                if {k:v for k,v in row.items() if k!='file_name'}!=member:issues.append('view silently relabels membership '+view)
                path=snap/folder/row['file_name']
                if not path.resolve().is_relative_to((snap/folder).resolve()) or not path.is_file() or _h(path.read_bytes())!=row['byte_sha256']:issues.append('view pixels missing or changed '+view)
                if row['family']!=manifest['families'][row['revision_id']]:issues.append('membership family differs from portable evidence')
                if view=='research':continue
                rev=graph['revisions'][row['revision_id']];run=graph['runs'][rev['run_id']];ev=graph['evaluations'][f"evaluation:{rev['id']}"]
                if not ev['evidence'].get('evaluator_identity'):issues.append('trainable example has incomplete historical evaluator identity')
                if ev['technical_status']!='pass' or ev['coverage']!='complete' or run['lifecycle']!='completed' or run['current_revision_id']!=rev['id']:issues.append('trainable example lacks complete passing exact output '+rev['id'])
                if any(m['run_id']==run['id'] and m['correction']['status'] not in {'resolved','cancelled'} for m in graph['interventions'].values()):issues.append('trainable output has unresolved human work')
                controls=[i['asset_id'] for i in graph['tasks'][rev['task_id']]['spec']['inputs']]+(graph['tasks'][rev['task_id']]['spec'].get('source_correspondence') or {}).get('frame_asset_ids',[])
                def ancestry_allowed(aid,active=None):
                    active=active or set()
                    if aid in active or aid not in graph['assets'] or aid not in asset_files:return False
                    a=graph['assets'][aid]
                    if (a['rights'] not in manifest['policy']['rights_allow'] or 'simulated' in a['origin'] or a['origin']=='unknown'
                        or (a['source_kind']=='procedural' and not manifest['policy']['include_procedural_positives'])
                        or (a['source_kind']=='derived' and not a.get('parent_asset_ids'))):return False
                    if a.get('source_job_id'):
                        provider=graph['provider_sources'].get(a['source_job_id'],{})
                        if not provider.get('available') or provider.get('metadata',{}).get('origin','unknown')=='unknown' or 'simulated' in str(provider.get('metadata',{}).get('origin','unknown')):return False
                    return all(ancestry_allowed(parent,active|{aid}) for parent in a.get('parent_asset_ids',[]))
                if not all(ancestry_allowed(aid) for aid in [row['asset_id']]+controls):issues.append('trainable ancestry or conditioning evidence is excluded')
                asset=graph['assets'][row['asset_id']]
                if asset['rights'] not in manifest['policy']['rights_allow'] or (asset['source_kind']=='procedural' and not manifest['policy']['include_procedural_positives']) or 'simulated' in asset['origin'] or asset['origin']=='unknown':issues.append('trainable asset violates rights/origin policy')
                if view=='human_accepted':
                    decision=graph['events'].get(run.get('human_decision_id'))
                    if not decision or decision['source']!='human' or decision['event']!='approve' or decision['revision_id']!=rev['id'] or decision['evaluation_id']!=ev['id'] or row['label_source']!='human':issues.append('invented or stale human positive')
                elif row['label_source']!='technical_policy' or not manifest['policy'].get('include_automatically_verified') or graph['tasks'][rev['task_id']]['spec']['completion']['id']!='technical-unreviewed-v1':issues.append('automatic view violates named policy')
                split_families.setdefault(row['family'],set()).add(row['split']);split_pixels.setdefault(row['pixel_sha256'],set()).add(row['split'])
        for splits in [*split_families.values(),*split_pixels.values()]:
            if len(splits-{'unsplit'})>1:issues.append('trainable family or exact pixels straddle held-out splits')
        for mark in graph['interventions'].values():
            correction=mark['correction']
            if correction['baseline_revision_id'] not in graph['revisions'] or correction['baseline_evaluation_id'] not in graph['evaluations']:issues.append('intervention bindings missing')
            if correction['status']=='resolved':
                event=graph['events'].get(correction['resolution_event_id'])
                if not event or event['source']!='human' or event['actor_id']!=mark['owner'] or event['event']!='resolve_issue':issues.append('subjective correction closed without its owner')
        temporal=load('temporal.jsonl')
        if {r['clip_revision_id'] for r in temporal}!=set(graph['revisions']):issues.append('temporal history incomplete')
        for row in temporal:
            revision=graph['revisions'][row['clip_revision_id']];spec=graph['tasks'][revision['task_id']]['spec']
            if row['holds']!=spec['timing']['holds'] or row['total_ticks']!=sum(row['holds']):issues.append('temporal authored timing differs')
            if row['generation_metadata']!=revision.get('generation_metadata'):issues.append('generation metadata invented or lost')
            if [f['id'] for f in row['frames']]!=revision['frame_instance_ids']:issues.append('temporal frame order differs')
            for frame in row['frames']:
                if frame['file']!=asset_files.get(frame['asset_id']):issues.append('temporal file binding differs')
        trajectories=load('trajectories.jsonl')
        expected_edges={(r['parent_revision_id'],r['id']) for r in graph['revisions'].values() if r.get('parent_revision_id')}
        if {(r['parent_revision_id'],r['candidate_revision_id']) for r in trajectories}!=expected_edges:issues.append('correction trajectory history incomplete')
        for trajectory in trajectories:
            before=graph['evaluations'][trajectory['before_evaluation_id']]
            after=graph['evaluations'][trajectory['after_evaluation_id']]
            if before['revision_id']!=trajectory['parent_revision_id'] or after['revision_id']!=trajectory['candidate_revision_id']:issues.append('trajectory evaluation bindings differ')
            old={r['id']:r for r in before['results']};new={r['id']:r for r in after['results']}
            expected_regressions=[k for k,r in old.items() if r['outcome']=='pass' and new.get(k,{}).get('outcome') not in {'pass','not_applicable'}]
            if trajectory['regressions']!=expected_regressions or trajectory['overall_outcome']!=after['technical_status']:issues.append('trajectory conceals overall failure or regression')
            for change in trajectory['targeted_changes']:
                cid=change['check_id']
                if change['before']!=old.get(cid,{}).get('outcome','subjective') or change['after']!=new.get(cid,{}).get('outcome','unresolved'):issues.append('trajectory target outcome differs from actual checks')
        for completion in graph['completions'].values():
            evaluation=graph['evaluations'][completion['evaluation_id']]
            if completion['revision_id']!=evaluation['revision_id'] or completion['evidence_digest']!=evaluation['evidence_digest']:issues.append('completion is not bound to its exact evidence')
            if evaluation['technical_status']!='pass' or evaluation['coverage']!='complete':issues.append('completion claims unsupported requirements met')
        if load('weak_preferences.jsonl'):issues.append('automatic rankings must not become human preference data')
        pairs=load('preferences.jsonl')
        if len(pairs)!=manifest['counts']['preferences']:issues.append('preference count differs from manifest')
        for pair in pairs:
            record=graph['preferences'].get(pair['id'])
            if not record or any(pair.get(k)!=v for k,v in record.items()):issues.append('preference lacks an exact saved human comparison');continue
            event=graph['events'].get(record['decision_event_id'])
            chosen=graph['revisions'][record['chosen_revision_id']];rejected=graph['revisions'][record['rejected_revision_id']]
            if (not event or event['source']!='human' or event['event']!='approve' or event['actor_id']!=record['actor_id']
                or event['revision_id']!=chosen['id'] or event['evaluation_id']!=record['chosen_evaluation_id']
                or event.get('request',{}).get('comparison_revision_id')!=rejected['id']
                or event.get('request',{}).get('comparison_evaluation_id')!=record['rejected_evaluation_id']):issues.append('preference is not the explicit reviewer choice')
            if chosen['task_id']!=rejected['task_id'] or chosen['id']==rejected['id']:issues.append('preference lacks distinct same-task candidates')
            if any(m['view']!='human_accepted' for m in members if m['revision_id']==chosen['id']):issues.append('preference chosen output is no longer human-positive')
            run=graph['runs'][chosen['run_id']]
            if run.get('human_decision_id')!=record['decision_event_id']:issues.append('stale preference approval')
            for key,revision in [('chosen',chosen),('rejected',rejected)]:
                if [f['asset_id'] for f in pair[key]]!=revision['frame_asset_ids']:issues.append('preference pixels differ from exact candidate')
                for frame in pair[key]:
                    asset=graph['assets'][frame['asset_id']]
                    if frame['file']!=asset_files.get(asset['id']) or frame['sha256']!=asset['byte_sha256']:issues.append('preference pixels missing or changed')
                    if asset['rights'] not in manifest['policy']['rights_allow'] or 'simulated' in asset['origin'] or (asset['source_kind']=='procedural' and not manifest['policy']['include_procedural_positives']):issues.append('preference violates rights/origin policy')
            if pair['label_source']!='explicit_human_comparison':issues.append('preference label source is not explicit human evidence')
        coco=_check_coco(snap,manifest,issues)
        counts=manifest['counts']
        for key,view in [('positives','human_accepted'),('automatically_verified','automatically_verified'),('research','research'),('withheld','withheld')]:
            if counts[key]!=sum(m['view']==view for m in members):issues.append('manifest count differs '+key)
        if counts['trajectories']!=len(trajectories) or counts['temporal']!=len(temporal):issues.append('trajectory/temporal manifest counts differ')
    except Exception as exc:
        issues.append(f'Unresolvable v3 snapshot: {type(exc).__name__}: {exc}')
    return dict(snapshot=manifest.get('snapshot'),ok=not issues,issues=issues,skipped=[],counts=manifest.get('counts',{}),
                exclusions=manifest.get('exclusions',[]),loaders={'version':'3.0','portable_records':True})
