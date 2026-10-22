"""CONFX6 resource-guard audit (CONFX6/SPEC.md section 2): metadata sizes and synthetic measurements.

    python audit_resource_guards.py --code-root DIR --scratch DIR --out RESOURCE_GUARD_AUDIT.json

`--code-root` is a scratch copy of CONF (CONFX2/*.py, code/*.py, DESIGN_CONFIG.json, FREEZE.json), so
no live access log is touched. Under CONFX2/host_state only file names, sizes and allocated blocks are
listed (os.stat); no file there is opened. Every measured fit uses synthetic values and the unchanged
`execution_adapter._worker` in a fresh process, so the measured peak RSS is the quantity the frozen
per-job and task-tree guards test.
"""
from __future__ import annotations
import argparse, datetime as dt, json, math, os, subprocess, sys, threading, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONF = HERE.parent
FEATURES = CONF / 'CONFX2' / 'host_state' / 'features'
PY = sys.executable
GIB = 1024 ** 3
NEWS_ROWS = 131472            # news panel rows: (news_P_content_matched.npy bytes - 128 header) bool rows
NOTICE_TRAIN_ROWS = 894901    # frozen RF2 C training bank rows (CONFX5/RESTART_PROCEDURE.json)
NOTICE_QUERY_ROWS = 527040    # notice D window keys
NOTICE_ROWS = NOTICE_TRAIN_ROWS + NOTICE_QUERY_ROWS
NPY_HEADER = 128              # NPY v1 header length for these 2-D float32 shapes


# ----------------------------------------------------------------------------- metadata (names/sizes only)
def stat_features():
    files, cache = {}, {'files': 0, 'apparent_bytes': 0, 'allocated_bytes': 0}
    for entry in sorted(FEATURES.iterdir()):
        if entry.is_file():
            s = entry.stat(); files[entry.name] = {'bytes': s.st_size, 'allocated_bytes': s.st_blocks * 512}
    for root, _, names in os.walk(FEATURES / 'embedding_cache'):
        for name in names:
            s = os.stat(os.path.join(root, name))
            cache['files'] += 1; cache['apparent_bytes'] += s.st_size; cache['allocated_bytes'] += s.st_blocks * 512
    def kind(name):
        if name.endswith('.extras.npy') or name.endswith('__shared_numeric.npy'): return 'arrays'
        if name in ('news_keys_labels.parquet', 'notice_joint.parquet'): return 'panel_copies'
        return 'auxiliary'
    categories = {'arrays': 0, 'panel_copies': 0, 'auxiliary': cache['allocated_bytes']}
    for name, item in files.items(): categories[kind(name)] += item['allocated_bytes']
    return files, cache, categories


def columns_from_size(size, rows):
    data = size - NPY_HEADER
    if data % (4 * rows): return None
    return data // (4 * rows)


def derived_shapes(files):
    """Unpruned column counts from .npy sizes (no header or value is read)."""
    shapes = {}
    for name, item in files.items():
        if not name.endswith('.extras.npy') and not name.endswith('__shared_numeric.npy'): continue
        source = name.split('__')[0]
        rows = NEWS_ROWS if source == 'news' else NOTICE_ROWS
        shapes[name] = {'rows': rows, 'columns': columns_from_size(item['bytes'], rows), 'bytes': item['bytes'],
                        'allocated_bytes': item['allocated_bytes']}
    return shapes


