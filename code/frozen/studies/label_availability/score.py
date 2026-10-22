'Score development forecasts using the saved comparison definitions.'
from __future__ import annotations

import gc
import hashlib
import importlib.util
import json
import os
import resource
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[2]
AUTO = PROJ / 'forecasting'
forecast_replication = HERE.parent / 'forecast_replication'
forecast_sensitivity = HERE.parent / 'forecast_sensitivity'
os.environ["MPLCONFIGDIR"] = str(HERE / "mpl-cache")
os.environ["TMPDIR"] = "/tmp"

import numpy as np
import pandas as pd
import pyarrow


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[name] = obj
    spec.loader.exec_module(obj)
    return obj


bs = module(forecast_replication / "score.py", "b6_b4_scorer")
sens = module(forecast_sensitivity / "sensitivity.py", "b6_b5_sensitivity")
se = module(AUTO / 'extension_p5/score_p5min.py', "b6_sealed_e3_scorer")
er = bs.er
sm = sens.sm
KEYS = list(er.KEYS)
FOLDS = tuple(f[0] for f in er.FOLDS)
SEEDS = (20260919, 20260920, 20260921)
MAIN_ARMS = tuple("NRLP")
E3_ARMS = ("NP", "NPL", "NPR", "NPP")
MAIN_CONTRASTS = (("L", "N"), ("R", "N"), ("P", "N"), ("L", "P"), ("L", "R"))
E3_CONTRASTS = tuple(se.CONTRASTS)
LENGTHS = (1, 3, 7, 14)
DRAWS, SEED, ATOL = 2000, 20260925, 1e-8
INPUTS, CHECKS = {}, []
START = time.monotonic()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def register(path, expected=None):
    path = Path(path).resolve()
    value = sha(path)
    require(expected is None or value == expected, f"input hash mismatch: {path}")
    require(str(path) not in INPUTS or INPUTS[str(path)] == value, f"input drift: {path}")
    INPUTS[str(path)] = value
    return path


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    return value


def write(path, value):
    path = Path(path)
    require(path.resolve().is_relative_to(HERE), 'write outside label_availability')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(clean(value), stream, indent=2, allow_nan=False)
        stream.write("\n")


def rss():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def progress(stage, **extra):
    peak = rss()
    record = dict(stage=stage, peak_rss_bytes=peak, seconds=time.monotonic() - START, **extra)
    print(json.dumps(clean(record)), flush=True)
    require(peak < 2 * 1024**3, "scoring exceeded 2 GiB RSS")


def compare(name, actual, expected, atol=ATOL):
    a, b = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    passed = a.shape == b.shape and np.allclose(a, b, atol=atol, rtol=0, equal_nan=True)
    finite = np.abs(a - b) if a.shape == b.shape else np.array([])
    finite = finite[np.isfinite(finite)]
    delta = float(finite.max()) if len(finite) else 0.0
    CHECKS.append(dict(check=name, passed=bool(passed), max_absolute_difference=delta, atol=atol))
    require(passed, f"parity failed {name}: max difference {delta}")


def compare_table(name, actual, expected):
    require(list(actual) == list(expected) and len(actual) == len(expected), f"table schema differs: {name}")
    for col in actual:
        if pd.api.types.is_numeric_dtype(actual[col]) and pd.api.types.is_numeric_dtype(expected[col]):
            compare(f"{name}/{col}", actual[col], expected[col])
        else:
            require(actual[col].fillna("").astype(str).equals(expected[col].fillna("").astype(str)),
                    f"table identity differs: {name}/{col}")


def configure(system):
    arms = MAIN_ARMS if system == "main" else MAIN_ARMS + E3_ARMS
    contrasts = MAIN_CONTRASTS if system == "main" else E3_CONTRASTS
    for obj in (er, se.er, bs, sens):
        obj.ARMS, obj.CONTRASTS = arms, contrasts
    return arms, contrasts


