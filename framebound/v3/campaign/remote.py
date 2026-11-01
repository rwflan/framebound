"""Pure-job protocol, bounded quotes and locally verified result artifacts."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Literal

from pydantic import Field, StrictInt

from .contracts import Strict, canonical, digest
from .assessment import Category
from .transfer import inspect_payload, transfer


class Job(Strict):
    schema_version: Literal['pure-feature-job-1.0'] = 'pure-feature-job-1.0'
    payload_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    recipe_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    image_digest: str = Field(pattern=r'^sha256:[0-9a-f]{64}$')
    purpose: Literal['profile','train','reproduce'] = 'train'
    categories: list[Category] = Field(default_factory=lambda:['temporal','artifacts'],min_length=1,max_length=9)
    gpu: Literal['L4','L40S'] = 'L4'
    seconds: StrictInt = Field(default=600,ge=1,le=3600)
    startup_seconds: StrictInt = Field(default=120,ge=0,le=600)
    replay_seconds: StrictInt = Field(default=600,ge=0,le=3600)
    cpu_physical: StrictInt = Field(default=2,ge=1,le=4)
    ram_gib: StrictInt = Field(default=16,ge=1,le=32)
    transfer_microdollars: StrictInt = Field(default=100000,ge=0)

    def quote(self):
        # Public planning rates rechecked at execution time; ceil upper bounds.
        import math
        seconds=self.seconds+self.startup_seconds+self.replay_seconds
        gpu=222 if self.gpu=='L4' else 542
        return math.ceil(seconds*(gpu+13.1*self.cpu_physical+2.22*self.ram_gib)+self.transfer_microdollars)


def execute_pure(raw: bytes, job: Job, executor):
    shard=inspect_payload(raw)
    if hashlib.sha256(raw).hexdigest()!=job.payload_sha256: raise ValueError('feature payload hash mismatch')
    started=time.monotonic()
    # Executor must implement checkpoints <=600s and resume keyed by this hash.
    result=executor(shard,job,digest(job))
    elapsed=time.monotonic()-started
    artifact=canonical(result)
    return dict(job_sha256=digest(job),payload_sha256=job.payload_sha256,result_sha256=hashlib.sha256(artifact).hexdigest(),
        result=result,elapsed_seconds=elapsed,resources=dict(gpu=job.gpu,cpu_physical=job.cpu_physical,ram_gib=job.ram_gib),
        cleanup='ephemeral input and output memory; no remote volume or persistent corpus')


def verify_result(result, job: Job):
    if result['job_sha256']!=digest(job) or result['payload_sha256']!=job.payload_sha256 or result['result_sha256']!=hashlib.sha256(canonical(result['result'])).hexdigest():
        raise ValueError('returned job/artifact hash mismatch')
    return result['result']


def submit(ledger, campaign, case_id, raw, job: Job, transport, *, study=None):
    shard=inspect_payload(raw)
    if any(row.split=='test' for row in shard.rows):raise ValueError('held-out final-test features cannot enter training jobs')
    if hashlib.sha256(raw).hexdigest()!=job.payload_sha256: raise ValueError('payload differs from quoted job')
    if job.purpose!='profile':
        if shard.schema_version!='feature-only-2.0':raise ValueError('paid training requires scoped v2 supervision; re-extract from the audited dataset')
        from .learning import eligibility
        from .assessment import CATEGORIES
        if not eligibility(shard,job.categories)['eligible']:
            raise ValueError('label-count/family gate must pass before paid training')
    elif len([r for r in shard.rows if r.split=='train'])<20:
        raise ValueError('profile requires 20 representative allowlisted cases')
    attempt={'profile':0,'train':1,'reproduce':2}[job.purpose]
    with ledger.db() as db:
        previous=db.execute("SELECT * FROM requests WHERE campaign=? AND case_id=? AND operation='train' AND json_extract(request,'$.attempt')=?",
                            (campaign,case_id,attempt)).fetchone()
    if previous:
        previous=dict(previous)
        if json.loads(previous['request'])['payload']['job']!=job.model_dump(mode='json'):
            raise ValueError('existing compute attempt has a different frozen job')
        if previous['state']=='received':
            result,receipt=ledger.artifact(previous['id'])
            return dict(result=json.loads(result),receipt=receipt)
        if previous['state']!='reserved':
            from .ledger import Stopped
            raise Stopped('compute outcome unresolved; reconcile the existing receipt before any new send')
    from .compute_gate import admit
    evidence=admit(ledger,campaign,raw,job,study)
    row=ledger.reserve(campaign,case_id,'train',dict(job=job.model_dump(mode='json'),study=evidence),quote=job.quote(),subsystem='modal',attempt=attempt)
    if row['state']=='received':
        result,receipt=ledger.artifact(row['id'])
        return dict(result=json.loads(result),receipt=receipt)
    permit=ledger.claim(row['id']);ledger.start_wire(row['id'],permit)
    try:
        started=time.monotonic()
        result=transfer(raw,lambda inspected:transport(inspected,job.model_dump(mode='json')))
        verify_result(result,job)
        result['end_to_end_seconds']=time.monotonic()-started
        # Billing can lag. Keep the entire upper bound booked pending actual usage
        # reconciliation instead of interpreting useful compute time as total cost.
        receipt=ledger.receive(row['id'],canonical(result),incurred=job.quote(),provider_receipt=dict(job_sha256=digest(job),
            cost_basis='conservative full upper bound; reconcile against actual workspace billing'),successful_images=0)
        output=dict(result=result,receipt=receipt)
        if job.purpose!='profile' and result['result'].get('temporal',{}).get('checkpoint'):
            from .study import save
            output['checkpoint']=save(ledger.root,campaign,'checkpoint',result['result']['temporal']['checkpoint'])
        return output
    except BaseException:
        ledger.unknown(row['id'],'remote pure job/result unresolved; reservation retained')
        raise
