"""Operator-issued provider grants and one-use durable transmission permits."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pydantic import Field, StrictInt, model_validator
from typing import Literal
from .. import domain as D,storage as S
from .errors import InvalidInput


class ProviderGrant(D.Strict):
    schema_version: Literal['2.0'] = '2.0'
    id: str = Field(min_length=1,max_length=128)
    targets: list[str] = Field(min_length=1)
    models: list[str] = Field(min_length=1)
    endpoints: list[str] = Field(default_factory=lambda:['https://api.meta.ai/v1'])
    limit_kind: Literal['dispatch_units','usd'] = 'dispatch_units'
    max_dispatches: StrictInt = Field(ge=1,le=1000)
    dispatches_reserved: StrictInt = Field(default=0,ge=0)
    ceiling_microusd: StrictInt | None = Field(default=None,ge=0)
    quote_microusd: StrictInt | None = Field(default=None,ge=1)
    reserved_microusd: StrictInt = Field(default=0,ge=0)
    pricing_reference: str | None = None
    output_rights: Literal['unknown','original'] = 'unknown'
    active: bool = True

    @model_validator(mode='after')
    def coherent(self):
        if self.limit_kind=='usd' and (self.ceiling_microusd is None or self.quote_microusd is None or not self.pricing_reference):
            raise ValueError('USD grants need a ceiling and an operator-reviewed maximum quote/reference')
        if self.limit_kind=='dispatch_units' and (self.ceiling_microusd is not None or self.quote_microusd is not None):
            raise ValueError('dispatch-unit grants do not assert monetary limits')
        return self


def issue(project_dir, proposal, operator_credential):
    from .sessions import require_operator
    require_operator(operator_credential)
    try:grant=ProviderGrant.model_validate(proposal)
    except ValueError as exc:raise InvalidInput(str(exc)) from exc
    if grant.dispatches_reserved or grant.reserved_microusd:
        raise InvalidInput('new grants cannot supply accounting counters')
    con=S.connect(project_dir)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            S.stage_identical(con,grant,('dispatches_reserved','reserved_microusd'))
            grant=ProviderGrant.model_validate(S.get(con,'provider_grants',grant.id)[0])
    finally:con.close()
    return grant.model_dump()


def reserve_in(con, job, simulation_mode):
    grant_id=job.provider_settings.get('grant_id')
    if not grant_id:
        if simulation_mode is False:
            raise InvalidInput('live dispatch requires an operator-issued provider grant')
        return 0
    try:data,version=S.get(con,'provider_grants',grant_id)
    except KeyError as exc:raise InvalidInput('provider grant not found') from exc
    grant=ProviderGrant.model_validate(data)
    if (not grant.active or not set(job.targets)<=set(grant.targets)
            or job.provider_settings.get('model') not in grant.models
            or job.provider_settings.get('base_url') not in grant.endpoints):
        raise InvalidInput('provider grant does not authorize this target/model')
    if grant.dispatches_reserved>=grant.max_dispatches:
        raise InvalidInput('provider grant dispatch ceiling exhausted')
    amount=grant.quote_microusd or 0
    job_cap=job.provider_settings.get('max_spend_usd')
    if job_cap is not None:
        try:job_ceiling=Decimal(str(job_cap))*1_000_000
        except InvalidOperation as exc:raise InvalidInput('invalid job money ceiling') from exc
        if grant.limit_kind!='usd' or not job_ceiling.is_finite() or job_ceiling<=0 or job.reserved_microusd+amount>job_ceiling:
            raise InvalidInput('job money ceiling cannot fund dispatch')

    if grant.limit_kind=='usd' and grant.reserved_microusd+amount>grant.ceiling_microusd:
        raise InvalidInput('provider grant money ceiling exhausted')
    import os
    cap=os.environ.get('FRAMEBOUND_SPEND_CEILING')
    if cap:
        if cap.startswith('calls-'):
            try:maximum=int(cap[6:])
            except ValueError as exc:raise InvalidInput('invalid call ceiling') from exc
            used=sum(json.loads(r['data']).get('dispatch_count',0) for r in con.execute('SELECT data FROM jobs'))
            if maximum<=used:raise InvalidInput('project call ceiling exhausted')
        else:
            try:ceiling=Decimal(cap.removeprefix('usd-'))*1_000_000
            except InvalidOperation as exc:raise InvalidInput('invalid USD ceiling') from exc
            if not ceiling.is_finite() or ceiling<=0:raise InvalidInput('zero/invalid USD ceiling')
            if grant.limit_kind!='usd':raise InvalidInput('unpriced grant cannot assert a USD ceiling')
            used=sum(json.loads(r['data']).get('reserved_microusd',0) for r in con.execute('SELECT data FROM jobs'))
            if used+amount>ceiling:raise InvalidInput('project money ceiling exhausted')
    grant.dispatches_reserved+=1;grant.reserved_microusd+=amount
    S.stage_update(con,'provider_grants',grant,version)
    job.reserved_microusd+=amount
    job.reserved_cost=f'reserved:{grant.limit_kind}:{amount if grant.limit_kind=="usd" else 1}'
    return amount


@dataclass
class DispatchPermit:
    project_dir: str
    job_id: str
    token: str
    request_sha256: str | None
    endpoint: str
    simulation_only: bool
    wire_version: int | None = None

    def consume(self,payload,simulated):
        from .jobs import _lease_live
        if not simulated and self.simulation_only:
            raise InvalidInput('simulation permit cannot authorize live I/O')
        if hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()!=self.request_sha256:
            raise InvalidInput('transmission differs from frozen request')
        con=S.connect(self.project_dir)
        try:
            with S.atomic(con):
                con.execute('BEGIN IMMEDIATE')
                data,version=S.get(con,'jobs',self.job_id);job=D.Job.model_validate(data)
                if (not job.dispatch_inflight or job.wire_started or job.offline or job.cancel_requested
                        or job.status!=D.JobStatus.RUNNING or not _lease_live(job)
                        or job.dispatch_token_sha256!=hashlib.sha256(self.token.encode()).hexdigest()):
                    raise InvalidInput('dispatch permit is stale, spent, offline or cancelled')
                if job.provider_settings.get('grant_id'):
                    grant=ProviderGrant.model_validate(S.get(con,'provider_grants',job.provider_settings['grant_id'])[0])
                    if not grant.active:raise InvalidInput('provider grant was revoked before transmission')
                from .specialist_repair import validate_job_in
                validate_job_in(con,self.project_dir,job,sending=True,reservation_included=True)
                job.wire_started=True
                self.wire_version=S.stage_update(con,'jobs',job,version)
        finally:con.close()
