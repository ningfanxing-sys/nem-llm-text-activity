'Build delayed notice features and forecasts with the frozen functions.'
from pathlib import Path
import numpy as np
import pandas as pd
import prediction_set as ps
import common

ARMS = ('L14', 'L_Laz')
DELAYS = (15, 60)
SCHEMA = 'FORECAST_BINDING_CORRECTED_DELAYS_V1'
PARITY_SCHEMA = 'FORECAST_BINDING_CORRECTED_DELAY_PARITY_V1'
VIEW_SCHEMA = 'FORECAST_BINDING_CORRECTED_DELAY_VIEW_V1'
DELTA_RULE = 'FROZEN_DLY8_DELTA_ADDED_TO_AVAILABLE_UTC_UNCHANGED'
SCOPE = dict(arms=list(ARMS), delta_minutes=list(DELAYS), seed=common.SEED,
             model_variant='main', models_refitted=0, window='D', delta_rule=DELTA_RULE)
require = common.require


def _synthetic(binding):
    return binding.get('synthetic_only') is True


def _scope(root, binding):
    root = Path(root).resolve()
    if _synthetic(binding):
        require(root.is_relative_to(Path('/private/tmp')),
                'Delay synthetic fixtures must remain under /private/tmp')
    else:
        require(root.is_relative_to(common.OUT), 'Corrected delay output escaped forecast_hashes')
    return root


def _family(binding):
    require(isinstance(binding, dict) and binding.get('schema') == 'FORECAST_BINDING_DLY8_TERMINALS_BOUND_V1',
            'Exact DLY8 terminal binding required for corrected delays')
    families = binding.get('families', [])
    require(isinstance(families, list) and len(families) == 2 and
            {row.get('mode') for row in families} == {1, 2}, 'Both DLY8 terminal families required')
    family = next(row for row in families if row['mode'] == 1)
    require(family.get('state') == 'ALL_DLY8_PREDICTIONS_SEALED',
            'Specified PRIMARY DLY8 readings are unavailable')
    require(family.get('source_seal') == binding.get('main_conf_seal'),
            'Specified DLY8 primary source seal drift')
    return family


def specified_delay_identities(dly_binding, *, synthetic=False, rows=None):

    family = _family(dly_binding)
    path = common.checked(family['receipt'])
    if synthetic:
        require(path.is_relative_to(Path('/private/tmp')) and type(rows) is int and rows > 0,
                'Explicit synthetic DLY8 support is required')
    else:
        require(rows in (None, ps.D_ROWS), 'Specified delay production support size drift')
        rows = ps.D_ROWS
    receipt = common.read_json(path)
    require(receipt.get('state') == family['state'] and receipt.get('arms') == list(common.PRIMARY) and
            receipt.get('delays_minutes') == [5, 15, 60] and receipt.get('models_refitted') == 0 and
            receipt.get('delta0_first') is True and receipt.get('training_rows_changed') is False and
            receipt.get('outcomes_read') is False and
            receipt.get('binding', {}).get('main_conf_seal') == dly_binding.get('main_conf_seal') and
            receipt.get('binding', {}).get('source_seal') == family['source_seal'],
            'Specified delayed receipt scope/parent drift')
    items = receipt.get('predictions', [])
    expected = {(arm, delta) for delta in (5, *DELAYS) for arm in common.PRIMARY}
    census = [(item.get('arm'), item.get('delta_minutes')) for item in items]
    require(len(items) == len(expected) and set(census) == expected and
            len({item.get('path') for item in items}) == len(expected),
            'Specified delayed prediction census drift')
    for item in items:
        require(item.get('source') == 'notice' and item.get('seed') == common.SEED and
                item.get('variant') == 'delay'+str(item['delta_minutes']) and item.get('rows') == rows,
                'Specified delayed identity scope drift')
        p = common.checked(item)
        if synthetic:
            require(p.is_relative_to(Path('/private/tmp')), 'Synthetic delayed identity escaped fixture')
    return {str(delta): {arm: next(item for item in items
                                  if (item['arm'], item['delta_minutes']) == (arm, delta))
                        for arm in common.PRIMARY} for delta in DELAYS}


