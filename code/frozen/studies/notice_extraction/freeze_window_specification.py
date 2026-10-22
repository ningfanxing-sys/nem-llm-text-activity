'Save the window prompt and validation source hashes.'
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

from prepare_notice_scope import sha_file

HERE = Path(__file__).resolve().parent
NEW_FILES = (
    'CONTRACT_SPECIFICATION_1_2.md', "NRX3_SPEC.json", "NRX3_SPEC_FREEZE.json",
    'label_specification_PRESERVATION_MANIFEST.json', 'verify_label_preservation.py',
    'grade_label_sample.py', "PILOT_GRADE_1_1_AUDIT.json", "results_1_1/PILOT_GATE_1_1.json",
    "prompt.txt", 'window_prompt.py', "test_prompt_assembly_1_2.py",
    'prepare_window_sample.py', "pilot_ids_1_2.json", "PILOT_SELECTION_1_2.json",
    "PILOT_PLAN_1_2.md", "FULL_PLAN_1_2.md", 'test_prepare_window_sample.py',
    "run_notice_extraction.py", "test_run_notice_extraction_1_2.py", 'test_window_schema.py',
    'freeze_window_specification.py', "BUILD_CHECKS_1_2.json", "BUILD_TEST_1_2.log",
    "TEST_RESULTS_1_2.json", 'REPORT.md',
)


def check_inputs() -> tuple[dict, list[str], dict]:
    from verify_label_preservation import verify
    from window_prompt import verify_prompt
    from prepare_window_sample import selected
    preservation = verify(HERE)
    verify_prompt(HERE)
    ids, selection = selected()
    if json.loads((HERE / "pilot_ids_1_2.json").read_text()) != ids or json.loads(
            (HERE / "PILOT_SELECTION_1_2.json").read_text()) != selection:
        raise RuntimeError("fresh1.2 pilot selection does not reproduce")
    old_plan = (HERE / "PILOT_PLAN_1_1.md").read_text()
    new_plan = (HERE / "PILOT_PLAN_1_2.md").read_text()
    def gate_section(text):
        return text.split("## Unchanged gate criteria\n", 1)[1].split("## Receipts, separate grading and reuse", 1)[0]
    if gate_section(old_plan) != gate_section(new_plan):
        raise RuntimeError("frozen1.1 gate criteria must remain byte-identical")
    gate = json.loads((HERE / "results_1_1/PILOT_GATE_1_1.json").read_text())
    if (gate.get("state"), gate.get("status"), gate.get('inactive_by_contract_version'),
        gate.get("full_run_authorized"), gate.get("failing_criteria")) != ("FAIL", "FAIL", "1.2", False, [2, 3]):
        raise RuntimeError('1.1FAIL grade/exclusion required; no1.1 full run')
    if gate.get("audit_sha256") != sha_file(HERE / "PILOT_GRADE_1_1_AUDIT.json"):
        raise RuntimeError("1.1 grading audit hash differs from gate")
    if gate.get("pilot_receipt_sha256") != sha_file(HERE / "results_1_1/PILOT_RECEIPT_1_1.json"):
        raise RuntimeError("1.1 graded receipt changed")
    return preservation, ids, gate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    preservation, ids, _ = check_inputs()
    from run_notice_extraction import CLI, verify_freeze
    freeze_path = HERE / "CONTRACT_FREEZE_1_2.json"
    if args.check:
        freeze = verify_freeze()
        print(json.dumps({"state": 'PASS_FROZEN_window_specification_BUILD_INTEGRITY', "contract_version": "1.2",
                          "notices": freeze["expected_unique_notices"], "pilot_notices": len(ids),
                          "pre_nrx3_original_files_verified": preservation["original_files_verified"],
                          "contract_sha256": freeze["contract_sha256"],
                          "contract_freeze_sha256": freeze["contract_freeze_sha256"], "model_calls": 0}))
        return
    if freeze_path.exists():
        raise RuntimeError("1.2 already frozen; use --check, never overwrite")
    if (HERE / "results_1_2").exists():
        raise RuntimeError("1.2 runtime exists; cannot freeze a fresh pre-pilot build")
    checks = json.loads((HERE / "BUILD_CHECKS_1_2.json").read_text())
    tests = json.loads((HERE / "TEST_RESULTS_1_2.json").read_text())
    if checks.get("state") != "PASS_BUILD_ONLY_NO_EXTRACTION" or checks.get("model_calls") != 0 or tests.get("state") != "PASS":
        raise RuntimeError("passing whole-suite build-only checks required")
    for name, expected in checks["tested_files_sha256"].items():
        if sha_file(HERE / name) != expected:
            raise RuntimeError(f"tested file changed: {name}")
    prior = json.loads((HERE / "CONTRACT_FREEZE_1_1.json").read_text())
    if sha_file(CLI) != prior["cli_sha256"]:
        raise RuntimeError("CLI binary drift from1.1; prompt-only contract cannot drift transport")
    names = set(NEW_FILES) | set(preservation["original_locations_or_archives"].values())
    freeze = {
        "state": "FROZEN_BEFORE_HOST_PILOT", "contract_version": "1.2",
        "frozen_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "base_contract_sha256": sha_file(HERE / "CONTRACT.md"),
        "prior_contract_sha256": sha_file(HERE / 'CONTRACT_SPECIFICATION_1_1.md'),
        "contract_sha256": sha_file(HERE / 'CONTRACT_SPECIFICATION_1_2.md'),
        "base_contract_freeze_sha256": sha_file(HERE / "CONTRACT_FREEZE.json"),
        "prior_contract_freeze_sha256": sha_file(HERE / "CONTRACT_FREEZE_1_1.json"),
        "scope_freeze_sha256": sha_file(HERE / "SCOPE_RECEIPT.json"),
        "spec_freeze_sha256": sha_file(HERE / "NRX3_SPEC_FREEZE.json"),
        "files_sha256": {name: sha_file(HERE / name) for name in sorted(names)},
        "model_requested": prior["model_requested"], "model_reasoning_effort": prior["model_reasoning_effort"],
        "cli_path": str(CLI), "cli_version": prior["cli_version"], "cli_sha256": sha_file(CLI),
        "expected_unique_notices": prior["expected_unique_notices"], "pilot_notices": len(ids),
        "pilot_salt": 'notice_extraction-PILOT-v1.2', "runtime_directory": "results_1_2",
        "transport_retries_total_per_notice": prior["transport_retries_total_per_notice"],
        "validation_retries_total_per_notice": prior["validation_retries_total_per_notice"],
        "maximum_requests_per_notice": prior["maximum_requests_per_notice"],
        "full_worker_policy": prior["full_worker_policy"], "model_calls_during_build": 0,
        "pilot_gate_state": "NOT_RUN_REQUIRES_SEPARATE_GRADING",
        "pilot_gate_path": "results_1_2/PILOT_GATE_1_2.json",
        "v1_results_reusable": False, 'label_specification_results_reusable': False,
        "unchanged_validator_version": "1.1", 'prompt_only_specification': True,
    }
    with freeze_path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(freeze, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    verified = verify_freeze()
    print(json.dumps({"state": verified["state"], "contract_version": "1.2", "pilot_notices": len(ids),
                      "contract_freeze_sha256": verified["contract_freeze_sha256"], "model_calls": 0}))


if __name__ == "__main__":
    main()
