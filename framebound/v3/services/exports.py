"""Manual export selection/preview over the established portable snapshot publisher."""
from pathlib import Path

from pydantic import Field, StrictBool

from ...v2.domain import Strict
from ...v2.exports import build_snapshot,validate_snapshot
from ...v2.exports.agent_snapshot import preview
from ...v2.services.errors import InvalidInput
from . import loop


class ExportSelection(Strict):
    name: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')
    run_ids: list[str] = Field(min_length=1, max_length=1000)
    policy_id: str = Field(default='agent-training-v1',pattern=r'^agent-training-v1$')
    include_automatically_verified: StrictBool = False
    include_procedural_positives: StrictBool = False
    rights_allow: list[str] = Field(default_factory=lambda:['original'],max_length=100)
    destination: str | None = None
    split: dict[str,list[str]] = Field(default_factory=lambda:{'train':[],'dev':[],'test':[]})
    split_policy: str = Field(default='exclude',pattern=r'^(strict|exclude)$')


def _selection(project,selection):
    request=ExportSelection.model_validate(selection)
    con=loop.connect(project)
    try:
        con.execute('BEGIN')
        rids=[]
        for rid in dict.fromkeys(request.run_ids):
            run=loop.get_in(con,'agent_runs',rid)
            if not run['current_revision_id']:raise InvalidInput(f'run {rid} has no submissions to export')
            rids.append(run['current_revision_id'])
        policy=dict(agent_export_policy=request.policy_id,include_automatically_verified=request.include_automatically_verified,
                    include_procedural_positives=request.include_procedural_positives,rights_allow=request.rights_allow,
                    split=request.split,split_policy=request.split_policy)
        destination=request.destination or str(Path(project)/'exports'/request.name)
        return request,rids,policy,destination
    finally:con.close()


def plan(project,selection):
    request,rids,policy,destination=_selection(project,selection)
    return dict(preview(project,rids,policy),destination=destination,snapshot_name=request.name)


def build(project,selection):
    request,rids,policy,destination=_selection(project,selection)
    manifest=build_snapshot(project,request.name,rids,destination,policy)
    report=validate_snapshot(destination)
    return dict(manifest=manifest,validation=report,destination=destination)