def _validate_models(binding):
    family = _family(binding['dly8'])
    receipt = common.read_json(common.checked(family['receipt']))
    models = receipt.get('binding', {}).get('models', [])
    wanted = binding.get('models', [])
    require(isinstance(wanted, list) and len(wanted) == len(ARMS) and
            len({item.get('path') for item in wanted}) == len(ARMS) and
            all(item in models for item in wanted), 'Corrected delayed models differ from specified models')
    for item in wanted:
        common.checked(item)


def _validate_authority(binding, *, synthetic):
    require(binding.get('delay_scope') == SCOPE, 'Corrected delayed computation scope drift')
    if synthetic:
        require(binding.get('synthetic_only') is True and
                isinstance(binding.get('delay_authority'), dict) and
                binding['delay_authority'].get('synthetic_only') is True,
                'Explicit synthetic delayed timestamp_checks required')
    else:
        from delay_freeze import verify_delay_release
        require(binding.get('delay_authority') == verify_delay_release(),
                'Corrected delayed source/decision release identity drift')


def _matrix_scope(matrix, panel, shape=None):
    require(isinstance(matrix, np.ndarray) and matrix.dtype == np.float32 and matrix.ndim == 2 and
            matrix.shape[0] == len(panel) and matrix.shape[1] > 0 and
            (shape is None or matrix.shape == shape), 'Delayed feature dtype/shape/order drift')


def _changed_rows(a, b):

    changed = np.zeros(len(a), dtype=bool)
    for start in range(0, len(a), 2048):
        end = min(len(a), start+2048)
        left = np.ascontiguousarray(a[start:end]).view(np.uint32)
        right = np.ascontiguousarray(b[start:end]).view(np.uint32)
        changed[start:end] = (left != right).any(axis=1)
    return changed


def _close(matrix):
    if isinstance(matrix, np.memmap) and not matrix._mmap.closed:
        matrix.flush()
        matrix._mmap.close()


def _retire(matrix):

    if isinstance(matrix, np.memmap):
        filename = Path(matrix.filename).resolve()
        require(filename.is_relative_to(Path('/private/tmp')),
                'Retained delayed matrix must be transient private scratch')
        _close(matrix)
        if filename.exists():
            filename.unlink()


def _feature_identity(matrix):
    import hashlib
    digest = hashlib.sha256()
    for start in range(0, len(matrix), 2048):
        digest.update(np.ascontiguousarray(matrix[start:start+2048]).tobytes())
    return dict(dtype='float32', shape=list(matrix.shape), sha256=digest.hexdigest())


def _require_grid(frame, panel):
    require(not frame.duplicated(common.KEYS).any() and
            frame[common.KEYS+['target_day']].equals(panel[common.KEYS+['target_day']]),
            'Corrected delayed reading full D keys/order drift')


