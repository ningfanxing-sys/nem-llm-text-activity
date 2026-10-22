'Save numerical source hashes after validating their input records.'
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import sys
import types
from .input_checks import HERE, require, source_identity, json_bytes


def utc(value):
    t=datetime.fromisoformat(value.replace('Z','+00:00'))
    require(t.utcoffset()==timedelta(0),'Exact UTC metadata required');return t


def metadata(item):
    path=Path(item['path'])
    owners=(HERE,HERE.parents[1]/'batch_estimation/batch_checks/statistics',
            HERE.parents[1]/'confirmation/notice_evaluation/statistics')
    require(path.resolve()==path and any(path.is_relative_to(x) for x in owners) and path.suffix=='.json'
            and not path.name.upper().startswith(('SEAL','SCORE')),'Scientific metadata only')
    require(source_identity(path)==item,'Metadata identity drift')
    return json.loads(path.read_bytes())


def c_eligibility(closure_identity):

    observation=json.loads((HERE/'C_INTERFACE_SOURCE_OBSERVATION.json').read_bytes())
    selected=observation['freeze_eligibility_sources'];old=sys.modules.get('closure_evidence');modules={}
    try:
        for name in ('closure_evidence.py','review_gate.py'):
            pin=selected[name];require(source_identity(pin['path'])==pin,'C independent gate source drift')
            module=types.ModuleType(name.removesuffix('.py'));module.__file__=pin['path']
            exec(compile(Path(pin['path']).read_bytes(),pin['path'],'exec',dont_inherit=True),vars(module))
            modules[name]=module
            if name=='closure_evidence.py':sys.modules['closure_evidence']=module
        root=Path(selected['review_gate.py']['path']).parent
        require(source_identity(root/'SOURCE_CLOSURE_RECEIPT.json')==closure_identity,'Actual independent C closure path drift')
        result=modules['review_gate.py'].eligibility(root)
        require(result.get('state')=='FREEZE-READY-PENDING-SOURCE-RELEASE' and
                result.get('freeze_permitted') is False and result.get('production_authority') is False,
                'Actual independent native C closure/review pending')
        for pin in selected.values():require(source_identity(pin['path'])==pin,'C gate changed during verification')
    finally:
        if old is None:sys.modules.pop('closure_evidence',None)
        else:sys.modules['closure_evidence']=old


