"""Training-only CPS8 selection, then one frozen-schedule D fit per setting.

All fits use the installed worker. The formal CPS8 spec fixes the notice
holdout by the bank's latest target time. No 2025/D outcome can
enter selection. Selection is immutable before any CPS8 D task is created.
"""
from dataclasses import replace
from pathlib import Path
import numpy as np
import pandas as pd
from a8_common import *

ARMS = {'news': ('M','L_count','L_chen'), 'notice': ('M_notice','L14','L_Laz','L_chen_notice')}
GRID = ('g0','g1','g2')

def cps_root(state):
    state = Path(state)
    return OUT/'cps8' if state.resolve() == (OUT/'state').resolve() else state/'cps8'

def encode_arm(arm,g):
    require(g in GRID, 'Unknown capacity grid point')
    return arm+'__CPS8_'+g

def decode_arm(arm):
    base,g = arm.rsplit('__CPS8_',1)
    require(g in GRID and base in (*ARMS['news'],*ARMS['notice']), 'Unregistered CPS8 arm')
    return base,g

def grid_parameters(original,g):
    require(g in GRID, 'Unregistered grid')
    params = dict(original)
    if g == 'g1':
        params['n_estimators'] *= 2
    elif g == 'g2':
        params['num_leaves'] = 2*params['num_leaves']+1
    return params

def validate_selection_spec(spec):
    require(spec.get('news_holdout_weeks') == 42 and spec.get('news_end_exclusive') == '2025-01-01', 'Frozen news holdout drift')
    require(spec.get('notice_split') == 'BANK_TARGET_TIME_LAST_42_WEEKS' and spec.get('notice_holdout_weeks') == 42, 'Formal notice holdout drift')
    require(spec.get('selection_loss') == 'NEWS_DAILY_MAE_NOTICE_BANK_WEIGHTED_MAE' and
            spec.get('tie_order') == list(GRID) and spec.get('relative_tie_tolerance') == 1e-12, 'Selection/tie rule drift')
    return True

def select_rows(panel,task,bundle):
    spec = bundle['cps8_spec']
    validate_selection_spec(spec)
    day = panel.target_day.astype(str).str[:10].to_numpy()
    clocks = pd.to_datetime(panel.label_available,utc=True)
    if task.variant == 'cps8_selection':
        if task.task == 'news':
            end = pd.Timestamp(spec['news_end_exclusive'],tz='Australia/Brisbane').tz_convert('UTC')
            cutoff = end-pd.Timedelta(weeks=42)
            lo,hi = cutoff.tz_convert('Australia/Brisbane').strftime('%Y-%m-%d'), spec['news_end_exclusive']
            legal = (clocks < cutoff).to_numpy() & np.isfinite(panel.y.to_numpy())
            domain = (day >= '2021-10-01') & (day < lo)
            membership = pd.DataFrame(dict(day=day,legal=legal & domain)).groupby('day')['legal'].agg(['size','sum'])
            train_days = membership.index[(membership['size'] == 72) & (membership['sum'] == 72)]
            train = np.flatnonzero(np.isin(day,train_days))
            query = np.flatnonzero((day >= lo) & (day < hi))
            counts = panel.iloc[query].groupby('target_day').size()
            require(len(counts) == 42*7 and (counts == 72).all(), 'Incomplete 42-week training holdout')
        else:
            n = int(bundle['train_rows'])
            targets = pd.to_datetime(panel.target_time,utc=True)
            cutoff = targets.iloc[:n].max()-pd.Timedelta(weeks=42)
            in_bank = np.arange(len(panel)) < n
            train = np.flatnonzero(in_bank & (targets <= cutoff).to_numpy())
            query = np.flatnonzero(in_bank & (targets > cutoff).to_numpy())
            require((clocks.iloc[:n] < pd.Timestamp('2026-07-31T13:30Z')).all() and
                    np.all((day[:n] >= '2021-10-01') & (day[:n] <= '2023-12-31')), 'Notice frozen bank/label-clock drift')
            require(np.isin(panel.weight.to_numpy()[train], [1.,50.]).all() and
                    np.isin(panel.weight.to_numpy()[query], [1.,50.]).all(), 'Notice bank weights drift')
        require(not np.any(day[query] >= '2025-01-01'), 'Selection included report-only or D outcomes')
        if task.task == 'news':
            require((clocks.iloc[train] < cutoff).all(), 'Selection train label-clock leakage')
    elif task.variant == 'cps8_D':
        if task.task == 'news':
            cutoff = pd.Timestamp('2026-03-01',tz='Australia/Brisbane').tz_convert('UTC')
            legal = (clocks < cutoff).to_numpy() & np.isfinite(panel.y.to_numpy())
            membership = pd.DataFrame(dict(day=day,legal=legal)).groupby('day')['legal'].agg(['size','sum'])
            days = membership.index[(membership['size'] == 72) & (membership['sum'] == 72) &
                                    (membership.index >= '2021-10-01') & (membership.index < '2026-03-01')]
            train = np.flatnonzero(np.isin(day,days))
            query = np.flatnonzero((day >= '2026-03-01') & (day <= '2026-09-30'))
            require(len(query) == 214*72, 'CPS8 full D news grid required')
        else:
            n = int(bundle['train_rows'])
            train,query = np.arange(n),np.arange(n,len(panel))
            cutoff = pd.Timestamp('2026-07-31T13:30Z')
            require((clocks.iloc[train] < cutoff).all() and np.all((day[train] >= '2021-10-01') & (day[train] <= '2023-12-31')), 'Notice full-bank drift')
            require(np.isin(panel.weight.to_numpy()[train],[1.,50.]).all() and (panel.weight.to_numpy()[query] == 1).all(), 'Notice full-bank weights drift')
    else:
        raise RuntimeError('Unregistered CPS8 schedule')
    require(len(train) > 0 and len(query) > 0 and np.isfinite(panel.y.to_numpy()[train]).all(), 'Empty/nonfinite CPS8 training support')
    return train,query,clocks

