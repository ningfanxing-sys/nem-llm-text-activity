'Build weighted forecast rows, labels and numerical features from AEMO dispatch data.'
from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import zipfile

import duckdb
import numpy as np
import pandas as pd

LAMP = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(LAMP / 'scripts' / 'historical_support'))
sys.path.insert(0, str(LAMP / 'experiments' / 'notice_forecasting'))
import audit_historical_support as ahs
import build_hstt_feature_bank as bank
import nw_phys

RAW = Path('Documents/thesis/data_sources/electricity_price_prediction/raw')
KEYS = ['region', 'issue_time', 'target_time', 'horizon']
LAG = pd.Timedelta(minutes=5)
LAGS = {'price_lag_5m_available': 10, 'price_lag_10m_available': 15, 'price_lag_30m_available': 35,
        'price_lag_60m_available': 65}          # Lag in minutes from issue time to the price interval end.


def _table_lines(text, table):
    tag = f'DISPATCH,{table},'
    return [line for line in text.splitlines() if line[2:].startswith(tag) and line[:2] in ('I,', 'D,')]


def _parse(lines):
    frames, header, rows = [], None, []
    for line in lines + ['I,END']:
        if line.startswith('I,'):
            if header and rows:
                frames.append(pd.read_csv(io.StringIO('\n'.join([header] + rows)), low_memory=False))
            header, rows = line, []
        else:
            rows.append(line)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def read_mmsdm(path, table):
    with zipfile.ZipFile(path) as archive:
        text = archive.read(archive.namelist()[0]).decode()
    return _parse(_table_lines(text, table))


def read_dispatchis_day(path, tables=('PRICE', 'REGIONSUM')):
    lines = {t: [] for t in tables}
    with zipfile.ZipFile(path) as outer:
        for name in sorted(outer.namelist()):
            with zipfile.ZipFile(io.BytesIO(outer.read(name))) as inner:
                text = inner.read(inner.namelist()[0]).decode()
            for t in tables:
                lines[t] += _table_lines(text, t)
    return {t: _parse(v) for t, v in lines.items()}


def _utc(settlement):
    return (pd.to_datetime(settlement, format='%Y/%m/%d %H:%M:%S') - pd.Timedelta(hours=10)).dt.tz_localize('UTC')


def price_series(price):
    p = price.loc[price.INTERVENTION == 0]
    out = pd.DataFrame({'region': p.REGIONID.astype(str).to_numpy(), 'event_time': _utc(p.SETTLEMENTDATE).to_numpy(),
                        'price': p.RRP.astype('float64').to_numpy()})
    out['event_time'] = pd.to_datetime(out.event_time, utc=True)
    out = out.drop_duplicates().sort_values(['region', 'event_time'], kind='mergesort').reset_index(drop=True)
    if out.duplicated(['region', 'event_time']).any():
        raise ValueError('conflicting pricing-run prices for one interval')
    out['label_available_time'] = out.event_time + LAG
    return out


def phys_frame(regionsum):
    'Build physical system features from parsed dispatch summaries.'
    frame = regionsum.loc[regionsum.INTERVENTION == 0, ['SETTLEMENTDATE', 'REGIONID'] + nw_phys.FIELDS].copy()
    frame['end_utc'] = _utc(frame.SETTLEMENTDATE)
    frame = frame.drop(columns='SETTLEMENTDATE').drop_duplicates()
    if frame.duplicated(['REGIONID', 'end_utc']).any():
        raise ValueError('Duplicate pricing-run region interval')
    frame = frame.sort_values(['REGIONID', 'end_utc']).reset_index(drop=True)
    frame['phys_margin'] = frame.AVAILABLEGENERATION - frame.TOTALDEMAND
    out = []
    for region, part in frame.groupby('REGIONID'):
        part = part.set_index('end_utc')
        earlier = part[['TOTALDEMAND', 'phys_margin']].reindex(part.index - pd.Timedelta(minutes=30))
        part = part.assign(phys_demand_change_30m=part.TOTALDEMAND.to_numpy() - earlier.TOTALDEMAND.to_numpy(),
                           phys_margin_change_30m=part.phys_margin.to_numpy() - earlier.phys_margin.to_numpy())
        out.append(part.reset_index().assign(region=region))
    frame = pd.concat(out, ignore_index=True).rename(columns={f: 'phys_' + f.lower() for f in nw_phys.FIELDS})
    frame['issue_time'] = frame.end_utc + nw_phys.LAG
    return frame[['region', 'issue_time'] + nw_phys.COLUMNS]


def event_blocks(series):
    'Group regional severe events and extend each interval by 30 minutes.'
    rows = series.loc[series.price > 300].copy()
    rows['event_time'] = rows.event_time.dt.tz_convert('Australia/Brisbane')
    rows['available_horizons'] = 6
    rows['horizon_values'] = ','.join(str(h) for h in bank.HORIZONS)
    clusters = ahs.assign_system_events(ahs.regional_clusters(rows, 'GT300'))
    out = []
    for item in clusters.itertuples(index=False):
        for stamp in pd.date_range(pd.Timestamp(item.start) - pd.Timedelta(minutes=30),
                                   pd.Timestamp(item.end) + pd.Timedelta(minutes=30), freq='5min'):
            out.append((str(item.region), stamp.tz_convert('UTC'), str(item.system_event_id)))
    frame = pd.DataFrame(out, columns=['region', 'target_time', 'event_block_id'])
    frame = frame.sort_values(['region', 'target_time', 'event_block_id'], kind='mergesort').drop_duplicates(
        ['region', 'target_time'], keep='first')
    return frame, clusters


