'Reconstruct label availability and compare the resulting forecast inputs.'
from __future__ import annotations
import gc
import hashlib
import importlib.util
import json
import resource
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
DEST = OUT / 'input_checks'
forecast_sensitivity = OUT.parent / 'forecast_sensitivity'
forecast_replication = OUT.parent / 'forecast_replication'
PROJ = OUT.parents[2]
AUTO = PROJ / 'forecasting'
INPUTS, EXPECTED = {}, {}
START = time.monotonic()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def bind(path, expected=None):
    path = Path(path).resolve()
    digest = sha(path)
    expected = expected or EXPECTED.get(str(path))
    if expected is not None:
        assert digest == expected, ("source hash changed", str(path))
    INPUTS[str(path)] = {"sha256": digest, "bytes": path.stat().st_size}
    return path


def read(path):
    return json.loads(bind(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, default=str, allow_nan=False)
        f.write("\n")


def rss():
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def log(stage, **kwargs):
    row = dict(stage=stage, utc=pd.Timestamp.now(tz="UTC").isoformat(), peak_rss_bytes=rss(), **kwargs)
    with (DEST / "progress.jsonl").open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")
    print(json.dumps(row, default=str), flush=True)
    if rss() > 1024**3:
        raise MemoryError('label_availability input_checks stage exceeded its 1 GiB ceiling')


def add_manifest(manifest, root=None):
    data = read(manifest)
    for name, entry in data["files"].items():
        path = (Path(root) / name if root else Path(name)).resolve()
        digest = entry["sha256"] if isinstance(entry, dict) else entry
        old = EXPECTED.get(str(path))
        assert old is None or old == digest, ("conflicting frozen bindings", str(path))
        EXPECTED[str(path)] = digest
    return data


def save_array(name, values):
    path = DEST / name
    assert not path.exists()
    with path.open("xb") as f:
        np.save(f, np.asarray(values, dtype=np.int64), allow_pickle=False)
    return dict(path=str(path), relative_path=str(path.relative_to(OUT)), sha256=sha(path), rows=len(values), dtype="int64")


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    freeze = read(OUT / "FREEZE.json")
    assert freeze["state"] == "B6_SPEC_FROZEN_BEFORE_COMPUTATION"
    assert sha(bind(OUT / "SPEC.md")) == freeze["spec_sha256"]
    bind(__file__)
    add_manifest(forecast_sensitivity / "label_audit_OUTPUT_MANIFEST.json", forecast_sensitivity)
    add_manifest(forecast_sensitivity / "label_audit_INPUT_MANIFEST.json")
    add_manifest(forecast_sensitivity / "OUTPUT_MANIFEST.json", forecast_sensitivity)
    add_manifest(forecast_replication / "OUTPUT_MANIFEST.json", forecast_replication)
    complete = read(forecast_sensitivity / "label_audit_COMPLETE.json")
    for path, evidence in complete["files"].items():
        digest = evidence["sha256"]
        assert path not in EXPECTED or EXPECTED[path] == digest
        EXPECTED[path] = digest
    prior_rows = {(row["design"], row["fold"]): row for row in complete["designs"]}
    assert complete["summary"]["unresolved_forecast_keys"] == 0

    module_path = bind(forecast_sensitivity / "label_audit.py")
    spec = importlib.util.spec_from_file_location("b6_reused_b5_label_audit", module_path)
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)


    audit.OUT = OUT
    audit.bind = bind
    audit.log = log
    audit.ROWS, audit.VIOL_TRAIN, audit.VIOL_TEST = [], [], []
    log("reconstruct_start")
    streams = audit.load_canonical()
    meta_path = bind(audit.B1B / "development_metadata.parquet")
    cols = audit.KEYS + ["y_true", "label_available_time", "bank_month", "weight", "event_replay_flag"]
    d = pd.read_parquet(meta_path, columns=cols, use_threads=False)
    assert not d.duplicated(audit.KEYS).any()
    assert np.array_equal(d.weight, np.where(d.event_replay_flag > .5, 1., 50.))
    av, missing, late, reversals = audit.reconstruct(d, streams)
    del streams
    gc.collect()
    canonical_missing = missing > 0
    fallback_path = bind(forecast_sensitivity / "label_audit_raw_fallback_rows.parquet")
    fallback = pd.read_parquet(fallback_path, use_threads=False)
    assert not fallback.duplicated(audit.KEYS).any()
    for field in ["raw_available_resolved", "raw_cache_verified", "cache_raw_clock_match", "cache_raw_price_match", "raw_price_matches_training_y", "raw_clock_matches_stored"]:
        assert fallback[field].all(), field
    assert not fallback.raw_duplicate_or_conflict.any()
    assert fallback.raw_available.eq(fallback.cache_available).all()
    assert fallback.raw_price.eq(fallback.cache_price).all()
    assert np.isclose(fallback.raw_price, fallback.y_true, rtol=1e-6, atol=1e-5).all()

    for path in sorted(set(fallback.raw_path) | set(fallback.cache_path)):
        assert path in complete["files"], ("unbound raw fallback source", path)
        bind(path)
    fallback_index = pd.MultiIndex.from_frame(fallback[audit.KEYS])
    need_index = pd.MultiIndex.from_frame(d.loc[canonical_missing, audit.KEYS])
    take = fallback_index.get_indexer(need_index)
    assert (take >= 0).all() and len(take) == len(fallback)
    assert len(take) == complete["summary"]["canonical_missing_unique_forecast_keys"]
    selected = fallback.iloc[take]
    assert np.isclose(d.loc[canonical_missing, "y_true"].to_numpy(), selected.raw_price.to_numpy(), rtol=1e-6, atol=1e-5).all()
    av[canonical_missing] = audit.ns(selected.raw_available)
    missing[canonical_missing] = 0
    late[canonical_missing] = av[canonical_missing] > audit.ns(d.loc[canonical_missing, "target_time"]) + audit.STEP
    assert not (av == audit.NAT).any()
    assert np.array_equal(av, audit.ns(d.label_available_time)), "verified clocks differ from stored clocks"
    availability = save_array("verified_availability.npy", av)
    del fallback, selected, fallback_index, need_index, take
    gc.collect()
    log("clocks_verified", rows=len(d), canonical_missing_rows=int(canonical_missing.sum()), unresolved_rows=int(missing.sum()))

    main_design = read(AUTO / 'run_forecasts/design_binding.json')
    e3_design = read(AUTO / "extension_p5/run/design_binding.json")
    b4_design = read(forecast_replication / 'aligned/design.json')
    e3_corrected = read(forecast_sensitivity / 'e3/aligned/design.json')
    assert main_design["folds"] == e3_design["folds"]
    assert main_design["bank_sha256"] == e3_design["bank_sha256"]
    assert main_design["seeds"] == e3_design["seeds"] == [20260919, 20260920, 20260921]

    bank_columns = audit.KEYS + ["label_available_time", "event_replay_flag"]
    for path, digest in main_design["bank_sha256"].items():
        path = bind(path, digest)
        month = pd.read_parquet(path, columns=bank_columns, use_threads=False).sort_values(["issue_time", "region", "horizon"], kind="mergesort").reset_index(drop=True)
        cached = d.loc[d.bank_month == path.stem, bank_columns].reset_index(drop=True)
        pd.testing.assert_frame_equal(month, cached, check_dtype=False)
        del month, cached
    log("bank_and_E3_shared_design_verified", banks=len(main_design["bank_sha256"]))

    masks, removed_parts = {}, []
    checked_old_rows = 0
    for fold, first, last in main_design["folds"]:
        nominal = pd.Timestamp(first + "-01", tz="Australia/Brisbane").tz_convert("UTC")
        test_mask = d.bank_month.between(first, last).to_numpy()
        test = d.loc[test_mask].reset_index(drop=True)
        start = min(nominal, test.issue_time.min())
        old = ((d.target_time < nominal) & (d.label_available_time < nominal)).to_numpy()
        new = old & (av < start.value)
        assert not old[test_mask].any() and not new[test_mask].any()
        old_receipt = read(AUTO / f"run_forecasts/receipts/{fold}.json")
        e3_receipt = read(AUTO / f"extension_p5/run/receipts/{fold}.json")
        expected_counts = (int(old.sum()), int(test_mask.sum()))
        for rec in (old_receipt, e3_receipt, b4_design["folds"][fold], e3_corrected["folds"][fold]):
            assert expected_counts == (rec["train_rows"], rec["test_rows"]), ("frozen mask mismatch", fold)
        for design, arms, new_name in [("main_B4_corrected", main_design["arms"], "main_B6_corrected"), ("E3_original_and_B5_same_masks", e3_design["arms"], "E3_B6_corrected")]:
            old_row = audit.audit_design(d, av, missing, late, reversals, old, test, design, fold, nominal, arms, main_design["seeds"], expected_counts[0], expected_counts[1], meta_path)
            prior = prior_rows[design, fold]
            for key, value in old_row.items():
                assert value == prior[key], ('forecast_sensitivity old audit mismatch', fold, design, key, value, prior[key])
            old_row["condition"] = "unrepaired_identity"
            checked_old_rows += 1
            new_row = audit.audit_design(d, av, missing, late, reversals, new, test, new_name, fold, start, arms, main_design["seeds"], int(new.sum()), expected_counts[1], meta_path)
            new_row["condition"] = "boundary_repaired"
            new_row["nominal_target_month_cutoff"] = nominal.isoformat()
            for field in ["train_missing_constituent_rows", "train_strict_cutoff_violations", "train_strict_earliest_origin_violations", "test_origin_strict_violating_keys", "test_origin_unknown_label_keys", "test_origin_equality_only_keys"]:
                assert new_row[field] == 0, (fold, new_name, field)
            assert new_row["strict_all_test_origin_training_information_available"]
        removal = old & ~new
        ledger = d.loc[removal, audit.KEYS + ["label_available_time", "weight"]].copy()
        ledger.insert(0, "row_id", np.flatnonzero(removal))
        ledger.insert(0, "fold", fold)
        ledger["verified_label_available_time"] = pd.to_datetime(av[removal], utc=True)
        ledger["operational_fold_start"] = start
        ledger["nominal_target_month_cutoff"] = nominal
        ledger["reason"] = np.where(av[removal] == start.value, "equal_to_operational_start", "later_than_operational_start")
        removed_parts.append(ledger)
        masks[fold] = dict(nominal_cutoff=nominal.isoformat(), operational_fold_start=start.isoformat(), earliest_test_origin=test.issue_time.min().isoformat(), old_train_rows=int(old.sum()), train_rows=int(new.sum()), test_rows=len(test), removed_rows=int(removal.sum()), removed_equal=int((removal & (av == start.value)).sum()), removed_later=int((removal & (av > start.value)).sum()), old_train_indices=save_array(f"old_train_indices_{fold}.npy", np.flatnonzero(old)), train_indices=save_array(f"train_indices_{fold}.npy", np.flatnonzero(new)), test_indices=save_array(f"test_indices_{fold}.npy", np.flatnonzero(test_mask)))
        log("fold_boundary_verified", fold=fold, old_train_rows=int(old.sum()), train_rows=int(new.sum()), removed_rows=int(removal.sum()))
        del test, old, new, ledger
        gc.collect()


    window = pd.read_parquet(bind(AUTO / "windows/C/features.parquet"), columns=audit.KEYS, use_threads=False)
    window["weight"] = 1.
    c_cutoff = window.target_time.min()
    c_train = ((d.target_time < c_cutoff) & (d.label_available_time < c_cutoff)).to_numpy()
    assert c_train.all()
    c_rows = []
    for design, arms in [("main_B4_corrected", main_design["arms"]), ("E3_original_and_B5_same_masks", e3_design["arms"])]:
        prior = prior_rows[design, "C"]
        row = audit.audit_design(d, av, missing, late, reversals, c_train, window, design, "C", c_cutoff, arms, main_design["seeds"], prior["train_rows"], prior["test_rows"], meta_path)
        for key, value in row.items():
            assert value == prior[key], ('C forecast_sensitivity mismatch', design, key)
        assert row["strict_all_test_origin_training_information_available"]
        row["condition"] = "unchanged_C_evidence"
        c_rows.append(row)
        checked_old_rows += 1
    del window
    gc.collect()

    removal_ledger = pd.concat(removed_parts, ignore_index=True)
    removal_ledger.to_parquet(DEST / "removed_training_rows.parquet", index=False)
    removal_ledger.to_csv(DEST / "removed_training_rows.csv", index=False)
    pd.DataFrame(audit.ROWS).to_csv(DEST / "label_audit_by_design.csv", index=False)

    pd.concat(audit.VIOL_TRAIN, ignore_index=True).to_parquet(DEST / "label_audit_training_boundary_rows.parquet", index=False)
    pd.concat(audit.VIOL_TEST, ignore_index=True).to_parquet(DEST / "label_audit_affected_test_keys.parquet", index=False)
    write(DEST / "label_audit_RESULT.json", dict(passed=True, reused_B5_audit_sha256=sha(module_path), old_rows_reproduced=checked_old_rows, designs=audit.ROWS, interpretation='Old rows exactly reproduce forecast_sensitivity COMPLETE; every new main/E3 fold has verified clocks and zero strict cutoff/origin violations.'))
    for path, evidence in INPUTS.items():
        assert sha(path) == evidence["sha256"], ("input changed during audit", path)
    write(DEST / "INPUT_MANIFEST.json", dict(files=INPUTS, spec_sha256=freeze["spec_sha256"], all_read_source_hashes_rechecked=True))
    artifacts = {str(path.relative_to(OUT)): {"sha256": sha(path), "bytes": path.stat().st_size} for path in sorted(DEST.iterdir()) if path.is_file() and path.name != "progress.jsonl"}
    write(OUT / "BOUNDARY.json", dict(passed=True, state="RECORDED_LABEL_BOUNDARY_REPAIRED_ZERO_VIOLATIONS", e3_applicable=True, spec_sha256=freeze["spec_sha256"], availability=availability, masks=masks, canonical_missing_forecast_keys_resolved=int(canonical_missing.sum()), unresolved_clocks=0, verified_stored_clock_discrepancies=0, old_audit_rows_exactly_reproduced=checked_old_rows, new_strict_origin_violations=0, new_unknown_origin_violations=0, new_equality_origin_violations=0, C=dict(clean=True, refit=False, evidence=c_rows), e3_applicability=dict(shared_folds=True, shared_bank_hashes=True, shared_mask_counts=True, shared_seeds=True, actual_original_receipts_checked=True, B5_corrected_design_counts_checked=True, B5_boundary_audit_exactly_reproduced=True), artifacts=artifacts, peak_rss_bytes=rss(), wall_seconds=time.monotonic()-START, limitations="Recorded publication/update clocks only; not historical first-release vintage proof."))
    log("boundary_complete", passed=True, new_violations=0, removed_training_row_incidences=len(removal_ledger))


if __name__ == "__main__":
    main()
