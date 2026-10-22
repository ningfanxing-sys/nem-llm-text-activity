"""Mechanical CONF feature storage and bounded, bit-preserving row assembly.

No feature value is calculated here. The source-wide numeric matrix and each
arm's extra matrix retain the unpruned float32 values. The frozen order sidecar
records the existing training-only pruning; loading selects those same columns.
Legacy physical, already-pruned matrices remain readable.
"""
from __future__ import annotations

from collections.abc import MutableMapping
from pathlib import Path
import shutil

import numpy as np

from runtime import read_json, sha256


FEATURE_HEADROOM_BYTES = 4 * 1024**3
FIT_HEADROOM_BYTES = 3 * 1024**3
_ORDER_FIELDS = ('shared_columns', 'extra_columns', 'original_columns',
                 'keep_indices', 'columns', 'pruned_names')


class DiskSpaceError(RuntimeError):
    """The complete remaining allocation plus headroom cannot fit on disk."""


def require_disk_space(path, planned_bytes, headroom_bytes, stage):
    """Check the target filesystem without creating the target or any file.

    ``planned_bytes`` must include every remaining output of the stage, rather
    than just its next individual bundle. Equality with the requirement passes.
    The nearest existing ancestor supports checking a fresh output directory.
    """
    planned_bytes = int(planned_bytes)
    headroom_bytes = int(headroom_bytes)
    if planned_bytes < 0 or headroom_bytes < 0:
        raise ValueError('Disk space budgets must be nonnegative')
    target = Path(path).resolve()
    existing = target
    while not existing.exists():
        parent = existing.parent
        if parent == existing:
            raise FileNotFoundError('No existing disk-space ancestor: ' + str(target))
        existing = parent
    free = int(shutil.disk_usage(existing).free)
    required = planned_bytes + headroom_bytes
    result = {'stage': str(stage), 'path': str(target),
              'filesystem_probe_path': str(existing), 'free_bytes': free,
              'planned_bytes': planned_bytes, 'headroom_bytes': headroom_bytes,
              'required_bytes': required}
    if free < required:
        raise DiskSpaceError(
            f'Disk space guard stopped {stage} before output writes: '
            f'{free:,} bytes free; {planned_bytes:,} bytes planned for all '
            f'remaining outputs + {headroom_bytes:,} bytes headroom = '
            f'{required:,} bytes required on {existing}. '
            'Free disk space (including emptying the Trash) and resume the same command.')
    return result


def _deduplicated(bundle):
    return 'shared_numeric' in bundle or 'extras_matrix' in bundle


def bundle_storage_identities(bundle):
    """Return all physical feature identities, excluding the virtual matrix."""
    if _deduplicated(bundle):
        return [bundle[key] for key in ('shared_numeric', 'extras_matrix', 'feature_order')]
    return [bundle['matrix']]


def bundle_storage_paths(bundle):
    """Return unique physical storage paths, including the order sidecar."""
    return list(dict.fromkeys(Path(item['path']) for item in bundle_storage_identities(bundle)))


def _verify_identity(item, seen):
    path = Path(item['path']).resolve()
    signature = (item['sha256'], int(item['bytes']))
    if isinstance(seen, MutableMapping):
        previous = seen.get(str(path))
        if previous is not None:
            if previous != signature:
                raise PermissionError('Conflicting feature identity: ' + str(path))
            # Stat remains cheap and rejects deletion/truncation after verification.
            if not path.is_file() or path.stat().st_size != signature[1]:
                raise PermissionError('Feature bytes drift: ' + str(path))
            return
    elif seen is not None and (str(path), *signature) in seen:
        if not path.is_file() or path.stat().st_size != signature[1]:
            raise PermissionError('Feature bytes drift: ' + str(path))
        return
    if not path.is_file() or path.stat().st_size != signature[1] or sha256(path) != signature[0]:
        raise PermissionError('Feature bytes drift: ' + str(path))
    if isinstance(seen, MutableMapping):
        seen[str(path)] = signature
    elif seen is not None:
        seen.add((str(path), *signature))


def _open_array(identity):
    # Zero-column NPY files contain only a header. Avoid mmap corner cases on
    # platforms where mapping a zero-sized data region is unsupported.
    shape = identity.get('shape')
    mmap_mode = None if shape is not None and 0 in shape else 'r'
    array = np.load(identity['path'], mmap_mode=mmap_mode, allow_pickle=False)
    if array.ndim != 2 or array.dtype != np.dtype('float32'):
        raise ValueError('Feature matrix must be two-dimensional float32: ' + str(identity['path']))
    if shape is not None and list(array.shape) != list(shape):
        raise ValueError('Feature matrix shape drift: ' + str(identity['path']))
    if identity.get('dtype', 'float32') != 'float32':
        raise ValueError('Feature matrix declared dtype drift: ' + str(identity['path']))
    return array


def _validate_order(bundle):
    shared = list(bundle['shared_columns'])
    extras = list(bundle['extra_columns'])
    original = list(bundle['original_columns'])
    keep = list(bundle['keep_indices'])
    columns = list(bundle['columns'])
    pruned = list(bundle['pruned_names'])
    if original != shared + extras or len(set(original)) != len(original):
        raise ValueError('Feature original/shared/extra column order mismatch')
    if any(not isinstance(i, (int, np.integer)) or isinstance(i, bool)
           or i < 0 or i >= len(original) for i in keep):
        raise ValueError('Feature pruning indices are invalid')
    if keep != sorted(set(keep)):
        raise ValueError('Feature pruning indices do not preserve the frozen order')
    if columns != [original[i] for i in keep]:
        raise ValueError('Feature pruned column order mismatch')
    kept = set(keep)
    if pruned != [name for i, name in enumerate(original) if i not in kept]:
        raise ValueError('Feature pruned names mismatch')
    sidecar = read_json(bundle['feature_order']['path'])
    for key in _ORDER_FIELDS:
        if sidecar.get(key) != bundle[key]:
            raise ValueError('Feature order sidecar mismatch: ' + key)
    for key in ('source', 'arm', 'variant', 'rows'):
        if key in sidecar and sidecar[key] != bundle.get(key):
            raise ValueError('Feature order sidecar mismatch: ' + key)
    if sidecar.get('dtype', 'float32') != 'float32':
        raise ValueError('Feature order sidecar dtype drift')