def run_delay_set(root, panel, specified, rebuild, predict, reference, binding,
                  checkpoint=lambda: None):
    'Rebuild and compare delayed feature matrices before predicting with saved models.'
    root = _scope(root, binding)
    require(list(binding.get('support', {}).get('affected_arms', [])) == list(ARMS),
            'Corrected delays require both affected primary arms exactly')
    panel = common.dly_module().normalize(panel)
    ps.validate_grid(panel, ps._support(binding, list(ARMS), synthetic=_synthetic(binding)))
    rows = len(panel)
    expected = specified_delay_identities(binding['dly8'], synthetic=_synthetic(binding), rows=rows)
    require(specified == expected, 'Specified delayed reference identities drift')
    _validate_authority(binding, synthetic=_synthetic(binding))
    _validate_models(binding)
    root.mkdir(parents=True, exist_ok=True)
    outputs, checks, coverage = {}, {}, {}
    grid_keys = ps.key_identity(panel)
    for delta in DELAYS:
        name = str(delta)
        outputs[name], checks[name], coverage[name] = {}, {}, {}
        for arm in common.PRIMARY:
            source = specified[name][arm]
            if arm not in ARMS:
                outputs[name][arm] = dict(mode='REUSE_BY_IDENTITY', identity=source)
                checks[name][arm] = dict(state='REUSE_BY_IDENTITY', rebuilt=False, identity_equal=True)
                coverage[name][arm] = dict(rows=rows, specified_identity=source,
                                           mode='SPECIFIED_DLY8_REUSE_BY_IDENTITY')
                continue
            checkpoint()
            ref = common.dly_module().normalize(reference(arm, delta))
            _require_grid(ref, panel)
            baseline = aligned = None
            try:
                baseline = rebuild(arm, False, delta, root/(arm+'__delta'+name+'__specified'))
                _matrix_scope(baseline, panel)
                baseline_feature_identity = _feature_identity(baseline)
                baseline_prediction = common.dly_module().normalize(predict(arm, baseline))
                _require_grid(baseline_prediction, panel)
                full_prediction = ps.parity(baseline_prediction, ref)
                checkpoint()
                aligned = rebuild(arm, True, delta, root/(arm+'__delta'+name+'__corrected'))
                _matrix_scope(aligned, panel, baseline.shape)
                require(_feature_identity(baseline) == baseline_feature_identity,
                        'Retained specified delayed feature matrix changed during corrected rebuild')
                if isinstance(baseline, np.memmap) and isinstance(aligned, np.memmap):
                    require(Path(baseline.filename).resolve() != Path(aligned.filename).resolve(),
                            'Specified and corrected delayed matrices must have distinct scratch files')
                changed = _changed_rows(baseline, aligned)
                require(int((~changed).sum()) > 0, 'Delayed untouched parity support is empty')
                untouched_feature = ps.feature_parity(aligned, lambda ids: baseline[ids], changed)
                corrected_prediction = common.dly_module().normalize(predict(arm, aligned))
                _require_grid(corrected_prediction, panel)
                untouched_prediction = ps.parity(corrected_prediction, ref, ~changed)
                counts = ps.touched_counts(panel, changed)
                file = root/(arm+'__corrected_D__delay'+name+'.parquet')
                ps.publish_parquet_exclusive(corrected_prediction, file)
                corrected_identity = common.identity(file, source='notice', arm=arm, seed=common.SEED,
                    variant='delay'+name, delta_minutes=delta, rows=rows, window='D',
                    model_variant='main', anchor_reading='corrected_day_first')
                outputs[name][arm] = dict(mode='CORRECTED_DLY8_D_SUBSTITUTION', identity=corrected_identity,
                                         specified_identity=source)
                checks[name][arm] = dict(state='PASS', specified_rebuilt_feature_identity=baseline_feature_identity,
                    specified_full_predictions=full_prediction, corrected_untouched_features=untouched_feature,
                    corrected_untouched_predictions=untouched_prediction, touched=counts,
                    changed_key_support=ps.key_identity(panel.loc[changed]), full_grid_keys=grid_keys,
                    untouched_keys=ps.key_identity(panel.loc[~changed]),
                    support_rule='EXACT_RETAINED_FEATURE_BYTE_DIFFERENCES_AT_THIS_SPECIFIED_DELAY',
                    feature_rows_changed=int(changed.sum()), values_printed=False)
                coverage[name][arm] = dict(rows=rows, keys=grid_keys, specified_identity=source,
                    corrected_identity=corrected_identity, keys_equal=True, mode='EXACT_SPECIFIED_DLY8_D_KEYS')
                checkpoint()
            finally:
                _retire(baseline)
                _retire(aligned)
    receipt = root/'PARITY_FORECAST_BINDING_DELAYS.json'
    value = dict(schema=PARITY_SCHEMA, state='PASS', binding=binding, specified=specified,
                 arms=checks, affected_arms=list(ARMS), delta_minutes=list(DELAYS),
                 coverage=coverage, full_grid_keys=grid_keys, grid_rows=rows, models_refitted=0,
                 seed=common.SEED, model_variant='main', window='D', delta_rule=DELTA_RULE,
                 touched_support_recomputed_per_delay=True, outcomes_read=False, values_printed=False)
    common.write_json(receipt, value)
    view = root/'PREDICTION_VIEW_DELAYS.json'
    common.write_json(view, dict(schema=VIEW_SCHEMA, state='CORRECTED_PRIMARY_NOTICE_D_DELAY_VIEW',
        source='notice', seed=common.SEED, model_variant='main', window='D', arms=outputs,
        affected_arms=list(ARMS), delta_minutes=list(DELAYS), parity=common.identity(receipt),
        specified_outside_D='REUSE_BY_IDENTITY', corrected_secondary_families=False,
        models_refitted=0, delta_rule=DELTA_RULE))
    return dict(schema=SCHEMA, parity=common.identity(receipt), prediction_view=common.identity(view),
                predictions=outputs, specified_dly8=binding['dly8'], coverage=coverage,
                arms=list(ARMS), delta_minutes=list(DELAYS), seed=common.SEED,
                model_variant='main', window='D', models_refitted=0, delta_rule=DELTA_RULE)


