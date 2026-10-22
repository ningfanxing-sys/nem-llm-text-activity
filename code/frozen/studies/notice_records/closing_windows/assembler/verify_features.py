'Compare notice inputs on the matched development and evaluation keys.'
from __future__ import annotations

import gc
import hashlib
import json
import os
from pathlib import Path
import resource
import sys

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
sys.dont_write_bytecode = True

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
notice_records = OUT.parent
PROJ = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(HERE))
import normalize_closing_windows as assembler

FOLDS = [
    ('F1', '2022-07', '2022-09'),
    ('F2', '2022-10', '2022-12'),
    ('F3', '2023-01', '2023-03'),
    ('F4', '2023-04', '2023-06'),
    ('F5', '2023-07', '2023-09'),
    ('F6', '2023-10', '2023-12'),
]
KEY_COLS = ['region', 'issue_time', 'target_time', 'horizon']
MAX_RSS = 2 * 1024**3


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda: f.read(1 << 20), b''):
            h.update(part)
    return h.hexdigest()


def rss():
    size = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if size >= MAX_RSS:
        raise MemoryError(f'feature gate peak RSS {size} exceeds {MAX_RSS}')
    return size


def sorted_keys(path, columns):
    data = pd.read_parquet(path, columns=columns)
    for c in ('issue_time', 'target_time', 'label_available_time'):
        if c in data:
            data[c] = pd.to_datetime(data[c], utc=True)
    data = data.sort_values(KEY_COLS, kind='mergesort').reset_index(drop=True)
    if data.duplicated(KEY_COLS).any():
        raise ValueError(f'duplicate forecasting key in {path}')
    rss()
    return data


def key_hash(keys):
    hashed = pd.util.hash_pandas_object(keys[KEY_COLS], index=False).to_numpy(dtype='<u8')
    return hashlib.sha256(hashed.tobytes(order='C')).hexdigest()


def matrix_hash(values, key_digest):
    values = np.asarray(values, dtype='<f4', order='C')
    words = values.view('<u4').copy()
    words[np.isnan(values)] = 0x7fc00000
    h = hashlib.sha256()
    h.update(json.dumps(list(assembler.COLUMNS), separators=(',', ':')).encode())
    h.update(b'\0')
    h.update(bytes.fromhex(key_digest))
    h.update(np.asarray(values.shape, dtype='<u8').tobytes())
    h.update(words.tobytes(order='C'))
    return h.hexdigest()


def check_subset(name, keys, reference_snapshot, after, mask, changed):
    if isinstance(mask, slice):
        k, a, b, z = keys, reference_snapshot, after, changed
    else:
        k, a, b, z = keys.loc[mask], reference_snapshot[mask], after[mask], changed[mask]
    kh = key_hash(k)
    old_hash, new_hash = matrix_hash(a, kh), matrix_hash(b, kh)
    count = int((~z).sum())
    return name, dict(rows=len(k), columns=list(assembler.COLUMNS), cells=int(a.size),
        key_sha256=kh, before_matrix_sha256=old_hash, after_matrix_sha256=new_hash,
        changed_cells=count, exact_equal=(count == 0 and old_hash == new_hash))


def select_masks(data, period):
    if period == 'C':
        return [('all', slice(None))]
    out = [('all', slice(None))]
    for fold, first, last in FOLDS:
        cutoff = pd.Timestamp(first + '-01', tz='Australia/Brisbane').tz_convert('UTC')
        train = ((data.target_time < cutoff) & (data.label_available_time < cutoff)).to_numpy()
        months = [str(p) for p in pd.period_range(first, last, freq='M')]
        test = data.bank_month.isin(months).to_numpy()
        if not train.any() or not test.any() or (train & test).any():
            raise ValueError(f'bad {fold} key split')
        out += [(fold + '_train', train), (fold + '_test', test)]
    return out


def compare(period, keys, before_records, after_records):


    print(f'{period}: computing before features', flush=True)
    a = assembler.features(keys[KEY_COLS], before_records).to_numpy(dtype=np.float32, copy=True)
    rss()
    print(f'{period}: computing after features', flush=True)
    b = assembler.features(keys[KEY_COLS], after_records).to_numpy(dtype=np.float32, copy=True)
    rss()
    if a.shape != (len(keys), len(assembler.COLUMNS)) or b.shape != a.shape:
        raise ValueError('feature matrix shape mismatch')
    same = (a == b) | (np.isnan(a) & np.isnan(b))
    results = {}
    for name, mask in select_masks(keys, period):
        label, result = check_subset(name, keys, a, b, mask, same)
        results[label] = result
    bad = np.argwhere(~same)
    examples = []
    for i, j in bad[:20]:
        row = keys.iloc[int(i)]
        examples.append(dict(key={c: str(row[c]) for c in KEY_COLS},
            column=assembler.COLUMNS[int(j)], reference_snapshot=str(a[i, j]), after=str(b[i, j])))
    result = dict(subsets=results, changed_cells=int(len(bad)), first_changed_cells=examples,
        all_cells_exact_equal=bool(same.all()), peak_rss_bytes=rss())
    del a, b, same, bad
    gc.collect()
    return result


