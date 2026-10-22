'Compare notice features and write them on the frozen forecast keys.'
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
import assemble_source_relations as assembler

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
    by_column = {column: int(value) for column, value in zip(assembler.COLUMNS,
        (~z).sum(axis=0)) if value}
    return name, dict(rows=len(k), columns=list(assembler.COLUMNS), cells=int(a.size),
        key_sha256=kh, before_matrix_sha256=old_hash, after_matrix_sha256=new_hash,
        changed_cells=count, changed_keys=int((~z).any(axis=1).sum()),
        changed_cells_by_column=by_column, exact_equal=(count == 0 and old_hash == new_hash))


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


def compare(arm, period, keys, before_records, after_records):


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
    changed = ~same
    bad = np.argwhere(changed)[:20]
    examples = []
    for i, j in bad[:20]:
        row = keys.iloc[int(i)]
        examples.append(dict(key={c: str(row[c]) for c in KEY_COLS},
            column=assembler.COLUMNS[int(j)], reference_snapshot=str(a[i, j]), after=str(b[i, j])))
    feature_dir = OUT / 'features'
    feature_dir.mkdir(exist_ok=True)
    feature_path = feature_dir / f'{arm}_{period}.parquet'
    stored = keys[KEY_COLS].copy()
    for j, column in enumerate(assembler.COLUMNS):
        stored[column] = b[:, j]
    stored.to_parquet(feature_path, index=False)
    result = dict(subsets=results, changed_cells=int(changed.sum()),
        changed_keys=int(changed.any(axis=1).sum()),
        changed_cells_by_column={column: int(value) for column, value in zip(assembler.COLUMNS,
            changed.sum(axis=0)) if value},
        first_changed_cells=examples, all_cells_exact_equal=bool(same.all()),
        materialized_feature_path=str(feature_path), materialized_feature_sha256=sha(feature_path),
        peak_rss_bytes=rss())
    del a, b, same, changed, bad, stored
    gc.collect()
    return result


def main():
    spec_freeze = json.loads((OUT / 'SPEC_FREEZE.json').read_text())
    if spec_freeze['spec_sha256'] != sha(OUT / 'SPEC.md'):
        raise ValueError('FINAL3 spec changed after its freeze')
    parent = json.loads((notice_records / 'closing_windows/FREEZE.json').read_text())
    data = sorted_keys(notice_records.parent / 'B1b' / 'development_metadata.parquet',
        KEY_COLS + ['label_available_time', 'bank_month'])
    cdata = sorted_keys(PROJ / 'forecasting/windows/C/features.parquet', KEY_COLS)
    result = dict(state='RUNNING', spec_sha256=spec_freeze['spec_sha256'],
        parent_freeze_sha256=sha(notice_records / 'closing_windows/FREEZE.json'),
        frozen_feature_code_sha256=sha(assembler.FROZEN_PATH),
        assembler_code_sha256=sha(HERE / 'assemble_source_relations.py'),
        sources={'development_keys': {'path': str(notice_records.parent / 'B1b' / 'development_metadata.parquet'),
                   'sha256': sha(notice_records.parent / 'B1b' / 'development_metadata.parquet'), 'rows': len(data)},
                 'window_C_keys': {'path': str(PROJ / 'forecasting/windows/C/features.parquet'),
                   'sha256': sha(PROJ / 'forecasting/windows/C/features.parquet'), 'rows': len(cdata)}},
        arms={}, no_forecast_fit_or_score=True)
    for arm in 'RLP':
        path = notice_records / 'closing_windows/records' / f'{arm}.parquet'
        expected = parent['files'][str(path)]
        if sha(path) != expected:
            raise ValueError(f'parent freeze record hash mismatch: {arm}')
        old = pd.read_parquet(path)
        new_path = OUT / 'records' / f'{arm}.parquet'
        new = pd.read_parquet(new_path)
        arm_result = dict(records=len(old), source_record_sha256=expected,
            new_record_sha256=sha(new_path), periods={})
        print(f'arm={arm} records={len(old)}', flush=True)
        for name, keys in (('development', data), ('C', cdata)):
            arm_result['periods'][name] = compare(arm, name, keys, old, new)
            print(f'arm={arm} period={name} changed_cells={arm_result["periods"][name]["changed_cells"]}', flush=True)
        result['arms'][arm] = arm_result
        del old, new
        gc.collect()
    l = pd.read_parquet(OUT / 'records/L.parquet')
    p = pd.read_parquet(OUT / 'records/P.parquet')
    pd.testing.assert_frame_equal(p, assembler.shifted(l, 28))
    result['P_is_L_shifted_28_days'] = True
    del l, p
    result['peak_rss_bytes'] = rss()
    result['state'] = 'PASS_REBUILT_AND_COMPARED'
    path = OUT / 'FEATURE_COMPARISON.json'
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    print(json.dumps(dict(state=result['state'], peak_rss_bytes=result['peak_rss_bytes'],
        changed_cells={a: {p: v['changed_cells'] for p, v in arm['periods'].items()}
                       for a, arm in result['arms'].items()})), flush=True)


if __name__ == '__main__':
    main()
