'Compare prediction arrays and save their forecast hashes.'
import hashlib
import os
from pathlib import Path
import re
import tempfile
import numpy as np
import pandas as pd
from common import *

AFFECTED = ('L14', 'L_Laz')
D_ROWS = 527040
AD_CHANGED_ROWS = {'L14': 29310, 'L_Laz': 3456}
VALUE_DTYPES = {'prediction': 'float32', 'raw_prediction': 'float64',
                'lower_bound': 'float64', 'upper_bound': 'float64'}

def _base_identity(item):
    return {key: item[key] for key in ('path', 'bytes', 'sha256')}

def build_production_support_binding(ad_inputs):

    by_path = {str(Path(item['path']).resolve()): item for item in ad_inputs}
    def named(name):
        path = (AD/name).resolve()
        require(str(path) in by_path, 'Missing bound completed AD input: '+name)
        return _base_identity(by_path[str(path)])
    manifest_identity, result_identity = named('OUTPUT_MANIFEST.json'), named('RESULT.json')
    manifest = read_json(checked(manifest_identity))
    result = read_json(checked(result_identity))
    require(manifest.get('state') == 'COMPLETE' and
            result.get('state') == 'COMPLETE_SOURCE_ONLY_BLINDED_DIAGNOSTIC' and
            bool(result.get('completed_utc')), 'Completed AD support required')
    files = manifest.get('files', [])
    require(isinstance(files, list), 'Invalid AD completed manifest')
    def manifested(name):
        matches = [item for item in files if item.get('path') == name]
        require(len(matches) == 1, 'AD manifest identity census invalid: '+name)
        bound = named(name); item = matches[0]
        require(bound['bytes'] == item.get('bytes') and bound['sha256'] == item.get('sha256'),
                'AD manifest changed-key/result identity drift')
        checked(bound)
        return bound
    manifested('RESULT.json')
    diff = result['D_feature_diff']; laz = result['Laz_feature_diff']
    require(diff.get('state') == 'COMPLETE' and laz.get('state') == 'COMPLETE' and
            diff['key_panel']['rows'] == D_ROWS and laz['D_keys'] == D_ROWS,
            'AD complete full D grid required')
    actual = {'L14': diff['families']['L14']['D_rows_any_difference'],
              'L_Laz': laz['D_rows_any_difference']}
    require(actual == AD_CHANGED_ROWS, 'Completed AD changed-key counts drift')
    arms = {arm: dict(changed_rows=AD_CHANGED_ROWS[arm],
                       untouched_rows=D_ROWS-AD_CHANGED_ROWS[arm],
                       changed_keys=manifested(arm+'_changed_keys.parquet')) for arm in AFFECTED}
    return dict(state='COMPLETED_AD_EXACT_D_SUPPORT', synthetic_only=False,
                affected_arms=list(AFFECTED), grid_rows=D_ROWS, arms=arms,
                ad_result=result_identity, ad_manifest=manifest_identity)

def synthetic_support_binding(panel, affected, changed_keys, root):

    root = Path(root).resolve()
    require(root.is_relative_to(Path('/private/tmp')), 'Synthetic support must be under /private/tmp')
    root.mkdir(parents=True, exist_ok=True)
    panel = dly_module().normalize(panel)
    require(len(panel) > 0 and not panel.duplicated(KEYS).any(), 'Synthetic support grid invalid')
    arms = {}
    for arm in affected:
        keys = _changed_frame(changed_keys(arm)); mask = touched_mask(panel, keys)
        require(0 < int(mask.sum()) < len(panel), 'Synthetic changed/untouched support must be nonempty')
        path = root/(arm+'_synthetic_changed_keys.parquet')
        publish_parquet_exclusive(keys, path)
        arms[arm] = dict(changed_rows=int(mask.sum()), untouched_rows=int((~mask).sum()),
                         changed_keys=identity(path, synthetic_only=True))
    return dict(state='EXPLICIT_SYNTHETIC_FIXTURE_SUPPORT', synthetic_only=True,
                affected_arms=list(affected), grid_rows=len(panel), arms=arms,
                grid_keys=key_identity(panel))

