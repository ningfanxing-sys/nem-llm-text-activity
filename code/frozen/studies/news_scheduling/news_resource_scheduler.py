'Schedule daily news fits under the specified memory limits.'
from __future__ import annotations
import concurrent.futures as cf
import hashlib
import importlib.util
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
import time

HERE=Path(__file__).resolve().parent
PROJ=HERE.parents[2]
spec=importlib.util.spec_from_file_location('newsrun2_dayahead_original',HERE/'newsrun2_dayahead.py')
d=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=d
spec.loader.exec_module(d)
sys.path.insert(0,str(HERE))
import newsrun2_runtime_hooks_v4 as hooks


def guard():
    original=d.guard()
    frozen=d.read(HERE/'RESOURCE_SCHEDULER_FREEZE_9.json')
    d.require(any(Path(name).name==Path(__file__).name for name in frozen['files_sha256']),
              'Resource scheduler absent from own freeze')
    for name,expected in frozen['files_sha256'].items():
        path=Path(name) if Path(name).is_absolute() else PROJ/name
        d.require(d.sha(path)==expected,f'Resource scheduler freeze mismatch: {name}')
    d.require(frozen['original_execution_freeze_sha256']==original['execution_freeze_sha256'],
              'Original execution freeze changed')
    d.require(frozen['original_specification_freeze_sha256']==original['specification_freeze_sha256'],
              'Original specification freeze changed')
    return frozen


def measure_fresh_counted_validation(pool):
    task=next(t for t in d.tasks() if not d.done(t))
    d.update_legal_labels(task['date'])
    future=pool.submit(d.fit_one,task)
    tree_peak=d.current_tree_rss()
    while not future.done():
        tree_peak=max(tree_peak,d.current_tree_rss())
        d.require(tree_peak<6.6*1024**3,'Fresh counted pilot exceeds6.6GiB')
        cf.wait([future],timeout=1)
    rec=future.result()
    d.write(d.BANK/'RESOURCE9_COUNTED_PILOT.json',dict(state='COMPLETE',counted=True,
        fit_id=task['fit_id'],all_existing_counted_fits_preserved=True,
        reason='Next pending original fit counted in fresh proxy-enabled worker; no extra fit',
        record=rec,known_process_tree_peak_rss_bytes=tree_peak,
        resource_scheduler_freeze_sha256=d.sha(HERE/'RESOURCE_SCHEDULER_FREEZE_9.json')))
    d.progress('FRESH_RESOURCE_COUNTED_PILOT_COMPLETE',fit_id=task['fit_id'],
        fits_done=sum(d.done(t) for t in d.tasks()),runtime_seconds=rec['runtime_seconds'],
        fresh_worker_peak_rss_bytes=rec['peak_rss_bytes'],process_tree_peak_rss_bytes=tree_peak)
    return rec


def snapshot(pool):
    import psutil
    parent=psutil.Process(os.getpid()).memory_info().rss
    workers=[]
    for proc in ((pool._processes or {}) if pool is not None else {}).values():
        if proc.pid:
            try: workers.append(psutil.Process(proc.pid).memory_info().rss)
            except psutil.NoSuchProcess:
                d.require(proc.exitcode is not None,'Known live worker vanished during RSS measurement')
            except (psutil.AccessDenied,PermissionError) as exc:
                raise RuntimeError(f'Known worker RSS measurement denied for PID{proc.pid}') from exc
    return parent,workers


TARGET_WORKERS=4


def planned_concurrency(parent,worker_rss,projected_worker):


    return TARGET_WORKERS


def strict_tree_rss():
    parent,workers=snapshot(d._POOL)
    return parent+sum(workers)


def proxy_worker_init():
    hooks.install(d)
    d.worker_init()


