"""Post-global-freeze fit adapter. Import performs no study I/O or fitting.

Uses CONF's immutable plan and exact learners; a filesystem-backed wall ledger
counts concurrent waves once, includes startup/failure time, and survives resume.
"""
from __future__ import annotations
from contextlib import contextmanager
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import math
import multiprocessing as mp
import os
import time
import uuid

try:
    from .runtime import conf_module, audit, install_audit, atomic_json, read_json, sha256
    from .feature_storage import (bundle_storage_paths, load_feature_rows,
                                  verify_bundle, require_disk_space, DiskSpaceError)
    from .a1_scoring import require_a1_dispositions
    from .anonymous_memory import anonymous_bytes, peak_anonymous_bytes_self, RULE as ANONYMOUS_MEASURE
except ImportError:
    from runtime import conf_module, audit, install_audit, atomic_json, read_json, sha256
    from feature_storage import (bundle_storage_paths, load_feature_rows,
                                 verify_bundle, require_disk_space, DiskSpaceError)
    from a1_scoring import require_a1_dispositions
    from anonymous_memory import anonymous_bytes, peak_anonymous_bytes_self, RULE as ANONYMOUS_MEASURE

BUDGET = 86400.0
JOB_LIMIT = 2 * 1024**3
TREE_LIMIT = 6.6 * 1024**3
THROTTLE = 6.0 * 1024**3
FIT_HEADROOM_BYTES = 3 * 1024**3
# CONFX7 (resource-only memory amendment): the per-fit and task-tree guards measure anonymous (non-file-backed)
# resident memory (anonymous_memory.py); RSS stays recorded. CONFX8 news gets 3.5 GiB; LEAR keeps 2 GiB; serial
# notice fits (6 learner threads, never beside the news pool) may use the machine admission of 6.6 GiB.
# CONFX8: news stop and conservative measured-class projection references only.
NEWS_JOB_LIMIT = 3758096384
NEWS_REFERENCE_ROWS = 131472
NEWS_REFERENCE_PEAKS = {'news_wide': 3300741536, 'news_narrow': 2487864800}
NEWS_REFERENCE_COLUMNS = {'news_wide': 1258, 'news_narrow': 872}
NOTICE_JOB_LIMIT = TREE_LIMIT
WIDE_EXTRA_COLUMNS = 384
MEMORY_RULE = ('CONFX8: ' + ANONYMOUS_MEASURE + '; per-fit limit news 3.5 GiB, LEAR 2 GiB, notice 6.6 GiB; task-tree stop 6.6 GiB, '
               'throttle 6.0 GiB; admission by projected anonymous peak of the task memory class')
# CONFX7 addendum 3 (author instruction, maximum throughput; resource-only): up to 7 single-thread news fits, each
# admitted while the measured anonymous memory, with every running fit reserved at its projected peak, plus its own
# projection stays below 6.6 GiB; LEAR daily jobs stay serial, their 12 window subjobs run on 3 workers.
NEWS_MAX_WORKERS = 7
THROUGHPUT_RULE = ('CONFX7 addendum 3: news pool up to 7 single-thread fits, admission with running fits reserved at '
                   'their projected anonymous peaks below 6.6 GiB; LEAR window subjobs on 3 workers, daily jobs serial')
KEYS = ['origin', 'target_time', 'region', 'horizon']
TERMINAL = {'COMPLETE', 'COMPLETE_WITH_UNAVAILABLE_CONFIGURATIONS', 'UNAVAILABLE_RESOURCE_BUDGET', 'UNAVAILABLE_INPUT_PREREQUISITE',
            'UNAVAILABLE_RESOURCE_FAILURE', 'UNAVAILABLE_MODEL_FAILURE'}


def require(permit, scoring=False):
    return conf_module('guard').require_execution(permit, scoring=scoring)


def job_limit(source):
    """CONFX8 per-fit anonymous-memory limit by source; LEAR and notice unchanged."""
    return NEWS_JOB_LIMIT if source == 'news' else (int(NOTICE_JOB_LIMIT) if source == 'notice' else JOB_LIMIT)


# CONFX5 (CONF-A1 decisions 4 and 7): secondary arms registered before any fit. They join
# existing secondary stages; stage names, order, mandatory flags, primary stages, seeds,
# learner parameters, the 24-hour budget and the whole-stage drop order are unchanged.
A1_NEWS_SECONDARY = ('W2_D',)
A1_NOTICE_SECONDARY = ('NPM',)


def registered_plan():
    """The frozen scheduler.plan() with only the registered CONF-A1 additions."""
    scheduler = conf_module('scheduler')
    stages = []
    for name, tasks, mandatory in scheduler.plan():
        tasks = list(tasks)
        if name == 'report_only_2025_validation':
            tasks += [scheduler.FitTask('news', '2025-01-01', arm, scheduler.SEED, '2025_fixed_validation')
                      for arm in A1_NEWS_SECONDARY]
        elif name == 'secondary_notice':
            tasks += scheduler.notice_tasks(A1_NOTICE_SECONDARY)
        elif name == 'secondary_news':
            tasks = scheduler.news_tasks(scheduler.NEWS_SECONDARY + A1_NEWS_SECONDARY)
        stages.append((name, tasks, mandatory))
    return stages


