'Assemble matched notice features from events, windows and quantities.'
from __future__ import annotations
import importlib.util
import json
import re
from collections import defaultdict
from pathlib import Path
import numpy as np
import pandas as pd

PROJ = Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location('_final_sealed_v2', PROJ / 'notice_assembly/notice_event_records.py')
v2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v2)
sealed_nw = v2.sealed_nw
COLUMNS, REGIONS, KINDS = v2.COLUMNS, v2.REGIONS, v2.KINDS
ROOT, REGISTRY, LABELS = v2.ROOT, v2.REGISTRY, v2.LABELS
NEM_OFFSET, RECENT, BIG = v2.NEM_OFFSET, v2.RECENT, v2.BIG
RECORD_COLUMNS = v2.RECORD_COLUMNS
load_population = v2.load_population
frame = v2.frame
_ns = v2._ns

REGION_TOKEN = r'(?:New South Wales|South Australia|Queensland|Tasmania|Victoria|NSW1?|QLD1?|SA1?|TAS1?|VIC1?)'
REGEX_REGION = re.compile(r'(?<![A-Za-z0-9])(' + REGION_TOKEN + r')(?![A-Za-z0-9])', re.I)
DIRECTION = re.compile(r'(?<![A-Za-z0-9])(' + REGION_TOKEN + r')\s*(?:to|->|→|–|-)\s*(' + REGION_TOKEN + r')(?![A-Za-z0-9])', re.I)
MONTH = r'(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)'
WEEKDAY = r'(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*,?\s+)?'
DATE = r'(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}(?:st|nd|rd|th)?\s+' + MONTH + r'(?:\s*,?\s+(?:19|20)\d{2})?|' + MONTH + r'\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s+\d{4})?)'
TIME = r'(?:(?:[012]?\d:[0-5]\d(?::[0-5]\d)?)(?:\s*(?:hrs?|hours))?|[012]\d[0-5]\d\s*(?:hrs?|hours))'
BARE_TIME = r'(?:(?:[012]?\d:[0-5]\d(?::[0-5]\d)?)(?:\s*(?:hrs?|hours))?|[012]\d[0-5]\d(?:\s*(?:hrs?|hours))?)'
ENDPOINT = r'(?:' + WEEKDAY + DATE + r'\s+(?:at\s+)?' + TIME + r'|' + TIME + r'(?:\s+(?:on\s+)?' + WEEKDAY + DATE + r')?|' + WEEKDAY + DATE + r')'
ENDPOINT_RE = re.compile(ENDPOINT, re.I)
INTERVAL_RE = re.compile(r'(?<![\d/])(?P<s>' + ENDPOINT + r')\s*(?:to|until|through|–|-)\s*(?P<e>until\s+further\s+notice|further\s+notice|' + ENDPOINT + r')', re.I)
BARE_INTERVAL_RE = re.compile(r'(?<![\d/])(?P<s>' + BARE_TIME + r')\s*(?:to|until|–|-)\s*(?P<e>' + BARE_TIME + r')\s+(?:on\s+)?(?P<d>' + WEEKDAY + DATE + r')', re.I)
START_RE = re.compile(r'\b(?:from|invoked\s+(?:at|from)|commenced\s+(?:operating\s+)?(?:at|from)|started\s+(?:operating\s+)?(?:at|from)|changes\s+at)\s*(' + ENDPOINT + r')(?:[^.!?\n]{0,120}?\buntil\s+further\s+notice)?', re.I)
INSTANT_RE = re.compile(r'\bAt\s+(' + ENDPOINT + r')', re.I)
EVENT_AT_RE = re.compile(r'\b(?:tripped|trip|occurred|restored|returned\s+to\s+service|commenced|started|ended)\s+(?:at\s+|from\s+)(' + ENDPOINT + r')', re.I)
ACTION_RE = re.compile(r'(?P<action>\bwill\s+(?:end|cease|be\s+cancelled|be\s+canceled)|\b(?:is\s+|was\s+|has\s+been\s+)?cancelled|\b(?:is\s+|was\s+|has\s+been\s+)?canceled|\brevoked|\bceased\s+operating|\b(?:has\s+)?ended|\breturned\s+to\s+service|\bCancellation(?:\s+time)?)\s*(?:(?:at|from|on)\s*:?\s*|:\s*)?(?P<time>' + ENDPOINT + r')', re.I)
DATE_FROM_INTERVAL_RE = re.compile(r'(?P<d>' + WEEKDAY + DATE + r')\s+from\s+(?P<s>' + BARE_TIME + r')\s*(?:to|until|–|-)\s*(?P<e>' + BARE_TIME + r')', re.I)
FORECAST_END_RE = re.compile(r'\bforecast\s+to\s+(?:exist|apply)\s+until\s+(' + ENDPOINT + r')', re.I)
EXPECTED_END_RE = re.compile(r'\bExpected\s+duration\s*:\s*(' + ENDPOINT + r')', re.I)
TRADING_START_RE = re.compile(r'\btrading\s+interval\s+starting\s+(' + ENDPOINT + r')', re.I)
MSL_CLOSE_RE = re.compile(r'(?P<action>\bCancellation\s*-?\s*(?:Forecast|Actual)\s+MSL\s*[123]\s*-?\s*' + REGION_TOKEN + r'\s+Region)\s+at\s+(?P<time>' + ENDPOINT + r')', re.I)
CEASE_IMPACT_RE = re.compile(r'(?P<action>\bceased\s+to\s+impact[^.!?]{0,180}?\bas\s+at)\s+(?P<time>' + ENDPOINT + r')', re.I)
STANDALONE_OPEN_RE = re.compile(r'\b(?:controls[^.!?]{0,130}?unavailable|constraint\s+sets?(?:\(s\))?[^.!?]{0,100}?invoked)\s+until\s+further\s+notice\b', re.I)
DIRECTION_ISSUED_RE = re.compile(r'\bDirection\s+issued\s+to:[^.!?]{1,220}?\bat\s+(' + ENDPOINT + r')', re.I)
DIRECTION_ACTION_RE = re.compile(r'\b(?:follow\s+dispatch\s+targets|synchroni[sz]e(?:\s+\d+\s+units)?)\s+at\s+(' + ENDPOINT + r')', re.I)
CONSTRAINT_ID = re.compile(r'(?<![A-Za-z0-9])NRM_[A-Za-z0-9_]+(?![A-Za-z0-9])', re.I)
NEGATIVE = re.compile(r'\b(?:identifies?\s+no\s+Low\s+Reserve\s+Conditions|No\s+LOR\s+condition\s+is\s+currently\s+forecast)', re.I)


