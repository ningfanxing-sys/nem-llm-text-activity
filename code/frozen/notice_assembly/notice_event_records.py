'Resolve notice references and construct event, window and quantity features.'
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

SEALED_NW_DIR = Path(__file__).resolve().parents[2] / 'notice_forecasting'
sys.path.insert(0, str(SEALED_NW_DIR))
import nw_notices as sealed_nw

ROOT = sealed_nw.ROOT
REGISTRY = sealed_nw.REGISTRY
LABELS = sealed_nw.LABELS
COLUMNS = sealed_nw.COLUMNS
REGIONS = sealed_nw.REGIONS
KINDS = sealed_nw.KINDS
NEM_OFFSET = sealed_nw.NEM_OFFSET
RECENT = sealed_nw.RECENT
BIG = sealed_nw.BIG
load_population = sealed_nw.load_population
parse_nem = sealed_nw.parse_nem
rule_regions = sealed_nw.rule_regions
rule_kind = sealed_nw.rule_kind

RECORD_COLUMNS = ['notice_id', 'region', 'kind', 'cancel', 'available_utc', 'start_utc',
                  'end_utc', 'req_mw', 'avail_mw', 'version_status', 'event_id',
                  'related_notice_ids', 'relation_scope', 'temporal_status',
                  'quantity_status', 'title_key', 'source_notice_type',
                  'source_body_regions', 'source_lor_level']
REF_BLOCK = re.compile(
    r'\b(?:electricity\s+)?market\s+notices?\s*(?:nos?\.?\s*)?[:#-]?\s*'
    r'(\d{4,8}(?:\s*(?:,|and|&)\s*\d{4,8})*)', re.I)
DATE_IN_TITLE = re.compile(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{1,2}\s+[A-Za-z]+\s+20\d{2}\b')
REGION_RELEASE = re.compile(
    r'\b(?:all|every)\s+(?:active\s+|forecast\s+|current\s+)?'
    r'(?:reserve\s+)?(?:conditions?|events?|outages?|constraints?)\s+'
    r'(?:in|across|throughout)\s+(?:the\s+)?(?:NSW|QLD|SA|TAS|VIC|'
    r'New South Wales|Queensland|South Australia|Tasmania|Victoria)\s+region\b'
    r'.{0,100}\b(?:cancelled|canceled|ceased|revoked|ended)\b', re.I)
PARTIAL_SCOPE = re.compile(
    r'\bonly\s+(?:the\s+)?(?:(?:NSW1?|QLD1?|SA1?|TAS1?|VIC1?)\s+)?'
    r'(?:reserve\s+|constraint\s+)?(?:conditions?|events?|outages?|windows?)\b', re.I)
REGION_FIELD = re.compile(r'\bRegion\s*:\s*(NSW1?|QLD1?|SA1?|TAS1?|VIC1?)\b', re.I)
BODY_CONDITION_REGION = re.compile(
    r'\b(?:condition|event|outage|reclassification)\s+in\s+(?:the\s+)?'
    r'(NSW1?|QLD1?|SA1?|TAS1?|VIC1?|New South Wales|Queensland|South Australia|Tasmania|Victoria)'
    r'\s+region\b', re.I)
REGION_NAMES = {'NEW SOUTH WALES': 'NSW1', 'QUEENSLAND': 'QLD1', 'SOUTH AUSTRALIA': 'SA1',
                'TASMANIA': 'TAS1', 'VICTORIA': 'VIC1'}


def _body_event_regions(text):
    matches = REGION_FIELD.findall(str(text)) or BODY_CONDITION_REGION.findall(str(text))
    return tuple(sorted({REGION_NAMES.get(m.upper(), m.upper().removesuffix('1') + '1') for m in matches}))


def rule_regions(title, text):
    # Prefer the explicit event region to equipment or interconnector codes.

    return list(_body_event_regions(text)) or sealed_nw.rule_regions(title, text)


def window_utc(start_text, end_text, anchor_local, available_utc):
    'Normalize explicit window endpoints in fixed NEM local time.'
    start, sp = parse_nem(start_text, anchor_local)
    if start is None:
        return pd.NaT, pd.NaT
    if sp == 'time_only' and end_text:
        # Take a time-only start date from its paired dated endpoint.

        end_probe, ep_probe = parse_nem(end_text, anchor_local)
        if end_probe is not None and ep_probe == 'datetime':
            start = end_probe.normalize() + (start - start.normalize())
            if start > end_probe:
                start -= pd.Timedelta(days=1)
            sp = 'date_from_end'
    if sp == 'time_only' and start < anchor_local - pd.Timedelta(hours=12):
        start += pd.Timedelta(days=1)
    start_utc = (start - NEM_OFFSET).tz_localize('UTC')
    end, ep = parse_nem(end_text, start) if end_text else (None, None)
    if end is None:
        return start_utc, pd.NaT
    if ep == 'time_only' and end <= start:
        end += pd.Timedelta(days=1)
    if ep == 'date_only':
        end += pd.Timedelta(days=1)
    end_utc = (end - NEM_OFFSET).tz_localize('UTC')
    return start_utc, end_utc if end_utc > start_utc else pd.NaT


def _temporal_status(start, end, end_text):
    if pd.isna(start):
        return 'UNKNOWN_START'
    if pd.notna(end):
        return 'BOUNDED'
    if end_text and 'further notice' in str(end_text).lower():
        return 'OPEN_UNTIL_NOTICE'
    return 'UNKNOWN_END'


def _references(text):
    return tuple(dict.fromkeys(ref for block in REF_BLOCK.findall(str(text))
                               for ref in re.findall(r'\b\d{4,8}\b', block)))


def _title_key(title):
    'Match dated event titles when no notice ID is available.'
    title = str(title)
    if not DATE_IN_TITLE.search(title):
        return ''
    value = title.lower()
    value = re.sub(r'^(?:stpasa|pdpasa)\s*[-:]\s*', '', value)
    value = re.sub(r'^(?:update\s*[-:]\s*|update\s+of\s+|cancellation\s+of\s+(?:the\s+)?|'
                   r'cancelled\s*[-:]\s*)', '', value)
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9/]+', ' ', value)).strip()