def digest_json(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def task_id(task):
    return f'{task.task}__{task.origin}__{task.arm}__s{task.seed}__{task.variant}'


@contextmanager
def exclusive_state(state_root):
    """One host scheduler owns the fitting ledger; advisory lock releases on crash."""
    import fcntl
    root = Path(state_root); root.mkdir(parents=True, exist_ok=True)
    with (root / '.fitting.lock').open('a+') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another CONF fitting command owns the host state') from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class WallLedger:
    """Union of non-overlapping fit-wave wall intervals, never worker-second sums.

    A durable heartbeat captures abandoned time. Recovery checks that recorded
    workers are dead before marking the prior wave abandoned. Downtime is not
    model fitting time. Every wave has its own task attempt records as well.
    """
    def __init__(self, state_root, clock=time.time):
        self.root = Path(state_root); self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'FITTING_WALL_LEDGER.json'
        self.clock = clock
        self.data = read_json(self.path) if self.path.exists() else {
            'budget_seconds': BUDGET, 'accounting': 'non-overlapping wave wall time including startup and failed attempts',
            'waves': []}
        if self.data['budget_seconds'] != BUDGET:
            raise RuntimeError('Frozen fitting budget drift')
        import psutil
        for wave in self.data['waves']:
            if wave.get('end') is None:
                for worker in wave.get('workers', []):
                    try:
                        proc = psutil.Process(worker['pid'])
                        if abs(proc.create_time() - worker['create_time']) < .01 and proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                            raise RuntimeError('Recorded CONF worker still alive after interrupted scheduler; cannot resume concurrently')
                    except psutil.NoSuchProcess:
                        pass
                wave['end'] = max(wave['start'], min(self.clock(), wave['heartbeat'] + 1.0))
                wave['state'] = 'ABANDONED_ATTEMPT_CHARGED'
                wave['abandonment_reserve_seconds'] = 1.0
        self.save()

    def save(self):
        atomic_json(self.path, self.data)

    def elapsed(self):
        now = self.clock()
        return sum(max(0., (w['end'] if w.get('end') is not None else now) - w['start']) for w in self.data['waves'])

    def remaining(self):
        return max(0., BUDGET - self.elapsed())

    def begin(self, tasks, stage):
        if any(w.get('end') is None for w in self.data['waves']):
            raise RuntimeError('Overlapping fitting wall accounting')
        if self.remaining() <= 0:
            raise TimeoutError('No new fitting launches at the 24-hour deadline')
        now = self.clock(); ident = uuid.uuid4().hex
        self.data['waves'].append({'id': ident, 'stage': stage, 'tasks': [task_id(t) for t in tasks],
                                   'start': now, 'heartbeat': now, 'end': None, 'workers': [], 'state': 'RUNNING'})
        self.save(); return ident

    def heartbeat(self, ident, workers=()):
        w = next(w for w in self.data['waves'] if w['id'] == ident)
        w['heartbeat'] = self.clock(); w['workers'] = list(workers); self.save()

    def finish(self, ident, state):
        w = next(w for w in self.data['waves'] if w['id'] == ident)
        w['end'] = self.clock(); w['heartbeat'] = w['end']; w['state'] = state; self.save()


def feature_manifest(feature_root, permit):
    require(permit)
    path = Path(feature_root) / 'manifest.json'
    manifest = read_json(path)
    if manifest.get('state') not in ('COMPLETE', 'FEATURE_BANK_COMPLETE'):
        raise RuntimeError('Complete feature bank required before fitting')
    # Opaque identity verification precedes every source read. Workers additionally
    # compare stat identities, avoiding a full multi-GB hash for every daily fit.
    stats = {}
    for item in manifest.get('inputs', []):
        p = Path(item['path'])
        if sha256(p) != item['sha256']:
            raise RuntimeError('Feature input drift: ' + str(p))
        s = p.stat(); stats[str(p)] = [s.st_size, s.st_mtime_ns]
    verified_storage = {}
    verified_panels = {}
    for bundle in manifest['bundles']:
        if bundle.get('state', 'COMPLETE') != 'COMPLETE':
            continue
        verify_bundle(bundle, seen=verified_storage)
        panel_path = Path(bundle['panel_path'])
        expected = bundle['panel_sha256']
        if str(panel_path) in verified_panels:
            if verified_panels[str(panel_path)] != expected:
                raise RuntimeError('Conflicting frozen feature panel identity: ' + str(panel_path))
        else:
            if sha256(panel_path) != expected:
                raise RuntimeError('Frozen feature panel drift: ' + str(panel_path))
            verified_panels[str(panel_path)] = expected
        paths = bundle_storage_paths(bundle) + [Path(bundle['panel_path'])]
        for p in paths:
            p = Path(p)
            if str(p) in stats:
                continue
            s = p.stat(); stats[str(p)] = [s.st_size, s.st_mtime_ns]
        for path_key, hash_key in (('coverage_path', 'coverage_sha256'), ('matched_mask_path', 'matched_mask_sha256')):
            if bundle.get(path_key) and sha256(bundle[path_key]) != bundle[hash_key]:
                raise RuntimeError('Frozen feature coverage/matched-mask drift: ' + bundle[path_key])
    for key in ('W_Bai_selection', 'W2_D_selection', 'notice_derived_dates'):
        if manifest.get(key) and sha256(manifest[key]['path']) != manifest[key]['sha256']:
            raise RuntimeError('Feature preprocessing/derived-date sidecar drift: ' + key)
    return manifest, sha256(path), stats


def find_bundle(manifest, task):
    matches = [b for b in manifest['bundles'] if b['source'] == task.task and b['arm'] == task.arm and
               b.get('variant', 'main') == task.variant]
    if len(matches) != 1:
        raise RuntimeError('Missing or duplicate registered feature bundle: ' + task_id(task))
    return matches[0]


def parameters(task):
    config = read_json(Path(__file__).resolve().parent.parent / 'DESIGN_CONFIG.json')
    params = dict(config['news']['lightgbm'])
    params.update(random_state=int(task.seed), verbosity=-1)
    if task.task == 'notice':
        params.update(objective='regression_l1', n_jobs=6)
    if task.task not in ('notice', 'news'):
        raise ValueError('Unknown LightGBM task')
    return params


def price_cap(target):
    """Byte-for-byte inherited thresholds from run_nw.price_cap, no 2026 update."""
    import numpy as np
    import pandas as pd
    local = pd.to_datetime(target, utc=True).dt.tz_convert('Australia/Brisbane')
    return np.select([local < pd.Timestamp('2022-07-01', tz='Australia/Brisbane'),
                      local < pd.Timestamp('2023-07-01', tz='Australia/Brisbane'),
                      local < pd.Timestamp('2024-07-01', tz='Australia/Brisbane')],
                     [15000., 15500., 16600.], 17500.)


def select_rows(panel, task, bundle):
    """Frozen complete-day strictly-before news / fixed-bank notice membership."""
    import numpy as np
    import pandas as pd
    day = panel['target_day'].astype(str).to_numpy()
    clocks = pd.to_datetime(panel['label_available'], utc=True, errors='coerce')
    if task.task == 'notice':
        n = int(bundle['train_rows'])
        train, query = np.arange(n), np.arange(n, len(panel))
        earliest = pd.Timestamp('2026-07-31 23:30', tz='Australia/Brisbane').tz_convert('UTC')
        if n <= 0 or not clocks.iloc[train].notna().all() or not (clocks.iloc[train] < earliest).all():
            raise ValueError('B6 strict notice train-label clock gate failed')
        if np.any(day[train] < '2021-10-01') or np.any(day[train] > '2023-12-31'):
            raise ValueError('Notice train membership exceeded RF2 frozen domain')
        if not np.isin(panel['weight'].to_numpy()[train], [1., 50.]).all():
            raise ValueError('Notice original replay weights 1/50 changed')
        if not np.all(panel['weight'].to_numpy()[query] == 1):
            raise ValueError('Notice unit evaluation weight changed')
    else:
        origin = pd.Timestamp(task.origin, tz='Australia/Brisbane').tz_convert('UTC')
        legal = clocks.notna().to_numpy() & (clocks < origin).to_numpy() & np.isfinite(panel['y'].to_numpy())
        support = pd.DataFrame({'day': day, 'legal': legal}).groupby('day', sort=True)['legal'].agg(['size', 'sum'])
        eligible = support.index[(support['size'] == 72) & (support['sum'] == 72) &
                                  (support.index >= '2021-10-01') & (support.index < task.origin)]
        train = np.flatnonzero(np.isin(day, eligible))
        query = np.flatnonzero((day >= '2025-01-01') & (day <= '2025-12-31')) if task.variant == '2025_fixed_validation' else np.flatnonzero(day == task.origin)
        expected = 365 * 72 if task.variant == '2025_fixed_validation' else 72
        if len(query) != expected:
            raise ValueError('Complete registered news query key grid missing')
    if len(train) == 0 or len(query) == 0 or not np.isfinite(panel['y'].to_numpy()[train]).all():
        raise ValueError('Empty or nonfinite training labels')
    return train, query, clocks


def _worker(payload):
    """Fresh spawned worker, float32 bounded/memmapped X, no scoring."""
    task, bundle, feature_sha, stats, permit, output_root = payload
    install_audit('execution_worker')
    require(permit)
    t = time.monotonic(); out = Path(output_root); ident = task_id(task)
    out.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('MPLCONFIGDIR', str(out / '.matplotlib_cache'))
    import resource
    import sys
    def peak():
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(r if sys.platform == 'darwin' else r * 1024)
    rec = {'task': asdict(task), 'task_id': ident, 'state': 'FAILED', 'feature_manifest_sha256': feature_sha,
           'design_freeze_sha256': permit.design_freeze_sha256,
           'completed_input_manifest_sha256': permit.completed_input_manifest_sha256}
    try:
        import numpy as np
        import pandas as pd
        import lightgbm as lgb
        for path in bundle_storage_paths(bundle) + [Path(bundle['panel_path'])]:
            s = Path(path).stat()
            identity_key = str(Path(path).resolve()) if str(Path(path).resolve()) in stats else str(Path(path))
            if [s.st_size, s.st_mtime_ns] != stats[identity_key]:
                raise RuntimeError('Source changed after admission identity check: ' + str(path))
            audit(path, 'authorized_postfreeze_read', 'registered fit adapter')
        needed = KEYS + ['target_day', 'y', 'label_available'] + (['anchor', 'weight'] if task.task == 'notice' else [])
        panel = pd.read_parquet(bundle['panel_path'], columns=needed)
        if panel.duplicated(KEYS).any():
            raise ValueError('Duplicate registered panel keys')
        target_clock = pd.to_datetime(panel['target_time'], utc=True)
        issue_clock = pd.to_datetime(panel['origin'], utc=True)
        expected_target = issue_clock + pd.to_timedelta(panel['horizon'], unit='h' if task.task == 'news' else 'm')
        if not np.all(target_clock.to_numpy(dtype='datetime64[ns]') == expected_target.to_numpy(dtype='datetime64[ns]')):
            raise ValueError('Frozen issue/horizon/target mapping changed')
        matrix = None
        if bundle.get('matrix', {}).get('path'):
            # Retain the old synthetic/archived-layout path for compatibility.
            matrix = np.load(bundle['matrix']['path'], mmap_mode='r', allow_pickle=False)
        shape = tuple(bundle['matrix']['shape'])
        if shape != (len(panel), len(bundle['columns'])) or (matrix is not None and
                (matrix.dtype != np.float32 or matrix.shape != shape)):
            raise ValueError('Float32 frozen feature order/shape drift')
        train, query, clocks = select_rows(panel, task, bundle)
        # Concatenate shared/extras only for admitted train/query rows. Chunked
        # float32 copies preserve frozen bits/order without a full bank copy.
        train_temp = out / (ident + '.train.npy')
        query_temp = out / (ident + '.query.npy')
        def gather(indices, path):
            if matrix is not None and np.array_equal(indices, np.arange(indices[0], indices[-1] + 1)):
                return matrix[indices[0]:indices[-1] + 1]
            dest = np.lib.format.open_memmap(path, mode='w+', dtype='float32', shape=(len(indices), shape[1]))
            for offset in range(0, len(indices), 4096):
                block = indices[offset:offset + 4096]
                dest[offset:offset + len(block)] = load_feature_rows(bundle, block)
            dest.flush(); return dest
        target = panel['y'].to_numpy(dtype='float64')[train]
        if task.task == 'notice':
            target = target - panel['anchor'].to_numpy(dtype='float64')[train]
            if not np.isfinite(target).all():
                raise ValueError('Nonfinite notice residual or legal anchor')
            weights = panel['weight'].to_numpy(dtype='float32')[train]
        else:
            weights = None
        params = parameters(task)
        rec.update(train_rows=len(train), prediction_rows=len(query), features=len(bundle['columns']),
                   feature_order=bundle['columns'], pruned_names=bundle.get('pruned_names', []),
                   train_indices_sha256=hashlib.sha256(train.astype('<i8').tobytes()).hexdigest(),
                   training_label_clock_max=clocks.iloc[train].max().isoformat(),
                   train_cutoff=task.origin, params=params)
        # CONFX7: keep only what the prediction needs and release the panel before the fit; the query
        # matrix is assembled only after the model is saved and the training matrix is released.
        result = panel.iloc[query][KEYS + ['target_day']].copy()
        if task.task == 'notice':
            query_anchor = panel['anchor'].to_numpy(dtype='float64')[query]
            query_target_time = panel.iloc[query]['target_time']
        del panel, clocks, target_clock, issue_clock, expected_target
        x = gather(train, train_temp)
        model = lgb.LGBMRegressor(**params).fit(x, target, sample_weight=weights, feature_name=bundle['columns'])
        model_path = out / (ident + '.model.txt'); model.booster_.save_model(str(model_path))
        if isinstance(x, np.memmap) and Path(x.filename) == train_temp and not x._mmap.closed:
            x.flush(); x._mmap.close()
        del x
        if train_temp.exists(): train_temp.unlink()
        q = gather(query, query_temp)
        raw = np.asarray(model.booster_.predict(q, num_threads=params['n_jobs']), dtype='float64')
        if task.task == 'notice':
            raw += query_anchor
            lower = np.full(len(query), -1000.); upper = price_cap(query_target_time)
            prediction = np.clip(raw, lower, upper).astype('float32')
            result['raw_prediction'], result['lower_bound'], result['upper_bound'] = raw, lower, upper
        else:
            prediction = raw
            result['raw_prediction'] = raw
        if not np.isfinite(prediction).all():
            raise ValueError('Nonfinite registered prediction')
        result['prediction'] = prediction
        prediction_path = out / (ident + '.predictions.parquet')
        result.to_parquet(prediction_path, index=False)
        rec.update(state='COMPLETE', model_path=str(model_path), model_sha256=sha256(model_path),
                   prediction_path=str(prediction_path), prediction_sha256=sha256(prediction_path),
                   prediction_key_sha256=hashlib.sha256(pd.util.hash_pandas_object(result[KEYS], index=False).to_numpy().tobytes()).hexdigest(),
                   lightgbm_version=lgb.__version__, numpy_version=np.__version__, pandas_version=pd.__version__)
    except Exception as exc:
        rec['error'] = repr(exc)
    finally:
        # A failed fit must not retain an assembled copy of the shared block.
        for name in ('x', 'q'):
            value = locals().get(name)
            if isinstance(value, np.memmap) and Path(value.filename) in (
                    out / (ident + '.train.npy'), out / (ident + '.query.npy')) and not value._mmap.closed:
                value.flush(); value._mmap.close()
        for suffix in ('.train.npy', '.query.npy'):
            path = out / (ident + suffix)
            if path.exists(): path.unlink()
    rec['runtime_seconds'], rec['peak_rss_bytes'] = time.monotonic() - t, peak()
    return _apply_job_memory_rule(rec, task.task)


def _apply_job_memory_rule(rec, source):
    """CONFX7: record the worker's own anonymous peak beside RSS; a true overrun fails the fit."""
    anonymous = peak_anonymous_bytes_self()
    rec['peak_anonymous_bytes'] = int(anonymous if anonymous is not None else rec.get('peak_rss_bytes', 0))
    rec['job_anonymous_limit_bytes'] = job_limit(source); rec['memory_rule'] = MEMORY_RULE
    if rec['peak_anonymous_bytes'] >= rec['job_anonymous_limit_bytes']:
        rec['state'] = 'FAILED_RESOURCE'
        rec['error'] = 'Per-fit anonymous-memory limit reached (' + str(rec['job_anonymous_limit_bytes']) + ' bytes)'
    return rec


def _lear_subjob_worker(payload):
    """CONFX7 addendum 3: one LEAR window subjob (lear_parallel), plus the anonymous-memory receipt fields."""
    try:
        from .lear_parallel import window_subjob
    except ImportError:
        from lear_parallel import window_subjob
    return _apply_job_memory_rule(window_subjob(payload), 'lear')


def _receipt_path(root, task):
    return Path(root) / 'fits' / 'receipts' / (task_id(task) + '.json')


def reusable(root, task, feature_sha, permit):
    p = _receipt_path(root, task)
    if not p.exists(): return None
    rec = read_json(p)
    if rec['state'] != 'COMPLETE': return None
    if rec['task'] != asdict(task) or rec['feature_manifest_sha256'] != feature_sha or rec['design_freeze_sha256'] != permit.design_freeze_sha256 or rec['completed_input_manifest_sha256'] != permit.completed_input_manifest_sha256:
        raise RuntimeError('Resume receipt identity mismatch: ' + task_id(task))
    for what in ('model', 'prediction'):
        if what == 'model' and task.task == 'lear': continue
        if sha256(rec[what + '_path']) != rec[what + '_sha256']:
            raise RuntimeError('Resume artifact changed: ' + task_id(task))
    return rec


def fit_disk_plan(tasks, manifest):
    """Metadata-only reserve for remaining artifacts and concurrent scratch.

    Tree/model and Parquet reservations deliberately exceed their fixed numeric
    payloads; they do not depend on labels, predictions, or observed fit losses.
    All remaining persistent outputs are reserved, while scratch is temporary
    and is bounded by the largest admitted simultaneous workers.
    """
    tasks = list(tasks)
    if not tasks:
        return {'planned_bytes': 0, 'persistent_output_bytes': 0,
                'peak_scratch_bytes': 0, 'remaining_jobs': 0}
    source = tasks[0].task
    if any(t.task != source for t in tasks):
        raise ValueError('Disk planning requires one registered fit source')
    persistent = 0; scratch = []
    for task in tasks:
        if source == 'lear':
            # Twelve model/scaling NPZ pairs, 288 hourly receipts, 72 forecasts.
            persistent += 2 * 1024**2
            scratch.append(0)
            continue
        lookup = task if task.variant != '2025_fixed_validation' else conf_module('scheduler').FitTask(
            'news', task.origin, task.arm, task.seed, 'main')
        bundle = find_bundle(manifest, lookup)
        rows, columns = map(int, bundle['matrix']['shape'])
        if columns != len(bundle['columns']) or rows <= 0:
            raise ValueError('Frozen feature shape unavailable for fit disk plan')
        prediction_rows = (rows - int(bundle['train_rows']) if source == 'notice' else
                           (365 * 72 if task.variant == '2025_fixed_validation' else 72))
        if prediction_rows < 0:
            raise ValueError('Frozen notice row membership changed')
        params = parameters(task)
        # One KiB per possible leaf covers text serialization of every tree
        # node; names/header and prediction/receipt overhead have separate caps.
        model_bytes = 64 * 1024 + columns * 256 + int(params['n_estimators']) * int(params['num_leaves']) * 1024
        prediction_bytes = 64 * 1024 + prediction_rows * 192
        receipt_bytes = 64 * 1024 + columns * 256
        persistent += model_bytes + prediction_bytes + receipt_bytes
        scratch.append(rows * columns * 4 + 256)
    workers = NEWS_MAX_WORKERS if source == 'news' else 1      # CONFX7 addendum 3: up to 7 concurrent news fits
    peak_scratch = sum(sorted(scratch, reverse=True)[:workers])
    return {'planned_bytes': persistent + peak_scratch,
            'persistent_output_bytes': persistent, 'peak_scratch_bytes': peak_scratch,
            'remaining_jobs': len(tasks), 'maximum_concurrent_workers': workers,
            'basis': 'frozen shape plus fixed learner/artifact byte reservations; no outcome reads'}


def guard_fit_bank(tasks, manifest, state_root, stage):
    plan = fit_disk_plan(tasks, manifest)
    require_disk_space(state_root, plan['planned_bytes'], FIT_HEADROOM_BYTES, stage)
    return plan


def _admits(measured, base, reserved, incoming):
    """CONFX7 addendum 3 admission: the larger of the measured task tree (plus fits admitted in this pass) and the
    parent with every running fit reserved at its projected peak, plus the incoming projection, below 6.6 GiB."""
    return max(measured, base + reserved) + incoming < TREE_LIMIT


def _projection_for(projected, task):
    """CONFX7: `projected` is one byte count or a mapping task_id -> projected anonymous bytes."""
    if isinstance(projected, dict):
        return int(projected.get(task_id(task), max(projected.values()) if projected else 512 * 1024**2))
    return int(projected)


def _fit_wave(tasks, stage, manifest, feature_sha, stats, permit, state_root, ledger, projected):
    """Fresh spawned workers, live anonymous-memory admission with reserved projections (CONFX7), barrier,
    deadline drains. News: up to NEWS_MAX_WORKERS single-thread fits; notices serial; LEAR: one daily job, its 12
    window subjobs on lear_parallel.SUBJOB_WORKERS persistent workers (CONFX7 addendum 3)."""
    import psutil
    scheduler = conf_module('scheduler')
    tasks = list(tasks)
    if not tasks: return []
    # Insufficient disk is an execution stop before ledger charge or launches.
    guard_fit_bank(tasks, manifest, state_root, stage + '__wave')
    source = tasks[0].task
    if source == 'lear':
        # CONFX5 template convergence rule inside the CONFX7 window subjobs (lear_adapter.py stays byte-identical).
        try:
            from . import lear_parallel
        except ImportError:
            import lear_parallel
        units = [unit for task in tasks for unit in lear_parallel.subjob_units(task)]
        max_workers = lear_parallel.SUBJOB_WORKERS
        # Persistent workers within the daily job; one BLAS thread set before any adapter import (frozen worker_init).
        pool_options = dict(initializer=scheduler.worker_init)
    else:
        units = list(tasks)
        max_workers = NEWS_MAX_WORKERS if source == 'news' else 1
        pool_options = dict(initializer=scheduler.worker_init if source != 'notice' else None, max_tasks_per_child=1)
    unit_task = (lambda unit: unit[0]) if source == 'lear' else (lambda unit: unit)
    ident = ledger.begin(tasks, stage); start = time.monotonic()
    deadline = time.monotonic() + ledger.remaining()
    records, waiting, active = [], list(units), {}
    reserved, launch_counts, started_tasks, attempts, subresults = {}, {}, {}, {}, {}
    throttled = False; failure = None; heartbeat_at = 0.; max_concurrent = 0
    peak_tree = 0; peak_worker = 0; peak_tree_anon = 0; peak_worker_anon = 0
    limit = job_limit(source)
    worker = _worker if source != 'lear' else _lear_subjob_worker
    ctx = mp.get_context('spawn')
    pool = ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx, **pool_options)

    def stamp(rec, concurrent):
        rec.update(wave_id=ident, wave_peak_task_tree_rss_bytes=peak_tree, wave_peak_owned_worker_rss_bytes=peak_worker,
                   wave_peak_task_tree_anonymous_bytes=peak_tree_anon,
                   wave_peak_owned_worker_anonymous_bytes=peak_worker_anon, memory_rule=MEMORY_RULE,
                   throughput_rule=THROUGHPUT_RULE, pool_max_workers=max_workers, concurrent_fits_at_launch=concurrent,
                   wave_max_concurrent_fits_so_far=max_concurrent,
                   feature_manifest_sha256=feature_sha, design_freeze_sha256=permit.design_freeze_sha256,
                   completed_input_manifest_sha256=permit.completed_input_manifest_sha256)
        return rec

    def settle(task, rec, attempt_path, concurrent):
        nonlocal failure
        stamp(rec, concurrent); rec['attempt_path'] = str(attempt_path)
        atomic_json(attempt_path, rec)
        atomic_json(_receipt_path(state_root, task), rec)
        records.append(rec)
        if rec['state'] != 'COMPLETE':
            failure = RuntimeError('Registered fit failed: ' + task_id(task))
            waiting.clear()

    try:
        while waiting or active:
            # Every estimator is a known spawned pool worker; enumerate only
            # these owned PIDs, as frozen scheduler.task_tree_rss does. Full-host
            # process enumeration is unnecessary and restricted on some hosts.
            children = [psutil.Process(proc.pid) for proc in (pool._processes or {}).values() if proc.pid]
            from multiprocessing import resource_tracker
            tracker_pid = resource_tracker._resource_tracker._pid
            if tracker_pid and tracker_pid not in {p.pid for p in children}:
                try: children.append(psutil.Process(tracker_pid))
                except psutil.NoSuchProcess: pass
            rss = psutil.Process().memory_info().rss
            anon = anonymous_bytes(os.getpid())
            anon = rss if anon is None else anon
            base = anon                                      # parent and resource tracker, measured now
            workers = []
            for child in children:
                try:
                    r = child.memory_info().rss; rss += r
                    a = anonymous_bytes(child.pid)
                    a = r if a is None else a              # unreadable anonymous measure: conservative RSS
                    anon += a
                    if child.pid == tracker_pid:
                        base += a
                    peak_worker = max(peak_worker, r); peak_worker_anon = max(peak_worker_anon, a)
                    workers.append({'pid': child.pid, 'create_time': child.create_time(), 'rss': r, 'anonymous': a})
                    if a >= limit:
                        failure = MemoryError('Live worker reached its anonymous-memory limit of ' + str(limit) + ' bytes'); break
                except psutil.NoSuchProcess:
                    pass
            if failure is None and anon >= TREE_LIMIT: failure = MemoryError('Live task tree reached 6.6 GiB anonymous memory')
            peak_tree = max(peak_tree, rss); peak_tree_anon = max(peak_tree_anon, anon)
            if isinstance(failure, MemoryError):
                for proc in (pool._processes or {}).values():
                    if proc.is_alive(): proc.terminate()
                break
            if anon >= THROTTLE: throttled = True
            effective = 1 if throttled else (NEWS_MAX_WORKERS if source == 'news' else max_workers)
            if time.monotonic() - heartbeat_at > 1:
                ledger.heartbeat(ident, workers); heartbeat_at = time.monotonic()
            if time.monotonic() >= deadline:
                # No new fit launches; already admitted fits (and the window subjobs of a started LEAR daily job) drain.
                kept = [u for u in waiting if source == 'lear' and task_id(unit_task(u)) in started_tasks]
                if len(kept) < len(waiting): failure = failure or TimeoutError('24-hour deadline: unlaunched tasks remain')
                waiting[:] = kept
            measured_plus = anon
            while waiting and len(active) < effective:
                unit = waiting[0]; task = unit_task(unit)
                if time.monotonic() >= deadline and task_id(task) not in started_tasks: break
                incoming = _projection_for(projected, task)
                if not _admits(measured_plus, base, sum(reserved.values()), incoming):
                    if active: break
                    raise MemoryError('Projected incoming worker exceeds 6.6 GiB anonymous admission')
                waiting.pop(0)
                if source == 'lear':
                    payload = (task, unit[1], unit[2], permit, str(Path(state_root) / 'fits' / 'artifacts'),
                               manifest['hourly_path'], manifest['hourly_sha256'])
                else:
                    lookup = task
                    if source == 'news' and task.variant == '2025_fixed_validation':
                        lookup = scheduler.FitTask('news', task.origin, task.arm, task.seed, 'main')
                    bundle = find_bundle(manifest, lookup)
                    if source == 'news' and task.variant == '2025_fixed_validation':
                        # Fixed validation shares the unchanged main preprocessing.
                        bundle = find_bundle(manifest, scheduler.FitTask('news', task.origin, task.arm, task.seed, 'main'))
                    payload = (task, bundle, feature_sha, stats, permit, str(Path(state_root) / 'fits' / 'artifacts'))
                key = task_id(task)
                if key not in started_tasks:
                    started_tasks[key] = time.monotonic()
                    attempts[key] = Path(state_root) / 'fits' / 'attempts' / (key + '__' + uuid.uuid4().hex + '.json')
                    atomic_json(attempts[key], {'state': 'LAUNCHED', 'task': asdict(task), 'wave_id': ident,
                                                'started_wall': time.time(), 'feature_manifest_sha256': feature_sha})
                future = pool.submit(worker, payload)
                active[future] = (unit, attempts[key])
                reserved[future] = incoming
                launch_counts[future] = len(active); max_concurrent = max(max_concurrent, len(active))
                known = []
                for proc in (pool._processes or {}).values():
                    try:
                        process = psutil.Process(proc.pid)
                        known.append({'pid': proc.pid, 'create_time': process.create_time(),
                                      'rss': process.memory_info().rss, 'anonymous': anonymous_bytes(proc.pid)})
                    except psutil.NoSuchProcess:
                        pass
                # Persist process identities at launch, before waiting for a
                # periodic heartbeat, so orphaned fits cannot overlap a resume.
                ledger.heartbeat(ident, known)
                measured_plus += incoming
            if not active:
                if failure: break
                if waiting: raise MemoryError('No registered task can be admitted')
                break
            finished, _ = wait(active, timeout=.2, return_when=FIRST_COMPLETED)
            for future in finished:
                unit, attempt_path = active.pop(future); reserved.pop(future, None)
                concurrent = launch_counts.pop(future)
                task = unit_task(unit)
                if source == 'lear':
                    try:
                        sub = future.result()
                    except BaseException as exc:
                        sub = {'task_id': task_id(task), 'region': unit[1], 'window_days': unit[2], 'state': 'FAILED',
                               'error': repr(exc), 'peak_rss_bytes': 0, 'peak_anonymous_bytes': 0}
                    subresults.setdefault(task_id(task), {})[(unit[1], unit[2])] = sub
                    if sub['state'] != 'COMPLETE':
                        failure = failure or RuntimeError('Registered LEAR window subjob failed: ' + task_id(task))
                        waiting[:] = [u for u in waiting if unit_task(u) != task]
                    pending = [u for u in waiting if unit_task(u) == task] + \
                              [u for u, _ in active.values() if unit_task(u) == task]
                    if not pending:
                        order = [(u[1], u[2]) for u in lear_parallel.subjob_units(task)]
                        results = [subresults[task_id(task)].get(o, {'region': o[0], 'window_days': o[1], 'state': 'NOT_RUN',
                                                                      'error': 'not launched'}) for o in order]
                        rec = lear_parallel.assemble_daily_job(task, feature_sha, permit,
                                                               str(Path(state_root) / 'fits' / 'artifacts'), results,
                                                               time.monotonic() - started_tasks[task_id(task)], max_workers)
                        subs = [r for r in results if r.get('state') != 'NOT_RUN']
                        rec.update(peak_anonymous_bytes=max([int(r.get('peak_anonymous_bytes') or 0) for r in subs] or [0]),
                                   job_anonymous_limit_bytes=job_limit('lear'),
                                   subjob_states=[r.get('state') for r in results])
                        if rec['state'] == 'COMPLETE' and any(r.get('state') != 'COMPLETE' for r in results):
                            rec['state'] = 'FAILED'
                        settle(task, rec, attempt_path, concurrent)
                else:
                    try:
                        rec = future.result()
                    except BaseException as exc:
                        rec = {'state': 'FAILED', 'task': asdict(task), 'task_id': task_id(task), 'error': repr(exc),
                               'runtime_seconds': time.monotonic() - start, 'peak_rss_bytes': 0, 'peak_anonymous_bytes': 0,
                               'feature_manifest_sha256': feature_sha}
                    settle(task, rec, attempt_path, concurrent)
            if failure and not active: break
        if failure:
            abandoned = {}
            for unit, attempt_path in active.values():
                abandoned.setdefault(task_id(unit_task(unit)), (unit_task(unit), attempt_path))
            for task, attempt_path in abandoned.values():
                rec = {'state': 'FAILED_ABANDONED_RESOURCE', 'task': asdict(task), 'wave_id': ident,
                       'error': repr(failure), 'runtime_seconds': time.monotonic() - start,
                       'wave_peak_task_tree_rss_bytes': peak_tree, 'wave_peak_owned_worker_rss_bytes': peak_worker,
                       'wave_peak_task_tree_anonymous_bytes': peak_tree_anon,
                       'wave_peak_owned_worker_anonymous_bytes': peak_worker_anon, 'memory_rule': MEMORY_RULE,
                       'throughput_rule': THROUGHPUT_RULE, 'pool_max_workers': max_workers,
                       'wave_max_concurrent_fits_so_far': max_concurrent,
                       'feature_manifest_sha256': feature_sha, 'design_freeze_sha256': permit.design_freeze_sha256,
                       'completed_input_manifest_sha256': permit.completed_input_manifest_sha256}
                atomic_json(attempt_path, rec); atomic_json(_receipt_path(state_root, task), rec)
            raise failure
        return records
    except BaseException as exc:
        failure = exc
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        ledger.finish(ident, 'COMPLETE' if failure is None else 'FAILED_ATTEMPTS_CHARGED')


