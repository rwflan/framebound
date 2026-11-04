"""Source-bound character and visible-item gates.

Landmarks and semantic observations are model proposals, not inferred truths or
human approval. Geometry is calculated here; unknown required evidence blocks.
"""
import hashlib
import json
import math
from typing import Literal

from pydantic import Field, model_validator
from ..v2.domain import Strict

VERSION = 'character-consistency-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def image_digest(image):
    rgba=image.convert('RGBA')
    return hashlib.sha256(json.dumps(rgba.size).encode()+rgba.tobytes()).hexdigest()


class Point(Strict):
    xy: tuple[float,float] | None = None
    visibility: Literal['visible','occluded','uncertain']
    evidence: str = Field(min_length=1,max_length=1200)

    @model_validator(mode='after')
    def valid_point(self):
        if self.visibility=='visible' and self.xy is None:raise ValueError('visible point needs coordinates')
        if self.xy and any(not math.isfinite(x) or not 0<=x<=1000 for x in self.xy):raise ValueError('point outside normalized source')
        if self.visibility!='visible' and self.xy is not None:raise ValueError('hidden points must not be invented')
        return self


class Feature(Strict):
    status: Literal['match','mismatch','uncertain','occluded']
    observed: str = Field(min_length=1,max_length=1800)
    expected: str = Field(min_length=1,max_length=1800)


class ItemObservation(Strict):
    visibility: Literal['visible','occluded','absent','uncertain']
    anchor: str | None = None
    grip: Point | None = None
    rigid_span: tuple[Point,Point] | None = None
    features: dict[str,Feature] = Field(default_factory=dict)
    evidence: str = Field(min_length=1,max_length=1800)


class Observation(Strict):
    image_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    frame_id: str = Field(min_length=1,max_length=128)
    execution_id: str = Field(min_length=1,max_length=200)
    raw_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    width: int = Field(gt=0,le=8192)
    height: int = Field(gt=0,le=8192)
    points: dict[str,Point]
    features: dict[str,Feature]
    items: dict[str,ItemObservation]
    limitation: str = Field(min_length=1,max_length=1800)
    normalization: list[str] = Field(default_factory=list)
    measurement_sources: dict = Field(default_factory=dict)


class ItemRule(Strict):
    id: str = Field(min_length=1,max_length=128)
    description: str = Field(min_length=1,max_length=2000)
    anchor: str = Field(min_length=1,max_length=128)
    anchor_by_frame: dict[str,str] = Field(default_factory=dict)
    occluded_frames: list[str] = Field(default_factory=list)
    # Flexible forms may bend/coils may overlap, but material, construction,
    # palette, scale and attachment remain invariant within visible scope.
    required_features: list[str] = Field(default_factory=lambda:['design','palette','scale','attachment'])
    rigid_measurement: str | None = None
    max_span_drift: float = Field(default=.12,gt=0,le=.3)
    max_attachment_head_ratio: float = Field(default=.4,gt=0,le=2)


    @model_validator(mode='after')
    def complete_inventory_gates(self):
        if not {'design','palette','scale','attachment'}<=set(self.required_features) or len(set(self.required_features))!=len(self.required_features):
            raise ValueError('Every visible item needs design, palette, scale and attachment coverage')
        return self


class Allowance(Strict):
    feature: str
    frames: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1,max_length=2000)
    request_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class TransitionRule(Strict):
    id: str = Field(min_length=1,max_length=128)
    left: str = Field(min_length=1,max_length=128)
    right: str = Field(min_length=1,max_length=128)
    feature: Literal['body.shape','item.shape','item.palette','item.texture','item.grip','item.owner','item.orientation','item.topology']
    item_id: str | None = None

    @model_validator(mode='after')
    def complete(self):
        if self.left==self.right:raise ValueError('Transition needs distinct frames')
        if self.feature.startswith('item.')!=bool(self.item_id):raise ValueError('Item transitions need an explicit inventory ID')
        return self