def candidate_keys(start_utc, end_utc):
    targets = pd.date_range(start_utc, end_utc, freq='5min', inclusive='left')
    parts = []
    for region in bank.REGIONS:
        for h in bank.HORIZONS:
            parts.append(pd.DataFrame({'region': region, 'issue_time': targets - pd.Timedelta(minutes=h),
                                       'target_time': targets, 'horizon': np.int16(h)}))
    keys = pd.concat(parts, ignore_index=True)
    keys['horizon'] = keys.horizon.astype('int16')
    return keys


def sample(keys, blocks):
    con = duckdb.connect()
    con.register('k', keys)
    picked = con.execute('SELECT region, issue_time, target_time, horizon FROM k '
                         'WHERE hash(region, issue_time, target_time, horizon) % 50 = 0').fetch_df()
    con.close()
    picked['ordinary_hash'] = True
    out = keys.merge(blocks, on=['region', 'target_time'], how='left')
    for c in ('issue_time', 'target_time'):
        picked[c] = pd.to_datetime(picked[c], utc=True)
    picked['horizon'] = picked.horizon.astype('int16')
    out = out.merge(picked, on=KEYS, how='left')
    out = out.loc[out.event_block_id.notna() | out.ordinary_hash.fillna(False).astype(bool)].drop(columns='ordinary_hash')
    return out.reset_index(drop=True)


def _price_at(series, region, times):
    s = series.loc[series.region == region].set_index('event_time').price
    return s.reindex(times).to_numpy('float64')


def panel(rows, series):
    'Attach truth, label availability and lagged prices to forecast rows.'
    out = rows.copy()
    for c in ('y_true', 'legal_anchor', *LAGS):
        out[c] = np.nan
    for region, idx in out.groupby('region').indices.items():
        part = out.iloc[idx]
        out.loc[out.index[idx], 'y_true'] = _price_at(series, region, part.target_time)
        out.loc[out.index[idx], 'legal_anchor'] = _price_at(series, region, part.issue_time - LAG)
        for c, minutes in LAGS.items():
            out.loc[out.index[idx], c] = _price_at(series, region, part.issue_time - pd.Timedelta(minutes=minutes))
    out['label_available_time'] = out.target_time + LAG
    return out


class History(bank.PriceHistory):
    def __init__(self, series):
        self.by_region = {}
        for region, part in series.groupby('region', sort=True):
            part = part.sort_values('event_time', kind='mergesort')
            self.by_region[str(region)] = (bank.timestamp_ns(part.label_available_time), bank.timestamp_ns(part.event_time),
                                           part.price.to_numpy(dtype=np.float32))


def build_rows(series, phys, start_utc, end_utc, block_series=None):
    'Build weighted feature rows for targets in the requested interval.'
    blocks, clusters = event_blocks(series if block_series is None else block_series)
    rows = sample(candidate_keys(start_utc, end_utc), blocks)
    rows = panel(rows, series)
    if rows[['y_true', 'legal_anchor', *LAGS]].isna().any().any():
        missing = rows[['y_true', 'legal_anchor', *LAGS]].isna().sum().to_dict()
        raise ValueError(f'missing prices for sampled rows: {missing}')
    rows = rows.sort_values(['issue_time', 'region', 'horizon'], kind='mergesort').reset_index(drop=True)
    feats = bank.fallback_training_features(rows, History(series))
    feats['event_block_id'] = feats.event_block_id.fillna('')
    feats['event_replay_flag'] = feats.event_block_id.ne('').astype(np.float32)
    feats = feats.merge(phys, on=['region', 'issue_time'], how='left', validate='many_to_one')
    feats['weight'] = np.where(feats.event_replay_flag > .5, 1., 50.).astype('float32')
    return feats.sort_values(KEYS, kind='mergesort').reset_index(drop=True), clusters


GRAPH = ['graph_neighbor_anchor_mean', 'graph_neighbor_ramp_mean', 'graph_source_mask']


def legal_graph(keys, series):
    'Average neighbour anchors and five-minute ramps available at issue time.'
    price = series.set_index(['region', 'event_time']).price
    out = np.zeros((len(keys), 3), dtype='float32')
    for region, idx in keys.groupby('region').indices.items():
        t = pd.DatetimeIndex(keys.issue_time.iloc[idx])
        anchors, ramps = [], []
        for n in bank.NEIGHBOURS[region]:
            a = price.reindex(pd.MultiIndex.from_arrays([np.repeat(n, len(t)), t - pd.Timedelta(minutes=5)])).to_numpy()
            b = price.reindex(pd.MultiIndex.from_arrays([np.repeat(n, len(t)), t - pd.Timedelta(minutes=10)])).to_numpy()
            anchors.append(a); ramps.append(a - b)
        A, R = np.vstack(anchors), np.vstack(ramps)
        with np.errstate(all='ignore'):
            out[idx, 0] = np.nan_to_num(np.nanmean(A, 0)); out[idx, 1] = np.nan_to_num(np.nanmean(R, 0))
        out[idx, 2] = np.isfinite(A).all(0) & np.isfinite(R).all(0)
    return out


