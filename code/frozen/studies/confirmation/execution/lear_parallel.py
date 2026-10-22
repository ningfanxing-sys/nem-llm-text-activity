"""CONFX7 (addendum 3): LEAR daily jobs with their 12 window subjobs on 3 workers (BASE25 approach).

COMPUTE_PLAN.md: "parallel hour subjobs require a separately documented resource-only implementation receipt and
must preserve deterministic fits" (CONFX7/SPEC_ADDENDUM_3_THROUGHPUT.md section 2 is that documentation). The
template is BASE25/code/lear_base25.py `run`: per issue, the (region, window) jobs in the CONFX2 loop order on a
spawn pool of 3 workers with an order-preserving map and an origin barrier; the hourly table is loaded once per
worker; the parent assembles the four-window ensemble. The pool initializer is the frozen `scheduler.worker_init`
(one BLAS thread), and the first subjob of each worker loads the table: an initializer imported from this package
would load numpy (through feature_storage) before the thread limit is set.

`window_subjob` is the inner-loop body of `lear_adapter_confx5.daily_forecast` for one (region, window), and
`assemble_daily_job` is the rest of `daily_forecast` and `run_daily_job`; `lear_adapter.py` and
`lear_adapter_confx5.py` stay byte-identical. Daily jobs stay serial. No study read happens at import.
"""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import hashlib
import os
import time

try:
    from .runtime import audit, install_audit, conf_module, sha256
    from .execution_adapter import require, task_id, KEYS
    from .lear_adapter import REGIONS, array_hash, hourly_index, price_profile
    from .lear_adapter_confx5 import fit_window_with_artifacts
except ImportError:
    from runtime import audit, install_audit, conf_module, sha256
    from execution_adapter import require, task_id, KEYS
    from lear_adapter import REGIONS, array_hash, hourly_index, price_profile
    from lear_adapter_confx5 import fit_window_with_artifacts

SUBJOB_WORKERS = 3
_W = {}


def subjob_units(task):
    """The 12 window subjobs of one daily job, in the CONFX2 loop order (region-major, window-minor)."""
    return [(task, region, days) for region in REGIONS for days in conf_module('lear').WINDOW_DAYS]


def worker_index(hourly_path, hourly_sha256):
    """The hourly index of this worker, built once from the hash-checked table (as run_daily_job reads it)."""
    if _W.get('key') != (str(hourly_path), hourly_sha256):
        install_audit('execution_worker')
        import pandas as pd
        if sha256(hourly_path) != hourly_sha256:
            raise RuntimeError('LEAR ordinary hourly source identity drift')
        audit(hourly_path, 'authorized_postfreeze_read', 'LEAR registered ordinary hourly labels and clocks')
        frame = pd.read_parquet(hourly_path, columns=['region', 'target_time', 'target_day', 'y', 'label_available'])
        _W.update(index=hourly_index(frame), key=(str(hourly_path), hourly_sha256))
    return _W['index']


def window_fit(index, issue_string, region, days, permit, output_root):
    """Exactly the inner-loop body of daily_forecast for one (region, window)."""
    require(permit)
    import numpy as np
    import pandas as pd
    frozen = conf_module('lear')
    issue = pd.Timestamp(issue_string, tz='Australia/Brisbane').tz_convert('UTC')
    out = Path(output_root); out.mkdir(parents=True, exist_ok=True)
    label_clocks = {d: clocks for (d, r), (prices, clocks) in index.items() if r == region and
                    np.isfinite(prices).all() and all(pd.notna(c) for c in clocks)}
    started = time.monotonic()
    dates = frozen.calibration_dates(issue, days, label_clocks, permit)
    train_prices = np.vstack([price_profile(day, region, index) for day in dates])
    query_prices = price_profile(issue.tz_convert('Australia/Brisbane').date(), region, index)[None, :]
    week = np.eye(7)[[day.weekday() for day in dates]]
    weekday_query = np.eye(7)[[issue.tz_convert('Australia/Brisbane').weekday()]]
    x, q, scale_receipt = frozen.prepare_calibration_inputs(train_prices, query_prices, week, weekday_query, permit)
    imputation = np.asarray([np.median(v[np.isfinite(v)]) if np.isfinite(v).any() else 0.
                             for v in train_prices.T], dtype='float64')
    filled = np.where(np.isnan(train_prices), imputation, train_prices)
    input_scale = frozen.AsinhScale.fit(filled, permit)
    scale_path = out / f'LEAR__{issue_string}__{region}__{days}__input_scaling.npz'
    np.savez(scale_path, imputation_median=imputation, input_median=input_scale.median,
             input_scale=input_scale.scale, zero_mad_columns=input_scale.zero_mad_columns)
    y = np.vstack([index[(day, region)][0] for day in dates])
    model_path = out / f'LEAR__{issue_string}__{region}__{days}.npz'
    forecast, hour_receipts, target_scale_sha = fit_window_with_artifacts(x, y, q, model_path, permit)
    receipt = {'region': region, 'window_days': days, 'calibration_first_day': dates[0].isoformat(),
               'calibration_last_day': dates[-1].isoformat(), 'input_features': 199,
               'training_label_clock_max': max(c for d in dates for c in label_clocks[d]).isoformat(),
               'input_matrix_sha256': array_hash(x), 'query_matrix_sha256': array_hash(q),
               'target_scaling_sha256': target_scale_sha,
               'input_scaling_path': str(scale_path), 'input_imputation_scaling_sha256': sha256(scale_path),
               'model_path': str(model_path), 'model_sha256': sha256(model_path),
               'prediction_array_sha256': array_hash(forecast), 'hours': hour_receipts,
               'runtime_seconds': time.monotonic() - started, **scale_receipt}
    return forecast, receipt