def _rule_windows_with_offsets(text):
    for i, pattern in enumerate(sealed_nw.RULE_WINDOWS):
        hits = list(pattern.finditer(text))
        if not hits:
            continue
        out = []
        for m in hits:
            g = m.groups()
            if i == 0:
                start, end = f'{g[0]} hrs {g[1]}', f'{g[2]} hrs {g[3]}'
            elif i == 1:
                start, end = f'{g[0]} hrs {g[2]}', f'{g[1]} hrs {g[2]}'
            elif i == 2:
                start, end = f'{g[0]} {g[1]}', None if g[2] == 'further notice' else g[2]
            elif i == 3:
                start = f'{g[0]} hrs' + (f' {g[1]}' if g[1] else '')
                end = None if not g[2] or g[2] == 'further notice' else g[2]
            else:
                start = f'{g[0]} hrs' + (f' {g[1]}' if g[1] else '')
                end = (f'{g[2]} hrs' + (f' {g[3]}' if g[3] else '')) if g[2] else None
            if end is None and 'further notice' in m.group(0).lower():
                end = 'until further notice'
            out.append((start, end, m.start()))
        return out
    return [(None, None, None)]


def _llm_window_offset(text, window, after):
    snippets = [window.get('start_text'), window.get('end_text')]
    snippets += [s for s in window.get('evidence_spans', []) if isinstance(s, str) and
                 re.search(r'\d{1,2}[:/]\d{1,2}|\d{4}\s*hrs', s)]
    for snippet in snippets:
        if not isinstance(snippet, str) or not snippet.strip():
            continue
        pattern = re.compile(r'\s+'.join(re.escape(p) for p in snippet.split()), re.I)
        hit = pattern.search(text, after) or pattern.search(text)
        if hit:
            return hit.start()
    return None


def _llm_quantities(text, items):
    out, used = [], set()
    for q in items:
        if str(q.get('unit', '')).upper() != 'MW' or q.get('direction') not in ('REQUIREMENT', 'AVAILABLE'):
            continue
        try:
            value = float(str(q.get('value_text', '')).replace(',', ''))
        except ValueError:
            continue
        if not np.isfinite(value):
            continue
        evidence = q.get('evidence_span')
        candidates = []
        if isinstance(evidence, str) and evidence.strip():
            pattern = re.compile(r'\s+'.join(re.escape(p) for p in evidence.split()), re.I)
            candidates = [m.start() for m in pattern.finditer(text)]
        if not candidates:
            number = re.escape(str(q.get('value_text', '')).replace(',', ''))
            candidates = [m.start() for m in re.finditer(r'\b' + number + r'\s*MW\b', text, re.I)]
        free = [p for p in candidates if p not in used]
        offset = free[0] if free else None
        if offset is not None:
            used.add(offset)
        out.append((q['direction'], value, offset))
    return out


def _rule_quantities(text):
    return ([('REQUIREMENT', float(m.group(1).replace(',', '')), m.start())
             for m in sealed_nw.RULE_REQ.finditer(text)] +
            [('AVAILABLE', float(m.group(1).replace(',', '')), m.start())
             for m in sealed_nw.RULE_AVAIL.finditer(text)])


