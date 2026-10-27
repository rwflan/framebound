from __future__ import annotations

from .. import domain as D
from .. import storage as S
from ..media.canonical import import_asset as _import
from .errors import InvalidInput


def import_asset(project_dir: str, src: str, asset_id: str, source_kind: str = "original",
                 rights: str = "original", eligible_roles: list[str] | None = None) -> D.ResultEnvelope:
    con = S.connect(project_dir)
    try:
        asset = _import(project_dir, src, asset_id=asset_id, source_kind=source_kind,
                        rights=rights, eligible_roles=eligible_roles)
        S.insert(con, asset)
    except ValueError as e:
        raise InvalidInput(str(e)) from e
    finally:
        con.close()
    return D.ResultEnvelope(ok=True, operation_id=f"op-import-{asset_id}", revision_id=asset_id,
                            artifacts=[{"id": asset_id, "role": "asset",
                                        "byte_sha256": asset.byte_sha256}],
                            next_actions=["contract_propose"])
