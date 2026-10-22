"""Frozen B5: score saved B4 corrected predictions only; no model fitting.

Writes exclusively to sibling sensitivity/. Run with python -B after B5 freeze.
"""
from __future__ import annotations

import gc
import hashlib
import json
import math
import resource
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[2]
AUTO = PROJ / "autopilot"
B4 = AUTO / "q1_audits/B4"
OUT = HERE / "sensitivity"
sys.path.insert(0, str(PROJ.parent / "notice_window_relation_repair_20260925"))
sys.path.insert(0, str(AUTO))
import evaluate_repair as er
import secondary_metrics as sm

ARMS = tuple("NRLP")
CONTRASTS = (("L", "N"), ("R", "N"), ("P", "N"), ("L", "P"), ("L", "R"))
KEYS = list(er.KEYS)
LENGTHS = (1, 3, 7, 14)
DRAWS, SEED, ATOL = 2000, 20260925, 1e-8
er.ARMS, er.CONTRASTS = ARMS, CONTRASTS
INPUT_HASHES = {}
CHECKS = []


def require(test, message):
    if not test:
        raise RuntimeError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def register(path, expected=None):
    path = Path(path)
    value = sha(path)
    if expected is not None:
        require(value == expected, f"input hash mismatch: {path}")
    INPUT_HASHES[str(path)] = value
    return path


def read(path):
    return json.loads(Path(path).read_text())


def clean(obj):
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return clean(obj.tolist())
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return float(obj) if np.isfinite(obj) else None
    if isinstance(obj, Path):
        return str(obj)
    return obj


def write(name, obj):
    path = OUT / name
    require(not path.exists(), f"refusing overwrite: {path}")
    path.write_text(json.dumps(clean(obj), indent=2, allow_nan=False) + "\n")


def compare(name, actual, expected, atol=ATOL):
    a, b = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    passed = a.shape == b.shape and np.allclose(a, b, rtol=0, atol=atol, equal_nan=True)
    maxdiff = float(np.nanmax(np.abs(a - b))) if a.size and a.shape == b.shape else None
    CHECKS.append(dict(check=name, passed=bool(passed), max_abs_difference=maxdiff, atol=atol))
    require(passed, f"parity failed: {name}: {maxdiff}")


def rss():
    v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(v if sys.platform == "darwin" else v * 1024)


def quantiles(values):
    finite = np.asarray(values)[np.isfinite(values)]
    return dict(ci90=np.quantile(finite, [.05, .95], method="linear").tolist() if len(finite) else [None, None],
                ci95=np.quantile(finite, [.025, .975], method="linear").tolist() if len(finite) else [None, None],
                finite_draws=len(finite), undefined_draws=len(values) - len(finite))


def divide(a, b):
    a, b = np.broadcast_arrays(np.asarray(a, float), np.asarray(b, float))
    return np.divide(a, b, out=np.full(a.shape, np.nan), where=b != 0)


