"""Independent recovery when pose-model palms contradict visible attachment.

The reviewer receives no desired item owner. It must trace both anatomical arm
chains from actual pixels, keeping uncertain palms unmeasured.
"""
import hashlib
import json
from pathlib import Path
from PIL import ImageDraw
from pydantic import Field
from ..v2.domain import Strict
from .character_consistency import Point,Observation,image_digest,digest,measurements
from .character_observations import png,ObservationInvalid
from .campaign.specialists import extract_text

VERSION='independent-anatomical-palms-v1'


class Palms(Strict):
    left_hand: Point
    right_hand: Point
    limitation: str = Field(min_length=1)


def recover(root,image,observation,*,dispatch,persist):
    obs=Observation.model_validate(observation)
    if obs.image_sha256!=image_digest(image):raise ValueError('Stale hand recovery source')
    overlay=image.copy();draw=ImageDraw.Draw(overlay)
    for name,color in [('left_hand','cyan'),('right_hand','yellow')]:
        p=obs.points.get(name)
        if p and p.visibility=='visible':
            x,y=p.xy[0]*image.width/1000,p.xy[1]*image.height/1000
            draw.ellipse((x-18,y-18,x+18,y+18),outline=color,width=6);draw.text((x+20,y),name,fill=color,stroke_width=1)
    prompt='''Independently locate BOTH anatomical palm centres in image ONE, normalized 0..1000 across the ENTIRE full image including transparent padding. Image TWO is a pose-model proposal overlay; it may have swapped its hand labels. Never trust those labels or infer anatomy from screen-left/right. Trace each shoulder -> upper arm -> elbow -> wrist -> palm in the ACTUAL source. Hands can cross in front of the chest. No requested object ownership is supplied: report actual anatomical hand locations, regardless of which hand holds an object. Return JSON only {"left_hand":{"xy":[x,y] or null,"visibility":"visible|uncertain|occluded","evidence":"specific shoulder/elbow/wrist chain to this palm"},"right_hand":same point object,"limitation":"honest limits"}. Mark ambiguous arm chains uncertain with xy:null. Do not move a palm toward an object to satisfy an attachment gate. Do not invent hidden hands.'''
    key='palm-recovery-'+digest([VERSION,obs.image_sha256,obs.model_dump(mode='json')['points'],prompt])[:20]
    raw=dispatch(Path(root),key,'muse-spark-1.3',prompt,[png(image),png(overlay)])
    try:result=Palms.model_validate(extract_text(raw))
    except (ValueError,TypeError,KeyError) as error:raise ObservationInvalid(key,hashlib.sha256(raw).hexdigest(),str(error)) from error
    evidence=dict(version=VERSION,image_sha256=obs.image_sha256,prior_points_sha256=digest(obs.model_dump(mode='json')['points']),execution_id=key,raw_sha256=hashlib.sha256(raw).hexdigest(),palms=result.model_dump(mode='json'),human_approval=False)
    persist(Path(root)/'private'/(key+'-review.json'),evidence)
    return result,evidence


def conflict(observation,scale_reference):
    obs=Observation.model_validate(observation);head=measurements(obs,scale_reference).get('head_px')
    if not head:return False
    for item in obs.items.values():
        if item.anchor not in ('left_hand','right_hand') or not item.grip or item.grip.visibility!='visible':continue
        own=obs.points.get(item.anchor)
        if not own or own.visibility!='visible':return True
        def distance(point):return (((point.xy[0]-item.grip.xy[0])*obs.width/1000)**2+((point.xy[1]-item.grip.xy[1])*obs.height/1000)**2)**.5/head
        if distance(own)>.4:return True
    return False
