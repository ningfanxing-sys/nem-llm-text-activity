'Fit the specified additional seeds and windowed activity references.'
from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

OUT = Path(__file__).resolve().parents[1]
STUDY = OUT.parents[2]
confirmation = STUDY / 'studies/confirmation'
FROZEN = confirmation / 'execution'
STATE = FROZEN / 'host_state'
PYTHON = (STUDY / '../../.venv/bin/python').resolve()
MIN_DISK = 3 * 1024**3
sys.dont_write_bytecode = True


def read(path):
    return json.loads(Path(path).read_text())


def write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024**2), b''):
            h.update(part)
    return h.hexdigest()


def progress(message):
    line = dt.datetime.now(dt.timezone.utc).isoformat() + ' ' + message
    with (OUT / 'status.txt').open('a') as stream:
        stream.write(line + '\n')
    print(line, flush=True)


def resources():
    import psutil
    m = psutil.virtual_memory()
    return {'available_ram_bytes': m.available, 'total_ram_bytes': m.total,
            'available_ram_fraction': m.available / m.total,
            'free_disk_bytes': shutil.disk_usage(OUT).free}


def check_resources():
    r = resources()
    if r['free_disk_bytes'] < MIN_DISK:
        raise RuntimeError('STOP: free disk below 3 GiB: ' + str(r))
    if r['available_ram_fraction'] < .10:
        raise RuntimeError('STOP: available RAM below 10%: ' + str(r))
    return r


def imports():
    sys.path.insert(0, str(FROZEN))
    import runtime

    runtime.ROOT = OUT / 'logs'
    runtime.ROOT.mkdir(exist_ok=True)
    import execution_adapter as execution
    scheduler = runtime.conf_module('scheduler')
    guard = runtime.conf_module('guard')
    return runtime, execution, scheduler, guard


def official_receipt(task, execution):
    return read(STATE / 'fits/receipts' / (execution.task_id(replace(task, seed=20260919)) + '.json'))


def fit_child(spec_path):
    runtime, execution, scheduler, guard = imports()
    spec = read(spec_path)
    task = scheduler.FitTask(**spec['task'])
    receipt = official_receipt(task, execution)
    permit = guard.ExecutionPermit('POSTHOC_20261019_USER_AUTHORIZED',
        receipt['design_freeze_sha256'], receipt['completed_input_manifest_sha256'], True)
    bundle = spec['bundle']


    import numpy as np
    assert bundle['columns'] == bundle['shared_columns']
    assert bundle['pruned_names'] == [] and bundle['extra_columns'] == []
    bundle['matrix'] = dict(bundle['shared_numeric'])
    original = execution.select_rows
    def contiguous_rows(panel, task, bundle):
        train, query, clocks = original(panel, task, bundle)
        for indices in (train, query):
            if not np.array_equal(indices, np.arange(indices[0], indices[-1] + 1)):
                raise RuntimeError('Read-only direct mmap requires contiguous frozen N rows')
        return train, query, clocks
    execution.select_rows = contiguous_rows
    result = execution._worker((task, bundle, spec['feature_manifest_sha256'],
        spec['stats'], permit, str(OUT / 'gate/artifacts')))
    output_root = Path(spec.get('output_root', str(OUT / 'gate')))

    if output_root != OUT / 'gate':
        raise RuntimeError('Unexpected gate child output destination')
    write(output_root / 'receipts' / (execution.task_id(task) + '.json'), result)
    return 0 if result['state'] == 'COMPLETE' else 2