def load_fold(fold, seal, q90):
    pred_path = register(B4 / "corrected/predictions" / f"{fold}.parquet", seal["files"][fold]["sha256"])
    pred = pd.read_parquet(pred_path, columns=KEYS + list(ARMS)).sort_values(KEYS, kind="mergesort").reset_index(drop=True)
    require(len(pred) == seal["files"][fold]["rows"], "prediction row count differs")
    if fold == "C":
        path = register(AUTO / "windows/C/truth.parquet", read(AUTO / "windows/C/build_receipt.json")["truth_sha256"])
        truth = pd.read_parquet(path, columns=KEYS + ["y_true", "weight", "event_replay_flag", "event_block_id"])
    else:
        _, start, end = next(v for v in er.FOLDS if v[0] == fold)
        months = pd.period_range(start, end, freq="M").astype(str).tolist()
        meta = AUTO / "q1_audits/B1b/development_metadata.parquet"
        if str(meta) not in INPUT_HASHES:
            register(meta, read(AUTO / "q1_audits/B1b/OUTPUT_MANIFEST.json")["files"][meta.name]["sha256"])
        truth = pd.read_parquet(meta, columns=KEYS + ["y_true", "weight", "event_replay_flag"], filters=[("bank_month", "in", months)])
        event_parts = []
        for month in months:
            path = register(er.BANK / f"{month}.parquet")
            event_parts.append(pd.read_parquet(path, columns=KEYS + ["event_block_id"]))
        event = pd.concat(event_parts, ignore_index=True)
        for c in ("issue_time", "target_time"):
            truth[c] = pd.to_datetime(truth[c], utc=True)
            event[c] = pd.to_datetime(event[c], utc=True)
        n = len(truth)
        truth = truth.merge(event, on=KEYS, validate="one_to_one", how="inner")
        require(len(truth) == n == len(event), "development event-key universe differs")
        require(truth.event_replay_flag.isin([0, 1]).all(), "invalid replay flag")
        compare(f"{fold}/weights", truth.weight, np.where(truth.event_replay_flag == 1, 1., 50.), 0)
        truth["weight"] = np.where(truth.event_replay_flag == 1, 1., 50.)
        del event, event_parts
    for frame in (pred, truth):
        for c in ("issue_time", "target_time"):
            frame[c] = pd.to_datetime(frame[c], utc=True)
    rows = pred.merge(truth, on=KEYS, how="inner", validate="one_to_one")
    require(len(rows) == len(pred) == len(truth), "prediction/truth universe differs")
    if fold == "C":
        require(rows.weight.eq(1).all(), "C weight differs")
    require(np.isfinite(rows.y_true).all(), "nonfinite truth")
    rows["fold"], rows["q90"] = fold, q90
    rows["local_day"] = rows.target_time.dt.tz_convert("Australia/Brisbane").dt.strftime("%Y-%m-%d")
    for a in ARMS:
        require(np.isfinite(rows[a]).all(), "nonfinite prediction")
        rows[f"{a}_ae"] = np.abs(rows[a].to_numpy("float64") - rows.y_true.to_numpy("float64"))
    return rows


def rebuild():
    seal = read(register(B4 / "corrected/candidate_seal.json"))
    q90 = read(register(B4 / "SCORE_INPUT_MANIFEST.json"))["q90"]
    by_scope, coverage, event_tables, fold_records = {}, {}, {}, {}
    for scope, folds in (("development", [f[0] for f in er.FOLDS]), ("C", ["C"])):
        all_days, all_events, per_fold, cv = [], [], {}, []
        for fold in folds:
            print(f"rebuild {fold}", flush=True)
            rows = load_fold(fold, seal, q90[fold])
            masks = er.band_masks(rows)
            days = er._day_units(rows, masks)
            events, cov = er._event_units(rows)
            events["fold"] = fold
            events.to_csv(OUT / f"{fold}_event_units.csv", index=False)
            per_fold[fold] = dict(rows=len(rows), event_coverage=cov, peak_rss_bytes=rss())
            all_days.append(days)
            all_events.append(events)
            cv.append(cov)
            del rows, masks, events, days
            gc.collect()
        days = pd.concat(all_days, ignore_index=True).sort_values(["band", "fold", "local_day"], kind="mergesort")
        days.to_csv(OUT / f"{scope}_day_units.csv", index=False)
        saved = pd.read_csv(register(B4 / f"scoring/corrected/{scope if scope == 'development' else 'C'}_day_units.csv"))
        saved = saved.sort_values(["band", "fold", "local_day"], kind="mergesort").reset_index(drop=True)
        new = days.reset_index(drop=True)
        require(new[["band", "fold", "local_day"]].equals(saved[["band", "fold", "local_day"]]), "daily identity differs")
        for col in ["weight"] + [f"{a}_sae" for a in ARMS]:
            compare(f"{scope}/daily/{col}", new[col], saved[col])
        events = pd.concat(all_events, ignore_index=True)
        # A connected event can touch a fold boundary; aggregate sums then divide
        # to preserve the evaluator's pooled event identity and row weighting.
        for a in ARMS:
            events[f"{a}_sum"] = events[f"{a}_ae"] * events.rows
        events = events.groupby("event_block_id", as_index=False)[["rows"] + [f"{a}_sum" for a in ARMS]].sum()
        for a in ARMS:
            events[f"{a}_ae"] = events[f"{a}_sum"] / events.rows
        events = events.sort_values("event_block_id").reset_index(drop=True)
        events.to_csv(OUT / f"{scope}_event_units.csv", index=False)
        cvtotal = {k: sum(v[k] for v in cv) for k in cv[0] if k != "severe_connected_events"}
        cvtotal["severe_connected_events"] = len(events)
        cvtotal["sum_fold_event_counts"] = sum(v["severe_connected_events"] for v in cv)
        by_scope[scope], coverage[scope], event_tables[scope], fold_records[scope] = days, cvtotal, events, per_fold
    return by_scope, coverage, event_tables, fold_records


