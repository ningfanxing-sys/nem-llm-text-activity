"""Anonymous (non-file-backed) resident memory of a process (CONFX7; execution resources only).

The CONFX7 per-fit and task-tree memory guards measure the memory the operating system cannot reclaim:
- macOS: the physical footprint of `proc_pid_rusage(pid, RUSAGE_INFO_V4)`, `ri_phys_footprint` now, and
  `ri_lifetime_max_phys_footprint` as the worker's own peak.
- Linux: `RssAnon` from `/proc/<pid>/status` now, and `VmHWM` (total peak resident set) as a conservative peak.

Pages of memory-mapped files are not counted, because the OS can reclaim them. RSS stays recorded beside this
measure in every receipt. No study file is read.
"""
from __future__ import annotations
import ctypes
import os
import sys
from pathlib import Path

RULE = ('anonymous resident memory: macOS proc_pid_rusage RUSAGE_INFO_V4 ri_phys_footprint (current) and '
        'ri_lifetime_max_phys_footprint (worker peak); Linux /proc RssAnon (current) and VmHWM (conservative peak)')
RUSAGE_INFO_V4 = 4


class _RUsageInfoV4(ctypes.Structure):
    _fields_ = [('ri_uuid', ctypes.c_uint8 * 16)] + [(name, ctypes.c_uint64) for name in (
        'ri_user_time', 'ri_system_time', 'ri_pkg_idle_wkups', 'ri_interrupt_wkups', 'ri_pageins', 'ri_wired_size',
        'ri_resident_size', 'ri_phys_footprint', 'ri_proc_start_abstime', 'ri_proc_exit_abstime', 'ri_child_user_time',
        'ri_child_system_time', 'ri_child_pkg_idle_wkups', 'ri_child_interrupt_wkups', 'ri_child_pageins',
        'ri_child_elapsed_abstime', 'ri_diskio_bytesread', 'ri_diskio_byteswritten', 'ri_cpu_time_qos_default',
        'ri_cpu_time_qos_maintenance', 'ri_cpu_time_qos_background', 'ri_cpu_time_qos_utility', 'ri_cpu_time_qos_legacy',
        'ri_cpu_time_qos_user_initiated', 'ri_cpu_time_qos_user_interactive', 'ri_billed_system_time',
        'ri_serviced_system_time', 'ri_logical_writes', 'ri_lifetime_max_phys_footprint', 'ri_instructions', 'ri_cycles',
        'ri_billed_energy', 'ri_serviced_energy', 'ri_interval_max_phys_footprint', 'ri_runnable_time')]


_LIBPROC = None


def _rusage(pid):
    global _LIBPROC
    if _LIBPROC is None:
        _LIBPROC = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        _LIBPROC.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        _LIBPROC.proc_pid_rusage.restype = ctypes.c_int
    info = _RUsageInfoV4()
    if _LIBPROC.proc_pid_rusage(int(pid), RUSAGE_INFO_V4, ctypes.byref(info)) != 0:
        return None
    return info


def _status_field(pid, field):
    try:
        text = Path(f'/proc/{int(pid)}/status').read_text()
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith(field + ':'):
            return int(line.split()[1]) * 1024
    return None


def anonymous_bytes(pid):
    """Current anonymous resident bytes of `pid`; None if the process is gone or not readable."""
    if sys.platform == 'darwin':
        info = _rusage(pid)
        return None if info is None else int(info.ri_phys_footprint)
    return _status_field(pid, 'RssAnon')


def peak_anonymous_bytes_self():
    """The calling process's own peak anonymous bytes (macOS lifetime maximum; Linux VmHWM upper bound)."""
    if sys.platform == 'darwin':
        info = _rusage(os.getpid())
        return None if info is None else int(info.ri_lifetime_max_phys_footprint)
    return _status_field(os.getpid(), 'VmHWM')
