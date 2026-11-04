"""Versioned seam-tolerant visible material sections; no hidden body inference."""
import colorsys
import hashlib
import json
from pathlib import Path
import numpy as np
from . import pose_measurement as base


def material_section(image,a,b,head):
    pixels=np.asarray(image.convert('RGBA'));h,w=pixels.shape[:2]
    axis=b-a;length=float(np.linalg.norm(axis))
    if head<4 or length<4:return None
    centre=(a+b)/2;normal=np.asarray([-axis[1],axis[0]])/length
    core=[]
    for d in np.linspace(-head*.12,head*.12,17):
        x,y=np.rint(centre+normal*d).astype(int)
        if 0<=x<w and 0<=y<h and pixels[y,x,3]>=128:core.append(pixels[y,x,:3])
    if len(core)<12:return None
    hue,saturation,value=colorsys.rgb_to_hsv(*(np.median(core,axis=0)/255))
    def matching(pos):
        x,y=np.rint(pos).astype(int)
        if not 0<=x<w or not 0<=y<h or pixels[y,x,3]<32:return False
        ch,cs,cv=colorsys.rgb_to_hsv(*(pixels[y,x,:3]/255))
        return (min(abs(ch-hue),1-abs(ch-hue))<.065 and abs(cs-saturation)<.35) or (saturation<.18 and cs<.23 and abs(cv-value)<.4)
    ends=[];bridge=max(3,min(12,round(head*.07)))
    for sign in (-1,1):
        gap=0;last=None
        for d in range(0,max(8,round(head*1.5))):
            pos=centre+sign*d*normal
            if matching(pos):last=pos;gap=0
            else:gap+=1
            if gap>bridge:break
        else:return None
        if last is None:return None
        ends.append(last)
    span=float(np.linalg.norm(ends[1]-ends[0]))
    # A tiny internal stripe cannot stand in for a rendered body section.
    if span<max(4,head*.2) or span>length*.75:return None
    return ends


class HumanPoseObserver(base.HumanPoseObserver):
    def __init__(self,*args):
        super().__init__(*args)
        self.recipe=dict(self.recipe,version='mediapipe-material-v2',material_implementation=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        self.recipe_sha256=hashlib.sha256(json.dumps(self.recipe,sort_keys=True).encode()).hexdigest()

    def measure(self,image):
        result=super().measure(image);points=result['points'];w,h=image.size
        top,chin=[base.xy(points,k,w,h) for k in ('face_top','face_chin')]
        if top is None or chin is None:return dict(result,recipe=self.recipe,recipe_sha256=self.recipe_sha256)
        head=float(np.linalg.norm(top-chin))
        sections=[]
        for side in ('left','right'):
            for name,a,b in [('arm',side+'_shoulder',side+'_elbow'),('thigh',side+'_hip',side+'_knee'),('calf',side+'_knee',side+'_ankle')]:
                sections.append((side+'_'+name,base.xy(points,a,w,h),base.xy(points,b,w,h),('inner','outer')))
        neck,pelvis=[base.xy(points,k,w,h) for k in ('neck','pelvis')]
        if neck is not None and pelvis is not None:
            for name,t in [('chest',.3),('waist',.55)]:
                centre=neck+(pelvis-neck)*t;axis=(pelvis-neck)*.5
                sections.append((name,centre-axis,centre+axis,('left','right')))
        for name,a,b,keys in sections:
            section=material_section(image,a,b,head) if a is not None and b is not None else None
            for i,key in enumerate(keys):
                points[name+'_'+key]=base.visible(*section[i],w,h,'Seam-tolerant visible material cross-section; not hidden anatomy') if section else base.unknown('Material cross-section ambiguous; no fabricated span')
        return dict(result,points=points,recipe=self.recipe,recipe_sha256=self.recipe_sha256)
