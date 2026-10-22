'Extract notice labels using the saved prompt and schema.'
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
CONTRACT_VERSION = "1.1"
RUNTIME_DIRECTORY = "results_1_1"
PILOT_RECEIPT_NAME = "PILOT_RECEIPT_1_1.json"
PILOT_GATE_NAME = "PILOT_GATE_1_1.json"


def runtime_path(name: str) -> Path:

    return HERE / RUNTIME_DIRECTORY / name


def raw_receipt_path(relative: str) -> Path:
    path = (HERE / relative).resolve()
    if not path.is_relative_to(runtime_path("raw").resolve()):
        raise RuntimeError("raw receipt is outside contract v1.1 runtime; v1 reuse prohibited")
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
    path = HERE / "CONTRACT_FREEZE_1_1.json"
    freeze = json.loads(path.read_text(encoding="utf-8"))
    if freeze.get("contract_version") != CONTRACT_VERSION or freeze.get("runtime_directory") != RUNTIME_DIRECTORY:
        raise RuntimeError("contract freeze is not version 1.1 with isolated runtime")
    if (freeze.get("transport_retries_total_per_notice"), freeze.get("validation_retries_total_per_notice"), freeze.get("maximum_requests_per_notice")) != (MAX_TRANSPORT_RETRIES, MAX_VALIDATION_RETRIES, 1 + MAX_TRANSPORT_RETRIES + MAX_VALIDATION_RETRIES):
        raise RuntimeError("frozen retry budgets differ from the unchanged v1 budgets")
    if freeze.get("model_requested") != MODEL or freeze.get("model_reasoning_effort") != REASONING_EFFORT:
        raise RuntimeError("requested model or effort differs from contract freeze")
    if freeze.get("cli_path") != str(CLI):
        raise RuntimeError("CLI path differs from contract freeze")
    if freeze.get("cli_sha256") and sha_file(CLI) != freeze["cli_sha256"]:
        raise RuntimeError("CLI binary differs from frozen version; freeze a new contract before extraction")
    if freeze.get("contract_sha256") != sha_file(HERE / 'CONTRACT_SPECIFICATION_1_1.md'):
        raise RuntimeError('contract specification text differs from freeze')
    if freeze.get("base_contract_sha256") != sha_file(HERE / "CONTRACT.md"):
        raise RuntimeError("immutable base contract text differs from freeze")
    required = {"CONTRACT.md", 'CONTRACT_SPECIFICATION_1_1.md', "prompt.txt", "schema_full.json", "schema_response_format.json", "run_notice_extraction.py", 'validate_notice_fields.py', "prepare_notice_scope.py", "scope.jsonl", "pilot_ids_1_1.json", "SCOPE_RECEIPT.json", "CONTRACT_FREEZE.json", "archive_v1/run_notice_extraction.py"}
    declared = freeze.get("files_sha256", {})
    if not required.issubset(declared):
        raise RuntimeError(f"freeze missing required files: {sorted(required - set(declared))}")
    for name, expected in declared.items():
        file_path = (HERE / name).resolve()
        if not file_path.is_relative_to(HERE.resolve()):
            raise RuntimeError(f"freeze file outside notice_extraction: {name}")
        if sha_file(file_path) != expected:
            raise RuntimeError(f"contract freeze mismatch: {name}")
    base_freeze = json.loads((HERE / "CONTRACT_FREEZE.json").read_text(encoding="utf-8"))
    for name in ("prompt.txt", "schema_full.json", "schema_response_format.json"):
        if declared[name] != base_freeze["files_sha256"][name]:
            raise RuntimeError(f"v1 frozen prompt/schema is not byte-identical: {name}")
    if declared["archive_v1/run_notice_extraction.py"] != base_freeze["files_sha256"]["run_notice_extraction.py"]:
        raise RuntimeError("archived v1 runner is not byte-identical to v1 freeze")
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
        raise RuntimeError("ledger contains foreign contract or v1 records; v1 reuse prohibited")
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
            raise RuntimeError("raw receipt ledger version differs from v1.1; v1 reuse prohibited")
        path = raw_receipt_path(record["raw_path"])
        if sha_file(path) != record["raw_sha256"]:
            raise RuntimeError(f"raw receipt missing or changed: {record.get('notice_key')} attempt {record.get('attempt')}")
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            raw = json.load(fh)
        if any(raw.get(key) != record.get(key) for key in ("contract_version", "contract_sha256", "contract_freeze_sha256", "scope_freeze_sha256", "notice_key", "notice_id", "attempt", "request_index")):
            raise RuntimeError("raw receipt identity differs from contract v1.1 ledger")
        if sha_bytes(raw.get("response", "").encode()) != record.get("output_sha256") or sha_bytes(raw.get("prompt", "").encode()) != record.get("prompt_sha256") or sha_bytes(canonical_json(raw.get("input")).encode()) != record.get("input_sha256"):
            raise RuntimeError("raw input/prompt/output hashes differ from ledger")
        if raw.get("parsed_label") != record.get("parsed_label"):
            raise RuntimeError("raw parsed output differs from ledger")