def _all_complete_receipts(state_root):
    return [read_json(p) for p in (Path(state_root) / 'fits' / 'receipts').glob('*.json') if read_json(p).get('state') == 'COMPLETE']


def _resource_records(state_root, feature_sha, permit):
    """Current-identity runtime/RSS receipts, including every retained attempt.

    Admission uses maxima, not sums; the wall ledger owns time accounting. A
    failed attempt can increase the conservative estimate but cannot establish
    successful completion, especially the complete 288-pair LEAR pilot.
    """
    records = []
    root = Path(state_root) / 'fits'
    for directory in ('receipts', 'attempts'):
        for path in (root / directory).glob('*.json'):
            r = read_json(path)
            if r.get('feature_manifest_sha256') != feature_sha or r.get('design_freeze_sha256') != permit.design_freeze_sha256 or r.get('completed_input_manifest_sha256') != permit.completed_input_manifest_sha256:
                continue
            duration = r.get('runtime_seconds')
            if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration < 0:
                continue
            if r.get('task', {}).get('task') not in ('news', 'notice', 'lear'):
                continue
            peak = r.get('peak_rss_bytes', r.get('wave_peak_owned_worker_rss_bytes', 0))
            if not isinstance(peak, (int, float)) or not math.isfinite(peak) or peak < 0:
                continue
            observed = r.get('wave_peak_owned_worker_rss_bytes', 0)
            if r.get('state') != 'COMPLETE' and isinstance(observed, (int, float)) and math.isfinite(observed) and observed >= 0:
                peak = max(peak, observed)
            # CONFX7: anonymous peaks drive admission; a record without one counts with its RSS (conservative).
            anonymous = r.get('peak_anonymous_bytes', peak)
            if not isinstance(anonymous, (int, float)) or not math.isfinite(anonymous) or anonymous < 0:
                anonymous = peak
            observed = r.get('wave_peak_owned_worker_anonymous_bytes', 0)
            if r.get('state') != 'COMPLETE' and isinstance(observed, (int, float)) and math.isfinite(observed) and observed >= 0:
                anonymous = max(anonymous, observed)
            records.append(dict(r, peak_rss_bytes=int(peak), peak_anonymous_bytes=int(anonymous)))
    return records


