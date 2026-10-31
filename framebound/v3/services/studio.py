"""Local reviewer-owned iterative animation feedback. Private evidence stays local."""
import base64
from contextlib import contextmanager
import io
import json
from pathlib import Path
import sqlite3
import threading
import uuid
from typing import Literal

from PIL import Image,ImageDraw
from pydantic import Field,StrictInt,model_validator
from ...v2 import storage as S
from ...v2.domain import Strict,utcnow
from ...v2.services.authz import require_reviewer
from ...v2.services.errors import InvalidInput
from ...v2.services.provenance import write_derived
from ..campaign.contracts import canonical,digest
from ..campaign.specialists import MuseResponses,wire,extract_image
from . import desk
from ..intake import inspect as inspect_sprite, cell, PRINCIPLE

class Stroke(Strict):
    slot: StrictInt=Field(ge=0,le=511)
    tool: str=Field(pattern='^(pen|highlighter)$')
    color: str=Field(pattern='^#[0-9a-fA-F]{6}$')
    width: float=Field(gt=0,le=64)
    points: list[tuple[float,float]]=Field(min_length=1,max_length=4000)

class Feedback(Strict):
    id: str=Field(pattern='^[a-zA-Z0-9-]{1,80}$')
    version_id: str=Field(min_length=1,max_length=128)
    text: str=Field(default='',max_length=8000)
    strokes: list[Stroke]=Field(default_factory=list,max_length=100)
    @model_validator(mode='after')
    def content(self):
        if not self.text.strip() and not self.strokes:raise ValueError('Describe or mark the issue')
        if sum(len(s.points) for s in self.strokes)>20000:raise ValueError('Too many annotation points')
        return self

class Replacement(Strict):
    id: str=Field(pattern='^[a-zA-Z0-9-]{1,80}$')
    version_id: str=Field(min_length=1,max_length=128)
    category: Literal['character','animal','figure','object']
    description: str=Field(min_length=8,max_length=2000)

def replace(project,actor,case_id,payload):
    require_reviewer(actor,'mark_issue');request=Replacement.model_validate(payload)
    prompt='Create an original isolated flat 2D game sprite of this '+request.category+': '+request.description+'. Show six consecutive distinct poses, fixed camera and scale. One whole uncropped subject per cell. No scenery, 3D rendering, paper texture, labels or effects-only abstract content. NEW clip: 6 frames, holds [2,2,2,2,2,2], 12 ticks/second, looping.'
    replacement=dict(title=request.description[:70],prompt=prompt,scope=request.category,source_run_id=case_id,source_revision=request.version_id,split_policy='retain source family and ancestry; never repartition',contract='NEW isolated 2D clip; 6 frames at 12 ticks/second')
    with db(project) as con:
        case=get(con,'cases',case_id)
        if case['status']!='excluded':raise InvalidInput('Only excluded input needs replacement; use feedback to edit an eligible take')
    return submit(project,actor,case_id,dict(id=request.id,version_id=request.version_id,text=request.description),replacement=replacement)

@contextmanager
def db(project):
    path=Path(project)/'studio.sqlite3';path.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(path,timeout=30);con.row_factory=sqlite3.Row
    con.executescript('''PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY,data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS feedback(id TEXT PRIMARY KEY,data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sends(id TEXT PRIMARY KEY,data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY,data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS settings(id TEXT PRIMARY KEY,data TEXT NOT NULL);
    ''')
    try:yield con;con.commit()
    except BaseException:con.rollback();raise
    finally:con.close()

def get(con,table,key):
    row=con.execute(f'SELECT data FROM {table} WHERE id=?',(key,)).fetchone()
    if not row:raise InvalidInput('Unknown review record')
    return json.loads(row[0])
def put(con,table,row,update=False):
    con.execute(f'INSERT {"OR REPLACE" if update else ""} INTO {table}(id,data) VALUES(?,?)',(row['id'],canonical(row).decode()))
