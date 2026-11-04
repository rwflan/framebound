"""Source-bound checks of declared transitions, separate from per-pose matches."""
import hashlib
import json
from pathlib import Path
from pydantic import Field
from ..v2.domain import Strict
from .character_consistency import Feature,Policy,image_digest,digest
from .character_observations import png,ObservationInvalid
from .campaign.specialists import extract_text

VERSION='declared-transition-review-v4'


class Check(Feature):
    id: str


class Review(Strict):
    checks: list[Check] = Field(min_length=1)
    limitation: str = Field(min_length=1)


def assess(root,reference,frames,rules,description,*,dispatch,persist,observations=None):
    ids=[fid for fid,_ in frames]
    if len(ids)!=len(set(ids)) or not rules:raise ValueError('Unique frames and declared transition rules required')
    rules=[r.model_dump(mode='json') if hasattr(r,'model_dump') else r for r in rules]
    if any(r['left'] not in ids or r['right'] not in ids for r in rules):raise ValueError('Transition source frames missing')
    prompt='''Review TRANSITIONS between the actual supplied drawings. Image 1 is the canonical design; remaining images have the exact frame IDs listed below. A frame can resemble the reference alone and still FAIL a transition. Return JSON only: {"checks":[{"id":"exact rule ID","status":"match|mismatch|uncertain|occluded","observed":"short visible comparison between both named frames","expected":"required invariant"}],"limitation":"honest limitations"}. Return exactly one check per rule. Do not invent missing or hidden evidence.
body.shape: compare torso, waist, shoulder and limb cross-sections RELATIVE TO THE FACE in both frames. The run may articulate and lean, but may not widen, inflate, narrow, squash or liquefy the body between drawings. Distinguish normal pose compression from changed underlying build. Compare fixed camera/view and garment construction. Passing separate bulk checks does not waive visible widening between frames.
item.shape: compare the SAME physical object across both poses: rigid handle length, thickness, fittings and strand thickness/taper remain consistent relative to the body. A flexible lash may uncoil, bend or extend for attack, but may not turn into a differently sized/designed whip, add handles or extra strands, or change material. Do not compare coiled silhouette length with extended lash reach as though flexibility were a defect.
item.topology: trace EVERY strand from its attachment to its free tip in both drawings. Exactly one rigid handle and one continuous lash are allowed for this whip. A tiny leftover coil or strand dangling from the pommel while another lash extends from the active collar is an EXTRA strand and FAILS, even when brown and braided. Count active and butt-end attachments independently; uncertain hidden connections cannot pass. Generalize counts to the declared item.
item.palette: compare actual item colour in both source drawings, separating normal shading from brown leather becoming grey, red, silver or another palette. item.texture: compare braid spacing, wrapped-handle construction, surface finish and line/shading style; leather must not become a smooth rod, chain, flat painted line or differently detailed weapon.
item.owner: trace the shoulder-elbow-wrist chain of the hand holding the object in BOTH frames. Follow the declared anatomical owner or mount in the request: a RIGHT-held item must stay RIGHT, a LEFT-held item must stay LEFT, and a mounted object must retain its declared mount, unless a transfer is expressly requested. Trace from the declared-view shoulder, not a guessed screen side. A fist can cross the front of the chest without changing arms. Screen position of the fist alone is not handedness. An ambiguous/hidden arm chain is uncertain, never match.
item.orientation: check the functional direction relative to the GRIP, not absolute screen up/down. For a conventional handle grip, the active/lash/blade end emerges from the thumb-index side; the butt/pommel points toward the little-finger/palm-heel side. A reversed handle or lash attachment exiting the butt end fails. The wrist may rotate during a swing, but active and butt ends must not exchange roles in the hand. The request defines exceptions for other objects.
item.grip: verify the declared grip/mount component is actually held in both frames and stays connected throughout the transition. If a handle is declared, the hand must grasp the rigid handle, not the loose lash or coil; the coil may hang beneath the grip. An empty hand or transferred/duplicated grip fails unless the request explicitly authorizes it. The final attack frame must still show the same held handle. Pose-to-pose arm movement is allowed.
Judge the explicit request and actual pixels. Do not infer continuity from repeated labels, similar colour, or presence of a weapon. A visible mismatch must identify what changes between the named drawings; ambiguous evidence is uncertain. Each observed/expected field must be below 30 words.'''
    prompt+='\nFrame/image order: '+json.dumps(ids)+'\nRules: '+json.dumps(rules)+'\nRequest and allowed changes: '+description
    hashes={fid:image_digest(im) for fid,im in frames};ref=image_digest(reference)
    key='transitions-'+digest([VERSION,hashes,ref,rules,prompt])[:20]
    details=[];detail_labels=[]
    if observations:
        from .character_consistency import Observation,measurements
        for fid,im in frames:
            if fid not in observations:continue
            obs=Observation.model_validate(observations[fid])
            if obs.image_sha256!=hashes[fid]:raise ValueError('Stale transition detail observation')
            head=measurements(obs,('head_top','chin')).get('head_px')
            if not head:continue
            for item_id in sorted({r['item_id'] for r in rules if r.get('item_id')}):
                item=obs.items.get(item_id)
                if not item or not item.grip or item.grip.visibility!='visible':continue
                x,y=item.grip.xy[0]*im.width/1000,item.grip.xy[1]*im.height/1000
                box=(max(0,int(x-head*2)),max(0,int(y-head*2)),min(im.width,int(x+head*2)),min(im.height,int(y+head*2)))
                details.append(png(im.crop(box)));detail_labels.append(dict(frame=fid,item=item_id,kind='item context',source_box=box))
                tight=(max(0,int(x-head*.7)),max(0,int(y-head*.7)),min(im.width,int(x+head*.7)),min(im.height,int(y+head*.7)))
                details.append(png(im.crop(tight)));detail_labels.append(dict(frame=fid,item=item_id,kind='palm anatomy only, endpoints may be outside this crop',source_box=tight))
    prompt+=' Native grip-detail crops after the full images, in this exact order: '+json.dumps(detail_labels)+'. Crops supplement full sources; never treat cropped-out tips as absent. Use the tight palm crops to resolve thumb/index versus little finger; use the wider item context and full source to trace collar, pommel and strand attachments.'
    key='transitions-'+digest([VERSION,hashes,ref,rules,prompt])[:20]
    raw=dispatch(Path(root),key,'muse-spark-1.3',prompt,[png(reference),*[png(im) for _,im in frames],*details])
    try:
        result=Review.model_validate(extract_text(raw))
        if len({c.id for c in result.checks})!=len(result.checks) or {c.id for c in result.checks}!={r['id'] for r in rules}:raise ValueError('Transition check coverage differs from declared rules')
        evidence=dict(version=VERSION,reference_sha256=ref,image_sha256s=hashes,rules_sha256=digest(rules),execution_id=key,
                      raw_sha256=hashlib.sha256(raw).hexdigest(),checks=[c.model_dump(mode='json') for c in result.checks],limitation=result.limitation,human_approval=False)
        persist(Path(root)/'private'/(key+'-review.json'),evidence)
        return evidence
    except (ValueError,TypeError,KeyError) as error:raise ObservationInvalid(key,hashlib.sha256(raw).hexdigest(),str(error)) from error


