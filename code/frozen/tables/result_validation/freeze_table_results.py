
'Save the checked table rendering sources and their hashes.'
import argparse,ast,json,hashlib
from datetime import datetime,timezone
from pathlib import Path
import table_results_conf_results as F

ROOT=Path(__file__).resolve().parent
STATE='TABLE_RESULTS_FROZEN_BEFORE_D_SCORES'

def inventory(root=ROOT):
    root=Path(root)
    static_json={'A8_POSTSCORE_INTERFACE.json','RENAME_GOLDEN.json','TEST_CASES.json'}
    static_md={'TEST_SPEC.md','INTERFACE_CHANGES_FOR_A8POST.md','PROOF_RECEIPT_SPEC.md'}
    paths=sorted(p for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and (p.suffix in ('.py','.sh') or p.name in static_json|static_md))
    return {str(p.relative_to(root)):F.sha256(p) for p in paths}


def candidate(root,timestamp_checks,test_receipt,reference_gate,prescore,acceptance=None,abstract_proof=None):
    root=Path(root);files=inventory(root)
    F.require(prescore.get('state')=='SOURCE_ATTESTS_BEFORE_CONF_SCORE' and prescore.get('score_not_started') is True and prescore.get('outcome_access') is False and bool(prescore.get('recorded_by')),'prescore source attestation required')
    F.require(isinstance(acceptance,dict) and acceptance.get('state')=='INDEPENDENT_ACCEPTANCE_PASS' and acceptance.get('code_sha256')==files and bool(acceptance.get('reviewed_by')) and acceptance.get('independent') is True,'independent acceptance of exact current inventory required')
    from receipt_gates import validate_tests,validate_proof
    test=validate_tests(test_receipt,root,files)
    F.require(timestamp_checks.get('specification2') is not None,'effective specification-2 receipt required')
    proof=validate_proof(abstract_proof,root,files,timestamp_checks,acceptance)
    when=datetime.now(timezone.utc).isoformat()
    gate=F.strict_json(reference_gate)
    F.require(gate.get('code_sha256')==files['table_renderer/reference_gate.py'],'reference evidence code identity')
    from table_renderer.reference_gate import verify_receipt
    gate_sha=F.sha256(reference_gate)
    verify_receipt(reference_gate,{'reference_gate_sha256':gate_sha,'created_utc':when})
    F.require(gate.get('clauses_active')=={'Clark2007':False,'Andrews2000':False},'R13 inactive policy required')
    ext={str((F.inference_design/name).relative_to(F.PROJ)):F.sha256(F.inference_design/name) for name in F.A8_BINDINGS}
    ext.update({str((F.MS/name).relative_to(F.PROJ)):F.sha256(F.MS/name) for name in ('SUMMARY_COMPARISONS_FREEZE.json','table_results_templates.json','main_comparisons_templates.json','fill2_templates.json','claims.sty','check_arxiv.py')})

    from table_renderer.prepare_table_fields import generate
    _,stage=generate()
    ext.update({'tables/'+rel:sha for rel,sha in stage['inputs_sha256'].items()})
    binding=timestamp_checks['specification2']
    ext.update({str(Path(x['path']).relative_to(F.PROJ)):x['sha256'] for x in binding['record']['files']})
    ext['studies/confirmation/inference_design/ADDENDUM_A8_SPECIFICATION_2_FREEZE.json']=binding['sha256']
    ext['studies/confirmation/inference_design/CLK8/CLK8_RESULT.json']=__import__('table_renderer.table_contract',fromlist=['CLOCK_SHA']).CLOCK_SHA
    result={'schema':'TABLE_RESULTS_FREEZE_V1','state':STATE,'created_utc':when,'files':files,'test_receipts':{str(Path(test_receipt).relative_to(root)):F.sha256(test_receipt)},'external_identities':ext,'a8_freeze_sha256':timestamp_checks['a8_freeze_sha256'],'a8_specification1_freeze_sha256':F.sha256(F.inference_design/'ADDENDUM_A8_SPECIFICATION_1_FREEZE.json'),'a8_specification2_freeze_sha256':binding['sha256'],'reference_gate_sha256':gate_sha,'r13_clauses_active':{'Clark2007':False,'Andrews2000':False},'prescore_attestation':prescore,'independent_acceptance':acceptance,'source_only_tests':True,'production_scoring_or_pdf_build':False}
    result['abstract_proof']={'path':str(Path(abstract_proof).relative_to(root)),'sha256':F.sha256(abstract_proof),'state':'PASS','verification':'P8R7_COMPLETE_VERIFIED','levels':{k:{f:v[f] for f in ('words','characters','sentence_max','sentence_witness')} for k,v in proof['levels'].items()},'bindings':proof['bindings'],'domain':proof['domain']}
    result['test_receipts'][str(Path(abstract_proof).relative_to(root))]=F.sha256(abstract_proof)
    for evidence in (test['raw_log'],proof['raw_log']):result['test_receipts'][evidence['path']]=evidence['sha256']
    result['test_collection_sha256']=test['collection_sha256']
    return result


