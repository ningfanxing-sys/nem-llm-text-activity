'Run the window-schema tests without extraction requests.'
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
COMPONENTS = {
    "1.0": ("archive_v1/run_notice_extraction.py", ("test_run_notice_extraction", "test_validate_notice_label")),
    "1.1": ('archive_label_specification/run_notice_extraction.py', ("test_run_notice_extraction_1_1", 'test_validate_notice_fields')),
    "1.2": ("run_notice_extraction.py", ("test_run_notice_extraction_1_2", "test_prompt_assembly_1_2",
                                        "test_prepare_notice_scope", 'test_prepare_window_sample')),
}


def child(version: str) -> int:
    path, modules = COMPONENTS[version]
    spec = importlib.util.spec_from_file_location("run_notice_extraction", HERE / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_notice_extraction"] = module
    spec.loader.exec_module(module)
    module.HERE = HERE
    suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
    counts = Counter()

    def walk(node):
        if isinstance(node, unittest.TestSuite):
            for item in node:
                walk(item)
        else:
            counts[node.__class__.__module__ + ".py"] += 1
    walk(suite)


    with patch.object(module, "invoke", side_effect=AssertionError("provider invocation blocked by test driver")), \
         patch("subprocess.Popen", side_effect=AssertionError("provider process spawn blocked by test driver")):
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({"component_version": version, "tests_run": result.testsRun, "failures": len(result.failures),
                      "errors": len(result.errors), "tests_by_component": dict(counts), "model_calls": 0,
                      "provider_process_spawn_blocked": True, "state": "PASS" if result.wasSuccessful() else "FAIL"}))
    return 0 if result.wasSuccessful() else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=COMPONENTS)
    args = parser.parse_args()
    if args.component:
        raise SystemExit(child(args.component))
    results, logs = [], []
    for version in COMPONENTS:
        process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--component", version],
                                 capture_output=True, text=True, check=False)
        logs.append(f"notice_extraction contract {version}\n" + process.stderr + process.stdout)
        try:
            result = json.loads(process.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            result = {"state": "FAIL", "errors": 1, "failures": 0, "tests_run": 0,
                      "tests_by_component": {}, "component_version": version, "driver_error": process.stderr[-4000:]}
        result["process_exit_code"] = process.returncode
        results.append(result)
    log = HERE / "BUILD_TEST_1_2.log"
    log.write_text("\n".join(logs), encoding="utf-8")
    summary = {"state": "PASS" if all(r["state"] == "PASS" and r["process_exit_code"] == 0 for r in results) else "FAIL",
               "tests_run": sum(r["tests_run"] for r in results), "failures": sum(r["failures"] for r in results),
               "errors": sum(r["errors"] for r in results), "versions": results,
               "tests_by_component": {k: v for r in results for k, v in r["tests_by_component"].items()},
               "model_calls": 0, "provider_process_spawn_blocked": True,
               "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
    (HERE / "TEST_RESULTS_1_2.json").write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n")
    print(json.dumps(summary))
    if summary["state"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
