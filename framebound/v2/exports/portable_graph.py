"""Validate portable lineage, policy and artifact relationships without a live DB."""
import hashlib
import io
import json
from .. import domain as D
from ..media.canonical import canonical_pixels,pixel_sha256
from PIL import Image


def check_graph(snap,manifest,issues):
    def records(name):
        return [json.loads(line) for line in (snap/'closure'/name).read_text().splitlines() if line.strip()]
    assets={}
    for raw in records('assets.jsonl'):
        asset=D.Asset.model_validate(raw)
        if asset.id in assets:issues.append('duplicate portable asset '+asset.id)
        assets[asset.id]=asset
        blob=snap/'closure'/'blobs'/asset.byte_sha256
        if not blob.is_file() or hashlib.sha256(blob.read_bytes()).hexdigest()!=asset.byte_sha256:
            issues.append('portable asset bytes missing or changed: '+asset.id);continue
        if asset.pixel_sha256:
            try:
                actual=pixel_sha256(canonical_pixels(Image.open(io.BytesIO(blob.read_bytes()))))
                if actual!=asset.pixel_sha256:issues.append('portable asset pixels mismatch: '+asset.id)
            except Exception as exc:issues.append('portable asset undecodable: '+asset.id+': '+str(exc))
    jobs={r['id']:D.Job.model_validate(r) for r in records('jobs.jsonl')}
    operations={r['id']:D.AuthorizedOperation.model_validate(r) for r in records('operations.jsonl')}
    plans={r['id']:D.CompiledAnimationPlan.model_validate(r) for r in records('animation_plans.jsonl')}
    revisions={r['id']:D.ClipRevision.model_validate(r) for r in records('revisions.jsonl')}
    frames={r['id']:D.FrameInstance.model_validate(r) for r in records('frames.jsonl')}
    conditioning=json.loads((snap/'closure'/'conditioning.json').read_text())
    approvals=conditioning['approvals'];guides=conditioning['motion_guides']
    for aid,ap in approvals.items():
        D.ReferenceApproval.model_validate(ap)
        if ap['motion_guide_id'] not in guides:issues.append('portable approval guide absent: '+aid)
        for assetid,sha in ap['asset_hashes'].items():
            if assetid not in assets or assets[assetid].byte_sha256!=sha:issues.append('portable approved control differs: '+assetid)
    for job in jobs.values():
        for key in ('request_artifact','response_artifact'):
            sha=getattr(job,key)
            if sha and not (snap/'closure'/'blobs'/sha).is_file():issues.append('portable provider artifact absent: '+job.id)
        for aid in job.output_asset_ids:
            # Only reachable outputs are necessarily packaged; unused alternatives remain outside.
            if aid in assets and assets[aid].source_job_id not in (None,job.id):issues.append('provider output has foreign source job: '+aid)
    for rev in revisions.values():
        if rev.parent_revision_id and rev.parent_revision_id not in revisions:issues.append('portable revision parent missing: '+rev.id)
        for fid in rev.frame_instance_ids:
            fi=frames.get(fid)
            if fi is None or fi.asset_id not in assets:issues.append('portable frame unresolved: '+fid)
    for op in operations.values():
        plan=plans.get(op.compiled_plan_id)
        if plan is None:issues.append('portable operation plan absent: '+op.id);continue
        if op.slot>=len(plan.controls) or plan.controls[op.slot].scope_sha256!=op.scope_sha256:issues.append('portable operation scope differs: '+op.id)
        if plan.reference_approval_id not in approvals:issues.append('portable operation approval absent: '+op.id)
        if op.input_asset_id not in assets or (op.status in ('committed','rendered','evaluated') and op.output_asset_id not in assets):issues.append('portable operation pixels absent: '+op.id)
    ancestry={}
    def visit(aid,active):
        if aid in active:raise ValueError('cyclic portable ancestry: '+aid)
        if aid in ancestry:return ancestry[aid]
        asset=assets.get(aid)
        if asset is None:raise ValueError('missing portable ancestor '+aid)
        rights={asset.rights};origins={asset.origin};problems=[]
        if asset.source_kind=='procedural':origins.add('procedural')
        if 'simulated' in asset.lineage:origins.add('simulated-transport')
        if asset.source_job_id:
            job=jobs.get(asset.source_job_id)
            if job is None:problems.append('missing source job')
            else:origins.add(job.origin)
        if asset.source_kind=='derived' and not asset.parent_asset_ids:problems.append('unresolved derived ancestry')
        for parent in asset.parent_asset_ids:
            r,o,p=visit(parent,active|{aid});rights.update(r);origins.update(o);problems.extend(p)
        ancestry[aid]=(rights,origins,problems);return ancestry[aid]
    for aid in assets:visit(aid,set())
    events=sorted(records('events.jsonl'),key=lambda e:(e['created_at'],e['id']))
    packets={p['id']:p for p in records('packets.jsonl')}
    evaluations={}
    for evaluation in sorted(records('evaluations.jsonl'),key=lambda e:(e['created_at'],e['id'])):
        evaluations[evaluation['clip_revision_id']]=evaluation
    tasks=records('tasks.jsonl')
    allowed=set(manifest['policy']['rights_allow'])
    for line in (snap/'hf'/'metadata.jsonl').read_text().splitlines():
        if not line.strip():continue
        meta=json.loads(line);aid=meta['asset_id'];asset=assets.get(aid)
        if asset is None:issues.append('positive missing portable asset: '+aid);continue
        rid=meta['clip'];decision=None
        for event in events:
            if event['actor_type']=='reviewer' and event['clip_revision_id']==rid and event['action'] in ('approve','reject','needs_changes','reopen_issue'):
                decision=event
        if decision is None or decision['action']!='approve':issues.append('positive lacks current reviewer approval: '+rid)
        else:
            packet=packets.get(decision.get('packet_id'));evaluation=evaluations.get(rid)
            if packet is None or evaluation is None or packet['clip_revision_id']!=rid or packet['evaluation_id']!=evaluation['id']:
                issues.append('positive approval is not bound to exact evaluation: '+rid)
            elif evaluation['technical_status']!='pass' or evaluation['coverage_status']!='complete':
                issues.append('positive lacks complete passing evidence: '+rid)
        chain=set();cur=revisions.get(rid)
        while cur and cur.id not in chain:
            chain.add(cur.id);cur=revisions.get(cur.parent_revision_id)
        if any(t['baseline_revision_id'] in chain and t['status'] not in ('resolved','cancelled') for t in tasks):
            issues.append('positive has unresolved lineage task: '+rid)
        rights,origins,problems=ancestry[aid]
        if not rights<=allowed:issues.append('positive ancestor rights disallow training: '+aid)
        if origins & {'simulated-transport','provider-simulated'}:issues.append('simulated ancestry in positives: '+aid)
        if 'procedural' in origins and not manifest['policy']['include_procedural_positives']:issues.append('procedural ancestry in default positives: '+aid)
        if problems:issues.append('positive unresolved provenance: '+aid+': '+str(problems))
        if meta.get('rights')!=asset.rights or meta.get('source_kind')!=asset.source_kind:issues.append('positive metadata differs from provenance: '+aid)
        blob=snap/'hf'/meta['file_name']
        if hashlib.sha256(blob.read_bytes()).hexdigest()!=asset.byte_sha256:issues.append('positive byte identity differs from provenance: '+aid)
    for line in (snap/'preferences.jsonl').read_text().splitlines():
        if not line.strip():continue
        preference=json.loads(line)
        for key in ('chosen_revision','rejected_revision'):
            revision=revisions.get(preference[key])
            if revision is None:issues.append('preference revision is not portable');continue
            for fid in revision.frame_instance_ids:
                rights,origins,problems=ancestry[frames[fid].asset_id]
                if not rights<=allowed or problems or origins & {'simulated-transport','provider-simulated'} or ('procedural' in origins and not manifest['policy']['include_procedural_positives']):
                    issues.append('preference pixels violate ancestry policy: '+fid)
    receipts={}
    if (snap/'closure'/'reconciliations.jsonl').is_file():
        receipts={r['id']:D.ProviderReconciliation.model_validate(r) for r in records('reconciliations.jsonl')}
    for receipt in receipts.values():
        job=jobs.get(receipt.job_id)
        if job is None or receipt.request_sha256!=job.frozen_request_sha256:issues.append('portable receipt request differs: '+receipt.id)
        if receipt.artifact_sha256 and not (snap/'closure'/'blobs'/receipt.artifact_sha256).is_file():issues.append('portable receipt artifact absent: '+receipt.id)
    annotation_rows={a['id']:a for a in records('annotations.jsonl')}
    for ev in records('evaluations.jsonl'):
        revision=revisions.get(ev['clip_revision_id'])
        if revision is None:issues.append('portable evaluation revision missing');continue
        bound=json.loads((snap/'closure'/'blobs'/ev['evidence_manifest_sha256']).read_text())
        approval_id=(bound.get('authority') or {}).get('approval_id')
        revoked={e.get('reference_approval_id') for e in events if e.get('action')=='revoke_reference' and e.get('actor_type')=='reviewer'}
        # A revoked historical evaluation remains inspectable; current positives
        # below must use an active captured authority.
        if approval_id in revoked and any(json.loads(line).get('clip')==revision.id for line in (snap/'hf'/'metadata.jsonl').read_text().splitlines() if line.strip()):
            issues.append('positive uses revoked reference authority: '+revision.id)
        for annotation in bound.get('annotations',[]):
            raw=snap/'closure'/'blobs'/annotation['sha256']
            if not raw.is_file() or hashlib.sha256(raw.read_bytes()).hexdigest()!=annotation['sha256']:
                issues.append('portable annotation bytes absent or altered: '+annotation['id'])
            elif annotation['id'] not in annotation_rows or json.loads(raw.read_bytes())!=annotation_rows[annotation['id']]:
                issues.append('portable annotation record differs from measured input: '+annotation['id'])
        measured=bound.get('frames',[])
        if len(measured)!=len(revision.frame_instance_ids):issues.append('portable evaluation frame count mismatch');continue
        for index,fid in enumerate(revision.frame_instance_ids):
            frame=frames[fid];asset=assets[frame.asset_id]
            if measured[index].get('byte_sha256')!=asset.byte_sha256 or measured[index].get('pixel_sha256')!=asset.pixel_sha256:
                issues.append('portable evaluation pixels differ: '+fid)
    return {'assets':len(assets),'jobs':len(jobs),'operations':len(operations)}
