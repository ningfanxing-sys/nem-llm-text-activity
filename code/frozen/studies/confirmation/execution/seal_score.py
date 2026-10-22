"""Complete-stage prediction seal followed by frozen CONF inference/reporting.

All data access is inside explicitly permitted entrypoints. No partial arm,
selected LEAR window, seed substitution or outcome-selected key mask is scored.
"""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import ast
import hashlib
import json

try:
    from .runtime import conf_module, read_json, sha256, atomic_json, file_identity, audit
    from .execution_adapter import (require, feature_manifest, reusable, find_bundle, task_id, KEYS, TERMINAL,
                                    registered_plan)
    from .report_adapter import primary_sentence, secondary_reading, write_host_report
    from . import a1_scoring as a1
except ImportError:
    from runtime import conf_module, read_json, sha256, atomic_json, file_identity, audit
    from execution_adapter import (require, feature_manifest, reusable, find_bundle, task_id, KEYS, TERMINAL,
                                   registered_plan)
    from report_adapter import primary_sentence, secondary_reading, write_host_report
    import a1_scoring as a1

SEED = 20260919
EVENT_SOURCE = Path('/Users/stacchining/Documents/thesis/lamp-moe-research/scripts/pivot_az/audit_historical_support.py')
EVENT_SOURCE_SHA = '91d09205238aba52e6655a0c31597d3e3cbdd15c6e0ce070471609374e554b14'


def tag(source, arm, seed=SEED, variant='main'):
    return f'{source}__{arm}__s{seed}__{variant}'


def key_hash(frame):
    import pandas as pd
    return hashlib.sha256(pd.util.hash_pandas_object(frame[KEYS], index=False).to_numpy().tobytes()).hexdigest()


def coerce_keys(frame):
    import pandas as pd
    f = frame.copy()
    for col in ('origin', 'target_time'):
        f[col] = pd.to_datetime(f[col], utc=True).astype('datetime64[ns, UTC]')
    f['target_day'] = f['target_day'].astype(str)
    return f


def normalize(frame):
    return coerce_keys(frame).sort_values(KEYS, kind='mergesort').reset_index(drop=True)


def complete_grid(keys, source, validation=False):
    """Validate the entire finite domain, without reading price/outcome values."""
    import numpy as np
    import pandas as pd
    if keys[KEYS].isna().any().any() or keys.duplicated(KEYS).any():
        raise ValueError('Missing or duplicate prediction key')
    local = keys['target_time'].dt.tz_convert('Australia/Brisbane')
    if not np.all(keys['target_day'].to_numpy() == local.dt.strftime('%Y-%m-%d').to_numpy()):
        raise ValueError('Target-day assignment differs from frozen AEST rule')
    if source == 'news':
        regions, horizons, per_day = {'NSW1', 'QLD1', 'TAS1'}, set(range(24)), 72
        start, end = ('2025-01-01', '2025-12-31') if validation else ('2026-03-01', '2026-09-30')
        issue = keys['origin'].dt.tz_convert('Australia/Brisbane')
        if not np.all(issue.dt.hour.eq(0) & issue.dt.minute.eq(0) & issue.dt.second.eq(0)):
            raise ValueError('News origin is not midnight AEST')
        if not np.all(keys['target_time'] == keys['origin'] + pd.to_timedelta(keys['horizon'], unit='h')):
            raise ValueError('News hour/horizon mapping drift')
    else:
        regions, horizons, per_day = {'NSW1', 'QLD1', 'SA1', 'TAS1', 'VIC1'}, {5, 10, 15, 20, 25, 30}, 8640
        start, end = '2026-08-01', '2026-09-30'
        if not np.all(local.dt.minute.mod(5).eq(0) & local.dt.second.eq(0)):
            raise ValueError('Notice target not on frozen 5-minute grid')
        if not np.all(keys['target_time'] == keys['origin'] + pd.to_timedelta(keys['horizon'], unit='m')):
            raise ValueError('Notice issue/target/horizon mapping drift')
    if set(keys['region']) != regions or set(keys['horizon']) != horizons:
        raise ValueError('Frozen region/horizon domain missing')
    expected = pd.date_range(start, end, freq='D').strftime('%Y-%m-%d').tolist()
    counts = keys.groupby('target_day', sort=True).size()
    if list(counts.index) != expected or not np.all(counts.to_numpy() == per_day):
        raise ValueError('Shortened/incomplete registered common target grid')
    return expected, counts.to_numpy().tolist()


def _stage_dispositions(state_root):
    result = []
    # CONFX5: the frozen plan plus the registered CONF-A1 W2_D/NPM tasks.
    for name, tasks, mandatory in registered_plan():
        path = Path(state_root) / 'stages' / (name + '.json')
        if not path.exists(): raise PermissionError('Every scheduled stage needs a disposition before sealing: ' + name)
        d = read_json(path)
        if d['state'] not in TERMINAL or (mandatory and d['state'] != 'COMPLETE'):
            raise PermissionError('Incomplete/unavailable primary or undisposed stage: ' + name)
        if d['registered_tasks'] != [task_id(t) for t in tasks]:
            raise PermissionError('Stage population differs from frozen plan: ' + name)
        result.append((name, tasks, d, file_identity(path)))
    return result


