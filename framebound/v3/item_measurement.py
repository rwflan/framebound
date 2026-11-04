"""Close-up rigid-component observations with exact crop/source transforms."""
import hashlib
from pathlib import Path
from pydantic import Field
from ..v2.domain import Strict
from .character_consistency import Point,Observation,ItemRule,image_digest,digest,measurements
from .character_observations import png,ObservationInvalid
from .campaign.specialists import extract_text

VERSION='native-item-component-v1'


class ComponentSpan(Strict):
    endpoints: tuple[Point,Point]
    component: str = Field(min_length=1,max_length=1000)
    limitation: str = Field(min_length=1,max_length=1000)


def measure(root,image,observation,rule,scale_reference,*,dispatch,persist,cache_roots=()):
    observation=Observation.model_validate(observation);rule=ItemRule.model_validate(rule)
    if image_digest(image)!=observation.image_sha256 or image.size!=(observation.width,observation.height):raise ValueError('Stale item measurement source')
    if not rule.rigid_measurement:raise ValueError('A named rigid component is required')
    item=observation.items.get(rule.id)
    if not item or item.visibility!='visible':raise ValueError('Visible item evidence required for detail localization')
    points=[]
    for p in [item.grip,observation.points.get(item.anchor),*(item.rigid_span or ())]:
        if p and p.visibility=='visible':points.append((p.xy[0]*image.width/1000,p.xy[1]*image.height/1000))
    head=measurements(observation,scale_reference).get('head_px')
    if not head or not points:raise ValueError('Missing source-bound component search scale/location')
    pad=head*1.4
    box=(max(0,int(min(p[0] for p in points)-pad)),max(0,int(min(p[1] for p in points)-pad)),min(image.width,int(max(p[0] for p in points)+pad+1)),min(image.height,int(max(p[1] for p in points)+pad+1)))
    crop=image.crop(box)
    prompt='''Localize the two terminal ends of ONLY the named rigid component in the SECOND image. The FIRST image supplies complete character/item context; the SECOND is a native-resolution crop of those exact pixels. Return JSON only: {"endpoints":[{"xy":[x,y],"visibility":"visible|occluded|uncertain","evidence":"which terminal end"},{"xy":[x,y],"visibility":"visible|occluded|uncertain","evidence":"which terminal end"}],"component":"actual visible component identified","limitation":"honest limitation"}. Coordinates are 0..1000 across the ENTIRE SECOND crop. Mark xy:null for hidden/uncertain endpoints. Do not measure coil diameter, flexible lash, total weapon length, a nearby belt, or the grip segment visible outside a fist instead of the full rigid component. For a wrapped handle, locate its actual two terminal ends, excluding the flexible strand and any unrelated end cap. If an end is hidden by the hand and cannot be localized, say occluded; never invent it. Report actual pixels, not the requested ideal length. No score or pass/fail verdict is requested.'''
    prompt+='\nItem design: '+rule.description+'\nExact rigid component: '+rule.rigid_measurement
    key='item-detail-'+digest([VERSION,observation.image_sha256,rule.model_dump(mode='json'),box,prompt])[:20]
    allowed=[Path(p).resolve() for p in (root,*cache_roots)]
    operation_root=allowed[0]
    for candidate in allowed:
        folder=candidate/'private'/key
        if (folder/'request.json').exists() or (folder/'response.json').exists():
            operation_root=candidate;break
    # Bind the logical component as well as the exact crop. A changed crop or
    # experiment directory cannot bypass a possibly accepted earlier request.
    import fcntl,json
    intent_root=min(allowed,key=str)/'private'/'item-detail-intents'
    intent_root.mkdir(parents=True,exist_ok=True)
    logical=digest([observation.image_sha256,rule.id,rule.rigid_measurement])
    journal=intent_root/(logical+'.json')
    with (intent_root/(logical+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if journal.exists():
            prior=json.loads(journal.read_text());prior_root=Path(prior['operation_root']).resolve()
            if prior_root not in allowed:raise ValueError('Component intent points outside declared lineage')
            folder=prior_root/'private'/prior['key']
            if (folder/'request.json').exists() and not (folder/'response.json').exists():
                raise FileExistsError('Unresolved logical component operation; do not resend with a different crop')
        journal.write_text(json.dumps(dict(key=key,operation_root=str(operation_root),image_sha256=observation.image_sha256,component=rule.rigid_measurement)))
        raw=dispatch(operation_root,key,'muse-spark-1.3',prompt,[png(image),png(crop)])
    try:
        result=ComponentSpan.model_validate(extract_text(raw));mapped=[]
        for p in result.endpoints:
            if p.visibility=='visible':
                x=box[0]+p.xy[0]*crop.width/1000;y=box[1]+p.xy[1]*crop.height/1000
                p=p.model_copy(update={'xy':(x/image.width*1000,y/image.height*1000)})
            mapped.append(p)
        data=observation.model_dump(mode='json');data['items'][rule.id]['rigid_span']=[p.model_dump(mode='json') for p in mapped]
        evidence=dict(version=VERSION,image_sha256=observation.image_sha256,crop=list(box),crop_sha256=image_digest(crop),
                      execution_id=key,operation_root=str(operation_root),raw_sha256=hashlib.sha256(raw).hexdigest(),component=result.component,limitation=result.limitation)
        data['measurement_sources'].setdefault('item_detail',{})[rule.id]=evidence
        measured=Observation.model_validate(data)
        persist(Path(root)/'private'/(key+'-measurement.json'),dict(evidence=evidence,observation=measured.model_dump(mode='json')))
        return measured
    except (ValueError,TypeError,KeyError) as error:raise ObservationInvalid(key,hashlib.sha256(raw).hexdigest(),str(error)) from error
