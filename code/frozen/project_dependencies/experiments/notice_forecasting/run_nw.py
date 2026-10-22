'Fit notice forecast models by seed and rolling-origin fold.'
from __future__ import annotations
import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import nw_notices as nw

BANK = ROOT / 'artifacts/historical_support/feature_bank/training'
CONTRACT = ROOT / 'experiments/news_event_alignment_20260924/ABC_FIT_CONTRACT.json'
OUT = HERE / 'run'
KEYS = ['region', 'issue_time', 'target_time', 'horizon']
MONTHS = [str(p) for p in pd.period_range('2021-10', '2024-07', freq='M')]
FOLDS = [('F1', '2022-07', '2022-09'), ('F2', '2022-10', '2022-12'), ('F3', '2023-01', '2023-03'),
         ('F4', '2023-04', '2023-06'), ('F5', '2023-07', '2023-09'), ('F6', '2023-10', '2023-12'),
         ('F7', '2024-01', '2024-03'), ('F8', '2024-04', '2024-06'), ('F9', '2024-07', '2024-07')]
ARMS = ('N', 'R', 'L', 'P')
SEEDS = (20260919, 20260920, 20260921)
PLACEBO_DAYS = 28
N_JOBS = 6
EXCLUDE = {'region', 'issue_time', 'target_time', 'y_true', 'label_available_time', 'event_block_id', 'event_replay_flag',
           'A2_14D', 'LEGAL_PERSISTENCE_STABILISER', 'LS_DASE', 'W90_FILTERED', 'W28_FILTERED', 'W28_RAW', 'W90_RAW',
           'S1_RESTRICTED_STRUCTURAL_LIGHTGBM', 'DISTRIBUTIONAL_H0_Q50', 'component_disagreement', 'ls_dase_source_mask'}
EXCLUDE_PREFIX = ('label_gt', 'target_', 'notice_')


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for block in iter(lambda: fh.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, value, immutable=False):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, indent=2, sort_keys=True, default=str, allow_nan=False) + '\n'
    if immutable and path.exists():
        if path.read_text() != data:
            raise RuntimeError('Refuse immutable overwrite: ' + str(path))
        return
    tmp = path.with_name(path.name + f'.tmp{os.getpid()}'); tmp.write_text(data); os.replace(tmp, path)


def log(stage, **fields):
    value = dict(stage=stage, utc=pd.Timestamp.now(tz='UTC').isoformat(), **fields)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / 'progress.jsonl').open('a') as fh:
        fh.write(json.dumps(value, default=str) + '\n')
    print(json.dumps(value, default=str), flush=True)


def guard():
    out = subprocess.run(['memory_pressure'], capture_output=True, text=True, timeout=10).stdout
    m = re.search(r'System-wide memory free percentage:\s*(\d+)%', out)
    if m and int(m.group(1)) < 8:
        raise RuntimeError(f'PAUSED_LOW_MEMORY {m.group(1)}%')
    if shutil.disk_usage(HERE).free < 2 * 1024**3:
        raise RuntimeError('PAUSED_LOW_DISK')


def numeric_columns():

    names = pq.read_schema(BANK / f'{MONTHS[0]}.parquet').names
    for month in MONTHS[1:]:
        if not set(names) <= set(pq.read_schema(BANK / f'{month}.parquet').names):
            raise ValueError('Common bank columns missing in ' + month)
    return [c for c in names if c not in EXCLUDE and not c.startswith(EXCLUDE_PREFIX)]


def load_bank(features):
    frames, hashes = [], {}
    for month in MONTHS:
        path = BANK / f'{month}.parquet'; hashes[str(path)] = sha(path)
        frame = pd.read_parquet(path, columns=KEYS + ['y_true', 'label_available_time', 'event_replay_flag'] +
                                [c for c in features if c != 'horizon'])
        frame['bank_month'] = month; frames.append(frame)
    data = pd.concat(frames, ignore_index=True); del frames
    for c in ('issue_time', 'target_time', 'label_available_time'):
        data[c] = pd.to_datetime(data[c], utc=True)
    if data.duplicated(KEYS).any():
        raise ValueError('Duplicate forecast keys in bank')
    local_month = data.target_time.dt.tz_convert('Australia/Brisbane').dt.strftime('%Y-%m')
    if not local_month.eq(data.bank_month).all():
        raise ValueError('Bank month partition is not the Brisbane target month')
    if not np.isfinite(data.legal_anchor.to_numpy(float)).all():
        raise ValueError('Non-finite legal anchor')
    replay = data.event_replay_flag.to_numpy(float)
    if not np.isin(replay, (0., 1.)).all():
        raise ValueError('Unexpected replay flag values')
    data['weight'] = np.where(replay > .5, 1., 50.).astype('float32')
    data = data.sort_values(['issue_time', 'region', 'horizon'], kind='mergesort').reset_index(drop=True)
    return data, hashes


