'Inspect source ASTs and check saved timestamp tokens offline.'
import ast,hashlib,json,os,resource,stat,subprocess
from pathlib import Path
HERE=Path(__file__).absolute().parent;AF=HERE.parent;PROJ=AF.parents[3];Q=PROJ/'studies'


def identity(path):
    p=Path(path).absolute()
    assert not {'host_state','state','predictions','scores','models','outcomes'}.intersection(p.parts)
    assert not p.name.startswith(('SEAL','SCORE_RECEIPT'))
    assert not any(x.is_symlink() for x in (p,*p.parents))
    reference_snapshot=p.stat();assert stat.S_ISREG(reference_snapshot.st_mode)
    data=p.read_bytes();after=p.stat()
    assert (reference_snapshot.st_dev,reference_snapshot.st_ino,reference_snapshot.st_size,reference_snapshot.st_mtime_ns,reference_snapshot.st_ctime_ns)==(after.st_dev,after.st_ino,len(data),after.st_mtime_ns,after.st_ctime_ns)
    return dict(path=str(p),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())

def read(path):identity(path);return json.loads(Path(path).read_bytes())
def write(name,value):(HERE/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def resources():
    p=subprocess.run(['/usr/bin/memory_pressure','-Q'],capture_output=True,text=True,check=True)
    free=int(p.stdout.split('System-wide memory free percentage:')[1].split('%')[0])
    nice=os.getpriority(os.PRIO_PROCESS,0);rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    scratch=sum(p.stat().st_size for p in Path('/private/tmp').glob('af_scoring_*.py') if p.is_file() and not p.is_symlink())
    assert nice==20 and free>=25 and rss<1500000000 and scratch<1000000000
    return dict(nice=nice,memory_free_percent=free,peak_rss_bytes=rss,processes=1,scratch_bytes=scratch,phase='prepare')

def inventory(p):
    blob=p.read_bytes();tree=ast.parse(blob);compile(tree,str(p),'exec')
    callables=[]
    for n in ast.walk(tree):
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
            callables.append(dict(name=n.name,line=n.lineno,signature=ast.unparse(n.args),
                ast_sha256=hashlib.sha256(ast.dump(n,include_attributes=False).encode()).hexdigest(),
                helpers=sorted({ast.unparse(c.func) for c in ast.walk(n) if isinstance(c,ast.Call)})))
    return dict(identity=identity(p),module_ast_sha256=hashlib.sha256(ast.dump(tree,include_attributes=False).encode()).hexdigest(),
        callables=callables,imports=sorted({ast.unparse(n) for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom))}))

def node(p,name):return next(n for n in ast.walk(ast.parse(p.read_bytes())) if isinstance(n,ast.FunctionDef) and n.name==name)

