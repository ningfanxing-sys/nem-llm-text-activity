'Score saved forecasts after checking both forecast seals.'
from __future__ import annotations

import gc
import hashlib
import json
from pathlib import Path
import resource
import sys
import time

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[2]
AUTO = PROJ / 'forecasting'
sys.path.insert(0, str(PROJ.parent / 'notice_comparison'))
sys.path.insert(0, str(AUTO))
import evaluate_notice_records as er
import score_window as sw

KEYS = list(er.KEYS)
ARMS = tuple("NRLP")
SEEDS = (20260919, 20260920, 20260921)
FOLDS = tuple(f[0] for f in er.FOLDS)
ALL_FOLDS = FOLDS + ("C",)
CONTRASTS = (("L", "N"), ("R", "N"), ("P", "N"), ("L", "P"), ("L", "R"))
BOOT_DRAWS, BOOT_SEED = 2000, 20260925
PARITY_ATOL = 1e-8
META = AUTO / 'studies/B1b/development_metadata.parquet'
TRUTH_C = AUTO / "windows/C/truth.parquet"
OUT = HERE / "scoring"
er.ARMS = ARMS
er.CONTRASTS = CONTRASTS


def require(test, message):
    if not test:
        raise RuntimeError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def clean(obj):
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return float(obj) if np.isfinite(obj) else None
    if isinstance(obj, Path):
        return str(obj)
    return obj


def write(path, obj):
    path = Path(path)
    require(path.resolve().is_relative_to(HERE), 'output outside forecast_replication')
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.exists(), f"refusing to overwrite scoring evidence: {path}")
    path.write_text(json.dumps(clean(obj), indent=2, allow_nan=False) + "\n")


def rss_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def preflight():
    require(not (HERE / "SCORES.json").exists(), 'forecast_replication already scored')
    freeze = read(HERE / "FREEZE.json")
    require(freeze["spec_sha256"] == sha(HERE / "SPEC.md"), 'forecast_replication specification hash drift')
    require(read(HERE / "IDENTITY.json")["passed"] is True, "identity gate has not passed")
    require(er.BOOT_SEED == BOOT_SEED and er.BOOT_DRAWS == BOOT_DRAWS, "sealed bootstrap constants drift")
    inputs = [HERE / "SPEC.md", HERE / "FREEZE.json", HERE / "IDENTITY.json", Path(__file__),
              Path(er.__file__), Path(sw.__file__), AUTO / "score_v2g.py", META, TRUTH_C,
              AUTO / "windows/C/build_receipt.json", AUTO / "windows/C/run/candidate_seal.json",
              AUTO / "evaluation_v2g/metrics.csv", AUTO / "evaluation_v2g/paired_intervals.csv",
              AUTO / "windows/C/evaluation/metrics.csv", AUTO / "windows/C/evaluation/paired_intervals.csv",
              AUTO / "windows/C/evaluation/WINDOW_RESULT.json",
              AUTO / 'studies/B1b/OUTPUT_MANIFEST.json',
              AUTO / 'studies/B1c/placebo_summary.csv', AUTO / 'studies/B1c/RESULT.json',
              AUTO / 'studies/B1c/OUTPUT_MANIFEST.json']
    entries = {}
    for condition in ("original", 'aligned'):
        seal_path = HERE / condition / "candidate_seal.json"
        seal = read(seal_path)
        require(seal.get("test_scored_before_bank_seal") is False, f"{condition}: no prescore seal assertion")
        require(set(seal["files"]) == set(ALL_FOLDS), f"{condition}: candidate fold universe mismatch")
        entries[condition] = {}
        inputs.append(seal_path)
        for fold in ALL_FOLDS:
            e = seal["files"][fold]
            expected = HERE / condition / "predictions" / f"{fold}.parquet"
            path = Path(e["path"])
            if not path.is_absolute():
                options = [PROJ / path, HERE / path, HERE / condition / path]
                path = next((p for p in options if p.resolve() == expected.resolve()), path)
            require(path.resolve() == expected.resolve(), f"{condition}/{fold}: candidate path differs")
            require(sha(path) == e["sha256"], f"{condition}/{fold}: candidate hash differs")
            schema = pq.read_schema(path)
            prediction_names = list(ARMS) + [f"{a}_s{s}" for a in ARMS for s in SEEDS]
            require(set(KEYS + prediction_names) <= set(schema.names), "missing candidate columns")
            require(not set(schema.names).intersection(er.FORBIDDEN), "candidate includes truth/weights")
            require(pq.ParquetFile(path).metadata.num_rows == e["rows"], "sealed candidate row count differs")
            entries[condition][fold] = dict(e, path=str(path))
            inputs.append(path)
    meta_manifest = read(AUTO / 'studies/B1b/OUTPUT_MANIFEST.json')
    require(sha(META) == meta_manifest["files"][META.name]["sha256"], "B1b development metadata hash differs")
    require(sha(TRUTH_C) == read(AUTO / "windows/C/build_receipt.json")["truth_sha256"], "C truth hash differs")
    placebo_manifest = read(AUTO / 'studies/B1c/OUTPUT_MANIFEST.json')
    for name in ("placebo_summary.csv", "RESULT.json"):
        require(sha(AUTO / 'studies/B1c' / name) == placebo_manifest["files"][name]["sha256"], "B1c source hash differs")
    q90 = {}
    for fold in FOLDS:
        path = AUTO / 'run_forecasts/receipts' / f"{fold}.json"
        q90[fold] = float(read(path)["q90"])
        inputs.append(path)
    q90["C"] = float(read(AUTO / "windows/C/run/candidate_seal.json")["prior_q90"])
    hashes = {str(p): sha(p) for p in inputs}
    write(HERE / "SCORE_INPUT_MANIFEST.json", dict(files=hashes, q90=q90))
    return entries, q90, hashes


