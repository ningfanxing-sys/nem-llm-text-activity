
'Read checked sensitivity losses and compute the reported comparisons.'
from __future__ import annotations

import argparse
import ast
import csv
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import ModuleType

import numpy as np

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]
SEEDS = (20260919, 20260920, 20260921)
SERIES = tuple(f"seed_{s}" for s in SEEDS) + ("three_seed_mean_prediction",)
MEAN_DEFINITION = "daily loss of the mean prediction; not mean arm loss"


class Refusal(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Refusal(message)


def day_range(first, last):
    start, end = date.fromisoformat(first), date.fromisoformat(last)
    return [(start + timedelta(days=i)).isoformat() for i in range((end-start).days+1)]


TASKS = {
    "news": dict(days=day_range("2026-05-19", "2026-09-30"),
                 exposed=day_range("2026-07-01", "2026-07-24")+day_range("2026-09-01", "2026-09-11"),
                 pairs=(("L_count", "M"), ("L_chen", "M")), keys_per_day=72),
    "notice": dict(days=day_range("2026-08-01", "2026-09-30"),
                   exposed=day_range("2026-09-01", "2026-09-11"),
                   pairs=(("L14", "M_notice"), ("L_Laz", "M_notice"), ("L_chen_notice", "M_notice")),
                   keys_per_day=8640),
}
for config in TASKS.values():
    config["U"] = [d for d in config["days"] if d not in set(config["exposed"])]
    config["arms"] = tuple(dict.fromkeys(a for pair in config["pairs"] for a in pair))
    config["unknown_in_U"] = [d for d in config["U"] if "2026-07-25" <= d <= "2026-09-23"]
DAYS, EXPOSED, U = (TASKS["news"][k] for k in ("days", "exposed", "U"))
FAMILY, ARMS = (TASKS["news"][k] for k in ("pairs", "arms"))
HAC_CONVENTION = "SENS35_PRESPECIFIED_RETAINED_OBSERVATION_HAC7"
HAC_LIMIT = "Not calendar 7-day HAC; nominal finite-sample size or conservativeness is not established."


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def strict_json_data(data):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, "Duplicate JSON key: " + key)
            out[key] = value
        return out
    def bad(value):
        raise Refusal("Nonfinite JSON: " + value)
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=bad)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise Refusal("Document not fully parsed: "+str(exc)) from exc


def strict_json(path):
    return strict_json_data(Path(path).read_bytes())


def sha_value(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def safe_path(path):
    p = Path(path)
    require(p.is_absolute(), "Absolute detached path required")

    forbidden = {"host_state", "sealed", "seals", "scores", "scored", "predictions"}
    require(not forbidden.intersection(p.parts), "Forbidden live outcome container")
    require(not forbidden.intersection(p.resolve().parts), "Forbidden resolved outcome container")
    require(not any(x.is_symlink() for x in (p, *p.parents)), "Symlink paths refused")
    return p


def checked(item):
    require(isinstance(item, dict) and set(item) == {"path", "sha256"}, "Exact path/hash identity required")
    require(sha_value(item["sha256"]), "Invalid SHA256")
    p = safe_path(item["path"])
    require(p.is_file() and digest(p) == item["sha256"], "Detached input identity mismatch")
    return p


def canonical_bytes(value):

    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                       separators=(",", ":"))+"\n").encode("utf-8")