def _region(token):
    token = token.upper()
    return v2.REGION_NAMES.get(token, token.removesuffix('1') + '1')


def source_regions(title, text):
    'Select event regions from explicit fields, clauses, endpoints and source text.'
    title, text = str(title), str(text)
    fields = list(re.finditer(r'\bRegion\s*:\s*(' + REGION_TOKEN + r')(?![A-Za-z0-9])', text, re.I))
    field = fields[0] if fields else None
    body = v2._body_event_regions(text)
    explicit_event_regions = {_region(m) for m in v2.BODY_CONDITION_REGION.findall(text)}
    directions = [(m.group(0), _region(m.group(1)), _region(m.group(2))) for m in DIRECTION.finditer(text)]
    field_regions = {_region(m.group(1)) for m in fields}
    if len(field_regions) > 1 or (field_regions and explicit_event_regions and field_regions != explicit_event_regions):
        return [], 'CONFLICTING_EXPLICIT_REGION_FIELDS', ' | '.join(m.group(0) for m in fields), directions
    if field:
        return [_region(field.group(1))], 'EXPLICIT_REGION_FIELD', field.group(0), directions
    if body:
        return list(body), 'EXPLICIT_EVENT_REGION_CLAUSE', '; '.join(body), directions
    generator_scope = re.search(r'\b(?:includes?|include)\s+(?:the\s+)?generators\s+in\s+([^.!?]{1,240}?)(?:\bon\s+the\s+left|\bas\s+well|\bLHS|[.!?]|$)', text, re.I)
    if generator_scope:
        matches = list(REGEX_REGION.finditer(generator_scope.group(1)))
        if matches:
            return sorted({_region(m.group(1)) for m in matches}), 'EXPLICIT_GENERATOR_GEOGRAPHY_CLAUSE', generator_scope.group(0), directions
    if directions:
        regs = sorted({r for _, a, b in directions for r in (a, b)})
        return regs, 'EXPLICIT_DIRECTIONAL_ENDPOINTS', ' | '.join(x[0] for x in directions), directions
    title_hits = list(REGEX_REGION.finditer(title))
    if title_hits:
        return sorted({_region(m.group(1)) for m in title_hits}), 'EXPLICIT_TITLE_REGION', ' | '.join(m.group(0) for m in title_hits), directions
    scoped = re.split(r'The NEM Local Temperature Alert Levels are:|Support Information:|For further information|Further information is available', text, flags=re.I)[0]
    matches = list(REGEX_REGION.finditer(scoped))
    if matches:
        return sorted({_region(m.group(1)) for m in matches}), 'EXPLICIT_SOURCE_REGION_TOKEN', ' | '.join(m.group(0) for m in matches), directions
    return [], 'UNRESOLVED_TEXTUAL_GEOGRAPHY', '', directions


def rule_regions(title, text):
    return source_regions(title, text)[0]


def source_category(notice_type, title, text):
    nt = str(notice_type)
    if nt == 'MARKET SYSTEMS':
        return 'ADMINISTRATIVE_SYSTEM', 'OTHER', False
    if nt == 'SETTLEMENTS RESIDUE' and re.search(r'NRM_|negative\s+(?:settlement\s+)?residu', title + ' ' + text, re.I):
        return 'NRM_CONSTRAINT', 'CONSTRAINT', True
    if nt in ('CONSTRAINTS', 'RECLASSIFY CONTINGENCY', 'PROTECTED EVENT'):
        return 'OPERATING_CONSTRAINT', 'CONSTRAINT', True
    if nt == 'MARKET SUSPENSION':
        return 'MARKET_SUSPENSION', 'OTHER', True
    if nt == 'ADMINISTERED PRICE CAP':
        return 'ADMINISTERED_PRICE', 'OTHER', True
    if 'MINIMUM' in nt and 'LOAD' in nt:
        return 'MINIMUM_LOAD', 'OTHER', True
    if nt == 'INTER-REGIONAL TRANSFER':
        return 'INTERCONNECTOR_EVENT', 'OUTAGE', True
    if NEGATIVE.search(text):
        return 'NEGATIVE_RESERVE_STATE', 'RESERVE', False
    return nt, v2.rule_kind(nt, title), True


def rule_kind(notice_type, title, text=''):
    return source_category(notice_type, title, text)[1]


def parse_nem(text, anchor_local):
    'Parse literal notice endpoints using fixed UTC+10 local time.'
    if not isinstance(text, str) or not text.strip() or re.search(r'unknown|further\s+(?:notice|advice)', text, re.I):
        return None, None
    clean = re.sub(r'(?<=\d)(?:st|nd|rd|th)\b', '', text, flags=re.I)
    clean = re.sub(r'\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b', '', clean, flags=re.I)
    clean = re.sub(r'(?<=\d)-\s*(?=hrs?\b)', ' ', clean, flags=re.I)
    clean = re.sub(r'\s+', ' ', clean).strip()
    date = None; stamp = None; year_missing = False
    try:
        date = re.search(r'(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)', clean)
        if date:
            y, mo, d = map(int, date.groups()); stamp = pd.Timestamp(y, mo, d)
        else:
            date = re.search(r'(?<!\d)(\d{1,2})[/-](\d{1,2})[/-](\d{4}|\d{2})(?!\d)', clean)
            if date:
                d, mo, y = map(int, date.groups()); y = y + 2000 if y < 100 else y
                stamp = pd.Timestamp(y, mo, d)
            else:
                date = re.search(r'(\d{1,2})\s+(' + MONTH + r')(?:\s*,?\s+((?:19|20)\d{2}))?', clean, re.I)
                if date:
                    d, mon, year = date.groups()
                else:
                    date = re.search(r'(' + MONTH + r')\s+(\d{1,2})(?:\s*,?\s+((?:19|20)\d{2}))?', clean, re.I)
                    if date: mon, d, year = date.groups()
                if date:
                    mo = sealed_nw.MONTHS.get(mon.lower()) or sealed_nw.MONTHS.get(mon[:3].lower())
                    year_missing = year is None
                    stamp = pd.Timestamp(int(year) if year else anchor_local.year, mo, int(d))
        clock_text = clean[:date.start()] + ' ' + clean[date.end():] if date else clean
        clock = re.search(r'(?<!\d)([012]?\d):([0-5]\d)(?::([0-5]\d))?(?!\d)|(?<!\d)([012]\d)([0-5]\d)\s*(?:hrs?|hours)\b', clock_text, re.I)
        ampm = re.search(r'(?<!\d)(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*(am|pm)\b', clock_text, re.I)
        if ampm:
            hh = int(ampm[1]) % 12 + (12 if ampm[3].lower() == 'pm' else 0)
            stamp = (stamp if stamp is not None else anchor_local.normalize()) + pd.Timedelta(hours=hh, minutes=int(ampm[2] or 0))
            return stamp, 'datetime' if date else 'time_only'
        if not clock and re.search(r'\b(?:TI\s+[012]\d[0-5]\d|[012]\d[0-5]\d\s+dispatch\s+interval)\b', clock_text, re.I):
            clock = re.search(r'()()()([012]\d)([0-5]\d)', clock_text)
        if not clock and re.fullmatch(r'\s*(?:at\s+)?[012]\d[0-5]\d\s*', clock_text, re.I):
            clock = re.search(r'()()()([012]\d)([0-5]\d)', clock_text)
        if clock:
            hh, mm = (int(clock.group(1)), int(clock.group(2))) if clock.group(1) else (int(clock.group(4)), int(clock.group(5)))
            ss = int(clock.group(3) or 0)
            if hh > 24 or (hh == 24 and (mm or ss)): return None, None
            has_date = stamp is not None
            stamp = (stamp if has_date else anchor_local.normalize()) + pd.Timedelta(hours=hh, minutes=mm, seconds=ss)
            return stamp, ('datetime_year_from_publication' if year_missing else 'datetime') if has_date else 'time_only'
        if stamp is not None:
            return stamp, 'date_only_year_from_publication' if year_missing else 'date_only'
    except (ValueError, OverflowError, TypeError):
        pass
    return None, None