def selection_tasks(A):
    F = A.scheduler.FitTask
    return [F(s,'2024-03-13' if s == 'news' else 'bank_last_42_weeks',encode_arm(a,g),SEED,'cps8_selection') for s in ARMS for a in ARMS[s] for g in GRID]

def add_bundles(manifest,spec):
    validate_selection_spec(spec)
    result = dict(manifest,bundles=list(manifest['bundles']))
    for source,arms in ARMS.items():
        for arm in arms:
            base = next(b for b in manifest['bundles'] if (b['source'],b['arm'],b.get('variant','main')) == (source,arm,'main'))
            for g in GRID:
                for variant in ('cps8_selection','cps8_D'):
                    result['bundles'].append(dict(base,arm=encode_arm(arm,g),variant=variant,cps8_spec=spec,cps8_base_arm=arm))
    return result

def training_loss(truth,predictions,source):
    """Reject any non-training day before decoding or using its outcomes."""
    require((truth.target_day.astype(str) < '2025-01-01').all(), 'CPS8 selection outcomes outside training period')
    require(truth[KEYS].equals(predictions[KEYS]), 'Selection keys drift')
    loss = np.abs(truth.y.to_numpy(dtype='float64')-predictions.prediction.to_numpy(dtype='float64'))
    require(np.isfinite(loss).all(), 'Nonfinite selection loss')
    weights = truth.weight.to_numpy(dtype='float64') if source == 'notice' else np.ones(len(truth))
    require(np.all(weights > 0), 'Invalid selection weights')
    if source == 'notice':
        return float(np.average(loss,weights=weights))
    data = pd.DataFrame(dict(day=truth.target_day.astype(str).to_numpy(),weighted=loss*weights,weight=weights))
    daily = data.groupby('day').sum()
    return float((daily.weighted/daily.weight).mean())

def choose(losses):
    require(set(losses) == set(GRID) and all(np.isfinite(v) for v in losses.values()), 'Incomplete capacity grid')
    best = min(losses.values())
    for g in GRID:
        scale = max(abs(best),abs(losses[g]))
        if losses[g] == best or (scale > 0 and abs(losses[g]-best)/scale <= 1e-12):
            return g
    raise RuntimeError('Unreachable grid selection')

def selection_record(state,A,permit,feature_sha,manifest,code_binding):
    destination = cps_root(state)/'CPS8_SELECTION.json'
    if destination.exists():
        old = read_json(destination)
        require(old['feature_manifest_sha256'] == feature_sha and old['code_binding'] == code_binding, 'CPS8 selection identity drift')
        for item in old['fit_receipts']:
            checked(item)
        return old
    losses = {}
    receipts = []
    details = {}
    for task in selection_tasks(A):
        rec = A.execution.reusable(state,task,feature_sha,permit)
        require(rec is not None, 'Incomplete CPS8 selection fit')
        b = A.execution.find_bundle(manifest,task)
        # Only training holdout rows are read with y for the choice.
        import pyarrow.parquet as pq
        pieces = []
        lo = (pd.Timestamp('2025-01-01')-pd.Timedelta(weeks=42)).strftime('%Y-%m-%d') if task.task == 'news' else '2021-10-01'
        hi = '2025-01-01' if task.task == 'news' else '2024-01-01'
        table = pq.read_table(b['panel_path'],columns=KEYS+['target_day','y','weight'],
                              filters=[('target_day','>=',lo),('target_day','<',hi)])
        truth = normalize(table.to_pandas())
        pred = normalize(pd.read_parquet(rec['prediction_path']))
        # Validation membership is exactly the worker's query grid, including
        # the target-time bank cut (not an approximated target-day split).
        truth = normalize(truth.merge(pred[KEYS],on=KEYS,how='inner',validate='one_to_one'))
        arm,g = decode_arm(task.arm)
        losses.setdefault(task.task+'/'+arm,{})[g] = training_loss(truth,pred,task.task)
        receipt_id = identity(A.execution._receipt_path(state,task))
        receipts.append(receipt_id)
        details.setdefault(task.task+'/'+arm,{})[g] = dict(metric=losses[task.task+'/'+arm][g],
                train_rows=rec['train_rows'],validation_rows=rec['prediction_rows'],
                receipt=receipt_id,model=identity(rec['model_path']),prediction=identity(rec['prediction_path']))
    record = dict(state='CPS8_SELECTION_FIXED_BEFORE_D_FITS', selection_utc=now(),
                  feature_manifest_sha256=feature_sha,code_binding=code_binding,training_only=True,
                  losses=losses,selected={arm:choose(points) for arm,points in losses.items()},fit_receipts=receipts,
                  fit_details=details,
                  tie_order=list(GRID),relative_tie_tolerance=1e-12,uses_2025_or_D_for_selection=False)
    write_json(destination,record,exclusive=True)
    return record

