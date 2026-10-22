'Save checked source hashes for numerical notice evaluation.'
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import types
from evaluator.validation import require, exact_identity
from freeze_layout import REVISION, SCHEMA, STATE, validate_layout, require_clean_receipt
from forecast_metadata import isolated_aliases

HERE=Path(__file__).absolute().parent


def phase():
    require(os.environ.get('SCORING_PHASE','prepare')=='source_runtime' and
        os.environ.get('ANCHORREADER_SOURCE_FREEZE')=='1', 'Separate source freeze release required')


def identity(path):
    path=Path(path)
    require(path.is_absolute() and path==path.resolve() and all(not x.is_symlink() for x in (path,*path.parents)),
            'Canonical regular metadata/source path')
    data=path.read_bytes()
    return dict(path=str(path),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())


def metadata(item):
    exact_identity(item);path=Path(item['path'])
    require(path.is_relative_to(HERE) and path.suffix=='.json' and
        not path.name.upper().startswith(('SEAL_','SCORE_')), 'Only notice_delays scientific metadata')
    require(identity(path)==item, 'Metadata identity drift')
    return json.loads(path.read_text())


def utc(value):
    stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
    require(stamp.utcoffset()==timedelta(0), 'Aware zero-offset UTC required')
    return stamp


def c_eligibility():
    observation=json.loads((HERE/'C_INTERFACE_SOURCE_OBSERVATION.json').read_text())
    selected={name:observation['sources'][name] for name in ('review_gate.py','closure_evidence.py')}
    modules={}
    with isolated_aliases({'closure_evidence'}):
        for name in ('closure_evidence.py','review_gate.py'):
            pin=selected[name];require(identity(pin['path'])==pin, 'C eligibility verifier source drift')
            module=types.ModuleType(name.removesuffix('.py'));module.__file__=pin['path']
            exec(compile(Path(pin['path']).read_bytes(),pin['path'],'exec',dont_inherit=True),vars(module))
            modules[name]=module
            if name=='closure_evidence.py':sys.modules['closure_evidence']=module
        result=modules['review_gate.py'].eligibility(Path(selected['review_gate.py']['path']).parent)
    require(result.get('state')=='FREEZE-READY-PENDING-SOURCE-RELEASE'
        and result.get('freeze_permitted') is False and result.get('production_authority') is False,
        'Native C same-version full closure/review pending')
    return result


def create(receipt_identity, review_identity, release_identity):
    phase()
    bindings=json.loads((HERE/'DEPENDENCY_ACCEPTANCE_BINDINGS.pending.json').read_text())
    require(bindings.get('status')=='OWNER_DELIVERED_INDEPENDENTLY_REVIEWED_SOURCE_CONTRACT'
        and bindings.get('review_contract_adopted') is True, 'Actual adopted owner/review contract pending')
    receipt=metadata(receipt_identity);review=metadata(review_identity);release=metadata(release_identity)
    specification=json.loads((HERE/'ACCEPTANCE_CENSUS.json').read_text())
    sources=specification['sources'];ids=specification['test_ids']
    for pin in sources.values():require(identity(pin['path'])==pin, 'Delivered scientific source drift')
    require_clean_receipt(receipt,sources,ids)
    require(receipt.get('full_protocol_acceptance') is True and
        receipt.get('pending_owner_integrations')==[] and specification['pending_owner_integrations']==[],
        'Kernel-only receipt cannot freeze; native provenance/input/eligibility migrations pending')
    require(review.get('schema')=='RD_SCORING_INDEPENDENT_REVIEW_V1' and review.get('task_revision')==REVISION
        and review.get('verdict')=='ACCEPT' and review.get('independent') is True
        and review.get('reviewer_role')=='RD_REVIEWER' and review.get('reviewed_sources')==sources
        and review.get('test_ids')==ids and review.get('test_receipt')==receipt_identity,
        'Actual exact-version independent notice_delays review required')
    require(isinstance(review.get('reviewed_by'),str) and review['reviewed_by'].strip()
        and review['reviewed_by'] not in ('RD7','AP6B2','numeric producer'), 'No producer self-approval')
    require(release.get('schema')=='RD_SCORING_SOURCE_FREEZE_RELEASE_V1' and release.get('adopted') is True
        and release.get('test_receipt')==receipt_identity and release.get('independent_review')==review_identity
        and utc(receipt['utc'])<=utc(review['reviewed_utc'])<=utc(release['released_utc']),
        'Actual separate source release/chronology required')
    c_eligibility()
    census=json.loads((HERE/'RUNTIME_CENSUS.json').read_text())['files']
    C=HERE.parents[4]/'studies/batch_estimation/batch_checks/statistics'
    policy=json.loads((C/'RUNTIME_FAMILY_POLICY.json').read_text())['families']['notice_delays']
    candidate=json.loads((HERE/'G39_RD_POLICY.candidate.json').read_text())['notice_delays']
    require(policy==candidate and policy['names']==census, 'Actual C/notice_delays file census and G39 descriptor agreement')
    ancestors=json.loads((HERE/'NUMERICAL_ANCESTOR_PINS.json').read_text())
    af=json.loads((HERE/'AF9_REVIEWED_SOURCE_PINS.json').read_text())
    news=json.loads((HERE/'R2_INDEPENDENT_SOURCE_PINS.json').read_text())
    value=dict(schema=SCHEMA,state=STATE,task_revision=REVISION,
        frozen_utc=datetime.now(timezone.utc).isoformat(),files=[identity(HERE/name) for name in census],
        declared_census=census,tested_sources=list(sources.values()),
        callable_ast_inventory=json.loads((HERE/'SOURCE_AST_HELPER_INVENTORY.json').read_text())['callables'],
        scientific_decisions=json.loads((HERE/'DECISION_AND_REVIEW_SOURCE_IDENTITIES.json').read_text())['sources'],
        numeric_ancestor_contract=ancestors,acceptance=receipt_identity,independent_review=review_identity,
        release_binding=release_identity,synthetic_only=False,
        source_functions=ancestors['source_functions'],delay_source_functions=ancestors['delay_source_functions'],
        news_source=news['approved_source'],forecast_binding_sources=list(af['reviewed_source_census'].values()),
        declared_scientific_test_census=ids)
    validate_layout(value,census,HERE)
    target=HERE/'RD_SCIENTIFIC_FREEZE.json'
    with target.open('x') as stream:json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
    return value


def main():
    phase()
    import argparse
    parser=argparse.ArgumentParser()
    for name in ('receipt','review','release'):parser.add_argument('--'+name+'-identity',type=Path,required=True)
    args=parser.parse_args()
    values=[]
    for p in (args.receipt_identity,args.review_identity,args.release_identity):
        require(p.is_relative_to(HERE), 'Identity descriptor in notice_delays additive output only')
        values.append(json.loads(p.read_text()))
    create(*values)


if __name__=='__main__':main()
