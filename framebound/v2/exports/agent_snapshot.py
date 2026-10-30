"""V3 run closure and honest label views, using the existing atomic snapshot publisher."""
from pathlib import Path
import json

from PIL import Image

from .. import storage as S
from .snapshot import _h, _rle, _silhouette_records, _safe_name
from ...v3 import evaluate as E

VERSION='3.0'
POLICY='agent-training-v1'


def rows(con,table):
    exists=con.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type='table'",(table,)).fetchone()
    return {r['id']:json.loads(r['data']) for r in con.execute(f'SELECT id,data FROM {table}')} if exists else {}


def is_agent_selection(con,rids):
    revisions=rows(con,'agent_clip_revisions')
    hits=[rid in revisions for rid in rids]
    if any(hits) and not all(hits):
        raise ValueError('Export v2 reviewed-guide and v3 agent revisions in separate versioned snapshots.')
    return bool(hits) and all(hits)


def closure(con,rids):
    all_revisions=rows(con,'agent_clip_revisions')
    run_ids={all_revisions[rid]['run_id'] for rid in rids}
    all_runs=rows(con,'agent_runs');specs=rows(con,'agent_task_specs')
    pending=list(run_ids)
    while pending:
        run_id=pending.pop()
        for rid in all_runs[run_id]['submission_ids']:
            source=specs[all_revisions[rid]['task_id']]['spec'].get('source_correspondence')
            source_id=source.get('source_revision_id') if source else None
            if source_id in all_revisions and all_revisions[source_id]['run_id'] not in run_ids:
                extra=all_revisions[source_id]['run_id'];run_ids.add(extra);pending.append(extra)
    runs={k:v for k,v in all_runs.items() if k in run_ids}
    revisions={rid:all_revisions[rid] for run in runs.values() for rid in run['submission_ids']}
    # Always include the complete selected run trajectory, not just its best output.
    specs=rows(con,'agent_task_specs');task_ids={r['task_id'] for r in revisions.values()}
    pending=list(task_ids)
    while pending:
        tid=pending.pop();parent=specs[tid]['spec'].get('supersedes')
        if parent and parent not in task_ids:task_ids.add(parent);pending.append(parent)
    tasks={k:specs[k] for k in task_ids}
    evaluations={k:v for k,v in rows(con,'agent_evaluations').items() if v['revision_id'] in revisions}
    feedback={k:v for k,v in rows(con,'agent_feedback').items() if v['run_id'] in run_ids}
    events={k:v for k,v in rows(con,'agent_run_events').items() if v['run_id'] in run_ids}
    marks={k:v for k,v in rows(con,'agent_interventions').items() if v['run_id'] in run_ids}
    completions={k:v for k,v in rows(con,'agent_completions').items() if v['run_id'] in run_ids}
    all_frames=rows(con,'frame_instances');frame_ids={f for r in revisions.values() for f in r['frame_instance_ids']}
    frames={fid:all_frames[fid] for fid in frame_ids}
    registrations=rows(con,'registrations');registrations={f['registration_id']:registrations[f['registration_id']] for f in frames.values()}
    all_assets=rows(con,'assets');asset_ids={f['asset_id'] for f in frames.values()}
    asset_ids.update(i['asset_id'] for t in tasks.values() for i in t['spec']['inputs'])
    asset_ids.update(aid for t in tasks.values() for aid in (t['spec'].get('source_correspondence') or {}).get('frame_asset_ids',[]))
    source_records={}
    for tid,task in tasks.items():
        source=task['spec'].get('source_correspondence')
        if not source:continue
        source_id=source.get('source_revision_id');raw=None
        if source_id:
            raw=all_revisions.get(source_id)
            if raw is None:raw=S.get(con,'clip_revisions',source_id)[0]
        source_records[tid]=dict(id=tid,source_revision_id=source_id,
            source_schema_version=raw.get('schema_version') if raw else None,
            origin_record_sha256=E.digest(raw) if raw else None,
            frame_asset_ids=source['frame_asset_ids'],timing=source['timing'],loop=source['loop'],
            designated_by=source['designated_by'],designation_basis=source['designation_basis'],provenance=source['provenance'])
    pending=list(asset_ids)
    while pending:
        aid=pending.pop()
        for parent in all_assets[aid].get('parent_asset_ids',[]):
            if parent not in asset_ids:asset_ids.add(parent);pending.append(parent)
    assets={aid:all_assets[aid] for aid in asset_ids}
    all_jobs=rows(con,'jobs');provider_sources={}
    for asset in assets.values():
        jid=asset.get('source_job_id')
        if not jid:continue
        job=all_jobs.get(jid)
        if not job:
            provider_sources[jid]=dict(id=jid,available=False,reason='source_job_record_not_available')
            continue
        def redact(value):
            if isinstance(value,dict):
                return {k:('[redacted]' if any(s in k.lower().replace('-','_') for s in ('secret','token','authorization','api_key','password')) else redact(v)) for k,v in value.items()}
            if isinstance(value,list):return [redact(v) for v in value]
            return value
        provider_sources[jid]=dict(id=jid,available=True,
            metadata={k:job.get(k) for k in ('kind','provider','origin','status','payload_sha256','cost_actual','cost_estimate','dispatch_count')},
            generation_brief=redact(job.get('request_brief')),
            hidden_provider_settings='omitted',artifact_hashes={k:job.get(k) for k in ('request_artifact','response_artifact')},
            raw_artifacts='not packaged; structured generation brief and evidence pixels retained')
    return dict(runs=runs,revisions=revisions,tasks=tasks,evaluations=evaluations,feedback=feedback,
                events=events,interventions=marks,completions=completions,frames=frames,
                registrations=registrations,assets=assets,provider_sources=provider_sources,source_records=source_records)


