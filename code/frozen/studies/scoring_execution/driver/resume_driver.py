'Check saved input identities before resuming the scoring calculation.'
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from adapters import exclusive_json, original_attachment, full_census
from association import register
from source_bytes import checked, document, identity, require

PREFIX=('primary_tests','sensitivity_tests','robustness_tests')
REST=('batch-parity','authorized-optional','sensitivity_tests','robustness_tests')
ATTEMPT_REL='paper_plan/minrun_execution_20261010/t5_final/a13f/source_delivery_final/SCORE_ATTEMPT_DECLARED_ONLY'
DEC_REL='studies/confirmation/comparison_specifications/SOURCE_DECISION_TIME_ALIGNMENT_A16_BATCH_STAGE_RESUME_20261011.md'
DEC_SHA='0c6a4563c3b7fe71eea98c0723468095c0d38b00bc4aa74ce03be95c93c3e22a'


def digest(control):
    return hashlib.sha256(json.dumps({k:v for k,v in control.items() if k not in ('release','_control_path')},sort_keys=True,separators=(',',':')).encode()).hexdigest()


def checkpoint(control, original_control, out):
    require(os.environ.get('SCORING_PHASE')=='source_runtime','Source-only checkpoint hashing')
    root=Path(control['attempt_directory'])
    require(root==Path(control['project'])/ATTEMPT_REL,'A16 exact original attempt only')
    decision=identity(Path(control['project'])/DEC_REL)
    require(decision['bytes']==2562 and decision['sha256']==DEC_SHA,'A16 adopted decision drift')

    cert_id=identity(control['c']['certificate_path']);cert=document(cert_id)
    require(cert['schema']=='C_SCORING_DUAL_OFFICIAL_VIEWS_V1','Exact official view metadata required')
    views=cert['view_inputs'];execution=views['execution']
    r2_id=identity(root/'02_R2_COMPLETE.json');r2=document(r2_id)
    require(r2['score_receipt']==views['r2']['score_receipt'] and r2['score_report']==views['r2']['score_report'],'R2 metadata association drift')
    rows=[identity(root/n) for n in ('ARMED.json','01_CAPTURE_COMPLETE.json','02_R2_COMPLETE.json')]+[cert_id]

    for view in ('original','r2'):
        rows+=list(views[view].values())
        state=Path(control[view if view=='r2' else 'original']['state_root'])/'scored'

        require(state.is_dir(),'Completed score directory missing')
        for p in sorted(state.iterdir()):
            require(p.is_file() and not p.is_symlink(),'Unexpected score output member')
            rows.append(identity(p))
    rows += [execution[k] for k in ('capture','clock','release','quiet_host')]
    readers={}
    for role in PREFIX:
        spec=control['readers'][role]
        readers[role]={k:identity(spec[v]) for k,v in (('source','output_path'),('receipt','receipt_path'))}
        rows+=list(readers[role].values())
    bypath={}
    for row in rows:
        checked(row);require(row['path'] not in bypath or bypath[row['path']]==row,'Conflicting completed identity')
        bypath[row['path']]=row
    require(not (root/'03_READERS_COMPLETE.json').exists(),'A16 only first incomplete batch stage')
    require(not Path(control['readers']['batch-parity']['receipt_path']).exists(),'Completed batch must not be repeated')
    failed=Path(control['readers']['batch-parity']['state_root'])/'scoring'
    partial=[]
    if failed.exists():
        for p in sorted(failed.rglob('*')):
            if p.is_file():partial.append(identity(p))
    return exclusive_json(out,dict(schema='MINRUN_A16_COMPLETED_CHECKPOINT_V1',state='IDENTITIES_ONLY_NOT_RESULTS',
        attempt_directory=str(root),first_incomplete='batch-parity',decision=decision,
        original_control=original_control,certificate=cert_id,r2_stage=r2_id,readers=readers,
        artifacts=[bypath[k] for k in sorted(bypath)],failed_batch_outputs=partial,
        failed_batch_directory=str(failed),opaque_values_decoded=False,
        observed_utc=datetime.now(timezone.utc).isoformat()))