def main():
    spec_freeze = json.loads((OUT / 'SPEC_FREEZE.json').read_text())
    if spec_freeze['spec_sha256'] != sha(OUT / 'SPEC.md'):
        raise ValueError('FINAL2 spec changed after its freeze')
    parent = json.loads((notice_records / 'FREEZE.json').read_text())
    data = sorted_keys(notice_records.parent / 'B1b' / 'development_metadata.parquet',
        KEY_COLS + ['label_available_time', 'bank_month'])
    cdata = sorted_keys(PROJ / 'forecasting/windows/C/features.parquet', KEY_COLS)
    result = dict(state='RUNNING', spec_sha256=spec_freeze['spec_sha256'],
        parent_freeze_sha256=sha(notice_records / 'FREEZE.json'),
        frozen_feature_code_sha256=sha(assembler.FROZEN_PATH),
        assembler_code_sha256=sha(HERE / 'normalize_closing_windows.py'),
        sources={'development_keys': {'path': str(notice_records.parent / 'B1b' / 'development_metadata.parquet'),
                   'sha256': sha(notice_records.parent / 'B1b' / 'development_metadata.parquet'), 'rows': len(data)},
                 'window_C_keys': {'path': str(PROJ / 'forecasting/windows/C/features.parquet'),
                   'sha256': sha(PROJ / 'forecasting/windows/C/features.parquet'), 'rows': len(cdata)}},
        arms={}, no_forecast_fit_or_score=True)
    normalized = {}
    for arm in 'RLP':
        path = notice_records / 'records' / f'{arm}.parquet'
        expected = parent['record_counts'][arm]['sha256']
        if sha(path) != expected:
            raise ValueError(f'parent freeze record hash mismatch: {arm}')
        old = pd.read_parquet(path)
        mask = assembler.closure_start_mask(old)
        new = assembler.normalize_closure_start(old)
        pd.testing.assert_frame_equal(old.drop(columns=['start_utc']), new.drop(columns=['start_utc']))
        pd.testing.assert_series_equal(old.loc[~mask, 'start_utc'], new.loc[~mask, 'start_utc'])
        pd.testing.assert_series_equal(new.loc[mask, 'start_utc'].reset_index(drop=True),
            old.loc[mask, 'action_effective_utc'].reset_index(drop=True), check_names=False)
        normalized[arm] = new
        arm_result = dict(changed_records=int(mask.sum()), records=len(old),
            source_record_sha256=expected, periods={})
        print(f'arm={arm} changed={int(mask.sum())} records={len(old)}', flush=True)
        for name, keys in (('development', data), ('C', cdata)):
            arm_result['periods'][name] = compare(name, keys, old, new)
            print(f'arm={arm} period={name} changed_cells={arm_result["periods"][name]["changed_cells"]}', flush=True)
        result['arms'][arm] = arm_result
        del old, new
        gc.collect()


    pd.testing.assert_frame_equal(normalized['P'], assembler.shifted(normalized['L'], 28))
    result['P_is_normalized_L_shifted_28_days'] = True
    result['peak_rss_bytes'] = rss()
    passed = all(p['all_cells_exact_equal'] and all(s['exact_equal'] for s in p['subsets'].values())
        for a in result['arms'].values() for p in a['periods'].values())
    result['state'] = 'PASS' if passed else 'FAIL_FEATURE_INVARIANCE'
    if passed:
        records_dir = OUT / 'records'
        records_dir.mkdir(exist_ok=True)
        for arm, frame in normalized.items():
            target = records_dir / f'{arm}.parquet'
            frame.to_parquet(target, index=False)
            result['arms'][arm]['normalized_record_sha256'] = sha(target)
    path = OUT / 'FEATURE_INVARIANCE.json'
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    print(json.dumps(dict(state=result['state'], peak_rss_bytes=result['peak_rss_bytes'],
        changed_records={a: v['changed_records'] for a, v in result['arms'].items()})), flush=True)
    if not passed:
        raise SystemExit('Feature invariance failed; normalized records were not published')


if __name__ == '__main__':
    main()
