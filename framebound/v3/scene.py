"""Bounded camera-compensated feature/event evidence. No internal generative agent."""
import math
from pathlib import Path

import numpy as np

from .evaluate import digest

VERSION='declared-color-camera-tracks-v1'


def validate(spec):
    scene=spec.scene
    if scene is None:return
    n=len(spec.timing.holds);subjects=set(scene.subjects)
    if len(subjects)!=len(scene.subjects):raise ValueError('scene subject IDs must be unique')
    if {c.slot for c in scene.camera}!=set(range(n)) or len(scene.camera)!=n:
        raise ValueError('scene needs an explicit camera transform for every authored frame')
    for camera in scene.camera:
        if not all(math.isfinite(v) for v in camera.translation):raise ValueError('camera translation must be finite')
    features={f.id:f for f in scene.features}
    ids=[f.id for f in scene.features]+[link.id for link in scene.links]+[event.id for event in scene.events]
    if len(ids)!=len(set(ids)):raise ValueError('scene measurement IDs must be unique')
    for f in scene.features:
        if f.subject_id not in subjects or f.slot>=n:raise ValueError('feature must bind a declared subject and actual authored frame')
        if f.roi.right>spec.canvas.width or f.roi.bottom>spec.canvas.height:raise ValueError('tracked feature ROI exceeds native canvas')
        if any(c<0 or c>255 for c in f.rgba) or f.minimum_pixels>f.maximum_pixels:raise ValueError('invalid tracked feature color/count bounds')
        if not all(math.isfinite(v) for v in f.expected_world):raise ValueError('world anchors must be finite')
    for subject in subjects:
        if {f.slot for f in scene.features if f.subject_id==subject}!=set(range(n)):
            raise ValueError('each subject needs visible/occluded/ambiguous declarations throughout the clip')
    for link in scene.links:
        if link.left_feature_id not in features or link.right_feature_id not in features:raise ValueError('track link needs actual feature IDs')
        left,right=features[link.left_feature_id],features[link.right_feature_id]
        if left.subject_id!=right.subject_id or left.slot==right.slot:raise ValueError('temporal link must bind one subject across distinct frames')
    for event in scene.events:
        if event.left_feature_id not in features or event.right_feature_id not in features:raise ValueError('scene event needs actual feature IDs')
        if features[event.left_feature_id].slot!=features[event.right_feature_id].slot:raise ValueError('interaction event must bind simultaneous landmarks')


def supported(spec):
    if not spec.scene:return set()
    return {'scene_track'} | ({'scene_temporal'} if any(link.required for link in spec.scene.links) else set()) | ({'scene_event'} if any(event.required for event in spec.scene.events) else set())


def evaluate(spec,images):
    scene=spec.scene
    if scene is None:return [],None
    camera={c.slot:c for c in scene.camera};features={f.id:f for f in scene.features};world={};results=[]
    def record(rid,family,slots,outcome,observed,expected,reason,roi=None,source='deterministic',required=True):
        slots=sorted(set(slots));starts=[sum(spec.timing.holds[:i]) for i in slots]
        results.append(dict(id='scene:'+rid,family=family,slots=slots,
            tick_range=[starts[0],starts[-1]+spec.timing.holds[slots[-1]]],outcome=outcome,observed=observed,expected=expected,
            reason=reason,roi=roi,evidence_method=VERSION,source=source,confidence=None,required=required))
    for f in scene.features:
        if f.visibility!='visible':
            world[f.id]=None
            record(f.id,'scene_track',[f.slot],'not_applicable' if f.visibility=='occluded' else 'unmeasured',None,
                   list(f.expected_world),'Declared occlusion has no visible-location claim; ambiguous features require independent evidence.',f.roi.model_dump(),f.source)
            continue
        image=images[f.slot];point=None;count=None
        if image is not None and image.size==(spec.canvas.width,spec.canvas.height):
            r=f.roi;a=np.asarray(image.convert('RGBA'));ys,xs=np.nonzero(np.all(a[r.top:r.bottom,r.left:r.right]==f.rgba,axis=2));count=len(xs)
            if count:
                c=camera[f.slot];point=((float(xs.mean())+r.left-c.translation[0])/c.scale,
                                       (float(ys.mean())+r.top-c.translation[1])/c.scale)
        world[f.id]=point
        distance=math.dist(point,f.expected_world) if point is not None else None
        outcome=('unmeasured' if image is None or image.size!=(spec.canvas.width,spec.canvas.height) else
                 'pass' if count is not None and f.minimum_pixels<=count<=f.maximum_pixels and distance is not None and distance<=f.max_error_world else 'fail')
        record(f.id,'scene_track',[f.slot],outcome,dict(matching_pixels=count,world_point=list(point) if point else None,error_world=distance),
            dict(count_interval=[f.minimum_pixels,f.maximum_pixels],world_anchor=list(f.expected_world),max_error_world=f.max_error_world),
            'Measure the declared feature inside its frame ROI, then remove the frozen 2D camera translation/scale. This does not establish hidden anatomy or prove that the proposed landmark is semantically correct.',f.roi.model_dump(),f.source)
    for link in scene.links:
        left,right=features[link.left_feature_id],features[link.right_feature_id];a,b=world[left.id],world[right.id]
        distance=math.dist(a,b) if a is not None and b is not None else None
        record(link.id,'scene_temporal',[left.slot,right.slot],
            'unmeasured' if distance is None else 'pass' if distance<=link.max_displacement_world else 'fail',distance,
            [0,link.max_displacement_world],'Check the declared camera-compensated feature motion interval. Missing/occluded endpoints cannot establish continuity.',required=link.required)
    for event in scene.events:
        left,right=features[event.left_feature_id],features[event.right_feature_id];a,b=world[left.id],world[right.id]
        value=None;passed=False
        if a is not None and b is not None:
            value=math.dist(a,b) if event.kind in {'contact','separation'} else b[0]-a[0] if event.kind=='left_of' else b[1]-a[1]
            passed=value<=event.distance_world if event.kind=='contact' else value>=event.distance_world
        record(event.id,'scene_event',[left.slot],'unmeasured' if value is None else 'pass' if passed else 'fail',value,
            dict(kind=event.kind,distance_world=event.distance_world),
            'Verify the explicitly authored landmark interaction/event. Image-plane contact/order is measurable; force, occluded contact and arbitrary narrative correctness remain unsupported.',source=event.source,required=event.required)
    return results,dict(method=VERSION,source_sha256=digest(Path(__file__).read_text()),camera=[c.model_dump(mode='json') for c in scene.camera],
                        subjects=scene.subjects,limitation=scene.limitation,assumptions='Task-authored camera and landmark proposals retain provenance; measurements do not independently certify their semantic meaning.')
