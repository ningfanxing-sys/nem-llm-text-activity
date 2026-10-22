'Save the quantity schema and validation source hashes.'
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

from prepare_notice_scope import sha_file

HERE = Path(__file__).resolve().parent
NEW_FILES = (
    'CONTRACT_SPECIFICATION_1_3.md', "NRX4_SPEC.json", "NRX4_SPEC_FREEZE.json",
    'window_specification_PRESERVATION_MANIFEST.json', 'verify_window_preservation.py',
    'grade_window_sample.py', "PILOT_GRADE_1_2_AUDIT.json", "results_1_2/PILOT_GATE_1_2.json",
    'prepare_quantity_sample.py', "pilot_ids_1_3.json", "PILOT_SELECTION_1_3.json",
    "PILOT_PLAN_1_3.md", "FULL_PLAN_1_3.md", 'test_prepare_quantity_sample.py',
    "run_notice_extraction.py", "test_run_notice_extraction_1_3.py", 'test_quantity_schema.py',
    'freeze_quantity_specification.py', "BUILD_CHECKS_1_3.json", "BUILD_TEST_1_3.log",
    "TEST_RESULTS_1_3.json", 'REPORT.md', "CONTRACT_FREEZE_1_2.json",
)
UNCHANGED_FILES = (
    "prompt.txt", "schema_full.json", "schema_response_format.json",
    "validate_notice_label.py", 'validate_notice_fields.py',
    "prepare_notice_scope.py", "scope.jsonl", "SCOPE_RECEIPT.json",
)
UNCHANGED_SETTINGS = (
    "model_requested", "model_reasoning_effort", "transport_retries_total_per_notice",
    "validation_retries_total_per_notice", "maximum_requests_per_notice", "cli_path",
    "cli_sha256", "cli_version", "full_worker_policy", "expected_unique_notices", "pilot_notices",
)


