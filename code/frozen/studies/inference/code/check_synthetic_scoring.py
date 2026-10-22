
'Check a synthetic scoring record through its source functions.'
import argparse,json,os,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import read_comparisons as P


def main():
    p=argparse.ArgumentParser();p.add_argument('--record',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True)
    p.add_argument('--consumer',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    P.resource_gate();P.require(not a.out.exists(),'Refuse existing source-test evidence');a.out.mkdir(parents=True)
    evidence=P.strict_json(a.evidence);P.require(Path(evidence['inputs']['seal']['path']).resolve().is_relative_to(Path('/private/tmp')),'Only explicit synthetic sealed record accepted')
    record=P.strict_json(a.record);specification=P.strict_json(P.checked(evidence['inputs']['specification2']))
    P.require(specification.get('synthetic') is True,'Synthetic specification input_checks required')
    root=a.consumer.resolve();P.require(root in (P.MS/'table_renderer/template_validation',P.MS/'table_renderer/result_validation'),'Unexpected consumer version')
    leaves=[root/'table_results_conf_results.py',root/'check_table_sources.py',root/'A8_POSTSCORE_INTERFACE.json',root/'INTERFACE_CHANGES_FOR_A8POST.md',*(root/'table_renderer').glob('*.py')]
    reference_snapshot={str(x.relative_to(P.PROJ)):P.sha256(x) for x in sorted(leaves)}
    for name in list(sys.modules):
        if name in ('table_results_conf_results','check_table_sources') or name.startswith('table_renderer'):del sys.modules[name]
    sys.path.insert(0,str(root));F=P.load_module('table_results_conf_results',root/'table_results_conf_results.py');sys.modules['table_results_conf_results']=F
    import check_table_sources as K
    from table_renderer import constraint_contract as C
    from table_renderer.complete_fill import validate_complete_inputs
    from table_renderer.prepare_table_fields import generate
    from unittest.mock import patch
    from jsonschema import Draft202012Validator
    binding=dict(sha256=evidence['inputs']['specification2']['sha256'],record=specification)
    started=time.monotonic();copy=a.out/'copy';copy.mkdir()
    with patch.object(C,'specification2',return_value=binding):
        schema=F.strict_json(root/'A8_POSTSCORE_INTERFACE.json');errors=list(Draft202012Validator(schema).iter_errors(record));P.require(not errors,'Consumer schema errors: '+str([(list(e.path),e.message) for e in errors[:3]]))
        F.validate_record(record);validate_complete_inputs(record)
        _,prefill,sources=generate(record['author_confirmation'],return_sources=True,record=record)
        outputs,manifest=F.render_bundle(record,dict(facts=F.fixed_facts_for_tests(),a8_freeze_sha256=F.A8_BINDINGS['A8_FREEZE.json'],fixed_facts_sha256=F.A8_BINDINGS['FIXED_FACTS_A8.json']))
        for rel,value in {**sources,**outputs}.items():
            path=copy/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value)
        checked=K.check_documents(copy,manifest,source_only=True)
    stable=reference_snapshot=={str(x.relative_to(P.PROJ)):P.sha256(x) for x in sorted(leaves)}
    receipt=dict(schema='A8POST3_SOURCE_CONSUMER_V1',state='PASS' if checked['state']=='PASS' and stable else 'FAIL',synthetic_only=True,source_only=True,no_build=True,no_freeze=True,source_stable=stable,consumer_root=str(root),consumer_sha256=reference_snapshot,record=P.identity(a.record),evidence=P.identity(a.evidence),k8=checked,seconds=time.monotonic()-started,nice=os.getpriority(os.PRIO_PROCESS,0),memory_free_percent=P.resource_gate(),outputs={rel:P.sha256(copy/rel) for rel in {**sources,**outputs}})
    for filename,value in [('SOURCE_CONSUMER_RECEIPT.json',receipt),('TABLE_RESULTS_K8_EXPECTATIONS.json',manifest)]:
        (a.out/filename).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'state':receipt['state'],'consumer':str(root),'problems':checked['problems']},indent=2))
    return 0 if receipt['state']=='PASS' else 2

if __name__=='__main__':sys.exit(main())