def window_details(start_text, end_text, anchor_local, available_utc=None):
    start, sp = parse_nem(start_text, anchor_local)
    end, ep = parse_nem(end_text, anchor_local)
    reasons = []
    if sp == 'time_only' and end is not None and ep != 'time_only':
        start = end.normalize() + (start - start.normalize())
        if start > end:
            start -= pd.Timedelta(days=1)
            reasons.append('OVERNIGHT_FROM_DATED_END')
        sp = 'date_from_same_interval_end'
    if ep == 'time_only' and start is not None:
        end = start.normalize() + (end - end.normalize())
        if end < start:
            end += pd.Timedelta(days=1)
            reasons.append('OVERNIGHT_ORDERED_TIME_RANGE')
        ep = 'date_from_same_interval_start'
    if ep and ep.startswith('date_only'):
        end += pd.Timedelta(days=1)
        reasons.append('INCLUSIVE_END_DATE')
    if sp == 'time_only' or ep == 'time_only':
        reasons.append('EXPLICIT_ENDPOINT_PUBLICATION_DAY_ANCHOR')
    if (sp and 'year_from_publication' in sp) or (ep and 'year_from_publication' in ep):
        reasons.append('EXPLICIT_MONTH_DAY_PUBLICATION_YEAR_ANCHOR')
    start_utc = pd.NaT if start is None else (start - NEM_OFFSET).tz_localize('UTC')
    end_utc = pd.NaT if end is None else (end - NEM_OFFSET).tz_localize('UTC')
    if start is not None and end is not None and end < start:
        reasons.append('CONTRADICTORY_ENDPOINT_ORDER_RETAINED')
    return start_utc, end_utc, sp or 'UNKNOWN', ep or 'UNKNOWN', tuple(reasons)


def window_utc(start_text, end_text, anchor_local, available_utc):
    return window_details(start_text, end_text, anchor_local, available_utc)[:2]


def event_clause_tail(text, offset):

    return re.split(r'(?<!\bNo)[.!?](?:\s|$)|\bAt\s+(?=\d)', str(text)[offset:offset+450], maxsplit=1, flags=re.I)[0]


def source_windows(title, text):
    'Read source time ranges and independent event instants in text order.'
    text = str(text)
    found, covered = [], []
    def add(s, e, m, why):
        if any(m.start() < b and m.end() > a for a, b in covered): return
        covered.append(m.span()); found.append((s, e, m.start(), m.group(0), why))
    for m in DATE_FROM_INTERVAL_RE.finditer(text):
        add(m['d'] + ' ' + m['s'], m['e'], m, 'RULE_DATE_THEN_INTERVAL')
    for m in BARE_INTERVAL_RE.finditer(text):


        add(m['s'], m['e'] + ' ' + m['d'], m, 'RULE_EXPLICIT_INTERVAL_END_DATE')
    for m in INTERVAL_RE.finditer(text):
        add(m['s'], m['e'], m, 'RULE_EXPLICIT_INTERVAL')
    for m in START_RE.finditer(text):
        prefix = text[max(0, m.start()-60):m.start()]
        if re.search(r'(?:cancelled|canceled|deadline|response|respond|submit|bid)\s*$', prefix, re.I): continue
        add(m.group(1), 'until further notice' if re.search(r'until\s+further\s+notice', m.group(0), re.I) else None, m, 'RULE_EXPLICIT_START')
    for m in INSTANT_RE.finditer(text):
        prefix = text[max(0, m.start()-65):m.start()]
        tail = event_clause_tail(text, m.end())
        if re.search(r'(?:updated?|published|issued|response|respond|deadline|by|offers?|submi(?:t|ssion))\s*$', prefix, re.I): continue
        if re.search(r'\b(?:trip(?:ped)?|outage|lost|loss|occurred|reclassified|restored|returned|ceased|commenced|started|island(?:ed|ing)?|fault|disconnected|opened|closed|de-?energised|energised|operated|load\s+shedding|activated|interrupted)\b', tail, re.I):
            add(m.group(1), None, m, 'RULE_EVENT_INSTANT')
    for m in EVENT_AT_RE.finditer(text):
        add(m.group(1), None, m, 'RULE_EVENT_AT_VERB')
    for m in TRADING_START_RE.finditer(text):
        add(m.group(1), None, m, 'RULE_TRADING_INTERVAL_START')
    for pattern, basis in ((FORECAST_END_RE, 'RULE_STANDALONE_FORECAST_END'), (EXPECTED_END_RE, 'RULE_EXPECTED_DURATION_END')):
        for m in pattern.finditer(text):


            add(None, m.group(1), m, basis)
    for m in STANDALONE_OPEN_RE.finditer(text):
        add(None, 'until further notice', m, 'RULE_STANDALONE_OPEN_CONDITION')
    for pattern, basis in ((DIRECTION_ISSUED_RE, 'RULE_DIRECTION_ISSUANCE'), (DIRECTION_ACTION_RE, 'RULE_DIRECTION_REQUIRED_ACTION')):
        for m in pattern.finditer(text): add(m.group(1), None, m, basis)


    if len(found) == 2:
        starts = [w for w in found if w[0] is not None and w[1] is None and w[4] in ('RULE_EXPLICIT_START', 'RULE_EVENT_AT_VERB')]
        ends = [w for w in found if w[0] is None and w[4] == 'RULE_STANDALONE_FORECAST_END']
        topics = {re.sub(r'\s+', '', token.upper()) for token in re.findall(r'\b(?:LOR|MSL)\s*[123]\b', text, re.I)}
        unique_topic = len(topics) == 1 or bool(re.search(r'\bIntervention\s+Event\b', text, re.I))
        if len(starts) == len(ends) == 1 and unique_topic and 0 < ends[0][2] - starts[0][2] <= 300:
            left, right = starts[0], ends[0]
            found = [(left[0], right[1], left[2], left[3] + ' ' + right[3], 'RULE_UNIQUE_FORECAST_INTERVAL')]
    if not found and str(title) != text:
        for m in INTERVAL_RE.finditer(str(title)):
            found.append((m['s'], m['e'], None, m.group(0), 'RULE_TITLE_EXPLICIT_INTERVAL'))
    return sorted(found, key=lambda x: -1 if x[2] is None else x[2]) or [(None, None, None, '', 'RULE_NO_OPERATING_WINDOW')]


