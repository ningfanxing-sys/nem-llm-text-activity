'Extract notice labels and grade the saved sample automatically.'
from __future__ import annotations

import argparse
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
import datetime as dt
import fcntl
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any

HERE = Path(__file__).resolve().parent
CONTRACT_VERSION = "1.3"
RUNTIME_DIRECTORY = "results_1_3"
PILOT_RECEIPT_NAME = "PILOT_RECEIPT_1_3.json"
PILOT_GATE_NAME = "PILOT_GATE_1_3.json"


def runtime_path(name: str) -> Path:

    return HERE / RUNTIME_DIRECTORY / name


def raw_receipt_path(relative: str) -> Path:
    path = (HERE / relative).resolve()
    if not path.is_relative_to(runtime_path("raw").resolve()):
        raise RuntimeError("raw receipt is outside contract v1.3 runtime; v1.0/v1.1/v1.2 reuse prohibited")
    return path

MODEL = "gpt-6-luna"
REASONING_EFFORT = "medium"
CLI = Path("openai-cli")
DISABLED_FEATURES = ("memories", "apps", "plugins", "browser_use", "computer_use", "in_app_browser", "skill_search")
MAX_TRANSPORT_RETRIES = 3
MAX_VALIDATION_RETRIES = 1
TIMEOUT_SECONDS = 900
TRANSIENT_WORDS = ("capacity", "rate limit", "too many requests", "overloaded", "server busy", "temporarily unavailable", "connection reset", "connection refused", "timeout", "timed out", "429", "503", "502", "504")
CAPACITY_WORDS = ("capacity", "rate limit", "too many requests", "overloaded", "server busy", "429")
TERMINAL_STATES = {"SUCCESS", "TERMINAL_FAILURE"}
IO_LOCK = threading.Lock()
PROCESS_LOCK = threading.Lock()
ACTIVE_PROCESSES: dict[int, subprocess.Popen] = {}
CANCELLED = threading.Event()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(temp, path)