def candidate(entry):
    pred = pd.read_parquet(entry["path"])
    for c in ("issue_time", "target_time"):
        pred[c] = pd.to_datetime(pred[c], utc=True)
    require(not pred.duplicated(KEYS).any(), "duplicate prediction key")
    for a in ARMS:
        seeds = pred[[f"{a}_s{s}" for s in SEEDS]].to_numpy(dtype="float64")
        values = pred[a].to_numpy(dtype="float32")
        require(np.isfinite(seeds).all() and np.isfinite(values).all(), "nonfinite candidate")
        require(np.array_equal(seeds.mean(axis=1).astype("float32"), values), "ensemble arithmetic differs")
    return pred.sort_values(KEYS, kind="mergesort").reset_index(drop=True)


def joined_rows(condition, fold, entry, q90):
    pred = candidate(entry)
    if fold == "C":
        truth = pd.read_parquet(TRUTH_C, columns=KEYS + ["y_true", "weight"])
    else:
        f = next(v for v in er.FOLDS if v[0] == fold)
        months = pd.period_range(f[1], f[2], freq="M").astype(str).tolist()
        truth = pd.read_parquet(META, columns=KEYS + ["y_true", "weight", "event_replay_flag"],
                                filters=[("bank_month", "in", months)])
        require(truth.event_replay_flag.isin([0, 1]).all(), "invalid event replay flag")
        expected_weight = np.where(truth.event_replay_flag.to_numpy() == 1, 1., 50.)
        require(np.array_equal(truth.weight.to_numpy(), expected_weight), "development weights differ")
        truth["weight"] = expected_weight
    for c in ("issue_time", "target_time"):
        truth[c] = pd.to_datetime(truth[c], utc=True)
    rows = pred.merge(truth, on=KEYS, how="inner", validate="one_to_one")
    require(len(rows) == len(pred) == len(truth), f"{condition}/{fold}: truth key universe mismatch")
    require(np.isfinite(rows.y_true).all(), "nonfinite truth")
    if fold == "C":
        require(rows.weight.eq(1).all(), "C weights must be 1")
    rows["fold"] = fold
    rows["q90"] = q90
    rows["local_day"] = rows.target_time.dt.tz_convert("Australia/Brisbane").dt.strftime("%Y-%m-%d")
    for a in ARMS:
        rows[f"{a}_ae"] = np.abs(rows[a].to_numpy("float64") - rows.y_true.to_numpy("float64"))
    return rows


