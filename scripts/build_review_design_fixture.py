"""Build portable design-study evidence with production services and original Pip art.

Reviewer authority here is a named test fixture in a disposable project. It is
never entrant approval. The generated HTML studies make local review records;
they cannot write decisions or correction tasks into a production project.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
from framebound.v2 import storage as S
from framebound.v2.demo_character import RUN, JUMP, IDLE, render
from framebound.v2.services import assets, approvals, characters, clips, contracts, packets, projects
from framebound.v2.services.authz import Actor
from framebound.v2.services.eligibility import release_eligibility


def build(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    art_dir = output / 'fixture'
    art_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='framebound-design-evidence-') as work:
        project = str(Path(work) / 'project')
        source = Path(work) / 'source'
        source.mkdir()
        projects.create_project(project, {'id': 'design-fixture', 'name': 'Character animation'})

        def import_image(aid, image):
            path = source / (aid + '.png')
            image.save(path)
            assets.import_asset(project, str(path), aid, source_kind='procedural', rights='original')
            shutil.copyfile(path, art_dir / path.name)
            con = S.connect(project)
            try:
                return S.get(con, 'assets', aid)[0]
            finally:
                con.close()

        identity = import_image('pip-identity', render(RUN[0][1]))
        style = import_image('pip-style', render(IDLE[1][1]))
        characters.propose_character(project, {
            'id': 'pip-character-01', 'project_id': 'design-fixture',
            'identity_asset_ids': [identity['id']], 'style_asset_ids': [style['id']],
            'view_set': ['side'], 'canvas': {'width': 96, 'height': 96},
            'scale_ruler': 'Frozen 96px fixture canvas',
            'asymmetry': 'Satchel on left hip; trailing scarf',
        })
        editable = Image.new('L', (96, 96))
        ImageDraw.Draw(editable).rectangle((30, 25, 65, 68), fill=255)
        protected = Image.eval(editable, lambda p: 255-p)
        import_image('editable-torso', editable)
        import_image('protected-rest', protected)
        families = {}
        for action, poses in [('run', RUN), ('jump', JUMP), ('idle', IDLE)]:
            refs = [import_image(f'{action}-reference-{i:02}', render(p[1])) for i, p in enumerate(poses)]
            guide_id = f'guide-{action}-01'
            approvals.propose_motion_guide(project, Actor(type='orchestrator', id='design-builder'), {
                'id': guide_id, 'character_revision_id': 'pip-character-01',
                'entries': [{'phase': poses[i][0], 'asset_id': a['id'], 'byte_sha256': a['byte_sha256'],
                             'editable_mask_asset_id': 'editable-torso',
                             'protected_mask_asset_id': 'protected-rest'} for i,a in enumerate(refs)],
            })
            approvals.approve_reference(project, Actor(type='reviewer', id='DESIGN-FIXTURE-NOT-ENTRANT'),
                                         'pip-character-01', guide_id, f'reference-fixture-{action}')
            contract = {
                'id': f'contract-{action}-01', 'character_revision_id': 'pip-character-01',
                'action': {'name': action, 'view': 'side', 'facing': 'right', 'loop': action != 'jump'},
                'canvas': {'width':96,'height':96},
                'timing': {'ticks_per_second':60,'holds':[4]*len(poses)},
                'references': {'identity':identity['id'],'style':style['id'],'motion_guide_revision':guide_id},
                'phase_schedule':[{'slot':i,'phase':p[0],'motion_reference_id':refs[i]['id']} for i,p in enumerate(poses)],
                'constraints':[
                    {'id':'registration','check':'native_registration','required':True},
                    {'id':'silhouette-area','check':'silhouette_area','required':True,'params':{'max_fraction':.12}},
                    {'id':'silhouette-width','check':'silhouette_width','required':True,'params':{'max_fraction':.15}},
                    {'id':'cadence','check':'locked_cadence','required':True},
                ],
                'allowed_transforms':{'per_pose_scale':False,'rigid_translation_budget_px':2},
            }
            if action=='jump':
                contract['constraints'].append({'id':'visible-torso-span','check':'visible_span','required':True,
                    'params':{'color_a':[255,200,40],'color_b':[255,200,40],
                        'window_a':[26,30,56,56],'window_b':[22,52,54,72],
                        'expected':20,'max_delta':8,'occluded_slots':[2,3,4]}})
            contracts.propose_contract(project, contract)
            families[action] = (poses, refs, contract)

        records = []
        def revision(action, number, faulty=False, baseline=None):
            poses, refs, contract = families[action]
            aids = [r['id'] for r in refs]
            rid = f'pip-{action}-r{number:02}'
            if faulty:
                params = list(poses[3][1]); params[-1] += 13
                a=import_image('run-wide-torso', render(tuple(params)))
                aids[3]=a['id']
            if action=='jump':
                image=render(poses[1][1])
                for y in range(30,52):
                    for x in range(26,56):
                        if image.getpixel((x,y))[:3] == (255,200,40):
                            image.putpixel((x,y),(38,92,86,255))
                aids[1]=import_image('jump-missing-compass',image)['id']
            clips.create_revision(project,contract['id'],rid,aids,[p[0] for p in poses])
            result = clips.evaluate(project,rid)
            eid=result.artifacts[0]['id']
            pid=f'packet-{rid}'
            packets.create_packet(project,pid,rid,eid,'Procedural design fixture',baseline)
            con=S.connect(project)
            try:
                evaluation=S.get(con,'evaluations',eid)[0]
                rev=S.get(con,'clip_revisions',rid)[0]
                frames=[]
                for fid in rev['frame_instance_ids']:
                    fi=S.get(con,'frame_instances',fid)[0]
                    frames.append({**fi,'url':f"fixture/{fi['asset_id']}.png"})
                packet=S.get(con,'review_packets',pid)[0]
            finally:
                con.close()
            rec={'id':rid,'project_id':'design-fixture','label':action.title(),'revision':rev,'packet':packet,'contract':contract,
                 'evaluation':evaluation,'frames':frames,
                 'references':[{'phase':p[0],'asset_id':refs[i]['id'],'url':f"fixture/{refs[i]['id']}.png"} for i,p in enumerate(poses)],
                 'eligibility':release_eligibility(project,rid),
                 'reference_approval':{'actor_id':'DESIGN-FIXTURE-NOT-ENTRANT','status':'fixture-approved'},
                 'origin':'procedural','rights':'original','baseline':baseline}
            records.append(rec)
            return rid

        baseline=revision('run',1)
        revision('run',2,True,baseline)
        revision('run',3,False,'pip-run-r02')
        revision('jump',1)
        revision('idle',1)
        assert any(r['outcome']=='fail' for r in records[1]['evaluation']['results']), 'Fault must be measured'
        assert records[2]['evaluation']['technical_status']=='pass'
        assert records[3]['evaluation']['technical_status']=='incomplete'
        assert records[3]['evaluation']['coverage_status']=='partial'
        assert any(r['outcome']=='unmeasured' for r in records[3]['evaluation']['results'])
        data={'schema':'review-design-fixture-3','default_revision':'pip-run-r02',
              'identity':'fixture/pip-identity.png','style':'fixture/pip-style.png',
              'editable':'fixture/editable-torso.png','protected':'fixture/protected-rest.png',
              'origin':'procedural fixture','projects':[{'id':'design-fixture','name':'Character animation'}],'records':records}
        (output/'fixture.js').write_text('window.FRAMEBOUND_REVIEW_FIXTURE = '+json.dumps(data,separators=(',',':'))+';\n')
        return {r['id']:{'technical':r['evaluation']['technical_status'],
                           'coverage':r['evaluation']['coverage_status'],
                           'findings':sum(x['outcome']=='fail' for x in r['evaluation']['results'])} for r in records}


if __name__=='__main__':
    target=ROOT/'web/public/designs/review-desk'
    print(json.dumps(build(target),indent=2))