def check_inputs() -> tuple[dict, list[str], dict]:
    from verify_window_preservation import verify
    from window_prompt import verify_prompt
    from prepare_quantity_sample import selected
    preservation = verify(HERE)
    verify_prompt(HERE)
    prior = json.loads((HERE / "CONTRACT_FREEZE_1_2.json").read_text())
    if prior.get("contract_version") != "1.2":
        raise RuntimeError('gate-only specification baseline must be contract1.2')
    for name in UNCHANGED_FILES:
        if sha_file(HERE / name) != prior["files_sha256"][name]:
            raise RuntimeError(f"gate-only specification changed extraction/source asset: {name}")
    if sha_file(HERE / 'archive_window_specification/run_notice_extraction.py') != prior["files_sha256"]["run_notice_extraction.py"]:
        raise RuntimeError("archived1.2 runner differs from its frozen build")
    ids, selection = selected()
    if json.loads((HERE / "pilot_ids_1_3.json").read_text()) != ids or json.loads(
            (HERE / "PILOT_SELECTION_1_3.json").read_text()) != selection:
        raise RuntimeError("fresh1.3 pilot selection does not reproduce")
    if selection["excluded_earlier_pilot_count"] != 60 or selection["excluded_human_review_count"] != 60 or selection["excluded_distinct_total"] != 120:
        raise RuntimeError("fresh1.3 exclusions changed")
    gate = json.loads((HERE / "results_1_2/PILOT_GATE_1_2.json").read_text())
    if (gate.get("state"), gate.get("status"), gate.get('inactive_by_contract_version'),
        gate.get("full_run_authorized"), gate.get("failing_criteria")) != ("FAIL", "FAIL", "1.3", False, [2, 3]):
        raise RuntimeError('frozen1.2FAIL grade/exclusion required; no1.2 full run')
    if gate.get("contract_version") != "1.2" or gate.get("contract_sha256") != prior["contract_sha256"]:
        raise RuntimeError("1.2 grade does not match its unchanged contract")
    if gate.get("contract_freeze_sha256") != sha_file(HERE / "CONTRACT_FREEZE_1_2.json"):
        raise RuntimeError("1.2 graded contract freeze changed")
    if gate.get("audit_sha256") != sha_file(HERE / "PILOT_GRADE_1_2_AUDIT.json"):
        raise RuntimeError("1.2 grading audit hash differs from gate")
    if gate.get("pilot_receipt_sha256") != sha_file(HERE / "results_1_2/PILOT_RECEIPT_1_2.json"):
        raise RuntimeError("1.2 graded receipt changed")
    return preservation, ids, gate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    preservation, ids, _ = check_inputs()
    from run_notice_extraction import CLI, verify_freeze
    freeze_path = HERE / "CONTRACT_FREEZE_1_3.json"
    if args.check:
        freeze = verify_freeze()
        print(json.dumps({"state": 'PASS_FROZEN_quantity_specification_BUILD_INTEGRITY', "contract_version": "1.3",
                          "notices": freeze["expected_unique_notices"], "pilot_notices": len(ids),
                          "pre_nrx4_original_files_verified": preservation["original_files_verified"],
                          "contract_sha256": freeze["contract_sha256"],
                          "contract_freeze_sha256": freeze["contract_freeze_sha256"], "model_calls": 0}))
        return
    if freeze_path.exists():
        raise RuntimeError("1.3 already frozen; use --check, never overwrite")
    if (HERE / "results_1_3").exists():
        raise RuntimeError("1.3 runtime exists; cannot freeze a fresh pre-pilot build")
    checks = json.loads((HERE / "BUILD_CHECKS_1_3.json").read_text())
    tests = json.loads((HERE / "TEST_RESULTS_1_3.json").read_text())
    if (checks.get("state") != "PASS_BUILD_ONLY_NO_EXTRACTION" or checks.get("model_calls") != 0 or
            tests.get("state") != "PASS" or tests.get("model_calls") != 0):
        raise RuntimeError("passing whole-suite build-only checks required")
    for name, expected in checks["tested_files_sha256"].items():
        if sha_file(HERE / name) != expected:
            raise RuntimeError(f"tested file changed: {name}")
    prior = json.loads((HERE / "CONTRACT_FREEZE_1_2.json").read_text())
    if sha_file(CLI) != prior["cli_sha256"]:
        raise RuntimeError("CLI binary drift from1.2; gate-only contract cannot drift transport")
    names = set(NEW_FILES) | set(preservation["original_locations_or_archives"].values())
    freeze = {
        "state": "FROZEN_BEFORE_HOST_PILOT", "contract_version": "1.3",
        "frozen_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "base_contract_sha256": sha_file(HERE / "CONTRACT.md"),
        "prior_contract_sha256": sha_file(HERE / 'CONTRACT_SPECIFICATION_1_2.md'),
        "contract_sha256": sha_file(HERE / 'CONTRACT_SPECIFICATION_1_3.md'),
        "base_contract_freeze_sha256": sha_file(HERE / "CONTRACT_FREEZE.json"),
        "prior_contract_freeze_sha256": sha_file(HERE / "CONTRACT_FREEZE_1_2.json"),
        "scope_freeze_sha256": sha_file(HERE / "SCOPE_RECEIPT.json"),
        "spec_freeze_sha256": sha_file(HERE / "NRX4_SPEC_FREEZE.json"),
        "files_sha256": {name: sha_file(HERE / name) for name in sorted(names)},
        **{key: prior[key] for key in UNCHANGED_SETTINGS},
        "cli_path": str(CLI), "cli_sha256": sha_file(CLI),
        "pilot_notices": len(ids), "pilot_salt": 'notice_extraction-PILOT-v1.3',
        "runtime_directory": "results_1_3", "model_calls_during_build": 0,
        "pilot_gate_state": "NOT_RUN_AUTOMATIC_GRADING",
        "pilot_gate_path": "results_1_3/PILOT_GATE_1_3.json",
        "pilot_audit_path": "results_1_3/PILOT_AUDIT_1_3.json",
        "pilot_audit_readable_path": "results_1_3/PILOT_AUDIT_1_3.md",
        "v1_results_reusable": False, 'label_specification_results_reusable': False, 'window_specification_results_reusable': False,
        "unchanged_validator_version": "1.1", 'gate_definition_only_specification': True,
        "prompt_byte_identical_to_contract_version": "1.2",
        "pilot_gate_scope": {"fabricated_evidence_spans": "accepted_final_outputs",
                             "window_quantity_structure": "accepted_final_outputs",
                             "contamination": "all_attempts",
                             "rejected_attempt_error_census": "reported_not_gating"},
        "minimum_valid_final_outputs": 18,
        "pilot_gate_computed_automatically": True,
    }
    with freeze_path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(freeze, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    verified = verify_freeze()
    print(json.dumps({"state": verified["state"], "contract_version": "1.3", "pilot_notices": len(ids),
                      "contract_freeze_sha256": verified["contract_freeze_sha256"], "model_calls": 0}))


if __name__ == "__main__":
    main()
