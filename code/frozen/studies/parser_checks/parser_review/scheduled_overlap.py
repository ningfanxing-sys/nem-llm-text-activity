'Compute notice overlap features with the prospective-schedule predicate.'
import json
import numpy as np
import pandas as pd

KIND_COL = {'RESERVE': ('nw_res_local', 'nw_res_foreign'), 'CONSTRAINT': ('nw_con_local', 'nw_con_foreign'),
            'INTERVENTION': ('nw_int_local', None), 'OUTAGE': ('nw_out_local', 'nw_out_foreign'), 'OTHER': (None, None)}


def features_overlap(v2, keys, records, hours, prospective_gate=True):

    columns, big = v2.COLUMNS, v2.BIG
    n = len(keys); span = np.int64(hours * 3600 * 10**9)
    order = np.argsort(v2._ns(keys.issue_time), kind='stable')
    issue = v2._ns(keys.issue_time)[order]
    regions = keys.region.to_numpy()[order]
    counts = {c: np.zeros(n, dtype=np.float32) for c in columns[:8] + columns[12:]}
    deficit = np.full(n, -np.inf); min_avail = np.full(n, np.inf)
    first_start = np.full(n, big, dtype=np.int64); last_end = np.full(n, np.iinfo(np.int64).min, dtype=np.int64)
    unknown_end = np.zeros(n, dtype=bool)
    rec = v2.resolve_event_states(records)
    rec['a'] = v2._ns(rec.available_utc); rec['s'] = v2._ns(rec.start_utc); rec['e'] = v2._ns(rec.end_utc)
    rec['c'] = np.where(rec.close_utc.isna(), big, v2._ns(rec.close_utc))
    for r in rec.loc[~rec.cancel].itertuples(index=False):
        if r.temporal_status not in ('BOUNDED', 'OPEN_UNTIL_NOTICE'):
            continue
        bounded = r.temporal_status == 'BOUNDED'


        close = min(r.c, r.e) if bounded else min(r.c, r.a + v2.sealed_nw.LOOKBACK)
        lo = np.searchsorted(issue, r.a, side='left'); hi = np.searchsorted(issue, close, side='left')
        if hi <= lo:
            continue
        idx = np.arange(lo, hi)
        idx = idx[r.s < issue[idx] + span]
        if bounded:
            idx = idx[r.e > issue[idx]]
        if prospective_gate:


            for announced, effective, _ in json.loads(getattr(r, 'prospective_closures_json', '[]')):
                ann_ns = pd.Timestamp(announced).value
                eff_ns = pd.Timestamp(effective).value
                exclude = (issue[idx] >= ann_ns) & ((issue[idx] >= eff_ns) | (r.s >= eff_ns))
                idx = idx[~exclude]
        if not len(idx):
            continue
        local = idx[regions[idx] == r.region]; foreign = idx[regions[idx] != r.region]
        lc, fc = KIND_COL[r.kind]
        if lc and len(local):
            counts[lc][local] += 1
        if fc and len(foreign):
            counts[fc][foreign] += 1
        if len(local):
            counts['nw_any_local'][local] += 1
            np.minimum.at(first_start, local, r.s)
            if bounded:
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
        lo = np.searchsorted(issue, r.a, side='left'); hi = np.searchsorted(issue, r.a + v2.RECENT, side='left')
        if hi <= lo:
            continue
        idx = np.arange(lo, hi); idx = idx[regions[idx] == r.region]
        counts['nw_cancel_local_6h' if r.cancel else 'nw_new_local_6h'][idx] += 1
    out = pd.DataFrame(counts)
    out['nw_res_deficit_mw_local'] = np.where(np.isfinite(deficit), deficit, np.nan).astype(np.float32)
    out['nw_res_min_avail_mw_local'] = np.where(np.isfinite(min_avail), min_avail, np.nan).astype(np.float32)
    has = first_start != big
    out['nw_minutes_since_start_local'] = np.where(has, (first_start - issue) / 6e10, np.nan).astype(np.float32)
    has_end = has & ~unknown_end & (last_end != np.iinfo(np.int64).min)
    out['nw_minutes_to_end_local'] = np.where(has_end, (last_end - issue) / 6e10, np.nan).astype(np.float32)
    out = out[columns]
    result = pd.DataFrame(index=keys.index, columns=columns, dtype=np.float32)
    result.iloc[order] = out.to_numpy()
    return result.astype(np.float32)