def _asset_reasons(asset,policy,assets=None,seen=None,provider_sources=None):
    reasons=[]
    if asset['rights'] not in policy['rights_allow']:reasons.append('rights_not_permitted')
    if asset['source_kind']=='procedural' and not policy['include_procedural_positives']:reasons.append('procedural_not_opted_in')
    if asset.get('origin') in {'unknown','simulated','simulated_transport','synthetic-fixture'} or 'simulated' in asset.get('origin',''):
        reasons.append('unknown_or_simulated_origin')
    if asset.get('source_job_id') and provider_sources is not None:
        provider=provider_sources.get(asset['source_job_id'],{})
        if not provider.get('available') or provider.get('metadata',{}).get('origin','unknown')=='unknown' or 'simulated' in str(provider.get('metadata',{}).get('origin','unknown')):
            reasons.append('source_job_unknown_or_simulated')
    if asset['source_kind']=='derived' and not asset.get('parent_asset_ids'):reasons.append('unresolved_derived_ancestry')
    if assets is not None:
        seen=seen or set()
        if asset['id'] in seen:return reasons+['cyclic_ancestry']
        for parent in asset.get('parent_asset_ids',[]):
            if parent not in assets or _asset_reasons(assets[parent],policy,assets,seen|{asset['id']},provider_sources):
                reasons.append('derivation_parent_excluded')
    return reasons


