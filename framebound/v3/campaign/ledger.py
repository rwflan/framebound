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

from .contracts import Campaign, canonical, digest, freeze, local_path


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
            old = db.execute('SELECT config FROM campaigns WHERE id=?', (config.id,)).fetchone()
            if old and old['config'].encode() != canonical(config):
                raise ValueError('campaign config changed')
            db.execute('INSERT OR IGNORE INTO campaigns(id,config) VALUES(?,?)', (config.id, canonical(config).decode()))
            db.executemany('INSERT OR IGNORE INTO cases(campaign,id,family) VALUES(?,?,?)', [(config.id,c.id,c.family) for c in config.cases])
        return result

    def config(self, campaign):
        with self.db() as db:
            row = db.execute('SELECT config FROM campaigns WHERE id=?', (campaign,)).fetchone()
        if not row:
            raise ValueError('unknown campaign')
        return Campaign.model_validate_json(row['config'])

    def fund(self, campaign, subsystem, microdollars, *, evidence):
        """Explicit allocation, never an implicit side effect of plan/run/resume."""
        if subsystem not in {'api', 'modal'} or type(microdollars) is not int or microdollars < 0:
            raise ValueError('invalid funding')
        config = self.config(campaign)
        if not evidence or not config.prices.verified_at:
            raise ValueError('verified prices and account/access evidence required before funding')
        if microdollars > getattr(config, subsystem + '_ceiling'):
            raise ValueError('allocation exceeds frozen release ceiling')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute(f'UPDATE campaigns SET {subsystem}_funding=? WHERE id=?', (microdollars, campaign))
            self._event(db, None, 'funding', dict(campaign=campaign, subsystem=subsystem, allocation=microdollars, evidence=evidence))

    def _event(self, db, request_id, kind, data):
        db.execute('INSERT INTO events(request_id,kind,at,data) VALUES(?,?,?,?)', (request_id, kind, time.time(), canonical(data).decode()))

    def reserve(self, campaign, case_id, operation, payload, *, quote, images=0, subsystem='api', attempt=0, parents=()):
        if type(quote) is not int or quote < 0 or type(images) is not int or images < 0 or subsystem not in {'api','modal'}:
            raise ValueError('nonnegative integer resource quote required')
        if operation not in {'anchor','generate','diagnose','recheck','repair','blind_rerun','compare','train','evaluate'}:
            raise ValueError('unsupported operation')
        config = self.config(campaign)
        spec = next((c for c in config.cases if c.id == case_id), None)
        if spec is None:
            raise ValueError('unknown case')
        if spec.stage != config.phase:
            raise Stopped('case is not in this release; final-test cases remain sealed')
        if attempt < 0 or (operation == 'repair' and attempt >= config.limits.repairs):
            raise Stopped('repair attempt limit')
        if images > config.limits.sheets:
            raise Stopped('sheet limit')
        if images and (quote < images * config.prices.image_microdollars or subsystem != 'api'):
            raise ValueError('image quote below frozen price')
        request = dict(campaign=campaign, family=spec.family, case_id=case_id, operation=operation, attempt=attempt,
                       parents=list(parents), payload=payload, quote=quote, images=images, subsystem=subsystem,
                       config_sha256=digest(config))
        rid = digest(request)
        # A changed prompt or model cannot create a new send for the same attempt.
        binding = digest([campaign, case_id, operation, attempt])
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
            if campaign_row['stopped'] or unknown or case['active_seconds'] >= config.limits.active_seconds:
                raise Stopped('stopped, unknown family outcome or active processing ceiling')
            if case['state'] in {'accepted','unchanged','rejected','ambiguous','exhausted'}:
                raise Stopped('case already has a durable terminal result')
            total = db.execute('SELECT COALESCE(SUM(COALESCE(incurred,reserved)),0) FROM requests WHERE campaign=? AND subsystem=?', (campaign,subsystem)).fetchone()[0]
            lifetime = db.execute('SELECT COALESCE(SUM(COALESCE(incurred,reserved)),0) FROM requests WHERE subsystem=?', (subsystem,)).fetchone()[0]
            if total + quote > campaign_row[subsystem+'_funding']:
                raise Stopped('unfunded or release budget exhausted')
            if lifetime + quote > (125000000 if subsystem == 'api' else 100000000):
                raise Stopped('lifetime spending ceiling, including unresolved reservations')
            counts = db.execute("SELECT COALESCE(SUM(images),0), COUNT(*) FROM requests WHERE images>0").fetchone()
            attempts = db.execute('SELECT COALESCE(SUM(images),0) FROM requests WHERE images>0').fetchone()[0]
            if counts[0] + images > config.limits.successful_images or attempts + images > config.limits.dispatch_attempts:
                raise Stopped('lifetime image/dispatch ceiling')
            db.execute('INSERT INTO requests(id,campaign,case_id,operation,binding,request,subsystem,reserved,images,state) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (rid,campaign,case_id,operation,binding,canonical(request).decode(),subsystem,quote,images,'reserved'))
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
            if successful_images > row['images']:
                raise ValueError('provider image count exceeds request')
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
            if incurred > row['reserved']:
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
