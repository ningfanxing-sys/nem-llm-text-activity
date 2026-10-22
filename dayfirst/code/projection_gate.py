'Rebuild the structural evaluation columns from frozen notice records.'
from __future__ import annotations
from contextlib import nullcontext
import concurrent.futures as cf
import multiprocessing as mp
from pathlib import Path
import resource
import sys
import time
import traceback
from types import SimpleNamespace
from equivalence import *

AF = confirmation / 'forecast_hashes'

def projection_one(arm, aligned=True, delta=0, production=False):
    import numpy as np
    import pandas as pd
    import lightgbm as lgb
    started = time.monotonic()
    if production:
        assert read(OUT/'EQUIVALENCE.json')['state']=='PASSED'
    runtime, execution, storage = imports()
    sys.path.insert(0, str(AF / 'code'))
    sys.path.insert(0, str(AF / 'overlap_cache'))
    sys.path.insert(0, str(STUDY / 'studies/batch_estimation/fitting/code'))
    import features_adapter as f
    import notice_label_adapter as nrx
    import rebuild_delayed_features as dly
    import speed_core
    from anchor_patch import install_patch
    guard = runtime.conf_module('guard')
    rec = read(STATE / ('fits/receipts/notice__prewindow_frozen_C_bank__' + arm + '__s20260919__main.json'))
    permit = guard.ExecutionPermit('DAYFIRST_20261020_USER_AUTHORIZED', rec['design_freeze_sha256'],
                                  rec['completed_input_manifest_sha256'], True)
    manifest = read(STATE / 'features/manifest.json')
    b = next(b for b in manifest['bundles'] if (b['source'],b['arm'],b.get('variant','main')) == ('notice',arm,'main'))
    panel, rows = dly.d_panel(b, None)
    panel['_production_row'] = rows
    panel = dly.normalize(panel)
    rows = panel.pop('_production_row').to_numpy(dtype='int64')
    freeze = read(STATE / 'COMPLETE_INPUT_FREEZE.json')
    notices = f.load_host_notices(Path(freeze['nrx_labels_path']).parent, permit=permit)
    notices = dly.shifted_notices(notices, delta)
    columns = b['extra_columns']
    array = np.empty((len(panel),len(columns)), dtype='float32')
    checks = []
    last = time.monotonic()
    minimum = resources()
    def checkpoint(scratch=None):
        nonlocal last
        r = resources()
        for k in minimum: minimum[k] = min(minimum[k],r[k])
        if time.monotonic()-last >= 30:
            progress(f'Projection {arm} day_first={aligned} delta={delta}: elapsed={time.monotonic()-started:.1f}s; checkpoint_count={len(checks)}')
            last = time.monotonic()
        return r


    speed_core.resources = checkpoint
    A = SimpleNamespace(features=f, storage=storage, execution=execution)
    ctx = install_patch(nrx,f) if aligned else nullcontext()
    with ctx:
        source_relations = f.load_final3(permit=permit)
        proxy = speed_core.structural_adapter(A,[arm],OUT/'gate',checks)
        seen = np.zeros(len(panel),dtype=bool)
        for indices,extras,_ in proxy.features.notice_feature_rows(panel,notices,permit=permit,source_relations=source_relations):
            assert not seen[indices].any()
            seen[indices] = True
            values = extras[(arm,'main')]
            for i,n in enumerate(columns):
                array[indices,i] = values[n]
        assert seen.all()
    checkpoint()
    if delta:
        return delayed_compare(arm, array, panel, rows, b, execution, storage, started, minimum, delta, production)

    model = lgb.Booster(model_file=rec['model_path'])
    assert model.feature_name() == b['columns'] == rec['feature_order']
    raw = np.empty(len(panel),dtype='float64')
    for start in range(0,len(panel),32768):
        stop = min(start+32768,len(panel))
        x = storage.load_feature_rows(b,rows[start:stop])
        for i,n in enumerate(columns):
            if n in b['columns']:
                x[:,b['columns'].index(n)] = array[start:stop,i]
        raw[start:stop] = model.predict(x,num_threads=8)
        checkpoint()
    raw += panel.anchor.to_numpy(dtype='float64')
    out = panel[KEYS+['target_day']].copy()
    out['raw_prediction'] = raw
    out['prediction'] = np.clip(raw,-1000.,execution.price_cap(panel.target_time)).astype('float32')
    ref_path = AF / 'prediction_set' / (arm+'__corrected_D.parquet')
    ref = dly.normalize(pd.read_parquet(ref_path))
    assert out[KEYS].equals(ref[KEYS])
    differences = {c:float(np.max(np.abs(out[c].to_numpy(dtype='float64')-ref[c].to_numpy(dtype='float64'))))
                   for c in ('prediction','raw_prediction')}
    item = dict(id=arm+'__dayfirst_a0',state='PASS' if max(differences.values()) <= 1e-9 else 'FAILED_STOP',
                rows=len(panel),differences=differences,tolerance=1e-9,
                reference_path=str(ref_path),reference_sha256=sha(ref_path),
                model_sha256=sha(rec['model_path']),runtime_seconds=time.monotonic()-started,
                peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024),
                minimum_resources=minimum,models_refitted=0,prediction_threads=8)
    write(OUT/'gate'/(item['id']+'.json'),item)
    if item['state'] == 'PASS':
        root=OUT/'features'
        root.mkdir(exist_ok=True)
        np.save(root/(arm+'__dayfirst_a0.extras.npy'),array,allow_pickle=False)
        panel[KEYS+['target_day']].to_parquet(root/(arm+'__evaluation_keys.parquet'),index=False)
        np.save(root/(arm+'__production_rows.npy'),rows,allow_pickle=False)
    return item

