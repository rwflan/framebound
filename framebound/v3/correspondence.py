"""Authored-time source correspondence; no index-based motion reference substitution."""
from fractions import Fraction

import numpy as np

VERSION='source-correspondence-v1'


def map_tick(source,output_tick):
    points=source.time_map
    for left,right in zip(points,points[1:]):
        if left.output_tick<=output_tick<=right.output_tick:
            return Fraction(left.source_tick)+Fraction(output_tick-left.output_tick,right.output_tick-left.output_tick)*(right.source_tick-left.source_tick)
    raise ValueError('output tick outside the frozen correspondence')


def validate(spec):
    source=spec.source_correspondence
    if source is None:return
    if source.loop!=spec.loop:raise ValueError('source and output loop/terminal behavior must agree')
    if source.time_map[-1].output_tick!=spec.timing.total_ticks():raise ValueError('time map must cover the complete output duration')
    if source.timing.total_ticks()*spec.timing.ticks_per_second!=spec.timing.total_ticks()*source.timing.ticks_per_second:
        raise ValueError('enhancement/interpolation must preserve authored duration in seconds')
    if any(a.source_tick*spec.timing.ticks_per_second!=a.output_tick*source.timing.ticks_per_second for a in source.time_map):
        raise ValueError('enhancement/interpolation preserves source key timing; retiming requires a separate supported task policy')
    source_starts={sum(source.timing.holds[:i]) for i in range(len(source.timing.holds))}
    output_starts={sum(spec.timing.holds[:i]) for i in range(len(spec.timing.holds))}
    keys=set()
    for key in source.protected_keys:
        if key.source_tick not in source_starts or key.output_tick not in output_starts:
            raise ValueError('protected keys must bind actual source and output drawing starts')
        if map_tick(source,key.output_tick)!=key.source_tick:raise ValueError('protected key disagrees with frozen time correspondence')
        if key.output_tick in keys:raise ValueError('duplicate protected output key')
        keys.add(key.output_tick)
        if key.roi and (key.roi.right>spec.canvas.width or key.roi.bottom>spec.canvas.height):raise ValueError('protected source ROI exceeds native canvas')
    # Every original key remains an authored output anchor; keys cannot silently disappear.
    if {key.source_tick for key in source.protected_keys}!=source_starts:
        raise ValueError('all original source keys need explicit preservation rules')


def frames_at_output_starts(spec):
    source=spec.source_correspondence
    if source is None:return []
    source_starts=[sum(source.timing.holds[:i]) for i in range(len(source.timing.holds))]
    keys={key.output_tick for key in source.protected_keys}
    frames=[]
    for slot in range(len(spec.timing.holds)):
        output_tick=sum(spec.timing.holds[:slot]);tick=map_tick(source,output_tick)
        source_slot=next(i for i,start in enumerate(source_starts) if start<=tick<start+source.timing.holds[i])
        frames.append(dict(output_slot=slot,output_tick=output_tick,source_tick=[tick.numerator,tick.denominator],
                           source_slot=source_slot,asset_id=source.frame_asset_ids[source_slot],
                           correspondence='protected_key' if output_tick in keys else 'source_motion_interval'))
    return frames


def evaluate(spec,images,source_images,source_manifest):
    source=spec.source_correspondence
    if source is None:return [],None
    results=[]
    starts=[sum(spec.timing.holds[:i]) for i in range(len(spec.timing.holds))]
    source_starts=[sum(source.timing.holds[:i]) for i in range(len(source.timing.holds))]
    for key in source.protected_keys:
        slot=starts.index(key.output_tick);source_slot=source_starts.index(key.source_tick)
        current=images[slot];original=source_images[source_slot]
        outcome,observed='unmeasured',None
        if original is not None and current is not None and current.size==original.size:
            a=np.asarray(current.convert('RGBA'));b=np.asarray(original.convert('RGBA'))
            if key.roi:
                r=key.roi;a=a[r.top:r.bottom,r.left:r.right];b=b[r.top:r.bottom,r.left:r.right]
            if key.preservation=='alpha_geometry':a=a[:,:,3];b=b[:,:,3]
            observed=int(np.count_nonzero(np.any(a!=b,axis=2) if a.ndim==3 else a!=b))
            outcome='pass' if observed==0 else 'fail'
        results.append(dict(id=f'source-key-{slot}',family='source_fidelity',slots=[slot],
            tick_range=[starts[slot],starts[slot]+spec.timing.holds[slot]],outcome=outcome,
            observed=observed,expected=0,reason=f'Preserve the declared {key.preservation} anchor at source tick {key.source_tick} and output tick {key.output_tick}; inserted frames have interval correspondence, not same-frame source authority.',
            roi=key.roi.model_dump() if key.roi else None,evidence_method=VERSION,
            source='explicit_source_designation',confidence=None,required=True,
            source_asset=source_manifest[source_slot],source_slot=source_slot,preservation=key.preservation))
    return results,dict(version=VERSION,assets=source_manifest,time_map=[a.model_dump() for a in source.time_map],
                       output_correspondence=frames_at_output_starts(spec),
                       designation=dict(by=source.designated_by,basis=source.designation_basis,provenance=source.provenance),
                       limitation=source.limitation)