def d_tasks(A,selection):
    F = A.scheduler.FitTask
    tasks = []
    all_news_g0 = all(selection['selected']['news/'+a] == 'g0' for a in ARMS['news'])
    for source,arms in ARMS.items():
        for arm in arms:
            chosen = selection['selected'][source+'/'+arm]
            if source == 'news' and all_news_g0:
                continue
            # News g0 is train-once and must be fitted. Notice g0 is the main
            # full-bank model, reused under seal/model hashes, never refitted.
            for g in dict.fromkeys(('g0',chosen) if source == 'news' else (() if chosen == 'g0' else (chosen,))):
                tasks.append(F(source,'2026-03-01' if source == 'news' else 'prewindow_frozen_C_bank',
                               encode_arm(arm,g),SEED,'cps8_D'))
    return tasks

def g0_gate(original,control,source):
    require(grid_parameters(original,'g0') == original, 'CPS8 g0 parameter drift')
    require(control['params'] == original and control['task']['seed'] == SEED, 'CPS8 g0 receipt drift')
    return dict(state='PASS',source=source,parameters_unchanged=True,
                schedule='train_once_first_D_origin' if source == 'news' else 'main_full_bank_sealed_model',
                schedule_matched_control=True)

def run(state,A,manifest,feature_sha,stats,permit,ledger,run_stage,resources,code_binding):
    # Both selection and D refits are charged to the batch's same ledger.
    jobs = selection_tasks(A)
    for source in ARMS:
        stage = run_stage('CPS8_selection_'+source,[t for t in jobs if t.task == source],manifest,feature_sha,stats,permit,state,ledger,A,resources)
        require(stage['state'] == 'COMPLETE', 'CPS8 selection incomplete; no D fits or capacity score')
    selected = selection_record(state,A,permit,feature_sha,manifest,code_binding)
    selection_id = identity(cps_root(state)/'CPS8_SELECTION.json')
    # Append the selection identity before the first D fitting wave. A restart
    # must retain and verify the same choice; it can never reselect from D.
    entries = ledger.data.setdefault('cps8_selections',[])
    if entries:
        require(entries == [selection_id], 'CPS8 selection ledger identity drift')
    else:
        entries.append(selection_id)
        ledger.save()
    tasks = d_tasks(A,selected)
    dispositions = {}
    for source in ARMS:
        group = [t for t in tasks if t.task == source]
        dispositions['CPS8_D_'+source] = run_stage('CPS8_D_'+source,group,manifest,feature_sha,stats,permit,state,ledger,A,resources)
        require(dispositions['CPS8_D_'+source]['state'] == 'COMPLETE', 'CPS8 D block incomplete')
        checked(selection_id)
    controls = {}
    for arm in ARMS['news'] if any(t.task == 'news' for t in tasks) else ():
        task = next(t for t in tasks if t.task == 'news' and decode_arm(t.arm) == (arm,'g0'))
        controls['news/'+arm] = g0_gate(A.params(task),A.execution.reusable(state,task,feature_sha,permit),'news')
    write_json(cps_root(state)/'CONTROL_RECEIPT.json',dict(state='PASS',selection=selection_id,controls=controls,
                   notice_g0='MAIN_SEAL_MODEL_IDENTITY_REQUIRED_AT_EXPORT',
                   news_all_g0_no_D_fit=not any(t.task == 'news' for t in tasks),
                   news_primary_schedule_comparison='DESCRIPTIVE_ONLY'),exclusive=True)
    return tasks,dispositions