def descriptive(rows, masks):
    result = {}
    for band, mask in masks.items():
        sub = rows.loc[mask]
        weights = sub.weight.to_numpy("float64")
        y = sub.y_true.to_numpy("float64")
        den = weights.sum()
        mae = {a: float(np.sum(weights * sub[f"{a}_ae"].to_numpy()) / den) if den else np.nan for a in ARMS}
        sums = {a: float(np.sum(weights * sub[f"{a}_ae"].to_numpy())) for a in ARMS}
        seed_metrics = {}
        for seed in SEEDS:
            seed_mae = {a: float(np.sum(weights * np.abs(sub[f"{a}_s{seed}"].to_numpy("float64") - y)) / den)
                        if den else np.nan for a in ARMS}
            seed_metrics[str(seed)] = dict(mae=seed_mae, contrasts={f"{a}-{b}": seed_mae[a] - seed_mae[b] for a, b in CONTRASTS})
        result[band] = dict(rows=len(sub), weight=float(den), mae=mae, weighted_absolute_error=sums,
                            contrasts={f"{a}-{b}": mae[a] - mae[b] for a, b in CONTRASTS}, per_seed=seed_metrics)
    return result


def interval(draws):
    finite = draws[np.isfinite(draws)]
    return dict(ci95=np.quantile(finite, [.025, .975]).tolist() if len(finite) else [None, None],
                finite_draws=len(finite), undefined_draws=int((~np.isfinite(draws)).sum()))


def day_scores(days, bands):
    n = int((days.band == "all").sum())
    picks = np.random.default_rng(BOOT_SEED).integers(0, n, size=(BOOT_DRAWS, n))
    records, arrays = {}, {}
    for band in bands:
        block = days.loc[days.band == band]
        require(len(block) == n, "zero-band days were omitted")
        w = block.weight.to_numpy("float64")
        den = w[picks].sum(axis=1)
        mae = {a: float(block[f"{a}_sae"].sum() / w.sum()) if w.sum() else np.nan for a in ARMS}
        contrasts = {}
        for a, b in CONTRASTS:
            name = f"{a}-{b}"
            delta = (block[f"{a}_sae"] - block[f"{b}_sae"]).to_numpy("float64")
            num = delta[picks].sum(axis=1)
            draws = np.divide(num, den, out=np.full_like(num, np.nan), where=den > 0)
            arrays[f"{band}__{name}"] = draws
            contrasts[name] = dict(estimate=float(delta.sum() / w.sum()) if w.sum() else np.nan,
                                   **interval(draws), blocks=n, zero_weight_blocks=int((w == 0).sum()),
                                   bootstrap_draws=BOOT_DRAWS, bootstrap_seed=BOOT_SEED)
        records[band] = dict(mae=mae, weight=float(w.sum()), contrasts=contrasts)
    return records, arrays, picks


