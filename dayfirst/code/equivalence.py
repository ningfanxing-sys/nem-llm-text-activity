'Compare saved predictions and check their input hashes.'
from __future__ import annotations
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import resource
import shutil
import sys
import time
import traceback

sys.dont_write_bytecode = True
OUT = Path(__file__).resolve().parents[1]
STUDY = OUT.parents[2]
confirmation = STUDY / 'studies/confirmation'
STATE = confirmation / 'execution/host_state'
POST = OUT.parent / 'posthoc_20261019'
BATCH = STUDY / 'studies/batch_estimation/disk_checks'
KEYS = ['origin', 'target_time', 'region', 'horizon']
os.environ['MPLCONFIGDIR'] = str(OUT / 'logs/matplotlib')
os.environ['XDG_CACHE_HOME'] = str(OUT / 'logs/cache')
os.environ['TMPDIR'] = str(OUT / 'logs/tmp')
for _folder in ('logs/matplotlib', 'logs/cache', 'logs/tmp'):
    (OUT / _folder).mkdir(parents=True, exist_ok=True)

def read(p):
    return json.loads(Path(p).read_text())

def write(p, obj):
    p = Path(p)
    assert p.resolve().is_relative_to(OUT)
    p.parent.mkdir(parents=True, exist_ok=True)
    t = p.with_suffix(p.suffix + '.tmp')
    t.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    t.replace(p)

def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as stream:
        for b in iter(lambda: stream.read(1024**2), b''):
            h.update(b)
    return h.hexdigest()

def progress(s):
    line = dt.datetime.now(dt.timezone.utc).isoformat() + ' ' + s
    with (OUT / 'status.txt').open('a') as f:
        f.write(line + '\n')
    print(line, flush=True)

def resources():
    import psutil
    m = psutil.virtual_memory()
    r = dict(available_ram_fraction=m.available / m.total,
             available_ram_bytes=m.available, free_disk_bytes=shutil.disk_usage(OUT).free)
    if r['available_ram_fraction'] < .10 or r['free_disk_bytes'] < 3 * 1024**3:
        raise RuntimeError('Resource minimum violated: ' + str(r))
    return r

def imports():
    sys.path.insert(0, str(confirmation / 'execution'))
    import runtime
    runtime.ROOT = OUT / 'logs'
    import execution_adapter as execution
    import feature_storage as storage
    return runtime, execution, storage

def notice_receipts():
    paths = list((STATE / 'fits/receipts').glob('notice__*.json'))
    paths += list((BATCH / 'state/fits/receipts').glob('notice__*.json'))
    paths += list((POST / 'fits').glob('*/receipts/notice__*.json'))
    return [(p, read(p)) for p in sorted(paths) if read(p).get('state') == 'COMPLETE']

def jobs():
    result = []
    manifest = read(STATE / 'features/manifest.json')
    for p, r in notice_receipts():
        a = r['task']['arm']
        if a not in ('L14', 'L_Laz', 'NPL', 'NPP', 'R', 'L14+', 'L_Laz+'):
            continue
        group = 'official' if p.is_relative_to(STATE) else 'windowed_activity' if p.is_relative_to(BATCH) else p.parents[1].name
        j = dict(id=group + '__' + r['task_id'], receipt_path=str(p), group=group)
        if group == 'windowed_activity':
            recipe = list((BATCH / 'state/features/windowed_activity').glob('attempts/*/notice__' + a + '.recipe.json'))
            assert len(recipe) == 1
            j['recipe_path'] = str(recipe[0])
            j['bundle'] = read(recipe[0])['recipe']['base']
        else:
            j['bundle'] = next(b for b in manifest['bundles'] if
                (b['source'], b['arm'], b.get('variant', 'main')) == ('notice', a, r['task']['variant']))
        if group in ('w7', 'w24', 'w7_shift'):
            j['activity_path'] = r['activity_path']
            assert sha(j['activity_path']) == r['activity_sha256']
        result.append(j)
    return result