def equivalence():
    started = time.monotonic()
    progress('equivalence: verifying frozen inputs; no other analyses started')
    expected = (OUT / 'PLAN.sha256').read_text().split()[0]
    if sha(OUT / 'PLAN.md') != expected:
        raise RuntimeError('PLAN hash mismatch')
    runtime, execution, scheduler, guard = imports()
    manifest_path = STATE / 'features/manifest.json'
    manifest = read(manifest_path)
    seal = read(STATE / 'SEAL.json')
    manifest_sha = sha(manifest_path)
    if manifest_sha != seal['feature_manifest_sha256']:
        raise RuntimeError('Frozen feature manifest differs from SEAL')
    if sha(confirmation / 'FREEZE.json') != seal['design_freeze_sha256']:
        raise RuntimeError('Frozen design differs from SEAL')
    tasks = [scheduler.FitTask('notice', 'prewindow_frozen_C_bank', 'N', 20260919)]
    tasks += [scheduler.FitTask('news', day, 'N', 20260919)
              for day in ('2026-05-19', '2026-05-20', '2026-05-21')]
    verified = {}
    gate = {'state': 'RUNNING', 'tolerance': 1e-9, 'plan_sha256': expected,
            'feature_manifest_sha256': manifest_sha, 'fits': []}
    write(OUT / 'EQUIVALENCE_GATE.json', gate)
    for task in tasks:
        check_resources()
        bundle = execution.find_bundle(manifest, task)
        execution.verify_bundle(bundle, seen=verified)
        if sha(bundle['panel_path']) != bundle['panel_sha256']:
            raise RuntimeError('Frozen panel hash mismatch')
        official = official_receipt(task, execution)
        if official['params'] != execution.parameters(task):
            raise RuntimeError('Frozen fitting parameter mismatch')
        if sha(official['prediction_path']) != official['prediction_sha256']:
            raise RuntimeError('Frozen prediction hash mismatch')
        sealed = [p for p in seal['predictions'] if p['source'] == task.task
                  and p['arm'] == task.arm and p['seed'] == task.seed and p['variant'] == task.variant]
        if len(sealed) != 1 or sha(sealed[0]['path']) != sealed[0]['sha256']:
            raise RuntimeError('Frozen sealed forecast identity mismatch')
        paths = execution.bundle_storage_paths(bundle) + [Path(bundle['panel_path'])]
        stats = {str(p): [p.stat().st_size, p.stat().st_mtime_ns] for p in paths}
        spec_path = OUT / 'gate/specs' / (execution.task_id(task) + '.json')
        write(spec_path, {'task': task.__dict__, 'bundle': bundle, 'stats': stats,
                         'feature_manifest_sha256': manifest_sha})
        receipt_path = OUT / 'gate/receipts' / (execution.task_id(task) + '.json')
        progress('equivalence: fitting ' + execution.task_id(task))
        reference_snapshot = check_resources()
        log_path = OUT / 'logs' / (execution.task_id(task) + '.stdout.log')
        with log_path.open('a') as log:
            child = subprocess.Popen([str(PYTHON), '-B', str(Path(__file__).resolve()),
                                      'fit-child', '--spec', str(spec_path)], stdout=log, stderr=log,
                                     env=os.environ.copy())
            min_ram = reference_snapshot['available_ram_fraction']
            min_disk = reference_snapshot['free_disk_bytes']
            try:
                while child.poll() is None:
                    r = check_resources()
                    min_ram = min(min_ram, r['available_ram_fraction'])
                    min_disk = min(min_disk, r['free_disk_bytes'])
                    time.sleep(.5)
            except BaseException:
                child.terminate()
                child.wait()
                raise
        if child.returncode or not receipt_path.exists():
            raise RuntimeError('Equivalence child failed; inspect ' + str(log_path))
        rec = read(receipt_path)
        if rec['state'] != 'COMPLETE':
            raise RuntimeError('Equivalence fit failed: ' + str(rec))
        import pandas as pd
        import numpy as np
        new = pd.read_parquet(rec['prediction_path'])
        old = pd.read_parquet(official['prediction_path'])
        frozen = pd.read_parquet(sealed[0]['path'])
        keys = execution.KEYS
        for col in ('origin', 'target_time'):
            for table in (new, old, frozen):
                table[col] = pd.to_datetime(table[col], utc=True)
        joined = new.merge(old, on=keys, validate='one_to_one', suffixes=('_new', '_old'))
        if len(joined) != len(new) or len(new) != len(old):
            raise RuntimeError('Equivalence keys mismatch')
        frozen_join = new.merge(frozen, on=keys, validate='one_to_one', suffixes=('_new', '_sealed'))
        if len(frozen_join) != len(new):
            raise RuntimeError('Equivalence sealed keys mismatch')
        diff = float(np.max(np.abs(joined.prediction_new - joined.prediction_old)))
        sealed_diff = float(np.max(np.abs(frozen_join.prediction_new - frozen_join.prediction_sealed)))
        rawdiff = float(np.max(np.abs(joined.raw_prediction_new - joined.raw_prediction_old)))
        item = {'task_id': execution.task_id(task), 'rows': len(new),
                'max_abs_difference': diff, 'max_abs_difference_sealed': sealed_diff,
                'max_abs_difference_raw': rawdiff,
                'runtime_seconds': rec['runtime_seconds'], 'peak_rss_bytes': rec['peak_rss_bytes'],
                'peak_anonymous_bytes': rec['peak_anonymous_bytes'],
                'min_available_ram_fraction': min_ram, 'min_free_disk_bytes': min_disk,
                'train_indices_match': rec['train_indices_sha256'] == official['train_indices_sha256'],
                'params_match': rec['params'] == official['params']}
        gate['fits'].append(item)
        gate['max_abs_difference'] = max(max(x['max_abs_difference'], x['max_abs_difference_sealed']) for x in gate['fits'])
        gate['runtime_seconds'] = time.monotonic() - started
        if gate['max_abs_difference'] > gate['tolerance']:
            gate['state'] = 'FAILED_STOP'
            write(OUT / 'EQUIVALENCE_GATE.json', gate)
            progress('STOP: equivalence discrepancy ' + str(gate['max_abs_difference']))
            return 2
        write(OUT / 'EQUIVALENCE_GATE.json', gate)
        progress('equivalence: exact prediction match ' + execution.task_id(task))
    gate['state'] = 'PASSED'
    write(OUT / 'EQUIVALENCE_GATE.json', gate)
    progress('equivalence: PASSED max_abs_difference=' + str(gate['max_abs_difference']))
    return 0


