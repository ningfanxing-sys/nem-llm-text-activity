"""CONF inference skeleton; no filesystem reads, fits or scores on import.

Public scoring entry requires the later execution/freeze authorization callback.
All internal helpers are pure in-memory functions and may be checked synthetically.
"""
from __future__ import annotations

from datetime import date, timedelta
import math
import numpy as np
try:
    from .guard import ExecutionPermit, require_execution
except ImportError:
    from guard import ExecutionPermit, require_execution

BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20260925
NEWS_FAMILY = (("L_count", "M"), ("L_chen", "M"))
NOTICE_FAMILY = (("L14", "M_notice"), ("L_Laz", "M_notice"), ("L_chen_notice", "M_notice"))


def dm_daily(difference, hac_lag=None):
    x = np.asarray(difference, dtype="float64")
    if x.ndim != 1 or len(x) < 2 or not np.isfinite(x).all():
        raise ValueError("DM requires complete finite chronological daily differences")
    mean = float(x.mean())
    if hac_lag is None:
        variance = float(x.var(ddof=1))
    else:
        if hac_lag != 7:
            raise ValueError("Only frozen HAC7 sensitivity is permitted")
        centered = x - mean
        variance = float(centered @ centered / len(x))
        for lag in range(1, min(hac_lag, len(x) - 1) + 1):
            covariance = float(centered[lag:] @ centered[:-lag] / len(x))
            variance += 2 * (1 - lag / (hac_lag + 1)) * covariance
    if not math.isfinite(variance) or variance <= 0:
        return {"n_days": len(x), "mean_difference": mean, "statistic": None,
                "p_improvement": None, "p_deterioration": None, "p_two_sided": None,
                "variance": variance, "state": "UNDEFINED_VARIANCE"}
    statistic = math.sqrt(len(x)) * mean / math.sqrt(variance)
    p_improvement = 0.5 * math.erfc(-statistic / math.sqrt(2))
    p_deterioration = 0.5 * math.erfc(statistic / math.sqrt(2))
    return {"n_days": len(x), "mean_difference": mean, "statistic": statistic,
            "p_improvement": p_improvement, "p_deterioration": p_deterioration,
            "p_two_sided": min(1.0, 2 * min(p_improvement, p_deterioration)),
            "variance": variance, "state": "DEFINED"}


def holm(p_values):
    """Undefined tests keep their family slots and can never reject."""
    raw = np.array([1.0 if p is None else float(p) for p in p_values])
    if np.any(~np.isfinite(raw)) or np.any((raw < 0) | (raw > 1)):
        raise ValueError("Invalid p value")
    order = np.argsort(raw, kind="stable")
    adjusted = np.empty(len(raw))
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, (len(raw) - rank) * raw[index])
        adjusted[index] = min(1.0, running)
    return [None if p is None else float(adjusted[i]) for i, p in enumerate(p_values)]


def block_picks(n_days, block_length, day_keys=None):
    """Non-circular moving blocks; common day picks across every paired arm."""
    if block_length not in (1, 7) or n_days < block_length:
        raise ValueError("Only 1-day and 7-day frozen blocks are allowed")
    admissible = np.arange(n_days - block_length + 1)
    if day_keys is not None:
        parsed = [date.fromisoformat(d) for d in day_keys]
        if len(parsed) != n_days:
            raise ValueError("Day keys do not match bootstrap units")
        admissible = np.asarray([i for i in admissible if
            (parsed[i + block_length - 1] - parsed[i]).days == block_length - 1], dtype=int)
        if not len(admissible):
            raise ValueError("No complete consecutive-calendar block for this subset")
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    starts = rng.choice(admissible, size=(BOOTSTRAP_DRAWS, math.ceil(n_days / block_length)))
    picks = (starts[..., None] + np.arange(block_length)).reshape(BOOTSTRAP_DRAWS, -1)
    return picks[:, :n_days]


