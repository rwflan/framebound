"""Local reviewer-owned iterative animation feedback. Private evidence stays local."""
import base64
from contextlib import contextmanager
import io
import json
from pathlib import Path
import sqlite3
import threading
import uuid

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
        v=dict(id=revision_id,case_id=cid,frames=bundle['revision']['frame_asset_ids'],holds=spec['timing']['holds'],tps=spec['timing']['ticks_per_second'],loop=spec['loop'],parent=None,feedback_id=None,provenance=bundle['revision'].get('generation_metadata'),created_at=utcnow())
        put(con,'versions',v);put(con,'cases',dict(id=cid,title=title or spec['animation_id'],reason=reason,current=revision_id,status='review',intent=spec['intent'],inputs=spec.get('inputs',[]),canvas=spec['canvas']))
    return cid

def snapshot(project,case_id=None):
    with db(project) as con:
        cases=all_rows(con,'cases')
        if case_id:
            c=get(con,'cases',case_id)
            versions=[dict(v,urls=['/api/asset/'+a for a in v['frames']]) for v in all_rows(con,'versions') if v['case_id']==case_id]
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

def submit(project,actor,case_id,payload):
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
        for stroke in request.strokes:
            if stroke.slot>=len(version['frames']) or any(not (0<=x<case['canvas']['width'] and 0<=y<case['canvas']['height']) for x,y in stroke.points):raise InvalidInput('Annotation outside native frame')
        sheets=(len(version['frames'])+5)//6;quote=sheets*10000
        setting=con.execute("SELECT data FROM settings WHERE id='budget'").fetchone();ceiling=json.loads(setting[0])['ceiling'] if setting else 0
        committed=sum(s.get('incurred',s['quote']) for s in all_rows(con,'sends'))
        if committed+quote>ceiling:raise InvalidInput('Studio generation allowance exhausted; feedback remains in your draft')
        row=dict(id=request.id,case_id=case_id,request=request.model_dump(mode='json'),owner=actor.id,state='queued',quote=quote,created_at=utcnow(),error=None)
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
        with db(project) as con:pending=[f for f in all_rows(con,'feedback') if f['state'] in {'queued','generating'}]
        for feedback in pending:
            try:_generate(project,feedback,specialist or MuseResponses())
            except Exception as error:
                with db(project) as con:
                    row=get(con,'feedback',feedback['id']);sends=[s for s in all_rows(con,'sends') if s['feedback_id']==row['id']]
                    unknown=any(s['state'] in {'wire_started','unknown'} for s in sends)
                    for send in sends:
                        if send['state']=='wire_started':send['state']='unknown';put(con,'sends',send,True)
                    row.update(state='unknown' if unknown else 'failed',error=type(error).__name__+': '+str(error)[:500]);put(con,'feedback',row,True)