# ----------------------------------------------------------------------------- fit-bank disk plan
def fit_disk_audit(code_root, shapes, free_now, remaining_feature_bytes):
    sys.path.insert(0, str(Path(code_root) / 'CONFX2'))
    import execution_adapter as ex  # noqa: E402
    shared = {src: shapes[src + '__shared_numeric.npy']['columns'] for src in ('news', 'notice')}
    bundles = []
    for name, shape in shapes.items():
        if not name.endswith('.extras.npy'): continue
        source, arm, variant = name[:-len('.extras.npy')].split('__')
        width = shared[source] + shape['columns']
        bundle = {'source': source, 'arm': arm, 'variant': variant, 'columns': ['c%d' % i for i in range(width)],
                  'matrix': {'shape': [shape['rows'], width], 'dtype': 'float32'}, 'state': 'COMPLETE'}
        if source == 'notice': bundle['train_rows'] = NOTICE_TRAIN_ROWS
        bundles.append(bundle)
    manifest = {'bundles': bundles}
    present = {(b['source'], b['arm'], b['variant']) for b in bundles}
    stages = []
    for stage, tasks, mandatory in ex.registered_plan():
        runnable = [t for t in tasks if t.task == 'lear' or (t.task, t.arm, 'main' if t.variant == '2025_fixed_validation' else t.variant) in present]
        excluded = sorted({t.arm for t in tasks if t not in runnable})
        plan = ex.fit_disk_plan(runnable, manifest) if runnable else {'planned_bytes': 0}
        stages.append({'stage': stage, 'mandatory': mandatory, 'registered_tasks': len(tasks), 'runnable_tasks': len(runnable),
                       'excluded_unavailable_arms': excluded, **plan,
                       'required_with_3GiB_headroom': plan['planned_bytes'] + ex.FIT_HEADROOM_BYTES})
    free_after_features = free_now - remaining_feature_bytes
    return {'free_bytes_now': free_now, 'remaining_feature_bytes_to_write': remaining_feature_bytes,
            'free_bytes_after_features_projection': free_after_features, 'stages': stages,
            'largest_stage_requirement': max(s['required_with_3GiB_headroom'] for s in stages),
            'reading': 'Each stage/wave guard reserves only its own remaining tasks; earlier persistent outputs are '
                       'already on disk. A guard trips only if free space after earlier outputs is below its row.'}