class Policy(Strict):
    schema_version: Literal['1.0'] = '1.0'
    request_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    master: Observation
    master_asset_id: str | None = Field(default=None,max_length=128)
    required_features: list[str] = Field(min_length=1)
    items: list[ItemRule] = Field(default_factory=list)
    allowances: list[Allowance] = Field(default_factory=list)
    scale_reference: tuple[str,str] = ('head_top','chin')
    expected_geometry_recipe: str | None = None
    transitions: list[TransitionRule] = Field(default_factory=list,max_length=512)
    torso_profile_pairs: list[tuple[str,str]] = Field(default_factory=list,max_length=512)
    max_torso_profile_drift: float = Field(default=.12,gt=0,le=.3)
    minimum_scale_reference_pixels: int = Field(default=0,ge=0,le=2048)
    pristine_render_sha256: str | None = Field(default=None,pattern=r'^[0-9a-f]{64}$')
    max_part_drift: float = Field(default=.18,gt=0,le=.35)
    max_adjacent_part_drift: float = Field(default=.12,gt=0,le=.3)
    max_head_scale_drift: float = Field(default=.08,gt=0,le=.2)
    required_measurements: list[str] = Field(default_factory=lambda:['torso','chest_width','waist_width'])
    require_visible_arm_and_leg: bool = True

    @model_validator(mode='after')
    def unique_rules(self):
        if 'rendering.clarity' in self.required_features and not self.pristine_render_sha256:raise ValueError('Rendering clarity requires a frozen pristine authority')
        if len({r.id for r in self.transitions})!=len(self.transitions):raise ValueError('Duplicate transition IDs')
        if any(r.item_id and r.item_id not in {i.id for i in self.items} for r in self.transitions):raise ValueError('Transition references undeclared inventory')
        if any(a==b for a,b in self.torso_profile_pairs):raise ValueError('Torso profile pair needs distinct frames')
        if len({i.id for i in self.items})!=len(self.items):raise ValueError('duplicate item rules')
        if len(set(self.required_features))!=len(self.required_features):raise ValueError('duplicate feature rules')
        for a in self.allowances:
            if a.request_sha256!=self.request_sha256:raise ValueError('allowance is not bound to frozen request')
            targets=set(self.required_features)|{'item:'+i.id+':'+f for i in self.items for f in i.required_features}
            if a.feature not in targets:raise ValueError('allowance must name an exact declared feature')
        return self


SEGMENTS = {
    'head_width':('head_left','head_right'),
    'chest_width':('chest_left','chest_right'), 'waist_width':('waist_left','waist_right'),
    'left_arm_width':('left_arm_inner','left_arm_outer'), 'right_arm_width':('right_arm_inner','right_arm_outer'),
    'left_thigh_width':('left_thigh_inner','left_thigh_outer'), 'right_thigh_width':('right_thigh_inner','right_thigh_outer'),
    'left_calf_width':('left_calf_inner','left_calf_outer'), 'right_calf_width':('right_calf_inner','right_calf_outer'),
    'torso':('neck','pelvis'),
    'left_upper_arm':('left_shoulder','left_elbow'), 'right_upper_arm':('right_shoulder','right_elbow'),
    'left_forearm':('left_elbow','left_wrist'), 'right_forearm':('right_elbow','right_wrist'),
    'left_thigh':('left_hip','left_knee'), 'right_thigh':('right_hip','right_knee'),
    'left_shin':('left_knee','left_ankle'), 'right_shin':('right_knee','right_ankle'),
}


def point(obs,name):
    p=obs.points.get(name)
    if p is None or p.visibility!='visible':return None
    return (p.xy[0]*obs.width/1000,p.xy[1]*obs.height/1000)


def span(obs,a,b):
    left,right=point(obs,a),point(obs,b)
    return math.dist(left,right) if left and right else None


def measurements(obs,scale_reference=('head_top','chin')):
    head=span(obs,*scale_reference)
    out={'head_px':head}
    if not head or head<4:return out
    for name,(a,b) in SEGMENTS.items():
        length=span(obs,a,b)
        out[name]=length/head if length else None
    return out


