"""Registered issue-legal LEAR adaptation; no data access/fit on import.

Reference: Lago et al., Applied Energy 293 (2021), 116983, pp.7--9,14.
All numerical entrypoints require a later execution permit. No models are
instantiated until that permit is supplied. The 2021-era AIC path formula is
explicit, avoiding modern sklearn's n>p noise-estimation requirement.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import timedelta

try:
    from .guard import require_execution
except ImportError:
    from guard import require_execution

WINDOW_DAYS = (56, 84, 1092, 1456)
PRICE_DAY_LAGS = (1, 2, 3, 7)
NORMAL_MAD_QUANTILE = 0.6744897501960817
MAX_ITER = 2500
BASE_FEATURES = 4 * 24 + 7
MISSING_MASKS = 4 * 24
TOTAL_FEATURES = BASE_FEATURES + MISSING_MASKS


def calibration_dates(issue, window_days, day_label_clocks, permit=None):
    """Exact consecutive-day calendar window ending at latest legal label day.

    Each mapping entry is a region's 24 target-label availability clocks. A
    midnight origin usually cannot train on the preceding day's last hour.
    Missing internal days stop this benchmark; never replace with older rows.
    """
    require_execution(permit)
    if window_days not in WINDOW_DAYS:
        raise ValueError("Unregistered LEAR calibration window")
    legal = [day for day, clocks in day_label_clocks.items()
             if day < issue.date() and len(clocks) == 24 and all(clock < issue for clock in clocks)]
    if not legal:
        raise ValueError("No strictly label-legal LEAR calibration day")
    last = max(legal)
    dates = tuple(last - timedelta(days=offset) for offset in range(window_days - 1, -1, -1))
    if any(day not in legal for day in dates):
        raise ValueError("Incomplete registered LEAR calendar calibration window")
    return dates


@dataclass
class AsinhScale:
    median: object
    scale: object
    zero_mad_columns: object

    @classmethod
    def fit(cls, matrix, permit=None):
        require_execution(permit)
        import numpy as np
        array = np.asarray(matrix, dtype=np.float64)
        if array.ndim != 2 or not np.isfinite(array).all():
            raise ValueError("Asinh scaler needs a finite, training-only 2D matrix")
        center = np.median(array, axis=0)
        mad = np.median(np.abs(array - center), axis=0) / NORMAL_MAD_QUANTILE
        zero = mad == 0
        # Frozen project handling for constant calibration columns; record hits.
        return cls(center, np.where(zero, 1.0, mad), zero)

    def transform(self, matrix, permit=None):
        require_execution(permit)
        import numpy as np
        return np.arcsinh((np.asarray(matrix, dtype=np.float64) - self.median) / self.scale)

    def inverse(self, matrix, permit=None):
        require_execution(permit)
        import numpy as np
        answer = np.sinh(np.asarray(matrix, dtype=np.float64)) * self.scale + self.median
        if not np.isfinite(answer).all():
            raise ValueError("LEAR inverse transform produced nonfinite predictions; no clipping repair")
        return answer


def prepare_calibration_inputs(train_prices, query_prices, weekday_train, weekday_query, permit=None):
    """96 conventional lagged-hour profiles, seven dummies, 96 missing masks.

    Price profiles use only source observations available <= each issue. At
    midnight, last hour of d-1 may be missing: impute with the calibration-set
    median, append its observed-missing mask, never use future prices. All-NaN
    columns get fixed zero fill and are explicitly reported.
    """
    require_execution(permit)
    import numpy as np
    train = np.asarray(train_prices, dtype=np.float64)
    query = np.asarray(query_prices, dtype=np.float64)
    if train.ndim != 2 or train.shape[1] != 96 or query.shape != (1, 96):
        raise ValueError("LEAR price profiles need training n x 96 and query 1 x 96")
    if np.isinf(train).any() or np.isinf(query).any():
        raise ValueError("Infinite predictor must be represented as unavailable before LEAR")
    all_missing = np.isnan(train).all(axis=0)
    medians = np.zeros(96)
    for j in range(96):
        legal = train[np.isfinite(train[:, j]), j]
        medians[j] = np.median(legal) if len(legal) else 0.0
    train_missing, query_missing = np.isnan(train), np.isnan(query)
    filled = np.where(train_missing, medians, train)
    query_filled = np.where(query_missing, medians, query)
    scale = AsinhScale.fit(filled, permit)
    x = np.concatenate([scale.transform(filled, permit), np.asarray(weekday_train),
                        train_missing.astype(float)], axis=1)
    q = np.concatenate([scale.transform(query_filled, permit), np.asarray(weekday_query),
                        query_missing.astype(float)], axis=1)
    if x.shape[1] != TOTAL_FEATURES or q.shape != (1, TOTAL_FEATURES):
        raise ValueError("LEAR feature dimension drift")
    receipt = {"all_missing_columns": np.flatnonzero(all_missing).tolist(),
               "zero_mad_columns": np.flatnonzero(scale.zero_mad_columns).tolist(),
               "training_missing_count": int(train_missing.sum()),
               "query_missing_count": int(query_missing.sum())}
    return x, q, receipt


def select_alpha_lars_aic(x_train, y_train, permit=None):
    """2021-era LassoLarsIC AIC: n*MSE/(var(centered y)+eps)+2*nonzero df.

    Center and L2-normalize predictors as sklearn 0.24.2's normalize=True.
    Source implementation and formula are pinned in LEAR_SPEC.md. The selected
    alpha is then used by coordinate-descent Lasso on the asinh input matrix,
    matching the official two-stage implementation (not LARS predictions).
    """
    require_execution(permit)
    import numpy as np
    from sklearn.linear_model import lars_path
    x = np.asarray(x_train, dtype=np.float64)
    y = np.asarray(y_train, dtype=np.float64)
    xc, yc = x - x.mean(axis=0), y - y.mean()
    norm = np.sqrt(np.sum(xc ** 2, axis=0))
    xn = xc / np.where(norm == 0, 1.0, norm)
    alphas, _, coefficients = lars_path(xn, yc, method="lasso", max_iter=MAX_ITER,
                                       Gram="auto", copy_X=True, return_path=True)
    residual = yc[:, None] - xn @ coefficients
    degrees = np.sum(np.abs(coefficients) > np.finfo(np.float64).eps, axis=0)
    aic = len(y) * np.mean(residual ** 2, axis=0) / (np.var(yc) + np.finfo(np.float64).eps) + 2 * degrees
    choice = int(np.argmin(aic))
    return float(alphas[choice]), {"path_points": len(alphas), "selected_df": int(degrees[choice]),
                                  "aic_rule": "sklearn_0.24.2_legacy_AIC", "alpha": float(alphas[choice])}


def fit_calibration_window(x_train, y_train_24, x_query, permit=None):
    """One region/origin/window, 24 LARS+CD pairs in sequence; small matrices."""
    require_execution(permit)
    import warnings
    import numpy as np
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.linear_model import Lasso
    x = np.asarray(x_train, dtype=np.float64)
    y = np.asarray(y_train_24, dtype=np.float64)
    if y.shape != (len(x), 24) or not np.isfinite(y).all():
        raise ValueError("LEAR targets must be complete 24-hour, strictly label-legal calibration days")
    scale = AsinhScale.fit(y, permit)
    transformed = scale.transform(y, permit)
    predictions = np.empty((1, 24), dtype=np.float64)
    receipts = []
    for hour in range(24):
        alpha, receipt = select_alpha_lars_aic(x, transformed[:, hour], permit)
        estimator = Lasso(alpha=alpha, max_iter=MAX_ITER, tol=1e-4, fit_intercept=True,
                          selection="cyclic", precompute=False)
        with warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            estimator.fit(x, transformed[:, hour])
        predictions[0, hour] = estimator.predict(x_query)[0]
        receipts.append(dict(receipt, hour=hour, coordinate_descent_iterations=int(estimator.n_iter_)))
    return scale.inverse(predictions, permit), receipts


def ensemble_four_windows(predictions_by_window, permit=None):
    require_execution(permit)
    import numpy as np
    if set(predictions_by_window) != set(WINDOW_DAYS):
        raise ValueError("LEAR benchmark requires all four registered windows; no selective averaging")
    predictions = np.stack([predictions_by_window[days] for days in WINDOW_DAYS])
    if not np.isfinite(predictions).all():
        raise ValueError("Incomplete LEAR benchmark")
    return np.mean(predictions, axis=0, dtype=np.float64)


if __name__ == "__main__":
    raise SystemExit("CONF DESIGN ONLY: LEAR fitting requires a separate execution task")
