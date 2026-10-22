'List Python source files and inspect their ASTs.'
import ast
import hashlib
import json
from pathlib import Path
import resource
import sys

HERE=Path(__file__).absolute().parent
PROJ=HERE.parents[4]
PARENT=HERE.parent

def _sha(payload):return hashlib.sha256(payload).hexdigest()
def _id(path):
    blob=path.read_bytes()
    return dict(path=str(path.relative_to(PROJ)),absolute_path=str(path),bytes=len(blob),sha256=_sha(blob))
def _dump(name,value):(HERE/name).write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def _ast_rows(path):
    blob=path.read_bytes();tree=ast.parse(blob);rows=[]
    def visit(body,prefix=''):
        for node in body:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                name=prefix+node.name
                rows.append(dict(name=name,line=node.lineno,end_line=node.end_lineno,
                    ast_sha256=_sha(ast.dump(node,include_attributes=False).encode()),
                    callable=ast.unparse(node.args) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) else None,
                    calls=sorted({ast.unparse(n.func) for n in ast.walk(node) if isinstance(n,ast.Call)}),
                    loaded_names=sorted({n.id for n in ast.walk(node) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load)})))
                if isinstance(node,ast.ClassDef):visit(node.body,name+'.')
    visit(tree.body)
    return dict(identity=_id(path),imports=[ast.unparse(n) for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom))],callables=rows)


def _expr(n,env):
    if isinstance(n,ast.Constant):return n.value
    if isinstance(n,ast.Name):return env[n.id]
    if isinstance(n,(ast.Tuple,ast.List,ast.Set)):
        value=[_expr(x,env) for x in n.elts]
        return tuple(value) if isinstance(n,ast.Tuple) else set(value) if isinstance(n,ast.Set) else value
    if isinstance(n,ast.Dict):return {_expr(k,env):_expr(v,env) for k,v in zip(n.keys,n.values)}
    if isinstance(n,ast.BinOp) and isinstance(n.op,ast.Add):return _expr(n.left,env)+_expr(n.right,env)
    if isinstance(n,ast.IfExp):return _expr(n.body if _expr(n.test,env) else n.orelse,env)
    if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in ('range','str'):
        return {'range':range,'str':str}[n.func.id](*[_expr(x,env) for x in n.args])
    raise ValueError('Non-static case-name expression: '+ast.dump(n))
def _registry(path,function):
    tree=ast.parse(path.read_bytes());env={};rows=[]
    for n in tree.body:
        if isinstance(n,ast.Assign):
            try:value=ast.literal_eval(n.value)
            except (ValueError,TypeError):continue
            for t in n.targets:
                if isinstance(t,ast.Name):env[t.id]=value
    if function=='Suite.run':
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Suite');fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='run')
    else:fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==function)
    def walk(body,values):
        for n in body:
            if isinstance(n,ast.For):
                for val in _expr(n.iter,values):
                    new=dict(values)
                    if isinstance(n.target,ast.Name):new[n.target.id]=val
                    elif isinstance(n.target,ast.Tuple):new.update({x.id:y for x,y in zip(n.target.elts,val)})
                    walk(n.body,new)
            elif isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and n.value.func.attr=='case':
                rows.append(dict(case_id=_expr(n.value.args[0],values),source=str(path.relative_to(PROJ)),line=n.lineno,
                                 original_case_call_ast_sha256=_sha(ast.dump(n,include_attributes=False).encode())))
    walk(fn.body,env);return rows

