'Extract one article per request using the frozen schema.'
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any

import pandas as pd

from prepare_articles import HERE, article_text, load_posts, sha_bytes, sha_file
from validate_label import quote_grounding_flags, validate

MODEL = "gpt-6-luna"
CONTRACT_VERSION = 4
REASONING_EFFORT = "medium"
CLI = Path("openai-cli")
LEDGER = HERE / "extraction_ledger.jsonl"
RAW = HERE / "raw"
LABELS = HERE / "labels.parquet"
FREEZE = HERE / "LABEL_FREEZE.json"
PILOT_IDS = HERE / "pilot_ids_v4.json"
LOCK = threading.Lock()
TRANSIENT_WORDS = ("capacity", "rate limit", "too many requests", "overloaded", "server busy", "temporarily unavailable", "connection reset", "connection refused", "timeout", "timed out", "429", "503", "502", "504")
CAPACITY_WORDS = ("capacity", "rate limit", "too many requests", "overloaded", "server busy", "429")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def atomic_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def append_ledger(record: dict[str, Any]) -> None:
    with LOCK:
        with LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush(); os.fsync(fh.fileno())


def records() -> list[dict[str, Any]]:
    if not LEDGER.exists():
        return []
    return [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify_freeze() -> dict[str, Any]:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if freeze["model_requested"] != MODEL:
        raise RuntimeError("model differs from freeze")
    if freeze.get("contract_version") != CONTRACT_VERSION:
        raise RuntimeError("contract version differs from freeze")
    if freeze.get("model_reasoning_effort") != REASONING_EFFORT:
        raise RuntimeError("reasoning effort differs from freeze")
    for name, expected in freeze["files_sha256"].items():
        if sha_file(HERE / name) != expected:
            raise RuntimeError(f"label freeze mismatch: {name}")
    if sha_file(HERE / "SCOPE_FREEZE_v2.json") != freeze["scope_freeze_sha256"]:
        raise RuntimeError("scope freeze differs")
    if sha_file(HERE / "freeze_v3/LABEL_FREEZE.json") != freeze["previous_freeze_sha256"]:
        raise RuntimeError("previous label freeze differs")
    return freeze


def usage_from_stdout(stdout: str) -> tuple[dict[str, int], list[str]]:
    usage: dict[str, int] = {}
    model_ids: set[str] = set()
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        for key in ("model", "model_id", "model_name", "snapshot"):
            if isinstance(event.get(key), str):
                model_ids.add(event[key])
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            for key, value in event["usage"].items():
                if isinstance(value, int):
                    usage[key] = usage.get(key, 0) + value
    return usage, sorted(model_ids)


def save_raw(article_id: str, attempt: int, payload: dict[str, Any]) -> Path:
    dest = RAW / article_id / f"attempt_{attempt:02d}.json.gz"
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_name(dest.name + ".tmp")
    with gzip.open(temp, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, sort_keys=True)
    os.replace(temp, dest)
    return dest


def call_one(article_id: str, meta: dict[str, str], post: dict, phase: str, prior_attempts: int) -> None:
    source = article_text(post)
    if sha_bytes(source.encode()) != meta["article_text_sha256"]:
        raise RuntimeError(f"source text drift: {article_id}")
    template = (HERE / "prompt.txt").read_text(encoding="utf-8")
    prompt = template.format(article_id=article_id, publication_utc=meta["publication_utc"], modified_utc=meta["modified_utc"], article_text=source)
    delay_index = 0
    for call_index in range(1, 9):
        attempt = prior_attempts + call_index
        started = utc_now()
        start = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="newsx_luna_") as tmp:
            output = Path(tmp) / "response.json"
            cmd = [str(CLI), "exec", "--ephemeral", "--ignore-rules", "--ignore-user-config", "--skip-git-repo-check", "--sandbox", "read-only", "-C", tmp, "-m", MODEL, "-c", f'model_reasoning_effort="{REASONING_EFFORT}"', "--disable", "memories", "--disable", "apps", "--disable", "plugins", "--disable", "browser_use", "--disable", "computer_use", "--disable", "in_app_browser", "--disable", "skill_search", "--output-schema", str(HERE / "schema.json"), "--json", "-o", str(output), "-"]
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
                try:
                    stdout, stderr = proc.communicate(input=prompt, timeout=900)
                    exit_code = proc.returncode
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    stdout, stderr = proc.communicate()
                    stderr += '\nnews_extraction bounded transport timeout after 900 seconds'
                    exit_code = 124
            except OSError as exc:
                stdout, stderr, exit_code = "", f"{type(exc).__name__}: {exc}", 127
            response = output.read_text(encoding="utf-8") if output.exists() else ""
        ended = utc_now()
        seconds = time.perf_counter() - start
        usage, exposed_model_ids = usage_from_stdout(stdout)
        errors: list[str] = []
        label: dict[str, Any] | None = None
        if exit_code == 0 and response:
            try:
                decoded = json.loads(response)
                errors = validate(decoded, article_id, source)
                if not errors:
                    label = decoded
            except (ValueError, TypeError) as exc:
                errors = [f"invalid JSON: {type(exc).__name__}: {exc}"]
        else:
            errors = [f"CLI exit {exit_code}; output present={bool(response)}"]
        diagnostic = (stderr + "\n" + stdout[-4000:]).lower()
        capacity = any(word in diagnostic for word in CAPACITY_WORDS)
        transient = capacity or exit_code == 124 or any(word in diagnostic for word in TRANSIENT_WORDS)
        if label is not None:
            status = "SUCCESS"
        elif transient and call_index < 8:
            status = "CAPACITY_RETRY" if capacity else "TRANSIENT_RETRY"
        else:
            status = "TERMINAL_FAILURE"
        raw_path = save_raw(article_id, attempt, {
            "article_id": article_id, "phase": phase, "attempt": attempt,
            "contract_version": CONTRACT_VERSION, "model_reasoning_effort": REASONING_EFFORT,
            "label_freeze_sha256": sha_file(FREEZE),
            "cmd": cmd,
            "prompt": prompt, "stdout_jsonl": stdout, "stderr": stderr,
            "last_response": response, "exit_code": exit_code,
            "started_utc": started, "ended_utc": ended,
        })
        record: dict[str, Any] = {
            "article_id": article_id, "phase": phase, "attempt": attempt, "status": status,
            "contract_version": CONTRACT_VERSION, "model_reasoning_effort": REASONING_EFFORT,
            "label_freeze_sha256": sha_file(FREEZE),
            "articles_in_request": 1,
            "started_utc": started, "ended_utc": ended, "wall_seconds": round(seconds, 3),
            "model_requested": MODEL, "model_ids_exposed": exposed_model_ids,
            "exit_code": exit_code, "usage": usage, "source_text_sha256": meta["article_text_sha256"],
            "prompt_sha256": sha_bytes(prompt.encode()), "response_sha256": sha_bytes(response.encode()),
            "raw_path": str(raw_path.relative_to(HERE)), "validation_errors": errors,
        }
        if label is not None:
            record["label"] = label
        if status.endswith("RETRY"):
            delay = min(900, 30 * (2 ** delay_index))
            delay_index += 1
            record["retry_after_seconds"] = delay
            record["retry_reason"] = "capacity" if capacity else "transient transport"
        append_ledger(record)
        if status == "SUCCESS" or status == "TERMINAL_FAILURE":
            return
        time.sleep(delay)


