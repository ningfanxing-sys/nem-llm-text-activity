
'Reconstruct the hourly panels in bounded chunks.'
from __future__ import annotations

import csv
import gc
import hashlib
import io
import json
import resource
import sys
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

OUT = Path(__file__).resolve().parent
REGIONS = ('NSW1', 'QLD1', 'TAS1')
FIELDS = ('RRP', 'TOTALDEMAND', 'AVAILABLEGENERATION',
          'DISPATCHABLEGENERATION', 'NETINTERCHANGE', 'DEMANDFORECAST')
NAMES = ('price',) + tuple('phys_' + x.lower() for x in FIELDS[1:])
TZ = 'Australia/Brisbane'
FIVE = 300_000_000_000
HOUR = 12 * FIVE
DAY = 24 * HOUR
NAT = np.iinfo(np.int64).min
START = pd.Timestamp('2021-10-01', tz=TZ).tz_convert('UTC').value
END = pd.Timestamp('2026-01-01', tz=TZ).tz_convert('UTC').value
N = (END - START) // FIVE + 1
LIMIT = int(1.5 * 1024**3)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def write(name, obj):
    (OUT / name).write_text(json.dumps(obj, indent=2, allow_nan=False) + '\n')


def rss():
    v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(v if sys.platform == 'darwin' else v * 1024)


def log(stage, **kw):
    obj = dict(utc=datetime.now(timezone.utc).isoformat(), stage=stage,
               peak_rss_bytes=rss(), **kw)
    with (OUT / 'progress.jsonl').open('a') as f:
        f.write(json.dumps(obj) + '\n')
    print(json.dumps(obj), flush=True)
    if rss() > LIMIT:
        raise MemoryError('Reader peak RSS exceeded frozen 1.5 GiB ceiling')


def clocks(series):
    return pd.DatetimeIndex(pd.to_datetime(series, format='%Y/%m/%d %H:%M:%S',
                           errors='coerce')).tz_localize(TZ).tz_convert('UTC').as_unit('ns').asi8


def iso(ns):
    return None if int(ns) == NAT else pd.Timestamp(int(ns), tz='UTC').isoformat()


def slots(values, availability, issue):
    legal = np.isfinite(values) & (availability != NAT) & (availability <= issue)
    counts = legal.sum(axis=-1)
    complete = counts == 12
    means = np.where(complete, np.where(legal, values, 0).sum(axis=-1) / 12, np.nan)
    maximum = np.max(np.where(legal, availability, NAT), axis=-1)
    return means, complete.astype(np.uint8), counts.astype(np.uint8), maximum


