'Predict day-first notice features with the saved fitted models.'
from __future__ import annotations
from contextlib import nullcontext
import concurrent.futures as cf
import multiprocessing as mp
import sys
import time
import resource
from pathlib import Path
from equivalence import *

AF=confirmation/'forecast_hashes'

def require_gate():
    g=read(OUT/'EQUIVALENCE.json')
    assert g['state']=='PASSED'
    assert sha(OUT/'PLAN.md')==g['plan_sha256']

def different(a,b):
    import numpy as np
    return ~(np.equal(a,b)|(np.isnan(a)&np.isnan(b)))

def save_patch(arm,old,new,names,rows):
    import numpy as np
    use=different(old,new)
    changed_columns=use.any(axis=0)
    order=np.argsort(rows)
    assert np.array_equal(rows[order],np.arange(rows.min(),rows.max()+1))
    path=OUT/'features'/(arm+'__changed_columns.npy')
    np.save(path,new[order][:,changed_columns],allow_pickle=False)
    item=dict(arm=arm,columns=[n for n,k in zip(names,changed_columns) if k],
              changed_input_rows=int(use.any(axis=1).sum()),rows=len(rows),path=str(path),sha256=sha(path))
    write(OUT/'features'/(arm+'__changed_columns.json'),item)
    return item

def special_one(arm):
    require_gate()
    import numpy as np
    import pandas as pd
    started=time.monotonic()
    runtime,execution,storage=imports()
    sys.path.insert(0,str(AF/'code'))
    sys.path.insert(0,str(STUDY/'studies/batch_estimation/fitting/code'))
    import features_adapter as f
    import notice_label_adapter as nrx
    import rebuild_delayed_features as dly
    from anchor_patch import install_patch,parse_anchor
    rec=read(STATE/f'fits/receipts/notice__prewindow_frozen_C_bank__{arm}__s20260919__main.json')
    guard=runtime.conf_module('guard')
    permit=guard.ExecutionPermit('DAYFIRST_20261020_USER_AUTHORIZED',rec['design_freeze_sha256'],rec['completed_input_manifest_sha256'],True)
    manifest=read(STATE/'features/manifest.json')
    b=next(b for b in manifest['bundles'] if (b['source'],b['arm'],b.get('variant','main'))==('notice',arm,'main'))
    panel,rows=dly.d_panel(b,None)
    panel['_production_row']=rows;panel=dly.normalize(panel)
    rows=panel.pop('_production_row').to_numpy(dtype='int64')
    freeze=read(STATE/'COMPLETE_INPUT_FREEZE.json')
    notices=f.load_host_notices(Path(freeze['nrx_labels_path']).parent,permit=permit)
    source_relations=f.load_final3(permit=permit)
    keys=panel[['origin','target_time','region']].rename(columns={'origin':'issue_time'})
    results=[]
    for aligned in (False,True):
        resources()
        if arm=='NPP':
            with install_patch(nrx,f) if aligned else nullcontext():
                records,_=f.normalize_notices(notices,source_relations,permit=permit)
                shifted=source_relations.shifted(records,28)
                projected=f.f.l14_projection(shifted,keys,source_relations.features,permit=permit)
        else:
            parser=f.load_corrected_rule(permit=permit)
            parse=parse_anchor if aligned else pd.Timestamp

            pop=pd.DataFrame([{'notice_id':n['notice_id'],'title':n.get('title',''),
                'text':n.get('body',n.get('text','')),'notice_type':n.get('notice_type',n.get('source_notice_type','')),
                'available_utc':pd.Timestamp(n['available_utc']),
                'anchor_local':parse(n.get('anchor_local') or pd.Timestamp(n['available_utc']).tz_convert('Australia/Brisbane').tz_localize(None))}
                for n in notices])
            rrecords=parser.rule_records(pop,reject_partial_year=True,completed_recovery=True)
            projected=parser.features(keys,rrecords)
        names=[n for n in b['columns'] if n in projected.columns]
        assert names
        results.append(projected.loc[:,names].to_numpy(dtype='float32'))
        if not aligned:
            old=storage.load_feature_rows(b,rows,columns=names)
            diff=different(old,results[-1])
            assert not diff.any(), f'{arm}: source reconstruction does not reproduce frozen month-first feature bytes'
        progress(f'{arm} source feature reconstruction day_first={aligned} complete')
    item=save_patch(arm,results[0],results[1],names,rows)
    item.update(month_first_feature_parity=True,runtime_seconds=time.monotonic()-started,
                peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024))
    write(OUT/'gate'/(arm+'__source_feature_parity.json'),item)
    return item

