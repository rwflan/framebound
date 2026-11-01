"""Single local authority for frozen requests, spend and one-use send permits.

No remote worker writes this database. A wire-started request is never retried;
reconciliation requires a receipt, including when the process died before I/O.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import sqlite3
import time

from .contracts import Campaign, canonical, digest, freeze, local_path, parse_campaign


class Stopped(ValueError):
    pass


class Ledger:
    def __init__(self, root):
        self.root = Path(root).resolve()
        path = local_path(root, 'campaigns/lifetime.sqlite3')
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.db() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS knowledge_releases(campaign TEXT, stage TEXT, cases TEXT NOT NULL,
                    evidence TEXT NOT NULL, request TEXT NOT NULL, PRIMARY KEY(campaign,stage));
                CREATE TABLE IF NOT EXISTS campaigns(id TEXT PRIMARY KEY, config TEXT NOT NULL, stopped INTEGER NOT NULL DEFAULT 0,
                    api_funding INTEGER NOT NULL DEFAULT 0, modal_funding INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS cases(campaign TEXT, id TEXT, family TEXT, state TEXT NOT NULL DEFAULT 'planned',
                    active_seconds REAL NOT NULL DEFAULT 0, result TEXT, PRIMARY KEY(campaign,id));
                CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, campaign TEXT, case_id TEXT, operation TEXT,
                    binding TEXT UNIQUE NOT NULL, request TEXT NOT NULL, subsystem TEXT NOT NULL,
                    reserved INTEGER NOT NULL, incurred INTEGER, images INTEGER NOT NULL,
                    state TEXT NOT NULL, permit TEXT, lease_until REAL, receipt TEXT, outcome TEXT);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, request_id TEXT, kind TEXT, at REAL, data TEXT);
            ''')
            if 'progress' not in {r[1] for r in db.execute('PRAGMA table_info(cases)')}:
                db.execute("ALTER TABLE cases ADD COLUMN progress TEXT NOT NULL DEFAULT '{}'")

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def plan(self, config: Campaign):
        result = freeze(self.root, config)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            registry={}
            for stored in db.execute('SELECT config FROM campaigns'):
                previous=parse_campaign(stored[0])
                for case in previous.cases:
                    for family in [case.family,*case.ancestry]:registry[family]=case.split
            for case in config.cases:
                for family in [case.family,*case.ancestry]:
                    if family in registry and registry[family]!=case.split:
                        raise ValueError('lifetime family/reference ancestry crosses splits')
            old = db.execute('SELECT config FROM campaigns WHERE id=?', (config.id,)).fetchone()
            if old and old['config'].encode() != canonical(config):
                raise ValueError('campaign config changed')
            db.execute('INSERT OR IGNORE INTO campaigns(id,config) VALUES(?,?)', (config.id, canonical(config).decode()))
            db.executemany('INSERT OR IGNORE INTO cases(campaign,id,family) VALUES(?,?,?)', [(config.id,c.id,c.family) for c in config.cases])
        folder = local_path(self.root, f'campaigns/{config.id}')
        artifacts = {'curriculum.jsonl': b''.join(canonical(c)+b'\n' for c in config.cases),
                     'families.json': canonical({c.family:dict(split=c.split,ancestry=c.ancestry) for c in config.cases})}
        for name,raw in artifacts.items():
            path=folder/name
            if path.exists() and path.read_bytes()!=raw: raise ValueError('frozen curriculum/registry differs')
            if not path.exists(): path.write_bytes(raw)
        return result

    def config(self, campaign):
        with self.db() as db:
            row = db.execute('SELECT config FROM campaigns WHERE id=?', (campaign,)).fetchone()
        if not row:
            raise ValueError('unknown campaign')
        return parse_campaign(row['config'])

    def fund(self, campaign, subsystem, microdollars, *, evidence):
        """Explicit allocation, never an implicit side effect of plan/run/resume."""
        if subsystem not in {'api', 'modal'} or type(microdollars) is not int or microdollars < 0:
            raise ValueError('invalid funding')
        config = self.config(campaign)
        if not evidence:
            raise ValueError('verified prices and account/access evidence required before funding')
        credit=None
        if config.schema_version=='2.0':
            from datetime import datetime,timezone,timedelta
            if not isinstance(evidence,dict):raise ValueError('v2 requires structured current price/account evidence')
            verified=datetime.fromisoformat(evidence['verified_at'])
            now=datetime.now(timezone.utc)
            if verified.tzinfo is None or not now-timedelta(hours=24)<=verified<=now:
                raise ValueError('funding evidence must be verified within 24 hours')
            if not evidence.get('source') or not evidence.get('account_access'):
                raise ValueError('price source and account/access evidence required')
            if subsystem=='api':
                if evidence.get('image_microdollars')!=config.prices.image_microdollars:
                    raise ValueError('verified image price differs from frozen quote; create a new campaign version')
            else:
                from .compute_gate import CreditEvidence
                credit=CreditEvidence.model_validate(evidence['credit'])
        elif not config.prices.verified_at:
            raise ValueError('verified prices and account/access evidence required before funding')
        if microdollars > getattr(config, subsystem + '_ceiling'):
            raise ValueError('allocation exceeds frozen release ceiling')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            committed=db.execute('SELECT COALESCE(SUM(COALESCE(incurred,reserved)),0) FROM requests WHERE campaign=? AND subsystem=?',(campaign,subsystem)).fetchone()[0]
            if microdollars<committed: raise ValueError('funding cannot erase existing spend/reservations')
            if credit is not None:
                from .compute_gate import credit_capacity
                if microdollars-committed>credit_capacity(credit):raise ValueError('allocation exceeds verified applicable credit or workspace usage capacity')
            db.execute(f'UPDATE campaigns SET {subsystem}_funding=? WHERE id=?', (microdollars, campaign))
            self._event(db, None, 'funding', dict(campaign=campaign, subsystem=subsystem, allocation=microdollars, evidence=evidence))

    def _event(self, db, request_id, kind, data):
        db.execute('INSERT INTO events(request_id,kind,at,data) VALUES(?,?,?,?)', (request_id, kind, time.time(), canonical(data).decode()))

    def reserve(self, campaign, case_id, operation, payload, *, quote, images=0, subsystem='api', attempt=0, parents=(), sheet=0):
        if type(quote) is not int or quote < 0 or type(images) is not int or images < 0 or subsystem not in {'api','modal'}:
            raise ValueError('nonnegative integer resource quote required')
        if operation not in {'anchor','generate','diagnose','recheck','repair','blind_rerun','compare','train','evaluate'}:
            raise ValueError('unsupported operation')
        config = self.config(campaign)
        spec = next((c for c in config.cases if c.id == case_id), None)
        if spec is None:
            raise ValueError('unknown case')
        from .progression import admitted
        if case_id not in admitted(self,config):
            raise Stopped('case is not in this release; final-test cases remain sealed')
        if type(attempt) is not int or type(sheet) is not int or not 0 <= sheet < config.limits.sheets:
            raise ValueError('bounded integer attempt and sheet required')
        if operation in {'anchor','generate','repair','blind_rerun'} and images<1:
            raise ValueError('image operations require quoted output images')
        if operation in {'anchor','blind_rerun','recheck'} and attempt != 0:
            raise Stopped('anchor, matched control or uncertainty recheck cannot be replenished')
        if attempt < 0 or (operation == 'repair' and attempt >= config.limits.repairs):
            raise Stopped('repair attempt limit')
        if images > config.limits.sheets:
            raise Stopped('sheet limit')
        if images and (quote < images * config.prices.image_microdollars or subsystem != 'api'):
            raise ValueError('image quote below frozen price')
        request = dict(campaign=campaign, family=spec.family, case_id=case_id, operation=operation, attempt=attempt,
                       parents=list(parents), sheet=sheet, payload=payload, quote=quote, images=images, subsystem=subsystem,
                       config_sha256=digest(config))
        rid = digest(request)
        # A changed prompt or model cannot create a new send for the same attempt.
        binding = digest([campaign, case_id, operation, attempt, sheet])
        self._disk(config)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM requests WHERE binding=?', (binding,)).fetchone()
            if old:
                if old['id'] != rid:
                    raise Stopped('attempt is already frozen; reconcile it before changing request shape')
                return dict(old)
            campaign_row = db.execute('SELECT * FROM campaigns WHERE id=?', (campaign,)).fetchone()
            case = db.execute('SELECT * FROM cases WHERE campaign=? AND id=?', (campaign,case_id)).fetchone()
            unknown = db.execute("SELECT 1 FROM requests r JOIN cases c ON c.campaign=r.campaign AND c.id=r.case_id WHERE c.family=? AND r.state IN ('wire_started','unknown_provider_outcome')", (spec.family,)).fetchone()
            if case_id not in admitted(self,config,db):
                raise Stopped('case is not in this release')
            if subsystem=='modal':
                from .remote import Job
                job=Job.model_validate(payload['job'])
                seconds=job.seconds+job.startup_seconds+job.replay_seconds
                booked=0
                stage_cost=0
                for prior in db.execute("SELECT request,incurred,reserved FROM requests WHERE subsystem='modal' AND state!='cancelled'"):
                    prior_job=Job.model_validate(json.loads(prior[0])['payload']['job'])
                    booked+=prior_job.seconds+prior_job.startup_seconds+prior_job.replay_seconds
                    if prior_job.purpose==job.purpose:stage_cost+=prior['incurred'] if prior['incurred'] is not None else prior['reserved']
                if stage_cost+quote>{'profile':1000000,'train':3000000,'reproduce':2000000}[job.purpose]:
                    raise Stopped('Modal experiment-stage allocation exhausted; reserve remains unallocated')
                if booked+seconds>config.limits.modal_seconds:
                    raise Stopped('lifetime Modal wall allowance exhausted, including unresolved reservations')
            if operation=='anchor' and db.execute("SELECT 1 FROM requests r JOIN cases c ON c.campaign=r.campaign AND c.id=r.case_id WHERE c.family=? AND r.operation='anchor' AND r.state!='cancelled'",(spec.family,)).fetchone():
                raise Stopped('identity anchor already has a frozen lifetime request; reuse or reconcile it')
            if campaign_row['stopped'] or unknown or case['active_seconds'] >= config.limits.active_seconds:
                raise Stopped('stopped, unknown family outcome or active processing ceiling')
            if subsystem!='modal' and case['state'] in {'accepted','unchanged','rejected','ambiguous','exhausted'}:
                raise Stopped('case already has a durable terminal result')
            total = db.execute('SELECT COALESCE(SUM(COALESCE(incurred,reserved)),0) FROM requests WHERE campaign=? AND subsystem=?', (campaign,subsystem)).fetchone()[0]
            lifetime = db.execute('SELECT COALESCE(SUM(COALESCE(incurred,reserved)),0) FROM requests WHERE subsystem=?', (subsystem,)).fetchone()[0]
            if total + quote > campaign_row[subsystem+'_funding']:
                raise Stopped('unfunded or release budget exhausted')
            if lifetime + quote > (125000000 if subsystem == 'api' else 100000000):
                raise Stopped('lifetime spending ceiling, including unresolved reservations')
            successful = db.execute("SELECT COALESCE(SUM(CASE WHEN receipt IS NOT NULL THEN json_extract(receipt,'$.successful_images') ELSE images END),0) FROM requests WHERE state!='cancelled'").fetchone()[0]
            attempts = db.execute("SELECT COALESCE(SUM(images),0) FROM requests WHERE state!='cancelled'").fetchone()[0]
            if successful + images > config.limits.successful_images or attempts + images > config.limits.dispatch_attempts:
                raise Stopped('lifetime image/dispatch ceiling')
            db.execute('INSERT INTO requests(id,campaign,case_id,operation,binding,request,subsystem,reserved,images,state) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (rid,campaign,case_id,operation,binding,canonical(request).decode(),subsystem,quote,images,'reserved'))
            if subsystem!='modal':
                db.execute("UPDATE cases SET state='budget_reserved' WHERE campaign=? AND id=?", (campaign,case_id))
            self._event(db,rid,'reserved',request)
            return dict(db.execute('SELECT * FROM requests WHERE id=?', (rid,)).fetchone())

    def claim(self, rid):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM requests WHERE id=?', (rid,)).fetchone()
            if not row:
                raise ValueError('unknown request')
            campaign = db.execute('SELECT stopped FROM campaigns WHERE id=?',(row['campaign'],)).fetchone()
            if campaign['stopped'] or row['state'] != 'reserved' or (row['lease_until'] or 0) > time.time():
                raise Stopped('request stopped, claimed or already sent')
            permit = secrets.token_hex(32)
            db.execute('UPDATE requests SET permit=?,lease_until=? WHERE id=?', (permit,time.time()+180,rid))
            return permit

    def start_wire(self, rid, permit):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM requests WHERE id=?', (rid,)).fetchone()
            if not row or row['state'] != 'reserved' or row['permit'] != permit or row['lease_until'] < time.time():
                raise Stopped('send permit already consumed, expired or invalid')
            if db.execute('SELECT stopped FROM campaigns WHERE id=?',(row['campaign'],)).fetchone()[0]:
                raise Stopped('campaign stopped')
            config = parse_campaign(db.execute('SELECT config FROM campaigns WHERE id=?',(row['campaign'],)).fetchone()[0])
            lane = "images>0" if row['images'] else "images=0 AND subsystem='api'" if row['subsystem']=='api' else "subsystem='modal'"
            limit = config.limits.generation_workers if row['images'] else config.limits.assessment_workers if row['subsystem']=='api' else config.limits.modal_workers
            if db.execute(f"SELECT COUNT(*) FROM requests WHERE state IN ('wire_started','unknown_provider_outcome') AND {lane}").fetchone()[0]>=limit:
                raise Stopped('configured concurrency ceiling')
            db.execute("UPDATE requests SET state='wire_started', permit=NULL WHERE id=?", (rid,))
            self._event(db,rid,'wire_started',{})
            return json.loads(row['request'])

    def receive(self, rid, raw: bytes, *, incurred, successful_images=0, provider_receipt):
        if type(incurred) is not int or incurred < 0 or type(successful_images) is not int or successful_images < 0 or not provider_receipt:
            raise ValueError('actual costs, successful images and provider evidence required')
        sha = hashlib.sha256(raw).hexdigest()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone()
            if not row or row['state'] not in {'wire_started','unknown_provider_outcome','received'}:
                raise Stopped('request has no possibly accepted send')
            receipt = dict(sha256=sha, incurred=incurred, successful_images=successful_images, provider=provider_receipt)
            if row['receipt']:
                if row['receipt'] != canonical(receipt).decode():
                    raise ValueError('immutable provider receipt differs')
                return receipt
            artifact = local_path(self.root, f"campaigns/{row['campaign']}/originals/{sha}")
            artifact.parent.mkdir(parents=True, exist_ok=True)
            if artifact.exists() and hashlib.sha256(artifact.read_bytes()).hexdigest() != sha:
                raise ValueError('content-addressed artifact was modified')
            if not artifact.exists():
                with artifact.open('xb') as stream:
                    stream.write(raw)
                    stream.flush()
                    import os
                    os.fsync(stream.fileno())
            # Unquoted excess still counts as actual spend and halts admission.
            db.execute("UPDATE requests SET state='received',incurred=?,receipt=? WHERE id=?", (incurred,canonical(receipt).decode(),rid))
            if incurred > row['reserved'] or successful_images > row['images']:
                db.execute('UPDATE campaigns SET stopped=1 WHERE id=?', (row['campaign'],))
            self._event(db,rid,'received',receipt)
        return receipt

    def unknown(self, rid, reason):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE requests SET state='unknown_provider_outcome',outcome=? WHERE id=? AND state='wire_started'", (reason,rid))
            self._event(db,rid,'unknown',dict(reason=reason))

    def cancel_reserved(self, rid, reason):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("UPDATE requests SET state='cancelled',incurred=0,permit=NULL WHERE id=? AND state='reserved'",(rid,)).rowcount
            if not changed:
                raise Stopped('possibly accepted sends require provider reconciliation')
            self._event(db,rid,'cancelled',dict(reason=reason))

    def stop(self, campaign):
        with self.db() as db:
            db.execute('UPDATE campaigns SET stopped=1 WHERE id=?',(campaign,))
        return self.status(campaign)

    def resume(self, campaign):
        # In-flight records and reservations remain intact. Never infer nonacceptance.
        with self.db() as db:
            db.execute('UPDATE campaigns SET stopped=0 WHERE id=?',(campaign,))
            db.execute("UPDATE requests SET state='unknown_provider_outcome' WHERE campaign=? AND state='wire_started' AND lease_until<?",(campaign,time.time()))
        return self.status(campaign)

    def finish_case(self, campaign, case_id, state, evidence):
        if state not in {'accepted','unchanged','rejected','ambiguous','exhausted'} or not evidence:
            raise ValueError('terminal result requires evidence')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            pending = db.execute("SELECT 1 FROM requests WHERE campaign=? AND case_id=? AND state IN ('reserved','wire_started','unknown_provider_outcome')", (campaign,case_id)).fetchone()
            if pending:
                raise Stopped('pending requests must retain their reservation and blocked status')
            row = db.execute('SELECT state,result FROM cases WHERE campaign=? AND id=?',(campaign,case_id)).fetchone()
            if not row:
                raise ValueError('unknown case')
            result = canonical(evidence).decode()
            if row['result'] and (row['state'] != state or row['result'] != result):
                raise ValueError('terminal evidence is immutable')
            db.execute('UPDATE cases SET state=?,result=? WHERE campaign=? AND id=?',(state,result,campaign,case_id))

    def add_active_time(self, campaign, case_id, seconds):
        if seconds < 0:
            raise ValueError('elapsed time cannot be negative')
        with self.db() as db:
            db.execute('UPDATE cases SET active_seconds=active_seconds+? WHERE campaign=? AND id=?',(seconds,campaign,case_id))

    def _disk(self, config):
        used = sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file() and not p.is_symlink())
        if used >= config.limits.disk_bytes or shutil.disk_usage(self.root).free < 1024**3:
            raise Stopped('disk quota/free-space guard; originals are preserved')

    def status(self, campaign):
        self.config(campaign)
        with self.db() as db:
            states = {r[0]:r[1] for r in db.execute('SELECT state,COUNT(*) FROM cases WHERE campaign=? GROUP BY state',(campaign,))}
            requests = [dict(r) for r in db.execute('SELECT id,case_id,operation,state,reserved,incurred,receipt FROM requests WHERE campaign=?',(campaign,))]
            budgets = {s:dict(incurred=sum(r['incurred'] or 0 for r in db.execute('SELECT incurred FROM requests WHERE campaign=? AND subsystem=?',(campaign,s))),
                reserved=db.execute('SELECT COALESCE(SUM(reserved),0) FROM requests WHERE campaign=? AND subsystem=? AND incurred IS NULL',(campaign,s)).fetchone()[0]) for s in ('api','modal')}
            stopped = bool(db.execute('SELECT stopped FROM campaigns WHERE id=?',(campaign,)).fetchone()[0])
        return dict(campaign=campaign, stopped=stopped, cases=states, budgets=budgets, requests=requests)

    def progress(self, campaign, case_id, *, state=None, data=None):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM cases WHERE campaign=? AND id=?',(campaign,case_id)).fetchone()
            if not row: raise ValueError('unknown case')
            if state is not None:
                if row['result']: raise Stopped('terminal case cannot be rewritten')
                if state not in {'planned','budget_reserved','generating','generated','canonicalized','measured','semantically_assessed','diagnosis_ready','repair_queued','repair_generated','remeasured','compared','unknown_provider_outcome'}:
                    raise ValueError('unsupported lifecycle transition')
                db.execute('UPDATE cases SET state=?,progress=? WHERE campaign=? AND id=?',(state,canonical(data or {}).decode(),campaign,case_id))
            else: return dict(state=row['state'],active_seconds=row['active_seconds'],data=json.loads(row['progress']),result=json.loads(row['result']) if row['result'] else None)

    def request(self, rid):
        with self.db() as db:
            row=db.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone()
            if not row: raise ValueError('unknown request')
            return dict(row)

    def artifact(self, rid):
        row=self.request(rid)
        if row['state']!='received' or not row['receipt']: raise Stopped('request result not received; reconcile before resuming')
        receipt=json.loads(row['receipt'])
        path=local_path(self.root,f"campaigns/{row['campaign']}/originals/{receipt['sha256']}")
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=receipt['sha256']: raise ValueError('received artifact was modified')
        return raw,receipt
