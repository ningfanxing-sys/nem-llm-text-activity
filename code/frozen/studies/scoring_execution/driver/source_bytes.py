'Compile numerical definitions from checked source snapshots.'
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys


class CoreStop(RuntimeError):
    pass


def require(ok, reason):
    if not ok:
        raise CoreStop(reason)


def identity(path):
    path = Path(path)
    data = path.read_bytes()
    return dict(path=str(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def checked(item):
    data = Path(item['path']).read_bytes()
    require(len(data) == item['bytes'] and hashlib.sha256(data).hexdigest() == item['sha256'],
            'K1 SOURCE_BYTES_DRIFT: ' + item['path'])
    return data


def document(item):
    return json.loads(checked(item))


class Sources:

    def __init__(self, rows):
        self.rows = {str(Path(x['logical_path']).absolute()): x for x in rows}
        require(len(self.rows) == len(rows), 'K1 duplicate logical source')
        self.snapshots = {p: checked(row) for p, row in self.rows.items()}
        self.loaded = set()

    def bytes(self, path):
        path = str(Path(path).absolute())
        require(path in self.rows, 'K1 UNLISTED_SOURCE: ' + path)
        return self.snapshots[path]

    def recheck(self):
        for path in self.rows:
            require(checked(self.rows[path]) == self.snapshots[path], 'K1 immutable snapshot changed')

    def module(self, name, path):
        path = str(Path(path).absolute())
        cached = sys.modules.get(name)
        if cached is not None:
            require(cached.__file__ == path and (path in self.loaded or
                    vars(cached).get('_minrun_source_sha256') == self.rows[path]['sha256']), 'K1 cached project module identity')
            self.bytes(path)
            return cached
        package = Path(path).name == '__init__.py'
        spec = importlib.util.spec_from_file_location(name, path,
                submodule_search_locations=[str(Path(path).parent)] if package else None)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        previous_path=sys.path[:]
        sys.path.insert(0,str(Path(path).parent))
        try:
            self.loaded.add(path)
            exec(compile(self.bytes(path), path, 'exec', dont_inherit=True), vars(module))
            module._minrun_source_sha256 = self.rows[path]['sha256']
        except BaseException:
            sys.modules.pop(name, None)
            raise
        finally:sys.path[:]=previous_path
        return module

    @contextlib.contextmanager
    def imports(self):

        original = importlib.machinery.SourceFileLoader.get_code
        reference_snapshot = dict(sys.modules)
        roots = {str(Path(p).parent) for p in self.rows}
        old_path = sys.path[:]
        names = {}
        for p in self.rows:
            path = Path(p)
            if path.suffix == '.py':
                name = path.parent.name if path.name == '__init__.py' else path.stem
                names.setdefault(name, []).append(p)
        sources = self
        class CatalogueFinder:
            def find_spec(self, fullname, path=None, target=None):


                if importlib.machinery.PathFinder.find_spec(fullname, path) is not None:
                    return None
                leaf = fullname.rsplit('.', 1)[-1]
                if path is None:
                    candidates = names.get(leaf, [])
                else:
                    candidates = [str(Path(root)/suffix) for root in path
                                  for suffix in (leaf+'.py', leaf+'/__init__.py')
                                  if str(Path(root)/suffix) in sources.rows]
                candidates = sorted(set(candidates))
                require(len(candidates) <= 1, 'K1 ambiguous lazy module: '+fullname)
                if not candidates:
                    return None
                filename = candidates[0]
                sources.bytes(filename)
                package = Path(filename).name == '__init__.py'
                return importlib.util.spec_from_file_location(fullname, filename,
                    submodule_search_locations=[str(Path(filename).parent)] if package else None)
        finder = CatalogueFinder()
        sys.meta_path.insert(0, finder)
        def get_code(loader, name):
            path = str(Path(loader.path))
            if path in self.rows:
                self.loaded.add(path)
                return compile(self.bytes(path), path, 'exec', dont_inherit=True)
            if any(Path(path).is_relative_to(Path(r)) for r in roots):
                raise CoreStop('K1 UNLISTED_SOURCE: ' + path)
            return original(loader, name)
        importlib.machinery.SourceFileLoader.get_code = get_code
        old_open, old_stat = Path.open, Path.stat
        def snapshot_open(p, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
            key = str(p.absolute())
            if key in self.snapshots and mode in ('r', 'rt', 'rb'):
                import io
                data = self.snapshots[key]
                return io.BytesIO(data) if 'b' in mode else io.StringIO(data.decode(__import__('locale').getencoding() if encoding == 'locale' else (encoding or 'utf-8'), errors or 'strict'), newline=newline)
            return old_open(p, mode, buffering, encoding, errors, newline)
        def snapshot_stat(p, *args, **kwargs):
            row = self.rows.get(str(p.absolute()))
            return old_stat(Path(row['path']), *args, **kwargs) if row else old_stat(p, *args, **kwargs)
        Path.open, Path.stat = snapshot_open, snapshot_stat
        try:
            yield self
        finally:
            Path.open, Path.stat = old_open, old_stat
            importlib.machinery.SourceFileLoader.get_code = original
            sys.meta_path.remove(finder)
            sys.path[:] = old_path
            for name, module in list(sys.modules.items()):
                if getattr(module, '__file__', None) in self.rows and name not in reference_snapshot:
                    sys.modules.pop(name, None)
