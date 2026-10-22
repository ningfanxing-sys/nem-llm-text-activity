"""Offline diagnostic of all saved v1 attempts under v1.1; no gate credit."""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path

from prepare_pilot_1_1 import verify_spec
from validate_notice_label import validate_label as validate_v1
from validate_notice_label_1_1 import parse_label_json, validate_label as validate_v11

HERE = Path(__file__).resolve().parent


def sha_file(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def diagnostic() -> dict:
    verify_spec()
    records = [json.loads(line) for line in (HERE / "extraction_ledger.jsonl").read_text().splitlines()]
    attempts = [row for row in records if row.get("phase") == "pilot" and row.get("event") == "ATTEMPT_RESULT"]
    if len(attempts) != 22:
        raise RuntimeError("v1 attempt population differs from frozen diagnostic definition")
    results = []
    for row in attempts:
        raw_path = (HERE / row["raw_path"]).resolve()
        if not raw_path.is_relative_to((HERE / "raw").resolve()) or sha_file(raw_path) != row["raw_sha256"]:
            raise RuntimeError("v1 raw receipt changed")
        with gzip.open(raw_path, "rt", encoding="utf-8") as handle:
            raw = json.load(handle)
        if hashlib.sha256(raw["response"].encode()).hexdigest() != row["response_sha256"]:
            raise RuntimeError("v1 response hash changed")
        label = parse_label_json(raw["response"])
        if label != row["parsed_label"] or raw["parsed_label"] != label:
            raise RuntimeError("v1 decoded response changed")
        errors_v1 = validate_v1(label, raw["input"])
        if errors_v1 != row["validation_errors"]:
            raise RuntimeError("v1 errors no longer reproduce")
        errors_v11 = validate_v11(label, raw["input"])
        results.append({"notice_id": row["notice_id"], "attempt": row["attempt"],
                        "v1_status": row["status"], "v1_errors": errors_v1,
                        "v1_1_valid": not errors_v11, "v1_1_errors": errors_v11,
                        "raw_path": row["raw_path"], "raw_sha256": row["raw_sha256"],
                        "response_sha256": row["response_sha256"], "input_sha256": row["input_sha256"]})
    final = {}
    for row in sorted(results, key=lambda r: r["attempt"]):
        final[row["notice_id"]] = row
    return {"state": "DIAGNOSTIC_ONLY_NO_FRESH_GATE_CREDIT", "contract_version": "1.1",
            "model_calls": 0, "fresh_gate_attempts_credited": 0, "full_run_outputs_reusable": 0,
            "source_v1_receipt_sha256": sha_file(HERE / "PILOT_RECEIPT.json"),
            "source_v1_ledger_sha256": sha_file(HERE / "extraction_ledger.jsonl"),
            "spec_freeze_sha256": sha_file(HERE / "NRX2_SPEC_FREEZE.json"),
            "amendment_sha256": sha_file(HERE / "CONTRACT_AMENDMENT_1_1.md"),
            "validator_v1_sha256": sha_file(HERE / "validate_notice_label.py"),
            "validator_v1_1_sha256": sha_file(HERE / "validate_notice_label_1_1.py"),
            "script_sha256": sha_file(Path(__file__)),
            "counts": {"attempts": len(results), "notices": len(final),
                       "v1_valid_attempts": sum(not r["v1_errors"] for r in results),
                       "v1_invalid_attempts": sum(bool(r["v1_errors"]) for r in results),
                       "v1_1_valid_attempts": sum(r["v1_1_valid"] for r in results),
                       "v1_1_invalid_attempts": sum(not r["v1_1_valid"] for r in results),
                       "v1_1_notices_with_valid_final_diagnostic": sum(r["v1_1_valid"] for r in final.values()),
                       "newly_valid_attempts": sum(bool(r["v1_errors"]) and r["v1_1_valid"] for r in results)},
            "v1_error_code_counts": dict(Counter(e["code"] for r in results for e in r["v1_errors"])),
            "v1_1_error_code_counts": dict(Counter(e["code"] for r in results for e in r["v1_1_errors"])),
            "attempts": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = HERE / "V1_REVALIDATION_1_1.json"
    result = diagnostic()
    if args.check:
        saved = json.loads(path.read_text())
        saved.pop("generated_utc", None)
        if saved != result:
            raise RuntimeError("saved v1.1 diagnostic does not reproduce")
    else:
        result["generated_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"state": result["state"], "counts": result["counts"]}))


if __name__ == "__main__":
    main()