def append_ledger(record: dict[str, Any]) -> None:
    with IO_LOCK:
        runtime_path("extraction_ledger.jsonl").parent.mkdir(parents=True, exist_ok=True)
        with runtime_path("extraction_ledger.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(canonical_json(record) + "\n")
            fh.flush()
            os.fsync(fh.fileno())


def records() -> list[dict[str, Any]]:
    path = runtime_path("extraction_ledger.jsonl")
    if not path.exists():
        return []
    result = []
    with path.open(encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:

                raise RuntimeError(f"ledger is incomplete at line {line_number}; preserve and repair it before resuming") from exc
            if not isinstance(record, dict):
                raise RuntimeError(f"ledger line {line_number} is not an object")
            result.append(record)
    return result


@contextmanager
def exclusive_run():
    with (HERE / ".runner.lock").open("a+", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('another notice_extraction runner holds the exclusive process lock') from exc
        fh.seek(0)
        fh.truncate()
        fh.write(canonical_json({"pid": os.getpid(), "started_utc": utc_now()}) + "\n")
        fh.flush()
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def verify_freeze() -> dict[str, Any]:
    path = HERE / "CONTRACT_FREEZE_1_3.json"
    freeze = json.loads(path.read_text(encoding="utf-8"))
    if freeze.get("contract_version") != CONTRACT_VERSION or freeze.get("runtime_directory") != RUNTIME_DIRECTORY:
        raise RuntimeError("contract freeze is not version 1.3 with isolated runtime")
    if (freeze.get("transport_retries_total_per_notice"), freeze.get("validation_retries_total_per_notice"), freeze.get("maximum_requests_per_notice")) != (MAX_TRANSPORT_RETRIES, MAX_VALIDATION_RETRIES, 1 + MAX_TRANSPORT_RETRIES + MAX_VALIDATION_RETRIES):
        raise RuntimeError("frozen retry budgets differ from the unchanged v1.2 budgets")
    if freeze.get("model_requested") != MODEL or freeze.get("model_reasoning_effort") != REASONING_EFFORT:
        raise RuntimeError("requested model or effort differs from contract freeze")
    if freeze.get("cli_path") != str(CLI):
        raise RuntimeError("CLI path differs from contract freeze")
    if not freeze.get("cli_sha256") or sha_file(CLI) != freeze["cli_sha256"]:
        raise RuntimeError("CLI binary differs from frozen version; freeze a new contract before extraction")
    if freeze.get("contract_sha256") != sha_file(HERE / 'CONTRACT_SPECIFICATION_1_3.md'):
        raise RuntimeError('contract specification text differs from freeze')
    if freeze.get("base_contract_sha256") != sha_file(HERE / "CONTRACT.md"):
        raise RuntimeError("immutable base contract text differs from freeze")
    required = {
        "CONTRACT.md", 'CONTRACT_SPECIFICATION_1_1.md', 'CONTRACT_SPECIFICATION_1_2.md', 'CONTRACT_SPECIFICATION_1_3.md',
        "prompt.txt", "schema_full.json", "schema_response_format.json", "run_notice_extraction.py",
        "validate_notice_label.py", 'validate_notice_fields.py', "prepare_notice_scope.py", "scope.jsonl",
        "pilot_ids_1_3.json", "SCOPE_RECEIPT.json", "CONTRACT_FREEZE.json", "CONTRACT_FREEZE_1_1.json",
        "CONTRACT_FREEZE_1_2.json", "archive_v1/run_notice_extraction.py", 'archive_label_specification/run_notice_extraction.py',
        'archive_window_specification/run_notice_extraction.py', 'archive_label_specification/prompt.txt', 'window_prompt.py',
        'verify_label_preservation.py', 'label_specification_PRESERVATION_MANIFEST.json',
        'verify_window_preservation.py', 'window_specification_PRESERVATION_MANIFEST.json',
        'prepare_quantity_sample.py', "PILOT_SELECTION_1_3.json", "PILOT_PLAN_1_3.md", "FULL_PLAN_1_3.md",
        "NRX4_SPEC.json", "NRX4_SPEC_FREEZE.json", "test_run_notice_extraction_1_3.py",
    }
    declared = freeze.get("files_sha256", {})
    if not required.issubset(declared):
        raise RuntimeError(f"freeze missing required files: {sorted(required - set(declared))}")
    for name, expected in declared.items():
        file_path = (HERE / name).resolve()
        if not file_path.is_relative_to(HERE.resolve()):
            raise RuntimeError(f"freeze file outside notice_extraction: {name}")
        if sha_file(file_path) != expected:
            raise RuntimeError(f"contract freeze mismatch: {name}")
    prior_path = HERE / "CONTRACT_FREEZE_1_2.json"
    if freeze.get("prior_contract_freeze_sha256") != sha_file(prior_path):
        raise RuntimeError('prior v1.2 contract freeze differs from specification baseline')
    prior = json.loads(prior_path.read_text(encoding="utf-8"))
    if prior.get("contract_version") != "1.2":
        raise RuntimeError('specification baseline is not contract v1.2')
    for key in ("model_requested", "model_reasoning_effort", "transport_retries_total_per_notice", "validation_retries_total_per_notice", "maximum_requests_per_notice", "cli_path", "cli_sha256", "cli_version", "full_worker_policy", "expected_unique_notices", "pilot_notices"):
        if freeze.get(key) != prior.get(key):
            raise RuntimeError(f"v1.2 frozen setting changed: {key}")
    for name in ("prompt.txt", "schema_full.json", "schema_response_format.json", "validate_notice_label.py", 'validate_notice_fields.py', "prepare_notice_scope.py", "scope.jsonl", "SCOPE_RECEIPT.json"):
        if declared[name] != prior["files_sha256"][name]:
            raise RuntimeError(f"v1.2 frozen asset is not byte-identical: {name}")
    if declared['archive_window_specification/run_notice_extraction.py'] != prior["files_sha256"]["run_notice_extraction.py"]:
        raise RuntimeError("archived v1.2 runner is not byte-identical")
    if freeze.get('gate_definition_only_specification') is not True or freeze.get("prompt_byte_identical_to_contract_version") != "1.2":
        raise RuntimeError("contract 1.3 must change only the gate definition")
    from window_prompt import verify_prompt
    from verify_window_preservation import verify
    verify_prompt(HERE)
    verify(HERE)
    if freeze.get("scope_freeze_sha256") != sha_file(HERE / "SCOPE_RECEIPT.json"):
        raise RuntimeError("scope receipt differs from freeze")
    freeze = dict(freeze)
    freeze["contract_freeze_sha256"] = sha_file(path)
    return freeze

def request_payload(notice: dict[str, Any]) -> dict[str, Any]:
    payload = {name: notice[name] for name in ("notice_id", "title", "body", "clocks")}
    if not isinstance(payload["notice_id"], str) or not isinstance(payload["title"], str) or not isinstance(payload["body"], str) or not isinstance(payload["clocks"], dict):
        raise RuntimeError("notice input has incorrect types")
    digest = sha_bytes(canonical_json(payload).encode("utf-8"))
    if digest != notice["input_sha256"]:
        raise RuntimeError(f"source input hash drift for {notice['notice_id']}")
    return payload


def render_prompt(notice: dict[str, Any]) -> str:
    template = (HERE / "prompt.txt").read_text(encoding="utf-8")
    if template.count("{notice_json}") != 1:
        raise RuntimeError("frozen prompt must have exactly one {notice_json} placeholder")
    return template.replace("{notice_json}", canonical_json(request_payload(notice)))


def verify_request_assets(freeze: dict[str, Any]) -> None:
    for name in ("prompt.txt", "schema_full.json", "schema_response_format.json"):
        if sha_file(HERE / name) != freeze["files_sha256"][name]:
            raise RuntimeError(f"frozen request asset changed during run: {name}")


def source_lineage(notice: dict[str, Any]) -> dict[str, Any]:
    keys = ("source_kind", "source_registry_path", "source_registry_line", "source_registry_sha256", "source_file", "source_file_sha256", "source_url", "source_capture_time_utc", "source_capture_time_status", "source_text_clock_sha256", "source_clock_status", "original_source_notice_id", "raw_record_sha256", "version_sha256", "title_sha256", "body_sha256")
    return {key: notice.get(key) for key in keys}


def command(output: Path, workdir: str) -> list[str]:
    cmd = [str(CLI), "exec", "--ephemeral", "--ignore-rules", "--ignore-user-config", "--skip-git-repo-check", "--sandbox", "read-only", "-C", workdir, "-m", MODEL, "-c", f'model_reasoning_effort="{REASONING_EFFORT}"', "-c", 'web_search="disabled"']
    for feature in DISABLED_FEATURES:
        cmd.extend(("--disable", feature))
    cmd.extend(("--output-schema", str(HERE / "schema_response_format.json"), "--json", "-o", str(output), "-"))
    return cmd


def usage_and_tools(stdout: str) -> tuple[dict[str, int], list[str], list[dict[str, Any]]]:
    usage: Counter = Counter()
    model_ids: set[str] = set()
    tool_events = []
    tool_types = {"command_execution", "mcp_tool_call", "web_search", "web_search_call", "browser_use", "computer_use", "image_generation", "file_change", "collab_tool_call", "tool_call", "function_call"}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        for obj in (event, event.get("item", {})):
            if not isinstance(obj, dict):
                continue
            for key in ("model", "model_id", "model_name", "snapshot"):
                if isinstance(obj.get(key), str):
                    model_ids.add(obj[key])
            typ = obj.get("type", "")
            if typ in tool_types or (isinstance(typ, str) and any(token in typ for token in ("tool_call", "browser", "computer", "web_search", "command_execution"))):
                tool_events.append({"event_type": event.get("type"), "item_type": typ, "item_id": obj.get("id")})
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            usage.update({k: v for k, v in event["usage"].items() if isinstance(v, int) and not isinstance(v, bool)})
    return dict(usage), sorted(model_ids), tool_events


def invoke(prompt: str) -> dict[str, Any]:

    started = utc_now()
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="nrx_luna_") as tmp:
        output = Path(tmp) / "response.json"
        cmd = command(output, tmp)
        try:
            if CANCELLED.is_set():
                raise RuntimeError("runner cancelled before provider dispatch")
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            with PROCESS_LOCK:
                ACTIVE_PROCESSES[proc.pid] = proc
            try:
                stdout, stderr = proc.communicate(input=prompt, timeout=TIMEOUT_SECONDS)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                stdout, stderr = proc.communicate()
                stderr += '\nnotice_extraction bounded transport timeout after 900 seconds'
                exit_code = 124
            finally:
                with PROCESS_LOCK:
                    ACTIVE_PROCESSES.pop(proc.pid, None)
        except OSError as exc:
            stdout, stderr, exit_code = "", f"{type(exc).__name__}: {exc}", 127
        response = output.read_text(encoding="utf-8") if output.exists() else ""
    return {"cmd": cmd, "stdout_jsonl": stdout, "stderr": stderr, "response": response, "exit_code": exit_code, "started_utc": started, "ended_utc": utc_now(), "wall_seconds": round(time.perf_counter() - start, 3)}


def cancel_active(signum: int, _frame: Any) -> None:
    CANCELLED.set()
    with PROCESS_LOCK:
        processes = list(ACTIVE_PROCESSES.values())
    for proc in processes:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    raise KeyboardInterrupt(f"notice_extraction received signal {signum}; active CLI process groups terminated")


def current_records(all_records: list[dict[str, Any]], freeze: dict[str, Any]) -> list[dict[str, Any]]:
    expected = {"contract_version": CONTRACT_VERSION, "contract_sha256": freeze["contract_sha256"], "contract_freeze_sha256": freeze["contract_freeze_sha256"], "scope_freeze_sha256": freeze["scope_freeze_sha256"]}
    if freeze.get("contract_version") != CONTRACT_VERSION or any(any(r.get(k) != v for k, v in expected.items()) for r in all_records):
        raise RuntimeError("ledger contains foreign contract or v1.0/v1.1/v1.2 records; v1.0/v1.1/v1.2 reuse prohibited")
    return all_records


def final_by_key(all_records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    terminal = {}
    for record in all_records:
        if record.get("event") == "ATTEMPT_RESULT" and record.get("status") in TERMINAL_STATES:
            key = record["notice_key"]
            if key in terminal:
                raise RuntimeError(f"duplicate terminal ledger state for {key}")
            terminal[key] = record
    return terminal


def pilot_ledger_digest(all_records: list[dict[str, Any]]) -> str:
    return sha_bytes(("".join(canonical_json(r) + "\n" for r in all_records if r.get("phase") == "pilot")).encode("utf-8"))


def base_record(freeze: dict[str, Any], phase: str) -> dict[str, Any]:
    return {"phase": phase, "contract_version": CONTRACT_VERSION, "contract_sha256": freeze["contract_sha256"], "contract_freeze_sha256": freeze["contract_freeze_sha256"], "scope_freeze_sha256": freeze["scope_freeze_sha256"], "model_requested": MODEL, "model_reasoning_effort": REASONING_EFFORT}


class CapacityController:

    def __init__(self, phase: str, workers: int, freeze: dict[str, Any], history: list[dict[str, Any]]):
        self.phase, self.freeze, self.initial = phase, freeze, workers
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.active = 0
        self.effective = workers
        self.launched = max((r.get("request_index", 0) for r in history if r.get("phase") == phase and r.get("event") == "ATTEMPT_STARTED"), default=0)
        self.completed = {r["request_index"]: bool(r.get("capacity_error")) for r in history if r.get("phase") == phase and r.get("event") == "ATTEMPT_RESULT" and "request_index" in r}
        changes = [r for r in history if r.get("phase") == phase and r.get("event") == "WORKERS_CHANGED"]
        if changes:
            self.effective = min(workers, changes[-1]["workers_after"]) if changes[-1]["reason"] == "capacity" or workers != 16 else changes[-1]["workers_after"]
        self.ever_capacity = any(self.completed.values()) or any(r.get("reason") == "capacity" for r in changes)
        self.ramped = any(r.get("reason") == "first_200_capacity_free" for r in changes)
        observed_capacity_indices = {r.get("request_index") for r in changes if r.get("reason") == "capacity"}
        for index, capacity in sorted(self.completed.items()):
            if capacity and index not in observed_capacity_indices:
                self.finished(index, True)

    def reserve(self) -> int:
        with self.lock:
            self.launched += 1
            return self.launched

    def limit(self) -> int:
        with self.lock:
            return self.effective

    def acquire(self) -> None:
        with self.condition:
            while self.active >= self.effective:
                self.condition.wait()
            self.active += 1

    def release(self) -> None:
        with self.condition:
            self.active -= 1
            self.condition.notify_all()

    def finished(self, request_index: int, capacity: bool) -> None:
        with self.lock:
            self.completed[request_index] = capacity
            reference_snapshot = self.effective
            reason = None
            if capacity:
                self.ever_capacity = True
                self.effective = max(1, math.ceil(self.effective / 2))
                reason = "capacity"
            elif self.phase == "full" and self.initial == 16 and not self.ramped and not self.ever_capacity and all(i in self.completed for i in range(1, 201)) and not any(self.completed[i] for i in range(1, 201)):
                self.effective = 24
                self.ramped = True
                reason = "first_200_capacity_free"
            if reason:
                append_ledger({**base_record(self.freeze, self.phase), "event": "WORKERS_CHANGED", "utc": utc_now(), "reason": reason, "request_index": request_index, "workers_before": reference_snapshot, "workers_after": self.effective, "inflight_policy": "existing calls finish; new notice launches wait for reduced limit"})
                self.condition.notify_all()


def transport_classification(result: dict[str, Any]) -> tuple[bool, bool]:

    if result["exit_code"] == 0 and result["response"]:
        return False, False
    error_messages = []
    for line in result["stdout_jsonl"].splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") in {"error", "turn.failed", "response.failed"}:
            error_messages.append(canonical_json(event))
    diagnostic = (result["stderr"] + "\n" + "\n".join(error_messages)).lower()
    capacity = any(word in diagnostic for word in CAPACITY_WORDS)
    transient = capacity or result["exit_code"] == 124 or any(word in diagnostic for word in TRANSIENT_WORDS) or (result["exit_code"] == 0 and not result["response"])
    return capacity, transient


def recovered_state(notice: dict[str, Any], phase: str, freeze: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    current_records(history, freeze)
    related = [r for r in history if r.get("notice_key") == notice["notice_key"]]
    if any(r.get("input_sha256") != notice["input_sha256"] for r in related if r.get("event") in {"ATTEMPT_STARTED", "ATTEMPT_RESULT"}):
        raise RuntimeError(f"resume input mismatch: {notice['notice_key']}")
    terminal = final_by_key(related).get(notice["notice_key"])
    if terminal:
        return {"terminal": terminal}
    starts = [r for r in related if r.get("event") == "ATTEMPT_STARTED"]
    results = {r["attempt"]: r for r in related if r.get("event") == "ATTEMPT_RESULT"}
    if not starts:
        return {"attempt": 0, "transport_retries_used": 0, "validation_retries_used": 0}
    last = max(starts, key=lambda r: r["attempt"])
    if last["attempt"] not in results:
        raw_path = raw_receipt_path(last["raw_path"])
        if raw_path.exists():
            from validate_notice_fields import parse_label_json, validate_label
            with gzip.open(raw_path, "rt", encoding="utf-8") as fh:
                raw = json.load(fh)
            identity = ("contract_version", "contract_sha256", "scope_freeze_sha256", "notice_key", "notice_id", "input_sha256", "prompt_sha256", "contract_freeze_sha256", "attempt", "request_index")
            if any(raw.get(key) != last.get(key) for key in identity):
                raise RuntimeError("uncommitted raw receipt identity differs from reserved request")
            if sha_bytes(raw.get("prompt", "").encode()) != last["prompt_sha256"] or sha_bytes(canonical_json(raw.get("input")).encode()) != last["input_sha256"] or sha_bytes(raw.get("response", "").encode()) != raw.get("output_sha256"):
                raise RuntimeError("uncommitted raw receipt hashes differ")
            parsed = None
            try:
                parsed = parse_label_json(raw["response"]) if raw["response"] else None
            except (ValueError, TypeError):
                pass
            if parsed != raw.get("parsed_label"):
                raise RuntimeError("uncommitted raw response and decoded output differ")
            recomputed = validate_label(parsed, notice) if parsed is not None else []
            if any(error not in raw.get("validation_errors", []) for error in recomputed):
                raise RuntimeError("uncommitted raw validation errors are incomplete")
            if raw.get("status") == "SUCCESS" and (recomputed or raw.get("exit_code") != 0 or raw.get("tool_calls")):
                raise RuntimeError("uncommitted raw SUCCESS is invalid")
            result_names = ("status", "transport_retries_used", "validation_retries_used", "ended_utc", "wall_seconds", "exit_code", "output_sha256", "response_sha256", "usage", "model_ids_exposed", "capacity_error", "tool_calls", "tool_events", "validation_errors", "parsed_label", "retry_after_seconds")
            recovered = {**last, **{key: raw[key] for key in result_names}, "event": "ATTEMPT_RESULT", "raw_sha256": sha_file(raw_path), "recovered_from_raw": True}
            append_ledger(recovered)
            if recovered["status"] in TERMINAL_STATES:
                return {"terminal": recovered, "recovered_record": recovered}
            return {**{key: recovered[key] for key in ("attempt", "transport_retries_used", "validation_retries_used")}, "recovered_record": recovered}
        used = last["transport_retries_used"]
        retry = used < MAX_TRANSPORT_RETRIES
        recovered = {**last, "event": "ATTEMPT_RESULT", "status": "TRANSPORT_RETRY" if retry else "TERMINAL_FAILURE", "ended_utc": utc_now(), "wall_seconds": None, "transport_retries_used": used + int(retry), "interrupted": True, "capacity_error": False, "exit_code": None, "output_sha256": None, "validation_errors": [{"code": "INTERRUPTED", "path": "$", "message": "reserved request interrupted; consumes remaining transport retry budget"}], "parsed_label": None, "raw_path": last["raw_path"] if raw_receipt_path(last["raw_path"]).exists() else None}
        append_ledger(recovered)
        if not retry:
            return {"terminal": recovered, "recovered_record": recovered}
        return {**{k: recovered[k] for k in ("attempt", "transport_retries_used", "validation_retries_used")}, "recovered_record": recovered}
    last_result = results[last["attempt"]]
    return {k: last_result[k] for k in ("attempt", "transport_retries_used", "validation_retries_used")}


def save_raw(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with gzip.open(temp, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, sort_keys=True)
    os.replace(temp, path)


def call_one(notice: dict[str, Any], phase: str, freeze: dict[str, Any], history: list[dict[str, Any]], controller: CapacityController) -> None:
    from validate_notice_fields import check_contamination, parse_label_json, validate_label
    state = recovered_state(notice, phase, freeze, history)
    if "recovered_record" in state:
        recovered = state["recovered_record"]
        controller.finished(recovered["request_index"], bool(recovered.get("capacity_error")))
    if "terminal" in state:
        return
    prompt = render_prompt(notice)
    transport_used, validation_used, attempt = state["transport_retries_used"], state["validation_retries_used"], state["attempt"]
    while True:
        verify_request_assets(freeze)
        attempt += 1
        if attempt > 1 + MAX_TRANSPORT_RETRIES + MAX_VALIDATION_RETRIES:
            raise RuntimeError("retry budget invariant failed")
        controller.acquire()
        if CANCELLED.is_set():
            controller.release()
            raise RuntimeError("runner cancelled before request reservation")
        request_index = controller.reserve()
        raw_path = runtime_path("raw") / sha_bytes(notice["notice_key"].encode())[:24] / f"attempt_{attempt:02d}.json.gz"
        started = {**base_record(freeze, phase), "event": "ATTEMPT_STARTED", "notice_key": notice["notice_key"], "notice_id": notice["notice_id"], "input_sha256": notice["input_sha256"], "prompt_sha256": sha_bytes(prompt.encode()), "notices_in_request": 1, "source_provenance": source_lineage(notice), "attempt": attempt, "request_index": request_index, "transport_retries_used": transport_used, "validation_retries_used": validation_used, "started_utc": utc_now(), "raw_path": str(raw_path.relative_to(HERE))}
        try:
            append_ledger(started)
            result = invoke(prompt)
            capacity, transient = transport_classification(result)
            controller.finished(request_index, capacity)
        finally:
            controller.release()
        response = result["response"]
        usage, exposed_model_ids, tool_events = usage_and_tools(result["stdout_jsonl"])
        parsed = None
        errors = []
        if response:
            try:
                parsed = parse_label_json(response)
                errors = validate_label(parsed, notice)
            except (ValueError, TypeError) as exc:
                errors = [{"code": "JSON", "path": "$", "message": f"{type(exc).__name__}: {exc}"}]
                errors.extend(check_contamination(response, notice))
        else:
            errors = [{"code": "TRANSPORT", "path": "$", "message": f"CLI exit {result['exit_code']}; no output"}]
        if tool_events:
            errors.append({"code": "TOOL_USE", "path": "$", "message": "CLI emitted tool invocation event; source isolation breached"})
        if result["exit_code"] != 0:
            errors.append({"code": "TRANSPORT", "path": "$", "message": f"CLI exit {result['exit_code']}"})
        if result["exit_code"] == 0 and response and not errors:
            status = "SUCCESS"
        elif tool_events:
            status = "TERMINAL_FAILURE"
        elif transient and transport_used < MAX_TRANSPORT_RETRIES:
            transport_used += 1
            status = "CAPACITY_RETRY" if capacity else "TRANSPORT_RETRY"
        elif result["exit_code"] == 0 and response and validation_used < MAX_VALIDATION_RETRIES:
            validation_used += 1
            status = "VALIDATION_RETRY"
        else:
            status = "TERMINAL_FAILURE"
        retry = status.endswith("RETRY")
        delay = min(900, 30 * 2 ** max(0, transport_used - 1)) if status in {"CAPACITY_RETRY", "TRANSPORT_RETRY"} else 0
        record = {**started, "event": "ATTEMPT_RESULT", "status": status, "transport_retries_used": transport_used, "validation_retries_used": validation_used, "ended_utc": result["ended_utc"], "wall_seconds": result["wall_seconds"], "exit_code": result["exit_code"], "input_sha256": notice["input_sha256"], "output_sha256": sha_bytes(response.encode()), "response_sha256": sha_bytes(response.encode()), "usage": usage, "model_ids_exposed": exposed_model_ids, "capacity_error": capacity, "tool_calls": len(tool_events), "tool_events": tool_events, "validation_errors": errors, "parsed_label": parsed, "retry_after_seconds": delay}
        raw = {**record, **result, "prompt": prompt, "input": request_payload(notice)}
        save_raw(raw_path, raw)
        record["raw_sha256"] = sha_file(raw_path)
        append_ledger(record)
        if not retry:
            return
        if delay:
            time.sleep(delay)


def audit_raw(all_records: list[dict[str, Any]]) -> None:
    for record in all_records:
        if record.get("event") != "ATTEMPT_RESULT" or not record.get("raw_sha256"):
            continue
        if record.get("contract_version") != CONTRACT_VERSION:
            raise RuntimeError("raw receipt ledger version differs from v1.3; v1.0/v1.1/v1.2 reuse prohibited")
        path = raw_receipt_path(record["raw_path"])
        if sha_file(path) != record["raw_sha256"]:
            raise RuntimeError(f"raw receipt missing or changed: {record.get('notice_key')} attempt {record.get('attempt')}")
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            raw = json.load(fh)
        if any(raw.get(key) != record.get(key) for key in ("contract_version", "contract_sha256", "contract_freeze_sha256", "scope_freeze_sha256", "notice_key", "notice_id", "attempt", "request_index")):
            raise RuntimeError("raw receipt identity differs from contract v1.3 ledger")
        if sha_bytes(raw.get("response", "").encode()) != record.get("output_sha256") or sha_bytes(raw.get("prompt", "").encode()) != record.get("prompt_sha256") or sha_bytes(canonical_json(raw.get("input")).encode()) != record.get("input_sha256"):
            raise RuntimeError("raw input/prompt/output hashes differ from ledger")
        if raw.get("parsed_label") != record.get("parsed_label"):
            raise RuntimeError("raw parsed output differs from ledger")


STRUCTURAL_CODES = {
    "SCHEMA", "EMPTY_WINDOW_ID", "DUPLICATE_WINDOW_ID", "WINDOW_ID_SEQUENCE",
    "BOUNDED_ENDPOINT_MISSING", "OPEN_INTERVAL_HAS_END", "ATTRIBUTE_REGION_CONFLICT",
    "BINDING_REASON_MISMATCH", "BAD_WINDOW_REFERENCE", "BOUND_ASSET_CONFLICT", "UNBOUND_HAS_WINDOW",
}
MACHINE_CRITERION_NAMES = {
    "valid_after_at_most_one_validation_retry", "all_20_terminal",
    "all_accepted_final_outputs_fully_valid", "zero_fabricated_spans_accepted_final_outputs",
    "all_window_quantity_bindings_valid_accepted_final_outputs",
    "no_other_notice_or_unsupported_date_all_attempts", "one_notice_per_request",
    "zero_tool_calls_all_attempts", "retry_budgets_respected", "no_prompt_schema_source_hash_drift",
}
PILOT_AUDIT_NAME = "PILOT_AUDIT_1_3.json"
PILOT_AUDIT_TEXT_NAME = "PILOT_AUDIT_1_3.md"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def pilot_sources(pilot_ids: list[str], scope: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    if scope is None:
        scope = []
        with (HERE / "scope.jsonl").open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    notice = json.loads(line)
                    if notice.get("notice_key") in pilot_ids:
                        scope.append(notice)
    selected = [notice for notice in scope if notice.get("notice_key") in pilot_ids]
    known = {notice["notice_key"]: notice for notice in selected}
    require(len(known) == len(selected) and set(known) == set(pilot_ids), "pilot sources missing or duplicated")
    return known


def raw_validation(raw: dict[str, Any], notice: dict[str, Any]) -> tuple[Any, list[dict[str, Any]], dict[str, Any], list[str], list[dict[str, Any]]]:

    from validate_notice_fields import check_contamination, parse_label_json, validate_label
    usage, model_ids, tools = usage_and_tools(raw["stdout_jsonl"])
    parsed, errors = None, []
    if raw["response"]:
        try:
            parsed = parse_label_json(raw["response"])
            errors = validate_label(parsed, notice)
        except (ValueError, TypeError) as exc:
            errors = [{"code": "JSON", "path": "$", "message": f"{type(exc).__name__}: {exc}"}]
            errors.extend(check_contamination(raw["response"], notice))
    else:
        errors = [{"code": "TRANSPORT", "path": "$", "message": f"CLI exit {raw['exit_code']}; no output"}]
    if tools:
        errors.append({"code": "TOOL_USE", "path": "$", "message": "CLI emitted tool invocation event; source isolation breached"})
    if raw["exit_code"] != 0:
        errors.append({"code": "TRANSPORT", "path": "$", "message": f"CLI exit {raw['exit_code']}"})
    return parsed, errors, usage, model_ids, tools


def independent_contamination(parsed: Any, response: str, notice: dict[str, Any]) -> list[dict[str, Any]]:

    from validate_notice_fields import check_contamination
    errors = check_contamination(parsed if parsed is not None else response, notice)
    if isinstance(parsed, dict) and parsed.get("notice_id") != notice["notice_id"]:
        for error in check_contamination(parsed.get("notice_id"), notice):
            error = {**error, "path": "/notice_id"}
            if error not in errors:
                errors.append(error)
    return errors


def gate_details(metrics: dict[str, bool], valid_final: int, accepted_errors: list[dict], contamination: list[dict]) -> list[dict]:
    return [
        {"criterion": 1, "pass": metrics["all_20_terminal"] and metrics["valid_after_at_most_one_validation_retry"] and metrics["all_accepted_final_outputs_fully_valid"], "valid_final_outputs": valid_final, "minimum_valid_final_outputs": 18, "maximum_validation_retries": 1},
        {"criterion": 2, "pass": metrics["zero_fabricated_spans_accepted_final_outputs"], "fabricated_spans_in_accepted_finals": sum(e["code"] == "FABRICATED_SPAN" for e in accepted_errors), "rejected_attempt_errors_are_reporting_only": True},
        {"criterion": 3, "pass": metrics["all_window_quantity_bindings_valid_accepted_final_outputs"], "structural_errors_in_accepted_finals": sum(e["code"] in STRUCTURAL_CODES for e in accepted_errors), "intermediate_structural_errors_are_reporting_only": True},
        {"criterion": 4, "pass": metrics["no_other_notice_or_unsupported_date_all_attempts"], "contamination_errors_in_any_attempt": len(contamination), "scope": "ALL_ATTEMPTS_INCLUDING_REJECTED"},
        {"criterion": 5, "pass": all(metrics[name] for name in ("one_notice_per_request", "zero_tool_calls_all_attempts", "retry_budgets_respected", "no_prompt_schema_source_hash_drift")), "source_request_raw_command_hashes_reproduced": metrics["no_prompt_schema_source_hash_drift"]},
    ]


def compute_pilot_audit(pilot_ids: list[str], all_records: list[dict[str, Any]], freeze: dict[str, Any], scope: list[dict[str, Any]] | None = None) -> dict[str, Any]:

    current_records(all_records, freeze)
    verify_request_assets(freeze)
    require(len(pilot_ids) == len(set(pilot_ids)) == 20, "pilot must contain 20 distinct notice keys")
    require(json.loads((HERE / "pilot_ids_1_3.json").read_text()) == pilot_ids, "pilot IDs differ from frozen selection")
    known = pilot_sources(pilot_ids, scope)
    subset = [r for r in all_records if r.get("phase") == "pilot"]
    starts = [r for r in subset if r.get("event") == "ATTEMPT_STARTED"]
    results = [r for r in subset if r.get("event") == "ATTEMPT_RESULT"]
    require(all(r.get("notice_key") in known for r in starts + results), "pilot ledger contains an unselected notice")
    start_map = {(r["notice_key"], r["attempt"]): r for r in starts}
    result_map = {(r["notice_key"], r["attempt"]): r for r in results}
    require(len(start_map) == len(starts) and len(result_map) == len(results), "duplicate pilot reservation/result")
    require(set(start_map) == set(result_map), "unmatched pilot reservation/result")
    require(sorted(r["request_index"] for r in starts) == list(range(1, len(starts) + 1)), "pilot request sequence differs")
    expected_base = base_record(freeze, "pilot")
    require(all(all(row.get(k) == v for k, v in expected_base.items()) for row in subset), "pilot ledger identity/model differs from contract")
    external_hashes: dict[Path, str] = {}
    for source in known.values():
        request_payload(source)
        require(source.get("version_sha256") == source["input_sha256"], "pilot input/source-version hash differs")
        for name in ("title", "body"):
            require(sha_bytes(source[name].encode()) == source.get(name + "_sha256"), "pilot source text digest differs")
        for path_name, hash_name in (("source_registry_path", "source_registry_sha256"), ("source_file", "source_file_sha256")):
            if source.get(path_name):
                path = Path(source[path_name])
                if path not in external_hashes:
                    external_hashes[path] = sha_file(path)
                require(external_hashes[path] == source.get(hash_name), f"pilot source provenance changed: {path}")
    rows, accepted_errors, contamination, rejected = [], [], [], []
    fully_valid_by_identity = {}
    for identity, record in sorted(result_map.items()):
        key, attempt = identity
        started, notice = start_map[identity], known[key]
        require(record.get("notice_id") == notice["notice_id"] == key, "pilot ledger/source ID differs")
        for name in ("input_sha256", "prompt_sha256", "raw_path", "request_index", "notice_id", "notices_in_request", "source_provenance", "started_utc"):
            if name == "raw_path" and record.get("interrupted") and not record.get("raw_sha256"):
                raw_receipt_path(started["raw_path"])
                continue
            require(record.get(name) == started.get(name), f"pilot start/result {name} differs: {identity}")
        require(record.get("input_sha256") == notice["input_sha256"], "pilot input hash differs")
        require(record.get("source_provenance") == source_lineage(notice), "pilot source lineage differs")
        prompt = render_prompt(notice)
        require(record.get("prompt_sha256") == sha_bytes(prompt.encode()), "pilot exact request differs")
        require(isinstance(attempt, int) and 1 <= attempt <= 5, "pilot attempt budget exceeded")
        if attempt == 1:
            require(started.get("transport_retries_used") == started.get("validation_retries_used") == 0, "pilot initial retry budget differs")
        else:
            require((key, attempt - 1) in result_map, "pilot attempt sequence has a gap")
            previous = result_map[(key, attempt - 1)]
            require(previous["status"].endswith("RETRY"), "pilot dispatch after terminal state")
            require((started.get("transport_retries_used"), started.get("validation_retries_used")) == (previous.get("transport_retries_used"), previous.get("validation_retries_used")), "pilot retry budget reset")
        scan_errors = []
        if record.get("interrupted") and not record.get("raw_sha256"):
            require(record.get("raw_path") is None and record.get("parsed_label") is None and record.get("output_sha256") is None and record.get("exit_code") is None, "interrupted request has inconsistent missing raw receipt")
            tused, vused = started["transport_retries_used"], started["validation_retries_used"]
            retry = tused < MAX_TRANSPORT_RETRIES
            errors = [{"code": "INTERRUPTED", "path": "$", "message": "reserved request interrupted; consumes remaining transport retry budget"}]
            require(record.get("validation_errors") == errors, "interrupted request errors differ")
            status, tused = ("TRANSPORT_RETRY" if retry else "TERMINAL_FAILURE"), tused + int(retry)
            parsed, tools = None, []
            fully_valid = False
        else:
            require(record.get("raw_sha256") is not None, "pilot response missing durable raw receipt")
            raw_path = raw_receipt_path(record["raw_path"])
            require(sha_file(raw_path) == record["raw_sha256"], "pilot compressed raw digest differs")
            with gzip.open(raw_path, "rt", encoding="utf-8") as fh:
                raw = json.load(fh)
            for name, value in record.items():
                if name not in {"raw_sha256", "started_utc", "recovered_from_raw"}:
                    require(raw.get(name) == value, f"pilot raw/ledger {name} differs: {identity}")
            require(raw.get("prompt") == prompt and raw.get("input") == request_payload(notice), "pilot exact raw request differs")
            require(sha_bytes(raw["response"].encode()) == record.get("output_sha256") == record.get("response_sha256"), "pilot response hash differs")
            cmd = raw.get("cmd", [])
            require("-C" in cmd and "-o" in cmd, "pilot CLI invocation missing workdir/output")
            workdir, output = cmd[cmd.index("-C") + 1], Path(cmd[cmd.index("-o") + 1])
            require(Path(workdir).is_absolute() and output.parent == Path(workdir), "pilot CLI workdir/output differs")
            require(cmd == command(output, workdir), "pilot CLI invocation differs from frozen transport")
            parsed, errors, usage, model_ids, tools = raw_validation(raw, notice)
            require(parsed == record.get("parsed_label") == raw.get("parsed_label"), "pilot independent JSON decode differs")
            require(errors == record.get("validation_errors"), "pilot unchanged validation errors do not reproduce")
            require((usage, model_ids, tools, len(tools)) == (record.get("usage"), record.get("model_ids_exposed"), record.get("tool_events"), record.get("tool_calls")), "pilot usage/model/tool census differs")
            capacity, transient = transport_classification(raw)
            require(capacity == record.get("capacity_error"), "pilot capacity classification differs")
            tused, vused = started["transport_retries_used"], started["validation_retries_used"]
            if raw["exit_code"] == 0 and raw["response"] and not errors:
                status = "SUCCESS"
            elif tools:
                status = "TERMINAL_FAILURE"
            elif transient and tused < MAX_TRANSPORT_RETRIES:
                tused += 1
                status = "CAPACITY_RETRY" if capacity else "TRANSPORT_RETRY"
            elif raw["exit_code"] == 0 and raw["response"] and vused < MAX_VALIDATION_RETRIES:
                vused += 1
                status = "VALIDATION_RETRY"
            else:
                status = "TERMINAL_FAILURE"
            delay = min(900, 30 * 2 ** max(0, tused - 1)) if status in {"CAPACITY_RETRY", "TRANSPORT_RETRY"} else 0
            require(record.get("retry_after_seconds") == delay, "pilot frozen backoff differs")
            scan_errors = independent_contamination(parsed, raw["response"], notice)
            fully_valid = parsed is not None and not errors and not scan_errors and raw["exit_code"] == 0 and not tools
        require((record.get("status"), record.get("transport_retries_used"), record.get("validation_retries_used")) == (status, tused, vused), "pilot retry/status disposition differs")
        require(tused <= MAX_TRANSPORT_RETRIES and vused <= MAX_VALIDATION_RETRIES, "pilot retry budget exceeded")
        full_errors = list(errors)
        for error in scan_errors:
            if error not in full_errors:
                full_errors.append(error)
        detail = {"notice_id": key, "attempt": attempt, "status": status, "accepted_final_output": status == "SUCCESS", "fully_valid": fully_valid, "validation_errors": errors, "independent_contamination_errors": scan_errors, "raw_path": record.get("raw_path"), "raw_sha256": record.get("raw_sha256"), "input_sha256": record["input_sha256"], "request_sha256": record["prompt_sha256"], "response_sha256": record.get("response_sha256"), "tool_calls": len(tools)}
        rows.append(detail)
        fully_valid_by_identity[identity] = fully_valid
        qualified = [{"notice_id": key, "attempt": attempt, **error, "raw_path": record.get("raw_path"), "raw_sha256": record.get("raw_sha256"), "response_sha256": record.get("response_sha256")} for error in full_errors]
        contamination.extend({"notice_id": key, "attempt": attempt, **error, "raw_path": record.get("raw_path"), "raw_sha256": record.get("raw_sha256"), "response_sha256": record.get("response_sha256")} for error in scan_errors)
        if status == "SUCCESS":
            accepted_errors.extend(qualified)
        else:
            rejected.append({**detail, "errors": qualified})
    finals = final_by_key(subset)
    accepted = [record for record in finals.values() if record["status"] == "SUCCESS"]
    valid_final = sum(record["status"] == "SUCCESS" and fully_valid_by_identity[(key, record["attempt"])] for key, record in finals.items())
    metrics = {
        "valid_after_at_most_one_validation_retry": valid_final >= 18,
        "all_20_terminal": len(finals) == 20 and set(finals) == set(pilot_ids),
        "all_accepted_final_outputs_fully_valid": all(fully_valid_by_identity[(r["notice_key"], r["attempt"])] for r in accepted),
        "zero_fabricated_spans_accepted_final_outputs": not any(e["code"] == "FABRICATED_SPAN" for e in accepted_errors),
        "all_window_quantity_bindings_valid_accepted_final_outputs": not any(e["code"] in STRUCTURAL_CODES for e in accepted_errors),
        "no_other_notice_or_unsupported_date_all_attempts": not contamination,
        "one_notice_per_request": all(r.get("notices_in_request") == 1 for r in starts),
        "zero_tool_calls_all_attempts": all(not r.get("tool_calls") for r in results),
        "retry_budgets_respected": all(r["transport_retries_used"] <= MAX_TRANSPORT_RETRIES and r["validation_retries_used"] <= MAX_VALIDATION_RETRIES and r["attempt"] <= 5 for r in results),
        "no_prompt_schema_source_hash_drift": True,
    }
    criteria = gate_details(metrics, valid_final, accepted_errors, contamination)
    rejected_errors = [error for row in rejected for error in row["errors"]]
    return {
        **base_record(freeze, "pilot"), "state": "PASS" if all(metrics.values()) else "FAIL",
        "gate_definition_version": "1.3", "pilot_ids_sha256": sha_file(HERE / "pilot_ids_1_3.json"),
        "pilot_ledger_sha256": pilot_ledger_digest(all_records), "pilot_notices": len(pilot_ids),
        "terminal_counts": dict(Counter(r["status"] for r in finals.values())), "valid_final_outputs": valid_final,
        "accepted_final_outputs": len(accepted), "provider_requests_reserved": len(starts), "completed_attempt_receipts": len(results),
        "machine_gate_criteria": metrics, "machine_gate_would_pass": all(metrics.values()),
        "gate_criterion_details": criteria, "failing_criteria": [row["criterion"] for row in criteria if not row["pass"]],
        "accepted_final_errors": accepted_errors, "contamination_errors_all_attempts": contamination,
        "rejected_attempt_count": len(rejected), "rejected_attempt_error_code_counts": dict(sorted(Counter(e["code"] for e in rejected_errors).items())),
        "rejected_attempt_error_code_path_counts": [{"code": code, "path": path, "count": count} for (code, path), count in sorted(Counter((e["code"], e["path"]) for e in rejected_errors).items())],
        "rejected_attempt_error_census": rejected, "rejected_errors_gate_scope": "REPORT_ONLY_EXCEPT_CONTAMINATION_AND_TOOLS_AND_BUDGET_OR_DRIFT",
        "attempt_audits": rows, "source_provenance_files_verified_sha256": {str(path): value for path, value in external_hashes.items()},
        "integrity_checks": {"source_input_request_hashes": True, "raw_receipt_sha256": True, "decoded_response_and_validator_equality": True, "frozen_cli_command_usage_tools": True, "retry_progression_terminal_disposition": True},
        "semantic_limits": "Mechanical validity does not establish semantic entailment, event attachment, completeness or recall.",
        "model_calls_during_grading": 0,
    }


def failed_integrity_audit(pilot_ids: list[str], all_records: list[dict[str, Any]], freeze: dict[str, Any], exc: Exception) -> dict[str, Any]:

    metrics = {name: False for name in sorted(MACHINE_CRITERION_NAMES)}
    rejected = [{"notice_id": r.get("notice_id"), "attempt": r.get("attempt"), "status": r.get("status"), "errors": r.get("validation_errors", []), "raw_path": r.get("raw_path"), "raw_sha256": r.get("raw_sha256"), "independently_verified": False} for r in all_records if r.get("phase") == "pilot" and r.get("event") == "ATTEMPT_RESULT" and r.get("status") != "SUCCESS"]
    return {**base_record(freeze, "pilot"), "state": "FAIL", "gate_definition_version": "1.3", "pilot_ids_sha256": sha_file(HERE / "pilot_ids_1_3.json"), "pilot_ledger_sha256": pilot_ledger_digest(all_records), "pilot_notices": len(pilot_ids), "valid_final_outputs": 0, "terminal_counts": {}, "machine_gate_criteria": metrics, "machine_gate_would_pass": False, "gate_criterion_details": gate_details(metrics, 0, [], []), "failing_criteria": [1, 2, 3, 4, 5], "integrity_error": f"{type(exc).__name__}: {exc}", "rejected_attempt_error_census": rejected, "rejected_attempt_census_complete_and_verified": False, "model_calls_during_grading": 0}


def audit_markdown(audit: dict[str, Any]) -> str:
    lines = ['# notice_extraction contract 1.3 automatic pilot audit', "", f"State: **{audit['state']}**. Valid final labels: **{audit['valid_final_outputs']}/20**.", "", "The frozen 18/20 threshold and extraction prompt remain unchanged. Fabrication and structural criteria apply to accepted final outputs; contamination, tools, request isolation, drift and budgets apply to every attempt. Rejected validation errors are reported below.", "", "| Criterion | Result |", "| --- | --- |"]
    for row in audit["gate_criterion_details"]:
        lines.append(f"| {row['criterion']} | {'PASS' if row['pass'] else 'FAIL'} |")
    if audit.get("integrity_error"):
        lines.extend(["", "Independent audit could not complete:", "", audit["integrity_error"]])
    lines.extend(["", "## Every rejected attempt", "", "| Notice | Attempt | Status | Error code | Path | Message |", "| --- | --- | --- | --- | --- | --- |"])
    for row in audit["rejected_attempt_error_census"]:
        for error in row["errors"] or [{"code": "NO_RECORDED_ERROR", "path": "$", "message": "See JSON audit/raw receipt."}]:
            message = str(error.get("message", "")).replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {row['notice_id']} | {row['attempt']} | {row['status']} | {error['code']} | {error['path']} | {message} |")
    if not audit["rejected_attempt_error_census"]:
        lines.append("| — | — | — | NONE | — | No rejected attempts. |")
    lines.extend(["", "Each raw receipt, response and complete request digest is recorded in PILOT_AUDIT_1_3.json. Rejected attempts never enter the label bank. A PASS permits the matching fresh 1.3 full run; prior gates supply no credit. Mechanical validity does not certify semantic correctness or recall.", "", f"Pilot ledger SHA-256: `{audit['pilot_ledger_sha256']}`", "", "No model calls are made by grading.", ""])
    return "\n".join(lines)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as fh:
        fh.write(value)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(temp, path)


def pilot_receipt(pilot_ids: list[str], all_records: list[dict[str, Any]], freeze: dict[str, Any], scope: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    try:
        audit = compute_pilot_audit(pilot_ids, all_records, freeze, scope)
    except (RuntimeError, ValueError, TypeError, KeyError, OSError) as exc:
        audit = failed_integrity_audit(pilot_ids, all_records, freeze, exc)
    timestamp = utc_now()
    audit["generated_utc"] = timestamp
    atomic_json(runtime_path(PILOT_AUDIT_NAME), audit)
    atomic_text(runtime_path(PILOT_AUDIT_TEXT_NAME), audit_markdown(audit))
    receipt = {**audit, "audit_file": PILOT_AUDIT_NAME, "audit_sha256": sha_file(runtime_path(PILOT_AUDIT_NAME)), "human_readable_audit_file": PILOT_AUDIT_TEXT_NAME, "human_readable_audit_sha256": sha_file(runtime_path(PILOT_AUDIT_TEXT_NAME)), "automatic_grading": True, "follow_up_required": "Run the matching contract 1.3 full command after PASS; no separate grading task." if audit["state"] == "PASS" else "Full extraction prohibited; retain the FAIL and its audit."}
    atomic_json(runtime_path(PILOT_RECEIPT_NAME), receipt)
    gate = {**receipt, "status": receipt["state"], "graded_utc": timestamp, "pilot_receipt_sha256": sha_file(runtime_path(PILOT_RECEIPT_NAME)), "audited_pilot_ledger_sha256": receipt["pilot_ledger_sha256"], "full_run_authorized": receipt["state"] == "PASS"}
    atomic_json(runtime_path(PILOT_GATE_NAME), gate)
    return receipt


def verify_pilot_gate(freeze: dict[str, Any], all_records: list[dict[str, Any]], scope: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    current_records(all_records, freeze)
    gate_path, receipt_path = runtime_path(PILOT_GATE_NAME), runtime_path(PILOT_RECEIPT_NAME)
    audit_path, audit_text_path = runtime_path(PILOT_AUDIT_NAME), runtime_path(PILOT_AUDIT_TEXT_NAME)
    if not all(path.exists() for path in (gate_path, receipt_path, audit_path, audit_text_path)):
        raise RuntimeError("fresh v1.3 pilot gate not PASS: gate/receipt/audit missing; full extraction prohibited")
    gate, receipt, audit = (json.loads(path.read_text(encoding="utf-8")) for path in (gate_path, receipt_path, audit_path))
    expected = {"contract_version": CONTRACT_VERSION, "gate_definition_version": "1.3", "contract_sha256": freeze["contract_sha256"], "contract_freeze_sha256": freeze["contract_freeze_sha256"], "scope_freeze_sha256": freeze["scope_freeze_sha256"], "pilot_ids_sha256": sha_file(HERE / "pilot_ids_1_3.json"), "pilot_ledger_sha256": pilot_ledger_digest(all_records)}
    if gate.get("state") != "PASS" or gate.get("status") != "PASS" or gate.get("full_run_authorized") is not True or any(gate.get(k) != v for k, v in expected.items()):
        raise RuntimeError("pilot gate not PASS or gate version/hashes differ; full extraction prohibited")
    if any(any(document.get(k) != v for k, v in expected.items()) for document in (receipt, audit)):
        raise RuntimeError("pilot receipt/audit contract version or hashes differ; full extraction prohibited")
    if gate.get("pilot_receipt_sha256") != sha_file(receipt_path) or gate.get("audited_pilot_ledger_sha256") != expected["pilot_ledger_sha256"]:
        raise RuntimeError("pilot receipt/ledger digest differs; full extraction prohibited")
    for name, path in (("audit_sha256", audit_path), ("human_readable_audit_sha256", audit_text_path)):
        if gate.get(name) != sha_file(path) or receipt.get(name) != sha_file(path):
            raise RuntimeError("pilot audit digest differs; full extraction prohibited")
    ids = json.loads((HERE / "pilot_ids_1_3.json").read_text())
    independent = compute_pilot_audit(ids, all_records, freeze, scope)
    saved = {key: value for key, value in audit.items() if key != "generated_utc"}
    if independent != saved or independent["state"] != "PASS":
        raise RuntimeError("pilot independent audit differs or failed; full extraction prohibited")
    if audit_text_path.read_text(encoding="utf-8") != audit_markdown(audit):
        raise RuntimeError("pilot human-readable audit differs from independently audited evidence")
    for key, value in audit.items():
        if receipt.get(key) != value or gate.get(key) != value:
            raise RuntimeError("pilot receipt/gate metrics or census differ from independent audit")
    metrics = receipt.get("machine_gate_criteria", {})
    if set(metrics) != MACHINE_CRITERION_NAMES or any(value is not True for value in metrics.values()) or receipt.get("machine_gate_would_pass") is not True or receipt.get("automatic_grading") is not True:
        raise RuntimeError("pilot machine criteria failed; full extraction prohibited")
    return gate


def finalize(scope: list[dict[str, Any]], freeze: dict[str, Any], all_records: list[dict[str, Any]]) -> dict[str, Any]:
    import pandas as pd
    from validate_notice_fields import validate_label
    current_records(all_records, freeze)
    audit_raw(all_records)
    finals = final_by_key(all_records)
    expected = {notice["notice_key"] for notice in scope}
    if len(expected) != len(scope) or set(finals) != expected:
        raise RuntimeError("finalize requires exactly one terminal state for every scope notice and no extra notice")
    rows = []
    counts_by_period: dict[str, Counter] = {}
    attempts_by_key: dict[str, list[dict[str, Any]]] = {}
    for record in all_records:
        if record.get("event") == "ATTEMPT_RESULT":
            attempts_by_key.setdefault(record["notice_key"], []).append(record)
    for notice in scope:
        terminal = finals.get(notice["notice_key"])
        request_payload(notice)
        if terminal["input_sha256"] != notice["input_sha256"] or terminal["notice_id"] != notice["notice_id"]:
            raise RuntimeError("terminal ledger/source identity or input hash differs")
        state = terminal["status"] if terminal else "PENDING"
        counts_by_period.setdefault(notice["period"], Counter())[state] += 1
        label = terminal.get("parsed_label") if terminal and state == "SUCCESS" else None
        if state == "SUCCESS" and (not terminal.get("raw_sha256") or validate_label(label, notice) or terminal.get("validation_errors") or terminal.get("tool_calls")):
            raise RuntimeError(f"accepted label no longer validates: {notice['notice_key']}")
        own_attempts = attempts_by_key.get(notice["notice_key"], [])
        row = {"notice_key": notice["notice_key"], "notice_id": notice["notice_id"], "period": notice["period"], "scope_group": notice.get("scope_group"), "terminal_state": state, "input_sha256": notice["input_sha256"], **source_lineage(notice), "source_provenance_json": canonical_json(source_lineage(notice)), "clocks_json": canonical_json(notice["clocks"]), "label_json": canonical_json(label) if label is not None else None, "model_requested": MODEL, "model_reasoning_effort": REASONING_EFFORT, "contract_version": CONTRACT_VERSION, "contract_sha256": freeze["contract_sha256"], "contract_freeze_sha256": freeze["contract_freeze_sha256"], "output_sha256": terminal.get("output_sha256") if terminal else None, "terminal_attempt": terminal.get("attempt") if terminal else None, "transport_retries_used": terminal.get("transport_retries_used"), "validation_retries_used": terminal.get("validation_retries_used"), "first_started_utc": min((r["started_utc"] for r in own_attempts), default=None), "last_ended_utc": max((r["ended_utc"] for r in own_attempts), default=None), "wall_seconds_total": sum(r.get("wall_seconds") or 0 for r in own_attempts), "validation_errors_json": canonical_json(terminal.get("validation_errors", [])) if terminal else None}
        if isinstance(label, dict):
            for key, value in label.items():
                if key == "notice_id":
                    continue
                row[key + "_json" if isinstance(value, (dict, list)) else key] = canonical_json(value) if isinstance(value, (dict, list)) else value
        rows.append(row)
    output = runtime_path("labels.parquet")
    temp = output.with_suffix(".parquet.tmp")
    pd.DataFrame(rows).to_parquet(temp, index=False, compression="zstd")
    os.replace(temp, output)
    attempts = [r for r in all_records if r.get("event") == "ATTEMPT_RESULT"]
    totals = Counter(row["terminal_state"] for row in rows)
    usage: Counter = Counter()
    for item in attempts:
        usage.update(item.get("usage", {}))
    receipt = {**base_record(freeze, "finalize"), "state": "COMPLETE" if totals.get("SUCCESS", 0) == len(scope) else "COMPLETE_WITH_FAILURES", "generated_utc": utc_now(), "expected_unique_notices": len(scope), "labels_rows_including_failed_placeholders": len(rows), "terminal_counts": dict(totals), "counts_by_period_and_terminal_state": {k: dict(v) for k, v in sorted(counts_by_period.items())}, "counts_by_scope_group": dict(Counter(n.get("scope_group", "UNKNOWN") for n in scope)), "provider_requests_reserved": sum(r.get("event") == "ATTEMPT_STARTED" for r in all_records), "attempt_receipts": len(attempts), "capacity_incidents": sum(bool(r.get("capacity_error")) for r in attempts), "transport_retries_total": sum(r.get("transport_retries_used", 0) for r in finals.values()), "validation_retries_total": sum(r.get("validation_retries_used", 0) for r in finals.values()), "first_call_utc": min((r["started_utc"] for r in attempts), default=None), "last_call_utc": max((r["ended_utc"] for r in attempts), default=None), "wall_seconds_total": sum(r.get("wall_seconds") or 0 for r in attempts), "worker_changes": [r for r in all_records if r.get("event") == "WORKERS_CHANGED"], "usage_tokens_where_available": dict(usage), "model_ids_exposed": sorted({m for r in attempts for m in r.get("model_ids_exposed", [])}), "cli_path": str(CLI), "cli_version": freeze.get("cli_version"), "temperature": "not exposed/settable in the client", "knowledge_cutoff": "not exposed", "scope_sha256": sha_file(HERE / "scope.jsonl"), "ledger_sha256": sha_file(runtime_path("extraction_ledger.jsonl")) if runtime_path("extraction_ledger.jsonl").exists() else None, "labels_sha256": sha_file(output), "pilot_receipt_sha256": sha_file(runtime_path(PILOT_RECEIPT_NAME)) if runtime_path(PILOT_RECEIPT_NAME).exists() else None, "pilot_gate_sha256": sha_file(runtime_path(PILOT_GATE_NAME)) if runtime_path(PILOT_GATE_NAME).exists() else None, "old_label_banks_read": False, "outcome_rows_read": False, "price_models_fitted": 0}
    atomic_json(runtime_path('EXTRACTION_RECEIPT.json'), receipt)
    return receipt


def run_phase(phase: str, workers: int, scope: list[dict[str, Any]], freeze: dict[str, Any], pilot_ids: list[str]) -> dict[str, Any]:
    history = current_records(records(), freeze)
    known = {n["notice_key"]: n for n in scope}
    if len(known) != len(scope) or len(pilot_ids) != 20 or len(set(pilot_ids)) != 20 or not set(pilot_ids).issubset(known):
        raise RuntimeError("scope/pilot notice keys are invalid")
    if phase == "pilot" and any(r.get("phase") == "full" for r in history):
        raise RuntimeError("pilot cannot run after full extraction begins")
    if phase in {"full", "finalize"}:
        verify_pilot_gate(freeze, history, scope)
    if phase == "finalize":
        return finalize(scope, freeze, history)
    selected = pilot_ids if phase == "pilot" else list(known)
    finals = final_by_key(history)
    for key, rec in finals.items():
        if key in known and rec.get("input_sha256") != known[key]["input_sha256"]:
            raise RuntimeError(f"terminal input differs: {key}")
    audit_raw(history)
    pending = deque(key for key in selected if key not in finals)
    controller = CapacityController(phase, workers, freeze, history)
    append_ledger({**base_record(freeze, phase), "event": "RUN_STARTED", "utc": utc_now(), "pid": os.getpid(), "selected": len(selected), "pending": len(pending), "workers_requested": workers, "workers_effective": controller.limit()})
    print(canonical_json({"phase": phase, "selected": len(selected), "pending": len(pending), "workers": controller.limit()}), flush=True)
    finished_count = 0
    with ThreadPoolExecutor(max_workers=24) as pool:
        futures = {}
        while pending or futures:
            while pending and len(futures) < controller.limit():
                key = pending.popleft()
                futures[pool.submit(call_one, known[key], phase, freeze, history, controller)] = key
            if not futures:
                continue
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                future.result()
                futures.pop(future)
                finished_count += 1
            if finished_count % 25 == 0 or not pending and not futures:
                print(canonical_json({"phase": phase, "finished_this_run": finished_count, "waiting": len(pending), "inflight": len(futures), "workers": controller.limit(), "utc": utc_now()}), flush=True)
    all_records = current_records(records(), freeze)
    if phase == "pilot":
        return pilot_receipt(pilot_ids, all_records, freeze, scope)
    return finalize(scope, freeze, all_records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("pilot", "full", "finalize"), required=True)
    parser.add_argument("--workers", type=int, default=16, help="1..24; full starting at 16 automatically steps to 24 after first 200 capacity-free requests")
    args = parser.parse_args()
    if not 1 <= args.workers <= 24:
        parser.error("workers must be between 1 and 24")
    signal.signal(signal.SIGINT, cancel_active)
    signal.signal(signal.SIGTERM, cancel_active)
    with exclusive_run():
        freeze = verify_freeze()
        from prepare_notice_scope import load_scope
        scope = load_scope(verify_sources=True)
        pilot_ids = json.loads((HERE / "pilot_ids_1_3.json").read_text(encoding="utf-8"))
        result = run_phase(args.phase, args.workers, scope, freeze, pilot_ids)
        print(canonical_json(result), flush=True)


if __name__ == "__main__":
    main()
