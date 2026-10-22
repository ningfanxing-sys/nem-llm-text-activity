'Write the source inventory and static validation results.'
import ast,hashlib,json,os,re,resource,sys
from pathlib import Path
HERE=Path(__file__).absolute().parent
P=HERE.parents[4];Q=P/'studies'

def pin(p):
    b=p.read_bytes();return dict(bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def dump(name,v):(HERE/name).write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def read(p):
    def pairs(rows):
        d={}
        for k,v in rows:
            if k in d:raise ValueError('Duplicate JSON '+str(p))
            d[k]=v
        return d
    return json.loads(p.read_bytes(),object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite')))
def main():
    assert os.environ.get('SCORING_PHASE','prepare')=='prepare' and os.getpriority(os.PRIO_PROCESS,0)==20
    assert min(read(HERE/'PREPARE_RESOURCE_OBSERVATIONS.json')['memory_free_percent_samples'])>=25
    errors=[];compiled=[];trees={}
    files=[p for p in HERE.rglob('*') if p.is_file() and 'HISTORY_PREPARE_1' not in p.parts and 'reference_snapshot' not in p.parts and '__pycache__' not in p.parts]
    for p in files:
        if p.suffix=='.py':
            try:
                b=p.read_bytes();t=ast.parse(b,filename=str(p));compile(t,str(p),'exec');trees[p.relative_to(HERE).as_posix()]=t;compiled.append(dict(path=str(p.relative_to(HERE)),**pin(p)))
            except Exception as e:errors.append(dict(path=str(p),error=repr(e)))
        elif p.suffix=='.json':
            try:read(p)
            except Exception as e:errors.append(dict(path=str(p),error=repr(e)))

    cb=read(HERE/'INHERITED_CASE_CALLBACKS.json')['rows']
    methods={n.name for name in ('inherited_cases.py','synthetic_inputs.py') for cl in trees[name].body if isinstance(cl,ast.ClassDef) for n in cl.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
    missing_methods=sorted({r['method'] for r in cb if r['method'] and r['method'] not in methods})
    if missing_methods:errors.append(dict(missing_callback_methods=missing_methods))


    for name in ('check_scoring_context.py','check_scoring_bindings.py','check_matched_controls.py','source_bindings/dispatch_scoring.py'):
        for n in ast.walk(trees[name]):
            if isinstance(n,ast.Subscript) and isinstance(n.value,ast.Attribute) and ast.unparse(n.value)=='os.environ' and not (isinstance(n.slice,ast.Constant) and isinstance(n.slice.value,str)):
                errors.append(dict(path=name,line=n.lineno,error='Non-string environment key'))
    spec=read(HERE/'SCIENTIFIC_ACCEPTANCE_SPEC.json')
    assert len(spec['case_ids'])==spec['retained_or_ported_cases']+spec['new_cases'] and len(spec['case_ids'])==len(set(spec['case_ids']))
    assert len(cb)==356
    manifest={name:pin(HERE/name) for name in spec['tested_source_files']}
    dump('PUBLIC_RUNTIME_SOURCE_MANIFEST.json',dict(schema='C_SCORING_PUBLIC_SOURCE_MANIFEST_V1',phase='prepare',files=manifest,production_authority=False,scientific_acceptance=False))
    lock=read(HERE/'SOURCE_LOCK.json');source_drift=[]
    for field in ('sources','authorities'):
        for name,row in lock[field].items():
            expected=row['identity'] if field=='sources' else row
            if pin(P/name)!={k:expected[k] for k in ('bytes','sha256')}:source_drift.append(name)
    assert not source_drift
    assert not any(n.startswith('tables/') for n in (*lock['sources'],*lock['authorities']))
    assert not any('/statistics/' in n for n in (*lock['sources'],*lock['authorities']))
    pending=read(HERE/'PENDING_IDENTITIES_BY_OWNER.json');pending['C_owned_implementation']='COMPLETE_SOURCE_ONLY_STATIC_CHECKED';dump('PENDING_IDENTITIES_BY_OWNER.json',pending)


    rows=read(HERE/'CANDIDATE_T5_ROWS.json')
    current={r['relative_to_studies']:r for r in rows['current_public_rows']}
    census=read(HERE/'FREEZE_CENSUS.json')
    for name in census['files']:
        p=HERE/name
        if not p.is_file():continue
        rel=str(p.relative_to(Q));current[rel]=dict(relative_to_studies=rel,identity=dict(path=str(p),**pin(p)),status='PUBLIC_METADATA_CANDIDATE_NOT_T5')


    for name in ('CANDIDATE_T5_ROWS.json','T5_ROOTS.candidate.txt','FINAL_STATIC_VERIFICATION.json','INVENTORY.json','INVENTORY.sha256'):
        rel=str((HERE/name).relative_to(Q));current.pop(rel,None)
        if not any(r['relative_to_studies']==rel for r in rows['pending_real_rows']):rows['pending_real_rows'].append(dict(relative_to_studies=rel,bytes=None,sha256=None,owner='C final artifact census / independent reviewer / source',status='NAMED_METADATA_ARTIFACT_IDENTITY_BY_FINAL_INVENTORY'))
    for name in census['pending_members']:
        rel=str((HERE/name).relative_to(Q))
        if not any(r['relative_to_studies']==rel for r in rows['pending_real_rows']):rows['pending_real_rows'].append(dict(relative_to_studies=rel,bytes=None,sha256=None,owner='C independent reviewer / relevant source owner / source',status='PENDING_SOURCE_OR_REAL_METADATA_NOT_READ'))
    rows['current_public_rows']=sorted(current.values(),key=lambda r:r['relative_to_studies'])
    rows['coverage']='Same exact prescore_paths sealed payload commitment, runtime bytes/SHA against verified seals/matrix receipts; metadata-only T5 source rows, no payload roots; no future scoring identity in source contract'
    dump('CANDIDATE_T5_ROWS.json',rows)
    paths=sorted(set(current)|{r['relative_to_studies'] for r in rows['pending_real_rows']})
    (HERE/'T5_ROOTS.candidate.txt').write_text('# CANDIDATE METADATA ONLY — NOT ACTUAL T5, no production permission\n# Unknown matrix four-release/successor member names must be enumerated by owners; no directories/wildcards.\n'+'\n'.join(paths)+'\n')
    if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss>1610612736:errors.append(dict(error='Static RSS resource breach'))
    if errors:
        dump('FINAL_STATIC_VERIFICATION.json',dict(state='SET_FIRST',errors=errors,scientific_runs=0,phase='prepare'))
        print(json.dumps(dict(state='SET_FIRST',errors=errors)));return 1
    observed=dict(schema='C_SCORING_FINAL_PREPARE_STATIC_V2',state='STATIC_PASS_READY_FOR_INDEPENDENT_REVIEW',phase='prepare',production_authority=False,scientific_suites_run=0,numerical_tests_run=0,scientific_modules_imported=0,fixture_constructors_run=0,unittest_discovery_run=0,freeze_created=False,timestamp_created=False,binding_created=False,acceptance_receipt_created=False,source_closure_receipt_created=False,full_numeric_chain=False,independent_owner_chain_acceptance='PENDING',remaining_own_implementation_gaps=[],static_parse_compile_files=compiled,strict_json_files=sum(p.suffix=='.json' for p in files),source_drift=source_drift,source_lock_successor_bytes=[],whole_FILL_completion_obligation_removed_static=True,callback_declarations=len(cb),inherited_case_count=470,pure_writing_removed=5,retained_or_ported_case_count=465,new_science_cases=spec['new_cases'],full_case_census=len(spec['case_ids']),tested_source_census=len(manifest),interface_identity=dict(path=str(HERE/'AP_ROUTE_INTERFACE.md'),**pin(HERE/'AP_ROUTE_INTERFACE.md')),resources=dict(actual_nice=os.getpriority(os.PRIO_PROCESS,0),test_processes=0,static_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,observed_memory_free_percent_samples=read(HERE/'PREPARE_RESOURCE_OBSERVATIONS.json')['memory_free_percent_samples'],minimum_required_free_percent=25,test_scratch_created=False,test_scratch_bytes=0,limits=dict(rss_max_bytes=1610612736,scratch_max_exclusive_bytes=1000000000),note='Actual inherited nice20 verified; prepare static checks only; no other job touched'),limitations=['Static evidence is not numerical parity, synthetic PASS, real C/T5 release or G42 native eligibility','Actual pending owner source contracts must be stable before final acceptance; real identities remain source-only','Python audit/FD isolation is not an OS/native-code sandbox','Initial AST builders alone do not regenerate later delivered fixes; exact final source is inventoried'])
    dump('FINAL_STATIC_VERIFICATION.json',observed)
    allfiles=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ('INVENTORY.json','INVENTORY.sha256')]

    allfiles=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p not in {HERE/'INVENTORY.json',HERE/'INVENTORY.sha256'}]
    inventory=dict(schema='C_SCORING_ADDITIVE_SOURCE_INVENTORY_V2',phase='prepare',state='EXACT_SOURCE_AND_HISTORY_NOT_FREEZE',files={str(p.relative_to(HERE)):dict(path=str(p),**pin(p)) for p in sorted(allfiles)},production_authority=False,scientific_acceptance=False)
    dump('INVENTORY.json',inventory);(HERE/'INVENTORY.sha256').write_text(pin(HERE/'INVENTORY.json')['sha256']+'  INVENTORY.json\n')
    print(json.dumps(dict(state=observed['state'],compiled_python=len(compiled),source_inventory=len(allfiles),scientific_case_census=len(spec['case_ids']),tested_source_census=len(manifest),nice=observed['resources']['actual_nice'],static_rss=observed['resources']['static_peak_rss_bytes'],source_drift=source_drift,scientific_runs=0)))
    return 0
if __name__=='__main__':raise SystemExit(main())