def hypotheses(rows, output):
    masks = er.band_masks(rows)
    hypotheses, arrays = {}, {}
    for name, second in (("H1_C", "N"), ("H2_C", "P")):
        block = sw.day_table(rows, masks["all"], "L", second)
        draws = sw.draws_day(block)
        require(np.isfinite(draws).all(), "undefined overall C draw")
        block.to_csv(output / f"{name}_day_blocks.csv", index=False)
        arrays[name] = draws
        estimate = float(block.d.sum() / block.w.sum())
        baseline_mae = float((rows.weight * rows[f"{second}_ae"]).sum() / rows.weight.sum())
        margin = .005 * baseline_mae
        high, low = int((draws >= margin).sum()), int((draws <= -margin).sum())
        count = max(high, low) if name == "H1_C" else low
        ci90 = np.quantile(draws, [.05, .95]).tolist()
        hypotheses[name] = dict(contrast=f"L-{second}", estimate=estimate, baseline_arm=second,
            baseline_mae=baseline_mae, margin=margin, bounds=[-margin, margin] if name == "H1_C" else [-margin, None],
            ci90=ci90, **interval(draws), tail_count=count, tail_denominator=BOOT_DRAWS,
            tail_display=f"{count}/{BOOT_DRAWS}", tail_fraction=count / BOOT_DRAWS,
            monte_carlo_resolution=1 / BOOT_DRAWS,
            tail_counts=dict(draws_ge_positive_margin=high, draws_le_negative_margin=low),
            ci90_strictly_inside_margin=bool(-margin < ci90[0] and ci90[1] < margin) if name == "H1_C" else None)

    order = sorted(hypotheses, key=lambda name: hypotheses[name]["tail_fraction"])
    running, rejected = 0., True
    for i, name in enumerate(order):
        p = hypotheses[name]["tail_fraction"]
        running = min(1., max(running, (len(order) - i) * p))
        rejected = rejected and p <= .05 / (len(order) - i)
        hypotheses[name].update(holm_tail_fraction=running, holm_supported=bool(rejected),
                                holm_step_threshold=.05 / (len(order) - i), holm_order_index=i + 1)
        hypotheses[name]["reading_holds"] = bool(rejected and (name != "H1_C" or hypotheses[name]["ci90_strictly_inside_margin"]))
    np.savez_compressed(output / "C_hypothesis_draws.npz", **arrays)
    return hypotheses, order


def pool_diagnostics(by_fold):
    result = {}
    for band in er.BANDS:
        weight = sum(by_fold[f][band]["weight"] for f in by_fold)
        mae = {a: sum(by_fold[f][band]["weighted_absolute_error"][a] for f in by_fold) / weight if weight else np.nan for a in ARMS}
        per_seed = {}
        for seed in SEEDS:
            seed_mae = {a: sum(by_fold[f][band]["per_seed"][str(seed)]["mae"][a] * by_fold[f][band]["weight"]
                               for f in by_fold if by_fold[f][band]["weight"]) / weight if weight else np.nan for a in ARMS}
            per_seed[str(seed)] = dict(mae=seed_mae, contrasts={f"{a}-{b}": seed_mae[a] - seed_mae[b] for a, b in CONTRASTS})
        result[band] = dict(rows=sum(by_fold[f][band]["rows"] for f in by_fold), weight=weight, mae=mae, per_seed=per_seed)
    return result


def score_condition(condition, entries, q90):
    output = OUT / condition
    require(not output.exists(), f"scoring condition directory exists: {output}")
    output.mkdir(parents=True)
    by_fold, days = {}, []
    for fold in FOLDS:
        rows = joined_rows(condition, fold, entries[fold], q90[fold])
        masks = er.band_masks(rows)
        by_fold[fold] = descriptive(rows, masks)
        days.append(er._day_units(rows, masks))
        del rows, masks
        gc.collect()
    days = pd.concat(days, ignore_index=True).sort_values(["band", "fold", "local_day"], kind="mergesort")
    days.to_csv(output / "development_day_units.csv", index=False)
    development, dev_arrays, dev_picks = day_scores(days, er.BANDS)
    np.savez_compressed(output / "development_draws.npz", **dev_arrays)
    np.save(output / "development_day_picks.npy", dev_picks)
    pooled = pool_diagnostics(by_fold)
    for band in er.BANDS:
        development[band]["rows"] = pooled[band]["rows"]
        development[band]["per_seed"] = pooled[band]["per_seed"]
    del days, dev_picks
    rows = joined_rows(condition, "C", entries["C"], q90["C"])
    masks = er.band_masks(rows)
    c_diagnostics = descriptive(rows, masks)
    days = er._day_units(rows, masks)
    days.to_csv(output / "C_day_units.csv", index=False)
    c_scores, c_arrays, c_picks = day_scores(days, ("all",))
    np.savez_compressed(output / "C_draws.npz", **c_arrays)
    np.save(output / "C_day_picks.npy", c_picks)
    hyp, order = hypotheses(rows, output)
    result = dict(development=dict(bands=development, per_fold=by_fold, pooled_diagnostics=pooled),
                  C=dict(bands=c_scores, diagnostics=c_diagnostics, hypotheses=hyp, family_holm=order,
                         rows=len(rows), days=int(rows.local_day.nunique()), prior_q90=q90["C"]),
                  peak_rss_bytes=rss_bytes())
    require(result["peak_rss_bytes"] <= 2 * 1024**3, "scoring exceeded 2 GiB RSS")
    write(output / "SCORE.json", result)
    del rows, masks, days, c_picks
    gc.collect()
    return result, dict(development=dev_arrays, C=c_arrays)


