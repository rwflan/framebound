"""Optional pinned human-pose localizer plus raster cross-sections.

These are image-space model estimates, never 3D physical measurements. Clothing
and occlusion are explicit; uncertain detections cannot fall back to invented
coordinates. MediaPipe is loaded only when this backend is selected.
"""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

VERSION='mediapipe-raster-v1'
JOINTS={'left_shoulder':11,'right_shoulder':12,'left_elbow':13,'right_elbow':14,'left_wrist':15,'right_wrist':16,'left_hip':23,'right_hip':24,'left_knee':25,'right_knee':26,'left_ankle':27,'right_ankle':28}


def unknown(reason):return dict(xy=None,visibility='uncertain',evidence=reason)

def visible(x,y,width,height,reason):
    if not 0<=x<width or not 0<=y<height:return unknown('Localizer point outside source')
    return dict(xy=[x/width*1000,y/height*1000],visibility='visible',evidence=reason)


def xy(points,name,width,height):
    p=points.get(name)
    if not p or p['visibility']!='visible':return None
    return np.asarray([p['xy'][0]*width/1000,p['xy'][1]*height/1000])


def raster_width(image,a,b,head):
    """Visible rendered-colour cross-section, including sleeve/boot surfaces.

    Stop at a source-alpha or local material boundary; short seam/outline gaps
    can bridge at most two pixels. Never estimate anatomy underneath clothing.
    """
    rgba=np.asarray(image.convert('RGBA'));height,width=rgba.shape[:2]
    delta=b-a;length=float(np.linalg.norm(delta))
    if length<4 or head<4:return None
    centre=(a+b)/2;normal=np.asarray([-delta[1],delta[0]])/length
    cx,cy=np.rint(centre).astype(int)
    if not (2<=cx<width-2 and 2<=cy<height-2):return None
    sample=rgba[cy-1:cy+2,cx-1:cx+2]
    if np.median(sample[:,:,3])<128:return None
    import colorsys
    rgb=np.median(sample[:,:,:3],axis=(0,1))/255
    hue,saturation,value=colorsys.rgb_to_hsv(*rgb)
    def same(pos):
        x,y=np.rint(pos).astype(int)
        if not 0<=x<width or not 0<=y<height or rgba[y,x,3]<32:return False
        h,s,v=colorsys.rgb_to_hsv(*(rgba[y,x,:3]/255))
        hue_distance=min(abs(h-hue),1-abs(h-hue))
        return (hue_distance<=.065 and abs(s-saturation)<=.35) or (saturation<.18 and s<.23 and abs(v-value)<.4)
    endpoints=[]
    limit=max(8,int(head*1.5))
    for sign in (-1,1):
        gap=0;last=centre
        for distance in range(1,limit+1):
            pos=centre+normal*distance*sign
            if same(pos):gap=0;last=pos
            else:gap+=1
            if gap>=3:break
        else:return None
        endpoints.append(last)
    span=float(np.linalg.norm(endpoints[1]-endpoints[0]))
    if span<4 or span>length*.75:return None
    return endpoints


