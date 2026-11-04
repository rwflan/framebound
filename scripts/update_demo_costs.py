"""Refresh an independent cost sidecar without touching live animation revisions."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from framebound.v3.experiment_costs import summarize
from scripts.build_movement_demo import save


def _update_locked(root, *, cache=None):
    config=json.loads((root/'config.json').read_text())
    roots=config.get('cost_lineage_roots')
    if not roots:raise ValueError('Explicit experiment cost lineage is required')
    report=summarize(roots,cache=cache)
    previous=root/'cost-ledger.json'
    if previous.exists() and json.loads(previous.read_text())['summary']['observed_microdollars']>report['summary']['observed_microdollars']:
        raise ValueError('Recorded provider cost regressed; reconcile missing lineage instead of resetting spend')
    save(previous,report)
    summary=report['summary'];public=Path(config['publish_root'])
    public_previous=public/'costs.json'
    if public_previous.exists() and json.loads(public_previous.read_text())['observed_microdollars']>summary['observed_microdollars']:
        raise ValueError('Public provider cost regressed; reconcile missing lineage')
    save(public_previous,summary)
    print('Provider observed USD',summary['observed_microdollars']/1e6,'unreconciled reserve USD',summary['unreconciled_reserve_microdollars']/1e6,flush=True)
    return summary


def update(root, *, cache=None):
    import fcntl
    config=json.loads((root/'config.json').read_text());public=Path(config['publish_root'])
    with (public/'.costs.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        return _update_locked(root,cache=cache)


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--watch',action='store_true');p.add_argument('--cycles',type=int,default=360);args=p.parse_args()
    if args.cycles<1:p.error('Positive bounded cycles required')
    cache={}
    for cycle in range(args.cycles if args.watch else 1):
        update(args.root,cache=cache)
        if args.watch and cycle+1<args.cycles:time.sleep(15)

if __name__=='__main__':main()
