'Write the source-file census used by validation.'
import ast,hashlib,json,os
from pathlib import Path
HERE=Path(__file__).absolute().parent
P=HERE.parents[4];Q=P/'studies'

def write(name,value):
    p=HERE/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text((json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n') if not isinstance(value,str) else value)
def identity(p):
    b=p.read_bytes();return dict(path=str(p),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def main():
    if os.environ.get('SCORING_PHASE','prepare')!='prepare':raise PermissionError('Documentation builder prepare only')
    if os.getpriority(os.PRIO_PROCESS,0)!=20:raise PermissionError('nice20 required')
    roles=dict(arm='scoring_callback',capture='scoring_callback',r2_complete='scoring_callback',ap5_science='AP5',ap6_joint='AP6',rd_joint='notice_delays',optional_loader='AP5',numeric_assembly='AP5',author_validation='AP5')
    args=dict(arm=['association','request'],capture=['association','request'],r2_complete=['association','original_capture','r2_receipt','r2_start_utc','r2_complete_utc','actual_permit_identity'],ap5_science=['association','request','argv','scientific_scope'],ap6_joint=['association','request','argv','scientific_scope'],rd_joint=['association','request','argv','scientific_scope'],optional_loader=['association','request','primary_tests','permit'],numeric_assembly=['association','args','kwargs','scientific_contract','author_validator'],author_validation=['OWNER_DECLARE_EXACT_VALIDATION_KWARGS'])
    if not (HERE/'UPSTREAM_PREPARE_ALIGNMENT.json').is_file():
        write('ENTRY_CONTRACTS.pending.json',dict(schema='C_SCORING_RUNTIME_ENTRIES_V1',status='PENDING_OWNER_DELIVERY',production_authority=False,entries={k:dict(family=v,status='PENDING',source=None,callable=None,keyword_contract=args[k]) for k,v in roles.items()}))
    scorer=json.loads((HERE/'SCORER_CONTRACT.pending.json').read_bytes())
    scorer['source_status']='R2_SOURCE_DELIVERY_ADOPT_READY_VERIFIED; OWNER_SCORER_PATHS_PENDING'
    scorer['status']='PENDING_AGREED_SOURCE_PATHS_CALLBACK_SCOPES_AND_ENTRIES'
    scorer['implementation']='scorer_adapter._run_r2; dispatch.py r2-score; original CLI unchanged'
    original=scorer['original'];original.update(seal_path=str(Q/'confirmation/execution/host_state/SEAL.json'),permit_path=None,receipt_identity=None,report_identity=None)
    r2=scorer['r2'];r2.update(feature_root=None,permit_path=None,receipt_identity=None,report_identity=None,
        argv_template=['SCORING_PHASE=source_runtime','/usr/bin/nice','-n','20',str(P.parent.parent/'.venv/bin/python'),'-B',str(HERE/'dispatch.py'),'r2-score','--project',str(P),'--request','<exact source-declared request>','--request-bytes','<actual bytes>','--request-sha256','<actual SHA>','--request-provenance','<detached verified request association>','--request-provenance-bytes','<actual bytes>','--request-provenance-sha256','<actual SHA>'],
        state_seal_association=dict(schema='C_SCORING_R2_STATE_SEAL_ASSOCIATION_V1',source_reviewed=False,resolution='EXACT_IN_PROCESS_ORIGINAL_SEAL_ONLY',state_root=None,seal_path=original['seal_path'],seal_identity=None))
    scorer['completion_scope']=dict(output_root=None,control_paths=[],control_identities=[],output_paths=[],status='PENDING_SCORECB_EXACT_FINITE_SCOPE')
    scorer['capture_contract'].update(producer_outputs=None,initial_input_paths=None)
    scorer['command_contracts']={cmd:dict(schema=schema,request_path=None,producer_family=fam,parent_paths=[],status='PENDING_OWNER_FINITE_SOURCE_CONTRACT') for cmd,schema,fam in [
        ('arm','C_SCORING_CONTROL_REQUEST_V1','scoring_callback'),('capture','C_SCORING_CONTROL_REQUEST_V1','scoring_callback'),('r2-complete','C_SCORING_CONTROL_REQUEST_V1','scoring_callback'),('r2-score','C_SCORING_R2_DISPATCH_REQUEST_V1','scoring_callback'),('postscore','C_SCORING_POSTSCORE_REQUEST_V1','AP5'),('optional-r2','C_SCORING_OPTIONAL_REQUEST_V1','AP5')]}
    scorer['future_identity_rule']='Freeze source paths/schemas/censuses only; resolve actual permit/seal/score/control identities from verified later evidence; no pre-T5 future-score/request SHA'
    write('SCORER_CONTRACT.pending.json',scorer)
    write('SCORER_BINDINGS.template.json',dict(schema='C_SCORING_SCORER_BINDINGS_V1',source_reviewed=False,scientific_eligibility_changed=False,scientific_authority_contract=dict(path=str(HERE/'SCIENCE_FREEZE.json'),schema='C_SCORING_SCIENTIFIC_FREEZE_V1',state='SCIENTIFIC_CONSUMER_FROZEN_BEFORE_T5'),numeric_ancestor_contract=None,runtime_family_policy=None,entry_contracts=None,scorer_contract=None,production_authority=False))
    write('DISPATCH_REQUESTS.template.json',dict(schema='C_SCORING_DISPATCH_REQUEST_TEMPLATES_V1',production_authority=False,status='PENDING_OWNER_FINITE_PATHS',
        r2_score=dict(schema='C_SCORING_R2_DISPATCH_REQUEST_V1',state_root=None,feature_root=None,permit_identity=None,seal_association=None,capture_evidence=None),
        control=dict(schema='C_SCORING_CONTROL_REQUEST_V1',output_root=None,control_identities=[],output_paths=[]),
        postscore=dict(schema='C_SCORING_POSTSCORE_REQUEST_V1',score_views=dict(original=None,r2=None,execution=None),function='main',function_kwargs={}),
        optional=dict(schema='C_SCORING_OPTIONAL_REQUEST_V1',output_root=None,output_paths=[],permit_identity=None,batch_seal_identity=None,replacement_identity=None),
        scorer_metadata=dict(schema='C_SCORING_SCORER_METADATA_REQUEST_V1',scorer_bindings=None,test_provenance=None,numerical_inputs=None),
        bootstrap=dict(schema='C_SCORING_BOOTSTRAP_SOURCE_PROPOSAL_V1',source_adopted=False,consumer_release=False,scientific_eligibility_changed=False,synthetic_only=False,source_manifest=None,sources={},acceptance=None,independent_review=None,numeric_ancestor_contract=None,host_bindings=None,adoption_binding=None),
        detached_provenance=dict(schema='C_SCORING_RUNTIME_REQUEST_ASSOCIATION_V1',source_verified=False,command=None,request_identity=None,t5_binding=None,producer_code=None,parent_identities=[])))
    write('SCORER_METADATA.schema.json',dict(schema='C_SCORING_SCORER_METADATA_SOURCE_SCHEMA_V1',actual_schema='C_SCORING_SCORER_METADATA_V1',actual_state='A8_SCORER_CODE_FROZEN_BEFORE_T5',required=['schema','state','frozen_utc','code_sha256','files','batch_code_freeze','numerical_inputs','scorer_bindings','test_provenance','production_fits'],forbidden=['table_results_freeze'],ordering='C science freeze < separate scorer metadata freeze < actual T5',writer='SOURCE_ONLY; not delivered/executed here'))


    lock=json.loads((HERE/'SOURCE_LOCK.json').read_bytes())
    files={**{r:v['identity'] for r,v in lock['sources'].items()},**lock['authorities']}
    files.update(json.loads((HERE/'NUMERIC_ANCESTOR_PROPOSAL.json').read_bytes())['files'])
    extra=['studies/batch_estimation/batch_checks/'+n for n in ('consumer_roots.py','runtime_sources.py','run_tests.py','tests_r8bpre.py','tests_g39.py','freeze_consumers.py','review_isolator.py')]
    extra+=['studies/batch_estimation/fitting/TEST_RESULTS.json','studies/confirmation/inference_design/AUTHOR_CONFIRMATION_A8_SCHEMA.json','studies/confirmation/robustness_tests/RULES_FOR_MAIN_COMPARISONS.json','studies/confirmation/sensitivity_tests/RULES_FOR_FILL3A.json','studies/confirmation/A6/RULES_FOR_SENSITIVITY_COMPARISONS.json']
    for rel in extra:
        p=P/rel
        if p.is_file():files[rel]={k:v for k,v in identity(p).items() if k!='path'}
    forbidden={'host_state','state','scored','score','scores','predictions','prediction','models','model','evaluation','run','private'}
    if any(r.startswith('tables/') or any(x.lower() in forbidden for x in Path(r).parts) for r in files):raise ValueError('Protected public allowlist path')
    write('FIXTURE_PUBLIC_SOURCE_CENSUS.json',dict(schema='C_SCORING_PUBLIC_FIXTURE_SOURCE_CENSUS_V1',files=files,source_only=True,production_authority=False))
    pending={
        'PCIMPL2':dict(source_status='scoring_inputs independently ADOPT-READY, exact identities rechecked',requests=['Agree exact fresh R2 state_root/feature_root/permit_path with scoring_callback; approve one-path in-process seal bridge; original CLI unchanged','No new fit/extraction/statistic; no R2 permit or real score identity supplied by this task']),
        'AP5_AP6':dict(status='PENDING_SOURCE_ENTRIES_AND_STABLE_WRITERS',requests=['Fill AP5/AP6 finite root/freeze/schema/state/inventory format/base/declared-census/names from actual successor writers including aware frozen_utc','Deliver ap5_science/ap6_joint/numeric_assembly/author_validation/optional_loader with ENTRY_CONTRACTS keyword contracts','Replace old input_specification whole-FILL author/schema input_checks only; preserve HRC/author/blinding/chronology and native scientific assembly','Enter native specified_scope first, then C scientific_scope around entire numeric build; use original dependencies(consumer=False); separate score_news_full_window attachment in every branch and exact R2 five primary/110 forest slots','Declare distinct R2 R8/CPS8 independent per-layer anchor receipts/pointers; do not reuse old214 optional receipts']),
        'notice_delays':dict(status='PENDING_SOURCE_ENTRY_AND_STABLE_WRITER',requests=['Deliver rd_joint entry and finite successor writer census/UTC; retain original scientific AST/helpers/18 conditions/3 joint/ownseed/weakest tier','Route all imports via C G39 AP6 closure and consume both verified score chains; no self-eligibility']),
        'scoring_callback':dict(status='PENDING_CALLBACK_SOURCE_CONTRACTS_NOT_REAL_HOST_SCAN',requests=['Deliver arm/capture/r2_complete exact entries; actual writer root/freeze/schema/state/inventory/census/frozen_utc and finite capture/control/output/request paths','Capture remains immediate and opaque after observed unchanged original CLI successful exit; preserve cutoff/embargo/clock/plan/T5 chain; no retrospective reconstruction','Use association._producer_identity(path) for just-written opaque output identities; cannot read/decode own opaque payload or unrelated unsealed file','Deliver execution evidence C_SCORING_SCORE_EXECUTION_EVIDENCE_V1 with distinct original/R2 receipt identities, real permit identity and code/freeze/clock/capture/time lineage','Declare actual fresh R2 state/permit/request paths with PCIMPL2 before final C source acceptance; future score/capture/request hashes remain runtime evidence','Real terminal host scan is source-only later; never an accept command']),
        'C_REVIEWER_G42':dict(status='PENDING_INDEPENDENT_SOURCE_CONTRACT_AND_REVIEW',requests=['Review C delivered exact code and current SCIENTIFIC_ACCEPTANCE_SPEC case census, G45 acyclic bootstrap, new scorer metadata and finite runtime contracts','Declare independent eligibility writer exact source/freeze/schema/state/census/T5 membership/public verify API plus exact nine bindings/13 receipts/native JSON pointers/full grid/specified-before-aligned/ownseed/weakest-tier refusals','Independent review follows actual clean scientific receipt in UTC; bind all current/adverse reviews and exact exclusion; AP/notice_delays cannot certify themselves']),
        'AF_AM3':dict(status='PENDING_REAL_SOURCE_ONLY_IDENTITIES',requests=['Preserve original numeric ancestor authorization, actual mapping/condition/clock/seal<T5/permits and independent AF consumer acceptance; no synthetic replacement']),
        'SOURCE':dict(status='PENDING_SEPARATE_ACCEPT_THEN_REAL_RELEASE',requests=['Release accept explicitly after source contracts stable; serialized artificial suites only','Later real bootstrap/adoption/operational evidence/terminal D seals/SET2-5 retained metadata/freezes/T5/permits/releases by separately authorized source; no command here'])}


    if not (HERE/'UPSTREAM_PREPARE_ALIGNMENT.json').is_file():
        write('PENDING_IDENTITIES_BY_OWNER.json',dict(schema='C_SCORING_PENDING_OWNER_IDENTITIES_V2',phase='prepare',C_owned_implementation='COMPLETE_SOURCE_ONLY_STATIC_CHECK_PENDING_FINALIZATION',C_remaining=['authorized synthetic acceptance','independent exact-version C review','source-only real release'],owners=pending,production_authority=False))
    old=json.loads((HERE/'FREEZE_CENSUS.json').read_bytes())
    future=set(old['pending_members'])-{'tests_science.py','run_synthetic_checks.py'}|{'ENTRY_CONTRACTS.json'}
    excluded={'INVENTORY.json','INVENTORY.sha256','FINAL_STATIC_VERIFICATION.json','SOURCE_AST_HELPER_INVENTORY.json','SCIENTIFIC_CORE_STATIC_PARITY.json','SCIENTIFIC_ACCEPTANCE_SPEC.json','SCIENTIFIC_REGRESSION_MIGRATION.json','RETAINED_SOURCE_CHECK.json'}
    actual={str(p.relative_to(HERE)) for p in HERE.rglob('*') if p.is_file() and 'HISTORY_PREPARE_1' not in p.parts and '__pycache__' not in p.parts}
    history={str(p.relative_to(HERE)) for p in (HERE/'HISTORY_PREPARE_1').rglob('*') if p.is_file()}
    allfiles=actual|future|excluded|history|{'ACCEPT_PLAN_source.md','PACKAGE_BUILD_ORDER.md','PUBLIC_RUNTIME_SOURCE_MANIFEST.json'}
    old.update(files=sorted(allfiles),pending_members=sorted(future),state='EXACT_PREPARE_SOURCE_CENSUS_PLUS_NAMED_PENDING_METADATA',freeze_writer_delivered=False)
    write('FREEZE_CENSUS.json',old)
    print(json.dumps(dict(entries=len(roles),public_fixture_sources=len(files),freeze_census=len(allfiles),nice=os.getpriority(os.PRIO_PROCESS,0),scientific_runs=0)))
if __name__=='__main__':main()