def _memory_class(task, manifest):
    """CONFX7 admission class: news wide (registered extras >= 384 columns), news narrow, notice or LEAR."""
    if task.task in ('notice', 'lear'):
        return task.task
    lookup = task if task.variant != '2025_fixed_validation' else conf_module('scheduler').FitTask(
        'news', task.origin, task.arm, task.seed, 'main')
    try:
        bundle = find_bundle(manifest, lookup)
    except RuntimeError:
        return 'news_narrow'
    return 'news_wide' if len(bundle.get('extra_columns', [])) >= WIDE_EXTRA_COLUMNS else 'news_narrow'


def _record_class(record, manifest):
    try:
        return _memory_class(conf_module('scheduler').FitTask(**record['task']), manifest)
    except (TypeError, KeyError):
        return None


def _projected_anonymous(task, records, manifest):
    """CONFX7: 1.08 x the largest anonymous peak of the task's memory class x the unchanged shape-growth bound."""
    same = [r for r in records if r.get('task', {}).get('task') == task.task]
    klass = _memory_class(task, manifest)
    relevant = [r for r in same if _record_class(r, manifest) == klass] or same
    floor = 0
    if task.task == 'news':
        lookup = task if task.variant != '2025_fixed_validation' else conf_module('scheduler').FitTask(
            'news', task.origin, task.arm, task.seed, 'main')
        b = find_bundle(manifest, lookup)
        cells = b['matrix']['shape'][0] * len(b['columns'])
        reference_cells = NEWS_REFERENCE_ROWS * NEWS_REFERENCE_COLUMNS[klass]
        floor = int(NEWS_REFERENCE_PEAKS[klass] * (1.08 * max(1., cells / reference_cells)))
    if not relevant:
        return floor or 512 * 1024**2
    growth = 1.08
    if task.task in ('news', 'notice'):
        shaped = [r for r in relevant if r.get('train_rows', 0) > 0 and r.get('features', 0) > 0 and r.get('prediction_rows', 0) > 0]
        if shaped:
            max_elements = max((r['train_rows'] + r['prediction_rows']) * r['features'] for r in shaped)
            lookup = task if task.variant != '2025_fixed_validation' else conf_module('scheduler').FitTask(
                'news', task.origin, task.arm, task.seed, 'main')
            b = find_bundle(manifest, lookup)
            growth *= max(1., b['matrix']['shape'][0] * len(b['columns']) / max_elements)
    return max(floor, int(max(r.get('peak_anonymous_bytes', r.get('peak_rss_bytes', 0)) for r in relevant) * growth))


