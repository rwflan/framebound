"""Resume explicitly configured refinement runs without resetting their budgets."""
import argparse
import fcntl
import json
from pathlib import Path
import time
from scripts.continue_character_demo import continue_run
from scripts.provider_operation import write


def serve(root):
    root=Path(root).resolve()
    with (root/'private/refinement-worker.lock').open('a+b') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        while True:
            config=root/'refinement-worker-config.json'
            if config.exists():
                for job in json.loads(config.read_text()).get('runs',[]):
                    name=job['run_id']
                    if not name.replace('-','').isalnum():continue
                    state=(root/job['state']).resolve()
                    if not state.is_relative_to(root):continue
                    ledger=root/('refinement-run-'+name+'.json')
                    status=json.loads(ledger.read_text()).get('status') if ledger.exists() else 'running'
                    if status not in ('running','provider_recovery_pending'):continue
                    try:continue_run(root,state,name,job['max_generations'],job.get('publish_preview',False))
                    except Exception as error:write(root/'refinement-worker-status.json',dict(run_id=name,status='pending',reason=type(error).__name__))
            time.sleep(5)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True,type=Path);a=p.parse_args();serve(a.root)