def _support(binding, affected=None, *, synthetic=False):
    value = binding.get('support')
    require(isinstance(value, dict), 'Explicit exact support binding required')
    require(value.get('synthetic_only') is synthetic, 'Synthetic/production support input_checks drift')
    if synthetic:
        require(binding.get('synthetic_only') is True and
                value.get('state') == 'EXPLICIT_SYNTHETIC_FIXTURE_SUPPORT',
                'Explicit labelled synthetic binding required')
        arms = value.get('affected_arms', [])
        require(arms and len(arms) == len(set(arms)) and set(arms) <= set(AFFECTED),
                'Synthetic affected arm census invalid')
    else:
        require(binding.get('synthetic_only', False) is False and
                value == build_production_support_binding(binding['ad_inputs']),
                'Production support does not match completed AD')
        arms = list(AFFECTED)
    require(affected is None or list(affected) == arms, 'Exact affected primary arm census required')
    rows = value.get('grid_rows')
    require(type(rows) is int and rows > 0 and set(value.get('arms', {})) == set(arms),
            'Full grid support census invalid')
    for arm in arms:
        info = value['arms'][arm]; count = info.get('changed_rows')
        require(type(count) is int and 0 < count < rows and
                info.get('untouched_rows') == rows-count,
                'Changed/untouched support must be exact and nonempty')
        path = checked(info['changed_keys'])
        if synthetic:
            require(path.is_relative_to(Path('/private/tmp')) and
                    info['changed_keys'].get('synthetic_only') is True,
                    'Synthetic changed keys must remain fixture-only')
    return value

def key_identity(frame):

    keys = frame[KEYS].copy()
    for col in ('origin', 'target_time'):
        keys[col] = pd.to_datetime(keys[col], utc=True).astype('datetime64[ns, UTC]')
    keys['horizon'] = keys.horizon.astype('int64')
    rows = pd.util.hash_pandas_object(keys, index=False).to_numpy(dtype='uint64')
    return dict(rows=len(keys), sha256=hashlib.sha256(rows.tobytes()).hexdigest(),
                algorithm='pandas-normalized-key-row-hash-uint64-sha256')

def validate_grid(panel, support):
    require(len(panel) == support['grid_rows'] and not panel.duplicated(KEYS).any(),
            'Exact complete D grid/key uniqueness required')
    require(panel[KEYS+['target_day']].notna().all().all(), 'D grid contains null keys/day')
    if support['synthetic_only']:
        require(key_identity(panel) == support['grid_keys'], 'Synthetic full-grid identity drift')
        return
    require(len(panel) == D_ROWS, 'Production complete D grid must have 527040 rows')
    target = pd.to_datetime(panel.target_time, utc=True).astype('datetime64[ns, UTC]')
    origin = pd.to_datetime(panel.origin, utc=True).astype('datetime64[ns, UTC]')
    lo = pd.Timestamp('2026-08-01', tz='Australia/Brisbane').tz_convert('UTC')
    hi = pd.Timestamp('2026-10-01', tz='Australia/Brisbane').tz_convert('UTC')
    require(target.ge(lo).all() and target.lt(hi).all() and
            ((target.astype('int64')-lo.value) % (5*60*10**9) == 0).all(),
            'Exact D five-minute target grid required')
    require(panel.region.isin(('NSW1','QLD1','SA1','TAS1','VIC1')).all() and
            panel.horizon.isin((5,10,15,20,25,30)).all() and
            ((target-origin).dt.total_seconds() == panel.horizon*60).all(),
            'Exact D region/horizon/origin grid required')
    require(panel.target_day.astype(str).equals(target.dt.tz_convert('Australia/Brisbane').dt.strftime('%Y-%m-%d')),
            'D target-day identity drift')


