"""Immutable derivations and transitive source policy shared by writers/exports."""
import hashlib
import io
import json

from PIL import Image
from .. import domain as D, storage as S
from ..media.canonical import canonical_pixels, pixel_sha256
from .errors import InvalidInput


def provenance_index_in(con):
    assets = {r['id']:json.loads(r['data']) for r in con.execute('SELECT id,data FROM assets')}
    jobs = {r['id']:json.loads(r['data']) for r in con.execute('SELECT id,data FROM jobs')}
    return assets, jobs


def ancestry_in(con, asset_id: str, *, index=None) -> dict:
    assets, jobs = index if index is not None else provenance_index_in(con)
    simulated = {aid for j in jobs.values() if j.get('origin') in ('simulated-transport','provider-simulated')
                 for aid in j.get('output_asset_ids',[])}
    seen, active, origins, rights, errors = set(), set(), set(), set(), []
    def walk(aid):
        if aid in active:
            errors.append('cyclic ancestry');return
        if aid in seen:return
        asset=assets.get(aid)
        if asset is None:
            errors.append(f'missing ancestor {aid}');return
        seen.add(aid);active.add(aid)
        rights.add(asset.get('rights','unknown'))
        origin=asset.get('origin','unknown')
        if aid in simulated or 'simulated' in asset.get('lineage',''):
            origin='simulated-transport'
        job=jobs.get(asset.get('source_job_id'))
        if job:origins.add(job.get('origin','unknown'))
        if asset.get('source_kind')=='procedural':origin='procedural'
        parents=asset.get('parent_asset_ids',[])
        if asset.get('source_kind')=='derived' and not parents and origin not in ('simulated-transport','procedural'):
            errors.append(f'unresolved derived ancestry {aid}')
        origins.add(origin)
        for parent in parents:walk(parent)
        active.remove(aid)
    walk(asset_id)
    return {'asset_ids':sorted(seen),'origins':sorted(origins),'rights':sorted(rights),'issues':errors}


def write_derived(project_dir: str, asset_id: str, image: Image.Image,
                  parents: list[str], operation: dict, *, operation_id: str | None = None) -> D.Asset:
    if not parents or len(parents)!=len(set(parents)):
        raise InvalidInput('derivation needs distinct stored parent assets')
    con=S.connect(project_dir)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            try:inputs=[D.Asset.model_validate(S.get(con,'assets',aid)[0]) for aid in parents]
            except KeyError as exc:raise InvalidInput(f'missing derivation input: {exc}') from exc
            for a in inputs:
                raw=S.blob_path(project_dir,a.byte_sha256).read_bytes()
                if hashlib.sha256(raw).hexdigest()!=a.byte_sha256:
                    raise InvalidInput('derivation source bytes changed')
            rights={a.rights for a in inputs}
            inherited=next(iter(rights)) if len(rights)==1 else 'mixed'
            index=provenance_index_in(con)
            origins=set(o for a in inputs for o in ancestry_in(con,a.id,index=index)['origins'])
            origin=('simulated-transport' if origins & {'simulated-transport','provider-simulated'} else
                    'procedural' if 'procedural' in origins else 'derived')
            rgba=image.convert('RGBA');buf=io.BytesIO();rgba.save(buf,format='PNG')
            asset=D.Asset(id=asset_id,byte_sha256=S.store_blob(project_dir,buf.getvalue()),
                pixel_sha256=pixel_sha256(canonical_pixels(rgba)),mime='image/png',
                width=rgba.width,height=rgba.height,source_kind='derived',rights=inherited,
                lineage=f"derived:{operation.get('operator','operation')}",
                parent_asset_ids=parents,derivation=operation,operation_id=operation_id,origin=origin)
            S.stage_identical(con,asset)
            return asset
    finally:con.close()
