"""Complete prediction seal and A2BATCH-shaped score inputs; no scoring here."""
from pathlib import Path
import numpy as np
import pandas as pd
from a8_common import *

FAMILIES = {'R8_news': [('L_count+','M+'),('L_chen+','M+')],
            'R8_notice': [('L14+','M+_n'),('L_Laz+','M+_n'),('L_chen_notice+','M+_n')]}
STATE_MAP = {'COMPLETE':'READY_FOR_FROZEN_SCORING','COMPLETE_WITH_UNAVAILABLE_CONFIGURATIONS':'READY_FOR_FROZEN_SCORING','INCOMPLETE_BUDGET':'NOT_RUN_BUDGET',
             'INCOMPLETE_CS8_BUDGET':'NOT_RUN_BUDGET','INCOMPLETE_FAILURE':'DEVIATION',
             'NOT_RUN_BUDGET':'NOT_RUN_BUDGET','NOT_RUN_INPUT_UNAVAILABLE':'NOT_RUN_INPUT_UNAVAILABLE',
             'NOT_RUN_A8_AMENDMENT_2':'NOT_RUN_A8_AMENDMENT_2','NOT_RUN_PARITY_FAILED':'NOT_RUN_PARITY_FAILED','DEVIATION':'DEVIATION'}

def grid(frame,source,variant):
    frame = normalize(frame)
    if source in ('news','lear'):
        start,end = ('2025-01-01','2025-12-31') if variant == '2025_fixed_validation' else ('2026-03-01','2026-09-30')
        expected = pd.date_range(start,end).strftime('%Y-%m-%d').tolist()
        counts = frame.groupby('target_day').size()
        require(list(counts.index) == expected and (counts == 72).all(), 'Incomplete sealed news stage grid')
        require(set(zip(frame.region,frame.horizon)) == {(r,h) for r in ('NSW1','QLD1','TAS1') for h in range(24)}, 'News region/horizon drift')
        expected_origin = pd.to_datetime(frame.target_day).dt.tz_localize('Australia/Brisbane').dt.tz_convert('UTC')
        require((frame.origin == expected_origin).all() and (frame.target_time == frame.origin+pd.to_timedelta(frame.horizon,unit='h')).all(), 'News seal clocks drift')
    else:
        counts = frame.groupby('target_day').size()
        require(list(counts.index) == pd.date_range('2026-08-01','2026-09-30').strftime('%Y-%m-%d').tolist() and
                (counts == 8640).all(), 'Incomplete sealed notice grid')
        require(set(frame.region) == {'NSW1','QLD1','SA1','TAS1','VIC1'} and set(frame.horizon) == {5,10,15,20,25,30}, 'Notice region/horizon drift')
        require((frame.target_time == frame.origin+pd.to_timedelta(frame.horizon,unit='m')).all(), 'Notice seal clock drift')
        counts_by_target = frame.groupby('target_time').size()
        expected_targets = pd.date_range('2026-08-01','2026-10-01',inclusive='left',freq='5min',tz='Australia/Brisbane').tz_convert('UTC')
        require(counts_by_target.index.equals(expected_targets) and (counts_by_target == 30).all(), 'Notice dispatch grid drift')
    require(np.isfinite(frame.prediction.to_numpy()).all(), 'Nonfinite seal prediction')
    return frame

