'Read bounded metadata files and compare their source hashes.'
from pathlib import Path
from contextvars import ContextVar
import hashlib
import json
import os
import re
import resource
import stat
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
OUT = Path(__file__).resolve().parents[1]
PROJ = OUT.parents[3]
Q = PROJ / 'studies'
confirmation = Q / 'confirmation'
AD = confirmation / 'ANCHORDIAG'
CODE_ROOT = Q / 'batch_estimation/fitting'
B = CODE_ROOT
X2 = confirmation / 'execution'
PRIMARY = ('N', 'M_notice', 'L14', 'L_Laz', 'L_chen_notice')
SEED = 20260919
KEYS = ['origin', 'target_time', 'region', 'horizon']
VALUES = ('prediction', 'raw_prediction', 'lower_bound', 'upper_bound')
SCRATCH_LIMIT = 1_000_000_000
_DIRECTORY_METADATA_REQUEST = ContextVar('forecast_binding_directory_metadata_request', default=None)

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()

def identity(path, **extra):
    p = Path(path).resolve()
    return dict(path=str(p), bytes=p.stat().st_size, sha256=sha(p), **extra)

def checked(item):
    p = Path(item['path']).resolve()
    require(p.is_file() and p.stat().st_size == item['bytes'] and sha(p) == item['sha256'],
            'Bound input drift: '+str(p))
    return p

def read_json(path):
    return json.loads(Path(path).read_text())

def write_json(path, value):

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()
    fd, temp = tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.link(temp, path)
    finally:
        os.unlink(temp)

def resources(scratch=None):
    require(os.getpriority(os.PRIO_PROCESS, 0) == 20, 'Actual nice 20 is required')
    if sys.platform == 'darwin':
        output = subprocess.check_output(['/usr/bin/memory_pressure', '-Q'], text=True)
        match = re.search(r'free percentage: (\d+)%', output)
        require(match is not None, 'Cannot verify memory free percentage')
        free = int(match[1])
    else:
        import psutil
        mem = psutil.virtual_memory(); free = 100*mem.available/mem.total
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != 'darwin':
        peak *= 1024
    require(free >= 25, 'System memory free is below 25%; stop and retain partial evidence')
    require(peak < 1_500_000_000, 'One-process peak RSS exceeds 1.5 GB')
    size = sum(p.stat().st_size for p in Path(scratch).rglob('*') if p.is_file()) if scratch else 0
    require(size < SCRATCH_LIMIT, 'Scratch is at least 1 GB')
    return dict(nice=20, memory_free_percent=free, peak_rss_bytes=int(peak), scratch_bytes=size)

def open_directory_metadata(name, *, dir_fd=None, parent_path=None):

    require(all(hasattr(os,n) for n in ('O_DIRECTORY','O_NOFOLLOW','O_CLOEXEC')),
            'Cannot certify before-T5: no-follow directory API missing')
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
    if dir_fd is None:
        require(name=='/' and parent_path is None,'Metadata traversal must begin at filesystem root')
        absolute='/'
    else:
        require(isinstance(name,str) and name not in ('','.','..') and '/' not in name and '\x00' not in name,
                'Unsafe directory metadata component')
        require(isinstance(parent_path,str) and parent_path.startswith('/')
                and os.path.normpath(parent_path)==parent_path,'Unverified metadata parent path')
        require(stat.S_ISDIR(os.fstat(dir_fd).st_mode),'Metadata parent is not a directory FD')
        absolute=os.path.join(parent_path,name)
    token=_DIRECTORY_METADATA_REQUEST.set((name,flags,absolute))
    try:
        return os.open(name,flags) if dir_fd is None else os.open(name,flags,dir_fd=dir_fd)
    finally:
        _DIRECTORY_METADATA_REQUEST.reset(token)

def install_audit(synthetic=False, source_only=False):

    reads = set()
    def hook(event, args):
        if event != 'open' or not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        request=_DIRECTORY_METADATA_REQUEST.get()
        if request is not None and os.fsdecode(args[0])==request[0] and args[1] is None and args[2]==request[1]:
            p=Path(request[2])
            if synthetic or source_only:
                require(p in (Path('/'),Path('/private'),Path('/private/tmp'))
                        or p.is_relative_to(Path('/private/tmp')),
                        'Build/test directory metadata escaped private synthetic trees')
            if p.is_relative_to(PROJ):reads.add(str(p))
            return
        p = Path(os.fsdecode(args[0])).resolve()
        if p == Path('/dev/null'):
            return
        mode, flags = args[1:3]
        writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC))
        require(p.name not in {'.env', 'auth.json', '.netrc'} and '/Keychains/' not in str(p)
                and '/semantic_validation/private/' not in str(p), 'Protected input')
        if writing:
            require(p.is_relative_to(OUT) or p.is_relative_to(Path('/private/tmp')), 'Write escaped forecast_hashes')
        elif p.is_relative_to(PROJ):
            if synthetic or source_only:
                require('host_state' not in p.parts, 'Build/test cannot open host_state')
                require(not p.name.startswith('SEAL') and (p.suffix in {'.py','.md','.sh'} or 'prediction' not in p.name.lower())
                        and not any(s in p.parts for s in ('scored','scores','evaluation','run')),
                        'Build/test cannot open real seals/predictions/scores')
                require(p.suffix in {'.py','.md','.sh','.json'} or (source_only and p == Q/'notice_extraction/scope.jsonl'),
                        'Build/test data read outside source whitelist')
            reads.add(str(p))
    sys.addaudithook(hook)
    return reads

def dly_module():
    sys.path.insert(0, str(CODE_ROOT/'code'))
    import rebuild_delayed_features
    return rebuild_delayed_features
