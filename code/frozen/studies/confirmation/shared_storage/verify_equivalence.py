"""Bounded execution-layout proof; input-only slices and synthetic projections.

This is a mechanical check, not a production feature build. Real panel reads
project only frozen inputs/key clocks. Study text, labels, and outcomes are not
opened. Archived old writing/pruning code supplies the independent reference.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ADAPTERS = HERE.parent / 'CONFX2'
ARCHIVE = HERE / 'archive/pre_CONFX3/CONFX2/features_adapter.py'
sys.path.insert(0, str(ADAPTERS))
sys.path.insert(0, str(ADAPTERS / 'tests'))
# Capture source bytes before the tested modules import. Later checks reject
# concurrent edits rather than attributing loaded behavior to a different file.
STARTUP_SOURCE_BYTES = {name: (ADAPTERS / name).read_bytes()
                        for name in ('features_adapter.py', 'feature_storage.py')}
import features_adapter as new
from runtime import atomic_json, sha256
from test_features_adapter import (SyntheticEncoder, article, news_panel,
                                   notice_panel, date_parser)
from test_nrx_adapter import PERMIT, FINAL3, notice, quantity

SEED = 20261001
SLICE_ROWS = 20000
TEMP_LIMIT = 300000000
KEY_CLOCKS = ('origin', 'target_time', 'target_day', 'label_available', 'region', 'horizon')
FORBIDDEN = frozenset(('y', 'outcome', 'target', 'rrp', 'price', 'label', 'weight'))


def archived_adapter():
    spec = importlib.util.spec_from_file_location('_confx3_archived_features', ARCHIVE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest_array(array):
    array = np.ascontiguousarray(array)
    return hashlib.sha256(array.tobytes()).hexdigest()


def tested_source_identities():
    requested = {'features_adapter.py': ('_write_bundles', 'fixed_pruning',
        'news_feature_rows', 'notice_feature_rows'),
        'feature_storage.py': ('load_feature_rows', '_open_array', '_normalise_rows')}
    result = {}
    for filename, content in STARTUP_SOURCE_BYTES.items():
        tree = ast.parse(content.decode())
        functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        result[filename] = {'path': str(ADAPTERS / filename),
            'startup_sha256': hashlib.sha256(content).hexdigest(),
            'tested_function_ast_sha256': {name: hashlib.sha256(ast.dump(functions[name],
                include_attributes=False).encode()).hexdigest() for name in requested[filename]}}
        if (ADAPTERS / filename).read_bytes() != content:
            raise RuntimeError('Tested adapter source changed during proof: ' + filename)
        result[filename]['completion_sha256'] = sha256(ADAPTERS / filename)
        result[filename]['startup_completion_bytes_equal'] = True
    return result


def assert_bits_equal(left, right):
    """Compare uint32 payloads, including NaNs and the sign bit of zero."""
    left = np.asarray(left); right = np.asarray(right)
    if left.dtype != np.dtype('float32') or right.dtype != np.dtype('float32'):
        raise AssertionError('Learner dtype drift')
    if left.shape != right.shape:
        raise AssertionError('Shape drift')
    np.testing.assert_array_equal(np.isnan(left), np.isnan(right))
    np.testing.assert_array_equal(left.view(np.uint32), right.view(np.uint32))


class TempBudget:
    def __init__(self, root):
        self.root = Path(root)
        self.peak = 0

    def check(self, additional=0):
        actual = sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())
        self.peak = max(self.peak, actual)
        if actual + additional > TEMP_LIMIT:
            raise AssertionError('Temporary-file cap exceeded before allocation: %d' % (actual + additional))
        return actual


def frozen_projection_fixture(source, cache_directory):
    """Use unchanged frozen row functions on synthetic documents and vectors."""
    cache_directory = Path(cache_directory) / 'embedding_cache'
    if source == 'news':
        panel = news_panel().drop(columns=['y'])
        articles = [article(str(i), pd.Timestamp(day, tz='Australia/Brisbane').tz_convert('UTC').isoformat())
                    for i, day in enumerate(('2026-07-05', '2026-07-12', '2026-07-19'))]
        rows = list(new.news_feature_rows(panel, articles, permit=PERMIT,
            encoder=SyntheticEncoder(), cache_directory=cache_directory,
            absolute_interval=date_parser, vocabulary={'title': ['coal'], 'body': ['failure']},
            stopwords=set()))
        numeric = ['num_a', 'num_b', 'constant', 'all_missing']
        expected = {(arm, 'main') for arm in new.NEWS_ARMS} | {
            ('M', '24h'), ('L_count', '24h'), ('L_chen', '24h'),
            ('L_chen', 'first_L'), ('E_raw', 'first_L')}
    else:
        panel = notice_panel().drop(columns=['y'])
        documents = [notice(), notice('9002', quantities=[quantity('100-200')],
            available='2026-08-01T00:05:00Z')]
        rows = list(new.notice_feature_rows(panel, documents, permit=PERMIT,
            encoder=SyntheticEncoder(), cache_directory=cache_directory, final3=FINAL3,
            corrected_rule=new.load_corrected_rule(permit=PERMIT),
            vocabulary={'title': ['synthetic'], 'body': []}, stopwords=set(), p5min_columns=['p5']))
        numeric = ['num_a', 'num_b']
        expected = {(arm, 'main') for arm in new.NOTICE_ARMS} | {('L_chen_notice', 'first_L')}
    seen = {key for _, extras, _ in rows for key in extras}
    if seen != expected:
        raise AssertionError('Registered arm/variant coverage drift: ' + str(seen ^ expected))
    return panel, numeric, rows, expected


def projected_extras(rows, length, p5_columns=(), panel=None):
    """Repeat frozen synthetic projection outputs; never encode study text."""
    bank = {}
    for indices, extras, _ in rows:
        for key, extra in extras.items():
            bank.setdefault(key, {})
            for name, value in extra.items():
                bank[key].setdefault(name, []).append(np.broadcast_to(np.asarray(value, dtype=np.float32), len(indices)).copy())
    result = {}
    for key, extra in bank.items():
        result[key] = {name: np.resize(np.concatenate(parts), length) for name, parts in extra.items()}
        if key[0] in ('NP', 'NPL', 'NPP') and p5_columns:
            # E3 uses the real frozen operator-input block in its original order.
            result[key] = {**{name: panel[name].to_numpy(dtype=np.float32) for name in p5_columns},
                           **{name: value for name, value in result[key].items() if name != 'p5'}}
    return result


def one_arm_rows(length, key, extras):
    for start in range(0, length, 10000):
        indices = np.arange(start, min(start + 10000, length))
        # The frozen writer's embedding coverage bookkeeping expects one
        # origin/region vector, whose coordinates are scalar, per yielded batch.
        values = {name: value[start] if name.startswith('emb_') else value[indices]
                  for name, value in extras.items()}
        yield indices, {key: values}, {
            'origin': 'SYNTHETIC_PROJECTION_ONLY', 'region': 'SYNTHETIC',
            'P_content': {'state': 'UNMATCHED'}}


def compare_one_arm(old, panel, numeric, key, extra, source, train_mask, temp_root, budget,
                    projection_rows=None):
    """Run independent old writer, remove its files, then assemble new storage."""
    from feature_storage import load_feature_rows
    old_root = Path(temp_root) / 'old'
    new_root = Path(temp_root) / 'new'
    captured = {}
    original_pruning = old.fixed_pruning
    original_evict = old._evict
    original_memmap = np.lib.format.open_memmap
    mapped = []

    def close_maps():
        for array in mapped:
            array.flush()
            array._mmap.close()
        mapped.clear()

    def rows_factory():
        if projection_rows is None:
            return one_arm_rows(len(panel), key, extra)
        return ((indices, {key: extras[key]}, coverage)
                for indices, extras, coverage in projection_rows)

    def capture(matrix, mask, names, *args, **kwargs):
        captured['original'] = np.array(matrix, dtype=np.float32, copy=True)
        captured['names'] = list(names)
        return original_pruning(matrix, mask, names, *args, **kwargs)

    def evict_and_check(matrix):
        original_evict(matrix)
        budget.check()

    def bounded_memmap(filename, *args, **kwargs):
        if kwargs.get('mode', 'r+') in ('w+', 'w'):
            shape = kwargs.get('shape')
            if shape is not None:
                size = int(np.prod(shape, dtype=np.int64)) * np.dtype(kwargs.get('dtype', np.float64)).itemsize + 1024
                budget.check(size)
        value = original_memmap(filename, *args, **kwargs)
        mapped.append(value)
        budget.check()
        return value

    try:
        # Function patches avoid unittest.mock call histories retaining deleted
        # memmaps and their disk allocations between bounded cases.
        with patch.object(old, 'fixed_pruning', new=capture), \
             patch.object(old, '_evict', new=evict_and_check), \
             patch.object(np.lib.format, 'open_memmap', new=bounded_memmap):
            old_bundle = old._write_bundles(panel, numeric, rows_factory(),
                old_root, source, train_mask, permit=PERMIT)[0]
        original = captured['original']
        retained = np.array(np.load(old_bundle['matrix']['path'], allow_pickle=False), copy=True)
        close_maps()
        budget.check()
        shutil.rmtree(old_root)
        with patch.object(new, 'require_disk_space', return_value={}), \
             patch.object(np.lib.format, 'open_memmap', new=bounded_memmap):
            bundle = new._write_bundles(panel, numeric, rows_factory(),
                new_root, source, train_mask, permit=PERMIT)[0]
        close_maps()
        if bundle['original_columns'] != captured['names'] or bundle['original_columns'] != old_bundle['original_columns']:
            raise AssertionError('Original feature order drift')
        if bundle['columns'] != old_bundle['columns'] or bundle['pruned_names'] != old_bundle['pruned_names']:
            raise AssertionError('Frozen training-only pruned order drift')
        for start in range(0, len(panel), 2000):
            indices = np.arange(start, min(start + 2000, len(panel)))
            assert_bits_equal(original[indices], load_feature_rows(bundle, indices, columns=bundle['original_columns']))
            assert_bits_equal(retained[indices], load_feature_rows(bundle, indices))
        budget.check()
        result = {'arm': key[0], 'variant': key[1], 'rows': len(panel),
            'original_columns': len(bundle['original_columns']), 'retained_columns': len(bundle['columns']),
            'original_order_sha256': hashlib.sha256(json.dumps(bundle['original_columns']).encode()).hexdigest(),
            'retained_order_sha256': hashlib.sha256(json.dumps(bundle['columns']).encode()).hexdigest(),
            'original_float32_sha256': digest_array(original), 'retained_float32_sha256': digest_array(retained),
            'nan_positions_sha256': digest_array(np.isnan(original)),
            'original_uint32_bits_equal': True, 'retained_uint32_bits_equal': True,
            'nan_positions_equal': True, 'original_order_equal': True, 'pruned_order_equal': True,
            'training_rows': int(train_mask.sum())}
        return result
    finally:
        close_maps()
        for directory in (old_root, new_root):
            if directory.exists():
                shutil.rmtree(directory)


def read_projected_rows(path, indices, columns):
    """Chunked parquet projection; no outcome field enters an Arrow batch."""
    if any(name.lower() in FORBIDDEN for name in columns):
        raise ValueError('Forbidden outcome column in projection')
    indices = np.asarray(indices, dtype=np.int64)
    if len(indices) and (np.diff(indices) < 0).any():
        raise ValueError('Indices must be sorted')
    parquet = pq.ParquetFile(path)
    selected = []
    offset = 0
    for batch in parquet.iter_batches(batch_size=10000, columns=columns):
        begin = np.searchsorted(indices, offset)
        end = np.searchsorted(indices, offset + batch.num_rows)
        if end > begin:
            table = pa.Table.from_batches([batch])
            selected.append(table.take(pa.array(indices[begin:end] - offset)))
        offset += batch.num_rows
        if len(indices) and offset > indices[-1]:
            break
    result = pa.concat_tables(selected).to_pandas() if selected else pd.DataFrame(columns=columns)
    if len(result) != len(indices):
        raise AssertionError('Projected row selection count drift')
    return result.reset_index(drop=True)


def host_slice(source, kind, panels_root, manifest):
    numeric = list(manifest['numeric_columns']['notices' if source == 'notice' else source])
    paths = [panels_root / 'news.parquet'] if source == 'news' else [panels_root / 'notices_train.parquet', panels_root / 'notices.parquet']
    counts = [pq.ParquetFile(path).metadata.num_rows for path in paths]
    total = sum(counts)
    selected = np.arange(min(SLICE_ROWS, total), dtype=np.int64) if kind == 'first' else np.sort(
        np.random.default_rng(SEED).choice(total, size=min(SLICE_ROWS, total), replace=False))
    frames = []; offset = 0; read_columns = {}
    for path, count in zip(paths, counts):
        local = selected[(selected >= offset) & (selected < offset + count)] - offset
        columns = list(dict.fromkeys(numeric + [name for name in KEY_CLOCKS if name in pq.ParquetFile(path).schema_arrow.names]))
        read_columns[str(path)] = columns
        if len(local):
            frames.append(read_projected_rows(path, local, columns))
        offset += count
    panel = pd.concat(frames, ignore_index=True)
    panel['origin'] = pd.to_datetime(panel.origin, utc=True)
    panel['target_time'] = pd.to_datetime(panel.target_time, utc=True)
    panel['target_day'] = panel.target_day.astype(str).str[:10]
    if source == 'news':
        train = panel.target_day.between('2021-10-01', '2024-12-31').to_numpy()
        train &= (pd.to_datetime(panel.label_available, utc=True) < pd.Timestamp('2024-12-31T14:00:00Z')).to_numpy()
    else:
        train = selected < counts[0]
        p5_frames = []; offset = 0
        for key, count in zip(('notice_p5_train', 'notice_p5'), counts):
            path = Path(manifest[key]['path'])
            local = selected[(selected >= offset) & (selected < offset + count)] - offset
            read_columns[str(path)] = list(manifest['p5_columns'])
            if len(local):
                p5_frames.append(read_projected_rows(path, local, manifest['p5_columns']))
            offset += count
        operator = pd.concat(p5_frames, ignore_index=True)
        for name in manifest['p5_columns']:
            panel[name] = operator[name].to_numpy(dtype=np.float32)
    if not train.any():
        raise AssertionError('Frozen host slice lacks training support')
    info = {'source': source, 'slice': kind, 'rows': len(selected), 'source_rows': total,
        'seed': SEED if kind == 'random' else None, 'row_indices_sha256': digest_array(selected),
        'numeric_float32_sha256': digest_array(panel[numeric].to_numpy(dtype=np.float32)),
        'training_membership_sha256': digest_array(train), 'input_columns': read_columns,
        'outcome_columns_read': [], 'p5_operator_columns': manifest.get('p5_columns', []) if source == 'notice' else [],
        'extras_scope': 'Frozen synthetic-document row projections repeated over input-only host slices; E3 operator inputs are real frozen P5MIN columns.'}
    return panel, numeric, train, info


def synthetic_checks(temp_root, budget):
    old = archived_adapter()
    records = []
    for source in ('news', 'notice'):
        fixture_root = Path(temp_root) / ('fixture_' + source)
        panel, numeric, rows, expected = frozen_projection_fixture(source, fixture_root)
        projected = projected_extras(rows, len(panel))
        train = np.arange(len(panel)) < len(panel) // 2
        records.append({'source': source, 'checks': [compare_one_arm(old, panel, numeric, key,
            projected[key], source, train, temp_root, budget, projection_rows=rows)
            for key in sorted(expected)]})
        shutil.rmtree(fixture_root)
    # Training-constant/all-missing columns vary only at evaluation; signed zero
    # and a noncanonical NaN payload make the float32-bit assertion stronger.
    nan = np.array([0x7fc00123], dtype=np.uint32).view(np.float32)[0]
    panel = pd.DataFrame({'origin': pd.date_range('2024-01-01', periods=4, tz='UTC'),
        'target_day': ['2024-01-01'] * 4, 'live': np.array([-0., 1., nan, 2.], dtype=np.float32),
        'constant_train': np.array([1., 1., 4., 7.], dtype=np.float32),
        'missing_train': np.array([nan, nan, 0., 1.], dtype=np.float32)})
    extras = {'extra_live': np.array([0., -1., -0., nan], dtype=np.float32),
        'extra_constant_train': np.array([0., -0., 8., 9.], dtype=np.float32),
        'extra_missing_train': np.array([nan, nan, 1., 0.], dtype=np.float32)}
    test = compare_one_arm(old, panel, ['live', 'constant_train', 'missing_train'], ('M', 'main'),
        extras, 'news', np.array([True, True, False, False]), temp_root, budget)
    if test['retained_columns'] != 2:
        raise AssertionError('Training-only constant/all-missing pruning changed')
    records.append({'source': 'synthetic_bit_and_training_pruning_fixture', 'checks': [test]})
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=HERE / 'EQUIVALENCE_RESULTS.json')
    args = parser.parse_args()
    spec = json.loads((HERE / 'SPEC_FREEZE.json').read_text())
    if not any(item.get('sha256') == sha256(HERE / 'SPEC.md') for item in spec.values() if isinstance(item, dict)):
        # Accepted explicit key form, without weakening hash verification.
        if spec.get('spec_sha256') != sha256(HERE / 'SPEC.md'):
            raise RuntimeError('Equivalence specification hash drift')
    old = archived_adapter()
    for name in ('news_feature_rows', 'notice_feature_rows', 'fixed_pruning'):
        if inspect.getsource(getattr(old, name)) != inspect.getsource(getattr(new, name)):
            raise AssertionError('Frozen projection/pruning source drift: ' + name)
    manifest_path = ADAPTERS / 'host_state/panels/manifest.json'
    manifest = json.loads(manifest_path.read_text())
    source_identities = tested_source_identities()
    records = []
    with tempfile.TemporaryDirectory(prefix='confx3_equivalence_') as temporary:
        budget = TempBudget(temporary)
        synthetic = synthetic_checks(temporary, budget)
        for source in ('news', 'notice'):
            fixture_root = Path(temporary) / ('projection_' + source)
            _, _, rows, expected = frozen_projection_fixture(source, fixture_root)
            for kind in ('first', 'random'):
                panel, numeric, train, info = host_slice(source, kind, manifest_path.parent, manifest)
                projected = projected_extras(rows, len(panel), manifest['p5_columns'] if source == 'notice' else (), panel)
                checks = []
                for key in sorted(expected):
                    check = compare_one_arm(old, panel, numeric, key, projected[key], source, train, temporary, budget)
                    checks.append(check)
                    print(source, kind, key[0], key[1], 'PASS', flush=True)
                records.append({**info, 'checks': checks})
                del panel, projected
            shutil.rmtree(fixture_root)
        budget.check()
        peak = budget.peak
    if tested_source_identities() != source_identities:
        raise RuntimeError('Tested source identity changed during proof')
    result = {'state': 'PASS', 'execution_layout_only': True,
        'production_build_calls': 0, 'fit_calls': 0, 'study_text_encoding_calls': 0,
        'outcome_columns_read': [], 'seed': SEED, 'slice_rows': SLICE_ROWS,
        'spec_sha256': sha256(HERE / 'SPEC.md'), 'panel_manifest_sha256': sha256(manifest_path),
        'archived_builder_sha256': sha256(ARCHIVE), 'new_builder_sha256': sha256(ADAPTERS / 'features_adapter.py'),
        'feature_loader_sha256': sha256(ADAPTERS / 'feature_storage.py'),
        'tested_source_identities': source_identities,
        'temporary_limit_bytes': TEMP_LIMIT, 'temporary_peak_bytes': peak,
        'temporary_files_cleaned': True, 'synthetic_projection_checks': synthetic, 'host_input_slice_checks': records,
        'claim_scope': 'Bit-identical old/new storage for every registered arm/variant with real frozen numeric/P5MIN inputs and deterministic synthetic projection outputs; no production text feature construction or outcome analysis.'}
    atomic_json(args.out, result)
    print(json.dumps({'state': 'PASS', 'host_cases': sum(len(r['checks']) for r in records),
        'synthetic_cases': sum(len(r['checks']) for r in synthetic), 'temporary_peak_bytes': peak,
        'out': str(args.out)}))


if __name__ == '__main__':
    main()