def create(family,receipt_identity,review_identity,release_identity,c_closure_identity):
    require(os.environ.get('SCORING_PHASE','prepare')=='source_runtime' and
            os.environ.get('A8POST_SOURCE_FREEZE')=='1','Separate source freeze release required')
    require(family in ('AP5','AP6'),'Exact scientific family')
    plan=json.loads((HERE/'FREEZE_PLAN.json').read_bytes())
    layout=next(x for x in plan['families'] if x['family']==family)
    receipt,review,release,closure=[metadata(x) for x in (receipt_identity,review_identity,release_identity,c_closure_identity)]
    require(receipt.get('full_protocol_acceptance') is True and receipt.get('state')=='CLEAN_FULL_PASS'
            and receipt.get('synthetic_only') is True and receipt.get('production_authority') is False
            and receipt.get('actual_T5_grant') is False
            and receipt.get('pending_owner_integrations')==[] and
            all(receipt.get(k)==[] for k in ('failures','errors','skipped','blocked_process_attempts')),
            'Kernel/targeted/pending/unclean receipt cannot freeze')
    require(receipt.get('scientific_case_groups')==['S%02d'%i for i in range(1,19)],'Complete independent scientific case groups')
    require(review.get('independent') is True and review.get('verdict')=='ACCEPT'
            and review.get('test_receipt')==receipt_identity and review.get('reviewed_by') not in (None,'','AP6B2','numeric producer'),
            'Same-version independent AP review required')
    require(closure.get('schema')=='C_SCORING_SOURCE_CLOSURE_V2' and closure.get('state')=='INDEPENDENT_SCIENTIFIC_CHAIN_VERIFIED'
            and closure.get('full_numeric_chain') is True and release.get('c_closure')==c_closure_identity,
            'Independent actual C full native closure required')
    require(release.get('schema')=='AP_SCORING_SOURCE_FREEZE_RELEASE_V1' and release.get('adopted') is True
            and release.get('family')==family and release.get('test_receipt')==receipt_identity
            and release.get('independent_review')==review_identity,'Distinct exact source release required')
    c_eligibility(c_closure_identity)
    c_root=Path(c_closure_identity['path']).parent
    policy=json.loads((c_root/'RUNTIME_FAMILY_POLICY.json').read_bytes())['families'][family]
    q=HERE.parents[1]
    descriptor=dict(root=str(Path(layout['candidate_root']).relative_to(q)),
        freeze=str(Path(layout['future_freeze_path']).relative_to(q)),schema=layout['schema'],state=layout['state'],
        inventory_field=layout['inventory_field'],inventory_format=layout['inventory_format'],
        inventory_base=layout['inventory_base'],declared_census_field=layout['declared_census_field'],names=layout['names'])
    require(policy==descriptor,'Exact independently adopted C/AP writer census/format disagreement')
    dependencies=release['dependencies']
    require(len({x['path'] for x in dependencies})==len(dependencies),'Duplicate dependency identities')
    for item in dependencies:
        path=Path(item['path'])
        require(path.is_absolute() and path.resolve()==path and path.suffix=='.json' and
                any(word in path.name.upper() for word in ('FREEZE','CONTRACT','ADOPTION')) and
                not any(x.lower() in ('host_state','scored','scores','sealed','predictions','outcomes') for x in path.parts)
                and not path.name.upper().startswith(('SEAL','SCORE_RECEIPT','SCORE_REPORT')),
                'Dependencies are scientific code/contract metadata only; no seal/score/outcome read')
        require(source_identity(item['path'])==item,'Actual dependency identity drift')
    required={str(c_root/'SCIENCE_FREEZE.json'):('C_SCORING_SCIENTIFIC_FREEZE_V1','SCIENTIFIC_CONSUMER_FROZEN_BEFORE_T5')}
    if family=='AP6':
        required[str(HERE/'NUMERIC_CODE_FREEZE.json')]=('AP_SCORING_NUMERIC_CODE_FREEZE_V1','SCIENTIFIC_CODE_FROZEN_BEFORE_T5')
        required[str(HERE.parents[1]/'confirmation/notice_evaluation/statistics/RD_SCIENTIFIC_FREEZE.json')]=('RD_SCORING_SCIENTIFIC_FREEZE_V1','RD_SCIENTIFIC_FROZEN_BEFORE_T5')
    indexed={x['path']:x for x in dependencies}
    require(set(required)<=set(indexed),'Actual mandatory scientific dependency freezes pending')
    for path,(schema,state) in required.items():
        value=metadata(indexed[path])
        require(value.get('schema')==schema and value.get('state')==state and
                utc(value['frozen_utc'])<=utc(release['released_utc'])<utc(release['T5_not_before_utc']),
                'Scientific dependency schema/state/pre-T5 chronology')
    inventory=release['ast_helper_inventory']
    require(inventory==source_identity(HERE/'SOURCE_AST_HELPER_INVENTORY.json'),'Exact AST/helper inventory identity')
    require(utc(receipt['utc'])<=utc(review['reviewed_utc'])<=utc(release['released_utc'])<utc(release['T5_not_before_utc']),
            'Review/release/T5 chronological input_checks')
    root=Path(layout['candidate_root']);names=layout['names'];require(len(names)==len(set(names)),'Unique finite source census')
    rows=[source_identity(root/name) for name in names]
    require(review['reviewed_sources'][family]==rows and release['sources']==rows,'Source changes after review/release')
    target=Path(layout['future_freeze_path']);require(target.is_relative_to(root) and not target.exists(),'Exclusive fixed freeze target')
    now=datetime.now(timezone.utc).isoformat()
    require(utc(release['released_utc'])<=utc(now)<utc(release['T5_not_before_utc']),'Actual freeze clock outside released pre-T5 window')
    body=dict(schema=layout['schema'],state=layout['state'],frozen_utc=now,sources=rows,
        declared_census=names,dependencies=release['dependencies'],ast_helper_inventory=release['ast_helper_inventory'],
        scientific_acceptance=receipt_identity,independent_review=review_identity,source_release=release_identity)
    require([source_identity(root/name) for name in names]==rows,'Source drift at publication')
    with target.open('xb') as h:h.write(json_bytes(body))
    return source_identity(target)


def main():
    if os.environ.get('SCORING_PHASE','prepare')!='source_runtime' or os.environ.get('A8POST_SOURCE_FREEZE')!='1':
        raise SystemExit('Prepare/accept: no freeze request reads or writer execution')
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--family',choices=('AP5','AP6'),required=True)
    parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--request-sha256',required=True)
    args=parser.parse_args()
    request_id=source_identity(args.request)
    require(request_id['sha256']==args.request_sha256,'Trusted source request identity drift')
    request=metadata(request_id)
    require(set(request)=={'family','receipt','review','release','c_closure'} and request['family']==args.family,
            'Exact source freeze request schema')
    create(args.family,request['receipt'],request['review'],request['release'],request['c_closure'])


if __name__=='__main__':main()
