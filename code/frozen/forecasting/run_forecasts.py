'Fit the notice forecast arms with features available at each issue time.'
from __future__ import annotations
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
PREP = HERE.parent
EXP = PREP.parent
sys.path.insert(0, str(EXP / 'notice_forecasting'))
sys.path.insert(0, str(HERE))
import run_nw_phys
import run_nw as rn
import oos_bank as ob

FREEZE = PREP / 'prospective' / 'SPECIFICATION_1_FREEZE.json'
OUT = HERE / 'run_forecasts'
SEEDS = (20260919, 20260920, 20260921)
ARMS = ('N', 'R', 'L', 'P')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def main():
    freeze = json.loads(FREEZE.read_text()) if FREEZE.exists() else {}
    if freeze.get('state') != 'SPECIFICATION_1_FROZEN':
        raise RuntimeError('specification 1 not frozen')
    if (OUT / 'candidate_bank_seal.json').exists():
        raise RuntimeError('set-G candidates already sealed')
    import lightgbm as lgb
    OUT.mkdir(parents=True, exist_ok=True); rn.OUT = OUT
    started = time.monotonic()
    v2 = load(PREP / 'notice_assembly' / 'notice_event_records.py', 'nw_v2_frozen'); rn.nw = v2
    rn.guard(); features = rn.numeric_columns()
    data, bank_hashes = rn.load_bank(features)
    blocks, info = rn.notice_blocks(data)
    series = pd.read_parquet(ob.LAMP / 'artifacts' / 'historical_support' / 'feature_bank' / 'canonical_price_series.parquet')
    series['event_time'] = pd.to_datetime(series.event_time, utc=True)
    series = series.loc[series.event_time < pd.Timestamp('2024-01-02', tz='UTC')]
    numeric = data[features].to_numpy('float32')
    gi = [features.index(c) for c in ob.GRAPH]
    numeric[:, gi] = ob.legal_graph(data[['region', 'issue_time']], series); del series; gc.collect()
    design = dict(state='SET_G_DESIGN_BOUND_BEFORE_SCORES', specification_freeze_sha256=sha(FREEZE), runner_sha256=sha(__file__),
                  oos_bank_sha256=sha(HERE / 'oos_bank.py'), notice_assembly_sha256=sha(PREP / 'notice_assembly' / 'notice_event_records.py'),
                  arms=list(ARMS), seeds=list(SEEDS), folds=rn.FOLDS, params=rn.params(SEEDS[0]), bank_sha256=bank_hashes,
                  notice_sources=info, numeric_features=features, fits=len(ARMS) * len(SEEDS) * len(rn.FOLDS))
    rn.write_json(OUT / 'design_binding.json', design, immutable=True)
    anchor = data.legal_anchor.to_numpy('float64'); target = data.y_true.to_numpy('float64') - anchor
    caps = rn.price_cap(data.target_time); weights = data.weight.to_numpy('float32'); local_month = data.bank_month.to_numpy()
    data = data[rn.KEYS + ['y_true', 'label_available_time']].copy(); gc.collect()
    files = []
    for fold, first, last in rn.FOLDS:
        rn.guard()
        fold_start = pd.Timestamp(first + '-01', tz='Australia/Brisbane').tz_convert('UTC')
        train = ((data.target_time < fold_start) & (data.label_available_time < fold_start)).to_numpy()
        test = np.isin(local_month, [str(p) for p in pd.period_range(first, last, freq='M')])
        if train[test].any():
            raise ValueError('Train/test overlap')
        q90 = rn.weighted_q90(data.y_true.to_numpy('float64')[train], weights[train].astype('float64'))
        kept_numeric, _ = rn.prune(numeric[train], features); idx = [features.index(n) for n in kept_numeric]
        out = data.loc[test, rn.KEYS].reset_index(drop=True)
        receipt = dict(fold=fold, train_rows=int(train.sum()), test_rows=int(test.sum()), q90=q90, arms={})
        for arm in ARMS:
            x_train, x_test, names = numeric[np.ix_(train, idx)], numeric[np.ix_(test, idx)], list(kept_numeric)
            if arm != 'N':
                block = blocks[arm]; bm = block.to_numpy('float32'); bnames = list(block.columns)
                kept, _ = rn.prune(bm[train], bnames)
                if kept:
                    bi = [bnames.index(n) for n in kept]
                    x_train = np.hstack([x_train, bm[np.ix_(train, bi)]]); x_test = np.hstack([x_test, bm[np.ix_(test, bi)]])
                    names += kept
            total, fits = np.zeros(int(test.sum())), []
            for seed in SEEDS:
                t0 = time.monotonic()
                model = lgb.LGBMRegressor(**rn.params(seed)).fit(x_train, target[train], sample_weight=weights[train], feature_name=names)
                path = OUT / 'models' / f'{fold}_{arm}_s{seed}.txt'; path.parent.mkdir(parents=True, exist_ok=True)
                model.booster_.save_model(str(path))
                pred = np.clip(anchor[test] + model.booster_.predict(x_test, num_threads=rn.N_JOBS), -1000., caps[test]).astype('float32')
                out[f'{arm}_s{seed}'] = pred; total += pred
                fits.append(dict(seed=seed, model_sha256=sha(path), seconds=round(time.monotonic() - t0, 1)))
                rn.log('set_g_fit', fold=fold, arm=arm, seed=seed, features=len(names), seconds=fits[-1]['seconds'])
                del model; gc.collect()
            out[arm] = (total / len(SEEDS)).astype('float32')
            receipt['arms'][arm] = dict(features=names, fits=fits)
        path = OUT / 'predictions' / f'{fold}.parquet'; path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pandas(out, preserve_index=False), path, compression='zstd')
        receipt.update(path=str(path), sha256=sha(path), rows=len(out))
        rn.write_json(OUT / 'receipts' / f'{fold}.json', receipt, immutable=True)
        files.append(dict(fold=fold, path=str(path), sha256=receipt['sha256'], rows=len(out), q90=q90))
    seal = dict(state='SET_G_CANDIDATE_BANK_SEALED', files=files, design_binding_sha256=sha(OUT / 'design_binding.json'),
                target_scoring_before_seal=False, wall_seconds=time.monotonic() - started)
    rn.write_json(OUT / 'candidate_bank_seal.json', seal, immutable=True)
    print(json.dumps(dict(state=seal['state'], folds=len(files), minutes=round(seal['wall_seconds'] / 60, 1))))


if __name__ == '__main__':
    main()