def create_seal(state,A,manifest,stage_tasks,dispositions,permit,conf_seal_path,feature_freeze,grid_check=grid):
    state = Path(state)
    destination = state/'SEAL_A8BATCH.json'
    if destination.exists():
        return verify_seal(state)
    inputs = read_json(state/'BATCH_INPUT_FREEZE.json')
    require(inputs['conf_seal'] == identity(conf_seal_path), 'Batch main seal drift')
    checked(inputs['code_freeze'])
    predictions,artifacts,stages = [],[],[]
    retained_budget_evidence = []
    for name,row in dispositions.items():
        require(name in stage_tasks, 'Unregistered batch stage')
        stage_path = state/'stages'/(name+'.json')
        require(read_json(stage_path) == row, 'Batch disposition identity drift')
        stages.append(dict(row,receipt_identity=identity(stage_path)))
        if row.get('budget_transition'):
            require(name=='CPS8' and row['state']=='NOT_RUN_BUDGET', 'Unregistered budget transition')
            for key in ('retained_previous','remedy_used','consumed_marker','ledger_snapshot'):
                item=row['budget_transition'][key];checked(item);retained_budget_evidence.append(item)
        if row['state'] not in COMPLETE:
            require(not row.get('partial_predictions_eligible_for_scoring'), 'Partial stage cannot be scored')
            continue
        eligible = row['eligible_tasks']
        groups = {}
        for task in stage_tasks[name]:
            if A.execution.task_id(task) not in eligible:
                continue
            rec = A.execution.reusable(state,task,sha(state/'features/manifest.json'),permit)
            require(rec is not None, 'Completed stage has missing/drifted fit')
            artifacts.append(identity(A.execution._receipt_path(state,task),kind='fit_receipt'))
            if task.task != 'lear':
                require(state in Path(rec['model_path']).resolve().parents, 'Batch model must live under own state')
                artifacts.append(identity(rec['model_path'],kind='LightGBM_model'))
            else:
                require(rec.get('component_pairs') == 288 and len(rec.get('windows',[])) == 12, 'Incomplete LEAR receipt')
                for window in rec['windows']:
                    for key,hash_key,kind in (('model_path','model_sha256','LEAR_window_models'),
                                              ('input_scaling_path','input_imputation_scaling_sha256','LEAR_input_scaling')):
                        require(state in Path(window[key]).resolve().parents and sha(window[key]) == window[hash_key], 'Batch LEAR artifact ownership/identity drift')
                        artifacts.append(identity(window[key],kind=kind))
            # Selection predictions are training-period diagnostics, never D score inputs.
            if task.variant == 'cps8_selection':
                artifacts.append(identity(rec['prediction_path'],kind='CPS8_training_holdout_prediction'))
                continue
            groups.setdefault((task.task,task.arm,task.seed,task.variant),[]).append(rec)
        for (source,arm,seed,variant),records in groups.items():
            frame = normalize(pd.concat([pd.read_parquet(r['prediction_path']) for r in records],ignore_index=True))
            frame = grid_check(frame,source,variant)
            from cps8_runner import cps_root
            prediction_root = cps_root(state)/'sealed' if variant == 'cps8_D' else state/'sealed'
            path = prediction_root/(source+'__'+arm+'__s'+str(seed)+'__'+variant+'.parquet')
            path.parent.mkdir(parents=True,exist_ok=True)
            if path.exists():
                require(normalize(pd.read_parquet(path)).equals(frame),'Partial sealed prediction drift')
            else:
                temporary = path.with_name(path.name+'.atomic.'+__import__('uuid').uuid4().hex)
                frame.to_parquet(temporary,index=False)
                os.replace(temporary,path)
            predictions.append(identity(path,source=source,arm=arm,seed=seed,variant=variant,rows=len(frame),
                                        common_keys_sha256=__import__('hashlib').sha256(pd.util.hash_pandas_object(frame[KEYS],index=False).to_numpy().tobytes()).hexdigest()))
    extra = [*retained_budget_evidence,identity(feature_freeze),identity(state/'features/manifest.json'),identity(state/'BATCH_INPUT_FREEZE.json')]
    b0_path = state/'B0_REPRODUCTION.json'
    if b0_path.is_file():
        b0 = read_json(b0_path)
        require(b0['state'] == 'PASS', 'B0 parity failure prohibits batch seal')
        for item in b0['artifacts']:
            checked(item)
        extra += [identity(b0_path),*b0['artifacts']]
    else:
        require(state.resolve() != (OUT/'state').resolve(), 'Production batch requires B0 reproduction gate')
    from dly8_rebuild import dly_root
    from cps8_runner import cps_root
    # PCX subsequently charges the same live ledger. Seal its pre-score snapshot
    # so that the authorised continuation cannot invalidate the batch seal.
    ledger = state/'FITTING_WALL_LEDGER.json'
    snapshot = state/'sealed/FITTING_WALL_LEDGER_PRET5.json'
    if ledger.exists():
        snapshot.parent.mkdir(parents=True,exist_ok=True)
        atomic_copy(ledger,snapshot)
    events = state/'FITTING_WALL_EVENTS.jsonl'
    event_snapshot = state/'sealed/FITTING_WALL_EVENTS_PRET5.jsonl'
    if events.exists():
        atomic_copy(events,event_snapshot)
    paths = [state/r for r in ('WORKER_BINDING.json','RESOURCE_RECEIPT.json','OPTIONAL_ADMISSION.json','DISK_RESERVATION.json')]
    paths += [state/'PCX_ADMISSION.json',state/'RHO.json',state/'R8_ADMISSION.json',*sorted((state/'admissions').glob('*.json'))]
    paths += [event_snapshot]
    paths += [snapshot]
    paths += [cps_root(state)/'CPS8_SELECTION.json',cps_root(state)/'CONTROL_RECEIPT.json',
              dly_root(state)/'mode1/DLY8_RECEIPT.json',dly_root(state)/'DLY8_SEAL_PRIMARY.json']
    for p in paths:
        if p.exists():
            extra.append(identity(p))
    seal = dict(state='ALL_A8BATCH_REGISTERED_PREDICTIONS_SEALED',sealed_utc=now(),sealed_before_outcome_scoring=True,
                conf_seal=inputs['conf_seal'],conf_seal_sha256=inputs['conf_seal']['sha256'],
                code_freeze=inputs['code_freeze'],adapter_freeze_sha256=inputs['adapter_freeze_sha256'],
                feature_manifest_path=str(state/'features/manifest.json'),feature_manifest_sha256=sha(state/'features/manifest.json'),
                fit_receipts_and_models=artifacts,predictions=predictions,stage_dispositions=stages,auxiliary=extra,
                truth_panels=read_json(conf_seal_path)['truth_panels'],outcome_scoring_performed=False,
                partial_predictions_scored=False,single_seed_R8=not any(i['seed'] != SEED and i['arm'] in R8_NEWS for i in predictions),drop_order=list(DROP_ORDER))
    write_json(destination,seal,exclusive=True)
    return seal

