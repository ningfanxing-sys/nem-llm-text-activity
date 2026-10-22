'Check source hashes and the records required for numerical validation.'
import hashlib
import json
from pathlib import Path
import re
import stat
import os
import datetime as dt

def _review_provenance(root,test,review):

    def identity(p):
        blob=p.read_bytes()
        return dict(path=str(p),bytes=len(blob),sha256=hashlib.sha256(blob).hexdigest())
    def decisions(text):
        return {re.sub(r'[-_\s]+',' ',x).upper().strip() for x in re.findall('(?: Verdict |verdict)\\s*[:：]\\s*\\**\\s*(FREEZE[-_ ]READY|SET[-_ ]FIRST)',text,re.I)}
    def utc(value):
        instant=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
        if instant.utcoffset()!=dt.timedelta(0):raise ValueError('Review/test UTC required')
        return instant
    spec=json.loads((root/'SCIENTIFIC_ACCEPTANCE_SPEC.json').read_bytes())
    if test.get('task_revision')!='SCORING_C8B_SCIENCE_V1' or test.get('case_ids')!=spec['case_ids'] or any(test.get(k)!=[] for k in ('failures','errors','skipped')):raise ValueError('Exact scientific receipt census/version required')
    unit=(test.get('schema')=='C_SCORING_ARTIFICIAL_REVIEW_METADATA_V1' and test.get('state')=='UNIT_REVIEW_METADATA_PREMISE_NOT_ACCEPTANCE' and test.get('synthetic_only') is True and root.is_relative_to(Path('/private/tmp')) and os.environ.get('SCORING_PHASE')=='accept')
    if not unit and (test.get('state')!='CLEAN_FULL_PASS' or test.get('schema')!='C_statistics_ACCEPTANCE_V1'):raise ValueError('Clean scientific receipt required')
    if set(test['delivered_sources'])!=set(spec['tested_source_files']) or review['reviewed_sources']!=test['delivered_sources']:raise ValueError('Reviewed/tested source census drift')
    for name,pin in test['delivered_sources'].items():_snapshot(root,name,pin)
    if not review.get('independent') or not isinstance(review.get('reviewed_by'),str) or not review['reviewed_by'].strip():raise ValueError('Named independent reviewer required')
    if any(v.get(k)!=0 for v in (test,review) for k in ('production_state_reads','production_commands_run')):raise ValueError('Source-only provenance required')
    if utc(review['reviewed_utc'])<utc(test['utc']):raise ValueError('Review precedes exact test receipt')
    if review['test_receipt']!=identity(root/'SCIENTIFIC_ACCEPTANCE_RECEIPT.json'):raise ValueError('Review/test receipt identity drift')
    names=sorted(str(p.relative_to(root)) for p in root.rglob('*.md') if re.fullmatch(r'REVIEW.*_zh\.md',p.name) or ('reviews' in p.relative_to(root).parts and p.name=='REPORT.md'))
    if not names or set(review['review_files'])!=set(names):raise ValueError('Dynamic review census drift')
    for name,pin in review['review_files'].items():_snapshot(root,name,pin)
    final=review['final_review'];relative=Path(final['path']).relative_to(root).as_posix()
    if relative not in names or final!=identity(root/relative):raise ValueError('Final review identity/path drift')
    final_text=_snapshot(root,relative,{k:final[k] for k in ('bytes','sha256')}).decode()
    if decisions(final_text)!={'FREEZE READY'}:raise ValueError('Final review SET FIRST/mixed verdict')
    blocking=[identity(root/n) for n in names if 'SET FIRST' in decisions((root/n).read_text())]
    if sorted(review['replaces'],key=lambda x:x['path'])!=sorted(blocking,key=lambda x:x['path']):raise ValueError('Exact adverse review exclusion missing/drifted')
    if not all(Path(x['path']).name in final_text and x['sha256'] in final_text for x in blocking):raise ValueError('Adverse review not explicitly addressed')
    census=json.loads((root/'FREEZE_CENSUS.json').read_bytes())
    for name in census['files']:
        if name in census.get('pending_members',[]):continue
        p=root/name
        _snapshot(root,name,{k:identity(p)[k] for k in ('bytes','sha256')})
    return dict(review_files=names,inactive=blocking,freeze_permitted=False)


def _snapshot(root,relative,pin):
    if not isinstance(relative,str) or relative!=Path(relative).as_posix() or '..' in Path(relative).parts or Path(relative).is_absolute():
        raise ValueError('Noncanonical package member')
    path=root/relative
    if any(p.is_symlink() for p in (path,*path.parents)) or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Symlink/directory member')
    payload=path.read_bytes()
    if len(payload)!=pin['bytes'] or hashlib.sha256(payload).hexdigest()!=pin['sha256']:
        raise ValueError('Reviewed/tested source identity drift')
    return payload