def validate_original(score):
    checks = []
    def check(label, value, expected, exact=False):
        if exact:
            passed, diff = value == expected, None
        else:
            diff = abs(float(value) - float(expected))
            passed = bool(np.isfinite(diff) and diff <= PARITY_ATOL)
        checks.append(dict(check=label, actual=value, sealed=expected, abs_difference=diff, passed=passed))
    for scope, folder in (("development", AUTO / "evaluation_v2g"), ("C", AUTO / "windows/C/evaluation")):
        intervals = pd.read_csv(folder / "paired_intervals.csv")
        metrics = pd.read_csv(folder / "metrics.csv")
        bands = er.BANDS if scope == "development" else ("all",)
        rename = (lambda a: f"{a}_g") if scope == "development" else (lambda a: a)
        for band in bands:
            result = score[scope]["bands"][band]
            m = metrics.loc[(metrics.scope == "pooled") & (metrics.band == band)].iloc[0]
            for a in ARMS:
                check(f"{scope}/{band}/{a}/mae", result["mae"][a], m[rename(a)])
            for a, b in CONTRASTS:
                name = f"{a}-{b}"
                old_name = f"{rename(a)}-{rename(b)}"
                sel = intervals.loc[(intervals.band == band) & (intervals.contrast == old_name) &
                                    (intervals.estimand == "weighted_row_mae")]
                require(len(sel) == 1, f"missing sealed interval {scope}/{band}/{name}")
                old = sel.iloc[0]
                new = result["contrasts"][name]
                check(f"{scope}/{band}/{name}/estimate", new["estimate"], old.estimate)
                for i, col in enumerate(("ci95_low", "ci95_high")):
                    check(f"{scope}/{band}/{name}/{col}", new["ci95"][i], old[col])
                for col in ("blocks", "undefined_draws"):
                    check(f"{scope}/{band}/{name}/{col}", new[col], int(old[col]), exact=True)
        for fold in FOLDS if scope == "development" else ("C",):
            diagnostics = score["development"]["per_fold"][fold] if scope == "development" else score["C"]["diagnostics"]
            for band in er.BANDS:
                sel = metrics.loc[(metrics.scope == "fold") & (metrics.key == fold) & (metrics.band == band)]
                if not len(sel):
                    require(diagnostics[band]["weight"] == 0, "missing nonempty sealed diagnostic")
                    continue
                old = sel.iloc[0]
                for a in ARMS:
                    check(f"{scope}/{fold}/{band}/{a}/descriptive_mae", diagnostics[band]["mae"][a], old[rename(a)])
                    for seed in SEEDS:
                        check(f"{scope}/{fold}/{band}/{a}/seed{seed}", diagnostics[band]["per_seed"][str(seed)]["mae"][a], old[f"{rename(a)}_s{seed}"])
    old_c = read(AUTO / "windows/C/evaluation/WINDOW_RESULT.json")
    check("C/family_holm", score["C"]["family_holm"], old_c["family_holm"], exact=True)
    for name in ("H1_C", "H2_C"):
        new, old = score["C"]["hypotheses"][name], old_c["hypotheses"][name]
        for k, old_k in (("estimate", "estimate"), ("tail_fraction", "p"), ("holm_tail_fraction", "holm_p")):
            check(f"{name}/{k}", new[k], old[old_k])
        check(f"{name}/margin", new["margin"], old["margin"] if name == "H1_C" else -old["bound"])
        for i in range(2):
            check(f"{name}/ci90/{i}", new["ci90"][i], old["ci90"][i])
        check(f"{name}/holm_supported", new["holm_supported"], old["supported"], exact=True)
    numeric = [c["abs_difference"] for c in checks if c["abs_difference"] is not None]
    result = dict(passed=all(c["passed"] for c in checks), absolute_tolerance=PARITY_ATOL, relative_tolerance=0,
                  checks_count=len(checks), max_absolute_difference=max(numeric), checks=checks,
                  convention="Counts and statuses exact; numeric estimates and CIs compared at atol=1e-8, rtol=0")
    write(HERE / "SCORE_VALIDATION.json", result)
    require(result["passed"], "original sealed scoring parity failed; corrected scoring stopped")
    return result


