"""Deterministic correction grouping, preserving every original check and authority."""
from .evaluate import digest


def groups(bundle):
    targets=bundle['targets'];parent=list(range(len(targets)))
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    def category(target):
        if target['observation_source']=='human':return 'human:'+target.get('resolution_owner','unknown')
        if target.get('depends_on_check_ids'):return 'candidate'
        return 'recovery' if target['outcome'] in {'error','unmeasured'} else 'candidate'
    def overlap(a,b):
        if not set(a['slots'])&set(b['slots']):return False
        if category(a)!=category(b):return False
        ar,br=a.get('roi'),b.get('roi')
        return ar is None or br is None or (ar['left']<br['right'] and br['left']<ar['right'] and ar['top']<br['bottom'] and br['top']<ar['bottom'])
    for i,target in enumerate(targets):
        for j in range(i):
            if overlap(target,targets[j]):parent[find(i)]=find(j)
    components={}
    for i,target in enumerate(targets):components.setdefault(find(i),[]).append(target)
    output=[]
    for component in components.values():
        slots=sorted({slot for target in component for slot in target['slots']})
        kind=category(component[0]);ids=sorted(target['id'] for target in component)
        output.append(dict(id='correction-group:'+digest(ids)[:16],target_ids=ids,
            priority=min(t['priority'] for t in component),slots=slots,
            tick_ranges=[list(interval) for interval in sorted({tuple(t['tick_range']) for t in component})],
            category='human_correction' if kind.startswith('human:') else 'tool_or_evidence_recovery' if kind=='recovery' else 'candidate_defect',
            suggested_scope='recover_inputs_or_measurements' if kind=='recovery' else 'declared_sequence_or_transition' if len(slots)>1 else 'declared_frame_region',
            verification_checks=sorted({t['check_id'] for t in component}),
            permission='Grouping does not widen task edit scope or saved grants; human resolution owners remain authoritative.'))
    return sorted(output,key=lambda group:(group['priority'],min(group['slots']),group['id']))