def window_subjob(payload):
    """Pool worker: one (region, window) of a daily job; the forecast travels as float64 values."""
    task, region, days, permit, output_root, hourly_path, hourly_sha256 = payload
    import resource
    import sys
    started = time.monotonic()
    rec = {'task_id': task_id(task), 'region': region, 'window_days': days, 'state': 'FAILED', 'worker_pid': os.getpid()}
    try:
        forecast, receipt = window_fit(worker_index(hourly_path, hourly_sha256), task.origin, region, days, permit, output_root)
        rec.update(state='COMPLETE', forecast=[float(v) for v in forecast[0]], receipt=receipt)
    except Exception as exc:
        rec['error'] = repr(exc)
    rec['subjob_wall_seconds'] = time.monotonic() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rec['peak_rss_bytes'] = int(peak if sys.platform == 'darwin' else peak * 1024)
    return rec


def assemble_daily_job(task, feature_sha, permit, output_root, results, runtime_seconds, workers):
    """The rest of daily_forecast and run_daily_job, from the 12 subjob results in the CONFX2 loop order."""
    require(permit)
    import numpy as np
    import pandas as pd
    frozen = conf_module('lear')
    ident = task_id(task)
    rec = {'task': asdict(task), 'task_id': ident, 'state': 'FAILED', 'feature_manifest_sha256': feature_sha,
           'design_freeze_sha256': permit.design_freeze_sha256,
           'completed_input_manifest_sha256': permit.completed_input_manifest_sha256}
    try:
        expected = [(region, days) for region in REGIONS for days in frozen.WINDOW_DAYS]
        if [(r['region'], r['window_days']) for r in results] != expected:
            raise RuntimeError('LEAR window subjobs out of the registered loop order')
        failed = [r for r in results if r['state'] != 'COMPLETE']
        if failed:
            raise RuntimeError('LEAR window subjob failed: ' + '; '.join(str(r.get('error')) for r in failed))
        issue = pd.Timestamp(task.origin, tz='Australia/Brisbane').tz_convert('UTC')
        rows, receipts = [], []
        for region in REGIONS:
            windows = {}
            for r in results:
                if r['region'] == region:
                    windows[r['window_days']] = np.asarray([r['forecast']], dtype='float64')
                    receipts.append(r['receipt'])
            final = frozen.ensemble_four_windows(windows, permit)[0]
            for hour, value in enumerate(final):
                target = issue + pd.Timedelta(hours=hour)
                rows.append({'origin': issue, 'target_time': target, 'target_day': task.origin,
                             'region': region, 'horizon': hour, 'prediction': value, 'raw_prediction': value})
        if sum(len(r['hours']) for r in receipts) != 288:
            raise RuntimeError('LEAR daily job must contain all 288 estimator pairs')
        predictions = pd.DataFrame(rows)
        Path(output_root).mkdir(parents=True, exist_ok=True)
        prediction_path = Path(output_root) / (ident + '.predictions.parquet')
        predictions.to_parquet(prediction_path, index=False)
        rec.update(state='COMPLETE', component_pairs=288, estimator_fits=576, features=199,
                   prediction_rows=72, prediction_path=str(prediction_path), prediction_sha256=sha256(prediction_path),
                   prediction_key_sha256=hashlib.sha256(pd.util.hash_pandas_object(predictions[KEYS], index=False).to_numpy().tobytes()).hexdigest(),
                   windows=receipts, window_weights=[.25, .25, .25, .25])
    except Exception as exc:
        rec['error'] = repr(exc)
    rec.update(runtime_seconds=runtime_seconds, subjob_workers=workers,
               subjob_worker_pids=sorted({r.get('worker_pid') for r in results}),
               subjob_wall_seconds=[r.get('subjob_wall_seconds') for r in results],
               peak_rss_bytes=max((r.get('peak_rss_bytes') or 0) for r in results) if results else 0)
    return rec