def require_gate():
    gate = read(OUT / 'EQUIVALENCE_GATE.json')
    if gate['state'] != 'PASSED' or gate['max_abs_difference'] > 1e-9 or len(gate['fits']) != 4:
        raise RuntimeError('All four equivalence fits must pass before later work')
    if sha(OUT / 'PLAN.md') != (OUT / 'PLAN.sha256').read_text().split()[0]:
        raise RuntimeError('PLAN changed')


def analysis_child(spec_path):
    runtime, execution, scheduler, guard = imports()
    spec = read(spec_path)
    task = scheduler.FitTask(**spec['task'])
    original = official_receipt(task, execution)
    permit = guard.ExecutionPermit('POSTHOC_20261019_USER_AUTHORIZED',
        original['design_freeze_sha256'], original['completed_input_manifest_sha256'], True)
    bundle = spec['bundle']
    import numpy as np
    if task.arm == 'N':
        assert bundle['columns'] == bundle['shared_columns']
        assert not bundle['pruned_names'] and not bundle['extra_columns']
        bundle['matrix'] = dict(bundle['shared_numeric'])
    else:


        sentinel = str(OUT / 'virtual_readonly_matrix')
        original_load = np.load
        small = original_load(spec['activity_path'], mmap_mode='r', allow_pickle=False)
        class Composite:
            dtype = np.dtype('float32')
            shape = tuple(bundle['matrix']['shape'])
            def __getitem__(self, rows):
                block = execution.load_feature_rows(bundle, rows)
                names = ['notice_prefix_count', 'notice_arrivals_6h', 'notice_failed_prefix_count']
                for i, name in enumerate(names):
                    block[:, bundle['columns'].index(name)] = small[rows, i]
                return block
        virtual = Composite()
        def virtual_load(path, *args, **kwargs):
            return virtual if str(path) == sentinel else original_load(path, *args, **kwargs)
        np.load = virtual_load
        bundle['matrix'] = {**bundle['matrix'], 'path': sentinel}
    original_rows = execution.select_rows
    def checked_rows(panel, task, bundle):
        train, query, clocks = original_rows(panel, task, bundle)
        for indices in (train, query):
            if not np.array_equal(indices, np.arange(indices[0], indices[-1] + 1)):
                raise RuntimeError('Frozen selection is not contiguous; refusing disk scratch copy')
        return train, query, clocks
    execution.select_rows = checked_rows
    result = execution._worker((task, bundle, spec['feature_manifest_sha256'], spec['stats'],
                                permit, str(Path(spec['output_root']) / 'artifacts')))
    result['posthoc_group'] = spec['group']
    if spec.get('activity_path'):
        result['activity_path'] = spec['activity_path']
        result['activity_sha256'] = sha(spec['activity_path'])
    if result.get('train_indices_sha256') != original['train_indices_sha256']:
        result.update(state='FAILED', error='Frozen training row indices differ')
    wanted = dict(original['params'], random_state=task.seed)
    if result.get('params') != wanted:
        result.update(state='FAILED', error='Fitting parameters differ beyond authorized seed')
    write(Path(spec['output_root']) / 'receipts' / (execution.task_id(task) + '.json'), result)
    return 0 if result['state'] == 'COMPLETE' else 2


