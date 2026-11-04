"""Receipt-derived experiment accounting; retained failed work is never reset.

Private paths, prompts, artwork and response IDs stay in the private ledger.
The public summary contains only amounts, counts and evidence hashes.
"""
import hashlib
import json
from pathlib import Path


def amount(value):
    if type(value) is not int or value<0:raise ValueError('Cost must be nonnegative integer microdollars')
    return value


def summarize(roots, *, cache=None):
    cache={} if cache is None else cache
    def retained(path,kind):
        stat=path.stat();key=(str(path),kind)
        signature=(stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
        old=cache.get(key)
        if old and old[0]==signature:return old[1]
        raw=path.read_bytes()
        value=json.loads(raw) if kind=='json' else hashlib.sha256(raw).hexdigest()
        cache[key]=(signature,value)
        return value
    rows=[];seen={};missing=[]
    for root in dict.fromkeys(str(Path(r).resolve()) for r in roots):
        base=Path(root)
        if not base.is_dir():missing.append(root);continue
        for marker in sorted(base.glob('private/**/request.json')):
            request=retained(marker,'json');receipt_path=marker.with_name('receipt.json');response=marker.with_name('response.json')
            quote=request.get('committed_microdollars',request.get('quote'))
            if quote is None:raise ValueError('Request lacks a frozen commitment')
            quote=amount(quote)
            wire=request.get('wire',request.get('payload',{}).get('wire',{}));model=wire.get('model','unknown')
            initial=marker.parent.name.endswith('-initial') and model=='muse-image-1.0'
            group='shared_initial' if initial else 'framework_work'
            row=dict(operation=str(marker.parent),model=model,group=group,committed_microdollars=quote,
                     request_sha256=retained(marker,'sha256'))
            if receipt_path.exists():
                receipt=retained(receipt_path,'json');meta=receipt.get('receipt',{})
                incurred=amount(receipt.get('incurred_microdollars',receipt.get('incurred')))
                response_id=meta.get('response_id');sha=retained(response,'sha256') if response.exists() else None
                if receipt.get('response_sha256') and receipt['response_sha256']!=sha:raise ValueError('Receipt response digest mismatch')
                key=('response',response_id) if response_id else ('response_digest',sha) if sha else ('receipt_path',str(receipt_path))
                fingerprint=(incurred,meta.get('requested_model',model),sha)
                if key in seen:
                    if seen[key]!=fingerprint:raise ValueError('Conflicting copied provider receipt')
                    continue
                seen[key]=fingerprint
                exact=meta.get('cost_basis')=='provider usage and frozen rate'
                row.update(status='observed' if exact else 'unreconciled',observed_microdollars=incurred if exact else 0,
                           reserved_microdollars=0 if exact else max(quote,incurred),response_id=response_id,
                           receipt_sha256=retained(receipt_path,'sha256'))
            else:
                row.update(status='unreconciled',observed_microdollars=0,reserved_microdollars=quote,
                           reason='Retained response without cost receipt' if response.exists() else 'Acceptance/result not reconciled; never retry from this accounting state')
            rows.append(row)
    observed=sum(r['observed_microdollars'] for r in rows);reserved=sum(r['reserved_microdollars'] for r in rows)
    summary=dict(currency='USD',observed_microdollars=observed,unreconciled_reserve_microdollars=reserved,
                 total_with_reserve_microdollars=observed+reserved,operations=len(rows),
                 unreconciled_operations=sum(r['status']=='unreconciled' for r in rows),missing_lineage_roots=len(missing),
                 scope='All retained shared initial generations plus framework generation, assessment, repair and failed/superseded attempts in the declared lineage. Local CPU and external unrecorded services are not priced.',
                 groups={name:dict(observed_microdollars=sum(r['observed_microdollars'] for r in rows if r['group']==name),
                                  unreconciled_reserve_microdollars=sum(r['reserved_microdollars'] for r in rows if r['group']==name),operations=sum(r['group']==name for r in rows)) for name in ('shared_initial','framework_work')})
    summary['ledger_sha256']=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
    return dict(summary=summary,operations=rows,missing_roots=missing)