def delayed_compare(arm, array, panel, rows, b, execution, storage, started, minimum, delta, production=False):
    import copy
    import lightgbm as lgb
    import numpy as np
    import pandas as pd
    import rebuild_delayed_features as dly
    import window_activity as windowed_activity
    items=[]
    for mode, model_arm in ((1,arm),(2,arm+'+')):
        bank=STATE if mode==1 else BATCH/'state'
        rec=read(bank/('fits/receipts/notice__prewindow_frozen_C_bank__'+model_arm+'__s20260919__main.json'))
        model=lgb.Booster(model_file=rec['model_path'])
        assert sha(rec['model_path'])==rec['model_sha256']
        assert model.feature_name()==rec['feature_order']
        names=list(b['extra_columns'])
        values=array
        if mode==2:
            manifests=list((BATCH/'state/features/windowed_activity').glob('attempts/*/manifest.json'))
            assert len(manifests)==1
            manifest=read(manifests[0]); contract=copy.deepcopy(manifest['metadata_contract'])
            records=windowed_activity.read_notices(contract['notice_scope'],contract['notice_type_map'])
            records=[dict(r,available=r['available']+pd.Timedelta(minutes=delta)
                if r['available']>=pd.Timestamp('2026-07-27T00:00',tz='Australia/Brisbane') else r['available']) for r in records]
            contract['coverage']['notice']=[[(pd.Timestamp(a)+pd.Timedelta(minutes=delta)).isoformat(),
                (pd.Timestamp(z)+pd.Timedelta(minutes=delta)).isoformat()] for a,z in contract['coverage']['notice']]
            metadata,metadata_names=windowed_activity.metadata_matrix(panel,records,'notice',contract,
                types=manifest['notice_type_coverage']['training_type_ids'])
            names+=metadata_names
            values=np.column_stack((array,metadata))
        raw=np.empty(len(panel),dtype='float64')
        for start in range(0,len(panel),32768):
            stop=min(start+32768,len(panel))
            base=storage.load_feature_rows(b,rows[start:stop])
            mapping={n:base[:,i] for i,n in enumerate(b['columns'])}
            mapping.update({n:values[start:stop,i] for i,n in enumerate(names)})
            x=np.column_stack([mapping[n] for n in rec['feature_order']]).astype('float32')
            raw[start:stop]=model.predict(x,num_threads=8)
            resources()
        raw+=panel.anchor.to_numpy(dtype='float64')
        prediction=np.clip(raw,-1000.,execution.price_cap(panel.target_time)).astype('float32')
        if production:
            out=panel[KEYS+['target_day']].copy()
            out['raw_prediction']=raw
            out['lower_bound']=-1000.
            out['upper_bound']=execution.price_cap(panel.target_time)
            out['prediction']=prediction
            path=OUT/f'predictions/delays/mode{mode}__{model_arm}__dayfirst_delay{delta}.parquet'
            path.parent.mkdir(parents=True,exist_ok=True)
            out.to_parquet(path,index=False)
            item=dict(id=f'mode{mode}__{model_arm}__dayfirst_delay{delta}',state='COMPLETE',
                group='official' if mode==1 else 'windowed_activity',arm=model_arm,seed=20260919,delta_minutes=delta,
                prediction_path=str(path),prediction_sha256=sha(path),model_sha256=rec['model_sha256'],
                rows=len(panel),runtime_seconds=time.monotonic()-started,
                peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024),
                minimum_resources=minimum,prediction_threads=8,models_refitted=0)
            write(OUT/'prediction_receipts'/(item['id']+'.json'),item)
            items.append(item)
            continue
        delay_receipt=read(BATCH/f'dly8/mode{mode}/DELAY_RECEIPT.json')
        entry=next(e for e in delay_receipt['predictions'] if e['arm']==model_arm and e['delta_minutes']==delta)
        assert sha(entry['path'])==entry['sha256']
        ref=dly.normalize(pd.read_parquet(entry['path']))
        assert panel[KEYS].equals(ref[KEYS])
        differences={'raw_prediction':float(np.max(np.abs(raw-ref.raw_prediction.to_numpy(dtype='float64')))),
                     'prediction':float(np.max(np.abs(prediction.astype('float64')-ref.prediction.to_numpy(dtype='float64'))))}
        item=dict(id=f'mode{mode}__{model_arm}__monthfirst_delay{delta}',rows=len(panel),differences=differences,
                  state='PASS' if max(differences.values())<=1e-9 else 'FAILED_STOP',
                  tolerance=1e-9,reference_path=entry['path'],reference_sha256=entry['sha256'],
                  runtime_seconds=time.monotonic()-started,
                  peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024),
                  minimum_resources=minimum,prediction_threads=8,models_refitted=0)
        write(OUT/'gate'/(item['id']+'.json'),item)
        items.append(item)
        if item['state']!='PASS': break
    return items