def verify_bundle(bundle, seen=None):
    """Verify physical bytes, float32 shapes, feature order, and pruning.

    Passing one ``seen`` dictionary through a bank verifies each shared hash
    once and rejects contradictory identities. A set is also accepted for
    callers that only need duplicate-hash suppression.
    """
    for item in bundle_storage_identities(bundle):
        _verify_identity(item, seen)
    if _deduplicated(bundle):
        _validate_order(bundle)
        shared = _open_array(bundle['shared_numeric'])
        extras = _open_array(bundle['extras_matrix'])
        expected_rows = int(bundle['rows'])
        if shared.shape != (expected_rows, len(bundle['shared_columns'])):
            raise ValueError('Shared feature block dimensions mismatch')
        if extras.shape != (expected_rows, len(bundle['extra_columns'])):
            raise ValueError('Extra feature block dimensions mismatch')
        virtual = bundle['matrix']
        if 'path' in virtual or virtual.get('dtype') != 'float32' or \
                list(virtual.get('shape', [])) != [expected_rows, len(bundle['columns'])]:
            raise ValueError('Virtual feature matrix dimensions/dtype mismatch')
    else:
        matrix = _open_array(bundle['matrix'])
        expected_rows = int(bundle.get('rows', matrix.shape[0]))
        if matrix.shape != (expected_rows, len(bundle['columns'])):
            raise ValueError('Legacy feature matrix dimensions mismatch')
    return bundle


def _normalise_rows(rows, nrows):
    if isinstance(rows, slice):
        start, stop, step = rows.indices(nrows)
        return rows, len(range(start, stop, step))
    if isinstance(rows, (int, np.integer)):
        rows = np.array([rows], dtype=np.int64)
    else:
        rows = np.asarray(rows)
    if rows.ndim != 1:
        raise ValueError('Feature row selector must be one-dimensional')
    if rows.dtype == np.bool_:
        if len(rows) != nrows:
            raise ValueError('Feature boolean row mask length mismatch')
        selected = np.flatnonzero(rows)
        return selected, len(selected)
    if rows.size == 0:
        return np.empty(0, dtype=np.int64), 0
    if not np.issubdtype(rows.dtype, np.integer):
        raise ValueError('Feature row indices must be integers')
    if np.any(rows >= nrows) or np.any(rows < -nrows):
        raise IndexError('Feature row index out of bounds')
    return rows, len(rows)


def load_feature_rows(bundle, rows, columns=None):
    """Assemble only requested rows/columns, preserving every float32 bit.

    By default this returns the original training-only pruned order. Explicit
    names permit another existing column order, including unpruned columns in
    deduplicated bundles. Array assignment copies bits without casting or
    arithmetic, retaining signed zeros and NaN payloads.

    The bank verifies identities once before fit stages with ``verify_bundle``;
    this hot loader checks header shapes and names without rehashing large files.
    """
    selected = list(bundle['columns'] if columns is None else columns)
    if _deduplicated(bundle):
        shared = _open_array(bundle['shared_numeric'])
        extras = _open_array(bundle['extras_matrix'])
        nrows = int(bundle['rows'])
        if shared.shape != (nrows, len(bundle['shared_columns'])) or \
                extras.shape != (nrows, len(bundle['extra_columns'])):
            raise ValueError('Feature storage dimensions mismatch')
        locations = {name: (shared, i) for i, name in enumerate(bundle['shared_columns'])}
        for i, name in enumerate(bundle['extra_columns']):
            if name in locations:
                raise ValueError('Duplicate physical feature column: ' + name)
            locations[name] = (extras, i)
    else:
        matrix = _open_array(bundle['matrix'])
        nrows = int(bundle.get('rows', matrix.shape[0]))
        if matrix.shape != (nrows, len(bundle['columns'])):
            raise ValueError('Legacy feature storage dimensions mismatch')
        locations = {name: (matrix, i) for i, name in enumerate(bundle['columns'])}
    if any(name not in locations for name in selected):
        missing = [name for name in selected if name not in locations]
        raise ValueError('Requested feature columns are unavailable: ' + repr(missing))
    selector, count = _normalise_rows(rows, nrows)
    output = np.empty((count, len(selected)), dtype=np.float32)
    groups = {}
    for destination, name in enumerate(selected):
        array, column = locations[name]
        group = groups.setdefault(id(array), (array, [], []))
        group[1].append(column)
        group[2].append(destination)
    # Read each physical source in bounded row blocks, avoiding both a full
    # unpruned copy and repeated strided disk scans for hundreds of columns.
    for start in range(0, count, 10000):
        stop = min(start+10000, count)
        if isinstance(selector, slice):
            first, _, step = selector.indices(nrows)
            block_rows = first + step*np.arange(start, stop, dtype=np.int64)
        else:
            block_rows = selector[start:stop]
        for array, physical_columns, destination_columns in groups.values():
            output[start:stop, destination_columns] = array[np.ix_(block_rows, physical_columns)]
    return output
