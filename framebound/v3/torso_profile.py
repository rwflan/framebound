"""Native visible-garment width profile in the observed torso coordinate frame.

The configurable material filter measures rendered garment pixels, not hidden
anatomy. Ambiguous/insufficient source coverage remains unmeasured.
"""
import hashlib
from pathlib import Path
import numpy as np
from .character_consistency import Observation,image_digest,measurements,point

VERSION='torso-material-profile-v1'


def measure(image,observation,scale_reference=('face_top','face_chin'),*,max_saturation=.28,min_value=80):
    obs=Observation.model_validate(observation)
    if obs.image_sha256!=image_digest(image) or (obs.width,obs.height)!=image.size:raise ValueError('Stale torso profile source')
    neck,pelvis=point(obs,'neck'),point(obs,'pelvis');head=measurements(obs,scale_reference).get('head_px')
    result=dict(version=VERSION,image_sha256=obs.image_sha256,implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),measured=False,sections=[],scope='Visible low-saturation torso garment only; no physical body-volume claim',material_filter=dict(max_saturation=max_saturation,min_value=min_value),scale_reference=list(scale_reference))
    if not neck or not pelvis or not head:return dict(result,reason='Missing source-bound torso/scale landmarks')
    start,end=np.array(neck),np.array(pelvis);axis=end-start;length=np.linalg.norm(axis)
    if length<head:return dict(result,reason='Ambiguous torso axis')
    normal=np.array([-axis[1],axis[0]])/length;rgba=np.asarray(image.convert('RGBA'));rows=[]
    offsets=np.arange(-int(head*2),int(head*2)+1)
    for t in np.linspace(.12,.55,18):
        centre=start+axis*t;positions=np.rint(centre+offsets[:,None]*normal).astype(int)
        inside=(positions[:,0]>=0)&(positions[:,0]<image.width)&(positions[:,1]>=0)&(positions[:,1]<image.height)
        colors=np.zeros((len(offsets),4));colors[inside]=rgba[positions[inside,1],positions[inside,0]]
        high=colors[:,:3].max(axis=1);low=colors[:,:3].min(axis=1)
        mask=inside&(colors[:,3]>=128)&(high>=min_value)&((high-low)/np.maximum(high,1)<=max_saturation)
        # Bridge only narrow trim/seam gaps in the declared material.
        indices=np.flatnonzero(mask);groups=[]
        if len(indices):
            for group in np.split(indices,np.where(np.diff(indices)>max(3,int(head*.09)))[0]+1):
                left,right=offsets[group[0]],offsets[group[-1]];width=right-left
                if .55*head<=width<=2.6*head and abs((left+right)/2)<=head*.6:
                    groups.append((width,left,right,len(group)/max(1,width+1)))
        if not groups:continue
        width,left,right,coverage=max(groups)
        if coverage<.6:continue
        rows.append(width/head)
        result['sections'].append(dict(t=float(t),relative_width=float(width/head),coverage=float(coverage)))
    if len(rows)<7:return dict(result,reason='Insufficient unambiguous visible torso material sections')
    q=np.quantile(rows,[.5,.85]);result.update(measured=True,profile=[float(v) for v in q],relative_length=float(length/head))
    return result
