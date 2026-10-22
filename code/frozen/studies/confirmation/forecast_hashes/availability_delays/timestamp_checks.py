'Check delayed-notice source hashes and timestamp certificates.'
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import types

HERE = Path(__file__).absolute().parent
AF = HERE.parent
PARENT = AF / 'deadline_checks'
Q = AF.parents[1]
DECISION = {'path': str(Q / 'confirmation/REVIEW8/SOURCE_DECISIONS_REVIEW8_20261005.md'),
            'bytes': 11684, 'sha256': '0c755ff3f08ab62d8c2b913088027fc7f10f0a8e923ddb561578185ef486303f'}
PARENT_AUTHORITY = {'path': str(PARENT / 'timestamp_checks.py'), 'bytes': 19951,
                    'sha256': 'ae35fb31eb5834e3677952727dfb4aa4e51288e575709c90750afd80443199ed'}
PARENT_DELIVERY = {'path': str(PARENT / 'DELIVERY_MANIFEST.json'), 'bytes': 30280,
                   'sha256': 'f1d7e8ac4c4e1caa642aeaf430968ffafd5e6e1858b40a200a4be57be4de4ecb'}
FROZEN_DLY8_SOURCES = {
    'batch_estimation/fitting/code/rebuild_delayed_features.py': {'bytes': 26058, 'sha256': '19dcc0d78dd2dae04236ee229160748a25e9f6745f769f72c5f4be8807bb31b5'},
    'batch_estimation/fitting/code/delay_cache.py': {'bytes': 4102, 'sha256': '47f931802ccc7d0aaa3569b84548fbafca10d945d909121ae38cc364b972bd53'},
    'batch_estimation/fitting/code/batch_inputs.py': {'bytes': 6411, 'sha256': 'e623cbef090cd7e7549c557146862e0c8d1f50e6666bcb0577774d14523add0a'},
    'batch_estimation/fitting/code/runner.py': {'bytes': 68147, 'sha256': 'a6fe3aae6412154adf1f4edd3ffa838266892a6e8f51a46dcd12caa77f460d0a'},
    'batch_estimation/disk_checks/disk_overlay.py': {'bytes': 24830, 'sha256': 'a6427660e649aa0bd86cff51977fbfa2525d23255fbc19e9fe7dfb5d7f9e19d1'},
    'batch_estimation/disk_checks/forecast_wrapper.py': {'bytes': 4443, 'sha256': '78ce7f04aea6d6d16a30434c6dc65a1947d8dd211ef1c42c7b34e119aaf4f176'},
}
T4K_PINS = {
    'MANIFEST_T4K.sha256': {'bytes': 1228, 'sha256': '50cbca84beadaa3f031a290c89f79b5fc8acb47ac50d448610c54cf36ea462d1'},
    'T4K_RESULT.json': {'bytes': 1558, 'sha256': '386bae50d907fc1ca0ea9ae54c1aa0c5e2f38b6134f7c4beca995905165a8dc1'},
    'T4K_freetsa.tsr': {'bytes': 4643, 'sha256': '9c1e834376af53d54633bf180163192f2148913dc52cdbfdaccbec1ec3847fe8'},
    'T4K_digicert.tsr': {'bytes': 6006, 'sha256': 'd7448d9b677a82907728fb8ae1a425127ea88ade2846feab763782118e473b10'},
}
CALENDAR_RULE = 'NO_CALENDAR_DEADLINE_CORRECTED_SEAL_PRECEDES_T5'
_BASE = None


def require(ok, why):
    if not ok:
        raise PermissionError(why)


def _key(value):
    return value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid


