'Check source-test receipts and the complete table-case enumeration.'
from pathlib import Path
import hashlib,json,re
import table_results_conf_results as F

TEST_SCHEMA='TABLE_RESULTSSET4_SYNTHETIC_TESTS_V2'
PROOF_SCHEMA='TABLE_RESULTS_COMPLETE_P8R7_V1'
LEVELS=('P0','P1','P2','PF','PFMIN')

def collection_hash(nodes):return hashlib.sha256(json.dumps(nodes,separators=(',',':')).encode()).hexdigest()

def validate_tests(path,root,files):
    t=F.strict_json(path);root=Path(root)
    required={'schema','state','passed','failed','pytest_exit','elapsed_seconds','peak_rss_bytes','code_sha256','code_unchanged','single_test_process','production_run','freeze_written','pdf_build','human_workbook_access','resource_samples','resource_violations','blocked_accesses','bytecode_caches_ignored','CONF_metadata_code_paths_read','test_cases','collected_nodeids','collection_sha256','raw_log'}
    F.require(isinstance(t,dict) and set(t)==required and t['schema']==TEST_SCHEMA,'full test receipt schema required')
    F.require(t['state']=='PASS' and type(t['failed']) is int and t['failed']==0 and type(t['pytest_exit']) is int and t['pytest_exit']==0,'test receipt state/count/exit contradiction')
    F.require(t['code_sha256']==files and t['code_unchanged'] is True and t['single_test_process'] is True,'test receipt code/process identity')
    for key in ('production_run','freeze_written','pdf_build','human_workbook_access'):F.require(t[key] is False,'test receipt prohibited operation: '+key)
    for key in ('resource_violations','blocked_accesses'):F.require(t[key]==[],'test receipt violation: '+key)
    F.require(type(t['elapsed_seconds']) in (int,float) and t['elapsed_seconds']>0 and type(t['peak_rss_bytes']) is int and 0<t['peak_rss_bytes']<=2_000_000_000,'test receipt elapsed/RSS')
    manifest=F.strict_json(root/'TEST_CASES.json')
    nodes=manifest.get('nodeids');F.require(isinstance(nodes,list) and bool(nodes) and all(isinstance(n,str) for n in nodes) and len(nodes)==len(set(nodes)),'current test collection manifest')
    F.require(t['collected_nodeids']==nodes and t['collection_sha256']==collection_hash(nodes)==manifest.get('collection_sha256'),'test receipt current suite collection identity')
    for rel,sha in manifest.get('suite_sources_sha256',{}).items():F.require(files.get(rel)==sha and F.sha256(F.safe_path(root,rel))==sha,'test collection suite source drift')
    F.require(set(manifest.get('suite_sources_sha256',{}))=={'test_validation_group_4.py','test_validation_group_4_edges.py','test_template_validation.py'},'test collection applicable suites')
    cases=t['test_cases'];F.require(isinstance(cases,list) and len(cases)==3*len(nodes),'test receipt incomplete phases')
    expected={(n,p) for n in nodes for p in ('setup','call','teardown')};seen=set()
    for r in cases:
        F.require(isinstance(r,dict) and set(r)=={'nodeid','phase','outcome'} and (r['nodeid'],r['phase']) in expected and (r['nodeid'],r['phase']) not in seen and r['outcome']=='passed','test receipt failed/missing/duplicate/skipped case')
        seen.add((r['nodeid'],r['phase']))
    F.require(seen==expected and type(t['passed']) is int and t['passed']==len(nodes),'test receipt passed count differs from applicable suite')
    samples=t['resource_samples'];F.require(isinstance(samples,list) and bool(samples),'test receipt resource samples missing')
    for sample in samples:
        F.require(isinstance(sample,dict) and set(sample)=={'elapsed_seconds','memory_free_percent','nice','scratch_bytes'},'test receipt resource schema')
        F.require(all(type(sample[k]) is int for k in ('memory_free_percent','nice','scratch_bytes')) and 25<=sample['memory_free_percent']<=100 and sample['nice']>=5 and 0<=sample['scratch_bytes']<1_000_000_000,'test receipt resource input_checks')
    for key in ('bytecode_caches_ignored','CONF_metadata_code_paths_read'):F.require(isinstance(t[key],list) and all(isinstance(x,str) for x in t[key]),'test receipt access list schema')
    for rel in t['CONF_metadata_code_paths_read']:
        F.require(not re.search(r'(?i)(?:^|/)(?:host_state|seals?|scores?|predictions?|prices?|truth|evaluation|run)(?:/|$)',rel),'test receipt prohibited confirmation access path')
        name=Path(rel).name
        F.require(not (Path(rel).suffix not in ('.py','.md') and re.search(r'(?i)(?:prediction|truth|price|daily.loss|scores?)(?:[_\.])',name)),'test receipt prohibited confirmation payload access')
    log=t['raw_log'];F.require(isinstance(log,dict) and set(log)=={'path','sha256'},'test receipt raw log binding required')
    lp=F.safe_path(root,log['path']);F.require(lp.is_file() and F.sha256(lp)==log['sha256'],'test receipt raw log hash')
    raw=lp.read_text();marker='TABLE_RESULTS_TEST_EVENTS='
    lines=[x[len(marker):] for x in raw.splitlines() if x.startswith(marker)]
    F.require(len(lines)==1 and json.loads(lines[0])=={'collected_nodeids':nodes,'pytest_exit':0,'test_cases':cases},'test receipt raw log execution identity')
    return t


