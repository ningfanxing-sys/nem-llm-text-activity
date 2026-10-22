"""CONF frozen feature projection skeletons; no I/O, fit, or import-time work.

All document-valued entry points require a later ExecutionPermit. Normalized
records are supplied by the separately frozen panel/NRX assembler, never loaded
here. The frozen FINAL3 resolver/14-column projection is injected explicitly.
"""
from __future__ import annotations
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import re
from typing import Callable, Mapping, Sequence
try:
    from .guard import require_execution
except ImportError:
    from guard import require_execution

AEST = timezone(timedelta(hours=10))
REGIONS = ("NSW1", "QLD1", "SA1", "TAS1", "VIC1")
ATTRIBUTES = ("impact_timeframe", "root_cause", "affected_infrastructure",
              "region", "energy_resource", "operational_indicators")
TIERS = ("c1", "c2", "c3", "Unknown")
TYPES = ("GENERATOR_OUTAGE", "FUEL_SHORTAGE", "EXTREME_WEATHER", "MAINTENANCE",
         "SUPPLY_CONSTRAINT", "ABNORMAL_MARKET_CONDITION", "NETWORK", "DEMAND",
         "RENEWABLE", "RESERVE", "POLICY", "REGULATION", "RESIDENTIAL_SURVEY",
         "OTHER", "Unknown")
KINDS = ("FACT", "FORECAST", "ANALYSIS", "UNKNOWN")
COUNT_COLUMNS = tuple([f"tier_{x}" for x in TIERS] + [f"event_{x}" for x in TYPES]
                      + [f"kind_{x}" for x in KINDS] + [f"region_{x}" for x in REGIONS]
                      + ["forecast_target_day"] + [f"forecast_target_day_{x}" for x in REGIONS])
L14_COLUMNS = ("nw_res_local", "nw_res_foreign", "nw_con_local", "nw_con_foreign",
               "nw_int_local", "nw_out_local", "nw_out_foreign", "nw_any_local",
               "nw_res_deficit_mw_local", "nw_res_min_avail_mw_local",
               "nw_minutes_since_start_local", "nw_minutes_to_end_local",
               "nw_new_local_6h", "nw_cancel_local_6h")
LAZ_COLUMNS = ("laz_UMM", "laz_Failure", "laz_NuclearFailure", "laz_HydroFailure",
               "laz_CoalFailure", "laz_failure_coal_gas_oil",
               "laz_failure_nuclear_hydro", "laz_SizeOfOutage_MW")
PERMUTATION_SEED = 20261001


