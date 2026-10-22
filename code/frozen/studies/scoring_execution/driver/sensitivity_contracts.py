'Validate the sensitivity input records and comparison definitions.'
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from adapters import exclusive_json
from association import register
from native_entries import boundary_function
from source_bytes import checked, document, identity, require

REPLAY_NAMES=('numeric_source','numeric_evidence','numeric_receipt')
PROFILE=dict(schema='SENS35_AP_MATCHING_CONTRACT_V1',state='MINRUN_RELEASED_MATCHING_V1',
    receipt_schema='AP_SCORING_NUMERIC_OUTPUT_RECEIPT_V1',receipt_state='NUMERIC_OUTPUT_COMPLETE',
    receipt_flags=dict(synthetic_only=False,production_authority=False),
    evidence_schema='AP_SCORING_NATIVE_NUMERIC_EVIDENCE_V1',source_request='MINRUN_AP5_DETACHED_REPLAY')


def detached(item, destination):
    data=checked(item)
    with Path(destination).open('xb') as f:f.write(data)
    copied=identity(destination)
    require((copied['bytes'],copied['sha256'])==(item['bytes'],item['sha256']),'K7 detached copy bytes')
    return copied


def release_source_delivery(a,sources,ap,eligibility_result):
    cfg=a._control['sensitivity_export'];permission=document(cfg['permit']);profile=document(cfg['matching_contract'])
    require(permission['schema']=='MINRUN_SENS35_WRITER_PERMISSION_V1' and permission['task_id']=='SENS35'
        and permission['matching_contract']==cfg['matching_contract'] and permission['driver_build']==a._control['driver_build']
        and permission['source_sha256']==sources.rows[str(Path(cfg['source']))]['sha256'], 'K7 actual SENS writer permit')
    expected=dict(PROFILE,receipt_flags=dict(synthetic_only=a.synthetic,production_authority=False))
    require(all(profile[k]==v for k,v in expected.items()),'K7 matching profile/state/writer agreement')
    time=lambda s:datetime.fromisoformat(s.replace('Z','+00:00'))
    adoption=document(cfg['comparison_adoption_verification'])
    require(adoption['decision_id']=='COMPARISON-A1' and adoption['dual_tsa_offline_verified'] is True
        and time(adoption['verified_utc'])<time(a._t5_value['utc']),'K7 COMPARISON actual verified pre-T5 adoption')
    require(eligibility_result['numeric_source']==ap['numeric_source'],'K7 independent G42 AP association')
    out=Path(cfg['source_delivery_directory']);out.mkdir(parents=True,exist_ok=False)
    original={k:ap[k] for k in REPLAY_NAMES}
    replay={k:detached(item,out/(k+'.json')) for k,item in original.items()}
    replay['original_identities']=original
    views=a._official_ready['view_inputs']
    copied_r2=detached(views['r2']['score_receipt'],out/'R2_RECEIPT.json')
    copied_capture=detached(views['execution']['capture'],out/'CAPTURE.json')
    losses={t:detached(ap['loss_exports'][t],out/(t+'_LOSSES.json')) for t in ('news','notice')}
    exports={t:document(item) for t,item in losses.items()}
    metadata={}
    receipt=document(views['r2']['score_receipt'])
    for task in ('news','notice'):
        primary=next(i for i in receipt['files'] if Path(i['path']).name==task+'__PRIMARY.json')
        panel=document(primary)['panel_identity']
        daily=next(i for i in receipt['files'] if Path(i['path']).name==task+'__DAILY_LOSSES.csv')
        checked(daily)
        metadata[task]=dict(days=exports[task]['days'],evaluation_view=receipt['evaluation_view'],
            daily_common_key_counts=panel['daily_common_key_counts'],common_keys_sha256=panel['common_keys_sha256'],
            sealed_prediction_manifest_sha256=panel['sealed_prediction_manifest_sha256'],
            r2_score_receipt_sha256=views['r2']['score_receipt']['sha256'],main_daily_csv_sha256=daily['sha256'])
    auth=dict(schema='SENS35_POSTSCORE_AUTHORIZATION_V2',state='SEPARATE_EXECUTION_TASK_AUTHORIZED',task_id='SENS35',
        synthetic=a.synthetic,writer_permission=cfg['permit'],matching_contract=cfg['matching_contract'],
        source_sha256=permission['source_sha256'],driver_build=a._control['driver_build'],
        original_capture_verified=True,r2_receipt_verified=True,ap_replay_verified=True,
        independent_g42=deepcopy(eligibility_result),comparison_timestamp_verified_before_t5=True,
        comparison_verification=cfg['comparison_adoption_verification'],r2_original_identity=views['r2']['score_receipt'],
        verified_execution_authority=deepcopy(views),verified_task_metadata=metadata,replay_provenance=replay,
        capture_receipt=copied_capture,r2_score_receipt=copied_r2,loss_exports=losses,
        output_directory=cfg['output_directory'],spec_freeze_sha256=cfg['specification']['sha256'])
    auth_id=register(a,exclusive_json(out/'AUTHORIZATION.json',auth))
    profile_id=register(a,exclusive_json(out/'MATCHING_CONTRACT.json',profile))
    module=sources.module('_minrun_sens35',cfg['source'])
    require(auth['spec_freeze_sha256']==sources.rows[str(Path(cfg['specification']['path']))]['sha256'], 'K7 original spec bytes')
    clean=module.matching_check(exports,document(auth_id),document(profile_id))
    from reference_gate import sens35_boundary
    sens35_boundary(clean,module,out)
    modules=boundary_function(module.frozen_modules,PROJ=Path(a._control['project']))()
    result=module.analyse_tasks(clean,modules)
    result['provenance']=dict(authorization=auth_id,matching_contract=profile_id,writer_permission=cfg['permit'],
        spec_freeze_sha256=auth['spec_freeze_sha256'],inputs={k:auth[k] for k in ('capture_receipt','r2_score_receipt','loss_exports','replay_provenance')})
    require(not Path(cfg['output_directory']).exists(),'K7 fresh SENS output')
    module.write_outputs(result,Path(cfg['output_directory']))
    result_id=register(a,identity(Path(cfg['output_directory'])/'SENSITIVITY_UNEXPOSED.json'))
    csv_id=register(a,identity(Path(cfg['output_directory'])/'SENSITIVITY_UNEXPOSED.csv'))
    receiptid=register(a,exclusive_json(Path(cfg['output_directory'])/'SENSITIVITY_RECEIPT.json',dict(
        schema='MINRUN_SENS35_RECEIPT_V1',files=[result_id,csv_id],authorization=auth_id,matching_contract=profile_id,synthetic_only=a.synthetic)))
    return dict(identity=result_id,document=result,receipt=receiptid,authorization=auth_id,
                expected_slots=cfg['expected_slots'])
