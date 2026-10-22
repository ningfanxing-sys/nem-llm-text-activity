# Check file access during synthetic numerical tests.
'Run synthetic tests with file-access checks.'
from __future__ import annotations
import argparse
import builtins
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import threading
import weakref
sys.dont_write_bytecode = True
_RUN_COUNT = 0
_INSTALLED = False
_ACTIVE = None
_AT_FDCWD = getattr(os, 'AT_FDCWD', -2 if sys.platform == 'darwin' else -100)
_EXTRA_METADATA = ('studies/batch_estimation/fitting/host_run_a8batch.sh', 'studies/batch_estimation/fitting/host_postscore_a8batch.sh', 'tables/table_results_templates.json', 'studies/confirmation/inference_design/AUTHOR_CONFIRMATION_A8_SCHEMA.json', 'studies/confirmation/inference_design/A8_FREEZE.json', 'studies/confirmation/robustness_tests/RULES_FOR_MAIN_COMPARISONS.json', 'studies/confirmation/sensitivity_tests/RULES_FOR_FILL3A.json', 'studies/confirmation/A6/RULES_FOR_SENSITIVITY_COMPARISONS.json')
_PRODUCTION_PARTS = {'state', 'host_state', 'dly8', 'cps8', 'scoring', 'scored', 'score', 'scores', 'models', 'model', 'sealed', 'predictions', 'prediction', 'evaluation', 'run', 'private'}

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def authority_metadata_rows(value,field):
    'Normalize saved path, byte-count and hash entries from a dictionary or list.'
    inventory=value.get(field,{})
    if isinstance(inventory,dict):return list(inventory.items())
    if isinstance(inventory,list):
        if any(not isinstance(row,dict) or set(row)!={'path','bytes','sha256'} for row in inventory):
            raise ValueError('Malformed exact frozen metadata list')
        names=[row['path'] for row in inventory]
        if any(not isinstance(n,str) or not Path(n).is_absolute() or n!=Path(n).as_posix() or '..' in Path(n).parts for n in names) or len(names)!=len(set(names)):
            raise ValueError('Frozen metadata list alias/duplicate')
        return [(row['path'],row) for row in inventory]
    raise ValueError('Unsupported frozen metadata inventory')

class ReviewIsolationError(PermissionError):
    pass

def current_isolator():
    if _ACTIVE is None:
        raise RuntimeError('No review isolator is installed')
    return _ACTIVE

