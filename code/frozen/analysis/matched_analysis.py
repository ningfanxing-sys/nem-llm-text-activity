'Compare notice representations on matched forecasts across three seeds.'
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PREP = HERE.parent
EXP = PREP.parent
REPAIR = EXP / 'notice_comparison'
sys.path.insert(0, str(REPAIR))
import evaluate_notice_records as er

OLD_RUN, SET1_RUN, SEED_VALIDATION_RUN, HELDOUT_SEEDS_RUN = er.OLD_RUN, REPAIR / "run", PREP / "seeds" / "run", PREP / 'seed_replications' / "run"
SEEDS = (20260919, 20260920, 20260921)
OLD_ARMS, SET_ARMS = ("N", "R", "L", "P"), ("R", "L", "P")
KEYS = list(er.KEYS)
WINDOW = 22
MAIN = (('L_set', "N_old"), ('L_set', 'R_set'), ('L_set', 'P_set'), ('R_set', "N_old"), ('P_set', "N_old"),
        ("L_old", "N_old"), ("L_old", "R_old"), ("L_old", "P_old"), ("R_old", "N_old"), ("P_old", "N_old"),
        ('L_set', "L_old"), ('R_set', "R_old"), ('P_set', "P_old"))


def _read(path):
    return json.loads(Path(path).read_text())


def _frame(path, sha256, rows, columns):
    er.require(er.sha(Path(path)) == sha256, f"prediction hash mismatch: {path}")
    frame = pd.read_parquet(path, columns=KEYS + columns)
    er.require(len(frame) == rows and not frame.duplicated(KEYS).any(), f"row universe problem: {path}")
    er.require(not set(frame.columns) & er.FORBIDDEN, f"truth in candidate: {path}")
    for c in ("issue_time", "target_time"):
        frame[c] = pd.to_datetime(frame[c], utc=True)
    return frame.sort_values(KEYS, kind="mergesort").reset_index(drop=True)


def candidates(mode):
    old_seal, old_design = _read(OLD_RUN / "candidate_bank_seal.json"), _read(OLD_RUN / "design_binding.json")
    er.require(old_seal.get("state") == "NW_CANDIDATE_BANK_SEALED" and old_design.get("seeds") == list(SEEDS),
               "old NW PHYS bank not sealed with the three-seed contract")
    runs = {}
    if mode == "full":
        snapshot = er.sha(REPAIR / 'notice_event_records.py')
        seed_binding = _read(SEED_VALIDATION_RUN / "seed_design_binding.json")
        seed_receipt = _read(SEED_VALIDATION_RUN / "seed_candidate_receipt.json")
        er.require(seed_binding["assembler_snapshot_sha256"] == snapshot == seed_receipt["assembler_snapshot_sha256"]
                   and seed_receipt.get("scoring_started") is False, "seed-completion run not bound to the repair assembler")
        er.require(_read(SET1_RUN / "repair_design_binding.json")["repair_notice_code_sha256"] == snapshot,
                   "seed-20260919 run not bound to the repair assembler")
        runs = {(20260919,): _read(SET1_RUN / "candidate_bank_seal.json"),
                (20260920, 20260921): _read(SEED_VALIDATION_RUN / "candidate_bank_seal.json")}
    if mode == "full_v2":
        v2_hash = er.sha(PREP / 'notice_assembly' / 'notice_event_records.py')
        binding, receipt = _read(HELDOUT_SEEDS_RUN / "v2_design_binding.json"), _read(HELDOUT_SEEDS_RUN / "v2_candidate_receipt.json")
        er.require(binding['notice_assembly_sha256'] == v2_hash == receipt['notice_assembly_sha256'] and
                   receipt.get("scoring_started") is False and binding["seeds"] == list(SEEDS),
                   "v2 run not bound to the current v2 assembler with three seeds")
        runs = {SEEDS: _read(HELDOUT_SEEDS_RUN / "candidate_bank_seal.json")}
    if runs:
        for seal in runs.values():
                er.require(str(seal.get("state", "")).endswith("CANDIDATE_BANK_SEALED") and
                           seal.get("target_scoring_before_seal") is False, "repaired bank not sealed before scoring")
    cands, months, q90 = {}, {}, {}
    for i, entry in enumerate(old_seal["files"]):
        fold = entry["fold"]
        receipt = _read(OLD_RUN / "receipts" / f"{fold}.json")
        old = _frame(entry["path"], entry["sha256"], entry["rows"], [f"{a}_s{s}" for a in OLD_ARMS for s in SEEDS])
        frame = old[KEYS].copy()
        for a in OLD_ARMS:
            for s in SEEDS:
                frame[f"{a}_old_s{s}"] = old[f"{a}_s{s}"].to_numpy("float64")
            frame[f"{a}_old"] = frame[[f"{a}_old_s{s}" for s in SEEDS]].mean(axis=1)
        for seeds, seal in runs.items():
            new_entry = seal["files"][i]
            er.require(new_entry["fold"] == fold and float(new_entry["q90"]) == float(receipt["q90"]), f"{fold}: fold or q90 drift")
            new = _frame(new_entry["path"], new_entry["sha256"], entry["rows"], [f"{a}_s{s}" for a in SET_ARMS for s in seeds])
            er.require(new[KEYS].equals(old[KEYS]), f"{fold}: forecast keys differ")
            for a in SET_ARMS:
                for s in seeds:
                    frame[f"{a}_set_s{s}"] = new[f"{a}_s{s}"].to_numpy("float64")
        if runs:
            for a in SET_ARMS:
                frame[f"{a}_set"] = frame[[f"{a}_set_s{s}" for s in SEEDS]].mean(axis=1)
        cands[fold], months[fold], q90[fold] = frame, receipt["months"], float(receipt["q90"])
    return er.Preflight(cands, months, q90, "", er.sha(OLD_RUN / "candidate_bank_seal.json"), "",
                        er.sha(OLD_RUN / "design_binding.json"), old_design["bank_sha256"])