def _revision_labels(graph,policy):
    labels={}
    for rid,revision in graph['revisions'].items():
        run=graph['runs'][revision['run_id']];evaluation=graph['evaluations'][f'evaluation:{rid}']
        task=graph['tasks'][revision['task_id']]
        reasons=[]
        if not evaluation['evidence'].get('evaluator_identity'):reasons.append('legacy_evaluator_identity_incomplete')
        if evaluation['technical_status']!='pass' or evaluation['coverage']!='complete':reasons.append('required_checks_not_complete_and_passing')
        if run['current_revision_id']!=rid or run['lifecycle']!='completed':reasons.append('not_current_completed_output')
        if any(m['run_id']==run['id'] and m['correction']['status'] not in {'resolved','cancelled'} for m in graph['interventions'].values()):
            reasons.append('unresolved_human_correction')
        decision=graph['events'].get(run.get('human_decision_id',''))
        approved=bool(decision and decision['source']=='human' and decision['event']=='approve'
                      and decision['revision_id']==rid and decision['evaluation_id']==evaluation['id'])
        controls=[graph['assets'][aid] for aid in [i['asset_id'] for i in task['spec']['inputs']]+(task['spec'].get('source_correspondence') or {}).get('frame_asset_ids',[])]
        if any(_asset_reasons(a,policy,graph['assets'],provider_sources=graph['provider_sources']) for a in controls):reasons.append('conditioning_input_excluded')
        human=approved and not reasons
        auto=(not reasons and task['spec']['completion']['id']=='technical-unreviewed-v1'
              and policy.get('include_automatically_verified',False))
        labels[rid]=dict(human=human,automatic=auto,reasons=reasons,
                         creative_status=run['creative_status'] if run['current_revision_id']==rid else 'historical_judgment_in_events')
    return labels


def _families(graph,project,asset_files=None):
    parent={rid:rid for rid in graph['revisions']}
    def find(k):
        while parent[k]!=k:parent[k]=parent[parent[k]];k=parent[k]
        return k
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b:parent[b]=a
    owners={};dhashes=[]
    for rid,revision in graph['revisions'].items():
        run=graph['runs'][revision['run_id']];task=graph['tasks'][revision['task_id']]
        keys=[('animation',run['project_id'],run['animation_id'])]
        aids=revision['frame_asset_ids']+[i['asset_id'] for i in task['spec']['inputs']]+(task['spec'].get('source_correspondence') or {}).get('frame_asset_ids',[])
        for aid in aids:
            asset=graph['assets'][aid];keys.append(('pixel',asset.get('pixel_sha256') or asset['byte_sha256']))
            keys.extend(('lineage',p) for p in [aid]+asset.get('parent_asset_ids',[]))
            blob=(Path(project)/asset_files[aid] if asset_files is not None and aid in asset_files
                  else S.blob_path(project,asset['byte_sha256']))
            if blob.is_file():
                with Image.open(blob) as im:
                    # Conservative near-duplicate split grouping, never a quality score.
                    import numpy as np
                    gray=np.asarray(im.convert('L').resize((9,8)))
                    bits=(gray[:,1:]>gray[:,:-1]).ravel()
                    dhash=sum(int(bit)<<i for i,bit in enumerate(bits))
                    dhashes.append((rid,dhash))
        for key in keys:
            if key in owners:union(rid,owners[key])
            else:owners[key]=rid
        if revision.get('parent_revision_id') in parent:union(rid,revision['parent_revision_id'])
    # Compare each revision's unique fingerprints to reduce repeated-frame work.
    seen={};buckets={}
    for rid,dhash in dict.fromkeys(dhashes):
        if dhash in seen:
            union(rid,seen[dhash]);continue
        # Distance <=4 implies an identical segment in one of five disjoint partitions.
        keys=[(i,(dhash>>(i*13)) & ((1<<13)-1)) for i in range(5)]
        candidates=set().union(*(buckets.get(key,set()) for key in keys))
        for previous in candidates:
            if (dhash^previous).bit_count()<=4:union(rid,seen[previous])
        seen[dhash]=rid
        for key in keys:buckets.setdefault(key,set()).add(dhash)
    groups={}
    for rid in parent:groups.setdefault(find(rid),[]).append(rid)
    return {rid:E.digest(sorted(group)) for group in groups.values() for rid in group}


