"""Content-free design inventory and later isolated NEWSX-v4 host adapter.

inventory: allowed now; reads only old manifest and DATA26 inventory, hashes raw
bytes without decoding them. prepare/extract: a separate news-extraction task
receipt is mandatory; neither action can run in CONF's design task.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

CONF = Path(__file__).resolve().parents[1]
PROJ = CONF.parents[2]
NEWSX = PROJ / "autopilot/q1_audits/NEWSX"
DATA = PROJ / "autopilot/q1_audits/DATA26/wattclarity"


def _audit():
    sys.path.insert(0, str(CONF))
    from audit_io import record, read_text, sha256
    return record, read_text, sha256


def _write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def inventory(output):
    record, read, digest = _audit()
    data = json.loads(read(DATA / "INVENTORY.json", "news keys/counts only"))
    old = list(csv.DictReader(read(NEWSX / "article_manifest.csv", "old prewindow news manifest").splitlines()))
    keep = ("article_id", "publication_local_date", "publication_utc", "modified_utc",
            "saved_version_available_utc", "article_text_sha256", "article_text_chars")
    existing = [{key: row[key] for key in keep} for row in old]
    current = [{"article_id": ident, "publication_month": month["month"],
                "normalization_state": "PENDING_POST_FREEZE_SOURCE_ONLY_NORMALIZATION"}
               for month in data["months"] for ident in month["ids"]]
    if len(current) != 286 or len({x["article_id"] for x in current}) != 286:
        raise ValueError("DATA26 registered 286-ID batch has drifted")
    raw_files = []
    for page in data["pagination"]:
        path = Path(page["raw_path"])
        raw_files.append({"path": str(path), "sha256": digest(path),
                          "page": page["page"], "rows": page["post_count"]})
    frozen_contract = {}
    for name in ("CONTRACT_V4.md", "prepare_newsx.py", "run_extraction.py", "prompt.txt",
                 "schema.json", "validate_label.py", "LABEL_FREEZE.json", "PILOT_GATE.json"):
        path = NEWSX / name
        frozen_contract[name] = {"path": str(path), "sha256": digest(path)}
    result = {"state": "DESIGN_METADATA_ONLY_NO_SOURCE_BODY_DECODE",
        "inventory_path": str(DATA / "INVENTORY.json"), "inventory_sha256": digest(DATA / "INVENTORY.json"),
        "existing_manifest_path": str(NEWSX / "article_manifest.csv"),
        "existing_manifest_sha256": digest(NEWSX / "article_manifest.csv"),
        "existing_articles": existing, "data26_batch": current, "data26_batch_count": len(current),
        "batch_includes_all_prewindow_articles": True,
        "prewindow_rule": "All DATA26 February articles run with March–September; do not filter by confirmation window",
        "old_labels_rule": "Old NEWSX training labels reused unchanged; do not reextract 2244 old articles",
        "cross_version_rule": "Any same-ID normalization hash or publication/modified clock conflict stops before model calls; no silent replacement",
        "source_raw_files": raw_files, "frozen_newsx_v4": frozen_contract,
        "pending": ["new perarticle literal clocks and normalized source text hashes",
                    "source-only normalization/cross-version check in later authorized task",
                    "NEWSX extension extraction receipt and labels"]}
    _write(output, result)
    return result


def _authorization(path, state):
    record, read, digest = _audit()
    receipt = json.loads(read(path, "separate host news extraction authorization"))
    if receipt.get("state") != state or receipt.get("task_id") in (None, "", "CONF"):
        raise PermissionError("A separate NEWS extraction task is required")
    if receipt.get("design_freeze_sha256") != digest(CONF / "FREEZE.json"):
        raise PermissionError("CONF freeze does not match authorization receipt")
    return receipt


def _contract(manifest):
    record, read, digest = _audit()
    for name, expected in manifest["frozen_newsx_v4"].items():
        if digest(expected["path"]) != expected["sha256"]:
            raise ValueError("NEWSX contract/input drift: " + name)
    return record, read, digest


def _import_newsx(manifest):
    record, _, _ = _contract(manifest)
    # Original prompt/schema/validator/runner are reused with no label semantics change.
    # Neither module's main function is called. Their imports perform no raw reads.
    sys.path.insert(0, str(NEWSX))
    sys.dont_write_bytecode = True  # do not write caches into the immutable NEWSX directory
    for name in ("prepare_newsx.py", "validate_label.py", "run_extraction.py"):
        record(NEWSX / name, "code_read", "reuse immutable NEWSX v4 code")
    spec = importlib.util.spec_from_file_location("_conf_newsx_v4", NEWSX / "run_extraction.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(manifest_path, output, authorization):
    _authorization(authorization, "SEPARATE_NEWS_EXTRACTION_TASK_AUTHORIZED")
    record, read, digest = _audit()
    manifest = json.loads(read(manifest_path, "metadata-only registered news source scope"))
    _contract(manifest)
    # Hash every raw input before decoding even news values, then freeze exact hashes.
    for source in manifest["source_raw_files"]:
        if digest(source["path"]) != source["sha256"]:
            raise ValueError("DATA26 raw page drift")
    runner = _import_newsx(manifest)
    old = {x["article_id"]: x for x in manifest["existing_articles"]}
    posts, rows, conflicts = {}, [], []
    for source in manifest["source_raw_files"]:
        for post in json.loads(read(source["path"], "post-freeze source-only news normalization")):
            ident = str(post["id"])
            if ident not in {x["article_id"] for x in manifest["data26_batch"]}:
                continue
            if ident in posts:
                raise ValueError("duplicate DATA26 article ID")
            prep = sys.modules["prepare_newsx"]
            meta = prep.manifest_row(ident, post, "DATA26")
            prior = old.get(ident)
            if prior and any(str(meta[key]) != str(prior[key]) for key in
                             ("article_text_sha256", "publication_utc", "modified_utc", "saved_version_available_utc")):
                conflicts.append({"article_id": ident, "fields": [key for key in
                    ("article_text_sha256", "publication_utc", "modified_utc", "saved_version_available_utc")
                    if str(meta[key]) != str(prior[key])]})
            # No raw article, evidence quote, price figure, or claim is displayed.
            posts[ident] = post
            rows.append(meta)
    output = Path(output).resolve()
    if not output.is_relative_to(CONF.resolve()) or output == NEWSX:
        raise PermissionError("extension output must be isolated under CONF")
    output.mkdir(parents=True, exist_ok=True)
    if conflicts:
        _write(output / "VERSION_CONFLICTS.json", {"state": "STOP_BEFORE_MODEL_CALLS", "conflicts": conflicts})
        raise ValueError("same-ID saved-version conflicts require source adjudication; no extraction started")
    if len(rows) != 286:
        raise ValueError("all 286 documents, including prewindow, must be in the same batch")
    rows.sort(key=lambda x: (x["publication_local_date"], x["article_id"]))
    with (output / "article_manifest.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    # Source-only cache is an intermediate for later extraction, not a feature matrix.
    _write(output / "source_posts.json", posts)
    for name in ("prompt.txt", "schema.json", "PILOT_GATE.json"):
        record(NEWSX / name, "copy_read", "unchanged v4 extension contract")
        shutil.copyfile(NEWSX / name, output / name)
    base = json.loads(read(NEWSX / "LABEL_FREEZE.json", "v4 runtime identity"))
    gate = json.loads(read(NEWSX / "PILOT_GATE.json", "inherited unchanged v4 gate"))
    if gate["state"] != "PASS" or gate["contract_version"] != 4:
        raise ValueError("NEWSX v4 pilot gate is not PASS")
    freeze = {"state": "NEWSX_V4_EXTENSION_SOURCE_ONLY_INPUTS_FROZEN_BEFORE_CALLS",
        "model_requested": "gpt-6-luna", "model_reasoning_effort": "medium", "contract_version": 4,
        "cli_version": base["cli_version"], "cli_version_provenance": base["cli_version_provenance"],
        "scope_freeze_sha256": digest(manifest_path), "scope_manifest": str(Path(manifest_path).resolve()),
        "inherited_v4_pilot_gate_sha256": digest(NEWSX / "PILOT_GATE.json"),
        "prompt_schema_validator_unchanged": True,
        "design_freeze_sha256": digest(CONF / "FREEZE.json"),
        "files_sha256": {name: digest(output / name) for name in
                         ("article_manifest.csv", "source_posts.json", "prompt.txt", "schema.json", "PILOT_GATE.json")},
        "frozen_newsx_v4": manifest["frozen_newsx_v4"],
        "source_sha256": {x["path"]: x["sha256"] for x in manifest["source_raw_files"]},
        "article_count": len(rows), "feature_builds": 0, "model_calls": 0}
    _write(output / "LABEL_FREEZE.json", freeze)
    return {"state": freeze["state"], "article_count": len(rows), "model_calls": 0}


def extract(manifest_path, output, authorization, workers):
    _authorization(authorization, "SEPARATE_NEWS_EXTRACTION_TASK_AUTHORIZED")
    if not 1 <= workers <= 8:
        raise ValueError("frozen NEWSX 4.2 range is 1..8 workers")
    record, read, digest = _audit()
    manifest = json.loads(read(manifest_path, "registered news source scope"))
    runner = _import_newsx(manifest)
    output = Path(output).resolve()
    if not output.is_relative_to(CONF.resolve()) or output == NEWSX:
        raise PermissionError("isolated extension output required")
    freeze = json.loads(read(output / "LABEL_FREEZE.json", "extension input freeze"))
    if freeze["design_freeze_sha256"] != digest(CONF / "FREEZE.json"):
        raise ValueError("design freeze drift")
    for name, expected in freeze["files_sha256"].items():
        if digest(output / name) != expected:
            raise ValueError("normalized source or contract drift")
    posts = json.loads(read(output / "source_posts.json", "authorized source-only extraction"))
    rows = list(csv.DictReader(read(output / "article_manifest.csv", "frozen normalized metadata").splitlines()))
    if len(rows) != 286 or set(posts) != {x["article_id"] for x in rows}:
        raise ValueError("batch/manifest IDs differ")
    for name, val in {"HERE": output, "LEDGER": output / "extraction_ledger.jsonl",
        "RAW": output / "raw", "LABELS": output / "labels.parquet",
        "FREEZE": output / "LABEL_FREEZE.json"}.items():
        setattr(runner, name, val)
    # These original functions read/write only redirected output and frozen source.
    record(output / "extraction_ledger.jsonl", "read_if_exists", "resume terminal extraction states")
    prior = runner.records(); latest = runner.final_by_id(runner.contract_records(prior))
    attempts = {r["article_id"]: max(x["attempt"] for x in prior if x["article_id"] == r["article_id"]) for r in prior}
    pending = [x for x in rows if x["article_id"] not in latest]
    # Terminal failures are retained; do not re-prompt them to improve later results.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = [pool.submit(runner.call_one, row["article_id"], row, posts[row["article_id"]],
                            "full", attempts.get(row["article_id"], 0)) for row in pending]
        for job in as_completed(jobs):
            job.result()
    return runner.finalize(rows, freeze)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("inventory", "prepare", "extract"), required=True)
    parser.add_argument("--manifest", type=Path, default=CONF / "NEWS_EXTENSION_MANIFEST.json")
    parser.add_argument("--output", type=Path, default=CONF / "newsx_extension")
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.mode == "inventory":
        result = inventory(args.manifest)
        print(json.dumps({"state": result["state"], "data26_batch_count": result["data26_batch_count"]}))
    else:
        if args.authorization is None:
            parser.error("a later task authorization receipt is mandatory")
        fn = prepare if args.mode == "prepare" else extract
        kwargs = {"workers": args.workers} if args.mode == "extract" else {}
        result = fn(args.manifest, args.output, args.authorization, **kwargs)
        print(json.dumps({k: result[k] for k in ("state", "article_count", "expected_unique_articles", "successful", "failures") if k in result}))


if __name__ == "__main__":
    main()
