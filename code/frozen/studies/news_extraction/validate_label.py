'Validate news labels against the schema and quoted source evidence.'
from __future__ import annotations

import json
from pathlib import Path
import re
import unicodedata
from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
_TYPOGRAPHY = str.maketrans({
    "\u2013": "-", "\u2014": "-", "\u2212": "-",
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u00a0": " ",
})


def normalize_verbatim(value: str) -> str:

    value = unicodedata.normalize("NFKC", value).translate(_TYPOGRAPHY)
    return re.sub(r"\s+", " ", value)


def quote_grounding_flags(statement: dict) -> tuple[bool, bool]:
    'Check the time and magnitude quotations for one extracted statement.'
    quote = statement.get("evidence_quote")
    normalized_quote = normalize_verbatim(quote) if isinstance(quote, str) else ""

    def present(field: str) -> bool:
        value = statement.get(field)
        if not isinstance(value, str) or value == "Unknown":
            return False
        normalized_value = normalize_verbatim(value)
        return bool(normalized_value.strip()) and normalized_value in normalized_quote

    return present("event_time_text"), present("magnitude_text")


def validate(label: object, article_id: str, article_text: str) -> list[str]:
    schema = json.loads((HERE / "schema.json").read_text(encoding="utf-8"))
    errors = ["schema: " + e.message for e in Draft202012Validator(schema).iter_errors(label)]
    if not isinstance(label, dict):
        return errors
    if label.get("article_id") != article_id:
        errors.append("article_id mismatch")
    quote = label.get("impact_evidence_quote", "")
    if label.get("impact_level") == "Unknown" and quote:
        errors.append("Unknown impact must have empty quote")
    if label.get("impact_level") not in (None, "Unknown") and not quote:
        errors.append("known impact needs evidence quote")
    normalized_article = normalize_verbatim(article_text)
    if isinstance(quote, str) and quote and normalize_verbatim(quote) not in normalized_article:
        errors.append("impact evidence is not a verbatim source substring")
    for i, statement in enumerate(label.get("statements", []) if isinstance(label.get("statements", []), list) else []):
        if not isinstance(statement, dict):
            continue
        q = statement.get("evidence_quote", "")
        if not isinstance(q, str) or not q:
            errors.append(f"statement {i} evidence quote is empty")
        if isinstance(q, str) and q and normalize_verbatim(q) not in normalized_article:
            errors.append(f"statement {i} evidence is not a verbatim source substring")
        regions = statement.get("regions", [])
        if isinstance(regions, list) and len(set(map(str, regions))) != len(regions):
            errors.append(f"statement {i} repeats a region")
        if isinstance(regions, list) and "Unknown" in regions and len(regions) > 1:
            errors.append(f"statement {i} mixes Unknown and known regions")
        for field in ("event_time_text", "magnitude_text"):
            v = statement.get(field)
            if isinstance(v, str) and v != "Unknown":
                normalized_value = normalize_verbatim(v)
                if not normalized_value.strip() or normalized_value not in normalized_article:
                    errors.append(f"statement {i} {field} not literal in article text")
    return errors


def self_test() -> None:

    assert normalize_verbatim("Ａ–Ｂ—Ｃ−Ｄ\u00a0‘x’ “y”\n z") == "A-B-C-D 'x' \"y\" z"
    article = "A unit fell by 10–20 MW. It returns on Friday."
    quote = "A unit fell by 10-20 MW. It returns on Friday."
    label = {
        "article_id": "SYNTHETIC-SELF-TEST",
        "impact_level": "c2",
        "impact_evidence_quote": quote,
        "attributes": {key: "Unknown" for key in (
            "impact_timeframe", "root_cause", "affected_infrastructure",
            "region", "energy_resource", "operational_indicators")},
        "statements": [{
            "kind": "FACT", "event_type": "MAINTENANCE", "regions": ["Unknown"],
            "event_time_text": "Friday", "direction": "Unknown",
            "magnitude_text": "10–20 MW", "source_attribution": "Unknown",
            "evidence_quote": quote,
        }],
    }
    assert validate(label, label["article_id"], article) == []
    label["statements"][0]["evidence_quote"] = "A unit fell by 10-20 MW."
    assert validate(label, label["article_id"], article) == []
    assert quote_grounding_flags(label["statements"][0]) == (False, True)
    label["statements"][0]["event_time_text"] = "Saturday"
    assert "statement 0 event_time_text not literal in article text" in validate(label, label["article_id"], article)
    label["impact_evidence_quote"] = "A unit rose by 10-20 MW."
    assert "impact evidence is not a verbatim source substring" in validate(
        label, label["article_id"], article)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", required=True)
    parser.parse_args()
    self_test()
    print('news_extraction validator synthetic self-test: OK')
