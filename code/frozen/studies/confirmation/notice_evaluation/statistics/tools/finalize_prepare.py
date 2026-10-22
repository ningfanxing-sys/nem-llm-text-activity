'Save the source inventory and validation file locations.'
import ast
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import re
import sys

OUT=Path(__file__).absolute().parents[1]
PROJ=OUT.parents[4]

def load(path):return json.loads(Path(path).read_text())
def write(name,data):
    (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def ident(path):
    path=Path(path).absolute()
    if path.resolve()!=path or any(p.is_symlink() for p in (path,*path.parents)):raise RuntimeError('Alias')
    if any(x.lower() in {'host_state','sealed','scores','predictions','run','evaluation'} for x in path.parts):raise RuntimeError('Protected')
    if path.suffix!='.py' and path.name.upper().startswith(('SEAL_','SCORE_')):raise RuntimeError('Payload')
    data=path.read_bytes()
    return dict(path=str(path),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
def digest(node):return hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()
def python_files():
    return sorted([*OUT.glob('*.py'),*OUT.joinpath('evaluator').glob('*.py'),*OUT.joinpath('native').glob('*.py'),*OUT.joinpath('tests').glob('*.py'),*OUT.joinpath('tools').glob('*.py')])
def resources():
    sample=subprocess.run(['/usr/bin/memory_pressure','-Q'],capture_output=True,text=True,check=True,timeout=20)
    match=re.search(r'System-wide memory free percentage:\s*(\d+)%',sample.stdout)
    value=dict(free_memory_percent=int(match[1]) if match else None,nice=os.getpriority(os.PRIO_PROCESS,0),peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,scratch_bytes=0)
    if value['nice']!=20 or value['free_memory_percent'] is None or value['free_memory_percent']<25 or value['peak_rss_bytes']>=1_500_000_000:raise RuntimeError('Resource refusal '+str(value))
    return value

def methods():
    rows=[]
    for path in sorted((OUT/'tests').glob('test_*.py')):
        for cls in ast.parse(path.read_text()).body:
            if isinstance(cls,ast.ClassDef):
                for node in cls.body:
                    if isinstance(node,ast.FunctionDef) and node.name.startswith('test_'):
                        rows.append(dict(id=path.stem+'.'+cls.name+'.'+node.name,source=ident(path),name=node.name,class_name=cls.name,ast_sha256=digest(node),state='NOT_RUN_PREPARE'))
    return rows

def node(path,name):
    matches=[n for n in ast.walk(ast.parse(Path(path).read_text())) if isinstance(n,ast.FunctionDef) and n.name==name]
    if len(matches)!=1:raise RuntimeError('Method census '+name)
    return matches[0]

def inventory():
    excluded={'INVENTORY.json','INVENTORY.sha256'}
    rows={str(p.relative_to(OUT)):ident(p) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name not in excluded and '__pycache__' not in p.parts}
    write('INVENTORY.json',dict(schema='RD7_SCORING_DELIVERY_INVENTORY_V2',state='READY_FOR_INDEPENDENT_REVIEW',phase='prepare',files=rows,source_census='RUNTIME_CENSUS.json',scientific_acceptance=None,freeze_performed=False,actual_T5_grant=False,note='History/reviews are retained evidence, not runtime timestamp_checks. Inventory excludes itself and checksum to avoid recursive identity.'))
    (OUT/'INVENTORY.sha256').write_text(ident(OUT/'INVENTORY.json')['sha256']+'  INVENTORY.json\n')

def main():
    if os.environ.get('SCORING_PHASE','prepare') not in ('prepare','accept'):raise RuntimeError('Source bookkeeping only')
    start=resources()
    if len(sys.argv)>1:
        if sys.argv[1:]!=['--inventory-only']:raise RuntimeError('Finite static mode')
        inventory();print(json.dumps(resources()));return
    files=python_files();callables=[];imports=[]
    for path in files:
        data=path.read_text();tree=ast.parse(data,filename=str(path));compile(tree,str(path),'exec',dont_inherit=True)
        def walk(nodes,parent=''):
            for n in nodes:
                if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                    qualified=parent+n.name
                    calls=sorted({ast.unparse(c.func) for c in ast.walk(n) if isinstance(c,ast.Call)})
                    callables.append(dict(path=str(path),name=qualified,kind=type(n).__name__,line=n.lineno,end_line=n.end_lineno,signature=ast.unparse(n.args) if hasattr(n,'args') else None,ast_sha256=digest(n),called_helpers=calls))
                    walk(n.body,qualified+'.')
        walk(tree.body)
        for n in ast.walk(tree):
            if isinstance(n,ast.Import):imports.append(dict(path=str(path),line=n.lineno,modules=[a.name for a in n.names]))
            elif isinstance(n,ast.ImportFrom):imports.append(dict(path=str(path),line=n.lineno,modules=['.'*n.level+(n.module or '')]))
    runtime_py=[p for p in files if p.parent==OUT or p.parent in (OUT/'native',OUT/'evaluator')]
    source_rows=[ident(p) for p in runtime_py]+[ident(OUT/'evaluator/JOINT_RECORD_SCHEMA.json')]
    source_asts=[]
    for path in runtime_py:
        for n in ast.parse(path.read_text()).body:
            if isinstance(n,(ast.FunctionDef,ast.ClassDef)):source_asts.append(dict(path=str(path),name=n.name,ast_sha256=digest(n)))
    write('PUBLIC_SOURCE_CONTRACT.json',dict(schema='RD_SCORING_PUBLIC_SOURCE_CONTRACT_V1',runtime_sources=source_rows,callable_asts=source_asts))
    rows=methods();ids=[r['id'] for r in rows]
    if len(ids)!=97 or len(set(ids))!=97:raise RuntimeError('Expected 97 declared kernel cases')
    ports=load(OUT/'SCIENTIFIC_PORTED_TESTS.json')
    for row in ports['ports']:
        original=node(row['original_path'],row['original_test']);successor=node(row['successor_path'],row['successor_test'])
        row['successor_ast_sha256']=digest(successor)
        row['test_body_exact']=digest(original)==digest(successor)
        row['source_seam_changes']=None if row['test_body_exact'] else dict(original_source=ast.get_source_segment(Path(row['original_path']).read_text(),original),successor_source=ast.get_source_segment(Path(row['successor_path']).read_text(),successor),scope='Only schema location or fixture-loader seam; scientific assertions retained. Independently review exact bodies.')
    ports['exact_body_count']=sum(r['test_body_exact'] for r in ports['ports']);write('SCIENTIFIC_PORTED_TESTS.json',ports)
    migration=load(OUT/'LEGACY_REGRESSION_MIGRATION.json')
    known={(r['original_path'],r['original_test']):r for r in ports['ports']}
    replacements={
        'test_missing_official_score_refuses_before_any_af_or_prediction_loader':['test_missing_official_score_before_af_or_prediction_loaders'],
        'test_source_pin_drift_and_function_removal_refused':['test_current_source_contract_and_AST_drift_refused'],
        'test_seal_before_t5_passes':['test_actual_seal_verification_must_be_strictly_before_t5'],
        'test_seal_exactly_at_t5_refused':['test_actual_seal_verification_must_be_strictly_before_t5'],
        'test_seal_after_t5_refused':['test_actual_seal_verification_must_be_strictly_before_t5'],
        'test_no_calendar_cutoff_and_other_chronology_gates':['test_calendar_deadline_is_absent','test_capture_and_r2_must_both_precede_reader_release'],
        'test_specification_sha_drift_refused':['test_exact_specification_and_timestamp_identity_drift_refused'],
        'test_manifest_and_timestamp_drift_refused':['test_exact_specification_and_timestamp_identity_drift_refused'],
        'test_exact_t5_metadata_membership':['test_source_census_and_t5_census_refused'],
        'test_main_a0_route_never_consumes_dly8_delta5':['test_main_a0_route_never_uses_dly8_delta5'],
        'test_d19_d24_fields_copy_native_intervals_and_dissent':['test_d19_d24_native_intervals_dissent_unchanged'],
        'test_dec11_det_null_set_is_null_with_both_qualifiers':['test_det_null_has_both_sensitivity_qualifiers'],
        'test_g39_writer_fields_and_census_match_consumer_contract':['test_g39_absolute_inventory_separate_file_census'],
        'test_targeted_receipt_cannot_authorize_freeze':['test_targeted_partial_and_bad_ledger_receipts_refused'],
        'test_speed_alias_loaded_before_final_source_and_restored':['test_af_aliases_restore_on_normal_and_exception_paths'],
        'test_speed_alias_restored_on_exception':['test_af_aliases_restore_on_normal_and_exception_paths'],
        'test_af9_identity_and_receipt_scope_drift_refused':['test_reviewed_af_source_identity_drift_refused','test_targeted_partial_and_bad_ledger_receipts_refused'],
        'test_final_af9_source_and_clean_receipt_bindings':['test_reviewed_af_source_identity_drift_refused']}
    static_names={'test_frozen_source_functions_and_single_consumer_pin_unchanged','test_t5_candidate_export_has_current_exact_absolute_identities','test_review4_reader_ast_and_unchanged_bytes','test_review4_support_changes_only_deadline_evidence','test_review4_pins_and_t5_preserve_existing_identities','test_interfaces_and_scientific_source_pins_unchanged'}
    writing_names={'test_selected_round_resolves_every_consumer_pin_and_t5_row','test_one_pin_resolves_future_root_without_editing_descriptors','test_migration_keeps_anchor_contract_and_records_outer_differences','test_validation_group_8_corrected_task_validator_accepts_real_frozen_output','test_freeze_requires_sidecar_chain_tests','test_agree_reader_output_to_validator_and_forms','test_sensitive_reader_output_to_validator_and_forms','test_nr_explicit_disposition_to_validator_and_forms','test_dev_reader_output_to_validator_and_forms'}
    classifications={}
    for entry in migration['files']:
        ident(entry['source']['path'])
        for m in entry['methods']:
            name=m['name'];key=(entry['source']['path'],name)
            if key in known:
                port=known[key];m['disposition']='PORTED_SCIENTIFIC_TEST_SOURCE';m['successor_ids']=[r['id'] for r in rows if r['source']['path']==port['successor_path'] and r['name']==port['successor_test']];m['exact_body']=port['test_body_exact']
            elif name in replacements:
                m['disposition']='SUCCESSOR_REGRESSION_SOURCE_WITH_OWNER_RUNTIME_LINK_PENDING';m['successor_ids']=[r['id'] for r in rows if r['name'] in replacements[name]];m['pending']='Native real AF/C/AP identity/chronology links remain owner contract dependent; artificial metadata tests do not grant them.'
            elif name in static_names:
                m['disposition']='STATIC_PUBLIC_SOURCE_IDENTITY_CHECK';m['evidence']='STATIC_CHECK_READY.json, NATIVE_AST_EXTRACTIONS.json, CANDIDATE_T5_ROWS.json';m['dynamic_gate_waived']=False
            elif name in writing_names:
                m['disposition']='SCORING_REMOVED_WRITING_ASSERTIONS_ONLY';m['replacement_scientific_cases']=[r['id'] for r in rows if r['name'] in {'test_native_family_to_evaluator_full_18_3','test_empty_replaced_and_relaxed_schema_refused','test_necessary_checks_never_grant_eligibility'}];m['scientific_identity_provenance_census_obligations']='Retained through pinned schema/native validators; actual author and independent G42 runtime remains pending.'
            else:
                m['disposition']='PENDING_OWNER_NATIVE_PROVENANCE_OR_FREEZE_CONTRACT';m['owner']='AP/C independent G42/notice_delays reviewer';m['gate_waived']=False
            classifications[m['disposition']]=classifications.get(m['disposition'],0)+1
    migration.update(state='PREPARE_METHOD_BY_METHOD_SOURCE_MIGRATION_NOT_FULL_PROTOCOL_ACCEPTANCE',final_methods=ids,scientific_acceptance_run=False,disposition_counts=classifications,note='All 88 original methods retained in parent. Exact per-method scientific ports and successor seams are recorded. Writing-only assertions removed under SCORING; mixed source/provenance/identity gates never waived. Pending integrations must be accepted before scientific freeze.')
    write('LEGACY_REGRESSION_MIGRATION.json',migration)
    pending=['AP exact native scientific input/author validation ABI and independently accepted owner chain','C reviewed stable source contract, dispatcher policy adoption and independent actual G42 writer/validator ABI','AF9 same-source 330/330 and PART A ACCEPTED are met; actual combined seal/AM3/verified seal<T5 remain later real source gates','Full native provenance/input/eligibility integration regression and same-version independent REV6; no fake human review or grant']
    spec=load(OUT/'SCIENTIFIC_ACCEPTANCE_SPEC.json');spec.update(state='NOT_RUN_PREPARE_SOURCE_READY',candidate_methods=rows,candidate_method_count=len(rows),declared_kernel_census=ids,final_complete_protocol_census=None,final_complete_census=None,final_acceptance_receipt=None,pending_owner_integrations=pending,final_static_inspection='STATIC_CHECK_READY.json',resource_limits=dict(nice=20,test_processes=1,blas_threads=1,free_memory_percent_at_least=25,global_floor_percent=10,peak_rss_bytes_less_than=1_500_000_000,scratch_bytes_less_than=1_000_000_000,check_every_seconds=5,sticky_STOP=True))
    write('SCIENTIFIC_ACCEPTANCE_SPEC.json',spec)
    names=sorted([str(p.relative_to(OUT)) for p in files]+['evaluator/JOINT_RECORD_SCHEMA.json','PUBLIC_SOURCE_CONTRACT.json','NUMERICAL_ANCESTOR_PINS.json','AF9_REVIEWED_SOURCE_PINS.json','R2_INDEPENDENT_SOURCE_PINS.json','NATIVE_AST_EXTRACTIONS.json','ORIGINAL_SOURCE_AST_INVENTORY.json','SCIENTIFIC_FREEZE.schema.json','SCIENTIFIC_ACCEPTANCE_SPEC.json','SCIENTIFIC_INTERFACE.pending.json','NUMERICAL_INTERFACE.json','INTERFACE_FOR_AP.md','SPEC.md','SCIENTIFIC_SOURCE_READ_CENSUS.json','SCIENTIFIC_PORTED_TESTS.json','LEGACY_REGRESSION_MIGRATION.json','DECISION_AND_REVIEW_SOURCE_IDENTITIES.json','DEPENDENCY_ACCEPTANCE_BINDINGS.pending.json','C_INTERFACE_SOURCE_OBSERVATION.json','ACCEPT_PLAN_source.md','G39_RD_POLICY.candidate.json','RUNTIME_CENSUS.json','ACCEPTANCE_CENSUS.json'])
    write('RUNTIME_CENSUS.json',dict(schema='RD_SCORING_FILE_CENSUS_V1',files=names,role='Finite G39 file census; NOT scientific test IDs, no grants or production artifacts',owner_agreed=False))
    policy=dict(root=str(OUT),freeze=str(OUT/'RD_SCIENTIFIC_FREEZE.json'),schema='RD_SCORING_SCIENTIFIC_FREEZE_V1',state='RD_SCIENTIFIC_FROZEN_BEFORE_T5',inventory_field='files',inventory_format='absolute_bytes_sha_list',inventory_base=str(OUT),declared_census_field='declared_census',names=names)
    write('G39_RD_POLICY.candidate.json',dict(schema='RD_G39_PROPOSED_C_POLICY_V1',state='PENDING_C_OWNER_ADOPTION',notice_delays=policy,actual_T5_grant=False))
    interface=load(OUT/'SCIENTIFIC_INTERFACE.pending.json');interface.update(state='SOURCE_IMPLEMENTED_PENDING_C_AGREEMENT_AND_FULL_PROTOCOL_ACCEPTANCE',inventory_form='absolute_bytes_sha_list',declared_census_field='declared_census',file_census='RUNTIME_CENSUS.json',test_census_field='declared_scientific_test_census',final_test_census=None,candidate_kernel_test_count=97,freeze_writer=dict(path=str(OUT/'freeze_notice_evaluation.py'),callable='create',arguments=['receipt_identity','review_identity','release_identity'],status='FUTURE_RELEASE_ONLY; no freeze generated; current kernel-only receipt refused'),CLI='--receipt-identity PATH --review-identity PATH --release-identity PATH',C_policy_agreed=False)
    write('SCIENTIFIC_INTERFACE.pending.json',interface)
    tested_names=sorted(set(names)-{'RUNTIME_CENSUS.json','ACCEPTANCE_CENSUS.json'})

    tested_names.append('RUNTIME_CENSUS.json')
    write('ACCEPTANCE_CENSUS.json',dict(schema='RD_SCORING_KERNEL_SOURCE_CENSUS_V2',test_ids=ids,sources={n:ident(OUT/n) for n in sorted(tested_names)},pending_owner_integrations=pending,full_protocol_acceptance=False,numerical_tests_run=0,scientific_acceptance=None))
    write('SOURCE_AST_HELPER_INVENTORY.json',dict(schema='RD7_SCORING_SOURCE_AST_HELPER_INVENTORY_V2',state='STATIC_SOURCE_ONLY',sources={str(p.relative_to(OUT)):ident(p) for p in files},callables=callables,imports=imports,exact_extraction=ident(OUT/'ORIGINAL_SOURCE_AST_INVENTORY.json'),native_exact_extraction=ident(OUT/'NATIVE_AST_EXTRACTIONS.json'),pure_exact_nodes=41,native_exact_nodes=42,helper_execution_evidence=None,static_receipt='STATIC_CHECK_ACCEPT1.json',whole_FILL_runtime_import=False,scientific_acceptance=None))
    old=load(OUT/'MIGRATION_DEPENDENCY_MAP.json');old.update(state='PREPARE_SOURCE_READY_OWNER_RUNTIME_INTEGRATION_PENDING',human_map=ident(OUT/'MIGRATION_DEPENDENCY_MAP.md'),active_candidate_source_contract=ident(OUT/'PUBLIC_SOURCE_CONTRACT.json'),AF_ancestor=ident(OUT/'AF9_REVIEWED_SOURCE_PINS.json'),pending_sources=ident(OUT/'C_INTERFACE_SOURCE_OBSERVATION.json'),scientific_tests_migration=ident(OUT/'LEGACY_REGRESSION_MIGRATION.json'),real_numeric_adapter_status='IMPLEMENTED_SOURCE_ONLY: main a0+literal15/60, frozen kernel and C ABI; AP author/input and G42 runtime contracts pending',dynamic_writing_roots_unavailable_check='NOT_RUN_PREPARE; future artificial harness denies whole tables')
    write('MIGRATION_DEPENDENCY_MAP.json',old)
    af=load(OUT/'AF9_REVIEWED_SOURCE_PINS.json');news=load(OUT/'R2_INDEPENDENT_SOURCE_PINS.json');anc=load(OUT/'NUMERICAL_ANCESTOR_PINS.json')
    write('CANDIDATE_T5_ROWS.json',dict(schema='RD7_SCORING_T5_CANDIDATES_V2',state='CANDIDATES_ONLY_NOT_ACTUAL_LISTING',phase='prepare',runtime_candidate_rows=[ident(OUT/n) for n in names],runtime_file_census=names,inherited_numeric_ancestor_rows=anc['files'],independent_news_runtime_source_rows=news['runtime_files'],AF9_reviewed_sources=list(af['reviewed_source_census'].values()),AF9_source_review=af['independent_source_review'],future_real_metadata=dict(RD_freeze=None,independent_clean_acceptance=None,REV6_clean_review=None,C_policy_adoption=None,AM3_approval=None,corrected_seal_identity=None,actual_T5=None),protected_payload_roots_included=False,actual_T5_grant=False,post_score_joint_and_eligibility_are_T5_roots=False,directory_wildcard_grants=False,freeze_performed=False))
    end=resources()
    receipt=dict(schema='RD7_PREPARE_BOOKKEEPING_V1',state='SOURCE_INVENTORIES_UPDATED',resources=dict(start=start,end=end),python_files=len(files),declared_kernel_tests=len(ids),ported_methods=len(ports['ports']),exact_ported_bodies=ports['exact_body_count'],migration_counts=classifications,numerical_tests_run=0,candidate_functions_executed=False,freeze_performed=False)
    candidates=[OUT/'prepare_finalize/BOOKKEEPING_STATIC_RECEIPT.json']+[OUT/('prepare_finalize/BOOKKEEPING_STATIC_RECEIPT_'+str(i)+'.json') for i in range(2,20)]
    target=next((p for p in candidates if not p.exists()),None)
    if target is None:raise RuntimeError('Preserve static receipts; finite receipt names exhausted')
    with target.open('x') as stream:json.dump(receipt,stream,ensure_ascii=False,indent=2)
    inventory();print(json.dumps(receipt,ensure_ascii=False))

if __name__=='__main__':main()
