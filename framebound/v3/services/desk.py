"""Run-based visual documentation independent of reviewed-guide packets."""
import json

from ...v2 import storage as S
from . import loop, tasks


def snapshot(project):
    con=loop.connect(project)
    try:
        con.execute('BEGIN')
        runs=[json.loads(r['data']) for r in con.execute('SELECT data FROM agent_runs')]
        events=[json.loads(r['data']) for r in con.execute('SELECT data FROM agent_run_events')]
        marks=[json.loads(r['data']) for r in con.execute('SELECT data FROM agent_interventions')]
        projects=[json.loads(r['data']) for r in con.execute('SELECT data FROM projects')]
        specs={r['id']:json.loads(r['data']) for r in con.execute('SELECT id,data FROM agent_task_specs')}
        for run in runs:
            run['task']=specs[run['task_id']]
            run['interventions']=[m for m in marks if m['run_id']==run['id']]
            open_marks=[m for m in run['interventions'] if m['correction']['status'] not in {'resolved','cancelled'}]
            run['needs_intervention']=bool(open_marks) or run['lifecycle'] in {'blocked','awaiting_input','awaiting_decision'}
        return dict(schema_version='3.0',runs=runs,events=sorted(events,key=lambda e:(e['created_at'],e['ordinal'],e['id'])),projects=projects)
    finally:con.close()


def revision(project, revision_id):
    con=loop.connect(project)
    try:
        con.execute('BEGIN')
        revision=loop.get_in(con,'agent_clip_revisions',revision_id)
        evaluation=loop.get_in(con,'agent_evaluations',f'evaluation:{revision_id}')
        run=loop.get_in(con,'agent_runs',revision['run_id'])
        task=tasks._get(con,revision['task_id']).model_dump(mode='json',exclude_unset=True)
        current_feedback_id=run.get('feedback_id',f"feedback:{run['current_revision_id']}")
        feedback_id=current_feedback_id if revision_id==run['current_revision_id'] else f'feedback:{revision_id}'
        feedback=loop.get_in(con,'agent_feedback',feedback_id)
        frames=[]
        for fid in revision['frame_instance_ids']:
            data,_=S.get(con,'frame_instances',fid)
            frames.append(dict(data,asset_url=f"/api/asset/{data['asset_id']}"))
        return dict(revision=revision,evaluation=evaluation,task=task,feedback=feedback,frames=frames,
                    current_revision_id=run['current_revision_id'],best_revision_id=run['best_revision_id'])
    finally:con.close()