def _conservative(tasks, records, manifest):
    """Only runtime, rows and matrix dimensions enter admission; no predictions."""
    if tasks[0].task == 'lear':
        relevant = [r for r in records if r['task']['task'] == 'lear']
        complete_pilot = [r for r in relevant if r.get('state') == 'COMPLETE' and r.get('component_pairs') == 288]
        return None if not complete_pilot else conf_module('scheduler').lear_daily_admission_estimate(max(r['runtime_seconds'] for r in relevant))
    relevant = [r for r in records if r['task']['task'] == tasks[0].task]
    if not relevant: return None
    largest = max(r['runtime_seconds'] for r in relevant)
    shape_support = [r for r in relevant if r.get('train_rows', 0) > 0 and r.get('features', 0) > 0]
    if not shape_support: return None
    seen_rows = max(r['train_rows'] for r in shape_support); seen_cols = max(r['features'] for r in shape_support)
    dimensions = []
    for task in tasks:
        target = task
        if task.variant == '2025_fixed_validation':
            target = conf_module('scheduler').FitTask(task.task, task.origin, task.arm, task.seed, 'main')
        b = find_bundle(manifest, target)
        if b.get('state', 'COMPLETE') != 'COMPLETE': return None
        dimensions.append(len(b['columns']))
    # Future expanding-row growth is metadata only, bounded by the declared bank.
    bank_rows = max(find_bundle(manifest, tasks[0] if tasks[0].variant != '2025_fixed_validation' else
                               conf_module('scheduler').FitTask(tasks[0].task, tasks[0].origin, tasks[0].arm, tasks[0].seed, 'main'))['matrix']['shape'][0], seen_rows)
    row_factor = max(1., bank_rows / max(1, seen_rows)) if tasks[0].task == 'news' else 1.
    return 1.25 * largest * row_factor * max(1., max(dimensions) / max(1, seen_cols))


