"""Explicit operator reconciliation. Unknown sends never retry themselves."""
import base64
from datetime import datetime,timedelta,timezone
import hashlib
import json
import secrets
from typing import Literal
from pydantic import Field,StrictInt
from .. import domain as D,storage as S
from .errors import InvalidInput
from .provider_grants import ProviderGrant


class ProviderReceipt(D.Strict):
    id: str = Field(min_length=1,max_length=128)
    expected_version: StrictInt = Field(ge=1)
    request_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    outcome: Literal['not_accepted','response','abandoned']
    receipt_reference: str = Field(min_length=1,max_length=500)
    evidence_note: str = Field(min_length=8,max_length=2000)
    provider_response: dict | None = None


def release_unsent_in(con,job):
    """Only a durable not-yet-consumed permit can release call and money units."""
    if not job.dispatch_inflight or job.wire_started:return False
    if job.dispatch_count<1:raise InvalidInput('incoherent pre-send dispatch accounting')
    gid=job.provider_settings.get('grant_id')
    if gid:
        data,version=S.get(con,'provider_grants',gid);grant=ProviderGrant.model_validate(data)
        amount=grant.quote_microusd or 0
        if grant.dispatches_reserved<1 or grant.reserved_microusd<amount or job.reserved_microusd<amount:
            raise InvalidInput('incoherent pre-send provider grant accounting')
        grant.dispatches_reserved-=1;grant.reserved_microusd-=amount;job.reserved_microusd-=amount
        S.stage_update(con,'provider_grants',grant,version)
    if job.dispatch_run_id:
        data,version=S.get(con,'runs',job.dispatch_run_id);run=D.Run.model_validate(data)
        if run.attempts_used<1:raise InvalidInput('incoherent pre-send run accounting')
        run.attempts_used-=1;S.stage_update(con,'runs',run,version)
    job.dispatch_count-=1;job.dispatch_inflight=False;job.dispatch_token_sha256=None
    job.settlement='known_not_sent';job.reserved_cost='released:verified pre-wire cancellation'
    return True


def _refund_confirmed_no_charge(con,job):
    gid=job.provider_settings.get('grant_id')
    if gid:
        data,version=S.get(con,'provider_grants',gid);grant=ProviderGrant.model_validate(data)
        amount=grant.quote_microusd or 0
        if grant.reserved_microusd<amount or job.reserved_microusd<amount:raise InvalidInput('incoherent reservation settlement')
        grant.reserved_microusd-=amount;job.reserved_microusd-=amount
        S.stage_update(con,'provider_grants',grant,version)
    # Dispatch units measure actual transport entries, including refused sends.
    # They are never refunded after wire_started.
    job.settlement='operator_confirmed_not_accepted_no_charge'


def reconcile(project,job_id,proposal,operator_credential):
    from .sessions import require_operator
    require_operator(operator_credential)
    receipt=ProviderReceipt.model_validate(proposal)
    identity=hashlib.sha256(receipt.model_dump_json().encode()).hexdigest()
    con=S.connect(project)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            prior=con.execute('SELECT data FROM provider_reconciliations WHERE id=?',(receipt.id,)).fetchone()
            if prior:
                previous=D.ProviderReconciliation.model_validate_json(prior['data'])
                if previous.input_sha256!=identity or previous.job_id!=job_id:raise S.ConflictError('receipt id bound to another payload')
                return previous.result
            data,version=S.get(con,'jobs',job_id);job=D.Job.model_validate(data)
            if version!=receipt.expected_version:raise S.StaleRevisionError('operator receipt version is stale')
            if job.frozen_request_sha256!=receipt.request_sha256:raise InvalidInput('receipt belongs to a different frozen request')
            if not job.reconciliation_required or job.status!=D.JobStatus.NEEDS_ATTENTION:
                raise InvalidInput('job is not awaiting explicit reconciliation')
            if receipt.outcome!='response' and receipt.provider_response is not None:
                raise InvalidInput('response bytes supplied for a different receipt outcome')
            artifact=None
            if receipt.outcome=='response':
                if not job.wire_started or not job.dispatch_inflight or not receipt.provider_response:
                    raise InvalidInput('completed response needs an actual unresolved dispatch and provider bytes')
                if job.origin not in ('live','simulated-transport'):raise InvalidInput('unresolved execution origin cannot become live evidence')
                body=receipt.provider_response
                from ..providers import ledger,image,sam
                payload={'receipt_reference':receipt.receipt_reference,'response_id':body.get('id'),'provider_status':body.get('status')}
                if job.provider=='image':
                    parsed=image.parse_response(body);raw=parsed['images'][0]['bytes'];shape=image._materialize(raw)
                    payload['output_blob']=S.store_blob(project,raw)
                else:
                    text=body.get('output_text') or ''.join(part.get('text','') for item in body.get('output',[]) if isinstance(item,dict) for part in item.get('content',[]) if isinstance(part,dict) and part.get('type') in ('output_text','text'))
                    parsed=sam.parse_output_text(text,source_width=job.provider_settings['source_width'],source_height=job.provider_settings['source_height'],status=body.get('status'))
                    payload['output_text']=text
                artifact=ledger.record_artifact(project,'operator_reconciled_response',payload,provider=job.provider,model=job.provider_settings.get('model',''))
                token=secrets.token_hex(24);worker='operator-reconciliation'
                job.status=D.JobStatus.RUNNING;job.lease_holder=worker
                job.lease_expires=(datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat()
                job.fencing_token_sha256=hashlib.sha256(token.encode()).hexdigest();job.response_artifact=artifact
                job.settlement='response_reconciled_quote_held'
                version=S.stage_update(con,'jobs',job,version)
                from . import jobs as J
                if job.provider=='image':
                    result=J.job_complete_success(project,job_id,worker_id=worker,expected_version=version,image_bytes=raw,
                        mime=shape['mime'],provider_response_id=parsed['response_id'],usage=parsed.get('usage'),
                        output_asset_id='receipt-output-'+hashlib.sha256(receipt.id.encode()).hexdigest()[:24],fencing_token=token,
                        origin=job.origin,connection=con,count_attempt=False)
                else:
                    parsed.update(response_id=body.get('id'),response_artifact=artifact,origin=job.origin)
                    result=J.job_complete_segmentation(project,job_id,worker_id=worker,expected_version=version,result=parsed,
                        fencing_token=token,connection=con,count_attempt=False)
            else:
                if receipt.outcome=='not_accepted':
                    if job.wire_started:_refund_confirmed_no_charge(con,job)
                    else:release_unsent_in(con,job)
                    job.status=D.JobStatus.QUEUED;job.error=None
                else:
                    job.status=D.JobStatus.FAILED;job.error='operator abandoned unresolved outcome; reservations retained'
                    job.settlement='abandoned_quote_held'
                job.dispatch_inflight=False;job.dispatch_token_sha256=None;job.wire_started=False
                job.reconciliation_required=False;job.lease_holder=None;job.lease_expires=None;job.fencing_token_sha256=''
                version=S.stage_update(con,'jobs',job,version)
                result={'job_id':job.id,'status':job.status.value,'version':version,'settlement':job.settlement}
            record=D.ProviderReconciliation(id=receipt.id,job_id=job_id,input_sha256=identity,request_sha256=receipt.request_sha256,
                outcome=receipt.outcome,receipt_reference=receipt.receipt_reference,evidence_note=receipt.evidence_note,
                artifact_sha256=artifact,result=result)
            S.stage(con,record)
            return result
    finally:con.close()