class HumanPoseObserver:
    def __init__(self,pose_model,face_model):
        import mediapipe as mp
        self.mp=mp
        self.paths=[Path(pose_model),Path(face_model)]
        self.pose=mp.tasks.vision.PoseLandmarker.create_from_options(mp.tasks.vision.PoseLandmarkerOptions(base_options=mp.tasks.BaseOptions(model_asset_path=str(pose_model)),running_mode=mp.tasks.vision.RunningMode.IMAGE,num_poses=2,min_pose_detection_confidence=.6,min_pose_presence_confidence=.6))
        self.face=mp.tasks.vision.FaceLandmarker.create_from_options(mp.tasks.vision.FaceLandmarkerOptions(base_options=mp.tasks.BaseOptions(model_asset_path=str(face_model)),running_mode=mp.tasks.vision.RunningMode.IMAGE,num_faces=1,min_face_detection_confidence=.4,min_face_presence_confidence=.4))
        self.recipe=dict(version=VERSION,runtime=mp.__version__,models=[hashlib.sha256(p.read_bytes()).hexdigest() for p in self.paths],implementation=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        self.recipe_sha256=hashlib.sha256(json.dumps(self.recipe,sort_keys=True).encode()).hexdigest()

    def close(self):self.pose.close();self.face.close()

    def measure(self,image):
        mp=self.mp;image=image.convert('RGBA');width,height=image.size
        white=Image.new('RGBA',image.size,(245,245,245,255));white.alpha_composite(image);rgb=white.convert('RGB')
        result=self.pose.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=np.asarray(rgb)))
        points={k:unknown('No unique detected human pose') for k in [*JOINTS,'left_hand','right_hand','neck','pelvis','face_top','face_chin']}
        for name in ('chest','waist','left_arm','right_arm','left_thigh','right_thigh','left_calf','right_calf'):
            for side in ('left','right') if name in ('chest','waist') else ('inner','outer'):points[name+'_'+side]=unknown('No valid visible raster cross-section')
        if len(result.pose_landmarks)!=1:return dict(points=points,recipe=self.recipe,recipe_sha256=self.recipe_sha256,pose_count=len(result.pose_landmarks))
        landmarks=result.pose_landmarks[0]
        def localized(index):
            p=landmarks[index]
            if p.visibility<.65 or p.presence<.8:return unknown('Pose-model visibility/presence below measurement threshold')
            x,y=p.x*width,p.y*height
            if not 0<=x<width or not 0<=y<height:return unknown('Out-of-source pose estimate')
            if np.asarray(image)[int(y),int(x),3]<32:return unknown('Pose estimate has no foreground pixel support')
            return visible(x,y,width,height,'Pinned pose model image-space estimate; confidence is not physical calibration')
        for name,index in JOINTS.items():points[name]=localized(index)
        for side,indices in [('left',(15,17,19)),('right',(16,18,20))]:
            if all(landmarks[i].visibility>=.65 for i in indices):
                x=sum(landmarks[i].x for i in indices)/3*width;y=sum(landmarks[i].y for i in indices)/3*height
                points[side+'_hand']=visible(x,y,width,height,'Pose-model palm proxy from wrist/index/pinky')
        for name,pair in [('neck',('left_shoulder','right_shoulder')),('pelvis',('left_hip','right_hip'))]:
            if all(points[k]['visibility']=='visible' for k in pair):
                a,b=[xy(points,k,width,height) for k in pair];mid=(a+b)/2
                points[name]=visible(*mid,width,height,'Midpoint of observed pose landmarks')
        nose=landmarks[0];radius=max(140,math.hypot(nose.x-landmarks[8].x,nose.y-landmarks[8].y)*width*3)
        for factor in (1.,.7,1.4):
            r=radius*factor;box=(max(0,int(nose.x*width-r)),max(0,int(nose.y*height-r)),min(width,int(nose.x*width+r)),min(height,int(nose.y*height+r)))
            crop=rgb.crop(box);face=self.face.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=np.asarray(crop)))
            if len(face.face_landmarks)==1:
                for name,index in [('face_top',10),('face_chin',152)]:
                    p=face.face_landmarks[0][index];points[name]=visible(p.x*crop.width+box[0],p.y*crop.height+box[1],width,height,'Pinned face-model oval surface landmark; scale proxy, not skull or 3D size')
                break
        top,chin=xy(points,'face_top',width,height),xy(points,'face_chin',width,height)
        if top is not None and chin is not None:
            head=float(np.linalg.norm(top-chin))
            for side in ('left','right'):
                for feature,a,b in [('arm',side+'_shoulder',side+'_elbow'),('thigh',side+'_hip',side+'_knee'),('calf',side+'_knee',side+'_ankle')]:
                    start,end=xy(points,a,width,height),xy(points,b,width,height)
                    section=raster_width(image,start,end,head) if start is not None and end is not None else None
                    if section:
                        for key,pos in zip(('inner','outer'),section):points[side+'_'+feature+'_'+key]=visible(*pos,width,height,'Rendered material cross-section, not hidden tissue width')
            neck,pelvis=xy(points,'neck',width,height),xy(points,'pelvis',width,height)
            if neck is not None and pelvis is not None:
                for name,t in [('chest',.3),('waist',.85)]:
                    centre=neck+(pelvis-neck)*t;axis=(pelvis-neck)*.5
                    section=raster_width(image,centre-axis,centre+axis,head)
                    if section:
                        for key,pos in zip(('left','right'),section):points[name+'_'+key]=visible(*pos,width,height,'Visible garment cross-section; hidden body volume remains unmeasured')
        return dict(points=points,recipe=self.recipe,recipe_sha256=self.recipe_sha256,pose_count=1)
