"""Resume active retained provider jobs; accepted jobs are always GET-only."""
import argparse
import base64
import fcntl
import json
from pathlib import Path
import time
from scripts.provider_operation import run,write
from scripts.build_movement_demo import send,refresh_costs
from framebound.v3.campaign.specialists import MuseResponses


def tick(root):
    root=Path(root);progress=[]
    for marker in sorted((root/'private').glob('*/request.json')):
        folder=marker.parent
        if not (folder/'job.json').exists() or (folder/'response.json').exists() or (folder/'successor.json').exists():continue
        with (folder/'operation.lock').open('a+b') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:continue  # The original request is still in flight.
            request=json.loads(marker.read_text());wire=request['wire'];accepted=(folder/'acceptance.json').exists()
        try:
            if accepted:
                quote=request['committed_microdollars'];run(folder,dict(payload=dict(wire=wire,quote=quote),quote=quote),MuseResponses(),timeout=30)
            else:
                texts=[];images=[]
                for item in wire['input']:
                    for part in item['content']:
                        if part['type']=='input_text':texts.append(part['text'])
                        elif part['type']=='input_image':
                            uri=part['image_url']
                            if not uri.startswith('data:image/'):raise ValueError('Only retained inline images supported')
                            images.append(base64.b64decode(uri.split(',',1)[1],validate=True))
                size=next((t['size'] for t in wire.get('tools',[]) if t['type']=='image_generation'),'1536x1024')
                send(root,folder.name,wire['model'],'\n'.join(texts),images,image_size=size)
            progress.append(dict(operation=folder.name,status='result_available'))
        except Exception as error:
            status=json.loads((folder/'status.json').read_text()) if (folder/'status.json').exists() else {}
            config=json.loads((root/'config.json').read_text());policy=config.get('provider_recovery_policy',{})
            if status.get('status')=='accepted_result_unavailable' and policy.get('authorization'):
                from scripts.recover_provider_operation import recover
                try:
                    recover(root,folder.name,folder.name+'-unavailable-recovery-1',policy['authorization'])
                    progress.append(dict(operation=folder.name,status='linked_recovery_result_available'))
                except Exception as failure:progress.append(dict(operation=folder.name,status='pending',reason=type(failure).__name__))
            else:progress.append(dict(operation=folder.name,status='pending',reason=type(error).__name__))
        refresh_costs(root)
    write(root/'provider-worker-status.json',dict(jobs=progress))
    return progress


def serve(root):
    root=Path(root)
    with (root/'private'/'provider-worker.lock').open('a+b') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        while True:
            try:tick(root)
            except Exception as error:write(root/'provider-worker-status.json',dict(status='pending',reason=type(error).__name__))
            time.sleep(5)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True,type=Path);p.add_argument('--once',action='store_true');a=p.parse_args();tick(a.root) if a.once else serve(a.root)
