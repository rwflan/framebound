"""Audit a retained cohort together; original evidence is never rewritten."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from framebound.v3.character_cohort import assess,overlay
from framebound.v3.character_consistency import image_digest,digest,evaluate_frame
from scripts.build_movement_demo import send,save
from scripts.refine_character_demo import initialize,load_config


def review(root,state,slots):
    config,brief,manifest,public=load_config(root);policy=initialize(root)
    reference=Image.open(config['master_image']).convert('RGBA')
    selected=[brief['poses'][i]['id'] for i in slots]
    frames=[(fid,Image.open(state['frames'][fid]['image']).convert('RGBA')) for fid in selected]
    features=['body.upper_arm_bulk','body.forearm_bulk','body.thigh_bulk']
    results=[]
    for start in range(0,len(selected),3):
        results.append(assess(root,reference,frames,features,config['items'],config['description'],dispatch=send,persist=save,focus_ids=selected[start:start+3]))
    for fid,image in frames:
        result=next(e for e in results if any(row['frame_id']==fid for row in e['review']['frames']))
        row=state['frames'][fid];obs=overlay(row['observation'],result,image_digest(reference))
        row['observation']=obs.model_dump(mode='json')
        row['report']=evaluate_frame(policy,obs,image_sha256=image_digest(image),frame_id=fid,pixel_scale=row['pixel_scale'])
        save(root/'private'/('registered-observation-'+fid+'-'+image_digest(image)[:16]+'.json'),row['observation'])
        print(fid,[(i['code'],i['feature'],i['observed']) for i in row['report']['issues']],flush=True)
    state['policy_sha256']=digest(policy.model_dump(mode='json'))
    return state,results


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--state',default='run');args=p.parse_args()
    config,brief,manifest,public=load_config(args.root)
    state=json.loads(args.input.read_text());state,result=review(args.root,state,manifest['states'][args.state]['frames'])
    save(args.output,state)

if __name__=='__main__':main()
