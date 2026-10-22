'Check forecast input roots and delayed-notice records.'
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

from common import B, OUT, Q, X2, PRIMARY, SEED, checked, identity, read_json, require

D = Q / 'batch_estimation/disk_checks'
F1 = Q / 'batch_estimation/A8BATCHDISKSET1'
F2 = Q / 'batch_estimation/A8BATCHDISKSET2'
C = Q / 'batch_estimation/batch_checks'
R8 = ('M0_n', 'M+0_n', 'M+_n', 'L14+', 'L_Laz+', 'L_chen_notice+')
TERMINAL = {'ALL_DLY8_PREDICTIONS_SEALED', 'NOT_RUN_R8_UNAVAILABLE',
            'NOT_RUN_A8_SPECIFICATION_2', 'NOT_RUN_PARITY_FAILED', 'A8DLY_DEV'}
SUCCESS_BINDING_FIELDS = {'mode', 'main_conf_seal', 'source_seal', 'code_freeze',
                          'models', 'cache_input', 'notice_census'}
SET2_NOTICE_CENSUS = dict(pool=796, lead_in=71,
                         scope='2026-07-27 through 2026-09-30 AEST')


def root_mapping_contract():

    sources = [B/'code/batch_inputs.py', B/'code/rebuild_delayed_features.py', B/'code/delay_cache.py',
               D/'disk_overlay.py', D/'forecast_wrapper.py', D/'freeze_disk.py',
               F1/'host_wrapper_set1.py', F1/'check_paths.py',
               F2/'host_wrapper_set2.py', F2/'freeze_set2.py', F2/'t4e_verify.py', F2/'census_patch.py',
               C/'consumer_roots.py', C/'FORECAST_BINDING_INTERFACE_NOTE.md',
               X2/'execution_adapter.py',X2/'runtime.py',X2/'cli.py',
               X2/'features_adapter.py',X2/'global_input_freeze.py',B/'code/runner.py',B/'code/run_comparison_sets.py',
               Q/'confirmation/lear_horizon/seal_lear_horizon.py',
               Q/'confirmation/news_memory/host_chain_SPEC_8.sh',
               Q/'confirmation/fit_memory/host_chain_SPEC_7.sh',
               Q/'confirmation/storage_limits/host_chain_SPEC_6.sh',
               Q/'confirmation/input_definitions/host_chain_SPEC_5.sh',X2/'host_chain_20261002.sh',
               Q/'confirmation/TIMESTAMPS/make_timestamp.py',Q/'batch_estimation/host_scripts/timestamp_a8batch.py',
               X2/'seal_score.py',Q/'confirmation/primary_tests/code/primary_comparisons.py',
               Q/'confirmation/sensitivity_tests/code/sensitivity_comparisons.py',Q/'confirmation/robustness_tests/code/robustness_comparisons.py',
               B/'code/score_batch.py',Q/'inference/HOST_RUN_A8POST.md',
               OUT/'REVIEW_IMPLEMENTATION_CHECK_20261005_source.md', OUT/'REVIEW2_IMPLEMENTATION_CHECK_20261005_source.md',
               OUT/'REVIEW3_IMPLEMENTATION_CHECK_20261005_source.md',OUT/'REVIEW4_IMPLEMENTATION_CHECK_20261005_source.md']
    score_namespaces=[X2/'host_state'/name for name in ('scored','a2_scored','a3_scored','a4_scored')]
    score_namespaces += [D/'state/scoring',C/'POSTSCORE_PRODUCER_RECEIPT.json',Q/'inference/production_output']
    gates=[C/'T5_BINDING.json',B/'T5_BINDING.json',D/'T5_BINDING.json',*score_namespaces]
    roots=dict(schema='FORECAST_BINDING_CURRENT_HOST_ROOTS_V3', code_root=str(B),output_root=str(OUT),
                disk_root=str(D), state_root=str(D/'state'), dly8_root=str(D/'dly8'),
                set1_root=str(F1), set2_root=str(F2), consumer_root=str(C),
                main_root=str(X2), t5_binding=str(C/'T5_BINDING.json'),


                t5_gate_paths=[str(p) for p in gates],
                score_gate_paths=[str(p) for p in score_namespaces],
                wrapper_entries=[str(D/'forecast_wrapper.py'), str(F1/'host_wrapper_set1.py'), str(F2/'host_wrapper_set2.py')],
                association_metadata_paths=[str(p) for p in (
                    D/'DISK_FREEZE.json', D/'T4C_ROOTS.json', D/'T4C_BINDING.json',
                    F1/'SET1_FREEZE.json', F1/'T4D_BINDING.json',
                    F2/'SET2_FREEZE.json', F2/'T4E_BINDING.json',
                    C/'SOURCE_LOCK.json', C/'CONSUMER_FREEZE.json',
                    C/'RELEASE_BINDINGS.json', C/'SCORER_CODE_FREEZE.json',
                    C/'SCORER_BINDINGS.json', C/'T5_IDENTITY_COMMITMENTS.json')],
                source_identities=[identity(p) for p in sources])
    from activity_guard import activity_paths
    roots['activity_guard']=activity_paths(roots)
    roots['before_t5_guard']=dict(schema='FORECAST_BINDING_POSITIVE_BEFORE_T5_CONTRACT_V1',
        timestamp_root=str(Q/'confirmation/TIMESTAMPS'),timestamp_label='T5',
        timestamp_label_path=str(Q/'confirmation/TIMESTAMPS/T5'),
        sentinel_paths=roots['t5_gate_paths'],
        score_receipts=[dict(path=str(path),absent_namespace=str(namespace)) for path,namespace in (
            (X2/'host_state/scored/SCORE_RECEIPT.json',score_namespaces[0]),
            (X2/'host_state/a2_scored/PRIMARY_COMPARISONS_RECEIPT.json',score_namespaces[1]),
            (X2/'host_state/a3_scored/SENSITIVITY_COMPARISONS_RECEIPT.json',score_namespaces[2]),
            (X2/'host_state/a4_scored/ROBUSTNESS_COMPARISONS_RECEIPT.json',score_namespaces[3]),
            (D/'state/scoring/CS8/scored/SCORE_RECEIPT.json',score_namespaces[4]),
            (D/'state/scoring/CS8_SCORE_RECEIPT_WITH_LOSSES.json',score_namespaces[4]),
            (D/'state/scoring/A8BATCH_POSTSCORE_INPUTS.json',score_namespaces[4]),
            (C/'POSTSCORE_PRODUCER_RECEIPT.json',score_namespaces[5]),
            (Q/'inference/production_output/A8_POSTSCORE_RECEIPT.json',score_namespaces[6]))])
    return roots


