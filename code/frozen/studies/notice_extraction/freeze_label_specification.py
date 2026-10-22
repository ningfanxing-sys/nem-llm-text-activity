'Save the tested label extraction inputs before sampling.'
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

from prepare_notice_scope import sha_file

HERE = Path(__file__).resolve().parent
NEW_FILES = (
    'CONTRACT_SPECIFICATION_1_1.md', "NRX2_SPEC.json", "NRX2_SPEC_FREEZE.json",
    "V1_PRESERVATION_MANIFEST.json", 'verify_initial_label_preservation.py',
    'grade_initial_labels.py', "PILOT_GRADE_V1_AUDIT.json", "PILOT_GATE.json",
    "PILOT_GATE_V1_PENDING_REVIEW.json", 'revalidate_saved_labels.py',
    "V1_REVALIDATION_1_1.json", 'prepare_label_sample.py', "pilot_ids_1_1.json",
    "PILOT_SELECTION_1_1.json", "PILOT_PLAN_1_1.md", "FULL_PLAN_1_1.md",
    'validate_notice_fields.py', 'test_validate_notice_fields.py',
    "run_notice_extraction.py", "test_run_notice_extraction_1_1.py",
    'freeze_label_specification.py', "BUILD_CHECKS_1_1.json", "BUILD_TEST_1_1.log", "TEST_RESULTS_1_1.json",
    'REPORT.md',
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    from verify_initial_label_preservation import verify
    preservation = verify()
    from prepare_label_sample import selected
    ids, selection = selected()
    if json.loads((HERE / "pilot_ids_1_1.json").read_text()) != ids or json.loads((HERE / "PILOT_SELECTION_1_1.json").read_text()) != selection:
        raise RuntimeError("fresh pilot selection does not reproduce")
    from revalidate_saved_labels import diagnostic
    saved_diagnostic = json.loads((HERE / "V1_REVALIDATION_1_1.json").read_text())
    saved_diagnostic.pop("generated_utc", None)
    if saved_diagnostic != diagnostic():
        raise RuntimeError("offline diagnostic does not reproduce")
    from run_notice_extraction import CLI, verify_freeze
    freeze_path = HERE / "CONTRACT_FREEZE_1_1.json"
    if args.check:
        freeze = verify_freeze()
        print(json.dumps({"state": 'PASS_FROZEN_label_specification_BUILD_INTEGRITY', "contract_version": "1.1",
                          "notices": freeze["expected_unique_notices"], "pilot_notices": len(ids),
                          "v1_original_files_verified": preservation["original_files_verified"],
                          "contract_sha256": freeze["contract_sha256"],
                          "contract_freeze_sha256": freeze["contract_freeze_sha256"], "model_calls": 0}))
        return
    if freeze_path.exists():
        raise RuntimeError("v1.1 already frozen; use --check, never overwrite")
    if (HERE / "results_1_1").exists():
        raise RuntimeError("v1.1 runtime already exists; cannot freeze as a fresh pre-pilot build")
    checks = json.loads((HERE / "BUILD_CHECKS_1_1.json").read_text())
    if checks.get("state") != "PASS_BUILD_ONLY_NO_EXTRACTION" or checks.get("model_calls") != 0:
        raise RuntimeError("passing v1.1 build-only checks required")
    for name, expected in checks["tested_files_sha256"].items():
        if sha_file(HERE / name) != expected:
            raise RuntimeError(f"tested file changed: {name}")
    old = json.loads((HERE / "CONTRACT_FREEZE.json").read_text())
    if sha_file(CLI) != old["cli_sha256"]:
        raise RuntimeError("CLI binary changed since v1; transport cannot silently drift")
    gate = json.loads((HERE / "PILOT_GATE.json").read_text())
    if gate.get("state") != 'INACTIVE_BY_CONTRACT_1_1' or gate.get("full_run_authorized") is not False:
        raise RuntimeError('v1 gate has not been inactive')
    files = set(NEW_FILES) | set(preservation["original_locations_or_archives"].values())
    freeze = {"state": "FROZEN_BEFORE_HOST_PILOT", "contract_version": "1.1",
              "frozen_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "base_contract_sha256": sha_file(HERE / "CONTRACT.md"),
              "contract_sha256": sha_file(HERE / 'CONTRACT_SPECIFICATION_1_1.md'),
              "base_contract_freeze_sha256": sha_file(HERE / "CONTRACT_FREEZE.json"),
              "scope_freeze_sha256": sha_file(HERE / "SCOPE_RECEIPT.json"),
              "spec_freeze_sha256": sha_file(HERE / "NRX2_SPEC_FREEZE.json"),
              "files_sha256": {name: sha_file(HERE / name) for name in sorted(files)},
              "model_requested": old["model_requested"], "model_reasoning_effort": old["model_reasoning_effort"],
              "cli_path": str(CLI), "cli_version": old["cli_version"], "cli_sha256": sha_file(CLI),
              "expected_unique_notices": old["expected_unique_notices"], "pilot_notices": len(ids),
              "pilot_salt": 'notice_extraction-PILOT-v1.1', "runtime_directory": "results_1_1",
              "transport_retries_total_per_notice": old["transport_retries_total_per_notice"],
              "validation_retries_total_per_notice": old["validation_retries_total_per_notice"],
              "maximum_requests_per_notice": old["maximum_requests_per_notice"],
              "full_worker_policy": old["full_worker_policy"], "model_calls_during_build": 0,
              "pilot_gate_state": "NOT_RUN_REQUIRES_SEPARATE_GRADING",
              "pilot_gate_path": "results_1_1/PILOT_GATE_1_1.json", "v1_results_reusable": False}
    with freeze_path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(freeze, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

    verified = verify_freeze()
    print(json.dumps({"state": verified["state"], "contract_version": "1.1",
                      "pilot_notices": len(ids), "contract_freeze_sha256": verified["contract_freeze_sha256"],
                      "model_calls": 0}))


if __name__ == "__main__":
    main()