def monthly_one(j):
    import numpy as np
    import pandas as pd
    import lightgbm as lgb
    started = time.monotonic()
    resources()
    runtime, execution, storage = imports()
    r = read(j['receipt_path'])
    assert sha(r['model_path']) == r['model_sha256']
    assert sha(r['prediction_path']) == r['prediction_sha256']
    b = j['bundle']
    storage.verify_bundle(b)
    assert sha(b['panel_path']) == b['panel_sha256']
    model = lgb.Booster(model_file=r['model_path'])
    assert model.feature_name() == r['feature_order']
    panel = pd.read_parquet(b['panel_path'], columns=KEYS + ['target_day', 'anchor'])
    indices = np.arange(b['train_rows'], len(panel))
    panel = panel.iloc[indices].reset_index(drop=True)
    raw = np.empty(len(indices), dtype='float64')
    activity = np.load(j['activity_path'], mmap_mode='r') if 'activity_path' in j else None
    recipe = read(j['recipe_path']) if 'recipe_path' in j else None
    meta = np.load(recipe['recipe']['metadata']['path'], mmap_mode='r') if recipe else None
    if recipe:
        assert sha(recipe['recipe']['metadata']['path']) == recipe['recipe']['metadata']['sha256']
    for start in range(0, len(indices), 32768):
        rows = indices[start:start + 32768]
        x = storage.load_feature_rows(b, rows)
        if activity is not None:
            for i, n in enumerate(('notice_prefix_count','notice_arrivals_6h','notice_failed_prefix_count')):
                x[:, b['columns'].index(n)] = activity[rows, i]
        if recipe:
            positions = {n: x[:,i] for i,n in enumerate(b['columns'])}
            positions.update({n:meta[rows,i] for i,n in enumerate(recipe['recipe']['metadata_columns'])})
            x = np.column_stack([positions[n] for n in recipe['columns']]).astype('float32')
        raw[start:start + len(rows)] = model.predict(x, num_threads=8)
        resources()
    raw += panel.anchor.to_numpy(dtype='float64')
    lower, upper = np.full(len(panel), -1000.), execution.price_cap(panel.target_time)
    new = panel[KEYS + ['target_day']].copy()
    new['raw_prediction'], new['prediction'] = raw, np.clip(raw, lower, upper).astype('float32')
    old = pd.read_parquet(r['prediction_path'])
    for f in (new, old):
        for c in ('origin', 'target_time'):
            f[c] = pd.to_datetime(f[c], utc=True)
        f.sort_values(KEYS, inplace=True)
        f.reset_index(drop=True, inplace=True)
    assert new[KEYS].equals(old[KEYS])
    differences = {c:float(np.max(np.abs(new[c].to_numpy(dtype='float64') - old[c].to_numpy(dtype='float64'))))
                   for c in ('raw_prediction','prediction')}
    result = dict(id=j['id'], state='PASS' if max(differences.values()) <= 1e-9 else 'FAILED_STOP',
                  rows=len(new), differences=differences, tolerance=1e-9, prediction_threads=8,
                  model_sha256=r['model_sha256'], receipt_path=j['receipt_path'],
                  runtime_seconds=time.monotonic() - started,
                  peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024))
    write(OUT / 'gate' / (j['id'] + '.json'), result)
    return result

def monthly():
    started = time.monotonic()
    plan_sha = (OUT / 'PLAN.sha256').read_text().split()[0]
    assert sha(OUT / 'PLAN.md') == plan_sha
    gate = dict(state='RUNNING_MONTH_FIRST', plan_sha256=plan_sha, tolerance=1e-9,
                month_first_checks=[], day_first_checks=[], models_refitted=0,
                scoring_started=False)
    write(OUT / 'EQUIVALENCE.json', gate)
    todo = jobs()
    write(OUT / 'gate/JOBS.json', todo)
    progress('Month-first equivalence: ' + str(len(todo)) + ' fitted-model checks, 2 processes, 8 prediction threads each')
    pending_jobs = iter(todo)
    pool = cf.ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context('spawn'), max_tasks_per_child=1)
    pending = {}
    try:
        for _ in range(2):
            j = next(pending_jobs, None)
            if j: pending[pool.submit(monthly_one, j)] = j
        while pending:
            resources()
            done, _ = cf.wait(pending, timeout=.5, return_when=cf.FIRST_COMPLETED)
            for future in done:
                j = pending.pop(future)
                item = future.result()
                gate['month_first_checks'].append(item)
                gate['runtime_seconds'] = time.monotonic() - started
                write(OUT / 'EQUIVALENCE.json', gate)
                progress(item['id'] + ' ' + item['state'] + ' ' + str(item['differences']))
                if item['state'] != 'PASS':
                    raise RuntimeError('Fixed-plan equivalence failed: ' + item['id'])
                j = next(pending_jobs, None)
                if j: pending[pool.submit(monthly_one, j)] = j
        gate['state'] = 'MONTH_FIRST_FITTED_MODELS_PASS_DELAYS_AND_DAY_FIRST_PENDING'
        write(OUT / 'EQUIVALENCE.json', gate)
    except BaseException as exc:
        gate.update(state='FAILED_STOP', error=str(exc), traceback=traceback.format_exc(), runtime_seconds=time.monotonic()-started)
        write(OUT / 'EQUIVALENCE.json', gate)
        progress('STOP: ' + str(exc))
        for p in list(pool._processes.values()):
            p.terminate()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)

if __name__ == '__main__':
    monthly()