def comparison(original, aligned, draws):
    result, sign_checks, shift_arrays = {}, {}, {}
    for scope, bands in (("development", er.BANDS), ("C", ("all",))):
        result[scope], sign_checks[scope] = {}, {}
        for band in bands:
            result[scope][band], sign_checks[scope][band] = {}, {}
            for a, b in CONTRASTS:
                name = f"{a}-{b}"
                old = original[scope]["bands"][band]["contrasts"][name]
                new = aligned[scope]["bands"][band]["contrasts"][name]
                old_sign, new_sign = int(np.sign(old["estimate"])), int(np.sign(new["estimate"]))
                sign_checks[scope][band][name] = dict(original_sign=old_sign, corrected_sign=new_sign, retained=old_sign == new_sign)
                shift = draws['aligned'][scope][f"{band}__{name}"] - draws["original"][scope][f"{band}__{name}"]
                shift_arrays[f"{scope}__{band}__{name}"] = shift
                result[scope][band][name] = dict(original=old, aligned=new, shift=new["estimate"] - old["estimate"],
                                                paired_shift_bootstrap=interval(shift), sign_retained=old_sign == new_sign)
    np.savez_compressed(OUT / "paired_shift_draws.npz", **shift_arrays)
    main_signs = all(v["retained"] for v in sign_checks["development"]["all"].values()) and all(
        sign_checks["C"]["all"][name]["retained"] for name in ("L-N", "L-P"))
    all_signs = all(v["retained"] for scope in sign_checks.values() for band in scope.values() for v in band.values())
    dev_no_improvement = aligned["development"]["bands"]["all"]["contrasts"]["L-N"]["ci95"][1] >= 0
    h2_holds = aligned["C"]["hypotheses"]["H2_C"]["reading_holds"]
    unchanged = dev_no_improvement and h2_holds and main_signs
    reading = dict(state="UNCHANGED_AFTER_CONTRACT_CORRECTION" if unchanged else "MAIN_READING_CHANGED_AFTER_CONTRACT_CORRECTION",
                   development_overall_L_minus_N_no_reliable_improvement=dev_no_improvement,
                   corrected_H2_C_holds=h2_holds, main_contrast_signs_retained=main_signs,
                   stricter_all_reported_contrasts_signs_retained=all_signs,
                   H1_C_original_holds=original["C"]["hypotheses"]["H1_C"]["reading_holds"],
                   H1_C_corrected_holds=aligned["C"]["hypotheses"]["H1_C"]["reading_holds"],
                   H1_C_does_not_enter_main_reading=True,
                   language="No reliable increment detected is not equivalence or zero effect")
    return result, sign_checks, reading


