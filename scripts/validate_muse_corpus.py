"""Validate an explicit local corpus manifest without generating or publishing media."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from framebound.v2 import storage as S


def validate(path):
    path=Path(path).resolve();root=path.parent
    data=json.loads(path.read_text());cases=data.get('cases',[])
    if not cases or len(cases)>96:raise ValueError('expected 1–96 corpus cases')
    if len({c['id'] for c in cases})!=len(cases):raise ValueError('duplicate case IDs')
    families={};succeeded=0
    for case in cases:
        family=case['board_id'];split=case['split']
        if family in families and families[family]!=split:raise ValueError('family crosses frozen splits')
        families[family]=split
        if case.get('status') not in {'succeeded','completed'}:continue
        from framebound.v3.corpus import _path
        receipt=json.loads(_path(root,case['receipt_file']).read_text())
        raw=_path(root,case['sheet_file']).read_bytes()
        if receipt.get('status')!='completed' or receipt.get('output_sha256')!=S.sha256_bytes(raw):raise ValueError('generation evidence differs')
        if not str(receipt.get('model_requested','')).startswith('muse-image-'):raise ValueError('Muse Image receipt required')
        if len(case['holds'])!=6 or any(type(h) is not int or h<=0 for h in case['holds']):raise ValueError('six positive holds required')
        succeeded+=1
    return dict(cases=len(cases),succeeded=succeeded,families=len(families),media_published=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('manifest')
    print(json.dumps(validate(parser.parse_args().manifest),indent=2))