def run_one(task, group, activity_path=None, stop_event=None):
    require_gate()
    runtime, execution, scheduler, guard = imports()
    manifest_path = STATE / 'features/manifest.json'
    manifest = read(manifest_path)
    bundle = execution.find_bundle(manifest, task)
    original = official_receipt(task, execution)
    output_root = OUT / 'fits' / group
    receipt_path = output_root / 'receipts' / (execution.task_id(task) + '.json')
    spec_path = output_root / 'specs' / (execution.task_id(task) + '.json')
    if receipt_path.exists():
        r = read(receipt_path)
        if r['state'] == 'COMPLETE' and sha(r['prediction_path']) == r['prediction_sha256']:
            if r['params'] == dict(original['params'], random_state=task.seed):
                if not activity_path or r.get('activity_sha256') == sha(activity_path):
                    progress(group + ': reused ' + execution.task_id(task))
                    return r
        raise RuntimeError('Existing receipt cannot be reused without investigation: ' + str(receipt_path))
    execution.verify_bundle(bundle)
    if sha(bundle['panel_path']) != bundle['panel_sha256']:
        raise RuntimeError('Frozen panel identity changed')
    paths = execution.bundle_storage_paths(bundle) + [Path(bundle['panel_path'])]
    stats = {str(p): [p.stat().st_size, p.stat().st_mtime_ns] for p in paths}
    write(spec_path, {'task': task.__dict__, 'bundle': bundle, 'stats': stats, 'group': group,
        'feature_manifest_sha256': sha(manifest_path), 'output_root': str(output_root),
        'activity_path': str(activity_path) if activity_path else None})
    reference_snapshot = check_resources()
    progress(group + ': fitting ' + execution.task_id(task))
    log_path = OUT / 'logs' / (group + '__' + execution.task_id(task) + '.stdout.log')
    start = time.monotonic()
    min_ram, min_disk = reference_snapshot['available_ram_fraction'], reference_snapshot['free_disk_bytes']
    with log_path.open('a') as log:
        child = subprocess.Popen([str(PYTHON), '-B', str(Path(__file__).resolve()),
            'analysis-child', '--spec', str(spec_path)], stdout=log, stderr=log, env=os.environ.copy())
        last = start
        try:
            while child.poll() is None:
                if stop_event is not None and stop_event.is_set():
                    raise RuntimeError('Another fit in the same news origin failed; stopping this worker')
                r = check_resources()
                min_ram = min(min_ram, r['available_ram_fraction'])
                min_disk = min(min_disk, r['free_disk_bytes'])
                if time.monotonic() - last >= 30:
                    progress(group + ': running ' + execution.task_id(task) + ' elapsed=' +
                             str(round(time.monotonic()-start, 1)) + 's ram_available=' +
                             str(round(r['available_ram_fraction']*100, 2)) + '%')
                    last = time.monotonic()
                time.sleep(.5)
        except BaseException:
            if stop_event is not None:
                stop_event.set()
            child.terminate()
            child.wait()
            raise
    if child.returncode or not receipt_path.exists():
        raise RuntimeError('Fit failed; inspect ' + str(log_path))
    rec = read(receipt_path)
    rec.update(min_available_ram_fraction=min_ram, min_free_disk_bytes=min_disk,
               wrapper_runtime_seconds=time.monotonic()-start)
    write(receipt_path, rec)
    if rec['state'] != 'COMPLETE':
        raise RuntimeError('Failed fit receipt ' + str(receipt_path))
    progress(group + ': complete ' + execution.task_id(task))
    return rec


