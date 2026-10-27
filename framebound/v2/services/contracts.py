from __future__ import annotations

from .. import domain as D
from .. import storage as S
from .errors import InvalidInput


def propose_contract(project_dir: str, contract_dict: dict) -> D.ResultEnvelope:
    try:
        contract = D.ClipContractRevision.model_validate(contract_dict)
    except Exception as e:
        raise InvalidInput(f"contract invalid: {e}") from e
    from ..checks import params as _params
    _params.validate_contract_constraints(contract, contract.canvas.width, contract.canvas.height)
    con = S.connect(project_dir)
    try:
        # authority check: referenced assets must exist
        missing = []
        for role in ("identity", "style"):
            aid = contract.references.get(role)
            if aid and con.execute("SELECT id FROM assets WHERE id=?", (aid,)).fetchone() is None:
                missing.append(f"{role}:{aid}")
        S.insert(con, contract)
    finally:
        con.close()
    issues = ([{"code": "missing_reference_authority", "scope": m} for m in missing])
    next_actions = ["clip_create_revision"] if not missing else ["asset_import"]
    return D.ResultEnvelope(ok=True, operation_id=f"op-contract-{contract.id}", revision_id=contract.id,
                            technical_status=D.TechnicalStatus.INCOMPLETE,
                            coverage={"required_total": len(contract.constraints),
                                      "required_measured": 0},
                            issues=issues, next_actions=next_actions)
