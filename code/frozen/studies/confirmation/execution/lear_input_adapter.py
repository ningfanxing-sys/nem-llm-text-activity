"""CONFX5 LEAR execution path: the CONFX2 LEAR wrapper with the template convergence rule.

Rule (CONFX5/SPEC_ADDENDUM_2_LEAR_TEMPLATE.md, adopted 2026-10-02 before any CONF fit): every
scikit-learn ConvergenceWarning, from the LARS/AIC step and from the coordinate-descent Lasso fit,
is recorded per hour fit and is never fatal, exactly as the pinned epftoolbox LEAR.recalibrate
(@ignore_warnings(category=ConvergenceWarning), CONF/evidence/epftoolbox_lear_source.py lines
40-41, covering LassoLarsIC line 75 and Lasso line 79; Lago et al., Applied Energy 293 (2021)
116983, pp. 8-9). Every other exception stays fatal (non-finite values, linear-algebra errors,
incomplete windows, non-finite inverse transform). lear_adapter.py stays byte-identical because
BASE25 enforces its SHA-256; daily_forecast and run_daily_job below are verbatim copies that
resolve fit_window_with_artifacts and daily_forecast in this module. No study reads at import.
"""
from __future__ import annotations
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
import hashlib
import re
import time

try:
    from .runtime import audit, install_audit, conf_module, read_json, sha256
    from .execution_adapter import require, task_id, KEYS
    from .lear_adapter import REGIONS, array_hash, hourly_index, price_profile
except ImportError:
    from runtime import audit, install_audit, conf_module, read_json, sha256
    from execution_adapter import require, task_id, KEYS
    from lear_adapter import REGIONS, array_hash, hourly_index, price_profile

CONVERGENCE_RULE = 'TEMPLATE_ALL_CONVERGENCE_WARNINGS_RECORDED_NOT_FATAL'
_GAP = re.compile(r'Duality gap: ([0-9.eE+-]+), tolerance: ([0-9.eE+-]+)')


def _recorded(caught):
    """Warnings as receipt records; a CD ConvergenceWarning keeps scikit-learn's printed gap and tolerance."""
    records = []
    for w in caught:
        item = dict(category=w.category.__name__, message=str(w.message)[:300])
        match = _GAP.search(str(w.message))
        if match:
            gap, tol = float(match.group(1)), float(match.group(2))
            item.update(reported_duality_gap=gap, reported_tolerance=tol,
                        gap_over_tolerance=gap / tol if tol > 0 else None)
        records.append(item)
    return records


def fit_window_with_artifacts(x, y, query, model_path, permit):
    """CONFX2 lear_adapter.fit_window_with_artifacts with only the warning handling changed.

    Warnings raised in the LARS/AIC step and in the coordinate-descent fit are recorded per hour and
    are not fatal (template rule); the alpha is the one LARS returned and the model is the CD fit.
    """
    require(permit)
    import warnings
    import numpy as np
    from sklearn.linear_model import Lasso
    frozen = conf_module('lear')
    if y.shape != (len(x), 24) or not np.isfinite(y).all():
        raise ValueError('LEAR requires every calibration target and strict legal clock')
    scale = frozen.AsinhScale.fit(y, permit)
    transformed = scale.transform(y, permit)
    prediction = np.empty((1, 24), dtype='float64')
    coefficients, intercepts, receipts = [], [], []
    for hour in range(24):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            alpha, receipt = frozen.select_alpha_lars_aic(x, transformed[:, hour], permit)
        lars_warnings = _recorded(caught)
        estimator = Lasso(alpha=alpha, max_iter=frozen.MAX_ITER, tol=1e-4, fit_intercept=True,
                          selection='cyclic', precompute=False)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            estimator.fit(x, transformed[:, hour])
        cd_warnings = _recorded(caught)
        cd_convergence = [w for w in cd_warnings if w['category'] == 'ConvergenceWarning']
        prediction[0, hour] = estimator.predict(query)[0]
        coef = np.asarray(estimator.coef_, dtype='float64')
        coefficients.append(coef); intercepts.append(estimator.intercept_)
        receipts.append(dict(receipt, hour=hour, coordinate_descent_iterations=int(estimator.n_iter_),
                             convergence='COMPLETE' if not cd_convergence else 'CD_CONVERGENCE_WARNING_RECORDED',
                             lars_warnings=lars_warnings,
                             lars_convergence_warnings=sum(w['category'] == 'ConvergenceWarning' for w in lars_warnings),
                             cd_warnings=cd_warnings, cd_converged=not cd_convergence,
                             cd_dual_gap_attribute=float(np.asarray(estimator.dual_gap_).ravel()[0]),
                             cd_gap_over_tolerance=max((w.get('gap_over_tolerance') or 0.) for w in cd_convergence) if cd_convergence else None,
                             convergence_rule=CONVERGENCE_RULE,
                             model_array_sha256=array_hash(coef, np.asarray([estimator.intercept_]))))
    np.savez(model_path, coefficients=np.asarray(coefficients), intercepts=np.asarray(intercepts),
             target_median=scale.median, target_scale=scale.scale, zero_mad_columns=scale.zero_mad_columns,
             alpha=np.asarray([r['alpha'] for r in receipts]))
    return scale.inverse(prediction, permit), receipts, array_hash(scale.median, scale.scale, scale.zero_mad_columns)


def convergence_diagnostic(lear_receipts):
    """Descriptive LEAR diagnostic from sealed daily job receipts; reads no forecast or outcome."""
    entries = [h for rec in lear_receipts for window in rec.get('windows', []) for h in window.get('hours', [])]
    hours = [h for h in entries if isinstance(h, dict)]          # receipts without hour records carry no fields
    cd = [h for h in hours if h.get('cd_converged') is False]
    ratios = [h['cd_gap_over_tolerance'] for h in cd if isinstance(h.get('cd_gap_over_tolerance'), (int, float))]
    lars = [w for h in hours for w in h.get('lars_warnings', []) if w.get('category') == 'ConvergenceWarning']
    kinds = {}
    for w in lars:
        message = w.get('message', '')
        kind = ('REGRESSORS_IN_ACTIVE_SET_DEGENERATE' if message.startswith('Regressors in active set degenerate') else
                'EARLY_STOPPING_LARS_PATH' if message.startswith('Early stopping the lars path') else 'OTHER')
        kinds[kind] = kinds.get(kind, 0) + 1
    return {'rule': CONVERGENCE_RULE, 'daily_jobs': len(lear_receipts), 'hour_fits': len(entries),
            'hour_fits_with_rule_fields': sum('cd_converged' in h for h in hours),
            'cd_nonconverged_hour_fits': len(cd), 'cd_max_gap_over_tolerance': max(ratios) if ratios else None,
            'hour_fits_with_lars_convergence_warning': sum(1 for h in hours if h.get('lars_convergence_warnings', 0)),
            'lars_convergence_warnings_by_type': kinds,
            'note': 'Descriptive LEAR diagnostic under the template convergence rule; no LEAR accuracy is computed.'}


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
