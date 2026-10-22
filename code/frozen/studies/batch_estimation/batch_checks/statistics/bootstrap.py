'Prepare metadata records from checked source files.'
import contextlib
import re
from pathlib import Path
from contract_io import ContractError,_phase,_snapshot,_json,_identity,_canonical,_write_exclusive

LIVE_CONTROL={'OPENED_PATHS.jsonl','EXPLICIT_READS.jsonl','FITTING_WALL_LEDGER.json','PROCESS_OVERLAP_AUDIT.jsonl','FITTING_WALL_EVENTS.jsonl','.fitting.lock'}

def _known(a,p):
    if p.parent==a.d/'state' and p.name in {'DLY8_LAUNCH.json','BATCH_STATUS.json','RESOURCE_REMEDY.json'}:return True
    if p.parent in {a.d/'state'/n for n in ('remedies','remedies_used','remedied_attempts')}:return bool(re.fullmatch(r'[A-Za-z0-9_-]+\.json',p.name))
    if p in {a.d/'state/stages'/(n+'.json') for n in ('R8_build','CS8_primary_seed_robustness_news')}:return True
    if p in {a.d/'dly8'/('mode'+str(n))/'STOPPED_FOR_REMEDY.json' for n in (1,2)}:return True
    return p in {a.d/'dly8/embedding_cache/MISSING_CORPORA.jsonl',a.d/'REMEDY_LOG.md'}

def _proof(a,item):
    _phase(a.project,a.synthetic)
    value=_json(_snapshot(item,a.out))
    if value.get('schema')!='C_SCORING_BOOTSTRAP_SOURCE_PROPOSAL_V1' or value.get('source_adopted') is not True \
       or value.get('scientific_eligibility_changed') is not False or value.get('consumer_release') is not False:
        raise ContractError('Separate reviewed/adopted source-only bootstrap required')
    if value.get('synthetic_only') is not a.synthetic:raise ContractError('Bootstrap synthetic/real input_checks')
    manifest=_json(_snapshot(value['source_manifest'],a.out))
    if value['sources']!=manifest['files']:raise ContractError('Bootstrap exact source census')
    for rel,pin in value['sources'].items():_snapshot(dict(path=str(a.out/rel),**pin),a.out)
    acceptance=_json(_snapshot(value['acceptance'],a.out));review=_json(_snapshot(value['independent_review'],a.out))
    spec=_json((a.out/'SCIENTIFIC_ACCEPTANCE_SPEC.json').read_bytes())
    artificial=(a.synthetic and acceptance.get('schema')=='C_SCORING_ARTIFICIAL_RELEASE_PREMISE_V1' and acceptance.get('state')=='ARTIFICIAL_PRIOR_REVIEW_PREMISE_NOT_ACCEPTANCE' and acceptance.get('premise_only') is True)
    if (not artificial and acceptance.get('state')!='CLEAN_FULL_PASS') or acceptance.get('case_ids')!=spec['case_ids'] or \
       any(acceptance.get(k)!=[] for k in ('failures','errors','skipped')) or acceptance.get('delivered_sources')!=value['sources']:
        raise ContractError('Bootstrap requires exact new clean scientific acceptance')
    if review.get('schema')!='C_SCORING_INDEPENDENT_REVIEW_V1' or review.get('verdict')!='ACCEPT' or \
       review.get('independent') is not True or review.get('reviewer_role')!='C_REVIEWER' or review.get('reviewed_sources')!=value['sources']:
        raise ContractError('Independent C bootstrap review, never AP/notice_delays self-certification')
    if not artificial:
        from review_gate import _review_provenance
        _review_provenance(a.out,acceptance,review)
        r=acceptance.get('resources',{})
        if r.get('nice')!=20 or r.get('test_processes')!=1 or r.get('minimum_memory_free_percent',0)<25 or r.get('peak_rss_bytes',10**12)>1610612736 or r.get('scratch_peak_bytes',10**12)>=10**9 or not r.get('periodic_samples') or r.get('breaches')!=[]:raise ContractError('Bootstrap observed resource evidence required')
    a.sources()

    with a._validation():a._verify_numeric_ancestors(value['numeric_ancestor_contract'])
    if not a.synthetic:
        adoption=_json(_snapshot(value['adoption_binding'],a.out))
        if adoption.get('state')!='C_BOOTSTRAP_SOURCE_ADOPTION_VERIFIED' or adoption.get('source_verified') is not True \
           or adoption.get('source_manifest')!=value['source_manifest']:
            raise ContractError('Actual source adoption binding required')

        a._host_timestamp(adoption,value['source_manifest'],'CBOOT')
    return value

