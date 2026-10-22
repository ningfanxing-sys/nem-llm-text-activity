'Refit the affected rule-parser folds and score their saved forecasts.'
from __future__ import annotations
import copy
import gc
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import resource
import sys
import time

os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
sys.dont_write_bytecode = True
OUT = Path(__file__).resolve().parent
PROJ = OUT.parents[2]
notice_fitting = OUT.parent / 'notice_fitting'
DEST = OUT / 'aligned/notice_fitting'
FREEZE = OUT / 'CORRECTION_FREEZE.json'
os.environ['MPLCONFIGDIR'] = str(OUT / 'mpl-cache')

import numpy as np
import pandas as pd


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    assert path.resolve().is_relative_to(OUT)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, default=str, allow_nan=False)
        stream.write('\n')


def freeze_check():
    frozen = read(FREEZE)
    assert frozen['state'] == 'EXTAUDIT_CORRECTION_FROZEN_BEFORE_REFITS'
    for path, digest in frozen['files'].items():
        assert sha(path) == digest, ('correction freeze changed', path)
    assert str(Path(__file__).resolve()) in frozen['files'], 'main helper was not frozen'
    return frozen


def rf_runner():
    runner = module(notice_fitting / 'runner.py', 'extaudit_original_rf2_runner')
    runner.OUT = DEST
    runner.rn.OUT = DEST
    runner.ACTIVE_FREEZE = FREEZE
    runner.rn.N_JOBS = 3
    runner.LIMIT = int(1.5 * 1024**3)
    os.environ['MPLCONFIGDIR'] = str(OUT / 'mpl-cache')
    return runner