def _bind_quantities(windows, quantities):
    'Bind MW quantities only to the window identified by their source span.'
    if len(windows) > 1 and any(w[3] is None for w in windows):
        return [(np.nan, np.nan, 'UNKNOWN_RELATION') for _ in windows]
    ordered = sorted([(int(w[3]), i) for i, w in enumerate(windows) if w[3] is not None])
    assigned = [defaultdict(list) for _ in windows]
    for role, value, offset in quantities:
        if len(windows) == 1:
            i = 0
        elif offset is None or not ordered or offset < ordered[0][0]:
            continue
        else:
            latest = max(start for start, _ in ordered if start <= offset)
            candidates = [j for start, j in ordered if start == latest]
            if len(candidates) != 1:
                continue  # Apply this source span to each listed region.
            i = candidates[0]
        assigned[i][role].append(value)
    out = []
    for values in assigned:
        def single(role):
            distinct = set(values[role])
            return next(iter(distinct)) if len(distinct) == 1 else np.nan
        req, avail = single('REQUIREMENT'), single('AVAILABLE')
        status = 'BOUND' if np.isfinite(req) and np.isfinite(avail) else 'UNKNOWN_RELATION'
        out.append((req, avail, status))
    return out


def _status(title, lifecycle=None, kind_raw=None):
    if re.search(r'\breturn(?:ed)?\s+to\s+service\b', title, re.I):
        return 'RECOVERY'
    if lifecycle in ('CANCELLATION', 'CEASED') or sealed_nw.CANCEL_RULE.search(title):
        return 'CANCELLATION'
    if lifecycle == 'RECLASSIFICATION':
        return 'RECLASSIFICATION'
    if kind_raw == 'RETURN_TO_SERVICE' and lifecycle == 'UPDATE':
        return 'RECOVERY'
    if lifecycle == 'UPDATE' or re.search(r'\bupdate(?:d)?\b', title, re.I):
        return 'UPDATE'
    return lifecycle if lifecycle in ('NEW', 'RECLASSIFICATION', 'UNKNOWN') else 'NEW'


def _rows_for_notice(r, windows, quantities):
    title = str(r.title)
    refs = _references(r.text)
    key = _title_key(title)
    body_regions = _body_event_regions(r.text)
    lor = re.search(r'\bLOR\s*([123])\b', str(r.text), re.I)
    bound = _bind_quantities([(w[0], w[3], w[4], w[5]) for w in windows], quantities)
    rows = []
    for (region, kind, status, start_text, end_text, _), (req, avail, qstatus) in zip(windows, bound):
        start, end = window_utc(start_text, end_text, r.anchor_local, r.available_utc)
        temporal = _temporal_status(start, end, end_text)
        scope = ('NOTICE_PARTIAL' if status in ('CANCELLATION', 'RECOVERY', 'UPDATE') and refs and
                 PARTIAL_SCOPE.search(r.text) else
                 'REGION_ALL' if status in ('CANCELLATION', 'RECOVERY') and not refs and
                 REGION_RELEASE.search(r.text) else 'EVENT')
        rows.append((str(r.notice_id), region, kind, status in ('CANCELLATION', 'RECOVERY'),
                     r.available_utc, start, end, req, avail, status, str(r.notice_id),
                     refs, scope, temporal, qstatus, key, str(r.notice_type), body_regions,
                     lor.group(1) if lor else ''))
    return rows


def frame(rows):
    out = pd.DataFrame(rows, columns=RECORD_COLUMNS)
    for c in ('available_utc', 'start_utc', 'end_utc'):
        out[c] = pd.to_datetime(out[c], utc=True)
    return out


def rule_records(pop):
    rows = []
    for r in pop.itertuples(index=False):
        regions = rule_regions(r.title, r.text)
        kind = rule_kind(r.notice_type, r.title)
        status = _status(r.title)
        source_windows = [(None, None, None)] if status in ('CANCELLATION', 'RECOVERY') else _rule_windows_with_offsets(r.text)
        windows = [(reg, kind, status, start, end, offset) for reg in regions
                   for start, end, offset in source_windows]
        rows.extend(_rows_for_notice(r, windows, _rule_quantities(r.text)))
    return frame(rows)


