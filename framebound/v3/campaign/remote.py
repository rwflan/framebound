"""Pure-job protocol, bounded quotes and locally verified result artifacts."""
from __future__ import annotations

import hashlib
import time
from typing import Literal

from pydantic import Field, StrictInt

from .contracts import Strict, canonical, digest
from .transfer import inspect_payload, transfer


class Job(Strict):
    schema_version: Literal['pure-feature-job-1.0'] = 'pure-feature-job-1.0'
    payload_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    recipe_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    image_digest: str = Field(pattern=r'^sha256:[0-9a-f]{64}$')
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


def submit(ledger, campaign, case_id, raw, job: Job, transport):
    inspect_payload(raw)
    if hashlib.sha256(raw).hexdigest()!=job.payload_sha256: raise ValueError('payload differs from quoted job')
    row=ledger.reserve(campaign,case_id,'train',dict(job=job.model_dump(mode='json')),quote=job.quote(),subsystem='modal')
    permit=ledger.claim(row['id']);ledger.start_wire(row['id'],permit)
    try:
        result=transfer(raw,lambda inspected:transport(inspected,job.model_dump(mode='json')))
        verify_result(result,job)
        # Billing can lag. Keep the entire upper bound booked pending actual usage
        # reconciliation instead of interpreting useful compute time as total cost.
        receipt=ledger.receive(row['id'],canonical(result),incurred=job.quote(),provider_receipt=dict(job_sha256=digest(job),
            cost_basis='conservative full upper bound; reconcile against actual workspace billing'),successful_images=0)
        return dict(result=result,receipt=receipt)
    except BaseException:
        ledger.unknown(row['id'],'remote pure job/result unresolved; reservation retained')
        raise
