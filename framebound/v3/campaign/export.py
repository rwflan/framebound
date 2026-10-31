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
            provenance=e['provenance'],label_source='model',human_acceptance=False)
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
                    binary_training_eligible=outcome in {'accepted','rejected'} and e.get('preference_target') in {'baseline','candidate'}))
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
            for artifact in [*row['frames'],*row['conditioning'],row['request'],*row.get('baseline_frames',[])]:
                file=(path/artifact['file']).resolve()
                if not file.is_relative_to(path) or hashlib.sha256(file.read_bytes()).hexdigest()!=artifact['sha256']: raise ValueError('dataset closure mismatch')
            from PIL import Image
            for frame in row['frames']:
                with Image.open(path/frame['file']) as image: image.verify()
    return dict(ok=True,counts=manifest['counts'])
