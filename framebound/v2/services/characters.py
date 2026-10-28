"""Immutable character proposals shared by model transports and review."""
from .. import domain as D, storage as S
from .errors import InvalidInput


def propose_character(project_dir: str, proposal: dict) -> D.ResultEnvelope:
    try:
        char = D.CharacterRevision.model_validate(proposal)
    except ValueError as exc:
        raise InvalidInput(f'character invalid: {exc}') from exc
    con = S.connect(project_dir)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            try:
                S.get(con, 'projects', char.project_id)
            except KeyError as exc:
                raise InvalidInput('character project is not stored') from exc
            if set(char.identity_asset_ids) & set(char.style_asset_ids):
                raise InvalidInput('identity and style need distinct assets')
            for aid in [*char.identity_asset_ids, *char.style_asset_ids]:
                try:
                    asset = D.Asset.model_validate(S.get(con, 'assets', aid)[0])
                except KeyError as exc:
                    raise InvalidInput(f'unknown reference asset {aid}') from exc
                if not S.blob_path(project_dir, asset.byte_sha256).is_file():
                    raise InvalidInput(f'reference bytes missing: {aid}')
                if asset.rights == 'unknown':
                    raise InvalidInput(f'reference rights unresolved: {aid}')
            S.stage_identical(con, char)
    finally:
        con.close()
    return D.ResultEnvelope(ok=True, operation_id=f'op-character-{char.id}',
                            revision_id=char.id, next_actions=['guide_propose'])