def action_metadata(title, text, anchor_local, available_utc):
    matches = list(ACTION_RE.finditer(str(text)))
    parsed = []
    for m in matches:
        value, precision = parse_nem(m.group('time'), anchor_local)
        if value is not None:
            parsed.append((value, precision, m))

    future = [x for x in parsed if x[2].group('action').lower().startswith('will')]
    candidates = future or parsed
    distinct = {x[0] for x in candidates}
    if len(distinct) != 1:
        return pd.NaT, False, 'CONFLICTING_ACTION_TIMES' if distinct else 'UNKNOWN_ACTION_TIME', '', ''
    value, precision, m = candidates[0]
    instant = (value - NEM_OFFSET).tz_localize('UTC')
    prospective = bool(future and instant > available_utc)
    reason = 'EXPLICIT_PROSPECTIVE_ACTION' if prospective else ('PAST_OR_CURRENT_ACTION_CLOSE_AT_AVAILABILITY' if instant <= available_utc else 'AMBIGUOUS_FUTURE_ACTION_CLOSE_AT_AVAILABILITY')
    return instant, prospective, reason, m.group(0), precision


def _status(title, text, lifecycle=None, kind_raw=None):
    if re.search(r'\bwill\s+(?:end|cease|be\s+cancelled|be\s+canceled)|\b(?:resumption|period\s+ends)\b', title + ' ' + text, re.I):
        return 'CANCELLATION'
    if re.search(r'\bceased\s+operating|\bis\s+cancelled\b|\bCancellation\s+time\s*:', text, re.I):
        return 'CANCELLATION'
    return v2._status(title, lifecycle, kind_raw)


def _temporal_status(start, end, end_text):
    if pd.isna(start):
        if pd.notna(end): return 'UNKNOWN_START_KNOWN_END'
        if end_text and re.search(r'further\s+(?:notice|advice)', str(end_text), re.I): return 'UNKNOWN_START_OPEN_UNTIL_NOTICE'
        return 'UNKNOWN_START'
    if pd.notna(end):
        return 'BOUNDED' if end > start else 'ACTION_INSTANT' if end == start else 'CONTRADICTORY_ENDPOINT_ORDER'
    if end_text and re.search(r'further\s+(?:notice|advice)', str(end_text), re.I):
        return 'OPEN_UNTIL_NOTICE'
    return 'UNKNOWN_END'


def label_regions(value):
    'Normalize the region field of a saved label window.'
    if not isinstance(value, str) or not value.strip() or value.strip().upper() == 'UNKNOWN':
        return ['UNKNOWN']
    if value.strip().upper() in REGIONS:
        return [value.strip().upper()]
    matches = list(REGEX_REGION.finditer(value))
    return sorted({_region(m.group(1)) for m in matches}) or ['UNKNOWN']


def label_evidence(row, raw):

    raw_evidence = getattr(row, 'evidence_spans_json', '[]')
    try:
        snippets = json.loads(raw_evidence) if isinstance(raw_evidence, str) else list(raw_evidence)
    except (ValueError, TypeError):
        snippets = []
    snippets += [s for w in raw for s in (w.get('evidence_spans') or [])]
    snippets += [q.get('evidence_span', '') for q in json.loads(row.quantities_json)]
    return ' '.join(dict.fromkeys(s for s in snippets if isinstance(s, str) and s.strip()))


def _label_quantities(raw, items):
    'Bind extracted MW values using the saved evidence spans and window endpoints.'
    assigned = [defaultdict(list) for _ in raw]
    for q in items:
        if str(q.get('unit', '')).upper() != 'MW' or q.get('direction') not in ('REQUIREMENT', 'AVAILABLE'):
            continue
        try: value = float(str(q.get('value_text', '')).replace(',', ''))
        except (TypeError, ValueError): continue
        if not np.isfinite(value): continue
        evidence = re.sub(r'\s+', ' ', str(q.get('evidence_span') or '')).strip()
        candidates = list(range(len(raw))) if len(raw) == 1 else [i for i, w in enumerate(raw)
            if evidence and any(evidence in re.sub(r'\s+', ' ', str(s)) or
                (len(str(s)) >= 15 and re.sub(r'\s+', ' ', str(s)) in evidence)
                for s in (w.get('evidence_spans') or []))]
        if len(candidates) == 1:
            assigned[candidates[0]][q['direction']].append(value)
    result = []
    for values in assigned:
        def one(key):
            distinct = set(values[key]); return next(iter(distinct)) if len(distinct) == 1 else np.nan
        req, avail = one('REQUIREMENT'), one('AVAILABLE')
        result.append((req, avail, 'BOUND' if np.isfinite(req) and np.isfinite(avail) else 'UNKNOWN_RELATION'))
    return result


