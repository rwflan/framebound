"""Durable paid-operation execution: retained acceptance resumes by GET only."""
import fcntl
import hashlib
import json
from pathlib import Path


def write(path,value):
    import uuid
    raw=json.dumps(value,sort_keys=True,indent=2).encode();tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');tmp.write_bytes(raw);tmp.replace(path)


def run(folder,request,adapter,*,timeout=300):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    with (folder/'operation.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        result_path=folder/'response.json';receipt=folder/'receipt.json';marker=folder/'request.json';acceptance=folder/'acceptance.json'
        if marker.exists() and json.loads(marker.read_text())['wire']!=request['payload']['wire']:raise ValueError('Operation request is immutable')
        if result_path.exists():
            raw=result_path.read_bytes()
            if not marker.exists():raise ValueError('Cached result lacks a frozen commitment')
            if receipt.exists() and json.loads(receipt.read_text()).get('response_sha256')!=hashlib.sha256(raw).hexdigest():raise ValueError('Cached receipt digest mismatch')
            if not receipt.exists():
                body=json.loads(raw)
                if acceptance.exists():
                    from framebound.v3.campaign.specialists import validate_acceptance
                    validate_acceptance(request,body)
                    if body['id']!=json.loads(acceptance.read_text())['id']:raise ValueError('Cached result identity mismatch')
                result=adapter._result(request,raw)
                write(receipt,dict(incurred_microdollars=result.incurred,receipt=result.receipt,response_sha256=hashlib.sha256(raw).hexdigest()))
            return raw
        if marker.exists():
            retained=json.loads(marker.read_text())
            if retained['wire']!=request['payload']['wire']:raise ValueError('Operation request is immutable')
            if not acceptance.exists():raise FileExistsError('Acceptance unknown; use an authorized distinct recovery, never repeat this POST')
        else:
            write(marker,dict(wire=request['payload']['wire'],committed_microdollars=request['quote']))
        def accepted(body):
            # The adapter validates model, metadata and response identity first.
            if acceptance.exists() and json.loads(acceptance.read_text()).get('id')!=body['id']:raise ValueError('Acceptance identity changed')
            write(acceptance,body)
        def observed(raw):
            tmp=folder/'stream.sse.tmp';tmp.write_bytes(raw);tmp.replace(folder/'stream.sse')
        try:
            if acceptance.exists():result=adapter.retrieve(request,json.loads(acceptance.read_text()),timeout=timeout)
            elif request['payload']['wire'].get('stream'):
                result=adapter.execute_stream(request,timeout=timeout,on_acceptance=accepted,on_observation=observed)
            else:result=adapter.execute(request,timeout=timeout)
            tmp_result=folder/'response.json.tmp';tmp_result.write_bytes(result.raw);tmp_result.replace(result_path)
            write(receipt,dict(incurred_microdollars=result.incurred,receipt=result.receipt,response_sha256=hashlib.sha256(result.raw).hexdigest()))
            write(folder/'status.json',dict(status='terminal_result',provider_status=result.receipt.get('status'),response_sha256=hashlib.sha256(result.raw).hexdigest()))
            return result.raw
        except Exception as error:
            from framebound.v3.campaign.dispatch import ProviderRejected
            if isinstance(error,ProviderRejected):
                result=error.response;tmp_result=folder/'response.json.tmp';tmp_result.write_bytes(result.raw);tmp_result.replace(result_path)
                write(receipt,dict(incurred_microdollars=result.incurred,receipt=result.receipt,response_sha256=hashlib.sha256(result.raw).hexdigest()))
                write(folder/'status.json',dict(status='rejected_before_acceptance'))
                raise
            raw=getattr(error,'provider_observation_raw',None) or getattr(error,'raw',None)
            if raw:(folder/'error-response.bin').write_bytes(raw)
            previous=json.loads((folder/'status.json').read_text()) if (folder/'status.json').exists() else {}
            unavailable=acceptance.exists() and getattr(error,'code',None) in (404,410)
            failures=previous.get('retrieval_failures',0)+1 if unavailable else 0
            status='accepted_result_unavailable' if unavailable and failures>=3 else 'accepted_pending' if acceptance.exists() else 'acceptance_unknown'
            write(folder/'status.json',dict(status=status,retrieval_failures=failures,error_type=type(error).__name__,http_status=getattr(error,'code',None),request_ids=getattr(error,'provider_request_ids',{})))
            raise


def authorize_recovery(root,parent,new_name,*,authorization,max_recoveries=2,max_recovery_microdollars=1_000_000):
    """Freeze a new authorized operation; preserve every original commitment."""
    import re
    if parent==new_name or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,240}',name) for name in (parent,new_name)):raise ValueError('Distinct valid operation names required')
    root=Path(root);base=root/'private';old=base/parent/'request.json'
    if not authorization.strip():raise ValueError('Recovery authorization required')
    if not old.exists():raise ValueError('Original commitment missing')
    if (old.parent/'response.json').exists():raise ValueError('Original has a result; inspect it instead')
    with (base/'recovery-policy.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        target=base/new_name;target.mkdir(exist_ok=True);path=target/'recovery.json'
        existing_successor=old.parent/'successor.json'
        if existing_successor.exists() and json.loads(existing_successor.read_text())['operation']!=new_name:raise ValueError('An authorized successor already exists; resume that chain')
        original=json.loads(old.read_text());quote=original['committed_microdollars']
        if type(quote) is not int or quote<0:raise ValueError('Invalid original commitment')
        parent_sha=hashlib.sha256(old.read_bytes()).hexdigest()
        if path.exists():
            value=json.loads(path.read_text())
            if value['recovery_of']!=parent or value['parent_request_sha256']!=parent_sha:raise ValueError('Recovery linkage changed')
            return value
        history=[json.loads(p.read_text()) for p in base.glob('*/recovery.json')]
        parent_link=old.parent/'recovery.json'
        recovery_root=json.loads(parent_link.read_text()).get('recovery_root',parent) if parent_link.exists() else parent
        if sum(row.get('recovery_root',row['recovery_of'])==recovery_root for row in history)>=max_recoveries:raise ValueError('Authorized recovery count exhausted')
        if sum(row['committed_microdollars'] for row in history)+quote>max_recovery_microdollars:raise ValueError('Authorized recovery budget exhausted')
        value=dict(recovery_of=parent,recovery_root=recovery_root,parent_request_sha256=parent_sha,authorization=authorization,committed_microdollars=quote,original_status='accepted_result_unavailable' if (old.parent/'acceptance.json').exists() else 'acceptance_unknown',new_operation=new_name)
        write(path,value);return value