def plan(project,con,rids,policy):
    if policy.get('agent_export_policy',POLICY)!=POLICY:raise ValueError('unsupported agent export policy')
    for option in ('include_procedural_positives','include_automatically_verified'):
        if type(policy.get(option,False)) is not bool:raise ValueError(f'{option} must be a boolean')
    if not isinstance(policy.get('rights_allow'),list) or any(not isinstance(r,str) for r in policy['rights_allow']):raise ValueError('rights_allow must be a list of rights labels')
    graph=closure(con,rids)
    if len(graph['frames'])>20000:raise ValueError('export closure exceeds 20000-frame bound; select fewer runs')
    labels=_revision_labels(graph,policy);families=_families(graph,project)
    splits={rid:'unsplit' for rid in graph['revisions']}
    for split,selected in policy.get('split',{}).items():
        if split not in {'train','dev','test'}:raise ValueError('unsupported split name')
        for rid in selected:
            matching=[r for r,v in graph['revisions'].items() if rid in {r,v['run_id']}]
            if not matching:raise ValueError(f'split member not in selected closure: {rid}')
            for r in matching:
                if splits[r]!='unsplit' and splits[r]!=split:raise ValueError('revision appears in multiple splits')
                splits[r]=split
    conflicts={fam for fam in set(families.values()) if len({splits[r] for r in splits if families[r]==fam and splits[r]!='unsplit'})>1}
    if conflicts and policy.get('split_policy')=='strict':raise ValueError('related/near-duplicate family straddles requested splits')
    asset_files={};withheld=[]
    for aid,asset in graph['assets'].items():
        blob=S.blob_path(project,asset['byte_sha256'])
        if asset['rights'] not in policy['rights_allow']:
            withheld.append(dict(asset_id=aid,reason='rights_not_permitted'));continue
        if not blob.is_file() or _h(blob.read_bytes())!=asset['byte_sha256']:
            withheld.append(dict(asset_id=aid,reason='missing_or_changed_bytes'));continue
        asset_files[aid]='closure/blobs/'+asset['byte_sha256']
    exclusions=[];membership=[]
    for rid,revision in graph['revisions'].items():
        label=labels[rid]
        task=graph['tasks'][revision['task_id']]
        control_ids=[i['asset_id'] for i in task['spec']['inputs']]+(task['spec'].get('source_correspondence') or {}).get('frame_asset_ids',[])
        if revision['run_id'] not in {graph['revisions'][r]['run_id'] for r in rids}:
            label=dict(label,human=False,automatic=False,reasons=label['reasons']+['source_dependency_not_selected_for_training'])
        full_assets_available=all(a in asset_files for a in revision['frame_asset_ids']+control_ids)
        for fid in revision['frame_instance_ids']:
            frame=graph['frames'][fid];asset=graph['assets'][frame['asset_id']]
            reasons=list(label['reasons'])+_asset_reasons(asset,policy,graph['assets'],provider_sources=graph['provider_sources'])
            if not full_assets_available:reasons.append('required_pixels_withheld_or_unavailable')
            if families[rid] in conflicts:reasons.append('family_split_conflict')
            human=label['human'] and not reasons;auto=label['automatic'] and not reasons
            view='human_accepted' if human else 'automatically_verified' if auto else 'research' if frame['asset_id'] in asset_files else 'withheld'
            if not human:exclusions.append(dict(frame_instance_id=fid,revision_id=rid,reasons=reasons+([] if label['human'] else ['no_current_exact_human_acceptance'])))
            membership.append(dict(frame_instance_id=fid,revision_id=rid,view=view,asset_id=frame['asset_id'],
                label_source='human' if human else 'technical_policy' if auto else 'unaccepted_evidence',
                creative_status=label['creative_status'],family=families[rid],split=splits[rid],
                reasons=reasons,evaluation_id=f'evaluation:{rid}',
                evidence_digest=graph['evaluations'][f'evaluation:{rid}']['evidence_digest'],
                completion_policy=task['spec']['completion']['id'],
                assumption_sources=sorted({r['source'] for r in task['spec'].get('region_observations',[])+task['spec'].get('temporal_observations',[])+((task['spec'].get('scene') or {}).get('features',[]))+((task['spec'].get('scene') or {}).get('camera',[]))+((task['spec'].get('scene') or {}).get('events',[]))}),
                byte_sha256=asset['byte_sha256'],pixel_sha256=asset.get('pixel_sha256'),
                rights=asset['rights'],origin=asset.get('origin','unknown'),source_kind=asset['source_kind']))
    return graph,membership,asset_files,withheld,exclusions