def required_proof_domain():
    return {
      'primary_classes':list(F.CLASSES),'six_checks':{k:['PASS','FAIL','UNAVAILABLE'] for k in F.CHECKS},
      'd3_alert':[False,True],'d6_seven_day':['DEFINED','UNDEFINED'],
      'three_seed_classes':list(F.CLASSES),'R8_relations':list(F.REL_STATES),
      'DLY8_relations':list(F.REL_STATES),'KCX_relations':list(F.REL_STATES),'CPS8_relations':list(F.REL_STATES),
      'CLK8_states':['OK','LATE','NOT_INFORMATIVE','NOT_RUN_INPUT_MISMATCH','NOT_RUN'],
      'registration_variant':['private','public','fallback'],'embargo_states':[False,True],
      'title_variant':['a8','a8b'],'PC':['RESULT','PENDING','SPEED_PENDING','NOT_RUN_REPIN'],
      'PCX_presence':[False,True],'R12b_B4_admission':[False,True],
      'R8_seed_disposition':['single'],'numeric_domain':'frozen plain_display_record envelope',
      'refused_branches':['public/fallback author registration','KCX other than not_run','r8_seeds=three'],
      'design_layer_subsets':'all frozen PLAIN_LAYER subsets','delay_grid':[5,15,60],
      'task_complete':[False,True],'incomplete_reasons':F.templates()['words']['PLAIN_INC_REASON'],
      'LEAR_classes':list(F.CLASSES),'LEAR_effect_sign':['negative','nonnegative'],
      'signal_failed':[False,True],'secondary_aggregate':['SAME','DIFF','NA'],
      'optional_presence_patterns':'all frozen optional-presence patterns'}

def proof_bindings(files,timestamp_checks):
    from table_renderer.constraint_contract import specification2
    return {'code_sha256':files,'renderer_sha256':files['table_results_conf_results.py'],
       'rules_sha256':F.sha256(F.inference_design/'RULES_FOR_TABLE_RESULTS.json'),
       'templates_sha256':F.sha256(F.MS/'table_results_templates.json'),
       'specification1_sha256':F.sha256(F.inference_design/'ADDENDUM_A8_SPECIFICATION_1_FREEZE.json'),
       'specification2_sources':timestamp_checks['specification2']['record']['files'],
       'specification2_changes_sha256':F.text_hash(json.dumps(timestamp_checks['specification2']['record']['changes'],sort_keys=True,separators=(',',':'))),
       'specification2_receipt_path':str(F.inference_design/'ADDENDUM_A8_SPECIFICATION_2_FREEZE.json')}