def _stage_path(root, name):
    return Path(root) / 'stages' / (name + '.json')


def _run_stage(name, tasks, mandatory, manifest, feature_sha, stats, permit, state_root, ledger):
    old = _stage_path(state_root, name)
    if old.exists():
        disposition = read_json(old)
        if disposition['state'] in TERMINAL:
            if disposition['state'] in ('COMPLETE', 'COMPLETE_WITH_UNAVAILABLE_CONFIGURATIONS'):
                eligible = set(disposition.get('eligible_tasks', disposition['registered_tasks']))
                for task in tasks:
                    if task_id(task) not in eligible: continue
                    if reusable(state_root, task, feature_sha, permit) is None:
                        raise RuntimeError('Complete stage lacks exact reusable fit: ' + task_id(task))
            return disposition
    missing = [t for t in tasks if reusable(state_root, t, feature_sha, permit) is None]
    unavailable = []
    for t in tasks:
        if t.task == 'lear': continue
        lookup = t if t.variant != '2025_fixed_validation' else conf_module('scheduler').FitTask('news', t.origin, t.arm, t.seed, 'main')
        b = find_bundle(manifest, lookup)
        if b.get('state', 'COMPLETE') != 'COMPLETE': unavailable.append({'task_id': task_id(t), 'state': b['state'], 'reason': b.get('reason')})
    rec = {'stage': name, 'mandatory': mandatory, 'registered_tasks': [task_id(t) for t in tasks],
           'feature_manifest_sha256': feature_sha, 'budget_before_seconds': ledger.remaining()}
    if unavailable:
        if mandatory: raise RuntimeError('Primary feature prerequisite unavailable: ' + repr(unavailable))
        # The protocol names source-prerequisite unavailability per configuration
        # (e.g. empty W_Bai/NO_VALID_PERMUTATION), without dropping unrelated arms.
        # The RESOURCE admission/drop unit remains the entire runnable stage.
        unavail_ids = {d['task_id'] for d in unavailable}
        missing = [t for t in missing if task_id(t) not in unavail_ids]
        runnable = [t for t in tasks if task_id(t) not in unavail_ids]
        rec.update(unavailable_configurations=unavailable, eligible_tasks=[task_id(t) for t in runnable])
        if not runnable:
            rec.update(state='UNAVAILABLE_INPUT_PREREQUISITE')
            atomic_json(old, rec); return rec
    else:
        runnable = tasks
        rec['eligible_tasks'] = [task_id(t) for t in runnable]
    records = _resource_records(state_root, feature_sha, permit)
    estimate = _conservative(runnable, records, manifest)
    # Counted pilot rows are reusable, but the admission unit stays the registered
    # whole stage. Charge only remaining rounds after the counted pilot completion.
    needed = None if estimate is None else conf_module('scheduler').projected_stage_seconds(missing, estimate)
    rec.update(conservative_per_job_seconds=estimate, conservative_completion_seconds=needed)
    if missing and (needed is None or needed > ledger.remaining()):
        if mandatory:
            rec.update(state='INCOMPLETE_PRIMARY_RESOURCE_BUDGET')
            atomic_json(old, rec)
            raise RuntimeError('Mandatory primary cannot complete in the remaining frozen wall budget')
        rec.update(state='UNAVAILABLE_RESOURCE_BUDGET', reason='Whole-stage runtime-only admission failed')
        atomic_json(old, rec); return rec
    if missing:
        rec['disk_plan'] = guard_fit_bank(missing, manifest, state_root, name)
        rec['disk_headroom_bytes'] = FIT_HEADROOM_BYTES
    try:
        grouped = {}
        for task in missing: grouped.setdefault(task.origin, []).append(task)
        for origin in sorted(grouped):
            complete = _resource_records(state_root, feature_sha, permit)
            # CONFX7: one anonymous projection per task, from the task's memory class (saved-bank shape bound
            # unchanged); wide news arms therefore lower the concurrency, narrow arms do not inherit wide peaks.
            projected = {task_id(t): _projected_anonymous(t, complete, manifest) for t in grouped[origin]}
            _fit_wave(grouped[origin], name, manifest, feature_sha, stats, permit, state_root, ledger, projected)
        rec.update(state='COMPLETE_WITH_UNAVAILABLE_CONFIGURATIONS' if unavailable else 'COMPLETE', completed_jobs=len(runnable), budget_after_seconds=ledger.remaining())
        atomic_json(old, rec); return rec
    except DiskSpaceError:
        # A host disk shortage never becomes a statistical stage disposition.
        raise
    except Exception as exc:
        state = 'INCOMPLETE_PRIMARY' if mandatory else ('UNAVAILABLE_RESOURCE_FAILURE' if isinstance(exc, (MemoryError, TimeoutError)) else 'UNAVAILABLE_MODEL_FAILURE')
        rec.update(state=state, error=repr(exc), budget_after_seconds=ledger.remaining(), partial_predictions_eligible_for_scoring=False)
        atomic_json(old, rec)
        if mandatory: raise
        return rec


