"""Keep local API/web children alive across agent sessions; no provider retries."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


class Adopted:
    """Monitor an existing owned service after supervisor replacement."""
    def __init__(self,pid,signature):self.pid=pid;self.signature=signature
    def poll(self):
        try:current=subprocess.check_output(['ps','-p',str(self.pid),'-o','lstart=','-o','command='],stderr=subprocess.DEVNULL).strip()
        except subprocess.CalledProcessError:return 0
        return None if current==self.signature else 0


def supervise(private_root,generation_roots=()):
    repo=Path(__file__).resolve().parents[1];private_root=Path(private_root);private_root.mkdir(exist_ok=True)
    logs=Path.home()/'Library/Logs/Framebound';logs.mkdir(parents=True,exist_ok=True)
    with (private_root/'dev-supervisor.lock').open('a+b') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        node=shutil.which('node') or '/opt/homebrew/opt/node@22/bin/node'
        specs={'api':([sys.executable,'-m','framebound','serve','--project',str(private_root/'project'),'--port','8765'],repo),
               'web':([node,str(repo/'web/node_modules/vite/bin/vite.js'),'--host','127.0.0.1','--port','5173','--strictPort'],repo/'web')}
        for index,root in enumerate(generation_roots):
            specs['provider-'+str(index)]=([sys.executable,'-m','scripts.provider_worker','--root',str(root)],repo)
            specs['refiner-'+str(index)]=([sys.executable,'-m','scripts.refinement_worker','--root',str(root)],repo)
        children={};previous=private_root/'dev-services.json'
        if previous.exists():
            prior=json.loads(previous.read_text())
            for name,pid in prior.get('children',{}).items():
                if name not in specs:continue
                try:signature=subprocess.check_output(['ps','-p',str(pid),'-o','lstart=','-o','command='],stderr=subprocess.DEVNULL).strip()
                except subprocess.CalledProcessError:continue
                if all(arg in signature.decode() for arg in specs[name][0][1:]):children[name]=Adopted(pid,signature)
        files={name:(logs/(name+'.log')).open('ab',buffering=0) for name in specs}
        while True:
            for name,(argv,cwd) in specs.items():
                if name not in children or children[name].poll() is not None:
                    children[name]=subprocess.Popen(argv,cwd=cwd,stdin=subprocess.DEVNULL,stdout=files[name],stderr=subprocess.STDOUT,start_new_session=True)
            state=dict(supervisor_pid=os.getpid(),children={name:p.pid for name,p in children.items()})
            temporary=private_root/'dev-services.json.tmp';temporary.write_text(json.dumps(state));temporary.replace(private_root/'dev-services.json')
            time.sleep(5)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--private-root',required=True,type=Path);p.add_argument('--generation-root',action='append',type=Path,default=[]);a=p.parse_args();supervise(a.private_root,a.generation_root)
