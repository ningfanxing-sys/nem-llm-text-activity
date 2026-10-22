'Read and compare saved computation records.'
import hashlib
import json
import os
from pathlib import Path
import stat

class ContractError(PermissionError):
    pass

def _canonical(value, root=None, *, regular=False):
    raw=os.fsdecode(os.fspath(value));p=Path(raw)
    if not p.is_absolute() or raw!=str(p) or '..' in p.parts:
        raise ContractError('Noncanonical path/alias')
    if root is not None and not p.is_relative_to(Path(root)):
        raise ContractError('Path outside approved root')
    for part in (*reversed(p.parents),p):
        try:s=part.lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(s.st_mode):raise ContractError('Symlink component: '+str(part))
    if regular and not stat.S_ISREG(p.lstat().st_mode):raise ContractError('Not a regular file')
    return p

def _identity(path, root):
    p=_canonical(path,root,regular=True);h=hashlib.sha256();size=0
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        start=os.fstat(fd)
        with os.fdopen(fd,'rb',closefd=False) as stream:
            for block in iter(lambda:stream.read(1<<20),b''):h.update(block);size+=len(block)
        end=os.fstat(fd)
        if (start.st_dev,start.st_ino,start.st_size,start.st_mtime_ns)!=(end.st_dev,end.st_ino,end.st_size,end.st_mtime_ns):
            raise ContractError('File changed while hashing')
    finally:os.close(fd)
    return dict(path=str(p),bytes=size,sha256=h.hexdigest())

def _snapshot(item,root):
    if not isinstance(item,dict) or set(item)!={'path','bytes','sha256'} or type(item['bytes']) is not int:
        raise ContractError('Exact path/bytes/SHA required')
    p=_canonical(item['path'],root,regular=True)
    if _identity(p,root)!=item:raise ContractError('Identity drift')
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        with os.fdopen(fd,'rb',closefd=False) as f:b=f.read()
    finally:os.close(fd)
    if len(b)!=item['bytes'] or hashlib.sha256(b).hexdigest()!=item['sha256']:raise ContractError('Snapshot drift')
    return b

def _json(payload):
    def pairs(rows):
        d={}
        for k,v in rows:
            if k in d:raise ContractError('Duplicate JSON key')
            d[k]=v
        return d
    def invalid(x):raise ContractError('Nonfinite JSON')
    return json.loads(payload,object_pairs_hook=pairs,parse_constant=invalid)

def _write_exclusive(path,value,root):
    p=_canonical(path,root);p.parent.mkdir(parents=True,exist_ok=True);_canonical(p.parent,root)
    blob=(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'wb',closefd=False) as f:f.write(blob);f.flush();os.fsync(fd)
    finally:os.close(fd)
    return _identity(p,root)

def _phase(project,synthetic):
    phase=os.environ.get('SCORING_PHASE','prepare');p=_canonical(project)
    if phase=='prepare':raise ContractError('Prepare prohibits runtime, payload reads, suites and commands')
    if phase=='accept':
        if not synthetic or not p.is_relative_to(Path('/private/tmp')):raise ContractError('Accept is artificial only')
        marker=p/'SYNTHETIC_ONLY.json';_canonical(marker,p,regular=True)
        if _json(marker.read_bytes())!={'synthetic_only':True}:raise ContractError('Explicit artificial marker required')
    elif phase!='source_runtime' or synthetic:
        raise ContractError('Separate source runtime release required')
    return phase