def main():
    gate = read(OUT/'EQUIVALENCE.json')
    if gate['state']=='FAILED_STOP' and gate.get('error')=="'laz_NuclearFailure' is not in list":


        write(OUT/'gate/DELIVERY_ERROR_ATTEMPT_1.json',gate)
        gate['execution_errors']=[dict(error=gate.pop('error'),traceback=gate.pop('traceback'),
            reason='Runner attempted to assign a training-pruned column; no L_Laz prediction or comparison occurred',
            correction='Assign only the exact saved/pruned model feature order')]
        gate['state']='MONTH_FIRST_FITTED_MODELS_PASS_DELAYS_AND_DAY_FIRST_PENDING'
        write(OUT/'EQUIVALENCE.json',gate)
    assert gate['state'] == 'MONTH_FIRST_FITTED_MODELS_PASS_DELAYS_AND_DAY_FIRST_PENDING'
    started = time.monotonic()
    progress('Day-first a0 equivalence: rebuilding L14 and L_Laz in 2 independent processes')
    pool=cf.ProcessPoolExecutor(max_workers=2,mp_context=mp.get_context('spawn'),max_tasks_per_child=1)
    completed={x['id'].split('__')[0] for x in gate['day_first_checks'] if x['state']=='PASS'}
    futures={pool.submit(projection_one,a):a for a in ('L14','L_Laz') if a not in completed}
    try:
        while futures:
            resources()
            done,_=cf.wait(futures,timeout=.5,return_when=cf.FIRST_COMPLETED)
            for future in done:
                arm=futures.pop(future)
                item=future.result()
                gate['day_first_checks'].append(item)
                write(OUT/'EQUIVALENCE.json',gate)
                progress(item['id']+' '+item['state']+' '+str(item['differences']))
                if item['state']!='PASS': raise RuntimeError('Day-first equivalence failed: '+arm)
        gate['state']='A0_CHECKS_PASS_DELAY_CHECKS_PENDING'
        gate['day_first_gate_runtime_seconds']=time.monotonic()-started
        write(OUT/'EQUIVALENCE.json',gate)
    except BaseException as exc:
        gate.update(state='FAILED_STOP',error=str(exc),traceback=traceback.format_exc(),
                    day_first_gate_runtime_seconds=time.monotonic()-started)
        write(OUT/'EQUIVALENCE.json',gate)
        progress('STOP: '+str(exc))
        for p in list(pool._processes.values()): p.terminate()
        raise
    finally:
        pool.shutdown(wait=True,cancel_futures=True)

def delays():
    gate=read(OUT/'EQUIVALENCE.json')
    assert gate['state']=='A0_CHECKS_PASS_DELAY_CHECKS_PENDING'
    gate['delayed_month_first_checks']=[]
    todo=iter([(arm,delta) for delta in (5,15,60) for arm in ('L14','L_Laz')])
    pool=cf.ProcessPoolExecutor(max_workers=2,mp_context=mp.get_context('spawn'),max_tasks_per_child=1)
    pending={}
    started=time.monotonic()
    heartbeat=started
    try:
        for _ in range(2):
            a,d=next(todo); pending[pool.submit(projection_one,a,False,d)]=(a,d)
        while pending:
            current=resources()
            if time.monotonic()-heartbeat>=30:
                progress('Delayed equivalence running: '+str(list(pending.values()))+'; resources='+str(current))
                heartbeat=time.monotonic()
            done,_=cf.wait(pending,timeout=.5,return_when=cf.FIRST_COMPLETED)
            for future in done:
                task=pending.pop(future)
                items=future.result()
                gate['delayed_month_first_checks']+=items
                write(OUT/'EQUIVALENCE.json',gate)
                for item in items:
                    progress(item['id']+' '+item['state']+' '+str(item['differences']))
                    if item['state']!='PASS': raise RuntimeError('Delayed equivalence failed: '+item['id'])
                job=next(todo,None)
                if job:
                    a,d=job; pending[pool.submit(projection_one,a,False,d)]=job
        assert len(gate['delayed_month_first_checks'])==12
        gate.update(state='PASSED',delayed_gate_runtime_seconds=time.monotonic()-started)
        write(OUT/'EQUIVALENCE.json',gate)
        progress('Full equivalence gate PASSED')
    except BaseException as exc:
        gate.update(state='FAILED_STOP',error=str(exc),traceback=traceback.format_exc(),
                    delayed_gate_runtime_seconds=time.monotonic()-started)
        write(OUT/'EQUIVALENCE.json',gate)
        progress('STOP: '+str(exc))
        for p in list(pool._processes.values()): p.terminate()
        raise
    finally: pool.shutdown(wait=True,cancel_futures=True)

if __name__=='__main__':
    delays() if len(sys.argv)>1 and sys.argv[1]=='delays' else main()