def value_hash(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def byte_identity(item):
    require(isinstance(item, dict) and set(item) == {"path", "bytes", "sha256"},
            "Exact replay path/bytes/hash identity required")
    require(isinstance(item["path"], str) and Path(item["path"]).is_absolute() and
            type(item["bytes"]) is int and item["bytes"] >= 0 and sha_value(item["sha256"]),
            "Invalid replay identity")


def checked_copy(item, original):
    byte_identity(item)
    byte_identity(original)
    require((item["bytes"], item["sha256"]) == (original["bytes"], original["sha256"]),
            "Detached replay copy differs from authorised original")
    p = checked({k: item[k] for k in ("path", "sha256")})
    require(p.stat().st_size == item["bytes"], "Replay copy byte count mismatch")
    return strict_json(p)


VERIFIED_METADATA = ("days", "evaluation_view", "daily_common_key_counts", "common_keys_sha256",
                     "sealed_prediction_manifest_sha256", "r2_score_receipt_sha256", "main_daily_csv_sha256")
REPLAY_NAMES = ("numeric_source", "numeric_evidence", "numeric_receipt")
RELEASE_FIELDS = ("schema", "state", "production_authority", "receipt_schema", "receipt_state",
                  "receipt_flags", "evidence_schema", "released_writer_identity",
                  "independent_read_authority_contract", "full_authorization_schema",
                  "trusted_authorization_sha256", "r2_original_identity", "verified_execution_authority",
                  "verified_task_metadata", "replay_provenance", "adoption", "source_request", "release_binding",
                  "document_schema_registry")
AUTHORIZATION_FIELDS = ("schema", "state", "task_id", "synthetic", "spec_freeze_sha256",
                        "original_capture_verified", "r2_receipt_verified", 'comparison_timestamp_verified_before_t5',
                        "capture_receipt", "r2_score_receipt", "loss_exports", "output_directory",
                        "ap_replay_verified", "replay_provenance", "r2_original_identity",
                        "verified_execution_authority", "verified_task_metadata")


RELEASE_BINDINGS = {
    "trusted_authorization_sha256": dict(binding='external_source_sha256', required=True),
    "adoption": dict(binding='source_verified_before_t5', field='comparison_timestamp_verified_before_t5', required=True),
    **{k: dict(binding="authorized_payload", field=k, required=True) for k in
       ("r2_original_identity", "verified_execution_authority", "verified_task_metadata", "replay_provenance")},
}


UNRESOLVED_VALUES = {"pending", "tbd", "unknown", "provisional", "null"}
JSON_SCHEMA_VERSION = 'https://json-schema.org/paper/2020-12/schema'


SUPPORTED_DOCUMENT_SCHEMAS = {
    "SENS35_AP_MATCHING_CONTRACT_V1", "SENS35_MATCHING_RELEASE_BINDING_V1",
    "SENS35_DOCUMENT_SCHEMA_REGISTRY_V1", "SENS35_POSTSCORE_AUTHORIZATION_V2",
    "SENS35_TASK_LOSSES_V2", 'AP_SCORING_SENS35_REPLAY_BINDING_V1',
    'AP_SCORING_SENS35_REPLAY_REFERENCE_V1', 'AP_SCORING_NATIVE_NUMERIC_EVIDENCE_V1',
    'AP_SCORING_NUMERIC_OUTPUT_RECEIPT_V1', "PCPRIMARY_R2_NEWS_EVALUATION_V1",
    "SENS35_LOCAL_PRESPECIFICATION_V1",
}


def require_resolved(value, label, required=True):

    require(value is not None, "Unresolved null: "+label)
    if isinstance(value, str):
        require(value.strip().casefold() not in UNRESOLVED_VALUES, "Unresolved/PENDING value: "+label)
        require(not required or bool(value.strip()), "Empty required value: "+label)
    elif isinstance(value, dict):
        require(not required or bool(value), "Empty required container: "+label)
        for key, item in value.items(): require_resolved(item, label+"/"+key, required=False)
    elif isinstance(value, list):
        require(not required or bool(value), "Empty required container: "+label)
        for i, item in enumerate(value): require_resolved(item, label+"/"+str(i), required=required)


def local_schema_refs(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("$ref", "$dynamicRef"):
                require(isinstance(item, str) and item.startswith("#"), "Schema requires detached local references")
            local_schema_refs(item)
    elif isinstance(value, list):
        for item in value: local_schema_refs(item)


class StructuralGate:

    def __init__(self, contract):
        import jsonschema
        self.js = jsonschema
        registry = release_document(contract["document_schema_registry"])
        require_resolved(registry, "document_schema_registry")
        require(isinstance(registry, dict) and set(registry) == {"schema", "schemas"} and
                registry["schema"] == "SENS35_DOCUMENT_SCHEMA_REGISTRY_V1" and
                isinstance(registry["schemas"], dict) and bool(registry["schemas"]), "Invalid document schema registry")
        require(set(registry["schemas"]) <= SUPPORTED_DOCUMENT_SCHEMAS, "Unknown schema version in registry")
        self.schemas = registry["schemas"]
        for name, schema in self.schemas.items():
            require(isinstance(schema, dict) and bool(schema), "Empty/unbound schema: "+name)
            require(schema.get("$schema") == JSON_SCHEMA_VERSION, "Unknown JSON Schema version: "+name)
            require_resolved(schema, "schema/"+name)
            local_schema_refs(schema)
            try: jsonschema.Draft202012Validator.check_schema(schema)
            except jsonschema.exceptions.SchemaError as exc: raise Refusal("Invalid document schema: "+str(exc)) from exc
        self.copies, self.visited = {}, set()
        self.admit(registry, "document_schema_registry")

    @staticmethod
    def identities(value):
        if isinstance(value, dict):
            if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
                require(set(value) in ({"path", "sha256"}, {"path", "bytes", "sha256"}), "Unclassified identity shape")
                yield value
            else:
                for item in value.values(): yield from StructuralGate.identities(item)
        elif isinstance(value, list):
            for item in value: yield from StructuralGate.identities(item)

    def admit(self, value, label, schema_override=None):
        require_resolved(value, label)
        require(isinstance(value, dict), "Structured document must be an object: "+label)


        def versions(item):
            if isinstance(item, dict):
                if isinstance(item.get("schema"), str):
                    require(item["schema"] in SUPPORTED_DOCUMENT_SCHEMAS, "Unknown schema version: "+item["schema"])
                if "$schema" in item:
                    require(item["$schema"] == JSON_SCHEMA_VERSION, "Unknown JSON Schema version")
                for child in item.values(): versions(child)
            elif isinstance(item, list):
                for child in item: versions(child)
        versions(value)
        if "schema" in value:
            require(value["schema"] in self.schemas, "Unregistered schema version: "+str(value["schema"]))
            schema = self.schemas[value["schema"]]
        else:
            require(value.get("$schema") == JSON_SCHEMA_VERSION, "Missing/unknown document schema version: "+label)
            local_schema_refs(value)
            schema = self.js.Draft202012Validator.META_SCHEMA
        if schema_override is not None:
            schema = schema_override
        declared = {}
        base_required = self.js.Draft202012Validator.VALIDATORS["required"]
        def required_fields(validator, fields, instance, definition):
            yield from base_required(validator, fields, instance, definition)
            if isinstance(instance, dict):
                for field in fields:
                    if field in instance: require_resolved(instance[field], label+"/"+field, required=True)
        base_dependent = self.js.Draft202012Validator.VALIDATORS["dependentRequired"]
        def dependent_fields(validator, dependencies, instance, definition):
            yield from base_dependent(validator, dependencies, instance, definition)
            if isinstance(instance, dict):
                for trigger, fields in dependencies.items():
                    if trigger in instance:
                        for field in fields:
                            if field in instance: require_resolved(instance[field], label+"/"+field, required=True)
        def linked_format(validator, kind, instance, definition):
            require(kind in ("json", "python", "json_reference", "python_reference"), "Unknown bound-document format")
            require(isinstance(instance, dict), "Hash-bound identity must be an object")
            declared[id(instance)] = kind
            return ()
        validator = self.js.validators.extend(self.js.Draft202012Validator,
            {"required": required_fields, "dependentRequired": dependent_fields, 'x-sensitivity_export-format': linked_format})


        def evaluation_copy(item):
            if isinstance(item, dict):
                return {k: evaluation_copy(v) for k, v in item.items() if k != "$schema"}
            if isinstance(item, list): return [evaluation_copy(v) for v in item]
            return item
        try: validator(evaluation_copy(schema)).validate(value)
        except self.js.exceptions.ValidationError as exc: raise Refusal("Required document structure failed: "+str(exc)) from exc
        links = list(self.identities(value))
        for identity in links:
            require(id(identity) in declared, "Unclassified hash-bound document: "+identity["path"])
            if not declared[id(identity)].endswith("_reference"):
                self.copies.setdefault(identity["sha256"], []).append((identity, declared[id(identity)]))
        for identity in links:
            kind = declared[id(identity)]
            target = identity
            if kind.endswith("_reference"):
                kind = kind.removesuffix("_reference")
                matches = [i for i, fmt in self.copies.get(identity["sha256"], []) if fmt == kind and
                           ("bytes" not in identity or i.get("bytes") == identity["bytes"])]
                require(bool(matches), "No authorised detached copy for bound reference")
                target = matches[0]
            key = (target["path"], target["sha256"], kind)
            if key in self.visited: continue
            data = release_bytes(target)
            self.visited.add(key)
            if kind == "python":
                try: ast.parse(data.decode("utf-8"))
                except (SyntaxError, UnicodeError) as exc: raise Refusal("Unparsed bound source: "+str(exc)) from exc
            else:
                self.admit(strict_json_data(data), "bound/"+target["path"])


def structural_authorization_gate(auth, contract):
    gate = StructuralGate(contract)
    gate.admit(auth, "actual_authorization", schema_override=authorization_schema(contract))
    return gate


def release_file(identity):
    byte_identity(identity)
    p = checked({k: identity[k] for k in ("path", "sha256")})
    require(p.stat().st_size == identity["bytes"], "Release document byte count mismatch")
    return p


def release_document(identity):
    return strict_json_data(release_bytes(identity))


def release_bytes(identity):
    path = release_file(identity) if "bytes" in identity else checked(identity)
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == identity["sha256"] and
            ("bytes" not in identity or len(data) == identity["bytes"]), "Parsed bytes identity mismatch")
    return data


def authorization_schema(contract):
    import jsonschema
    document = release_document(contract["full_authorization_schema"])
    local_schema_refs(document)
    require(document.get("$schema") == JSON_SCHEMA_VERSION, "Unknown JSON Schema version")
    require_resolved(document, "complete_authorization_schema")
    require(document.get("type") == "object" and
            set(AUTHORIZATION_FIELDS) <= set(document.get("required", [])) and
            set(document.get("required", [])) <= set(document.get("properties", {})),
            "Complete required authorization schema is unbound/incomplete")
    try:
        jsonschema.Draft202012Validator.check_schema(document)
    except jsonschema.exceptions.SchemaError as exc:
        raise Refusal("Invalid released authorization schema: "+str(exc)) from exc
    return document


def production_matching_contract():
    contract = strict_json(HERE / "MATCHING_CONTRACT.json")
    require(contract.get("state") == "RELEASED_PRODUCTION_CONTRACT" and
            contract.get("production_authority") is True,
            "PENDING: independently released real numeric receipt/authorisation contract")
    require(set(RELEASE_FIELDS) <= set(contract), "Missing mandatory release field")
    require_resolved(contract, "matching_contract")
    require(contract["schema"] == "SENS35_AP_MATCHING_CONTRACT_V1", "Wrong matching release schema")
    for key in ("receipt_schema", "receipt_state", "evidence_schema", "source_request"):
        require(isinstance(contract[key], str) and bool(contract[key]), "Invalid release field: "+key)
    require(isinstance(contract["receipt_flags"], dict), "Receipt flags must be bound")
    require(contract["receipt_state"] != "ARTIFICIAL_NUMERIC_OUTPUT_COMPLETE" and
            contract["receipt_flags"].get("synthetic_only") is False,
            "Artificial numeric receipt cannot authorise production")
    for key in ("released_writer_identity", "independent_read_authority_contract",
                "full_authorization_schema", "release_binding", "document_schema_registry"):
        byte_identity(contract[key])
    for key, rule in RELEASE_BINDINGS.items():
        require(canonical_bytes(contract[key]) == canonical_bytes(rule), "Unbound required release rule: "+key)


    freeze = strict_json(HERE / "SPEC_FREEZE.json")
    require_resolved(freeze, "bound_spec_freeze")
    require(freeze.get("schema") == "SENS35_LOCAL_PRESPECIFICATION_V1", "Unknown specification schema version")
    require(freeze.get("matching_release_binding") == contract["release_binding"], "Unbound independent matching release")
    record = release_document(contract["release_binding"])
    approved = {k: v for k, v in contract.items() if k != "release_binding"}
    require(set(record) == {"schema", "approved_contract", "contract_sha256"} and
            record["schema"] == "SENS35_MATCHING_RELEASE_BINDING_V1" and
            canonical_bytes(record["approved_contract"]) == canonical_bytes(approved) and
            record["contract_sha256"] == value_hash(approved), "Independent whole-contract binding mismatch")

    release_document(contract["independent_read_authority_contract"])
    release_file(contract["released_writer_identity"])
    authorization_schema(contract)
    gate = StructuralGate(contract)
    gate.admit(contract, "production_matching_contract")
    require(contract["receipt_schema"] in gate.schemas and contract["evidence_schema"] in gate.schemas,
            "Unregistered receipt/evidence schema version")
    return contract


def validate_release_authorization(auth, expected_sha, contract):

    import jsonschema
    require_resolved(auth, "actual_authorization")
    require(sha_value(expected_sha), 'External source authorization SHA required')
    for key, rule in RELEASE_BINDINGS.items():
        require(canonical_bytes(contract.get(key)) == canonical_bytes(rule), "Unbound required release rule: "+key)
    require(auth.get("ap_replay_verified") is True and auth.get('comparison_timestamp_verified_before_t5') is True,
            "Independently verified replay and pre-T5 adoption required")
    try:
        jsonschema.Draft202012Validator(authorization_schema(contract)).validate(auth)
    except jsonschema.exceptions.ValidationError as exc:
        raise Refusal("Authorization fails complete released schema: "+str(exc)) from exc
    structural_authorization_gate(auth, contract)


def replay_preflight(exports):
    states, issues = {}, {task: {} for task in TASKS}
    for task in TASKS:
        validate_export(exports[task], task, task_only=True)
    for task in TASKS:
        states[task] = {}
        for tag in SERIES:
            item = exports[task]["series"].get(tag)
            try:
                require(isinstance(item, dict), "Missing/non-object series entry: "+tag)
                require(item.get("days") == TASKS[task]["days"], "Missing/extra days in "+tag)
                require(item.get("seeds") == (list(SEEDS) if tag == SERIES[-1] else [int(tag[5:])]),
                        "Wrong seed definition: "+tag)
                states[task][tag] = series_disposition(item, tag)
            except Refusal as exc:
                require(tag != SERIES[0], "Primary preflight mismatch "+task+"/"+tag+": "+str(exc))
                raw = item if isinstance(item, dict) else {}
                native = raw.get("native_status", raw.get("state"))
                states[task][tag] = dict(state="NOT_EVALUABLE",
                    native_status=native if isinstance(native, str) and native else "UNDEFINED_NATIVE_STATUS",
                    native_parity=raw.get("frozen_parity"), reason=raw.get("reason", ""))
                issues[task][tag] = "Preflight mismatch: "+str(exc)
    return states, issues


def matching_check(exports, timestamp_checks, receipt_contract):

    require(set(exports) == set(TASKS), "Both replay tasks required")

    states, issues = replay_preflight(exports)
    require(timestamp_checks.get("ap_replay_verified") is True, 'Independent AP replay timestamp_checks required')
    provenance = timestamp_checks.get("replay_provenance", {})
    require(set(provenance) == {*REPLAY_NAMES, "original_identities"}, "Missing authorised replay receipt/copies")
    originals = provenance["original_identities"]
    require(set(originals) == set(REPLAY_NAMES), "Closed original replay identities required")
    for task in TASKS:
        ref = exports[task].get("replay_binding", {})
        require(set(ref) == {"schema", "pointer", *REPLAY_NAMES} and
                ref["schema"] == 'AP_SCORING_SENS35_REPLAY_REFERENCE_V1' and
                ref["pointer"] == "/sens35_replay_binding/tasks/"+task,
                "Missing/wrong task replay reference")
        require(all(ref[k] == originals[k] for k in REPLAY_NAMES), "Unauthorised/wrong replay receipt reference")
    payloads = {k: checked_copy(provenance[k], originals[k]) for k in REPLAY_NAMES}
    receipt, evidence, source = (payloads[k] for k in ("numeric_receipt", "numeric_evidence", "numeric_source"))
    require(receipt.get("schema") == receipt_contract["receipt_schema"] and
            receipt.get("state") == receipt_contract["receipt_state"] and
            all(type(receipt.get(k)) is type(v) and receipt.get(k) == v
                for k, v in receipt_contract["receipt_flags"].items()), "Numeric receipt incomplete/wrong contract")
    require(receipt.get("files") == [originals["numeric_source"], originals["numeric_evidence"]],
            "Numeric receipt missing/duplicate/unlisted source or evidence")
    commitment = source.get("sens35_replay_binding", {})
    require(set(commitment) == {"schema", "r2_score_receipt", "execution_authority_sha256", "loss_replay_sha256", "tasks"}
            and commitment["schema"] == 'AP_SCORING_SENS35_REPLAY_BINDING_V1', "Wrong replay commitment")
    original_r2 = timestamp_checks.get("r2_original_identity")
    byte_identity(original_r2)
    require(commitment["r2_score_receipt"] == original_r2 and
            original_r2["sha256"] == timestamp_checks["r2_score_receipt"]["sha256"], "Authorised R2 original mismatch")
    lineage = timestamp_checks.get("verified_execution_authority")
    require(isinstance(lineage, dict) and lineage.get("r2", {}).get("score_receipt") == original_r2 and
            evidence.get("schema") == receipt_contract["evidence_schema"] and
            canonical_bytes(evidence.get("execution_authority")) == canonical_bytes(lineage),
            "Independent original/capture/R2 lineage mismatch")
    require(commitment["execution_authority_sha256"] == value_hash(lineage) and
            "loss_replay" in evidence and commitment["loss_replay_sha256"] == value_hash(evidence["loss_replay"]),
            "Numeric replay evidence commitment mismatch")
    verified = timestamp_checks.get("verified_task_metadata", {})
    require(set(verified) == set(TASKS) and set(commitment["tasks"]) == set(TASKS), "Independent task metadata required")
    def failure(task, tag, reason):
        bundle = exports[task]["series"].get(tag, {})
        require(tag != SERIES[0], f"Primary replay mismatch {task}/{tag}: {reason}; native_status={bundle.get('native_status', bundle.get('state'))}; native_reason={bundle.get('reason', '')}")
        issues[task][tag] = (issues[task][tag]+"; " if tag in issues[task] else "")+reason

    for task in TASKS:
        obj, bound = exports[task], commitment["tasks"][task]
        require(set(bound) == {"metadata", "export_sha256", "series"} and
                sha_value(bound["export_sha256"]) and isinstance(bound["series"], dict) and
                SERIES[0] in bound["series"] and set(bound["series"]) <= set(SERIES), "Malformed task commitment")
        metadata = {k: v for k, v in obj.items() if k not in ("series", "replay_binding")}
        require(canonical_bytes(metadata) == canonical_bytes(bound["metadata"]), "Replay task metadata drift")
        require(set(verified[task]) == set(VERIFIED_METADATA) and
                canonical_bytes({k: obj[k] for k in VERIFIED_METADATA}) == canonical_bytes(verified[task]),
                "Independent task grid/manifest/CSV/view drift")
        require(obj["r2_score_receipt_sha256"] == original_r2["sha256"], "Task R2 identity drift")
        for tag in SERIES:
            if tag in issues[task]: continue
            item, entry = obj["series"][tag], bound["series"].get(tag)
            try:
                require(isinstance(entry, dict) and set(entry) == {"metadata", "losses_sha256"}, "Malformed/missing series commitment")
                meta = {k: v for k, v in item.items() if k != "losses"}
                require(canonical_bytes(meta) == canonical_bytes(entry["metadata"]), "Replay series metadata/status drift")
                if states[task][tag]["state"] != "COMPUTED":
                    require(entry["losses_sha256"] == {}, "Unavailable series has computed replay hashes/status conflict")
                    continue
                hashes = entry["losses_sha256"]
                require(isinstance(hashes, dict) and set(hashes) == set(TASKS[task]["arms"]) and
                        all(sha_value(h) for h in hashes.values()), "Missing/malformed per-arm commitment")
            except (Refusal, TypeError, ValueError) as exc:
                failure(task, tag, str(exc))
    output = {}
    for task in TASKS:
        obj, bound = exports[task], commitment["tasks"][task]
        safe = {k: deepcopy(v) for k, v in obj.items() if k not in ("series", "replay_binding")}
        safe["series"] = {}
        for tag in SERIES:
            raw = obj["series"].get(tag)
            item = raw if isinstance(raw, dict) else {}
            safe["series"][tag] = {k: deepcopy(v) for k, v in item.items() if k != "losses"}
            if states[task][tag]["state"] != "COMPUTED" or tag in issues[task]:
                continue
            try:
                losses = item.get("losses", {})
                require(set(losses) == set(TASKS[task]["arms"]), "Missing/extra replay arm")
                for arm in TASKS[task]["arms"]:
                    require(value_hash(losses[arm]) == bound["series"][tag]["losses_sha256"][arm],
                            "Replay array hash mismatch: "+arm)
                    require(isinstance(losses[arm], list) and len(losses[arm]) == len(TASKS[task]["days"])
                            and all(type(v) in (int, float) and np.isfinite(v) and v >= 0 for v in losses[arm]),
                            "Replay loss shape/type/finite mismatch: "+arm)
                if tag == SERIES[-1]:
                    require(item.get("loss_definition") == MEAN_DEFINITION, "Mean-prediction losses required")
                safe["series"][tag]["losses"] = deepcopy(losses)
            except (Refusal, ValueError, TypeError) as exc:
                failure(task, tag, str(exc))


        if not issues[task]:
            require(value_hash(safe) == bound["export_sha256"], "Unlocalized whole-task replay hash mismatch")
        for tag, reason in issues[task].items():
            item = safe["series"][tag]
            item.pop("losses", None)
            native_metadata = deepcopy(item)
            native_reason = states[task][tag]["reason"]
            reason_text = native_reason if isinstance(native_reason, str) else repr(native_reason)
            item.update(state="NOT_EVALUABLE", native_status=states[task][tag]["native_status"],
                        days=list(TASKS[task]["days"]), seeds=list(SEEDS) if tag == SERIES[-1] else [int(tag[5:])],
                        native_state=native_metadata.get("state"), native_metadata=native_metadata,
                        native_reason=native_reason, reason=reason_text + ("; " if reason_text else "") + reason,
                        matching_state="MISMATCH", matching_reason=reason)
        safe["replay_verification"] = dict(state="PASS_WITH_QUARANTINE" if issues[task] else "PASS",
            whole_export_hash="INVALIDATED_BY_LOCALIZED_SECONDARY_FAILURE" if issues[task] else "PASS",
            original_identities=deepcopy(originals), quarantined_series=list(issues[task]))
        validate_export(safe, task)
        output[task] = safe
    return output


def frozen_modules():

    sys.dont_write_bytecode = True
    freeze = strict_json(HERE / "SPEC_FREEZE.json")
    paths = freeze["statistical_sources"]
    for rel, sha in paths.items():
        require(digest(PROJ / rel) == sha, "Frozen source drift: " + rel)

    package = ModuleType("_sens35_conf")
    package.__path__ = [str(PROJ / 'studies/confirmation/code')]
    sys.modules[package.__name__] = package
    def load(name, rel):
        spec = importlib.util.spec_from_file_location(name, PROJ / rel)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    load("_sens35_conf.guard", 'studies/confirmation/code/guard.py')
    sc = load("_sens35_conf.scoring", 'studies/confirmation/code/scoring.py')
    a2 = load("_sens35_a2", 'studies/confirmation/primary_tests/code/primary_comparisons.py')
    ap = load("_sens35_ap", 'studies/inference/code/read_comparisons.py')
    require(tuple(sc.NEWS_FAMILY) == FAMILY and tuple(sc.NOTICE_FAMILY) == TASKS["notice"]["pairs"]
            and ap.DRAWS == 100000 and ap.SEED == 20260925,
            "Frozen family/bootstrap constants drift")
    return sc, a2, ap


def series_disposition(bundle, tag):

    state, parity = bundle.get("state"), bundle.get("frozen_parity")
    native = bundle.get("native_status", state)
    require(state in ("COMPUTED", "NOT_RUN", "NOT_EVALUABLE", "DEVIATION", "PENDING"),
            "Unknown native series status")
    require(isinstance(native, str) and bool(native), "Nonempty native status required")


    computed = state == "COMPUTED" and parity == "PASS" and native == "COMPUTED"
    if tag == SERIES[0]:
        require(computed,
                f"Primary-seed completion/parity failure: state={state}, native_status={native}, parity={parity}, reason={bundle.get('reason', '')}")
    if computed:
        effective = "COMPUTED"
    else:
        require(isinstance(bundle.get("reason"), str) and bool(bundle["reason"]), "Native failure reason required")
        not_run = state == "NOT_RUN" and native == "NOT_RUN" and parity in (None, "NOT_RUN")
        effective = "NOT_RUN" if not_run else "NOT_EVALUABLE"
    return dict(state=effective, native_status=native,
                native_parity=parity, reason=bundle.get("reason", ""),
                **{k: bundle[k] for k in ("native_state", "native_metadata", "native_reason", "matching_state", "matching_reason") if k in bundle})


def validate_export(export, expected_task=None, metadata_only=False, task_only=False):
    require(export.get("schema") == "SENS35_TASK_LOSSES_V2", "Wrong loss export schema")
    task = export.get("task")
    require(task in TASKS and (expected_task is None or task == expected_task), "Wrong task export")
    config = TASKS[task]
    days, n = config["days"], len(config["days"])
    require(export.get("days") == days, "Missing, extra, duplicate or unordered task days")
    view = export.get("evaluation_view", {})
    require(view.get("schema") == "PCPRIMARY_R2_NEWS_EVALUATION_V1" and
            view.get("issue_days") == DAYS and view.get("primary_days") == 135 and
            view.get("sealed_domain_days") == 214 and sha_value(view.get("scientific_source_sha256")),
            "Wrong R2 evaluation view")
    require(export.get("daily_common_key_counts") == [config["keys_per_day"]] * n, "Task common grid attestation failed")
    for field in ("common_keys_sha256", "sealed_prediction_manifest_sha256", "r2_score_receipt_sha256",
                  "main_daily_csv_sha256"):
        require(sha_value(export.get(field)), "Missing export identity: " + field)
    require(export.get("main_daily_csv_parity") == "PASS", "Main daily CSV parity required")
    series = export.get("series", {})
    if task_only:
        require(isinstance(series, dict) and SERIES[0] in series and set(series) <= set(SERIES),
                "Missing primary or extra unregistered series")
        return
    require(set(series) == set(SERIES), "Missing/extra seed or mean disposition")
    dispositions = {}


    for tag in SERIES:
        bundle = series[tag]
        require(bundle.get("days") == days, "Missing/extra days in " + tag)
        require(bundle.get("seeds") == (list(SEEDS) if tag == SERIES[-1] else [int(tag[5:])]),
                "Wrong seed definition: " + tag)
        dispositions[tag] = series_disposition(bundle, tag)
    if metadata_only:
        return
    for tag in SERIES:
        bundle = series[tag]
        if dispositions[tag]["state"] != "COMPUTED":

            continue
        if tag == SERIES[-1]:
            require(bundle.get("loss_definition") == MEAN_DEFINITION, "Mean-prediction losses required")
        require(set(bundle.get("losses", {})) == set(config["arms"]), "Exact primary arms required")
        for arm, values in bundle["losses"].items():
            require(isinstance(values, list) and len(values) == n and
                    all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values),
                    "Daily loss shape/type mismatch: " + tag + "/" + arm)
            x = np.asarray(values, dtype="float64")
            require(np.isfinite(x).all() and (x >= 0).all(), "Invalid absolute daily losses")


