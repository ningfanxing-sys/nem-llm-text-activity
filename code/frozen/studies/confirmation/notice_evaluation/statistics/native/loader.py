'Check source hashes before loading numerical modules.'
from contextlib import contextmanager
import ast
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from evaluator.validation import require
from source_validator import checked_public_source
from . import reader as R


def source_rows():
    document = json.loads((R.OUT/'NUMERICAL_ANCESTOR_PINS.json').read_text())
    rows = document['files']
    require(isinstance(rows, list) and rows, 'Numerical ancestor census required')
    require(len(rows) == len({r['path'] for r in rows}), 'Duplicate numerical ancestor')
    require(not any('/tables/' in r['path'] for r in rows), 'Writing source in numerical closure')
    return {r['path']:r for r in rows}


@contextmanager
def checked_imports(rows):

    permitted = set(rows)
    for item in rows.values():
        checked_public_source(item, permitted_paths=permitted)
    saved_path = sys.path[:]
    saved_modules = dict(sys.modules)
    directories = sorted({str(Path(p).parent) for p in rows if p.endswith('.py')})
    for module in list(sys.modules.values()):
        raw = getattr(module, '__file__', None)
        if raw and str(raw).startswith(str(R.PROJ)+'/'):
            path = str(Path(raw).absolute())
            if path.startswith(str(R.OUT)+'/'):
                continue
            require(path in rows, 'Unlisted cached project module')
            checked_public_source(rows[path], permitted_paths=permitted)
    class Finder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, fullname, path=None, target=None):
            locations = path if path is not None else sys.path
            matches = [Path(d)/(fullname.rsplit('.', 1)[-1]+'.py') for d in locations]
            candidates = [p for p in matches if str(p.absolute()) in rows]
            if not candidates:
                return None
            self.paths[fullname] = str(candidates[0].absolute())
            return importlib.util.spec_from_loader(fullname, self, origin=self.paths[fullname])
        def create_module(self, spec):
            return None
        def exec_module(self, module):
            path = self.paths[module.__name__]
            data = checked_public_source(rows[path], permitted_paths=permitted)
            module.__file__ = path
            exec(compile(data, path, 'exec', dont_inherit=True), vars(module))
            checked_public_source(rows[path], permitted_paths=permitted)
    finder = Finder(); finder.paths = {}
    original_get_code = importlib.machinery.SourceFileLoader.get_code
    def checked_get_code(loader, fullname):
        raw = str(Path(loader.path).absolute())
        if raw.startswith(str(R.PROJ)+'/') and not raw.startswith(str(R.OUT)+'/'):
            require(raw in rows, 'Unlisted direct project source loader')


            origin = getattr(getattr(original_get_code, '__code__', None), 'co_filename', '')
            if origin.startswith(str(R.PROJ)+'/'):
                require(Path(origin) == R.Q/'batch_estimation/batch_checks/statistics/consumer_roots.py',
                        'Unknown project source-loader wrapper')
                original_get_code(loader, fullname)
            else:
                require(origin.startswith('<frozen importlib.'), 'Unknown runtime source-loader wrapper')
            data = checked_public_source(rows[raw], permitted_paths=permitted)
            return compile(data, raw, 'exec', dont_inherit=True)
        return original_get_code(loader, fullname)
    importlib.machinery.SourceFileLoader.get_code = checked_get_code
    sys.path[:0] = directories
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        importlib.machinery.SourceFileLoader.get_code = original_get_code
        sys.meta_path.remove(finder)
        sys.path[:] = saved_path
        for name, module in list(sys.modules.items()):
            raw = getattr(module, '__file__', None)
            if raw and str(Path(raw).absolute()) in rows and name not in saved_modules:
                sys.modules.pop(name, None)
        for item in rows.values():
            checked_public_source(item, permitted_paths=permitted)


def artificial_modules(P):

    require(os.environ.get('SCORING_PHASE','prepare')=='accept', 'Artificial source scope requires accept')
    raw=os.environ.get('ANCHORREADER_SYNTHETIC_SCRATCH')
    require(isinstance(raw,str) and raw, 'Marked artificial scratch required')
    root=Path(raw)
    require(root.is_absolute() and root==root.resolve() and root.is_relative_to(Path('/private/tmp'))
        and all(not p.is_symlink() for p in (root,*root.parents)), 'Canonical artificial scratch only')
    require(json.loads((root/'SYNTHETIC_ONLY.json').read_text())=={'synthetic_only':True},
            'Explicit artificial source fixture marker required')
    rows=source_rows();permitted=set(rows)
    def exact_module(relative, substitutions):
        path=R.confirmation/relative
        data=checked_public_source(rows[str(path)],permitted_paths=permitted)
        tree=ast.parse(data,filename=str(path));body=[];found=[]
        for n in tree.body:
            assignment=isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)
            key=n.targets[0].id if assignment else None
            if key in substitutions:
                require(isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name)
                    and n.value.func.id=='load_'+key.lower() and not n.value.args and not n.value.keywords,
                    'Exact legacy import constructor AST required')
                found.append(key)
            else:body.append(n)
        require(found==list(substitutions), 'Exact private constructor census')
        namespace=dict(__file__=str(path),__name__='_rd_artificial_'+path.stem,**substitutions)
        exec(compile(ast.Module(body=body,type_ignores=[]),str(path),'exec',dont_inherit=True),namespace)
        checked_public_source(rows[str(path)],permitted_paths=permitted)
        return SimpleNamespace(**namespace)
    primary_tests=exact_module('primary_tests/code/primary_comparisons.py',{})
    sensitivity_tests=exact_module('sensitivity_tests/code/sensitivity_comparisons.py',{'primary_tests':primary_tests})
    robustness_tests=exact_module('robustness_tests/code/robustness_comparisons.py',{'sensitivity_tests':sensitivity_tests})
    sc=P.load_module('_rd_artificial_frozen_scoring',R.confirmation/'code/scoring.py')
    return primary_tests,sensitivity_tests,robustness_tests,sc,None


@contextmanager
def frozen_modules():
    require(os.environ.get('SCORING_PHASE', 'prepare') in ('accept', 'source_runtime'),
            'Prepare: native computation forbidden')
    with checked_imports(source_rows()), R.import_path(R.AP/'code'), R.import_path(R.B/'code'):
        import read_comparisons as P
        import frozen_losses as L
        import parity_gate as G
        import score_batch as BS
        if os.environ.get('SCORING_PHASE') == 'accept':
            primary_tests,sensitivity_tests,robustness_tests,sc,consumer=artificial_modules(P)
        else:
            primary_tests,sensitivity_tests,robustness_tests,sc,consumer=P.dependencies(consumer=False)
        require(consumer is None, 'Unexpected whole-FILL numerical dependency')
        yield SimpleNamespace(P=P, L=L, G=G, primary_tests=primary_tests, sensitivity_tests=sensitivity_tests, robustness_tests=robustness_tests,
            sc=sc, native=SimpleNamespace(**L.native_functions()), BS=BS)