def tree_identities(directory):
    root=Path(directory)
    require(root.is_dir() and not root.is_symlink(), 'Completed directory missing or symlink: '+str(root))
    result=[]
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'Completed tree symlink refused')
        if path.is_file():result.append(identity(path))
        else:require(path.is_dir(), 'Unexpected completed tree member')
    return result


def verified_checkpoint(control, *, synthetic=False):
    cfg=control['resume'];value=document(cfg['checkpoint'])
    require(value['schema']=='MINRUN_A16_COMPLETED_CHECKPOINT_V1' and value['first_incomplete'] in ('batch-parity','ap-numbers','rd-joint'), 'A16 checkpoint schema/stage')
    require(value['attempt_directory']==control['attempt_directory'],'A16 different attempt')
    require(synthetic or value['attempt_directory']==str(Path(control['project'])/ATTEMPT_REL),'A16 attempt not authorised')
    require(value['opaque_values_decoded'] is False,'A16 checkpoint must contain identities only')
    old=document(value['original_control'])

    for key in ('project','attempt_directory','original','r2','capture','readers'):
        require(control[key]==old[key],'A16 original invocation/input/output drift: '+key)
    for key in ('ap','c','exporter'):
        if key in old:require(control[key]==old[key],'A16 unchanged scientific input contract: '+key)
    if 'sensitivity_export' in old:
        require({k:v for k,v in control['sensitivity_export'].items() if k!='permit'}==
                {k:v for k,v in old['sensitivity_export'].items() if k!='permit'},'A16 SENS35 science contract changed')
    if 'rd' in old:
        require({k:v for k,v in control['rd'].items() if k not in ('request_template','t5_projection')}==
                {k:v for k,v in old['rd'].items() if k not in ('request_template','t5_projection')},'A16 notice_delays science contract changed')
    for item in value['artifacts']:checked(item)
    cert=document(value['certificate']);r2=document(value['r2_stage'])
    require(cert['view_inputs']['r2']['score_receipt']==r2['score_receipt'] and cert['view_inputs']['r2']['score_report']==r2['score_report'],'A16 R2 identity drift')
    root=Path(control['attempt_directory'])
    if value['first_incomplete']=='batch-parity':
        require(not (root/'03_READERS_COMPLETE.json').exists() and not Path(control['readers']['batch-parity']['receipt_path']).exists(),'A16 batch already completed')
    else:
        require(value.get('readers_complete') in value['artifacts'], 'AP resume requires timestamped reader completion identity')
        require(set(value['readers'])==set(PREFIX+REST), 'AP resume completed reader census')
        require(value['readers_complete']['path']==str(root/'03_READERS_COMPLETE.json'), 'AP reader completion path drift')
        for tree in value['completed_trees']:
            actual=tree_identities(tree['directory'])
            require(actual==tree['files'], 'AP completed tree census/identity drift: '+tree['directory'])
        if value['first_incomplete']=='ap-numbers':
            require(not (root/'04_AP_COMPLETE.json').exists(), 'AP already completed; refuse repeated AP stage')
        else:
            require(value.get('ap_complete') in value['artifacts'] and
                    value['ap_complete']['path']==str(root/'04_AP_COMPLETE.json'), 'notice_delays resume requires exact AP completion identity')
            require(not (root/'05_RD_COMPLETE.json').exists(), 'notice_delays already completed; refuse repetition')
            require(value['prior_ap_checkpoint']['path']!=cfg['checkpoint']['path'], 'notice_delays checkpoint cannot refer to itself')
            require({k:r['path'] for k,r in value['ap_state'].items()}==completed_ap_paths(control), 'notice_delays checkpoint AP pointer/writer contract drift')
            require(all(r in value['artifacts'] for r in value['ap_state'].values()), 'notice_delays AP identity absent from completed census')
    return value,old,cert,r2


