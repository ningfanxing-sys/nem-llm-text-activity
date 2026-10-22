'Grade the initial notice label sample with the frozen validator.'
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
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
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import archived module: {path}")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def all_hash_values(value: Any):
    if isinstance(value, dict):
        for child in value.values():
            yield from all_hash_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from all_hash_values(child)
    elif isinstance(value, str):
        yield value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def grade(archive: Path, spec_path: Path, spec_freeze_path: Path) -> dict:
    require(archive.resolve().is_relative_to(HERE), 'v1 archive must be within notice_extraction')
    for path in (spec_path, spec_freeze_path):
        require(path.resolve().is_relative_to(HERE), 'diagnostic analysis_specification must be within notice_extraction')
    diagnostic_spec_sha = sha_file(spec_path)
    require(diagnostic_spec_sha in set(all_hash_values(read_json(spec_freeze_path))),
            "diagnostic specification SHA-256 missing from freeze; analysis prohibited")

    freeze_path = archive / "CONTRACT_FREEZE.json"
    if not freeze_path.exists():
        freeze_path = HERE / "CONTRACT_FREEZE.json"
    freeze = read_json(freeze_path)
    freeze_hash = sha_file(freeze_path)
    require(freeze.get("contract_version") == 1, "archive is not the frozen v1 contract")
    frozen_files_verified = {}
    for name, expected in freeze["files_sha256"].items():
        path = archive / name
        if not path.exists():
            path = HERE / name
        require(sha_file(path) == expected, f"v1 frozen file mismatch: {name}")
        frozen_files_verified[name] = expected
    validator_path = archive / "validate_notice_label.py"
    if not validator_path.exists():
        validator_path = HERE / "validate_notice_label.py"
    validator = module(validator_path, "nrx_v1_frozen_validator")
    validator.SCHEMA_PATH = HERE / "schema_full.json"
    runner = module(archive / "run_notice_extraction.py", "nrx_v1_frozen_runner")


    runner.HERE = HERE
    pilot_ids_path = archive / "pilot_ids.json"
    if not pilot_ids_path.exists():
        pilot_ids_path = HERE / "pilot_ids.json"
    pilot_ids = read_json(pilot_ids_path)
    require(len(pilot_ids) == len(set(pilot_ids)) == 20, "v1 pilot must contain 20 unique IDs")
    known = {}
    with (HERE / "scope.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            source = json.loads(line)
            if source["notice_key"] in pilot_ids:
                require(source["notice_key"] not in known, "duplicate scoped pilot source")
                known[source["notice_key"]] = source
    require(set(known) == set(pilot_ids), "pilot ID absent from source pool")
    with (HERE / "extraction_ledger.jsonl").open(encoding="utf-8") as handle:
        ledger = [json.loads(line) for line in handle if line.strip()]
    subset = [record for record in ledger if record.get("phase") == "pilot"
              and record.get("contract_freeze_sha256") == freeze_hash]
    require(bool(subset), "no v1 pilot ledger records")
    ledger_digest = sha_bytes("".join(canonical(record) + "\n" for record in subset).encode())
    receipt = read_json(HERE / "PILOT_RECEIPT.json")
    require(receipt["pilot_ledger_sha256"] == ledger_digest, "v1 pilot ledger slice differs from receipt")
    expected_base = {
        "contract_sha256": freeze["contract_sha256"],
        "contract_freeze_sha256": freeze_hash,
        "scope_freeze_sha256": sha_file(HERE / "SCOPE_RECEIPT.json"),
        "model_requested": freeze["model_requested"],
        "model_reasoning_effort": freeze["model_reasoning_effort"],
    }
    for record in subset:
        require(all(record.get(key) == value for key, value in expected_base.items()),
                "v1 ledger base identity differs from freeze")
    starts = [record for record in subset if record.get("event") == "ATTEMPT_STARTED"]
    results = [record for record in subset if record.get("event") == "ATTEMPT_RESULT"]
    start_by_identity = {(record["notice_key"], record["attempt"]): record for record in starts}
    result_by_identity = {(record["notice_key"], record["attempt"]): record for record in results}
    require(len(start_by_identity) == len(starts), "duplicate dispatch reservation")
    require(len(result_by_identity) == len(results), "duplicate attempt result")
    require(set(start_by_identity) == set(result_by_identity), "unmatched reserved/completed attempt")
    request_indices = [record["request_index"] for record in starts]
    require(sorted(request_indices) == list(range(1, len(starts) + 1)), "request index sequence differs")
    template = (HERE / "prompt.txt").read_text(encoding="utf-8")
    require(template.count("{notice_json}") == 1, "prompt payload placeholder differs")
    rows, fresh_errors, failure_details, external_hashes = [], [], [], {}


    for source in known.values():
        for name in ("source_registry", "source_file"):
            source_path = Path(source[name + "_path"] if name == "source_registry" else source[name])
            expected = source[name + "_sha256"]
            if source_path not in external_hashes:
                external_hashes[source_path] = sha_file(source_path)
            require(external_hashes[source_path] == expected, f"source provenance file drift: {source_path}")
    for identity, record in sorted(result_by_identity.items()):
        key, attempt = identity
        started = start_by_identity[identity]
        source = known[key]
        require(record["notice_id"] == source["notice_id"] == key, "notice echo/source identity differs")
        for name in ("input_sha256", "prompt_sha256", "raw_path", "request_index", "notice_id", "notices_in_request", "source_provenance"):
            require(record[name] == started[name], f"start/result {name} differs: {identity}")
        require(record["notices_in_request"] == 1, "request contains more than one notice")
        payload = {name: source[name] for name in ("notice_id", "title", "body", "clocks")}
        input_hash = sha_bytes(canonical(payload).encode())
        require(input_hash == source["input_sha256"] == source["version_sha256"] == record["input_sha256"],
                "scoped payload/source-version digest differs")
        for name in ("title", "body"):
            require(sha_bytes(source[name].encode()) == source[name + "_sha256"], "source text hash differs")
        require(record["source_provenance"] == runner.source_lineage(source), "ledger lineage differs from scope")
        prompt = template.replace("{notice_json}", canonical(payload))
        require(sha_bytes(prompt.encode()) == record["prompt_sha256"], "full request digest differs")
        raw_path = (HERE / record["raw_path"]).resolve()
        require(raw_path.is_relative_to((HERE / "raw").resolve()), "raw path outside preserved raw directory")
        require(sha_file(raw_path) == record["raw_sha256"], "compressed raw receipt digest differs")
        with gzip.open(raw_path, "rt", encoding="utf-8") as handle:
            raw = json.load(handle)


        for name, value in record.items():
            if name not in {"raw_sha256", "started_utc"}:
                require(raw.get(name) == value, f"raw/ledger {name} differs: {identity}")
        require(raw["prompt"] == prompt and raw["input"] == payload, "raw request/source text differs")
        require(sha_bytes(raw["response"].encode()) == record["output_sha256"] == record["response_sha256"],
                "raw response digest differs")
        cmd = raw["cmd"]
        workdir_index = cmd.index("-C") + 1
        output_index = cmd.index("-o") + 1
        workdir, output = cmd[workdir_index], Path(cmd[output_index])
        require(Path(workdir).is_absolute() and output.parent == Path(workdir), "CLI temporary directory/output binding differs")
        require(cmd == runner.command(output, workdir), "CLI invocation differs from frozen transport")
        usage, model_ids, tools = runner.usage_and_tools(raw["stdout_jsonl"])
        require(usage == record["usage"] and model_ids == record["model_ids_exposed"], "usage/model receipt differs")
        require(tools == record["tool_events"] and len(tools) == record["tool_calls"], "tool event receipt differs")
        parsed = None
        errors = []
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
        require(parsed == raw["parsed_label"] == record["parsed_label"], "fresh JSON decode differs from saved label")
        require(errors == record["validation_errors"], "fresh v1 validation differs from saved errors")
        fresh_errors.extend(errors)
        capacity, transient = runner.transport_classification(raw)
        require(capacity == record["capacity_error"], "transport capacity classification differs")
        tused, vused = started["transport_retries_used"], started["validation_retries_used"]
        if raw["exit_code"] == 0 and raw["response"] and not errors:
            status = "SUCCESS"
        elif tools:
            status = "TERMINAL_FAILURE"
        elif transient and tused < 3:
            tused += 1
            status = "CAPACITY_RETRY" if capacity else "TRANSPORT_RETRY"
        elif raw["exit_code"] == 0 and raw["response"] and vused < 1:
            vused += 1
            status = "VALIDATION_RETRY"
        else:
            status = "TERMINAL_FAILURE"
        require((status, tused, vused) == (record["status"], record["transport_retries_used"], record["validation_retries_used"]),
                "retry/terminal disposition differs from frozen rules")
        delay = min(900, 30 * 2 ** max(0, tused - 1)) if status in {"CAPACITY_RETRY", "TRANSPORT_RETRY"} else 0
        require(record["retry_after_seconds"] == delay, "retry backoff differs from frozen rule")
        if attempt == 1:
            require(started["transport_retries_used"] == started["validation_retries_used"] == 0,
                    "initial attempt starts with consumed retry budget")
        else:
            previous = result_by_identity[(key, attempt - 1)]
            require(previous["status"].endswith("RETRY"), "retry dispatched after terminal status")
            require((started["transport_retries_used"], started["validation_retries_used"]) ==
                    (previous["transport_retries_used"], previous["validation_retries_used"]), "retry budget reset")
        rows.append({"notice_id": key, "attempt": attempt, "status": status,
                     "v1_valid": parsed is not None and not errors, "error_codes": [error["code"] for error in errors],
                     "raw_path": record["raw_path"], "raw_sha256": record["raw_sha256"],
                     "input_sha256": input_hash, "request_sha256": record["prompt_sha256"],
                     "response_sha256": record["response_sha256"], "tool_calls": len(tools)})
        for error in errors:
            if error["code"] == "VALUE_NOT_IN_EVIDENCE":
                pointer = error["path"].split("/")[1:]
                value_object: Any = parsed
                for item in pointer[:-1]:
                    value_object = value_object[int(item)] if isinstance(value_object, list) else value_object[item]
                value = value_object[pointer[-1]]
                spans = value_object["evidence_spans"]
                normalized = validator.normalize_verbatim(value)
                literal_source = [name for name in ("title", "body") if normalized in validator.normalize_verbatim(source[name])]
                failure_details.append({"notice_id": key, "attempt": attempt, "path": error["path"],
                                        "value": value, "evidence_spans": spans,
                                        "value_literal_in_normalized_source_parts": literal_source,
                                        "each_span_literal_in_normalized_source": all(validator._contains(span, validator._source_parts(source)) for span in spans),
                                        "value_in_single_evidence_span": any(normalized in validator.normalize_verbatim(span) for span in spans)})
    finals = runner.final_by_key(subset)
    valid_final = sum(finals.get(key, {}).get("status") == "SUCCESS" for key in pilot_ids)
    fabricated = [error for error in fresh_errors if error["code"] == "FABRICATED_SPAN"]
    structural = [error for error in fresh_errors if error["code"] in STRUCTURAL_CODES]
    contamination = [error for error in fresh_errors if any(token in error["code"] for token in ("OTHER_NOTICE", "OTHER_DATE", "CONTAMINATION", "UNSUPPORTED_DATE", "FOREIGN_"))]
    metrics = {
        "valid_after_at_most_one_validation_retry": valid_final >= 18,
        "all_20_terminal": len(finals) == 20 and set(finals) == set(pilot_ids),
        "zero_fabricated_spans_all_attempts": not fabricated,
        "all_window_quantity_bindings_valid_all_attempts": not structural,
        "no_other_notice_or_unsupported_date_all_attempts": not contamination,
        "one_notice_per_request": all(record["notices_in_request"] == 1 and record["notice_key"] in pilot_ids for record in starts),
        "zero_tool_calls_all_attempts": all(not record.get("tool_calls") for record in results),
        "retry_budgets_respected": all(record.get("transport_retries_used", 0) <= 3 and record.get("validation_retries_used", 0) <= 1 and record.get("attempt", 0) <= 5 for record in results),
    }
    require(metrics == receipt["machine_gate_criteria"], "independent criteria differ from frozen pilot receipt")
    require(valid_final == receipt["valid_final_outputs"], "valid final count differs from pilot receipt")
    terminal_counts = dict(Counter(record["status"] for record in finals.values()))
    require(terminal_counts == receipt["terminal_counts"], "terminal counts differ from pilot receipt")
    require(len(starts) == receipt["provider_requests_reserved"] and len(results) == receipt["completed_attempt_receipts"],
            "attempt receipt/reservation counts differ")
    require(all(metrics.values()) == receipt["machine_gate_would_pass"], "machine pass status differs")
    hashes = {**expected_base, "pilot_ids_sha256": sha_file(pilot_ids_path),
              "pilot_receipt_sha256": sha_file(HERE / "PILOT_RECEIPT.json"), "pilot_ledger_sha256": ledger_digest}
    require(hashes["pilot_ids_sha256"] == receipt["pilot_ids_sha256"], "pilot IDs digest differs")
    audit = {
        "state": 'AUDITED_V1_INACTIVE', "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "contract_version": 1, **hashes,
        "diagnostic_spec_sha256": diagnostic_spec_sha,
        "diagnostic_spec_freeze_sha256": sha_file(spec_freeze_path),
        "grader_sha256": sha_file(Path(__file__)),
        "v1_frozen_files_verified": frozen_files_verified,
        "source_provenance_files_verified_sha256": {str(key): value for key, value in external_hashes.items()},
        "machine_gate_criteria": metrics, "machine_gate_would_pass": all(metrics.values()),
        "terminal_counts": terminal_counts, "valid_final_outputs": valid_final,
        "provider_requests_reserved": len(starts), "completed_attempt_receipts": len(results),
        "attempt_validity_counts_v1": dict(Counter("VALID" if row["v1_valid"] else "INVALID" for row in rows)),
        "attempt_audits": rows, "mechanical_rejection_details": failure_details,
        "integrity_checks": {"frozen_v1_files": True, "source_input_request": True,
                             "raw_receipt_sha256": True, "decoded_response_equality": True,
                             "frozen_cli_command": True, "usage_tools": True,
                             "v1_schema_spans_bindings_ids_dates": True,
                             "retry_progression_and_terminal_disposition": True,
                             "receipt_reproduced_independently": True},
        "finding": "The frozen machine gate passes. Four attempts fail the same VALUE_NOT_IN_EVIDENCE check, and the adjacent-span examples reveal a systematic mechanical rejection mode motivating validator-only contract 1.1; extraction loss across the full pool must not be assumed random. Separately, 94968 attempt 1 has one evidence span that omits its value's trailing T-V-MNSP1, so that evidence gap remains a legitimate rejection under the specification.",
        "retained_evidence_gap": {
            "notice_id": "94968", "attempt": 1,
            "unsupported_by_supplied_spans_tail": "T-V-MNSP1",
            "reading_rule": "Source-literal value wording alone does not excuse an incomplete supporting source region. This observation comes from the preserved exact value/span pair, not a new model call.",
        },
        "semantic_spot_check": {"notice_ids": ["132882", "105821", "130778"],
                                "finding": "Faithful, conservative outputs.",
                                "attribution": "User-supplied grading finding; not independently adjudicated by this mechanical audit."},
        "semantic_limits": "Literal/structural checks do not certify semantic entailment, completeness or unique event attachment.",
        "model_calls_during_grading": 0,
    }
    audit_path = HERE / "PILOT_GRADE_V1_AUDIT.json"
    write_json(audit_path, audit)
    gate_path = HERE / "PILOT_GATE.json"
    archive_gate_path = HERE / "PILOT_GATE_V1_PENDING_REVIEW.json"
    if gate_path.exists():
        previous = gate_path.read_bytes()
        previous_gate = json.loads(previous)
        if previous_gate.get("state") == "PENDING_REVIEW":
            if archive_gate_path.exists():
                require(archive_gate_path.read_bytes() == previous, "pending v1 gate archive differs")
            else:
                archive_gate_path.write_bytes(previous)
        else:
            require(previous_gate.get("state") == 'INACTIVE_BY_CONTRACT_1_1', "refuse replacing an unrelated gate")
    gate = {**hashes, "phase": "pilot", "contract_version": 1,
            "state": 'INACTIVE_BY_CONTRACT_1_1', "status": 'INACTIVE_BY_CONTRACT_1_1',
            "graded_utc": audit["generated_utc"], "machine_gate_criteria": metrics,
            "machine_gate_would_pass": all(metrics.values()), "valid_final_outputs": valid_final,
            "terminal_counts": terminal_counts, "completed_attempt_receipts": len(results),
            "audited_pilot_ledger_sha256": ledger_digest,
            "audit_file": audit_path.name, "audit_sha256": sha_file(audit_path),
            "pending_gate_archive": archive_gate_path.name,
            "pending_gate_archive_sha256": sha_file(archive_gate_path),
            "full_run_authorized": False,
            "finding": audit["finding"], "affected_terminal_notice_ids": ["94968", "117252"],
            "affected_path": "/impact_windows/0/attributes/operational_indicators/value",
            "diagnostic_only": True,
            "follow_up_required": "Freeze contract 1.1, run the fresh disjoint host pilot, and grade its own attempts; no full run under v1."}
    write_json(gate_path, gate)
    return {"state": gate["state"], "machine_gate_would_pass": gate["machine_gate_would_pass"],
            "terminal_counts": terminal_counts, "attempt_validity_counts_v1": audit["attempt_validity_counts_v1"],
            "audit_path": str(audit_path), "gate_path": str(gate_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--spec-freeze", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(grade(args.archive.resolve(), args.spec.resolve(), args.spec_freeze.resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