def _changed_frame(frame):
    frame = frame.rename(columns={'issue_time':'origin'})
    require(set(KEYS) <= set(frame.columns) and not frame.columns.duplicated().any(),
            'AD changed-key schema invalid')
    changed = frame[KEYS].copy()
    for col in ('origin','target_time'):
        changed[col] = pd.to_datetime(changed[col], utc=True).astype('datetime64[ns, UTC]')
    return changed

def publish_parquet_exclusive(frame, path):

    import pyarrow.parquet as pq
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name+'.', suffix='.publication.tmp', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            frame.to_parquet(stream, index=False)
            stream.flush(); os.fsync(stream.fileno())
        produced = identity(temp)
        require(produced['bytes'] > 0 and pq.ParquetFile(temp).metadata.num_rows == len(frame),
                'Incomplete corrected parquet publication')
        checked(produced)
        reference_snapshot = temp.stat()

        os.link(temp, path)
        after = path.stat()
        require((reference_snapshot.st_dev, reference_snapshot.st_ino) == (after.st_dev, after.st_ino) and
                identity(path)['sha256'] == produced['sha256'], 'Parquet publication identity drift')
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except FileExistsError as exc:
        raise FileExistsError('Preserve existing corrected file; complete publication evidence: '+str(temp)) from exc
    except BaseException:

        raise
    else:
        temp.unlink()
        return identity(path)

def value_identity(array):
    array = np.ascontiguousarray(array)
    return dict(dtype=str(array.dtype), shape=list(array.shape), sha256=hashlib.sha256(array.tobytes()).hexdigest())

def key_index(frame):
    return pd.MultiIndex.from_frame(frame[KEYS])

def touched_mask(panel, changed_keys):
    changed = _changed_frame(changed_keys)
    require(not changed.duplicated(KEYS).any(), 'Duplicate AD changed keys')
    require(key_index(changed).isin(key_index(panel)).all(), 'AD changed key outside D grid')
    return key_index(panel).isin(key_index(changed))

