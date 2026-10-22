#!/usr/bin/env python3
"""Prepare an outcome-blind, exact-text notice scope and deterministic pilot.

Reads source notices and fixed human-review IDs only. No extraction is executed.
FINAL3 source admission is reproduced from its inherited source-only loader,
without importing any assembler (or reading any M331 label table).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import itertools
import json
import re
from collections import Counter, defaultdict, deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[2]
LAMP = PROJ.parents[1]
REGISTRY = LAMP / "artifacts/pivot_bq/m463_corrected_notice_timing/corrected_notice_registry.csv"
DATA26 = PROJ / "autopilot/q1_audits/DATA26/notices"
HUMAN_IDS = PROJ / "autopilot/q1_audits/FINAL/final3/human60_changes.csv"
SOURCE_LOADER = LAMP / "experiments/notice_window_llm_increment_20260924/nw_notices.py"
PERIODS = ("2021-22", "2023", "2024", "2025-11..2026-02", "2026-07..09")
TYPES = ("reserve/LOR", "reclassification", "intervention/direction",
         "transfer/constraint", "general/other")
PILOT_SEED = "NRX-PILOT-v1"
REGISTRY_DIGESTS = {}
SPEC = {
    "state": "FROZEN_SOURCE_ONLY_PREPARATION_RULE",
    "source_admission": "All M463 rows with is_relevant_operational=True and available_time_valid=True; assert17583 unique IDs; no date-based removal",
    "data26_admission": "Union of numeric-canonical IDs from normalized_registry and normalized_notices whose source_clock_aest is2026-03-01..2026-09-30 inclusive",
    "id_normalization": "strip identifier whitespace and trailing .0 serialization suffix; never normalize title/body",
    "canonical_version": "FINAL3 M463 exact row wins overlap; otherwise adopted DATA26 normalized_registry canonical row; missing registry ID requires one unique exact input version or fails",
    "version_handling": "preserve unique text/clock/source variants in SOURCE_VERSIONS.jsonl; record conflicts explicitly; no silent replacement",
    "input": "one object notice_id/title/body/clocks; source hashes/types/period/selection metadata sidecars only; no truncation or whitespace normalization",
    "periods": list(PERIODS), "types": list(TYPES),
    "pilot": {"total": 20, "per_period": 4, "per_type": 4,
              "excluded": "60 unique numeric notice IDs from FINAL3 human60_changes.csv; only notice_id/review_id columns projected",
              "cell_rule": "Try lexicographically ordered permutations of one omitted type per period; first with all20 retained cells nonempty. Choose smallest SHA256 in each retained cell. If no feasible permutation, deterministic capacity maxflow with4 per period/type and per-cell capacity eligible count, then smallest hashes per allocated cell. Fail if quotas infeasible.",
              "hash": "SHA256(UTF8('NRX-PILOT-v1' + NUL + canonical notice_id + NUL + version_sha256)); ID breaks hash ties",
              "period_clock": "source raw_time_local/source_clock_aest AEST date; July1..Sep30 eligible, including July27..Sep30 scope; no March..June pilot"},
    "outcome_rows_read": False, "label_rows_read": 0, "llm_calls": 0,
}


def canonical_json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_id(value) -> str:
    result = re.sub(r"\.0+$", "", str(value).strip())
    if not result.isdigit():
        raise ValueError(f"non-numeric notice identifier: {result!r}")
    return result


def notice_payload(row: dict) -> dict:
    return {key: row[key] for key in ("notice_id", "title", "body", "clocks")}


def period_for(day: str) -> str:
    if "2021-10-01" <= day <= "2022-12-31": return "2021-22"
    if "2023-01-01" <= day <= "2023-12-31": return "2023"
    if "2024-01-01" <= day <= "2024-07-31": return "2024"
    if "2025-11-01" <= day <= "2026-02-28": return "2025-11..2026-02"
    if "2026-07-01" <= day <= "2026-09-30": return "2026-07..09"
    if "2026-03-01" <= day <= "2026-06-30": return "2026-03..06"
    raise ValueError(f"source date outside specified scope: {day}")


def pilot_type(source_type: str) -> str:
    value = source_type.upper()
    if "RECLASS" in value: return "reclassification"
    if "INTERVENTION" in value or "DIRECTION" in value or "INSTRUCTION" in value:
        return "intervention/direction"
    if "INTER-REGIONAL" in value or "CONSTRAINT" in value:
        return "transfer/constraint"
    if "RESERVE" in value or "LOR" in value or "LRC" in value:
        return "reserve/LOR"
    return "general/other"


def make_row(raw: dict, registry_path: Path, line: int, source_kind: str) -> dict:
    ident = canonical_id(raw["notice_id"])
    title, body = raw.get("title", ""), raw.get("text", "")
    if not isinstance(title, str) or not isinstance(body, str):
        raise ValueError(f"title/body must be literal source strings for {ident}")
    clock = raw.get("raw_time_local") or raw.get("source_clock_aest")
    if not isinstance(clock, str) or len(clock) < 10:
        raise ValueError(f"missing source clock for {ident}")
    clocks = {"raw_time_local": clock,
              "available_time_utc": raw["available_time_utc"],
              "timezone_contract": raw.get("timezone_contract") or "AEST_FIXED_UTC_PLUS_10"}
    if source_kind == "DATA26":
        for key in ("source_clock_aest", "issue_datetime", "issue_date", "lastchanged",
                    "creation_datetime", "effective_datetime"):
            if raw.get(key): clocks[key] = raw[key]
    day = (raw["source_clock_aest"] if source_kind == "DATA26" else clock)[:10]
    group = "DATA26_CONFIRMATION_LEADIN_20260727_TO_20260930" if day >= "2026-07-27" else (
        "DATA26_INCOMPLETE_202603_TO_20260726" if day >= "2026-03-01" else "FINAL3_HISTORICAL")
    result = {"notice_key": ident, "notice_id": ident, "title": title, "body": body,
              "clocks": clocks, "source_notice_type": raw.get("notice_type", ""),
              "period": period_for(day), "scope_group": group, "source_day_aest": day,
              "pilot_type": pilot_type(raw.get("notice_type", "")),
              "source_kind": source_kind, "original_source_notice_id": raw["notice_id"],
              "source_registry_path": str(registry_path), "source_registry_line": line,
              "source_registry_sha256": registry_digest(registry_path),
              "source_text_clock_sha256": sha_bytes(canonical_json({"notice_id": ident, "title": title,
                  "body": body, "source_clock_aest": raw.get("source_clock_aest") or clock})),
              "source_file": raw.get("source_file", ""),
              "source_file_sha256": raw.get("source_file_sha256") or raw.get("source_file_sha256_y") or raw.get("source_file_sha256_x"),
              "source_url": raw.get("source_url", ""),
              "source_capture_time_utc": raw.get("capture_time_utc"),
              "source_capture_time_status": raw.get("capture_time_status", "not supplied in M463 registry"),
              "available_time_contract": raw.get("available_time_contract"),
              "source_clock_status": raw.get("source_clock_status", "M463 corrected clock; not independently proven first-publication time"),
              "raw_record_sha256": sha_bytes(canonical_json(raw))}
    result["input_sha256"] = sha_bytes(canonical_json(notice_payload(result)))
    result["version_sha256"] = result["input_sha256"]
    result["body_sha256"] = sha_bytes(body.encode("utf-8"))
    result["title_sha256"] = sha_bytes(title.encode("utf-8"))
    return result


def registry_digest(path: Path) -> str:
    if path not in REGISTRY_DIGESTS:
        REGISTRY_DIGESTS[path] = sha_file(path)
    return REGISTRY_DIGESTS[path]


def jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip(): yield line_number, json.loads(line)


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                               allow_nan=False) + "\n", encoding="utf-8")


def source_variant(row: dict) -> dict:
    return {key: row[key] for key in ("notice_id", "original_source_notice_id", "input_sha256", "version_sha256", "source_text_clock_sha256",
        "title_sha256", "body_sha256", "clocks", "source_kind", "source_registry_path",
        "source_registry_line", "source_registry_sha256", "source_file", "source_file_sha256",
        "source_url", "source_capture_time_utc", "source_capture_time_status", "raw_record_sha256")}


def eligible_human_ids() -> set[str]:
    # Explicit projection; comparison values and old label columns are not opened.
    import pandas as pd
    frame = pd.read_csv(HUMAN_IDS, usecols=["notice_id", "review_id"], dtype=str)
    ids = {canonical_id(value) for value in frame.notice_id}
    if len(ids) != 60 or frame.review_id.nunique() != 60:
        raise ValueError("fixed human-review exclusion is not60 unique notices/reviews")
    return ids


def allocate_cells(cells: dict) -> tuple[dict, str]:
    # Twenty distinct cells, exactly four per period and four per type.
    for omitted in itertools.permutations(range(5)):
        kept = {(p, t): 1 for p in range(5) for t in range(5) if t != omitted[p]}
        if all(cells[(PERIODS[p], TYPES[t])] for p, t in kept):
            return kept, "first_feasible_omitted_type_permutation:" + ",".join(map(str, omitted))
    # Frozen fallback permits multiple draws in a cell, while preserving both margins.
    source, sink = "source", "sink"
    residual, adjacent = {}, defaultdict(list)
    def edge(a, b, capacity):
        residual[(a, b)], residual[(b, a)] = capacity, 0
        adjacent[a].append(b); adjacent[b].append(a)
    for p in range(5): edge(source, ("p", p), 4)
    for p in range(5):
        for t in range(5): edge(("p", p), ("t", t), len(cells[(PERIODS[p], TYPES[t])]))
    for t in range(5): edge(("t", t), sink, 4)
    total = 0
    while total < 20:
        parent, queue = {source: None}, deque([source])
        while queue and sink not in parent:
            node = queue.popleft()
            for nxt in adjacent[node]:
                if nxt not in parent and residual[(node, nxt)] > 0:
                    parent[nxt] = node; queue.append(nxt)
        if sink not in parent: raise ValueError("balanced20-notice pilot quotas are infeasible")
        node, path = sink, []
        while parent[node] is not None:
            path.append((parent[node], node)); node = parent[node]
        increment = min(residual[e] for e in path)
        for a, b in path: residual[(a,b)] -= increment; residual[(b,a)] += increment
        total += increment
    return {(p,t): residual[(("t",t),("p",p))] for p in range(5) for t in range(5)
            if residual[(("t",t),("p",p))]}, "deterministic_capacity_maxflow"


def select_pilot(rows: list[dict], excluded: set[str]) -> tuple[list[str], dict]:
    cells = defaultdict(list)
    for row in rows:
        if row["period"] in PERIODS and row["notice_id"] not in excluded:
            rank = sha_bytes((PILOT_SEED + "\0" + row["notice_id"] + "\0" + row["version_sha256"]).encode("utf-8"))
            cells[(row["period"], row["pilot_type"])].append((rank, row["notice_id"]))
    for values in cells.values(): values.sort()
    allocation, method = allocate_cells(cells)
    selected, details = [], []
    for (p,t), n in sorted(allocation.items()):
        for rank, ident in cells[(PERIODS[p], TYPES[t])][:n]:
            selected.append(ident)
            details.append({"notice_id": ident, "period": PERIODS[p], "pilot_type": TYPES[t], "selection_hash": rank})
    if len(selected) != 20 or len(set(selected)) != 20 or set(selected) & excluded:
        raise AssertionError("pilot cardinality or exclusion failed")
    return selected, {"allocation_method": method, "selected": details,
                     "eligible_cell_counts": {p: {t: len(cells[(p,t)]) for t in TYPES} for p in PERIODS},
                     "selected_counts_by_period": dict(Counter(d["period"] for d in details)),
                     "selected_counts_by_type": dict(Counter(d["pilot_type"] for d in details))}


def build() -> dict:
    HERE.mkdir(parents=True, exist_ok=True)
    if (HERE / "CONTRACT_FREEZE.json").exists() or (HERE / "extraction_ledger.jsonl").exists():
        raise RuntimeError("source bank may not be rebuilt after contract freeze or extraction ledger creation; use --check")
    spec_path = HERE / "PREPARATION_SPEC.json"
    if spec_path.exists() and json.loads(spec_path.read_text()) != SPEC:
        raise RuntimeError("preparation specification changed; prepare in a new isolated directory")
    write_json(spec_path, SPEC)
    write_json(HERE / "PREPARATION_FREEZE.json", {"state": "FROZEN_BEFORE_SOURCE_SELECTION",
        "spec_sha256": sha_file(spec_path), "script_sha256": sha_file(Path(__file__))})
    selected, variants = {}, defaultdict(dict)
    with REGISTRY.open(encoding="utf-8", newline="") as handle:
        for line, raw in enumerate(csv.DictReader(handle), 2):
            if raw["is_relevant_operational"] != "True" or raw["available_time_valid"] != "True": continue
            row = make_row(raw, REGISTRY, line, "FINAL3")
            ident = row["notice_id"]
            if ident in selected: raise ValueError(f"duplicate FINAL3 source identifier: {ident}")
            selected[ident] = row
            variants[ident][(row["source_file"], row["input_sha256"])] = source_variant(row)
    final_ids = set(selected)
    if len(final_ids) != 17583: raise ValueError(f"FINAL3 source population drift: {len(final_ids)} !=17583")
    canonical_data, raw_ids = {}, set()
    canonical_path = DATA26 / "normalized_registry.jsonl"
    for line, raw in jsonl(canonical_path):
        if not "2026-03-01" <= raw["source_clock_aest"][:10] <= "2026-09-30": continue
        row = make_row(raw, canonical_path, line, "DATA26")
        ident = row["notice_id"]
        if ident in canonical_data: raise ValueError(f"duplicate DATA26 canonical identifier: {ident}")
        canonical_data[ident] = row
        variants[ident][(row["source_file"], row["input_sha256"])] = source_variant(row)
    raw_candidates = defaultdict(dict)
    for line, raw in jsonl(DATA26 / "normalized_notices.jsonl"):
        if not "2026-03-01" <= raw["source_clock_aest"][:10] <= "2026-09-30": continue
        row = make_row(raw, DATA26 / "normalized_notices.jsonl", line, "DATA26")
        ident = row["notice_id"]; raw_ids.add(ident)
        raw_candidates[ident][row["input_sha256"]] = row
        variants[ident][(row["source_file"], row["input_sha256"])] = source_variant(row)
    union_data = set(canonical_data) | raw_ids
    for ident in sorted(union_data, key=int):
        if ident in final_ids: continue
        if ident in canonical_data:
            selected[ident] = canonical_data[ident]
        else:
            candidates = raw_candidates[ident]
            if len(candidates) != 1: raise ValueError(f"no DATA26 canonical version for conflicting ID: {ident}")
            selected[ident] = next(iter(candidates.values()))
    rows = sorted(selected.values(), key=lambda r: int(r["notice_id"]))
    excluded = eligible_human_ids()
    if not excluded.issubset(final_ids): raise ValueError("human exclusion ID absent from FINAL3 source scope")
    pilot, pilot_audit = select_pilot(rows, excluded)
    conflicts = []
    for ident in sorted(variants, key=int):
        versions = list(variants[ident].values())
        unique = {v["input_sha256"] for v in versions}
        if len(unique) > 1:
            conflicts.append({"notice_id": ident, "selected_input_sha256": selected[ident]["input_sha256"],
                              "selected_source_kind": selected[ident]["source_kind"],
                              "rule": "retain FINAL3 M463 if present; else adopted DATA26 canonical registry",
                              "variant_input_sha256": sorted(unique),
                              "distinct_text_and_source_clock_versions": len({v["source_text_clock_sha256"] for v in versions})})
    with (HERE / "scope.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows: handle.write(canonical_json(row).decode("utf-8") + "\n")
    with (HERE / "SOURCE_VERSIONS.jsonl").open("w", encoding="utf-8") as handle:
        for ident in sorted(variants, key=int):
            handle.write(canonical_json({"notice_id": ident, "selected_input_sha256": selected[ident]["input_sha256"],
                                        "versions": sorted(variants[ident].values(), key=lambda v:(v["source_file"],v["input_sha256"]))}).decode("utf-8") + "\n")
    write_json(HERE / "pilot_ids.json", pilot)
    write_json(HERE / "PILOT_SELECTION.json", pilot_audit)
    write_json(HERE / "EXCLUDED_HUMAN60_IDS.json", sorted(excluded, key=int))
    write_json(HERE / "SOURCE_VERSION_CONFLICTS.json", conflicts)
    input_paths = (REGISTRY, canonical_path, DATA26 / "normalized_notices.jsonl", HUMAN_IDS, SOURCE_LOADER)
    produced = ("scope.jsonl", "pilot_ids.json", "SOURCE_VERSIONS.jsonl", "SOURCE_VERSION_CONFLICTS.json",
                "PILOT_SELECTION.json", "EXCLUDED_HUMAN60_IDS.json", "PREPARATION_SPEC.json", "PREPARATION_FREEZE.json")
    receipt = {"state": "SOURCE_SCOPE_AND_PILOT_PREPARED_NO_EXTRACTION", "model_calls": 0,
        "source_files": {str(path): {"sha256": sha_file(path), "bytes": path.stat().st_size} for path in input_paths},
        "files": {name: {"sha256": sha_file(HERE/name), "bytes": (HERE/name).stat().st_size} for name in produced},
        "request_payload_keys": ["notice_id", "title", "body", "clocks"],
        "input_hash_rule": "SHA256 UTF8 canonical JSON sorted keys, separators(',',':'), ensure_ascii=False, no truncation or text normalization",
        "final3_notice_count": len(final_ids), "data26_requested_union_count": len(union_data),
        "data26_registry_count": len(canonical_data), "data26_raw_union_count_after_numeric_id_canonicalization": len(raw_ids),
        "final3_data26_overlap_count": len(final_ids & union_data), "total_notice_count": len(rows),
        "expected_base_requests_full_including_reused_pilot": len(rows),
        "expected_remaining_base_requests_after_all20_valid_pilot": len(rows)-20,
        "counts_by_period": dict(Counter(r["period"] for r in rows)),
        "counts_by_scope_group": dict(Counter(r["scope_group"] for r in rows)),
        "counts_by_source_kind": dict(Counter(r["source_kind"] for r in rows)),
        "counts_by_source_month_aest": dict(sorted(Counter(r["source_day_aest"][:7] for r in rows).items())),
        "confirmation_and_leadin_20260727_20260930": sum(r["source_day_aest"]>="2026-07-27" for r in rows),
        "incomplete_20260301_20260726": sum("2026-03-01"<=r["source_day_aest"]<="2026-07-26" for r in rows),
        "calendar_20260301_20260731": sum("2026-03-01"<=r["source_day_aest"]<="2026-07-31" for r in rows),
        "final3_outside_user_historical_periods": sum(r["source_day_aest"]>="2026-03-01" for r in rows if r["notice_id"] in final_ids),
        "scope_discrepancy_note": "The inherited FINAL3 population is17583 but includes648 M463 notices datedMarch-May2026;16935 lie in stated2021-10..2024-07 and2025-11..2026-02 periods. Preserve all17583; separately report the648 overlap in incomplete extension.",
        "notice_ids_with_multiple_input_versions": len(conflicts),
        "notice_ids_with_multiple_text_or_source_clock_versions": sum(c["distinct_text_and_source_clock_versions"]>1 for c in conflicts),
        "data26_ids_with_multiple_text_or_source_clock_versions": sum(len({v["source_text_clock_sha256"] for v in vv.values() if v["source_kind"]=="DATA26"})>1 for vv in variants.values()),
        "source_versions_retained": sum(len(v) for v in variants.values()),
        "source_version_policy": SPEC["canonical_version"], "pilot_count": len(pilot),
        "pilot_counts_by_period": pilot_audit["selected_counts_by_period"],
        "pilot_counts_by_type": pilot_audit["selected_counts_by_type"],
        "excluded_human_review_notice_count": len(excluded),
        "full_text_body_chars_max": max(len(r["body"]) for r in rows),
        "full_text_title_chars_max": max(len(r["title"]) for r in rows),
        "full_text_title_plus_body_chars_max": max(len(r["title"])+len(r["body"]) for r in rows),
        "notices_body_over_7000_characters": sum(len(r["body"])>7000 for r in rows),
        "text_rule": "title and body exactly as selected source registry stores strings; source normalization inherited from DATA26 is disclosed but no NRX normalization applied",
        "clock_limitation": "M463 and DATA26 clocks are source/version contracts; ingestion time does not establish historical first publication. June DATA26 source coverage is absent; March-July26 coverage incomplete and not planned for scoring.",
        "outcome_rows_read": False, "m331_label_rows_read": 0,
        "traceability": "all counts above computed only from source-only scope.jsonl; pilot counts from PILOT_SELECTION.json; population admission from source loader code; source registry rows traced per notice"}
    write_json(HERE / "SCOPE_RECEIPT.json", receipt)
    return receipt


def load_scope(verify_sources: bool = True) -> list[dict]:
    receipt = json.loads((HERE / "SCOPE_RECEIPT.json").read_text(encoding="utf-8"))
    for name in ("scope.jsonl", "pilot_ids.json", "PILOT_SELECTION.json", "EXCLUDED_HUMAN60_IDS.json"):
        if sha_file(HERE/name) != receipt["files"][name]["sha256"]:
            raise RuntimeError(f"frozen preparation artifact digest mismatch: {name}")
    if verify_sources:
        for path, facts in receipt["source_files"].items():
            if sha_file(path) != facts["sha256"]: raise RuntimeError(f"source changed since preparation: {path}")
    rows = [row for _,row in jsonl(HERE / "scope.jsonl")]
    if len(rows) != receipt["total_notice_count"] or len({r["notice_key"] for r in rows}) != len(rows):
        raise RuntimeError("frozen source count/unique identifier mismatch")
    for row in rows:
        if sha_bytes(canonical_json(notice_payload(row))) != row["input_sha256"]:
            raise RuntimeError(f"source payload hash mismatch: {row['notice_key']}")
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify existing preparation receipts without changing files")
    args=parser.parse_args()
    if args.check:
        rows=load_scope(); print(json.dumps({"state":"PASS_SOURCE_SCOPE_INTEGRITY", "notices":len(rows)}))
    else:
        if (HERE/"SCOPE_RECEIPT.json").exists():
            raise SystemExit("Scope already frozen. Use --check; preparation does not overwrite an existing receipt.")
        receipt=build()
        print(json.dumps({key:receipt[key] for key in ("state","total_notice_count","final3_notice_count","data26_requested_union_count","final3_data26_overlap_count","counts_by_period","counts_by_scope_group","notice_ids_with_multiple_input_versions")},indent=2))


if __name__=="__main__": main()
