"""Lower-torso material band, separate from the pose model's hip/skirt centre."""
import hashlib
import json
from pathlib import Path
import numpy as np
from . import material_geometry as previous
from . import pose_measurement as base


class HumanPoseObserver(previous.HumanPoseObserver):
    def __init__(self,*args):
        super().__init__(*args)
        self.recipe=dict(self.recipe,version='mediapipe-torso-band-v3',torso_implementation=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        self.recipe_sha256=hashlib.sha256(json.dumps(self.recipe,sort_keys=True).encode()).hexdigest()

    def measure(self,image):
        result=super().measure(image);points=result['points'];w,h=image.size
        neck,pelvis,top,chin=[base.xy(points,k,w,h) for k in ('neck','pelvis','face_top','face_chin')]
        sections=[]
        if all(v is not None for v in (neck,pelvis,top,chin)):
            head=float(np.linalg.norm(top-chin));axis=(pelvis-neck)*.5
            for fraction in (.4,.45,.5):
                centre=neck+(pelvis-neck)*fraction
                section=previous.material_section(image,centre-axis,centre+axis,head)
                if section:sections.append(section)
        lengths=[float(np.linalg.norm(s[1]-s[0])) for s in sections]
        valid=len(sections)>=2 and max(lengths)/min(lengths)<=1.3
        chosen=sections[int(np.argsort(lengths)[len(lengths)//2])] if valid else None
        for index,key in enumerate(('waist_left','waist_right')):
            points[key]=base.visible(*chosen[index],w,h,'Median consistent lower-torso garment band; not hip/skirt width or hidden anatomy') if valid else base.unknown('Lower-torso material band not consistently visible')
        return dict(result,points=points,recipe=self.recipe,recipe_sha256=self.recipe_sha256)
