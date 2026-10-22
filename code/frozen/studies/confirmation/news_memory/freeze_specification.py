"""Coordinator-only CONFX7→CONFX8 freeze, same after/freeze/chain/verify pattern.
Run after install, host update and pre-freeze checks. No host_state file is opened.
Measurement artifacts are written later and explicitly required by the bound gate.
"""
from __future__ import annotations
import argparse, datetime as dt, importlib.util, json, sys
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;CONF=HERE.parent;ADAPTERS=CONF/'CONFX2'
sys.path.insert(0,str(ADAPTERS))
import runtime
ROOT_HASH='de80c4e0c3450f3e4383c477c4a3a088cc7d3956835f8ba5e51cf5d78944b394'
PARENT_HASH='38c3894c4135014e9d3f5a7f296d8e588f50d0290277798bccd9accf6b9627fc'
PARENT=HERE/'archive/pre_CONFX8/CONFX2/ADAPTER_FREEZE.json'
TASKS=['CONFX3','CONFX4','CONFX5','CONFX6','CONFX7','CONFX8']
CHANGED=['CONFX2/execution_adapter.py','CONFX2/runtime.py','CONFX2/tests/test_execution_amendment.py',
         'CONFX2/tests/test_confx7_memory.py','HOST_RUN.md']
NEW=['CONFX2/tests/test_confx8_resources.py']
BOUND=['SPEC.md','SPEC_FREEZE.json','PRE_IDENTITIES.json','BEFORE_IDENTITIES.json','AFTER_IDENTITIES.json',
       'EXECUTION_DIFF.patch','EXECUTION_NOTE.md','HOST_RUN_DRAFT.md','HOST_RUN_DIFF.patch',
       'UNCHANGED_CODE.json','FROZEN_DESIGN_VERIFICATION.json','T3_CONTINUITY.json','FINAL_TEST_RESULTS.json',
       'confx7_unchanged.log','confx7_unchanged.xml','confx8_amended.log','confx8_amended.xml',
       'features_completion_rule.py','measure_fit_memory.py','measure_speed_a3.py','feasibility_24h.py',
       'feasibility_24h_a3.py','measurement_gate.py','make_scratch_roots.py','host_chain_CONFX8.sh',
       'update_host_run.py','verify_code_scope.py','verify_frozen_design.py','t3_continuity.py',
       'install_confx8.py','freeze_amendment.py','run_tests.py','repair_tests.py',
       'confx7_unchanged_repair.log','confx7_unchanged_repair.xml','confx8_amended_repair.log','confx8_amended_repair.xml',
       'HARNESS_PROTOCOL_TESTS.json','PREINSTALL_VERIFICATION.json',
       'T4_NOTE.md','staging/STAGING_MANIFEST.json','STAGING_MANIFEST.json']

def require(ok,message):
    if not ok:raise AssertionError(message)
def load(name):
    s=importlib.util.spec_from_file_location('confx8_'+name,HERE/(name+'.py'))
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def stamp():return dt.datetime.now(dt.timezone.utc).isoformat()

def after():
    require(tuple(runtime.AMENDMENT_CHAIN)==tuple(TASKS),'CONFX8 is not installed')
    out={rel:runtime.file_identity(CONF/rel) for rel in CHANGED+NEW}
    out.update({'CONFX8/'+rel:runtime.file_identity(HERE/rel) for rel in BOUND if rel!='AFTER_IDENTITIES.json'})
    runtime.atomic_json(HERE/'AFTER_IDENTITIES.json',out,immutable=True);return out

