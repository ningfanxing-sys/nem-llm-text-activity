'Grade the notice label sample against the specified schema.'
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from typing import Any

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / 'archive_label_specification'
RUNTIME = HERE / "results_1_1"
STRUCTURAL_CODES = {
    "SCHEMA", "EMPTY_WINDOW_ID", "DUPLICATE_WINDOW_ID", "WINDOW_ID_SEQUENCE",
    "BOUNDED_ENDPOINT_MISSING", "OPEN_INTERVAL_HAS_END", "ATTRIBUTE_REGION_CONFLICT",
    "BINDING_REASON_MISMATCH", "BAD_WINDOW_REFERENCE", "BOUND_ASSET_CONFLICT",
    "UNBOUND_HAS_WINDOW",
}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot import {path}")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def verify_spec() -> dict:
    freeze = read_json(HERE / "NRX3_SPEC_FREEZE.json")
    require(freeze.get("files_sha256", {}).get("NRX3_SPEC.json") == sha_file(HERE / "NRX3_SPEC.json"),
            "NRX3 specification is missing from its freeze or changed")
    for name, expected in freeze["files_sha256"].items():
        path = (HERE / name).resolve()
        require(path.is_relative_to(HERE.resolve()), 'specification file outside notice_extraction')

        if name == "results_1_1/PILOT_GATE_1_1.json":
            path = ARCHIVE / name
        require(sha_file(path) == expected, f"NRX3 specified input differs: {name}")
    return read_json(HERE / "NRX3_SPEC.json")


def pointer_value(label: Any, pointer: str) -> tuple[Any, Any]:
    parts = pointer.split("/")[1:]
    parent = label
    for part in parts[:-1]:
        parent = parent[int(part)] if isinstance(parent, list) else parent[part.replace("~1", "/").replace("~0", "~")]
    last = parts[-1].replace("~1", "/").replace("~0", "~")
    value = parent[int(last)] if isinstance(parent, list) else parent[last]
    return parent, value