def interaction(days, events, picks):
    out = []
    for band in er.BANDS:
        block = days.loc[days.band == band]
        w = block.weight.to_numpy("float64")
        d = ((block.L_set_sae - block.R_set_sae) - (block.L_old_sae - block.R_old_sae)).to_numpy("float64")
        den = w[picks].sum(1)
        draws = np.divide(d[picks].sum(1), den, out=np.full(len(picks), np.nan), where=den > 0)
        lo, hi = np.nanquantile(draws, [0.025, 0.975])
        out.append(dict(band=band, contrast='(L_set-R_set)-(L_old-R_old)', estimand="weighted_row_mae",
                        estimate=float(d.sum() / w.sum()), ci95_low=float(lo), ci95_high=float(hi)))
    if len(events):
        per = ((events.L_set_ae - events.R_set_ae) - (events.L_old_ae - events.R_old_ae)).to_numpy("float64")
        ep = np.random.default_rng(er.BOOT_SEED).integers(0, len(per), size=(er.BOOT_DRAWS, len(per)))
        lo, hi = np.quantile(per[ep].mean(1), [0.025, 0.975])
        out.append(dict(band="y_gt_5000_event_identified", contrast='(L_set-R_set)-(L_old-R_old)',
                        estimand="severe_event_equal_mae", estimate=float(per.mean()), ci95_low=float(lo), ci95_high=float(hi)))
    return pd.DataFrame(out)