def eligibility(root):

    raw=os.fsdecode(os.fspath(root));root=Path(raw)
    if not root.is_absolute() or str(root)!=raw or '..' in root.parts or any(x.is_symlink() for x in (root,*root.parents)):
        raise ValueError('Noncanonical/symlink review root')
    own=Path(__file__).absolute().parent
    if root!=own:
        if os.environ.get('SCORING_PHASE')!='accept' or not root.is_relative_to(Path('/private/tmp')) or \
           json.loads((root/'SYNTHETIC_ONLY.json').read_bytes())!={'synthetic_only':True}:
            raise ValueError('Eligibility root outside scientific package/artificial fixture')
    pending=[name for name in ('SCIENTIFIC_ACCEPTANCE_RECEIPT.json','INDEPENDENT_REVIEW.json',
                               'RUNTIME_FAMILY_POLICY.json','SCORER_CONTRACT.json','SOURCE_CLOSURE_RECEIPT.json')
             if not (root/name).is_file()]
    if pending:return dict(state='PENDING',missing=pending,freeze_permitted=False,production_authority=False)
    def read(name):
        def pairs(rows):
            value={}
            for k,v in rows:
                if k in value:raise ValueError('Duplicate metadata key')
                value[k]=v
            return value
        p=root/name
        if any(x.is_symlink() for x in (p,*p.parents)):raise ValueError('Unsafe review artifact')
        return json.loads(p.read_bytes(),object_pairs_hook=pairs)
    spec=read('SCIENTIFIC_ACCEPTANCE_SPEC.json');test=read('SCIENTIFIC_ACCEPTANCE_RECEIPT.json');review=read('INDEPENDENT_REVIEW.json')
    policy=read('RUNTIME_FAMILY_POLICY.json');scorer=read('SCORER_CONTRACT.json')
    if policy.get('schema')!='C_SCORING_RUNTIME_FAMILIES_V1' or policy.get('status')!='REVIEWED_EXACT_OWNER_CONTRACTS' or set(policy.get('families',{}))!={'AP5','AP6','notice_delays','scoring_callback'}:
        raise ValueError('Four actual reviewed successor owner contracts pending')
    fields={'root','freeze','schema','state','inventory_field','inventory_format','inventory_base','declared_census_field','names'}
    for row in policy['families'].values():
        if set(row)!=fields or any(row[x] is None for x in fields) or not row['names'] or len(row['names'])!=len(set(row['names'])):
            raise ValueError('Successor exact owner census missing/duplicate')
    if scorer.get('schema')!='C_SCORING_SCORER_CONTRACT_V1' or scorer.get('status')!='REVIEWED_EXACT_R2_SOURCE_DELIVERY':
        raise ValueError('Actual agreed original/R2 scorer contract pending')
    if test.get('state')!='CLEAN_FULL_PASS' or test.get('task_revision')!='SCORING_C8B_SCIENCE_V1' or \
       test.get('case_ids')!=spec['case_ids'] or any(test.get(k)!=[] for k in ('failures','errors','skipped')):
        raise ValueError('Exact new full scientific acceptance missing')
    if set(test['delivered_sources'])!=set(spec['tested_source_files']):raise ValueError('Tested source census missing/extra')
    for rel,pin in test['delivered_sources'].items():_snapshot(root,rel,pin)
    if review.get('schema')!='C_SCORING_INDEPENDENT_REVIEW_V1' or review.get('independent') is not True or \
       review.get('reviewer_role')!='C_REVIEWER' or review.get('verdict')!='ACCEPT' or \
       review.get('task_revision')!='SCORING_C8B_SCIENCE_V1' or \
       review.get('reviewed_sources')!=test['delivered_sources']:
        raise ValueError('G42 independent exact-version review required; no producer self-certification')

    names=sorted(str(p.relative_to(root)) for p in root.rglob('*.md') if re.fullmatch(r'REVIEW.*_zh\.md',p.name) or ('reviews' in p.relative_to(root).parts and p.name=='REPORT.md'))
    if not names or set(review.get('review_files',{}))!=set(names):raise ValueError('Review inventory missing/extra')
    for rel,pin in review['review_files'].items():_snapshot(root,rel,pin)
    _review_provenance(root,test,review)
    resources=test.get('resources',{})
    if not(resources.get('nice')==20 and resources.get('test_processes')==1 and
           resources.get('minimum_memory_free_percent',0)>=25 and resources.get('scratch_peak_bytes',10**12)<10**9 and
           resources.get('peak_rss_bytes',10**12)<=1610612736 and resources.get('periodic_samples') and resources.get('breaches')==[]):
        raise ValueError('Observed inherited resource gates absent/breached')
    closure=read('SOURCE_CLOSURE_RECEIPT.json')
    from closure_evidence import verify as verify_closure
    verify_closure(root,closure,test,spec,review)
    return dict(state='FREEZE-READY-PENDING-SOURCE-RELEASE',freeze_permitted=False,production_authority=False,
                tested_sources=test['delivered_sources'])