def family_statistics(losses, days, modules, draws, task="news"):

    sc, a2, ap = modules
    adapter = ap.ChunkedScoring(sc, draws=draws, chunk=512, gate=None)
    pairs = TASKS[task]["pairs"]
    result = a2.family_inference(adapter, losses, pairs, days, m=len(pairs), subset=True)


    hac = [sc.dm_daily(np.asarray(losses[a])-np.asarray(losses[b]), 7) for a, b in pairs]
    adjusted = sc.holm([r["p_two_sided"] for r in hac])
    for row, h, adj in zip(result["reports"], hac, adjusted):
        row.update(frozen_a2_hac7_state=row["hac7_state"],
                   hac7_p_two_sided=h["p_two_sided"], hac7_state=h["state"],
                   hac7_statistic=h["statistic"], hac7_variance=h["variance"],
                   hac7_holm_p=adj, hln_df=len(days)-1,
                   hac7_lag_unit="chronological retained observation",
                   hac7_convention=HAC_CONVENTION, hac7_calendar_days=False,
                   hac7_finite_sample_limit=HAC_LIMIT)
        zero = row["reference_mae"] == 0
        row.update(percentage_state="UNDEFINED_ZERO_REFERENCE_MAE" if zero else "DEFINED",
                   percentage_reason="Subset reference MAE is zero; percentage effect and intervals are undefined."
                   if zero else "")

        for key in ("decision", "hln_decision", "hac7_decision"):
            row.pop(key, None)
    return result