def counted_pilots(permit, feature_root, state_root):
    """First five notice fits, four main news fits and one full LEAR issue.

    Every result remains a counted task in its exact registered stage. No pilot
    loss is read and no partial pilot sequence can be scored.
    """
    require(permit)
    with exclusive_state(state_root):
        ledger = WallLedger(state_root)
        manifest, feature_sha, stats = feature_manifest(feature_root, permit)
        require_a1_dispositions(manifest)
        stages = registered_plan()
        selected = [('primary_notice', stages[0][1]), ('primary_news', stages[1][1][:4]),
                    ('secondary_LEAR', stages[5][1][:1])]
        receipts = []
        for name, tasks in selected:
            missing = [t for t in tasks if reusable(state_root, t, feature_sha, permit) is None]
            if not missing: continue
            guard_fit_bank(missing, manifest, state_root, 'counted_pilot__' + name)
            # First fits start serially until measured lifetime RSS exists. The
            # full bank retains its four-worker news ceiling and origin barrier.
            for task in missing:
                try:
                    receipts.extend(_fit_wave([task], 'counted_pilot__' + name, manifest, feature_sha, stats,
                                              permit, state_root, ledger, _projected_anonymous(task, [], manifest)
                                              if task.task == 'news' else 768 * 1024**2))
                except DiskSpaceError:
                    raise
                except Exception as exc:
                    atomic_json(Path(state_root) / 'COUNTED_PILOT_FAILURE.json', {'stage': name, 'task_id': task_id(task),
                                'error': repr(exc), 'elapsed_fitting_seconds': ledger.elapsed(), 'partial_score_allowed': False})
                    if name != 'secondary_LEAR': raise
                    atomic_json(_stage_path(state_root, name), {'stage': name, 'state': 'UNAVAILABLE_MODEL_FAILURE',
                                'registered_tasks': [task_id(t) for t in stages[5][1]], 'reason': repr(exc),
                                'partial_predictions_eligible_for_scoring': False})
                    break
        rec = {'state': 'COUNTED_PILOTS_COMPLETE', 'elapsed_fitting_seconds': ledger.elapsed(),
               'feature_manifest_sha256': feature_sha, 'pilots_are_reusable_registered_tasks': True,
               'no_pilot_scoring': True}
        atomic_json(Path(state_root) / 'COUNTED_PILOTS.json', rec); return rec


