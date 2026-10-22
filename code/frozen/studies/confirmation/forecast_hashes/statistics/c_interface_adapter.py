'Check notice source metadata through the numerical interface.'
from pathlib import Path
import datetime as dt
import sys
import types
from contextlib import contextmanager
from science_contract import require, digest
import metadata_io as io

NATIVE_REVISION = 'SCORING_C8B_SCIENCE_V1'
NATIVE_FREEZE_SCHEMA = 'C_SCORING_SCIENTIFIC_FREEZE_V1'
NATIVE_RECEIPT_SCHEMA = 'C_statistics_ACCEPTANCE_V1'
NATIVE_REVIEW_SCHEMA = 'C_SCORING_INDEPENDENT_REVIEW_V1'
C_ROOT = io.PROJ/'studies/batch_estimation/batch_checks/statistics'
FREEZE_FIELDS = {'schema','state','task_revision','frozen_utc','files','tested_sources',
 'callable_ast_inventory','scientific_decisions','numeric_ancestor_contract','acceptance',
 'independent_review','release_binding','synthetic_only'}


def utc(value):
    require(isinstance(value,str),'UTC required')
    v=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    require(v.utcoffset()==dt.timedelta(0),'Aware UTC zero offset required')
    return v


def normalize_documents(freeze, acceptance, review, contract):
    require(contract.get('stable') is True and contract.get('owner_agreed') is True,
            'Delivered exact source contract required (acceptance remains separate)')
    require(contract.get('revision')==NATIVE_REVISION and contract.get('native_api_source_identities')
            and contract.get('native_case_ids') and contract.get('native_freeze_files'),
            'Exact native source/case/freeze census required')
    sources=contract['sources']
    require(freeze.get('schema')==NATIVE_FREEZE_SCHEMA and
            freeze.get('state')=='SCIENTIFIC_CONSUMER_FROZEN_BEFORE_T5' and
            freeze.get('task_revision')==NATIVE_REVISION and set(freeze)==FREEZE_FIELDS and
            freeze.get('files')==contract['native_freeze_files'] and freeze.get('tested_sources')==sources and
            freeze.get('scientific_decisions')==contract.get('scientific_decisions') and
            freeze.get('numeric_ancestor_contract')==contract.get('numeric_ancestor_contract'),
            'Native timestamp_checks schema/source/revision drift')
    freeze_utc=utc(freeze['frozen_utc'])
    require(acceptance.get('schema')==NATIVE_RECEIPT_SCHEMA and acceptance.get('state')=='CLEAN_FULL_PASS'
            and acceptance.get('task_revision')==NATIVE_REVISION and
            acceptance.get('case_ids')==contract['native_case_ids'] and
            len(set(acceptance['case_ids']))==len(acceptance['case_ids']) and
            all(acceptance.get(k)==[] for k in ('failures','errors','skipped')) and
            acceptance.get('delivered_sources')==sources,
            'Exact new native scientific receipt required; obsolete AF8B/FILL receipt refused')
    r=acceptance.get('resources',{})
    require(r.get('nice')==20 and r.get('test_processes')==1 and
            r.get('minimum_memory_free_percent',0)>=25 and r.get('peak_rss_bytes',10**12)<=1610612736
            and r.get('scratch_peak_bytes',10**12)<1000000000 and r.get('periodic_samples') and
            r.get('breaches')==[], 'C inherited source-acceptance resource gates')
    require(all(x.get('nice')==20 and 25<=x.get('memory_free_percent',0)<=100 and
                x.get('rss_bytes',10**12)<=1610612736 and x.get('scratch_bytes',10**12)<1000000000
                for x in r['periodic_samples']), 'Native periodic resource observations required')
    require(review.get('schema')==NATIVE_REVIEW_SCHEMA and review.get('verdict')=='ACCEPT'
            and review.get('independent') is True and review.get('reviewer_role')=='C_REVIEWER'
            and review.get('task_revision')==NATIVE_REVISION and review.get('reviewed_sources')==sources
            and isinstance(review.get('reviewed_by'),str) and review['reviewed_by'].strip()
            and freeze_utc>=utc(review.get('reviewed_utc'))>=utc(acceptance.get('utc'))
            and all(v.get(k)==0 for v in (review,acceptance)
                    for k in ('production_state_reads','production_commands_run')),
            'Genuine independent C review/provenance/chronology required')
    require(contract.get('native_document_hashes')=={
        'timestamp_checks':digest(freeze),'acceptance':digest(acceptance),'review':digest(review)},
        'Exact native document binding drift')
    require(review.get('test_receipt')==freeze['acceptance'] and freeze['independent_review']==contract.get('review_identity'),
            'Native timestamp_checks/review/test byte identities disagree')
    return dict(native_authority=freeze,native_acceptance=acceptance,native_review=review,
                native_document_hashes=contract['native_document_hashes'],source_association_only=True,
                production_authority=False)