def analyse_export(export, modules, subset=None):

    require("replay_binding" not in export, "Bound AP export must pass matching_check before analysis")
    validate_export(export)
    task = export["task"]
    config = TASKS[task]
    keep = config["U"] if subset is None else list(subset)
    require(keep in (config["U"], config["days"]), "Only frozen U, or full-D synthetic parity, is supported")
    index = [config["days"].index(d) for d in keep]
    result = dict(task=task, role="SENSITIVITY_ONLY",
                  changes_primary=False, days=keep, n_days=len(keep), hln_df=len(keep)-1,
                  excluded_recorded_analysis_days=config["exposed"], family=[list(p) for p in config["pairs"]],
                  family_size=len(config["pairs"]), alpha=.05, bootstrap_seed=20260925,
                  reported_draws=100000, native_draws=2000,
                  exposure_label="no recorded analysis; includes unknown use",
                  unknown_prior_use_days=[d for d in keep if "2026-07-25" <= d <= "2026-09-23"],
                  unknown_prior_use_count=sum("2026-07-25" <= d <= "2026-09-23" for d in keep),
                  hac7_convention=HAC_CONVENTION, hac7_calendar_days=False, hac7_finite_sample_limit=HAC_LIMIT,
                  interval_method="paired non-circular 1/7-day; calendar-contiguous blocks; linear quantiles",
                  evaluation_view=export["evaluation_view"], series={})
    if "replay_verification" in export:
        result["replay_verification"] = export["replay_verification"]
    for tag in SERIES:
        bundle = export["series"][tag]
        disposition = series_disposition(bundle, tag)
        if disposition["state"] != "COMPUTED":
            result["series"][tag] = dict(**disposition, seeds=bundle["seeds"],
                                        reports=[dict(arm=a, reference=b, **disposition,
                                                      hln_df=len(keep)-1, hac7_convention=HAC_CONVENTION,
                                                      hac7_calendar_days=False, hac7_finite_sample_limit=HAC_LIMIT)
                                                 for a, b in config["pairs"]])
            continue
        losses = {a: np.asarray(bundle["losses"][a])[index] for a in config["arms"]}
        native = family_statistics(losses, keep, modules, 2000, task)
        reported = family_statistics(losses, keep, modules, 100000, task)
        reported.update(**disposition, seeds=bundle["seeds"], native_B2000=native,
                        loss_definition=bundle.get("loss_definition", "daily mean absolute loss"))
        result["series"][tag] = reported
    return modules[1].json_safe(result)