def final_by_id(all_records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for item in all_records:
        if item["status"] in {"SUCCESS", "TERMINAL_FAILURE"}:
            latest[item["article_id"]] = item
    return latest


def contract_records(all_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in all_records if r.get("contract_version") == CONTRACT_VERSION]


def pilot_gate(pilot_ids: list[str], all_records: list[dict[str, Any]]) -> dict[str, Any]:
    subset = [r for r in contract_records(all_records) if r["phase"] == "pilot"]
    by_id = final_by_id(subset)
    successful = sum(by_id.get(ident, {}).get("status") == "SUCCESS" for ident in pilot_ids)
    one_article_per_request = all(r["article_id"] in pilot_ids and r.get("articles_in_request") == 1 for r in subset)
    no_unsupported_evidence = all(not any("evidence" in e for e in r.get("validation_errors", [])) for r in subset)
    result = {
        "state": "PASS" if successful >= 19 and one_article_per_request and no_unsupported_evidence and len(by_id) == 20 else "FAIL",
        "contract_version": CONTRACT_VERSION,
        "label_freeze_sha256": sha_file(FREEZE),
        "pilot_ids_sha256": sha_file(PILOT_IDS),
        "pilot_articles": 20, "schema_valid_final_outputs": successful,
        "all_evidence_quotes_verbatim": no_unsupported_evidence,
        "one_article_per_request": one_article_per_request,
        "distinct_terminal_article_results": len(by_id),
        "pilot_requests_including_retries": len(subset),
        "reading_rule": ">=19/20 final schema-valid; every quote exact; one article/request",
    }
    atomic_json(HERE / "PILOT_GATE.json", result)
    return result


def finalize(manifest: list[dict[str, str]], freeze: dict[str, Any]) -> dict[str, Any]:
    all_records = contract_records(records())
    by_id = final_by_id(all_records)
    rows = []
    for meta in manifest:
        rec = by_id.get(meta["article_id"])
        if not rec or rec["status"] != "SUCCESS":
            continue
        label = rec["label"]
        quote_flags = [quote_grounding_flags(statement) for statement in label["statements"]]
        rows.append({**meta, "impact_level": label["impact_level"], "impact_evidence_quote": label["impact_evidence_quote"],
                     "attributes_json": json.dumps(label["attributes"], ensure_ascii=False, sort_keys=True),
                     "statements_json": json.dumps(label["statements"], ensure_ascii=False, sort_keys=True),
                     "time_in_quote": [time for time, _ in quote_flags],
                     "magnitude_in_quote": [magnitude for _, magnitude in quote_flags],
                     "statement_count": len(label["statements"]), "model_requested": MODEL,
                     "successful_attempt": rec["attempt"], "response_sha256": rec["response_sha256"]})
    temp = LABELS.with_suffix(".parquet.tmp")
    pd.DataFrame(rows).to_parquet(temp, index=False, compression="zstd")
    os.replace(temp, LABELS)
    usage: dict[str, int] = {}
    for r in all_records:
        for k, v in r.get("usage", {}).items():
            usage[k] = usage.get(k, 0) + v
    failed = [m["article_id"] for m in manifest if by_id.get(m["article_id"], {}).get("status") != "SUCCESS"]
    starts = [r["started_utc"] for r in all_records]
    ends = [r["ended_utc"] for r in all_records]
    receipt = {
        "contract_version": CONTRACT_VERSION,
        "state": "COMPLETE" if not failed else "PARTIAL",
        "expected_unique_articles": len(manifest), "successful": len(rows), "failures": len(failed),
        "failed_article_ids": failed, "attempts": len(all_records),
        "capacity_incidents": sum(r["status"] == "CAPACITY_RETRY" for r in all_records),
        "transient_retries": sum(r["status"] == "TRANSIENT_RETRY" for r in all_records),
        "model_requested": MODEL, "model_reasoning_effort": REASONING_EFFORT,
        "cli_version": freeze["cli_version"],
        "cli_version_provenance": freeze["cli_version_provenance"],
        "exposed_model_ids": sorted({v for r in all_records for v in r.get("model_ids_exposed", [])}),
        "temperature": "not exposed/settable in the client help", "knowledge_cutoff": "not exposed",
        "usage_tokens_total_where_available": usage,
        "first_call_utc": min(starts) if starts else None, "last_call_utc": max(ends) if ends else None,
        "sealed_utc": utc_now(), "scope_freeze_sha256": freeze["scope_freeze_sha256"],
        "label_freeze_sha256": sha_file(FREEZE), "manifest_sha256": sha_file(HERE / "article_manifest.csv"),
        "ledger_sha256": sha_file(LEDGER) if LEDGER.exists() else None,
        "labels_sha256": sha_file(LABELS), "pilot_gate": json.loads((HERE / "PILOT_GATE.json").read_text()) if (HERE / "PILOT_GATE.json").exists() else None,
        "price_models_fitted": 0, "old_label_banks_read": False,
    }
    atomic_json(HERE / "EXTRACTION_RECEIPT.json", receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("pilot", "full", "finalize"), required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        raise ValueError("workers must be between 1 and 8 (4.2: the author set no two-worker limit)")
    freeze = verify_freeze()
    manifest = list(csv.DictReader((HERE / "article_manifest.csv").open(newline="", encoding="utf-8")))
    posts, membership, digests = load_posts()
    if digests != freeze["source_sha256"]:
        raise RuntimeError("source hash drift")
    if {r["article_id"] for r in manifest} != set(posts):
        raise RuntimeError("manifest/source ID mismatch")
    pilot_ids = json.loads(PILOT_IDS.read_text())
    prior_records = records()
    current_records = contract_records(prior_records)
    if args.phase == "pilot" and any(r["phase"] == "full" for r in current_records):
        raise RuntimeError("pilot phase cannot run after full phase")
    if args.phase == "full":
        gate = json.loads((HERE / "PILOT_GATE.json").read_text())
        if (gate.get("contract_version") != CONTRACT_VERSION or
                gate.get("label_freeze_sha256") not in (sha_file(FREEZE), freeze.get("v4_freeze_sha256")) or
                gate.get("pilot_ids_sha256") != sha_file(PILOT_IDS) or
                gate["state"] != "PASS"):
            raise RuntimeError("pilot gate failed; full extraction prohibited")
    if args.phase == "finalize":
        print(json.dumps(finalize(manifest, freeze), ensure_ascii=False))
        return
    selected = pilot_ids if args.phase == "pilot" else [r["article_id"] for r in manifest]
    latest = final_by_id(current_records)
    pending = [ident for ident in selected if latest.get(ident, {}).get("status") != "SUCCESS"]
    meta_by_id = {r["article_id"]: r for r in manifest}
    prior = {}
    for r in prior_records:
        prior[r["article_id"]] = max(prior.get(r["article_id"], 0), r["attempt"])
    print(json.dumps({"phase": args.phase, "selected": len(selected), "pending": len(pending), "workers": args.workers}), flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(call_one, ident, meta_by_id[ident], posts[ident], args.phase, prior.get(ident, 0)) for ident in pending]
        for n, future in enumerate(as_completed(futures), 1):
            future.result()
            if n % 25 == 0 or n == len(futures):
                print(json.dumps({"phase": args.phase, "finished": n, "pending": len(futures), "utc": utc_now()}), flush=True)
    if args.phase == "pilot":
        print(json.dumps(pilot_gate(pilot_ids, records()), ensure_ascii=False), flush=True)
    else:
        rec = finalize(manifest, freeze)
        print(json.dumps({k: rec[k] for k in ("state", "expected_unique_articles", "successful", "failures", "attempts", "capacity_incidents")}), flush=True)


if __name__ == "__main__":
    main()