def prepare_primary():
    import numpy as np
    _,_,storage=imports()
    manifest=read(STATE/'features/manifest.json')
    patches={}
    for arm,count in (('L14',29310),('L_Laz',3456)):
        saved=OUT/'features'/(arm+'__changed_columns.json')
        if not (OUT/f'features/{arm}__dayfirst_a0.extras.npy').exists() and saved.exists():
            item=read(saved)
            assert sha(item['path'])==item['sha256'] and item['changed_input_rows']==count
            patches[arm]=item
            continue
        b=next(b for b in manifest['bundles'] if (b['source'],b['arm'],b.get('variant','main'))==('notice',arm,'main'))
        new=np.load(OUT/f'features/{arm}__dayfirst_a0.extras.npy',mmap_mode='r')
        rows=np.load(OUT/f'features/{arm}__production_rows.npy',mmap_mode='r')
        names=[n for n in b['columns'] if n in b['extra_columns']]
        new=new[:,[b['extra_columns'].index(n) for n in names]]
        old=storage.load_feature_rows(b,rows,columns=names)
        item=save_patch(arm,old,new,names,rows)
        assert item['changed_input_rows']==count
        patches[arm]=item
    return patches

def inventory(patches):
    import pandas as pd
    records=notice_receipts()
    records += [(p,read(p)) for p in (POST/'gate/receipts').glob('notice__*.json') if read(p).get('state')=='COMPLETE']
    out=[]
    aliases={'L14+':'L14','L_Laz+':'L_Laz','NPL':'L14'}
    for path,r in records:
        arm=r['task']['arm'];base=aliases.get(arm,arm)
        patch=patches.get(base)
        changed=bool(patch and any(n in r['feature_order'] for n in patch['columns']))
        group='official' if path.is_relative_to(STATE) else 'windowed_activity' if path.is_relative_to(BATCH) else 'posthoc_gate' if path.is_relative_to(POST/'gate') else path.parents[1].name
        reason=('Evaluation source timestamps enter '+base+' projection; frozen model retains changed columns'
                if changed else 'No retained evaluation column depends on the changed source anchoring')
        if base in patches and not changed: reason=base+' rebuilt with both parsings; retained evaluation inputs are equal'
        row=dict(model_id=group+'__'+r['task_id'],group=group,arm=arm,seed=r['task']['seed'],
            variant=r['task']['variant'],availability_minutes=0,evaluation_inputs_change=changed,
            changed_input_rows=patch['changed_input_rows'] if changed else 0,reason=reason,
            model_path=r['model_path'],model_sha256=r['model_sha256'],receipt_path=str(path),
            saved_prediction_path=r['prediction_path'],action='RE_PREDICT' if changed else 'REUSE_SAVED_FORECAST')
        out.append(row)
    for mode in (1,2):
        rec=read(BATCH/f'dly8/mode{mode}/DELAY_RECEIPT.json')
        for e in rec['predictions']:
            arm=e['arm'];base=aliases.get(arm,arm);p=patches.get(base)
            changed=bool(p and p['columns'])
            r=read((STATE if mode==1 else BATCH/'state')/f'fits/receipts/notice__prewindow_frozen_C_bank__{arm}__s20260919__main.json')
            out.append(dict(model_id=f'delay_mode{mode}__{arm}__{e["delta_minutes"]}',group=f'delay_mode{mode}',arm=arm,
                seed=20260919,variant='main',availability_minutes=e['delta_minutes'],evaluation_inputs_change=changed,
                changed_input_rows='',reason='Same anchored structural projection with the frozen availability delay' if changed else
                'Delay affects availability; changing creation-date anchoring does not affect these columns',
                model_path=r['model_path'],model_sha256=r['model_sha256'],receipt_path=str(BATCH/f'dly8/mode{mode}/DELAY_RECEIPT.json'),
                saved_prediction_path=e['path'],action='RE_PREDICT' if changed else 'REUSE_SAVED_FORECAST'))
    pd.DataFrame(out).to_csv(OUT/'MODEL_INVENTORY.csv',index=False)
    return out