def evaluate_frame(policy, observation, *, image_sha256, frame_id, pixel_scale=1., master_pixel_scale=1.):
    policy=Policy.model_validate(policy);obs=Observation.model_validate(observation)
    issues=[];coverage=[]
    def add(code,feature,observed,expected,status='fail'):
        issues.append(dict(code=code,feature=feature,frame_id=frame_id,status=status,observed=observed,expected=expected))
    if not math.isfinite(pixel_scale) or not math.isfinite(master_pixel_scale) or pixel_scale<=0 or master_pixel_scale<=0:
        add('calibration_invalid','render_scale',None,'Positive finite source-to-render calibration','unmeasured')
        return dict(passed=False,issues=issues,coverage=[],measurements={})
    if obs.image_sha256!=image_sha256 or obs.frame_id!=frame_id:
        add('stale_evidence','binding',obs.image_sha256,image_sha256,'unmeasured')
        return dict(passed=False,issues=issues,coverage=[],measurements={},policy_sha256=digest(policy.model_dump(mode='json')))
    if policy.expected_geometry_recipe and obs.measurement_sources.get('geometry_recipe_sha256')!=policy.expected_geometry_recipe:
        add('measurement_method_changed','geometry',obs.measurement_sources.get('geometry_recipe_sha256'),policy.expected_geometry_recipe,'unmeasured')
    base,current=measurements(policy.master,policy.scale_reference),measurements(obs,policy.scale_reference)
    head=base.get('head_px');actual=current.get('head_px')
    if policy.pristine_render_sha256:
        fidelity=obs.measurement_sources.get('render_fidelity',{})
        if fidelity.get('pristine_sha256')!=policy.pristine_render_sha256 or fidelity.get('candidate_sha256')!=image_sha256:
            add('render_fidelity_unmeasured','rendering.clarity',None,'Current candidate compared against the frozen original clean authority','unmeasured')
        else:
            from .render_fidelity import Review as RenderReview
            try:
                verdict=RenderReview.model_validate(fidelity.get('checks',{}))
                statuses=[getattr(verdict,k).status for k in ('linework','colour_separation','material_detail')]
                if 'mismatch' in statuses:add('render_fidelity_changed','rendering.clarity',fidelity['checks'],'Original clean linework, colour separation and material detail')
                elif not all(v=='match' for v in statuses):add('render_fidelity_unmeasured','rendering.clarity',None,'Complete native rendering evidence','unmeasured')
            except (ValueError,TypeError):add('render_fidelity_unmeasured','rendering.clarity',None,'Complete native rendering evidence','unmeasured')
    if not head or not actual:
        add('head_unmeasured','head_scale',actual,head,'unmeasured')
    else:
        if actual<policy.minimum_scale_reference_pixels:
            add('insufficient_native_character_detail','native_head_span',actual,policy.minimum_scale_reference_pixels)
        ratio=actual*pixel_scale/(head*master_pixel_scale)
        if abs(ratio-1)>policy.max_head_scale_drift:add('scale_drift','head_scale',ratio,[1-policy.max_head_scale_drift,1+policy.max_head_scale_drift])
        coverage.append(dict(feature='head_scale',status='measured',ratio=ratio))
    names=set(policy.required_measurements)
    for name in SEGMENTS:
        other=('right_'+name[5:]) if name.startswith('left_') else ('left_'+name[6:]) if name.startswith('right_') else name
        if current.get(name) is not None and (base.get(name) is not None or base.get(other) is not None):names.add(name)
        elif current.get(name) is not None:coverage.append(dict(feature=name,status='not_established_in_reference'))
    if policy.require_visible_arm_and_leg:
        for family in ('arm','leg'):
            pairs=[(s+'_upper_arm',s+'_forearm') if family=='arm' else (s+'_thigh',s+'_shin') for s in ('left','right')]
            width_pairs=[(s+'_arm_width',s+'_forearm') if family=='arm' else (s+'_thigh_width',s+'_calf_width') for s in ('left','right')]
            if not any(all(current.get(k) is not None for k in pair) for pair in pairs+width_pairs):
                add('coverage_gap',family,'No usable visible limb evidence','At least one visible '+family+' chain or paired visible part dimensions','unmeasured')
    if policy.require_visible_arm_and_leg:
        numeric_bulk=any(current.get(side+'_arm_width') is not None and
            (base.get(side+'_arm_width') is not None or base.get(('left' if side=='right' else 'right')+'_arm_width') is not None) for side in ('left','right'))
        targeted_bulk=obs.features.get('body.upper_arm_bulk') if 'body.upper_arm_bulk' in policy.required_features else None
        if not numeric_bulk and (targeted_bulk is None or targeted_bulk.status in ('uncertain','occluded')):
            add('coverage_gap','arm_volume',None,'Comparable visible arm width or explicit source-bound upper-arm bulk assessment; length alone is insufficient','unmeasured')
    # Compare the same anatomical side when visible. A hidden far side cannot
    # become a fabricated measurement or be called a pass.
    for name in sorted(names):
        expected=base.get(name);value=current.get(name)
        if expected is None and name.startswith(('left_','right_')):
            other=('right_'+name[5:]) if name.startswith('left_') else ('left_'+name[6:])
            expected=base.get(other)
        if expected is None or value is None:
            add('part_unmeasured',name,value,expected,'unmeasured');continue
        ratio=value/expected
        coverage.append(dict(feature=name,status='measured',ratio=ratio))
        if abs(ratio-1)>policy.max_part_drift:add('part_proportion_drift',name,ratio,[1-policy.max_part_drift,1+policy.max_part_drift])
    for name in policy.required_features:
        feature=obs.features.get(name)
        allowed=any(a.feature==name and frame_id in a.frames for a in policy.allowances)
        if feature is None or feature.status in ('uncertain','occluded'):
            add('feature_unmeasured',name,None if feature is None else feature.observed,'Visible localized comparison','unmeasured')
        elif feature.status=='mismatch' and not allowed:
            add('feature_changed',name,feature.observed,feature.expected)
        else:coverage.append(dict(feature=name,status='request_scoped_change' if allowed and feature.status=='mismatch' else 'model_match',evidence=feature.observed))
    known={i.id for i in policy.items}
    for name in obs.items:
        if name not in known:add('unexpected_item',name,obs.items[name].evidence,'Only declared visible inventory')
    for rule in policy.items:
        item=obs.items.get(rule.id)
        if item and item.visibility=='occluded' and frame_id in rule.occluded_frames:
            coverage.append(dict(feature='item:'+rule.id,status='declared_occlusion',evidence=item.evidence));continue
        if item is None or item.visibility!='visible':
            add('item_unmeasured',rule.id,None if item is None else item.visibility,'Declared item visible; occlusion must be scoped','unmeasured');continue
        anchor=rule.anchor_by_frame.get(frame_id,rule.anchor)
        if item.anchor!=anchor:add('item_owner_changed',rule.id,item.anchor,anchor)
        for name in rule.required_features:
            feature=item.features.get(name)
            if feature is None or feature.status in ('uncertain','occluded'):
                add('item_feature_unmeasured',rule.id+':'+name,None if feature is None else feature.observed,'Visible reference-bound item evidence','unmeasured')
            elif feature.status!='match':
                allowed=any(a.feature=='item:'+rule.id+':'+name and frame_id in a.frames for a in policy.allowances)
                if not allowed:add('item_design_changed',rule.id+':'+name,feature.observed,feature.expected)
                else:coverage.append(dict(feature='item:'+rule.id+':'+name,status='request_scoped_change',evidence=feature.observed))
            else:coverage.append(dict(feature='item:'+rule.id+':'+name,status='model_match',evidence=feature.observed))
        if rule.rigid_measurement:
            original=policy.master.items.get(rule.id)
            def item_length(item, observation):
                if not item or not item.rigid_span or any(p.visibility!='visible' for p in item.rigid_span):return None
                xy=[(p.xy[0]*observation.width/1000,p.xy[1]*observation.height/1000) for p in item.rigid_span]
                return math.dist(*xy)
            expected_length=item_length(original,policy.master)
            observed_length=item_length(item,obs)
            if not expected_length or not observed_length or not actual or not head:
                add('item_span_unmeasured',rule.id,None,rule.rigid_measurement,'unmeasured')
            else:
                ratio=(observed_length/actual)/(expected_length/head)
                if abs(ratio-1)>rule.max_span_drift:add('item_scale_drift',rule.id,ratio,[1-rule.max_span_drift,1+rule.max_span_drift])
        body_anchor=point(obs,anchor)
        if item.grip and item.grip.visibility=='visible' and body_anchor and actual:
            grip=(item.grip.xy[0]*obs.width/1000,item.grip.xy[1]*obs.height/1000)
            distance=math.dist(grip,body_anchor)/actual
            if distance>rule.max_attachment_head_ratio:add('item_detached',rule.id,distance,rule.max_attachment_head_ratio)
        else:add('attachment_unmeasured',rule.id,None,'Visible grip/mount point and body anchor','unmeasured')
    return dict(passed=not issues,issues=issues,coverage=coverage,measurements=current,
                policy_sha256=digest(policy.model_dump(mode='json')),image_sha256=image_sha256,
                evidence_source='model_proposed_landmarks_and_semantics; deterministic distances and bounds',human_approval=False)


