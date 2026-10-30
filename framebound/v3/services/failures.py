"""Durable parent-reported failures; reports authorize no provider execution."""
import json

from pydantic import Field,StrictBool

from ...v2 import domain as D,storage as S
from ...v2.services.errors import InvalidInput
from ..evaluate import digest
from . import loop,tasks,interventions as I


class FailureReport(D.Strict):
    id: str = Field(min_length=1,max_length=64)
    kind: str = Field(pattern='^(provider_failure|tool_error|missing_input)$')
    reason: str = Field(min_length=1,max_length=2000)
    outcome_known: StrictBool
    provider: str | None = Field(default=None,max_length=100)
    external_request_id: str | None = Field(default=None,max_length=200)


def record(project,run_id,payload):
    request=FailureReport.model_validate(payload);con=loop.connect(project)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            run=loop.get_in(con,'agent_runs',run_id);event_id='external-failure:'+digest([run_id,request.id])
            existing=con.execute('SELECT data FROM agent_run_events WHERE id=?',(event_id,)).fetchone()
            if existing:
                event=json.loads(existing['data'])
                if event['run_id']!=run_id or event['report']!=request.model_dump(mode='json'):raise S.ConflictError('failure ID already binds another report')
                return dict(event=event,feedback=loop.get_in(con,'agent_feedback',event['feedback_id']))
            if run['lifecycle'] in {'completed','cancelled','blocked'}:raise InvalidInput('stopped or completed runs do not accept new execution attempts')
            run['external_failures']=run.get('external_failures',0)+1
            if request.kind=='provider_failure':run['provider_failures']=run.get('provider_failures',0)+1
            if request.kind=='provider_failure' and not request.outcome_known:
                run['lifecycle']='blocked';run['blocker_kind']='provider_outcome_unknown'
                run['stop_reason']='Unknown parent-reported provider outcome; do not blindly redispatch. Resolve the provider outcome outside this stopped run or cancel it.'
            elif (run['external_failures']>=run['limits'].get('max_external_failures',8)
                  or run.get('provider_failures',0)>=run['limits'].get('max_provider_failures',3)):
                run['lifecycle']='blocked';run['stop_reason']='Persistent parent-reported execution failure limit reached.'
            else:
                run['lifecycle']='awaiting_agent' if request.kind=='provider_failure' else 'awaiting_input'
                run['stop_reason']=request.reason
            feedback_id=f'handoff:{event_id}'
            event=dict(schema_version='3.0',id=event_id,run_id=run_id,project_id=run['project_id'],animation_id=run['animation_id'],
                task_id=run['task_id'],revision_id=run['current_revision_id'],source='external_agent',event=request.kind,
                note=request.reason,report=request.model_dump(mode='json'),feedback_id=feedback_id,
                created_at=D.utcnow(),ordinal=run['version']+1)
            if run['current_revision_id']:
                # Build the final immutable bundle once, with its failure provenance attached.
                revision=loop.get_in(con,'agent_clip_revisions',run['current_revision_id'])
                evaluation=loop.get_in(con,'agent_evaluations',f"evaluation:{revision['id']}")
                task=tasks._get(con,revision['task_id'])
                feedback=loop._feedback(run,task,revision,evaluation,[])
                I.augment_in(con,feedback,run)
            else:
                task=tasks._get(con,run['task_id'])
                feedback=dict(schema_version='3.0',bundle_version=2,id=feedback_id,project_id=run['project_id'],animation_id=run['animation_id'],
                    run_id=run_id,task_id=task.id,spec_sha256=task.spec_sha256,baseline_revision_id=None,evaluation_id=None,evidence_digest=None,
                    disposition='blocked' if run['lifecycle']=='blocked' else 'awaiting_input' if run['lifecycle']=='awaiting_input' else 'continue',
                    reason=run['stop_reason'],technical_status='unevaluated',coverage='unsupported',creative_status='unreviewed',
                    best_revision_id=None,current_revision_id=None,targets=[],correction_groups=[],preserve=task.spec.preserve,
                    allowed_changes=task.spec.allowed_changes,repair_scope=task.spec.repair_scope,timing=task.spec.timing.model_dump(),
                    remaining_submissions=max(0,run['limits']['max_submissions']-len(run['submission_ids'])),
                    verification='No pixels have been submitted; recover the reported failure, then generate and evaluate against the frozen task.',
                    continuation=dict(operation='agent_run_get',arguments=dict(run_id=run_id),submission_allowed=False) if run['lifecycle']=='blocked' else
                        dict(operation='task_compile_inputs',arguments=dict(task_id=task.id),submission=dict(operation='agent_run_submit',arguments=dict(run_id=run_id,
                            revision_id='<new immutable ID>',frame_asset_ids='<complete ordered imported asset IDs>',feedback_id=feedback_id))))
            feedback['id']=feedback_id;feedback['external_failure_event_id']=event_id
            feedback['external_failure']=dict(request.model_dump(mode='json'),observation_source='parent_reported; not independently provider-verified')
            if feedback['continuation']['operation']=='agent_run_submit':feedback['continuation']['arguments']['feedback_id']=feedback_id
            if run['task_id']!=feedback['task_id']:feedback['next_task_id']=run['task_id'];feedback['next_spec_sha256']=run['spec_sha256']
            event['evidence_task_id']=feedback['task_id']
            loop.insert(con,'agent_run_events',event)
            loop.insert(con,'agent_feedback',feedback);run['feedback_id']=feedback_id
            loop._update(con,run)
        return dict(event=event,feedback=feedback)
    finally:con.close()
