'Track output directories and check their computation metadata.'
import contextlib
from pathlib import Path
from contract_io import ContractError, _canonical, _identity, _snapshot, _json

@contextlib.contextmanager
def _producer(a,code,root,*,read_ids=(),sealed_reads=False,outputs=(),opaque=False):
    if a._native_scope is not None:raise ContractError('Nested native producer scope')
    a.verify_code(code['path'])
    root=_canonical(root,a.project)
    if root in {a.d,a.project,a.q}:raise ContractError('Overbroad output root')
    reads={}
    with a._validation():
        for row in read_ids:
            _snapshot(row,a.project);reads[row['path']]=row
    for raw in outputs:_canonical(raw,root)
    scope=dict(code=code,root=root,reads=reads,sealed_reads=sealed_reads,
               outputs=set(outputs),written=set(),opaque=opaque,observed={})
    a._native_scope=scope
    try:
        yield scope
        a.verify_code(code['path'])
        with a._validation():
            for row in reads.values():_snapshot(row,a.project)
    except BaseException:
        a._official_ready=None;a.revoke_ap_route();raise
    finally:a._native_scope=None

def _read(a,p):
    scope=a._native_scope
    if scope is None:return False
    with a._validation():
        a.verify_code(scope['code']['path'])
        key=str(_canonical(p,a.project))
        row=scope['reads'].get(key)
        if row is None and scope['sealed_reads']:row=a._verified_files.get(key)
        if row is not None:
            _snapshot(row,a.project);return True
        if p.is_relative_to(scope['root']) and (not scope['outputs'] or key in scope['outputs']):
            if key not in scope['written']:raise ContractError('Pre-existing unverified producer output')
            if scope['opaque']:raise ContractError('Opaque callback cannot decode producer payload')
            row=_identity(p,scope['root'])
            previous=scope['observed'].setdefault(key,row)
            if previous!=row:raise ContractError('In-flight producer self-check drift')
            return True
    raise ContractError('Native scope read outside exact controls/sealed inputs/own outputs')

def _write(a,p,*,directory=False):
    scope=a._native_scope
    if scope is None:return False


    if directory and scope['root'].is_relative_to(p) and p.is_dir():
        _canonical(p,a.project)
        return True
    _canonical(p,scope['root'])
    with a._validation():a.verify_code(scope['code']['path'])
    if directory:
        if scope['outputs'] and not any(Path(x).parent.is_relative_to(p) for x in scope['outputs']):
            raise ContractError('Undeclared producer directory')
        return True
    if scope['outputs'] and str(p) not in scope['outputs']:

        temporary=any(p.parent==Path(x).parent and p.name.startswith(Path(x).name+'.') and p.name.endswith('.tmp') for x in scope['outputs'])
        if not temporary:raise ContractError('Undeclared producer output')
    scope['written'].add(str(p));scope['observed'].pop(str(p),None);return True

def _complete(a,root,receipt_id,*,state,seal_sha256,marker=None):
    root=_canonical(root,a.project);receipt=_json(_snapshot(receipt_id,root))
    if receipt.get('state')!=state or receipt.get('seal_sha256')!=seal_sha256:
        raise ContractError('Producer completion state/seal drift')
    if marker is not None and receipt.get('evaluation_view')!=marker:raise ContractError('Wrong R2 view')
    if marker is None and 'evaluation_view' in receipt:raise ContractError('Original receipt relabelled R2')
    rows=receipt.get('files')
    if not isinstance(rows,list) or len(rows)!=len({r['path'] for r in rows}):raise ContractError('Duplicate/omitted receipt members')
    for row in rows:_snapshot(row,root)
    actual={str(_canonical(p,root,regular=True)) for p in root.iterdir()}
    if actual!={r['path'] for r in rows}|{receipt_id['path']}:raise ContractError('Unsealed extra/missing producer outputs')
    report=root/'SCORE_REPORT.json';bound=next((r for r in rows if r['path']==str(report)),None)
    if bound is None:raise ContractError('Official report unbound')
    return dict(seal=None,score_receipt=receipt_id,score_report=bound,files=rows)
