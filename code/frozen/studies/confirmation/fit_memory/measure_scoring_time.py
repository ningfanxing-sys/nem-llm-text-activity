"""CONFX7 addendum 3 measurements (synthetic, production shape): news 4 versus 7 workers, LEAR serial versus 1 and 3.

    python measure_speed_a3.py --new-root DIR --memory MEMORY_MEASUREMENTS.json --scratch DIR --out SPEED_MEASUREMENTS_A3.json

`--new-root` is a scratch copy of CONF with the CONFX7 adapters (`DIR/CONFX2`). Run only while no CONF process runs.
- News. Two registered origin waves at the last origin, 2026-09-30, each run through the real `_fit_wave` (real
  ProcessPool, admission, ledger and worker) with the pool limited to 4 and to 7 workers:
  - seed robustness: M, L_count and L_chen, each with two seeds;
  - secondary: M_shift, E_raw, P_shift, P_content and W2_D (W_Bai has no bundle).

  The bundles are the full-shape synthetic bundles that `measure_fit_memory.py` made: L_chen-like, 872 + 386 columns
  (also standing in for the other wide arms and for W2_D, whose width is unknown), and N-like, 872 columns. Rows are
  131,472. Projections are 1.08 × the measured anonymous peaks of `MEMORY_MEASUREMENTS.json`. Recorded per task:
  model, booster text, prediction, key and training-index hashes, runtime, concurrency at launch and both memory
  peaks. Recorded per wave: wall time and the maximum concurrency.
- LEAR. A synthetic hourly table (3 regions, 2021-10-01..2026-09-30) and two daily jobs (2026-03-01, 2026-09-30):
  - the serial reference `lear_adapter_confx5.run_daily_job` runs in one spawned worker with the frozen
    one-thread `worker_init`, as in production before addendum 3;
  - the parallel path runs through `_fit_wave` with 1 and with 3 subjob workers.

  Predictions, window receipts (without wall times, paths and npz container hashes) and every array in the model and
  scaling files are compared.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, multiprocessing as mp, os, sys, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

GIB = 1024 ** 3


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def news_part(ex, runtime, scheduler, memory, measure_scratch, scratch):
    cases = {c['case']['name']: c for c in memory['cases']}
    def peak(name):
        run = cases[name]['runs']['new']
        return (run['result'] or {}).get('peak_anonymous_bytes') or run['sampled_max_anonymous_bytes']
    wide_peak, narrow_peak = peak('news_L_chen_last_origin_full_shape'), peak('news_N_last_origin_full_shape')
    wide = json.loads((Path(measure_scratch) / 'news_L_chen_last_origin_full_shape' / 'bundle.json').read_text())
    narrow = json.loads((Path(measure_scratch) / 'news_N_last_origin_full_shape' / 'bundle.json').read_text())
    plan = {name: tasks for name, tasks, _ in ex.registered_plan()}
    waves = {'primary_seed_robustness_news': [t for t in plan['primary_seed_robustness_news'] if t.origin == '2026-09-30'],
             'secondary_news': [t for t in plan['secondary_news'] if t.origin == '2026-09-30' and t.arm != 'W_Bai']}
    is_wide = lambda arm: arm in ('L_chen', 'E_raw', 'P_shift', 'P_content', 'W2_D')
    out = {'wide_projection_bytes': int(1.08 * wide_peak), 'narrow_projection_bytes': int(1.08 * narrow_peak), 'waves': {}}
    permit = runtime.conf_module('guard').ExecutionPermit('SYNTHETIC_ONLY', 'a' * 64, 'b' * 64, True)
    for name, tasks in waves.items():
        arms = sorted({t.arm for t in tasks})
        manifest = {'bundles': [dict(wide if is_wide(arm) else narrow, arm=arm, variant='main') for arm in arms]}
        stats = {}
        for b in (wide, narrow):
            for p in [Path(item['path']) for item in (b['shared_numeric'], b['extras_matrix'], b['feature_order'])] + [Path(b['panel_path'])]:
                s = p.resolve().stat(); stats[str(p.resolve())] = [s.st_size, s.st_mtime_ns]
        projected = {ex.task_id(t): out['wide_projection_bytes'] if is_wide(t.arm) else out['narrow_projection_bytes'] for t in tasks}
        runs = {}
        for workers in (4, 7):
            state = Path(scratch) / f'{name}__{workers}'
            state.mkdir(parents=True, exist_ok=False)
            ex.NEWS_MAX_WORKERS = workers
            started = time.monotonic()
            records = ex._fit_wave(tasks, 'speed_proof_' + name, manifest, 'c' * 64, stats, permit, state, ex.WallLedger(state), projected)
            wall = time.monotonic() - started
            per = {}
            for r in records:
                per[r['task_id']] = {k: r.get(k) for k in ('state', 'error', 'model_sha256', 'prediction_sha256', 'prediction_key_sha256',
                                                           'train_indices_sha256', 'train_rows', 'features', 'runtime_seconds',
                                                           'peak_rss_bytes', 'peak_anonymous_bytes', 'concurrent_fits_at_launch',
                                                           'pool_max_workers', 'wave_max_concurrent_fits_so_far')}
                if r.get('model_path'):
                    per[r['task_id']]['booster_text_sha256'] = sha(r['model_path'])
            runs[workers] = {'wave_wall_seconds': wall, 'max_concurrent_fits': max(v['wave_max_concurrent_fits_so_far'] or 0 for v in per.values()),
                             'tasks': per}
            print(json.dumps({'wave': name, 'workers': workers, 'wall': round(wall, 1), 'max_concurrent': runs[workers]['max_concurrent_fits'],
                              'states': sorted({v['state'] for v in per.values()})}), flush=True)
        ex.NEWS_MAX_WORKERS = 7
        keys = ('model_sha256', 'booster_text_sha256', 'prediction_sha256', 'prediction_key_sha256', 'train_indices_sha256',
                'train_rows', 'features')
        identity = {tid: {k: runs[4]['tasks'][tid].get(k) == runs[7]['tasks'][tid].get(k) and runs[4]['tasks'][tid].get(k) is not None
                          for k in keys} for tid in runs[4]['tasks']}
        out['waves'][name] = {'tasks': [ex.task_id(t) for t in tasks], 'wide_arms': [t.arm for t in tasks if is_wide(t.arm)],
                              'runs': {str(k): v for k, v in runs.items()}, 'identity_4_vs_7': identity,
                              'all_identical': all(all(v.values()) for v in identity.values()) and set(runs[4]['tasks']) == set(runs[7]['tasks'])}
    return out


def hourly_table(path, tests_dir):
    import numpy as np, pandas as pd
    sys.path.insert(0, str(tests_dir))
    from test_execution_adapters import news_rows
    frame = news_rows(pd.date_range('2021-10-01', '2026-09-30').strftime('%Y-%m-%d'))
    rng = np.random.default_rng(31)
    frame['y'] = 60. + 25. * np.sin(np.arange(len(frame)) / 9.) + rng.gamma(2., 6., len(frame))
    frame[['region', 'target_time', 'target_day', 'y', 'label_available']].to_parquet(path, index=False)


def comparable(window):
    return {k: v for k, v in window.items() if k not in ('runtime_seconds', 'model_path', 'input_scaling_path', 'model_sha256',
                                                         'input_imputation_scaling_sha256')}


def arrays_equal(left, right):
    import numpy as np
    with np.load(left) as a, np.load(right) as b:
        return sorted(a.files) == sorted(b.files) and all(np.array_equal(a[k], b[k]) for k in a.files)


def lear_part(ex, lp, confx5, runtime, scheduler, tests_dir, scratch):
    root = Path(scratch) / 'lear'; root.mkdir(parents=True, exist_ok=False)
    hourly = root / 'hourly.parquet'; hourly_table(hourly, tests_dir)
    manifest = {'hourly_path': str(hourly), 'hourly_sha256': runtime.sha256(hourly)}
    permit = runtime.conf_module('guard').ExecutionPermit('SYNTHETIC_ONLY', 'a' * 64, 'b' * 64, True)
    out = {'issues': {}}
    for issue in ('2026-03-01', '2026-09-30'):
        task = scheduler.FitTask('lear', issue, 'LEAR', 20260919, component_pairs=288)
        started = time.monotonic()
        with ProcessPoolExecutor(max_workers=1, mp_context=mp.get_context('spawn'), initializer=scheduler.worker_init) as one:
            serial = one.submit(confx5.run_daily_job, (task, manifest, 'c' * 64, {}, permit, str(root / ('serial_' + issue)))).result()
        entry = {'serial': {'state': serial['state'], 'error': serial.get('error'), 'runtime_seconds': serial['runtime_seconds'],
                            'wall_seconds_with_spawn': time.monotonic() - started, 'peak_rss_bytes': serial['peak_rss_bytes']},
                 'parallel': {}}
        for workers in (1, 3):
            state = root / f'state_{issue}_{workers}'
            lp.SUBJOB_WORKERS = workers
            started = time.monotonic()
            rec = ex._fit_wave([task], 'speed_proof_lear', manifest, 'c' * 64, {}, permit, state, ex.WallLedger(state), 512 * 1024 ** 2)[0]
            wall = time.monotonic() - started
            same = (rec['state'] == 'COMPLETE' == serial['state'] and
                    sha(rec['prediction_path']) == sha(serial['prediction_path']) and
                    rec['prediction_key_sha256'] == serial['prediction_key_sha256'] and
                    [comparable(w) for w in rec['windows']] == [comparable(w) for w in serial['windows']] and
                    all(arrays_equal(a[f], b[f]) for a, b in zip(serial['windows'], rec['windows'])
                        for f in ('model_path', 'input_scaling_path')))
            entry['parallel'][str(workers)] = {'state': rec['state'], 'error': rec.get('error'), 'runtime_seconds': rec['runtime_seconds'],
                                               'wave_wall_seconds': wall, 'subjob_workers': rec.get('subjob_workers'),
                                               'distinct_worker_pids': len(rec.get('subjob_worker_pids') or []),
                                               'peak_anonymous_bytes': rec.get('peak_anonymous_bytes'), 'peak_rss_bytes': rec.get('peak_rss_bytes'),
                                               'identical_to_serial': same}
            print(json.dumps({'lear': issue, 'workers': workers, 'wall': round(wall, 1), 'identical': same}), flush=True)
        lp.SUBJOB_WORKERS = 3
        out['issues'][issue] = entry
    out['all_identical'] = all(p['identical_to_serial'] for e in out['issues'].values() for p in e['parallel'].values())
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--new-root', required=True); parser.add_argument('--memory', required=True)
    parser.add_argument('--measure-scratch', required=True); parser.add_argument('--scratch', required=True); parser.add_argument('--out', required=True)
    args = parser.parse_args()
    code = Path(args.new_root) / 'CONFX2'
    sys.path.insert(0, str(code))
    import runtime, execution_adapter as ex, lear_parallel as lp, lear_adapter_confx5 as confx5  # noqa: E401,E402
    scheduler = runtime.conf_module('scheduler')
    Path(args.scratch).mkdir(parents=True, exist_ok=False)
    memory = json.loads(Path(args.memory).read_text())
    result = {'task': 'CONFX7', 'addendum': 3, 'time_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'synthetic_only': True,
              'host': {'cpu': 'Apple M2, 4 performance + 4 efficiency cores', 'memory_bytes': 8 * GIB},
              'code_root': str(code), 'script_sha256': sha(__file__)}
    result['news'] = news_part(ex, runtime, scheduler, memory, args.measure_scratch, Path(args.scratch) / 'news')
    result['lear'] = lear_part(ex, lp, confx5, runtime, scheduler, code / 'tests', args.scratch)
    result['findings'] = {'news_identical_4_vs_7': all(w['all_identical'] for w in result['news']['waves'].values()),
                          'lear_identical_serial_vs_1_and_3': result['lear']['all_identical']}
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result['findings']))


if __name__ == '__main__':
    main()
