"""Import Muse-authored sheets and model labels without generating artwork."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from framebound.v3.corpus import prepare

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--manifest',required=True)
parser.add_argument('--project',required=True)
parser.add_argument('--review')
parser.add_argument('--native-size',type=int,default=256)
args=parser.parse_args()
print(json.dumps(prepare(args.manifest,args.project,review_path=args.review,native_size=args.native_size),indent=2))