def freeze():
    require(tuple(runtime.AMENDMENT_CHAIN)==tuple(TASKS),'CONFX8 is not installed')
    require(runtime.sha256(PARENT)==PARENT_HASH,'archived CONFX7 freeze drift')
    require(runtime.sha256(ADAPTERS/'ADAPTER_FREEZE.json')==PARENT_HASH,'freeze is not at its registered parent')
    parent=runtime.read_json(PARENT)
    for rel,item in runtime.read_json(HERE/'BEFORE_IDENTITIES.json').items():
        require(runtime.sha256(item['archive_path'])==item['sha256'],'archive drift: '+rel)
    for rel,item in runtime.read_json(HERE/'AFTER_IDENTITIES.json').items():
        require(runtime.file_identity(item['path'])==item,'after-identity drift: '+rel)
    tests=runtime.read_json(HERE/'FINAL_TEST_RESULTS.json')
    require(tests['state']=='PASS' and not tests['source_drift_during_tests'],'suite not cleanly passing')
    require(tests['suites']['confx7_unchanged']['state']=='PASS','original CONFX7 suite not passing')
    require(tests.get('full_shape_fits_run')==0 and not tests.get('host_state_opened'),'preparation scope violated')
    for name in ('UNCHANGED_CODE.json','FROZEN_DESIGN_VERIFICATION.json','T3_CONTINUITY.json'):
        require(runtime.read_json(HERE/name)['state']=='PASS',name+' did not pass')
    unchanged=runtime.read_json(HERE/'UNCHANGED_CODE.json')
    proven,why=load('features_completion_rule').feature_path_proven(unchanged)
    require(proven,why)
    require(unchanged.get('worker_and_admission_ast_identical') is True,'worker/admission scope drift')
    covered={str(Path(i['path']).relative_to(Path(i['path']).parents[1] if '/tests/' in i['path'] else Path(i['path']).parent)):i
             for i in tests['test_files']+tests['adapter_source_files']}
    for rel,item in covered.items():require(runtime.sha256(ADAPTERS/rel)==item['sha256'],'tested source not installed: '+rel)
    # Inherited parent records remain frozen; only the registered live replacements change.
    files={rel:{'sha256':runtime.sha256(ADAPTERS/rel),'bytes':(ADAPTERS/rel).stat().st_size} for rel in parent['files']}
    for rel in NEW:
        p=CONF/rel;files[str(p.relative_to(ADAPTERS))]={'sha256':runtime.sha256(p),'bytes':p.stat().st_size}
    for rel in BOUND:
        p=HERE/rel;files['../CONFX8/'+rel]={'sha256':runtime.sha256(p),'bytes':p.stat().st_size}
    ident=runtime.file_identity
    amendment={'task':'CONFX8','parent_adapter_freeze':ident(PARENT),'before_identities':ident(HERE/'BEFORE_IDENTITIES.json'),
        'after_identities':ident(HERE/'AFTER_IDENTITIES.json'),'execution_note':ident(HERE/'EXECUTION_NOTE.md'),
        'spec':ident(HERE/'SPEC.md'),'spec_freeze':ident(HERE/'SPEC_FREEZE.json'),
        'no_statistical_design_or_feature_content_change':True,'execution_resource_rule':runtime.CONFX8_RESOURCE_RULE,
        'reason':'Author CONFX8 instruction 2026-10-04: full-shape news failed at 2 GiB anonymous; news alone gets 3.5 GiB. '
                 'LEAR 2 GiB, notice/tree 6.6 GiB, throttle 6.0 GiB unchanged; measured news projection floors only. '
                 'Old pre-CONFX7 worker RSS override exists exclusively in the synthetic measurement harness.',
        'measurement_gate':ident(HERE/'measurement_gate.py'),'measurement_records_after_install':
            ['MEMORY_MEASUREMENTS.json','SPEED_MEASUREMENTS_A3.json','FEASIBILITY_24H.json','FEASIBILITY_24H_A3.json'],
        'feature_path_identical_to_confx7':True,'unchanged_code':ident(HERE/'UNCHANGED_CODE.json'),
        'frozen_design_verification':ident(HERE/'FROZEN_DESIGN_VERIFICATION.json'),'t3_continuity':ident(HERE/'T3_CONTINUITY.json'),
        'registered_chain':TASKS,'primary_decision_rule_change':False}
    out={**parent,'files':dict(sorted(files.items())),'execution_amendment':amendment,'parent_task_id':'CONFX7',
        'task_id':'CONFX8','test_results':ident(HERE/'FINAL_TEST_RESULTS.json'),'time_utc':stamp(),
        'production_commands_run':[],'window_outcomes_read':False,'window_values_read':False,
        'state':'ADAPTERS_FROZEN_SYNTHETICALLY_VERIFIED'}
    runtime.atomic_json(ADAPTERS/'ADAPTER_FREEZE.json',out);return out