def predict_one(j,patch):
    require_gate()
    import lightgbm as lgb
    import numpy as np
    import pandas as pd
    started=time.monotonic();resources()
    _,execution,storage=imports()
    r=read(j['receipt_path']);b=j['bundle']
    model=lgb.Booster(model_file=r['model_path'])
    assert sha(r['model_path'])==r['model_sha256'] and model.feature_name()==r['feature_order']
    panel=pd.read_parquet(b['panel_path'],columns=KEYS+['target_day','anchor']).iloc[b['train_rows']:].reset_index(drop=True)
    small=np.load(patch['path'],mmap_mode='r')
    assert sha(patch['path'])==patch['sha256']
    activity=np.load(j['activity_path'],mmap_mode='r') if 'activity_path' in j else None
    recipe=read(j['recipe_path']) if 'recipe_path' in j else None
    metadata=np.load(recipe['recipe']['metadata']['path'],mmap_mode='r') if recipe else None
    raw=np.empty(len(panel),dtype='float64')
    for start in range(0,len(panel),32768):
        stop=min(start+32768,len(panel));rows=np.arange(start,stop)+b['train_rows']
        x=storage.load_feature_rows(b,rows)
        for i,n in enumerate(patch['columns']):
            if n in b['columns']:x[:,b['columns'].index(n)]=small[start:stop,i]
        if activity is not None:
            for i,n in enumerate(('notice_prefix_count','notice_arrivals_6h','notice_failed_prefix_count')):
                x[:,b['columns'].index(n)]=activity[rows,i]
        if recipe:
            mapping={n:x[:,i] for i,n in enumerate(b['columns'])}
            mapping.update({n:metadata[rows,i] for i,n in enumerate(recipe['recipe']['metadata_columns'])})
            x=np.column_stack([mapping[n] for n in recipe['columns']]).astype('float32')
        raw[start:stop]=model.predict(x,num_threads=8)
        resources()
    raw+=panel.anchor.to_numpy(dtype='float64')
    out=panel[KEYS+['target_day']].copy()
    out['raw_prediction']=raw;out['lower_bound']=-1000.;out['upper_bound']=execution.price_cap(panel.target_time)
    out['prediction']=np.clip(raw,out.lower_bound.to_numpy(),out.upper_bound.to_numpy()).astype('float32')
    path=OUT/'predictions'/j['group']/(r['task_id']+'.predictions.parquet')
    path.parent.mkdir(parents=True,exist_ok=True);out.to_parquet(path,index=False)
    old=pd.read_parquet(r['prediction_path'],columns=['prediction'])
    item=dict(id=j['id'],group=j['group'],arm=r['task']['arm'],seed=r['task']['seed'],variant=r['task']['variant'],
        delta_minutes=0,state='COMPLETE',prediction_path=str(path),prediction_sha256=sha(path),
        model_path=r['model_path'],model_sha256=r['model_sha256'],rows=len(out),
        changed_input_rows=patch['changed_input_rows'],changed_prediction_rows=int(np.sum(out.prediction.to_numpy()!=old.prediction.to_numpy())),
        runtime_seconds=time.monotonic()-started,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024),
        prediction_threads=8,models_refitted=0)
    write(OUT/'prediction_receipts'/(j['id']+'.json'),item)
    return item

def parallel_jobs(function,arguments,workers=2):
    pool=cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn'),max_tasks_per_child=1)
    todo=iter(arguments);pending={};result=[];heartbeat=time.monotonic()
    try:
        for _ in range(workers):
            arg=next(todo,None)
            if arg is not None:pending[pool.submit(function,*arg)]=arg
        while pending:
            current=resources()
            if time.monotonic()-heartbeat>=30:
                progress(f'Running {function.__name__}: {len(result)}/{len(arguments)} complete; resources={current}')
                heartbeat=time.monotonic()
            done,_=cf.wait(pending,timeout=.5,return_when=cf.FIRST_COMPLETED)
            for future in done:
                arg=pending.pop(future);value=future.result();result.append(value)
                progress(f'{function.__name__}: completed {len(result)}/{len(arguments)}')
                arg=next(todo,None)
                if arg is not None:pending[pool.submit(function,*arg)]=arg
        return result
    except BaseException:
        for p in list(pool._processes.values()):p.terminate()
        raise
    finally:pool.shutdown(wait=True,cancel_futures=True)

def main():
    require_gate();started=time.monotonic()
    progress('Prediction stage: full equivalence PASSED; no refitting')
    patches=prepare_primary()
    for item in parallel_jobs(special_one,[(a,) for a in ('R','NPP')]):patches[item['arm']]=item
    write(OUT/'FEATURE_CHANGES.json',patches)
    inventory(patches)
    aliases={'L14+':'L14','L_Laz+':'L_Laz','NPL':'L14'}
    arguments=[]
    for j in jobs():
        r=read(j['receipt_path']);a=aliases.get(r['task']['arm'],r['task']['arm']);p=patches[a]
        if p['columns']:arguments.append((j,p))
    predictions=parallel_jobs(predict_one,arguments)
    from projection_gate import projection_one
    delayed=parallel_jobs(projection_one,[(a,True,d,True) for d in (5,15,60) for a in ('L14','L_Laz')])
    for values in delayed:predictions+=values
    write(OUT/'PREDICTIONS.json',dict(state='COMPLETE',models_refitted=0,predictions=predictions,
          runtime_seconds=time.monotonic()-started))
    progress('Prediction stage COMPLETE')

if __name__=='__main__':main()