def n_notices():
    require_gate()
    _, _, scheduler, _ = imports()
    start = time.monotonic()
    records = [run_one(scheduler.FitTask('notice', 'prewindow_frozen_C_bank', 'N', seed), 'no_text_notice')
               for seed in (20260920, 20260921)]
    write(OUT / 'STAGE_a1_notice.json', {'state': 'COMPLETE', 'runtime_seconds': time.monotonic()-start,
        'fits': len(records), 'peak_rss_bytes': max(r['peak_rss_bytes'] for r in records),
        'peak_anonymous_bytes': max(r['peak_anonymous_bytes'] for r in records)})
    progress('no_text_notice: STAGE COMPLETE')
    return 0


def window_notices():
    require_gate()
    if read(OUT / 'STAGE_a1_notice.json')['state'] != 'COMPLETE':
        raise RuntimeError('Analysis 1 notices must complete before Analysis 2')
    start = time.monotonic()
    checks_path = OUT / 'FEATURE_CHECKS.json'
    if checks_path.exists():
        checks = read(checks_path)
        if checks['state'] != 'PASS' or not all(sha(x['path']) == x['sha256'] for x in checks['outputs']):
            raise RuntimeError('Existing feature checks or count hashes failed')
    else:
        from window_features import build
        checks = build()
    _, _, scheduler, _ = imports()
    records = []
    for group in ('w7', 'w24'):
        for seed in (20260919, 20260920, 20260921):
            for arm in ('M_notice', 'L14', 'L_Laz', 'L_chen_notice'):
                records.append(run_one(scheduler.FitTask('notice', 'prewindow_frozen_C_bank', arm, seed),
                    group, OUT / 'features' / (group + '.activity.npy')))
    for arm in ('M_shift_notice', 'P_shift'):
        records.append(run_one(scheduler.FitTask('notice', 'prewindow_frozen_C_bank', arm, 20260919),
            'w7_shift', OUT / 'features/w7_shift.activity.npy'))
    if len(records) != 26:
        raise RuntimeError('Analysis 2 fixed fit count changed')
    write(OUT / 'STAGE_a2_notice.json', {'state': 'COMPLETE', 'runtime_seconds': time.monotonic()-start,
        'fits': len(records), 'peak_rss_bytes': max(r['peak_rss_bytes'] for r in records),
        'peak_anonymous_bytes': max(r['peak_anonymous_bytes'] for r in records)})
    progress('a2_notice: STAGE COMPLETE')
    return 0