def preview(project,rids,policy=None):
    from ...v3.services import loop
    from .snapshot import default_policy
    policy=default_policy(policy);con=loop.connect(project)
    try:
        con.execute('BEGIN')
        graph,membership,asset_files,withheld,exclusions=plan(project,con,rids,policy)
        return dict(schema_version='3.0',policy=policy,counts={view:sum(m['view']==view for m in membership) for view in ('human_accepted','automatically_verified','research','withheld')},
                    trajectories=sum(bool(r.get('parent_revision_id')) for r in graph['revisions'].values()),
                    runs=list(graph['runs']),revisions=list(graph['revisions']),exclusions=exclusions,withheld=withheld,
                    validation='Pixels and labels are revalidated against a pinned database snapshot before atomic publication.')
    finally:con.close()


def build_into(project,name,rids,out,policy,digest,con):
    con.execute('BEGIN')
    graph,membership,asset_files,withheld,exclusions=plan(project,con,rids,policy)
    out=Path(out);used=set()
    def write(rel,value):
        p=out/rel;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(value if isinstance(value,str) else json.dumps(value,sort_keys=True,indent=2))
    write('.framebound-output',{'tool':'framebound-export-snapshot','snapshot':name,'dataset_version':VERSION})
    for table,records in graph.items():write(f'closure/{table}.jsonl',''.join(json.dumps(row,sort_keys=True)+'\n' for row in records.values()))
    for aid,rel in asset_files.items():
        path=out/rel;path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():path.write_bytes(S.blob_path(project,graph['assets'][aid]['byte_sha256']).read_bytes())
    write('closure/asset_files.json',asset_files);write('closure/withheld.json',withheld)
    write('closure/conditioning.json',{'schema_version':'3.0','tasks':graph['tasks'],'motion_guides':{},
                                      'asset_resolution':'closure/asset_files.json; resolve saved evidence asset IDs through this portable index'})
    coco_images=[];coco_annotations=[];views={v:[] for v in ('human_accepted','automatically_verified','research')}
    folders={'human_accepted':'hf','automatically_verified':'automatically_verified','research':'research'}
    for index,member in enumerate(membership,1):
        view=member['view'];aid=member['asset_id'];rel=asset_files.get(aid)
        if not rel:continue
        asset=graph['assets'][aid]
        with Image.open(out/rel) as im:
            im.load();sil=_silhouette_records(im)
        coco_images.append(dict(id=index,file_name='../'+rel,width=asset['width'],height=asset['height']))
        coco_annotations.append(dict(id=index,image_id=index,category_id=0,segmentation=_rle(sil['mask'],*sil['size']),
                                     area=sil['area'],bbox=[sil['bbox'][0],sil['bbox'][1],sil['bbox'][2]-sil['bbox'][0],sil['bbox'][3]-sil['bbox'][1]],iscrowd=0))
        folder=folders[view];filename='data/'+_safe_name(member['frame_instance_id'],used)+'.png'
        target=out/folder/filename;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((out/rel).read_bytes())
        views[view].append(dict(member,file_name=filename))
    for view,folder in folders.items():write(folder+'/metadata.jsonl',''.join(json.dumps(row,sort_keys=True)+'\n' for row in views[view]))
    write('membership.jsonl',''.join(json.dumps(row,sort_keys=True)+'\n' for row in membership))
    write('coco/annotations.json',dict(images=coco_images,annotations=coco_annotations,categories=[dict(id=0,name='subject',supercategory='subject')]))
    temporal=[];trajectories=[]
    for rid,revision in graph['revisions'].items():
        spec=graph['tasks'][revision['task_id']]['spec'];evaluation=graph['evaluations'][f'evaluation:{rid}']
        temporal.append(dict(clip_revision_id=rid,task_id=revision['task_id'],run_id=revision['run_id'],holds=spec['timing']['holds'],
            ticks_per_second=spec['timing']['ticks_per_second'],total_ticks=sum(spec['timing']['holds']),loop=spec['loop'],
            frames=[dict(graph['frames'][fid],file=asset_files.get(graph['frames'][fid]['asset_id'])) for fid in revision['frame_instance_ids']],
            evaluation_id=evaluation['id'],technical_status=evaluation['technical_status'],coverage=evaluation['coverage'],
            time_map=spec.get('source_correspondence'),traces={'missing':['world_positions','tracking']},
            generation_metadata=revision.get('generation_metadata')))
        parent=revision.get('parent_revision_id')
        if parent:
            before=graph['evaluations'][f'evaluation:{parent}'];old={r['id']:r for r in before['results']}
            after={r['id']:r for r in evaluation['results']}
            targeted=graph['feedback'][revision['targeted_feedback_id']]
            target_ids={t['check_id'] for t in targeted['targets']}
            trajectories.append(dict(parent_revision_id=parent,candidate_revision_id=rid,task_id=revision['task_id'],run_id=revision['run_id'],
                feedback_id=revision['targeted_feedback_id'],changed_slots=revision['changed_slots'],
                before_evaluation_id=before['id'],after_evaluation_id=evaluation['id'],
                targeted_changes=[dict(check_id=k,before=old.get(k,{}).get('outcome','subjective'),after=after.get(k,{}).get('outcome','unresolved')) for k in sorted(target_ids)],
                regressions=[k for k,r in old.items() if r['outcome']=='pass' and after.get(k,{}).get('outcome') not in {'pass','not_applicable'}],
                overall_outcome=evaluation['technical_status'],human_resolution='see exact intervention/events records'))
    for rel,data in [('temporal.jsonl',temporal),('trajectories.jsonl',trajectories),('preferences.jsonl',[]),('weak_preferences.jsonl',[])]:
        write(rel,''.join(json.dumps(row,sort_keys=True)+'\n' for row in data))
    write('README.md','# Framebound agent trajectories\n\nVersion 3 requires explicit reader support. `hf/` contains exact human-accepted positives only; `automatically_verified/` is a separate technical-policy view. Research/withheld data retain rights, source and missing-evidence labels. No preference pairs are inferred. Snapshot transport does not grant training rights. Missing generation metadata remains null. Controlled declared-region measurements do not certify arbitrary creative quality.\n')
    files={str(p.relative_to(out)):_h(p.read_bytes()) for p in out.rglob('*') if p.is_file()}
    manifest=dict(snapshot=name,dataset_version=VERSION,schemas={'domain':'3.0'},reader_capabilities=['agent-tasks-v3','honest-label-sources-v1','optional-input-closure-v1']+(['source-correspondence-v1'] if graph['source_records'] else [])+(['declared-color-camera-tracks-v1'] if any(t['spec'].get('scene') for t in graph['tasks'].values()) else []),
        inputs_digest=digest,clip_revisions=rids,policy=dict(policy,agent_export_policy=POLICY),files=files,exclusions=exclusions,
        families={m['revision_id']:m['family'] for m in membership},split_semantics='animation/derivation/shared-input/exact-pixel and 64-bit dHash distance <=4 components; conservative grouping only, not quality judgment',
        counts=dict(images=len(coco_images),annotations=len(coco_annotations),positives=len(views['human_accepted']),automatically_verified=len(views['automatically_verified']),
                    research=len(views['research']),withheld=sum(m['view']=='withheld' for m in membership),preferences=0,weak_preferences=0,temporal=len(temporal),trajectories=len(trajectories)))
    write('manifest.json',manifest)
    return manifest