def utc(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(stamp, datetime) or stamp.tzinfo is None:
        raise ValueError("clock must have an explicit offset")
    return stamp.astimezone(timezone.utc)


def value(field):
    """NRX source-only attributes use {value,evidence_spans}; NEWSX uses strings."""
    answer = field.get("value", "UNKNOWN") if isinstance(field, Mapping) else field
    return "UNKNOWN" if answer in (None, "", "Unknown", "UNKNOWN") else str(answer)


def news_support(articles, issue, *, permit, hours=72, shift_days=0):
    require_execution(permit)
    if hours not in (72, 24) or shift_days not in (0, 28):
        raise ValueError("unregistered window/shift")
    issue = utc(issue)
    left = issue - timedelta(hours=hours)
    admitted, seen = [], set()
    for article in articles:
        aid = str(article["article_id"])
        if aid in seen:
            raise ValueError("one deterministic version per article must be resolved upstream")
        seen.add(aid)
        available = utc(article["saved_version_available_utc"]) + timedelta(days=shift_days)
        publication = utc(article["publication_utc"]) + timedelta(days=shift_days)
        if publication <= issue and left < available <= issue:
            admitted.append(article)
    return sorted(admitted, key=lambda a: (utc(a["saved_version_available_utc"]), str(a["article_id"])))


def news_metadata(support, *, permit):
    require_execution(permit)
    return {"article_count": len(support),
            "extraction_failed_count": sum(a["extraction_status"] != "SUCCESS" for a in support)}


def news_count(support, target_day: date, absolute_interval: Callable, *, permit, shift_days=0):
    """Existing 34-column projection on matched support; failed labels stay Unknown.

    absolute_interval is the hash-pinned NEWSD absolute-date parser; add shift to
    both ends before target-day membership, never to only the document clock.
    """
    require_execution(permit)
    if shift_days not in (0, 28):
        raise ValueError("unregistered shift")
    out = dict.fromkeys(COUNT_COLUMNS, 0)
    for article in support:
        if article["extraction_status"] != "SUCCESS":
            out["tier_Unknown"] += 1
            continue
        tier = article["impact_level"]
        if tier not in TIERS:
            raise ValueError("unknown tier is an explicit enum, not a catch-all")
        out[f"tier_{tier}"] += 1
        statements = article["statements_json"]
        if isinstance(statements, str):
            statements = json.loads(statements)
        types, regions_seen = set(), set()
        for statement in statements:
            kind, typ, regions = statement["kind"], statement["event_type"], statement["regions"]
            if kind not in KINDS or typ not in TYPES or not isinstance(regions, list):
                raise ValueError("NEWSX v4 contract violation")
            types.add(typ)
            regions_seen.update(r for r in regions if r in REGIONS)
            out[f"kind_{kind}"] += 1
            interval = absolute_interval(statement["event_time_text"]) if kind == "FORECAST" else None
            if interval:
                start, end = (d + timedelta(days=shift_days) for d in interval)
                if start <= target_day <= end:
                    out["forecast_target_day"] += 1
                    for r in regions:
                        if r in REGIONS:
                            out[f"forecast_target_day_{r}"] += 1
        for typ in types:
            out[f"event_{typ}"] += 1
        for r in regions_seen:
            out[f"region_{r}"] += 1
    return out


def chen_news_text(support, *, permit):
    """One whole concatenated corpus, not article-wise embedding averages."""
    require_execution(permit)
    blocks = []
    for article in support:
        if article["extraction_status"] != "SUCCESS":
            fields = ["impact_level=UNKNOWN"] + [f"{name}=UNKNOWN" for name in ATTRIBUTES]
        else:
            attrs = article["attributes_json"]
            attrs = json.loads(attrs) if isinstance(attrs, str) else attrs
            fields = [f"impact_level={value(article['impact_level'])}"]
            fields += [f"{name}={value(attrs[name])}" for name in ATTRIBUTES]
        blocks.append("\n".join(fields))
    return "\n\n".join(blocks)


def raw_news_text(support, *, permit):
    require_execution(permit)
    return "\n\n".join(a["title"] + "\n\n" + a["body"] for a in support)


def bai_tokens(text, stopwords):
    """Bai formal title/body word-frequency adaptation; raw counts, no TF-IDF."""
    return Counter(t for t in re.findall(r"[a-z0-9]+", text.lower())
                   if len(t) >= 3 and not t.isdigit() and t not in stopwords)


def bai_counts(support, vocabulary, stopwords, *, permit):
    require_execution(permit)
    counts = {f: Counter() for f in ("title", "body")}
    for article in support:
        for f in counts:
            counts[f].update(bai_tokens(article[f], stopwords))
    return {f"bai_{f}_{word}": counts[f][word] for f in ("title", "body") for word in vocabulary[f]}


def select_bai_vocabulary(training_daily_series, training_price_series, *, permit,
                          frozen_stopwords, training_documents, adf_and_bilateral_granger):
    """Interface for the later training-only Bai selection, with no default fit.

    Callback must return an audit row per candidate: ADF/AIC differencing status,
    lag selected by AIC from {1,7,30,90}, forward/reverse OLS F-test p-values.
    Series and outcome clocks must already pass the 2021-10..2024-12 gate. No
    confirmation/2025 outcome can be supplied for this selection.
    """
    require_execution(permit)
    if any(not "2021-10-01" <= str(d) <= "2024-12-31" for d in training_daily_series):
        raise ValueError("Bai preprocessing is training-only")
    if set(training_daily_series) != set(training_price_series):
        raise ValueError("complete observed same-day training series required")
    # Corpus thresholds count each admitted source article once, not once
    # per repeated 72h rolling window. Daily rolling series are used only for
    # the training-side ADF/Granger time-series tests.
    corpus = list(training_documents)
    identities = [str(doc["article_id"]) for doc in corpus]
    if len(identities) != len(set(identities)):
        raise ValueError("Bai corpus requires one frozen version per unique training article")
    if any(not "2021-10-01" <= str(doc["first_admitted_issue_aest"])[:10] <= "2024-12-31" for doc in corpus):
        raise ValueError("Bai corpus includes a source not admitted to nominal training")
    audit, selected = [], {"title": [], "body": []}
    for field, threshold in (("title", 200), ("body", 5000)):
        candidates = Counter()
        for doc in corpus:
            candidates.update(bai_tokens(doc[field], frozen_stopwords))
        for word in sorted(w for w, n in candidates.items() if n >= threshold):
            row = adf_and_bilateral_granger(field, word, training_daily_series,
                    training_price_series, lag_candidates=(1, 7, 30, 90), adf_alpha=.05,
                    granger_alpha=.05, adf_regression="c", lag_criterion="AIC")
            row = {**row, "field": field, "word": word, "training_count": candidates[word]}
            audit.append(row)
            if (math.isfinite(row.get("forward_p", math.nan)) and
                math.isfinite(row.get("reverse_p", math.nan)) and
                row["forward_p"] < .05 <= row["reverse_p"]):
                selected[field].append(word)
    return {"vocabulary": selected, "audit": audit,
            "state": "AVAILABLE" if any(selected.values()) else "BAI_UNAVAILABLE_EMPTY_VOCABULARY"}


def notice_prefix(notices, issue, *, permit, shift_days=0):
    require_execution(permit)
    if shift_days not in (0, 28):
        raise ValueError("unregistered shift")
    issue = utc(issue)
    return sorted((n for n in notices if utc(n["available_utc"]) + timedelta(days=shift_days) <= issue),
                  key=lambda n: (utc(n["available_utc"]), str(n["notice_id"])))


def notice_metadata(prefix, issue, *, permit, shift_days=0):
    require_execution(permit)
    issue = utc(issue)
    recent = [n for n in prefix if issue - timedelta(hours=6) <
              utc(n["available_utc"]) + timedelta(days=shift_days) <= issue]
    return {"notice_prefix_count": len({str(n["notice_id"]) for n in prefix}),
            "notice_arrivals_6h": len({str(n["notice_id"]) for n in recent}),
            "notice_failed_prefix_count": sum(n["extraction_status"] != "SUCCESS" for n in prefix)}


def chen_notice_text(prefix, *, permit):
    require_execution(permit)
    blocks = []
    for notice in prefix:
        if notice["extraction_status"] != "SUCCESS":
            blocks.append("\n".join(f"{name}=UNKNOWN" for name in ATTRIBUTES))
            continue
        windows = notice["nrx_label"]["impact_windows"]
        if not windows:
            blocks.append("\n".join(f"{name}=UNKNOWN" for name in ATTRIBUTES))
        for window in windows:  # schema order, never reorder after seeing outcomes
            blocks.append("\n".join(f"{name}={value(window['attributes'][name])}" for name in ATTRIBUTES))
    return "\n\n".join(blocks)


def l14_projection(normalized_records, origins, frozen_final3_features, *, permit):
    """Inject exactly hash-pinned FINAL3 state/features after NRX-schema bridge.

    The upstream bridge populates FINAL3 records from new labels alone for all
    schema fields. Shared source relation metadata follows FINAL3. It must also
    supply NRX sidecar event-class/fuel/unique quantity bindings for L_Laz.
    """
    require_execution(permit)
    projected = frozen_final3_features(origins, normalized_records)
    columns = tuple(c for c in projected.columns if c in L14_COLUMNS)
    if columns != L14_COLUMNS:
        raise ValueError("FINAL3 14-column order drift")
    return projected.loc[:, L14_COLUMNS]


def laz_overlap_components(resolved_records, issue, delivery_start, delivery_end, region, *, permit):
    """Lazarczyk-exact overlap components on an explicitly adapted NEM sample.

    Records must be forward-resolved at issue: updates/closures never backfill.
    Message counts deduplicate source notice IDs. Independent failure MW add;
    a sum is NaN when any relevant failure lacks uniquely bound source MW or
    event identity (unknown is never turned into zero). No Nordic role names.
    """
    require_execution(permit)
    issue, left, right = map(utc, (issue, delivery_start, delivery_end))
    if right <= left:
        raise ValueError("delivery interval must be nonempty")
    live = []
    for r in resolved_records:
        if utc(r["available_utc"]) > issue or r["region"] != region or not r["feature_eligible"]:
            continue
        if r.get("closed_asof_issue", False) or r.get("start_utc") is None:
            continue
        start = utc(r["start_utc"])
        end = utc(r["end_utc"]) if r.get("end_utc") is not None else None
        if r["interval_status"] == "OPEN_UNTIL_NOTICE":
            if issue - utc(r["available_utc"]) >= timedelta(hours=48):
                continue
        elif r["interval_status"] != "BOUNDED" or end is None:
            continue
        if start < right and (end is None or end > left):
            live.append(r)
    # The NEM operational sample is broader than Nordic capacity messages. UMM
    # counts every overlap-qualified eligible message, without conditioning on a
    # recognized failure/maintenance type; this sample deviation is disclosed.
    substantive = live
    failures = [r for r in live if r["event_class"] == "FAILURE"]
    count = lambda rows: len({str(r["notice_id"]) for r in rows})
    out = dict(zip(LAZ_COLUMNS[:7], [count(substantive), count(failures),
        count([r for r in failures if r["fuel_type"] == "NUCLEAR"]),
        count([r for r in failures if r["fuel_type"] == "HYDRO"]),
        count([r for r in failures if r["fuel_type"] == "COAL"]),
        count([r for r in failures if r["fuel_type"] in ("COAL", "GAS", "OIL")]),
        count([r for r in failures if r["fuel_type"] in ("NUCLEAR", "HYDRO")])]))
    unique, missing = {}, 0
    for r in failures:
        identity = r.get("resolved_event_identity")
        quantities = r.get("bound_loss_mw", ())
        if not identity or not r.get("identity_reliable", False) or not quantities:
            missing += 1
            continue
        # upstream unique quantity IDs prevent duplicating an MW per window
        for quantity_id, mw in quantities:
            key = (identity, str(quantity_id))
            if not math.isfinite(mw) or mw < 0:
                missing += 1
            elif key in unique and unique[key] != mw:
                raise ValueError("conflicting latest-version outage capacity")
            else:
                unique[key] = float(mw)
    out[LAZ_COLUMNS[-1]] = math.nan if missing else sum(unique.values())
    sidecar = {"failure_missing_or_unbound_mw_records": missing,
               "failure_unknown_fuel_records": sum(r["fuel_type"] == "UNKNOWN" for r in failures),
               "overlapping_records": len(live), "distinct_failure_notices": count(failures)}
    return out, sidecar


def shift_normalized_clocks(record, *, permit):
    """Derived clocks/event dates shift together; immutable source literals stay."""
    require_execution(permit)
    out = dict(record)
    for key in ("publication_utc", "modified_utc", "saved_version_available_utc", "available_utc",
                "start_utc", "end_utc", "action_effective_utc", "forecast_target_utc"):
        if out.get(key) is not None:
            out[key] = utc(out[key]) + timedelta(days=28)
    for key in ("forecast_target_date", "event_start_date", "event_end_date"):
        if out.get(key) is not None:
            d = date.fromisoformat(out[key]) if isinstance(out[key], str) else out[key]
            out[key] = d + timedelta(days=28)
    return out


def activity_matched_donor(recipient, earlier_bundles, *, permit):
    """Deterministic past-only within-month bundle reassignment; no relaxation.

    A globally bijective calendar permutation cannot also be past-only for the
    earliest origins. This implementation is conditional bundle reassignment;
    donor reuse across origins is reported rather than hidden as a bijection.
    """
    require_execution(permit)
    origin = utc(recipient["issue_utc"])
    day = origin.astimezone(AEST).date()
    recipient_sources = tuple(sorted(map(str, recipient["source_document_ids"])))
    if len(set(recipient_sources)) != recipient["document_count"]:
        raise ValueError("recipient document keys/count disagree")
    choices = {}
    for donor in earlier_bundles:
        stamp = utc(donor["issue_utc"])
        other_day = stamp.astimezone(AEST).date()
        donor_sources = tuple(sorted(map(str, donor["source_document_ids"])))
        if len(set(donor_sources)) != donor["document_count"]:
            raise ValueError("donor document keys/count disagree")
        if (stamp < origin and utc(donor["latest_content_available_utc"]) <= origin and
            donor_sources != recipient_sources and donor["region"] == recipient["region"] and
            other_day.strftime("%Y-%m") == day.strftime("%Y-%m") and other_day.weekday() == day.weekday() and
            donor["document_count"] == recipient["document_count"] and
            tuple(donor["extraction_status_mask"]) == tuple(recipient["extraction_status_mask"])):
            # Repeated origins with the same source documents are one donor, not
            # extra independent article bundles. Choose its earliest legal slot.
            previous = choices.get(donor_sources)
            if previous is None or (stamp, str(donor["bundle_id"])) < (
                    utc(previous["issue_utc"]), str(previous["bundle_id"])):
                choices[donor_sources] = donor
    if len(choices) < 2:
        return None, {"state": "UNMATCHED", "eligible_donors": len(choices)}
    ranked = sorted(choices.values(), key=lambda d: hashlib.sha256(
        (f"{PERMUTATION_SEED}|{recipient['bundle_id']}|" +
         json.dumps(sorted(map(str, d["source_document_ids"])), separators=(",", ":"))).encode()).hexdigest())
    donor = ranked[0]
    return donor, {"state": "MATCHED", "eligible_donors": len(choices),
        "donor_calendar_offset_days": (day - utc(donor["issue_utc"]).astimezone(AEST).date()).days}


def relocate_content_dates(content, donor_publication, slot_publication, *, permit):
    """Transfer parsed event dates by publication offset; never rewrite raw text."""
    require_execution(permit)
    delta = utc(slot_publication) - utc(donor_publication)
    out = dict(content)
    for key in ("start_utc", "end_utc", "action_effective_utc", "forecast_target_utc"):
        if out.get(key) is not None:
            out[key] = utc(out[key]) + delta
    day_delta = (utc(slot_publication).astimezone(AEST).date() -
                 utc(donor_publication).astimezone(AEST).date())
    for key in ("forecast_target_date", "event_start_date", "event_end_date"):
        if out.get(key) is not None:
            d = date.fromisoformat(out[key]) if isinstance(out[key], str) else out[key]
            out[key] = d + day_delta
    return out


def notice_tfn2_counts(prefix, issue, vocabulary, stopwords, *, permit):
    """Existing T comparator: raw same-source title/body counts over 24 h."""
    require_execution(permit)
    stamp = utc(issue)
    support = [n for n in prefix if stamp - timedelta(hours=24) < utc(n["available_utc"]) <= stamp]
    counts = {field: Counter() for field in ("title", "body")}
    for notice in support:
        for field in counts:
            counts[field].update(bai_tokens(notice[field], stopwords))
    return {f"tfn2_{field}_{word}": counts[field][word]
            for field in ("title", "body") for word in vocabulary[field]}