def placebo_calibration(comparisons):
    path = AUTO / 'studies/B1c/placebo_summary.csv'
    table = pd.read_csv(path).sort_values("set", kind="mergesort")
    require(table["set"].tolist() == list(range(1, 21)), "B1c matched-placebo universe differs")
    values = table["shift"].to_numpy("float64")
    pass_values = table.H1_pass.astype(str).str.lower().map({"true": True, "false": False})
    require(pass_values.notna().all(), "B1c H1 pass field is not boolean")
    pass_count = int(pass_values.sum())
    require(pass_count == 5, "B1c H1 saved pass count does not reproduce 5/20")
    old = read(AUTO / 'studies/B1c/RESULT.json')["calibration"]
    require(pass_count == old["H1_pass_count"] and len(table) == old["H1_pass_denominator"], "B1c summary count differs")
    require(np.allclose(values, old["distribution"]["shifts_in_set_order"], atol=1e-14, rtol=0), "B1c saved shifts differ")
    observed = comparisons["C"]["all"]["L-N"]["shift"]
    quantiles = np.quantile(values, [.05, .25, .5, .75, .95])
    count = int((values <= observed).sum())
    return dict(source=str(path), values_in_set_order=values.tolist(), min=float(values.min()), max=float(values.max()),
        mean=float(values.mean()), sample_sd=float(values.std(ddof=1)),
        percentiles={str(p): float(q) for p, q in zip((5, 25, 50, 75, 95), quantiles)},
        observed_corrected_C_L_minus_N_shift=observed,
        development_L_minus_N_shift_not_ranked=comparisons["development"]["all"]["L-N"]["shift"],
        count_le_observed=count, denominator=len(values), empirical_rank_fraction=count / len(values),
        empirical_rank_definition="count(placebo shift <= observed C shift)/20, descriptive ECDF",
        inclusive_central_90_percent=bool(quantiles[0] <= observed <= quantiles[-1]),
        H1_pass_count=pass_count, H1_pass_denominator=len(values),
        interpretation='Descriptive calibration, not a new p-value. B1c changes L labels with N/P fixed; forecast_replication corrects shared numeric inputs and refits all arms. Interventions are not equivalent and no single cause is attributed.')


def main():
    start = time.monotonic()
    entries, q90, hashes = preflight()
    original, original_draws = score_condition("original", entries["original"], q90)
    parity = validate_original(original)
    aligned, corrected_draws = score_condition('aligned', entries['aligned'], q90)
    comparisons, signs, reading = comparison(original, aligned, dict(original=original_draws, aligned=corrected_draws))
    calibration = placebo_calibration(comparisons)
    final_hashes = {path: sha(path) for path in hashes}
    require(final_hashes == hashes, "scoring input hash drift during execution")
    result = dict(state="B4_ORIGINAL_AND_CORRECTED_SCORED", specification_sha256=sha(HERE / "SPEC.md"),
        original=original, aligned=aligned, comparisons=comparisons, sign_checks=signs, reading=reading,
        placebo_calibration=calibration,
        score_parity=dict(passed=parity["passed"], checks_count=parity["checks_count"],
                          absolute_tolerance=PARITY_ATOL, max_absolute_difference=parity["max_absolute_difference"],
                          detail=str(HERE / "SCORE_VALIDATION.json")),
        margins_comparison={name: {condition: score["C"]["hypotheses"][name]["margin"]
                             for condition, score in (("original", original), ('aligned', aligned))}
                            for name in ("H1_C", "H2_C")},
        conventions=dict(draws=BOOT_DRAWS, seed=BOOT_SEED, day_blocks="(fold, Brisbane target day)",
                         zero_weight_days_retained=True, resampling="pooled days, not fold-stratified",
                         sign_rule="numpy.sign equality", zero_tail="Count/2000 with 1/2000 Monte Carlo resolution and interval; not population p=0"),
        source_manifest=str(HERE / "SCORE_INPUT_MANIFEST.json"), protected_scoring_input_hashes_unchanged=True,
        wall_seconds=time.monotonic() - start, peak_rss_bytes=rss_bytes(), unresolved_issues=[])
    require(result["peak_rss_bytes"] <= 2 * 1024**3, "scoring exceeded 2 GiB RSS")
    write(HERE / "SCORES.json", result)
    print(json.dumps(clean(dict(state=result["state"], reading=reading, score_parity=result["score_parity"],
                                wall_seconds=result["wall_seconds"], peak_rss_bytes=result["peak_rss_bytes"])), indent=2))


if __name__ == "__main__":
    main()
