'Construct the numerical news feature projection.'
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone

AEST = timezone(timedelta(hours=10))
REGIONS = ("NSW1", "QLD1", "SA1", "TAS1", "VIC1")
TIERS = ("c1", "c2", "c3", "Unknown")
TYPES = ("GENERATOR_OUTAGE", "FUEL_SHORTAGE", "EXTREME_WEATHER", "MAINTENANCE",
         "SUPPLY_CONSTRAINT", "ABNORMAL_MARKET_CONDITION", "NETWORK", "DEMAND",
         "RENEWABLE", "RESERVE", "POLICY", "REGULATION", "RESIDENTIAL_SURVEY",
         "OTHER", "Unknown")
KINDS = ("FACT", "FORECAST", "ANALYSIS", "UNKNOWN")
LABEL_COLUMNS = tuple([f"tier_{x}" for x in TIERS] + [f"event_{x}" for x in TYPES]
                      + [f"kind_{x}" for x in KINDS] + [f"region_{x}" for x in REGIONS]
                      + ["forecast_target_day"] + [f"forecast_target_day_{x}" for x in REGIONS])
assert len(LABEL_COLUMNS) == 34

MONTHS = {name: index for index, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
MONTH = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
         r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
DATE_RE = re.compile(rf"(?<![A-Za-z0-9])(?:\d{{4}}-\d{{2}}-\d{{2}}|"
                     rf"\d{{1,2}}\s+{MONTH}\s+\d{{4}}|{MONTH}\s+\d{{1,2}},?\s+\d{{4}})"
                     rf"(?![A-Za-z0-9])", re.IGNORECASE)
TOKEN_RE = re.compile(r"[a-z0-9]+")


def utc(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if stamp.tzinfo is None:
        raise ValueError("timestamp needs explicit offset")
    return stamp.astimezone(timezone.utc)


def source_day(issue_time_utc, shift_days=0):
    if shift_days not in (0, 28):
        raise ValueError("unregistered placebo shift")
    return utc(issue_time_utc).astimezone(AEST).date() - timedelta(days=1 + shift_days)


def admitted(articles, issue_time_utc, shift_days=0):
    issue, day, seen, out = utc(issue_time_utc), source_day(issue_time_utc, shift_days), set(), []
    for article in articles:
        aid = str(article["article_id"])
        if aid in seen:
            raise ValueError(f"duplicate article ID {aid}")
        seen.add(aid)
        if (date.fromisoformat(article["publication_local_date"]) == day
                and utc(article["saved_version_available_utc"]) + timedelta(days=shift_days) <= issue):
            out.append(article)
    return out


def _one_date(text):
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return date.fromisoformat(text)
    words = text.replace(",", "").split()
    day, month, year = (int(words[0]), words[1], int(words[2])) if words[0].isdigit() else (int(words[1]), words[0], int(words[2]))
    return date(year, MONTHS[month[:3].lower()], day)


def absolute_interval(raw):

    if not raw or raw == "Unknown":
        return None
    if re.search(r"\b(?:UTC|GMT|AEDT|ACDT|NZST|NZDT)\b", raw, re.IGNORECASE):
        return None
    hits = list(DATE_RE.finditer(raw))
    if len(hits) not in (1, 2):
        return None
    try:
        days = [_one_date(hit.group()) for hit in hits]
    except (ValueError, KeyError, IndexError):
        return None
    if len(days) == 1:
        return days[0], days[0]
    between = raw[hits[0].end():hits[1].start()].strip().lower()
    return (days[0], days[1]) if between in ("to", "through", "until") and days[0] <= days[1] else None


def tokenize(text, stopwords):
    return Counter(token for token in TOKEN_RE.findall(text.lower())
                   if len(token) >= 3 and not token.isdigit() and token not in stopwords)


def metadata_features(articles, issue_time_utc):
    return {"article_count": len(admitted(articles, issue_time_utc))}


def label_features(articles, issue_time_utc, target_day_aest, *, shift_days=0, quote_only=False, failed_article_ids=()):
    failed = frozenset(str(aid) for aid in failed_article_ids)
    out = {column: 0 for column in LABEL_COLUMNS}
    for article in admitted(articles, issue_time_utc, shift_days):
        if str(article["article_id"]) in failed:
            continue
        tier = article["impact_level"]
        if tier not in TIERS:
            raise ValueError("invalid impact tier")
        out[f"tier_{tier}"] += 1
        statements = article["statements_json"]
        statements = json.loads(statements) if isinstance(statements, str) else statements
        flags = article["time_in_quote"]
        if len(statements) != len(flags) or len(statements) != int(article["statement_count"]):
            raise ValueError("statement and time-flag lengths differ")
        types, regions_in_article = set(), set()
        for statement, time_in_quote in zip(statements, flags, strict=True):
            kind, event_type, regions = statement["kind"], statement["event_type"], statement["regions"]
            if kind not in KINDS or event_type not in TYPES or not isinstance(regions, list) or not regions:
                raise ValueError("invalid statement kind, event type or regions")
            if any(r not in (*REGIONS, "Unknown") for r in regions) or ("Unknown" in regions and len(regions) > 1):
                raise ValueError("invalid structured region")
            types.add(event_type)
            regions_in_article.update(r for r in regions if r in REGIONS)
            out[f"kind_{kind}"] += 1
            time = statement["event_time_text"] if not quote_only or bool(time_in_quote) else "Unknown"
            interval = absolute_interval(time) if kind == "FORECAST" else None
            if interval is not None and interval[0] <= target_day_aest <= interval[1]:
                out["forecast_target_day"] += 1
                for region in regions:
                    if region in REGIONS:
                        out[f"forecast_target_day_{region}"] += 1
        for event_type in types:
            out[f"event_{event_type}"] += 1
        for region in regions_in_article:
            out[f"region_{region}"] += 1
    return out


def previous_day_failure_report(articles, issue_time_utc, failed_article_ids):
    'Report failed articles for the preceding AEST calendar date.'
    failed = frozenset(str(aid) for aid in failed_article_ids)
    day = source_day(issue_time_utc)
    ids = [str(a["article_id"]) for a in articles
           if str(a["article_id"]) in failed
           and date.fromisoformat(a["publication_local_date"]) == day]
    return {"previous_day_failed_present": bool(ids),
            "previous_day_failed_count": len(ids)}