def validate_proof(path,root,files,timestamp_checks,acceptance):
    F.require(path is not None and Path(path).is_file(),'complete P8R7 proof receipt required (FAST PFMIN envelope is insufficient)')
    p=F.strict_json(path)
    required={'schema','state','mode','bindings','domain','coverage','levels','proof_engine','proof_spec','raw_log','signatures_evaluated'}
    F.require(isinstance(p,dict) and set(p)==required and p['schema']==PROOF_SCHEMA and p['state']=='PASS' and p['mode']=='COMPLETE_FROZEN_REACHABLE_DOMAIN','complete P8R7 proof schema/mode/state')
    F.require(p['bindings']==proof_bindings(files,timestamp_checks),'complete P8R7 proof stale bindings')
    F.require(p['domain']==required_proof_domain(),'complete P8R7 proof incomplete domain')
    F.require(type(p['signatures_evaluated']) is int and p['signatures_evaluated']>0,'complete proof has no enumeration')
    F.require(p['coverage']=={'all_levels':True,'exhaustive':True,'refused_branches_checked':True,'attained_witnesses_verified':True,'first_qualifying_level_verified':True},'complete P8R7 proof coverage')
    root=Path(root)
    for key in ('proof_engine','proof_spec','raw_log'):
        entry=p[key];F.require(isinstance(entry,dict) and set(entry)=={'path','sha256'},'complete proof artifact schema')
        q=F.safe_path(root,entry['path']);F.require(q.is_file() and F.sha256(q)==entry['sha256'],'complete proof artifact identity: '+key)
        if key!='raw_log':F.require(files.get(entry['path'])==entry['sha256'],'proof engine/spec must belong to reviewed inventory')
    F.require(acceptance.get('abstract_proof_sha256')==F.sha256(path) and acceptance.get('abstract_proof_verified') is True,'independent acceptance must verify complete P8R7 proof')
    F.require(isinstance(p['levels'],dict) and set(p['levels'])==set(LEVELS),'complete proof missing level')
    for level,v in p['levels'].items():
        F.require(set(v)=={'words','characters','sentence_max','sentence_witness','witnesses','texts'},'complete proof level schema')
        F.require(all(type(v[k]) is int and v[k]>0 for k in ('words','characters','sentence_max')) and v['sentence_max']<=35 and F.words(v['sentence_witness'])==v['sentence_max'],'complete proof 35-word sentence gate: '+level)
        F.require(set(v['witnesses'])==set(v['texts'])=={'words','characters','sentence'},'complete proof metric witnesses')
        for metric,r in v['witnesses'].items():
            F.validate_record(r);rendered=F.plain_render(r,level=level)
            F.require(rendered['text']==v['texts'][metric],'complete proof production witness text: '+level)
            F.require(rendered['words']<=v['words'] and rendered['characters']<=v['characters'] and rendered['sentence_max']<=v['sentence_max'],'complete proof understated metric: '+level)
            F.require(rendered['words' if metric=='words' else 'characters' if metric=='characters' else 'sentence_max']==v['words' if metric=='words' else 'characters' if metric=='characters' else 'sentence_max'],'complete proof unattained maximum: '+level)
            if metric=='sentence':F.require(v['sentence_witness'] in rendered['sentences'],'complete proof longest sentence witness')
            selected=F.render(r);F.require(selected['words']<=250 and selected['characters']<=1920 and selected['sentence_max']<=35,'complete proof selection gate')
    T=F.templates();floor=p['levels']['PFMIN']
    F.require(floor['words']<=F.strict_json(F.inference_design/'RULES_FOR_TABLE_RESULTS.json')['proof']['worst_validator_words'] and floor['characters']<=T['words']['PFMIN_PROOF']['char_bound'],'complete proof PFMIN frozen bound')
    return p
