'Select the notice quantity sample from source records.'
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import prepare_notice_scope as base

HERE = Path(__file__).resolve().parent
SALT = 'notice_extraction-PILOT-v1.3'
OUTPUTS = ("pilot_ids_1_3.json", "PILOT_SELECTION_1_3.json")
EXCLUSIONS = ("pilot_ids.json", "pilot_ids_1_1.json", "pilot_ids_1_2.json", "EXCLUDED_HUMAN60_IDS.json")
EXPECTED_EXCLUSION_COUNTS = (20, 20, 20, 60)


def verify_spec() -> dict:
    freeze = json.loads((HERE / "NRX4_SPEC_FREEZE.json").read_text())
    for name, expected in freeze["files_sha256"].items():
        if base.sha_file(HERE / name) != expected:
            raise RuntimeError(f"NRX4 specification/input changed: {name}")
    spec = json.loads((HERE / "NRX4_SPEC.json").read_text())
    if spec["pilot"]["salt"] != SALT or spec["model_calls_authorized_in_this_task"] != 0:
        raise RuntimeError('selection salt or no-call input_checks changed')
    if spec["pilot"]["exclude"] != list(EXCLUSIONS):
        raise RuntimeError("fresh pilot exclusion rule changed")
    if 'prepare_quantity_sample.py' not in freeze["files_sha256"]:
        raise RuntimeError("fresh selection script was not frozen before computation")
    return spec


def exclusion_sets() -> tuple[set[str], ...]:
    groups = []
    for name, expected_count in zip(EXCLUSIONS, EXPECTED_EXCLUSION_COUNTS):
        ids = json.loads((HERE / name).read_text())
        if not isinstance(ids, list) or len(ids) != expected_count or any(not isinstance(i, str) for i in ids):
            raise RuntimeError("earlier pilot/human exclusion cardinality or ID type changed")
        group = set(ids)
        if len(group) != expected_count:
            raise RuntimeError("earlier pilot/human exclusion cardinality changed")
        groups.append(group)
    if any(groups[i] & groups[j] for i in range(len(groups)) for j in range(i + 1, len(groups))):
        raise RuntimeError("earlier pilot/human exclusions are not all distinct")
    return tuple(groups)


def select_source_rows(rows: list[dict], excluded: set[str]) -> tuple[list[str], dict]:

    original_salt = base.PILOT_SEED
    try:
        base.PILOT_SEED = SALT
        ids, details = base.select_pilot(rows, excluded)
    finally:
        base.PILOT_SEED = original_salt
    if len(ids) != 20 or len(set(ids)) != 20 or set(ids) & excluded:
        raise RuntimeError("fresh selection is not 20 distinct, excluded-source-free IDs")
    if any(details[key] != dict(Counter({s: 4 for s in strata})) for key, strata in
           (("selected_counts_by_period", base.PERIODS), ("selected_counts_by_type", base.TYPES))):
        raise RuntimeError("balanced source margins failed")
    return ids, details


def selected() -> tuple[list[str], dict]:
    verify_spec()
    receipt = json.loads((HERE / "SCOPE_RECEIPT.json").read_text())

    for name in ("scope.jsonl", "pilot_ids.json", "PILOT_SELECTION.json", "EXCLUDED_HUMAN60_IDS.json"):
        if base.sha_file(HERE / name) != receipt["files"][name]["sha256"]:
            raise RuntimeError(f"v1 source preparation changed: {name}")
    for path, facts in receipt["source_files"].items():
        if base.sha_file(path) != facts["sha256"]:
            raise RuntimeError(f"source changed since preparation: {path}")
    old, old_1_1, old_1_2, human = exclusion_sets()
    earlier = old | old_1_1 | old_1_2
    excluded = earlier | human

    rows, seen = [], set()
    for _, row in base.jsonl(HERE / "scope.jsonl"):
        ident = row["notice_id"]
        if ident in seen or row["notice_key"] != ident:
            raise RuntimeError("source identity is duplicated or inconsistent")
        seen.add(ident)
        if base.sha_bytes(base.canonical_json(base.notice_payload(row))) != row["input_sha256"]:
            raise RuntimeError(f"source payload hash changed: {ident}")
        if row["version_sha256"] != row["input_sha256"]:
            raise RuntimeError(f"source version hash changed: {ident}")
        rows.append({key: row[key] for key in ("notice_id", "period", "pilot_type", "version_sha256")})
    if len(rows) != receipt["total_notice_count"] or not excluded.issubset(seen):
        raise RuntimeError("source count or exclusion coverage changed")
    ids, details = select_source_rows(rows, excluded)
    details.update({"state": "FRESH_SOURCE_ONLY_PILOT_SELECTED", "contract_version": "1.3",
                    "salt": SALT, "excluded_v1_pilot_count": len(old),
                    'excluded_label_specification_pilot_count': len(old_1_1),
                    'excluded_window_specification_pilot_count': len(old_1_2),
                    "excluded_earlier_pilot_count": len(earlier),
                    "excluded_human_review_count": len(human),
                    "excluded_distinct_total": len(excluded),
                    "overlap_with_v1": [], 'overlap_with_label_specification': [], 'overlap_with_window_specification': [],
                    "overlap_with_human_review": [], "model_calls": 0,
                    "spec_freeze_sha256": base.sha_file(HERE / "NRX4_SPEC_FREEZE.json"),
                    "scope_receipt_sha256": base.sha_file(HERE / "SCOPE_RECEIPT.json"),
                    "selection_script_sha256": base.sha_file(Path(__file__)),
                    "base_selection_script_sha256": base.sha_file(HERE / "prepare_notice_scope.py"),
                    "exclusion_files_sha256": {name: base.sha_file(HERE / name) for name in EXCLUSIONS}})
    return ids, details


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    ids, details = selected()
    if args.check:
        for name, value in zip(OUTPUTS, (ids, details)):
            if json.loads((HERE / name).read_text()) != value:
                raise RuntimeError(f"frozen fresh selection differs: {name}")
        print(json.dumps({"state": "PASS_FRESH_PILOT_SELECTION", "notices": len(ids), "salt": SALT}))
        return
    if (HERE / "CONTRACT_FREEZE_1_3.json").exists() or (HERE / "results_1_3").exists() or any((HERE / name).exists() for name in OUTPUTS):
        raise RuntimeError("v1.3 selection or runtime already exists; use --check, never overwrite")
    for name, value in zip(OUTPUTS, (ids, details)):
        with (HERE / name).open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"state": details["state"], "notices": len(ids), "ids": ids,
                      "selected_counts_by_period": details["selected_counts_by_period"],
                      "selected_counts_by_type": details["selected_counts_by_type"]}))


if __name__ == "__main__":
    main()