def picks_for(n, length):
    length = min(length, n)
    k = int(np.ceil(n / length))
    starts = np.random.default_rng(SEED).integers(0, n - length + 1, size=(DRAWS, k))
    return (starts[:, :, None] + np.arange(length)[None, None, :]).reshape(DRAWS, -1)[:, :n]


def tail_result(absolute, pct, reference_mae, name, mode):
    margin = .005 * reference_mae
    if mode == "fixed_reference":
        high, low = int((absolute >= margin).sum()), int((absolute <= -margin).sum())
    else:
        high, low = int((pct >= .5).sum()), int((pct <= -.5).sum())
    count = max(high, low) if name == "H1_C" else low
    q = quantiles(pct)
    ci = q["ci90"]
    return dict(estimand=mode, **q, reference_mae=reference_mae, absolute_margin=margin,
                tail_count=count, tail_denominator=DRAWS, tail_display=f"{count}/{DRAWS}",
                tail_fraction=count / DRAWS, monte_carlo_resolution=1 / DRAWS,
                tail_counts=dict(draws_ge_positive_margin=high, draws_le_negative_margin=low),
                ci90_inside_inclusive_percent_margin=bool(ci[0] >= -.5 and ci[1] <= .5) if name == "H1_C" else None,
                ci90_strictly_inside_percent_margin=bool(ci[0] > -.5 and ci[1] < .5) if name == "H1_C" else None)


def holm(hyp):
    order = sorted(hyp, key=lambda name: hyp[name]["tail_fraction"])
    running, rejected = 0., True
    for i, name in enumerate(order):
        v = hyp[name]["tail_fraction"]
        running = min(1., max(running, (len(order) - i) * v))
        threshold = .05 / (len(order) - i)
        rejected = rejected and v <= threshold
        hyp[name].update(holm_tail_fraction=running, holm_supported=bool(rejected),
                         holm_step_threshold=threshold, holm_order_index=i + 1,
                         reading_holds=bool(rejected and (name != "H1_C" or hyp[name]["ci90_strictly_inside_percent_margin"])))
    return order