def _bootstrap_parent_authority():

    path = PARENT_AUTHORITY['path']
    require(path == str(PARENT / 'timestamp_checks.py'), 'Exact parent timestamp_checks source required')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    handles, edges = [], []
    try:
        directory_open = getattr(sys.modules.get('common'), 'open_directory_metadata', None)
        handles.append(directory_open('/') if directory_open else os.open('/', flags))
        parent_path = '/'
        for part in Path(path).parts[1:-1]:
            parent = handles[-1]
            reference_snapshot = os.stat(part, dir_fd=parent, follow_symlinks=False)
            require(stat.S_ISDIR(reference_snapshot.st_mode), 'Parent source ancestry must be real directories')
            child = (directory_open(part, dir_fd=parent, parent_path=parent_path) if directory_open
                     else os.open(part, flags, dir_fd=parent))
            handles.append(child)
            require(_key(os.fstat(child)) == _key(reference_snapshot), 'Parent source directory drift')
            edges.append((parent, part, child, _key(reference_snapshot)))
            parent_path = str(Path(parent_path) / part)
        reference_snapshot = os.stat('timestamp_checks.py', dir_fd=handles[-1], follow_symlinks=False)
        require(stat.S_ISREG(reference_snapshot.st_mode) and reference_snapshot.st_size == PARENT_AUTHORITY['bytes'],
                'Pinned parent timestamp_checks must be a real regular source file')
        leaf_parent = handles[-1]
        leaf = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        handles.append(leaf)
        require(_key(os.fstat(leaf)) == _key(reference_snapshot), 'Parent timestamp_checks file identity changed')
        require(_key(os.stat('timestamp_checks.py', dir_fd=leaf_parent, follow_symlinks=False)) == _key(reference_snapshot),
                'Parent timestamp_checks leaf changed before read')
        for parent, part, child, expected in edges:
            require(_key(os.stat(part, dir_fd=parent, follow_symlinks=False)) == expected
                    and _key(os.fstat(child)) == expected, 'Parent source ancestry drift before read')
        payload = b''
        while True:
            block = os.read(leaf, 1 << 16)
            if not block:
                break
            payload += block
            require(len(payload) <= PARENT_AUTHORITY['bytes'], 'Parent source grew beyond pin')
        after = os.fstat(leaf)
        require(_key(after) == _key(reference_snapshot) and reference_snapshot.st_size == after.st_size == len(payload)
                and reference_snapshot.st_mtime_ns == after.st_mtime_ns and reference_snapshot.st_ctime_ns == after.st_ctime_ns
                and hashlib.sha256(payload).hexdigest() == PARENT_AUTHORITY['sha256'],
                'Parent timestamp_checks source bytes drift')
        require(_key(os.stat('timestamp_checks.py', dir_fd=leaf_parent, follow_symlinks=False)) == _key(reference_snapshot),
                'Parent timestamp_checks leaf changed after read')
        for parent, part, child, expected in edges:
            require(_key(os.stat(part, dir_fd=parent, follow_symlinks=False)) == expected
                    and _key(os.fstat(child)) == expected, 'Parent source ancestry drift after read')
        return payload
    except PermissionError:
        raise
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise PermissionError('Cannot verify exact unchanged parent timestamp_checks source') from exc
    finally:
        for descriptor in reversed(handles):
            os.close(descriptor)


def parent_authority():

    global _BASE
    if _BASE is None:
        module = types.ModuleType('_forecast_binding8_parent_authority')
        module.__file__ = str(PARENT / 'timestamp_checks.py')
        existing = sys.modules.get('timestamp_checks')
        if getattr(existing, '__file__', None) == module.__file__:


            vars(module).update(vars(existing))
            for name, value in list(vars(module).items()):
                if isinstance(value, types.FunctionType) and value.__globals__ is vars(existing):
                    cloned = types.FunctionType(value.__code__, vars(module), value.__name__,
                                                value.__defaults__, value.__closure__)
                    cloned.__kwdefaults__ = value.__kwdefaults__
                    setattr(module, name, cloned)
        else:
            exec(compile(_bootstrap_parent_authority(), module.__file__, 'exec'), vars(module))
        original_reader = module.read_metadata


        module._unchanged_reader = original_reader
        module.read_metadata = read_metadata
        _BASE = module
    return _BASE


def read_metadata(path):
    base = parent_authority()
    raw = base.canonical(path)
    exact_leaves = {DECISION['path'], *(str(Q / name) for name in FROZEN_DLY8_SOURCES)}
    if raw in exact_leaves:
        exact_globals = dict(base._unchanged_reader.__globals__)
        exact_globals['ERRATUM'] = {'path': raw}
        reader = types.FunctionType(base._unchanged_reader.__code__, exact_globals,
                                    '_exact_additive_source_metadata')
        return reader(raw)
    return base._unchanged_reader(raw)


def identity(path):
    raw = parent_authority().canonical(path)
    data = read_metadata(raw)
    return {'path': raw, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def read_json(path):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, 'Duplicate source timestamp_checks JSON key')
            value[key] = item
        return value
    try:
        return json.loads(read_metadata(path), object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(PermissionError('Nonfinite timestamp_checks JSON')))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise PermissionError('Invalid source timestamp_checks JSON') from exc