def main():
    assert os.environ.get('SCORING_PHASE','prepare')=='prepare';checks=[resources()]
    old=read(HERE/'ADOPTION_CHECK.json')
    for row in old['authors_and_dec13']:assert identity(row['path'])==row
    adopted=identity(old['adopted_decision']['path']);manifest=identity(old['adoption_manifest']['path'])
    assert adopted==old['adopted_decision'] and manifest==old['adoption_manifest']
    assert adopted['sha256']=='fe334d6df5fff7672b19d9a1daced81cdaac0e874a5ca53b4e016da6bad454df'
    assert manifest['sha256']=='75078b8f23f0ffe30dc2b5974c4afc2b7b79de7819824cfe9a92cab9b1fff3bc'
    line=old['bound_line'];assert line in Path(manifest['path']).read_text().splitlines() and line.split()[0]==adopted['sha256']
    token_verification=[]
    for evidence in old['tsa_offline_verification']:
        assert identity(evidence['token']['path'])==evidence['token']
        cmd=evidence['command'];assert cmd[:3]==['/opt/homebrew/bin/openssl','ts','-verify']
        result=subprocess.run(cmd,cwd=evidence['cwd'],capture_output=True,text=True)
        assert result.returncode==0 and 'Verification: OK' in result.stdout
        token_verification.append(dict(command=cmd,exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr,token=evidence['token']))

    reference_snapshot=read(AF/'availability_delays/VALIDATION_FORECAST_BINDING9/SOURCE_AT_TASK_START.json');history={};drift=[]
    for label,key in [('T4F47','historical_T4F'),('OV1_25','all_OV1_files')]:
        history[label]={}
        for rel,expected in reference_snapshot[key].items():
            actual=identity(expected['path']);assert actual==expected
            history[label][rel]=dict(expected=expected,current=actual,bytes_identical=True)
    pre=read(AF/'availability_delays/VALIDATION_FORECAST_BINDING9/SOURCE_PREFLIGHT_FINAL.json')
    parent=pre['source_inventory'];assert len(parent)==27
    for rel,pin in parent.items():assert identity(pin['path'])==pin
    write('HISTORICAL_BYTE_CHECK.json',dict(schema='AF_SCORING_HISTORICAL_BYTE_CHECK_V2',groups=history,OV2_27=parent,
        files_checked=99,byte_identical=True,drift=drift,historical_is_not_final=True,numerical_tests_run=0))
    speed=pre['speed_overlay_binding'];speed_checks={}
    for kind in ('source_inventory','evidence_inventory'):
        speed_checks[kind]={}
        for name,pin in speed[kind].items():assert identity(pin['path'])==pin;speed_checks[kind][name]=pin
        checks.append(resources())
    assert len(speed['source_inventory'])==35 and len(speed['evidence_inventory'])==42
    write('SELECTED_SPEED_INVENTORY.json',dict(schema='AF_SCORING_SELECTED_SPEED_STATIC_INVENTORY_V2',inherited_binding=speed,
        current_rehashed=speed_checks,production_authority=False,new_speed_measurement=False,numerical_tests_run=0))
    inherited=read(HERE/'INHERITED_SOURCE_PINS.json')['files'];c=read(HERE/'C_INTERFACE_SOURCE_PINS.json')['files']
    croot=Q/'batch_estimation/batch_checks/statistics'
    for rel,pin in inherited.items():assert identity(PROJ/rel)==pin
    for rel,pin in c.items():assert identity(croot/rel)==pin

    archived=read(HERE/'PREPARE_CONTINUATION_HISTORY.json')

    for name,pin in archived['files'].items():
        actual=identity(HERE/'HISTORY_PREPARE_1'/name)
        assert {k:actual[k] for k in ('bytes','sha256')}==pin
    old_manifest=read(HERE/'HISTORY_PREPARE_1/DELIVERY_MANIFEST.json')
    archived_rows={p.relative_to(HERE/'HISTORY_PREPARE_1').as_posix():identity(p) for p in (HERE/'HISTORY_PREPARE_1').rglob('*') if p.is_file()}

    spec=read(HERE/'SCIENTIFIC_ACCEPTANCE_SPEC.json');census=read(HERE/'TEST_CENSUS.json');migration=read(HERE/'SCIENTIFIC_TEST_MIGRATION.json')
    own_files=sorted([*HERE.glob('*.py'),*HERE.joinpath('tests').glob('*.py')]);own={p.relative_to(HERE).as_posix():inventory(p) for p in own_files}
    ids=[]
    for p in sorted(HERE.joinpath('tests').glob('test_*.py')):
        t=ast.parse(p.read_bytes())
        for cls in sorted([n for n in t.body if isinstance(n,ast.ClassDef)],key=lambda n:n.name):
            ids.extend(f'{p.stem}.{cls.name}.{n.name}' for n in sorted([n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')],key=lambda n:n.name))
    assert ids==census['own_test_ids'] and len(ids)==spec['own_count']==133
    assert len(spec['test_ids'])==len(set(spec['test_ids']))==330 and spec['test_ids']==ids+migration['retained_test_ids']
    assert spec['task_revision']=='AF9_statistics_V3'
    repair=read(HERE/'prepare_set_AFREV8/BEFORE_SOURCE_INVENTORY.json')
    for rel,pin in repair['files'].items():
        actual=identity(HERE/'prepare_set_AFREV8/reference_snapshot'/rel)
        assert {k:actual[k] for k in ('bytes','sha256')}==pin
    assert len(repair['files'])==54

    calls={}
    for rel in ('tests/test_interface_wiring.py','tests/test_campaign_stop.py','tests/run_acceptance.py'):
        tree=ast.parse((HERE/rel).read_bytes())
        calls[rel]=sorted({ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)})
    needed={'adapter.read_scientific_authority','root_mapping.current_mapping','root_mapping.verify_final_mapping',
            'source_inventory.record_final_source','source_inventory.verify_final_source','runtime_bridge.delay_freezer_provider',
            'provider.source_preflight','provider._source_association'}
    assert needed<=set(calls['tests/test_interface_wiring.py'])
    assert 'result_class' in calls['tests/test_campaign_stop.py']
    assert 'control_module.result_class' in calls['tests/run_acceptance.py']
    abort=node(HERE/'acceptance_control.py','abort')
    latch=next(n.lineno for n in ast.walk(abort) if isinstance(n,ast.Assign) and any(ast.unparse(t)=='self._stopped' for t in n.targets))
    save=next(n.lineno for n in ast.walk(abort) if isinstance(n,ast.Call) and ast.unparse(n.func)=='self.persist')
    assert latch<save
    ledger=node(HERE/'science_contract.py','clean_receipt')
    predicate=ast.unparse(ledger)
    assert "type(value.get('breaches')) is list" in predicate and "value['breaches'] == []" in predicate
    assert "value.get('campaign_stopped') is False" in predicate
    report=identity(HERE/'reviews/AFREV8/REPORT.md')
    control=dict(schema='AFREV8_PREPARE_REPAIR_STATIC_CONTROL_FLOW_V1',phase='prepare',
        state='SOURCE_PATHS_PRESENT_NOT_EXECUTED',review=report,findings_all_accepted=['R1','R2','R3'],
        calls=calls,required_native_wiring_calls=sorted(needed),sticky_latch_line=latch,persist_line=save,
        mandatory_ledger_predicate=predicate,exact_own_test_ids=ids,own_count=len(ids),
        archive_files_preserved=54,regression_runs=0,scientific_acceptance=None,production_authority=False)
    write('prepare_set_AFREV8/REPAIR_STATIC_CONTROL_FLOW.json',control)
    assert len(migration['ports'])==41 and migration['mixed_test_migrations_pending']==0
    assert set(p['old_id'] for p in migration['ports'])==set(x['id'] for x in census['inherited_case_migration'] if x['migration']=='PORT_SCIENTIFIC_METADATA_REMOVE_WHOLE_WRITING')
    assert all(set(p['new_or_retained_test_ids'])<=set(spec['test_ids']) for p in migration['ports'])
    assert not list(HERE.glob('VALIDATION_SCORING/**/SCIENTIFIC_ACCEPTANCE_RECEIPT.json'))
    for name in ('validate_activation','extend_activity_guard'):
        assert ast.dump(node(HERE/'forecast_wrapper.py',name),include_attributes=False)==ast.dump(node(AF/'availability_delays/forecast_wrapper.py',name),include_attributes=False)
    b=(AF/'freeze_forecast_binding.py').read_bytes();token=b"OUT/'CODE_FREEZE.json'";assert b.count(token)==2 and b.replace(token,b'SCI_CODE_FREEZE').replace(b'SCI_CODE_FREEZE',token)==b
    writing=[]
    for name,entry in own.items():
        for imp in entry['imports']:
            if any(s in imp.lower() for s in ('table_results','tables','consumer_scope','k8')):writing.append([name,imp])
    assert not writing
    dependencies={rel:inventory(PROJ/rel) for rel,pin in inherited.items() if rel.endswith('.py')}
    c_ast={rel:inventory(croot/rel) for rel in c if rel.endswith('.py')}
    write('CALLABLE_AST_HELPER_INVENTORY.json',dict(schema='AF_SCORING_AST_HELPER_CLOSURE_V2',own=own,inherited=dependencies,
        C_native=c_ast,ast_compile_only=True,test_modules_imported=0,dynamic_runtime_edges_pending="NOT_RUN_PREPARE; independent source review and accept compatibility required",actual_numeric_functions_changed=False))
    write('PUBLIC_SOURCE_INVENTORY.json',dict(schema='AF_SCORING_PUBLIC_SOURCE_INVENTORY_V2',inherited=inherited,C_native=c,
        source_association_not_C_grant=True,old_af9_receipt_identity=pre['test_receipt'],historical_test_receipt_not_new_acceptance=True,
        actual_C_authority=None,actual_C_acceptance=None,actual_C_independent_review=None))
    checks.append(resources());write('STATIC_CHECK.json',dict(schema='AF_SCORING_PREPARE_STATIC_CHECK_V2',phase='prepare',
        state='READY_FOR_INDEPENDENT_REVIEW',resources=checks,syntax_ast_checked_files=len(own),inherited_callable_files=len(dependencies),
        C_callable_files=len(c_ast),own_test_methods=len(ids),retained_test_methods=197,ported_original_methods=41,full_acceptance_census=len(spec['test_ids']),
        numerical_test_runs=0,test_modules_imported=0,protected_contents_opened=0,real_locks_or_state_touched=False,host_executed=False,
        removed_writing_imports=writing,removed_roots_unavailable_dynamic_test='NOT_RUN_PREPARE',freeze=False,timestamp=False,
        refresh=False,publish=False,real_binding=False,actual_C_grant=False,scientific_acceptance='NOT_RUN_PREPARE',
        adoption=adopted,existing_dual_TSA_offline_verification=token_verification,historical_archive_leaf_count=len(archived_rows),
        AFREV8_review=report,AFREV8_review_verdict_preserved='SET FIRST',repair_source_ready_not_review_acceptance=True,
        repair_archive_files_preserved=54,repair_regressions_executed=0))
    print(json.dumps(dict(state='READY_FOR_INDEPENDENT_REVIEW',python_AST_compile_files=len(own),own_tests=len(ids),retained_tests=197,census=len(spec['test_ids']),
        numerical_tests_run=0,T4F_OV1_OV2_unchanged=99,selected_speed_sources=35,selected_speed_evidence=42,C_source_pins=len(c),resources=checks)))

if __name__=='__main__':main()
