'Check historical source contracts and current execution inputs.'
from contextlib import contextmanager
import importlib.machinery
from pathlib import Path
import sys
from types import FunctionType
from source_bytes import checked, document, identity, require

HERE = Path(__file__).absolute().parent
INDEX = {'path': 'paper_plan/minrun_execution_20261010/t5_final/a18h_rd_resume_20261011_01/HISTORY_INDEX.json', 'bytes': 14259, 'sha256': 'a7ff68f3dbf030189c143575f332646341d07c606735bae3a76f3c493b07568e'}


class HistoricalPins:
    def __init__(self, a, sources, commitment, *, index=INDEX):
        self.a, self.sources = a, sources
        self.history = document(index)['files']
        self.current = {}
        build = document(a._control['driver_build'])
        require(identity(HERE/'BUILD_IDENTITY.json') == a._control['driver_build'],
                'A18F current build identity drift')
        for name, pin in build['files'].items():
            self.current[str(HERE/name)] = dict(path=str(HERE/name), **pin)
        self.current[str(HERE/'BUILD_IDENTITY.json')] = a._control['driver_build']
        require(commitment['state'] == 'T6_DUAL_OFFLINE_VERIFIED', 'A18F verified T6 required')
        self.committed = {(r['path'],r['bytes'],r['sha256']) for r in commitment['files']}
        self.events = []

    def verify(self, item):

        path = item.get('path') if isinstance(item, dict) else None
        if path not in self.current:
            return False
        live = self.current[path]
        if all(item.get(k) == live[k] for k in ('path','bytes','sha256')):

            return False
        checked(live)
        require(tuple(live[k] for k in ('path','bytes','sha256')) in self.committed,
                'A18F current source absent from T6: '+path)
        if path in self.sources.rows:
            r = self.sources.rows[path]
            require(all(r[k] == live[k] for k in ('bytes','sha256')),
                    'A18F current build/K1 disagreement')
            require(checked(r) == self.sources.bytes(path), 'A18F current snapshot drift')
        else:
            require(Path(path).name in ('BUILD_IDENTITY.json','RUNTIME_SOURCES.json'),
                    'A18F current source absent from K1')
        matches = [r for r in self.history if r['original'] == item]
        require(len(matches) == 1, 'A18F exact old source archive missing: '+path)
        archive = matches[0]['archive']
        require(all(archive[k] == item[k] for k in ('bytes','sha256')),
                'A18F old source archive pin mismatch')
        checked(archive)
        self.events.append(dict(original=item,archive=archive,current=live))
        return True


def _checked(item):
    return _minrun_a18f_dispatch(item)


def _snapshot_check(self, item):
    return _minrun_a18f_snapshot_dispatch(self, item)


@contextmanager
def installed(a, sources, commitment, *, index=INDEX):
    router = HistoricalPins(a,sources,commitment,index=index)
    saved = {}
    old_exec = importlib.machinery.SourceFileLoader.exec_module
    old_module = sources.module
    q = Path(a._control['project'])/'studies'
    roots = (q/'source_bindings', q/'batch_estimation/fitting/code',
             q/'batch_estimation/batch_checks/statistics')

    def replace(fn, template, attr, dispatch):
        if id(fn) in saved: return
        require(fn.__closure__ is None, 'A18F unsupported identity-check closure')
        original = FunctionType(fn.__code__,fn.__globals__,fn.__name__,fn.__defaults__)
        original.__kwdefaults__ = fn.__kwdefaults__
        previous = fn.__globals__.get(attr)
        had = attr in fn.__globals__
        saved[id(fn)] = (fn,fn.__code__,attr,had,previous)
        fn.__globals__[attr] = dispatch(original)
        fn.__code__ = template.__code__

    def apply(module):
        file = getattr(module,'__file__',None)
        if file is None or not any(Path(file).is_relative_to(r) for r in roots): return module
        for name in ('checked','_checked'):
            fn = getattr(module,name,None)
            if isinstance(fn,FunctionType) and any(Path(fn.__code__.co_filename).is_relative_to(r) for r in roots):
                def dispatch(original):
                    def call(item):
                        if router.verify(item): return Path(item['path'])
                        return original(item)
                    return call
                replace(fn,_checked,'_minrun_a18f_dispatch',dispatch)
        cls = getattr(module,'Snapshot',None)
        if cls is not None and Path(file).is_relative_to(q/'source_bindings'):
            def dispatch(original):
                def call(snapshot,item):
                    if router.verify(item):


                        snapshot.ident(item['path'])
                        return Path(item['path'])
                    return original(snapshot,item)
                return call
            replace(cls.check,_snapshot_check,'_minrun_a18f_snapshot_dispatch',dispatch)
        return module

    def execute(loader,module):
        old_exec(loader,module);apply(module)
    def load(name,path):return apply(old_module(name,path))
    importlib.machinery.SourceFileLoader.exec_module = execute
    sources.module = load
    try:
        for module in list(sys.modules.values()):
            if module is not None: apply(module)
        yield router
    finally:
        sources.module = old_module
        importlib.machinery.SourceFileLoader.exec_module = old_exec
        for fn,code,attr,had,previous in reversed(list(saved.values())):
            fn.__code__ = code
            if had: fn.__globals__[attr] = previous
            else: fn.__globals__.pop(attr,None)