def synthetic_checks():
    t = pd.Timestamp('2025-01-01', tz=TZ).tz_convert('UTC').value
    target_ends = t + np.arange(1, 13) * FIVE
    history_ends = t - HOUR + np.arange(12) * FIVE
    assert target_ends[-1] == t + HOUR
    assert history_ends[-1] == t - FIVE
    assert ((target_ends - FIVE - t) // HOUR == 0).all()
    a = history_ends + FIVE
    m, mask, count, _ = slots(np.arange(12, dtype=float)[None, :], a[None, :], t)
    assert m[0] == 5.5 and mask[0] == 1 and count[0] == 12
    a[-1] = t + 1
    m, mask, count, _ = slots(np.arange(12, dtype=float)[None, :], a[None, :], t)
    assert np.isnan(m[0]) and mask[0] == 0 and count[0] == 11
    frame = pd.DataFrame({'region': ['NSW1'] * 3, 'end': [t] * 3,
                          'RRP': [1., 1., 1.], 'clock': [t, t, t + 1]})
    dedup = frame.drop_duplicates()
    assert len(dedup) == 2 and dedup.duplicated(['region', 'end'], keep=False).all()
    assert pd.Timestamp(t, tz='UTC').tz_convert(TZ).strftime('%Y-%m-%d %H:%M') == '2025-01-01 00:00'
    return dict(state='PASS', checks=['fixed AEST midnight/year input_checks',
                '12-interval target and shifted history alignment',
                'availability equal to issue admitted; one nanosecond later rejected',
                'arithmetic mean and incomplete-slot mask',
                'same price/different clock is conflicting after exact collapse'])


def preflight():
    freeze = json.loads((OUT / 'FREEZE.json').read_text())
    for name, expected in freeze['files_sha256'].items():
        assert sha(OUT / name) == expected, name
    for path, expected in {**freeze['new_sd_verified_files_sha256'],
                           **freeze['contracts_sha256']}.items():
        assert sha(path) == expected, path
    assert sha(OUT.parents[2] / 'paper_plan/task_specs/COMMON_RULES.md') == freeze['current_common_rules_sha256']
    code = json.loads((OUT / 'CODE_FREEZE.json').read_text())
    assert sha(__file__) == code['build_panel.py_sha256']
    assert sha(OUT / 'FREEZE.json') == code['rules_freeze_sha256']
    return json.loads((OUT / 'SOURCE_MANIFEST.json').read_text())['sources']


class RawStore:
    def __init__(self):
        self.values = np.full((3, N, 6), np.nan, dtype=np.float64)
        self.price_clock = np.full((3, N), NAT, dtype=np.int64)
        self.source = np.full((3, N, 2), -1, dtype=np.int16)
        self.outside = {}
        self.receipts = []

    def consume(self, rows, rec, receipt):
        price = rec['family'] == 'price'
        cols = ['end', 'region'] + (['RRP', 'LASTCHANGED'] if price else list(FIELDS[1:]))
        d = pd.DataFrame(rows, columns=cols)
        d['end'] = clocks(d['end'])
        if (d.end == NAT).any() or ((d.end - START) % FIVE != 0).any():
            raise ValueError('Invalid/off-grid SETTLEMENTDATE: ' + rec['path'])
        for c in cols[2:]:
            d[c] = clocks(d[c]) if c == 'LASTCHANGED' else pd.to_numeric(d[c], errors='coerce')
        reference_snapshot = len(d)
        d = d.drop_duplicates()
        receipt['exact_duplicates'] += reference_snapshot - len(d)
        conflict = d.duplicated(['region', 'end'], keep=False)
        if conflict.any():
            d.loc[conflict].to_csv(OUT / 'CONFLICTING_RAW_KEYS.csv', index=False)
            raise ValueError('Conflicting projected keys inside chunk: ' + rec['path'])
        if price:
            receipt['invalid_LASTCHANGED'] += int((d.LASTCHANGED == NAT).sum())
        fam = 0 if price else 1
        for row in d.itertuples(index=False, name=None):
            end, region = row[:2]
            r = REGIONS.index(region)
            idx = (end - START) // FIVE
            nums = np.asarray(row[2:3] if price else row[2:], dtype=np.float64)
            lc = int(row[-1]) if price else NAT
            if idx < 0 or idx >= N:
                key = (fam, r, int(end))
                payload = tuple(row[2:])
                old = self.outside.get(key)
                if old is not None:
                    if not all(a == b or (pd.isna(a) and pd.isna(b)) for a, b in zip(old, payload)):
                        raise ValueError('Conflicting out-of-grid key: ' + rec['path'])
                    receipt['exact_duplicates'] += 1
                else:
                    self.outside[key] = payload
                receipt['outside_study_grid_rows'] += 1
                continue
            prior = int(self.source[r, idx, fam])
            dst = slice(0, 1) if price else slice(1, 6)
            if prior >= 0:
                same = np.array_equal(self.values[r, idx, dst], nums, equal_nan=True)
                same = same and (not price or self.price_clock[r, idx] == lc)
                if not same:
                    write('CONFLICTING_RAW_KEYS.json', dict(region=region,
                          interval_end_utc=iso(end), previous_source_id=prior,
                          current_source_id=rec['source_id'], path=rec['path']))
                    raise ValueError('Conflicting cross-chunk/file key: ' + rec['path'])
                receipt['exact_duplicates'] += 1
                continue
            self.values[r, idx, dst] = nums
            self.price_clock[r, idx] = lc if price else self.price_clock[r, idx]
            self.source[r, idx, fam] = rec['source_id']
            receipt['unique_grid_keys_added'] += 1

    def read_archive(self, rec):
        assert sha(rec['path']) == rec['sha256'], rec['path']
        receipt = dict(source_id=rec['source_id'], month=rec['month'], family=rec['family'],
                       path=rec['path'], sha256=rec['sha256'], target_region_rows=0,
                       ignored_other_region_rows=0, intervention_rows_discarded=0,
                       other_run_rows_discarded={}, exact_duplicates=0,
                       conflicting_keys=0, invalid_LASTCHANGED=0,
                       outside_study_grid_rows=0, unique_grid_keys_added=0,
                       csv_chunk_rows=10000)
        price = rec['family'] == 'price'
        fields = ['SETTLEMENTDATE', 'REGIONID'] + (['RRP', 'LASTCHANGED'] if price else list(FIELDS[1:]))
        table = 'PRICE' if price else 'REGIONSUM'
        required = fields + ['INTERVENTION'] + (['RUNNO'] if price else [])
        chunk, runs = [], Counter()
        with zipfile.ZipFile(rec['path']) as z:
            members = [x for x in z.namelist() if x.lower().endswith('.csv')]
            assert len(members) == 1, rec['path']
            receipt['zip_member'] = members[0]
            header = None
            with z.open(members[0]) as f:
                for row in csv.reader(io.TextIOWrapper(f, encoding='utf-8-sig')):
                    if len(row) < 4 or row[1:3] != ['DISPATCH', table]:
                        continue
                    if row[0] == 'I':
                        header = {c: i for i, c in enumerate(row)}
                        assert set(required) <= set(header), (rec['path'], required)
                        continue
                    if row[0] != 'D':
                        continue
                    if header is None:
                        raise ValueError('Data before required header')
                    if row[header['REGIONID']] not in REGIONS:
                        receipt['ignored_other_region_rows'] += 1
                        continue
                    receipt['target_region_rows'] += 1
                    if row[header['INTERVENTION']] not in ('0', '0.0'):
                        receipt['intervention_rows_discarded'] += 1
                        continue
                    if price and row[header['RUNNO']] not in ('1', '1.0'):
                        runs[row[header['RUNNO']]] += 1
                        continue
                    chunk.append([row[header[c]] for c in fields])
                    if len(chunk) == 10000:
                        self.consume(chunk, rec, receipt)
                        chunk.clear()
                if chunk:
                    self.consume(chunk, rec, receipt)
        receipt['other_run_rows_discarded'] = dict(runs)
        self.receipts.append(receipt)
        write('ARCHIVE_RECEIPTS.json', self.receipts)
        log('archive_complete', source_id=rec['source_id'], family=rec['family'], month=rec['month'])


def provenance(sources):
    columns = {}
    def add(name, role, description, source='derived'):
        columns[name] = dict(role=role, description=description, source=source)
    for name in ['issue_time_utc', 'issue_date_aest', 'region', 'split', 'target_hour_start_utc',
                 'target_hour_end_utc', 'target_date_aest']:
        add(name, 'key_or_audit', 'Frozen nominal AEST issue/target identity')
    add('region_code', 'predictor', 'NSW1=0, QLD1=1, TAS1=2')
    add('horizon', 'predictor', 'Target hour 0..23 on issue day')
    for x in ['hour', 'weekday', 'month']:
        for trig in ['sin', 'cos']:
            add('target_' + x + '_' + trig, 'predictor',
                f'{trig} cyclic calendar encoding: hour/24, Monday-zero weekday/7, (month-1)/12')
    for name in ['target_price', 'target_interval_count', 'target_price_available_time_utc',
                 'day_label_available_time_utc', 'pooled_day_label_available_time_utc',
                 'target_price_source_ids', 'weekly_naive_price', 'weekly_naive_interval_count',
                 'weekly_naive_available_time_utc', 'weekly_naive_source_ids',
                 'weekly_naive_issue_legal', 'history_source_window_complete', 'history_eligible', 'train_history_eligible']:
        add(name, 'label_or_audit', 'See SPEC target/weekly-naive/eligibility rules',
            'DISPATCHPRICE or interval-presence audit')
    for j, name in enumerate(NAMES):
        src = 'DISPATCHPRICE.RRP' if j == 0 else 'DISPATCHREGIONSUM.' + FIELDS[j]
        for k in range(1, 73):
            col = f'{name}_lag_{k:02d}'
            add(col, 'predictor', f'Mean of 12 finite legal ends issue-{k}h .. issue-{k-1}h-5min', src)
            add(col + '_observed', 'predictor', '1 iff all 12 expected values finite and available <= issue', src)
            add(col + '_legal_count', 'audit', '0..12 legal finite constituents', src)
            add(col + '_max_legal_available_time_utc', 'audit', 'Max accepted clock, even for partial slot', src)
            add(col + '_source_ids', 'audit', 'Distinct source IDs of raw constituents; SOURCE_MANIFEST lookup', src)
    obj = dict(spec_sha256=sha(OUT / 'SPEC.md'), source_manifest_sha256=sha(OUT / 'SOURCE_MANIFEST.json'),
               clock='AEST UTC+10 / stored UTC', columns=columns,
               selected_sources=sources, audit_columns_excluded_from_predictors=True)
    write('COLUMN_PROVENANCE.json', obj)
    return obj


def source_ids(ids):
    return ','.join(str(int(x)) for x in np.unique(ids) if x >= 0)


def split_name(date):
    return 'train' if date.year < 2024 else 'validation' if date.year == 2024 else 'test'


def aggregate_targets(raw):

    v = raw.values[:, 1:, 0].reshape(3, -1, 12)
    ends = START + np.arange(1, N, dtype=np.int64) * FIVE
    lc = raw.price_clock[:, 1:]
    a = np.where(lc != NAT, np.maximum(ends[None, :] + FIVE, lc), NAT).reshape(3, -1, 12)
    count = np.isfinite(v).sum(axis=-1).astype(np.uint8)
    means = np.where(count == 12, np.where(np.isfinite(v), v, 0).sum(axis=-1) / 12, np.nan)
    full_clock = (a != NAT).all(axis=-1) & (count == 12)
    max_avail = np.where(full_clock, np.max(a, axis=-1), NAT)
    return means, count, max_avail


def raw_gap_audit(raw, sources):

    by_id = {x['source_id']: x for x in sources}
    selected = {(x['family'], x['month']): x for x in sources}
    counts = Counter()
    with (OUT / 'RAW_GAPS.csv').open('w') as f:
        w = csv.writer(f)
        w.writerow(['region', 'interval_end_utc', 'interval_end_aest', 'field', 'reason',
                    'observed_source_id', 'selected_month_source_path', 'official_url', 'official_fill_status'])
        for r, region in enumerate(REGIONS):
            for j, field in enumerate(FIELDS):
                fam = 0 if j == 0 else 1
                bad = ~np.isfinite(raw.values[r, 1:, j])
                if j == 0:
                    bad |= raw.price_clock[r, 1:] == NAT
                for ix in np.flatnonzero(bad) + 1:
                    end = START + int(ix) * FIVE
                    aest = pd.Timestamp(end, tz='UTC').tz_convert(TZ)
                    month = (aest - pd.Timedelta(minutes=5)).strftime('%Y-%m')
                    rec = selected[('price' if j == 0 else 'physical', month)]
                    sid = int(raw.source[r, ix, fam])
                    reason = 'missing_interval' if sid < 0 else 'nonfinite_value' if not np.isfinite(raw.values[r, ix, j]) else 'invalid_LASTCHANGED'
                    counts[(region, field, reason)] += 1
                    w.writerow([region, iso(end), aest.isoformat(), field, reason, sid,
                                rec['path'], rec['official_url'] or '', 'UNVERIFIED_NO_DOWNLOAD'])
    return [dict(region=k[0], field=k[1], reason=k[2], count=v) for k, v in counts.items()]


def build(raw, sources):
    means, counts, avail = aggregate_targets(raw)
    gaps = raw_gap_audit(raw, sources)
    prov = provenance(sources)
    days = pd.date_range('2021-10-01', '2025-12-31', freq='D', tz=TZ)
    stats = {s: dict(days=0, expected_rows=0, finite_target_rows=0, proven_target_clock_rows=0,
                    complete_72_target_days=0, legal_weekly_naive_rows=0,
                    source_window_complete_issues=0, regions={}) for s in ['train', 'validation', 'test']}
    for s in stats:
        for reg in REGIONS:
            stats[s]['regions'][reg] = dict(complete_target_days=0, complete_clock_days=0,
                                             legal_weekly_naive_hours=0)
    missing_slots = Counter()
    missing_lags = Counter()
    exclusions = []
    target_gaps = []
    naive_gaps = []
    audits = []
    writer = None
    chunk_frames = []
    chunk_month = None
    hours = means.shape[1]
    first_support = np.empty((3, 2), dtype=np.int64)
    by_source_id = {rec['source_id']: rec for rec in sources}
    by_month = {(rec['family'], rec['month']): rec for rec in sources}
    hist_file = (OUT / 'HISTORY_SLOT_GAPS.csv').open('w')
    hist_writer = csv.writer(hist_file)
    hist_writer.writerow(['issue_date_aest', 'issue_time_utc', 'region', 'field', 'lag',
                          'legal_count', 'reasons', 'source_ids', 'selected_source_paths',
                          'illegal_interval_end_utc_and_reason'])
    for r in range(3):
        for fam in range(2):
            ix = np.flatnonzero(raw.source[r, :, fam] >= 0)
            first_support[r, fam] = START + int(ix[0]) * FIVE if len(ix) else END + FIVE
    def flush():
        nonlocal writer, chunk_frames
        if not chunk_frames:
            return
        data = pd.concat(chunk_frames, ignore_index=True)
        table = pa.Table.from_pandas(data, preserve_index=False)
        if writer is None:
            fields = [f.with_metadata({b'provenance': json.dumps(prov['columns'][f.name]).encode()}) for f in table.schema]
            schema = pa.schema(fields, metadata={b'DAPANEL_SPEC_SHA256': sha(OUT / 'SPEC.md').encode(),
                        b'DAPANEL_FREEZE_SHA256': sha(OUT / 'FREEZE.json').encode(),
                        b'DAPANEL_SOURCE_MANIFEST_SHA256': sha(OUT / 'SOURCE_MANIFEST.json').encode(),
                        b'DAPANEL_COLUMN_PROVENANCE_SHA256': sha(OUT / 'COLUMN_PROVENANCE.json').encode(),
                        b'DAPANEL_GATE': b'PENDING_SEPARATE_COVERAGE_AND_VERIFICATION_REQUIRED',
                        b'DAPANEL_CLOCK': b'AEST UTC+10; timestamp columns UTC',
                        b'DAPANEL_NO_MODEL_FITS': b'true'})
            writer = pq.ParquetWriter(OUT / 'panel.parquet', schema, compression='zstd', use_dictionary=True)
        table = table.cast(writer.schema)
        writer.write_table(table, row_group_size=len(data))
        chunk_frames = []
        del data, table
        gc.collect()
        log('panel_month_written', month=chunk_month)
    for di, day in enumerate(days):
        month = day.strftime('%Y-%m')
        if chunk_month is not None and month != chunk_month:
            flush()
        chunk_month = month
        issue = day.tz_convert('UTC').value
        s = split_name(day)
        st = stats[s]
        st['days'] += 1
        st['expected_rows'] += 72
        lo = di * 24
        hi = lo + 24
        pooled_day_avail = int(avail[:, lo:hi].max()) if (avail[:, lo:hi] != NAT).all() else NAT
        st['complete_72_target_days'] += int(np.isfinite(means[:, lo:hi]).all())
        for r, reg in enumerate(REGIONS):
            slot_ends = issue - np.arange(1, 73, dtype=np.int64)[:, None] * HOUR + np.arange(12) * FIVE
            idx = (slot_ends - START) // FIVE
            within = (idx >= 0) & (idx < N)
            safe = np.clip(idx, 0, N - 1)
            vals = raw.values[r, safe, :].transpose(2, 0, 1).copy()
            vals[:, ~within] = np.nan
            phys_a = slot_ends + FIVE
            lc = raw.price_clock[r, safe]
            price_a = np.where((lc != NAT) & within, np.maximum(phys_a, lc), NAT)
            aa = np.broadcast_to(phys_a, vals.shape).copy()
            aa[0] = price_a
            aa[:, ~within] = NAT
            hist, masks, legal_counts, maximum = slots(vals, aa, issue)
            present = raw.source[r, safe, :] >= 0
            window_complete = bool(within.all() and present.all())

            early_ineligible = bool(slot_ends.min() < first_support[r].max())
            history_eligible = not early_ineligible
            eligible = s == 'train' and not early_ineligible
            if s == 'train' and early_ineligible:
                exclusions.append(dict(issue_date_aest=day.strftime('%Y-%m-%d'), region=reg,
                                       reason='72h window extends before selected source support'))
            st['source_window_complete_issues'] += int(window_complete)
            for j, name in enumerate(NAMES):
                missing_slots[(s, reg, name)] += int((masks[j] == 0).sum())
                for k in np.flatnonzero(masks[j] == 0):
                    missing_lags[(s, reg, name, int(k + 1))] += 1
                    details, paths, reasons = [], set(), set()
                    for q in range(12):
                        end = int(slot_ends[k, q])
                        sid = int(raw.source[r, safe[k,q], 0 if j == 0 else 1]) if within[k,q] else -1
                        if sid >= 0:
                            paths.add(by_source_id[sid]['path'])
                        else:
                            stamp = pd.Timestamp(end,tz='UTC').tz_convert(TZ)
                            for mon in {stamp.strftime('%Y-%m'), (stamp-pd.Timedelta(minutes=5)).strftime('%Y-%m')}:
                                rec = by_month.get(('price' if j == 0 else 'physical',mon))
                                if rec:
                                    paths.add(rec['path'])
                        reason = ('before_selected_support' if end < first_support[r,0 if j == 0 else 1]
                                  else 'missing_interval' if sid < 0
                                  else 'nonfinite_value' if not np.isfinite(vals[j,k,q])
                                  else 'unproven_price_clock' if aa[j,k,q] == NAT
                                  else 'after_issue' if aa[j,k,q] > issue else None)
                        if reason:
                            details.append({'interval_end_utc':iso(end),'reason':reason})
                            reasons.add(reason)
                    ids = raw.source[r,safe[k],0 if j == 0 else 1]
                    hist_writer.writerow([day.strftime('%Y-%m-%d'),iso(issue),reg,name,int(k+1),
                         int(legal_counts[j,k]),','.join(sorted(reasons)),source_ids(ids[within[k]]),
                         json.dumps(sorted(paths)),json.dumps(details)])
            a = avail[r, lo:hi]
            target = means[r, lo:hi]
            naive_idx = np.arange(lo, hi) - 168
            naive = np.full(24, np.nan)
            naive_a = np.full(24, NAT, dtype=np.int64)
            naive_c = np.zeros(24, dtype=np.uint8)
            in_naive = naive_idx >= 0
            naive_a[in_naive] = avail[r, naive_idx[in_naive]]
            naive_c[in_naive] = counts[r, naive_idx[in_naive]]
            legal = in_naive & (naive_a != NAT) & (naive_a <= issue)
            naive[legal] = means[r, naive_idx[legal]]
            legal &= np.isfinite(naive)
            naive[~legal] = np.nan
            st['finite_target_rows'] += int(np.isfinite(target).sum())
            st['proven_target_clock_rows'] += int((a != NAT).sum())
            st['legal_weekly_naive_rows'] += int(legal.sum())
            st['regions'][reg]['complete_target_days'] += int(np.isfinite(target).all())
            st['regions'][reg]['complete_clock_days'] += int((a != NAT).all())
            st['regions'][reg]['legal_weekly_naive_hours'] += int(legal.sum())
            for h in range(24):
                if not np.isfinite(target[h]) or a[h] == NAT:
                    target_gaps.append(dict(issue_date_aest=day.strftime('%Y-%m-%d'), region=reg,
                         horizon=h, target_hour_start_utc=iso(issue + h * HOUR),
                         finite_intervals=int(counts[r, lo+h]), proven_clock=bool(a[h] != NAT)))
                if not legal[h]:
                    naive_gaps.append(dict(issue_date_aest=day.strftime('%Y-%m-%d'), region=reg,
                        horizon=h, split=s, reason='before_selected_support' if not in_naive[h] else
                        'incomplete_price_or_clock' if naive_a[h] == NAT else 'late_availability'))
            data = dict(issue_time_utc=pd.to_datetime(np.repeat(issue, 24), utc=True),
                        issue_date_aest=[day.strftime('%Y-%m-%d')] * 24, region=[reg] * 24,
                        split=[s] * 24, region_code=np.repeat(np.uint8(r), 24),
                        horizon=np.arange(24, dtype=np.uint8),
                        target_hour_start_utc=pd.to_datetime(issue + np.arange(24) * HOUR, utc=True),
                        target_hour_end_utc=pd.to_datetime(issue + np.arange(1, 25) * HOUR, utc=True),
                        target_date_aest=[day.strftime('%Y-%m-%d')] * 24,
                        target_price=target, target_interval_count=counts[r, lo:hi],
                        target_price_available_time_utc=pd.to_datetime(a, utc=True),
                        day_label_available_time_utc=pd.to_datetime(np.repeat(a.max() if (a != NAT).all() else NAT, 24), utc=True),
                        pooled_day_label_available_time_utc=pd.to_datetime(np.repeat(pooled_day_avail, 24), utc=True),
                        target_price_source_ids=[source_ids(raw.source[r, 1+(lo+h)*12:1+(lo+h+1)*12, 0]) for h in range(24)],
                        weekly_naive_price=naive, weekly_naive_interval_count=naive_c,
                        weekly_naive_available_time_utc=pd.to_datetime(naive_a, utc=True),
                        weekly_naive_source_ids=[source_ids(raw.source[r, 1+int(ni)*12:1+(int(ni)+1)*12, 0]) if ni >= 0 else '' for ni in naive_idx],
                        weekly_naive_issue_legal=legal.astype(np.uint8),
                        history_source_window_complete=np.repeat(window_complete, 24),
                        history_eligible=np.repeat(history_eligible, 24),
                        train_history_eligible=np.repeat(eligible, 24))
            for label, phases in [('hour', np.arange(24)/24),
                                  ('weekday', np.repeat(day.weekday()/7, 24)),
                                  ('month', np.repeat((day.month-1)/12, 24))]:
                data['target_'+label+'_sin'] = np.sin(2*np.pi*phases)
                data['target_'+label+'_cos'] = np.cos(2*np.pi*phases)
            for j, name in enumerate(NAMES):
                for k in range(72):
                    col = f'{name}_lag_{k+1:02d}'
                    data[col] = np.repeat(hist[j, k], 24)
                    data[col+'_observed'] = np.repeat(masks[j, k], 24)
                    data[col+'_legal_count'] = np.repeat(legal_counts[j, k], 24)
                    data[col+'_max_legal_available_time_utc'] = pd.to_datetime(np.repeat(maximum[j, k], 24), utc=True)
                    ids = raw.source[r, safe[k], 0 if j == 0 else 1]
                    data[col+'_source_ids'] = [source_ids(ids[within[k]])] * 24
            chunk_frames.append(pd.DataFrame(data))
            audits.append(dict(issue_date_aest=day.strftime('%Y-%m-%d'), region=reg, split=s,
                        complete_targets=bool(np.isfinite(target).all()),
                        proven_target_clocks=bool((a != NAT).all()), legal_naive_hours=int(legal.sum()),
                        missing_numeric_slots=int((masks == 0).sum()),
                        history_source_window_complete=window_complete,
                        history_eligible=history_eligible,
                        train_history_eligible=eligible, day_label_available_time_utc=iso(a.max()) if (a != NAT).all() else None))
    flush()
    hist_file.close()
    pd.DataFrame(audits).to_csv(OUT / 'ISSUE_AUDIT.csv', index=False)
    pd.DataFrame(target_gaps, columns=['issue_date_aest', 'region', 'horizon', 'target_hour_start_utc',
                   'finite_intervals', 'proven_clock']).to_csv(OUT / 'TARGET_GAPS.csv', index=False)
    pd.DataFrame(naive_gaps, columns=['issue_date_aest', 'region', 'horizon', 'split', 'reason']).to_csv(OUT / 'WEEKLY_NAIVE_GAPS.csv', index=False)
    pd.DataFrame(exclusions, columns=['issue_date_aest', 'region', 'reason']).to_csv(OUT / 'EARLY_TRAIN_EXCLUSIONS.csv', index=False)
    passed = all(x['finite_target_rows'] == x['expected_rows'] and x['proven_target_clock_rows'] == x['expected_rows'] for x in stats.values())
    passed &= all(stats[s]['legal_weekly_naive_rows'] == stats[s]['expected_rows'] for s in ['validation', 'test'])
    passed &= not any(x['invalid_LASTCHANGED'] for x in raw.receipts)
    writer.add_key_value_metadata({'DAPANEL_GATE': 'PASS' if passed else 'FAIL',
                                  'DAPANEL_SUITABLE_FOR_FITTING': 'true' if passed else 'false'})
    writer.close()
    coverage = dict(gate='PASS' if passed else 'FAIL', expected_2025_target_rows=365*3*24,
                    splits=stats, raw_gap_counts=gaps, conflicting_keys=0,
                    archive_count=len(raw.receipts), early_train_exclusions=exclusions,
                    early_train_excluded_unique_days=len({x['issue_date_aest'] for x in exclusions}),
                    first_source_support_utc={REGIONS[r]: {'price':iso(first_support[r,0]),
                          'physical':iso(first_support[r,1])} for r in range(3)},
                    raw_interval_coverage={REGIONS[r]:{
                         family:dict(expected_intervals=int(N-1),
                              present_intervals=int((raw.source[r,1:,fam]>=0).sum()),
                              missing_intervals=int((raw.source[r,1:,fam]<0).sum()),
                              all_present=bool((raw.source[r,1:,fam]>=0).all()))
                         for fam,family in enumerate(['price','physical'])} for r in range(3)},
                    missing_numeric_slots=[dict(split=k[0], region=k[1], field=k[2], count=v,
                       denominator=stats[k[0]]['days']*72) for k,v in missing_slots.items()],
                    missing_numeric_slots_by_lag=[dict(split=k[0],region=k[1],field=k[2],lag=k[3],count=v)
                       for k,v in missing_lags.items()],
                    numeric_NaN_rule='12 finite issue-legal intervals required; masks preserve all nominal keys',
                    physical_first_publication_vintage='UNPROVEN_B3_INTERVAL_END_PLUS_5MIN_PROXY',
                    official_gap_fill='UNVERIFIED_NO_DOWNLOAD; exact paths/URLs in RAW_GAPS.csv',
                    no_model_fits=0, no_downloads=True, panel_rows=sum(x['expected_rows'] for x in stats.values()),
                    panel_sha256=sha(OUT/'panel.parquet'), peak_rss_bytes=rss())
    write('COVERAGE.json', coverage)
    return coverage


def report(coverage):
    rows = '\n'.join(f"| {s} | {v['days']} | {v['finite_target_rows']}/{v['expected_rows']} | {v['proven_target_clock_rows']}/{v['expected_rows']} | {v['legal_weekly_naive_rows']}/{v['expected_rows']} |" for s,v in coverage['splits'].items())
    (OUT/'REPORT.md').write_text(f'''# hourly_panels  Price ／ numerical panel

 Gate ：**{coverage['gate']}**。 Retains  2025  year  365  days 、NSW1/QLD1/TAS1、 per day  24  hours ； No fitting 、 no scoring 、 no downloads 。

 Record the identities of  SPEC.md、 all  102  archives in  SOURCE_MANIFEST.json  and  FREEZE.json， then read in chunks ； existing  news_features、B3  and the recovery-manifest hashes have been checked 。 Price source filters are  RUNNO=1、INTERVENTION=0， the physical-variable table  INTERVENTION=0； exact duplicates are collapsed ， conflicts stop the computation 。

 Fixed  AEST（UTC+10）： The target-hour mean uses intervals from  5  minutes after the start to the end of the hour, comprising  12  intervals 。72  historical slots use  issue−k  hours through  issue−(k−1) hours −5  minutes ； price availability is  max( interval end +5 minutes ，LASTCHANGED)， the five physical fields use interval end plus +5 minutes as an availability proxy 。 Each field requires  12  finite values 、issue  available at that issue ， otherwise  NaN／mask=0。 The weekly naive benchmark uses the same region and hour seven days earlier ， with its availability checked 。

|  Split  |  Days  |  Complete hourly prices  |  Verified label clocks  |  Available weekly naive hours  |
| --- | ---: | ---: | ---: | ---: |
{rows}

 Source ：COVERAGE.json  of  splits；2025  requires  {coverage['expected_2025_target_rows']}  target keys 。 Early training days excluded for incomplete history ：{coverage['early_train_excluded_unique_days']}（ by region ／ and date in  EARLY_TRAIN_EXCLUSIONS.csv）； Missing seven-day price histories at the start of training are reported separately ， the training window remains fixed 。

panel.parquet  contains  {coverage['panel_rows']}  nominal keys 、432  historical values and  432  entries  mask， also includes calendar fields 、 label clocks 、 source file  ID  and audit columns 。 Column sources are recorded in  Parquet metadata  and  COLUMN_PROVENANCE.json； Audit columns are excluded from predictors 。 Missing values are listed in  COVERAGE.json， raw intervals ／ field gaps and their source files are listed in  RAW_GAPS.csv， hourly gaps are listed in  TARGET_GAPS.csv／WEEKLY_NAIVE_GAPS.csv。 Availability from other official archives has not been verified ； Sources are fixed 。

 Physical variables use the specified availability proxy ； Monthly archives establish neither first publication times nor the absence of revisions 。 Independent batch checks are in  VERIFICATION.json。 Fitting stops if the gate fails ， the test year remains fixed ； The panel retains gaps for diagnosis 。 The construction script produces all reported numbers ， file hashes are in  COVERAGE.json  and  ARTIFACT_MANIFEST.json。
''', encoding='utf-8')


def main():
    started = time.monotonic()
    sources = preflight()
    write('SYNTHETIC_CHECKS.json', synthetic_checks())
    log('preflight_passed', sources=len(sources))
    raw = RawStore()

    for rec in sorted(sources, key=lambda x: (x['month'], x['family'])):
        try:
            raw.read_archive(rec)
        except Exception:
            write('FAILED_SOURCE.json', rec)
            raise
    coverage = build(raw, sources)
    report(coverage)
    log('build_complete', gate=coverage['gate'], seconds=round(time.monotonic()-started, 3))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        failure = dict(gate='FAIL', error=type(exc).__name__, message=str(exc),
                       peak_rss_bytes=rss(), model_fits=0, downloads=0,
                       coverage='NOT_FULLY_COMPUTABLE_BUILD_STOPPED',
                       failed_source=json.loads((OUT/'FAILED_SOURCE.json').read_text())
                         if (OUT/'FAILED_SOURCE.json').exists() else None)
        write('BUILD_FAILURE.json', failure)
        write('COVERAGE.json', failure)
        (OUT/'REPORT.md').write_text('# hourly_panels\n\n Gate ：**FAIL**。 Construction stopped because  '+str(exc)+'  Stopped ； See  BUILD_FAILURE.json。 No fitting 、 no downloads ， The test period and specified rules remain fixed 。\n')
        raise
