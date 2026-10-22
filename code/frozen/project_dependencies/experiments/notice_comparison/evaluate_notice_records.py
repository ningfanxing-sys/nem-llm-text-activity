'Score matched notice forecasts after checking their saved inputs.'
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


HERE = Path(__file__).resolve().parent
OLD_RUN = HERE.parent / 'notice_forecasting' / "run_phys"
BANK = HERE.parents[1] / 'artifacts/historical_support/feature_bank/training'
SEED = 20260919
BOOT_SEED = 20260925
BOOT_DRAWS = 2000
KEYS = ("region", "issue_time", "target_time", "horizon")
FOLDS = (
    ("F1", "2022-07", "2022-09"),
    ("F2", "2022-10", "2022-12"),
    ("F3", "2023-01", "2023-03"),
    ("F4", "2023-04", "2023-06"),
    ("F5", "2023-07", "2023-09"),
    ("F6", "2023-10", "2023-12"),
)
OLD_ARMS = ("N", "R", "L", "P")
NEW_ARMS = ("R", "L", "P")
ARMS = ("N_old", "R_old", "L_old", "P_old", 'R_set', 'L_set', 'P_set')
BANDS = ("all", "high_q90", "y_le_300", "y_300_to_5000", "y_gt_5000")
CONTRASTS = (
    ('L_set', "N_old"), ('L_set', 'R_set'), ('L_set', 'P_set'),
    ('R_set', "N_old"), ('P_set', "N_old"),
    ('L_set', "L_old"), ('R_set', "R_old"), ('P_set', "P_old"),
    ("L_old", "N_old"), ("L_old", "R_old"), ("L_old", "P_old"),
    ("R_old", "N_old"), ("P_old", "N_old"),
)
FORBIDDEN = {"y_true", "weight", "event_replay_flag", "event_block_id", "label_available_time"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _sealed_path(run: Path, stated: str, expected: Path) -> Path:
    path = Path(stated)
    if not path.is_absolute():
        path = run / path
    require(path.resolve() == expected.resolve(), f"candidate path mismatch: {stated} != {expected}")
    require(expected.is_file(), f"missing candidate: {expected}")
    return expected


def _candidate(run: Path, entry: dict, fold: str, arms: tuple[str, ...], *, is_new: bool) -> pd.DataFrame:
    expected = run / "predictions" / f"{fold}.parquet"
    path = _sealed_path(run, entry["path"], expected)
    require(sha(path) == entry["sha256"], f"{fold}: prediction hash mismatch at {path}")
    schema = pq.read_schema(path)
    names = set(schema.names)
    require(not names.intersection(FORBIDDEN) and not any(n.startswith("label_") for n in names),
            f"{fold}: truth, weights or future labels in candidate {path}")
    cols = list(KEYS) + [f"{arm}_s{SEED}" for arm in arms]
    require(set(cols) <= names, f"{fold}: missing single-seed columns in {path}")
    aliases = list(arms) if is_new and set(arms) <= names else []
    frame = pd.read_parquet(path, columns=cols + aliases)
    require(len(frame) == int(entry["rows"]), f"{fold}: sealed row count mismatch")
    for column in ("issue_time", "target_time"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    require(not frame.duplicated(list(KEYS)).any(), f"{fold}: duplicate forecast key")
    for arm in arms:
        values = frame[f"{arm}_s{SEED}"].to_numpy(dtype="float64")
        require(np.isfinite(values).all(), f"{fold}: nonfinite {arm} prediction")
        if arm in aliases:
            require(np.array_equal(values, frame[arm].to_numpy(dtype="float64")),
                    f"{fold}: {arm} is not the single-seed prediction")
    return frame.drop(columns=aliases).sort_values(list(KEYS), kind="mergesort").reset_index(drop=True)


def _repair_binding_preflight(new_run: Path, old_run: Path, repair_dir: Path,
                              old_seal: dict, new_seal: dict, old_design: dict, new_design: dict) -> None:

    repair_dir = repair_dir.resolve()
    old_source = old_run.parent
    old_seal_path = old_run / "candidate_bank_seal.json"
    old_design_path = old_run / "design_binding.json"
    new_seal_path = new_run / "candidate_bank_seal.json"
    binding_path = new_run / "repair_design_binding.json"
    receipt_path = new_run / "repair_candidate_receipt.json"
    binding, receipt = read_json(binding_path), read_json(receipt_path)
    require(binding.get("state") == "NW_REPAIR_DESIGN_BOUND_BEFORE_NEW_FIT_OR_SCORE" and
            binding.get("target_scoring_before_seal") is False,
            "repair design was not bound before fit or score")
    require(receipt.get("state") == "NW_EVENT_STATE_REPAIR_CANDIDATES_SEALED_BEFORE_SCORE" and
            receipt.get("scoring_started") is False,
            "repair candidate receipt does not certify sealed-before-score state")
    expected = {
        "old_seal_sha256": sha(old_seal_path),
        "old_design_sha256": sha(old_design_path),
        "old_physical_binding_sha256": sha(old_run / "phys_binding.json"),
        "old_notice_code_sha256": sha(old_source / "nw_notices.py"),
        "repair_notice_code_sha256": sha(repair_dir / 'notice_event_records.py'),
        "repair_tests_sha256": sha(repair_dir / "test_nw_notices_repaired.py"),
        "repair_protocol_sha256": sha(repair_dir / "PROTOCOL.md"),
        "this_runner_sha256": sha(repair_dir / "run_repair.py"),
        "fit_recipe_sha256": sha(old_source / "run_nw.py"),
        "physical_loader_sha256": sha(old_source / "run_nw_phys.py"),
    }
    for field, digest in expected.items():
        require(binding.get(field) == digest, f"repair pre-fit binding drift: {field}")
    require(binding.get("seed") == SEED and binding.get("new_arms") == list(NEW_ARMS) and
            binding.get("old_controls") == list(OLD_ARMS), "repair pre-fit seed/arms changed")
    require(binding.get("folds") == [list(x) for x in FOLDS], "repair pre-fit folds changed")
    source_months = list(pd.period_range("2021-10", "2023-12", freq="M").astype(str))
    require(binding.get("source_months") == source_months, "repair pre-fit source months changed")
    require(binding.get("fixed_params") == old_design.get("params") == new_design.get("params"),
            "repair pre-fit model parameters changed")
    require(binding.get("old_files") == [dict(fold=f["fold"], prediction_sha256=f["sha256"],
                                             q90=f["q90"], rows=f["rows"]) for f in old_seal["files"]],
            "repair pre-fit old candidate bank changed")
    require(new_design.get("notice_code_sha256") == expected["repair_notice_code_sha256"] and
            new_design.get("notice_sources", {}).get("code_sha256") == expected["repair_notice_code_sha256"],
            "new design does not bind the current repair notice code")
    require(new_design.get("notice_sources", {}).get("legacy_code_sha256") == expected["old_notice_code_sha256"],
            "new design old notice-code provenance changed")
    require(receipt.get("candidate_bank_seal_sha256") == sha(new_seal_path) and
            receipt.get("repair_design_binding_sha256") == sha(binding_path) and
            receipt.get("original_design_binding_sha256") == expected["old_design_sha256"] and
            receipt.get("repaired_notice_code_sha256") == expected["repair_notice_code_sha256"],
            "post-fit repair candidate receipt hash mismatch")
    require(new_seal.get("design_binding_sha256") == sha(new_run / "design_binding.json"),
            "post-fit receipt references an unbound candidate design")


@dataclass
class Preflight:
    candidates: dict[str, pd.DataFrame]
    months: dict[str, list[str]]
    q90: dict[str, float]
    new_seal_sha256: str
    old_seal_sha256: str
    new_design_sha256: str
    old_design_sha256: str
    bank_sha256: dict[str, str]


def preflight(new_run: Path, old_run: Path = OLD_RUN, *, repair_dir: Path = HERE) -> Preflight:

    new_run, old_run = Path(new_run).resolve(), Path(old_run).resolve()
    require(new_run != old_run, "new candidate run cannot be the frozen old run")
    old_seal_path, new_seal_path = old_run / "candidate_bank_seal.json", new_run / "candidate_bank_seal.json"
    old_design_path, new_design_path = old_run / "design_binding.json", new_run / "design_binding.json"
    old_seal, new_seal = read_json(old_seal_path), read_json(new_seal_path)
    old_design, new_design = read_json(old_design_path), read_json(new_design_path)
    require(old_seal.get("state") == "NW_CANDIDATE_BANK_SEALED" and
            old_seal.get("target_scoring_before_seal") is False, "old candidate bank is not sealed")
    require(str(new_seal.get("state", "")).endswith("CANDIDATE_BANK_SEALED") and
            new_seal.get("target_scoring_before_seal") is False, "new candidate bank is not sealed before scoring")
    require(old_seal.get("design_binding_sha256") == sha(old_design_path), "old design hash mismatch")
    require(new_seal.get("design_binding_sha256") == sha(new_design_path), "new design hash mismatch")
    expected_folds = [list(x) for x in FOLDS]
    require(old_design.get("folds") == expected_folds and new_design.get("folds") == expected_folds,
            "F1-F6 fold schedule differs from frozen PHYS comparison")
    require(old_design.get("seeds") == [SEED, 20260920, 20260921], "old seed schedule differs")
    require(new_design.get("seeds") == [SEED], "repair must fit exactly one seed")
    require(old_design.get("arms") == list(OLD_ARMS) and new_design.get("arms") == list(NEW_ARMS),
            "arm set differs from fixed N-old/RLP-repair design")
    require(new_design.get("bank_sha256") == old_design.get("bank_sha256"), "training-bank source hashes differ")
    for field in ("numeric_features", "params", "weights", "target", "projection", "placebo_days"):
        require(new_design.get(field) == old_design.get(field), f"fixed recipe changed: {field}")
    old_sources, new_sources = old_design.get("notice_sources", {}), new_design.get("notice_sources", {})
    for field in ("registry_sha256", "labels_sha256"):
        require(new_sources.get(field) == old_sources.get(field), f"notice source changed: {field}")
    _repair_binding_preflight(new_run, old_run, repair_dir, old_seal, new_seal, old_design, new_design)
    for seal, label in ((old_seal, "old"), (new_seal, "new")):
        require([f.get("fold") for f in seal.get("files", [])] == [f[0] for f in FOLDS],
                f"{label} seal does not cover F1-F6 exactly once in order")
    candidates, months, q90 = {}, {}, {}
    for old_entry, new_entry in zip(old_seal["files"], new_seal["files"]):
        fold = old_entry["fold"]
        old_receipt = read_json(old_run / "receipts" / f"{fold}.json")
        new_receipt = read_json(new_run / "receipts" / f"{fold}.json")
        require(old_receipt.get("fold") == fold and new_receipt.get("fold") == fold,
                f"{fold}: receipt identity mismatch")
        require(new_receipt.get("months") == old_receipt.get("months"), f"{fold}: test months changed")
        for item in (old_entry, new_entry, old_receipt, new_receipt):
            require(float(item["q90"]) == float(old_receipt["q90"]), f"{fold}: prior-fold q90 changed")
        require(int(new_entry["rows"]) == int(old_entry["rows"]) == int(new_receipt["rows"]),
                f"{fold}: candidate row universe changed")
        require(int(new_receipt["train_rows"]) == int(old_receipt["train_rows"]),
                f"{fold}: training row universe changed")
        require(set(new_receipt.get("arms", {})) == set(NEW_ARMS), f"{fold}: receipt arms differ")
        for arm in NEW_ARMS:
            fits = new_receipt["arms"][arm].get("fits", [])
            require(len(fits) == 1 and fits[0].get("seed") == SEED, f"{fold}/{arm}: expected exactly one fit")
            model = new_run / "models" / f"{fold}_{arm}_s{SEED}.txt"
            require(model.is_file() and fits[0].get("model_sha256") == sha(model),
                    f"{fold}/{arm}: fitted model receipt/hash mismatch")
        old = _candidate(old_run, old_entry, fold, OLD_ARMS, is_new=False)
        new = _candidate(new_run, new_entry, fold, NEW_ARMS, is_new=True)
        require(old[list(KEYS)].equals(new[list(KEYS)]), f"{fold}: old/new forecast keys differ")
        frame = old[list(KEYS)].copy()
        for arm in OLD_ARMS:
            frame[f"{arm}_old"] = old[f"{arm}_s{SEED}"].to_numpy()
        for arm in NEW_ARMS:
            frame[f"{arm}_set"] = new[f"{arm}_s{SEED}"].to_numpy()
        candidates[fold] = frame
        months[fold] = old_receipt["months"]
        q90[fold] = float(old_receipt["q90"])
    return Preflight(candidates, months, q90, sha(new_seal_path), sha(old_seal_path),
                     sha(new_design_path), sha(old_design_path), old_design["bank_sha256"])


def _truth(pre: Preflight) -> pd.DataFrame:

    for stated, digest in pre.bank_sha256.items():
        path = Path(stated)
        require(path.is_file() and sha(path) == digest, f"training-bank source drift: {path}")
    parts = []
    for fold, _, _ in FOLDS:
        month_parts = [pd.read_parquet(BANK / f"{month}.parquet",
                                       columns=list(KEYS) + ["y_true", "event_replay_flag", "event_block_id"])
                       for month in pre.months[fold]]
        truth = pd.concat(month_parts, ignore_index=True)
        for column in ("issue_time", "target_time"):
            truth[column] = pd.to_datetime(truth[column], utc=True)
        require(not truth.duplicated(list(KEYS)).any(), f"{fold}: duplicate truth key")
        candidate = pre.candidates[fold]
        joined = candidate.merge(truth, on=list(KEYS), how="inner", validate="one_to_one")
        require(len(joined) == len(candidate) == len(truth), f"{fold}: truth/candidate key universe mismatch")
        require(joined.event_replay_flag.isin([0, 1]).all(), f"{fold}: invalid replay flag")
        require(np.isfinite(joined.y_true.to_numpy(dtype="float64")).all(), f"{fold}: nonfinite truth")
        joined["fold"] = fold
        joined["q90"] = pre.q90[fold]
        parts.append(joined)
    return pd.concat(parts, ignore_index=True)


def band_masks(rows: pd.DataFrame) -> dict[str, np.ndarray]:
    y = rows.y_true.to_numpy(dtype="float64")
    return {
        "all": np.ones(len(rows), dtype=bool),
        "high_q90": y > rows.q90.to_numpy(dtype="float64"),
        "y_le_300": y <= 300,
        "y_300_to_5000": (y > 300) & (y <= 5000),
        "y_gt_5000": y > 5000,
    }


def _mae(part: pd.DataFrame, arm: str) -> float:
    den = part.weight.sum()
    return float((part.weight * part[f"{arm}_ae"]).sum() / den) if den else float("nan")


def metrics(rows: pd.DataFrame, masks: dict[str, np.ndarray]) -> pd.DataFrame:
    output = []
    for band in BANDS:
        selected = rows.loc[masks[band]]
        scopes = (("pooled", [("ALL", selected)]), ("fold", selected.groupby("fold")),
                  ("region", selected.groupby("region")), ("horizon", selected.groupby("hgroup")),
                  ("fold_region", selected.groupby(["fold", "region"])))
        for scope, groups in scopes:
            for key, part in groups:
                record = dict(band=band, scope=scope, key="/".join(key) if isinstance(key, tuple) else key,
                              rows=len(part), weight=float(part.weight.sum()))
                record.update({arm: _mae(part, arm) for arm in ARMS})
                output.append(record)
    return pd.DataFrame(output)


def _day_units(rows: pd.DataFrame, masks: dict[str, np.ndarray]) -> pd.DataFrame:
    all_days = rows[["fold", "local_day"]].drop_duplicates().sort_values(["fold", "local_day"])
    output = []
    for band in BANDS:
        subset = rows.loc[masks[band]]
        weight = subset.groupby(["fold", "local_day"], as_index=False).weight.sum()
        block = all_days.merge(weight, on=["fold", "local_day"], how="left")
        for arm in ARMS:
            sums = (subset.assign(weighted_error=subset.weight * subset[f"{arm}_ae"])
                    .groupby(["fold", "local_day"], as_index=False).weighted_error.sum())
            block = block.merge(sums.rename(columns={"weighted_error": f"{arm}_sae"}),
                                on=["fold", "local_day"], how="left")
        output.append(block.fillna(0).assign(band=band))
    return pd.concat(output, ignore_index=True)


def _event_units(rows: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    severe = rows.y_true > 5000
    replay = rows.event_replay_flag == 1
    identity = rows.event_block_id.notna() & rows.event_block_id.astype(str).str.len().gt(0)
    eligible = rows.loc[severe & replay & identity].copy()
    coverage = dict(severe_all_rows=int(severe.sum()), severe_replay_rows=int((severe & replay).sum()),
                    severe_ordinary_hash_rows=int((severe & ~replay).sum()),
                    severe_replay_rows_without_event_id=int((severe & replay & ~identity).sum()),
                    severe_replay_rows_with_event_id=len(eligible),
                    severe_connected_events=int(eligible.event_block_id.nunique()))
    if eligible.empty:
        return pd.DataFrame(columns=["event_block_id", "rows"] + [f"{a}_ae" for a in ARMS]), coverage
    agg = {f"{arm}_ae": "mean" for arm in ARMS}
    events = (eligible.groupby("event_block_id", as_index=False).agg({**agg, "y_true": "size"})
              .rename(columns={"y_true": "rows"}).sort_values("event_block_id"))
    return events, coverage


def event_metrics(rows: pd.DataFrame) -> pd.DataFrame:
    severe = rows.loc[(rows.y_true > 5000) & (rows.event_replay_flag == 1) &
                      rows.event_block_id.notna() & rows.event_block_id.astype(str).str.len().gt(0)]
    result = []
    for scope, group_cols in (("pooled", ["event_block_id"]), ("fold", ["fold", "event_block_id"]),
                              ("region", ["region", "event_block_id"])):
        if severe.empty:
            continue
        block = severe.groupby(group_cols, as_index=False).agg(
            {**{f"{arm}_ae": "mean" for arm in ARMS}, "y_true": "size"}).rename(columns={"y_true": "rows"})
        if scope == "pooled":
            groups = [("ALL", block)]
        else:
            groups = block.groupby(group_cols[0])
        for key, part in groups:
            record = dict(scope=scope, key=key, connected_events=len(part), severe_replay_rows=int(part.rows.sum()))
            record.update({arm: float(part[f"{arm}_ae"].mean()) for arm in ARMS})
            result.append(record)
    return pd.DataFrame(result)


def paired_intervals(day_units: pd.DataFrame, events: pd.DataFrame, rows: pd.DataFrame,
                     masks: dict[str, np.ndarray]) -> pd.DataFrame:
    output = []
    rng = np.random.default_rng(BOOT_SEED)
    days_n = len(day_units.loc[day_units.band == "all"])
    day_picks = rng.integers(0, days_n, size=(BOOT_DRAWS, days_n))
    for band in BANDS:
        block = day_units.loc[day_units.band == band]
        weight = block.weight.to_numpy(dtype="float64")
        den = weight[day_picks].sum(axis=1)
        for first, second in CONTRASTS:
            difference = (block[f"{first}_sae"] - block[f"{second}_sae"]).to_numpy(dtype="float64")
            numer = difference[day_picks].sum(axis=1)
            draws = np.divide(numer, den, out=np.full_like(numer, np.nan), where=den > 0)
            finite = draws[np.isfinite(draws)]
            lo, hi = np.quantile(finite, [0.025, 0.975]) if len(finite) else (np.nan, np.nan)
            selected = rows.loc[masks[band]]
            changed = int((selected[first].to_numpy() != selected[second].to_numpy()).sum())
            output.append(dict(band=band, contrast=f"{first}-{second}", estimand="weighted_row_mae",
                               block_unit="Brisbane_target_day", blocks=days_n, rows=len(selected),
                               changed_rows=changed, estimate=float(difference.sum() / weight.sum()) if weight.sum() else np.nan,
                               ci95_low=float(lo), ci95_high=float(hi), undefined_draws=int((~np.isfinite(draws)).sum()),
                               draws=BOOT_DRAWS, seed=BOOT_SEED))
    if len(events):
        picks = np.random.default_rng(BOOT_SEED).integers(0, len(events), size=(BOOT_DRAWS, len(events)))
        sizes = events.rows.to_numpy(dtype="float64")
        for first, second in CONTRASTS:
            per_event = (events[f"{first}_ae"] - events[f"{second}_ae"]).to_numpy(dtype="float64")
            for estimand, equal in (("severe_event_equal_mae", True), ("severe_connected_row_mae", False)):
                if equal:
                    draws = per_event[picks].mean(axis=1)
                    estimate = per_event.mean()
                else:
                    den = sizes[picks].sum(axis=1)
                    draws = (per_event[picks] * sizes[picks]).sum(axis=1) / den
                    estimate = np.average(per_event, weights=sizes)
                lo, hi = np.quantile(draws, [0.025, 0.975])
                output.append(dict(band="y_gt_5000_event_identified", contrast=f"{first}-{second}",
                                   estimand=estimand, block_unit="connected_event_block_id", blocks=len(events),
                                   rows=int(sizes.sum()), changed_rows=np.nan, estimate=float(estimate),
                                   ci95_low=float(lo), ci95_high=float(hi), undefined_draws=0,
                                   draws=BOOT_DRAWS, seed=BOOT_SEED))
    return pd.DataFrame(output)


def _gate(metrics_table: pd.DataFrame, intervals: pd.DataFrame, *, fixed: bool) -> dict:
    first = 'L_set' if fixed else "L_old"
    numeric = "N_old"
    rule = 'R_set' if fixed else "R_old"
    placebo = 'P_set' if fixed else "P_old"
    def contrast(band: str, second: str) -> pd.Series:
        matching = intervals.loc[(intervals.band == band) & (intervals.estimand == "weighted_row_mae") &
                                 (intervals.contrast == f"{first}-{second}")]
        require(len(matching) == 1, f"missing interval {band} {first}-{second}")
        return matching.iloc[0]
    qn, on, qp, qr, orule = (contrast("high_q90", numeric), contrast("all", numeric),
                             contrast("high_q90", placebo), contrast("high_q90", rule), contrast("all", rule))
    fold = metrics_table.loc[(metrics_table.band == "high_q90") & (metrics_table.scope == "fold")]
    favorable_folds = int(((fold[first] - fold[numeric]) < 0).sum())
    h1 = dict(q90_L_minus_N_negative_and_ci_upper_below_zero=bool(qn.estimate < 0 and qn.ci95_high < 0),
              overall_L_minus_N_not_positive=bool(on.estimate <= 0),
              q90_L_minus_placebo_negative=bool(qp.estimate < 0),
              q90_L_minus_N_favorable_at_least_4_of_6_folds=favorable_folds >= 4)
    h2 = dict(q90_L_minus_rule_negative_and_ci_upper_below_zero=bool(qr.estimate < 0 and qr.ci95_high < 0),
              overall_L_minus_rule_not_positive=bool(orule.estimate <= 0))
    return dict(single_seed_descriptive=True, seed=SEED, h1_components=h1, h1_all=all(h1.values()),
                h2_components=h2, h2_all=all(h2.values()), q90_favorable_folds=favorable_folds)


def score(pre: Preflight, new_run: Path, output: Path) -> dict:
    require(not output.exists(), f"evaluation output already exists: {output}")
    rows = _truth(pre)
    rows["weight"] = np.where(rows.event_replay_flag.to_numpy() == 1, 1.0, 50.0)
    rows["local_day"] = rows.target_time.dt.tz_convert("Australia/Brisbane").dt.strftime("%Y-%m-%d")
    rows["hgroup"] = np.where(rows.horizon.to_numpy() <= 15, "h05_15", "h20_30")
    for arm in ARMS:
        rows[f"{arm}_ae"] = np.abs(rows[arm].to_numpy(dtype="float64") - rows.y_true.to_numpy(dtype="float64"))
    masks = band_masks(rows)
    metric = metrics(rows, masks)
    days = _day_units(rows, masks)
    events, coverage = _event_units(rows)
    emetric = event_metrics(rows)
    intervals = paired_intervals(days, events, rows, masks)
    for first, second in CONTRASTS:
        if len(events):
            events[f"{first}-{second}"] = events[f"{first}_ae"] - events[f"{second}_ae"]
    decisions = dict(state="EXPOSED_HISTORY_SINGLE_SEED_REPAIR_SCORED",
                     resolved=_gate(metric, intervals, fixed=True), old_single_seed=_gate(metric, intervals, fixed=False),
                     interpretation="Descriptive matched F1-F6 NW PHYS repair; not a frozen M1517 improvement or independent confirmation.")
    summary = dict(state=decisions["state"], seed=SEED, folds=[f[0] for f in FOLDS],
                   old_seal_sha256=pre.old_seal_sha256, new_seal_sha256=pre.new_seal_sha256,
                   old_design_sha256=pre.old_design_sha256, new_design_sha256=pre.new_design_sha256,
                   scoring_code_sha256=sha(Path(__file__)), rows=len(rows), event_coverage=coverage,
                   changed_forecast_rows={f"{arm}_set_vs_{arm}_old": int((rows[f"{arm}_set"] != rows[f"{arm}_old"]).sum())
                                          for arm in NEW_ARMS},
                   note="All original and fixed arms use saved or newly fitted seed 20260919 predictions on identical keys.")
    output.mkdir(parents=True, exist_ok=False)
    metric.to_csv(output / "metrics.csv", index=False)
    emetric.to_csv(output / "event_equal_metrics.csv", index=False)
    intervals.to_csv(output / "paired_intervals.csv", index=False)
    days.to_csv(output / "day_units.csv", index=False)
    events.to_csv(output / "event_gains.csv", index=False)
    (output / "decision.json").write_text(json.dumps(decisions, indent=2, allow_nan=False) + "\n")
    (output / "evaluation_manifest.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new-run", type=Path, default=HERE / "run")
    parser.add_argument("--old-run", type=Path, default=OLD_RUN)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--preflight-only", action="store_true", help="candidate hashes, keys and recipe only; never read labels")
    args = parser.parse_args()
    new_run = args.new_run.resolve()
    pre = preflight(new_run, args.old_run)
    if args.preflight_only:
        print(json.dumps(dict(state="NO_TRUTH_PREFLIGHT_PASSED", folds=list(pre.candidates),
                              rows={f: len(d) for f, d in pre.candidates.items()},
                              old_seal_sha256=pre.old_seal_sha256, new_seal_sha256=pre.new_seal_sha256), indent=2))
        return
    output = (args.output or new_run / "evaluation").resolve()
    require(output.is_relative_to(new_run) and not output.is_relative_to(args.old_run.resolve()),
            "evaluation must be written within the new run only")
    print(json.dumps(score(pre, new_run, output), indent=2))


if __name__ == "__main__":
    main()
