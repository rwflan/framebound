"""Optional isolated pose runtime; never sends private images to a provider."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from framebound.v3.pose_measurement import HumanPoseObserver

p=argparse.ArgumentParser();p.add_argument('--image',type=Path,required=True);p.add_argument('--models',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--backend',choices=['v1','material-v2','torso-v3'],default='v1');args=p.parse_args()
if args.backend=='material-v2':
    from framebound.v3.material_geometry import HumanPoseObserver
if args.backend=='torso-v3':
    from framebound.v3.torso_geometry import HumanPoseObserver
observer=HumanPoseObserver(args.models/'pose_landmarker_heavy.task',args.models/'face_landmarker.task')
try:result=observer.measure(Image.open(args.image))
finally:observer.close()
import tempfile,os
with tempfile.NamedTemporaryFile('w',dir=args.output.parent,delete=False) as stream:
    json.dump(result,stream,indent=2);temporary=stream.name
os.replace(temporary,args.output)