def all_rows(con,table):return [json.loads(r[0]) for r in con.execute(f'SELECT data FROM {table} ORDER BY rowid')]

def seed(project,revision_id,title=None,reason='Review animation'):
    bundle=desk.revision(project,revision_id);spec=bundle['task']['spec'];cid=bundle['revision']['run_id']
    with db(project) as con:
        con.execute('BEGIN IMMEDIATE')
        if con.execute('SELECT 1 FROM cases WHERE id=?',(cid,)).fetchone():return cid
        gate=gate_frames(project,bundle['revision']['frame_asset_ids'])
        v=dict(intake=gate,id=revision_id,case_id=cid,frames=bundle['revision']['frame_asset_ids'],holds=spec['timing']['holds'],tps=spec['timing']['ticks_per_second'],loop=spec['loop'],parent=None,feedback_id=None,provenance=bundle['revision'].get('generation_metadata'),created_at=utcnow())
        put(con,'versions',v);put(con,'cases',dict(id=cid,title=title or spec['animation_id'],reason=reason,current=revision_id,status='review' if gate['eligible'] else 'excluded',intake=gate,intent=spec['intent'],inputs=spec.get('inputs',[]),canvas=spec['canvas']))
    return cid

def gate_frames(project,frames):
    checks=[]
    for aid in frames:
        try:
            with Image.open(io.BytesIO(image_bytes(project,aid))) as im:checks.append(inspect_sprite(im))
        except (OSError,ValueError,KeyError):checks.append(inspect_sprite(None))
    return dict(eligible=bool(checks) and all(c['eligible'] for c in checks),frames=checks,principle=PRINCIPLE)

def snapshot(project,case_id=None):
    with db(project) as con:
        versions_by_id={v['id']:v for v in all_rows(con,'versions')}
        cases=[dict(c,thumbnail_url='/api/asset/'+versions_by_id[c['current']]['frames'][0] if c.get('intake',{}).get('eligible') else None) for c in all_rows(con,'cases')]
        if case_id:
            c=get(con,'cases',case_id)
            versions=[dict(v,intake=v.get('intake') or gate_frames(project,v['frames']),urls=['/api/asset/'+a for a in v['frames']]) for v in all_rows(con,'versions') if v['case_id']==case_id]
            return dict(case=c,versions=versions,feedback=[f for f in all_rows(con,'feedback') if f['case_id']==case_id],approvals=[a for a in all_rows(con,'approvals') if a['case_id']==case_id])
        setting=con.execute("SELECT data FROM settings WHERE id='budget'").fetchone()
        budget=json.loads(setting[0]) if setting else dict(ceiling=0)
        sends=all_rows(con,'sends');reserved=sum(s['quote'] for s in sends if s['state'] in {'reserved','wire_started','unknown'})
        spent=sum(s.get('incurred',s['quote']) for s in sends if s['state']=='received')
        return dict(cases=cases,budget=dict(ceiling=budget['ceiling'],spent=spent,reserved=reserved))

def allocate(project,microdollars):
    if type(microdollars) is not int or microdollars<0:raise InvalidInput('Invalid allocation')
    with db(project) as con:
        con.execute('BEGIN IMMEDIATE')
        committed=sum(s.get('incurred',s['quote']) for s in all_rows(con,'sends'))
        if microdollars<committed:raise InvalidInput('Cannot erase committed costs')
        put(con,'settings',dict(id='budget',ceiling=microdollars),True)

