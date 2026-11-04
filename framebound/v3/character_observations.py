"""Source-bound model observations for the generic character gates.

Artwork, descriptions and evidence stay under the caller's private root.
Annotation is an observation proposal; numeric gates live in the framework.
"""
import hashlib
import io
import json
from pathlib import Path
from PIL import Image
from .character_consistency import Observation, SEGMENTS, image_digest
from .campaign.specialists import extract_text
from ..v2.providers.wire import parse_spark_response


class ObservationInvalid(ValueError):
    """A retained completed response could not be used as observation evidence."""
    def __init__(self,key,raw_sha256,reason):
        self.execution_id=key;self.raw_sha256=raw_sha256
        super().__init__(reason)


def png(image):
    out=io.BytesIO();image.convert('RGBA').save(out,format='PNG');return out.getvalue()


def propose_observation(root,frame_id,image,reference,features,items,description,*,dispatch,persist,phase='measure',geometry_external=False):
    names=sorted({'head_top','chin','left_hand','right_hand'} | {p for pair in SEGMENTS.values() for p in pair} | {i['anchor'] for i in items} | {a for i in items for a in i.get('anchor_by_frame',{}).values()})
    rubric='''Annotate ACTUAL visible source pixels; never move coordinates to satisfy an expected design. This is measurement evidence, not art approval. Compare the SUBJECT rendering only: transparent surroundings, a viewer backing, and removal of the technical magenta backing are not style or palette failures. Image 1 is the canonical character reference; Image 2 is the frame to annotate. Coordinates are normalized 0..1000 across the ENTIRE image 2, including transparent padding. head_top is the anatomical skull crown EXCLUDING bun, braid and loose hair; chin is the lower jaw. head_left/right measure skull width, not hairstyle. neck and pelvis are visible body/garment junction centres (pelvis at hip line); do not invent hidden joint positions. Left/right are ANATOMICAL, never screen-left/right. Use the explicitly declared view and anatomical orientation; never infer hand ownership solely from screen position. If ownership cannot be established, mark it uncertain. Hands mean palm centres; wrists mean wrist joints. Width endpoints measure the VISIBLE OUTER RENDERED contour at the limb midsection, perpendicular to its long axis, not an axis-aligned rectangle. When clothed, measure the sleeve or boot-shaft outer contour as a rendered-part proxy; do NOT claim hidden skin/bone thickness. In particular calf_inner/outer are the visible boot-shaft edges when boots cover the calf, and arm_inner/outer use sleeve edges when covered. Mark occluded only when even those outer edges cannot be localized. Articulation changes angles, not intrinsic segment length. Occluded/uncertain points MUST have xy:null. Do not infer hidden bones. Return JSON only with keys points, features, items, limitation.
points: object keyed by all requested landmark names; values {"xy":[x,y] or null,"visibility":"visible"|"occluded"|"uncertain","evidence":"brief localized pixel observation"}.
features: object keyed by every requested feature ID; values {"status":"match"|"mismatch"|"uncertain"|"occluded","observed":"specific visible evidence in image 2","expected":"the referenced invariant"}. Compare facial identity/proportions independently of expression. Costume material, construction, colour and accessory placement must remain the same. Do not treat wetness/damage/expression as permission to change identity unless explicitly scoped in request.
items: object keyed by all declared item IDs and any EXTRA visible items (use undeclared_1 etc); values {"visibility":"visible"|"occluded"|"absent"|"uncertain","anchor":"actual anatomical hand or mount" or null,"grip":point object or null,"rigid_span":[point,point] or null,"features":{"design":feature,"palette":feature,"scale":feature,"attachment":feature},"evidence":"visible item and which hand/mount it really touches"}. rigid_span endpoints cover the named rigid component, not flexible overall pose; retain original material/construction when coiled or flexed. Report actual hand ownership, not desired ownership. A different hand, chain replacing leather, different handle, duplicate or disconnected item is a mismatch. Do not hide failures behind a generic high score.
limitation: concise honest statement about uncertain/occluded observations. No confidence calibration is implied.'''
    if geometry_external:
        standard={'head_top','chin','left_hand','right_hand','neck','pelvis'} | {p for pair in SEGMENTS.values() for p in pair}
        names=sorted(({i['anchor'] for i in items} | {a for i in items for a in i.get('anchor_by_frame',{}).values()})-standard)
    prompt=rubric+'\nLandmarks: '+json.dumps(names)+'\nFeature IDs: '+json.dumps(features)+'\nDeclared inventory: '+json.dumps(items)+'\nCharacter/request description: '+description
    if geometry_external:
        prompt+='\nGEOMETRY IS PROVIDED BY A SEPARATE PINNED LOCALIZER. Return points only for the requested nonstandard mount landmarks, using actual visible attachment locations; return points:{} when none are requested. Do not estimate other body coordinates or widths. Item grip, mount and rigid-span points require full xy/visibility/evidence objects. Focus on visible appearance, anatomical item ownership, exact item design and garment/face identity.'
    if 'format-recovery' in phase:
        schema=Observation.model_json_schema()
        keep={'points','features','items','limitation'}
        schema['properties']={k:v for k,v in schema['properties'].items() if k in keep}
        schema['required']=sorted(keep)
        prompt+='\nFORMAT RECOVERY: Return precisely this JSON schema, including visibility and evidence in EVERY grip and rigid-span point. Do not abbreviate point objects: '+json.dumps(schema)
    sha=image_digest(image)
    key=phase+'-'+frame_id+'-'+hashlib.sha256((sha+prompt+image_digest(reference)).encode()).hexdigest()[:16]
    raw=dispatch(Path(root),key,'muse-spark-1.3',prompt,[png(reference),png(image)])
    try:
        normalized=[]
        try:
            result=extract_text(raw)
        except json.JSONDecodeError:
            # Some completed model turns close the outer object immediately before
            # the final limitation field. Accept only this unambiguous, disjoint
            # top-level boundary repair, retaining the exact original response.
            text=parse_spark_response(json.loads(raw))['text']
            first,end=json.JSONDecoder().raw_decode(text)
            tail=text[end:].strip()
            if not tail.startswith(','):raise
            final=json.loads('{'+tail[1:])
            if set(first)!={'points','features','items'} or set(final)!={'limitation'}:raise ValueError('Ambiguous annotation JSON')
            result=dict(first,**final)
            normalized.append('Disjoint final limitation moved inside its premature root closing brace')
        if 'items' not in result and isinstance(result.get('features',{}).get('items'),dict):
            result['items']=result['features'].pop('items')
            normalized.append('Declared inventory moved from an unambiguous features.items nesting to root items')
        def clear_hidden(value):
            if isinstance(value,dict):
                if value.get('visibility') in {'uncertain','occluded'} and value.get('xy') is not None:
                    value['xy']=None;normalized.append('Discarded coordinates explicitly marked non-visible; remains unmeasured')
                for child in value.values():clear_hidden(child)
            elif isinstance(value,list):
                for child in value:clear_hidden(child)
        clear_hidden(result)
        trusted=dict(normalization=normalized,image_sha256=sha,frame_id=frame_id,execution_id=key,raw_sha256=hashlib.sha256(raw).hexdigest(),width=image.width,height=image.height)
        observation=Observation.model_validate(dict(result,**trusted))
        persist(Path(root)/'private'/(key+'-observation.json'),observation.model_dump(mode='json'))
        return observation
    except (ValueError,TypeError,KeyError) as error:
        raise ObservationInvalid(key,hashlib.sha256(raw).hexdigest(),str(error)) from error