def prepare():

    spec_freeze = read(OUT / 'SPEC_FREEZE.json')
    assert sha(OUT / 'SPEC.md') == spec_freeze['sha256']
    r = rf_runner()
    old = read(notice_fitting / 'final/design.json')
    design = copy.deepcopy(old)
    changes = {}
    affected = []
    manifests = {}
    for period in ['development', 'C']:
        metadata_path = r.B1B / f'{period}_metadata.parquet'
        keys = pd.read_parquet(metadata_path, columns=r.KEYS)
        feature_keys_path = OUT.parent / f'notice_records/source_relations/features/R_{period}.parquet'
        feature_keys = pd.read_parquet(feature_keys_path, columns=r.KEYS)
        # Match feature matrices to the training rows by their forecast keys.
        # Compute the row permutation by matching keys within each region.
        permutation = np.empty(len(keys), dtype=np.int64)
        for region in sorted(set(keys.region) | set(feature_keys.region)):
            wanted_index = np.flatnonzero(keys.region.to_numpy() == region)
            source_index = np.flatnonzero(feature_keys.region.to_numpy() == region)
            wanted = keys.iloc[wanted_index].assign(_destination_row=wanted_index)
            existing = feature_keys.iloc[source_index].assign(_source_row=source_index)
            match = wanted.merge(existing, on=r.KEYS, how='inner', validate='one_to_one')
            assert len(match) == len(wanted_index) == len(source_index), ('main key universe differs', period, region)
            permutation[match._destination_row.to_numpy()] = match._source_row.to_numpy()
            del wanted, existing, match
            gc.collect()
        assert np.array_equal(np.sort(permutation), np.arange(len(keys)))
        assert keys.equals(feature_keys.iloc[permutation].reset_index(drop=True)), ('main key alignment failed', period)
        cached_path = OUT / f'corrected_main_R_{period}.npy'
        assert cached_path.exists(), ('root correction matrix not prepared', period)
        cached = np.load(cached_path, mmap_mode='r')
        assert cached.dtype == np.float32
        block = np.empty(cached.shape, dtype=np.float32)
        for start in range(0, len(block), 20000):
            block[start:start + 20000] = cached[permutation[start:start + 20000]]
        previous_path = notice_fitting / f'blocks/final/notices_{period}_R.npy'
        previous = np.load(previous_path, mmap_mode='r')
        assert block.shape == previous.shape
        original_saved = pd.read_parquet(feature_keys_path, columns=old['notice_columns']).to_numpy('float32')
        for start in range(0, len(block), 20000):
            original_aligned = original_saved[permutation[start:start + 20000]]
            assert np.array_equal(original_aligned.view('uint32'), previous[start:start + 20000].view('uint32')), ('original FINAL3/notice_fitting feature parity failed', period, start)
        del original_saved, original_aligned
        same = (block == previous) | (np.isnan(block) & np.isnan(previous))
        changes[period] = (~same).any(axis=1)
        output_path = r.matrix_path('final', period, 'R')
        output_path.parent.mkdir(parents=True, exist_ok=True)
        assert not output_path.exists()
        np.save(output_path, block)
        manifests[period] = dict(rows=len(block), changed_keys=int(changes[period].sum()),
                                 changed_cells=int((~same).sum()), original_sha256=sha(previous_path),
                                 corrected_sha256=sha(output_path), cached_sha256=sha(cached_path), path=str(output_path),
                                 exact_B1B_FINAL3_key_order_after_permutation=True,
                                 original_FINAL3_RF2_features_bitwise_equal_after_alignment=True,
                                 permutation_sha256=hashlib.sha256(permutation.tobytes()).hexdigest())
        del block, cached, previous, same, keys, feature_keys, permutation
        gc.collect()
    for fold in r.FOLDS:
        spec = design['folds'][fold]
        ids = np.load(spec['train_indices_path'])
        tids = np.load(spec['test_indices_path'])
        assert sha(spec['train_indices_path']) == spec['train_indices_sha256']
        assert sha(spec['test_indices_path']) == spec['test_indices_sha256']
        train_changed = int(changes['development'][ids].sum())
        test_changed = int(changes['C' if fold == 'C' else 'development'][tids].sum())
        if train_changed or test_changed:
            affected.append(dict(fold=fold, train_changed_keys=train_changed, test_changed_keys=test_changed))
        matrix = np.load(r.matrix_path('final', 'development', 'R'), mmap_mode='r')
        names = ['R_' + name for name in design['notice_columns']]
        kept, dropped = r.prune(matrix, names, ids)
        spec['arms']['R'].update(notice_kept=kept, notice_dropped=dropped,
                                 features=spec['numeric_kept'] + kept,
                                 matches_reference_features=spec['numeric_kept'] + kept == old['folds'][fold]['arms']['R']['features'])
        del matrix, ids, tids
    for seed, params in design['params_by_seed'].items():
        original = dict(params)
        params['n_jobs'] = 3
        assert {k: v for k, v in params.items() if k != 'n_jobs'} == {k: v for k, v in original.items() if k != 'n_jobs'}
    design.update(correction_freeze_pending=True, original_design_sha256=sha(notice_fitting / 'final/design.json'),
                  original_protocol_sha256=sha(notice_fitting / 'PROTOCOL_RF2.md'),
                  execution_thread_change=dict(original=6, aligned=3, statistical_capacity_unchanged=True))
    write(DEST / 'final/design.json', design)
    write(DEST / 'MAIN_PREFIT_PREPARATION.json', dict(
        state='EXTAUDIT_MAIN_R_PREPARED_BEFORE_REFIT_FREEZE',
        original_runner_sha256=sha(notice_fitting / 'runner.py'), original_scorer_sha256=sha(notice_fitting / 'scoring/score.py'),
        corrected_rule_sha256=sha(OUT / 'parser_review/scheduled_notice_features.py'), corrected_records_sha256=sha(OUT / 'corrected_records_R.parquet'),
        matrices=manifests, affected_folds=affected, fit_count=3 * len(affected),
        design_sha256=sha(DEST / 'final/design.json'),
        inherited='notice_fitting residual labels, legal anchors, set G, forecast_replication numeric matrices, label_availability indices, weights, q90, folds, seeds, train-only pruning and price projection unchanged; only LightGBM threads capped at three.'))
    print(json.dumps(dict(stage='main_prefit_prepared', affected_folds=affected, fit_count=3 * len(affected))), flush=True)