def build_all_rows(series, phys, start_utc, end_utc):
    'Build every forecast key in the target interval with unit weight.'
    blocks, clusters = event_blocks(series)
    rows = candidate_keys(start_utc, end_utc).merge(blocks, on=['region', 'target_time'], how='left')
    rows = panel(rows, series)
    if rows[['y_true', 'legal_anchor', *LAGS]].isna().any().any():
        raise ValueError(f"missing prices: {rows[['y_true', 'legal_anchor', *LAGS]].isna().sum().to_dict()}")
    rows = rows.sort_values(['issue_time', 'region', 'horizon'], kind='mergesort').reset_index(drop=True)
    feats = bank.fallback_training_features(rows, History(series))
    feats[GRAPH] = legal_graph(feats[['region', 'issue_time']], series)
    feats['event_block_id'] = feats.event_block_id.fillna('')
    feats['event_replay_flag'] = feats.event_block_id.ne('').astype(np.float32)
    feats = feats.merge(phys, on=['region', 'issue_time'], how='left', validate='many_to_one')
    feats['weight'] = np.float32(1.0)
    return feats.sort_values(KEYS, kind='mergesort').reset_index(drop=True), clusters


def validate_dev_month(month='2023-06'):
    first = pd.Period(month, 'M')
    months = [str(first - 1), str(first), str(first + 1)]
    price = pd.concat([read_mmsdm(next((RAW / 'aemo_mmsdm_post5ms_dispatchprice_2021_2023' / f"MMSDM_{m.replace('-', '_')}").glob('*DISPATCHPRICE*')), 'PRICE')
                       for m in months], ignore_index=True)
    series = price_series(price)
    regionsum = pd.concat([read_mmsdm(next((RAW / 'aemo_mmsdm_post5ms_core_2021_2023' / f"MMSDM_{m.replace('-', '_')}").glob('*DISPATCHREGIONSUM*')), 'REGIONSUM')
                           for m in months[:2]], ignore_index=True)
    phys = phys_frame(regionsum)
    ref_phys, _ = nw_phys.build(months[:2])
    both = phys.merge(ref_phys, on=['region', 'issue_time'], suffixes=('', '_ref'))
    phys_diff = {c: float(np.nanmax(np.abs(both[c] - both[c + '_ref']))) for c in nw_phys.COLUMNS}
    start = pd.Timestamp(f'{month}-01', tz='Australia/Brisbane').tz_convert('UTC')
    end = (pd.Timestamp(f'{month}-01', tz='Australia/Brisbane') + pd.offsets.MonthBegin(1)).tz_convert('UTC')
    rebuilt, _ = build_rows(series, phys, start, end)
    ref = pd.read_parquet(bank.OUT / 'training' / f'{month}.parquet')
    for c in ('issue_time', 'target_time', 'label_available_time'):
        ref[c] = pd.to_datetime(ref[c], utc=True)
    ref['horizon'] = ref.horizon.astype('int16')
    ref = ref.merge(ref_phys, on=['region', 'issue_time'], how='left')
    keyset = lambda f: set(map(tuple, f[KEYS].astype(str).to_numpy()))
    a, b = keyset(rebuilt), keyset(ref)
    report = dict(month=month, rebuilt_rows=len(rebuilt), bank_rows=len(ref), only_rebuilt=len(a - b), only_bank=len(b - a),
                  phys_max_abs_diff=phys_diff)
    joined = rebuilt.merge(ref, on=KEYS, suffixes=('', '_bank'))
    report['event_flag_agree'] = float((joined.event_replay_flag == joined.event_replay_flag_bank).mean())
    report['label_time_agree'] = float((joined.label_available_time == joined.label_available_time_bank).mean())
    runner = sys.modules.get('run_nw') or __import__('run_nw')
    features = [c for c in runner.numeric_columns() if c in ref.columns and c != 'horizon'] + nw_phys.COLUMNS
    diffs = {}
    for c in ['y_true'] + features:
        x, y = joined[c].to_numpy('float64'), joined[c + '_bank'].to_numpy('float64')
        both_nan = np.isnan(x) & np.isnan(y)
        diffs[c] = float(np.nanmax(np.where(both_nan, 0, np.abs(x - y)))) if len(x) else 0.0
    report['max_abs_diff'] = {c: v for c, v in diffs.items() if v > 1e-3}
    report['columns_checked'] = len(diffs)
    return report


if __name__ == '__main__':
    print(json.dumps(validate_dev_month(sys.argv[1] if len(sys.argv) > 1 else '2023-06'), indent=1, default=str))