def validate_extension(extension, binding, *, synthetic=False):

    require(isinstance(extension, dict) and extension.get('schema') == SCHEMA and
            extension.get('arms') == list(ARMS) and extension.get('delta_minutes') == list(DELAYS) and
            extension.get('seed') == common.SEED and extension.get('model_variant') == 'main' and
            extension.get('window') == 'D' and extension.get('models_refitted') == 0 and
            extension.get('delta_rule') == DELTA_RULE and
            extension.get('specified_dly8') == binding.get('dly8'), 'Corrected delayed seal scope drift')
    support = ps._support(binding, list(ARMS), synthetic=synthetic)
    _validate_authority(binding, synthetic=synthetic)
    rows = support['grid_rows']
    refs = specified_delay_identities(binding['dly8'], synthetic=synthetic, rows=rows)
    _validate_models(binding)
    receipt = common.read_json(common.checked(extension['parity']))
    view = common.read_json(common.checked(extension['prediction_view']))
    require(receipt.get('schema') == PARITY_SCHEMA and receipt.get('state') == 'PASS' and
            receipt.get('binding') == binding and receipt.get('specified') == refs and
            receipt.get('coverage') == extension.get('coverage') and receipt.get('grid_rows') == rows and
            receipt.get('affected_arms') == list(ARMS) and receipt.get('delta_minutes') == list(DELAYS) and
            receipt.get('seed') == common.SEED and receipt.get('model_variant') == 'main' and
            receipt.get('window') == 'D' and receipt.get('models_refitted') == 0 and
            receipt.get('delta_rule') == DELTA_RULE and receipt.get('outcomes_read') is False and
            receipt.get('values_printed') is False and receipt.get('touched_support_recomputed_per_delay') is True,
            'Corrected delayed parity receipt binding/scope drift')
    require(view.get('schema') == VIEW_SCHEMA and view.get('state') == 'CORRECTED_PRIMARY_NOTICE_D_DELAY_VIEW' and
            view.get('arms') == extension.get('predictions') and view.get('parity') == extension['parity'] and
            view.get('source') == 'notice' and view.get('seed') == common.SEED and
            view.get('model_variant') == 'main' and view.get('window') == 'D' and
            view.get('affected_arms') == list(ARMS) and view.get('delta_minutes') == list(DELAYS) and
            view.get('specified_outside_D') == 'REUSE_BY_IDENTITY' and
            view.get('corrected_secondary_families') is False and view.get('models_refitted') == 0 and
            view.get('delta_rule') == DELTA_RULE, 'Corrected delayed prediction view drift')
    grid = receipt.get('full_grid_keys')
    ps._valid_key_identity(grid, rows)
    if synthetic:
        require(grid == support['grid_keys'], 'Synthetic corrected delay grid identity drift')
    names = {str(delta) for delta in DELAYS}
    require(set(extension['predictions']) == set(receipt['arms']) == set(extension['coverage']) == names,
            'Corrected delayed reading census drift')
    for delta in DELAYS:
        name = str(delta)
        predictions, checks, coverage = extension['predictions'][name], receipt['arms'][name], extension['coverage'][name]
        require(set(predictions) == set(checks) == set(coverage) == set(common.PRIMARY),
                'Corrected delayed primary arm census drift')
        for arm in common.PRIMARY:
            output, check, cov = predictions[arm], checks[arm], coverage[arm]
            common.checked(output['identity'])
            require(cov.get('rows') == rows and cov.get('specified_identity') == refs[name][arm],
                    'Corrected delayed specified coverage identity drift')
            if arm not in ARMS:
                require(output == dict(mode='REUSE_BY_IDENTITY', identity=refs[name][arm]) and
                        check == dict(state='REUSE_BY_IDENTITY', rebuilt=False, identity_equal=True) and
                        cov.get('mode') == 'SPECIFIED_DLY8_REUSE_BY_IDENTITY',
                        'Unaffected delayed arm was rebuilt/substituted')
                continue
            require(output.get('mode') == 'CORRECTED_DLY8_D_SUBSTITUTION' and
                    output.get('specified_identity') == refs[name][arm] and check.get('state') == 'PASS' and
                    cov.get('keys_equal') is True and cov.get('keys') == grid and
                    cov.get('corrected_identity') == output['identity'] and
                    cov.get('mode') == 'EXACT_SPECIFIED_DLY8_D_KEYS', 'Corrected delayed affected coverage drift')
            item = output['identity']
            require(item.get('source') == 'notice' and item.get('arm') == arm and item.get('seed') == common.SEED and
                    item.get('variant') == 'delay'+name and item.get('delta_minutes') == delta and
                    item.get('model_variant') == 'main' and item.get('window') == 'D' and
                    item.get('rows') == rows and item.get('anchor_reading') == 'corrected_day_first',
                    'Corrected delayed prediction identity scope drift')
            count = check.get('feature_rows_changed')
            require(type(count) is int and 0 <= count < rows and check.get('full_grid_keys') == grid and
                    check.get('support_rule') == 'EXACT_RETAINED_FEATURE_BYTE_DIFFERENCES_AT_THIS_SPECIFIED_DELAY' and
                    check.get('values_printed') is False, 'Corrected delayed touched support drift')
            untouched = rows-count
            ps._valid_key_identity(check.get('untouched_keys'), untouched)
            changed = check.get('changed_key_support')
            ps._valid_key_identity(changed, count)
            counts = check.get('touched', {})
            require(counts.get('rows') == count and
                    all(type(n) is int and n > 0 for n in counts.get('regions', {}).values()) and
                    all(type(n) is int and n > 0 for n in counts.get('origin_hours_aest', {}).values()) and
                    sum(counts.get('regions', {}).values()) == count and
                    sum(counts.get('origin_hours_aest', {}).values()) == count,
                    'Corrected delayed count-only touched receipt drift')
            ps._prediction_receipt(check.get('specified_full_predictions'), rows, grid)
            ps._prediction_receipt(check.get('corrected_untouched_predictions'), untouched, check['untouched_keys'])
            feature_identity = check.get('specified_rebuilt_feature_identity', {})
            shape = feature_identity.get('shape')
            require(isinstance(shape, list) and len(shape) == 2 and shape[0] == rows and
                    type(shape[1]) is int and shape[1] > 0,
                    'Specified delayed rebuilt feature shape drift')
            ps._array_receipt(feature_identity, 'float32', shape)
            columns = shape[1]
            require(ps._feature_receipt(check.get('corrected_untouched_features'), untouched) == columns and
                    check['corrected_untouched_features'].get('retained_feature_changed_rows') == count,
                    'Corrected delayed feature support/column drift')
    return receipt, view