def preflight(condition, system):
    require(read(HERE / "FREEZE.json")["spec_sha256"] == sha(HERE / "SPEC.md"), 'label_availability freeze mismatch')
    require(er.BOOT_DRAWS == DRAWS and er.BOOT_SEED == SEED, "bootstrap constants changed")
    for path in [HERE / "SPEC.md", HERE / "FREEZE.json", Path(__file__), Path(bs.__file__),
                 Path(sens.__file__), Path(er.__file__), Path(sm.__file__), Path(se.__file__),
                 forecast_sensitivity / "e3_score.py", forecast_replication / "SCORE_INPUT_MANIFEST.json",
                 AUTO / 'studies/B1b/OUTPUT_MANIFEST.json']:
        register(path)
    if condition == 'resolved':
        for group in ("main", "e3"):
            path = HERE / "identity" / group / "scores/SCORE_VALIDATION.json"
            require(path.exists() and read(register(path))["passed"], f"identity score parity missing: {group}")
    systems = ("main",) if system == "main" else ("main", "e3")
    seals = {}
    for group in systems:
        directory = HERE / condition / group
        seal = read(register(directory / "candidate_seal.json"))
        require(set(seal["files"]) == set(FOLDS), "candidate fold universe differs")
        require(seal.get("test_scored_before_bank_seal") is False, "pre-score seal assertion missing")
        design_path = register(directory / "design.json", seal.get("design_sha256"))
        for fold, entry in seal["files"].items():
            path = Path(entry["path"])
            if not path.is_absolute():
                options = [PROJ / path, directory / path, HERE / path]
                path = next((p for p in options if p.exists()), path)
            require(path.resolve().is_relative_to(directory), "candidate outside stage directory")
            entry["path"] = str(register(path, entry["sha256"]))
        seals[group] = seal
    return seals


def prediction(entry, arms):
    columns = KEYS + list(arms) + [f"{a}_s{s}" for a in arms for s in SEEDS]
    frame = pd.read_parquet(entry["path"], columns=columns)
    require(len(frame) == entry["rows"] and not frame.duplicated(KEYS).any(), "candidate keys/count differ")
    for col in ("issue_time", "target_time"):
        frame[col] = pd.to_datetime(frame[col], utc=True)
    frame = frame.sort_values(KEYS, kind="mergesort").reset_index(drop=True)
    for arm in arms:
        values = frame[[f"{arm}_s{s}" for s in SEEDS]].to_numpy("float64")
        require(np.isfinite(values).all() and np.isfinite(frame[arm]).all(), "nonfinite prediction")
        require(np.array_equal(values.mean(axis=1).astype("float32"), frame[arm].to_numpy()), "ensemble arithmetic differs")
    return frame


def joined(fold, system, seals, q90):
    pred = prediction(seals["main"]["files"][fold], MAIN_ARMS)
    if system == "e3":
        ext = prediction(seals["e3"]["files"][fold], E3_ARMS)
        require(pred[KEYS].equals(ext[KEYS]), "main/E3 candidate keys differ")
        for col in ext:
            if col not in KEYS:
                pred[col] = ext[col].to_numpy()
        del ext
    _, first, last = next(f for f in er.FOLDS if f[0] == fold)
    months = pd.period_range(first, last, freq="M").astype(str).tolist()
    path = AUTO / 'studies/B1b/development_metadata.parquet'
    expected = read(AUTO / 'studies/B1b/OUTPUT_MANIFEST.json')["files"][path.name]["sha256"]
    if str(path.resolve()) not in INPUTS:
        register(path, expected)
    truth = pd.read_parquet(path, columns=KEYS + ["y_true", "weight", "event_replay_flag"],
                            filters=[("bank_month", "in", months)])
    event = pd.concat([pd.read_parquet(register(er.BANK / f"{m}.parquet"),
                                      columns=KEYS + ["event_block_id"]) for m in months], ignore_index=True)
    for frame in (truth, event):
        for col in ("issue_time", "target_time"):
            frame[col] = pd.to_datetime(frame[col], utc=True)
    truth = truth.merge(event, on=KEYS, how="inner", validate="one_to_one")
    require(len(truth) == len(event) == len(pred), "truth/event/candidate key universe differs")
    del event
    require(truth.event_replay_flag.isin([0, 1]).all(), "invalid replay flag")
    expected_weight = np.where(truth.event_replay_flag == 1, 1., 50.)
    require(np.array_equal(expected_weight, truth.weight.to_numpy()), "development weights differ")
    truth["weight"] = expected_weight
    rows = pred.merge(truth, on=KEYS, how="inner", validate="one_to_one")
    require(len(rows) == len(pred), "joined key count differs")
    require(np.isfinite(rows.y_true).all(), "nonfinite truth")
    for group in seals:
        declared = seals[group]["files"][fold].get("q90")
        require(declared is None or declared == q90, "sealed scoring q90 differs")
    rows["fold"], rows["q90"] = fold, q90
    rows["local_day"] = rows.target_time.dt.tz_convert("Australia/Brisbane").dt.strftime("%Y-%m-%d")
    rows["hgroup"] = np.where(rows.horizon.to_numpy() <= 15, "h05_15", "h20_30")
    arms, _ = configure(system)
    for arm in arms:
        rows[f"{arm}_ae"] = np.abs(rows[arm].to_numpy("float64") - rows.y_true.to_numpy("float64"))
    return rows


