"""Install a login launcher for the supervised local development services.

Terminal supplies the user's existing removable-volume access context; direct
launchd children can otherwise wait indefinitely on external workspace access.
No privacy permissions or security settings are changed.
"""
import argparse
import os
from pathlib import Path
import plistlib
import shlex
import subprocess
import sys


def install(private_root,generation_roots=()):
    if sys.platform!='darwin':raise ValueError('Login service installation requires macOS')
    repo=Path(__file__).resolve().parents[1];private_root=Path(private_root).resolve()
    support=Path.home()/'Library/Application Support/Framebound';support.mkdir(parents=True,exist_ok=True)
    logs=Path.home()/'Library/Logs/Framebound';logs.mkdir(parents=True,exist_ok=True)
    command=support/'start-dev.command'
    argv=[sys.executable,str(repo/'scripts/supervise_dev.py'),'--private-root',str(private_root)]
    for root in generation_roots:argv.extend(['--generation-root',str(root)])
    text='#!/bin/zsh\ncd '+shlex.quote(str(repo))+'\nnohup '+shlex.join(argv)+' > '+shlex.quote(str(logs/'supervisor.log'))+' 2>&1 < /dev/null &\n'
    command.write_text(text);command.chmod(0o700)
    agents=Path.home()/'Library/LaunchAgents';agents.mkdir(parents=True,exist_ok=True)
    for old in ('api','web'):
        subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}/com.framebound.dev-{old}'],capture_output=True)
    label='com.framebound.dev-launcher';path=agents/(label+'.plist')
    value=dict(Label=label,ProgramArguments=['/usr/bin/open','-a','Terminal',str(command)],WorkingDirectory='/tmp',RunAtLoad=True,KeepAlive=False,
               StandardOutPath=str(logs/'launcher.out.log'),StandardErrorPath=str(logs/'launcher.err.log'))
    content=plistlib.dumps(value)
    if not path.exists() or path.read_bytes()!=content:
        subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}/{label}'],capture_output=True);path.write_bytes(content)
        subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(path)],check=True)
    print('Login launcher installed; supervisor restarts API/web after exits.',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--private-root',required=True,type=Path);p.add_argument('--generation-root',action='append',type=Path,default=[]);a=p.parse_args();install(a.private_root,a.generation_root)