def windows(days, pairs):
    block = days.loc[days.band == "all"].sort_values("local_day")
    day = block.groupby("local_day")[["weight"] + [c for c in block.columns if c.endswith("_sae")]].sum()
    result, table = {}, pd.DataFrame(index=day.index)
    for first, second in pairs:
        for scope, s in (("day", day), ("window22", day.rolling(WINDOW).sum().dropna())):
            imp = (s[f"{second}_sae"] - s[f"{first}_sae"]) / s[f"{second}_sae"] * 100
            q = np.percentile(imp, [0, 5, 25, 50, 75, 95, 100])
            result[f"{scope}|{first}-vs-{second}_pct"] = dict(
                n=int(len(imp)), min=q[0], p5=q[1], p25=q[2], median=q[3], p75=q[4], p95=q[5], max=q[6],
                share_ge_3pct=float((imp >= 3).mean()), share_ge_10pct=float((imp >= 10).mean()),
                share_le_minus_3pct=float((imp <= -3).mean()))
            if scope == "day":
                table[f"{first}-vs-{second}_pct"] = imp
    result["note"] = "NW rows are a weighted sample (ordinary 2% x 50); single-day values include sampling noise."
    return result, table


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["validate_old", "full", "full_v2"], required=True)
    mode = ap.parse_args().mode
    out_dir = HERE / f"output_{mode}"
    er.require(not out_dir.exists(), f"output exists, refuse rescore: {out_dir}")
    pre = candidates(mode)
    per_seed = [f"{a}_old_s{s}" for a in OLD_ARMS for s in SEEDS] + (
        [f"{a}_set_s{s}" for a in SET_ARMS for s in SEEDS] if mode != "validate_old" else [])
    main_arms = [f"{a}_old" for a in OLD_ARMS] + ([f"{a}_set" for a in SET_ARMS] if mode != "validate_old" else [])
    er.ARMS = tuple(main_arms + per_seed)
    er.CONTRASTS = tuple(c for c in MAIN if set(c) <= set(main_arms))
    rows = er._truth(pre)                      # Read labels after validating the candidate forecasts.
    rows["weight"] = np.where(rows.event_replay_flag.to_numpy() == 1, 1.0, 50.0)
    rows["local_day"] = rows.target_time.dt.tz_convert("Australia/Brisbane").dt.strftime("%Y-%m-%d")
    rows["hgroup"] = np.where(rows.horizon.to_numpy() <= 15, "h05_15", "h20_30")
    for arm in er.ARMS:
        rows[f"{arm}_ae"] = np.abs(rows[arm].to_numpy("float64") - rows.y_true.to_numpy("float64"))
    masks = er.band_masks(rows)
    metric = er.metrics(rows, masks)
    days = er._day_units(rows, masks)
    events, coverage = er._event_units(rows)
    intervals = er.paired_intervals(days, events, rows, masks)
    out_dir.mkdir(parents=True)
    metric.to_csv(out_dir / "metrics.csv", index=False)
    intervals.to_csv(out_dir / "paired_intervals.csv", index=False)
    er.event_metrics(rows).to_csv(out_dir / "event_equal_metrics.csv", index=False)
    summary = dict(mode=mode, rows=len(rows), event_coverage=coverage, seeds=list(SEEDS))
    pooled = metric.loc[metric.scope == "pooled"].set_index("band")
    seed_rows = []
    for s in SEEDS:
        for band in ("all", "high_q90", "y_gt_5000"):
            rec = dict(seed=s, band=band, L_old_minus_R_old=pooled.loc[band, f"L_old_s{s}"] - pooled.loc[band, f"R_old_s{s}"],
                       L_old_minus_N_old=pooled.loc[band, f"L_old_s{s}"] - pooled.loc[band, f"N_old_s{s}"])
            if mode != "validate_old":
                rec.update(L_set_minus_R_set=pooled.loc[band, f"L_set_s{s}"] - pooled.loc[band, f"R_set_s{s}"],
                           L_set_minus_N_old=pooled.loc[band, f"L_set_s{s}"] - pooled.loc[band, f"N_old_s{s}"])
            seed_rows.append(rec)
    pd.DataFrame(seed_rows).to_csv(out_dir / "per_seed_point_estimates.csv", index=False)
    if mode == "validate_old":
        sealed = pd.read_csv(OLD_RUN / "evaluation" / "metrics.csv")
        sealed = sealed.loc[sealed.scope == "pooled"].set_index("band")
        boot = pd.read_csv(OLD_RUN / "evaluation" / "bootstrap.csv")
        diffs = [abs(pooled.loc[b, f"{a}_old"] - sealed.loc[b, a]) for b in ("all", "high_q90") for a in OLD_ARMS]
        checks = []
        for band in ("all", "high_q90"):
            for first, second in (("L", "N"), ("L", "R"), ("R", "N"), ("L", "P"), ("P", "N")):
                mine = intervals.loc[(intervals.band == band) & (intervals.contrast == f"{first}_old-{second}_old") &
                                     (intervals.estimand == "weighted_row_mae")].iloc[0]
                ref = boot.loc[(boot.band == band) & (boot.contrast == f"{first}-{second}")].iloc[0]
                checks.append(max(abs(mine.estimate - ref.estimate), abs(mine.ci95_low - ref.ci95_low), abs(mine.ci95_high - ref.ci95_high)))
        summary.update(max_abs_diff_pooled_mae=float(max(diffs)), max_abs_diff_contrast_and_ci=float(max(checks)))
    else:
        picks = np.random.default_rng(er.BOOT_SEED).integers(0, len(days.loc[days.band == "all"]),
                                                             size=(er.BOOT_DRAWS, len(days.loc[days.band == "all"])))
        interaction(days, events, picks).to_csv(out_dir / "assembler_interaction.csv", index=False)
        dist, table = windows(days, (('L_set', "N_old"), ('L_set', 'R_set'), ('P_set', "N_old"), ('R_set', "N_old")))
        (out_dir / "window_distribution.json").write_text(json.dumps(dist, indent=1, default=float))
        table.to_csv(out_dir / "per_day_improvement.csv")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=float))
    print(json.dumps(summary, indent=1, default=float))


if __name__ == "__main__":
    main()
