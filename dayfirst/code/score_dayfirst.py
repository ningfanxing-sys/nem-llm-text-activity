'Compute the day-first seed and window comparisons with the frozen tests.'
from __future__ import annotations
import concurrent.futures as cf
import copy
import importlib.util
import multiprocessing as mp
from pathlib import Path
import resource
import sys
import time
from types import SimpleNamespace
from equivalence import *

OFFICIAL=STUDY/'paper_plan/minrun_execution_20261010/t5_final/a13f/source_delivery_final/SCORE_ATTEMPT_DECLARED_ONLY/export/OFFICIAL_RESULTS.json'

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m)
    return m

def statistical_modules():
    runtime,_,_=imports()
    frozen=runtime.conf_module('scoring')
    primary_tests=module('_dayfirst_frozen_A2',confirmation/'primary_tests/code/primary_comparisons.py')
    post=module('_dayfirst_frozen_bootstrap',STUDY/'studies/inference/code/read_comparisons.py')
    return frozen,primary_tests,post

def safe(value):
    import numpy as np
    if isinstance(value,dict):return {str(k):safe(v) for k,v in value.items() if k!='draws'}
    if isinstance(value,(tuple,list)):return [safe(v) for v in value]
    if isinstance(value,np.ndarray):return value.tolist()
    if isinstance(value,np.generic):return value.item()
    return value

def stat_worker(spec):
    import numpy as np
    started=time.monotonic();resources()
    frozen,primary_tests,post=statistical_modules()
    sc=post.ChunkedScoring(frozen,draws=100000,chunk=512,gate=resources)
    if spec['kind']=='posthoc':
        a,b=np.asarray(spec['a'],float),np.asarray(spec['b'],float)
        boot=sc.paired_percent_interval(a,b,sc.block_picks(len(spec['days']),7,spec['days']))
        result=safe(boot)
        one=sc.paired_percent_interval(a,b,sc.block_picks(len(spec['days']),1,spec['days']))
        result['interval95_one_day_percent']=one['interval95_percent']
    else:
        losses={k:np.asarray(v,float) for k,v in spec['losses'].items()}
        bundle=dict(state='COMPUTED',id=spec['id'],days=spec['days'],losses=losses,
                    pairs=spec['pairs'],family_m=spec['m'],subset=spec.get('subset',False),
                    unadjusted=spec.get('unadjusted',False))
        result=safe(post.compute_bundle(primary_tests,sc,bundle))
    receipt=dict(id=spec['id'],result=result,runtime_seconds=time.monotonic()-started,
                 peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024))
    write(OUT/'stat_receipts'/(spec['id'].replace('/','__')+'.json'),receipt)
    return receipt

def run_stats(specs):
    import psutil
    cached={};todo_specs=[]
    bindings=read(OUT/'STAT_CACHE_BINDINGS.json') if (OUT/'STAT_CACHE_BINDINGS.json').exists() else {}
    for spec in specs:
        entry=bindings.get(spec['id']);path=OUT/'stat_receipts'/(spec['id'].replace('/','__')+'.json')
        digest=hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        if entry and entry['spec_sha256']==digest and path.exists() and sha(path)==entry['receipt_sha256']:
            cached[spec['id']]=read(path)
        else:todo_specs.append(spec)
    if not todo_specs:return cached,0
    progress(f'Bootstrap resume: reuse {len(cached)} hash-bound jobs; compute {len(todo_specs)} remaining specified jobs')


    with cf.ProcessPoolExecutor(max_workers=1,mp_context=mp.get_context('spawn')) as measure:
        first=measure.submit(stat_worker,todo_specs[0]).result()
    incoming=max(96*1024**2,int(first['peak_rss_bytes']*1.08))
    available=psutil.virtual_memory().available-.10*psutil.virtual_memory().total
    workers=max(1,min(8,int(available/incoming)))
    progress(f'Bootstrap admission: {workers} parallel processes; observed first-job peak={first["peak_rss_bytes"]}')
    results={**cached,first['id']:first};todo=iter(todo_specs[1:]);pending={}
    pool=cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn'),max_tasks_per_child=8)
    heartbeat=time.monotonic()
    try:
        for _ in range(workers):
            spec=next(todo,None)
            if spec is not None:pending[pool.submit(stat_worker,spec)]=spec['id']
        while pending:
            current=resources()
            if time.monotonic()-heartbeat>=30:
                progress(f'Bootstrap {len(results)}/{len(specs)} complete; resources={current}')
                heartbeat=time.monotonic()
            done,_=cf.wait(pending,timeout=.5,return_when=cf.FIRST_COMPLETED)
            for future in done:
                ident=pending.pop(future);results[ident]=future.result()
                spec=next(todo,None)
                if spec is not None:pending[pool.submit(stat_worker,spec)]=spec['id']
        return results,workers
    except BaseException:
        for p in list(pool._processes.values()):p.terminate()
        raise
    finally:pool.shutdown(wait=True,cancel_futures=True)