# ----------------------------------------------------------------------------- synthetic fit cases
def make_fit_case(code_root, case, folder):
    """Synthetic panel + deduplicated float32 bundle with the registered layout (chunked writes)."""
    sys.path.insert(0, str(Path(code_root) / 'CONFX2'))
    import numpy as np, pandas as pd
    import runtime  # noqa: E402
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20261002)
    if case['source'] == 'news':
        days = pd.date_range('2021-10-01', case['origin'], freq='D')
        issue = pd.DatetimeIndex([pd.Timestamp(d.date().isoformat(), tz='Australia/Brisbane') for d in days]).tz_convert('UTC')
        frames = []
        for region in ('NSW1', 'QLD1', 'TAS1'):
            for hour in range(24):
                target = issue + pd.Timedelta(hours=hour)
                frames.append(pd.DataFrame({'origin': issue, 'target_time': target, 'region': region, 'horizon': hour,
                                            'target_day': [d.date().isoformat() for d in days],
                                            'label_available': target + pd.Timedelta(hours=1, minutes=5)}))
        panel = pd.concat(frames, ignore_index=True).sort_values(['origin', 'region', 'horizon'], kind='mergesort').reset_index(drop=True)
        panel['y'] = rng.normal(80., 30., len(panel))
    else:
        def block(start, count, weight):
            origins = pd.date_range(pd.Timestamp(start, tz='Australia/Brisbane'), periods=count // 30 + 1, freq='5min').tz_convert('UTC')
            rows = []
            for region in ('NSW1', 'QLD1', 'SA1', 'TAS1', 'VIC1'):
                for horizon in (5, 10, 15, 20, 25, 30):
                    target = origins + pd.Timedelta(minutes=horizon)
                    rows.append(pd.DataFrame({'origin': origins, 'target_time': target, 'region': region, 'horizon': horizon,
                                              'label_available': target + pd.Timedelta(minutes=5)}))
            frame = pd.concat(rows, ignore_index=True).sort_values(['origin', 'region', 'horizon'], kind='mergesort').iloc[:count]
            frame['target_day'] = frame['target_time'].dt.tz_convert('Australia/Brisbane').dt.strftime('%Y-%m-%d')
            frame['weight'] = weight(len(frame))
            return frame
        train = block('2022-01-01', case['train_rows'], lambda n: np.where(np.arange(n) % 50 == 0, 50., 1.))
        query = block('2026-08-01', case['query_rows'], lambda n: np.ones(n))
        panel = pd.concat([train, query], ignore_index=True)
        panel['y'] = rng.normal(80., 30., len(panel)); panel['anchor'] = panel['y'] + rng.normal(0., 5., len(panel))
    panel_path = folder / 'panel.parquet'; panel.to_parquet(panel_path, index=False)
    rows = len(panel); shared_names = ['s%d' % i for i in range(case['shared'])]; extra_names = ['e%d' % i for i in range(case['extras'])]
    paths = {}
    for label, names in (('shared', shared_names), ('extras', extra_names)):
        path = folder / (label + '.npy')
        matrix = np.lib.format.open_memmap(path, mode='w+', dtype='float32', shape=(rows, len(names)))
        for start in range(0, rows, 20000):
            stop = min(rows, start + 20000)
            matrix[start:stop] = rng.normal(size=(stop - start, len(names))).astype('float32')
        matrix.flush(); del matrix; paths[label] = path
    order = {'shared_columns': shared_names, 'extra_columns': extra_names, 'original_columns': shared_names + extra_names,
             'keep_indices': list(range(len(shared_names) + len(extra_names))), 'columns': shared_names + extra_names,
             'pruned_names': []}
    order_path = folder / 'order.json'; runtime.atomic_json(order_path, order)
    bundle = {'source': case['source'], 'arm': case['arm'], 'variant': 'main', 'rows': rows,
              'panel_path': str(panel_path.resolve()), 'matrix': {'shape': [rows, len(order['columns'])], 'dtype': 'float32'},
              'shared_numeric': runtime.file_identity(paths['shared'], shape=[rows, len(shared_names)], dtype='float32'),
              'extras_matrix': runtime.file_identity(paths['extras'], shape=[rows, len(extra_names)], dtype='float32'),
              'feature_order': runtime.file_identity(order_path), **order}
    if case['source'] == 'notice': bundle['train_rows'] = case['train_rows']
    (folder / 'bundle.json').write_text(json.dumps(bundle))
    print(json.dumps({'rows': rows, 'columns': len(order['columns'])}))


def run_fit_case(code_root, case, folder):
    """One registered fit through the unchanged worker, as a fresh process (spawn equivalent)."""
    if case['source'] == 'news':                     # frozen scheduler.worker_init for news workers
        for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
            os.environ[key] = '1'
    sys.path.insert(0, str(Path(code_root) / 'CONFX2'))
    import runtime, execution_adapter as ex  # noqa: E401,E402
    folder = Path(folder); bundle = json.loads((folder / 'bundle.json').read_text())
    scheduler = runtime.conf_module('scheduler')
    task = scheduler.FitTask(case['source'], case['origin'] if case['source'] == 'news' else 'prewindow_frozen_C_bank',
                             case['arm'], 20260919)
    permit = runtime.conf_module('guard').ExecutionPermit('SYNTHETIC_ONLY', 'a' * 64, 'b' * 64, True)
    stats = {}
    for p in [Path(item['path']) for item in (bundle['shared_numeric'], bundle['extras_matrix'], bundle['feature_order'])] + [Path(bundle['panel_path'])]:
        s = p.resolve().stat(); stats[str(p.resolve())] = [s.st_size, s.st_mtime_ns]
    rec = ex._worker((task, bundle, 'c' * 64, stats, permit, str(folder / 'out')))
    keep = {k: rec.get(k) for k in ('state', 'error', 'train_rows', 'prediction_rows', 'features', 'runtime_seconds', 'peak_rss_bytes')}
    print('RESULT ' + json.dumps(keep))


def sample(pid, stop, out):
    import psutil
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    rss = uss = 0; n = 0
    while not stop.is_set():
        try:
            rss = max(rss, proc.memory_info().rss)
            if n % 4 == 0:
                try: uss = max(uss, proc.memory_full_info().uss)
                except (psutil.AccessDenied, AttributeError): pass
        except psutil.NoSuchProcess:
            break
        n += 1; time.sleep(.05)
    out.update(sampled_max_rss_bytes=rss, sampled_max_uss_bytes=uss or None)


def measured(cmd, env=None):
    stop = threading.Event(); out = {}
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    thread = threading.Thread(target=sample, args=(proc.pid, stop, out)); thread.start()
    stdout, stderr = proc.communicate(); stop.set(); thread.join()
    result = None
    for line in stdout.splitlines():
        if line.startswith('RESULT '): result = json.loads(line[7:])
    return {'returncode': proc.returncode, 'result': result, **out, 'stderr_tail': stderr[-1500:] if proc.returncode else None}


# ----------------------------------------------------------------------------- LEAR synthetic daily job
def run_lear_case(code_root, folder):
    sys.path.insert(0, str(Path(code_root) / 'CONFX2'))
    import numpy as np, pandas as pd, resource
    import runtime, lear_adapter_confx5 as lear  # noqa: E401,E402
    permit = runtime.conf_module('guard').ExecutionPermit('SYNTHETIC_ONLY', 'a' * 64, 'b' * 64, True)
    issue = '2026-06-15'
    days = pd.date_range(pd.Timestamp(issue) - pd.Timedelta(days=1475), pd.Timestamp(issue) - pd.Timedelta(days=1), freq='D')
    rng = np.random.default_rng(7); rows = []
    for region in lear.REGIONS:
        level = 80. + np.cumsum(rng.normal(0, 3, len(days)))
        for i, day in enumerate(days):
            start = pd.Timestamp(day.date().isoformat(), tz='Australia/Brisbane')
            for hour in range(24):
                target = (start + pd.Timedelta(hours=hour)).tz_convert('UTC')
                rows.append((region, target, day.date().isoformat(), float(level[i] + 20 * np.sin(hour / 24 * 2 * np.pi) + rng.normal(0, 8)),
                             target + pd.Timedelta(hours=1, minutes=5)))
    hourly = pd.DataFrame(rows, columns=['region', 'target_time', 'target_day', 'y', 'label_available'])
    out = Path(folder); out.mkdir(parents=True, exist_ok=True)
    predictions, receipts = lear.daily_forecast(hourly, issue, permit, out)
    receipt_bytes = len(json.dumps(receipts, default=str).encode())
    models = sum(p.stat().st_size for p in out.glob('*.npz'))
    hours = [h for w in receipts for h in w['hours']]
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print('RESULT ' + json.dumps({'receipt_json_bytes': receipt_bytes, 'model_and_scaling_npz_bytes': models,
                                  'hour_fits': len(hours), 'lars_convergence_warnings': sum(h['lars_convergence_warnings'] for h in hours),
                                  'cd_nonconverged': sum(not h['cd_converged'] for h in hours), 'peak_rss_bytes': int(peak)}))


# ----------------------------------------------------------------------------- seal sizes
def seal_sizes(folder):
    import numpy as np, pandas as pd
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True); rng = np.random.default_rng(3)
    n = NOTICE_QUERY_ROWS
    origin = pd.date_range(pd.Timestamp('2026-08-01', tz='UTC'), periods=n, freq='s')
    notice = pd.DataFrame({'origin': origin, 'target_time': origin + pd.Timedelta(minutes=5), 'region': np.repeat(['NSW1', 'QLD1', 'SA1', 'TAS1', 'VIC1'], n // 5 + 1)[:n],
                           'horizon': np.tile([5, 10, 15, 20, 25, 30], n // 6 + 1)[:n], 'target_day': origin.strftime('%Y-%m-%d'),
                           'raw_prediction': rng.normal(80, 30, n), 'lower_bound': -1000., 'upper_bound': 17500.,
                           'prediction': rng.normal(80, 30, n).astype('float32')})
    notice.to_parquet(folder / 'notice.parquet', index=False)
    m = 214 * 72
    news_origin = pd.date_range(pd.Timestamp('2026-03-01', tz='UTC'), periods=m, freq='h')
    news = pd.DataFrame({'origin': news_origin, 'target_time': news_origin, 'region': 'NSW1', 'horizon': 0,
                         'target_day': news_origin.strftime('%Y-%m-%d'), 'raw_prediction': rng.normal(80, 30, m), 'prediction': rng.normal(80, 30, m)})
    news.to_parquet(folder / 'news.parquet', index=False)
    return {'synthetic_notice_sealed_parquet_bytes': (folder / 'notice.parquet').stat().st_size,
            'synthetic_news_sealed_parquet_bytes': (folder / 'news.parquet').stat().st_size}


# ----------------------------------------------------------------------------- main
def fit_line(points):
    xs = [p[0] for p in points]; ys = [p[1] for p in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return my - slope * mx, slope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode')
    for name in ('make', 'fit'):
        s = sub.add_parser(name); s.add_argument('--code-root'); s.add_argument('--case'); s.add_argument('--folder')
    s = sub.add_parser('lear'); s.add_argument('--code-root'); s.add_argument('--folder')
    parser.add_argument('--code-root'); parser.add_argument('--scratch'); parser.add_argument('--out')
    args = parser.parse_args()
    if args.mode == 'make': return make_fit_case(args.code_root, json.loads(args.case), args.folder)
    if args.mode == 'fit': return run_fit_case(args.code_root, json.loads(args.case), args.folder)
    if args.mode == 'lear': return run_lear_case(args.code_root, args.folder)
    scratch = Path(args.scratch); scratch.mkdir(parents=True, exist_ok=False)
    files, cache, categories = stat_features()
    shapes = derived_shapes(files)
    import shutil
    free_now = shutil.disk_usage(FEATURES).free
    planned_arrays = sum(s['bytes'] for s in shapes.values())
    remaining_feature_bytes = planned_arrays - sum(s['allocated_bytes'] for s in shapes.values())
    result = {'task': 'CONFX6', 'time_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'host_state_contents_read': False,
              'window_outcomes_read': False, 'production_commands_run': [], 'synthetic_measurements_only': True,
              'features_metadata': {'files': files, 'embedding_cache': cache, 'allocated_by_category': categories,
                                    'derived_unpruned_shapes': shapes, 'free_bytes_now': free_now,
                                    'apparent_array_bytes_when_complete': planned_arrays,
                                    'array_bytes_still_to_allocate': remaining_feature_bytes}}
    result['fit_bank_disk'] = fit_disk_audit(args.code_root, shapes, free_now, remaining_feature_bytes)
    cases = [
        {'name': 'news_L_chen_last_origin_full_shape', 'source': 'news', 'arm': 'L_chen', 'origin': '2026-09-30',
         'shared': shapes['news__shared_numeric.npy']['columns'], 'extras': shapes['news__L_chen__main.extras.npy']['columns']},
        *[{'name': f'notice_L_chen_notice_width_R{r}', 'source': 'notice', 'arm': 'L_chen_notice', 'train_rows': r,
           'query_rows': round(r * NOTICE_QUERY_ROWS / NOTICE_TRAIN_ROWS),
           'shared': shapes['notice__shared_numeric.npy']['columns'], 'extras': shapes['notice__L_chen_notice__main.extras.npy']['columns']}
          for r in (75000, 150000, 225000)],
        {'name': 'notice_L14_narrow_R225000', 'source': 'notice', 'arm': 'L14', 'train_rows': 225000,
         'query_rows': round(225000 * NOTICE_QUERY_ROWS / NOTICE_TRAIN_ROWS),
         'shared': shapes['notice__shared_numeric.npy']['columns'], 'extras': shapes['notice__L14__main.extras.npy']['columns']}]
    measurements = []
    for case in cases:
        folder = scratch / case['name']
        made = subprocess.run([PY, '-B', __file__, 'make', '--code-root', args.code_root, '--case', json.dumps(case), '--folder', str(folder)],
                              capture_output=True, text=True, check=True)
        m = measured([PY, '-B', __file__, 'fit', '--code-root', args.code_root, '--case', json.dumps(case), '--folder', str(folder)])
        m.update(case=case, data=json.loads(made.stdout.strip().splitlines()[-1]))
        measurements.append(m)
        print(json.dumps({'case': case['name'], 'worker_peak_rss': (m['result'] or {}).get('peak_rss_bytes'),
                          'sampled_max_rss': m.get('sampled_max_rss_bytes'), 'state': (m['result'] or {}).get('state')}), flush=True)
    notice_points = [(m['case']['train_rows'], m['result']['peak_rss_bytes']) for m in measurements
                     if m['case']['name'].startswith('notice_L_chen') and m['result'] and m['result'].get('peak_rss_bytes')]
    projection = None
    if len(notice_points) >= 2:
        a, b = fit_line(notice_points)
        projection = {'model': 'worker peak RSS = a + b * training rows (query rows = 0.589 * training rows), 448 columns',
                      'points': notice_points, 'a_bytes': a, 'b_bytes_per_training_row': b,
                      'projected_peak_rss_bytes_at_production': a + b * NOTICE_TRAIN_ROWS,
                      'frozen_job_limit_bytes': 2 * GIB, 'frozen_tree_limit_bytes': 6.6 * GIB}
    result['memory'] = {'measurements': measurements, 'notice_448_column_projection': projection,
                        'frozen_rules': 'COMPUTE_PLAN.md: a job reaching 2 GiB or a task tree reaching 6.6 GiB stops with a resource '
                                        'failure receipt; at 6.0 GiB the news origin throttles to one worker',
                        'metric': 'execution_adapter._worker records ru_maxrss; _fit_wave samples psutil RSS of each worker; both '
                                  'count resident pages of the memory-mapped train/query scratch matrices'}
    lear = measured([PY, '-B', __file__, 'lear', '--code-root', args.code_root, '--folder', str(scratch / 'lear')])
    result['lear'] = {'synthetic_daily_job': lear,
                      'base25_amendment2_measured': 'BASE25/TEST_LOG.md: 365 origins, 211,451 LARS ConvergenceWarnings in 38,857 '
                                                    'hour-fits, worker RSS <= 282 MB; receipts <= 507,085 bytes per origin (200-character '
                                                    'messages); models 192.7 MB / 365 origins',
                      'reservation_per_daily_job_bytes': 2 * 1024 ** 2}
    result['seal'] = seal_sizes(scratch / 'seal')
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + '\n')
    print(json.dumps({'written': args.out}))


if __name__ == '__main__':
    main()