def write_combined_seal(path, result, binding, synthetic=False):
    'Save forecast hashes for the 5-, 15- and 60-minute availability delays.'
    _scope(Path(path).parent, binding)
    require(synthetic is _synthetic(binding), 'Corrected seal synthetic/production input_checks drift')
    require(isinstance(result, dict) and 'delay_extension' in result,
            'All corrected delay readings are required before sealing')
    ps._validate_result(result, binding, synthetic=synthetic)
    validate_extension(result['delay_extension'], binding, synthetic=synthetic)
    value = dict(state='FORECAST_BINDING_SEALED_BEFORE_T5', synthetic_only=synthetic,
        sealed_before_outcome_scoring=True, binding=binding, **result, models_refitted=0,
        seed=common.SEED, variant='main', window='D', scoring_run=False,
        specified_main_seal_preserved=True, corrected_readings=[5, 15, 60],
        corrected_delay_extension_schema=SCHEMA)
    common.write_json(path, value)
    return value


def verify_combined_seal(path, *, allow_synthetic=False):
    'Check saved forecast hashes and parity for all availability delays.'
    value = ps.verify_seal(path, allow_synthetic=allow_synthetic)
    _scope(Path(path).parent, value['binding'])
    require(value.get('corrected_readings') == [5, 15, 60] and
            value.get('corrected_delay_extension_schema') == SCHEMA,
            'Corrected seal omits a required delay reading')
    validate_extension(value.get('delay_extension'), value['binding'], synthetic=value['synthetic_only'])
    return value
