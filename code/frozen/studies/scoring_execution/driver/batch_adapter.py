'Apply the saved batch scoring functions within the evaluation context.'
from contextlib import contextmanager
import importlib.machinery
import os
from pathlib import Path
import sys
from types import FunctionType
from source_bytes import require, checked, document


def frozen_source_paths(path_type, sources, frozen_rows=None, authority_root=None):

    class FrozenSourcePath(path_type):
        def resolve(self, strict=False):
            return type(self)(str(super().resolve(strict=strict)))
        def __truediv__(self, key):
            if os.path.isabs(key):


                return type(self)(key)
            if '..' in Path(key).parts:
                canonical=os.path.normpath(os.path.join(str(self),str(key)))
                if authority_root is not None:
                    require(Path(canonical).is_relative_to(authority_root),
                            'Frozen source alias escaped timestamp_checks root')
                    require(canonical in (frozen_rows or {}),
                            'Unlisted frozen inventory alias')

                candidate=path_type(canonical).resolve()
                require(str(candidate)==canonical, 'Frozen source alias redirected')
                if canonical in (frozen_rows or {}):checked(frozen_rows[canonical])
                if canonical in sources.rows:sources.bytes(canonical)
                elif canonical not in (frozen_rows or {}):
                    require(canonical in (frozen_rows or {}),'K1 unlisted frozen source operand')
                return type(self)(canonical)
            return super().__truediv__(key)
    return FrozenSourcePath


@contextmanager
def installed(a, sources):
    root = Path(a._control['project'])/'studies/batch_estimation/fitting/code'
    saved = {}
    defaults = {}
    original_exec = importlib.machinery.SourceFileLoader.exec_module
    original_load = a._load_verified
    previous_authorities = a._authority_files


    a._authority_files = {r['path']:r for field in ('source_files','metadata_files','direct_opaque_targets')
                          for r in a._t5_value.get(field, [])}

    def apply(module):
        file = getattr(module, '__file__', None)
        if file is None or not Path(file).is_relative_to(root) or id(module) in saved:
            return module
        sources.bytes(file)
        saved[id(module)] = (module, dict(vars(module)))
        for value in vars(module).values():
            if isinstance(value, FunctionType) and value.__module__ == module.__name__:
                defaults[id(value)] = (value, value.__defaults__, value.__kwdefaults__)
        a.patch(module)
        if Path(file).name=='batch_identities.py':
            original_declared=module.declared_identity
            def declared_identity(record, root, pin, frozen, source):
                expected=Path(a._control['project'])/'studies/confirmation/execution'
                require(Path(root)==expected, 'Declared adapter root differs from original confirmation')
                rows={os.path.normpath(str(expected/rel)):dict(
                    path=os.path.normpath(str(expected/rel)),**item)
                    for rel,item in frozen['files'].items()}
                old=module.Path
                module.Path=frozen_source_paths(old,sources,rows,expected.parent)
                try:return original_declared(record,root,pin,frozen,source)
                finally:module.Path=old
            module.declared_identity=declared_identity
        if Path(file).name=='freeze_batch_sources.py':


            owner=sys.modules['batch_identities']
            module.declared_identity=apply(owner).declared_identity
            original_verify=module.verify_adapter
            def verify_adapter(*args,**kwargs):
                old=module.Path
                root=Path(args[0] if args else kwargs.get('root',module.ADAPTER))
                expected=args[1] if len(args)>1 else kwargs.get('expected')
                freeze=old(root)/'ADAPTER_FREEZE.json'
                require(expected is not None and module.sha(freeze)==expected,
                        'Installed adapter freeze drift or missing pin')
                frozen=module.read_json(freeze)
                rows={os.path.normpath(str(root/rel)):dict(path=os.path.normpath(str(root/rel)),**pin)
                      for rel,pin in frozen['files'].items()}
                module.Path=frozen_source_paths(old,sources,rows,root.parent)
                try:return original_verify(*args,**kwargs)
                finally:module.Path=old
            module.verify_adapter=verify_adapter
            original_t4b=module.validate_t4b
            def validate_t4b(*args,**kwargs):


                target=root.parent/'SCORER_BINDINGS.json'
                gate=module.read_json(root.parent/'T4B_BINDING.json')
                rows=[r for r in gate['files'] if r['path']==str(target)]
                require(len(rows)==1,'Exact original T4B scorer binding required')
                checked(rows[0]);previous=a.route
                def original_namespace(value):
                    p=Path(os.path.normpath(str(value)))
                    return p if p==target else previous(value)
                a.route=original_namespace
                try:return original_t4b(*args,**kwargs)
                finally:a.route=previous
            module.validate_t4b=validate_t4b
        if Path(file).name=='runner.py':
            original_fitting=module.fitting_argv
            def fitting_argv(*args,**kwargs):
                old=module.Path;module.Path=frozen_source_paths(old,sources)
                try:return original_fitting(*args,**kwargs)
                finally:module.Path=old
            module.fitting_argv=fitting_argv
        return module

    def execute(loader, module):
        original_exec(loader, module)
        apply(module)

    def load(relative):
        return apply(original_load(relative))

    importlib.machinery.SourceFileLoader.exec_module = execute
    a._load_verified = load
    try:
        for module in list(sys.modules.values()):
            if module is not None: apply(module)
        yield apply
    finally:
        importlib.machinery.SourceFileLoader.exec_module = original_exec
        a._load_verified = original_load
        a._authority_files = previous_authorities
        for value, args, kwargs in defaults.values():
            value.__defaults__, value.__kwdefaults__ = args, kwargs
        for module, namespace in reversed(list(saved.values())):
            vars(module).clear()
            vars(module).update(namespace)


def state_root(a, spec):
    expected = Path(a._control['project'])/'studies/batch_estimation/disk_checks/state'
    require(Path(spec['state_root']) == expected, 'A13 batch state must be disk_checks/state')
    return a.route(expected)