def pilot_receipt(pilot_ids: list[str], all_records: list[dict[str, Any]], freeze: dict[str, Any]) -> dict[str, Any]:
    subset = [r for r in all_records if r.get("phase") == "pilot"]
    attempts = [r for r in subset if r.get("event") == "ATTEMPT_RESULT"]
    finals = final_by_key(subset)
    errors = [e for r in attempts for e in r.get("validation_errors", [])]
    spans = [e for e in errors if e.get("code") == "FABRICATED_SPAN"]
    structural_codes = {"SCHEMA", "EMPTY_WINDOW_ID", "DUPLICATE_WINDOW_ID", "WINDOW_ID_SEQUENCE", "BOUNDED_ENDPOINT_MISSING", "OPEN_INTERVAL_HAS_END", "ATTRIBUTE_REGION_CONFLICT", "BINDING_REASON_MISMATCH", "BAD_WINDOW_REFERENCE", "BOUND_ASSET_CONFLICT", "UNBOUND_HAS_WINDOW"}
    structural = [e for e in errors if e.get("code") in structural_codes]
    contamination = [e for e in errors if any(token in e.get("code", "") for token in ("OTHER_NOTICE", "OTHER_DATE", "CONTAMINATION", "UNSUPPORTED_DATE", "FOREIGN_"))]
    successful = sum(finals.get(key, {}).get("status") == "SUCCESS" for key in pilot_ids)
    metrics = {"valid_after_at_most_one_validation_retry": successful >= 18, "all_20_terminal": len(finals) == 20 and set(finals) == set(pilot_ids), "zero_fabricated_spans_all_attempts": not spans, "all_window_quantity_bindings_valid_all_attempts": not structural, "no_other_notice_or_unsupported_date_all_attempts": not contamination, "one_notice_per_request": all(r.get("notices_in_request") == 1 and r.get("notice_key") in pilot_ids for r in subset if r.get("event") == "ATTEMPT_STARTED"), "zero_tool_calls_all_attempts": all(not r.get("tool_calls") for r in attempts), "retry_budgets_respected": all(r.get("transport_retries_used", 0) <= MAX_TRANSPORT_RETRIES and r.get("validation_retries_used", 0) <= MAX_VALIDATION_RETRIES and r.get("attempt", 0) <= 5 for r in attempts)}
    receipt = {**base_record(freeze, "pilot"), "state": "PENDING_REVIEW", "generated_utc": utc_now(), "pilot_ids_sha256": sha_file(HERE / "pilot_ids_1_1.json"), "pilot_ledger_sha256": pilot_ledger_digest(all_records), "pilot_notices": len(pilot_ids), "terminal_counts": dict(Counter(r["status"] for r in finals.values())), "valid_final_outputs": successful, "provider_requests_reserved": sum(r.get("event") == "ATTEMPT_STARTED" for r in subset), "completed_attempt_receipts": len(attempts), "fabricated_span_errors": spans, "window_binding_errors": structural, "contamination_errors": contamination, "machine_gate_criteria": metrics, "machine_gate_would_pass": all(metrics.values()), "follow_up_required": "Grade only the fresh v1.1 pilot outputs and sign results_1_1/PILOT_GATE_1_1.json; runner never assigns PASS."}
    atomic_json(runtime_path(PILOT_RECEIPT_NAME), receipt)
    gate_path = runtime_path(PILOT_GATE_NAME)
    if not gate_path.exists():
        atomic_json(gate_path, {**base_record(freeze, "pilot"), "state": "PENDING_REVIEW", "pilot_ids_sha256": receipt["pilot_ids_sha256"], "pilot_ledger_sha256": receipt["pilot_ledger_sha256"], "pilot_receipt_sha256": sha_file(runtime_path(PILOT_RECEIPT_NAME)), "machine_gate_criteria": metrics, "valid_final_outputs": successful, "follow_up_required": receipt["follow_up_required"]})
    return receipt


