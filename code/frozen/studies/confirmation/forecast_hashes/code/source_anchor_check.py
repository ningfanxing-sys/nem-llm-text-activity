
'Compare notice counts and source hashes with the extraction inputs.'
from __future__ import annotations

import os
for _thread_env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_thread_env] = "1"

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import resource
import subprocess
import sys
import time
import warnings
from datetime import datetime

sys.dont_write_bytecode = True

OUT = Path(__file__).resolve().parents[1]
PROJ = OUT.parents[3]
AD = OUT.parent / "ANCHORDIAG"
SCOPE = PROJ / 'studies/notice_extraction/scope.jsonl'
ISO_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
SCRATCH_LIMIT_BYTES = 1024 ** 3
EXPECTED_REFERENCE = "pd.Timestamp(datetime.strptime(' '.join(raw.split()), '%d/%m/%Y %H:%M:%S'))"


def _hash_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _memory_sample(start):
    if sys.platform == "darwin":
        result = subprocess.run(["/usr/bin/memory_pressure", "-Q"], check=True,
                                capture_output=True, text=True)
        match = re.search(r"free percentage:\s*(\d+)%", result.stdout)
        if match is None:
            raise RuntimeError("Cannot verify 25% memory floor")
        percent = int(match.group(1))
    else:
        fields = {row.split(":")[0]: int(row.split()[1])
                  for row in Path("/proc/meminfo").read_text().splitlines()
                  if row.startswith(("MemTotal:", "MemAvailable:"))}
        percent = 100 * fields["MemAvailable"] // fields["MemTotal"]
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != "darwin":
        peak *= 1024
    if percent < 25:
        raise MemoryError("Source check stopped: free memory below 25%")
    if peak >= SCRATCH_LIMIT_BYTES:
        raise MemoryError("Source check stopped: process RSS reaches 1 GiB")
    return {"elapsed_seconds": round(time.monotonic() - start, 3),
            "free_percent": percent, "peak_rss_bytes": peak}


def _ad_reference(diagnose_path, pandas_module):

    source = Path(diagnose_path).read_text()
    tree = ast.parse(source)
    expected = ast.parse(EXPECTED_REFERENCE, mode="eval").body
    wanted = ast.dump(expected, include_attributes=False)
    matches = [node for node in ast.walk(tree)
               if isinstance(node, ast.Call) and
               ast.dump(node, include_attributes=False) == wanted]
    if len(matches) != 1:
        raise ValueError("AD correction expression drift or unexpected cardinality")
    expression = ast.Expression(body=matches[0])
    code = compile(expression, str(diagnose_path), "eval")
    def reference(raw):


        return eval(code, {"__builtins__": {"__import__": __import__}, "pd": pandas_module, "datetime": datetime}, {"raw": raw})
    return reference, hashlib.sha256(wanted.encode()).hexdigest()