def submit(project,actor,case_id,payload,*,replacement=None):
    require_reviewer(actor,'mark_issue');request=Feedback.model_validate(payload)
    with db(project) as con:
        con.execute('BEGIN IMMEDIATE')
        old=con.execute('SELECT data FROM feedback WHERE id=?',(request.id,)).fetchone()
        if old:
            row=json.loads(old[0])
            if row['request']!=request.model_dump(mode='json') or row['case_id']!=case_id or row['owner']!=actor.id:raise S.ConflictError('Feedback ID already used')
            return row
        case=get(con,'cases',case_id);version=get(con,'versions',request.version_id)
        if case['status']=='approved' or case['current']!=request.version_id or version['case_id']!=case_id:raise S.StaleRevisionError('Review the current animation before submitting')
        if any(f['case_id']==case_id and f['state'] in {'queued','generating','unknown'} for f in all_rows(con,'feedback')):raise S.ConflictError('Generation already pending')
        if not replacement and (case['status']=='excluded' or not gate_frames(project,version['frames'])['eligible']):raise InvalidInput('Outside MVP intake; generate an isolated replacement before reviewing')
        for stroke in request.strokes:
            if stroke.slot>=len(version['frames']) or any(not (0<=x<case['canvas']['width'] and 0<=y<case['canvas']['height']) for x,y in stroke.points):raise InvalidInput('Annotation outside native frame')
        sheets=1 if replacement else (len(version['frames'])+5)//6;quote=sheets*10000
        setting=con.execute("SELECT data FROM settings WHERE id='budget'").fetchone();ceiling=json.loads(setting[0])['ceiling'] if setting else 0
        committed=sum(s.get('incurred',s['quote']) for s in all_rows(con,'sends'))
        if committed+quote>ceiling:raise InvalidInput('Animation generation allowance exhausted; feedback remains in your draft')
        row=dict(replacement=replacement,id=request.id,case_id=case_id,request=request.model_dump(mode='json'),owner=actor.id,state='queued',quote=quote,created_at=utcnow(),error=None)
        put(con,'feedback',row)
        for sheet in range(sheets):put(con,'sends',dict(id=request.id+'-'+str(sheet),feedback_id=request.id,sheet=sheet,quote=10000,state='reserved'))
        return row

_workers=set();_guard=threading.Lock()
def start(project):
    with _guard:
        if str(project) in _workers:return
        _workers.add(str(project))
    def work():
        try:drain(project)
        finally:
            with _guard:_workers.discard(str(project))
    threading.Thread(target=work,daemon=True).start()

def image_bytes(project,aid):
    with S.connect(project) as con:asset,_=S.get(con,'assets',aid)
    raw=S.blob_path(project,asset['byte_sha256']).read_bytes()
    if S.sha256_bytes(raw)!=asset['byte_sha256']:raise InvalidInput('Frame hash differs')
    return raw

def drain(project,specialist=None):
    from filelock import FileLock
    with FileLock(str(Path(project)/'studio-worker.lock'),timeout=0):
        def process(feedback):
            try:_generate(project,feedback,specialist or MuseResponses())
            except Exception as error:
                with db(project) as con:
                    row=get(con,'feedback',feedback['id']);sends=[s for s in all_rows(con,'sends') if s['feedback_id']==row['id']]
                    unknown=any(s['state'] in {'wire_started','unknown'} for s in sends)
                    for send in sends:
                        if send['state']=='wire_started':send['state']='unknown';put(con,'sends',send,True)
                    row.update(state='unknown' if unknown else 'failed',error=type(error).__name__+': '+str(error)[:500]);put(con,'feedback',row,True)
        from concurrent.futures import ThreadPoolExecutor
        while True:
            with db(project) as con:pending=[f for f in all_rows(con,'feedback') if f['state'] in {'queued','generating'}]
            if not pending:break
            with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(process,pending))