def price_cap(target):
    local = target.dt.tz_convert('Australia/Brisbane')
    tz = 'Australia/Brisbane'
    return np.select([local < pd.Timestamp('2022-07-01', tz=tz), local < pd.Timestamp('2023-07-01', tz=tz),
                      local < pd.Timestamp('2024-07-01', tz=tz)], [15000., 15500., 16600.], 17500.)


def params(seed):
    contract = json.loads(CONTRACT.read_text()); p = dict(contract['capacity'])
    p.pop('seed'); p.update(random_state=int(seed), objective=contract['objective'], verbosity=-1, n_jobs=N_JOBS)
    return p


def weighted_q90(values, weights):
    order = np.argsort(values, kind='stable'); cum = np.cumsum(weights[order], dtype='float64')
    return float(values[order][int(np.searchsorted(cum, .9 * cum[-1], side='left'))])


def prune(matrix, names):

    finite = np.isfinite(matrix); present = finite.sum(axis=0)
    lo = np.where(finite, matrix, np.inf).min(axis=0); hi = np.where(finite, matrix, -np.inf).max(axis=0)
    keep = [(present[i] > 0) and not (lo[i] == hi[i] and present[i] == len(matrix)) for i in range(len(names))]
    return [n for n, k in zip(names, keep) if k], {n: ('ALL_MISSING' if present[i] == 0 else 'CONSTANT')
                                                   for i, (n, k) in enumerate(zip(names, keep)) if not k}