def rebuild(condition, system, seals, out):
    q90 = read(forecast_replication / "SCORE_INPUT_MANIFEST.json")["q90"]
    arms, contrasts = configure(system)
    day_parts, event_parts, coverages, by_fold, pooled_rows = [], [], [], {}, []
    for fold in FOLDS:
        rows = joined(fold, system, seals, q90[fold])
        masks = er.band_masks(rows)
        by_fold[fold] = bs.descriptive(rows, masks)
        day_parts.append(er._day_units(rows, masks))
        events, coverage = er._event_units(rows)
        events.to_csv(out / f"{fold}_event_units.csv", index=False)
        event_parts.append(events)
        coverages.append(coverage)
        if system == "e3":
            keep = KEYS + list(arms) + ["y_true", "weight", "event_replay_flag", "event_block_id", "fold", "q90"]
            pooled_rows.append(rows[keep].copy())
        del rows, masks, events
        gc.collect()
        progress("fold_scored", condition=condition, system=system, fold=fold)
    days = pd.concat(day_parts, ignore_index=True).sort_values(["band", "fold", "local_day"], kind="mergesort").reset_index(drop=True)
    days.to_csv(out / "development_day_units.csv", index=False)
    events = pd.concat(event_parts, ignore_index=True)
    for arm in arms:
        events[f"{arm}_sum"] = events[f"{arm}_ae"] * events.rows
    events = events.groupby("event_block_id", as_index=False)[["rows"] + [f"{a}_sum" for a in arms]].sum()
    for arm in arms:
        events[f"{arm}_ae"] = events[f"{arm}_sum"] / events.rows
    events = events.sort_values("event_block_id").reset_index(drop=True)
    events.to_csv(out / "development_event_units.csv", index=False)
    coverage = {k: sum(v[k] for v in coverages) for k in coverages[0] if k != "severe_connected_events"}
    coverage.update(severe_connected_events=len(events), sum_fold_event_counts=sum(v["severe_connected_events"] for v in coverages))
    primary, draws, picks = bs.day_scores(days, er.BANDS)
    np.savez_compressed(out / "development_primary_draws.npz", **draws)
    np.save(out / "development_primary_picks.npy", picks)
    pooled = bs.pool_diagnostics(by_fold)
    for band in er.BANDS:
        primary[band].update(rows=pooled[band]["rows"], per_seed=pooled[band]["per_seed"])
    sealed_e3 = None
    if system == "e3":
        rows = pd.concat(pooled_rows, ignore_index=True)
        del pooled_rows
        gc.collect()
        metrics, intervals, _ = se.evaluate(rows, list(arms))
        metrics.to_csv(out / "dev_metrics.csv", index=False)
        intervals.to_csv(out / "dev_paired_intervals.csv", index=False)
        sealed_e3 = {band: {f"{a}-{b}": se.get(intervals, f"{a}-{b}", band) for a, b in contrasts} for band in er.BANDS}
        for band, contrasts_by_band in sealed_e3.items():
            for name, value in contrasts_by_band.items():
                compare(f"E3/sealed_primary/{band}/{name}/estimate", primary[band]["contrasts"][name]["estimate"], value["estimate"])
                compare(f"E3/sealed_primary/{band}/{name}/ci95", primary[band]["contrasts"][name]["ci95"], value["ci95"])
        del rows, metrics, intervals
        gc.collect()
    return days, events, coverage, dict(bands=primary, per_fold=by_fold, pooled_diagnostics=pooled, sealed_e3=sealed_e3)


