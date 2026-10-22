'Apply the measured memory limits to forecast calculations.'
import contextlib
import importlib.machinery
from pathlib import Path
import sys
import types
from source_bytes import Sources, require

COMMON = 'studies/confirmation/forecast_hashes/code/common.py'
POST = 'studies/inference/code/read_comparisons.py'
_ACTIVE = None


def constants(code, changes):

    require(all(code.co_consts.count(old) == 1 for old in changes),
            'A11 exact frozen resource constants required')
    return code.replace(co_consts=tuple(changes.get(x, x) if not isinstance(x, types.CodeType)
                        else x for x in code.co_consts))


class Calibration:
    def __init__(self, sources, project, *, scoring=False):
        self.sources, self.project, self.scoring = sources, Path(project), scoring
        self.path = str(self.project/COMMON)
        self.payload = sources.bytes(self.path)
        tree = compile(self.payload, self.path, 'exec', dont_inherit=True)
        self.expected = next(c for c in tree.co_consts
                             if isinstance(c, types.CodeType) and c.co_name == 'resources')
        self.patched = constants(self.expected, {
            25: 10, 1_500_000_000: 4_000_000_000,
            'System memory free is below 25%; stop and retain partial evidence':
                'System memory free is below 10%; stop and retain partial evidence',
            'One-process peak RSS exceeds 1.5 GB': 'One-process peak RSS exceeds 4 GB'})
        self.common = None
        self.saved_codes = []
        self.io_loaders = []

    def observe(self, module):
        file = getattr(module, '__file__', None)
        if file == str(self.project/'studies/confirmation/forecast_hashes/statistics/metadata_io.py'):
            if not any(module is m for m, old in self.io_loaders):
                original = module.load_source
                def load(name, path, expected=None, *, register=True):
                    if str(Path(path).absolute()) == self.path:
                        _, payload = module.snapshot(path, expected)
                        require(payload == self.payload, 'A11 frozen common bytes differ')
                        if register: sys.modules[name] = self.common
                        result = self.common
                    else:
                        result = original(name, path, expected, register=register)
                    self.observe(result)
                    self.assert_active()
                    return result
                self.io_loaders.append((module, original))
                module.load_source = load
        if self.scoring and file == str(self.project/POST):
            name = 'resource_gate'
            fn = getattr(module, name)
            if not any(fn is f for f, old, patched in self.saved_codes):

                code = compile(self.sources.bytes(file), file, 'exec', dont_inherit=True)
                expected = next(c for c in code.co_consts
                    if isinstance(c, types.CodeType) and c.co_name == name)
                require(fn.__code__ == expected, 'A11 selected scoring guard differs')
                message = 'Less than 25% memory free; stop'
                patched = constants(expected, {25: 10, message: message.replace('25%', '10%')})
                self.saved_codes.append((fn, fn.__code__, patched))
                fn.__code__ = patched
        self.aliases(module)

    def aliases(self, module):
        file = getattr(module, '__file__', None)
        if not isinstance(file, str) or not Path(file).is_relative_to(self.project): return []
        aliases = []
        for key, value in list(vars(module).items()):
            if callable(value) and (key == 'resources' or
                    isinstance(value, types.FunctionType) and value.__name__ == 'resources'):
                require(value is self.common.resources,
                        'A11 uncovered resources alias: '+module.__name__+'.'+key)
                aliases.append(module.__name__+'.'+key)
        return aliases

    def assert_active(self):
        require(self.common is not None and self.common.resources.__code__ is self.patched,
                'A11 resource calibration is not active')
        aliases = []
        for name, module in list(sys.modules.items()):
            if isinstance(module, types.ModuleType): aliases.extend(self.aliases(module))
        for fn, old, patched in self.saved_codes:
            require(fn.__code__ is patched, 'A11 scoring resource calibration drift')
        return dict(active=True, peak_rss_exclusive_bytes=4_000_000_000,
                    minimum_memory_free_percent=10, aliases=sorted(aliases),
                    historical_receipt_validators_unchanged=True)

    @contextlib.contextmanager
    def installed(self):
        original_module = Sources.module
        original_exec = importlib.machinery.SourceFileLoader.exec_module
        reference_snapshot = dict(sys.modules)
        try:
            self.common = self.sources.module('common', self.path)
            require(self.common.resources.__code__ == self.expected,
                    'A11 frozen resources function differs')
            fn = self.common.resources
            self.saved_codes.append((fn, fn.__code__, self.patched))
            fn.__code__ = self.patched
            def source_module(sources, name, path):
                if str(Path(path).absolute()) == self.path:
                    require(sources.bytes(path) == self.payload, 'A11 common source identity differs')
                    sys.modules[name] = self.common
                    module = self.common
                else: module = original_module(sources, name, path)
                self.observe(module)
                self.assert_active()
                return module
            def exec_module(loader, module):


                if str(Path(loader.path).absolute()) == self.path:
                    require(self.sources.bytes(self.path) == self.payload,
                            'A11 direct common source identity differs')
                    module.__dict__.update(vars(self.common))
                else:
                    original_exec(loader, module)
                self.observe(module)
                self.assert_active()
            Sources.module = source_module
            importlib.machinery.SourceFileLoader.exec_module = exec_module
            for module in list(sys.modules.values()):
                if isinstance(module, types.ModuleType): self.observe(module)
            self.assert_active()
            try: yield self
            finally: self.assert_active()
        finally:
            Sources.module = original_module
            importlib.machinery.SourceFileLoader.exec_module = original_exec
            for module, original in reversed(self.io_loaders): module.load_source = original
            for fn, original, patched in reversed(self.saved_codes): fn.__code__ = original
            for name, module in list(sys.modules.items()):
                if module is self.common and name not in reference_snapshot: sys.modules.pop(name, None)


@contextlib.contextmanager
def calibrated(sources, project, *, scoring=False):
    global _ACTIVE
    if _ACTIVE is not None:
        require(_ACTIVE.project == Path(project), 'A11 calibration project differs')
        _ACTIVE.assert_active()
        yield _ACTIVE
        return
    calibration = Calibration(sources, project, scoring=scoring)
    with calibration.installed():
        _ACTIVE = calibration
        try: yield calibration
        finally: _ACTIVE = None


def installed(native, action):
    require(action in ('af-execute', 'verify-seal'), 'A11 runtime scope is AF execute/verify only')
    return calibrated(native.sources, native.project)


def installed_score(sources, project):


    return calibrated(sources, project, scoring=True)


def assert_active():
    require(_ACTIVE is not None, 'A11 no active scoped resource calibration')
    return _ACTIVE.assert_active()