def seal(permit, feature_root, state_root):
    require(permit)
    import numpy as np
    import pandas as pd
    root = Path(state_root); path = root / 'SEAL.json'
    if path.exists():
        return verify_seal(permit, feature_root, state_root)
    manifest, feature_sha, _ = feature_manifest(feature_root, permit)
    stages = _stage_dispositions(root)
    grouped = {}; fit_identities = []
    for name, tasks, disposition, identity in stages:
        if disposition['state'] not in ('COMPLETE', 'COMPLETE_WITH_UNAVAILABLE_CONFIGURATIONS'): continue
        eligible = set(disposition.get('eligible_tasks', disposition['registered_tasks']))
        for task in tasks:
            if task_id(task) not in eligible: continue
            rec = reusable(root, task, feature_sha, permit)
            if rec is None: raise PermissionError('Completed stage has incomplete fit: ' + task_id(task))
            fit_identities.append(file_identity(root / 'fits' / 'receipts' / (task_id(task) + '.json'), kind='fit_receipt'))
            if task.task != 'lear': fit_identities.append(file_identity(rec['model_path'], kind='LightGBM_model'))
            if task.task == 'lear':
                if rec.get('component_pairs') != 288 or len(rec['windows']) != 12:
                    raise PermissionError('Incomplete 288-pair daily LEAR job')
                for window in rec['windows']:
                    if sha256(window['model_path']) != window['model_sha256'] or len(window['hours']) != 24:
                        raise PermissionError('LEAR window model receipt drift')
                    fit_identities.append(file_identity(window['model_path'], kind='LEAR_window_models_and_target_scaling'))
                    if sha256(window['input_scaling_path']) != window['input_imputation_scaling_sha256']:
                        raise PermissionError('LEAR calibration input-scaling artifact drift')
                    fit_identities.append(file_identity(window['input_scaling_path'], kind='LEAR_input_imputation_and_scaling'))
            grouped.setdefault((task.task, task.arm, task.seed, task.variant), []).append((task, rec))
    canonical = {}; original_order = {}; canonical_order = {}
    truth_identities = {}
    for source in ('news', 'notice'):
        task = conf_module('scheduler').FitTask(source, '2026-03-01' if source == 'news' else 'prewindow_frozen_C_bank', 'N', SEED)
        bundle = find_bundle(manifest, task)
        audit(bundle['panel_path'], 'key_columns_only', 'pre-score common-key seal')
        frame = pd.read_parquet(bundle['panel_path'], columns=KEYS + ['target_day'])
        days = frame['target_day'].astype(str)
        mask = days.between('2026-03-01' if source == 'news' else '2026-08-01', '2026-09-30')
        original_order[source] = coerce_keys(frame.loc[mask]).reset_index(drop=True)
        ordered = original_order[source].sort_values(KEYS, kind='mergesort')
        canonical_order[source] = ordered.index.to_numpy()
        canonical[source] = ordered.reset_index(drop=True)
        complete_grid(canonical[source], source)
        truth_identities[source] = file_identity(bundle['panel_path'])
    outputs = []
    for (source, arm, seed, variant), fits in sorted(grouped.items()):
        files = []
        for task, rec in sorted(fits, key=lambda x: x[0].origin):
            audit(rec['prediction_path'], 'sealed_candidate_predictions', 'complete stage key/finite validation before score')
            files.append(pd.read_parquet(rec['prediction_path']))
        raw = coerce_keys(pd.concat(files, ignore_index=True))
        domain = 'news' if source == 'lear' else source
        validation = variant == '2025_fixed_validation'
        if not validation and raw[KEYS].equals(original_order[domain][KEYS]):
            joined = raw.iloc[canonical_order[domain]].reset_index(drop=True)
        else:
            joined = raw.sort_values(KEYS, kind='mergesort').reset_index(drop=True)
        if validation: complete_grid(joined, domain, validation)
        if not validation and not joined[KEYS].equals(canonical[domain][KEYS]):
            raise ValueError('Exact common key identity differs for ' + tag(source, arm, seed, variant))
        if not validation and not joined['target_day'].equals(canonical[domain]['target_day']):
            raise ValueError('Paired target-day assignment differs from common-key grid')
        if not np.isfinite(joined['prediction'].to_numpy()).all():
            raise ValueError('Nonfinite completed stage prediction')
        destination = root / 'sealed' / (tag(source, arm, seed, variant) + '.parquet')
        destination.parent.mkdir(parents=True, exist_ok=True)
        joined.to_parquet(destination, index=False)
        outputs.append(file_identity(destination, source=source, arm=arm, seed=seed, variant=variant,
                                     rows=len(joined), common_keys_sha256=key_hash(joined)))
    common = {}
    for source, frame in canonical.items():
        destination = root / 'sealed' / (source + '__COMMON_KEYS.parquet')
        frame.to_parquet(destination, index=False)
        common[source] = file_identity(destination, rows=len(frame), common_keys_sha256=key_hash(frame))
    cov = []
    for bundle in manifest['bundles']:
        for key in ('coverage_path', 'matched_mask_path'):
            if bundle.get(key): cov.append(file_identity(bundle[key]))
    auxiliary = []
    for key in ('W_Bai_selection', 'W2_D_selection', 'notice_derived_dates'):
        if manifest.get(key): auxiliary.append(dict(manifest[key], kind=key))
    for kind in ('hourly', 'canonical_price'):
        p = manifest.get(kind + '_path')
        if p:
            identity = file_identity(p)
            if identity['sha256'] != manifest.get(kind + '_sha256'):
                raise ValueError('Feature-manifest auxiliary identity changed: ' + kind)
            auxiliary.append(dict(identity, kind=kind))
    if (root / 'FITTING_WALL_LEDGER.json').exists(): auxiliary.append(file_identity(root / 'FITTING_WALL_LEDGER.json', kind='wall_fitting_ledger'))
    rec = {'state': 'ALL_REGISTERED_PREDICTIONS_SEALED', 'design_freeze_sha256': permit.design_freeze_sha256,
           'completed_input_manifest_sha256': permit.completed_input_manifest_sha256,
           'feature_manifest_path': str(Path(feature_root) / 'manifest.json'), 'feature_manifest_sha256': feature_sha,
           'stage_dispositions': [dict(d, receipt_identity=i) for _, _, d, i in stages],
           'predictions': outputs, 'common_keys': common, 'truth_panels': truth_identities,
           'coverage_and_matched_masks': cov, 'fit_receipts_and_models': fit_identities,
           'auxiliary_sources_and_resources': auxiliary, 'partial_predictions_scored': False,
           'sealed_before_outcome_scoring': True}
    atomic_json(path, rec, immutable=True)
    return rec


def verify_seal(permit, feature_root, state_root):
    require(permit)
    rec = read_json(Path(state_root) / 'SEAL.json')
    if rec['state'] != 'ALL_REGISTERED_PREDICTIONS_SEALED' or not rec['sealed_before_outcome_scoring']:
        raise PermissionError('Global prediction seal missing')
    if rec['design_freeze_sha256'] != permit.design_freeze_sha256 or rec['completed_input_manifest_sha256'] != permit.completed_input_manifest_sha256:
        raise PermissionError('Sealed input identities changed')
    if sha256(Path(feature_root) / 'manifest.json') != rec['feature_manifest_sha256']:
        raise PermissionError('Sealed feature manifest changed')
    for d in rec['stage_dispositions']:
        ident = d['receipt_identity']
        if sha256(ident['path']) != ident['sha256']:
            raise PermissionError('Sealed stage disposition changed')
    for ident in rec['predictions'] + list(rec['common_keys'].values()) + list(rec['truth_panels'].values()) + rec['coverage_and_matched_masks'] + rec['fit_receipts_and_models'] + rec['auxiliary_sources_and_resources']:
        if sha256(ident['path']) != ident['sha256']:
            raise PermissionError('Sealed data changed: ' + ident['path'])
    return rec


