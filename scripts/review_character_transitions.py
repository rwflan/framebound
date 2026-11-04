"""Review declared transition pairs against retained sources; never waive negatives."""
import argparse
import fcntl
import json
from pathlib import Path
from PIL import Image
from framebound.v3.character_consistency import image_digest
from framebound.v3.transition_consistency import assess,evaluate
from scripts.build_movement_demo import send,save
from scripts.refine_character_demo import initialize,load_config


def review(root,state,*,only=None):
    root=Path(root);(root/'private').mkdir(parents=True,exist_ok=True)
    with (root/'private'/'transition-review.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        return _review(root,state,only=only)


def _review(root,state,*,only=None):
    config,*_=load_config(root);policy=initialize(root)
    reference=Image.open(config['master_image']).convert('RGBA')
    path=root/'transition-evidence.json'
    evidence=json.loads(path.read_text()) if path.exists() else []
    if not isinstance(evidence,list):evidence=[evidence]
    sources={fid:Image.open(row['image']).convert('RGBA') for fid,row in state['frames'].items() if row.get('image')}
    hashes={fid:image_digest(im) for fid,im in sources.items()}
    current={row['id']:row for row in evaluate(policy,evidence,hashes)}
    pairs={}
    for rule in policy.transitions:
        if only and only not in (rule.left,rule.right):continue
        if rule.left not in sources or rule.right not in sources:continue
        pairs.setdefault((rule.left,rule.right),[]).append(rule)
    for pair,rules in pairs.items():
        # A retained negative is actionable. Re-review unchanged artwork cannot clear it.
        if all(current[r.id]['status']!='unmeasured' for r in rules):continue
        result=assess(root,reference,[(fid,sources[fid]) for fid in pair],rules,config['description'],dispatch=send,persist=save,observations={fid:state['frames'][fid]['observation'] for fid in pair if state['frames'][fid].get('observation')})
        evidence.append(result);save(path,evidence)
        print('transition',*pair,flush=True)
    state['transitions']=evidence
    return evaluate(policy,evidence,hashes)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True,type=Path);parser.add_argument('--state',required=True,type=Path);parser.add_argument('--only')
    args=parser.parse_args();state=json.loads(args.state.read_text());result=review(args.root,state,only=args.only);save(args.state,state);save(args.root/'transition-results.json',result)
    print(json.dumps({s:sum(r['status']==s for r in result) for s in ('pass','fail','unmeasured')}))