def parity(candidate, reference, mask=None):
    dly = dly_module()
    a, b = dly.normalize(candidate), dly.normalize(reference)
    require(a.columns.tolist() == b.columns.tolist(), 'Prediction schema drift')
    require(a[KEYS+['target_day']].equals(b[KEYS+['target_day']]), 'Prediction keys/order drift')
    mask = np.ones(len(a), dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
    require(mask.shape == (len(a),), 'Parity mask length drift')
    require(int(mask.sum()) > 0, 'Prediction parity support is empty')
    columns = {}
    for col in VALUES:
        require(col in a, 'Missing prediction parity column')
        aa, bb = a[col].to_numpy()[mask], b[col].to_numpy()[mask]
        equal = dly.bytes_equal(aa, bb)
        columns[col] = dict(byte_equal=equal, recomputed=value_identity(aa), sealed=value_identity(bb))
    require(all(row['byte_equal'] for row in columns.values()), 'Prediction byte parity failed')
    return dict(state='PASS', rows=int(mask.sum()), keys_equal=True, columns=columns,
                support_keys=key_identity(a.loc[mask, KEYS]))

def feature_parity(matrix, expected, allowed=None):
    require(matrix.ndim == 2 and matrix.shape[0] > 0 and matrix.shape[1] > 0,
            'Frozen feature support shape invalid')
    allowed = np.zeros(len(matrix), dtype=bool) if allowed is None else np.asarray(allowed, dtype=bool)
    require(allowed.shape == (len(matrix),), 'Feature mask length drift')
    support_rows = int((~allowed).sum())
    require(support_rows > 0, 'Feature parity support is empty')
    digest_a, digest_b = hashlib.sha256(), hashlib.sha256()
    changed_rows = 0
    for start in range(0, len(matrix), 2048):
        end = min(start+2048, len(matrix))
        a, b = np.asarray(matrix[start:end]), expected(slice(start,end))
        require(a.dtype == b.dtype == np.float32 and a.shape == b.shape, 'Frozen feature order/dtype drift')

        different = (a.view(np.uint32) != b.view(np.uint32)).any(axis=1)
        require(not (different & ~allowed[start:end]).any(), 'Feature changed outside AD touched rows')
        changed_rows += int(different.sum())
        mask = ~allowed[start:end]
        digest_a.update(np.ascontiguousarray(a[mask]).tobytes())
        digest_b.update(np.ascontiguousarray(b[mask]).tobytes())
    require(digest_a.hexdigest() == digest_b.hexdigest(), 'Untouched feature hash mismatch')
    return dict(state='PASS', untouched_byte_equal=True, untouched_rows=int((~allowed).sum()),
                retained_feature_changed_rows=changed_rows, recomputed_sha256=digest_a.hexdigest(),
                sealed_sha256=digest_b.hexdigest(),
                recomputed=dict(dtype='float32', shape=[support_rows, matrix.shape[1]], sha256=digest_a.hexdigest()),
                sealed=dict(dtype='float32', shape=[support_rows, matrix.shape[1]], sha256=digest_b.hexdigest()))

def touched_counts(panel, mask):
    f = panel.loc[mask]
    hour = pd.to_datetime(f.origin, utc=True).dt.tz_convert('Australia/Brisbane').dt.strftime('%Y-%m-%d %H')
    return dict(rows=len(f), regions=f.region.value_counts().sort_index().astype(int).to_dict(),
                origin_hours_aest=hour.value_counts().sort_index().astype(int).to_dict())

def run_set(root, panel, affected, sealed, reference, expected, rebuild, predict, changed_keys, binding,
            checkpoint=lambda:None):

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    synthetic = binding.get('synthetic_only') is True
    support = _support(binding, affected, synthetic=synthetic)
    require(set(sealed) == set(PRIMARY), 'Five primary identity census required')
    dly = dly_module(); panel = dly.normalize(panel)
    validate_grid(panel, support)
    checks, outputs = {}, {}
    for arm in PRIMARY:
        if arm not in affected:
            checked(sealed[arm])
            outputs[arm] = dict(mode='REUSE_BY_IDENTITY', identity=sealed[arm])
            checks[arm] = dict(state='REUSE_BY_IDENTITY', rebuilt=False, identity_equal=True)
            continue
        checkpoint()
        ref = dly.normalize(reference(arm))
        require(ref[KEYS+['target_day']].equals(panel[KEYS+['target_day']]), 'D reference grid drift')
        keys = _changed_frame(changed_keys(arm)); mask = touched_mask(panel, keys)
        arm_support = support['arms'][arm]
        require(len(keys) == int(mask.sum()) == arm_support['changed_rows'] and
                int((~mask).sum()) == arm_support['untouched_rows'] > 0,
                'AD changed-key count/nonempty complement drift')
        bound_keys = _changed_frame(pd.read_parquet(checked(arm_support['changed_keys'])))
        require(key_index(keys).equals(key_index(bound_keys)), 'AD exact changed-key identity drift')
        matrices = []
        try:
            baseline = rebuild(arm, False, root/(arm+'_specified'))
            matrices.append(baseline)
            require(len(baseline) == len(panel), 'Specified feature full-grid row drift')
            zero = feature_parity(baseline, lambda ids:expected(arm,ids))
            baseline_predictions = predict(arm,baseline)
            zero_predictions = parity(baseline_predictions,ref)
            checkpoint()
            if isinstance(baseline,np.memmap):
                baseline._mmap.close()
            aligned = rebuild(arm, True, root/(arm+'_corrected'))
            matrices.append(aligned)
            require(aligned.shape == baseline.shape, 'Corrected feature full-grid shape drift')
            feature_check = feature_parity(aligned, lambda ids:expected(arm,ids), mask)
            corrected_predictions = predict(arm,aligned)
            outside = parity(corrected_predictions,ref,~mask)
            counts = touched_counts(panel,mask)
            path = root/(arm+'__corrected_D.parquet')
            publish_parquet_exclusive(dly.normalize(corrected_predictions), path)
            outputs[arm] = dict(mode='CORRECTED_D_SUBSTITUTION', identity=identity(path,source='notice',arm=arm,
                                seed=SEED,variant='main',rows=len(panel),window='D'),specified_identity=sealed[arm])
            checks[arm] = dict(state='PASS', specified_full_features=zero, specified_full_predictions=zero_predictions,
                              corrected_untouched_features=feature_check, corrected_untouched_predictions=outside,
                              touched=counts, changed_keys=arm_support['changed_keys'],
                              changed_key_support=key_identity(keys),
                              full_grid_keys=key_identity(panel),
                              untouched_keys=key_identity(panel.loc[~mask]), values_printed=False)
            checkpoint()
        finally:
            for matrix in matrices:
                if isinstance(matrix,np.memmap) and not matrix._mmap.closed:
                    matrix.flush(); matrix._mmap.close()
    receipt = root/'PARITY_FORECAST_BINDING.json'
    write_json(receipt, dict(state='PASS', binding=binding, arms=checks, affected_arms=list(affected),
                            affected_arm_count=len(affected), support=support,
                            models_refitted=0,outcomes_read=False,values_printed=False))
    view = root/'PREDICTION_VIEW.json'
    write_json(view,dict(state='CORRECTED_PRIMARY_NOTICE_D_VIEW', source='notice',seed=SEED,variant='main',
                        window='D',arms=outputs, parity=identity(receipt),specified_outside_D='REUSE_BY_IDENTITY',
                        corrected_secondary_families=False))
    return dict(parity=identity(receipt),prediction_view=identity(view),predictions=outputs)

def _valid_key_identity(item, rows):
    require(isinstance(item, dict) and item.get('rows') == rows and
            item.get('algorithm') == 'pandas-normalized-key-row-hash-uint64-sha256' and
            re.fullmatch(r'[0-9a-f]{64}', str(item.get('sha256'))) is not None,
            'Incomplete parity key support identity')

def _array_receipt(item, dtype, shape):
    require(isinstance(item, dict) and set(item) == {'dtype','shape','sha256'} and
            item.get('dtype') == dtype and item.get('shape') == shape and
            all(type(n) is int and n > 0 for n in item.get('shape', [])) and
            re.fullmatch(r'[0-9a-f]{64}', str(item.get('sha256'))) is not None,
            'Incomplete parity dtype/shape/hash identity')

def _prediction_receipt(value, rows, keys):
    require(isinstance(value, dict) and value.get('state') == 'PASS' and
            value.get('rows') == rows > 0 and value.get('keys_equal') is True and
            set(value.get('columns', {})) == set(VALUES), 'Incomplete prediction parity support/fields')
    _valid_key_identity(value.get('support_keys'), rows)
    require(value['support_keys'] == keys, 'Prediction exact support key drift')
    for name in VALUES:
        column = value['columns'][name]
        require(column.get('byte_equal') is True, 'Incomplete prediction byte parity')
        for side in ('recomputed', 'sealed'):
            _array_receipt(column.get(side), VALUE_DTYPES[name], [rows])
        require(column['recomputed'] == column['sealed'], 'Prediction parity dtype/shape/hash drift')

def _feature_receipt(value, rows):
    require(isinstance(value, dict) and value.get('state') == 'PASS' and
            value.get('untouched_byte_equal') is True and value.get('untouched_rows') == rows > 0,
            'Incomplete feature parity support')
    shape = value.get('recomputed', {}).get('shape')
    require(isinstance(shape, list) and len(shape) == 2 and shape[0] == rows and
            type(shape[1]) is int and shape[1] > 0, 'Incomplete feature parity shape')
    for side in ('recomputed', 'sealed'):
        _array_receipt(value.get(side), 'float32', shape)
        require(value.get(side+'_sha256') == value[side]['sha256'], 'Feature digest alias drift')
    require(value['recomputed'] == value['sealed'], 'Feature parity dtype/shape/hash drift')
    return shape[1]

def _validate_result(result, binding, *, synthetic):

    support = _support(binding, synthetic=synthetic)
    receipt = read_json(checked(result['parity']))
    view = read_json(checked(result['prediction_view']))
    require(receipt.get('state') == 'PASS' and receipt.get('binding') == binding and
            receipt.get('support') == support, 'Parity/binding failed')
    arms = support['affected_arms']; rows = support['grid_rows']
    require(receipt.get('affected_arms') == arms and receipt.get('affected_arm_count') == len(arms) and
            set(receipt.get('arms', {})) == set(PRIMARY), 'Exact affected parity arm census drift')
    require(set(result['predictions']) == set(PRIMARY) and view['arms'] == result['predictions'], 'View census drift')
    require(view.get('parity') == result['parity'] and
            view.get('state') == 'CORRECTED_PRIMARY_NOTICE_D_VIEW' and
            view.get('source') == 'notice' and view.get('seed') == SEED and
            view.get('variant') == 'main' and view.get('window') == 'D' and
            view.get('specified_outside_D') == 'REUSE_BY_IDENTITY' and
            view.get('corrected_secondary_families') is False, 'Prediction view scope drift')
    require(set(binding) >= {'main_conf_seal','batch_seal','code_freeze','models','patch','ad_inputs','activation'}, 'Incomplete seal binding')
    grid_keys = None
    for arm,row in result['predictions'].items():
        checked(row['identity'])
        check = receipt['arms'][arm]
        if arm in arms:
            require(row.get('mode') == 'CORRECTED_D_SUBSTITUTION' and check.get('state') == 'PASS',
                    'Missing affected arm parity')
            checked(row['specified_identity'])
            require(row['identity'].get('rows') == rows and row['identity'].get('arm') == arm and
                    row['identity'].get('window') == 'D' and row['identity'].get('seed') == SEED and
                    row['identity'].get('variant') == 'main', 'Corrected identity full-grid scope drift')
            info = support['arms'][arm]; touched = check.get('touched', {})
            require(check.get('changed_keys') == info['changed_keys'], 'Parity AD changed-key identity drift')
            bound_keys = _changed_frame(pd.read_parquet(checked(info['changed_keys'])))
            require(len(bound_keys) == info['changed_rows'] and not bound_keys.duplicated(KEYS).any() and
                    check.get('changed_key_support') == key_identity(bound_keys), 'Parity AD exact key support drift')
            require(touched.get('rows') == info['changed_rows'] and
                    all(type(n) is int and n > 0 for n in touched.get('regions', {}).values()) and
                    all(type(n) is int and n > 0 for n in touched.get('origin_hours_aest', {}).values()) and
                    sum(touched.get('regions', {}).values()) == info['changed_rows'] and
                    sum(touched.get('origin_hours_aest', {}).values()) == info['changed_rows'],
                    'Touched row count receipt drift')
            full_keys, untouched_keys = check.get('full_grid_keys'), check.get('untouched_keys')
            _valid_key_identity(full_keys, rows)
            _valid_key_identity(untouched_keys, info['untouched_rows'])
            if grid_keys is None:
                grid_keys = full_keys
            require(full_keys == grid_keys, 'Affected arm full-grid identity drift')
            if synthetic:
                require(full_keys == support['grid_keys'], 'Synthetic sealed grid identity drift')
            _prediction_receipt(check.get('specified_full_predictions'), rows, full_keys)
            _prediction_receipt(check.get('corrected_untouched_predictions'), info['untouched_rows'], untouched_keys)
            columns = _feature_receipt(check.get('specified_full_features'), rows)
            require(_feature_receipt(check.get('corrected_untouched_features'), info['untouched_rows']) == columns,
                    'Corrected retained feature column shape drift')
            require(check['specified_full_features'].get('retained_feature_changed_rows') == 0 and
                    type(check['corrected_untouched_features'].get('retained_feature_changed_rows')) is int and
                    0 <= check['corrected_untouched_features']['retained_feature_changed_rows'] <= info['changed_rows'] and
                    check.get('values_printed') is False, 'Feature change/count-only input_checks drift')
        else:
            require(row.get('mode') == 'REUSE_BY_IDENTITY' and check.get('state') == 'REUSE_BY_IDENTITY' and
                    check.get('identity_equal') is True and check.get('rebuilt') is False,
                    'Unaffected arm was rebuilt')
    for field in ('main_conf_seal','batch_seal','code_freeze','patch','activation'):
        checked(binding[field])
    for item in binding['models']+binding['ad_inputs']:
        checked(item)
    for item in binding.get('model_receipts',[]):
        checked(item)
    if binding.get('main_feature_manifest'):
        checked(binding['main_feature_manifest'])
    if not synthetic:
        from forecast_inputs import verify_dly8_binding, verify_runtime_root_binding
        require('dly8' in binding and 'runtime_roots' in binding, 'Missing exact DLY8/runtime root binding')
        verify_runtime_root_binding(binding['runtime_roots'])
        verify_dly8_binding(binding['dly8'])
    require(receipt.get('models_refitted') == 0 and receipt.get('outcomes_read') is False and
            receipt.get('values_printed') is False, 'Refit/outcome input_checks failed')
    return receipt, view

def write_seal(path, result, binding, synthetic=False):
    'Save forecast hashes after checking prediction parity for every requested delay.'
    _validate_result(result, binding, synthetic=synthetic)
    value = dict(state='FORECAST_BINDING_SEALED_BEFORE_T5',synthetic_only=synthetic,
                 sealed_before_outcome_scoring=True,binding=binding,**result,
                 models_refitted=0,seed=SEED,variant='main',window='D',scoring_run=False,
                 specified_main_seal_preserved=True)
    write_json(path,value)
    return value

def substitute_view(specified, aligned, *, arm):

    dly=dly_module(); original=dly.normalize(specified)
    if aligned is None:
        require(arm in PRIMARY, 'Unknown primary arm')
        return original
    replacement=dly.normalize(aligned)
    mask=original.target_day.between('2026-08-01','2026-09-30')
    require(original.loc[mask,KEYS+['target_day']].reset_index(drop=True).equals(replacement[KEYS+['target_day']]), 'Corrected view keys drift')
    require(original.columns.tolist()==replacement.columns.tolist(), 'Corrected view schema drift')
    for col in VALUES:
        require(original[col].dtype==replacement[col].dtype, 'Corrected view dtype drift')
        original.loc[mask,col]=replacement[col].to_numpy()
    return original

def verify_seal(path, *, allow_synthetic=False):
    'Check saved forecast hashes and prediction parity.'
    value=read_json(path)
    require(value['state']=='FORECAST_BINDING_SEALED_BEFORE_T5' and value['sealed_before_outcome_scoring'], 'Invalid corrected seal')
    require(allow_synthetic or not value['synthetic_only'], 'Synthetic seal cannot authorize production')
    require(value['models_refitted']==0 and value['seed']==SEED and value['variant']=='main' and value['window']=='D', 'Correction scope drift')
    require(type(value.get('synthetic_only')) is bool and value.get('scoring_run') is False and
            value.get('specified_main_seal_preserved') is True, 'Sealed scope/deviation input_checks drift')
    result = {field: value[field] for field in ('parity','prediction_view','predictions')}
    _validate_result(result, value['binding'], synthetic=value['synthetic_only'])
    return value
