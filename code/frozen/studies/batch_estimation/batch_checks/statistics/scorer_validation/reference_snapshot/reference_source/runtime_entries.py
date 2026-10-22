'Resolve the numerical entry points from checked source files.'
import inspect
from pathlib import Path
from contract_io import ContractError, _snapshot, _json

SCHEMA='C_SCORING_RUNTIME_ENTRIES_V1'
ROLE_FAMILY=dict(arm='scoring_callback',capture='scoring_callback',r2_complete='scoring_callback',ap5_science='AP5',ap6_joint='AP6',rd_joint='notice_delays',optional_loader='AP5',numeric_assembly='AP5',author_validation='AP5')

def _resolve(a,role):
    a.verify_t5_coverage()
    with a._validation():
        document=_json(_snapshot(a._science_binding['entry_contracts'],a.out))
    if document.get('schema')!=SCHEMA:raise ContractError('Wrong runtime-entry contract')
    row=document['entries'][role]
    if row.get('status')!='OWNER_DELIVERED_REVIEWED':raise ContractError('PENDING external entry: '+role)
    family=row['family']
    if family!=ROLE_FAMILY.get(role):raise ContractError('Entry role/family mismatch')
    root=a.q/a._science_policy['families'][family]['root']
    p=root/row['source'];pin=a._ap_runtime.member(p)

    import importlib.util
    name='_scoring_entry_'+family+'_'+p.stem
    spec=importlib.util.spec_from_file_location(name,p);module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn=getattr(module,row['callable'])
    if not callable(fn):raise ContractError('Declared entry is not callable')
    target=getattr(fn,'__wrapped__',fn)
    if Path(inspect.getsourcefile(target)).absolute()!=p:raise ContractError('Entry alias/foreign callable')
    a._ap_runtime.member(p)
    if a.synthetic and family=='scoring_callback' and getattr(module,'__synthetic_fixture__',False) is not True:
        raise ContractError('Accept cannot execute actual scoring_callback host machinery')
    return fn,pin,row

def _entry(a,role):
    try:return _resolve(a,role)
    except BaseException:
        a._official_ready=None;a.revoke_ap_route();raise

def _call(a,role,**kwargs):
    fn,pin,row=_entry(a,role)
    try:
        result=fn(**kwargs)
        a._ap_runtime.member(pin['path'])
        return result
    except BaseException:
        a._official_ready=None;a.revoke_ap_route();raise