def battery(days_by_scope):
    output, hypotheses, lodo_rows, lodo_ranges, dm_rows, calendar = {}, {}, [], {}, [], {}
    oldscore = read(register(B4 / "scoring/corrected/SCORE.json"))
    for scope, days in days_by_scope.items():
        n = int(days.band.eq("all").sum())
        cal = days.loc[days.band == "all", ["fold", "local_day"]].reset_index(drop=True)
        diffs = pd.to_datetime(cal.local_day).diff().dt.days
        irregular = cal.loc[(diffs.notna()) & (diffs != 1)].copy()
        irregular["previous_day"] = cal.local_day.shift(1).loc[irregular.index]
        irregular["day_difference"] = diffs.loc[irregular.index]
        calendar[scope] = dict(blocks=n, first_day=cal.local_day.iloc[0], last_day=cal.local_day.iloc[-1],
                               nonunit_calendar_steps=irregular.to_dict("records"), fold_stratified=False)
        output[scope] = {}
        lodo_ranges[scope] = {}
        for length in LENGTHS:
            picks = picks_for(n, length)
            np.save(OUT / f"{scope}_{length}d_picks.npy", picks)
            arrays, scored = {}, {}
            for band in er.BANDS:
                block = days.loc[days.band == band].reset_index(drop=True)
                require(len(block) == n, "zero-band days omitted")
                w = block.weight.to_numpy(float)
                den = w[picks].sum(axis=1)
                mae = {a: float(block[f"{a}_sae"].sum() / w.sum()) if w.sum() else np.nan for a in ARMS}
                record = dict(weight=float(w.sum()), zero_weight_days=int((w == 0).sum()), mae=mae, contrasts={})
                for first, second in CONTRASTS:
                    name = f"{first}-{second}"
                    delta = (block[f"{first}_sae"] - block[f"{second}_sae"]).to_numpy(float)
                    num = delta[picks].sum(axis=1)
                    absolute = divide(num, den)
                    fixed = 100 * divide(absolute, mae[second])
                    ratio = 100 * divide(num, block[f"{second}_sae"].to_numpy(float)[picks].sum(axis=1))
                    estimate = float(delta.sum() / w.sum()) if w.sum() else np.nan
                    for kind, arr in (("absolute", absolute), ("fixed_reference_percent", fixed), ("paired_ratio_percent", ratio)):
                        arrays[f"{band}__{name}__{kind}"] = arr
                    entry = dict(estimate=estimate, **quantiles(absolute),
                                 fixed_reference_percent=dict(estimate=100 * estimate / mae[second], **quantiles(fixed)),
                                 paired_ratio_percent=dict(estimate=100 * estimate / mae[second], **quantiles(ratio)))
                    record["contrasts"][name] = entry
                    if length == 1:
                        if scope == "development" or band == "all":
                            old = oldscore[scope]["bands"][band]["contrasts"][name]
                            compare(f"{scope}/{band}/{name}/estimate", estimate, old["estimate"])
                            compare(f"{scope}/{band}/{name}/ci95", entry["ci95"], old["ci95"])
                        keep_w = w.sum() - w
                        lod = divide(delta.sum() - delta, keep_w)
                        fixed_lod = 100 * divide(lod, mae[second])
                        base = block[f"{second}_sae"].to_numpy(float)
                        ratio_lod = 100 * divide(delta.sum() - delta, base.sum() - base)
                        for i in range(n):
                            lodo_rows.append(dict(scope=scope, band=band, contrast=name, fold=block.fold.iloc[i],
                                omitted_day=block.local_day.iloc[i], omitted_weight=float(w[i]), estimate=lod[i],
                                fixed_reference_percent=fixed_lod[i], paired_ratio_percent=ratio_lod[i]))
                        lodo_ranges[scope].setdefault(band, {})[name] = dict(
                            absolute=range_record(lod, block), fixed_reference_percent=range_record(fixed_lod, block),
                            paired_ratio_percent=range_record(ratio_lod, block), reference_mae=mae[second])
                        selected = w > 0
                        dd = sm.dm(delta[selected] / w[selected])
                        dm_rows.append(dict(scope=scope, band=band, contrast=name, **dd,
                            aggregation="equal mean of nonempty Brisbane target-day weighted MAE differences",
                            covariance="centred Newey-West Bartlett; automatic floor(4*(T/100)^(2/9))",
                            alternative="two-sided daily expected loss equality", multiplicity_adjustment="none; descriptive secondary"))
                scored[band] = record
            np.savez_compressed(OUT / f"{scope}_{length}d_draws.npz", **arrays)
            if length == 1:
                olddraws = np.load(register(B4 / f"scoring/corrected/{scope}_draws.npz"))
                for key in olddraws.files:
                    compare(f"{scope}/1d_saved_draws/{key}", arrays[f"{key}__absolute"], olddraws[key])
            output[scope][str(length)] = scored
            if scope == "C":
                hypotheses[str(length)] = {}
                for mode, key in (("fixed_reference", "fixed_reference_percent"), ("paired_ratio", "paired_ratio_percent")):
                    hyp = {}
                    for name, second in (("H1_C", "N"), ("H2_C", "P")):
                        contrast = f"L-{second}"
                        abs_draw = arrays[f"all__{contrast}__absolute"]
                        pct = arrays[f"all__{contrast}__{key}"]
                        hyp[name] = tail_result(abs_draw, pct, scored["all"]["mae"][second], name, mode)
                        hyp[name].update(contrast=contrast, estimate=scored["all"]["contrasts"][contrast][key]["estimate"],
                                         absolute_estimate=scored["all"]["contrasts"][contrast]["estimate"],
                                         absolute_ci90=scored["all"]["contrasts"][contrast]["ci90"])
                    order = holm(hyp)
                    hypotheses[str(length)][mode] = dict(hypotheses=hyp, family_holm=order)
                    if length == 1 and mode == "fixed_reference":
                        for name in hyp:
                            old = oldscore["C"]["hypotheses"][name]
                            for field in ("tail_count", "holm_tail_fraction", "holm_supported", "reading_holds"):
                                compare(f"C/{name}/{field}", hyp[name][field], old[field], 0)
                            compare(f"C/{name}/ci90", hyp[name]["absolute_ci90"], old["ci90"])
            del arrays, picks
        print(f"scored {scope}, peak {rss()} bytes", flush=True)
    pd.DataFrame(lodo_rows).to_csv(OUT / "leave_one_day_out.csv", index=False)
    pd.DataFrame(dm_rows).to_csv(OUT / "dm_statistics.csv", index=False)
    robust = {}
    for mode in ("fixed_reference", "paired_ratio"):
        fail = [length for length in LENGTHS if not hypotheses[str(length)][mode]["hypotheses"]["H1_C"]["ci90_inside_inclusive_percent_margin"]]
        robust[mode] = dict(robust_to_block_length=not fail, failing_lengths=fail, margin_percent=[-.5, .5])
    robust["unqualified_robustness"] = all(robust[m]["robust_to_block_length"] for m in ("fixed_reference", "paired_ratio"))
    return dict(intervals=output, hypotheses=hypotheses, H1_robustness=robust, leave_one_day_out_ranges=lodo_ranges,
                dm_statistics=dm_rows, calendar=calendar)