def verify_seal(state):
    path = Path(state)/'SEAL_A8BATCH.json'
    seal = read_json(path)
    require(seal['state'] == 'ALL_A8BATCH_REGISTERED_PREDICTIONS_SEALED' and seal['sealed_before_outcome_scoring'], 'Invalid A8 batch seal')
    require(seal['conf_seal_sha256'] == seal['conf_seal']['sha256'], 'Main seal binding drift')
    checked(seal['conf_seal'])
    checked(seal['code_freeze'])
    require(sha(seal['feature_manifest_path']) == seal['feature_manifest_sha256'], 'Batch feature/seal drift')
    for item in [*seal['fit_receipts_and_models'],*seal['predictions'],*seal['auxiliary'],
                 *(d['receipt_identity'] for d in seal['stage_dispositions'])]:
        checked(item)
        if item.get('kind') == 'fit_receipt':
            rec = read_json(item['path'])
            require(sha(rec['prediction_path']) == rec['prediction_sha256'], 'Sealed per-fit prediction drift')
            if rec['task']['task'] != 'lear':
                require(sha(rec['model_path']) == rec['model_sha256'], 'Sealed per-fit model drift')
    return seal

def family_inputs(name,row,predictions):
    require(row['state'] in STATE_MAP, 'Unknown stage disposition')
    result = dict(state=STATE_MAP[row['state']],source_state=row['state'],reason=row.get('reason'),
                  family_m=len(FAMILIES[name]),reports=[],contrasts=[dict(arm=a,reference=r) for a,r in FAMILIES[name]],
                  single_seed=True,maximum_reading='NOT_FULLY_CHECKED')
    if row['state'] in COMPLETE:
        required = {a for p in FAMILIES[name] for a in p}
        found = {i['arm']:i for i in predictions if i['variant'] == 'main' and i['seed'] == SEED}
        require(required <= set(found), 'Complete R8 family missing sealed member')
        result['predictions'] = {a:found[a] for a in sorted(required)}
    else:
        result['reason'] = row.get('reason') or row['state']
        result['predictions'] = {}
    return result