def n_news():
    require_gate()
    if read(OUT / 'STAGE_a2_notice.json')['state'] != 'COMPLETE':
        raise RuntimeError('All notice fits must complete before news fits')
    _, _, scheduler, _ = imports()
    start = time.monotonic()
    records = []
    import threading
    from concurrent.futures import ThreadPoolExecutor


    for day in scheduler.days('2026-05-19', '2026-09-30'):
        stop_event = threading.Event()
        def one(seed):
            try:
                return run_one(scheduler.FitTask('news', day, 'N', seed), 'no_text_news', stop_event=stop_event)
            except BaseException:
                stop_event.set()
                raise
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(one, seed) for seed in (20260920, 20260921)]
            records.extend(f.result() for f in futures)
        progress('no_text_news: complete origin ' + day + ' fits=' + str(len(records)) + '/270')
    if len(records) != 270:
        raise RuntimeError('Analysis 1 news fixed fit count changed')
    write(OUT / 'STAGE_a1_news.json', {'state': 'COMPLETE', 'runtime_seconds': time.monotonic()-start,
        'fits': len(records), 'max_workers': 2, 'learner_threads': 1,
        'peak_rss_bytes': max(r['peak_rss_bytes'] for r in records),
        'peak_anonymous_bytes': max(r['peak_anonymous_bytes'] for r in records)})
    progress('no_text_news: STAGE COMPLETE')
    return 0


def scoring_stage():
    from score_posthoc import score
    score()
    from make_report import generate
    generate()
    return 0


def remaining_chain():

    require_gate()
    if (OUT / 'STOP.json').exists():
        raise RuntimeError('A prior STOP record prohibits automatic continuation')
    progress('remaining: waiting for the current Analysis 2 notice stage')
    last = time.monotonic()
    while not (OUT / 'STAGE_a2_notice.json').exists():
        if (OUT / 'STOP.json').exists():
            raise RuntimeError('A prerequisite stage stopped; dependent stages prohibited')
        check_resources()
        if time.monotonic()-last >= 45:
            progress('remaining: still waiting; no news or scoring launched')
            last = time.monotonic()
        time.sleep(5)
    if read(OUT / 'STAGE_a2_notice.json')['state'] != 'COMPLETE':
        raise RuntimeError('Analysis 2 notice stage is incomplete')
    n_news()
    from score_posthoc import score
    score()
    progress('remaining: all fixed-plan fits and scoring complete; writing final report')
    from make_report import generate
    generate()
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument('stage', choices=['equivalence', 'fit-child', 'analysis-child', 'a1-notice', 'a2-notice', 'a1-news', 'score', 'remaining'])
    p.add_argument('--spec')
    args = p.parse_args()
    os.environ.update(PYTHONDONTWRITEBYTECODE='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1',
                      MPLCONFIGDIR=str(OUT / 'tmp/matplotlib'), TMPDIR=str(OUT / 'tmp'))
    (OUT / 'tmp').mkdir(exist_ok=True)
    lock = None
    try:
        actions = {'equivalence': equivalence, 'a1-notice': n_notices, 'a2-notice': window_notices,
                   'a1-news': n_news, 'score': scoring_stage, 'remaining': remaining_chain}
        if args.stage == 'fit-child':
            return fit_child(args.spec)
        if args.stage == 'analysis-child':
            return analysis_child(args.spec)
        import fcntl
        lock = (OUT / '.posthoc_execution.lock').open('a+')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another seed and window stage is active; no concurrent resume permitted') from exc
        return actions[args.stage]()
    except BaseException as exc:
        if args.stage not in ('fit-child', 'analysis-child'):
            write(OUT / 'STOP.json', {'state': 'STOP', 'stage': args.stage,
                                     'error': repr(exc), 'resources': resources()})
            progress('STOP: ' + repr(exc))
        raise
    finally:
        if lock is not None:
            lock.close()


if __name__ == '__main__':
    sys.exit(main())
