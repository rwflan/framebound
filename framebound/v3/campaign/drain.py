"""Finish unaffected members of an interrupted cohort without passing its gate."""
import hashlib
import json
from filelock import FileLock
from .contracts import Identity,canonical,digest,local_path
from .ledger import Ledger
from .runner import Runner
from .progression import cohort_evidence


def run(root,campaign,*,parent_batch,version,specialist,max_cases=20):
    Identity(id=parent_batch);Identity(id=version)
    if type(max_cases) is not int or not 1<=max_cases<=20:raise ValueError('bounded cohort continuation requires1..20cases')
    ledger=Ledger(root);config=ledger.config(campaign)
    parent=local_path(root,f'campaigns/{campaign}/upskill/{parent_batch}')
    request_raw=(parent/'request.json').read_bytes();report_raw=(parent/'result.json').read_bytes()
    request=json.loads(request_raw);report=json.loads(report_raw)
    if request['config_sha256']!=digest(config) or report['case_ids']!=request['case_ids']:
        raise ValueError('interrupted parent cohort/config differs')
    if report['status']!='blocked' or report.get('batch_evidence',{}).get('acquisition_failed',0)>len(request['case_ids'])*.25:
        raise ValueError('only interrupted, scientifically unfailed cohorts can drain')
    if not report.get('deferred') or any(v not in {'URLError','TimeoutError','ConnectionResetError','Stopped'} for v in report['deferred'].values()):
        raise ValueError('parent requires a diagnosed transport interruption')
    with ledger.db() as db:
        unresolved=list(db.execute("SELECT r.case_id,r.state,r.acceptance,i.request_id isolated FROM requests r LEFT JOIN unknown_isolations i ON i.request_id=r.id WHERE r.campaign=? AND r.state IN ('wire_started','provider_pending','unknown_provider_outcome')",(campaign,)))
    if (not any(r['isolated'] for r in unresolved) or any(
            (not r['isolated'] and not (r['state'] in {'provider_pending','wire_started'} and r['acceptance']))
            or r['case_id'] not in request['case_ids'] for r in unresolved)):
        raise ValueError('only permanently isolated unknown members of this exact interrupted cohort may be skipped')
    out=local_path(root,f'campaigns/{campaign}/drains/{version}')
    out.mkdir(parents=True,exist_ok=True)
    binding=dict(parent_batch=parent_batch,case_ids=request['case_ids'],config_sha256=digest(config),
        parent_request_sha256=hashlib.sha256(request_raw).hexdigest(),parent_report_sha256=hashlib.sha256(report_raw).hexdigest(),
        max_cases=max_cases,stage_release_permitted=False)
    with FileLock(str(out/'lock'),timeout=0):
        frozen=out/'request.json'
        if frozen.exists() and frozen.read_bytes()!=canonical(binding):raise ValueError('drain version is immutable')
        if not frozen.exists():frozen.write_bytes(canonical(binding))
        result_file=out/'result.json'
        if result_file.exists():return json.loads(result_file.read_text())
        result=Runner(root,campaign,specialist).run(max_cases=max_cases,case_ids=request['case_ids'],isolated_continuation=True)
        if (parent/'request.json').read_bytes()!=request_raw or (parent/'result.json').read_bytes()!=report_raw:
            raise ValueError('original parent artifacts changed')
        evidence=cohort_evidence(ledger,config,request['case_ids'])
        result.update(parent_batch=parent_batch,stage_release_permitted=False,original_cohort_evidence=evidence,
                      unknowns_preserved=True,parent_artifacts_unchanged=True)
        if any(r['state']=='provider_pending' or (r['state']=='wire_started' and r.get('provider_response_id'))
                for r in result['status']['requests']):
            result['waiting_for_response']=True
            temporary=out/'pending.tmp';temporary.write_bytes(canonical(result));temporary.replace(out/'pending.json')
            return result
        result_file.write_bytes(canonical(result))
        return result
