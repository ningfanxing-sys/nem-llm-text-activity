'Read checked metadata files without following symbolic links.'
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import types
from science_contract import require

HERE = Path(__file__).absolute().parent
AF = HERE.parent
PROJ = AF.parents[3]
FORBIDDEN = {'host_state', 'state', 'predictions', 'scores', 'scored', 'models', 'outcomes', 'private'}


def phase(*, root=None, synthetic=False, source_flag=None):
    value = os.environ.get('SCORING_PHASE', 'prepare')
    require(value != 'prepare', 'Prepare rejects any action before request/fixture I/O')
    if value == 'accept':
        require(synthetic and root is not None and Path(root).is_relative_to('/private/tmp'),
                'Accept requires explicitly artificial private scratch')
        require(read_json(Path(root)/'SYNTHETIC_ONLY.json') == {'synthetic_only': True},
                'Artificial marker required')
    else:
        flags=source_flag if isinstance(source_flag,tuple) else (source_flag,)
        require(value == 'source_runtime' and not synthetic and any(
                flag and os.environ.get(flag)=='1' for flag in flags), 'Separate explicit source action required')
    return value


def canonical(value):
    raw = os.fsdecode(os.fspath(value)); p = Path(raw)
    require(p.is_absolute() and str(p) == raw and os.path.normpath(raw) == raw and '..' not in p.parts,
            'Canonical path required, no lexical alias')
    parts = p.relative_to('/private/tmp').parts if p.is_relative_to('/private/tmp') else p.parts
    require(not FORBIDDEN.intersection(parts) and not p.name.startswith(('SEAL', 'SCORE_RECEIPT')) and
            p.name != '.fitting.lock', 'Protected payload/lock is not source metadata')
    require(p.is_relative_to(PROJ) or p.is_relative_to('/private/tmp'), 'Metadata escaped source/scratch roots')
    return p


def snapshot(path, expected=None):
    p = canonical(path); handles=[]; edges=[]
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    key = lambda s: (s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid)
    try:
        handles.append(os.open('/',flags))
        for name in p.parts[1:-1]:
            parent=handles[-1]; reference_snapshot=os.stat(name,dir_fd=parent,follow_symlinks=False)
            require(stat.S_ISDIR(reference_snapshot.st_mode), 'Every directory component must exist and be real')
            fd=os.open(name,flags,dir_fd=parent);handles.append(fd)
            require(key(os.fstat(fd))==key(reference_snapshot),'Directory identity changed')
            edges.append((parent,name,fd,key(reference_snapshot)))
        parent=handles[-1];reference_snapshot=os.stat(p.name,dir_fd=parent,follow_symlinks=False)
        require(stat.S_ISREG(reference_snapshot.st_mode) and reference_snapshot.st_size<=32*1024*1024,'Regular bounded metadata required')
        fd=os.open(p.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent);handles.append(fd)
        require(key(os.fstat(fd))==key(reference_snapshot),'Leaf identity changed before read')
        chunks=[];size=0
        while True:
            b=os.read(fd,1<<20)
            if not b:break
            size+=len(b);require(size<=32*1024*1024,'Metadata grew beyond bound');chunks.append(b)
        after=os.fstat(fd)
        require(key(after)==key(reference_snapshot) and size==reference_snapshot.st_size==after.st_size and
                reference_snapshot.st_mtime_ns==after.st_mtime_ns and reference_snapshot.st_ctime_ns==after.st_ctime_ns,
                'Leaf changed while reading')
        require(key(os.stat(p.name,dir_fd=parent,follow_symlinks=False))==key(reference_snapshot),'Leaf name drift')
        for parent,name,fd,k in edges:
            require(key(os.fstat(fd))==k and key(os.stat(name,dir_fd=parent,follow_symlinks=False))==k,
                    'Directory ancestry drift')
        payload=b''.join(chunks);item=dict(path=str(p),bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())
        require(expected is None or item==expected,'Exact source/metadata bytes drift')
        return item,payload
    except (OSError,AttributeError,ValueError) as exc:
        raise PermissionError('Cannot certify metadata snapshot') from exc
    finally:
        for fd in reversed(handles):os.close(fd)


def identity(path):
    return snapshot(path)[0]


def decode(payload):
    def pairs(rows):
        out={}
        for k,v in rows:
            require(k not in out,'Duplicate JSON key');out[k]=v
        return out
    return json.loads(payload,object_pairs_hook=pairs,
        parse_constant=lambda v: (_ for _ in ()).throw(PermissionError('Nonfinite JSON')))


def read_json(path, expected=None):
    return decode(snapshot(path,expected)[1])


def load_source(name, path, expected=None, *, register=True):
    item,payload=snapshot(path,expected)
    require(Path(path).suffix=='.py','Source loader accepts only Python source')
    module=types.ModuleType(name);module.__file__=item['path']
    if register:sys.modules[name]=module
    exec(compile(payload,item['path'],'exec',dont_inherit=True),vars(module))
    snapshot(path,item)
    return module


def write_exclusive(path,value,*,root,synthetic=False,flag):
    phase(root=root,synthetic=synthetic,source_flag=flag)
    p=canonical(path);require(p.parent==Path(root),'Exclusive metadata output must be in exact owner root')
    payload=(json.dumps(value,indent=2,ensure_ascii=False,sort_keys=True,allow_nan=False)+'\n').encode()
    parent=canonical(p.parent);handles=[];edges=[]
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
    key=lambda v:(v.st_dev,v.st_ino,v.st_mode,v.st_uid,v.st_gid)
    try:
        handles.append(os.open('/',flags))
        for name in parent.parts[1:]:
            previous=handles[-1];reference_snapshot=os.stat(name,dir_fd=previous,follow_symlinks=False)
            require(stat.S_ISDIR(reference_snapshot.st_mode),'Real existing output ancestry required')
            fd=os.open(name,flags,dir_fd=previous);handles.append(fd)
            require(key(os.fstat(fd))==key(reference_snapshot),'Output parent identity drift')
            edges.append((previous,name,fd,key(reference_snapshot)))
        descriptor=os.open(p.name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o444,dir_fd=handles[-1])
        with os.fdopen(descriptor,'wb') as f:f.write(payload);f.flush();os.fsync(f.fileno())
        for previous,name,fd,k in edges:
            require(key(os.fstat(fd))==k and key(os.stat(name,dir_fd=previous,follow_symlinks=False))==k,
                    'Output ancestry changed during exclusive write')
    finally:
        for fd in reversed(handles):os.close(fd)
    return identity(p)