def _record(r, arm, reg, kind, status, start_text, end_text, req, avail, qstatus,
            refs, scoped_regions, lor, category, feature_eligible, rawreg, rbasis,
            evidence, wbasis, offset=None, action=pd.NaT, action_evidence='',
            action_precision='', prospective=False, action_reason='UNKNOWN_ACTION_TIME',
            scope='EVENT', constraint_ids=(), negative=False, raw=None):
    start, end, sp, ep, reasons = window_details(start_text, end_text, r.anchor_local, r.available_utc)
    cancel = status in ('CANCELLATION', 'RECOVERY')
    temporal = _temporal_status(start, end, end_text)
    if pd.isna(start) and pd.isna(end) and pd.notna(action): temporal = 'CLOSING_INSTANT_ONLY'
    admission = ('EXCLUDED_ADMINISTRATIVE_SYSTEM' if category == 'ADMINISTRATIVE_SYSTEM' else
                 'NEGATIVE_STATE_CONTROL_ONLY' if negative else
                 'UNRESOLVED_REGION_DIAGNOSTIC_ONLY' if reg not in REGIONS else 'REGIONAL_RECORD')
    return dict(zip(RECORD_COLUMNS, [str(r.notice_id), reg, kind, cancel, r.available_utc,
        start, end, req, avail, status, str(r.notice_id), tuple(refs), scope,
        temporal, qstatus, v2._title_key(r.title), str(r.notice_type),
        tuple(scoped_regions), lor]), arm=arm, population_admission='OPERATIONAL_VALID_CLOCK_UNCHANGED',
        source_category=category, admission_reason=admission,
        feature_eligible=bool(feature_eligible and reg in REGIONS), raw_region=rawreg,
        normalized_region=reg, region_derivation=rbasis, region_evidence='', directional_links_json='[]',
        raw_start_text=start_text, raw_end_text=end_text, end_is_open=bool(end_text and re.search(r'further\s+(?:notice|advice)', str(end_text), re.I)), window_derivation=wbasis,
        window_evidence=evidence, start_anchor_basis=sp, end_anchor_basis=ep,
        clock_reason_codes=json.dumps(reasons), action_effective_utc=action,
        prospective_action=bool(prospective and cancel), action_time_reason=action_reason,
        action_evidence=action_evidence, action_anchor_basis=action_precision,
        constraint_ids=tuple(constraint_ids), negative_state=negative,
        raw_m331_windows_json=json.dumps(raw or []) if arm == 'L' else '[]',
        raw_m331_quantities_json=getattr(r, 'quantities_json', '[]') if arm == 'L' else '[]')


def _llm_rows(r):


    raw = json.loads(r.impact_windows_json)
    evidence = label_evidence(r, raw)
    refs = v2._references(evidence)
    quantities = _label_quantities(raw, json.loads(r.quantities_json))
    category = 'ADMINISTRATIVE_SYSTEM' if r.notice_type == 'MARKET SYSTEMS' else str(r.notice_type)
    scoped_regions = sorted({reg for w in raw for reg in label_regions(w.get('region')) if reg in REGIONS})
    lor = re.search(r'\bLOR\s*([123])\b', evidence, re.I)
    ids = tuple(sorted({m.group(0).upper() for m in CONSTRAINT_ID.finditer(evidence)}))
    rows = []
    for i, w in enumerate(raw):
        kind_raw = w.get('window_kind')
        kind = ('CONSTRAINT' if r.notice_type == 'RECLASSIFY CONTINGENCY' else
                kind_raw if kind_raw in ('RESERVE', 'CONSTRAINT', 'INTERVENTION', 'OUTAGE') else
                'OUTAGE' if kind_raw == 'RETURN_TO_SERVICE' else sealed_nw.TYPE_KIND.get(r.notice_type, 'OTHER'))
        status = v2._status(r.title, r.lifecycle, kind_raw)
        if kind_raw == 'RETURN_TO_SERVICE' and status != 'CANCELLATION': status = 'RECOVERY'
        start_text, end_text = w.get('start_text'), w.get('end_text')
        start, end, sp, ep, _ = window_details(start_text, end_text, r.anchor_local, r.available_utc)
        action, aprecision = pd.NaT, ''
        if status in ('CANCELLATION', 'RECOVERY'):
            if pd.notna(end): action, aprecision = end, ep
            elif pd.notna(start): action, aprecision = start, sp


        for reg in label_regions(w.get('region')):
            rows.append(_record(r, 'L', reg, kind, status, start_text, end_text, *quantities[i],
                refs, scoped_regions, lor.group(1) if lor else '', category, category != 'ADMINISTRATIVE_SYSTEM',
                w.get('region', 'UNKNOWN'), 'M331_REGION_ONLY',
                ' | '.join(str(s) for s in w.get('evidence_spans', [])), 'M331_ENDPOINTS_ONLY',
                action=action, action_precision=aprecision,
                action_reason='M331_CLOSING_ENDPOINT' if pd.notna(action) else 'UNKNOWN_ACTION_TIME',
                constraint_ids=ids, raw=raw))

    # Retain an unknown region when the source gives no window.
    if not raw and r.lifecycle in ('CANCELLATION', 'CEASED'):
        rows.append(_record(r, 'L', 'UNKNOWN', sealed_nw.TYPE_KIND.get(r.notice_type, 'OTHER'),
            v2._status(r.title, r.lifecycle), None, None, np.nan, np.nan, 'UNKNOWN_RELATION',
            refs, [], lor.group(1) if lor else '', category, False, 'UNKNOWN', 'M331_NO_REGION',
            evidence, 'M331_LIFECYCLE_ONLY', constraint_ids=ids))
    return rows