def paired_percent_interval(loss_a, loss_b, picks):
    a, b = np.asarray(loss_a, dtype="float64"), np.asarray(loss_b, dtype="float64")
    if a.shape != b.shape or a.ndim != 1 or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("Paired complete daily mean absolute losses are required")
    if np.any(a < 0) or np.any(b < 0):
        raise ValueError("Absolute losses cannot be negative")
    denominator = float(b.mean())
    effect = None if denominator <= 0 else 100.0 * float((a - b).mean()) / denominator
    sampled_b = b[picks].mean(axis=1)
    sampled_delta = (a[picks] - b[picks]).mean(axis=1)
    finite = np.isfinite(sampled_b) & (sampled_b > 0)
    draws = np.full(len(picks), np.nan)
    draws[finite] = 100.0 * sampled_delta[finite] / sampled_b[finite]
    interval = np.quantile(draws[finite], [0.025, 0.975], method="linear").tolist() if finite.any() else None
    return {"effect_percent_reference_mae": effect, "interval95_percent": interval,
            "reference_mae": denominator, "finite_draws": int(finite.sum()),
            "undefined_draws": int((~finite).sum()), "draws": draws,
            "bootstrap_nonpositive_effect_count": int(np.sum(draws[finite] <= 0)),
            "monte_carlo_resolution": 1 / BOOTSTRAP_DRAWS}


def check_days(day_keys, expected_start, expected_end):
    actual = [date.fromisoformat(d) for d in day_keys]
    start, end = date.fromisoformat(expected_start), date.fromisoformat(expected_end)
    expected = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    if actual != expected:
        raise ValueError("Missing, duplicate, shortened or unordered confirmation days")


def registered_daily_inference(daily_losses, day_keys, task, permit: ExecutionPermit, panel_identity):
    """Accept daily mean |error| arrays only after predictions and truth are sealed.

    Assemble daily losses outside this module with exact common target keys,
    region/horizon completeness and unit window weights, then verify their hash.
    This task never invokes this entry on real data.
    """
    require_execution(permit, scoring=True)
    if task == "news":
        family, start, end, expected_daily_keys = NEWS_FAMILY, "2026-03-01", "2026-09-30", 72
    elif task == "notice":
        family, start, end, expected_daily_keys = NOTICE_FAMILY, "2026-08-01", "2026-09-30", 8640
    else:
        raise ValueError("Unknown registered task")
    check_days(day_keys, start, end)
    # Future loss assembler supplies this attestation from the verified common
    # key grid and sealed prediction manifest. Never infer counts from losses.
    counts = np.asarray(panel_identity["daily_common_key_counts"])
    if counts.shape != (len(day_keys),) or not np.all(counts == expected_daily_keys):
        raise ValueError("Primary complete common region/horizon/time grid gate failed")
    for key in ("common_keys_sha256", "sealed_prediction_manifest_sha256"):
        value = panel_identity[key]
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError("Missing sealed common-key/prediction-manifest identity")
        int(value, 16)
    picks = {block: block_picks(len(day_keys), block) for block in (1, 7)}
    reports = []
    for arm, reference in family:
        if arm not in daily_losses or reference not in daily_losses:
            undefined = {"n_days": len(day_keys), "mean_difference": None, "statistic": None,
                         "p_improvement": None, "p_deterioration": None, "p_two_sided": None,
                         "variance": None, "state": "NOT_EVALUABLE_INPUT_OR_COMPLETION_GATE"}
            reports.append({"arm": arm, "reference": reference,
                            "dm_p1": dict(undefined), "dm_hac7": dict(undefined),
                            "bootstrap": {block: {"interval95_percent": None,
                                                  "effect_percent_reference_mae": None,
                                                  "state": "NOT_EVALUABLE"} for block in (1, 7)}})
            continue
        a = np.asarray(daily_losses[arm], dtype="float64")
        b = np.asarray(daily_losses[reference], dtype="float64")
        if len(a) != len(day_keys) or len(b) != len(day_keys):
            raise ValueError("Daily arrays do not match frozen dates")
        reports.append({"arm": arm, "reference": reference,
                        "dm_p1": dm_daily(a - b), "dm_hac7": dm_daily(a - b, 7),
                        "bootstrap": {block: paired_percent_interval(a, b, picks[block]) for block in (1, 7)}})
    adjusted = holm([r["dm_p1"]["p_two_sided"] for r in reports])
    hac_adjusted = holm([r["dm_hac7"]["p_two_sided"] for r in reports])
    for report, p, hac_p in zip(reports, adjusted, hac_adjusted):
        report["primary_two_sided_holm_p"] = p
        report["sensitivity_hac7_two_sided_holm_p"] = hac_p
        mean = report["dm_p1"]["mean_difference"]
        if p is None:
            report["primary_decision"] = "NOT_EVALUABLE"
        else:
            report["primary_decision"] = ("CONDITIONAL_IMPROVEMENT" if mean < 0 else "CONDITIONAL_DETERIORATION") if p < .05 else "NO_RELIABLE_INCREMENT_DETECTED"
        seven = report["bootstrap"][7]["interval95_percent"]
        one = report["bootstrap"][1]["interval95_percent"]
        report["primary_interval_bound_excludes_improvements_larger_than_percent"] = None if one is None else max(0.0, -one[0])
        report["seven_day_bound_excludes_improvements_larger_than_percent"] = None if seven is None else max(0.0, -seven[0])
        expected_sign = -1 if mean is not None and mean < 0 else 1
        report["interval_direction_agrees"] = {block: (None if report["bootstrap"][block]["interval95_percent"] is None else
            (report["bootstrap"][block]["interval95_percent"][1] < 0 if expected_sign < 0 else report["bootstrap"][block]["interval95_percent"][0] > 0)) for block in (1, 7)}
        report["primary_direction_robust"] = bool(p is not None and p < .05 and hac_p is not None and hac_p < .05
            and all(value is True for value in report["interval_direction_agrees"].values()))
    return {"task": task, "family_size": len(family), "reports": reports,
            "paired_day_picks": picks, "panel_identity": panel_identity, "equivalence_test": "NOT_REGISTERED"}


