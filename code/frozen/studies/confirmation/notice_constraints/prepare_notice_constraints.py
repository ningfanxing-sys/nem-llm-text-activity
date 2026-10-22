
'Check notice constraints and forecast source paths.'
import argparse
import importlib.util
from pathlib import Path
import sys
sys.dont_write_bytecode=True
s=importlib.util.spec_from_file_location('_am3_prepare',Path(__file__).with_name('freeze_notice_constraints.py'))
F=importlib.util.module_from_spec(s);s.loader.exec_module(F)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-prepare',action='store_true');p.add_argument('--input',required=True,type=Path);a=p.parse_args()
    try:
        F.resource_gate();F.current_version();F.verify_citations();F.require(a.source_prepare,'Explicit source action required')
        F.require(a.input.absolute().parent==F.HERE and a.input.name!='FINAL_AF_REVIEW8_COMMITMENT.template.json','Actual completed input in notice_constraints required')
        q=F.HERE.parent.parent
        _,historical=F.manifest(q/'confirmation/TIMESTAMPS/T4F/MANIFEST_T4F.sha256','T4F',q)
        F.require(F.sha(q/'confirmation/TIMESTAMPS/T4F/MANIFEST_T4F.sha256')==F.B.strict(F.HERE/'INPUT_PINS.json')['confirmation/TIMESTAMPS/T4F/MANIFEST_T4F.sha256'],'Historical T4F manifest drift')
        F.deadline_inputs();F.review8_inputs()
        value=F.final_sources(F.HERE/'FINAL_AF_REVIEW8_COMMITMENT.json',q,historical,value=F.strict(a.input))
        F.exclusive_json(F.HERE/'FINAL_AF_REVIEW8_COMMITMENT.json',value)
        print('notice_records AF SOURCE COMMITMENT RECORDED; no AM3/AF freeze or timestamp')
    except (ValueError,RuntimeError,OSError,KeyError,TypeError) as e:raise SystemExit('notice_records AF COMMITMENT REFUSED: '+str(e))