def notice_blocks(data):
    pop = nw.load_population()
    rule = nw.rule_records(pop); llm, joined = nw.llm_records(pop); placebo = nw.shifted(llm, PLACEBO_DAYS)
    keys = data[['region', 'issue_time', 'target_time']]
    blocks = {}
    for arm, rec in (('R', rule), ('L', llm), ('P', placebo)):
        started = time.monotonic(); block = nw.features(keys, rec)
        block.columns = [f'{arm}_{c}' for c in nw.COLUMNS]; blocks[arm] = block
        log('notice_features', arm=arm, records=len(rec), seconds=round(time.monotonic() - started, 1),
            rows_with_local_window=int((block[f'{arm}_nw_any_local'] > 0).sum()))
    info = dict(population=len(pop), llm_joined_notices=joined, rule_records=len(rule), llm_records=len(llm),
                registry_sha256=sha(nw.REGISTRY), labels_sha256=sha(nw.LABELS), code_sha256=sha(HERE / 'nw_notices.py'))
    return blocks, info


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    lock = OUT / '.writer.lock'; fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY); os.close(fd)
    started = time.monotonic()
    try:
        import lightgbm as lgb
        guard(); features = numeric_columns()
        data, bank_hashes = load_bank(features)
        log('bank', rows=len(data), numeric_features=len(features))
        blocks, info = notice_blocks(data)
        design = dict(state='NW_DESIGN_BOUND_BEFORE_SCORES', protocol_sha256=sha(HERE / 'PROTOCOL_NW.md'),
                      runner_sha256=sha(Path(__file__)), notice_code_sha256=info['code_sha256'],
                      tests_sha256=sha(HERE / 'test_nw_notices.py'), bank_sha256=bank_hashes, numeric_features=features,
                      notice_columns=nw.COLUMNS, arms=list(ARMS), seeds=list(SEEDS), folds=FOLDS, params=params(SEEDS[0]),
                      notice_sources=info, placebo_days=PLACEBO_DAYS, rows=len(data),
                      weights='event replay 1; hash-sampled 2% ordinary 50', target='y - legal_anchor',
                      projection='clip(legal_anchor + f, -1000, date-specific market price cap)')
        write_json(OUT / 'design_binding.json', design, immutable=True)
        anchor = data.legal_anchor.to_numpy('float64'); target = data.y_true.to_numpy('float64') - anchor
        caps = price_cap(data.target_time); weights = data.weight.to_numpy('float32')
        local_month = data.bank_month.to_numpy()
        numeric = data[features].to_numpy('float32')
        data = data[KEYS + ['y_true', 'label_available_time']].copy(); gc.collect()
        files = []
        for fold, first, last in FOLDS:
            guard()
            fold_start = pd.Timestamp(first + '-01', tz='Australia/Brisbane').tz_convert('UTC')
            train = ((data.target_time < fold_start) & (data.label_available_time < fold_start)).to_numpy()
            months = [str(p) for p in pd.period_range(first, last, freq='M')]
            test = np.isin(local_month, months)
            if train[test].any():
                raise ValueError('Train/test overlap')
            q90 = weighted_q90(data.y_true.to_numpy('float64')[train], weights[train].astype('float64'))
            kept_numeric, dropped_numeric = prune(numeric[train], features)
            idx_numeric = [features.index(n) for n in kept_numeric]
            out = data.loc[test, KEYS].reset_index(drop=True)
            receipt = dict(fold=fold, months=months, fold_start_utc=fold_start.isoformat(), train_rows=int(train.sum()),
                           train_weight=float(weights[train].sum()), test_rows=int(test.sum()), q90=q90,
                           numeric_kept=len(kept_numeric), numeric_dropped=dropped_numeric, arms={})
            for arm in ARMS:
                if arm == 'N':
                    block_names, block = [], None
                else:
                    block = blocks[arm].to_numpy('float32'); block_names = list(blocks[arm].columns)
                kept_block, dropped_block = prune(block[train], block_names) if block is not None else ([], {})
                names = kept_numeric + kept_block
                x_train = numeric[np.ix_(train, idx_numeric)]
                x_test = numeric[np.ix_(test, idx_numeric)]
                if kept_block:
                    bi = [block_names.index(n) for n in kept_block]
                    x_train = np.hstack([x_train, block[np.ix_(train, bi)]]); x_test = np.hstack([x_test, block[np.ix_(test, bi)]])
                support = {} if block is None else dict(
                    train_rows_local_window=int((blocks[arm][f'{arm}_nw_any_local'].to_numpy()[train] > 0).sum()),
                    test_rows_local_window=int((blocks[arm][f'{arm}_nw_any_local'].to_numpy()[test] > 0).sum()))
                total = np.zeros(int(test.sum()), dtype='float64'); fits = []
                for seed in SEEDS:
                    guard(); t0 = time.monotonic()
                    model = lgb.LGBMRegressor(**params(seed))
                    model.fit(x_train, target[train], sample_weight=weights[train], feature_name=names)
                    path = OUT / 'models' / f'{fold}_{arm}_s{seed}.txt'; path.parent.mkdir(parents=True, exist_ok=True)
                    model.booster_.save_model(str(path))
                    raw = model.booster_.predict(x_test, num_threads=N_JOBS)
                    pred = np.clip(anchor[test] + raw, -1000., caps[test]).astype('float32')
                    out[f'{arm}_s{seed}'] = pred; total += pred.astype('float64')
                    fits.append(dict(seed=seed, model_sha256=sha(path), seconds=round(time.monotonic() - t0, 1)))
                    log('fit', fold=fold, arm=arm, seed=seed, features=len(names), train_rows=int(train.sum()),
                        seconds=fits[-1]['seconds'])
                    del model; gc.collect()
                out[arm] = (total / len(SEEDS)).astype('float32')
                receipt['arms'][arm] = dict(features=names, dropped_block=dropped_block, support=support, fits=fits)
                del x_train, x_test; gc.collect()
            if 'y_true' in out:
                raise ValueError('Truth leaked to candidate')
            path = OUT / 'predictions' / f'{fold}.parquet'; path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                raise RuntimeError('Refuse candidate overwrite')
            pq.write_table(pa.Table.from_pandas(out, preserve_index=False), path, compression='zstd')
            receipt.update(path=str(path), sha256=sha(path), rows=len(out), truth_in_candidate=False)
            write_json(OUT / 'receipts' / f'{fold}.json', receipt, immutable=True)
            files.append(dict(fold=fold, path=str(path), sha256=receipt['sha256'], rows=len(out), q90=q90))
            log('fold_sealed', fold=fold, rows=len(out))
        seal = dict(state='NW_CANDIDATE_BANK_SEALED', files=files, design_binding_sha256=sha(OUT / 'design_binding.json'),
                    target_scoring_before_seal=False, wall_seconds=time.monotonic() - started)
        write_json(OUT / 'candidate_bank_seal.json', seal, immutable=True)
        log('seal', state=seal['state'])
    except Exception as exc:
        write_json(OUT / f'failure_{pd.Timestamp.now(tz="UTC"):%Y%m%dT%H%M%S}.json', dict(error=repr(exc)))
        log('failure', error=repr(exc)); raise
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()