def gate(control, sources):
    value,old,cert,r2=verified_checkpoint(control)
    cfg=control['resume'];t6=document(cfg['t6'])
    require(t6['schema']=='MINRUN_A16_T6_BINDING_V1' and t6['state']=='T6_DUAL_OFFLINE_VERIFIED', 'Actual T6 required')
    require(t6['checkpoint']==cfg['checkpoint'] and t6['driver_build']==control['driver_build'], 'T6 checkpoint/current build drift')
    require(len(t6['tsa_verifications'])==2 and {x['tsa'] for x in t6['tsa_verifications']}=={'freetsa','digicert'} and all(x['offline_signature_verified'] and x['manifest_imprint_verified'] for x in t6['tsa_verifications']),'T6 both offline TSA verifications required')
    for row in t6['tsa_verifications']:checked(row['verification_receipt'])
    stamp=lambda x:datetime.fromisoformat(x.replace('Z','+00:00'))
    require(stamp(r2['completed_utc'])<stamp(t6['utc'])<datetime.now(timezone.utc),'T6 must follow completed R2 and precede resume')
    files={(r['path'],r['bytes'],r['sha256']) for r in t6['files']}
    require((cfg['checkpoint']['path'],cfg['checkpoint']['bytes'],cfg['checkpoint']['sha256']) in files,'T6 lacks checkpoint')
    for row in (cfg['history'],cfg['failed_batch_archive'],control['sensitivity_export']['permit'],control['rd']['request_template']):
        checked(row);require((row['path'],row['bytes'],row['sha256']) in files, 'T6 lacks actual resume input identity')
    request=document(control['rd']['request_template']);original_request=document(old['rd']['request_template'])
    expected=deepcopy(original_request)
    expected['bindings']['scorer_freeze']=identity(Path(__file__).parent/'RUNTIME_SOURCES.json')
    require(request==expected,'A16 only current notice_delays scorer inventory binding may change')
    projection=document(control['rd']['t5_projection']);prior_projection=document(old['rd']['t5_projection'])
    expected_files=dict(prior_projection['files']);expected_files.update({r['path']:r['sha256'] for r in t6['files']})
    require(projection['utc']==prior_projection['utc'] and projection['files']==expected_files,
            'A16 notice_delays supplementary identity projection drift')


    for row in sources.rows.values():
        checked(row);require((row['path'],row['bytes'],row['sha256']) in files,'T6 lacks current K1 source: '+row['logical_path'])
    require(identity(Path(__file__).parent/'BUILD_IDENTITY.json')==control['driver_build'],'Current resume build drift')
    require(identity(sys.executable)==control['interpreter'],'Resume interpreter drift')
    require(control['t5']==old['t5'],'Original pre-score T5 role must remain unchanged')
    original_release=document(old['release'])
    require(original_release['schema']=='MINRUN_SCORE_RELEASE_V1' and original_release['control_sha256_without_release']==digest(old)
        and original_release['driver_build']==old['driver_build'] and original_release['permit']==old['original']['permit']
        and original_release['capture_clock_authorized'] is True,'Original release identity/permit gate')
    old_t5=document(old['t5'])
    require(old_t5['state']=='T5_VERIFIED_AND_BOUND' and len(old_t5['tsa_verifications'])==2
        and all(r['offline_signature_verified'] and r['manifest_imprint_verified'] for r in old_t5['tsa_verifications']), 'Original dual-TSA T5 gate')


    history=document(cfg['history'])['files']
    def old_checked(item):
        matches=[r for r in history if r['original']==item]
        if matches:
            require(len(matches)==1 and all(matches[0]['archive'][k]==item[k] for k in ('bytes','sha256')), 'A16 old code history mismatch')
            checked(matches[0]['archive'])
        else:checked(item)
    old_checked(old['driver_build']);old_checked(original_release['capture_clock_writer'])
    require(original_release['capture_clock_writer']['path']==str(Path(__file__).parent/'backend.py'),'Original capture writer identity')
    for row in old_t5['metadata_files']:old_checked(row)
    for row in old_t5['tsa_verifications']:checked(row['verification_receipt'])
    for row in control['corrected_eligibility']['authority_files']:checked(row)
    require(control['corrected_eligibility']==old['corrected_eligibility']
        and stamp(control['corrected_eligibility']['verified_seal_utc'])<stamp(old_t5['utc']), 'Original corrected eligibility chronology')
    failed=Path(value.get('failed_batch_directory',control['readers']['batch-parity']['state_root']+'/scoring'))
    if value['first_incomplete']=='batch-parity':
        require(not failed.exists(),'A16 failed batch outputs must be exclusively archived before resume')
    if value.get('failed_batch_outputs'):
        move=document(cfg['failed_batch_archive'])
        require(move['checkpoint']==cfg['checkpoint'] and move['source_directory']==str(failed), 'A16 partial archive subject drift')
        require([r['original'] for r in move['files']]==value['failed_batch_outputs'], 'A16 partial archive census drift')
        for r in move['files']:
            require(all(r['original'][k]==r['archive'][k] for k in ('bytes','sha256')), 'A16 partial archive identity drift')
            checked(r['archive'])
    if value['first_incomplete']=='ap-numbers':


        prior=document(value['prior_checkpoint'])
        require(prior['first_incomplete']=='batch-parity' and prior['attempt_directory']==value['attempt_directory'], 'AP prior checkpoint drift')
        if prior.get('failed_batch_outputs'):
            previous_move=document(cfg['failed_batch_archive'])
            require(previous_move['checkpoint']==value['prior_checkpoint'] and previous_move['source_directory']==prior['failed_batch_directory'], 'AP prior failed-batch archive subject drift')
            require([r['original'] for r in previous_move['files']]==prior['failed_batch_outputs'], 'AP prior failed-batch archive census drift')
            for item in previous_move['files']:
                require(all(item['original'][k]==item['archive'][k] for k in ('bytes','sha256')), 'AP prior failed-batch archive identity drift')
                checked(item['archive'])
        move=document(cfg['original214_archive'])
        require(move['checkpoint']==cfg['checkpoint'] and move['source_directory']==control['ap']['score_news_full_window']['output_directory'], 'AP partial news_full_window archive subject drift')
        require(move['files']==value['partial_original214_archive_files'], 'AP partial news_full_window move census drift')
        require(not Path(move['source_directory']).exists(), 'AP partial news_full_window must be exclusively moved')
        for item in move['files']:
            require(all(item['original'][k]==item['archive'][k] for k in ('bytes','sha256')), 'AP partial move bytes mismatch')
            checked(item['archive'])
        checked(cfg['original214_archive'])
        require(tuple(cfg['original214_archive'][k] for k in ('path','bytes','sha256')) in files, 'T6 lacks partial news_full_window move record')
    if value['first_incomplete']=='rd-joint':
        prior=document(value['prior_ap_checkpoint'])
        require(prior['first_incomplete']=='ap-numbers' and prior['attempt_directory']==value['attempt_directory'], 'notice_delays prior AP checkpoint drift')
        prior_batch=document(prior['prior_checkpoint'])
        if prior_batch.get('failed_batch_outputs'):
            previous=document(cfg['failed_batch_archive'])
            require(previous['checkpoint']==prior['prior_checkpoint'] and previous['source_directory']==prior_batch['failed_batch_directory'] and
                    [r['original'] for r in previous['files']]==prior_batch['failed_batch_outputs'], 'notice_delays prior failed-batch archive drift')
            for item in previous['files']:
                require(all(item['original'][k]==item['archive'][k] for k in ('bytes','sha256')), 'notice_delays prior batch move bytes drift')
                checked(item['archive'])
        prior_move=document(cfg['original214_archive'])
        require(prior_move['checkpoint']==value['prior_ap_checkpoint'] and
                prior_move['files']==prior['partial_original214_archive_files'], 'notice_delays prior news_full_window move subject drift')
        for item in prior_move['files']:
            require(all(item['original'][k]==item['archive'][k] for k in ('bytes','sha256')), 'notice_delays prior news_full_window archive drift')
            checked(item['archive'])
        partial=document(cfg['rd_partial_archive'])
        require(partial['checkpoint']==cfg['checkpoint'] and partial['files']==value['partial_rd_archive_files'], 'notice_delays partial move subject drift')
        require(not Path(control['rd']['output_directory']).exists() and
                not Path(control['rd']['g42_input_path']).exists() and not Path(control['rd']['g42_output_path']).exists(), 'Partial notice_delays/G42 outputs must be absent or exclusively moved')
        for item in partial['files']:
            require(all(item['original'][k]==item['archive'][k] for k in ('bytes','sha256')), 'notice_delays partial archive identity drift')
            checked(item['archive'])
        for required in (cfg['original214_archive'],cfg['rd_partial_archive']):
            checked(required)
            require(tuple(required[k] for k in ('path','bytes','sha256')) in files, 'T6 lacks preserved move record')
    quiet=document(control['quiet_host'])
    require(quiet['kind']=='PROCEDURAL_QUIET_HOST' and quiet['unknown_activity'] is False and quiet['concurrent_activity'] is False and quiet['single_direct_terminal'] is True and quiet['dispositions'] and all(x['terminal'] is True for x in quiet['dispositions']),'Actual resume quiet dispositions required')
    release=document(control['release'])
    require(release['schema']=='MINRUN_RESUME_RELEASE_V1' and release['control_sha256_without_release']==digest(control) and release['checkpoint']==cfg['checkpoint'] and release['t6']==cfg['t6'] and release['driver_build']==control['driver_build'] and release['original_control']==value['original_control'] and release['resume_original_score'] is False and release['resume_capture'] is False and release['source_authorized'] is True,'Actual bounded resume release required')
    for key in ('source','signed_utc','signature'):
        require(release.get(key) not in (None,'','PENDING'),'Unsigned resume release: '+key)
    require(stamp(t6['utc'])<stamp(release['signed_utc'])<datetime.now(timezone.utc),'Resume release chronology')
    return value,old,cert,r2,t6