def run_check(scope_path=SCOPE, diagnose_path=AD / "diagnose.py",
              notice_diff_path=AD / "NOTICE_DIFF.json", *, check_resources=True):

    scope_path = Path(scope_path).resolve()
    real_source = scope_path == SCOPE.resolve()
    if real_source and not check_resources:
        raise ValueError("Real source requires resource checks")
    if check_resources and os.getpriority(os.PRIO_PROCESS, 0) != 20:
        raise RuntimeError("Source check requires nice 20")
    start = time.monotonic()
    memory = [_memory_sample(start)] if check_resources else []

    from anchor_patch import parse_anchor, loader_anchor, STRICT_ANCHOR
    import pandas as pd
    if check_resources:
        memory.append(_memory_sample(start))
    reference, reference_hash = _ad_reference(diagnose_path, pd)
    diff = json.loads(Path(notice_diff_path).read_text())
    expected = diff["population"]
    source_identity = next(i for i in diff["inputs"] if Path(i["path"]).resolve() == scope_path)
    digest = hashlib.sha256()
    total = strict = iso = corrected_equal = iso_equal = bridge_equal = changed = 0
    with scope_path.open("rb") as stream, warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Parsing dates in.*")
        for raw_line in stream:
            digest.update(raw_line)
            source = json.loads(raw_line)
            raw = source["clocks"]["raw_time_local"]
            total += 1
            patched = parse_anchor(raw)
            bridge = loader_anchor(raw)
            if isinstance(raw, str) and STRICT_ANCHOR.fullmatch(raw):
                strict += 1
                ad_corrected = reference(raw)
                corrected_equal += patched == ad_corrected
                bridge_equal += bridge == ad_corrected
                changed += pd.Timestamp(raw) != patched
            else:
                if not isinstance(raw, str) or ISO_PATTERN.fullmatch(raw) is None:
                    raise ValueError("Source census contains an unregistered clock shape")
                iso += 1
                frozen = pd.Timestamp(raw)
                iso_equal += patched == frozen
                bridge_equal += bridge is raw
            if check_resources and total % 1024 == 0:
                memory.append(_memory_sample(start))
    actual_hash = digest.hexdigest()
    checks = {
        "scope_sha256_matches_AD": actual_hash == source_identity["sha256"],
        "scope_bytes_matches_AD": scope_path.stat().st_size == source_identity["bytes"],
        "total_matches_AD": total == expected["scope_notices"],
        "strict_count_matches_AD": strict == expected["DDMM_notices"],
        "ISO_count_matches_AD": iso == expected["ISO_notices"],
        "anchor_change_count_matches_AD": changed == expected["anchor_differences"],
        "every_strict_anchor_equals_AD": corrected_equal == strict,
        "every_ISO_anchor_equals_frozen": iso_equal == iso,
        "every_loader_bridge_matches_or_preserves_identity": bridge_equal == total,
    }
    if not all(checks.values()):
        raise ValueError("Source anchor check failed: " + ", ".join(k for k, v in checks.items() if not v))
    if real_source and (strict != 796 or iso != 20674 or total != 21470):
        raise ValueError("Bound source census count drift")
    if check_resources:
        memory.append(_memory_sample(start))
    return {
        "state": "PASS_SOURCE_ONLY_ANCHOR_PARITY",
        "counts": {"scope_notices": total, "strict_DDMM_notices": strict,
                   "strict_anchors_equal_AD": corrected_equal, "changed_anchors": changed,
                   "ISO_notices": iso, "ISO_equal_frozen": iso_equal,
                   "loader_bridge_equal_or_identical": bridge_equal},
        "checks": checks,
        "inputs": [{"path": str(scope_path), "sha256": actual_hash,
                    "bytes": scope_path.stat().st_size},
                   {"path": str(Path(diagnose_path).resolve()), "sha256": _hash_file(diagnose_path)},
                   {"path": str(Path(notice_diff_path).resolve()), "sha256": _hash_file(notice_diff_path)}],
        "AD_corrected_expression_ast_sha256": reference_hash,
        "values_printed": False,
        "scope_only_no_labels": True,
        "host_state_seals_models_predictions_scores_prices_opened": False,
        "resource_checks_enabled": check_resources,
        "memory_checks": memory,
        "runtime_seconds": round(time.monotonic() - start, 3),
        "scratch_bytes_written": 0,
        "worker_processes": 1,
    }


def _install_read_audit():

    allowed = {SCOPE.resolve(), (AD / "diagnose.py").resolve(),
               (AD / "NOTICE_DIFF.json").resolve()}
    def audit(event, args):
        if event != "open" or not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        path = Path(os.fsdecode(args[0])).resolve()
        mode, flags = args[1], args[2]
        writing = ((isinstance(mode, str) and any(c in mode for c in "wax+")) or
                   bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)))
        if writing:
            if not (path.is_relative_to(OUT) or path.is_relative_to(Path("/private/tmp"))):
                raise PermissionError("Source check write outside authorized output")
        elif path.is_relative_to(PROJ) and path not in allowed and not path.is_relative_to(OUT / "code"):
            raise PermissionError("Source check project read outside the source-only allowlist")
    sys.addaudithook(audit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not (output.is_relative_to(OUT) or output.is_relative_to(Path("/private/tmp"))):
        raise ValueError("Source receipt must stay in OUT or /private/tmp")
    _install_read_audit()
    receipt = run_check()
    text = json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if len(text.encode()) >= SCRATCH_LIMIT_BYTES:
        raise ValueError("Source check receipt exceeds scratch budget")
    with output.open("x") as stream:
        stream.write(text)
    print(json.dumps({"state": receipt["state"], "counts": receipt["counts"],
                      "checks": receipt["checks"]}, sort_keys=True))


if __name__ == "__main__":
    main()