def _rule_rows(r):
    regions, rbasis, revidence, direction = source_regions(r.title, r.text)
    category, kind, admission = source_category(r.notice_type, r.title, r.text)
    status = _status(r.title, r.text)
    refs = v2._references(r.text)
    ids = tuple(sorted({m.group(0).upper() for m in CONSTRAINT_ID.finditer(r.text)}))
    lor = re.search(r'\bLOR\s*([123])\b', r.text, re.I)
    negative = bool(NEGATIVE.search(r.text))
    if negative and status not in ('CANCELLATION', 'RECOVERY'): status = 'UPDATE'
    windows = source_windows(r.title, r.text)

    # Retain the unknown endpoint rather than borrowing an outage time.
    open_reclass = list(re.finditer(r'\b(?:has\s+(?:therefore\s+)?reclassified|reclassified|reclassification)[^.!?]{0,240}\buntil\s+further\s+notice\b', r.text, re.I))
    if open_reclass and not any(e and re.search(r'further\s+notice', str(e), re.I) for _, e, *_ in windows):
        windows = [w for w in windows if w[0] is not None or w[1] is not None]
        windows += [(None, 'until further notice', match.start(), match.group(0), 'RULE_RECLASSIFICATION_OPEN_NO_START') for match in open_reclass]
    actions = []
    for m in sorted([match for pattern in (ACTION_RE, MSL_CLOSE_RE, CEASE_IMPACT_RE) for match in pattern.finditer(r.text)], key=lambda match: match.start()):
        local, precision = parse_nem(m['time'], r.anchor_local)
        if local is not None:
            actions.append(((local - NEM_OFFSET).tz_localize('UTC'), precision, m))


    specs = []
    for s, e, offset, evidence, basis in windows:
        if s is None and e is None and actions: continue
        action, precision, aev, prospective, reason = pd.NaT, '', '', False, 'UNKNOWN_ACTION_TIME'
        if len(actions) == 1:
            action, precision, match = actions[0]
            aev = match.group(0); prospective = match['action'].lower().startswith('will') and action > r.available_utc
            reason = 'EXPLICIT_PROSPECTIVE_ACTION' if prospective else 'PAST_OR_CURRENT_ACTION_CLOSE_AT_AVAILABILITY' if action <= r.available_utc else 'AMBIGUOUS_FUTURE_ACTION_CLOSE_AT_AVAILABILITY'
        local_status = 'RECLASSIFICATION' if basis == 'RULE_RECLASSIFICATION_OPEN_NO_START' else status
        if basis == 'RULE_EVENT_INSTANT' and offset is not None:
            match = INSTANT_RE.match(r.text, offset)
            clause = event_clause_tail(r.text, match.end()) if match else ''
            if re.search(r'\b(?:was\s+|has\s+been\s+)?returned\s+to\s+service\b', clause, re.I):
                local_status = 'RECOVERY'
                action, _, precision, _, _ = window_details(s, None, r.anchor_local, r.available_utc)
                aev = evidence + ' ' + clause.strip(); prospective = False
                reason = 'RULE_EVENT_CLAUSE_RECOVERY'
        specs.append((s, e, offset, evidence, basis, local_status, action, precision, aev, prospective, reason))
    carried = {x[6] for x in specs if pd.notna(x[6])}
    for action, precision, match in actions:
        if action in carried: continue
        prospective = match['action'].lower().startswith('will') and action > r.available_utc
        astatus = 'RECOVERY' if re.search(r'returned\s+to\s+service', match['action'], re.I) else 'CANCELLATION'
        reason = 'EXPLICIT_PROSPECTIVE_ACTION' if prospective else 'PAST_OR_CURRENT_ACTION_CLOSE_AT_AVAILABILITY' if action <= r.available_utc else 'AMBIGUOUS_FUTURE_ACTION_CLOSE_AT_AVAILABILITY'
        specs.append((None, None, match.start(), match.group(0), 'RULE_EXPLICIT_CLOSING_TIME',
                      astatus, action, precision, match.group(0), prospective, reason))
        carried.add(action)
    windows_expanded = [(reg, *spec) for reg in (regions or ['UNKNOWN']) for spec in specs]
    qbound = v2._bind_quantities([(reg, s, e, offset) for reg, s, e, offset, *_ in windows_expanded], v2._rule_quantities(r.text))
    rows = []
    for (reg, s, e, offset, evidence, basis, local_status, action, precision, aev, prospective, reason), quantities in zip(windows_expanded, qbound):
        cancel = local_status in ('CANCELLATION', 'RECOVERY')
        scope = ('NOTICE_PARTIAL' if local_status in ('CANCELLATION', 'RECOVERY', 'UPDATE') and refs and v2.PARTIAL_SCOPE.search(r.text) else
                 'REGION_ALL' if cancel and not refs and v2.REGION_RELEASE.search(r.text) else 'EVENT')
        local_kind = 'CONSTRAINT' if basis == 'RULE_RECLASSIFICATION_OPEN_NO_START' else kind
        record = _record(r, 'R', reg, local_kind, local_status, s, e, *quantities,
            refs, regions, lor.group(1) if lor else '', category,
            (admission and not negative) or (cancel and category != 'ADMINISTRATIVE_SYSTEM'),
            'RULE_SOURCE', rbasis, evidence, basis, offset, action, aev, precision,
            prospective, reason, scope, ids, negative)
        record['region_evidence'] = revidence; record['directional_links_json'] = json.dumps(direction)

        if offset is not None:
            reference_snapshot = re.split(r'[.!?]', r.text[:int(offset)])[-1][-120:]
            after = re.split(r'[.!?]', r.text[int(offset):])[0][:180]
            if re.search(r'\b(?:tomorrow|yesterday|next\s+(?:day|week|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)|following\s+day)\b', reference_snapshot + after, re.I):
                sp, ep = parse_nem(s, r.anchor_local)[1], parse_nem(e, r.anchor_local)[1]
                for field, precision_here, paired in [('start', sp, ep), ('end', ep, sp)]:
                    if precision_here == 'time_only' and paired in ('time_only', None):
                        record[field + '_utc'] = pd.NaT; record[field + '_anchor_basis'] = 'UNRESOLVED_RELATIVE_DAY_CONTEXT'
                record['temporal_status'] = _temporal_status(record['start_utc'], record['end_utc'], e)
        rows.append(record)
    return rows


def _assemble(pop, arm, labels=None):
    if pop.notice_id.astype(str).duplicated().any(): raise ValueError('Duplicate source notice')
    if arm == 'L':
        labels = labels.copy(); labels['notice_id'] = labels.notice_id.astype(str)
        if labels.notice_id.duplicated().any(): raise ValueError('Duplicate M331 notice')

        pop = pop.drop(columns=['text']).merge(labels.drop(columns=['notice_type'], errors='ignore'),
            on='notice_id', how='left', validate='one_to_one', indicator=True)
        if not pop['_merge'].eq('both').all(): raise ValueError('Incomplete M331 join')
    rows = []
    for row in pop.itertuples(index=False): rows.extend(_llm_rows(row) if arm == 'L' else _rule_rows(row))
    out = pd.DataFrame(rows)
    if not len(out): out = frame([])
    for field in ('available_utc', 'start_utc', 'end_utc', 'action_effective_utc'):
        if field in out: out[field] = pd.to_datetime(out[field], utc=True)
    return out


def rule_records(pop):
    return _assemble(pop, 'R')


def llm_records(pop, labels=None):
    if labels is None:
        labels = pd.read_parquet(LABELS, columns=['notice_id', 'notice_type', 'impact_windows_json',
            'lifecycle', 'quantities_json', 'evidence_spans_json', 'propagation_paths_json'])
    return _assemble(pop, 'L', labels), len(pop)


def _overlap(a, b):
    if pd.isna(a.start_utc) or pd.isna(b.start_utc):
        return False
    a_end = a.end_utc if pd.notna(a.end_utc) else pd.Timestamp.max.tz_localize('UTC')
    b_end = b.end_utc if pd.notna(b.end_utc) else pd.Timestamp.max.tz_localize('UTC')
    return a.start_utc < b_end and b.start_utc < a_end