def analyse_tasks(exports, modules):
    require(set(exports) == set(TASKS), "Both news and notice dispositions are required")
    for task, export in exports.items():
        validate_export(export, expected_task=task, metadata_only=True)
    require(not any("replay_binding" in obj for obj in exports.values()),
            "Bound AP exports must pass matching_check before arrays")
    for task, export in exports.items():
        validate_export(export, expected_task=task)
    return dict(schema="SENSITIVITY_UNEXPOSED_V2", role="SENSITIVITY_ONLY", changes_primary=False,
                tasks={task: analyse_export(exports[task], modules) for task in TASKS})


def authorization_inputs(path, expected_sha):

    require(sha_value(expected_sha), "Externally supplied authorization SHA256 required")
    p = checked({"path": str(path), "sha256": expected_sha})
    auth = strict_json(p)
    require(auth.get("schema") == "SENS35_POSTSCORE_AUTHORIZATION_V2" and
            auth.get("state") == "SEPARATE_EXECUTION_TASK_AUTHORIZED" and
            auth.get("task_id") == "SENS35" and auth.get("synthetic") is False,
            "Separate production authorization required")
    require(auth.get("spec_freeze_sha256") == digest(HERE / "SPEC_FREEZE.json"), "Specification freeze drift")
    freeze = strict_json(HERE / "SPEC_FREEZE.json")
    for rel, sha in freeze["delivery_files"].items():
        require(digest(HERE / rel) == sha, "Delivery drift: " + rel)
    require(auth.get("original_capture_verified") is True and auth.get("r2_receipt_verified") is True,
            "Successful original capture AND verified R2 receipt required")
    require(auth.get('comparison_timestamp_verified_before_t5') is True,
            'Source must verify adopted COMPARISON timestamp before T5')


    matching_contract = production_matching_contract()
    validate_release_authorization(auth, expected_sha, matching_contract)
    for field in ("capture_receipt", "r2_score_receipt", "loss_exports"):
        require(field in auth, "Missing authorised input: " + field)
    checked(auth["capture_receipt"])
    receipt = strict_json(checked(auth["r2_score_receipt"]))
    require(receipt.get("state") == "FROZEN_SCORE_COMPLETE", "R2 score incomplete")
    view = receipt.get("evaluation_view", {})
    require(view.get("schema") == "PCPRIMARY_R2_NEWS_EVALUATION_V1" and view.get("issue_days") == DAYS,
            "Original-window receipt cannot authorise R2")


    require(set(auth["loss_exports"]) == set(TASKS), "Both detached task exports must be authorised")
    exports = {}
    for task in TASKS:
        export = strict_json(checked(auth["loss_exports"][task]))
        require(export.get("r2_score_receipt_sha256") == auth["r2_score_receipt"]["sha256"] and
                export.get("evaluation_view") == view, "Export/R2 receipt binding mismatch")
        validate_export(export, expected_task=task, task_only=True)
        listed = [f for f in receipt.get("files", []) if Path(f.get("path", "")).name == task+"__DAILY_LOSSES.csv"]
        require(len(listed) == 1 and listed[0].get("sha256") == export["main_daily_csv_sha256"],
                "Main daily export not bound to R2 score receipt")
        exports[task] = export
    exports = matching_check(exports, auth, matching_contract)
    return auth, exports


