"""Deterministic evidence matching; no fuzzy identities or expanded edit scope."""
import unicodedata

VERSION='scoped-corroboration-v1'


def label(value):
    # Formatting normalization only. Synonyms, punctuation and entity aliases
    # are deliberately not inferred from free-form teacher prose.
    return ' '.join(unicodedata.normalize('NFC',value or '').split()).casefold()


def compare(first,second):
    reasons=[]
    if first.category!=second.category:reasons.append('category_differs')
    stable_canvas=(first.category==second.category=='artifacts' and first.subject_id==second.subject_id=='scene_canvas')
    if not stable_canvas and label(first.subject)!=label(second.subject):reasons.append('subject_identity_unresolved')
    if label(first.part)!=label(second.part):reasons.append('part_identity_differs')
    if set(first.slots)!=set(second.slots):reasons.append('slot_scope_differs')
    if first.roi!=second.roi:reasons.append('spatial_scope_differs')
    if max(first.tick_range[0],second.tick_range[0])>=min(first.tick_range[1],second.tick_range[1]):reasons.append('time_scope_disjoint')
    if second.visibility!='supported':reasons.append('independent_visibility_unsupported')
    if second.severity not in {'material','critical'}:reasons.append('independent_severity_insufficient')
    return dict(matched=not reasons,reasons=reasons,independent_finding_id=second.id)


def audit(assessment,independent):
    targets=sorted((f for f in assessment.findings if f.severity in {'material','critical'} and f.visibility=='supported'),
        key=lambda f:(f.severity!='critical',f.id))
    independent_execution=(assessment.binding==independent.binding and
        assessment.provenance.execution_id!=independent.provenance.execution_id and
        assessment.provenance.rubric_sha256!=independent.provenance.rubric_sha256)
    rows=[]
    for target in targets:
        comparisons=[compare(target,g) for g in independent.findings]
        matches=[c for c in comparisons if c['matched']]
        rows.append(dict(finding_id=target.id,category=target.category,
            matched=independent_execution and bool(matches),comparisons=comparisons,
            reason='corroborated' if independent_execution and matches else 'execution_or_binding_not_independent' if not independent_execution else 'no_independent_finding' if not comparisons else 'no_matching_evidence'))
    return dict(version=VERSION,targets=rows,eligible_finding_ids=[r['finding_id'] for r in rows if r['matched']])


def replay(root,campaign):
    """Read-only audit of all saved pairs. Never modifies labels or run authority."""
    import json
    from collections import Counter
    from pathlib import Path
    from .assessment import Assessment
    from .contracts import canonical,digest,local_path
    from .ledger import Ledger
    ledger=Ledger(root);folder=local_path(root,f'campaigns/{campaign}')
    groups={};quarantined=set()
    for path in sorted((folder/'annotations').glob('*.json')):
        if path.name.endswith('-normalization.json'):continue
        if path.name.endswith('-quarantine.json'):
            quarantined.add(path.name.removesuffix('-quarantine.json'));continue
        a=Assessment.model_validate_json(path.read_bytes())
        req=json.loads(ledger.request(a.provenance.execution_id)['request'])
        groups.setdefault(req['case_id'],{})[req['attempt']]=a
    counts=Counter();rows=[]
    for cid,group in sorted(groups.items()):
        first=group.get(0)
        if not first:continue
        targets=[f for f in first.findings if f.severity in {'material','critical'} and f.visibility=='supported']
        if not targets:continue
        second=group.get(1)
        result=audit(first,second) if second else None
        if second is None:reason='missing_independent_assessment'
        elif second.provenance.execution_id in quarantined:reason='independent_response_quarantined'
        elif result['eligible_finding_ids']:reason='corroborated'
        elif not second.findings:reason='independent_assessment_disagrees_or_abstains'
        else:
            near=any(f.category==g.category and set(f.slots)&set(g.slots) and g.visibility=='supported' and g.severity in {'material','critical'}
                for f in targets for g in second.findings)
            reason='overlapping_category_requires_identity_and_scope_resolution' if near else 'different_defect_or_scope'
        counts[reason]+=1
        rows.append(dict(case_id=cid,classification=reason,evidence=result,
            first_execution_id=first.provenance.execution_id,second_execution_id=second.provenance.execution_id if second else None,
            limitation='Category/window overlap alone never establishes same defect, subject or edit permission.'))
    report=dict(version=VERSION,campaign=campaign,counts=dict(counts),cases=rows,model_calls=0,
        authority_created=False,terminal_results_changed=False,eligible_cases=[r['case_id'] for r in rows if r['classification']=='corroborated'])
    path=folder/'reports'/('corroboration-audit-'+digest(report)[:16]+'.json')
    path.parent.mkdir(parents=True,exist_ok=True);raw=canonical(report)
    if path.exists() and path.read_bytes()!=raw:raise ValueError('immutable audit artifact differs')
    path.write_bytes(raw)
    return dict(path=str(path),report=report)