def hydrate(backend, control, sources, cert, r2, checkpoint, t6):
    import association
    backend.load_definitions()
    backend.original_receipt=cert['view_inputs']['original']['score_receipt']
    ex=cert['view_inputs']['execution']
    backend.capture_id,backend.clock_id=ex['capture'],ex['clock']
    backend.armed=ex['armed_utc'];backend.r2_started=r2['started_utc'];backend.r2_completed=r2['completed_utc'];backend.r2_receipt=r2['score_receipt']


    backend.association_context=association.installed(control,sources,source_commitment=t6)
    backend.a=backend.association_context.__enter__()
    backend.a._official_ready=deepcopy(cert)
    for row in checkpoint['artifacts']:register(backend.a,row)
    backend.certificate_id=checkpoint['certificate']
    backend.reader_results=deepcopy(checkpoint['readers'])


def continue_batch(backend, control, checkpoint):
    out=Path(control['attempt_directory'])
    from reader_dispatch import run
    backend.reader_results.update(run(backend.a,backend.sources,REST))
    readers=backend.reader_results
    evidence=[checkpoint['artifacts'],exclusive_json(out/'03_READERS_COMPLETE.json',readers)]
    return continue_ap(backend,control,checkpoint,evidence)


def continue_ap(backend, control, checkpoint, evidence=None):
    out=Path(control['attempt_directory']);readers=backend.reader_results
    evidence=[checkpoint['artifacts']] if evidence is None else evidence
    numeric=backend.ap_numbers(readers)
    attachment=original_attachment(numeric['original_news_214'],backend.original_receipt)
    evidence.append(exclusive_json(out/'04_AP_COMPLETE.json',numeric))
    return continue_rd(backend,control,checkpoint,numeric,attachment,evidence)