def _generate(project,feedback,specialist):
    from ..campaign.runner import png
    with db(project) as con:
        case=get(con,'cases',feedback['case_id']);baseline=get(con,'versions',feedback['request']['version_id'])
        feedback['state']='generating';put(con,'feedback',feedback,True)
    frames=[image_bytes(project,a) for a in baseline['frames']];result=[];receipts=[]
    for sheet in range((len(frames)+5)//6):
        sid=feedback['id']+'-'+str(sheet)
        with db(project) as con:
            con.execute('BEGIN IMMEDIATE');send=get(con,'sends',sid)
            if send['state'] in {'wire_started','unknown'}:raise InvalidInput('Unknown provider outcome requires reconciliation; no retry')
            if send['state']=='reserved':
                images=[]
                if result:images.append(image_bytes(project,result[-1]))
                for inp in case['inputs'][:1]:images.append(image_bytes(project,inp['asset_id']))
                for i,raw in enumerate(frames[sheet*6:sheet*6+6],start=sheet*6):
                    images.append(raw)
                    marks=[s for s in feedback['request']['strokes'] if s['slot']==i]
                    if marks:
                        with Image.open(io.BytesIO(raw)) as source:im=source.convert('RGBA')
                        overlay=Image.new('RGBA',im.size);draw=ImageDraw.Draw(overlay)
                        for stroke in marks:
                            color=stroke['color']+('66' if stroke['tool']=='highlighter' else 'ff');points=[tuple(p) for p in stroke['points']]
                            draw.line(points+points[-1:],fill=color,width=max(1,round(stroke['width'])),joint='curve')
                        images.append(png(Image.alpha_composite(im,overlay)))
                text=case['intent']+'\nAuthored timing: '+canonical(dict(holds=baseline['holds'],ticks_per_second=baseline['tps'],loop=baseline['loop'])).decode()+'\nUser correction: '+feedback['request']['text']+'\nAnnotations are visual feedback only; do not draw their marks into the artwork. Preserve identity and authored timing. Return a row-major 3-by-2 sheet, one pose per cell, for native slots '+str(list(range(sheet*6,min(len(frames),sheet*6+6))))+'. Baseline native frames are attached in order, with marked duplicates only where annotated. '+canonical(feedback['request']['strokes']).decode()
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
            for i in range(min(6,len(frames)-sheet*6)):
                im=source.crop((i%3*w,i//3*h,i%3*w+w,i//3*h+h)).convert('RGBA').resize((case['canvas']['width'],case['canvas']['height']),Image.Resampling.LANCZOS)
                aid='studio-'+digest([sid,i])[:40]
                write_derived(project,aid,im,baseline['frames'],dict(operator='studio-muse-crop-v1',original_output_sha256=original_sha,raw_response_sha256=send['response_sha256'],sheet_slot=i,feedback_id=feedback['id']))
                result.append(aid)
    with db(project) as con:
        con.execute('BEGIN IMMEDIATE');case=get(con,'cases',case['id'])
        if case['current']!=baseline['id']:raise S.StaleRevisionError('Parent changed during generation')
        version=dict(baseline,id='studio-version-'+feedback['id'],frames=result,parent=baseline['id'],feedback_id=feedback['id'],provenance=None,receipts=receipts,created_at=utcnow())
        put(con,'versions',version);case['current']=version['id'];put(con,'cases',case,True)
        feedback['state']='completed';feedback['version_id']=version['id'];put(con,'feedback',feedback,True)

def approve(project,actor,case_id,version_id):
    require_reviewer(actor,'approve')
    with db(project) as con:
        con.execute('BEGIN IMMEDIATE');case=get(con,'cases',case_id);version=get(con,'versions',version_id)
        if case['current']!=version_id or version['case_id']!=case_id:raise S.StaleRevisionError('Approve the current inspected version')
        if any(f['case_id']==case_id and f['state'] in {'queued','generating','unknown'} for f in all_rows(con,'feedback')):raise InvalidInput('Resolve pending generation before approval')
        aid='approval-'+digest([case_id,version_id]);old=con.execute('SELECT data FROM approvals WHERE id=?',(aid,)).fetchone()
        if old:return json.loads(old[0])
        feedback=[f for f in all_rows(con,'feedback') if f['case_id']==case_id]
        record=dict(id=aid,case_id=case_id,version_id=version_id,reviewer=actor.id,created_at=utcnow(),source='human',pairwise_preference=None)
        handoff=dict(schema_version='studio-human-approval-1.0',approval=record,version=version,feedback=feedback,case=case,training_status='explicit human acceptance; no inferred pairwise preference')
        history=[v for v in all_rows(con,'versions') if v['case_id']==case_id]
        handoff['history']=history
        closure=set(a for v in history for a in v['frames'])
        closure.update(i['asset_id'] for i in case['inputs'])
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
        record['handoff_path']=str(path);put(con,'approvals',record);case['status']='approved';put(con,'cases',case,True)
        return record
