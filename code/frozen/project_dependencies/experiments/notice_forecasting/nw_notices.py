'Convert notice text and extracted labels to a common record schema.'
from __future__ import annotations
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / 'artifacts/pivot_bq/m463_corrected_notice_timing/corrected_notice_registry.csv'
LABELS = ROOT / 'artifacts/pivot_bq/m331_llm_impact_interval_full_operational/labels.parquet'
REGIONS = ('NSW1', 'QLD1', 'SA1', 'TAS1', 'VIC1')
KINDS = ('RESERVE', 'CONSTRAINT', 'INTERVENTION', 'OUTAGE', 'OTHER')
NEM_OFFSET = pd.Timedelta(hours=10)
OPEN_ENDED = pd.Timedelta(hours=24)
MAX_SPAN = pd.Timedelta(days=7)
MONTHS = {m.lower(): i for i, m in enumerate(
    ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
     'September', 'October', 'November', 'December'], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
TYPE_KIND = {'RESERVE NOTICE': 'RESERVE', 'RECLASSIFY CONTINGENCY': 'CONSTRAINT',
             'MARKET INTERVENTION': 'INTERVENTION', 'INTER-REGIONAL TRANSFER': 'OUTAGE',
             'POWER SYSTEM EVENTS': 'OUTAGE'}


_D = r'(\d{1,2})/(\d{1,2})/(\d{4})'
_MON = r'(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})'
PATTERNS = [
    (re.compile(_D + r'\s+(\d{1,2}):(\d{2})(?::\d{2})?'), 'dmy_hm'),
    (re.compile(r'(\d{2}):?(\d{2})\s*hrs\s+(?:on\s+)?' + _D), 'hm_dmy'),
    (re.compile(_D + r'\s+(\d{2}):?(\d{2})\s*hrs'), 'dmy_hm'),
    (re.compile(r'(\d{2}):?(\d{2})\s*hrs\s+(?:on\s+)?' + _MON), 'hm_mon'),
    (re.compile(r'(\d{2}):?(\d{2})\s*hrs'), 'hm'),
    (re.compile(r'^\s*(\d{1,2}):(\d{2})\s*$'), 'hm'),
    (re.compile(_D), 'dmy'),
    (re.compile(_MON), 'mon'),
]


def parse_nem(text, anchor_local):
    'Parse literal notice endpoints using fixed UTC+10 local time.'
    if not isinstance(text, str) or not text.strip() or 'unknown' in text.lower() or 'further notice' in text.lower():
        return None, None
    for pattern, kind in PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        g = m.groups()
        try:
            if kind == 'dmy_hm':
                d, mo, y, hh, mm = map(int, g[:5]); return pd.Timestamp(y, mo, d) + pd.Timedelta(hours=hh, minutes=mm), 'datetime'
            if kind == 'hm_dmy':
                hh, mm, d, mo, y = map(int, g); return pd.Timestamp(y, mo, d) + pd.Timedelta(hours=hh, minutes=mm), 'datetime'
            if kind == 'hm_mon':
                month = MONTHS.get(g[3].lower()) or MONTHS.get(g[3].lower()[:3])
                if not month:
                    continue
                return pd.Timestamp(int(g[4]), month, int(g[2])) + pd.Timedelta(hours=int(g[0]), minutes=int(g[1])), 'datetime'
            if kind == 'hm':
                hh, mm = int(g[0]), int(g[1])
                if hh > 24 or mm > 59:
                    continue
                return anchor_local.normalize() + pd.Timedelta(hours=hh, minutes=mm), 'time_only'
            if kind == 'dmy':
                d, mo, y = map(int, g); return pd.Timestamp(y, mo, d), 'date_only'
            if kind == 'mon':
                month = MONTHS.get(g[1].lower()) or MONTHS.get(g[1].lower()[:3])
                if not month:
                    continue
                return pd.Timestamp(int(g[2]), month, int(g[0])), 'date_only'
        except (ValueError, OverflowError):
            continue
    return None, None


def window_utc(start_text, end_text, anchor_local, available_utc):
    'Normalize explicit window endpoints in fixed NEM local time.'
    start, sp = parse_nem(start_text, anchor_local)
    if start is not None and sp == 'time_only' and start < anchor_local - pd.Timedelta(hours=12):
        start += pd.Timedelta(days=1)
    start_utc = available_utc if start is None else (start - NEM_OFFSET).tz_localize('UTC')
    end, ep = parse_nem(end_text, start if start is not None else anchor_local) if end_text else (None, None)
    if end is not None and ep == 'time_only' and start is not None and end <= start:
        end += pd.Timedelta(days=1)
    if end is not None and ep == 'date_only':
        end += pd.Timedelta(days=1)
    end_utc = None if end is None else (end - NEM_OFFSET).tz_localize('UTC')
    if end_utc is None or end_utc <= start_utc:
        end_utc = start_utc + OPEN_ENDED
    return start_utc, min(end_utc, start_utc + MAX_SPAN)


def load_population():
    reg = pd.read_csv(REGISTRY, usecols=['notice_id', 'notice_type', 'title', 'text', 'available_time_utc',
                                         'raw_time_local', 'is_relevant_operational', 'available_time_valid'])
    reg = reg.loc[reg.is_relevant_operational & reg.available_time_valid].copy()
    reg['notice_id'] = reg.notice_id.astype(str)
    if reg.notice_id.duplicated().any():
        raise ValueError('Duplicate notice id in operational registry')
    reg['available_utc'] = pd.to_datetime(reg.available_time_utc, utc=True)
    reg['anchor_local'] = pd.to_datetime(reg.raw_time_local)
    reg['title'] = reg.title.fillna('').astype(str)
    reg['text'] = reg.text.fillna('').astype(str).str.replace(r'\s+', ' ', regex=True)
    return reg.reset_index(drop=True)


CANCEL_RULE = re.compile(r'cancel|ceased|no longer|return(?:ed)? to service', re.I)
REGION_CODE = re.compile(r'\b(NSW|QLD|SA|TAS|VIC)1\b')
REGION_WORD = re.compile(r'\b(NSW|QLD|SA|TAS|VIC|Vic|Qld|Tas|New South Wales|Queensland|South Australia|Tasmania|Victoria)\b'
                         r'(?:\s*\((?:NSW|QLD|SA|TAS|VIC)\))?\s+[Rr]egion')
WORD_CODE = {'NSW': 'NSW1', 'QLD': 'QLD1', 'SA': 'SA1', 'TAS': 'TAS1', 'VIC': 'VIC1', 'Vic': 'VIC1', 'Qld': 'QLD1',
             'Tas': 'TAS1', 'New South Wales': 'NSW1', 'Queensland': 'QLD1', 'South Australia': 'SA1',
             'Tasmania': 'TAS1', 'Victoria': 'VIC1'}
_T = r'(\d{4})\s*hrs'
_DT = r'(\d{1,2}/\d{1,2}/\d{4})'
RULE_WINDOWS = [
    re.compile(r'[Ff]rom ' + _T + r' (?:on )?' + _DT + r' to ' + _T + r' (?:on )?' + _DT),
    re.compile(r'[Ff]rom ' + _T + r' to ' + _T + r' (?:on )?' + _DT),
    re.compile(r'Duration:\s*' + _DT + r' (\d{1,2}:\d{2}) until (further notice|' + _DT[1:-1] + r' \d{1,2}:\d{2})'),
    re.compile(r'invoked (?:from|at) ' + _T + r'(?: (?:on )?' + _DT + r')?(?: until (further notice|\d{4}\s*hrs(?: (?:on )?\d{1,2}/\d{1,2}/\d{4})?))?'),
    re.compile(r'\b[Ff]rom ' + _T + r'(?: (?:on )?' + _DT + r')?(?:.{0,120}?until ' + _T + r'(?: (?:on )?' + _DT + r')?)?'),
]
RULE_REQ = re.compile(r'reserve requirement is ([\d,]+)\s*MW', re.I)
RULE_AVAIL = re.compile(r'reserve available is ([\d,]+)\s*MW', re.I)


def rule_regions(title, text):
    found = {f'{m}1' for m in REGION_CODE.findall(title)} | {WORD_CODE[m] for m in REGION_WORD.findall(title)}
    if not found:
        found = {f'{m}1' for m in REGION_CODE.findall(text)} | {WORD_CODE[m] for m in REGION_WORD.findall(text)}
    return sorted(found)


def rule_windows(text):
    for i, pattern in enumerate(RULE_WINDOWS):
        hits = list(pattern.finditer(text))
        if not hits:
            continue
        out = []
        for m in hits:
            g = m.groups()
            if i == 0:
                out.append((f'{g[0]} hrs {g[1]}', f'{g[2]} hrs {g[3]}'))
            elif i == 1:
                out.append((f'{g[0]} hrs {g[2]}', f'{g[1]} hrs {g[2]}'))
            elif i == 2:
                out.append((f'{g[0]} {g[1]}', None if g[2] == 'further notice' else g[2]))
            elif i == 3:
                start = f'{g[0]} hrs' + (f' {g[1]}' if g[1] else '')
                out.append((start, None if not g[2] or g[2] == 'further notice' else g[2]))
            else:
                start = f'{g[0]} hrs' + (f' {g[1]}' if g[1] else '')
                end = (f'{g[2]} hrs' + (f' {g[3]}' if g[3] else '')) if g[2] else None
                out.append((start, end))
        return out
    return [(None, None)]


def rule_kind(notice_type, title):
    if re.search(r'\bdirect(?:ion|ed)\b', title, re.I):
        return 'INTERVENTION'
    return TYPE_KIND.get(notice_type, 'OTHER')


def _mw(values, reducer):
    numbers = [float(v.replace(',', '')) for v in values if v.replace(',', '').replace('.', '', 1).isdigit()]
    return reducer(numbers) if numbers else np.nan


def rule_records(pop):
    rows = []
    for r in pop.itertuples(index=False):
        regions = rule_regions(r.title, r.text)
        cancel = bool(CANCEL_RULE.search(r.title))
        kind = rule_kind(r.notice_type, r.title)
        req = _mw(RULE_REQ.findall(r.text), max); avail = _mw(RULE_AVAIL.findall(r.text), min)
        windows = [(None, None)] if cancel else rule_windows(r.text)
        for region in regions:
            for start_text, end_text in windows:
                start, end = window_utc(start_text, end_text, r.anchor_local, r.available_utc)
                rows.append((r.notice_id, region, kind, cancel, r.available_utc, start, end, req, avail))
    return frame(rows)


def _quantities(items):
    req, avail = [], []
    for q in items:
        if str(q.get('unit', '')).upper() != 'MW':
            continue
        try:
            value = float(str(q.get('value_text', '')).replace(',', ''))
        except ValueError:
            continue
        if q.get('direction') == 'REQUIREMENT':
            req.append(value)
        elif q.get('direction') == 'AVAILABLE':
            avail.append(value)
    return (max(req) if req else np.nan), (min(avail) if avail else np.nan)


def llm_records(pop):
    labels = pd.read_parquet(LABELS, columns=['notice_id', 'notice_type', 'impact_windows_json', 'lifecycle', 'quantities_json'])
    labels['notice_id'] = labels.notice_id.astype(str)
    if labels.notice_id.duplicated().any():
        raise ValueError('Duplicate LLM label')
    merged = pop.merge(labels.drop(columns=['notice_type']), on='notice_id', how='inner', validate='one_to_one')
    rows = []
    for r in merged.itertuples(index=False):
        notice_cancel = r.lifecycle in ('CANCELLATION', 'CEASED')
        req, avail = _quantities(json.loads(r.quantities_json))
        for w in json.loads(r.impact_windows_json):
            region = w.get('region')
            if region not in REGIONS:
                continue
            kind_raw = w.get('window_kind')
            cancel = notice_cancel or kind_raw == 'RETURN_TO_SERVICE'
            if kind_raw in ('RESERVE', 'CONSTRAINT', 'INTERVENTION', 'OUTAGE'):
                kind = kind_raw
            elif kind_raw == 'RETURN_TO_SERVICE':
                kind = 'OUTAGE'
            else:
                kind = TYPE_KIND.get(r.notice_type, 'OTHER')
            start, end = window_utc(w.get('start_text'), w.get('end_text'), r.anchor_local, r.available_utc)
            rows.append((r.notice_id, region, kind, cancel, r.available_utc, start, end, req, avail))
    return frame(rows), len(merged)


def frame(rows):
    out = pd.DataFrame(rows, columns=['notice_id', 'region', 'kind', 'cancel', 'available_utc', 'start_utc',
                                      'end_utc', 'req_mw', 'avail_mw'])
    for c in ('available_utc', 'start_utc', 'end_utc'):
        out[c] = pd.to_datetime(out[c], utc=True)
    return out


def shifted(records, days):
    out = records.copy(); delta = pd.Timedelta(days=days)
    for c in ('available_utc', 'start_utc', 'end_utc'):
        out[c] = out[c] + delta
    return out


COLUMNS = ['nw_res_local', 'nw_res_foreign', 'nw_con_local', 'nw_con_foreign', 'nw_int_local', 'nw_out_local',
           'nw_out_foreign', 'nw_any_local', 'nw_res_deficit_mw_local', 'nw_res_min_avail_mw_local',
           'nw_minutes_since_start_local', 'nw_minutes_to_end_local', 'nw_new_local_6h', 'nw_cancel_local_6h']
LOOKBACK = np.int64(48 * 3600 * 10**9)
RECENT = np.int64(6 * 3600 * 10**9)
BIG = np.iinfo(np.int64).max


def _ns(series):
    return series.dt.tz_convert('UTC').dt.as_unit('ns').astype('int64').to_numpy()


def features(keys, records):

    n = len(keys)
    order = np.argsort(_ns(keys.issue_time), kind='stable')
    issue = _ns(keys.issue_time)[order]; target = _ns(keys.target_time)[order]
    region = keys.region.to_numpy()[order]
    counts = {c: np.zeros(n, dtype=np.float32) for c in COLUMNS[:8] + COLUMNS[12:]}
    deficit = np.full(n, -np.inf); min_avail = np.full(n, np.inf)
    first_start = np.full(n, BIG, dtype=np.int64); last_end = np.full(n, np.iinfo(np.int64).min, dtype=np.int64)
    rec = records.copy()
    rec['a'] = _ns(rec.available_utc); rec['s'] = _ns(rec.start_utc); rec['e'] = _ns(rec.end_utc)
    # End a record at the first available cancellation for its region and type.
    rec['c'] = BIG
    for (reg, kind), group in rec.groupby(['region', 'kind']):
        cancels = np.sort(group.loc[group.cancel, 'a'].to_numpy())
        if len(cancels):
            pos = np.searchsorted(cancels, group.a.to_numpy(), side='right')
            rec.loc[group.index, 'c'] = np.where(pos < len(cancels), cancels[np.minimum(pos, len(cancels) - 1)], BIG)
    kind_col = {'RESERVE': ('nw_res_local', 'nw_res_foreign'), 'CONSTRAINT': ('nw_con_local', 'nw_con_foreign'),
                'INTERVENTION': ('nw_int_local', None), 'OUTAGE': ('nw_out_local', 'nw_out_foreign'), 'OTHER': (None, None)}
    active = rec.loc[~rec.cancel]
    for r in active.itertuples(index=False):
        lo = np.searchsorted(issue, r.a, side='left')
        hi = np.searchsorted(issue, min(r.a + LOOKBACK, r.c), side='left')
        if hi <= lo:
            continue
        idx = np.arange(lo, hi)
        idx = idx[(target[idx] >= r.s) & (target[idx] < r.e)]
        if not len(idx):
            continue
        local = idx[region[idx] == r.region]; foreign = idx[region[idx] != r.region]
        lc, fc = kind_col[r.kind]
        if lc and len(local):
            counts[lc][local] += 1
        if fc and len(foreign):
            counts[fc][foreign] += 1
        if len(local):
            counts['nw_any_local'][local] += 1
            np.minimum.at(first_start, local, r.s); np.maximum.at(last_end, local, r.e)
            if r.kind == 'RESERVE':
                if np.isfinite(r.req_mw) and np.isfinite(r.avail_mw):
                    np.maximum.at(deficit, local, r.req_mw - r.avail_mw)
                if np.isfinite(r.avail_mw):
                    np.minimum.at(min_avail, local, r.avail_mw)
    # Count each notice once per region, combining its windows.
    per_notice = rec.groupby(['notice_id', 'region'], as_index=False).agg(a=('a', 'min'), cancel=('cancel', 'max'))
    for r in per_notice.itertuples(index=False):
        lo = np.searchsorted(issue, r.a, side='left'); hi = np.searchsorted(issue, r.a + RECENT, side='left')
        if hi <= lo:
            continue
        idx = np.arange(lo, hi); idx = idx[region[idx] == r.region]
        counts['nw_cancel_local_6h' if r.cancel else 'nw_new_local_6h'][idx] += 1
    out = pd.DataFrame(counts)
    out['nw_res_deficit_mw_local'] = np.where(np.isfinite(deficit), deficit, np.nan).astype(np.float32)
    out['nw_res_min_avail_mw_local'] = np.where(np.isfinite(min_avail), min_avail, np.nan).astype(np.float32)
    has = first_start != BIG
    out['nw_minutes_since_start_local'] = np.where(has, (target - first_start) / 6e10, np.nan).astype(np.float32)
    out['nw_minutes_to_end_local'] = np.where(has, (last_end - target) / 6e10, np.nan).astype(np.float32)
    out = out[COLUMNS]
    result = pd.DataFrame(index=keys.index, columns=COLUMNS, dtype=np.float32)
    result.iloc[order] = out.to_numpy()
    return result.astype(np.float32)