def mapping_sha256(mapping):
    return hashlib.sha256(json.dumps(mapping, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def verify_root_mapping(mapping):

    require(mapping == root_mapping_contract(), 'Current DISK/SET2 root mapping/source drift')
    for key in ('code_root', 'disk_root', 'state_root', 'dly8_root', 'set1_root',
                'set2_root', 'consumer_root', 'main_root', 'output_root'):
        p = Path(mapping[key])
        require(p.is_absolute() and p.resolve() == p, 'Root alias/escape: '+key)
    for item in mapping['source_identities']:
        checked(item)
    return mapping


resolve_host_roots = verify_root_mapping


def _load_source(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    require(Path(module.__file__).resolve() == Path(path).resolve(), 'Release verifier entry drift')
    return module


def verify_runtime_roots(mapping):

    roots = verify_root_mapping(mapping)
    saved = list(sys.path)
    sys.path[:0] = [str(F2), str(D), str(F1)]
    try:

        f2 = _load_source(F2/'host_wrapper_set2.py', '_forecast_binding_set2_verifier')
        release = f2.verify_set2()


        overlay = sys.modules.get('disk_overlay')
        require(overlay is None or Path(overlay.__file__).resolve() == D/'disk_overlay.py',
                'Foreign disk overlay module')
        disk = _load_source(D/'forecast_wrapper.py', '_forecast_binding_disk_verifier')
        disk.verify_release()
    finally:
        sys.path[:] = saved
    paths = [D/'DISK_FREEZE.json', D/'T4C_ROOTS.json', D/'T4C_BINDING.json',
             F1/'SET1_FREEZE.json', F1/'T4D_BINDING.json',
             F2/'SET2_FREEZE.json', F2/'T4E_BINDING.json']
    require(release['set_freeze'] == identity(paths[-2]) and
            release['t4e_binding'] == identity(paths[-1]), 'SET2 release snapshot drift')
    return dict(schema='FORECAST_BINDING_RUNTIME_ROOTS_BOUND_V1', mapping=roots,
                mapping_sha256=mapping_sha256(roots), releases=[identity(p) for p in paths])


def verify_runtime_root_binding(binding):

    require(binding == verify_runtime_roots(binding['mapping']), 'Runtime root/release binding drift')
    return True


def _identity_shape(item):
    require(isinstance(item, dict) and {'path', 'bytes', 'sha256'} <= set(item), 'Missing identity fields')
    p = Path(item['path'])
    require(p.is_absolute() and p.resolve() == p and type(item['bytes']) is int and item['bytes'] >= 0
            and isinstance(item['sha256'], str) and re.fullmatch('[0-9a-f]{64}', item['sha256']),
            'Malformed/noncanonical bound identity')
    return p


def _dly_path(path, root):
    p, root = Path(path), Path(root)
    require(p.is_absolute() and p.resolve() == p and p.is_relative_to(root)
            and not any(q.is_symlink() for q in [p, *p.parents] if q.is_relative_to(root)),
            'DLY8 output escaped exact D root or has a symlink')
    return p


def _recursive_identities(value, dly_root, seen=None):

    seen = set() if seen is None else seen
    if isinstance(value, dict):
        if {'path', 'bytes', 'sha256'} <= set(value):
            p = _identity_shape(value)
            checked(value)
            if p.is_relative_to(Path(dly_root)):
                _dly_path(p, dly_root)


                cache = Path(dly_root)/'embedding_cache'
                metadata = not p.is_relative_to(cache) or p == cache/'PRODUCTION_CACHE_INPUTS.json'
                if p.suffix == '.json' and metadata and p not in seen:
                    seen.add(p)
                    _recursive_identities(read_json(p), dly_root, seen)
        for child in value.values():
            _recursive_identities(child, dly_root, seen)
    elif isinstance(value, list):
        for child in value:
            _recursive_identities(child, dly_root, seen)


def _production_cache_input(item, roots):

    source_root = Path(roots['main_root'])/'host_state/features/embedding_cache'
    copy_root = Path(roots['dly8_root'])/'embedding_cache'
    receipt_path = copy_root/'PRODUCTION_CACHE_INPUTS.json'
    _identity_shape(item)
    require(item == identity(receipt_path), 'DLY8 cache input is not the exact current D production-cache receipt')
    _dly_path(receipt_path, Path(roots['dly8_root']))
    receipt = read_json(checked(item))
    require(isinstance(receipt, dict) and set(receipt) == {
        'state', 'files', 'reencoding_allowed', 'content_values_decoded'}
        and receipt.get('state') == 'SEALED_PRODUCTION_CACHE_COPIED'
        and receipt.get('reencoding_allowed') == 'LOCKED_MISSING_CORPORA_ONLY_WITH_RECEIPTS'
        and receipt.get('content_values_decoded') is False,
        'DLY8 production-cache receipt frozen schema/flags drift')
    files = receipt['files']
    require(isinstance(files, list) and files, 'DLY8 production-cache receipt has no source copies')
    source_paths, copy_paths, corpora = set(), set(), 0
    for row in files:
        require(isinstance(row, dict) and set(row) == {'source', 'copy'}, 'DLY8 cache source/copy row schema drift')
        source, copy = row['source'], row['copy']
        sp, cp = _identity_shape(source), _identity_shape(copy)
        require(set(source) == {'path', 'bytes', 'sha256'} and set(copy) == set(source),
                'DLY8 cache file identity schema drift')
        require(sp.is_relative_to(source_root), 'DLY8 cache source is outside the current main production cache')
        relative = sp.relative_to(source_root)
        require(len(relative.parts) >= 2 and relative.parts[0] in ('chunks', 'corpora')
                and sp.suffix in ('.npy', '.json')
                and not {'revisions', 'failed_attempts'} & set(relative.parts)
                and '.atomic.' not in sp.name and '.tmp.' not in sp.name and not sp.name.endswith('.tmp'),
                'DLY8 cache row is not an original frozen production-cache input')
        require(cp == copy_root/relative, 'DLY8 cache copy path does not match its source relative path')
        _dly_path(cp, Path(roots['dly8_root']))
        require(sp not in source_paths and cp not in copy_paths, 'Duplicate DLY8 cache source/copy identity')
        require((source['bytes'], source['sha256']) == (copy['bytes'], copy['sha256']),
                'DLY8 cache source/copy bytes or SHA do not match')
        checked(source); checked(copy)
        source_paths.add(sp); copy_paths.add(cp)
        corpora += relative.parts[0] == 'corpora'
    require(corpora > 0, 'DLY8 frozen production corpus cache is empty')
    return True


def _successful_binding(bound, roots, batch):

    require(isinstance(bound, dict) and set(bound) == SUCCESS_BINDING_FIELDS,
            'DLY8 success binding is missing or adds frozen schema fields')
    freeze_path = Path(roots['code_root'])/'CODE_FREEZE.json'
    freeze = identity(freeze_path)
    _identity_shape(bound['code_freeze'])
    require(bound['code_freeze'] == freeze and batch.get('code_freeze') == freeze,
            'DLY8 success code freeze is not the exact current B batch release')
    checked(bound['code_freeze'])
    census = bound['notice_census']
    require(isinstance(census, dict) and census == SET2_NOTICE_CENSUS
            and type(census.get('pool')) is int and type(census.get('lead_in')) is int,
            'DLY8 success notice census is not the exact SET2 contract')
    _production_cache_input(bound['cache_input'], roots)


def _successful_receipt(row, mode, parent, dly_root, roots, batch):
    arms = list(PRIMARY if mode == 1 else R8)
    bound = row['binding']
    _successful_binding(bound, roots, batch)
    require(bound.get('mode') == mode and type(bound.get('mode')) is int, 'Successful DLY8 receipt mode drift')
    require(row.get('arms') == arms and row.get('delays_minutes') == [5, 15, 60]
            and row.get('delta0_first') is True and row.get('training_rows_changed') is False
            and row.get('outcomes_read') is False, 'Successful DLY8 receipt frozen scope drift')
    models = bound.get('models')
    require(isinstance(models, list) and len(models) == len(arms)
            and len({i.get('path') for i in models}) == len(arms), 'DLY8 model identity census incomplete')
    sealed_models = [i for i in parent['fit_receipts_and_models'] if i.get('kind') == 'LightGBM_model']
    require(all(i in sealed_models for i in models), 'DLY8 model absent from source seal')
    parity = row.get('parity')
    _identity_shape(parity)
    _dly_path(parity['path'], dly_root)
    report = read_json(checked(parity))
    require(report.get('state') == 'PASS' and report.get('binding') == bound
            and report.get('delta_minutes') == 0, 'DLY8 zero-parity receipt binding drift')
    checks = report.get('checks', [])
    require([i.get('arm') for i in checks] == arms and all(
        i.get('state') == 'PASS' and i.get('features_byte_equal') is True
        and i.get('predictions_byte_equal') is True
        and isinstance(i.get('feature_bytes_sha256'), str)
        and re.fullmatch('[0-9a-f]{64}', i['feature_bytes_sha256']) for i in checks),
        'DLY8 complete frozen zero-parity checks required')
    predictions = row.get('predictions')
    require(isinstance(predictions, list), 'Missing DLY8 prediction identity census')
    expected = {(arm, delay) for delay in (5, 15, 60) for arm in arms}
    actual = [(i.get('arm'), i.get('delta_minutes')) for i in predictions]
    require(len(actual) == len(expected) and set(actual) == expected
            and len({i.get('path') for i in predictions}) == len(expected), 'DLY8 prediction identity census drift')
    for item in predictions:
        _identity_shape(item)
        _dly_path(item['path'], dly_root)
        require(item.get('source') == 'notice' and item.get('seed') == SEED
                and item.get('variant') == 'delay'+str(item['delta_minutes'])
                and item.get('rows') == 527040, 'DLY8 prediction frozen scope drift')


def load_dly8_binding(roots, main_identity, batch_identity, adapter_pin):

    roots = verify_root_mapping(roots)
    require(re.fullmatch('[0-9a-f]{64}', adapter_pin) is not None, 'Invalid adapter pin')
    main_path, batch_path = (_identity_shape(i) for i in (main_identity, batch_identity))
    require(main_path == Path(roots['main_root'])/'host_state/SEAL.json'
            and batch_path == Path(roots['state_root'])/'SEAL_BATCH.json', 'DLY8 parent root drift')
    main = read_json(checked(main_identity)); batch = read_json(checked(batch_identity))
    require(main.get('state') == 'ALL_SPECIFIED_PREDICTIONS_SEALED'
            and main.get('sealed_before_outcome_scoring') is True
            and batch.get('state') == 'ALL_A8BATCH_SPECIFIED_PREDICTIONS_SEALED'
            and batch.get('sealed_before_outcome_scoring') is True
            and batch.get('conf_seal') == main_identity
            and batch.get('conf_seal_sha256') == main_identity['sha256']
            and batch.get('adapter_freeze_sha256') == adapter_pin, 'DLY8 parent seal/adapter association drift')
    root = Path(roots['dly8_root']); families = []
    for mode, name in ((1, 'PRIMARY'), (2, 'R8')):
        seal_path = _dly_path(root/('DLY8_SEAL_'+name+'.json'), root)
        receipt_path = _dly_path(root/('mode'+str(mode))/'DELAY_RECEIPT.json', root)
        seal = read_json(seal_path)
        source = main_identity if mode == 1 else batch_identity
        require(seal.get('state') in ('DLY8_SEALED_BEFORE_SCORING', 'NOT_RUN_R8_UNAVAILABLE')
                and seal.get('receipt') == identity(receipt_path)
                and seal.get('conf_seal_sha256') == main_identity['sha256']
                and seal.get('source_seal') == source
                and seal.get('adapter_freeze_sha256') == adapter_pin
                and seal.get('models_refitted', 0) == 0, 'DLY8 family seal terminal/source/adapter drift')
        row = read_json(checked(seal['receipt']))
        state = row.get('state'); bound = row.get('binding', {})
        require(state in TERMINAL and row.get('models_refitted') == 0
                and bound.get('main_conf_seal') == main_identity
                and bound.get('source_seal') == source, 'DLY8 receipt is nonterminal or has wrong parents/refits')
        require('mode' not in bound or type(bound['mode']) is int and bound['mode'] == mode,
                'DLY8 receipt mode drift')
        require('mode_state' not in seal or seal['mode_state'] == state, 'DLY8 mode-state seal/receipt mismatch')
        require(state not in ('NOT_RUN_R8_UNAVAILABLE', 'NOT_RUN_A8_SPECIFICATION_2') or mode == 2,
                'R8-only terminal state in PRIMARY mode')
        require(seal['state'] != 'NOT_RUN_R8_UNAVAILABLE' or mode == 2 and state == 'NOT_RUN_R8_UNAVAILABLE',
                'R8 unavailable seal/receipt mismatch')
        if state == 'ALL_DLY8_PREDICTIONS_SEALED':
            _successful_receipt(row, mode, main if mode == 1 else batch, root, roots, batch)
        else:
            require(row.get('predictions') == [] and row.get('parity') is None
                    and row.get('partial_predictions_eligible_for_scoring', False) is False,
                    'Unavailable/failed DLY8 terminal contains eligible output')
        _recursive_identities(seal, root)
        _recursive_identities(row, root)
        families.append(dict(mode=mode, state=state, seal=identity(seal_path),
                             receipt=identity(receipt_path), source_seal=source))
    return dict(schema='FORECAST_BINDING_DLY8_TERMINALS_BOUND_V1', root_mapping=roots,
                main_conf_seal=main_identity, batch_seal=batch_identity,
                adapter_freeze_sha256=adapter_pin, families=families)


def verify_dly8_binding(binding):

    require(binding == load_dly8_binding(binding['root_mapping'], binding['main_conf_seal'],
                                        binding['batch_seal'], binding['adapter_freeze_sha256']),
            'DLY8 bound terminal identity drift')
    return True
