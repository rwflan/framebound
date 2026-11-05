"""Create an explicitly authorized successor, retaining the unresolved parent."""
import argparse
import base64
import json
from pathlib import Path
from scripts.provider_operation import authorize_recovery,write
from scripts.build_movement_demo import send


def recover(root,parent,name,authorization):
    config=json.loads((root/'config.json').read_text());policy=config.get('provider_recovery_policy',{})
    link=authorize_recovery(root,parent,name,authorization=authorization,max_recoveries=policy.get('max_successors_per_parent',2),max_recovery_microdollars=policy.get('max_recovery_microdollars',1000000))
    write(root/'private'/parent/'successor.json',dict(operation=name,original_acceptance='unknown',commitment_retained=True))
    wire=json.loads((root/'private'/parent/'request.json').read_text())['wire'];texts=[];images=[]
    for message in wire['input']:
        for part in message['content']:
            if part['type']=='input_text':texts.append(part['text'])
            elif part['type']=='input_image':
                uri=part['image_url']
                if not uri.startswith('data:image/'):raise ValueError('Only retained local inline images may be recovered')
                images.append(base64.b64decode(uri.split(',',1)[1],validate=True))
            else:raise ValueError('Unsupported retained input')
    size=next((t['size'] for t in wire.get('tools',[]) if t['type']=='image_generation'),'1536x1024')
    return send(root,name,wire['model'],'\n'.join(texts),images,image_size=size)


def resume(root,name):
    """Resume the immutable original wire or its authorized linked successor."""
    folder=root/'private'/name;successor=folder/'successor.json'
    if successor.exists():return resume(root,json.loads(successor.read_text())['operation'])
    marker=json.loads((folder/'request.json').read_text());quote=marker['committed_microdollars']
    from scripts.provider_operation import run
    from scripts.build_movement_demo import refresh_costs
    from framebound.v3.campaign.specialists import MuseResponses
    try:return run(folder,dict(payload=dict(wire=marker['wire'],quote=quote),quote=quote),MuseResponses(),timeout=300)
    except FileExistsError:
        config=json.loads((root/'config.json').read_text());policy=config.get('provider_recovery_policy',{})
        if not policy.get('authorization'):raise
        return recover(root,name,name+'-recovery-1',policy['authorization'])
    finally:refresh_costs(root)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True,type=Path);p.add_argument('--parent',required=True);p.add_argument('--name',required=True);p.add_argument('--authorization',required=True);a=p.parse_args();recover(a.root,a.parent,a.name,a.authorization)
