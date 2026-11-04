"""Optional isolated pose runtime; never sends private images to a provider."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from framebound.v3.pose_measurement import HumanPoseObserver

p=argparse.ArgumentParser();p.add_argument('--image',type=Path,required=True);p.add_argument('--models',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
observer=HumanPoseObserver(args.models/'pose_landmarker_heavy.task',args.models/'face_landmarker.task')
try:result=observer.measure(Image.open(args.image))
finally:observer.close()
args.output.write_text(json.dumps(result,indent=2)+'\n')