def posthoc_context():
    assert read(OUT/'EQUIVALENCE.json')['state']=='PASSED'
    predictions=read(OUT/'PREDICTIONS.json')
    assert predictions['state']=='COMPLETE' and predictions['models_refitted']==0
    changes={(e['group'],e['arm'],e['seed'],e.get('variant','main')):e for e in predictions['predictions'] if e['delta_minutes']==0}
    for e in predictions['predictions']:
        assert sha(e['prediction_path'])==e['prediction_sha256']
    sys.path.insert(0,str(POST/'code'))
    import run_posthoc as rp
    rp.OUT=OUT
    rp.require_gate=lambda: (_ for _ in ()).throw(RuntimeError('Equivalence not passed')) if read(OUT/'EQUIVALENCE.json')['state']!='PASSED' else None
    frozen_posthoc=module('_dayfirst_score_posthoc',POST/'code/score_posthoc.py')
    seal=read(POST/'SEAL_POSTHOC.json')
    original_seal=copy.deepcopy(seal)
    for e in seal['predictions']:
        change=changes.get((e['group'],e['arm'],e['seed'],e['variant']))
        if change:e.update(path=change['prediction_path'],sha256=change['prediction_sha256'])
    assert len(seal['predictions'])==298
    write(OUT/'SEAL_POSTHOC_DAYFIRST.json',seal)
    runtime,_,_=imports()
    import seal_score as native
    forecasts=frozen_posthoc.Forecasts(seal,native)
    for (group,arm,seed,variant),e in changes.items():
        if group in ('official','windowed_activity'):
            key=('notice',arm,seed,variant)
            forecasts.entries[key]={**forecasts.entries[key],'path':e['prediction_path'],'sha256':e['prediction_sha256']}
    return frozen_posthoc,forecasts,seal,original_seal,changes,native

def prepare_posthoc(frozen_posthoc,forecasts):
    import pandas as pd
    specs=[];seen={};lookup={}
    old_daily=pd.read_csv(POST/'results/daily_losses.csv',dtype={'seed':str},float_precision='round_trip')
    old_cache={}
    for key,part in old_daily.groupby(['task','arm','seed','group','placebo'],sort=False):
        part=part.sort_values('target_day');old_cache[key]=(part.target_day.tolist(),part.daily_mae.to_numpy())
    for filename in ('analysis1_comparisons','analysis2_comparisons','placebo_comparisons'):
        rows=pd.read_csv(POST/'results'/(filename+'.csv'),dtype={'seed':str})
        for index,r in rows.iterrows():
            seed='mean' if r.seed=='mean' else int(r.seed)
            placebo=r.analysis=='a2_w7_placebo'
            days,a=forecasts.losses(r.task,r.arm,seed,r.arm_group,placebo)
            bd,b=forecasts.losses(r.task,r.reference,seed,r.reference_group,placebo)
            assert days==bd
            import numpy as np
            key=hashlib.sha256(a.astype('<f8').tobytes()+b.astype('<f8').tobytes()+('|'.join(days)).encode()).hexdigest()
            lookup[(filename,index,'day-first')]=key
            if key not in seen:
                ident='seeds_windows/'+key
                seen[key]=dict(id=ident,kind='posthoc',days=days,a=a.tolist(),b=b.tolist())
            old_days,old_a=old_cache[(r.task,r.arm,str(r.seed),r.arm_group,placebo)]
            old_bd,old_b=old_cache[(r.task,r.reference,str(r.seed),r.reference_group,placebo)]
            assert old_days==old_bd==days
            old_key=hashlib.sha256(old_a.astype('<f8').tobytes()+old_b.astype('<f8').tobytes()+('|'.join(days)).encode()).hexdigest()
            lookup[(filename,index,'month-first')]=old_key
            if old_key not in seen:
                seen[old_key]=dict(id='seeds_windows/'+old_key,kind='posthoc',days=days,a=old_a.tolist(),b=old_b.tolist())
        specs=list(seen.values())
    return specs,lookup

def write_posthoc_intervals(results,lookup):
    import pandas as pd
    rows=[]
    for filename in ('analysis1_comparisons','analysis2_comparisons','placebo_comparisons'):
        original=pd.read_csv(POST/'results'/(filename+'.csv'),dtype={'seed':str})
        for index,row in original.iterrows():
            for version in ('month-first','day-first'):
                result=results['seeds_windows/'+lookup[(filename,index,version)]]['result']
                one=result['interval95_one_day_percent'];seven=result['interval95_percent']
                if version=='month-first':
                    assert abs(seven[0]-row.interval95_low_percent)<=2e-9
                    assert abs(seven[1]-row.interval95_high_percent)<=2e-9
                rows.append(dict(analysis=row.analysis,task=row.task,seed=row.seed,representation=row.representation,step=row.step,
                    version=version,delta_percent=result['effect_percent_reference_mae'],
                    interval95_one_day_low=one[0],interval95_one_day_high=one[1],
                    interval95_seven_day_low=seven[0],interval95_seven_day_high=seven[1]))
    pd.DataFrame(rows).to_csv(OUT/'results/posthoc_intervals_both_blocks.csv',index=False)

def run_posthoc_frozen(frozen_posthoc,forecasts,seal,bootstrap_results):
    import numpy as np
    _,_,post=statistical_modules()
    class CachedScoring(post.ChunkedScoring):
        def paired_percent_interval(self,a,b,picks):
            assert picks.block==7 and picks.draws==100000

            hits=[]
            for days,la in forecasts.cache.values():
                if np.array_equal(la,a):hits.append(days)
            keys={hashlib.sha256(np.asarray(a,dtype='<f8').tobytes()+np.asarray(b,dtype='<f8').tobytes()+('|'.join(days)).encode()).hexdigest() for days in hits}
            available=[bootstrap_results['seeds_windows/'+k]['result'] for k in keys if 'seeds_windows/'+k in bootstrap_results]
            assert len(available)==1
            return copy.deepcopy(available[0])
    frozen_posthoc.seal_all=lambda:seal
    frozen_posthoc.Forecasts=lambda sealed,native:forecasts
    frozen_posthoc.import_file=lambda name,path:SimpleNamespace(ChunkedScoring=CachedScoring)
    return frozen_posthoc.score()

if __name__=='__main__':
    raise SystemExit('Use run_scoring.py after the prediction completion record exists')
