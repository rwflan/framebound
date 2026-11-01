"""Evidence-linked local advisory retrieval. It never grants repair authority."""
import json
from pathlib import Path

from .assessment import Assessment, CATEGORIES
from .contracts import canonical, digest, local_path
from .export import load


def build(root, campaign, *, version, dataset_version=None):
    from .contracts import Identity
    Identity(id=version)
    dataset_version=dataset_version or version
    Identity(id=dataset_version)
    dataset = local_path(root, f'campaigns/{campaign}/training/{dataset_version}')
    entries = []
    examples=load(dataset)
    from .leakage import exclusions
    excluded=exclusions(examples,dataset)
    from .ledger import Ledger
    isolated=Ledger(root).isolated_families()
    for example in examples:
        row = example['metadata']
        if isolated.intersection([row['family'],*row.get('ancestry',[])]):continue
        if row['id'] in excluded:continue
        if row['split'] != 'train' or not row.get('assessment') or any(r!='original' for r in row.get('rights',['unknown'])):
            continue
        from ..intake import inspect
        if not all(inspect(f)['eligible'] for f in example['frames']):
            continue
        assessment = Assessment.model_validate(row['assessment'])
        common=dict(sequence_id=row.get('sequence_id',row['id']),revision_id=row['id'],family=row['family'],
            provenance=assessment.provenance.model_dump(mode='json'),assessment_sha256=digest(assessment),
            dataset_sha256=digest(json.loads((dataset/'manifest.json').read_text())),evidence_files=row['frames'],
            proposed_correction=None,preservation_requirements=None,actual_outcome='unlinked',experiences=[],
            label_source='model',human_acceptance=False)
        for f in assessment.findings:
            entry=dict(common,record_kind='observed_finding',category=f.category,subject=f.subject,part=f.part,
                slots=f.slots,tick_range=f.tick_range,roi=f.roi,observed=f.observed,expected=f.expected,
                counterexamples=f.counterexamples,visibility=f.visibility,severity=f.severity)
            entries.append(dict(entry,experiences=[],id=digest(entry)))
        for coverage in assessment.coverage:
            if coverage.status!='absent_within_assessed_scope' or not coverage.slots:continue
            ticks=[0]
            for hold in row['holds']:ticks.append(ticks[-1]+hold)
            entry=dict(common,record_kind='assessed_negative',category=coverage.category,subject=None,part=None,
                slots=coverage.slots,tick_range=None,tick_ranges=[[ticks[s],ticks[s+1]] for s in sorted(coverage.slots)],roi=None,
                observed='No defect reported within this explicitly assessed scope',expected=None,
                counterexamples=coverage.limitations,visibility='assessed_scope',severity=None,
                limitation='Scoped model-negative evidence; not a whole-clip quality pass or a new defect finding.')
            entries.append(dict(entry,experiences=[],id=digest(entry)))
    # Retain successful, failed and ambiguous corrections as distinct experiences.
    for lane in ('editing','preference','failure'):
        for example in load(dataset,lane):
            row=example['metadata']
            if row['split']!='train':continue
            for entry in entries:
                if entry['revision_id'] in {row['id'],row.get('baseline_revision_id')} and row.get('comparison'):
                    experience=dict(candidate_revision_id=row['id'],outcome=row.get('outcome','unassessed'),
                        instruction=row.get('edit_instruction'),scope=row.get('scope'),comparison=row['comparison'])
                    if experience not in entry['experiences']:entry['experiences'].append(experience)
                    entry.update(proposed_correction=row.get('edit_instruction'),
                        preservation_requirements=row.get('scope'),actual_outcome=row.get('outcome','unassessed'),
                        comparison=row['comparison'])
    # IDs bind the complete entry, including observed outcomes.
    entries=[dict(e,id=digest({k:v for k,v in e.items() if k!='id'})) for e in entries]
    value=dict(schema_version='animation-knowledge-2.0',campaign=campaign,dataset_version=dataset_version,
               entries=entries,authority='advisory_only',excluded_splits=['validation','test'])
    path=local_path(root,f'campaigns/{campaign}/knowledge/{version}.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=canonical(value)
    if path.exists() and path.read_bytes()!=raw:raise ValueError('knowledge version is immutable')
    path.write_bytes(raw)
    return dict(path=str(path),entries=len(entries),sha256=digest(value),authority='advisory_only')


def retrieve(root,campaign,*,version,categories,exclude_families=(),limit=3):
    if not categories or any(c not in CATEGORIES for c in categories):raise ValueError('supported categories required')
    if type(limit) is not int or not 1<=limit<=10:raise ValueError('retrieval limit must be 1..10')
    from .contracts import Identity
    Identity(id=version)
    path=local_path(root,f'campaigns/{campaign}/knowledge/{version}.json')
    library=json.loads(path.read_text())
    if library.get('schema_version') not in {'animation-knowledge-1.0','animation-knowledge-2.0'}:
        raise ValueError('unsupported knowledge label semantics')
    # Revalidate closure on use so stale or edited evidence is not cited as knowledge.
    dataset=local_path(root,f"campaigns/{campaign}/training/{library['dataset_version']}")
    from .export import validate
    validate(dataset)
    manifest_sha=digest(json.loads((dataset/'manifest.json').read_text()))
    rows=[]
    from .ledger import Ledger
    isolated=Ledger(root).isolated_families()
    for e in library['entries']:
        if e['family'] in isolated:continue
        if e['id']!=digest({k:v for k,v in e.items() if k!='id'}) or e['dataset_sha256']!=manifest_sha:
            raise ValueError('knowledge evidence identity mismatch')
        if e['category'] in categories and e['family'] not in exclude_families:
            rows.append(e)
    rows.sort(key=lambda e:(e['visibility']!='supported',e['actual_outcome']!='accepted',e['id']))
    return dict(schema_version='animation-knowledge-query-2.0',authority='advisory_only',entries=rows[:limit],evidence_root=str(dataset),
                limitation='Retrieved model observations do not validate this candidate or authorize an edit.')