def main():
    audit=json.loads((PROJ/'paper_plan/nof12_path_20261009/INVENTORY.json').read_text())
    source_paths=[PROJ/x for x in audit['source_snapshots']]
    source_paths += [PARENT/x for x in ('runtime_sources.py','run_tests.py','tests_r8bpre.py','tests_g39.py')]

    source_delivery=PROJ/'comparison_inputs/scoring_inputs'
    source_paths += [source_delivery/x for x in ('INTERFACE_CONTRACT.json','INVENTORY.json','INVENTORY.sha256','CONTRACT_source.md','REPORT.md')]
    source_paths += sorted(p for p in HERE.rglob('*.py') if 'HISTORY_PREPARE_1' not in p.parts and 'reference_snapshot' not in p.parts)
    inventories={str(p.relative_to(PROJ)):_ast_rows(p) if p.suffix=='.py' else dict(identity=_id(p)) for p in dict.fromkeys(source_paths)}
    _dump('SOURCE_AST_HELPER_INVENTORY.json',dict(schema='C_SCORING_PREPARE_PUBLIC_AST_INVENTORY_V1',phase='prepare',production_authority=False,sources=inventories))

    lock=json.loads((HERE/'SOURCE_LOCK.json').read_text());drift=[]
    for field in ('sources','authorities'):
        for rel,row in lock[field].items():
            expected=row['identity'] if field=='sources' else row
            actual=_id(PROJ/rel)
            if any(actual[k]!=expected[k] for k in ('bytes','sha256')):drift.append(dict(path=rel,expected=expected,actual=actual))
    _dump('RETAINED_SOURCE_CHECK.json',dict(schema='C_SCORING_RETAINED_SOURCE_CHECK_V1',sources=len(lock['sources']),authorities=len(lock['authorities']),drift=drift,numerical_suite_runs=0))
    rows=_registry(PARENT/'run_tests.py','Suite.run')+_registry(PARENT/'tests_r8bpre.py','run')
    t=ast.parse((PARENT/'tests_g39.py').read_bytes());cls=next(n for n in t.body if isinstance(n,ast.ClassDef) and n.name=='RuntimeAuthorityTests')
    g39=[dict(case_id=n.name,source=str((PARENT/'tests_g39.py').relative_to(PROJ)),line=n.lineno,
               original_case_call_ast_sha256=_sha(ast.dump(n,include_attributes=False).encode())) for n in cls.body if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')]
    variants=('missing','unfrozen','schema','source_drift','freeze_drift','freeze_not_t5','source_not_t5','after_t5','equal_t5','missing_frozen_utc','non_utc','omitted','extra','duplicate','symlink','parent_symlink','dotdot','absolute','directory')
    for family in ('AP5','AP6','notice_delays','scoring_callback'):
        g39 += [dict(case_id='test_'+family+'_'+variant+'_refused',source=str((PARENT/'tests_g39.py').relative_to(PROJ)),line=772,original_case_call_ast_sha256=None) for variant in variants]
        g39 += [dict(case_id='test_'+family+'_drift_revokes_on_'+kind,source=str((PARENT/'tests_g39.py').relative_to(PROJ)),line=781,original_case_call_ast_sha256=None) for kind in ('import','public_read')]
    rows+=g39
    drop={'pinned_fill_shared_template_drift_table_results_templates.json','pinned_fill_shared_template_drift_main_comparisons_templates.json',
          'pinned_fill_shared_template_drift_fill2_templates.json','pinned_fill_authority_refusal_external_templates',
          'pinned_fill_authority_refusal_historical_proof'}
    mapping=[]
    for row in rows:
        case=row['case_id'];new=dict(row)
        if case in drop:
            new.update(disposition='REMOVE_WRITING_ONLY',reason='SCORING removes whole prose-template/abstract-proof identity completion, history retained',new_case_id=None)
        elif any(x in case for x in ('pinned_fill','literal_parity','FILL_CPS','pre_F12','AP_route_proposal','scorer_preparation')):
            new.update(disposition='SPLIT_RETAIN_SCIENCE',reason='Port original scientific/timestamp_checks/parity/refusal part to distinct scientific schema; remove whole FILL/prose/render obligation only',new_case_id='SCORING_PORT_'+case)
        else:
            new.update(disposition='RETAIN_SCIENTIFIC_OR_REFUSAL',reason='Keep same scientific or integrity/resource/operational refusal predicate, adapt artificial timestamp_checks fixture only',new_case_id='SCORING_RETAIN_'+case)
        mapping.append(new)
    if len(rows)!=len({r['case_id'] for r in rows}):raise RuntimeError('Duplicate inherited case IDs')
    _dump('SCIENTIFIC_REGRESSION_MIGRATION.json',dict(schema='C_SCORING_EXACT_REGRESSION_MIGRATION_V1',derived_without_running_tests=True,inherited_case_count=len(rows),removed_writing_case_count=len(drop),rows=mapping,port_status='C_SOURCE_PORT_IMPLEMENTED_NOT_RUN; OWNER_CONTRACTS_AND_ACCEPT_PENDING',old_PASS_not_transferred=True))
    extra=['failed_initial_view_validation_revokes_cached_graph','public_verified_score_payload_read_survives_T5_revalidation','score_namespace_extra_after_completion_revokes','fixture_restore_preserves_bound_science_graph','science_decision_exact_anchor_before_any_read','positive_scientific_release','distinct_original_R2_receipt_chains','original_always_separate_214_attachment',
           'R2_full214_before135_integrity','R2_all_arrays_masks_optional_pooled_same_view','R2_native_picks_and_HLN',
           'original_capture_before_R2','failed_original_or_capture_no_R2','failed_R2_no_readers','retry_never_repeat_successful_original',
           'actual_permit_missing_or_drifted','wrong_seal','wrong_view','old_receipt_as_R2_resume','missing_R2_marker',
           'R2_optional_old_anchor_refused','full_source_closure_without_writing_roots','full_scientific_slot_census',
           'G45_prefreeze_proposal_without_C_freeze','G45_missing_ancestor_or_review_refused','G45_no_public_consumer_grant',
           'G42_producer_self_certification_refused','G42_exact_nine_binding_13_receipt_native_pointer_contract',
           'original_numerical_ancestor_identity_gap_refused','no_C_AP_C_hash_cycle','review_all_files_bound',
           'no_historical_FULL_FILL_PASS_in_science_authority','unsealed_extra_R2_output','unverified_namespace_or_loader_refused',
           'prepare_runtime_entry_refused','accept_live_root_refused','delivered_tested_exact_bytes','resource_breach_checkpoints_and_stops']
    extra+=['public_postscore_requires_both_views','support_payload_before_both_views_refused',
            'official_certificate_drift_before_publication_refused','failed_view_revalidation_revokes_cached_completion']
    for role in ('science_authority','original_score','R2_score'):
        for variant in ('missing','unfrozen','drifted','unlisted','after_T5','extra','omitted','duplicate','alias','symlink','directory','wrong_seal','wrong_view'):
            extra.append(role+'_'+variant+'_refused')
    for family in ('AP5','AP6','notice_delays','scoring_callback'):
        extra+=['successor_'+family+'_declared_census_field_missing','successor_'+family+'_wildcard_refused']
    closure_tree=ast.parse((HERE/'tests_closure_evidence.py').read_bytes())
    closure_cases=ast.literal_eval(next(n.value for n in closure_tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CASES' for t in n.targets)))
    extra+=closure_cases
    isolator_tree=ast.parse((HERE/'tests_isolator_metadata.py').read_bytes())
    extra+=ast.literal_eval(next(n.value for n in isolator_tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CASES' for t in n.targets)))
    cases=[r['new_case_id'] for r in mapping if r['new_case_id']]+['SCORING_NEW_'+x for x in extra]
    if len(cases)!=len(set(cases)):raise RuntimeError('Duplicate new scientific case IDs')
    tested=['consumer_roots.py','runtime_sources.py','science_contract.py','review_gate.py','SOURCE_LOCK.json',
            'NUMERIC_ANCESTOR_PROPOSAL.json','SCIENTIFIC_FREEZE.schema.json','SCORER_CONTRACT.pending.json',
            'RUNTIME_FAMILY_POLICY.pending.json','SCIENTIFIC_ACCEPTANCE_SPEC.json','SCIENTIFIC_REGRESSION_MIGRATION.json',
            'SCIENCE_RULES.json','AP_ROUTE_INTERFACE.md',
            'tests_science.py','run_synthetic_checks.py']
    tested=sorted(set(tested)|{str(p.relative_to(HERE)) for p in HERE.rglob('*.py') if 'HISTORY_PREPARE_1' not in p.parts and 'reference_snapshot' not in p.parts}|{
        'ENTRY_CONTRACTS.pending.json','DISPATCH_REQUESTS.template.json','SCORER_BINDINGS.template.json','SCORER_METADATA.schema.json',
        'INHERITED_CASE_CALLBACKS.json','FIXTURE_PUBLIC_SOURCE_CENSUS.json','FREEZE_CENSUS.json','G45_BOOTSTRAP_PROPOSAL.md','G42_ELIGIBILITY_INTERFACE.md',
        'G42_ELIGIBILITY.pending.json','INDEPENDENT_REVIEW.template.json','SCIENTIFIC_CHAIN_EVIDENCE_CONTRACT.json'})
    tested=sorted(set(tested)|{name for name in ('RUNTIME_FAMILY_POLICY.json','ENTRY_CONTRACTS.json','SCORER_CONTRACT.json','G42_ELIGIBILITY_SOURCE_CONTRACT.json') if (HERE/name).is_file()})
    _dump('SCIENTIFIC_ACCEPTANCE_SPEC.json',dict(schema='C_SCORING_SCIENTIFIC_ACCEPTANCE_SPEC_V1',task_revision='SCORING_C8B_SCIENCE_V1',
        phase='prepare',state='SPECIFICATION_NOT_RUN',case_ids=cases,tested_source_files=tested,
        inherited_cases=len(rows),retained_or_ported_cases=len(cases)-len(extra),new_cases=len(extra),
        required_pending=['independently accepted same-version complete owner execution/helper/read relations; C input_checks evidence is not full numeric chain','four exact stable successor writers/censuses and callable SOURCE contracts','PCIMPL2/scoring_callback agreed finite fresh-state/permit/capture/request source contracts','G42 independent reviewer writer contract','separate source accept release'],
        resources=dict(nice=20,test_processes=1,memory_free_percent_min=25,scratch_bytes_max_exclusive=1000000000,peak_rss_bytes_max_inclusive=1610612736,periodic_check='before each case and within long numerical/parity sections; stop/checkpoint on any breach'),
        execution='source-only artificial fixture chain under /private/tmp; suites serialized; no production data or host scan',
        numerical_seams='unchanged original score and explicit R2 official_score, original native B2000 parity then B100000; C adds no statistic',
        acceptance_scope='C input_checks/parity/refusal census; full numeric chain additionally requires independent owner relations, never four PASS names',
        dependencies='removed writing roots unavailable, archival AST references only; all full numerical/operational/refusal gates active; unit premises separately disclosed',
        receipt_schema='C_statistics_ACCEPTANCE_V1',receipt_created=False,production_authority=False))

    old=ast.parse((PARENT/'consumer_roots.py').read_bytes());new=ast.parse((HERE/'consumer_roots.py').read_bytes())
    oc=next(n for n in old.body if isinstance(n,ast.ClassDef) and n.name=='Association');nc=next(n for n in new.body if isinstance(n,ast.ClassDef) and n.name=='Association')
    oldm={n.name:n for n in oc.body if isinstance(n,ast.FunctionDef)}
    names={'read','sha','identity','checked','write','contained','no_symlink_path','ConsumerModule','RoutedPath','RepinQPath','RepinQ'}
    class Normalize(ast.NodeTransformer):
        def visit_Attribute(self,node):
            if isinstance(node.value,ast.Name) and node.value.id=='runtime_sources' and node.attr in {'_Core','_RuntimeAuthorities'}:
                node.attr=node.attr[1:]
            return self.generic_visit(node)
        def visit_Name(self,node):
            if node.id.startswith('_') and node.id[1:] in names:node.id=node.id[1:]
            return node
    checks=[]
    for n in nc.body:
        if isinstance(n,ast.FunctionDef) and n.name in oldm:

            copy=Normalize().visit(ast.parse(ast.unparse(n)).body[0])
            checks.append(dict(name=n.name,original_ast_sha256=_sha(ast.dump(oldm[n.name],include_attributes=False).encode()),
                normalized_delivered_ast_sha256=_sha(ast.dump(copy,include_attributes=False).encode()),
                same_after_private_helper_name_mapping=ast.dump(oldm[n.name],include_attributes=False)==ast.dump(copy,include_attributes=False)))
    _dump('SCIENTIFIC_CORE_STATIC_PARITY.json',dict(schema='C_SCORING_ALPHA_RENAME_STATIC_PARITY_V1',helper_renames=sorted(names),methods=checks,scientific_test_run=False))
    print(json.dumps(dict(public_inventory_files=len(inventories),retained_source_drift=len(drift),inherited_cases=len(rows),new_science_cases=len(cases),static_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),sort_keys=True))

if __name__=='__main__':main()