def range_record(values, block):
    valid = np.flatnonzero(np.isfinite(values))
    if not len(valid):
        return dict(min=None, max=None, finite=0, undefined=len(values))
    imin, imax = valid[np.argmin(values[valid])], valid[np.argmax(values[valid])]
    return dict(min=float(values[imin]), max=float(values[imax]), finite=len(valid), undefined=len(values) - len(valid),
                min_omitted_fold=block.fold.iloc[imin], min_omitted_day=block.local_day.iloc[imin],
                max_omitted_fold=block.fold.iloc[imax], max_omitted_day=block.local_day.iloc[imax])


def event_scores(event_tables, coverage):
    results = {}
    for scope, events in event_tables.items():
        n = len(events)
        records, arrays = [], {}
        if n:
            picks = np.random.default_rng(SEED).integers(0, n, size=(DRAWS, n))
            np.save(OUT / f"{scope}_event_picks.npy", picks)
            sizes = events.rows.to_numpy(float)
            for first, second in CONTRASTS:
                name = f"{first}-{second}"
                per_event = (events[f"{first}_ae"] - events[f"{second}_ae"]).to_numpy(float)
                for estimand, equal in (("severe_event_equal_mae", True), ("severe_connected_row_mae", False)):
                    if equal:
                        draws, estimate = per_event[picks].mean(axis=1), per_event.mean()
                    else:
                        draws = (per_event[picks] * sizes[picks]).sum(axis=1) / sizes[picks].sum(axis=1)
                        estimate = np.average(per_event, weights=sizes)
                    arrays[f"{name}__{estimand}"] = draws
                    records.append(dict(contrast=name, estimand=estimand, estimate=estimate, **quantiles(draws),
                                        connected_events=n, rows=int(sizes.sum()), draws=DRAWS, seed=SEED))
            np.savez_compressed(OUT / f"{scope}_event_draws.npz", **arrays)
        results[scope] = dict(coverage=coverage[scope], contrasts=records,
                             interpretation="Connected-event identity and replay eligibility unchanged; event-equal and eligible-row weighting are distinct estimands.")
    return results