def read_scientific_authority(root=C_ROOT, *, synthetic=False):
    io.phase(root=root,synthetic=synthetic,source_flag=('FORECAST_BINDING_SOURCE_MAPPING_REFRESH','FORECAST_BINDING_SOURCE_SOURCE_COMMITMENT','FORECAST_BINDING_SOURCE_FREEZE','FORECAST_BINDING_SOURCE_RUN','FORECAST_BINDING_SOURCE_TIMESTAMP_BIND'))
    root=Path(root).absolute()
    require(root==C_ROOT or (synthetic and root.is_relative_to('/private/tmp')),'Exact C root required')
    pins=io.read_json(io.HERE/'C_INTERFACE_SOURCE_PINS.json')['files']


    for name,item in pins.items():
        if not synthetic:io.snapshot(C_ROOT/name,item)
    authority_identity=io.identity(root/'SCIENCE_FREEZE.json')
    freeze=io.read_json(root/'SCIENCE_FREEZE.json',authority_identity)
    spec=io.read_json(root/'SCIENTIFIC_ACCEPTANCE_SPEC.json')
    census=io.read_json(root/'FREEZE_CENSUS.json')
    require(set(freeze['files'])==set(census['files']) and len(census['files'])==len(set(census['files'])),
            'Actual C scientific exact freeze census required')
    require(set(freeze['tested_sources'])==set(spec['tested_source_files']),'Exact tested source census required')
    require(freeze.get('synthetic_only') is synthetic,'Real/artificial timestamp_checks input_checks')
    for name,pin in freeze['files'].items():
        require(name==Path(name).as_posix() and not Path(name).is_absolute() and '..' not in Path(name).parts,
                'C inventory alias/escape')
        io.snapshot(root/name,dict(path=str(root/name),**pin))
    for item in [freeze['callable_ast_inventory'],*freeze['scientific_decisions']]:io.snapshot(item['path'],item)
    native_binding=io.read_json(freeze['release_binding']['path'],freeze['release_binding'])
    require(Path(freeze['release_binding']['path']).parent==root and native_binding.get('schema')=='C_SCORING_SCIENTIFIC_RELEASE_V1'
            and native_binding.get('source_reviewed') is True and native_binding.get('scientific_eligibility_changed') is False
            and native_binding.get('integration_complete') is True
            and native_binding.get('numeric_ancestor_contract')==freeze['numeric_ancestor_contract'],
            'Actual native scientific binding/ancestor association required')
    for name in ('runtime_family_policy','scorer_contract','entry_contracts'):
        item=native_binding[name];require(Path(item['path']).parent==root,'Native binding member outside exact root')
        io.snapshot(item['path'],item)
    test=io.read_json(freeze['acceptance']['path'],freeze['acceptance'])
    review=io.read_json(freeze['independent_review']['path'],freeze['independent_review'])
    for item in [freeze['acceptance'],freeze['independent_review']]:
        require(Path(item['path']).parent==root,'Native source-review path escaped C root')
    contract=dict(stable=True,owner_agreed=True,revision=NATIVE_REVISION,
        native_api_source_identities=pins,native_case_ids=spec['case_ids'],
        native_freeze_files=freeze['files'],sources=freeze['tested_sources'],review_identity=freeze['independent_review'],
        scientific_decisions=io.read_json(root/'SCIENCE_RULES.json')['authority_identities'],
        numeric_ancestor_contract=freeze['numeric_ancestor_contract'],
        native_document_hashes={'timestamp_checks':digest(freeze),'acceptance':digest(test),'review':digest(review)})
    result=normalize_documents(freeze,test,review,contract)
    with native_review_helpers(pins):
        gate=io.load_source('_af_native_c_review_gate',C_ROOT/'review_gate.py',pins['review_gate.py'],register=False)
        verdict=gate.eligibility(root)
    ancestor=verify_numeric_ancestor(root,freeze['numeric_ancestor_contract'],pins)
    require(verdict['state']=='FREEZE-READY-PENDING-SOURCE-RELEASE','Exact native source-review gate not ready')

    for item in [authority_identity,freeze['acceptance'],freeze['independent_review'],freeze['release_binding'],
                 freeze['numeric_ancestor_contract'],freeze['callable_ast_inventory'],*freeze['scientific_decisions']]:
        io.snapshot(item['path'],item)
    for name,pin in freeze['files'].items():io.snapshot(root/name,dict(path=str(root/name),**pin))
    result['contract']=contract;result['authority_identity']=authority_identity
    result['independent_source_verdict']=verdict
    result['numeric_ancestor_verification']=ancestor
    result['native_release_binding']=native_binding
    result['root']=str(root)
    result['source_association_only']=True
    return result


@contextmanager
def native_review_helpers(pins):

    names=('closure_evidence',)
    old={name:sys.modules.get(name) for name in names}
    try:
        for name in names:
            io.load_source(name,C_ROOT/(name+'.py'),pins[name+'.py'])
        yield
    finally:
        for name,value in old.items():
            if value is None:sys.modules.pop(name,None)
            else:sys.modules[name]=value


def verify_numeric_ancestor(root,item,pins):

    root=Path(root);module=io.load_source('_af_native_c_ancestor',C_ROOT/'science_contract.py',
                                        pins['science_contract.py'],register=False)
    live=io.PROJ if root==C_ROOT else root/'ARTIFICIAL_LIVE'
    def contained(path,base):
        require(Path(path).is_relative_to(base),'Numerical ancestor path outside exact root')
    facade=types.SimpleNamespace(require=require,contained=contained,checked=lambda row:io.snapshot(row['path'],row),
         read=io.read_json,LIVE=live,Refusal=PermissionError)
    association=types.SimpleNamespace(out=root,_authority_files={})
    module._numeric_ancestors(association,facade,item)
    return dict(files=association._authority_files,source_only=True,production_authority=False)