def resolve_event_states(records):
    'Close referenced event states in notice availability order.'
    if 'close_utc' in records and 'relation_basis' in records:
        return records.copy()
    out = records.copy().reset_index(drop=True)
    if 'feature_eligible' not in out:
        out['feature_eligible'] = True
    if 'prospective_action' not in out:
        out['prospective_action'] = False
    if 'action_effective_utc' not in out:
        out['action_effective_utc'] = pd.NaT
    if 'constraint_ids' not in out:
        out['constraint_ids'] = [()] * len(out)
    groups = {str(n): g for n, g in out.groupby('notice_id', sort=False)}
    ordered = sorted(groups, key=lambda n: (groups[n].available_utc.iloc[0], n))
    close_ns = np.full(len(out), BIG, dtype=np.int64)
    event_id = [''] * len(out)
    relation_basis = [''] * len(out)
    notice_events = {}
    notice_available = {}
    active_by_event = defaultdict(set)
    title_index = defaultdict(set)
    constraint_index = defaultdict(set)
    schedules = [[] for _ in range(len(out))]

    def close_indices(indices, at):
        at_ns = int(at.value)
        for index in indices:
            if bool(first.cancel) and bool(first.prospective_action) and pd.notna(first.action_effective_utc):
                schedules[index].append((str(at), str(first.action_effective_utc), str(first.notice_id)))
            else:
                close_ns[index] = min(close_ns[index], at_ns)

    for notice_id in ordered:
        group = groups[notice_id]
        first = group.iloc[0]
        now = first.available_utc
        prospective = bool(first.cancel) and bool(first.prospective_action) and pd.notna(first.action_effective_utc)
        refs = tuple(first.related_notice_ids)
        targets = set()
        basis = 'NEW_EVENT'
        if first.version_status in ('UPDATE', 'CANCELLATION', 'RECOVERY') and refs:
            incompatible = None
            for ref in refs:
                if ref in notice_events and notice_available[ref] < now:
                    cited = groups[ref]
                    old = cited.iloc[0]
                    if first.source_notice_type != old.source_notice_type:
                        incompatible = 'INCOMPATIBLE_SOURCE_TYPE'
                        continue
                    if (first.source_lor_level and old.source_lor_level and
                            first.source_lor_level != old.source_lor_level):
                        incompatible = 'INCOMPATIBLE_SOURCE_TOPIC'
                        continue
                    stated_regions = set(first.source_body_regions)
                    cited_regions = set(cited.region) | set(old.source_body_regions)
                    if stated_regions and not (stated_regions & cited_regions):
                        incompatible = 'INCOMPATIBLE_SOURCE_REGION'
                        continue
                    if not stated_regions and not (set(group.region) & cited_regions) and not bool(first.get('negative_state', False)):
                        incompatible = 'INCOMPATIBLE_SOURCE_REGION'
                        continue
                    targets.update(notice_events[ref])
            if incompatible:
                targets.clear()
                basis = incompatible
            else:
                basis = 'EXPLICIT_NOTICE_ID' if targets else 'UNRESOLVED_REFERENCE'
        elif tuple(first.constraint_ids) and not refs and first.version_status in ('UPDATE', 'CANCELLATION', 'RECOVERY'):
            candidates = set()
            for identity in tuple(first.constraint_ids):
                for event in constraint_index.get((first.source_notice_type, identity), ()):
                    if active_by_event[event] and all(out.at[j, 'available_utc'] < now for j in active_by_event[event]):
                        candidates.add(event)
            if len(candidates) == 1:
                targets = candidates
                basis = 'EXACT_CONSTRAINT_SET_ID'
            else:
                basis = 'AMBIGUOUS_CONSTRAINT_ID' if candidates else 'UNRESOLVED_CONSTRAINT_ID'
        elif first.title_key and not refs and first.version_status in ('UPDATE', 'CANCELLATION', 'RECOVERY'):
            candidates = set()
            for current in group.itertuples(index=False):
                key = (current.title_key, current.region, current.kind)
                for event in title_index.get(key, ()):
                    if not active_by_event[event]:
                        continue
                    if current.cancel or any(_overlap(current, out.iloc[j]) for j in active_by_event[event]
                                             if out.at[j, 'title_key'] == current.title_key and
                                             out.at[j, 'region'] == current.region and
                                             out.at[j, 'kind'] == current.kind):
                        candidates.add(event)
            if len(candidates) == 1:
                targets = candidates
                basis = 'UNIQUE_DATED_TITLE' if first.cancel else 'DATED_TITLE_OVERLAP'
            elif first.version_status in ('UPDATE', 'CANCELLATION', 'RECOVERY'):
                basis = 'AMBIGUOUS_TITLE' if candidates else 'UNRESOLVED_RELATION'
        elif first.version_status in ('UPDATE', 'CANCELLATION', 'RECOVERY'):
            basis = 'UNRESOLVED_RELATION'

        # Resolve explicit notice references before regional release statements.


        if not refs and group.relation_scope.eq('REGION_ALL').any():
            release_pairs = set(zip(group.region, group.kind))
            for event, active in active_by_event.items():
                matched = {j for j in active if (out.at[j, 'region'], out.at[j, 'kind']) in release_pairs}
                if matched:
                    close_indices(matched, now)
                    if not prospective:
                        active.difference_update(matched)
                    targets.add(event)
            basis = 'REGION_ALL'
        elif group.relation_scope.eq('NOTICE_PARTIAL').any() and targets:
            planned = {}
            affected_regions = set(first.source_body_regions) or set(group.region)
            affected_kinds = set(group.kind)
            for event in targets:
                matched = {j for j in active_by_event[event]
                           if out.at[j, 'region'] in affected_regions and out.at[j, 'kind'] in affected_kinds}
                if len(matched) != 1:
                    basis = 'UNRESOLVED_SCOPE'
                    planned.clear()
                    targets.clear()
                    break
                planned[event] = matched
            for event, matched in planned.items():
                close_indices(matched, now)
                if not prospective:
                    active_by_event[event].difference_update(matched)
        else:
            for event in targets:
                # Withdraw the cited event across its linked regions and event types.

                close_indices(active_by_event[event], now)
                if not prospective:
                    active_by_event[event].clear()

        event = next(iter(targets)) if len(targets) == 1 else notice_id
        for index in group.index:
            event_id[index] = event
            relation_basis[index] = basis
        if first.cancel:
            notice_events[notice_id] = tuple(sorted(targets))
        else:
            # Keep the histories of distinct cited events separate.

            notice_events[notice_id] = (event,)
            active_by_event[event].update(group.index)
            for row in group.itertuples(index=False):
                if row.title_key:
                    title_index[(row.title_key, row.region, row.kind)].add(event)
                for identity in tuple(row.constraint_ids):
                    constraint_index[(row.source_notice_type, identity)].add(event)
        notice_available[notice_id] = now

    out['event_id'] = event_id
    out['relation_basis'] = relation_basis
    out['prospective_closures_json'] = [json.dumps(x) for x in schedules]
    out['close_utc'] = pd.Series(pd.NaT, index=out.index, dtype='datetime64[ns, UTC]')
    finite = close_ns != BIG
    if finite.any():
        out.loc[finite, 'close_utc'] = pd.to_datetime(close_ns[finite], unit='ns', utc=True)
    return out


