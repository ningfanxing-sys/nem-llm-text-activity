
'Select the notice constraint sources for validation.'
import argparse
import importlib.util
from pathlib import Path
import sys
sys.dont_write_bytecode=True
s=importlib.util.spec_from_file_location('_am3dld_source_freezer',Path(__file__).with_name('freeze_notice_constraints.py'))
F=importlib.util.module_from_spec(s);s.loader.exec_module(F)


def dispatch(action,*,canonical=F.TEXT,attestation=None,af_code_freeze=None,require_timestamp=False,require_af_freeze=False):
    F.resource_gate();F.current_version(canonical=canonical,entry=Path(__file__).name)
    if action=='freeze':
        F.require(attestation is not None,'Actual current-version attestation required')
        return F.create(attestation_path=attestation,af_code_freeze=af_code_freeze)
    if action=='verify':
        return F.verify(F.HERE/F.RECEIPT,require_timestamp=require_timestamp,require_af_freeze=require_af_freeze)
    F.require(action=='bind','Closed current source action required')
    s=importlib.util.spec_from_file_location('_am3dld_source_binder',F.HERE/'bind_notice_constraints.py')
    module=importlib.util.module_from_spec(s);s.loader.exec_module(module)
    return module.create(af_code_freeze=af_code_freeze)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--action',required=True,choices=['freeze','verify','bind'])
    p.add_argument('--canonical',default=F.TEXT);p.add_argument('--attestation',type=Path);p.add_argument('--af-code-freeze',type=Path)
    p.add_argument('--require-timestamp',action='store_true');p.add_argument('--require-af-freeze',action='store_true');a=p.parse_args()
    dispatch(a.action,canonical=a.canonical,attestation=a.attestation,af_code_freeze=a.af_code_freeze,require_timestamp=a.require_timestamp,require_af_freeze=a.require_af_freeze)
    print('AM3DLE CURRENT '+a.action.upper()+' COMPLETE; no timestamp created')

if __name__=='__main__':
    try:main()
    except (ValueError,RuntimeError,OSError,KeyError,TypeError) as e:raise SystemExit('AM3DLE SOURCE REFUSED: '+str(e))