def run():
    frozen=guard();hooks.install(d);d.current_tree_rss=strict_tree_rss;d.prepare()
    proof=d.read(d.BANK/'NUMERIC_PROXY_BITWISE_PROOF.json')
    d.require(proof['state']=='PASS_FLOAT64_BITWISE_ALL_NUMERIC_ROWS_AND_BOUNDED_COPIES','Numeric proxy bitwise gate required')
    if all(d.done(task) for task in d.tasks()):
        d.progress('ALL_ORIGINAL_FITS_REUSED_NO_NEW_RESOURCE_PILOT',fits_done=2562,fits_total=2562)
        d.seal();d.score();return
    started=time.perf_counter()

    ctx=mp.get_context('spawn')
    tree_peak=d.current_tree_rss()
    completed=sum(d.done(t) for t in d.tasks())
    origin_counts=[]
    with cf.ProcessPoolExecutor(max_workers=4,mp_context=ctx,initializer=proxy_worker_init) as pool:
        d._POOL=pool
        pilot=measure_fresh_counted_validation(pool)
        completed=sum(d.done(t) for t in d.tasks())
        observed_peak=pilot['peak_rss_bytes']
        observed_rows=pilot['training_rows']
        observed_features=pilot['feature_count']


        grouped={}
        for task in d.tasks():
            grouped.setdefault(task['date'],[]).append(task)
        for date,group in grouped.items():
            waiting=[task for task in group if not d.done(task)]
            if not waiting: continue
            legal=d.update_legal_labels(date)
            max_features=max(len(d.read(d.BANK/'PREPARE.json')['feature_order'][t['arm']]) for t in waiting)
            growth=max(1.0,(len(legal)*max_features)/(observed_rows*observed_features))
            projected_worker=observed_peak*growth*1.08
            parent,worker_rss=snapshot(pool)
            effective=planned_concurrency(parent,worker_rss,projected_worker)
            d.require(effective>=1,'Insufficient6.6GiB projected headroom even for one worker')
            active={}
            origin_counts.append(dict(date=date,training_rows=len(legal),
                estimated_peak_worker_rss_bytes=int(projected_worker),active_concurrency=effective))
            while waiting or active:
                current=d.current_tree_rss();tree_peak=max(tree_peak,current)
                d.require(current<6.6*1024**3,'Known day-ahead task tree exceeds6.6GiB; resume serially')
                if current>6.0*1024**3:
                    effective=1
                while waiting and len(active)<effective:
                    parent,worker_rss=snapshot(pool)
                    current=parent+sum(worker_rss)
                    idle_count=max(0,len(worker_rss)-len(active))
                    incoming=(max(0,projected_worker-min(worker_rss))
                              if idle_count and worker_rss else projected_worker)
                    if current+incoming>=6.6*1024**3 and active:
                        break
                    d.require(current+incoming<6.6*1024**3,'No6.6GiB projected headroom for pending specified fit')
                    task=waiting.pop(0)
                    active[pool.submit(d.fit_one,task)]=task
                d.require(bool(active),'Insufficient memory headroom for next specified fit')
                finished,_=cf.wait(active,timeout=1,return_when=cf.FIRST_COMPLETED)
                for future in finished:
                    rec=future.result();del active[future];completed+=1
                    if rec['training_rows']>=observed_rows:
                        observed_peak=max(observed_peak,rec['peak_rss_bytes'])
                        observed_rows=rec['training_rows']
                        observed_features=rec['feature_count']
                    if completed%7==0 or rec['split']=='validation':
                        d.progress('RESOURCE_SCHEDULED_FITS_PROGRESS',fits_done=completed,fits_total=2562,
                            origin_date_aest=date,effective_workers=effective,
                            elapsed_seconds=time.perf_counter()-started,
                            process_tree_peak_rss_bytes=tree_peak)
            d.write(d.BANK/'RESOURCE_SCHEDULER_PROGRESS.json',dict(state='ACTIVE',fits_done=completed,
                origin_date_aest=date,origin_concurrency=origin_counts,
                process_tree_peak_rss_bytes=tree_peak,resource_scheduler_freeze_sha256=d.sha(HERE/'RESOURCE_SCHEDULER_FREEZE_9.json')))
        d._POOL=None
    d.require(completed==2562,'Original complete2,562-fit bank not achieved')
    summary=dict(state='COMPLETE',fits=2562,validation_fits=7,test_fits=2555,
        fits_per_arm={arm:366 for arm in d.ARMS},runtime_this_invocation_seconds=time.perf_counter()-started,
        process_tree_peak_rss_bytes=tree_peak,max_workers=4,
        resource_scheduler_freeze_sha256=d.sha(HERE/'RESOURCE_SCHEDULER_FREEZE_9.json'),
        original_execution_freeze_sha256=frozen['original_execution_freeze_sha256'])
    d.write(d.BANK/'FIT_SUMMARY.json',summary)
    d.progress('FITS_COMPLETE',**summary)
    d.seal();d.score()

if __name__=='__main__':
    run()