def secondary_daily_inference(daily_losses, contrasts, day_keys, permit: ExecutionPermit):
    """Frozen contrast list is supplied by protocol, never selected from losses.

    Allows registered matched-origin/first-seven-days subsets after their common
    key mask is sealed. It reports raw tests only and cannot confirm the primary.
    """
    require_execution(permit, scoring=True)
    parsed = [date.fromisoformat(d) for d in day_keys]
    if len(parsed) < 7 or len(set(parsed)) != len(parsed) or parsed != sorted(parsed):
        raise ValueError("Secondary dates must be unique, ordered and adequate for 7-day blocks")
    # Matched-origin subsets may have gaps. Seven-day blocks must still span
    # seven consecutive calendar dates, never seven arbitrary retained units.
    gaps = [(a.isoformat(), b.isoformat()) for a, b in zip(parsed, parsed[1:]) if (b - a).days != 1]
    picks = {1: block_picks(len(day_keys), 1, day_keys)}
    try:
        picks[7] = block_picks(len(day_keys), 7, day_keys)
    except ValueError:
        picks[7] = None
    reports = []
    for arm, reference in contrasts:
        a, b = np.asarray(daily_losses[arm], dtype="float64"), np.asarray(daily_losses[reference], dtype="float64")
        if len(a) != len(day_keys) or len(b) != len(day_keys):
            raise ValueError("Secondary arrays must share the exact frozen matched dates")
        hac = dm_daily(a - b, 7) if not gaps else {
            "state": "UNDEFINED_SECONDARY_DATE_GAPS", "statistic": None, "p_two_sided": None,
            "p_improvement": None, "p_deterioration": None}
        reports.append({"arm": arm, "reference": reference, "status": "SECONDARY_ONLY",
                        "dm_p1": dm_daily(a - b), "dm_hac7": hac,
                        "bootstrap": {block: (paired_percent_interval(a, b, picks[block]) if picks[block] is not None else
                            {"interval95_percent": None, "state": "UNDEFINED_NO_COMPLETE_SEVEN_CALENDAR_DAY_BLOCK"}) for block in (1, 7)}})
    return {"reports": reports, "paired_day_picks": picks, "date_gaps": gaps,
            "primary_confirmation": False, "equivalence_test": "NOT_REGISTERED"}


def notice_clipping_counts(raw_prediction, final_prediction, lower, upper):
    """Pure helper; future authorized diagnostics preserve RF2 clipping bounds."""
    raw, final = np.asarray(raw_prediction), np.asarray(final_prediction)
    lo, hi = np.broadcast_to(lower, raw.shape), np.broadcast_to(upper, raw.shape)
    if raw.shape != final.shape or not np.isfinite(raw).all() or not np.isfinite(final).all():
        raise ValueError("Clipping diagnostics require matching finite predictions")
    if np.any(lo > hi):
        raise ValueError("Invalid clipping bounds")
    return {"eligible_predictions": int(raw.size),
            "raw_below_lower": int(np.sum(raw < lo)), "raw_above_upper": int(np.sum(raw > hi)),
            "final_lower_hits": int(np.sum(final == lo)), "final_upper_hits": int(np.sum(final == hi))}


if __name__ == "__main__":
    raise SystemExit("CONF is design-only. Real scoring requires a separate authorized execution task.")
