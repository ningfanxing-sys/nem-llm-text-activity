'Fit the notice models on development data and predict the evaluation window.'
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
import oos_bank as ob
import run_nw_phys
import run_nw as rn

FREEZE = PREP / 'prospective' / 'SPECIFICATION_1_FREEZE.json'
SEEDS = (20260919, 20260920, 20260921)
ARMS = ('N', 'R', 'L', 'P')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def window_blocks(v2, keys, name):
    pop = v2.load_population()
    rule = v2.rule_records(pop); llm = v2.llm_records(pop)[0]
    placebo = v2.shifted(llm, rn.PLACEBO_DAYS)
    out = {}
    for arm, rec in (('R', rule), ('L', llm), ('P', placebo)):
        block = v2.features(keys, rec); block.columns = [f'{arm}_{c}' for c in v2.COLUMNS]; out[arm] = block
    return out


def main(name):
    freeze = json.loads(FREEZE.read_text()) if FREEZE.exists() else {}
    if freeze.get('state') != 'SPECIFICATION_1_FROZEN' or name not in freeze.get('windows', []):
        raise RuntimeError(f'window {name} not admitted by a frozen specification')
    wdir = HERE / 'windows' / name
    build = json.loads((wdir / 'build_receipt.json').read_text())
    if sha(wdir / 'features.parquet') != build['features_sha256']:
        raise RuntimeError('window features changed since the build')
    out = wdir / 'run'
    if (out / 'candidate_seal.json').exists():
        raise RuntimeError('window candidates already sealed')
    out.mkdir(parents=True, exist_ok=True); rn.OUT = out
    import lightgbm as lgb
    started = time.monotonic()
    v2 = load(PREP / 'notice_assembly' / 'notice_event_records.py', 'nw_v2_frozen'); rn.nw = v2
    rn.guard(); features = rn.numeric_columns()
    data, bank_hashes = rn.load_bank(features)
    blocks, info = rn.notice_blocks(data)
    win = pd.read_parquet(wdir / 'features.parquet')
    for c in ('issue_time', 'target_time', 'label_available_time'):
        win[c] = pd.to_datetime(win[c], utc=True)
    if set(win.columns) & {'y_true'}:
        raise RuntimeError('truth in window features')
    wkeys = win[['region', 'issue_time', 'target_time']].reset_index(drop=True)
    wblocks = window_blocks(v2, wkeys, name)
    first_target = win.target_time.min()
    anchor = data.legal_anchor.to_numpy('float64'); target = data.y_true.to_numpy('float64') - anchor
    weights = data.weight.to_numpy('float32'); numeric = data[features].to_numpy('float32')
    series = pd.read_parquet(ob.LAMP / 'artifacts' / 'historical_support' / 'feature_bank' / 'canonical_price_series.parquet')
    series['event_time'] = pd.to_datetime(series.event_time, utc=True)
    series = series.loc[series.event_time < first_target]
    numeric[:, [features.index(c) for c in ob.GRAPH]] = ob.legal_graph(data[['region', 'issue_time']], series)
    del series
    train = ((data.target_time < first_target) & (data.label_available_time < first_target)).to_numpy()
    if not train.all():
        raise RuntimeError('development rows overlap the window')
    q90 = rn.weighted_q90(data.y_true.to_numpy('float64'), weights.astype('float64'))
    kept_numeric, dropped = rn.prune(numeric, features); idx = [features.index(n) for n in kept_numeric]
    missing = [c for c in kept_numeric if c not in win.columns]
    if missing:
        raise RuntimeError(f'window lacks kept features: {missing}')
    design = dict(state='WINDOW_DESIGN_BOUND_BEFORE_SCORES', window=name, specification_freeze_sha256=sha(FREEZE),
                  runner_sha256=sha(__file__), window_features_sha256=build['features_sha256'],
                  notice_assembly_sha256=sha(PREP / 'notice_assembly' / 'notice_event_records.py'), bank_sha256=bank_hashes,
                  notice_sources=info, kept_numeric=kept_numeric, arms=list(ARMS), seeds=list(SEEDS), params=rn.params(SEEDS[0]),
                  train_rows=int(train.sum()), window_rows=len(win), prior_q90=q90, placebo_days=rn.PLACEBO_DAYS)
    rn.write_json(out / 'design_binding.json', design, immutable=True)
    x_num, w_num = numeric[:, idx], win[kept_numeric].to_numpy('float32')
    w_anchor = win.legal_anchor.to_numpy('float64'); caps = rn.price_cap(win.target_time)
    del numeric; gc.collect()
    pred = win[rn.KEYS].copy(); receipt = dict(arms={})
    pred['notice_active'] = ((wblocks['R']['R_nw_any_local'] > 0) | (wblocks['L']['L_nw_any_local'] > 0)).to_numpy()   # Apply one row mask to every forecast arm.
    pred['Z'] = w_anchor.astype('float32')          # Use the available anchor price as the persistence forecast.
    for arm in ARMS:
        x_train, x_win, names = x_num, w_num, list(kept_numeric)
        if arm != 'N':
            block = blocks[arm]; bnames = list(block.columns); bm = block.to_numpy('float32')
            kept, _ = rn.prune(bm, bnames)
            if kept:
                bi = [bnames.index(n) for n in kept]
                x_train = np.hstack([x_num, bm[:, bi]])
                x_win = np.hstack([w_num, wblocks[arm][kept].to_numpy('float32')])
                names += kept
        total, fits = np.zeros(len(win)), []
        for seed in SEEDS:
            t0 = time.monotonic()
            model = lgb.LGBMRegressor(**rn.params(seed)).fit(x_train, target, sample_weight=weights, feature_name=names)
            path = out / 'models' / f'{arm}_s{seed}.txt'; path.parent.mkdir(parents=True, exist_ok=True)
            model.booster_.save_model(str(path))
            p = np.clip(w_anchor + model.booster_.predict(x_win, num_threads=rn.N_JOBS), -1000., caps).astype('float32')
            pred[f'{arm}_s{seed}'] = p; total += p
            fits.append(dict(seed=seed, model_sha256=sha(path), seconds=round(time.monotonic() - t0, 1)))
            rn.log('window_fit', window=name, arm=arm, seed=seed, features=len(names), seconds=fits[-1]['seconds'])
            del model; gc.collect()
        pred[arm] = (total / len(SEEDS)).astype('float32')
        receipt['arms'][arm] = dict(features=names, fits=fits)
    path = out / 'predictions.parquet'
    pq.write_table(pa.Table.from_pandas(pred, preserve_index=False), path, compression='zstd')
    seal = dict(state=f'WINDOW_{name}_CANDIDATES_SEALED', predictions=str(path), predictions_sha256=sha(path), rows=len(pred),
                design_binding_sha256=sha(out / 'design_binding.json'), prior_q90=q90, receipt=receipt,
                target_scoring_before_seal=False, wall_seconds=time.monotonic() - started)
    rn.write_json(out / 'candidate_seal.json', seal, immutable=True)
    print(json.dumps(dict(state=seal['state'], rows=len(pred), minutes=round(seal['wall_seconds'] / 60, 1))))


if __name__ == '__main__':
    main(sys.argv[1])
