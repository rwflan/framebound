"""Independent, source-bound visual review of a character sequence.

The judge sees the canonical source and every sequence frame together. Results
are model proposals and cannot waive numeric gates or missing measurements.
"""
import hashlib
import json
from pathlib import Path
from pydantic import Field
from ..v2.domain import Strict
from .character_consistency import Feature,Observation,image_digest,digest
from .character_observations import png,ObservationInvalid
from .campaign.specialists import extract_text

VERSION='character-cohort-body-items-v3'
IMPLEMENTATION_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class FrameReview(Strict):
    frame_id: str
    features: dict[str,Feature]
    items: dict[str,dict[str,Feature]]


class CohortReview(Strict):
    frames: list[FrameReview] = Field(min_length=1)
    limitation: str = Field(min_length=1)


class NamedCheck(Feature):
    frame_id: str
    feature: str
    item_id: str | None = None


class FlatReview(Strict):
    checks: list[NamedCheck] = Field(min_length=1)
    limitation: str = Field(min_length=1)


def canonical_review(value):
    if 'checks' not in value:return CohortReview.model_validate(value)
    flat=FlatReview.model_validate(value);rows={};seen=set()
    for check in flat.checks:
        key=(check.frame_id,check.item_id,check.feature)
        if key in seen:raise ValueError('Duplicate named cohort check')
        seen.add(key)
        row=rows.setdefault(check.frame_id,dict(frame_id=check.frame_id,features={},items={}))
        target=row['features'] if check.item_id is None else row['items'].setdefault(check.item_id,{})
        target[check.feature]=check.model_dump(include={'status','observed','expected'})
    return CohortReview.model_validate(dict(frames=list(rows.values()),limitation=flat.limitation))