def features(keys, records):

    n = len(keys)
    order = np.argsort(_ns(keys.issue_time), kind='stable')
    issue = _ns(keys.issue_time)[order]
    target = _ns(keys.target_time)[order]
    regions = keys.region.to_numpy()[order]
    counts = {c: np.zeros(n, dtype=np.float32) for c in COLUMNS[:8] + COLUMNS[12:]}
    deficit = np.full(n, -np.inf)
    min_avail = np.full(n, np.inf)
    first_start = np.full(n, BIG, dtype=np.int64)
    last_end = np.full(n, np.iinfo(np.int64).min, dtype=np.int64)
    unknown_end = np.zeros(n, dtype=bool)
    rec = resolve_event_states(records)
    rec['a'] = _ns(rec.available_utc)
    rec['s'] = _ns(rec.start_utc)
    rec['e'] = _ns(rec.end_utc)
    rec['c'] = np.where(rec.close_utc.isna(), BIG, _ns(rec.close_utc))

    kind_col = {'RESERVE': ('nw_res_local', 'nw_res_foreign'),
                'CONSTRAINT': ('nw_con_local', 'nw_con_foreign'),
                'INTERVENTION': ('nw_int_local', None),
                'OUTAGE': ('nw_out_local', 'nw_out_foreign'), 'OTHER': (None, None)}
    eligible = rec.region.isin(REGIONS) & rec.get('feature_eligible', pd.Series(True, index=rec.index)).astype(bool)
    for r in rec.loc[~rec.cancel & eligible].itertuples(index=False):
        if r.temporal_status not in ('BOUNDED', 'OPEN_UNTIL_NOTICE'):
            continue
        lo = np.searchsorted(issue, r.a, side='left')
        # Limit unbounded current-state evidence to the specified 48-hour window.


        evidence_close = min(r.c, r.a + sealed_nw.LOOKBACK) if r.temporal_status == 'OPEN_UNTIL_NOTICE' else r.c
        hi = np.searchsorted(issue, evidence_close, side='left')
        if hi <= lo:
            continue
        idx = np.arange(lo, hi)
        idx = idx[target[idx] >= r.s]
        if r.temporal_status == 'BOUNDED':
            idx = idx[target[idx] < r.e]
        for announced, effective, _ in json.loads(getattr(r, 'prospective_closures_json', '[]')):
            ann_ns, eff_ns = pd.Timestamp(announced).value, pd.Timestamp(effective).value
            idx = idx[~((issue[idx] >= ann_ns) & (target[idx] >= eff_ns))]
        if not len(idx):
            continue
        local = idx[regions[idx] == r.region]
        foreign = idx[regions[idx] != r.region]
        lc, fc = kind_col[r.kind]
        if lc and len(local):
            counts[lc][local] += 1
        if fc and len(foreign):
            counts[fc][foreign] += 1
        if len(local):
            counts['nw_any_local'][local] += 1
            np.minimum.at(first_start, local, r.s)
            if r.temporal_status == 'BOUNDED':
                np.maximum.at(last_end, local, r.e)
            else:
                unknown_end[local] = True
            if r.kind == 'RESERVE':
                if np.isfinite(r.req_mw) and np.isfinite(r.avail_mw):
                    np.maximum.at(deficit, local, r.req_mw - r.avail_mw)
                if np.isfinite(r.avail_mw):
                    np.minimum.at(min_avail, local, r.avail_mw)
    per_notice = rec.loc[eligible].groupby(['notice_id', 'region'], as_index=False).agg(a=('a', 'min'), cancel=('cancel', 'max'))
    for r in per_notice.itertuples(index=False):
        lo = np.searchsorted(issue, r.a, side='left')
        hi = np.searchsorted(issue, r.a + RECENT, side='left')
        if hi <= lo:
            continue
        idx = np.arange(lo, hi)
        idx = idx[regions[idx] == r.region]
        counts['nw_cancel_local_6h' if r.cancel else 'nw_new_local_6h'][idx] += 1
    out = pd.DataFrame(counts)
    out['nw_res_deficit_mw_local'] = np.where(np.isfinite(deficit), deficit, np.nan).astype(np.float32)
    out['nw_res_min_avail_mw_local'] = np.where(np.isfinite(min_avail), min_avail, np.nan).astype(np.float32)
    has = first_start != BIG
    out['nw_minutes_since_start_local'] = np.where(has, (target - first_start) / 6e10, np.nan).astype(np.float32)
    has_end = has & ~unknown_end & (last_end != np.iinfo(np.int64).min)
    out['nw_minutes_to_end_local'] = np.where(has_end, (last_end - target) / 6e10, np.nan).astype(np.float32)
    out = out[COLUMNS]
    result = pd.DataFrame(index=keys.index, columns=COLUMNS, dtype=np.float32)
    result.iloc[order] = out.to_numpy()
    return result.astype(np.float32)


def shifted(records, days):

    out = records.copy(); delta = pd.Timedelta(days=days)
    for c in ('available_utc', 'start_utc', 'end_utc', 'close_utc', 'action_effective_utc'):
        if c in out:
            out[c] = pd.to_datetime(out[c], utc=True) + delta
    if 'prospective_closures_json' in out:
        out['prospective_closures_json'] = [json.dumps([(str(pd.Timestamp(a) + delta), str(pd.Timestamp(e) + delta), n)
            for a, e, n in json.loads(value)]) for value in out.prospective_closures_json]
    return out


def relation_audit(records):
    rec = resolve_event_states(records)
    return {'records': len(rec), 'notices': rec.notice_id.nunique(),
            'relation_basis_counts': rec.drop_duplicates('notice_id').relation_basis.value_counts().to_dict(),
            'temporal_status_counts': rec.temporal_status.value_counts().to_dict(),
            'admission_reason_counts': rec.admission_reason.value_counts().to_dict() if 'admission_reason' in rec else {}}