def chain():
    current,steps=runtime.adapter_amendment_chain(ADAPTERS,ROOT_HASH)
    require([s['task'] for s in steps]==TASKS,'exact chain failed')
    prior=runtime.read_json(CONF/'CONFX7/AMENDED_ADAPTER_CHAIN.json');ident=runtime.file_identity
    prior_steps=prior['steps'][:-1]+[{**prior['steps'][-1],'adapter_freeze':ident(PARENT)}]
    last={'task':'CONFX8','adapter_freeze':ident(ADAPTERS/'ADAPTER_FREEZE.json'),
          'parent_adapter_freeze':ident(PARENT),'execution_note':ident(HERE/'EXECUTION_NOTE.md'),
          'before_identities':ident(HERE/'BEFORE_IDENTITIES.json'),'unchanged_code':ident(HERE/'UNCHANGED_CODE.json'),
          'measurement_gate':ident(HERE/'measurement_gate.py'),
          'declaration':{'no_statistical_design_or_feature_content_change':True,'execution_resource_rule':runtime.CONFX8_RESOURCE_RULE}}
    out={'state':'EXECUTION_AMENDMENT_CHAIN_FROZEN','time_utc':stamp(),
        'registered_chain':['input-bound original']+TASKS,'input_bound_root':prior['input_bound_root'],
        'steps':prior_steps+[last],'amended_adapter_freeze':ident(ADAPTERS/'ADAPTER_FREEZE.json'),
        'confx7_chain_record':ident(CONF/'CONFX7/AMENDED_ADAPTER_CHAIN.json'),
        'features_completion_rule':'CONFX8/features_completion_rule.py: current freeze or proven CONFX7/CONFX6 completion',
        'original_input_freeze_and_authorization_retained':True,'primary_decision_rule_change':False}
    runtime.atomic_json(HERE/'AMENDED_ADAPTER_CHAIN.json',out,immutable=True);return out

def verify():
    current,steps=runtime.adapter_amendment_chain(ADAPTERS,ROOT_HASH);design=runtime.verify_design()
    record=runtime.read_json(HERE/'AMENDED_ADAPTER_CHAIN.json');tests=runtime.read_json(HERE/'FINAL_TEST_RESULTS.json')
    source_items=tests['test_files']+tests['adapter_source_files']
    source_match=all(runtime.sha256(i['path'])==i['sha256'] for i in source_items)
    installed_match=all(runtime.sha256(ADAPTERS/('tests/'+Path(i['path']).name if '/tests/' in i['path'] else Path(i['path']).name))==i['sha256'] for i in source_items)
    covered={('tests/'+Path(i['path']).name if '/tests/' in i['path'] else Path(i['path']).name) for i in source_items}
    actual={str(p.relative_to(ADAPTERS)) for p in [*ADAPTERS.glob('*.py'),*(ADAPTERS/'tests').glob('*.py')]}
    refusals={}
    for label,digest in [('unknown','f'*64)]+[(s['task'],s['parent_adapter_freeze']['sha256']) for s in steps[1:]]:
        try:runtime.verify_adapter_ancestor(ADAPTERS,digest);refusals[label]=False
        except PermissionError as exc:refusals[label]=str(exc)
    rule=load('features_completion_rule');u=runtime.read_json(HERE/'UNCHANGED_CODE.json')
    checks={k:rule.verdict({'adapter_freeze_sha256':v},record,u)[0] for k,v in
            [('confx8',record['amended_adapter_freeze']['sha256']),('confx7',PARENT_HASH),('confx6',rule.CONFX6_FREEZE),('unknown','f'*64)]}
    okay=(source_match and installed_match and actual==covered and all(refusals.values()) and
          checks=={'confx8':True,'confx7':True,'confx6':True,'unknown':False} and
          record['amended_adapter_freeze']==runtime.file_identity(ADAPTERS/'ADAPTER_FREEZE.json'))
    require(okay,'final verification failed')
    out={'task':'CONFX8','state':'PASS','time_utc':stamp(),'real_chain_tasks':[s['task'] for s in steps],
        'adapter_files_verified':len(current['files']),'design_frozen_files_verified':len(design['frozen_files']),
        'chain_refusals':refusals,'features_completion_checks':checks,'suite_source_identities_match':source_match,
        'installed_sources_equal_tested_sources':installed_match,'suite_covers_all_installed_python':actual==covered,
        'amended_adapter_freeze':runtime.file_identity(ADAPTERS/'ADAPTER_FREEZE.json'),
        'production_shape_bit_identity':'PENDING_COORDINATOR_MEASUREMENT_GATE','host_state_opened':False,'production_commands_run':[]}
    runtime.atomic_json(HERE/'FINAL_VERIFICATION.json',out);return out

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('step',choices=['after','freeze','chain','verify']);a=p.parse_args()
    r=globals()[a.step]();print(json.dumps({'step':a.step,'ok':True,'keys':len(r)}))