def run_fits(permit, feature_root, state_root, until='secondary_news'):
    """Fixed forward plan through secondary news; resume-safe complete stages."""
    require(permit)
    with exclusive_state(state_root):
        ledger = WallLedger(state_root); manifest, feature_sha, stats = feature_manifest(feature_root, permit)
        require_a1_dispositions(manifest)
        dispositions = []
        for name, tasks, mandatory in registered_plan():
            if name == 'secondary_LEAR': break
            dispositions.append(_run_stage(name, tasks, mandatory, manifest, feature_sha, stats, permit, state_root, ledger))
            if name == until: return dispositions
        return dispositions


def run_lear_and_remaining(permit, feature_root, state_root):
    """LEAR followed by seeds, 24h and first-L, preserving frozen priority."""
    require(permit)
    with exclusive_state(state_root):
        ledger = WallLedger(state_root); manifest, feature_sha, stats = feature_manifest(feature_root, permit)
        require_a1_dispositions(manifest)
        dispositions = []; reached = False
        for name, tasks, mandatory in registered_plan():
            if name == 'secondary_LEAR': reached = True
            if not reached:
                path = _stage_path(state_root, name)
                if not path.exists() or read_json(path)['state'] not in TERMINAL:
                    raise RuntimeError('Earlier stage has no complete/unavailable disposition: ' + name)
                continue
            dispositions.append(_run_stage(name, tasks, mandatory, manifest, feature_sha, stats, permit, state_root, ledger))
        atomic_json(Path(state_root) / 'ALL_STAGE_DISPOSITIONS.json', {'state': 'ALL_REGISTERED_STAGES_DISPOSED',
                    'stages': [read_json(_stage_path(state_root, n)) for n, _, _ in registered_plan()],
                    'elapsed_fitting_seconds': ledger.elapsed(), 'budget_seconds': BUDGET})
        return dispositions