def _json_result(value):
    import numpy as np
    if isinstance(value, dict): return {str(k): _json_result(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_json_result(v) for v in value]
    if isinstance(value, np.ndarray): return _json_result(value.tolist())
    if isinstance(value, np.generic): return _json_result(value.item())
    if isinstance(value, float) and not np.isfinite(value): return None
    return value


def _write_inference(path, result):
    """Retain bootstrap picks/draws in a standalone binary artifact plus JSON."""
    import numpy as np
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {}
    for block, picks in result.get('paired_day_picks', {}).items():
        if picks is not None: arrays['picks_' + str(block)] = picks
    cleaned = dict(result); cleaned.pop('paired_day_picks', None)
    cleaned['reports'] = []
    for index, report in enumerate(result['reports']):
        r = dict(report); r['bootstrap'] = {}
        for block, bootstrap in report.get('bootstrap', {}).items():
            b = dict(bootstrap)
            draws = b.pop('draws', None)
            if draws is not None: arrays[f'contrast_{index}_draws_{block}'] = draws
            r['bootstrap'][block] = b
        cleaned['reports'].append(r)
    binary = path.with_suffix('.npz'); np.savez_compressed(binary, **arrays)
    cleaned['bootstrap_artifact'] = file_identity(binary)
    atomic_json(path, _json_result(cleaned)); return cleaned


def _primary_sentence(report, task):
    return primary_sentence(report, task)


def _read_task_data(source, seal_receipt, diagnostic_root=None):
    import numpy as np
    import pandas as pd
    identity = seal_receipt['truth_panels'][source]
    audit(identity['path'], 'authorized_postseal_outcome_read', 'frozen absolute daily losses')
    columns = KEYS + ['target_day', 'y', 'weight']
    if source == 'news':
        import pyarrow.parquet as pq
        if 'weekly_naive' in pq.ParquetFile(identity['path']).schema.names: columns.append('weekly_naive')
    panel = pd.read_parquet(identity['path'], columns=columns)
    lo = '2026-03-01' if source == 'news' else '2026-08-01'
    panel = normalize(panel.loc[panel['target_day'].astype(str).between(lo, '2026-09-30')])
    days, counts = complete_grid(panel, source)
    if not np.isfinite(panel['y'].to_numpy()).all() or not np.all(panel['weight'].to_numpy() == 1):
        raise ValueError('Complete finite truth and unit evaluation weight gate failed')
    predicted, identities, clips, raw = {}, {}, [], {}
    for ident in seal_receipt['predictions']:
        if ident['source'] not in (source, 'lear' if source == 'news' else source) or ident['variant'] == '2025_fixed_validation': continue
        # Seal persisted every prediction in the canonical key order already.
        frame = coerce_keys(pd.read_parquet(ident['path'])).reset_index(drop=True)
        if not frame[KEYS].equals(panel[KEYS]): raise ValueError('Postseal paired key equality failed')
        label = (ident['arm'], ident['seed'], ident['variant'])
        predicted[label] = frame['prediction'].to_numpy(dtype='float64'); identities[label] = ident
        # CONFX5 (CONF-A1 decision 6): the sealed raw prediction for the official-cap sensitivity.
        raw[label] = frame['raw_prediction'].to_numpy(dtype='float64')
        # No clipping operation is applied to news, including LEAR. Bounds are
        # diagnostic only; notice raw/final and inherited date caps are retained.
        if source == 'notice':
            frame['raw_below_lower'] = frame['raw_prediction'] < frame['lower_bound']
            frame['raw_above_upper'] = frame['raw_prediction'] > frame['upper_bound']
            frame['final_lower_hits'] = frame['prediction'] == frame['lower_bound']
            frame['final_upper_hits'] = frame['prediction'] == frame['upper_bound']
        else:
            frame['raw_below_lower'] = frame['raw_prediction'] < -1000.
            frame['raw_above_upper'] = frame['raw_prediction'] > 17500.
            frame['final_lower_hits'] = frame['prediction'] == -1000.
            frame['final_upper_hits'] = frame['prediction'] == 17500.
        fields = ['raw_below_lower', 'raw_above_upper', 'final_lower_hits', 'final_upper_hits']
        if diagnostic_root is not None:
            affected = frame.loc[frame[fields].any(axis=1), KEYS + ['target_day', 'raw_prediction', 'prediction'] + fields]
            path = Path(diagnostic_root) / (tag(source, ident['arm'], ident['seed'], ident['variant']) + '__BOUND_DIAGNOSTIC_KEYS.parquet')
            path.parent.mkdir(parents=True, exist_ok=True); affected.to_parquet(path, index=False)
        for grouping in (['region', 'horizon'], ['target_day'], []):
            groups = frame.groupby(grouping, sort=True) if grouping else [((), frame)]
            for values, group in groups:
                if not isinstance(values, tuple): values = (values,)
                item = dict(zip(grouping, values)); item.update(source=source, arm=ident['arm'], seed=ident['seed'], variant=ident['variant'], eligible_predictions=len(group), clipping_operations=int((group['raw_prediction'] != group['prediction']).sum()) if source == 'notice' else 0)
                item.update({name: int(group[name].sum()) for name in fields}); clips.append(item)
    return panel, days, counts, predicted, identities, clips, raw


def _daily(panel, prediction, mask=None):
    import numpy as np
    import pandas as pd
    selected = np.ones(len(panel), dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
    loss = np.abs(prediction[selected] - panel['y'].to_numpy(dtype='float64')[selected])
    frame = pd.DataFrame({'day': panel['target_day'].to_numpy()[selected], 'loss': loss})
    daily = frame.groupby('day', sort=True)['loss'].mean()
    return list(daily.index), daily.to_numpy(dtype='float64')


def _matched_mask(manifest, source, panel):
    import numpy as np
    import pandas as pd
    found = [b for b in manifest['bundles'] if b['source'] == source and b['arm'] == 'P_content' and b.get('variant', 'main') == 'main']
    if len(found) != 1 or not found[0].get('matched_mask_path'): return np.zeros(len(panel), dtype=bool)
    b = found[0]; mask = np.load(b['matched_mask_path'], mmap_mode='r', allow_pickle=False)
    keys = pd.read_parquet(b['panel_path'], columns=KEYS + ['target_day'])
    if mask.shape != (len(keys),): raise ValueError('Matched P_content mask shape mismatch')
    keys['matched'] = mask.astype(bool)
    keys = normalize(keys); keys = keys.loc[keys['target_day'].between('2026-03-01' if source == 'news' else '2026-08-01', '2026-09-30')].reset_index(drop=True)
    if not keys[KEYS].equals(panel[KEYS]): raise ValueError('Matched P_content key identity mismatch')
    return keys['matched'].to_numpy(dtype=bool)


def _secondary_contrasts(source):
    if source == 'news':
        arms = ['M', 'L_count', 'L_chen', 'M_shift', 'E_raw', 'W_Bai', 'P_shift', 'P_content', 'LEAR']
        pairs = [(a, 'N') for a in arms] + [('E_raw', 'M'), ('W_Bai', 'M'), ('L_chen', 'E_raw'),
                ('L_chen', 'W_Bai'), ('P_shift', 'M_shift'), ('P_content', 'M'),
                ('L_chen', 'P_shift'), ('L_chen', 'P_content'), ('LEAR', 'M')]
        pairs += [(a, 'LEAR') for a in ['N'] + [a for a in arms if a != 'LEAR']]
    else:
        arms = ['M_notice', 'L14', 'L_Laz', 'L_chen_notice', 'M_shift_notice', 'R', 'T', 'P_shift', 'P_content', 'NP', 'NPL', 'NPP']
        pairs = [(a, 'N') for a in arms] + [('R', 'M_notice'), ('T', 'M_notice'), ('P_shift', 'M_shift_notice'),
                ('P_content', 'M_notice'), ('L_chen_notice', 'P_shift'), ('L_chen_notice', 'P_content'),
                ('NPL', 'NP'), ('NPL', 'NPP'), ('NPP', 'NP')]
    # CONFX5 (CONF-A1 decisions 4, 7): registered additions after every frozen slot.
    pairs += list(a1.A1_SECONDARY_CONTRASTS[source])
    return list(dict.fromkeys(pairs))


def _secondary_reading(arm, reference, report, source):
    return secondary_reading(arm, reference, report, source)


def severe_events(prices, panel, predictions, source, matched_masks=None):
    """Frozen source functions only; robust empty handling is a mechanical guard."""
    import numpy as np
    import pandas as pd
    if sha256(EVENT_SOURCE) != EVENT_SOURCE_SHA: raise PermissionError('Frozen severe-event source drift')
    audit(EVENT_SOURCE, 'code_read', 'hash-pinned severe connected-event functions only')
    tree = ast.parse(EVENT_SOURCE.read_text())
    needed = {'directly_connected', 'regional_clusters', 'assign_system_events'}
    functions = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in needed], type_ignores=[])
    if {n.name for n in functions.body} != needed: raise RuntimeError('Frozen event functions not found')
    namespace = {'pd': pd, 'json': json, 'DIRECT_EDGES': frozenset({frozenset(('QLD1', 'NSW1')),
                 frozenset(('NSW1', 'VIC1')), frozenset(('VIC1', 'SA1')), frozenset(('VIC1', 'TAS1'))})}
    exec(compile(functions, str(EVENT_SOURCE), 'exec'), namespace)
    f = prices.copy(); f['event_time'] = pd.to_datetime(f['event_time'], utc=True)
    lo = pd.Timestamp('2026-03-01' if source == 'news' else '2026-08-01', tz='Australia/Brisbane').tz_convert('UTC')
    hi = pd.Timestamp('2026-10-01', tz='Australia/Brisbane').tz_convert('UTC')
    event_clock = f['event_time'] - pd.Timedelta(minutes=5) if source == 'news' else f['event_time']
    f = f.loc[(event_clock >= lo) & (event_clock < hi) & f['price'].gt(5000)].copy()
    f['available_horizons'] = 24 if source == 'news' else 6
    f['horizon_values'] = ','.join(map(str, range(24) if source == 'news' else (5, 10, 15, 20, 25, 30)))
    columns = ['system_event_id', 'start', 'end', 'regions', 'severe_interval_count', 'unique_matched_target_keys', 'peak_price', 'boundary_truncated']
    if f.empty: return pd.DataFrame(columns=columns), {'state': 'ZERO_SEVERE_EVENTS', 'events': 0, 'event_equal_losses': {}}
    clusters = namespace['assign_system_events'](namespace['regional_clusters'](f, 'GT5000'))
    rows = []
    for ident, group in clusters.groupby('system_event_id', sort=True):
        selected = []
        for _, cluster in group.iterrows():
            intervals = f.loc[f['region'].eq(cluster['region']) & f['event_time'].between(cluster['start'], cluster['end'])]
            targets = (intervals['event_time'] - pd.Timedelta(minutes=5)).dt.floor('h') if source == 'news' else intervals['event_time']
            selected.append(panel['region'].eq(cluster['region']).to_numpy() & panel['target_time'].isin(targets).to_numpy())
        mask = np.logical_or.reduce(selected)
        row = {'system_event_id': ident, 'start': group['start'].min().isoformat(), 'end': group['end'].max().isoformat(),
               'regions': ','.join(sorted(set(group['region']))), 'severe_interval_count': int(group['rows'].sum()),
               'unique_matched_target_keys': int(mask.sum()), 'peak_price': float(group['peak_price'].max()),
               'boundary_truncated': bool((group['start'] <= lo + pd.Timedelta(minutes=5)).any() or
                                          (group['end'] >= hi - pd.Timedelta(minutes=5)).any())}
        for horizon in sorted(panel['horizon'].unique()): row['keys_h' + str(horizon)] = int((mask & panel['horizon'].eq(horizon).to_numpy()).sum())
        masks = {arm: mask & (matched_masks or {}).get(arm, np.ones(len(mask), dtype=bool)) for arm in predictions}
        for arm, pred in predictions.items():
            amask = masks[arm]
            row[arm + '__matched_keys'] = int(amask.sum())
            row[arm + '__mae'] = float(np.abs(pred[amask] - panel['y'].to_numpy()[amask]).mean()) if amask.any() else None
        ref = 'M' if source == 'news' else 'M_notice'
        for arm in predictions:
            amask = masks[arm]
            a = row[arm + '__mae']
            b = float(np.abs(predictions[ref][amask] - panel['y'].to_numpy()[amask]).mean()) if ref in predictions and amask.any() else None
            row[arm + '__minus_reference'] = a - b if a is not None and b is not None else None
            row[arm + '__percent_reference'] = 100 * (a - b) / b if a is not None and b is not None and b > 0 else None
        for a, b in _secondary_contrasts(source) + list(conf_module('scoring').NEWS_FAMILY if source == 'news' else conf_module('scoring').NOTICE_FAMILY):
            if a not in predictions or b not in predictions: continue
            pair_mask = masks[a] & masks[b]
            la = float(np.abs(predictions[a][pair_mask] - panel['y'].to_numpy()[pair_mask]).mean()) if pair_mask.any() else None
            lb = float(np.abs(predictions[b][pair_mask] - panel['y'].to_numpy()[pair_mask]).mean()) if pair_mask.any() else None
            row[a + '__minus__' + b] = la - lb if la is not None and lb is not None else None
            row[a + '__percent__' + b] = 100 * (la - lb) / lb if la is not None and lb is not None and lb > 0 else None
        rows.append(row)
    table = pd.DataFrame(rows)
    equal = {arm: {'event_equal_mae': float(table[arm + '__mae'].dropna().mean()) if table[arm + '__mae'].notna().any() else None}
             for arm in predictions}
    return table, {'state': 'DESCRIPTIVE_ONLY', 'events': len(table), 'event_equal_losses': equal}