@contextlib.contextmanager
def _scope(a,proof):
    if a._released or a._bootstrap_depth:raise ContractError('Bootstrap cannot borrow consumer release')
    a._bootstrap_source_ready=True;a._bootstrap_depth=1
    try:
        with a.installed(preparation=True,metadata_only=True),a._validation():
            a._disk_release(proof['host_bindings']);a._check_ambiguity()
            yield
    finally:
        a._bootstrap_source_ready=False;a._bootstrap_depth=0
        a.sealed.clear();a._verified_files.clear();a._official_files.clear();a._sealed_roots.clear()
        a._released=False;a._official_ready=None;a.revoke_ap_route()

def _collect(a,destination,*,_legacy_artificial_component=False):
    if _legacy_artificial_component and (not a.synthetic or not a.project.is_relative_to(Path('/private/tmp'))):raise ContractError('Legacy component unit premise cannot affect real bootstrap')
    a._evidence_proposal_chain();rows=[]
    for root in (a.d/'state',a.d/'dly8',a.d/'cps8'):
        if not root.exists():continue
        for p in sorted(root.rglob('*')):
            _canonical(p,root)
            if not p.is_file() or (p in a.sealed and not _known(a,p)):continue
            item=_identity(p,root)
            if p.parent==a.d/'state' and p.name in LIVE_CONTROL:
                target=destination/'evidence_snapshots'/p.name
                target.parent.mkdir(parents=True,exist_ok=True)

                blob=_snapshot(item,root)
                with target.open('xb') as stream:stream.write(blob)
                rows.append(dict(role='OPERATIONAL_LIVE',identity=item,snapshot=_identity(target,destination)))
            elif _known(a,p):rows.append(dict(role='OPERATIONAL_EVIDENCE',identity=item))
            elif any(n in p.parts for n in ('failed_attempts','revisions','retained_budget')):rows.append(dict(role='RETAINED_EXCLUDED',identity=item))
            elif p.is_relative_to(a.d/'dly8/embedding_cache') and p.suffix in ('.npy','.json'):
                pair=a.cache_pair(p)
                import consumer_roots as C
                rows.append(dict(role='PRODUCER_SIDECAR_CACHE',identity=item,sidecar=_identity(pair[1],a.d),producer_sources=[C._identity(C.LIVE/'studies/confirmation/execution/embedding_adapter.py'),C._identity(C.LIVE/C.B_REL/'code/delay_cache.py')]))
            else:raise ContractError('Unknown unsealed scientific output; repair seal chain: '+str(p))
    log=a.d/'REMEDY_LOG.md'
    if log.exists():rows.append(dict(role='OPERATIONAL_EVIDENCE',identity=_identity(log,a.d)))

    if _legacy_artificial_component and not (a.f5/'FAILURE_BINDINGS.json').exists():
        history=a.operational_history(rows) if (a.d/'state/remedies/DLY8_mode1.json').exists() else None
        four=None
    else:history=a.operational_history(rows);four=a.remedy_history(rows)
    evidence=dict(schema='A8DISK_OUTPUT_EVIDENCE_IDENTITIES_V1',source_reviewed=False,
                  batch_seal=_identity(a.d/'state/SEAL_BATCH.json',a.d),scientific_eligibility_changed=False,
                  files=rows)
    if history is not None:evidence['operational_history']=history
    if four is not None:evidence['remedy_history']=four

    if (a.out/'OUTPUT_EVIDENCE_BINDINGS.json').exists():a.census()
    files=[_identity(p,a.project) for p in sorted(a.prescore_paths())]
    source=dict(schema='A8DISK_T5_COMMITMENT_SOURCE_V1',association_source=_identity(Path(__file__).parent/'consumer_roots.py',Path(__file__).parent),batch_seal=evidence['batch_seal'],files=files)
    return evidence,source

def _propose(a,source_proposal,destination):
    proof=_proof(a,source_proposal);destination=_canonical(destination,a.out)
    if destination.exists():raise ContractError('Exclusive proposal destination; preserve attempts')
    destination.mkdir(parents=True)
    with _scope(a,proof):
        evidence,source=_collect(a,destination)
        eid=_write_exclusive(destination/'OUTPUT_EVIDENCE_BINDINGS.proposal.json',evidence,destination)
        sid=_write_exclusive(destination/'T5_COMMITMENT_SOURCE.proposal.json',source,destination)
        commitments=dict(schema='A8DISK_T5_IDENTITY_COMMITMENTS_V1',source_reviewed=False,
                         scientific_eligibility_changed=False,batch_seal=source['batch_seal'],files=source['files'],closure_receipt=sid)
        cid=_write_exclusive(destination/'T5_IDENTITY_COMMITMENTS.proposal.json',commitments,destination)
    return dict(state='PROPOSAL_ONLY',production_authority=False,consumer_release=False,
                evidence=eid,source=sid,commitments=cid,
                metadata_only_T5_paths=sorted(r['path'] for r in source['files'] if a.metadata_root(r['path'])))
