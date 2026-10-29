"""Public MCP acceptance client. All reviewer decisions are explicit browser fixtures.

No raw SQL domain inserts are used. Creation uses MCP; the simulated upstream
uses the standard provider controller. Images are labeled procedural
regression art; training consumption opts into that disclosed research policy.
"""
import asyncio
import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from PIL import Image,ImageDraw
from mcp.client.stdio import StdioServerParameters,stdio_client
from mcp.client.session import ClientSession

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from framebound.v2.checks import fixtures as F


def row(project,table,rid):
    con=sqlite3.connect('file:'+str(Path(project)/'framebound.sqlite3')+'?mode=ro',uri=True)
    try:return json.loads(con.execute(f'SELECT data FROM {table} WHERE id=?',(rid,)).fetchone()[0])
    finally:con.close()


def raw_asset(project,aid):
    digest=row(project,'assets',aid)['byte_sha256']
    return (Path(project)/'blobs'/'sha256'/digest[:2]/digest[2:]).read_bytes()


async def execute(project,mode):
    params=StdioServerParameters(command=sys.executable,args=['-m','framebound','v2-mcp','--project',project],env=dict(os.environ))
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            names={tool.name for tool in (await session.list_tools()).tools}
            required={'project_create','character_propose','guide_propose','asset_import','contract_propose','clip_create_revision',
                      'animation_start','animation_step','animation_get','clip_evaluate','review_packet_create','generation_submit'}
            assert required<=names,names
            assert not names & {'approve_reference','reference_approve','spark_critique'}
            async def call(name,arguments):
                result=await session.call_tool(name,arguments)
                assert not result.is_error,(name,result.content)
                return json.loads(result.content[0].text)
            if mode=='setup':
                await call('project_create',{'project_id':'public-e2e','name':'Procedural acceptance fixtures'})
                await call('project_create',{'project_id':'public-e2e','name':'Procedural acceptance fixtures'})
                source=Path(project)/'test-input';source.mkdir(exist_ok=True)
                editable=Image.new('L',(64,64));ImageDraw.Draw(editable).rectangle((12,12,31,31),fill=255)
                protected=Image.new('L',(64,64));protected.putpixel((16,16),255)
                for aid,image in [('m-e2e-scope',editable),('m-e2e-protected',protected)]:
                    path=source/(aid+'.png');image.save(path)
                    await call('asset_import',{'src':str(path),'asset_id':aid,'source_kind':'original','rights':'original'})
                for family,scale,color in [('e2e',1.0,F.SHIRT),('second',1.2,(30,185,70,255))]:
                    assets=[];hashes={}
                    for slot in range(8):
                        aid=f'f-{family}-{slot}';path=source/(aid+'.png')
                        F.render(phase=slot*math.pi/4,torso_scale=scale,shirt=color).save(path)
                        result=await call('asset_import',{'src':str(path),'asset_id':aid,'source_kind':'procedural','rights':'original'})
                        assets.append(aid);hashes[aid]=result['artifacts'][0]['byte_sha256']
                    char=f'char-{family}-01';guide=f'mg-{family}-01';contract=f'contract-{family}-01'
                    await call('character_propose',{'character':{'id':char,'project_id':'public-e2e','identity_asset_ids':[assets[0]],
                        'style_asset_ids':[assets[1]],'view_set':['side'],'canvas':{'width':64,'height':64},'scale_ruler':'64px native test family'}})
                    await call('guide_propose',{'guide':{'id':guide,'character_revision_id':char,
                        'repair_policy':{'operators':['protected_restore'],'max_local_attempts':3,'max_compute_steps':8},
                        'entries':[{'phase':f'p{i}','asset_id':aid,'byte_sha256':hashes[aid],
                            'editable_mask_asset_id':'m-e2e-scope','protected_mask_asset_id':'m-e2e-protected'} for i,aid in enumerate(assets)]}})
                    await call('contract_propose',{'contract':{'id':contract,'character_revision_id':char,
                        'action':{'name':'run','view':'side','facing':'right','loop':True},'canvas':{'width':64,'height':64},
                        'timing':{'ticks_per_second':60,'holds':[4]*8},
                        'references':{'identity':assets[0],'style':assets[1],'motion_guide_revision':guide},
                        'phase_schedule':[{'slot':i,'phase':f'p{i}','motion_reference_id':assets[i]} for i in range(8)],
                        'constraints':[{'id':'registration','check':'native_registration','required':True},
                            {'id':'protection','check':'repair_protection','required':True}],
                        'allowed_transforms':{'per_pose_scale':False,'rigid_translation_budget_px':2}}})
                    damaged=Image.open(source/(assets[0]+'.png')).convert('RGBA');damaged.putpixel((0,0),(255,0,100,255))
                    damaged_path=source/(family+'-damaged.png');damaged.save(damaged_path)
                    await call('asset_import',{'src':str(damaged_path),'asset_id':family+'-damaged','source_kind':'procedural','rights':'original'})
                    faulty=list(assets);faulty[0]=family+'-damaged'
                    if family=='e2e':
                        visual=Image.open(source/(assets[3]+'.png')).convert('RGBA');ImageDraw.Draw(visual).rectangle((20,24,25,29),fill=(255,0,200,255))
                        path=source/'visual-issue.png';visual.save(path)
                        await call('asset_import',{'src':str(path),'asset_id':'visual-issue','source_kind':'procedural','rights':'original'})
                        faulty[3]='visual-issue'
                        await call('clip_create_revision',{'contract_id':contract,'revision_id':'rev-base','frame_asset_ids':assets,'phase_names':[f'p{i}' for i in range(8)]})
                    await call('clip_create_revision',{'contract_id':contract,'revision_id':family+'-faulty','frame_asset_ids':faulty,'phase_names':[f'p{i}' for i in range(8)]})
                return {'guard_active':bool(getattr(sys,'_framebound_egress_guard_active',False)),'phase':'references_pending','mcp_tool_count':len(names),'characters':['char-e2e-01','char-second-01']}
            if mode=='automatic':
                results=[]
                for family in ('e2e','second'):
                    run=await call('animation_start',{'revision_id':family+'-faulty','idempotency_key':family+'-native-work'})
                    if family=='e2e':
                        script="""import os,sys
from framebound.v2.services import auto_repair as A
def crash(stage):
 if stage=='rendered':os._exit(77)
A._checkpoint=crash
A.step_run(sys.argv[1],sys.argv[2])
"""
                        crashed=subprocess.run([sys.executable,'-c',script,project,run['run_id']],capture_output=True,text=True)
                        assert crashed.returncode==77,crashed.stderr
                    for _ in range(5):
                        run=await call('animation_step',{'run_id':run['run_id']})
                        if run['status']!='running':break
                    assert run['status']=='technically_ready',run
                    assert run['local_attempts_used']==1
                    assert await call('animation_get',{'run_id':run['run_id']})==run
                    revision=row(project,'clip_revisions',run['revision_id'])
                    frame=row(project,'frame_instances',revision['frame_instance_ids'][0])
                    actual=Image.open(io.BytesIO(raw_asset(project,frame['asset_id']))).convert('RGBA').tobytes()
                    expected=Image.open(io.BytesIO(raw_asset(project,f'f-{family}-0'))).convert('RGBA').tobytes()
                    assert actual==expected
                    results.append((run,frame['asset_id']))
                base_eval=await call('clip_evaluate',{'revision_id':'rev-base'})
                await call('review_packet_create',{'packet_id':'pkt-base','revision_id':'rev-base','evaluation_id':base_eval['artifacts'][0]['id'],'intent':'Test fixture reference'})
                review=results[0][0]
                await call('review_packet_create',{'packet_id':'pkt-diff','revision_id':review['revision_id'],'evaluation_id':review['evaluation_id'],'intent':'Procedural fixture: review bounded visual issue','comparison_revision_id':'rev-base'})
                return {'review_revision':review['revision_id'],'review_frame0_asset':results[0][1],
                        'automatic_runs':[result[0] for result in results],'worker_crash_exit':77}
            if mode=='negative':
                from framebound.v2.services import jobs as J,orchestrator as O
                os.environ['MODEL_API_KEY']='test-never-live'
                prepared=await call('brief_compile',{'contract_id':'contract-e2e-01','slot':2})
                envelope=await call('generation_submit',{'brief':prepared['brief'],'references':[],
                    'idempotency_key':'public-simulated-negative','offline':False})
                jid=envelope['artifacts'][0]['id'];provider_run=O.start_run(project,[jid]);claim=O.run_once(project,provider_run['run_id'],worker_id='fixture-specialist')
                image=Image.new('RGBA',(64,64),(140,0,240,255));buf=io.BytesIO();image.save(buf,format='PNG')
                def fake(request):return {'status':'completed','id':'fixture-response-not-live','output':[{'type':'image_generation_call','id':'fixture-image','result':base64.b64encode(buf.getvalue()).decode()}]}
                result=O.orchestrator_send(project,provider_run['run_id'],jid,worker_id='fixture-specialist',fencing_token=claim['fencing_token'],transport=fake)
                assert result['action']=='succeeded'
                asset=J.job_get(project,jid)['job']['output_asset_ids'][0]
                frames=[f'f-e2e-{i}' for i in range(8)];frames[2]=asset
                await call('clip_create_revision',{'contract_id':'contract-e2e-01','revision_id':'simulated-root','frame_asset_ids':frames,'phase_names':[f'p{i}' for i in range(8)]})
                run=await call('animation_start',{'revision_id':'simulated-root','idempotency_key':'simulated-derived'})
                for _ in range(5):
                    run=await call('animation_step',{'run_id':run['run_id']})
                    if run['status']!='running':break
                assert run['status']=='technically_ready',run
                revision=row(project,'clip_revisions',run['revision_id']);frame=row(project,'frame_instances',revision['frame_instance_ids'][2])
                derived=row(project,'assets',frame['asset_id']);assert derived['origin']=='simulated-transport' and derived['rights']=='mixed'
                assert row(project,'assets',asset)['rights']=='unknown'
                # A distinct pending SAM note is not reachable from any selected output.
                pending=await call('generation_submit',{'brief':prepared['brief'],'references':[],
                    'idempotency_key':'unrelated-private-note','offline':True,
                    'provider_settings':{'provider':'sam','source_asset_id':'f-e2e-2','prompt':'unrelated private provider note sentinel'}})
                private=J.job_get(project,pending['artifacts'][0]['id'])['job']
                return {'negative_revision':run['revision_id'],'negative_asset':derived['id'],'negative_packet':run['packet_id'],
                        'private_note_digest':private['request_artifact'],'private_note':'unrelated private provider note sentinel'}
            raise ValueError('unknown setup phase '+mode)


if __name__=='__main__':
    print(json.dumps(asyncio.run(execute(str(Path(sys.argv[1]).absolute()),sys.argv[2] if len(sys.argv)>2 else 'setup'))))