def grade() -> tuple[dict, dict]:
    spec = verify_spec()
    require(spec.get("model_calls_authorized_in_this_task") == 0, 'NRX3 no-call input_checks differs')
    freeze_path = HERE / "CONTRACT_FREEZE_1_1.json"
    freeze = read_json(freeze_path)
    freeze_hash = sha_file(freeze_path)
    require(freeze.get("contract_version") == "1.1", "pilot freeze is not contract 1.1")
    frozen_files_verified = {}
    for name, expected in freeze["files_sha256"].items():
        path = ARCHIVE / name
        if not path.exists():
            path = HERE / name
        require(sha_file(path) == expected, f"preserved v1.1 frozen file differs: {name}")
        frozen_files_verified[name] = expected
    validator = module(HERE / 'validate_notice_fields.py', 'nrx3_frozen_label_schema_validator')
    validator.SCHEMA_PATH = HERE / "schema_full.json"
    runner = module(ARCHIVE / "run_notice_extraction.py", 'nrx3_frozen_label_schema_runner')
    runner.HERE = HERE
    pilot_path = HERE / "pilot_ids_1_1.json"
    pilot_ids = read_json(pilot_path)
    require(len(pilot_ids) == len(set(pilot_ids)) == 20, "v1.1 pilot must have 20 distinct IDs")


    known = {}
    key_pattern = re.compile(r'"notice_key"\s*:\s*"([^"]+)"')
    with (HERE / "scope.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            match = key_pattern.search(line)
            require(match is not None, "source row lacks a notice key")
            key = match.group(1)
            if key in pilot_ids:
                source = json.loads(line)
                require(key not in known, "duplicate scoped pilot source")
                known[key] = source
    require(set(known) == set(pilot_ids), "v1.1 pilot absent from unchanged scope")
    ledger_path = RUNTIME / "extraction_ledger.jsonl"
    with ledger_path.open(encoding="utf-8") as handle:
        ledger = [json.loads(line) for line in handle if line.strip()]
    require(all(row.get("phase") == "pilot" for row in ledger), "v1.1 full execution already occurred")
    runner.current_records(ledger, {**freeze, "contract_freeze_sha256": freeze_hash})
    subset = ledger
    ledger_digest = runner.pilot_ledger_digest(subset)
    receipt_path = RUNTIME / "PILOT_RECEIPT_1_1.json"
    receipt = read_json(receipt_path)
    archived_gate_path = ARCHIVE / "results_1_1/PILOT_GATE_1_1.json"
    archived_gate = read_json(archived_gate_path)
    require(archived_gate.get("state") == "PENDING_REVIEW", "original v1.1 pending gate not preserved")
    expected_base = {
        "contract_version": "1.1", "contract_sha256": freeze["contract_sha256"],
        "contract_freeze_sha256": freeze_hash,
        "scope_freeze_sha256": sha_file(HERE / "SCOPE_RECEIPT.json"),
        "model_requested": freeze["model_requested"],
        "model_reasoning_effort": freeze["model_reasoning_effort"],
    }
    for row in subset:
        require(all(row.get(key) == value for key, value in expected_base.items()),
                "v1.1 ledger identity/model differs from freeze")
    starts = [row for row in subset if row.get("event") == "ATTEMPT_STARTED"]
    results = [row for row in subset if row.get("event") == "ATTEMPT_RESULT"]
    start_by_identity = {(row["notice_key"], row["attempt"]): row for row in starts}
    result_by_identity = {(row["notice_key"], row["attempt"]): row for row in results}
    require(len(start_by_identity) == len(starts) and len(result_by_identity) == len(results),
            "duplicate attempt reservation/result")
    require(set(start_by_identity) == set(result_by_identity), "unmatched attempt reservation/result")
    require(sorted(row["request_index"] for row in starts) == list(range(1, len(starts) + 1)),
            "request sequence differs")
    template = (ARCHIVE / "prompt.txt").read_text(encoding="utf-8")
    require(template.count("{notice_json}") == 1, "frozen v1.1 prompt placeholder differs")
    external_hashes = {}
    for source in known.values():
        for kind in ("source_registry", "source_file"):
            path = Path(source["source_registry_path"] if kind == "source_registry" else source[kind])
            if path not in external_hashes:
                external_hashes[path] = sha_file(path)
            require(external_hashes[path] == source[kind + "_sha256"], f"source provenance changed: {path}")
    rows, fresh_errors, error_details, value_details = [], [], [], []
    for identity, record in sorted(result_by_identity.items()):
        key, attempt = identity
        require(key in known, "nonpilot attempt in v1.1 pilot ledger")
        source, started = known[key], start_by_identity[identity]
        require(record["notice_id"] == source["notice_id"] == key, "notice echo/source identity differs")
        for name in ("input_sha256", "prompt_sha256", "raw_path", "request_index", "notice_id", "notices_in_request", "source_provenance"):
            require(record[name] == started[name], f"start/result {name} differs: {identity}")
        require(record["notices_in_request"] == 1, "request is not one notice")
        payload = runner.request_payload(source)
        input_hash = sha_bytes(canonical(payload).encode())
        require(input_hash == source["input_sha256"] == source["version_sha256"] == record["input_sha256"],
                "input/source-version hash differs")
        for name in ("title", "body"):
            require(sha_bytes(source[name].encode()) == source[name + "_sha256"], "source text hash differs")
        require(record["source_provenance"] == runner.source_lineage(source), "source lineage differs")
        prompt = template.replace("{notice_json}", canonical(payload))
        require(sha_bytes(prompt.encode()) == record["prompt_sha256"], "complete v1.1 request digest differs")
        raw_path = runner.raw_receipt_path(record["raw_path"])
        require(sha_file(raw_path) == record["raw_sha256"], "compressed raw digest differs")
        with gzip.open(raw_path, "rt", encoding="utf-8") as handle:
            raw = json.load(handle)
        for name, value in record.items():
            if name not in {"raw_sha256", "started_utc"}:
                require(raw.get(name) == value, f"raw/ledger {name} differs: {identity}")
        require(raw["prompt"] == prompt and raw["input"] == payload, "exact raw request differs")
        require(sha_bytes(raw["response"].encode()) == record["output_sha256"] == record["response_sha256"],
                "response hash differs")
        cmd = raw["cmd"]
        workdir, output = cmd[cmd.index("-C") + 1], Path(cmd[cmd.index("-o") + 1])
        require(Path(workdir).is_absolute() and output.parent == Path(workdir), "CLI workdir/output binding differs")
        require(cmd == runner.command(output, workdir), "CLI invocation differs from frozen transport")
        usage, model_ids, tools = runner.usage_and_tools(raw["stdout_jsonl"])
        require((usage, model_ids, tools, len(tools)) ==
                (record["usage"], record["model_ids_exposed"], record["tool_events"], record["tool_calls"]),
                "usage/model/tool event receipt differs")
        parsed, errors = None, []
        if raw["response"]:
            try:
                parsed = validator.parse_label_json(raw["response"])
                errors = validator.validate_label(parsed, source)
            except (ValueError, TypeError) as exc:
                errors = [{"code": "JSON", "path": "$", "message": f"{type(exc).__name__}: {exc}"}]
                errors.extend(validator.check_contamination(raw["response"], source))
        else:
            errors = [{"code": "TRANSPORT", "path": "$", "message": f"CLI exit {raw['exit_code']}; no output"}]
        if tools:
            errors.append({"code": "TOOL_USE", "path": "$", "message": "CLI emitted tool invocation event; source isolation breached"})
        if raw["exit_code"] != 0:
            errors.append({"code": "TRANSPORT", "path": "$", "message": f"CLI exit {raw['exit_code']}"})
        require(parsed == raw["parsed_label"] == record["parsed_label"], "independent JSON decode differs")
        require(errors == record["validation_errors"], "unchanged v1.1 validation no longer reproduces")
        capacity, transient = runner.transport_classification(raw)
        require(capacity == record["capacity_error"], "capacity classification differs")
        tused, vused = started["transport_retries_used"], started["validation_retries_used"]
        if raw["exit_code"] == 0 and raw["response"] and not errors:
            status = "SUCCESS"
        elif tools:
            status = "TERMINAL_FAILURE"
        elif transient and tused < runner.MAX_TRANSPORT_RETRIES:
            tused += 1
            status = "CAPACITY_RETRY" if capacity else "TRANSPORT_RETRY"
        elif raw["exit_code"] == 0 and raw["response"] and vused < runner.MAX_VALIDATION_RETRIES:
            vused += 1
            status = "VALIDATION_RETRY"
        else:
            status = "TERMINAL_FAILURE"
        require((status, tused, vused) == (record["status"], record["transport_retries_used"], record["validation_retries_used"]),
                "retry/status disposition differs")
        delay = min(900, 30 * 2 ** max(0, tused - 1)) if status in {"CAPACITY_RETRY", "TRANSPORT_RETRY"} else 0
        require(record["retry_after_seconds"] == delay, "frozen backoff differs")
        if attempt == 1:
            require(started["transport_retries_used"] == started["validation_retries_used"] == 0, "initial retry budget differs")
        else:
            require((key, attempt - 1) in result_by_identity, "attempt sequence has gap")
            previous = result_by_identity[(key, attempt - 1)]
            require(previous["status"].endswith("RETRY"), "dispatch after terminal state")
            require((started["transport_retries_used"], started["validation_retries_used"]) ==
                    (previous["transport_retries_used"], previous["validation_retries_used"]), "retry budget reset")
        fresh_errors.extend(errors)
        rows.append({"notice_id": key, "attempt": attempt, "status": status,
                     'label_specification_valid': parsed is not None and not errors, "validation_errors": errors,
                     "raw_path": record["raw_path"], "raw_sha256": record["raw_sha256"],
                     "input_sha256": input_hash, "request_sha256": record["prompt_sha256"],
                     "response_sha256": record["response_sha256"], "tool_calls": len(tools)})
        for error in errors:
            detail = {"notice_id": key, "attempt": attempt, **error,
                      "raw_path": record["raw_path"], "raw_sha256": record["raw_sha256"],
                      "response_sha256": record["response_sha256"]}
            if parsed is not None:
                parent, value = pointer_value(parsed, error["path"])
                detail["returned_value"] = value
                if isinstance(parent, dict):
                    if "evidence_spans" in parent:
                        detail["evidence_spans"] = parent["evidence_spans"]
                    if "binding_status" in parent:
                        detail["binding_status"] = parent["binding_status"]
                        detail["binding_reason"] = parent["binding_reason"]
                if error["code"] == "FABRICATED_SPAN":
                    detail["source_title"] = source["title"]
                    detail["supporting_body_phrase"] = "Direction is cancelled" if "Direction is cancelled" in source["body"] else None
                if error["code"] == "VALUE_NOT_IN_EVIDENCE":
                    normalized = validator.normalize_verbatim(value)
                    detail["value_literal_in_normalized_source_parts"] = [name for name in ("title", "body")
                        if normalized in validator.normalize_verbatim(source[name])]
                    detail["each_span_literal_in_normalized_source"] = all(
                        validator._contains(span, validator._source_parts(source)) for span in parent["evidence_spans"])
                    value_details.append(detail)
            error_details.append(detail)
    finals = runner.final_by_key(subset)
    valid_final = sum(finals.get(key, {}).get("status") == "SUCCESS" for key in pilot_ids)
    fabricated = [error for error in fresh_errors if error["code"] == "FABRICATED_SPAN"]
    structural = [error for error in fresh_errors if error["code"] in STRUCTURAL_CODES]
    contamination = [error for error in fresh_errors if any(token in error["code"] for token in
                     ("OTHER_NOTICE", "OTHER_DATE", "CONTAMINATION", "UNSUPPORTED_DATE", "FOREIGN_"))]
    metrics = {
        "valid_after_at_most_one_validation_retry": valid_final >= 18,
        "all_20_terminal": len(finals) == 20 and set(finals) == set(pilot_ids),
        "zero_fabricated_spans_all_attempts": not fabricated,
        "all_window_quantity_bindings_valid_all_attempts": not structural,
        "no_other_notice_or_unsupported_date_all_attempts": not contamination,
        "one_notice_per_request": all(row["notices_in_request"] == 1 and row["notice_key"] in pilot_ids for row in starts),
        "zero_tool_calls_all_attempts": all(not row.get("tool_calls") for row in results),
        "retry_budgets_respected": all(row.get("transport_retries_used", 0) <= 3 and
            row.get("validation_retries_used", 0) <= 1 and row.get("attempt", 0) <= 5 for row in results),
    }
    terminal_counts = dict(Counter(row["status"] for row in finals.values()))
    require(metrics == receipt["machine_gate_criteria"], "independent criteria differ from receipt")
    require(valid_final == receipt["valid_final_outputs"] and terminal_counts == receipt["terminal_counts"],
            "independent final counts differ from receipt")
    require(len(starts) == receipt["provider_requests_reserved"] and len(results) == receipt["completed_attempt_receipts"],
            "dispatch/receipt counts differ")
    require(all(metrics.values()) == receipt["machine_gate_would_pass"], "machine gate outcome differs")
    require(fabricated == receipt["fabricated_span_errors"] and structural == receipt["window_binding_errors"] and
            contamination == receipt["contamination_errors"], "receipt error arrays differ")
    hashes = {**expected_base, "pilot_ids_sha256": sha_file(pilot_path),
              "pilot_receipt_sha256": sha_file(receipt_path), "pilot_ledger_sha256": ledger_digest}
    require(all(receipt.get(key) == value for key, value in hashes.items() if key != "pilot_receipt_sha256"),
            "receipt pilot contract/source hashes differ")
    require(all(archived_gate.get(key) == value for key, value in hashes.items()), "preserved pending gate hashes differ")
    failing_numbers = sorted(({2} if fabricated or value_details else set()) | ({3} if structural else set()))
    criterion_detail = [
        {"criterion": 1, "pass": metrics["all_20_terminal"] and metrics["valid_after_at_most_one_validation_retry"],
         "terminal_notices": len(finals), "valid_final_outputs": valid_final},
        {"criterion": 2, "pass": not fabricated and not value_details,
         "fabricated_span_errors": len(fabricated), "value_not_in_evidence_errors": len(value_details)},
        {"criterion": 3, "pass": not structural, "structural_errors": len(structural)},
        {"criterion": 4, "pass": not contamination, "contamination_errors": len(contamination)},
        {"criterion": 5, "pass": metrics["one_notice_per_request"] and metrics["zero_tool_calls_all_attempts"] and metrics["retry_budgets_respected"],
         "source_request_hashes_reproduced": True, "tool_calls": sum(row["tool_calls"] for row in rows)},
    ]
    require(failing_numbers == [2, 3] and not all(metrics.values()), "v1.1 observed failure differs from NRX3 task")
    audit = {
        "state": 'AUDITED_label_specification_FAIL', **hashes,
        "diagnostic_spec_sha256": sha_file(HERE / "NRX3_SPEC.json"),
        "diagnostic_spec_freeze_sha256": sha_file(HERE / "NRX3_SPEC_FREEZE.json"),
        "grader_sha256": sha_file(Path(__file__)), 'label_specification_frozen_files_verified': frozen_files_verified,
        "source_provenance_files_verified_sha256": {str(path): value for path, value in external_hashes.items()},
        "ledger_file_sha256": sha_file(ledger_path), "machine_gate_criteria": metrics,
        "machine_gate_would_pass": False, "failing_criteria": failing_numbers, "gate_criterion_details": criterion_detail,
        "terminal_counts": terminal_counts, "valid_final_outputs": valid_final,
        "provider_requests_reserved": len(starts), "completed_attempt_receipts": len(results),
        'attempt_validity_counts_label_specification': dict(Counter("VALID" if row['label_specification_valid'] else "INVALID" for row in rows)),
        "error_code_counts": dict(Counter(error["code"] for error in fresh_errors)),
        "value_not_in_evidence_attempts": len({(row["notice_id"], row["attempt"]) for row in value_details}),
        "value_not_in_evidence_notices": len({row["notice_id"] for row in value_details}),
        "attempt_audits": rows, "failure_details": error_details,
        "mechanical_rejection_details": value_details,
        "integrity_checks": {'preserved_frozen_label_specification_files': True, "source_input_request": True,
            "raw_receipt_sha256": True, "decoded_response_equality": True,
            "frozen_cli_command": True, "usage_tools": True,
            'unchanged_label_specification_schema_spans_bindings_ids_dates': True,
            "retry_progression_and_terminal_disposition": True, "receipt_reproduced_independently": True},
        "finding": "FAIL: final validity meets 18/20, but criteria 2 and 3 fail on intermediate attempts. "
            "145251 attempt 1 joins title and body into a fabricated span; 132521 attempt 1 assigns w1 to "
            "three UNKNOWN_RELATION quantities. Repeated VALUE_NOT_IN_EVIDENCE rejections are source-copy "
            "compliance errors, including paraphrases and a start endpoint carrying the end endpoint's date. "
            'The frozen validator and gate remain unchanged; contract 1.1 is inactive by prompt-only 1.2.',
        "semantic_limits": "Literal/structural checks do not certify semantic entailment, completeness or unique event attachment.",
        "model_calls_during_grading": 0,
    }
    gate = {**hashes, "phase": "pilot", "state": "FAIL", "status": "FAIL",
        'inactive_by_contract_version': "1.2", "full_run_authorized": False,
        "machine_gate_criteria": metrics, "machine_gate_would_pass": False,
        "failing_criteria": failing_numbers, "failing_machine_gate_criteria": [key for key, value in metrics.items() if not value],
        "gate_criterion_details": criterion_detail, "valid_final_outputs": valid_final,
        "terminal_counts": terminal_counts, "completed_attempt_receipts": len(results),
        "audited_pilot_ledger_sha256": ledger_digest, "audit_file": "PILOT_GRADE_1_1_AUDIT.json",
        "pending_gate_archive": 'archive_label_specification/results_1_1/PILOT_GATE_1_1.json',
        "pending_gate_archive_sha256": sha_file(archived_gate_path),
        "failure_evidence": [row for row in error_details if row["code"] == "FABRICATED_SPAN" or row["code"] in STRUCTURAL_CODES],
        "finding": audit["finding"], "model_calls_during_grading": 0,
        "follow_up_required": "Run the separately frozen fresh contract 1.2 host pilot and grade every attempt; no full run under 1.1.",
    }
    return audit, gate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    audit, gate = grade()
    audit_path, gate_path = HERE / "PILOT_GRADE_1_1_AUDIT.json", RUNTIME / "PILOT_GATE_1_1.json"
    if args.check:
        saved_audit = read_json(audit_path)
        generated_utc = saved_audit.pop("generated_utc")
        require(saved_audit == audit, "saved v1.1 grading audit does not reproduce")
        saved_gate = read_json(gate_path)
        require(saved_gate.pop("graded_utc") == generated_utc, "gate/audit grading times differ")
        require(saved_gate.pop("audit_sha256") == sha_file(audit_path), "gate audit digest differs")
        require(saved_gate == gate, "saved v1.1 FAIL gate does not reproduce")
    else:
        require(not audit_path.exists(), "v1.1 audit already exists; use --check")
        require(gate_path.read_bytes() == (ARCHIVE / "results_1_1/PILOT_GATE_1_1.json").read_bytes(),
                "current pending gate differs from preserved original")
        generated_utc = dt.datetime.now(dt.timezone.utc).isoformat()
        audit["generated_utc"] = generated_utc
        with audit_path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(audit, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        gate["graded_utc"], gate["audit_sha256"] = generated_utc, sha_file(audit_path)
        gate_path.write_text(json.dumps(gate, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": "PASS_REPRODUCED_FAIL_GRADE" if args.check else "FAIL",
        "failing_criteria": gate["failing_criteria"], "valid_final_outputs": gate["valid_final_outputs"],
        "attempts": audit["completed_attempt_receipts"], 'attempt_validity_counts_label_specification': audit['attempt_validity_counts_label_specification'],
        "error_code_counts": audit["error_code_counts"], "audit_path": str(audit_path), "gate_path": str(gate_path)}))


if __name__ == "__main__":
    main()