def verify_pilot_gate(freeze: dict[str, Any], all_records: list[dict[str, Any]]) -> dict[str, Any]:
    current_records(all_records, freeze)
    gate_path = runtime_path(PILOT_GATE_NAME)
    receipt_path = runtime_path(PILOT_RECEIPT_NAME)
    if not gate_path.exists() or not receipt_path.exists():
        raise RuntimeError("fresh v1.1 pilot gate not PASS: gate/receipt missing; full extraction prohibited")
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    expected = {"contract_version": CONTRACT_VERSION, "contract_sha256": freeze["contract_sha256"], "contract_freeze_sha256": freeze["contract_freeze_sha256"], "scope_freeze_sha256": freeze["scope_freeze_sha256"], "pilot_ids_sha256": sha_file(HERE / "pilot_ids_1_1.json"), "pilot_receipt_sha256": sha_file(receipt_path), "pilot_ledger_sha256": pilot_ledger_digest(all_records)}
    if gate.get("state") != "PASS" or any(gate.get(k) != v for k, v in expected.items()):
        raise RuntimeError("pilot gate not PASS or gate hashes differ; full extraction prohibited")
    if any(receipt.get(k) != v for k, v in expected.items() if k != "pilot_receipt_sha256"):
        raise RuntimeError("pilot receipt contract version or hashes differ; full extraction prohibited")
    criterion_names = {"valid_after_at_most_one_validation_retry", "all_20_terminal", "zero_fabricated_spans_all_attempts", "all_window_quantity_bindings_valid_all_attempts", "no_other_notice_or_unsupported_date_all_attempts", "one_notice_per_request", "zero_tool_calls_all_attempts", "retry_budgets_respected"}
    metrics = receipt.get("machine_gate_criteria", {})
    if set(metrics) != criterion_names or any(value is not True for value in metrics.values()) or receipt.get("machine_gate_would_pass") is not True or receipt.get("valid_final_outputs", 0) < 18:
        raise RuntimeError("pilot machine criteria failed; full extraction prohibited")
    if any(gate.get(k) != v for k, v in {"machine_gate_criteria": receipt["machine_gate_criteria"], "valid_final_outputs": receipt["valid_final_outputs"]}.items()):
        raise RuntimeError("pilot gate metrics do not match receipt")
    audit_raw([r for r in all_records if r.get("phase") == "pilot"])
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
    atomic_json(runtime_path("EXTRACTION_RECEIPT_1_1.json"), receipt)
    return receipt


def run_phase(phase: str, workers: int, scope: list[dict[str, Any]], freeze: dict[str, Any], pilot_ids: list[str]) -> dict[str, Any]:
    history = current_records(records(), freeze)
    known = {n["notice_key"]: n for n in scope}
    if len(known) != len(scope) or len(pilot_ids) != 20 or len(set(pilot_ids)) != 20 or not set(pilot_ids).issubset(known):
        raise RuntimeError("scope/pilot notice keys are invalid")
    if phase == "pilot" and any(r.get("phase") == "full" for r in history):
        raise RuntimeError("pilot cannot run after full extraction begins")
    if phase in {"full", "finalize"}:
        verify_pilot_gate(freeze, history)
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
        return pilot_receipt(pilot_ids, all_records, freeze)
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
        pilot_ids = json.loads((HERE / "pilot_ids_1_1.json").read_text(encoding="utf-8"))
        result = run_phase(args.phase, args.workers, scope, freeze, pilot_ids)
        print(canonical_json(result), flush=True)


if __name__ == "__main__":
    main()
