"""Portable, local detector/editor/preference/sequence/failure datasets."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from .assessment import Assessment, CATEGORIES
from .contracts import canonical, digest, local_path


def _copy(root, relative, output):
    path=local_path(root,relative)
    if not path.is_file(): raise ValueError('missing dataset closure artifact')
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    destination=output/'blobs'/sha
    destination.parent.mkdir(parents=True,exist_ok=True)
    if not destination.exists(): shutil.copyfile(path,destination)
    return dict(file=str(destination.relative_to(output)),sha256=sha)


def build(root, campaign, examples, *, version):
    """Each example carries actual conditioning/prompt closure and scoped labels.

    No preference or positive editor target is inferred from candidate recency.
    Failed/ambiguous corrections remain in failures.jsonl with their evidence.
    """
    if not version or '/' in version or version in {'.','..'}: raise ValueError('safe dataset version required')
    out=local_path(root,f'campaigns/{campaign}/training/{version}')
    out.mkdir(parents=True,exist_ok=True)
    families={}; hashes={}; rows={k:[] for k in ('detection','editing','preference','sequence','failure')}
    for example in examples:
        e=dict(example)
        for identity in [e['family'],*e.get('ancestry',[])]:
            if identity in families and families[identity]!=e['split']: raise ValueError('family/ancestry leakage')
            families[identity]=e['split']
        frames=[_copy(root,p,out) for p in e['frames']]
        if len(frames)!=len(e['holds']) or any(type(h) is not int or h<=0 for h in e['holds']): raise ValueError('native timing mismatch')
        for frame in frames:
            if frame['sha256'] in hashes and hashes[frame['sha256']]!=e['split']: raise ValueError('exact pixels cross splits')
            hashes[frame['sha256']]=e['split']
        common=dict(id=e['id'],family=e['family'],split=e['split'],frames=frames,holds=e['holds'],loop=e['loop'],
            request=_copy(root,e['request_file'],out),conditioning=[_copy(root,p,out) for p in e['conditioning_files']],
            corroborating_assessments=e.get('corroborating_assessments',[]),provenance=e['provenance'],provenance_artifacts=[_copy(root,p,out) for p in e.get('provenance_files',[])],label_source='model',human_acceptance=False)
        assessment=Assessment.model_validate(e['assessment']) if e.get('assessment') else None
        labels=assessment.targets() if assessment else {c:dict(target=0,mask=False,slots=[],source='unknown') for c in CATEGORIES}
        rows['detection'].append(dict(common,labels=labels,assessment=assessment.model_dump(mode='json') if assessment else None))
        rows['sequence'].append(dict(common,acceptance_coverage=labels,quality_claim='Only explicitly assessed categories have labels'))
        outcome=e.get('outcome','unassessed')
        if e.get('baseline_frames'):
            pair=dict(common,baseline_frames=[_copy(root,p,out) for p in e['baseline_frames']],outcome=outcome,
                scope=e.get('scope'),comparison=e.get('comparison'),edit_instruction=e.get('edit_instruction'),authority=e.get('authority'))
            if outcome=='accepted' and e.get('comparison') and e.get('edit_instruction'):
                rows['editing'].append(pair)
            # Ties and ambiguity are retained without fabricating a binary pair.
            if e.get('comparison'):
                rows['preference'].append(dict(pair,preference_target=e.get('preference_target'),
                    binary_training_eligible=outcome in {'accepted','rejected'} and e.get('preference_target') in {'baseline','candidate'} and e['comparison'].get('target_improved') is True and e['comparison'].get('material_regression') is False))
        if outcome not in {'accepted'} or e.get('challenge_negative'):
            rows['failure'].append(dict(common,outcome=outcome,assessment=assessment.model_dump(mode='json') if assessment else None))
    files={}
    for name,data in rows.items():
        raw=b''.join(canonical(row)+b'\n' for row in data)
        path=out/(name+'.jsonl')
        if path.exists() and path.read_bytes()!=raw: raise ValueError('dataset version is immutable')
        path.write_bytes(raw);files[path.name]=hashlib.sha256(raw).hexdigest()
    manifest=dict(schema_version='animation-training-1.0',dataset_version=version,files=files,counts={k:len(v) for k,v in rows.items()},
        categories=CATEGORIES,generator_training_status='ready-to-consume local data; no hosted-generator fine-tuning job claimed')
    path=out/'manifest.json';raw=canonical(manifest)
    if path.exists() and path.read_bytes()!=raw: raise ValueError('dataset manifest is immutable')
    path.write_bytes(raw)
    validate(out)
    return dict(path=str(out),manifest=manifest)


def validate(path):
    """Verify bytes, path closure, decode and preserve label masks on reload."""
    path=Path(path).resolve();manifest=json.loads((path/'manifest.json').read_text())
    families={}
    for filename,sha in manifest['files'].items():
        file=(path/filename).resolve()
        if not file.is_relative_to(path) or hashlib.sha256(file.read_bytes()).hexdigest()!=sha: raise ValueError('dataset hash mismatch')
        for line in file.read_text().splitlines():
            row=json.loads(line)
            if row['family'] in families and families[row['family']]!=row['split']: raise ValueError('dataset family leakage')
            families[row['family']]=row['split']
            for artifact in [*row['frames'],*row['conditioning'],row['request'],*row.get('baseline_frames',[]),*row.get('provenance_artifacts',[])]:
                file=(path/artifact['file']).resolve()
                if not file.is_relative_to(path) or hashlib.sha256(file.read_bytes()).hexdigest()!=artifact['sha256']: raise ValueError('dataset closure mismatch')
            from PIL import Image
            for frame in row['frames']:
                with Image.open(path/frame['file']) as image: image.verify()
    return dict(ok=True,counts=manifest['counts'])


def export_campaign(root,campaign,*,version='1'):
    """Close actual campaign revisions, raw receipts and conditioning locally."""
    from ...v2 import storage as S
    from .. import provenance as P
    from ..services import loop,tasks
    from .ledger import Ledger
    root=Path(root).resolve();ledger=Ledger(root);config=ledger.config(campaign)
    folder=local_path(root,f'campaigns/{campaign}');project=str(folder/'project')
    con=loop.connect(project)
    try:
        revisions=[json.loads(r['data']) for r in con.execute('SELECT data FROM agent_clip_revisions')]
        authorities=[json.loads(r['data']) for r in con.execute('SELECT data FROM agent_auto_authorities')]
        comparisons=[json.loads(r['data']) for r in con.execute('SELECT data FROM agent_auto_comparisons')]
        examples=[]
        def relative_blob(sha):
            return str(S.blob_path(project,sha).resolve().relative_to(root))
        for revision in revisions:
            context=(revision.get('generation_metadata') or {}).get('campaign')
            if not context or context['id']!=campaign:continue
            spec=tasks._get(con,revision['task_id']).spec
            assets=[S.get(con,'assets',aid)[0] for aid in revision['frame_asset_ids']]
            p=P.parse(revision['generation_metadata'])
            closure=set(P.blob_hashes(p))
            conditioning=[]
            for event in p.generations:
                for ref in event.conditioning:
                    closure.add(ref.byte_sha256);conditioning.append(relative_blob(ref.byte_sha256))
            request_ids=[e.request_id for e in p.generations if e.request_id]
            request_path=folder/'training'/'closure'/(revision['id']+'.request.json')
            request_path.parent.mkdir(parents=True,exist_ok=True)
            request_path.write_bytes(canonical([json.loads(ledger.request(rid)['request']) for rid in request_ids]))
            assessment=None;corroborating=[]
            for path in sorted((folder/'annotations').glob('*.json')):
                candidate=Assessment.model_validate_json(path.read_bytes())
                if candidate.binding.revision_sha256==digest(revision):
                    evaluation=loop.get_in(con,'agent_evaluations','evaluation:'+revision['id'])
                    from .assessment import Binding
                    binding=Binding(request_sha256=tasks._get(con,spec.id).spec_sha256,revision_sha256=digest(revision),
                        timing_sha256=digest(spec.timing.model_dump(mode='json')),evaluation_sha256=digest(evaluation))
                    candidate.validate_evidence(binding,spec.timing.holds,(spec.canvas.width,spec.canvas.height))
                    if assessment is None:assessment=candidate.model_dump(mode='json')
                    corroborating.append(candidate.model_dump(mode='json'))
            authority=next((a for a in authorities if a['candidate_revision_id']==revision['id']),None)
            pair=next((c for c in comparisons if c['candidate_revision_id']==revision['id'] and c['comparison']),None)
            baseline=loop.get_in(con,'agent_clip_revisions',authority['baseline_revision_id']) if authority else None
            raw_files=[]
            with ledger.db() as db:
                receipts=[dict(r) for r in db.execute('SELECT id,receipt FROM requests WHERE campaign=? AND case_id=? AND receipt IS NOT NULL',(campaign,context['case_id']))]
            for receipt in receipts:
                sha=json.loads(receipt['receipt'])['sha256'];raw_files.append(str((folder/'originals'/sha).relative_to(root)))
            preference=None
            if pair and pair['comparison']['preference'] in {'A','B'}:
                chosen=pair['assignment'][pair['comparison']['preference']]
                preference='candidate' if chosen==pair['candidate_sha256'] else 'baseline'
            examples.append(dict(id=revision['id'],family=context['family'],split=context['split'],frames=[relative_blob(a['byte_sha256']) for a in assets],
                holds=spec.timing.holds,loop=spec.loop,request_file=str(request_path.relative_to(root)),conditioning_files=conditioning,
                provenance=revision['generation_metadata'],provenance_files=[relative_blob(h) for h in sorted(closure)]+raw_files,assessment=assessment,corroborating_assessments=corroborating,
                baseline_frames=[relative_blob(S.get(con,'assets',aid)[0]['byte_sha256']) for aid in baseline['frame_asset_ids']] if baseline else [],
                outcome=authority['status'] if authority else 'unassessed',scope=authority['scope'] if authority else None,
                edit_instruction=authority['instruction'] if authority else None,authority=authority['source'] if authority else None,
                comparison=pair['comparison'] if pair else None,preference_target=preference,
                challenge_negative=next(c.challenge_negative for c in config.cases if c.id==context['case_id'])))
        if not examples:return dict(status='no_generated_examples',exported=0)
        return build(root,campaign,examples,version=version)
    finally:con.close()


def load(path,lane='detection'):
    """Explicit-version reader preserving unknown labels and nonbinary outcomes."""
    if lane not in {'detection','editing','preference','sequence','failure'}:raise ValueError('unknown training objective')
    path=Path(path).resolve();manifest=json.loads((path/'manifest.json').read_text())
    if manifest.get('schema_version')!='animation-training-1.0':raise ValueError('unsupported campaign label semantics')
    validate(path)
    from PIL import Image
    rows=[]
    for line in (path/(lane+'.jsonl')).read_text().splitlines():
        metadata=json.loads(line);frames=[]
        for artifact in metadata['frames']:
            with Image.open(path/artifact['file']) as image:frames.append(image.convert('RGBA').copy())
        rows.append(dict(metadata=metadata,frames=frames,request=json.loads((path/metadata['request']['file']).read_text()),
            label_source='model',human_acceptance=False))
    return rows
