"""Unattended local campaign workflow over bounded external specialists.

Immutable outbox results are re-consumed after a crash. Artwork is always Muse;
normalization and compositing are explicit local derivations. Failure results
are retained. Unknown provider outcomes never trigger another paid attempt.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import time
from pathlib import Path

from filelock import FileLock
from PIL import Image, ImageOps

from ...v2 import storage as S, domain as D
from ...v2.media.canonical import canonical_pixels, pixel_sha256
from ...v2.services.assets import import_asset
from ...v2.services.projects import create_project
from ...v2.services.provenance import write_derived
from ..services import loop, tasks
from .assessment import Assessment, Binding, CATEGORIES, Provenance, abstention, DIAGNOSIS_RUBRIC, COMPARISON_RUBRIC, temporal_windows
from .contracts import canonical, digest, local_path
from .dispatch import dispatch
from .features import extract
from .experiment import controls, paired_report
from .repair import blind_assignment, decide
from .ledger import Ledger, Stopped
from .repair import Scope, Comparison, authorize, binding_in, composite, prepare_comparisons, record_comparison
from .specialists import wire, extract_image, extract_text


def png(image):
    stream=io.BytesIO();image.convert('RGBA').save(stream,format='PNG');return stream.getvalue()


class Runner:
    def __init__(self, root, campaign, specialist):
        self.ledger=Ledger(root);self.root=Path(root).resolve();self.campaign=campaign
        self.config=self.ledger.config(campaign);self.specialist=specialist
        self.folder=local_path(root,f'campaigns/{campaign}')
        self.project=str(self.folder/'project')
        create_project(self.project,dict(id='campaign',name='Local animation campaign'))

    def _save(self, area, name, raw):
        path=local_path(self.root,f'campaigns/{self.campaign}/{area}/{name}')
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists() and path.read_bytes()!=raw: raise ValueError('immutable campaign artifact differs')
        if not path.exists(): path.write_bytes(raw)
        return path

    def _call(self, case, operation, text, images=(), *, attempt=0, sheet=0, parents=(), image=False):
        if hasattr(self,'_case_started') and time.monotonic()-self._case_started+self._case_initial_active>=self.config.limits.active_seconds:
            raise Stopped('case active processing ceiling')
        model='muse-image-1.0' if image else 'muse-spark-1.3'
        # Reuse frozen executable requests across software changes. Only a known
        # incomplete diagnosis can consume the one explicit recheck lane.
        with self.ledger.db() as db:
            existing=db.execute("SELECT * FROM requests WHERE campaign=? AND case_id=? AND operation=? AND json_extract(request,'$.attempt')=? AND json_extract(request,'$.sheet')=?",
                (self.campaign,case.id,operation,attempt,sheet)).fetchone()
        if existing:
            row=dict(existing)
        else:
            tokens=65536;output=8192
            request_wire=wire(model,text,images,max_output_tokens=None if image else output)
            if not image:request_wire['reasoning']={'effort':'low'}
            else:request_wire['tools']=[dict(type='image_generation',size='1024x1024' if operation=='anchor' else '1536x1024',output_format='png',enable_image_search=False,enable_web_search=False)]
            quote=self.config.prices.image_microdollars if image else math.ceil(tokens*1.25+output*4.25)
            payload=dict(provider='meta',requested_model=model,wire=request_wire,
                input_token_ceiling=None if image else tokens,output_token_ceiling=None if image else output)
            row=self.ledger.reserve(self.campaign,case.id,operation,payload,quote=quote,images=int(image),attempt=attempt,sheet=sheet,parents=parents)
        if row['state']=='reserved': dispatch(self.ledger,row['id'],self.specialist)
        raw,receipt=self.ledger.artifact(row['id'])
        if not self.ledger.status(self.campaign)['stopped']:
            return row['id'],raw,receipt
        raise Stopped('provider cost exceeded frozen quote; result preserved before stopping')

    def _frames(self, ids):
        images=[]
        con=S.connect(self.project)
        try:
            for aid in ids:
                asset,_=S.get(con,'assets',aid);path=S.blob_path(self.project,asset['byte_sha256'])
                if S.sha256_bytes(path.read_bytes())!=asset['byte_sha256']: raise ValueError('native frame hash mismatch')
                with Image.open(path) as source: source.load();images.append(source.convert('RGBA'))
        finally:con.close()
        return images

    def _anchor(self, case):
        path=local_path(self.root,f'campaigns/anchors/{digest(case.family)}.json')
        if path.exists():
            stored=json.loads(path.read_text());raw,receipt=self.ledger.artifact(stored['request_id'])
            return stored['request_id'],extract_image(raw)
        with self.ledger.db() as db:
            existing=db.execute("SELECT r.id,r.state FROM requests r JOIN cases c ON c.campaign=r.campaign AND c.id=r.case_id WHERE c.family=? AND r.operation='anchor' AND r.state!='cancelled' ORDER BY r.rowid LIMIT 1",(case.family,)).fetchone()
        if existing:
            if existing['state']=='reserved':dispatch(self.ledger,existing['id'],self.specialist)
            raw,receipt=self.ledger.artifact(existing['id'])
            image=extract_image(raw)
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(canonical(dict(request_id=existing['id'],sha256=hashlib.sha256(image).hexdigest())))
            return existing['id'],image
        rid,raw,receipt=self._call(case,'anchor',
            'Create one original isolated design anchor for the declared entity graph; do not invent an actor for an effect-only graph. No existing character or source reference. '+case.request+' Style treatment: '+self.config.treatments[case.treatment]+' Graph: '+canonical(case.complexity).decode(),
            image=True)
        image=extract_image(raw)
        with Image.open(io.BytesIO(image)) as check: check.verify()
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(canonical(dict(request_id=rid,sha256=hashlib.sha256(image).hexdigest())))
        return rid,image

    def _import_muse_media(self,raw,asset_id):
        """Preserve actual provider bytes and record PNG normalization as derivation."""
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in {'PNG','WEBP','JPEG'} or source.width*source.height>16777216 or max(source.size)>8192:
                raise ValueError('unsupported or oversized Muse source media')
            source_format=source.format
            source.load();image=ImageOps.exif_transpose(source).convert('RGBA')
            original_size=source.size
        original_sha=S.store_blob(self.project,raw)
        self._save('originals',original_sha+'.'+source_format.lower(),raw)
        original_id=asset_id+'-original'
        original=D.Asset(id=original_id,byte_sha256=original_sha,pixel_sha256=pixel_sha256(canonical_pixels(image)),
            mime={'PNG':'image/png','WEBP':'image/webp','JPEG':'image/jpeg'}[source_format],
            width=original_size[0],height=original_size[1],source_kind='generated',rights='original',origin='imported')
        con=S.connect(self.project)
        try:
            with S.atomic(con):
                con.execute('BEGIN IMMEDIATE');S.stage_identical(con,original)
        finally:con.close()
        normalized=write_derived(self.project,asset_id,image,[original_id],dict(operator='muse-source-to-png-v1',
            source_format=source_format,orientation='explicit EXIF transpose',resampling='none',alpha='preserved; no extraction'))
        self._save('canonical/sources',asset_id+'.png',S.blob_path(self.project,normalized.byte_sha256).read_bytes())
        return normalized,dict(operation='decode '+source_format+' and explicitly normalize orientation/RGBA to PNG',
            input_sha256=original_sha,output_sha256=normalized.byte_sha256)

    def _spec(self, case, anchor):
        tid='campaign-'+digest([self.campaign,case.id])[:32]
        try:
            saved=tasks.get(self.project,tid)['spec']
            loop.start(self.project,tid,tid+'-run')
            return saved,tid+'-run'
        except InvalidInput:pass
        anchor_id=tid+'-anchor'
        anchor_asset,_=self._import_muse_media(anchor,anchor_id)
        spec=dict(id=tid,project_id='campaign',animation_id=case.id,intent=case.request,subjects='Original entity graph: '+canonical(case.complexity).decode(),
            canvas=dict(width=256,height=256),timing=dict(holds=case.holds,ticks_per_second=case.ticks_per_second),loop=case.loop,
            inputs=[dict(asset_id=anchor_id,role='identity',byte_sha256=anchor_asset.byte_sha256,provenance='PNG-normalized Muse anchor; untouched provider bytes and derivation retained',designated_by='frozen campaign',basis='Original generated bytes and durable receipt')],
            automatic_repair=dict(enabled=True,categories=list(CATEGORIES),allowed_slots=list(range(len(case.holds))),allow_full_frame=True),
            repair_scope='declared_regions',limits=dict(max_submissions=3),requirements=[dict(id='semantic-quality',check='animation_quality',required=False,
                desired_outcome='Bounded semantic assessment is separate from structural checks')])
        tasks.create(self.project,spec);loop.start(self.project,tid,tid+'-run')
        return tasks.get(self.project,tid)['spec'],tid+'-run'

    def _materialize(self, case, anchor, *, operation='generate', attempt=0, authority=None):
        spec,run_id=self._spec(case,anchor)
        anchor=S.blob_path(self.project,spec['inputs'][0]['byte_sha256']).read_bytes()
        baseline=self._frames(loop.revision_get(self.project,authority['baseline_revision_id'])['revision']['frame_asset_ids']) if authority else None
        scope=Scope.model_validate(authority['scope']) if authority else None
        frame_ids=[];events=[];boundary=None
        for sheet in range(math.ceil(len(case.holds)/6)):
            start=sheet*6;count=min(6,len(case.holds)-start)
            refs=[anchor];conditioning=[spec['inputs'][0]['asset_id']]
            if boundary is not None:
                refs.append(png(boundary));conditioning.append(frame_ids[-1])
            if baseline:
                refs.extend(png(f) for f in baseline[start:start+count])
                parent=loop.revision_get(self.project,authority['baseline_revision_id'])['revision']
                conditioning.extend(parent['frame_asset_ids'][start:start+count])
            instruction=case.request+'\nStyle treatment: '+self.config.treatments[case.treatment]+' Detail: '+case.detail+'\n'+canonical(dict(holds=case.holds,loop=case.loop,complexity=case.complexity.model_dump(),sheet=sheet,
                native_slots=list(range(start,start+count)))).decode()
            instruction+='\nReturn a row-major 3-by-2 sheet of six distinct square poses. Preserve original anchor identity; the last input boundary pose fixes continuity.'
            if authority: instruction+='\n'+authority['instruction']
            rid,response,receipt=self._call(case,operation,instruction,refs,attempt=attempt,sheet=sheet,image=True,
                parents=[authority['baseline_revision_id']] if authority else [])
            raw=extract_image(response);sha=S.store_blob(self.project,raw)
            source_id='sheet-'+rid[:32]
            source_asset,normalization=self._import_muse_media(raw,source_id)
            receipt_sha=S.store_blob(self.project,response)
            anchor_record=json.loads(local_path(self.root,f'campaigns/anchors/{digest(case.family)}.json').read_text())
            anchor_response,_=self.ledger.artifact(anchor_record['request_id'])
            anchor_receipt_sha=S.store_blob(self.project,anchor_response)
            with Image.open(S.blob_path(self.project,source_asset.byte_sha256)) as source:
                source.load()
                if source.width*source.height>16777216 or source.width%3 or source.height%2 or source.width//3!=source.height//2:
                    raise ValueError('wrong-size sheet; stop before repeating this request shape')
                w=source.width//3;h=source.height//2
                crops=[source.crop((i%3*w,i//3*h,i%3*w+w,i//3*h+h)).convert('RGBA').resize((256,256),Image.Resampling.LANCZOS) for i in range(count)]
            raw_crops=crops
            if baseline:
                local_scope=Scope(slots=[s-start for s in scope.slots if start<=s<start+count] or [0],roi=scope.roi)
                if any(start<=s<start+count for s in scope.slots): crops=composite(baseline[start:start+count],crops,local_scope)
                else:crops=[f.copy() for f in baseline[start:start+count]]
            event=dict(id='generation-'+rid[:40],provider='meta',requested_model='muse-image-1.0',
                observed_model=receipt['provider'].get('observed_model'),observed_version=receipt['provider'].get('observed_version'),
                evidence_source='external_assertion',outcome='succeeded',response_id=receipt['provider'].get('response_id'),
                request_id=rid,edit_parent_event_id=(loop.revision_get(self.project,authority['baseline_revision_id'])['revision']['generation_metadata']['provenance']['generations'][-1]['id'] if authority else None),prompt_sha256=hashlib.sha256(instruction.encode()).hexdigest(),conditioning=[],
                original_output_sha256=[sha],receipt_sha256=[receipt_sha,anchor_receipt_sha],output_asset_ids=[],transformations=[normalization])
            con=S.connect(self.project)
            try:
                for aid in conditioning:
                    asset,_=S.get(con,'assets',aid)
                    event['conditioning'].append(dict(asset_id=aid,byte_sha256=asset['byte_sha256'],role='identity' if aid==spec['inputs'][0]['asset_id'] else 'boundary_or_baseline',
                        conditioning_eligibility='original',eligibility_basis='Original generated ancestry, retained locally'))
            finally:con.close()
            for i,frame in enumerate(crops):
                aid='native-'+rid[:32]+f'-{i}'
                derived=write_derived(self.project,aid,frame,[source_id,*conditioning],dict(operator='campaign-crop-resize-composite-v1',
                    canvas=[256,256],sheet_slot=i,global_slot=start+i,scope=scope.model_dump() if scope else None,resampling='LANCZOS'))
                frame_ids.append(aid);event['output_asset_ids'].append(aid)
                event['transformations'].append(dict(operation='declared crop, resize and authorized compositing' if baseline else 'declared crop and resize',
                    input_sha256=source_asset.byte_sha256,output_sha256=derived.byte_sha256))
                self._save('canonical',aid+'.png',S.blob_path(self.project,derived.byte_sha256).read_bytes())
                self._save('repairs' if baseline else 'canonical','raw-'+aid+'.png',png(raw_crops[i]))
            events.append(event);boundary=crops[-1]
        from ...v2.services.provenance import ancestry_in,provenance_index_in
        con=S.connect(self.project)
        try:
            index=provenance_index_in(con);ancestor_ids=set()
            for aid in frame_ids:ancestor_ids.update(ancestry_in(con,aid,index=index)['asset_ids'])
            source_ancestry={aid:index[0][aid] for aid in sorted(ancestor_ids)}
        finally:con.close()
        metadata=dict(provenance=dict(schema_version='1.0',generations=events),campaign=dict(id=self.campaign,case_id=case.id,family=case.family,split=case.split,
            authority=authority['source'] if authority else None,asset_ancestry=source_ancestry))
        if operation=='blind_rerun': return frame_ids,metadata
        revision='revision-'+digest([self.campaign,case.id,operation,attempt])[:40]
        parent=authority['baseline_revision_id'] if authority else None
        loop.submit(self.project,run_id,revision,frame_ids,parent_revision_id=parent,feedback_id='feedback:'+parent if parent else None,generation_metadata=metadata)
        return run_id,revision

    def _assess(self, case, run_id, revision_id, *, ordinal):
        run=loop.get(self.project,run_id);revision=loop.revision_get(self.project,revision_id)['revision']
        con=loop.connect(self.project)
        try:
            task=tasks._get(con,revision['task_id'])
            evaluation=loop.get_in(con,'agent_evaluations','evaluation:'+revision_id)
            binding=Binding(request_sha256=task.spec_sha256,revision_sha256=digest(revision),
                timing_sha256=digest(task.spec.timing.model_dump(mode='json')),evaluation_sha256=digest(evaluation))
            anchor_asset,_=S.get(con,'assets',task.spec.inputs[0].asset_id)
            anchor=S.blob_path(self.project,anchor_asset['byte_sha256']).read_bytes()
        finally:con.close()
        frames=self._frames(revision['frame_asset_ids']);features=extract(frames,case.holds,loop=case.loop)
        context=dict(request=case.request,binding=binding.model_dump(),subject_registry={'scene_canvas':'The whole native canvas; use subject_id=scene_canvas only for composition/canvas artifacts. For actor/part/prop identity, leave subject_id null and name the exact subject; never alias different entities.'},holds=case.holds,ticks_per_second=case.ticks_per_second,
            image_order='identity anchor, then ordered native frames',windows=temporal_windows(case.holds,loop=case.loop),measurement_proposals=features['proposals'],schema=Assessment.model_json_schema())
        rubric=DIAGNOSIS_RUBRIC+(' Independent preservation audit: inspect each subject, legitimate deformation and event order without seeing another assessment.' if ordinal%2 else '')
        text=rubric+'\nFor any assessed category, list actual native slots (0 to '+str(len(frames)-1)+'). No props or no extraction means not_assessed, not an empty-scope negative label. Include a visibility field in every finding.\nCoverage present means a DEFECT exists in that category, never that an entity or property exists. Every present category MUST have a corresponding localized finding. Explicitly include visibility=supported only when the pose and observations support a defect. Opaque backdrops do not establish extraction defects unless extraction was actually performed.\nReturn only {"coverage": [...], "findings": [...]}; provenance and binding are attached locally.\n'+canonical(context).decode()
        rid,raw,receipt=self._call(case,'diagnose',text,[anchor,*[png(f) for f in frames]],attempt=ordinal,parents=[revision_id])
        response=json.loads(raw)
        if response.get('status')=='incomplete':
            if response.get('incomplete_details',{}).get('reason')!='max_output_tokens':
                raise ValueError('unsupported incomplete assessment; retain uncertainty')
            original_rid=rid
            rid,raw,receipt=self._call(case,'recheck',text,[anchor,*[png(f) for f in frames]],
                attempt=0,parents=[revision_id,original_rid],sheet=ordinal%self.config.limits.sheets)
        # Provenance describes the actual frozen request, including legacy requests.
        actual_request=json.loads(self.ledger.request(rid)['request'])
        p=Provenance(provider='meta',requested_model='muse-spark-1.3',observed_model=receipt['provider'].get('observed_model'),
            observed_version=receipt['provider'].get('observed_version'),rubric_sha256=digest(actual_request['payload']['wire']['input'][0]['content'][0]['text'].split('\nReturn only')[0]),raw_sha256=hashlib.sha256(raw).hexdigest(),execution_id=rid)
        try:
            body=extract_text(raw)
            if set(body)!={'coverage','findings'}:raise ValueError('unexpected teacher fields')
            # Downgrade unsupported claims only; never fill absent scope from
            # another category or invent negative/positive training evidence.
            downgrades=[]
            for coverage in body['coverage']:
                category=coverage['category']
                unsupported=(coverage['status'] in {'present','absent_within_assessed_scope'} and not coverage.get('slots'))
                unsupported|=coverage['status']=='present' and not any(f.get('category')==category for f in body['findings'])
                unsupported|=category=='extraction'  # this pipeline performs no matting
                if unsupported:
                    downgrades.append(category)
                    coverage['status']='not_assessed'
                    coverage['limitations']='Unsupported scope or absent extraction operation. Original teacher claim retained in the raw response.'
                    body['findings']=[f for f in body['findings'] if f.get('category')!=category]
            if downgrades:self._save('annotations',rid+'-normalization.json',canonical(dict(raw_sha256=p.raw_sha256,
                downgraded_categories=downgrades,operator='unsupported-coverage-abstention-v1')))
            assessment=Assessment(binding=binding,provenance=p,**body).validate_evidence(binding,case.holds,frames[0].size)
        except ValueError as error:
            self._save('annotations',rid+'-quarantine.json',canonical(dict(raw_sha256=p.raw_sha256,reason=str(error),
                normalization='No semantic targets inferred; invalid teacher schema retained separately')))
            assessment=abstention(binding,p,list(range(len(frames))),'Teacher response failed the bounded evidence contract; raw response retained and case quarantined.')
        self._save('annotations',rid+'.json',canonical(assessment))
        return assessment

    def _compare(self, case, authority):
        rows=prepare_comparisons(self.project,authority['id'],seed=self.config.seed)
        for row in rows:
            if row['comparison']:continue
            baseline=loop.revision_get(self.project,row['baseline_revision_id'])['revision']
            candidate=loop.revision_get(self.project,row['candidate_revision_id'])['revision']
            by_sha={digest(baseline):baseline,digest(candidate):candidate}
            images=[]
            for key in ('A','B'):images.extend(png(f) for f in self._frames(by_sha[row['assignment'][key]]['frame_asset_ids']))
            target=next(f for f in authority['assessment']['findings'] if f['id']==authority['finding_id'])
            text=COMPARISON_RUBRIC+'\n'+canonical(dict(request=case.request,assignment=row['assignment'],target_category=target['category'],
                expected_behavior=target['expected'],holds=case.holds,ticks_per_second=case.ticks_per_second,windows=temporal_windows(case.holds,loop=case.loop),
                output_fields=['preference','target_improved','material_regression','evidence','assessed_categories'],image_order='all native A frames, then all native B frames')).decode()
            rid,raw,receipt=self._call(case,'compare',text,images,attempt=int(row['id'][:8],16),parents=[row['id']])
            p=Provenance(provider='meta',requested_model='muse-spark-1.3',observed_model=receipt['provider'].get('observed_model'),
                rubric_sha256=digest(COMPARISON_RUBRIC),raw_sha256=hashlib.sha256(raw).hexdigest(),execution_id=rid)
            record_comparison(self.project,row['id'],Comparison(assignment_sha256=digest(row['assignment']),provenance=p,**extract_text(raw)))
        con=loop.connect(self.project)
        try:return loop.get_in(con,'agent_auto_authorities',authority['id'])['status']
        finally:con.close()

    def case(self,case):
        self._case_started=time.monotonic()
        self._case_initial_active=self.ledger.progress(self.campaign,case.id)['active_seconds']
        try:return self._case(case)
        finally:
            elapsed=time.monotonic()-self._case_started
            recorded=self.ledger.progress(self.campaign,case.id)['active_seconds']-self._case_initial_active
            self.ledger.add_active_time(self.campaign,case.id,max(0,elapsed-recorded))

    def _case(self, case):
        progress=self.ledger.progress(self.campaign,case.id)
        if progress['result']:return progress['result']
        # The frozen plan requires six-pose provider operation before longer
        # sequence admission. A local test alone does not establish this gate.
        if len(case.holds)>6:
            gate=local_path(self.root,f'campaigns/{self.campaign}/capabilities/long-sequences.json')
            if not gate.is_file() or json.loads(gate.read_text()).get('config_sha256')!=digest(self.config):
                raise Stopped('long-sequence provider capability gate has not been recorded for this frozen config')
        anchor_id,anchor=self._anchor(case)
        if not progress['data'].get('base_revision'):
            run_id,revision=self._materialize(case,anchor)
            self.ledger.progress(self.campaign,case.id,state='canonicalized',data=dict(run_id=run_id,base_revision=revision))
        else:run_id=progress['data']['run_id'];revision=progress['data']['base_revision']
        from ..intake import inspect,PRINCIPLE
        frame_ids=loop.revision_get(self.project,revision)['revision']['frame_asset_ids']
        intake=[inspect(im) for im in self._frames(frame_ids)]
        if not all(r['eligible'] for r in intake):
            result=dict(outcome='rejected',base_revision_id=revision,reason='MVP intake failed before semantic assessment',intake=intake,principle=PRINCIPLE)
            self.ledger.finish_case(self.campaign,case.id,'rejected',result)
            return result
        a=self._assess(case,run_id,revision,ordinal=0)
        original_revision=revision
        outcome='ambiguous';authority=None;after=a;corroboration=None
        for attempt in range(self.config.limits.repairs):
            targets=[f for f in a.findings if f.severity in {'material','critical'} and f.visibility=='supported']
            if not targets:
                if attempt==0 and int(digest(case.id)[:8],16)%5==0:self._assess(case,run_id,revision,ordinal=1)
                if attempt==0:outcome='unchanged' if all(c.status=='absent_within_assessed_scope' for c in a.coverage) else 'ambiguous'
                break
            independent=self._assess(case,run_id,revision,ordinal=attempt*2+1)
            from .corroboration import audit
            corroboration=audit(a,independent)
            self._save('comparisons','corroboration-'+digest([a.provenance.execution_id,independent.provenance.execution_id])+'.json',canonical(corroboration))
            eligible=corroboration['eligible_finding_ids']
            if not eligible:
                outcome='ambiguous';break
            target=next(f for f in targets if f.id==eligible[0])
            con=loop.connect(self.project)
            try:
                previous=[json.loads(r['data']) for r in con.execute('SELECT data FROM agent_auto_authorities')
                    if json.loads(r['data'])['run_id']==run_id and json.loads(r['data'])['baseline_revision_id']==revision]
            finally:con.close()
            try:authority=previous[0] if previous else authorize(self.project,run_id,a,independent,target.id)
            except InvalidInput as exc:
                outcome='ambiguous';break
            _,candidate=self._materialize(case,anchor,operation='repair',attempt=attempt,authority=authority)
            after=self._assess(case,run_id,candidate,ordinal=attempt*2+2)
            outcome=self._compare(case,authority)
            if outcome!='accepted':break
            revision=candidate;a=after
        result=dict(outcome=outcome,base_revision_id=original_revision,after_assessment=after.model_dump(mode='json'),
            authority_id=authority['id'] if authority else None,corroboration=corroboration)
        allocation=controls(self.config)
        if authority and case.id in {r['case_id'] for r in allocation['cases']}:
            result['control']=self._control(case,anchor,original_revision,authority,outcome)
        self.ledger.finish_case(self.campaign,case.id,outcome,result)
        return result

    def _control(self,case,anchor,original_revision,authority,guided_outcome):
        """One original-request rerun, selected before observing repair success."""
        ids,_=self._materialize(case,anchor,operation='blind_rerun')
        original=loop.revision_get(self.project,original_revision)['revision']
        candidate_sha=digest(ids)
        assignment=blind_assignment(case.id,digest(original),candidate_sha,seed=self.config.seed)
        by_sha={digest(original):self._frames(original['frame_asset_ids']),candidate_sha:self._frames(ids)}
        images=[]
        for key in ('A','B'):images.extend(png(f) for f in by_sha[assignment[key]])
        target=next(f for f in authority['assessment']['findings'] if f['id']==authority['finding_id'])
        text=COMPARISON_RUBRIC+'\n'+canonical(dict(request=case.request,assignment=assignment,target_category=target['category'],
            expected_behavior=target['expected'],holds=case.holds,ticks_per_second=case.ticks_per_second,
            windows=temporal_windows(case.holds,loop=case.loop),image_order='all A native frames, then all B native frames',
            output_fields=['preference','target_improved','material_regression','evidence','assessed_categories'])).decode()
        key=digest([case.id,'control'])
        rid,raw,receipt=self._call(case,'compare',text,images,attempt=int(key[:8],16),parents=[original_revision,candidate_sha])
        p=Provenance(provider='meta',requested_model='muse-spark-1.3',observed_model=receipt['provider'].get('observed_model'),
            rubric_sha256=digest(COMPARISON_RUBRIC),raw_sha256=hashlib.sha256(raw).hexdigest(),execution_id=rid)
        comparison=Comparison(assignment_sha256=digest(assignment),provenance=p,**extract_text(raw))
        outcome=decide(assignment,comparison,candidate_sha256=candidate_sha,target_category=target['category'],preservation_passed=True)
        mapping={'accepted':'improved','unchanged':'unchanged','rejected':'unchanged','ambiguous':'ambiguous'}
        rows=[dict(case_id=case.id,family=case.family,arm='guided_edit',outcome=mapping[guided_outcome]),
              dict(case_id=case.id,family=case.family,arm='blind_rerun',outcome='regressed' if comparison.material_regression else mapping[outcome])]
        self._save('comparisons',key+'.json',canonical(dict(rows=rows,assignment=assignment,comparison=comparison.model_dump(mode='json'))))
        return dict(rows=rows,comparison_id=key)

    def run(self):
        results={};deferred={}
        self._save('comparisons','allocation.json',canonical(controls(self.config)))
        with FileLock(str(self.folder/'coordinator.lock'),timeout=0):
            for case in self.config.cases:
                if case.stage!=self.config.phase:continue
                if self.ledger.status(self.campaign)['stopped']:break
                try:
                    results[case.id]=self.case(case)
                    gate=self.folder/'capabilities/long-sequences.json'
                    if not gate.exists():
                        evidence=[]
                        for candidate in self.config.cases:
                            if candidate.stage!=self.config.phase or len(candidate.holds)!=6:continue
                            result=self.ledger.progress(self.campaign,candidate.id)['result']
                            assessment=(result or {}).get('after_assessment') or (result or {}).get('assessment')
                            if assessment and any(c['status'] in {'present','absent_within_assessed_scope'} and c['slots'] for c in assessment['coverage']):
                                evidence.append(candidate.id)
                            if len(evidence)==2:
                                enable_long_sequences(self.root,self.campaign,evidence)
                                break
                except Stopped as exc:deferred[case.id]=str(exc)
                except Exception as exc:
                    # One malformed schema/shape stops the batch before the same
                    # paid request shape can fan out. Originals/receipts survive.
                    self.ledger.stop(self.campaign)
                    deferred[case.id]=type(exc).__name__
                    self._save('reports','failure-'+digest([case.id,type(exc).__name__])+'.json',canonical(dict(case_id=case.id,error=type(exc).__name__,detail=str(exc))))
                    break
        return dict(results=results,deferred=deferred,status=self.ledger.status(self.campaign))


from ...v2.services.errors import InvalidInput


def enable_long_sequences(root,campaign,case_ids):
    """Capability evidence must resolve to actual six-pose provider receipts."""
    ledger=Ledger(root);config=ledger.config(campaign)
    if len(set(case_ids))<2:raise ValueError('two distinct completed six-pose cases required')
    evidence=[]
    for cid in case_ids:
        spec=next((c for c in config.cases if c.id==cid),None)
        if not spec or len(spec.holds)!=6:raise ValueError('capability evidence must use six native poses')
        progress=ledger.progress(campaign,cid)
        result=progress['result']
        assessment=(result or {}).get('after_assessment') or (result or {}).get('assessment')
        if not result or result.get('outcome') not in {'accepted','unchanged','ambiguous'} or not assessment:
            raise ValueError('six-pose cases require completed assessed evidence')
        validated=Assessment.model_validate(assessment)
        if not any(c.status in {'present','absent_within_assessed_scope'} and c.slots for c in validated.coverage):
            raise ValueError('six-pose capability requires actual scoped assessment, not blanket abstention')
        project=str(local_path(root,f'campaigns/{campaign}/project'))
        rid=result.get('base_revision_id') or result.get('revision_id')
        revision=loop.revision_get(project,rid)['revision']
        if len(revision['frame_asset_ids'])!=6:raise ValueError('six native imported frames required')
        con=S.connect(project)
        try:
            from ...v2.media.canonical import load_native_image
            for aid in revision['frame_asset_ids']:
                asset,_=S.get(con,'assets',aid);raw=S.blob_path(project,asset['byte_sha256']).read_bytes()
                if S.sha256_bytes(raw)!=asset['byte_sha256']:raise ValueError('native capability evidence changed')
                load_native_image(raw)
        finally:con.close()
        with ledger.db() as db:
            requests=[dict(r) for r in db.execute("SELECT * FROM requests WHERE campaign=? AND case_id=? AND operation='generate'",(campaign,cid))]
        if not requests or any(r['state']!='received' for r in requests):raise ValueError('generation receipts unresolved')
        for r in requests:
            raw,receipt=ledger.artifact(r['id'])
            if receipt['successful_images']!=1:raise ValueError('six-pose result is not an actual generated image')
        evidence.append(dict(case_id=cid,result_sha256=digest(progress['result']),request_ids=[r['id'] for r in requests]))
    path=local_path(root,f'campaigns/{campaign}/capabilities/long-sequences.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    value=dict(config_sha256=digest(config),evidence=evidence,meaning='six-pose operation established; longer sequence attempts still require measured boundaries')
    if path.exists() and path.read_bytes()!=canonical(value):raise ValueError('capability evidence is immutable')
    path.write_bytes(canonical(value));return value
