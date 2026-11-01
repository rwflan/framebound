"""Account evidence and measured utility gates for paid feature-only compute."""
from datetime import datetime, timezone, timedelta
import json
import math

from pydantic import Field, StrictInt, model_validator

from .contracts import Strict, digest, local_path
from .learning import recipe


class CreditEvidence(Strict):
    verified_at: datetime
    expires_at: datetime
    source: str = Field(min_length=1,max_length=2000)
    restrictions: str = Field(min_length=1,max_length=2000)
    available_microdollars: StrictInt = Field(ge=0)
    workspace_remaining_microdollars: StrictInt = Field(ge=0)
    net_spend_remaining_microdollars: StrictInt = Field(ge=0)
    pricing_source: str = Field(min_length=1,max_length=2000)
    l4_microdollars_per_second: float = Field(gt=0)
    l40s_microdollars_per_second: float = Field(gt=0)
    cpu_microdollars_per_core_second: float = Field(gt=0)
    ram_microdollars_per_gib_second: float = Field(gt=0)

    @model_validator(mode='after')
    def current(self):
        now=datetime.now(timezone.utc)
        if self.verified_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError('credit evidence needs explicit timezone offsets')
        if not now-timedelta(hours=24)<=self.verified_at<=now:
            raise ValueError('credit/account evidence must be verified within 24 hours')
        if self.expires_at<=now:raise ValueError('credit has expired')
        return self


def admit(ledger,campaign,raw,job,study):
    from .transfer import inspect_payload
    from .study import verify_baseline
    if not study:raise ValueError('local profile, account evidence and frozen hypothesis are required')
    shard=inspect_payload(raw)
    root=ledger.root
    if job.seconds>600:raise ValueError('jobs over ten minutes require durable checkpoint/resume transport')
    if job.recipe_sha256!=digest(recipe(shard.extractor)):raise ValueError('unpinned feature/training recipe')
    profile=json.loads(local_path(root,study['local_profile_file']).read_text())
    if profile.get('schema_version')!='local-workload-profile-1.0' or profile['campaign']!=campaign:
        raise ValueError('actual local workload profile required')
    if (profile['data_sha256']!=digest(shard) or profile['recipe_sha256']!=job.recipe_sha256
            or profile['categories']!=job.categories or profile['steps']!=200):
        raise ValueError('local profile must measure this exact training workload')
    if not math.isfinite(profile['wall_seconds']) or profile['wall_seconds']<=0:
        raise ValueError('positive measured local wall time required')
    baseline=verify_baseline(root,campaign,study['baseline_file'])
    if baseline['data_sha256']!=digest(shard) or baseline['categories']!=job.categories:
        raise ValueError('baseline differs from proposed compute experiment')
    credit=CreditEvidence.model_validate_json(local_path(root,study['credit_file']).read_bytes())
    rates=(credit.l4_microdollars_per_second,credit.l40s_microdollars_per_second,
           credit.cpu_microdollars_per_core_second,credit.ram_microdollars_per_gib_second)
    if rates!=(222.,542.,13.1,2.22):
        raise ValueError('verified compute prices differ from this frozen quote implementation; update the versioned quote before dispatch')
    with ledger.db() as db:
        pending=db.execute("SELECT COALESCE(SUM(reserved),0) FROM requests WHERE subsystem='modal' AND incurred IS NULL").fetchone()[0]
        since_verification=db.execute("""SELECT COALESCE(SUM(incurred),0) FROM requests WHERE subsystem='modal' AND incurred IS NOT NULL
            AND EXISTS(SELECT 1 FROM events WHERE request_id=requests.id AND kind='wire_started' AND at>=?)""",(credit.verified_at.timestamp(),)).fetchone()[0]
    if job.quote()+pending+since_verification>min(credit.available_microdollars,credit.workspace_remaining_microdollars,credit.net_spend_remaining_microdollars):
        raise ValueError('job and outstanding reservations exceed verified account availability')
    hypothesis=json.loads(local_path(root,study['hypothesis_file']).read_text())
    if set(hypothesis)!={'question','success_measure','stop_condition'} or not all(isinstance(v,str) and v.strip() for v in hypothesis.values()):
        raise ValueError('freeze a concrete hypothesis, success measure and stop condition')
    if job.purpose!='profile':
        if not baseline['informative']:raise ValueError('training requires an informative local baseline')
        row=ledger.request(study['remote_profile_request_id'])
        from .remote import Job,verify_result
        original=Job.model_validate(json.loads(row['request'])['payload']['job'])
        if row['campaign']!=campaign or original.purpose!='profile':raise ValueError('matching remote workload profile required')
        comparable=original.model_dump(exclude={'purpose'})==job.model_dump(exclude={'purpose'})
        if not comparable:raise ValueError('remote profile differs from proposed workload or resources')
        received,_=ledger.artifact(row['id']);wrapped=json.loads(received)
        remote=verify_result(wrapped,original)
        elapsed=wrapped.get('end_to_end_seconds')
        if remote.get('status')!='profile_only' or remote.get('steps')!=200 or remote.get('cases')!=len(shard.rows) or elapsed is None or not math.isfinite(elapsed) or elapsed<=0:
            raise ValueError('remote profile must include observed end-to-end wall time')
        if profile['wall_seconds']/elapsed<1.25:
            raise ValueError('Modal did not improve end-to-end runtime by at least 25%; retain local compute')
    if job.purpose=='reproduce':
        training=ledger.request(study['training_request_id'])
        training_job=Job.model_validate(json.loads(training['request'])['payload']['job'])
        if training['campaign']!=campaign or training_job.purpose!='train' or training_job.model_dump(exclude={'purpose'})!=job.model_dump(exclude={'purpose'}):
            raise ValueError('reproduction requires a matching received training job')
        ledger.artifact(training['id'])
    return dict(local_profile_sha256=digest(profile),baseline_sha256=digest(baseline),
                credit_evidence_sha256=digest(credit),hypothesis_sha256=digest(hypothesis),
                account_evidence_scope='operator-provided account evidence, not a provider account API attestation')