def _generate(project,feedback,specialist):
    from ..campaign.runner import png
    with db(project) as con:
        case=get(con,'cases',feedback['case_id']);baseline=get(con,'versions',feedback['request']['version_id'])
        feedback['state']='generating';put(con,'feedback',feedback,True)
    replacement=feedback.get('replacement')
    frames=[b'']*6 if replacement else [image_bytes(project,a) for a in baseline['frames']];result=[];receipts=[];intakes=[]
    for sheet in range((len(frames)+5)//6):
        sid=feedback['id']+'-'+str(sheet)
        with db(project) as con:
            con.execute('BEGIN IMMEDIATE');send=get(con,'sends',sid)
            if send['state'] in {'wire_started','unknown'}:raise InvalidInput('Unknown provider outcome requires reconciliation; no retry')
            if send['state']=='reserved':
                images=[]
                if result:images.append(image_bytes(project,result[-1]))
                for inp in ([] if replacement else case['inputs'][:1]):images.append(image_bytes(project,inp['asset_id']))
                for i,raw in enumerate(frames[sheet*6:sheet*6+6],start=sheet*6):
                    if raw:images.append(raw)
                    marks=[s for s in feedback['request']['strokes'] if s['slot']==i]
                    if marks:
                        with Image.open(io.BytesIO(raw)) as source:im=source.convert('RGBA')
                        overlay=Image.new('RGBA',im.size);draw=ImageDraw.Draw(overlay)
                        for stroke in marks:
                            color=stroke['color']+('66' if stroke['tool']=='highlighter' else 'ff');points=[tuple(p) for p in stroke['points']]
                            draw.line(points+points[-1:],fill=color,width=max(1,round(stroke['width'])),joint='curve')
                        images.append(png(Image.alpha_composite(im,overlay)))
                text=case['intent']+'\nAuthored timing: '+canonical(dict(holds=baseline['holds'],ticks_per_second=baseline['tps'],loop=baseline['loop'])).decode()+'\nUser correction: '+feedback['request']['text']+'\nAnnotations are visual feedback only; do not draw their marks into the artwork. Preserve identity and authored timing. Return a row-major 3-by-2 sheet, one pose per cell, for native slots '+str(list(range(sheet*6,min(len(frames),sheet*6+6))))+'. Baseline native frames are attached in order, with marked duplicates only where annotated. '+canonical(feedback['request']['strokes']).decode()
                if replacement:text=replacement['prompt']
                text+='\nMVP REQUIREMENT: '+PRINCIPLE+' Render clean flat 2D sprite artwork on perfectly uniform pure RGB(255,0,255) magenta in every cell, including enclosed gaps. No magenta in the subject. No texture, grid lines, captions, cast shadows or scenery. Leave generous clear margins in every cell. Local extraction of this explicitly declared key will create alpha. Exactly 3 columns by 2 rows, equally sized square cells, six distinct consecutive poses, no gutters.'
                w=wire('muse-image-1.0',text,images);w['tools']=[dict(type='image_generation',size='1536x1024',output_format='png',enable_image_search=False,enable_web_search=False)]
                send.update(state='wire_started',request=dict(payload=dict(wire=w),quote=10000,images=1));put(con,'sends',send,True)
        if send['state']=='wire_started':
            response=specialist.execute(send['request'],timeout=180)
            sha=S.store_blob(project,response.raw)
            with db(project) as con:
                send.update(state='received',response_sha256=sha,incurred=response.incurred,receipt=response.receipt);put(con,'sends',send,True)
        if send.get('incurred',0)>send['quote']:raise InvalidInput('Provider cost exceeded the quoted amount; receipt retained')
        raw=S.blob_path(project,send['response_sha256']).read_bytes();output=extract_image(raw);original_sha=S.store_blob(project,output);receipts.append(dict(send_id=sid,raw_response=send['response_sha256'],original_output=original_sha))
        with Image.open(io.BytesIO(output)) as source:
            if source.width*source.height>16777216 or source.width%3 or source.height%2 or source.width//3!=source.height//2:raise InvalidInput('Generated sheet layout differs; original retained')
            source.load();w=source.width//3;h=source.height//2
            from ...v2.domain import Asset
            from ...v2.media.canonical import canonical_pixels,pixel_sha256
            original_id='review-sheet-'+original_sha[:40]
            asset=Asset(id=original_id,byte_sha256=original_sha,pixel_sha256=pixel_sha256(canonical_pixels(source)),mime='image/png',width=source.width,height=source.height,source_kind='generated',rights='original',origin='imported')
            with S.connect(project) as assets_con:
                with S.atomic(assets_con):S.stage_identical(assets_con,asset)
            for i in range(min(6,len(frames)-sheet*6)):
                im=source.crop((i%3*w,i//3*h,i%3*w+w,i//3*h+h)).convert('RGBA')
                im,extraction=cell(im)
                im=im.resize((case['canvas']['width'],case['canvas']['height']),Image.Resampling.LANCZOS)
                native_intake=inspect_sprite(im)
                if not native_intake['eligible']:raise InvalidInput('Native resampling failed intake: '+'; '.join(native_intake['reasons']))
                intakes.append(native_intake)
                aid='studio-'+digest([sid,i,'alpha-v3'])[:40]
                write_derived(project,aid,im,[original_id],dict(conditioning_frame_asset_ids=[] if replacement else baseline['frames'],operator='studio-muse-crop-v1',original_output_sha256=original_sha,raw_response_sha256=send['response_sha256'],sheet_slot=i,resampling='RGBA Lanczos after alpha extraction',feedback_id=feedback['id'],alpha_extraction=extraction))
                result.append(aid)
    with db(project) as con:
        con.execute('BEGIN IMMEDIATE');case=get(con,'cases',case['id'])
        if case['current']!=feedback.get('reprocess_parent',baseline['id']):raise S.StaleRevisionError('Parent changed during generation')
        version=dict(baseline,id='studio-version-'+feedback['id']+('-alpha-v3' if feedback.get('reprocess_parent') else ''),frames=result,parent=feedback.get('reprocess_parent',baseline['id']),feedback_id=feedback['id'],provenance=None,receipts=receipts,created_at=utcnow())
        version['intake']=dict(eligible=all(c['eligible'] for c in intakes),frames=intakes,principle=PRINCIPLE)
        if replacement:version.update(holds=[2]*6,tps=12,loop=True,replacement=replacement)
        put(con,'versions',version);case.update(current=version['id'],status='review',intake=version['intake'])
        if replacement:case.setdefault('original_inputs',case['inputs'])
        if replacement:case.update(title=replacement['title'],intent=replacement['prompt'],inputs=[],reason='Isolated 2D replacement · review requested')
        put(con,'cases',case,True)
        feedback['state']='completed';feedback['version_id']=version['id'];put(con,'feedback',feedback,True)
        for prior in all_rows(con,'feedback'):
            if prior['case_id']==case['id'] and prior['id']!=feedback['id'] and prior['state']=='failed':
                prior['superseded_by']=version['id'];put(con,'feedback',prior,True)

def reprocess_received(project,feedback_id):
    """Operator remediation: consume frozen receipts under a new alpha recipe, no sends.

    Preserve original takes; reject if a human has approved or started a child edit.
    """
    with db(project) as con:
        con.execute('BEGIN IMMEDIATE');feedback=get(con,'feedback',feedback_id);case=get(con,'cases',feedback['case_id'])
        if case['status']=='approved':raise InvalidInput('Cannot supersede an approved take')
        if feedback['state']=='unknown':raise InvalidInput('Unknown acceptance cannot be reprocessed')
        sends=[s for s in all_rows(con,'sends') if s['feedback_id']==feedback_id]
        if not sends or any(s['state']!='received' for s in sends):raise InvalidInput('Only completely received work can be reprocessed')
        if case['current'].endswith('-alpha-v3'):return
        if any(f['case_id']==case['id'] and f['id']!=feedback_id and f['state'] in {'queued','generating','unknown'} for f in all_rows(con,'feedback')):raise InvalidInput('A later edit is pending')
        current=get(con,'versions',case['current'])
        if current['id']!=feedback['request']['version_id'] and current.get('feedback_id')!=feedback_id:raise InvalidInput('A later take is already current')
        feedback.update(state='queued',error=None,reprocess_parent=current['id'],reprocess_reason='Versioned declared-key extraction and edge unmatting; original response and prior take retained',reprocess_at=utcnow())
        put(con,'feedback',feedback,True)

def approve(project,actor,case_id,version_id):
    require_reviewer(actor,'approve')
    with db(project) as con:
        con.execute('BEGIN IMMEDIATE');case=get(con,'cases',case_id);version=get(con,'versions',version_id)
        if not gate_frames(project,version['frames'])['eligible']:raise InvalidInput('MVP intake failed; approval and export withheld')
        if case['current']!=version_id or version['case_id']!=case_id:raise S.StaleRevisionError('Approve the current inspected version')
        if any(f['case_id']==case_id and f['state'] in {'queued','generating','unknown'} for f in all_rows(con,'feedback')):raise InvalidInput('Resolve pending generation before approval')
        aid='approval-'+digest([case_id,version_id]);old=con.execute('SELECT data FROM approvals WHERE id=?',(aid,)).fetchone()
        if old:return json.loads(old[0])
        feedback=[f for f in all_rows(con,'feedback') if f['case_id']==case_id]
        record=dict(id=aid,case_id=case_id,version_id=version_id,reviewer=actor.id,created_at=utcnow(),source='human',pairwise_preference=None)
        handoff=dict(schema_version='studio-human-approval-1.0',approval=record,version=version,feedback=feedback,case=case,training_status='explicit human acceptance; no inferred pairwise preference')
        history=[v for v in all_rows(con,'versions') if v['case_id']==case_id]
        attempts=[s for s in all_rows(con,'sends') if s['feedback_id'] in {f['id'] for f in feedback}]
        handoff['provider_attempts']=attempts
        handoff['history']=history
        handoff['learning_views']=dict(human_accepted_version_ids=[version_id],evidence_only_version_ids=[v['id'] for v in history if v['id']!=version_id],excluded_intake_version_ids=[v['id'] for v in history if not v.get('intake',{}).get('eligible')])
        closure=set(a for v in history for a in v['frames'])
        closure.update(i['asset_id'] for i in case['inputs']+case.get('original_inputs',[]))
        from ..provenance import parse
        for v in history:
            provenance=parse(v.get('provenance'))
            if provenance:closure.update(ref.asset_id for event in provenance.generations for ref in event.conditioning)
        with S.connect(project) as assets_con:
            assets={}
            pending=list(closure)
            while pending:
                aid=pending.pop()
                if aid in assets:continue
                assets[aid]=S.get(assets_con,'assets',aid)[0]
                pending.extend(assets[aid].get('parent_asset_ids',[]))
            closure=set(assets)
            handoff['assets']=assets
            handoff['asset_files']={a:'blobs/'+v['byte_sha256'] for a,v in assets.items()}
        for asset in closure:image_bytes(project,asset)
        path=Path(project)/'studio-exports'/aid;path.mkdir(parents=True,exist_ok=True)
        (path/'blobs').mkdir(exist_ok=True)
        from ..provenance import parse,blob_hashes
        for v in history:
            provenance=parse(v.get('provenance'))
            for sha in blob_hashes(provenance) if provenance else []:
                raw=S.blob_path(project,sha).read_bytes()
                if S.sha256_bytes(raw)!=sha:raise InvalidInput('Provenance closure differs')
                (path/'blobs'/sha).write_bytes(raw)
        (path/'handoff.json').write_bytes(canonical(handoff))
        for asset in closure:(path/'blobs'/assets[asset]['byte_sha256']).write_bytes(image_bytes(project,asset))
        for v in history:
            for receipt in v.get('receipts',[]):
                for key in ('raw_response','original_output'):
                    sha=receipt[key];raw=S.blob_path(project,sha).read_bytes()
                    if S.sha256_bytes(raw)!=sha:raise InvalidInput('Receipt closure hash differs')
                    (path/sha).write_bytes(raw)
        for send in attempts:
            if send.get('response_sha256'):
                sha=send['response_sha256'];raw=S.blob_path(project,sha).read_bytes()
                if S.sha256_bytes(raw)!=sha:raise InvalidInput('Attempt receipt hash differs')
                (path/sha).write_bytes(raw)
        record['handoff_path']=str(path);put(con,'approvals',record);case['status']='approved';put(con,'cases',case,True)
        return record