def fit(pilot=False):
    freeze_check()
    r = rf_runner()
    prep = read(DEST / 'MAIN_PREFIT_PREPARATION.json')
    design = read(DEST / 'final/design.json')
    assert prep['design_sha256'] == sha(DEST / 'final/design.json')
    import lightgbm as lgb
    for item in prep['affected_folds']:
        fold = item['fold']
        x, z, y, weight, anchor, caps, keys, names, spec = r.matrices('final', fold, 'R')
        original = pd.read_parquet(notice_fitting / f'final/predictions/{fold}.parquet', columns=r.KEYS)
        assert keys[r.KEYS].equals(original)
        for seed in r.SEEDS:
            receipt_path = DEST / f'receipts/final_{fold}_R_{seed}.json'
            model_path = DEST / f'final/models/{fold}_R_s{seed}.txt'
            prediction_path = DEST / f'final/predictions/{fold}_R_s{seed}.parquet'
            if receipt_path.exists():
                receipt = read(receipt_path)
                assert receipt['freeze_sha256'] == sha(FREEZE)
                assert sha(model_path) == receipt['model_sha256'] and sha(prediction_path) == receipt['prediction_sha256']
                continue
            assert not model_path.exists() and not prediction_path.exists()
            params = dict(design['params_by_seed'][str(seed)])
            assert params == r.rn.params(seed) and params['n_jobs'] == 3
            started = time.monotonic()
            model = lgb.LGBMRegressor(**params).fit(x, y, sample_weight=weight, feature_name=names)
            prediction = np.clip(anchor + model.booster_.predict(z, num_threads=3), -1000., caps).astype('float32')
            assert np.isfinite(prediction).all()
            model_path.parent.mkdir(parents=True, exist_ok=True)
            model.booster_.save_model(str(model_path))
            part = keys.copy()
            part[f'R_s{seed}'] = prediction
            prediction_path.parent.mkdir(parents=True, exist_ok=True)
            part.to_parquet(prediction_path, index=False)
            write(receipt_path, dict(fold=fold, arm='R', seed=seed, train_rows=len(x), test_rows=len(z),
                                     feature_names=names, model_sha256=sha(model_path), prediction_sha256=sha(prediction_path),
                                     freeze_sha256=sha(FREEZE), design_sha256=sha(DEST / 'final/design.json'),
                                     train_indices_sha256=spec['train_indices_sha256'], test_indices_sha256=spec['test_indices_sha256'],
                                     target_sha256=hashlib.sha256(y.tobytes()).hexdigest(), weight_sha256=hashlib.sha256(weight.tobytes()).hexdigest(),
                                     lightgbm_threads=3, seconds=time.monotonic() - started,
                                     peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
            print(json.dumps(dict(stage='main_corrected_fit', fold=fold, seed=seed, seconds=time.monotonic() - started)), flush=True)
            del model, prediction, part
            gc.collect()
            if pilot:
                return
        del x, z, y, weight, anchor, caps, keys, original
        gc.collect()
    seal()


def seal():
    freeze_check()
    r = rf_runner()
    original = read(notice_fitting / 'final/candidate_seal.json')
    affected = {x['fold'] for x in read(DEST / 'MAIN_PREFIT_PREPARATION.json')['affected_folds']}
    files, reuse = {}, []
    for fold, entry in original['files'].items():
        assert sha(entry['path']) == entry['sha256']
        old = pd.read_parquet(entry['path'])
        new = old.copy()
        if fold in affected:
            total = np.zeros(len(new), dtype='float64')
            for seed in r.SEEDS:
                part_path = DEST / f'final/predictions/{fold}_R_s{seed}.parquet'
                receipt = read(DEST / f'receipts/final_{fold}_R_{seed}.json')
                assert sha(part_path) == receipt['prediction_sha256']
                part = pd.read_parquet(part_path)
                assert new[r.KEYS].equals(part[r.KEYS])
                new[f'R_s{seed}'] = part[f'R_s{seed}'].to_numpy()
                total += part[f'R_s{seed}'].to_numpy()
            new['R'] = (total / len(r.SEEDS)).astype('float32')
        unchanged = [col for col in old if fold not in affected or (col != 'R' and not col.startswith('R_s'))]
        assert old[unchanged].equals(new[unchanged])
        path = DEST / f'final/predictions/{fold}.parquet'
        assert not path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        new.to_parquet(path, index=False)
        files[fold] = dict(entry, path=str(path), sha256=sha(path))
        reuse.append(dict(fold=fold, source=entry['path'], source_sha256=entry['sha256'], corrected_path=str(path),
                          unchanged_columns=unchanged, exact_equal=True, refitted_R=fold in affected))
    write(DEST / 'UNCHANGED_PREDICTION_REUSE.json', reuse)
    write(DEST / 'final/candidate_seal.json', dict(original, files=files,
        state='EXTAUDIT_RF2_AFFECTED_R_SEALED', original_seal_sha256=sha(notice_fitting / 'final/candidate_seal.json'),
        design_sha256=sha(DEST / 'final/design.json'), protocol_sha256=sha(notice_fitting / 'PROTOCOL_RF2.md'),
        freeze_sha256=sha(FREEZE), test_scored_before_bank_seal=False))


def score():
    freeze_check()
    scorer = module(notice_fitting / 'scoring/score.py', 'extaudit_frozen_rf2_scorer')
    scorer.RF = DEST
    scorer.HERE = DEST / 'scoring'
    scorer.HERE.mkdir(parents=True, exist_ok=True)
    scorer.ACTIVE_FREEZE = FREEZE
    os.environ['MPLCONFIGDIR'] = str(OUT / 'mpl-cache')
    def bound_freeze():
        freeze_check()
        scorer.register(FREEZE)
        for obj in (scorer.b6, scorer.bs, scorer.sens, scorer.er, scorer.bs.sw, scorer.sens.sm, scorer.b6.se):
            scorer.register(obj.__file__)
        assert scorer.er.BOOT_DRAWS == 2000 and scorer.er.BOOT_SEED == 20260925
    def bound_seal():
        receipt = read(scorer.register(DEST / 'final/candidate_seal.json'))
        assert receipt['freeze_sha256'] == sha(FREEZE)
        assert receipt['protocol_sha256'] == sha(notice_fitting / 'PROTOCOL_RF2.md')
        assert receipt['design_sha256'] == sha(DEST / 'final/design.json')
        assert receipt['test_scored_before_bank_seal'] is False
        assert set(receipt['files']) == set(scorer.FOLDS) | {'C'}
        for entry in receipt['files'].values():
            scorer.register(entry['path'], entry['sha256'])
        return receipt
    scorer.freeze_check = bound_freeze
    scorer.seal_for = bound_seal


    for obj, function in [(scorer, 'c_rows'), (scorer.b6, 'joined')]:
        src = inspect.getsource(getattr(obj, function))
        old = '.dt.tz_convert("Australia/Brisbane").dt.strftime('
        new = '.dt.tz_convert("Australia/Brisbane").dt.tz_localize(None).dt.strftime('
        if old in src:
            exec(compile(src.replace(old, new), str(Path(__file__)), 'exec'), obj.__dict__)
    scorer.stage()


if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'prepare':
        prepare()
    elif mode == 'fit':
        fit(pilot=len(sys.argv) > 2 and sys.argv[2] == 'pilot')
    elif mode == 'seal':
        seal()
    elif mode == 'score':
        score()
    else:
        raise SystemExit(mode)
