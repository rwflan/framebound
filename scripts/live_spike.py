"""Persistent participant-authorized specialist spike; never seeds or approves art."""
import json
import os
from pathlib import Path
import sys


def run(work_dir):
    from framebound.v2 import recorded_run as RR
    from framebound.v2.providers import base
    from framebound.v2.services.provider_grants import get_grant
    from framebound.v2.services.errors import InvalidInput
    work=Path(work_dir).expanduser().absolute();work.mkdir(parents=True,exist_ok=True)
    config_path=work/'live-config.json'
    if not config_path.exists():
        config_path.write_text(json.dumps({'project_dir':'<existing approved project>','contract_id':'<contract>',
            'slot':0,'baseline_revision_id':'<baseline>','new_revision_id':'<new revision>',
            'idempotency_key':'participant-spike-1','grant_id':'<operator-issued grant>'},indent=2)+'\n')
        print('PENDING: fill the persistent participant configuration at '+str(config_path));return 3
    config=json.loads(config_path.read_text())
    required={'project_dir','contract_id','slot','baseline_revision_id','new_revision_id','idempotency_key','grant_id'}
    if set(config)!=required or any('<' in str(value) for value in config.values()):
        print('PENDING: live-config.json needs exact project/contract/slot/baseline/new revision/key/grant values');return 3
    if type(config['slot']) is not int or config['slot']<0:raise InvalidInput('live slot must be a nonnegative integer')
    project=Path(config['project_dir']).expanduser().absolute()
    if not (project/'framebound.sqlite3').is_file():
        print('PENDING: configured project is unavailable; no project was created');return 3
    if not base._key():print('PENDING: participant MODEL_API_KEY or META_API_KEY is absent');return 3
    if not os.environ.get('FRAMEBOUND_SPEND_CEILING'):
        print('PENDING: set an explicit calls-N ceiling, or a USD ceiling backed by an operator-reviewed quote grant');return 3
    try:
        grant=get_grant(str(project),config['grant_id'])['grant']
        if not grant['active']:raise InvalidInput('operator provider grant is revoked')
        RR.prepare(str(project),config['contract_id'],config['slot'])
    except (KeyError,InvalidInput) as exc:
        print('PENDING: participant reference/grant input required: '+str(exc));return 3
    old=os.environ.get('FRAMEBOUND_PROVIDER_GRANT')
    os.environ['FRAMEBOUND_PROVIDER_GRANT']=config['grant_id']
    try:
        bundle=RR.run_recorded(str(project),str(work/'live-bundle.json'),contract_id=config['contract_id'],slot=config['slot'],
            baseline_revision_id=config['baseline_revision_id'],new_revision_id=config['new_revision_id'],offline=False,
            idempotency_key=config['idempotency_key'])
    finally:
        if old is None:os.environ.pop('FRAMEBOUND_PROVIDER_GRANT',None)
        else:os.environ['FRAMEBOUND_PROVIDER_GRANT']=old
    capabilities={cap['capability']:cap['status'] for cap in bundle.get('capabilities',[])}
    print(json.dumps({'status':bundle['status'],'origin':bundle['origin'],'capabilities':capabilities,'bundle':str(work/'live-bundle.json')},indent=2))
    expected={'image-generation','image-edit','sam-segmentation'}
    return 0 if bundle['origin']=='live' and bundle['status']=='recorded' and set(capabilities)==expected and all(v=='recorded' for v in capabilities.values()) else 1


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('usage: python scripts/live_spike.py PERSISTENT_WORK_DIR')
    raise SystemExit(run(sys.argv[1]))
