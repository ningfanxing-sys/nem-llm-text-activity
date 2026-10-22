"""NRX offline notice validator: full schema, literal evidence, local bindings.

This proves structural consistency and literal grounding, not semantic entailment
of categorical values or a unique real-world event interpretation. It never reads
prices, forecasts, labels, or any notice other than the supplied source object.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterator

from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "schema_full.json"
_TYPOGRAPHY = str.maketrans({
    "\u2013": "-", "\u2014": "-", "\u2212": "-",
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u00a0": " ",
})
_ENUM_VALUE_FIELDS = {"lifecycle", "region", "interval_status", "fuel_type",
                      "event_class", "event_family"}
_REGION_PATTERNS = {
    "NSW1": r"\b(?:NSW1?|New South Wales)\b",
    "QLD1": r"\b(?:QLD1?|Queensland)\b",
    "SA1": r"\b(?:SA1?|South Australian?)\b",
    "TAS1": r"\b(?:TAS1?|Tasmanian?)\b",
    "VIC1": r"\b(?:VIC1?|Victorian?)\b",
}
_MONTH = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
          r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
          r"Nov(?:ember)?|Dec(?:ember)?)")
_DATE_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"(?<!\d)(?:19|20)\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])(?!\d)",
    r"(?<!\d)(?:0?[1-9]|[12]\d|3[01])[-/.](?:0?[1-9]|1[0-2])[-/.](?:\d{2}|(?:19|20)\d{2})(?!\d)",
    rf"\b(?:0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\s+{_MONTH}\.?\s+(?:19|20)\d{{2}}\b",
    rf"\b{_MONTH}\.?\s+(?:0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\s*,?\s+(?:19|20)\d{{2}}\b",
    r"(?<!\d)(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?!\d)",
    r"(?<!\d)(?:0?[1-9]|[12]\d|3[01])[/.-](?:0?[1-9]|1[0-2])(?!\d)",
    rf"\b(?:0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\s+{_MONTH}\b",
    rf"\b{_MONTH}\.?\s*(?:0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\b",
))
# Numeric AEMO IDs occur as standalone 5--9 digit strings. Explicitly marked
# references additionally cover nonnumeric IDs in synthetic checks or registries.
_BARE_ID = re.compile(r"(?<![\w.])\d{5,9}(?![\w.])")
_MARKED_ID = re.compile(
    r"\b(?:(?:market\s*)?notice(?:\s*(?:number|no\.?|id))?|marketnoticeid)"
    r"\s*(?:[#:=>-]\s*)?([A-Za-z0-9][A-Za-z0-9_-]*)\b", re.IGNORECASE)


def normalize_verbatim(value: str) -> str:
    """Exact NEWSX mapping: NFKC, typographic punctuation, whitespace runs."""
    value = unicodedata.normalize("NFKC", value).translate(_TYPOGRAPHY)
    return re.sub(r"\s+", " ", value)


def _error(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _path(parts: Any) -> str:
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _strings(value: Any, path: tuple = ()) -> Iterator[tuple[tuple, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _strings(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _strings(child, (*path, index))


def _fields(value: Any, path: tuple = ()) -> Iterator[tuple[tuple, dict]]:
    if isinstance(value, dict):
        if "value" in value and "evidence_spans" in value:
            yield path, value
        for key, child in value.items():
            yield from _fields(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _fields(child, (*path, index))


def _source_parts(notice: dict) -> tuple[str, str]:
    # Never concatenate title/body for substring matching: a quote cannot bridge
    # two distinct source fields, and registry metadata cannot act as evidence.
    return tuple(normalize_verbatim(notice.get(key, ""))
                 if isinstance(notice.get(key, ""), str) else ""
                 for key in ("title", "body"))


def _contains(value: str, parts: tuple[str, str]) -> bool:
    normalized = normalize_verbatim(value)
    return bool(normalized.strip()) and any(normalized in part for part in parts)


def _identifier_present(value: str, parts: tuple[str, str]) -> bool:
    """An ID must be a whole token, never the prefix of a different ID."""
    pattern = re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(value) + r"(?![A-Za-z0-9_-])")
    return any(pattern.search(part) for part in parts)


def _supported_spans(spans: Any, parts: tuple[str, str], path: tuple,
                     errors: list[dict]) -> list[str]:
    if not isinstance(spans, list):
        return []  # Full schema reports the type error.
    good = []
    for index, span in enumerate(spans):
        if not isinstance(span, str):
            continue
        if not normalize_verbatim(span).strip():
            errors.append(_error("EMPTY_SPAN", _path((*path, index)),
                                 "Evidence span is empty after typography normalization."))
        elif not _contains(span, parts):
            errors.append(_error("FABRICATED_SPAN", _path((*path, index)),
                                 "Evidence span is not literal in title or body."))
        else:
            good.append(normalize_verbatim(span))
    return good


def check_contamination(label: object, notice: dict) -> list[dict[str, str]]:
    """Scan every output string for unsupported explicit IDs or date tokens.

    Date grammars: Y-M-D / D-M-Y (also slash/dot), compact YYYYMMDD,
    D/M (also dot/hyphen), D Month and Month D, with or without years.
    Token checks are literal under NEWSX normalization, case-preserving; no date
    inferred from the notice clock is permitted. Referenced IDs/dates actually
    printed in the same title/body are permitted. Unmarked arbitrary alphanumeric
    identifiers and implicit/relative dates are outside this deterministic scan.
    """
    parts = _source_parts(notice)
    own_id = str(notice.get("notice_id", ""))
    errors = []
    for path, value in _strings(label):
        if path == ("notice_id",):
            continue  # Echo checked separately; its ID is permitted here only.
        normalized = normalize_verbatim(value)
        seen = set()
        ids = [(m.group(0), m.start()) for m in _BARE_ID.finditer(normalized)]
        ids += [(m.group(1), m.start(1)) for m in _MARKED_ID.finditer(normalized)
                if m.group(1).lower() not in {"is", "was", "has", "will", "for", "of", "the", "on"}]
        for token, _ in ids:
            if ("id", token) in seen:
                continue
            seen.add(("id", token))
            if token != own_id and not _identifier_present(token, parts):
                errors.append(_error("FOREIGN_NOTICE_ID", _path(path),
                                     f"Notice ID token {token!r} is absent from this source notice."))
        for pattern in _DATE_PATTERNS:
            for match in pattern.finditer(normalized):
                token = match.group(0)
                if ("date", token) in seen:
                    continue
                seen.add(("date", token))
                if not _contains(token, parts):
                    errors.append(_error("FOREIGN_DATE", _path(path),
                                         f"Date token {token!r} is absent from this source notice."))
    return errors


def validate_label(label: object, notice: dict) -> list[dict[str, str]]:
    """Return machine-readable validation errors; an empty list means valid."""
    errors = [_error("SCHEMA", _path(error.absolute_path), error.message)
              for error in _validator().iter_errors(label)]
    if not isinstance(label, dict):
        return errors
    own_id = str(notice.get("notice_id", ""))
    if label.get("notice_id") != own_id:
        errors.append(_error("NOTICE_ID_MISMATCH", "/notice_id", "notice_id must echo the supplied source ID exactly."))
    parts = _source_parts(notice)
    for path, field in _fields(label):
        value = field.get("value")
        good = _supported_spans(field.get("evidence_spans"), parts,
                                (*path, "evidence_spans"), errors)
        if isinstance(value, str) and value != "UNKNOWN":
            if not normalize_verbatim(value).strip():
                errors.append(_error("EMPTY_VALUE", _path((*path, "value")), "Known value is blank."))
            if not good:
                errors.append(_error("MISSING_EVIDENCE", _path(path), "Every known value needs a literal source evidence span."))
            # attributes.region is raw source text, whereas window.region is enum.
            is_enum = bool(path) and path[-1] in _ENUM_VALUE_FIELDS and not ("attributes" in path)
            if not is_enum:
                normalized_value = normalize_verbatim(value)
                if not any(normalized_value in span for span in good):
                    errors.append(_error("VALUE_NOT_IN_EVIDENCE", _path((*path, "value")),
                                         "Raw source value must occur literally in its own evidence spans."))
            elif path[-1] == "region" and value in _REGION_PATTERNS:
                if not any(re.search(_REGION_PATTERNS[value], span, re.IGNORECASE) for span in good):
                    errors.append(_error("REGION_EVIDENCE_MISMATCH", _path(path), "Typed region needs an explicit corresponding region name/code in its evidence."))

    windows = label.get("impact_windows", [])
    windows = windows if isinstance(windows, list) else []
    window_map: dict[str, list[dict]] = {}
    for index, window in enumerate(windows):
        if not isinstance(window, dict):
            continue
        wid = window.get("window_id")
        if isinstance(wid, str):
            window_map.setdefault(wid, []).append(window)
            if not wid.strip():
                errors.append(_error("EMPTY_WINDOW_ID", f"/impact_windows/{index}/window_id", "window_id cannot be blank."))
            if wid != f"w{index + 1}":
                errors.append(_error("WINDOW_ID_SEQUENCE", f"/impact_windows/{index}/window_id", "window_id must be w1, w2, ... in output source order."))
        def field_value(key: str) -> Any:
            field = window.get(key, {})
            return field.get("value") if isinstance(field, dict) else None
        status = field_value("interval_status")
        if status == "BOUNDED" and any(field_value(key) in (None, "UNKNOWN") for key in ("start_text", "end_text")):
            errors.append(_error("BOUNDED_ENDPOINT_MISSING", f"/impact_windows/{index}", "BOUNDED requires explicit start_text and end_text."))
        if status == "OPEN_UNTIL_NOTICE" and field_value("end_text") not in (None, "UNKNOWN"):
            errors.append(_error("OPEN_INTERVAL_HAS_END", f"/impact_windows/{index}/end_text", "OPEN_UNTIL_NOTICE requires UNKNOWN end_text."))
        attrs = window.get("attributes", {})
        raw_region = attrs.get("region", {}) if isinstance(attrs, dict) else {}
        raw_region = raw_region.get("value") if isinstance(raw_region, dict) else None
        typed_region = field_value("region")
        if isinstance(raw_region, str) and raw_region != "UNKNOWN" and isinstance(typed_region, str) and typed_region in _REGION_PATTERNS:
            explicit_regions = {region for region, pattern in _REGION_PATTERNS.items()
                                if re.search(pattern, raw_region, re.IGNORECASE)}
            if explicit_regions and typed_region not in explicit_regions:
                errors.append(_error("ATTRIBUTE_REGION_CONFLICT", f"/impact_windows/{index}/attributes/region", "Raw region contradicts typed window region."))
    for wid, matching in window_map.items():
        if len(matching) > 1:
            errors.append(_error("DUPLICATE_WINDOW_ID", "/impact_windows", f"window_id {wid!r} is repeated."))

    quantities = label.get("quantities", [])
    for index, quantity in enumerate(quantities if isinstance(quantities, list) else []):
        if not isinstance(quantity, dict):
            continue
        qpath = ("quantities", index)
        good = _supported_spans(quantity.get("evidence_spans"), parts,
                                (*qpath, "evidence_spans"), errors)
        value = quantity.get("value_text")
        if isinstance(value, str) and value != "UNKNOWN":
            if not good:
                errors.append(_error("MISSING_EVIDENCE", _path(qpath), "Known quantity needs literal source evidence even when unbound."))
            if not normalize_verbatim(value).strip() or not any(normalize_verbatim(value) in span for span in good):
                errors.append(_error("VALUE_NOT_IN_EVIDENCE", _path((*qpath, "value_text")), "Quantity text must occur literally in its own evidence."))
        for field in ("unit", "role"):
            if quantity.get(field) not in (None, "UNKNOWN") and not good:
                errors.append(_error("MISSING_EVIDENCE", _path((*qpath, field)), f"Known {field} needs literal source evidence."))
        unit = quantity.get("unit")
        if unit in ("MW", "MWh", "minutes"):
            pattern = {
                "MW": r"\b(?:MW|megawatts?(?![- ]hours?\b))\b",
                "MWh": r"\b(?:MWh|megawatt[- ]hours?)\b",
                "minutes": r"\b(?:minutes?|mins?)\b",
            }[unit]
            if not any(re.search(pattern, span, re.IGNORECASE) for span in good):
                errors.append(_error("UNIT_EVIDENCE_MISMATCH", _path((*qpath, "unit")), "Unit is absent from quantity evidence."))
        status, reason, wid = (quantity.get(key) for key in ("binding_status", "binding_reason", "window_id"))
        if status == "BOUND":
            if reason != "BOUND_EXPLICIT_SOURCE_SCOPE":
                errors.append(_error("BINDING_REASON_MISMATCH", _path((*qpath, "binding_reason")), "BOUND requires BOUND_EXPLICIT_SOURCE_SCOPE."))
            matches = window_map.get(wid, []) if isinstance(wid, str) else []
            if len(matches) != 1:
                errors.append(_error("BAD_WINDOW_REFERENCE", _path((*qpath, "window_id")), "BOUND must reference exactly one real local window_id."))
            else:
                qa, wa = quantity.get("asset_id", {}), matches[0].get("asset_id", {})
                qasset = qa.get("value") if isinstance(qa, dict) else None
                wasset = wa.get("value") if isinstance(wa, dict) else None
                if isinstance(qasset, str) and qasset != "UNKNOWN" and (not isinstance(wasset, str) or normalize_verbatim(qasset) != normalize_verbatim(wasset)):
                    errors.append(_error("BOUND_ASSET_CONFLICT", _path((*qpath, "asset_id")), "Known quantity asset must match its bound window asset, or quantity asset must be UNKNOWN."))
        elif status == "UNKNOWN_RELATION":
            if wid is not None:
                errors.append(_error("UNBOUND_HAS_WINDOW", _path((*qpath, "window_id")), "UNKNOWN_RELATION requires null window_id."))
            if reason not in ("SOURCE_SCOPE_AMBIGUOUS", "SOURCE_SCOPE_ABSENT"):
                errors.append(_error("BINDING_REASON_MISMATCH", _path((*qpath, "binding_reason")), "UNKNOWN_RELATION requires SOURCE_SCOPE_AMBIGUOUS or SOURCE_SCOPE_ABSENT."))
    errors.extend(check_contamination(label, notice))
    return errors


def validate(label: object, notice_id: str, title: str, body: str) -> list[str]:
    """Compatibility API for a NEWSX-style runner."""
    return [f"{e['code']} {e['path']}: {e['message']}" for e in validate_label(
        label, {"notice_id": notice_id, "title": title, "body": body})]


def contamination_errors(label: object, notice_id: str, title: str, body: str) -> list[str]:
    return [f"{e['code']} {e['path']}: {e['message']}" for e in check_contamination(
        label, {"notice_id": notice_id, "title": title, "body": body})]


def parse_label_json(text: str) -> object:
    """Strict JSON, rejecting repeated keys and nonfinite numeric constants."""
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    def invalid_constant(value: str) -> Any:
        raise ValueError(f"Invalid JSON constant: {value}")
    return json.loads(text, object_pairs_hook=pairs_hook, parse_constant=invalid_constant)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", type=Path)
    parser.add_argument("--notice", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        import unittest
        suite = unittest.defaultTestLoader.discover(str(HERE), pattern="test_validate_notice_label.py")
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    if args.label is None or args.notice is None:
        parser.error("--label and --notice are required unless --self-test is used")
    try:
        label = parse_label_json(args.label.read_text(encoding="utf-8"))
        notice = json.loads(args.notice.read_text(encoding="utf-8"))
        errors = validate_label(label, notice)
    except (ValueError, TypeError) as exc:
        errors = [_error("PARSE_ERROR", "/", str(exc))]
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