def battery(days, system, out):
    arms, contrasts = configure(system)
    n = int(days.band.eq("all").sum())
    calendar = days.loc[days.band.eq("all"), ["fold", "local_day"]].reset_index(drop=True)
    diffs = pd.to_datetime(calendar.local_day).diff().dt.days
    gaps = calendar.loc[diffs.notna() & diffs.ne(1)].copy()
    gaps["previous_day"] = calendar.local_day.shift(1).loc[gaps.index]
    gaps["day_difference"] = diffs.loc[gaps.index]
    result, lodo_rows, lodo_ranges, dm_rows = {}, [], {}, []
    primary_draws = np.load(out / "development_primary_draws.npz")
    for length in LENGTHS:
        picks = sens.picks_for(n, length)
        np.save(out / f"development_{length}d_picks.npy", picks)
        arrays, scored = {}, {}
        for band in er.BANDS:
            block = days.loc[days.band.eq(band)].reset_index(drop=True)
            require(len(block) == n, "zero-band days omitted")
            weight = block.weight.to_numpy(float)
            denominator = weight[picks].sum(axis=1)
            mae = {a: float(block[f"{a}_sae"].sum() / weight.sum()) if weight.sum() else np.nan for a in arms}
            record = dict(weight=float(weight.sum()), zero_weight_days=int((weight == 0).sum()), mae=mae, contrasts={})
            for first, second in contrasts:
                name = f"{first}-{second}"
                delta = (block[f"{first}_sae"] - block[f"{second}_sae"]).to_numpy(float)
                numerator = delta[picks].sum(axis=1)
                absolute = sens.divide(numerator, denominator)
                fixed = 100 * sens.divide(absolute, mae[second])
                ratio = 100 * sens.divide(numerator, block[f"{second}_sae"].to_numpy(float)[picks].sum(axis=1))
                estimate = float(delta.sum() / weight.sum()) if weight.sum() else np.nan
                for kind, values in (("absolute", absolute), ("fixed_reference_percent", fixed), ("paired_ratio_percent", ratio)):
                    arrays[f"{band}__{name}__{kind}"] = values
                record["contrasts"][name] = dict(estimate=estimate, **sens.quantiles(absolute),
                    fixed_reference_percent=dict(estimate=100 * estimate / mae[second], **sens.quantiles(fixed)),
                    paired_ratio_percent=dict(estimate=100 * estimate / mae[second], **sens.quantiles(ratio)))
                if length == 1:
                    compare(f"battery_primary/{band}/{name}", absolute, primary_draws[f"{band}__{name}"])
                    keep_weight = weight.sum() - weight
                    leave = sens.divide(delta.sum() - delta, keep_weight)
                    fixed_leave = 100 * sens.divide(leave, mae[second])
                    base = block[f"{second}_sae"].to_numpy(float)
                    ratio_leave = 100 * sens.divide(delta.sum() - delta, base.sum() - base)
                    for i in range(n):
                        lodo_rows.append(dict(scope="development", band=band, contrast=name, fold=block.fold.iloc[i],
                            omitted_day=block.local_day.iloc[i], omitted_weight=float(weight[i]), estimate=leave[i],
                            fixed_reference_percent=fixed_leave[i], paired_ratio_percent=ratio_leave[i]))
                    lodo_ranges.setdefault(band, {})[name] = dict(absolute=sens.range_record(leave, block),
                        fixed_reference_percent=sens.range_record(fixed_leave, block),
                        paired_ratio_percent=sens.range_record(ratio_leave, block), reference_mae=mae[second])
                    selected = weight > 0
                    dm_rows.append(dict(scope="development", band=band, contrast=name, **sm.dm(delta[selected] / weight[selected]),
                        aggregation="equal mean of nonempty Brisbane target-day weighted MAE differences",
                        covariance="centred Newey-West Bartlett; automatic floor(4*(T/100)^(2/9))",
                        alternative="two-sided daily expected loss equality", multiplicity_adjustment="none; descriptive secondary"))
            scored[band] = record
        np.savez_compressed(out / f"development_{length}d_draws.npz", **arrays)
        result[str(length)] = scored
        del arrays, picks
    primary_draws.close()
    pd.DataFrame(lodo_rows).to_csv(out / "leave_one_day_out.csv", index=False)
    pd.DataFrame(dm_rows).to_csv(out / "dm_statistics.csv", index=False)
    return dict(intervals=result, leave_one_day_out_ranges=lodo_ranges, dm_statistics=dm_rows,
        calendar=dict(blocks=n, first_day=calendar.local_day.iloc[0], last_day=calendar.local_day.iloc[-1],
                      nonunit_calendar_steps=gaps.to_dict("records"), fold_stratified=False),
        dm_universe='All paired label_availability truth/prediction rows within band, aggregated to nonempty target days; identical forecast_sensitivity all-row universe. DM weights nonempty days equally, unlike primary pooled row-weighted MAE. No restriction to P5-present rows.')