def assess(root,reference,frames,features,items,description,*,dispatch,persist,focus_ids=None):
    ids=[fid for fid,_ in frames]
    if not ids or len(ids)!=len(set(ids)):raise ValueError('Unique sequence frame IDs required')
    focus=list(focus_ids) if focus_ids is not None else ids
    if not focus or len(set(focus))!=len(focus) or not set(focus)<=set(ids):raise ValueError('Invalid cohort focus IDs')
    prompt='''Inspect the ACTUAL drawings together as an evidence-based regression reviewer. Do not assume a defect exists; report match when the reference build is preserved. Image 1 is the immutable character/item design. Following images are sequence frames in the listed order. This is NOT art approval. Return JSON only with a FLAT named check list: {"checks":[{"frame_id":"exact supplied ID","item_id":null,"feature":"body.upper_arm_bulk","status":"match|mismatch|uncertain|occluded","observed":"short specific finding","expected":"reference invariant"},{"frame_id":"exact supplied ID","item_id":"declared item ID","feature":"topology","status":"match|mismatch|uncertain|occluded","observed":"short specific finding","expected":"reference invariant"}],"limitation":"honest limitations"}. Each check is one flat object; do not nest feature or item dictionaries.
Return every FOCUS frame, every required body feature and every required feature for every declared visible item. Compare each frame BOTH to image 1 AND to its neighbours. Do not rubber-stamp a sequence because it contains the right colours or the same action. The canonical source wins: do not demand a correct focus frame copy an incorrect neighbour. A focus mismatch must describe that focus drawing’s own departure from the canonical design.
body.upper_arm_bulk: compare biceps/triceps outer width, volume and muscle definition with the reference. A flexed arm may modestly change silhouette and muscle definition. Flag substantial added thickness or exaggerated anatomy relative to face/torso scale, not ordinary contraction or a different joint angle. Localize which actual arm and contour differs; never reuse an observation from a neighbouring image. Judge this individual reference, never gender stereotypes. Inspect ALL visible arms; one enlarged arm makes this feature mismatch. body.forearm_bulk and body.thigh_bulk independently compare visible mass. Compression, perspective or pose cannot justify unexplained added volume. A length measurement alone cannot establish thickness. When genuinely hidden, say so, not match.
For every item: design means exact construction and fittings, material means actual leather/metal/fabric, topology means counts of rigid handles, strands, blades or compartments, proportions means rigid-component length AND flexible-strand thickness/coil size relative to the body, configuration means the specified per-state shape and coiling, attachment means the actual anatomical hand/mount. One whip does not gain two wrapped handles, multiple lashes or extra free strand ends; a brown coil may still be a redesigned oversized weapon. Flexible bending does not authorize a different item. Explicitly flag frame-to-frame variation even if each image is plausible alone. Use mismatch with localized evidence for visible defects, uncertain for evidence gaps. Transparent surroundings or removed technical magenta backing are not style failures. Keep each observed/expected field below 25 words.'''
    prompt+='\nOutput reviews ONLY for these frame IDs (all images remain context): '+json.dumps(focus)+'\nFrame order: '+json.dumps(ids)+'\nRequired body features: '+json.dumps(features)+'\nDeclared generic inventory: '+json.dumps(items)+'\nExact request: '+description
    hashes=[image_digest(im) for _,im in frames];refsha=image_digest(reference)
    key='cohort-'+digest([VERSION,refsha,ids,hashes,prompt])[:20]
    raw=dispatch(Path(root),key,'muse-spark-1.3',prompt,[png(reference),*[png(im) for _,im in frames]])
    try:
        result=canonical_review(extract_text(raw))
        by_id={f.frame_id:f for f in result.frames}
        if len(by_id)!=len(result.frames) or set(by_id)!=set(focus):raise ValueError('Cohort frame coverage differs from source images')
        for fid in focus:
            row=by_id[fid]
            if set(row.features)!=set(features):raise ValueError('Cohort body coverage incomplete')
            if set(row.items)!={i['id'] for i in items}:raise ValueError('Cohort item coverage incomplete')
            for item in items:
                if set(row.items[item['id']])!=set(item.get('required_features',['design','palette','scale','attachment'])):raise ValueError('Cohort item feature coverage incomplete')
        evidence=dict(version=VERSION,implementation_sha256=IMPLEMENTATION_SHA256,execution_id=key,raw_sha256=hashlib.sha256(raw).hexdigest(),reference_sha256=refsha,
                      image_sha256s=dict(zip(ids,hashes)),review=result.model_dump(mode='json'),human_approval=False)
        persist(Path(root)/'private'/(key+'-review.json'),evidence)
        return evidence
    except (ValueError,KeyError,TypeError) as error:raise ObservationInvalid(key,hashlib.sha256(raw).hexdigest(),str(error)) from error


def overlay(observation,evidence,reference_sha256):
    observation=Observation.model_validate(observation)
    if evidence['reference_sha256']!=reference_sha256 or evidence['image_sha256s'].get(observation.frame_id)!=observation.image_sha256:
        raise ValueError('Stale cohort evidence')
    rows=[row for row in evidence['review']['frames'] if row['frame_id']==observation.frame_id]
    if len(rows)!=1:raise ValueError('Missing/duplicate cohort frame')
    row=rows[0];data=observation.model_dump(mode='json')
    def retain_negative(existing,proposed):
        return existing if existing and existing.get('status')=='mismatch' and proposed.get('status')!='mismatch' else proposed
    for name,feature in row['features'].items():
        data['features'][name]=retain_negative(data['features'].get(name),feature)
    for item,features in row['items'].items():
        if item not in data['items']:raise ValueError('Cohort does not fabricate missing inventory observations')
        for name,feature in features.items():
            data['items'][item]['features'][name]=retain_negative(data['items'][item]['features'].get(name),feature)
    history=data['measurement_sources'].setdefault('cohort_reviews',[])
    previous=data['measurement_sources'].get('cohort_review')
    if previous and previous not in history:history.append(previous)
    data['measurement_sources']['cohort_review']=dict(version=evidence['version'],execution_id=evidence['execution_id'],raw_sha256=evidence['raw_sha256'],reference_sha256=reference_sha256,image_sha256=observation.image_sha256,context_sha256s=evidence['image_sha256s'])
    return Observation.model_validate(data)