def main():
    started = time.time()
    require(not OUT.exists(), "sensitivity output exists; do not overwrite")
    freeze = read(HERE / "FREEZE.json")
    require(freeze["spec_sha256"] == sha(HERE / "SPEC.md"), "B5 freeze mismatch")
    OUT.mkdir()
    for path in (HERE / "SPEC.md", HERE / "FREEZE.json", Path(__file__), Path(er.__file__), Path(sm.__file__),
                 AUTO / "score_window.py", AUTO / "score_v2g.py", B4 / "score.py", B4 / "SCORE_VALIDATION.json",
                 B4 / "SCORE_INPUT_MANIFEST.json", AUTO / "windows/C/build_receipt.json",
                 AUTO / "q1_audits/B1b/OUTPUT_MANIFEST.json"):
        register(path)
    require(er.BOOT_DRAWS == DRAWS and er.BOOT_SEED == SEED, "scorer constants differ")
    days, coverage, events, folds = rebuild()
    result = battery(days)
    result.update(severe_events=event_scores(events, coverage), fold_rebuild=folds,
                  bootstrap_draws=DRAWS, bootstrap_seed=SEED, lengths=list(LENGTHS),
                  input_version="B4 corrected saved three-seed ensemble predictions",
                  no_refitting=True, software=dict(python=sys.version, numpy=np.__version__, pandas=pd.__version__, pyarrow=pyarrow.__version__),
                  limitations=["Moving blocks require approximate dependence stability and cannot establish uniform finite-sample coverage.",
                    "Noncircular moving blocks underweight endpoints; development pools fold/day sequence without stratification, matching scorer.",
                    "Tail fractions reproduce the frozen operational rule; bootstrap calibration is not independently established.",
                    "DM uses B4 all-row loss universe, unlike legacy P5-present secondary DM, and uses actual automatic lags.",
                    "No label-removal or refit-stability experiment is performed; original B1c 5/20 cannot be transferred to B4.",
                    "Severe-event equal weighting and eligible row weighting differ from all-row severe-band weighting."])
    drift = []
    for path, digest in INPUT_HASHES.items():
        if sha(path) != digest:
            drift.append(path)
    require(not drift, f"input drift: {drift}")
    result.update(runtime_seconds=time.time() - started, peak_rss_bytes=rss(),
                  parity_passed=all(c["passed"] for c in CHECKS), input_hashes_unchanged=True)
    require(rss() < 2 * 1024**3, "RSS over 2 GiB")
    write("INPUT_MANIFEST.json", dict(files=INPUT_HASHES))
    write("VALIDATION.json", dict(passed=all(c["passed"] for c in CHECKS), checks=CHECKS,
                                  input_recheck_passed=True, peak_rss_bytes=rss()))
    write("RESULT.json", result)
    manifest = {str(p.relative_to(OUT)): dict(sha256=sha(p), bytes=p.stat().st_size) for p in sorted(OUT.iterdir()) if p.is_file()}
    write("OUTPUT_MANIFEST.json", dict(files=manifest))
    print(json.dumps(clean(dict(state="COMPLETE", H1_robustness=result["H1_robustness"],
                                peak_rss_bytes=rss(), runtime_seconds=result["runtime_seconds"])), indent=2), flush=True)


if __name__ == "__main__":
    main()