def severe(events, coverage, system, out):
    configure(system)
    sens.OUT = out
    return sens.event_scores({"development": events}, {"development": coverage})["development"]


def validate_identity(system, primary, battery_result, events_result, out):
    if system == "main":
        old = read(register(forecast_replication / 'scoring/aligned/SCORE.json'))["development"]
        for band in er.BANDS:
            current, reference = primary["bands"][band], old["bands"][band]
            compare(f"forecast_replication/{band}/weight", current["weight"], reference["weight"])
            for arm in MAIN_ARMS:
                compare(f"forecast_replication/{band}/{arm}/MAE", current["mae"][arm], reference["mae"][arm])
                for seed in SEEDS:
                    compare(f"forecast_replication/{band}/{arm}/{seed}/MAE", current["per_seed"][str(seed)]["mae"][arm], reference["per_seed"][str(seed)]["mae"][arm])
            for name, value in current["contrasts"].items():
                for field in ("estimate", "ci95"):
                    compare(f"forecast_replication/{band}/{name}/{field}", value[field], reference["contrasts"][name][field])
        old_battery = read(register(forecast_sensitivity / "sensitivity/RESULT.json"))
        for length in LENGTHS:
            for band in er.BANDS:
                for name, value in battery_result["intervals"][str(length)][band]["contrasts"].items():
                    reference = old_battery["intervals"]["development"][str(length)][band]["contrasts"][name]
                    for field in ("estimate", "ci90", "ci95"):
                        compare(f"forecast_sensitivity/{length}/{band}/{name}/{field}", value[field], reference[field])
                    for mode in ("fixed_reference_percent", "paired_ratio_percent"):
                        for field in ("estimate", "ci90", "ci95"):
                            compare(f"forecast_sensitivity/{length}/{band}/{name}/{mode}/{field}", value[mode][field], reference[mode][field])
        for current, reference in zip(events_result["contrasts"], old_battery["severe_events"]["development"]["contrasts"]):
            require(current["contrast"] == reference["contrast"] and current["estimand"] == reference["estimand"], "event contrast order differs")
            for field in ("estimate", "ci90", "ci95"):
                compare(f"forecast_sensitivity/event/{current['contrast']}/{current['estimand']}/{field}", current[field], reference[field])
        old_dm = pd.read_csv(register(forecast_sensitivity / "sensitivity/dm_statistics.csv"))
        old_dm = old_dm.loc[old_dm.scope.eq("development")].reset_index(drop=True)
        compare_table('forecast_sensitivity/DM', pd.read_csv(out / "dm_statistics.csv"), old_dm)
        compare_table('forecast_sensitivity/LODO', pd.read_csv(out / "leave_one_day_out.csv"),
                      pd.read_csv(register(forecast_sensitivity / "sensitivity/leave_one_day_out.csv")).query("scope == 'development'").reset_index(drop=True))
    else:
        old = read(register(forecast_sensitivity / 'e3/aligned/E3_RESULT.json'))
        for band in er.BANDS:
            for arm in MAIN_ARMS + E3_ARMS:
                compare(f"E3/{band}/{arm}/MAE", primary["bands"][band]["mae"][arm], old["pooled_mae"]["dev"][band][arm])
        for name, value in old["dev"].items():
            for field in ("estimate", "ci95"):
                compare(f"E3/all/{name}/{field}", primary["bands"]["all"]["contrasts"][name][field], value[field])
        for name, values in old["dev_bands"].items():
            for band, value in values.items():
                for field in ("estimate", "ci95"):
                    compare(f"E3/{band}/{name}/{field}", primary["bands"][band]["contrasts"][name][field], value[field])
        for arm in E3_ARMS:
            for seed in SEEDS:
                compare(f"E3/{arm}/{seed}/MAE", primary["bands"]["all"]["per_seed"][str(seed)]["mae"][arm], old["per_seed_mae"]["dev"][f"{arm}_s{seed}"])
        for table in ("metrics", "paired_intervals"):
            compare_table(f"E3/dev_{table}", pd.read_csv(out / f"dev_{table}.csv"),
                          pd.read_csv(register(forecast_sensitivity / f"e3/aligned/scores/dev_{table}.csv")))


