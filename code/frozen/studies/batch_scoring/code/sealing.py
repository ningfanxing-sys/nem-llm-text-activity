"""CONF-format identities; only complete stages enter the prediction seal."""
from pathlib import Path
import hashlib
import numpy as np
import pandas as pd
from common import KEYS, SEED, identity, checked, require, write_json, read_json, sha

def normalize(frame):
    frame = frame.copy()
    for c in ('origin', 'target_time'):
        frame[c] = pd.to_datetime(frame[c], utc=True).astype('datetime64[ns, UTC]')
    frame['target_day'] = frame.target_day.astype(str)
    return frame.sort_values(KEYS, kind='mergesort').reset_index(drop=True)

def key_hash(frame):
    return hashlib.sha256(pd.util.hash_pandas_object(frame[KEYS], index=False).to_numpy().tobytes()).hexdigest()

def grid(frame, days):
    require(not frame[KEYS].isna().any().any() and not frame.duplicated(KEYS).any(), 'Missing/duplicate seal keys')
    counts = frame.groupby('target_day', sort=True).size()
    require(list(counts.index) == list(days) and (counts.to_numpy() == 72).all(), 'Incomplete news seal grid')
    for day, f in frame.groupby('target_day'):
        require(set(zip(f.region, f.horizon)) == {(r, h) for r in ('NSW1', 'QLD1', 'TAS1') for h in range(24)}, 'Missing region/hour seal grid')
        issue = pd.Timestamp(day, tz='Australia/Brisbane').tz_convert('UTC')
        require((f.origin == issue).all() and (f.target_time == f.origin + pd.to_timedelta(f.horizon, unit='h')).all(), 'Seal issue/target clock drift')

def create(state, manifest, tasks_by_stage, dispositions, permit, days, input_freeze):
    state = Path(state); path = state / 'SEAL_A2BATCH.json'
    require(not path.exists(), 'Never overwrite existing batch seal')
    source = manifest['base_bundles']['N']
    panel = normalize(pd.read_parquet(source['panel_path'], columns=KEYS + ['target_day']))
    common = panel.loc[panel.target_day.isin(days)].reset_index(drop=True)
    grid(common, days)
    sealed = state / 'sealed'; sealed.mkdir(parents=True, exist_ok=True)
    common_path = sealed / 'news__COMMON_KEYS.parquet'
    common.to_parquet(common_path, index=False)
    predictions, fits, stages = [], [], []
    for name, disposition in dispositions.items():
        stages.append(dict(disposition, receipt_identity=identity(state / 'stages' / (name + '.json'))))
        if disposition['state'] != 'COMPLETE':
            continue
        tasks = tasks_by_stage[name]
        groups = {}
        for task in tasks:
            ident = f'{task.task}__{task.origin}__{task.arm}__s{task.seed}__{task.variant}'
            receipt_path = state / 'fits/receipts' / (ident + '.json')
            rec = read_json(receipt_path)
            require(rec['state'] == 'COMPLETE' and rec['task_id'] == ident, 'Complete stage lacks complete fit')
            require(rec['feature_manifest_sha256'] == sha(state / 'features/manifest.json') and
                    rec['design_freeze_sha256'] == permit.design_freeze_sha256 and
                    rec['completed_input_manifest_sha256'] == permit.completed_input_manifest_sha256, 'Fit identity differs from batch input freeze')
            for what in ('model', 'prediction'):
                require(sha(rec[what + '_path']) == rec[what + '_sha256'], 'Fit artifact drift')
            fits += [identity(receipt_path, kind='fit_receipt'), identity(rec['model_path'], kind='LightGBM_model')]
            groups.setdefault((task.arm, task.variant), []).append(rec)
        for (arm, variant), records in groups.items():
            f = normalize(pd.concat([pd.read_parquet(r['prediction_path']) for r in records], ignore_index=True))
            expected_days = days if variant == 'main' else pd.date_range('2025-01-01', '2025-12-31').strftime('%Y-%m-%d').tolist()
            grid(f, expected_days)
            require(np.isfinite(f.prediction.to_numpy()).all(), 'Nonfinite completed predictions')
            if variant == 'main':
                require(f[KEYS + ['target_day']].equals(common[KEYS + ['target_day']]), 'Sealed common key mismatch')
            dest = sealed / f'news__{arm}__s{SEED}__{variant}.parquet'
            f.to_parquet(dest, index=False)
            predictions.append(identity(dest, source='news', arm=arm, seed=SEED, variant=variant, rows=len(f), common_keys_sha256=key_hash(f)))
    auxiliary = [identity(input_freeze), identity(state / 'features/manifest.json')]
    for name in ('FITTING_WALL_LEDGER.json', 'RESOURCE_RECEIPT.json', 'PARITY_GATE.json'):
        if (state / name).exists():
            auxiliary.append(identity(state / name))
    for b in manifest['bundles']:
        auxiliary.append(b['matrix'])
    if manifest.get('pd6_unpruned'):
        auxiliary.append(manifest['pd6_unpruned'])
    result = dict(state='ALL_REGISTERED_PREDICTIONS_SEALED',
                  design_freeze_sha256=permit.design_freeze_sha256,
                  completed_input_manifest_sha256=permit.completed_input_manifest_sha256,
                  feature_manifest_path=str(state / 'features/manifest.json'), feature_manifest_sha256=sha(state / 'features/manifest.json'),
                  predictions=predictions, common_keys={'news': identity(common_path, rows=len(common), common_keys_sha256=key_hash(common))},
                  truth_panels={'news': identity(source['panel_path'])}, fit_receipts_and_models=fits,
                  stage_dispositions=stages, auxiliary_sources_and_resources=auxiliary,
                  coverage_and_matched_masks=[], partial_predictions_scored=False, sealed_before_outcome_scoring=True)
    write_json(path, result, exclusive=True)
    return result

def verify(state):
    result = read_json(Path(state) / 'SEAL_A2BATCH.json')
    require(result['state'] == 'ALL_REGISTERED_PREDICTIONS_SEALED' and result['sealed_before_outcome_scoring'] and not result['partial_predictions_scored'], 'Invalid batch seal')
    identities = (result['predictions'] + list(result['common_keys'].values()) + list(result['truth_panels'].values()) +
                  result['fit_receipts_and_models'] + result['auxiliary_sources_and_resources'] +
                  [d['receipt_identity'] for d in result['stage_dispositions']])
    for item in identities:
        checked(item)
    return result