def _stage_reasons_for(seal_receipt, source):
    """Recorded reasons when the frozen extra-seed stage of a task is not complete."""
    reasons = []
    for stage in seal_receipt.get('stage_dispositions', []):
        if stage.get('stage') == 'primary_seed_robustness_' + source and stage.get('state') != 'COMPLETE':
            reasons.append(str(stage.get('stage')) + ': ' + str(stage.get('state')) + '; ' +
                           str(stage.get('reason') or stage.get('error') or 'see retained stage receipt'))
    return reasons


def _a1_contrast_row(report, n_days=None):
    one = report.get('bootstrap', {}).get(1, report.get('bootstrap', {}).get('1', {}))
    seven = report.get('bootstrap', {}).get(7, report.get('bootstrap', {}).get('7', {}))
    dm = report.get('dm_p1', {})
    return {'arm': report['arm'], 'reference': report['reference'], 'n_days': dm.get('n_days', n_days),
            'effect_percent_reference_mae': one.get('effect_percent_reference_mae'),
            'interval95_percent_one_day': one.get('interval95_percent'),
            'interval95_percent_seven_day': seven.get('interval95_percent'),
            'daily_mean_difference': dm.get('mean_difference'), 'p_two_sided': dm.get('p_two_sided'),
            'hln_t_p_two_sided': a1.hln_p_two_sided(dm.get('statistic'), dm.get('n_days')),
            'hac7_state': report.get('dm_hac7', {}).get('state')}