def stage(condition, system):
    require(condition in ("identity", 'resolved') and system in ("main", "e3"), "invalid score stage")
    out = HERE / condition / system / "scores"
    require(not out.exists(), f"refusing overwrite {out}")
    seals = preflight(condition, system)
    out.mkdir()
    days, events, coverage, primary = rebuild(condition, system, seals, out)
    battery_result = battery(days, system, out)
    event_result = severe(events, coverage, system, out)
    if condition == "identity":
        validate_identity(system, primary, battery_result, event_result, out)
    for path, digest in INPUTS.items():
        require(sha(path) == digest, f"source drift: {path}")
    result = dict(condition=condition, system=system, primary=primary, battery=battery_result,
        severe_events=event_result, bootstrap_draws=DRAWS, bootstrap_seed=SEED, lengths=LENGTHS,
        comparison_reference='forecast_replication corrected' if system == "main" else 'forecast_sensitivity corrected E3 with forecast_replication corrected main references',
        C_refit=False, C_scored=False, peak_rss_bytes=rss(), runtime_seconds=time.monotonic() - START,
        software=dict(python=sys.version, numpy=np.__version__, pandas=pd.__version__, pyarrow=pyarrow.__version__),
        limitations=["Moving blocks assume approximate dependence stability and do not establish uniform coverage.",
                     "Noncircular blocks underweight calendar endpoints; folds are pooled without stratification.",
                     "Main and E3 sensitivity batteries are descriptive; no extra hypothesis family is introduced.",
                     "Severe connected-event estimands differ from all-row severe-band weighting.",
                     "Recorded update/publication times do not establish historical first-release vintages."])
    progress("score_complete", condition=condition, system=system)
    write(out / "SCORE.json", result)
    write(out / "INPUT_MANIFEST.json", dict(files=INPUTS))
    write(out / "SCORE_VALIDATION.json", dict(passed=all(c["passed"] for c in CHECKS),
        reference_parity=condition == "identity", tolerance=ATOL, checks=CHECKS,
        peak_rss_bytes=rss(), source_hashes_unchanged=True))
    write(out / "OUTPUT_MANIFEST.json", dict(files={str(p.relative_to(out)): dict(sha256=sha(p), bytes=p.stat().st_size)
          for p in sorted(out.iterdir()) if p.is_file()}))


