'Release mapped matrix pages while checking that their bytes are preserved.'
from pathlib import Path


class EvictionPreflightError(RuntimeError):
    'Input metadata.'


_LIBC = None
MAX_PREFLIGHT_BYTES = 64 * 1024**2
MS_INVALIDATE = 0x0002
MS_SYNC = 0x0010


def _msync(mapping):

    import ctypes
    import sys
    if sys.platform != 'darwin':
        raise OSError('DISKSET5 eviction requires the verified Darwin msync ABI')
    global _LIBC
    if _LIBC is None:
        _LIBC = ctypes.CDLL(None, use_errno=True)
        _LIBC.msync.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int)
        _LIBC.msync.restype = ctypes.c_int


    length = len(mapping)
    if length <= 0:
        raise ValueError('DLY8 cannot invalidate an empty backing mapping')
    buffer = (ctypes.c_char * length).from_buffer(mapping)
    try:
        ctypes.set_errno(0)
        result = _LIBC.msync(ctypes.addressof(buffer), length, MS_SYNC | MS_INVALIDATE)
        error = ctypes.get_errno()
    finally:
        del buffer
    if result != 0:
        import os
        raise OSError(error, 'DLY8 msync(MS_SYNC|MS_INVALIDATE) failed: '+os.strerror(error))


def evict(matrix):

    matrix.flush()
    _msync(matrix._mmap)


def install(features_module):

    if features_module._evict is evict:
        return features_module._evict
    original = features_module._evict
    features_module._evict = evict
    return original


def current_rss():
    import psutil
    return int(psutil.Process().memory_info().rss)


def _digest(matrix):
    import hashlib
    digest = hashlib.sha256()
    digest.update(matrix._mmap[:matrix.offset])

    for start in range(0, matrix.size, 16384):
        digest.update(matrix[start:start+16384].tobytes())
    return digest.hexdigest()


def preflight(*, scratch_root=None, size_bytes=MAX_PREFLIGHT_BYTES-128):

    import tempfile
    import numpy as np
    import sys
    if sys.platform != 'darwin':
        raise EvictionPreflightError('DLY8 eviction preflight requires Darwin')
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or not 16*1024**2 <= size_bytes <= MAX_PREFLIGHT_BYTES-128:
        raise EvictionPreflightError('Preflight data must be 16 MiB..64 MiB minus its NPY header')
    parent = Path(scratch_root or '/private/tmp').resolve()
    if not parent.is_relative_to(Path('/private/tmp')) or not parent.is_dir():
        raise EvictionPreflightError('Preflight scratch must be an existing directory under /private/tmp')
    matrix = None
    try:
        with tempfile.TemporaryDirectory(prefix='diskset5_preflight_', dir=parent) as directory:
            baseline = current_rss()
            matrix = np.lib.format.open_memmap(Path(directory)/'mapping.npy', mode='w+', dtype='uint8', shape=(size_bytes,))
            mapping_bytes = len(matrix._mmap)
            if mapping_bytes > MAX_PREFLIGHT_BYTES:
                raise EvictionPreflightError('Preflight backing mapping exceeds 64 MiB')

            for start in range(0, size_bytes, 65536):
                stop = min(size_bytes, start+65536)
                matrix[start:stop] = np.arange(stop-start, dtype='uint8')
            written = _digest(matrix)
            resident = current_rss()
            evict(matrix)
            released = current_rss()
            minimum_drop = size_bytes // 2
            headroom = 16*1024**2
            if resident-baseline < minimum_drop or resident-released < minimum_drop or released > baseline+headroom:
                raise EvictionPreflightError('Patched eviction did not release resident pages: '+repr(dict(
                    baseline_rss_bytes=baseline, touched_rss_bytes=resident, invalidated_rss_bytes=released,
                    required_drop_bytes=minimum_drop, allowed_headroom_bytes=headroom)))
            after = _digest(matrix)
            if written != after:
                raise EvictionPreflightError('Patched eviction changed memmap bytes')

            evict(matrix)
            matrix._mmap.close()
            matrix = None
            return dict(state='PASS',mapping_data_bytes=size_bytes,mapping_bytes=mapping_bytes,
                        baseline_rss_bytes=baseline,touched_rss_bytes=resident,
                        invalidated_rss_bytes=released,rss_drop_bytes=resident-released,
                        required_drop_bytes=minimum_drop,allowed_headroom_bytes=headroom,
                        bytes_sha256=written,bytes_preserved=True,temporary_removed=True,
                        remedy_operations=0,production_writes=0)
    except EvictionPreflightError:
        raise
    except Exception as exc:
        raise EvictionPreflightError('DLY8 eviction preflight failed: '+repr(exc)) from exc
    finally:
        if matrix is not None and not matrix._mmap.closed:
            matrix._mmap.close()