def _a1_task(source, panel, days, prediction, raw, primary, three_seed, seed_results, scoring, scoring_permit,
             panel_identity, root, stage_reasons):
    """CONF-A1 declared sensitivities for one task; never changes a saved frozen reading."""
    import numpy as np
    family = scoring.NEWS_FAMILY if source == 'news' else scoring.NOTICE_FAMILY
    tested = list(dict.fromkeys(a for pair in family for a in pair))
    out = {}
    # Decision 9: HLN small-sample calibration of the frozen statistic, same family size.
    hln = a1.hln_family(primary['reports'], scoring.holm)
    atomic_json(root / (source + '__A1_HLN.json'), a1.json_safe(hln)); out['hln'] = hln
    # Decision 3: SEED_FRAGILE against the frozen three-seed equal prediction mean.
    reason = None if three_seed is not None else ('; '.join(stage_reasons) or
        'the three-seed equal prediction mean was not computed (paired sealed extra-seed predictions unavailable)')
    fragile = a1.seed_fragility(primary['reports'], None if three_seed is None else three_seed['reports'],
                                seed_results, reason)
    atomic_json(root / (source + '__A1_SEED_FRAGILE.json'), a1.json_safe(fragile)); out['seed_fragile'] = fragile
    # Decision 2: SESOI wording appended to the frozen primary sentences.
    out['sesoi'] = [a1.sesoi_reading(r) for r in primary['reports']]
    # Decision 10: primary contrasts on the days with no recorded analysis (descriptive).
    keep = a1.exposure_excluded_days(source)
    mask = panel['target_day'].astype(str).isin(keep).to_numpy()
    d = {}
    for arm in tested:
        subset, d[arm] = _daily(panel, prediction[(arm, SEED, 'main')], mask)
        if subset != keep:
            raise ValueError('Exposure-excluded day subset differs from the frozen list')
    report = scoring.secondary_daily_inference(d, list(family), keep, scoring_permit)
    report.update(analysis_role='A1_EXPOSURE_EXCLUDED_DESCRIPTIVE', rule=a1.EXPOSURE_RULE,
                  day_runs=[list(run) for run in a1.EXPOSURE_EXCLUDED_RUNS[source]])
    _write_inference(root / (source + '__A1_EXPOSURE_EXCLUDED.json'), report)
    out['exposure_excluded'] = {'state': 'COMPUTED_DESCRIPTIVE', 'days': len(keep),
        'day_runs': [list(run) for run in a1.EXPOSURE_EXCLUDED_RUNS[source]], 'rule': a1.EXPOSURE_RULE,
        'report_path': str(root / (source + '__A1_EXPOSURE_EXCLUDED.json')), 'date_gaps': report['date_gaps'],
        'rows': [_a1_contrast_row(r) for r in report['reports']]}
    # Decision 6: official market price cap. Truth is never clipped; news is never clipped.
    targets = panel['target_time']
    cap = a1.official_market_price_cap(targets)
    diagnostic = []
    for (arm, seed, variant), values in sorted(raw.items()):
        row = {'source': source, 'arm': arm, 'seed': seed, 'variant': variant, 'eligible_predictions': int(len(values)),
               'raw_above_17500': int(np.sum(values > 17500.)), 'raw_above_official_cap': int(np.sum(values > cap)),
               'raw_below_floor': int(np.sum(values < a1.OFFICIAL_MARKET_FLOOR)),
               'official_cap_values': sorted(set(float(v) for v in np.unique(cap)))}
        if source == 'notice':
            reclipped = a1.official_reclip(values, targets).astype('float64')
            row['keys_changed_by_official_reclip'] = int(np.sum(reclipped != prediction[(arm, seed, variant)]))
        diagnostic.append(row)
    import pandas as pd
    pd.DataFrame([{k: (','.join(map(str, v)) if isinstance(v, list) else v) for k, v in row.items()} for row in diagnostic]
                 ).to_csv(root / (source + '__A1_OFFICIAL_CAP_DIAGNOSTIC.csv'), index=False)
    out['official_cap'] = {'diagnostic_path': str(root / (source + '__A1_OFFICIAL_CAP_DIAGNOSTIC.csv')),
                           'caps_by_financial_year': [list(row) for row in a1.OFFICIAL_MARKET_PRICE_CAP],
                           'window_c': a1.WINDOW_C_RECLIP_STATE}
    if source == 'notice':
        out['official_cap'].update(_a1_reclip(panel, days, prediction, raw, tested, scoring, scoring_permit,
                                              panel_identity, root))
    else:
        out['official_cap']['news_rule'] = ('News predictions are not clipped; the official cap by date (20,300 for target days '
                                            'in FY2025-26, 23,200 in FY2026-27) is reported next to 17,500 as a descriptive count.')
    return out