def write_exclusive(path,record):

    path=Path(path)
    with path.open('x') as f:json.dump(record,f,indent=2);f.write('\n')


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');p.add_argument('--abstract-proof',type=Path);p.add_argument('--test-receipt',type=Path);p.add_argument('--reference-gate',type=Path);p.add_argument('--prescore-attestation',type=Path);p.add_argument('--acceptance',type=Path);a=p.parse_args(argv)
    if not a.apply:
        print(json.dumps({'state':'PLAN_ONLY_NO_FREEZE','output':str(ROOT/'TABLE_RESULTS_FREEZE.json'),'requires':['validation_group_6 independent acceptance including complete proof SHA','current full TEST_RECEIPT PASS with collection and raw log','complete current P8R7 proof for all five levels and reachable domain','effective specification-2','fresh reference evidence with both clauses inactive','source prescore attestation'],'files':inventory()},indent=2));return 0
    F.require(all((a.test_receipt,a.reference_gate,a.prescore_attestation,a.acceptance,a.abstract_proof)),'all explicit freeze inputs required')
    F.require(a.test_receipt.resolve().is_relative_to(ROOT) and a.abstract_proof.resolve().is_relative_to(ROOT) and a.reference_gate.resolve()==ROOT/'table_renderer/REFERENCE_GATE_AT_FREEZE.json','receipt locations must belong to this consumer version')
    F.require(not (F.inference_design.parent/'host_state/SCORE_RECEIPT.json').exists(),'confirmation score receipt exists; refuse prescore freeze')
    timestamp_checks=F.timestamp_checks(frozen=False)
    record=candidate(ROOT,timestamp_checks,a.test_receipt,a.reference_gate,F.strict_json(a.prescore_attestation),F.strict_json(a.acceptance),a.abstract_proof)
    for path in (a.acceptance,a.prescore_attestation):
        F.require(path.resolve().is_relative_to(F.PROJ),'acceptance/prescore receipt must be in the project')
        record['external_identities'][str(path.resolve().relative_to(F.PROJ))]=F.sha256(path)


    F.require(record['files']==inventory(),'consumer drift during freeze preparation')
    for rel,sha in record['external_identities'].items():
        path=F.safe_path(F.PROJ,rel)
        F.require(path.is_file() and F.sha256(path)==sha,'external identity drift before freeze: '+rel)
    F.require(F.sha256(a.test_receipt)==next(iter(record['test_receipts'].values())) and F.sha256(a.reference_gate)==record['reference_gate_sha256'],'gate receipt drift before freeze')
    for rel,sha in record['test_receipts'].items():F.require(F.sha256(F.safe_path(ROOT,rel))==sha,'proof/test evidence drift before freeze: '+rel)
    write_exclusive(ROOT/'TABLE_RESULTS_FREEZE.json',record)
    F.verify_manifest(ROOT/'TABLE_RESULTS_FREEZE.json',ROOT)
    print(json.dumps({'state':STATE,'path':str(ROOT/'TABLE_RESULTS_FREEZE.json'),'sha256':F.sha256(ROOT/'TABLE_RESULTS_FREEZE.json')}));return 0
if __name__=='__main__':raise SystemExit(main())