class ReviewIsolator:


    def __init__(self, project, owned_root):
        self.project = Path(project).resolve(strict=True)
        self.code = self.project / 'studies/batch_estimation/batch_checks/statistics'
        self.owned = Path(owned_root).resolve(strict=True)
        if not self.owned.is_relative_to(Path('/private/tmp')):
            raise ValueError('Owned review root must be under /private/tmp')
        self.blocked = []
        self.read_paths = set()
        self.executed_source_paths = set()
        self.events = {'allowed_reads': 0, 'owned_writes': 0, 'directory_fd_resolutions': 0, 'memory_pressure_calls': 0, 'high_level_file_registrations': 0}
        self.fd = {}
        self.local = threading.local()
        self.original = {name: getattr(os, name) for name in ('open', 'close', 'dup', 'dup2', 'pipe', 'read', 'write', 'fstat', 'ftruncate')}
        if hasattr(os, 'pipe2'):
            self.original['pipe2'] = os.pipe2
        self.original['builtins.open'] = builtins.open
        self.original['io.open'] = io.open
        self.original_mkdtemp = tempfile.mkdtemp
        lock_path = self.code / 'SOURCE_LOCK.json'
        lock = json.loads(lock_path.read_bytes())
        self.pinned_roots = []
        self.fill_rel = None
        self.lock_sha256 = digest(lock_path)
        self.allowed = {lock_path}
        for rel, item in lock['sources'].items():
            path = self.project / rel
            if path.stat().st_size != item['identity']['bytes'] or digest(path) != item['identity']['sha256']:
                raise ValueError('Public source drift')
            self._approve_live(path)
        for rel, pin in json.loads((self.code / 'NUMERIC_ANCESTOR_PROPOSAL.json').read_bytes())['files'].items():
            path = self.project / rel
            if path.stat().st_size != pin['bytes'] or digest(path) != pin['sha256']:
                raise ValueError('Numeric ancestor drift')
            self._approve_live(path)
        for rel, pin in lock['authorities'].items():
            path = self.project / rel
            if path.stat().st_size != pin['bytes'] or digest(path) != pin['sha256']:
                raise ValueError('Code timestamp_checks drift')
            self._approve_live(path)
            value = json.loads(path.read_bytes())
            if rel.endswith('fitting/CODE_FREEZE.json'):
                row = value['test_receipts_provenance']['tests']
                p = Path(row['path'])
                if p != self.project / 'studies/batch_estimation/fitting/TEST_RESULTS.json' or p.stat().st_size != row['bytes'] or digest(p) != row['sha256']:
                    raise ValueError('Frozen numeric test source drift')
                self._approve_live(p)
            for field in ('files', 'code_sha256'):
                for name, pin in authority_metadata_rows(value,field):
                    p = path.parent / name
                    expected = pin if isinstance(pin, str) else pin.get('sha256')
                    if expected and self._inventory_metadata(p):
                        if digest(p) != expected:
                            raise ValueError('Code metadata drift')
                        self._approve_live(p)
        manifest = json.loads((self.code / 'PUBLIC_RUNTIME_SOURCE_MANIFEST.json').read_bytes())
        self._approve_live(self.code / 'PUBLIC_RUNTIME_SOURCE_MANIFEST.json')
        for rel, pin in manifest['files'].items():
            p = self.code / rel
            if p.stat().st_size != pin['bytes'] or digest(p) != pin['sha256']:
                raise ValueError('C exact source drift')
            self._approve_live(p)
        for rel,pin in json.loads((self.code / 'FIXTURE_PUBLIC_SOURCE_CENSUS.json').read_bytes())['files'].items():
            p=self.project/rel
            if p.stat().st_size!=pin['bytes'] or digest(p)!=pin['sha256']:raise ValueError('Fixture public source drift')
            self._approve_live(p)


        inventory_path=self.code/'INVENTORY.json'
        inventory_blob=inventory_path.read_bytes()
        inventory_digest=hashlib.sha256(inventory_blob).hexdigest()
        sidecar=self.code/'INVENTORY.sha256'
        if sidecar.read_text().strip()!=inventory_digest+'  INVENTORY.json':
            raise ValueError('Public package inventory sidecar drift')
        package=json.loads(inventory_blob)['files']
        self._approve_live(inventory_path);self._approve_live(sidecar)
        for name in json.loads((self.code/'FREEZE_CENSUS.json').read_bytes())['files']:
            if name in ('INVENTORY.json','INVENTORY.sha256'):continue
            pin=package.get(name)
            if pin is None:continue
            p=self.code/name
            if Path(name).is_absolute() or '..' in Path(name).parts or name!=Path(name).as_posix() or any(x.is_symlink() for x in (p,*p.parents)):
                raise ValueError('Public package inventory alias/symlink')
            if not self._inventory_metadata(p):raise ValueError('Non-public package census member')
            blob=p.read_bytes()
            if pin.get('path')!=str(p) or len(blob)!=pin['bytes'] or hashlib.sha256(blob).hexdigest()!=pin['sha256']:
                raise ValueError('Public package inventory member drift')
            self._approve_live(p)
        self.allowed_directories = {p.parent for p in self.allowed}
        self.allowed_directories.update({self.project, self.code, self.project / 'studies/batch_estimation/fitting/code', self.project / 'studies/batch_estimation/fitting/tests'})
        self.runtime = tuple((p.resolve(strict=False) for p in (Path(sys.base_prefix) / 'lib', Path(sys.prefix) / 'lib' / ('python' + str(sys.version_info.major) + '.' + str(sys.version_info.minor)) / 'site-packages')))
        self.infrastructure = {Path('/dev/null'), Path('/dev/urandom')}
        for descriptor in (1, 2):
            try:
                self._register(descriptor, None, 'stream', read=False, write=True)
            except OSError:
                pass

    def _approve_live(self, path):
        p = Path(os.path.abspath(os.fspath(path)))
        if not p.is_relative_to(self.project):
            raise ValueError('Allowlist path escapes the project: ' + str(p))
        rel = p.relative_to(self.project)
        if any((part.lower() in _PRODUCTION_PARTS for part in rel.parts)) or p.name in ('auth.json', '.env') or p.name.startswith('.env.'):
            raise ValueError('Production/protected path in allowlist: ' + str(p))
        resolved = p.resolve(strict=False)
        if not resolved.is_relative_to(self.project):
            raise ValueError('Allowlist symlink escapes the project: ' + str(p))
        if any((part.lower() in _PRODUCTION_PARTS for part in resolved.relative_to(self.project).parts)) or resolved.name in ('auth.json', '.env') or resolved.name.startswith('.env.'):
            raise ValueError('Allowlist symlink resolves to production/protected path: ' + str(p))
        self.allowed.add(resolved)

    def _inventory_path(self, path, *, pinned_source_form=False):

        raw = Path(path)
        if not raw.is_absolute():
            raise ValueError('Frozen inventory path must be absolute')
        cursor = Path(raw.anchor)
        for part in raw.parts[1:]:
            if cursor.is_symlink():
                raise ValueError('Frozen inventory symlink component: ' + str(cursor))
            cursor = cursor.parent if part == '..' else cursor / part
            if cursor.is_symlink():
                raise ValueError('Frozen inventory symlink component: ' + str(cursor))
        p = Path(os.path.abspath(raw))
        exact_form = pinned_source_form and any((p.is_relative_to(root) for root in self.pinned_roots)) and (p.suffix in ('.py', '.json', '.md', '.tex', '.sh', '.txt', '.log', '.sha256')) and (not any((part.lower() in _PRODUCTION_PARTS for part in p.relative_to(self.project).parts)))
        if not p.is_relative_to(self.project) or not (self._inventory_metadata(p) or exact_form) or (not p.is_file()):
            raise ValueError('Unsafe frozen metadata inventory path: ' + str(p))
        return p

    def _inventory_metadata(self, path):

        p = Path(path)
        if not p.is_relative_to(self.project):
            return False
        forbidden = _PRODUCTION_PARTS | {'.aws', '.llm_client', '.git', '__pycache__', 'a1_paper_not_frozen', 'run_null_ext'}
        parts = p.relative_to(self.project).parts
        if 'TIMESTAMPS' in parts or any((s.lower() in forbidden for s in parts)):
            return False
        if p.name.startswith(('.env', 'OPENED_PATHS')) or p.name in ('auth.json', '.DS_Store'):
            return False
        if re.search('(^|_)(model|models)(_|\\.|$)', p.name, re.I) and p.suffix not in ('.py', '.md'):
            return False
        if re.search('(^|_)(SEAL|SCORE_RECEIPT|A8_POSTSCORE|INPUTS_V2)(_|\\.|$)', p.name) or re.search('(^|_)predictions?(_|\\.|$)', p.name, re.I) or (p.suffix in ('.json', '.csv', '.jsonl') and re.search('(^|_)(SCORE|SCORES|SCORE_RECEIPT)(_|\\.|$)', p.name, re.I)):
            return False
        return p.suffix in ('.json', '.jsonl', '.md', '.py', '.sh', '.txt', '.csv', '.sha256', '.tsr', '.tsq', '.pem', '.crt')

    def _deny(self, event, path, reason):
        self.blocked.append({'event': event, 'path': str(path), 'reason': reason})
        raise ReviewIsolationError(reason + ': ' + str(path))

    def _descriptor(self, number, event):
        row = self.fd.get(number)
        if row is None:
            self._deny(event, 'fd:' + str(number), 'Unknown descriptor')
        owner_ref = row.get('owner')
        if owner_ref is not None:
            owner = owner_ref()
            if owner is None or owner.closed:
                self.fd.pop(number, None)
                self._deny(event, 'fd:' + str(number), 'Closed high-level file owner')
        try:
            s = self.original['fstat'](number)
        except OSError:
            self.fd.pop(number, None)
            self._deny(event, 'fd:' + str(number), 'Closed descriptor')
        if (s.st_dev, s.st_ino, stat.S_IFMT(s.st_mode)) != row['identity']:
            self.fd.pop(number, None)
            self._deny(event, 'fd:' + str(number), 'Reused descriptor identity')
        return row

    def _register(self, number, path, kind, *, read, write, owner=None):
        s = self.original['fstat'](number)
        self.fd[number] = dict(path=path, kind=kind, read=read, write=write, identity=(s.st_dev, s.st_ino, stat.S_IFMT(s.st_mode)), owner=weakref.ref(owner) if owner is not None else None)

    def canonical(self, token, dir_fd=None, *, event='path'):
        base = None
        if dir_fd is not None and dir_fd != _AT_FDCWD:
            base = self._descriptor(dir_fd, event)
            if base['kind'] != 'directory':
                self._deny(event, 'fd:' + str(dir_fd), 'Relative path needs directory descriptor')
        if isinstance(token, int):
            row = self._descriptor(token, event)
            if row['kind'] != 'directory':
                self._deny(event, 'fd:' + str(token), 'Descriptor is not a directory')
            return row['path']
        if not isinstance(token, (str, bytes, os.PathLike)):
            self._deny(event, repr(token), 'Unrecognized pathname')
        text = os.fsdecode(token)
        if os.path.isabs(text):
            p = Path(os.path.normpath(text))
        elif dir_fd is None or dir_fd == _AT_FDCWD:
            p = Path(os.path.abspath(text))
        else:
            p = Path(os.path.normpath(os.path.join(base['path'], text)))
            self.events['directory_fd_resolutions'] += 1
        if p.is_relative_to(self.project) and any((x.lower() in _PRODUCTION_PARTS for x in p.relative_to(self.project).parts)):
            self._deny(event, p, 'Live production/protected path')
        if p.name == 'auth.json' or p.name == '.env' or p.name.startswith('.env.'):
            self._deny(event, p, 'Credential/protected pathname')
        resolved = p.resolve(strict=False)
        if resolved.is_relative_to(self.project) and any((x.lower() in _PRODUCTION_PARTS for x in resolved.relative_to(self.project).parts)):
            self._deny(event, resolved, 'Resolved live production/protected path')
        if resolved.name == 'auth.json' or resolved.name == '.env' or resolved.name.startswith('.env.'):
            self._deny(event, resolved, 'Resolved credential/protected pathname')
        return resolved

    def check(self, token, *, write=False, directory=False, dir_fd=None, event='path'):
        p = self.canonical(token, dir_fd, event=event)
        if p.is_relative_to(self.owned):
            self.events['owned_writes' if write else 'allowed_reads'] += 1
            if not write and not directory:self.read_paths.add(str(p))
            return p
        if write:
            self._deny(event, p, 'Write outside exclusively owned review root')
        if p.is_relative_to(self.project):
            if p in (self.allowed_directories if directory else self.allowed):
                self.events['allowed_reads'] += 1
                if not directory:self.read_paths.add(str(p))
                return p
            self._deny(event, p, 'Unapproved live project contents or enumeration')
        if any((p.is_relative_to(root) for root in self.runtime)) or p in self.infrastructure:
            self.events['allowed_reads'] += 1
            return p
        self._deny(event, p, 'Read outside source/runtime/owned roots')

    @staticmethod
    def writing(mode, flags):
        return isinstance(mode, str) and any((c in mode for c in 'wax+')) or (isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))

    @staticmethod
    def audit_dir_fd(value):

        return None if value == -1 else value

    def audit(self, event, args):
        if event == 'exec':
            name=getattr(args[0],'co_filename','')
            if name and Path(name).is_absolute():self.executed_source_paths.add(name)
        elif event == 'open':
            token, mode, flags = args
            writing = self.writing(mode, flags)
            if isinstance(token, int):
                row = self._descriptor(token, event)
                if not row['write' if writing else 'read']:
                    self._deny(event, 'fd:' + str(token), 'Descriptor access not authorized')
                return
            context = getattr(self.local, 'open_path', None)
            self.check(context if context is not None else token, write=writing, event=event)
        elif event in ('os.listdir', 'os.scandir'):
            self.check(args[0] if args and args[0] is not None else '.', directory=True, event=event)
        elif event in ('os.remove', 'os.rmdir'):
            self.check(args[0], write=True, dir_fd=self.audit_dir_fd(args[1]), event=event)
        elif event == 'os.mkdir':
            self.check(args[0], write=True, dir_fd=self.audit_dir_fd(args[2]), event=event)
        elif event in ('os.rename', 'os.link'):
            self.check(args[0], write=True, dir_fd=self.audit_dir_fd(args[2]), event=event)
            self.check(args[1], write=True, dir_fd=self.audit_dir_fd(args[3]), event=event)
        elif event == 'os.symlink':
            destination = self.check(args[1], write=True, dir_fd=self.audit_dir_fd(args[2]), event=event)
            source = Path(os.fsdecode(args[0]))
            self.check(source if source.is_absolute() else destination.parent / source, write=True, event=event)
        elif event in ('os.chmod', 'os.utime'):
            self.check(args[0], write=True, dir_fd=self.audit_dir_fd(args[-1]), event=event)
        elif event == 'os.chown':
            self.check(args[0], write=True, dir_fd=self.audit_dir_fd(args[3]), event=event)
        elif event in ('os.truncate', 'os.setxattr', 'os.removexattr'):
            if isinstance(args[0], int):
                row = self._descriptor(args[0], event)
                if not row['write'] or row['path'] is None:
                    self._deny(event, 'fd:' + str(args[0]), 'Descriptor mutation not authorized')
                self.check(row['path'], write=True, event=event)
            else:
                self.check(args[0], write=True, event=event)
        elif event in ('shutil.rmtree',):
            self.check(args[0], write=True, dir_fd=self.audit_dir_fd(args[1]), event=event)
        elif event in ('shutil.copyfile', 'shutil.copymode', 'shutil.copystat'):
            self.check(args[0], event=event)
            self.check(args[1], write=True, event=event)
        elif event == 'shutil.copytree':
            self.check(args[0], directory=True, event=event)
            self.check(args[1], write=True, event=event)
        elif event in ('tempfile.mkdtemp', 'tempfile.mkstemp'):
            self.check(args[0], write=True, event=event)
        elif event == 'os.chdir':
            self.check(args[0], write=True, directory=True, event=event)
        elif event == 'subprocess.Popen':
            executable, command, cwd, _environment = args
            if os.fsdecode(executable) != '/usr/bin/memory_pressure' or list(command) != ['/usr/bin/memory_pressure']:
                self._deny(event, executable, 'Only memory_pressure subprocess is permitted')
            if cwd is not None:
                self.check(cwd, write=True, directory=True, event=event)
            self.events['memory_pressure_calls'] += 1
        elif event == 'os.posix_spawn':
            if os.fsdecode(args[0]) != '/usr/bin/memory_pressure' or list(args[1]) != ['/usr/bin/memory_pressure']:
                self._deny(event, args[0], 'Only memory_pressure subprocess is permitted')
        elif event == 'mmap.__new__' and args[0] != -1:
            row = self._descriptor(args[0], event)
            if not row['read']:
                self._deny(event, 'fd:' + str(args[0]), 'Mapping unreadable descriptor')
            if args[2] in (0, 2):
                if not row['write'] or row['path'] is None:
                    self._deny(event, 'fd:' + str(args[0]), 'Writable mapping not authorized')
                self.check(row['path'], write=True, event=event)
        elif event in ('os.system', 'os.exec', 'os.startfile', 'os.fork', 'os.forkpty', 'socket.__new__', 'socket.connect'):
            self._deny(event, repr(args[:2]), 'Production execution/network is outside review')

    def install(self):
        global _INSTALLED, _ACTIVE
        if _INSTALLED:
            raise RuntimeError('Review isolator cannot be installed twice')
        _INSTALLED = True
        _ACTIVE = self
        sys.modules['consumer_review_isolator'] = sys.modules[__name__]
        guard = self

        def guarded_high_level_open(original, token, *args, **kwargs):
            mode = args[0] if args else kwargs.get('mode', 'r')
            wants_read = isinstance(mode, str) and ('r' in mode or '+' in mode)
            wants_write = guard.writing(mode, None)
            previous_row = None
            if isinstance(token, int):
                previous_row = guard._descriptor(token, 'high_level_open')
                if wants_read and (not previous_row['read']) or (wants_write and (not previous_row['write'])):
                    guard._deny('high_level_open', 'fd:' + str(token), 'Descriptor access not authorized')
                path = previous_row['path']
            else:
                path = guard.check(token, write=wants_write, event='high_level_open')
            stream = original(token, *args, **kwargs)
            try:
                number = stream.fileno()
                readable, writable = (stream.readable(), stream.writable())
                if previous_row is not None:
                    guard._descriptor(number, 'high_level_open')
                    if readable and (not previous_row['read']) or (writable and (not previous_row['write'])):
                        guard._deny('high_level_open', 'fd:' + str(number), 'Returned file escalates descriptor access')
                    return stream
                opener = args[6] if len(args) > 6 else kwargs.get('opener')
                if opener is not None:
                    row = guard._descriptor(number, 'high_level_open')
                    if row['path'] != path or (readable and (not row['read'])) or (writable and (not row['write'])):
                        guard._deny('high_level_open', 'fd:' + str(number), 'Custom opener descriptor differs from checked path')
                s = guard.original['fstat'](number)
                kind = 'directory' if stat.S_ISDIR(s.st_mode) else 'file'
                guard._register(number, path, kind, read=readable, write=writable, owner=stream)
                guard.events['high_level_file_registrations'] += 1
                return stream
            except BaseException:
                stream.close()
                raise

        def guarded_open(path, flags, mode=511, *, dir_fd=None):
            canonical = guard.check(path, write=guard.writing(None, flags), dir_fd=dir_fd, event='os.open')
            previous = getattr(guard.local, 'open_path', None)
            guard.local.open_path = canonical
            try:
                result = guard.original['open'](path, flags, mode, dir_fd=dir_fd)
            finally:
                guard.local.open_path = previous
            s = guard.original['fstat'](result)
            kind = 'directory' if stat.S_ISDIR(s.st_mode) else 'file'
            access = flags & os.O_ACCMODE
            guard._register(result, canonical, kind, read=access != os.O_WRONLY, write=access != os.O_RDONLY)
            return result

        def guarded_close(fd):
            guard._descriptor(fd, 'os.close')
            try:
                return guard.original['close'](fd)
            finally:
                guard.fd.pop(fd, None)

        def guarded_dup(fd):
            row = guard._descriptor(fd, 'os.dup')
            result = guard.original['dup'](fd)
            guard._register(result, row['path'], row['kind'], read=row['read'], write=row['write'])
            return result

        def guarded_dup2(fd, fd2, inheritable=True):
            row = guard._descriptor(fd, 'os.dup2')
            if fd2 in (0, 1, 2):
                guard._deny('os.dup2', 'fd:' + str(fd2), 'Cannot replace initial standard descriptor')
            result = guard.original['dup2'](fd, fd2, inheritable=inheritable)
            guard._register(result, row['path'], row['kind'], read=row['read'], write=row['write'])
            return result

        def pipe_result(result):
            guard._register(result[0], None, 'pipe', read=True, write=False)
            guard._register(result[1], None, 'pipe', read=False, write=True)
            return result

        def guarded_read(fd, length):
            if not guard._descriptor(fd, 'os.read')['read']:
                guard._deny('os.read', 'fd:' + str(fd), 'Descriptor is not readable')
            return guard.original['read'](fd, length)

        def guarded_write(fd, data):
            if not guard._descriptor(fd, 'os.write')['write']:
                guard._deny('os.write', 'fd:' + str(fd), 'Descriptor is not writable')
            return guard.original['write'](fd, data)

        def guarded_ftruncate(fd, length):
            row = guard._descriptor(fd, 'os.ftruncate')
            if not row['write'] or row['path'] is None:
                guard._deny('os.ftruncate', 'fd:' + str(fd), 'Descriptor cannot truncate')
            guard.check(row['path'], write=True, event='os.ftruncate')
            return guard.original['ftruncate'](fd, length)

        def guarded_builtin_open(file, *args, **kwargs):
            return guarded_high_level_open(guard.original['builtins.open'], file, *args, **kwargs)

        def guarded_io_open(file, *args, **kwargs):
            return guarded_high_level_open(guard.original['io.open'], file, *args, **kwargs)

        def owned_mkdtemp(suffix=None, prefix=None, dir=None):
            if dir is not None and Path(dir).resolve(strict=False) not in (Path('/private/tmp'), guard.owned):
                guard.check(dir, write=True, directory=True, event='tempfile.mkdtemp')
            return guard.original_mkdtemp(suffix=suffix, prefix=prefix, dir=guard.owned)
        os.open, os.close, os.dup, os.dup2 = (guarded_open, guarded_close, guarded_dup, guarded_dup2)
        os.pipe = lambda: pipe_result(guard.original['pipe']())
        if 'pipe2' in guard.original:
            os.pipe2 = lambda flags: pipe_result(guard.original['pipe2'](flags))
        os.read, os.write, os.ftruncate = (guarded_read, guarded_write, guarded_ftruncate)
        builtins.open, io.open = (guarded_builtin_open, guarded_io_open)
        tempfile.mkdtemp = owned_mkdtemp
        tempfile.tempdir = str(self.owned)
        os.environ['TMPDIR'] = str(self.owned)
        os.environ['MPLCONFIGDIR'] = str(self.owned / 'matplotlib_config')
        sys.addaudithook(self.audit)
        os.chdir(self.owned)

def main(argv=None):
    import os
    if os.environ.get('SCORING_PHASE','prepare')!='accept':raise PermissionError('Prepare cannot run the suite')
    from tests_science import main as run
    return run(argv)
if __name__=='__main__':raise SystemExit(main())