def _a1_reclip(panel, days, prediction, raw, tested, scoring, scoring_permit, panel_identity, root):
    """Decision 6: sealed raw notice predictions re-clipped at the official cap; frozen rules rescored."""
    targets = panel['target_time']
    reclipped = {arm: a1.official_reclip(values, targets).astype('float64')
                 for (arm, seed, variant), values in raw.items() if seed == SEED and variant == 'main'}
    result = {'analysis_role': 'A1_OFFICIAL_CAP_RECLIP_SENSITIVITY'}
    if all(arm in reclipped for arm in tested):
        primary = scoring.registered_daily_inference({a: _daily(panel, reclipped[a])[1] for a in tested}, days,
                                                     'notice', scoring_permit, panel_identity)
        primary['analysis_role'] = 'A1_OFFICIAL_CAP_RECLIP_SENSITIVITY'
        _write_inference(root / 'notice__A1_OFFICIAL_CAP_RECLIP_PRIMARY.json', primary)
        result['primary'] = {'report_path': str(root / 'notice__A1_OFFICIAL_CAP_RECLIP_PRIMARY.json'),
            'rows': [dict(_a1_contrast_row(r), primary_two_sided_holm_p=r.get('primary_two_sided_holm_p'),
                          primary_decision=r.get('primary_decision')) for r in primary['reports']]}
    else:
        result['primary'] = {'state': 'NOT_EVALUABLE_PRIMARY_RAW_PREDICTIONS_MISSING'}
    e3 = []
    for arm, reference in a1.E3_RECLIP_CONTRASTS:
        if arm not in reclipped or reference not in reclipped:
            e3.append({'arm': arm, 'reference': reference, 'state': 'NOT_EVALUABLE_WHOLE_STAGE_UNAVAILABLE'}); continue
        mask = a1.shift_support_mask(panel) if a1.shift_dependent('notice', arm, reference) else None
        subset, la = _daily(panel, reclipped[arm], mask); _, lb = _daily(panel, reclipped[reference], mask)
        report = scoring.secondary_daily_inference({arm: la, reference: lb}, [(arm, reference)], subset, scoring_permit)
        report['analysis_role'] = 'A1_OFFICIAL_CAP_RECLIP_SENSITIVITY'
        path = root / ('notice__A1_OFFICIAL_CAP_RECLIP__' + arm + '__' + reference + '.json')
        _write_inference(path, report)
        e3.append(dict(_a1_contrast_row(report['reports'][0]), state='COMPUTED_SECONDARY', report_path=str(path),
                       days=len(subset), **({'a1_day_rule': 'SHIFT_SUPPORTED_TARGET_DAYS_ONLY'} if mask is not None else {})))
    joint = [r for r in e3 if (r['arm'], r['reference']) in (('NPL', 'NP'), ('NPL', 'NPP'))]
    if len(joint) != 2 or any(r['state'] != 'COMPUTED_SECONDARY' or r['p_two_sided'] is None for r in joint):
        state = 'E3_SECONDARY_JOINT_NOT_EVALUABLE'
    else:
        state = ('E3_SECONDARY_JOINT_CONFIRMED' if all(r['daily_mean_difference'] < 0 and r['p_two_sided'] < .05 for r in joint)
                 else 'E3_SECONDARY_JOINT_NOT_CONFIRMED')
    result.update(e3=e3, e3_joint_state=state, e3_joint_day_rule=a1.E3_DAY_RULE)
    return result


def _lear_convergence(seal_receipt):
    """Template-rule LEAR diagnostic from the sealed LEAR fit receipts (no forecast or outcome is read)."""
    try:
        from .lear_adapter_confx5 import convergence_diagnostic
    except ImportError:
        from lear_adapter_confx5 import convergence_diagnostic
    receipts = []
    for identity in seal_receipt.get('fit_receipts_and_models', []):
        if identity.get('kind') == 'fit_receipt' and Path(identity['path']).name.startswith('lear__'):
            audit(identity['path'], 'sealed_fit_receipt', 'CONFX5 LEAR convergence diagnostic (template rule)')
            receipts.append(read_json(identity['path']))
    if not receipts:
        return {'state': 'NOT_AVAILABLE_NO_SEALED_LEAR_JOB'}
    return dict(convergence_diagnostic(receipts), state='DESCRIPTIVE_ONLY')


def _a1_summary(manifest, tasks, primary_by_source, seal_receipt=None):
    bundles = {(b.get('source'), b.get('arm'), b.get('variant', 'main')): b for b in manifest.get('bundles', [])}
    def disposition(key):
        b = bundles.get(key)
        return None if b is None else {'state': b.get('state', 'COMPLETE'), 'reason': b.get('reason')}
    w_bai = disposition(('news', 'W_Bai', 'main'))
    return {'addendum': 'CONF-A1', 'implemented_by': 'CONFX5', 'decisions_sha256_at_implementation': a1.DECISIONS_SHA256,
            'spec_sha256_at_implementation': a1.SPEC_SHA256, 'source': a1.A1_SOURCE,
            'sesoi_percent': a1.SESOI_PERCENT, 'tasks': tasks,
            'per_task_statements': a1.per_task_statements(primary_by_source),
            'w2_d': disposition(('news', 'W2_D', 'main')), 'npm': disposition(('notice', 'NPM', 'main')),
            'w_bai': w_bai, 'w_bai_note': None if w_bai is None or w_bai['state'] == 'COMPLETE' else a1.w_bai_note(w_bai['state']),
            'shift_support_rule': {'arms': list(a1.SHIFT_DEPENDENT_NOTICE_ARMS), **a1.shift_slot_fields()},
            'exposure_wording': a1.EXPOSURE_WORDING,
            'lear_convergence_diagnostic': _lear_convergence(seal_receipt or {}),
            'primary_decision_rule_changed': False}


