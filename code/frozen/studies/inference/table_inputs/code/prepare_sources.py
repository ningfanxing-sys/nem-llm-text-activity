'Update the source inventory for table-input validation.'
import ast,hashlib,json
from pathlib import Path
from table_input_hash import ROOT,AP,PROJ,FILL_ROOT,FILL_ROUND

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')

def prepare():
    old=json.loads((AP/'a8post4/DEPENDENCY_PINS.json').read_text())


    files={rel:digest for rel,digest in old['files'].items() if not rel.startswith('tables/table_renderer/validation_group_8/')}
    rd=PROJ/'studies/confirmation/notice_evaluation'
    clean_path=rd/'test_receipts/anchorreader4_clean.json'
    clean=json.loads(clean_path.read_text())
    assert clean['state']=='PASS_SYNTHETIC_TESTS' and clean['tests_run']==38 and clean['production_payload_reads']==0,'notice_delays reviewed migration receipt absent'
    for rel,digest in clean['own_source_sha256'].items():assert sha(rd/rel)==digest,'notice_delays source changed after its clean migration suite'
    rd_pins=json.loads((rd/'PINNED_SOURCES.json').read_text())
    tree=ast.parse((FILL_ROOT/'table_renderer/forecast_binding.py').read_text())
    source_functions=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='FUNCTION_SOURCES' for t in n.targets))
    assert rd_pins['source_functions']==source_functions,'notice_delays/FILL frozen function association mismatch'
    for item in source_functions:
        assert sha(item['path'])==item['sha256'],'notice_delays frozen scientific source drift'
        names={n.name for n in ast.parse(Path(item['path']).read_text()).body if isinstance(n,ast.FunctionDef)}
        assert set(item['functions'])<=names,'notice_delays frozen function census drift'
    changed='studies/confirmation/notice_evaluation/code/anchor_reader.py'
    refreshed=clean['own_source_sha256']['code/anchor_reader.py']
    refresh=dict(schema='A8POST5_DEPENDENCY_REFRESH_V1',state='CURRENT_RD_MIGRATION_REVIEWED_NOT_FROZEN',
        old_identity=dict(path=str(PROJ/changed),sha256=files[changed]),new_identity=dict(path=str(PROJ/changed),sha256=refreshed),
        basis=dict(path=str(clean_path),sha256=sha(clean_path)),frozen_function_identities=source_functions,
        input_checks='Only the owner-tested notice_delays round migration is refreshed; specified mathematical dependencies stay exactly pinned. AP never computes the corrected view.')
    files[changed]=refreshed
    for rel,digest in files.items():assert sha(PROJ/rel)==digest, 'Specified dependency drift: '+rel
    for rel,digest in clean['own_source_sha256'].items():files[str((rd/rel).relative_to(PROJ))]=digest
    files[str(clean_path.relative_to(PROJ))]=sha(clean_path)
    write(ROOT/'DEPENDENCY_REFRESH.json',refresh)
    inventory=json.loads((FILL_ROOT/'CODE_INVENTORY_SHA256.json').read_text())
    for rel,digest in inventory.items():
        path=FILL_ROOT/rel;assert sha(path)==digest,'FILL inventory drift: '+rel
        files[str(path.relative_to(PROJ))]=digest
    receipts=['CODE_INVENTORY_SHA256.json','CODE_INVENTORY_AT_FULL_SUITE_SHA256.json','FINAL_VALIDATION.json']
    assert inventory==json.loads((FILL_ROOT/'CODE_INVENTORY_AT_FULL_SUITE_SHA256.json').read_text()),'FILL tested inventory mismatch'

    final=json.loads((FILL_ROOT/'FINAL_VALIDATION.json').read_text())
    declared=[]
    for section in ('suite','rendered_k8','rendered','proof','abstract_proof'):
        block=final.get(section,{})
        if isinstance(block,dict) and isinstance(block.get('receipt'),str):
            assert sha(FILL_ROOT/block['receipt'])==block['sha256'],'FILL declared receipt drift'
            declared.append(block['receipt'])
    assert final['code_inventory_sha256']==sha(FILL_ROOT/'CODE_INVENTORY_SHA256.json'),'FILL final inventory association'
    receipts+=declared
    for rel in set(receipts):
        path=FILL_ROOT/rel;files[str(path.relative_to(PROJ))]=sha(path)
    pins=dict(schema='A8POST5_DEPENDENCY_PINS_V1',files=dict(sorted(files.items())),exact_ast=old['exact_ast'],
        consumer_root=str(FILL_ROOT),consumer_round=FILL_ROUND,consumer_inventory_sha256=sha(FILL_ROOT/'CODE_INVENTORY_SHA256.json'),
        consumer_leaf_count=len(inventory),consumer_receipts={rel:sha(FILL_ROOT/rel) for rel in sorted(set(receipts))},
        ancestor_pin_manifest=dict(path=str(AP/'a8post4/DEPENDENCY_PINS.json'),sha256=sha(AP/'a8post4/DEPENDENCY_PINS.json')))
    write(ROOT/'DEPENDENCY_PINS.json',pins)
    plan=json.loads((AP/'a8post4/T5_ROWS.json').read_text())
    plan['schema']='A8POST5_T5_ROW_PLAN_V1'
    own=[*sorted((ROOT/'code').glob('*.py')),*sorted((ROOT/'tests').glob('*.py')),
         *[ROOT/name for name in ('SPEC.md','HOST_RUN.md','DEPENDENCY_PINS.json','DEPENDENCY_REFRESH.json','EXPECTED_TEST_CASES.json','G05_CLASSIFICATION.json','G05_INTERFACE_SCHEMAS.json','G05_FILL_INTERFACE_REQUEST.md')]]
    plan['current_metadata_rows']=[dict(path=str(PROJ/rel),sha256=digest,role='PINNED_DEPENDENCY_METADATA') for rel,digest in pins['files'].items()]
    plan['current_metadata_rows'] += [dict(path=str(p),sha256=sha(p),role='AP5_OWN_METADATA') for p in own]
    for row in plan['future_exact_path_rows']:
        row['path']=row['path'].replace('/a8post4/','/table_inputs/').replace('A8POST4_CODE_FREEZE','A8POST5_CODE_FREEZE')
        row['role']=row['role'].replace('AP4','AP5').replace('validation_group_8','FILL')
        if row['role'] in ('FILL_FREEZE','FILL_ACCEPTANCE'):row['path']=str(FILL_ROOT/Path(row['path']).name)
    for row in plan['future_runtime_identity_roles']:
        row['role']=row['role'].replace('validation_group_8','FILL').replace('AP4','AP5')
        row['required_rule']=row['required_rule'].replace('context.validation_group_8_table_plan','context.table_plan').replace('AP4','AP5').replace('validation_group_8',FILL_ROUND)
    plan['future_runtime_identity_roles'][0]['required_rule']='context.table_plan exact path/SHA directly in genuine T5; prescore native descriptors retain exact T5 bytes. Dynamic nonprimary native authorities are separately verified POSTscore, never retroactively T5-listed.'
    plan['postscore_only_roles'] += ['AP5_NATIVE_SUPPLEMENT_AUTHORITY','AP5_FULL_NATIVE_K8_RECEIPT','AP5_SPECIFIED_SUPPLEMENT_PLAN_NUMERIC_BINDINGS','AP5_EXPANDED_TABLE_PLAN_POSTSCORE']
    plan['input_checks']='Candidate only. Dynamic native numeric timestamp_checks/reader outputs never enter historic T5. Own T5_ROWS hash is covered directly by the future freeze inventory (no selfhash). Single table_input_hash.py controls the active consumer round; prepare refreshes current inventory/paths before the next authorized suite.'
    write(ROOT/'T5_ROWS.json',plan)
    return pins

if __name__=='__main__':print(json.dumps(dict(state='CANDIDATE_METADATA_ONLY',dependencies=len(prepare()['files']))))