def evaluate(policy,evidence,source_hashes):
    policy=Policy.model_validate(policy);rules=policy.transitions
    groups=evidence if isinstance(evidence,list) else [evidence]
    proposals={r.id:[] for r in rules}
    for group in groups:
        if not isinstance(group,dict) or group.get('reference_sha256')!=policy.master.image_sha256:continue
        try:rows=[Check.model_validate(c) for c in group.get('checks',[])]
        except (ValueError,TypeError):continue
        ids={c.id for c in rows};subset=[r for r in rules if r.id in ids]
        if len(ids)!=len(rows) or len(subset)!=len(ids) or group.get('rules_sha256')!=digest([r.model_dump(mode='json') for r in subset]):continue
        declared=group.get('image_sha256s',{});context_current=bool(declared) and all(fid in source_hashes and source_hashes[fid]==sha for fid,sha in declared.items())
        by_id={r.id:r for r in subset}
        for check in rows:
            rule=by_id[check.id]
            pair_current=all(fid in declared and fid in source_hashes and declared[fid]==source_hashes[fid] for fid in (rule.left,rule.right))
            # A current pair's negative finding survives unrelated context edits.
            # A positive result requires the complete reviewed context to match.
            if pair_current and (context_current or check.status=='mismatch'):proposals[check.id].append(check)
    results=[]
    for rule in rules:
        rows=proposals[rule.id]
        c=next((c for c in rows if c.status=='mismatch'),None) or next((c for c in rows if c.status=='match'),None) or next(iter(rows),None)
        status='unmeasured' if c is None or c.status in ('uncertain','occluded') else 'pass' if c.status=='match' else 'fail'
        results.append(dict(id=rule.id,feature=rule.feature,item_id=rule.item_id,frames=[rule.left,rule.right],status=status,
                            observed=c.observed if c else None,expected=c.expected if c else 'Complete current source-bound transition evidence',
                            reason='transition_'+('unmeasured' if status=='unmeasured' else 'changed' if status=='fail' else 'matched')))
    return results


def repair_tasks(results,frame_id):
    """Return concrete pair defects for correction, leaving missing evidence unknown."""
    return [dict(code='transition_changed',feature=row['feature'],item_id=row.get('item_id'),
                 frames=row['frames'],observed=row['observed'],expected=row['expected'],
                 source_roi=None,action='Correct this frame against the other named retained source; preserve pose and already-correct design.')
            for row in results if row['status']=='fail' and frame_id in row['frames']]