def evaluate_sequence(policy, observations, image_sha256s, frame_ids, pixel_scales=None, pairs=(), images=None, transition_review=None):
    policy=Policy.model_validate(policy)
    if not (len(observations)==len(image_sha256s)==len(frame_ids)) or not observations:raise ValueError('One exact observation per actual frame is required')
    if len(set(frame_ids))!=len(frame_ids):raise ValueError('Duplicate frame IDs')
    scales=pixel_scales or [1.]*len(observations)
    if len(scales)!=len(observations) or any(not math.isfinite(s) or s<=0 for s in scales):raise ValueError('Invalid render calibration')
    frames=[evaluate_frame(policy,o,image_sha256=sha,frame_id=fid,pixel_scale=s) for o,sha,fid,s in zip(observations,image_sha256s,frame_ids,scales)]
    source_map=dict(zip(frame_ids,image_sha256s))
    for index,raw in enumerate(observations):
        obs=Observation.model_validate(raw);cohort=obs.measurement_sources.get('cohort_review')
        if cohort and (cohort.get('reference_sha256')!=policy.master.image_sha256 or
                not cohort.get('context_sha256s') or any(source_map.get(fid)!=sha for fid,sha in cohort.get('context_sha256s',{}).items())):
            frames[index]['issues'].append(dict(code='stale_cohort_context',feature='cohort_binding',frame_id=frame_ids[index],status='unmeasured',observed=None,expected='Exact current reference and neighbour source hashes'))
            frames[index]['passed']=False
    temporal=[]
    for left,right in pairs:
        if left==right or min(left,right)<0 or max(left,right)>=len(frames):raise ValueError('Invalid temporal pair')
        a,b=frames[left]['measurements'],frames[right]['measurements']
        for feature in SEGMENTS:
            if a.get(feature) is None or b.get(feature) is None:continue
            ratio=b[feature]/a[feature]
            if abs(ratio-1)>policy.max_adjacent_part_drift:
                temporal.append(dict(code='part_pulse',feature=feature,frames=[frame_ids[left],frame_ids[right]],observed=ratio,expected=[1-policy.max_adjacent_part_drift,1+policy.max_adjacent_part_drift]))
        left_obs=Observation.model_validate(observations[left]);right_obs=Observation.model_validate(observations[right])
        for rule in policy.items:
            if not rule.rigid_measurement:continue
            def relative_span(observation):
                item=observation.items.get(rule.id);head=measurements(observation,policy.scale_reference).get('head_px')
                if not item or item.visibility!='visible' or not item.rigid_span or not head or any(p.visibility!='visible' for p in item.rigid_span):return None
                ends=[(p.xy[0]*observation.width/1000,p.xy[1]*observation.height/1000) for p in item.rigid_span]
                return math.dist(*ends)/head
            aa,bb=relative_span(left_obs),relative_span(right_obs)
            if aa and bb and abs(bb/aa-1)>policy.max_adjacent_part_drift:
                temporal.append(dict(code='item_size_pulse',feature=rule.id,frames=[frame_ids[left],frame_ids[right]],observed=bb/aa,expected=[1-policy.max_adjacent_part_drift,1+policy.max_adjacent_part_drift]))
    transition_results=[]
    if policy.transitions:
        from .transition_consistency import evaluate as evaluate_transitions
        transition_results=evaluate_transitions(policy,transition_review,dict(zip(frame_ids,image_sha256s)))
    profile_results=[]
    profiles={}
    if policy.torso_profile_pairs:
        from .torso_profile import measure as measure_profile
        if images is not None:
            if len(images)!=len(observations):raise ValueError('Torso profiles require exact source image coverage')
            for fid,im,obs,sha in zip(frame_ids,images,observations,image_sha256s):
                if image_digest(im)!=sha:raise ValueError('Torso profile pixels differ from source binding')
                profiles[fid]=measure_profile(im,obs,policy.scale_reference)
        for left,right in policy.torso_profile_pairs:
            a,b=profiles.get(left),profiles.get(right)
            if not a or not b or not a['measured'] or not b['measured']:
                profile_results.append(dict(code='torso_profile_unmeasured',frames=[left,right],status='unmeasured',observed=None,expected='Visible source-bound torso material profile in both frames'))
            else:
                ratios=[bb/aa for aa,bb in zip(a['profile'],b['profile'])]
                if any(abs(v-1)>policy.max_torso_profile_drift for v in ratios):
                    profile_results.append(dict(code='torso_shape_pulse',frames=[left,right],status='fail',observed=ratios,expected=[1-policy.max_torso_profile_drift,1+policy.max_torso_profile_drift]))
    return dict(version=VERSION,passed=all(f['passed'] for f in frames) and not temporal and not profile_results and all(r['status']=='pass' for r in transition_results),
                frames=frames,temporal_issues=temporal,transition_results=transition_results,transition_evidence_sha256=digest(transition_review) if transition_review is not None else None,torso_profile_issues=profile_results,torso_profiles=profiles,policy_sha256=digest(policy.model_dump(mode='json')),
                image_sha256s=image_sha256s,pixel_scales=scales,human_approval=False)