def continue_rd(backend,control,checkpoint,numeric,attachment,evidence=None):
    out=Path(control['attempt_directory'])
    evidence=[checkpoint['artifacts']] if evidence is None else evidence
    rd,eligibility=backend.rd_and_independent_eligibility(numeric);full_census(numeric,rd)
    evidence.append(exclusive_json(out/'05_RD_COMPLETE.json',dict(rd=rd,eligibility=eligibility)))
    sens=backend.sens35_from_detached_ap(numeric)
    evidence.append(exclusive_json(out/'06_SENS_COMPLETE.json',sens))
    exported=backend.export(numeric,rd,eligibility,sens,attachment)
    evidence.append(exclusive_json(out/'07_EXPORT_COMPLETE.json',exported))
    final=dict(schema='MINRUN_A16_RESUMED_ATTEMPT_V1',state='COMPLETE',checkpoint=control['resume']['checkpoint'],t6=control['resume']['t6'],evidence=evidence,original_score_repeated=False,capture_repeated=False,r2_repeated=False,completed_readers_repeated=False,first_incomplete=checkpoint['first_incomplete'],batch_repeated=False,optional_repeated=False,ap_repeated=False,original214_repeated=False)
    exclusive_json(out/'A16_RESUME_COMPLETE.json',final)
    return final