def summarize():
    require(read(HERE / "FREEZE.json")["spec_sha256"] == sha(HERE / "SPEC.md"), "freeze mismatch")
    values, changes, sign_checks = {}, {}, {}
    out = HERE / "scoring"
    require(not out.exists(), "refusing overwrite scoring summary")
    out.mkdir()
    for system in ("main", "e3"):
        values[system] = {}
        for condition in ("identity", 'resolved'):
            directory = HERE / condition / system / "scores"
            validation = read(register(directory / "SCORE_VALIDATION.json"))
            require(validation["passed"], f"invalid scoring {system}/{condition}")
            values[system][condition] = read(register(directory / "SCORE.json"))
        changes[system], sign_checks[system] = {}, {}
        for band in er.BANDS:
            changes[system][band], sign_checks[system][band] = {}, {}
            reference_snapshot = values[system]["identity"]["primary"]["bands"][band]
            after = values[system]['resolved']["primary"]["bands"][band]
            for name, new in after["contrasts"].items():
                old = reference_snapshot["contrasts"][name]
                second = name.split("-")[1]
                changes[system][band][name] = dict(reference_snapshot=old, after=new,
                    absolute_shift=new["estimate"] - old["estimate"],
                    shift_percent_of_before_reference_mae=100 * (new["estimate"] - old["estimate"]) / reference_snapshot["mae"][second],
                    before_percent_of_own_reference=100 * old["estimate"] / reference_snapshot["mae"][second],
                    after_percent_of_own_reference=100 * new["estimate"] / after["mae"][second])
                sign_checks[system][band][name] = dict(before_sign=int(np.sign(old["estimate"])),
                    after_sign=int(np.sign(new["estimate"])), retained=bool(np.sign(old["estimate"]) == np.sign(new["estimate"])))
        paired_shifts = {}
        for length in LENGTHS:
            first = HERE / "identity" / system / "scores" / f"development_{length}d_draws.npz"
            second = HERE / 'resolved' / system / "scores" / f"development_{length}d_draws.npz"
            a, b = np.load(register(first)), np.load(register(second))
            old_picks = np.load(register(first.with_name(f"development_{length}d_picks.npy")))
            new_picks = np.load(register(second.with_name(f"development_{length}d_picks.npy")))
            require(np.array_equal(old_picks, new_picks), 'reference_snapshot/after resample picks differ')
            require(a.files == b.files, 'reference_snapshot/after draw names differ')
            arrays = {key: b[key] - a[key] for key in a.files}
            np.savez_compressed(out / f"{system}_{length}d_paired_shift_draws.npz", **arrays)
            paired_shifts[str(length)] = {key: sens.quantiles(arr) for key, arr in arrays.items()}
            a.close(); b.close()
        changes[system]["paired_bootstrap_shifts"] = paired_shifts
    before_l = values["main"]["identity"]["primary"]["bands"]["all"]["contrasts"]["L-N"]
    after_l = values["main"]['resolved']["primary"]["bands"]["all"]["contrasts"]["L-N"]
    no_improvement = after_l["ci95"][1] >= 0
    signs_retained = all(v["retained"] for v in sign_checks["main"]["all"].values())
    changed = [name for name, v in sign_checks["main"]["all"].items() if not v["retained"]]
    reading = dict(state='UNCHANGED_BY_LABEL_BOUNDARY_SET' if no_improvement and signs_retained else 'DEVELOPMENT_READING_CHANGED_BY_LABEL_BOUNDARY_SET',
        development_overall_L_minus_N_no_reliable_improvement=bool(no_improvement),
        main_contrast_signs_retained=signs_retained, changed_main_contrast_signs=changed,
        L_minus_N_interval_criterion_changed=bool((before_l["ci95"][1] >= 0) != no_improvement),
        language="No reliable increment detected is not equivalence or zero effect.")
    e3_c = read(register(forecast_sensitivity / 'e3/aligned/E3_RESULT.json'))
    e3_main = values["e3"]['resolved']["primary"]["bands"]["all"]["contrasts"]
    e3_increment = e3_main["NPL-NP"]["ci95"][1] < 0 and e3_main["NPL-NPP"]["ci95"][1] < 0 and e3_c["primary"]["window_C_NPL_NP"]["estimate"] < 0
    e3_reading = dict(reading="LLM increment on top of P5MIN" if e3_increment else "no reliable LLM increment detected under the original E3 criterion",
        original_rule=e3_c["rule"], criterion_pass=bool(e3_increment),
        primary=dict(dev_NPL_NP=e3_main["NPL-NP"], dev_NPL_NPP=e3_main["NPL-NPP"], window_C_NPL_NP=e3_c["primary"]["window_C_NPL_NP"]),
        C_unchanged=True, C_source=str(forecast_sensitivity / 'e3/aligned/E3_RESULT.json'),
        dev_signs_retained=all(v["retained"] for v in sign_checks["e3"]["all"].values()))
    for path, digest in INPUTS.items():
        require(sha(path) == digest, f"summary input drift: {path}")
    result = dict(status="COMPLETE", reading=reading, e3_reading=e3_reading, changes=changes, sign_checks=sign_checks,
        systems=values, C_refit=False, C_scored=False, input_hashes_unchanged=True,
        peak_rss_bytes=rss(), runtime_seconds=time.monotonic() - START)
    write(out / "SCORES.json", result)
    write(out / "INPUT_MANIFEST.json", dict(files=INPUTS))
    write(out / "OUTPUT_MANIFEST.json", dict(files={str(p.relative_to(out)): dict(sha256=sha(p), bytes=p.stat().st_size)
          for p in sorted(out.iterdir()) if p.is_file()}))
    progress("summary_complete", reading=reading, e3_reading=e3_reading)


if __name__ == "__main__":
    if sys.argv[1:] == ["summarize"]:
        summarize()
    else:
        require(len(sys.argv) == 3, "usage: score.py {identity,repaired} {main,e3} | summarize")
        stage(sys.argv[1], sys.argv[2])