def verify_timestamp_bundle(label, required_identities, expected_metadata=None):
    return parent_authority().verify_timestamp_bundle(label, required_identities, expected_metadata)


def verify_decision():
    require(identity(DECISION['path']) == DECISION, 'Exact pre-outcome REVIEW8 decision SHA required')
    proof = verify_timestamp_bundle('T4K', [DECISION], T4K_PINS)
    require(proof.get('label') == 'T4K' and set(proof.get('tsa', {})) == {'freetsa', 'digicert'}
            and all(row.get('verified') is True and row.get('utc') == '2026-10-05T11:28:31+00:00'
                    for row in proof['tsa'].values()), 'Exact T4K two-TSA pre-outcome timestamp_checks required')
    return {'schema': 'FORECAST_BINDING8_REVIEW8_DECISION_AUTHORITY_V1', 'decision': DECISION.copy(),
            'timestamp': proof, 'accepted_clause': 'D1.1', 'delay_minutes': [15, 60],
            'corrected_arms': ['L14', 'L_Laz'], 'window': 'D', 'primary_seed': 20260919,
            'variant': 'main', 'models_refitted': 0, 'calendar_rule': CALENDAR_RULE,
            'before_T5_required': True, 'single_corrected_seal_required': True,
            'specified_month_first_delay_parity_required': True}


def verify_specification():
    return parent_authority().verify_specification()


def verify_frozen_delay_sources():
    rows = {}
    for name, pin in sorted(FROZEN_DLY8_SOURCES.items()):
        expected = {'path': str(Q / name), **pin}
        require(identity(expected['path']) == expected, 'Frozen specified DLY8 source bytes drift')
        rows[name] = expected
    return rows


def historical_snapshot(verify_current=True, verify_tsa=True):
    return parent_authority().historical_snapshot(verify_current, verify_tsa)


def verify_unchanged_parents():

    require(identity(PARENT_DELIVERY['path']) == PARENT_DELIVERY, 'Exact parent delivery identity required')
    delivery = read_json(PARENT_DELIVERY['path'])
    require(delivery.get('schema') == 'FORECAST_BINDING7_ADDITIVE_DELIVERY_MANIFEST_V1'
            and delivery.get('state') == 'PREPARED_TESTED_NOT_FROZEN_NOT_HOST_RUN'
            and isinstance(delivery.get('files'), dict) and len(delivery['files']) == 23,
            'Exact unchanged deadline_checks source delivery required')
    rows = []
    base = parent_authority()
    for name, row in sorted(delivery['files'].items()):
        require(isinstance(name, str) and not name.startswith('/') and '..' not in name.split('/')
                and row == base.row_identity(row) and row['path'] == str(PARENT / name),
                'Parent overlay inventory escaped exact source root')
        require(identity(row['path']) == row, 'Parent overlay committed bytes changed')
        rows.append(row)
    tests = read_json(PARENT / 'TEST_RESULTS.json')
    require(tests.get('schema') == 'FORECAST_BINDING7_FULL_SUITE_RECEIPT_V1'
            and tests.get('state') == 'PASS_SYNTHETIC_TESTS' and tests.get('tests_run') == 162
            and tests.get('historical_tests_run') == 118 and tests.get('overlay_tests_run') == 44
            and tests.get('full_suite_runs') == 1 and tests.get('numerical_processes') == 1
            and all(tests.get(name) == 0 for name in ('failures', 'errors', 'skipped')),
            'Unchanged passing parent 162-test source receipt required')
    require(identity(PARENT / 'TEST_RESULTS.json') == delivery['full_suite_receipt'],
            'Parent source receipt delivery association drift')
    historical = historical_snapshot(verify_current=True, verify_tsa=False)
    return {'schema': 'FORECAST_BINDING8_UNCHANGED_PARENT_SOURCES_V1', 'historical_T4F': historical,
            'parent_overlay_delivery': PARENT_DELIVERY.copy(), 'parent_overlay_source_rows': rows,
            'parent_overlay_files': delivery['files'],
            'parent_overlay_test_receipt': delivery['full_suite_receipt'],
            'parent_overlay_runtime_authority_asserted': False}