def llm_records(pop):
    labels = pd.read_parquet(LABELS, columns=['notice_id', 'notice_type', 'impact_windows_json',
                                               'lifecycle', 'quantities_json'])
    labels['notice_id'] = labels.notice_id.astype(str)
    if labels.notice_id.duplicated().any():
        raise ValueError('Duplicate LLM label')
    merged = pop.merge(labels.drop(columns=['notice_type']), on='notice_id', how='inner', validate='one_to_one')
    rows = []
    for r in merged.itertuples(index=False):
        windows, after = [], 0
        for w in json.loads(r.impact_windows_json):
            region = w.get('region')
            if region not in REGIONS:
                continue
            kind_raw = w.get('window_kind')
            kind = ('CONSTRAINT' if r.notice_type == 'RECLASSIFY CONTINGENCY' else
                    kind_raw if kind_raw in ('RESERVE', 'CONSTRAINT', 'INTERVENTION', 'OUTAGE')
                    else 'OUTAGE' if kind_raw == 'RETURN_TO_SERVICE'
                    else sealed_nw.TYPE_KIND.get(r.notice_type, 'OTHER'))
            status = _status(r.title, r.lifecycle, kind_raw)
            offset = _llm_window_offset(r.text, w, after)
            if offset is not None:
                after = offset + 1
            windows.append((region, kind, status, w.get('start_text'), w.get('end_text'), offset))
        closing = _status(r.title, r.lifecycle)
        if not windows and closing in ('CANCELLATION', 'RECOVERY'):
            # Locate window-free cancellations from the source region and notice type.

            kind = ('CONSTRAINT' if r.notice_type == 'RECLASSIFY CONTINGENCY'
                    else sealed_nw.TYPE_KIND.get(r.notice_type, 'OTHER'))
            windows = [(region, kind, closing, None, None, None) for region in rule_regions(r.title, r.text)]
        rows.extend(_rows_for_notice(r, windows, _llm_quantities(r.text, json.loads(r.quantities_json))))
    return frame(rows), len(merged)


def shifted(records, days):
    out = records.copy()
    delta = pd.Timedelta(days=days)
    for c in ('available_utc', 'start_utc', 'end_utc', 'close_utc'):
        if c not in out:
            continue
        out[c] = out[c] + delta
    return out


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
    groups = {str(n): g for n, g in out.groupby('notice_id', sort=False)}
    ordered = sorted(groups, key=lambda n: (groups[n].available_utc.iloc[0], n))
    close_ns = np.full(len(out), BIG, dtype=np.int64)
    event_id = [''] * len(out)
    relation_basis = [''] * len(out)
    notice_events = {}
    notice_available = {}
    active_by_event = defaultdict(set)
    title_index = defaultdict(set)

    def close_indices(indices, at):
        at_ns = int(at.value)
        for index in indices:
            close_ns[index] = min(close_ns[index], at_ns)

    for notice_id in ordered:
        group = groups[notice_id]
        first = group.iloc[0]
        now = first.available_utc
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
                    if not stated_regions and not (set(group.region) & cited_regions):
                        incompatible = 'INCOMPATIBLE_SOURCE_REGION'
                        continue
                    targets.update(notice_events[ref])
            if incompatible:
                targets.clear()
                basis = incompatible
            else:
                basis = 'EXPLICIT_NOTICE_ID' if targets else 'UNRESOLVED_REFERENCE'
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
                active_by_event[event].difference_update(matched)
        else:
            for event in targets:
                # Withdraw the cited event across its linked regions and event types.

                close_indices(active_by_event[event], now)
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
        notice_available[notice_id] = now

    out['event_id'] = event_id
    out['relation_basis'] = relation_basis
    out['close_utc'] = pd.Series(pd.NaT, index=out.index, dtype='datetime64[ns, UTC]')
    finite = close_ns != BIG
    if finite.any():
        out.loc[finite, 'close_utc'] = pd.to_datetime(close_ns[finite], unit='ns', utc=True)
    return out


def relation_audit(records):
    'Count notice relations using source records.'
    resolved = resolve_event_states(records)
    notice = resolved.drop_duplicates('notice_id')
    action = notice.loc[notice.version_status.isin(['UPDATE', 'CANCELLATION', 'RECOVERY'])]
    linked = action.relation_basis.isin(['EXPLICIT_NOTICE_ID', 'UNIQUE_DATED_TITLE',
                                        'DATED_TITLE_OVERLAP', 'REGION_ALL'])
    return {'records': len(records), 'notices': len(notice),
            'action_notices': len(action), 'action_resolved': int(linked.sum()),
            'action_unresolved': int((~linked).sum()),
            'dated_title_component_notices': int(notice.relation_basis.eq('DATED_TITLE_OVERLAP').sum()),
            'explicit_reference_notices': int(notice.relation_basis.eq('EXPLICIT_NOTICE_ID').sum()),
            'unknown_temporal_records': int(records.temporal_status.isin(['UNKNOWN_START', 'UNKNOWN_END']).sum()),
            'unknown_quantity_records': int(records.quantity_status.eq('UNKNOWN_RELATION').sum()),
            'event_components': notice.event_id.nunique()}


def _ns(series):
    return series.dt.tz_convert('UTC').dt.as_unit('ns').astype('int64').to_numpy()


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
    for r in rec.loc[~rec.cancel].itertuples(index=False):
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
    per_notice = rec.groupby(['notice_id', 'region'], as_index=False).agg(a=('a', 'min'), cancel=('cancel', 'max'))
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
