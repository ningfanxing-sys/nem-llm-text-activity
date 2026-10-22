"""Complete registered 288-pair daily LEAR job, no study reads at import."""
from __future__ import annotations
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
import hashlib
import time

try:
    from .runtime import audit, install_audit, conf_module, read_json, sha256
    from .execution_adapter import require, task_id, KEYS
except ImportError:
    from runtime import audit, install_audit, conf_module, read_json, sha256
    from execution_adapter import require, task_id, KEYS

REGIONS = ('NSW1', 'QLD1', 'TAS1')


def array_hash(*arrays):
    import numpy as np
    h = hashlib.sha256()
    for arr in arrays:
        a = np.ascontiguousarray(arr)
        h.update(str(a.dtype).encode()); h.update(str(a.shape).encode()); h.update(a.tobytes())
    return h.hexdigest()


def hourly_index(hourly):
    """Ordinary 12-interval hourly prices and their independent availability."""
    import numpy as np
    import pandas as pd
    frame = hourly.copy()
    frame['target_day'] = frame['target_day'].astype(str)
    frame['label_available'] = pd.to_datetime(frame['label_available'], utc=True, errors='coerce')
    times = pd.to_datetime(frame['target_time'], utc=True).dt.tz_convert('Australia/Brisbane')
    frame['hour'] = times.dt.hour
    if frame.duplicated(['target_day', 'region', 'hour']).any():
        raise ValueError('Duplicate ordinary hourly key')
    index = {}
    for (day, region), group in frame.groupby(['target_day', 'region'], sort=True):
        group = group.sort_values('hour')
        if list(group['hour']) != list(range(24)):
            # Missing target support is recorded in the index; calibration will
            # fail its exact consecutive-calendar window rather than backfill.
            continue
        index[(pd.Timestamp(day).date(), region)] = (
            group['y'].to_numpy(dtype='float64'), tuple(group['label_available']))
    return index


def price_profile(day, region, index):
    """Lag d-1/d-2/d-3/d-7 observed at that example's own issue."""
    import numpy as np
    import pandas as pd
    issue = pd.Timestamp(day, tz='Australia/Brisbane').tz_convert('UTC')
    values = []
    for lag in (1, 2, 3, 7):
        entry = index.get((day - timedelta(days=lag), region))
        if entry is None:
            values.extend([np.nan] * 24)
        else:
            prices, clocks = entry
            values.extend(float(p) if np.isfinite(p) and pd.notna(c) and c <= issue else np.nan
                          for p, c in zip(prices, clocks))
    return np.asarray(values, dtype='float64')


def fit_window_with_artifacts(x, y, query, model_path, permit):
    """Frozen LEAR calculation with model/scale serialization instrumentation.

    The formula/solver/order matches code/lear.py.fit_calibration_window. Only
    saving estimator coefficients/intercepts and scale hashes is added.
    """
    require(permit)
    import warnings
    import numpy as np
    from sklearn.linear_model import Lasso
    from sklearn.exceptions import ConvergenceWarning
    frozen = conf_module('lear')
    if y.shape != (len(x), 24) or not np.isfinite(y).all():
        raise ValueError('LEAR requires every calibration target and strict legal clock')
    scale = frozen.AsinhScale.fit(y, permit)
    transformed = scale.transform(y, permit)
    prediction = np.empty((1, 24), dtype='float64')
    coefficients, intercepts, receipts = [], [], []
    for hour in range(24):
        with warnings.catch_warnings():
            # LEAR_SPEC makes nonconvergence unavailable for the whole benchmark;
            # preserve converged LARS results and never introduce an alpha fallback.
            warnings.simplefilter('error', ConvergenceWarning)
            alpha, receipt = frozen.select_alpha_lars_aic(x, transformed[:, hour], permit)
        estimator = Lasso(alpha=alpha, max_iter=frozen.MAX_ITER, tol=1e-4, fit_intercept=True,
                          selection='cyclic', precompute=False)
        with warnings.catch_warnings():
            warnings.simplefilter('error', ConvergenceWarning)
            estimator.fit(x, transformed[:, hour])
        prediction[0, hour] = estimator.predict(query)[0]
        coef = np.asarray(estimator.coef_, dtype='float64')
        coefficients.append(coef); intercepts.append(estimator.intercept_)
        receipts.append(dict(receipt, hour=hour, coordinate_descent_iterations=int(estimator.n_iter_),
                             convergence='COMPLETE', model_array_sha256=array_hash(coef, np.asarray([estimator.intercept_]))))
    np.savez(model_path, coefficients=np.asarray(coefficients), intercepts=np.asarray(intercepts),
             target_median=scale.median, target_scale=scale.scale, zero_mad_columns=scale.zero_mad_columns,
             alpha=np.asarray([r['alpha'] for r in receipts]))
    return scale.inverse(prediction, permit), receipts, array_hash(scale.median, scale.scale, scale.zero_mad_columns)