def write_outputs(result, out):
    out = safe_path(out)
    out.mkdir(parents=True, exist_ok=True)
    jp, cp = out / "SENSITIVITY_UNEXPOSED.json", out / "SENSITIVITY_UNEXPOSED.csv"
    require(not jp.exists() and not cp.exists(), "Existing sensitivity outputs cannot be overwritten")
    fields = ("task", "series", "state", "reason", "native_status", "native_parity", "native_state", "native_reason", "matching_state", "matching_reason", "arm", "reference", "n_days", "hln_df", "arm_mae", "reference_mae",
              "mean_difference", "effect_percent_reference_mae", "p_two_sided", "holm_p", "dm_state",
              "hac7_p_two_sided", "hac7_holm_p", "hac7_state", "frozen_a2_hac7_state", "hac7_convention",
              "hac7_calendar_days", "hac7_finite_sample_limit", "percentage_state", "percentage_reason",
              "hln_p_two_sided", "hln_holm_p",
              "interval95_one_day", "interval95_seven_day", "interval_family_one_day", "interval_family_seven_day")
    rows = []
    for task, task_result in result["tasks"].items():
      for tag, family in task_result["series"].items():
        for report in family["reports"]:
            row = {k: report.get(k) for k in fields}
            row.update(task=task, series=tag, state=family["state"], reason=family.get("reason", ""),
                       native_status=family["native_status"], native_parity=family["native_parity"],
                       **{k: family.get(k) for k in ("native_state", "native_reason", "matching_state", "matching_reason")},
                       n_days=task_result["n_days"])
            for block, label in (("1", "one_day"), ("7", "seven_day")):
                boot = report.get("bootstrap", {}).get(block, {})
                for prefix, source in (("interval95_", "interval95_percent"),
                                       ("interval_family_", "interval_family_adjusted_percent")):
                    value = boot.get(source)
                    row[prefix+label] = None if value is None else json.dumps(value, allow_nan=False)
            rows.append(row)
    with jp.open("x") as f:
        json.dump(result, f, indent=2, allow_nan=False)
        f.write("\n")
    with cp.open("x", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", required=True, type=Path)
    parser.add_argument("--authorization-sha256", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    auth, exports = authorization_inputs(args.authorization, args.authorization_sha256)
    require(safe_path(args.out).resolve() == safe_path(auth["output_directory"]).resolve(),
            "Output directory not authorised")
    result = analyse_tasks(exports, frozen_modules())
    result["provenance"] = dict(authorization_sha256=args.authorization_sha256,
                                spec_freeze_sha256=auth["spec_freeze_sha256"],
                                inputs={k: auth[k] for k in ("capture_receipt", "r2_score_receipt", "loss_exports", "replay_provenance")})
    write_outputs(result, args.out)


if __name__ == "__main__":
    main()
