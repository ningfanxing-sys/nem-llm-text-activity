'Resolve source identities from saved computation records.'
import copy
from pathlib import Path
from contract_io import ContractError,_snapshot,_json,_identity,_canonical

def _wire(a):
    with a._validation():
        source=copy.deepcopy(a._scorer_contract)
        parent=_json(_snapshot(a._verified_files[str(a.d/'state/SEAL_BATCH.json')],a.d))['conf_seal']
        _snapshot(parent,a.project)
        original=source['original'];r2=source['r2']
        if original.get('seal_path',parent['path'])!=parent['path'] or original.get('seal_identity') not in (None,parent):
            raise ContractError('Original seal source association drift')
        for wire in (original,r2):
            if wire.get('seal_identity') not in (None,parent):raise ContractError('Wrong scorer seal')
            wire['seal_identity']=parent
        bridge=copy.deepcopy(r2['state_seal_association'])
        if bridge.get('seal_path',parent['path'])!=parent['path'] or bridge.get('seal_identity') not in (None,parent):raise ContractError('Wrong fresh-state seal bridge')
        bridge['seal_identity']=parent;r2['state_seal_association']=bridge
        for view in ('original','r2'):
            wire=source[view];root=_canonical(wire['state_root'],a.project)
            if wire['receipt_path']!=str(root/'scored/SCORE_RECEIPT.json') or wire['report_path']!=str(root/'scored/SCORE_REPORT.json'):raise ContractError('Runtime path differs from finite source contract')
    return source

def _permit(a,wire,item):
    with a._validation():
        expected=wire.get('permit_identity')
        if expected is not None and item!=expected:raise ContractError('Actual permit identity drift')
        if item['path']!=wire.get('permit_path',expected['path'] if expected else None):raise ContractError('Permit outside finite reviewed path')
        _snapshot(item,a.project)
        from scorer_adapter import _namespace
        with _namespace(a) as (_,runtime):
            return runtime.validate_permit(conf_root=a.q/'confirmation',receipt_path=item['path'])