def repair_plan(policy,observation,report):
    """Turn localized gate failures into bounded, source-bound edit directions."""
    policy=Policy.model_validate(policy);obs=Observation.model_validate(observation)
    head=measurements(obs,policy.scale_reference).get('head_px') or 40
    tasks=[]
    for issue in report['issues']:
        name=issue['feature'];code=issue['code'];points=[]
        if name in SEGMENTS:
            points=[point(obs,k) for k in SEGMENTS[name]]
        elif name in {'body.upper_arm_bulk','body.forearm_bulk','body.thigh_bulk'}:
            suffixes={'body.upper_arm_bulk':('shoulder','elbow'),'body.forearm_bulk':('elbow','wrist'),'body.thigh_bulk':('hip','knee')}[name]
            points=[point(obs,side+'_'+suffix) for side in ('left','right') for suffix in suffixes]
            points=[p for p in points if p is not None]
        elif code=='item_scale_drift' and name in obs.items and obs.items[name].rigid_span:
            points=[(p.xy[0]*obs.width/1000,p.xy[1]*obs.height/1000) for p in obs.items[name].rigid_span if p.visibility=='visible']
        message=code+': restore '+name+' to the immutable reference.'
        if code in ('part_proportion_drift','item_scale_drift') and isinstance(issue['observed'],(int,float)) and issue['observed']>0:
            bounds=issue['expected']
            target=1.
            if isinstance(bounds,(list,tuple)) and len(bounds)==2:
                # Aim just inside the frozen gate, avoiding unnecessary redraw.
                target=bounds[0]+.03 if issue['observed']<bounds[0] else bounds[1]-.03
            change=(target/issue['observed']-1)*100
            message=('Increase' if change>0 else 'Reduce')+' the current rendered '+name+' span by '+str(round(abs(change),1))+'%. Preserve joint angles, neighbouring part lengths, colour, volume, attachment and all unmentioned pixels.'
        elif code=='feature_changed' and name in {'body.upper_arm_bulk','body.forearm_bulk','body.thigh_bulk'}:
            message='Reduce the exaggerated visible '+name+' volume and muscle bulges by approximately 20 percent in the CURRENT drawing, matching the canonical lean athletic contour. Preserve the joint centres, action, costume and face. Do not add bodybuilding lobes or vascularity; recheck all proportions after the edit.'
        elif code=='item_owner_changed':
            message='Move this SAME item to '+str(issue['expected'])+'; the other hand/mount must not retain a copy. Preserve the identical design and pose.'
        elif issue['status']=='unmeasured':
            message='Expose '+name+' clearly enough to verify its source pixels; do not invent hidden measurements or alter unrelated anatomy.'
        roi=None
        if len(points)>=2 and all(p is not None for p in points):
            roi=[max(0,int(min(p[0] for p in points)-head*.4)),max(0,int(min(p[1] for p in points)-head*.4)),
                 min(obs.width,int(max(p[0] for p in points)+head*.4+1)),min(obs.height,int(max(p[1] for p in points)+head*.4+1))]
        tasks.append(dict(code=code,feature=name,frame_id=obs.frame_id,instruction=message,source_roi=roi,
                          observed=issue['observed'],expected=issue['expected']))
    return dict(policy_sha256=digest(policy.model_dump(mode='json')),image_sha256=obs.image_sha256,frame_id=obs.frame_id,tasks=tasks,
                authority='edit proposal only; every invariant must be rechecked on the actual replacement')