def daily_forecast(hourly, issue_string, permit, output_root):
    """All 3 regions × 4 windows × 24 hours or one whole-job failure."""
    require(permit)
    import numpy as np
    import pandas as pd
    frozen = conf_module('lear'); index = hourly_index(hourly)
    issue = pd.Timestamp(issue_string, tz='Australia/Brisbane').tz_convert('UTC')
    out = Path(output_root); out.mkdir(parents=True, exist_ok=True)
    rows, receipts = [], []
    for region in REGIONS:
        label_clocks = {d: clocks for (d, r), (prices, clocks) in index.items() if r == region and
                        np.isfinite(prices).all() and all(pd.notna(c) for c in clocks)}
        windows = {}
        for days in frozen.WINDOW_DAYS:
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
            windows[days] = forecast
            receipts.append({'region': region, 'window_days': days, 'calibration_first_day': dates[0].isoformat(),
                             'calibration_last_day': dates[-1].isoformat(), 'input_features': 199,
                             'training_label_clock_max': max(c for d in dates for c in label_clocks[d]).isoformat(),
                             'input_matrix_sha256': array_hash(x), 'query_matrix_sha256': array_hash(q),
                             'target_scaling_sha256': target_scale_sha,
                             'input_scaling_path': str(scale_path), 'input_imputation_scaling_sha256': sha256(scale_path),
                             'model_path': str(model_path), 'model_sha256': sha256(model_path),
                             'prediction_array_sha256': array_hash(forecast), 'hours': hour_receipts,
                             'runtime_seconds': time.monotonic() - started, **scale_receipt})
        final = frozen.ensemble_four_windows(windows, permit)[0]
        for hour, value in enumerate(final):
            target = issue + pd.Timedelta(hours=hour)
            rows.append({'origin': issue, 'target_time': target, 'target_day': issue_string,
                         'region': region, 'horizon': hour, 'prediction': value, 'raw_prediction': value})
    if sum(len(r['hours']) for r in receipts) != 288:
        raise RuntimeError('LEAR daily job must contain all 288 estimator pairs')
    return pd.DataFrame(rows), receipts


def run_daily_job(payload):
    task, manifest, feature_sha, stats, permit, output_root = payload
    install_audit('execution_worker')
    require(permit)
    import resource
    import sys
    import pandas as pd
    started = time.monotonic(); ident = task_id(task)
    rec = {'task': asdict(task), 'task_id': ident, 'state': 'FAILED', 'feature_manifest_sha256': feature_sha,
           'design_freeze_sha256': permit.design_freeze_sha256,
           'completed_input_manifest_sha256': permit.completed_input_manifest_sha256}
    try:
        path = manifest['hourly_path']
        if sha256(path) != manifest['hourly_sha256']:
            raise RuntimeError('LEAR ordinary hourly source identity drift')
        audit(path, 'authorized_postfreeze_read', 'LEAR registered ordinary hourly labels and clocks')
        frame = pd.read_parquet(path, columns=['region', 'target_time', 'target_day', 'y', 'label_available'])
        predictions, windows = daily_forecast(frame, task.origin, permit, output_root)
        prediction_path = Path(output_root) / (ident + '.predictions.parquet')
        predictions.to_parquet(prediction_path, index=False)
        rec.update(state='COMPLETE', component_pairs=288, estimator_fits=576, features=199,
                   prediction_rows=72, prediction_path=str(prediction_path), prediction_sha256=sha256(prediction_path),
                   prediction_key_sha256=hashlib.sha256(pd.util.hash_pandas_object(predictions[KEYS], index=False).to_numpy().tobytes()).hexdigest(),
                   windows=windows, window_weights=[.25, .25, .25, .25])
    except Exception as exc:
        rec['error'] = repr(exc)
    rec['runtime_seconds'] = time.monotonic() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rec['peak_rss_bytes'] = int(peak if sys.platform == 'darwin' else peak * 1024)
    return rec