def export_score_inputs(state):
    """A2BATCH identity/families/descriptive shapes; no fabricated statistics."""
    state = Path(state)
    seal = verify_seal(state)
    rows = {row['stage']:row for row in seal['stage_dispositions']}
    families = {name:family_inputs(name,rows[name],seal['predictions']) for name in FAMILIES}
    descriptive = {}
    for source,pairs in {'news':[('M0','N'),('M','M0'),('M+0','N'),('M+','M+0'),('M+','M')],
                         'notice':[('M0_n','N'),('M_notice','M0_n'),('M+0_n','N'),('M+_n','M+0_n'),('M+_n','M_notice')]}.items():
        name = 'R8_'+source
        for arm,reference in pairs:
            descriptive[source+':'+arm+'-'+reference] = dict(source=source,arm=arm,reference=reference,
                state=families[name]['state'],reason=families[name]['reason'],unadjusted=True,single_seed=True)
    delayed = []
    from dly8_rebuild import dly_root
    for mode in (1,2):
        path = dly_root(state)/('mode'+str(mode))/'DLY8_RECEIPT.json'
        require(path.is_file(), 'Both DLY8 modes must be sealed before score-input export')
        rec = read_json(path)
        require(rec['binding']['main_conf_seal'] == seal['conf_seal'], 'DLY8/main seal drift')
        if mode == 2:
            require(rec['binding']['source_seal'] == identity(state/'SEAL_A8BATCH.json'), 'DLY8/R8 batch seal drift')
        for item in ([rec['parity']] if rec.get('parity') else []) + rec['predictions']:
            checked(item)
        delayed.append(identity(path,mode=mode))
    from cps8_runner import cps_root
    capacity = dict(state='NOT_RUN_BUDGET',reason='Metadata-only batch drop',reports=[])
    if rows.get('CPS8',{}).get('state') in ('DEVIATION','INCOMPLETE_FAILURE','NOT_RUN_PARITY_FAILED'):
        capacity = dict(state='NOT_RUN_PARITY_FAILED' if rows['CPS8']['state'] == 'NOT_RUN_PARITY_FAILED' else 'DEVIATION',reason=rows['CPS8']['reason'],reports=[])
    if (cps_root(state)/'CPS8_SELECTION.json').exists() and all(rows.get('CPS8_D_'+s,{}).get('state') in COMPLETE for s in ('news','notice')):
        require(all(rows.get('CPS8_D_'+s,{}).get('state') in COMPLETE for s in ('news','notice')), 'Partial CPS8 D family cannot enter score inputs')
        selection = read_json(cps_root(state)/'CPS8_SELECTION.json')
        controls = read_json(cps_root(state)/'CONTROL_RECEIPT.json')
        require(controls['state'] == 'PASS', 'CPS8 g0 controls incomplete')
        main = read_json(checked(seal['conf_seal']))
        from dly8_rebuild import model_bank
        from cps8_runner import ARMS,g0_gate
        notice_controls = model_bank(main,ARMS['notice'])
        for arm,rec in notice_controls.items():
            task = rec['task']
            # Explicit g0 parameter check is recorded for every main-bank control.
            from a8_adapter import load
            A = load(expected=seal['adapter_freeze_sha256'],preverified=True)
            g0_gate(A.params(A.scheduler.FitTask(**task)),rec,'notice')
        capacity = dict(state='READY_FOR_FROZEN_SCORING',reports=[],selection=identity(cps_root(state)/'CPS8_SELECTION.json'),
                        selected=selection['selected'],control_receipt=identity(cps_root(state)/'CONTROL_RECEIPT.json'),
                        notice_g0_models=[r['model_identity'] for r in notice_controls.values()],
                        predictions=[i for i in seal['predictions'] if i['variant'] == 'cps8_D'],
                        family_m={'news':2,'notice':3},primary_schedule_difference_descriptive=True)
        capacity['news_all_g0_no_D_fit'] = controls['news_all_g0_no_D_fit']
        capacity['notice_all_g0_no_D_fit'] = all(selection['selected']['notice/'+a] == 'g0' for a in ARMS['notice'])
        capacity['news_state'] = 'CAPACITY_SELECTION_KEPT_G0' if controls['news_all_g0_no_D_fit'] else 'READY_FOR_FROZEN_SCORING'
        capacity['notice_g0_predictions'] = [i for i in main['predictions'] if
                      i.get('source') == 'notice' and i.get('arm') in ARMS['notice'] and i.get('seed') == SEED and i.get('variant') == 'main']
        require(len(capacity['notice_g0_predictions']) == 4, 'CPS8 notice g0 prediction census incomplete')
        for item in capacity['notice_g0_predictions']:
            checked(item)
    result = dict(state='A8BATCH_SCORE_INPUTS_SEALED_NOT_SCORED',conf_seal_sha256=seal['conf_seal_sha256'],
                  code_freeze=seal['code_freeze'],seal=identity(state/'SEAL_A8BATCH.json'),families=families,
                  descriptive=descriptive,CPS8=capacity,DLY8=delayed,stage_dispositions=seal['stage_dispositions'],
                  production_score_performed=False,statistics_computed=False)
    write_json(state/'score_inputs/A8BATCH_INPUTS.json',result,exclusive=True)
    return result

def export_scored(result,code_freeze,seal,conf_seal,destination):
    """Later scorer can emit the exact A2BATCH families/reports/descriptive shape."""
    for item in (code_freeze,seal,conf_seal):
        checked(item)
    from a8_freeze import verify
    frozen = verify(code_freeze['path'])
    sealed = read_json(seal['path'])
    require(sealed['conf_seal_sha256'] == conf_seal['sha256'] and sealed['code_freeze'] == code_freeze,
            'Scored export seal/code identity drift')
    require(set(result['families']) == set(FAMILIES), 'Scored R8 family inventory drift')
    for name,pairs in FAMILIES.items():
        family = result['families'][name]
        require(family['state'] in ('COMPUTED','NOT_RUN_BUDGET','NOT_RUN_INPUT_UNAVAILABLE','NOT_RUN_PARITY_FAILED'), 'Unknown score state')
        if family['state'] == 'COMPUTED':
            require([(r['arm'],r['reference']) for r in family['reports']] == pairs, 'Scored R8 contrast order drift')
        else:
            require(not family['reports'] and family.get('reason'), 'Partial family may not produce statistics')
    payload = dict(result,state='A8BATCH_SCORED',code_freeze=code_freeze,seal=seal,conf_seal_sha256=conf_seal['sha256'])
    write_json(destination,payload,exclusive=True)
    return payload