def score(permit, feature_root, state_root):
    """Verify global seal, then assemble every frozen primary/secondary reading."""
    require(permit)
    import numpy as np
    import pandas as pd
    root = Path(state_root); scoring_root = root / 'scored'
    seal_receipt = verify_seal(permit, feature_root, root)
    complete_score = scoring_root / 'SCORE_RECEIPT.json'
    if complete_score.exists():
        receipt = read_json(complete_score)
        if receipt['seal_sha256'] != sha256(root / 'SEAL.json'):
            raise PermissionError('Score resume seal identity drift')
        for identity in receipt['files']:
            if sha256(identity['path']) != identity['sha256']:
                raise PermissionError('Score resume artifact drift: ' + identity['path'])
        return read_json(scoring_root / 'SCORE_REPORT.json')
    scoring_permit = replace(permit, predictions_sealed=True)
    require(scoring_permit, scoring=True)
    manifest = read_json(Path(feature_root) / 'manifest.json')
    scoring = conf_module('scoring'); summaries = {}; lines = []
    a1_tasks = {}; a1_primary = {}
    for source in ('news', 'notice'):
        panel, days, counts, prediction, identities, clips, raw = _read_task_data(source, seal_receipt, scoring_root)
        primary_arms = ['N', 'M', 'L_count', 'L_chen'] if source == 'news' else ['N', 'M_notice', 'L14', 'L_Laz', 'L_chen_notice']
        base = {a: prediction[(a, SEED, 'main')] for a in primary_arms}
        daily = {a: _daily(panel, p)[1] for a, p in base.items()}
        for (arm, seed, variant), pred in prediction.items():
            if seed == SEED and variant == 'main': daily[arm] = _daily(panel, pred)[1]
        panel_identity = {'daily_common_key_counts': counts, 'common_keys_sha256': seal_receipt['common_keys'][source]['common_keys_sha256'],
                          'sealed_prediction_manifest_sha256': sha256(root / 'SEAL.json')}
        primary = scoring.registered_daily_inference(daily, days, source, scoring_permit, panel_identity)
        primary_path = scoring_root / (source + '__PRIMARY.json')
        saved_primary = _write_inference(primary_path, primary)
        lines.extend(_primary_sentence(r, source) for r in primary['reports'])
        daily_frame = pd.DataFrame({'target_day': days, **daily}); scoring_root.mkdir(parents=True, exist_ok=True)
        daily_frame.to_csv(scoring_root / (source + '__DAILY_LOSSES.csv'), index=False)
        pd.DataFrame(clips).to_csv(scoring_root / (source + '__CLIPPING.csv'), index=False)
        # Secondary comparisons keep their fixed slots, including unavailable arms.
        matched = _matched_mask(manifest, source, panel); secondary = []
        for arm, reference in _secondary_contrasts(source):
            mask = matched if 'P_content' in (arm, reference) else None
            # CONFX5 (CONF-A1 decision 5): 28-day-shifted notice inputs are evaluated only
            # on shift-supported target days; the early-August source gap is not evaluable.
            shift_rule = a1.shift_dependent(source, arm, reference)
            if shift_rule:
                support = a1.shift_support_mask(panel)
                mask = support if mask is None else (mask & support)
            if arm not in daily or reference not in daily or (mask is not None and not mask.any()):
                slot = {'arm': arm, 'reference': reference, 'state': 'NO_VALID_PERMUTATION' if 'P_content' in (arm, reference) and not matched.any() else 'NOT_EVALUABLE_WHOLE_STAGE_UNAVAILABLE', 'primary_confirmation': False}
                if shift_rule: slot.update(a1.shift_slot_fields())
                secondary.append(slot)
                continue
            a = prediction[(arm, SEED, 'main')]; b = prediction[(reference, SEED, 'main')]
            subset_days, la = _daily(panel, a, mask); rb_days, lb = _daily(panel, b, mask)
            if subset_days != rb_days: raise ValueError('Secondary paired days changed')
            if len(subset_days) < 7:
                secondary.append({'arm': arm, 'reference': reference, 'state': 'NOT_EVALUABLE_INSUFFICIENT_REGISTERED_BLOCK_SUPPORT', 'primary_confirmation': False}); continue
            report = scoring.secondary_daily_inference({arm: la, reference: lb}, [(arm, reference)], subset_days, scoring_permit)
            name = source + '__SECONDARY__' + arm + '__' + reference
            saved = _write_inference(scoring_root / (name + '.json'), report)
            r = report['reports'][0]; slot = {'arm': arm, 'reference': reference, 'state': 'COMPUTED_SECONDARY',
                'reading': _secondary_reading(arm, reference, r, source), 'report_path': str(scoring_root / (name + '.json')),
                'daily_mean_difference': r['dm_p1']['mean_difference'], 'p_two_sided': r['dm_p1']['p_two_sided'],
                'matched_keys': int(mask.sum()) if mask is not None else len(panel), 'days': len(subset_days)}
            # CONFX5 (CONF-A1 decision 9): HLN t(n-1) p recorded beside the frozen normal p.
            slot['hln_t_p_two_sided'] = a1.hln_p_two_sided(r['dm_p1'].get('statistic'), r['dm_p1'].get('n_days'))
            if shift_rule: slot.update(a1.shift_slot_fields())
            secondary.append(slot)
        sensitivities = []
        seed_results = {}; three_seed = None
        # Extra seeds and the fixed equal prediction mean are secondary; do not
        # average p values or replace main-seed family readings.
        family = scoring.NEWS_FAMILY if source == 'news' else scoring.NOTICE_FAMILY
        tested = list(dict.fromkeys(a for pair in family for a in pair))
        seed_signs = {}
        for seed in (20260920, 20260921):
            if not all((a, seed, 'main') in prediction for a in tested): continue
            d = {a: _daily(panel, prediction[(a, seed, 'main')])[1] for a in tested}
            result = scoring.registered_daily_inference(d, days, source, scoring_permit, panel_identity)
            result['analysis_role'] = 'SECONDARY_SEED_SENSITIVITY'; result['seed'] = seed
            _write_inference(scoring_root / f'{source}__SEED_{seed}.json', result)
            seed_results[seed] = result
            seed_signs[seed] = [np.sign(r['dm_p1']['mean_difference']) for r in result['reports']]
            sensitivities.append({'name': 'seed', 'seed': seed, 'state': 'COMPUTED_SECONDARY'})
        if all((a, seed, 'main') in prediction for a in tested for seed in (SEED, 20260920, 20260921)):
            d = {}
            for a in tested:
                mean_prediction = np.mean([prediction[(a, seed, 'main')] for seed in (SEED, 20260920, 20260921)], axis=0)
                if source == 'notice': mean_prediction = mean_prediction.astype('float32')
                d[a] = _daily(panel, mean_prediction)[1]
            result = scoring.registered_daily_inference(d, days, source, scoring_permit, panel_identity)
            result['analysis_role'] = 'SECONDARY_THREE_SEED_EQUAL_PREDICTION_MEAN'
            _write_inference(scoring_root / (source + '__THREE_SEED_MEAN.json'), result)
            three_seed = result
        signs = [np.sign(r['dm_p1']['mean_difference']) if r['dm_p1']['mean_difference'] is not None else 0 for r in primary['reports']]
        unstable = any(x != 0 and y != 0 and x != y for values in seed_signs.values() for x, y in zip(signs, values))
        seed_state = 'EXTRA_SEEDS_NOT_AVAILABLE' if not seed_signs else ('SEED_DIRECTION_INSTABILITY' if unstable else 'NO_OBSERVED_SEED_SIGN_REVERSAL')
        # 24-hour windows use unchanged N; first-L compares registered changed
        # embeddings to the same main activity reference and matched truth.
        for variant, arms in ([('24h', ['M', 'L_count', 'L_chen']), ('first_L', ['L_chen', 'E_raw'])] if source == 'news' else [('first_L', ['L_chen_notice'])]):
            available = [a for a in arms if (a, SEED, variant) in prediction]
            if not available:
                sensitivities.append({'name': variant, 'state': 'NOT_EVALUABLE_WHOLE_STAGE_UNAVAILABLE'}); continue
            ref = 'M' if source == 'news' else 'M_notice'
            d = {a: _daily(panel, prediction[(a, SEED, variant)])[1] for a in available}
            if ref not in d: d[ref] = daily[ref]
            pairs = [(a, ref) for a in available if a != ref]
            if variant == '24h': d['N'] = daily['N']; pairs.append(('M', 'N'))
            result = scoring.secondary_daily_inference(d, pairs, days, scoring_permit)
            result['analysis_role'] = 'PRESPECIFIED_SENSITIVITY'; result['variant'] = variant
            _write_inference(scoring_root / f'{source}__{variant}.json', result)
            sensitivities.append({'name': variant, 'state': 'COMPUTED_SECONDARY'})
        if source == 'notice':
            mask = panel['target_day'].ge('2026-08-08').to_numpy()
            subset_days = list(pd.date_range('2026-08-08', '2026-09-30').strftime('%Y-%m-%d'))
            result = scoring.secondary_daily_inference({a: _daily(panel, p, mask)[1] for a, p in base.items()}, family, subset_days, scoring_permit)
            result['analysis_role'] = 'FIRST_SEVEN_TARGET_DAYS_EXCLUSION_NO_REFIT'
            _write_inference(scoring_root / 'notice__DROP_FIRST_SEVEN_DAYS.json', result)
        # CONFX5: CONF-A1 declared sensitivities and reporting rules (decisions 2, 3, 6, 9, 10).
        a1_primary[source] = primary['reports']
        a1_tasks[source] = _a1_task(source, panel, days, prediction, raw, primary, three_seed, seed_results,
                                    scoring, scoring_permit, panel_identity, scoring_root,
                                    _stage_reasons_for(seal_receipt, source))
        # Region/horizon summaries remain descriptive (no rescued primary tests).
        breakdown = []
        for arm, values in daily.items():
            pred = prediction[(arm, SEED, 'main')]
            work = panel[['target_day', 'region', 'horizon']].copy(); work['loss'] = np.abs(pred - panel['y'].to_numpy())
            for (region, horizon), group in work.groupby(['region', 'horizon'], sort=True):
                breakdown.append({'arm': arm, 'region': region, 'horizon': horizon, 'rows': len(group), 'mae': float(group['loss'].mean()), 'analysis_role': 'DESCRIPTIVE_ONLY'})
        pd.DataFrame(breakdown).to_csv(scoring_root / (source + '__REGION_HORIZON_MAE.csv'), index=False)
        summaries[source] = {'primary_path': str(primary_path), 'secondary': secondary, 'sensitivities': sensitivities,
                            'seed_robustness': seed_state, 'main_seed': SEED, 'family_size': len(family),
                            'pooled_mae': {a: float(v.mean()) for a, v in daily.items()}}
        if source == 'news':
            naive = panel['weekly_naive'].to_numpy() if 'weekly_naive' in panel else np.full(len(panel), np.nan)
            if np.isfinite(naive).all():
                denominator = float(np.abs(naive - panel['y'].to_numpy()).mean())
                summaries[source]['weekly_naive'] = {'state': 'COMPLETE' if denominator > 0 else 'UNDEFINED_ZERO_REFERENCE_MAE',
                    'mae': denominator, 'rmae': {a: float(v.mean()) / denominator if denominator > 0 else None for a, v in daily.items()}}
            else:
                summaries[source]['weekly_naive'] = {'state': 'UNAVAILABLE_LEGAL_WEEKLY_NAIVE', 'missing_keys': int((~np.isfinite(naive)).sum())}
        if source == 'notice':
            e3 = [r for r in secondary if (r['arm'], r['reference']) in [('NPL', 'NP'), ('NPL', 'NPP')]]
            if len(e3) != 2 or any(r['state'] != 'COMPUTED_SECONDARY' or r['p_two_sided'] is None for r in e3):
                summaries[source]['e3_joint_state'] = 'E3_SECONDARY_JOINT_NOT_EVALUABLE'
            else:
                summaries[source]['e3_joint_state'] = 'E3_SECONDARY_JOINT_CONFIRMED' if all(r['daily_mean_difference'] < 0 and r['p_two_sided'] < .05 for r in e3) else 'E3_SECONDARY_JOINT_NOT_CONFIRMED'
            # CONFX5: the NPL-NPP slot above was evaluated on the shift-supported days only.
            summaries[source]['e3_joint_day_rule'] = a1.E3_DAY_RULE
        # Connected severe events read prices only after every prediction seal.
        price_path = manifest.get('canonical_price_path', manifest.get('raw_price_path'))
        if not price_path: raise ValueError('Frozen canonical all-five-region price identity missing')
        audit(price_path, 'authorized_postseal_outcome_read', 'frozen descriptive severe connected events')
        prices = pd.read_parquet(price_path, columns=['region', 'event_time', 'price'])
        events, event_summary = severe_events(prices, panel, {a: prediction[(a, SEED, 'main')] for a in daily}, source,
                                              {'P_content': matched})
        events.to_csv(scoring_root / (source + '__CONNECTED_SEVERE_EVENTS.csv'), index=False)
        summaries[source]['severe_events'] = event_summary
    # 2025 remains report-only and cannot select a representation or parameter.
    validation = []
    for ident in seal_receipt['predictions']:
        if ident['variant'] != '2025_fixed_validation': continue
        panel = normalize(pd.read_parquet(seal_receipt['truth_panels']['news']['path'], columns=KEYS + ['target_day', 'y']))
        panel = panel.loc[panel['target_day'].between('2025-01-01', '2025-12-31')].reset_index(drop=True)
        pred = normalize(pd.read_parquet(ident['path']))
        if not pred[KEYS].equals(panel[KEYS]): raise ValueError('Report-only 2025 fixed validation key mismatch')
        validation.append({'arm': ident['arm'], 'mae': float(np.abs(pred['prediction'].to_numpy() - panel['y'].to_numpy()).mean()), 'rows': len(panel), 'role': 'REPORT_ONLY_NO_SELECTION'})
    summaries['validation_2025'] = validation
    summaries['stage_dispositions'] = seal_receipt['stage_dispositions']
    summaries['coverage_flow_files'] = seal_receipt['coverage_and_matched_masks']
    summaries['seal_sha256'] = sha256(root / 'SEAL.json'); summaries['state'] = 'FROZEN_SCORE_COMPLETE'
    summaries['inference_limits'] = 'Historical conditional design; asymptotic covariance-stationarity DM assumptions; 214/61 days shorter than Lago test-year recommendation; nominal fixed-prediction intervals; no equivalence or mechanism identification.'
    # CONFX5: CONF-A1 additions are reported beside, never in place of, the frozen readings.
    summaries['A1'] = _a1_summary(manifest, a1_tasks, a1_primary, seal_receipt)
    atomic_json(scoring_root / 'SCORE_REPORT.json', _json_result(summaries))
    lines += [summaries['inference_limits'], 'All optional stage omissions and resource failures are retained in SCORE_REPORT.json; partial predictions are not scored.']
    write_host_report(scoring_root, summaries)
    outputs = [file_identity(p) for p in sorted(scoring_root.iterdir()) if p.is_file() and p.name != 'SCORE_RECEIPT.json']
    atomic_json(scoring_root / 'SCORE_RECEIPT.json', {'state': 'FROZEN_SCORE_COMPLETE', 'seal_sha256': summaries['seal_sha256'], 'files': outputs})
    return summaries
