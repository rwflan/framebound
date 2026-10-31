"""Assessment-only replay of a validated historical snapshot, zero model calls."""
import hashlib
import json
from pathlib import Path

from ...v2.exports.agent_reader import load_model_annotations, load_model_corrections
from .assessment import CATEGORIES
from .contracts import canonical, digest, local_path
from .features import extract
from .learning import experiment
from .transfer import FeatureRow,FeatureShard,preupload


def historical_split(value):
    return {'dev':'train','development':'train','train':'train','validation':'validation','held_out':'test','test':'test'}.get(value)


def replay(root, snapshot, *, name='historical-replay-v1'):
    # Validate and decode through the existing portable consumer. Never rewrite
    # corpus manifests, native frames or the historical project.
    snapshot=Path(snapshot).resolve()
    annotations=load_model_annotations(snapshot);pairs=load_model_corrections(snapshot)
    if not annotations: raise ValueError('no historical model annotations in validated snapshot')
    tasks={r['id']:r for r in map(json.loads,(snapshot/'closure/tasks.jsonl').read_text().splitlines())}
    report_rows=[];feature_rows=[]
    folder=local_path(root,f'campaigns/{name}');folder.mkdir(parents=True,exist_ok=True)
    for row in annotations:
        task=tasks[row['task_id']]['spec'];holds=task['timing']['holds']
        measured=extract(row['frames'],holds,loop=task['loop'])
        judgment=row['judgment'];observations=judgment.get('defects',[])
        # Historical vocabulary is retained, not guessed into a new taxonomy.
        # This replay creates no new semantic labels or negative examples.
        split=historical_split(row['split'])
        if split is not None:
            feature_rows.append(FeatureRow(case_id=digest(row['revision_id']),family_id=digest(row['family']),
                split=split,features=measured['features'].tolist(),targets=[0]*9,assessed=[False]*9))
        report_rows.append(dict(case_id=digest(row['revision_id']),family_id=digest(row['family']),
            state='ambiguous',reason='Historical labels lack the new bounded category/visibility/coverage contract; originals retained.',
            native_frames=len(holds),explicit_observation_count=len(observations),raw_judgment_sha256=digest(judgment),
            learned_coverage='not_assessed_under_new_taxonomy',legacy_model_evidence=judgment,
            measurement_proposals=measured['proposals'],limitations=measured['limitations']))
    shard=FeatureShard(rows=feature_rows);raw,manifest=preupload(shard)
    (folder/'features').mkdir(exist_ok=True)
    (folder/'features/features.json').write_bytes(raw)
    (folder/'features/preupload-manifest.json').write_bytes(canonical(manifest))
    result=experiment(root,name,shard,categories=list(CATEGORIES))
    report=dict(schema_version='historical-assessment-replay-1.0',cases=len(annotations),native_frames=sum(len(r['frames']) for r in annotations),
        correction_pairs=len(pairs),rows=report_rows,model_calls=0,incurred_microdollars=0,remote_bytes_transferred=0,
        training_excluded_unsplit_cases=len(annotations)-len(feature_rows),training=result['card']['gate'],detector_status=result['card']['status'],promoted=False,
        limitation='This replays existing model evidence; it is not a new independent assessment, comparison or measured improvement.')
    (folder/'reports').mkdir(exist_ok=True)
    (folder/'reports/replay.json').write_bytes(canonical(report))
    return {k:v for k,v in report.items() if k!='rows'} | dict(report_path=str(folder/'reports/replay.json'))