def completed_ap_paths(control):
    cfg=control['ap'];n=Path(cfg['output_directory']);o=Path(cfg['score_news_full_window']['output_directory'])
    return dict(manifest=cfg['manifest_path'],context=cfg['context_path'],
        numeric_source=str(n/'SCORING_NUMERIC.json'),numeric_evidence=str(n/'SCORING_NUMERIC_EVIDENCE.json'),
        numeric_receipt=str(n/'SCORING_NUMERIC_RECEIPT.json'),news_losses=str(n/'news__SENS35_LOSSES.json'),notice_losses=str(n/'notice__SENS35_LOSSES.json'),
        original_source=str(o/'SPECIFIED_NEWS_214.json'),original_proof=str(o/'NEWS_FULL_WINDOW_PARITY.json'),original_receipt=str(o/'NEWS_FULL_WINDOW_RECEIPT.json'))


def hydrate_ap(backend,control,checkpoint):
    from backend import declare_inputs
    apcfg=control['ap'];ids=checkpoint['ap_state']

    for item in ids.values():
        require(item in checkpoint['artifacts'], 'AP hydrate identity absent from checkpoint')
        register(backend.a,item)
    contract=deepcopy(document(apcfg['scientific_contract']))
    declare_inputs(backend.a,contract)
    contract.update(manifest=ids['manifest'],original_attachment=ids['original_source'],
        cutoff_snapshot=backend.capture_id,output_directory=apcfg['output_directory'],chunk=apcfg['chunk'])
    backend.ap_contract=contract


    backend.ap=dict(record=document(ids['numeric_source']),numeric_source=ids['numeric_source'],
        numeric_evidence=ids['numeric_evidence'],numeric_receipt=ids['numeric_receipt'],
        loss_exports={t:ids[t+'_losses'] for t in ('news','notice')})
    backend.original_science=dict(source=ids['original_source'],document=document(ids['original_source']),
        proof=ids['original_proof'],receipt=ids['original_receipt'])
    return backend.ap['record']


def execute(control,sources,backend,*,run=False):
    checkpoint,old,cert,r2,t6=gate(control,sources)
    try:
        hydrate(backend,control,sources,cert,r2,checkpoint,t6)
        if run:
            if checkpoint['first_incomplete']=='rd-joint':
                numeric=hydrate_ap(backend,control,checkpoint)
                attachment=original_attachment(numeric['original_news_214'],backend.original_receipt)
                return continue_rd(backend,control,checkpoint,numeric,attachment)
            return continue_ap(backend,control,checkpoint) if checkpoint['first_incomplete']=='ap-numbers' else continue_batch(backend,control,checkpoint)
        return dict(state='A16_RESUME_IDENTITIES_READY',first_incomplete=checkpoint['first_incomplete'])
    finally:backend.close()


def prepare_main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--control',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    a=p.parse_args(argv);c=json.loads(a.control.read_bytes())
    result=checkpoint(c,identity(a.control),a.out);print(json.dumps(result))

if __name__=='__main__':prepare_main()
