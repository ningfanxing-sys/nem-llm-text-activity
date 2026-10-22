'Connect checked input records to the frozen forecasting functions.'
import ast
from contextlib import contextmanager
from pathlib import Path
import sys
import types
import metadata_io as io
from science_contract import require

HERE=io.HERE;AF=io.AF;OV1=AF/'deadline_checks';OV2=AF/'availability_delays';B=io.PROJ/'studies/batch_estimation/fitting/code'
_MODULES=None


def pinned_source(relative):
    pins=io.read_json(HERE/'INHERITED_SOURCE_PINS.json')['files']
    path=io.PROJ/relative
    require(relative in pins,'Exact finite inherited source required')
    return path,pins[relative]


def frozen_modules():
    global _MODULES
    if _MODULES is not None:
        for p,item in _MODULES['_pins'].items():io.snapshot(p,item)
        return _MODULES
    rows={};pins={}
    def load(name,path):
        rel=Path(path).relative_to(io.PROJ).as_posix();p,pin=pinned_source(rel)
        pins[str(p)]=pin;rows[name]=io.load_source(name,p,pin);return rows[name]
    saved=sys.path[:];sys.path[:0]=[str(AF/'code'),str(OV1),str(OV2),str(B)]
    all_pins=io.read_json(HERE/'INHERITED_SOURCE_PINS.json')['files']
    paths={}
    for directory in (AF/'code',OV1,OV2,B):
        for p in directory.glob('*.py'):
            rel=p.relative_to(io.PROJ).as_posix()
            if rel in all_pins:paths.setdefault(p.stem,(p,all_pins[rel]))
    imports=pinned_imports(paths);imports.__enter__()
    try:
        for n in ('common','activity_guard','check_prescoring_state','forecast_inputs','run_bound_forecasts'):
            load(n,AF/'code'/(n+'.py'))
            if n=='common':rows[n].resources()
        load('runner',B/'runner.py')
        load('anchor_patch',AF/'code/anchor_patch.py')
        for n in ('timestamp_checks','deadline_patch'):load(n,OV1/(n+'.py'))
        for name,file in [('delay_authority','timestamp_checks'),('delay_speed_binding','speed_binding'),
                          ('delay_patch','delay_patch'),('delay_core','delay_core')]:load(name,OV2/(file+'.py'))
        load('_original_delay_freeze',OV2/'freeze_delay.py')
        load('_original_delay_host',OV2/'forecast_wrapper.py')
        load('structural_projection',AF/'code/structural_projection.py')
    finally:
        imports.__exit__(None,None,None);sys.path[:]=saved

    pins.update({str(p):pin for p,pin in paths.values()})
    rows['_pins']=pins;_MODULES=rows;return rows


def resolved_base_freezer(name,path):

    p,pin=pinned_source(Path(path).relative_to(io.PROJ).as_posix())
    source=io.snapshot(p,pin)[1]
    old=b"OUT/'CODE_FREEZE.json'";new=b"SCI_CODE_FREEZE"
    require(source.count(old)==2,'Frozen base freezer output token census drift')
    patched=source.replace(old,new)
    require(patched.replace(new,old)==source,'Unexpected base-freezer byte change')
    tree=ast.parse(patched);original=ast.parse(source)
    class Restore(ast.NodeTransformer):
        def visit_Name(self,node):
            return ast.parse("OUT/'CODE_FREEZE.json'",mode='eval').body if node.id=='SCI_CODE_FREEZE' else node
    require(ast.dump(Restore().visit(tree),include_attributes=False)==ast.dump(original,include_attributes=False),
            'All non-output base freezer AST must remain identical')
    module=types.ModuleType(name);module.__file__=str(p)
    module.SCI_CODE_FREEZE=HERE/'BASE_CODE_FREEZE.json'
    exec(compile(patched,str(p),'exec'),vars(module));return module


@contextmanager
def metadata_aliases(modules):

    saved=[];virtual=AF/'CODE_FREEZE.json';actual=HERE/'BASE_CODE_FREEZE.json'
    for module in modules:
        for name in ('read_json','read','identity'):
            original=getattr(module,name,None)
            if original is None:continue
            def wrapped(path,*args,_original=original,**kwargs):
                if Path(path).absolute()==virtual:path=actual
                return _original(path,*args,**kwargs)
            saved.append((module,name,original));setattr(module,name,wrapped)
    try:yield
    finally:
        for module,name,value in reversed(saved):setattr(module,name,value)


def delay_freezer_provider():

    import freeze_science,root_mapping,source_inventory
    m=frozen_modules();original=m['_original_delay_freeze']
    provider=types.ModuleType('_af_science_delay_freezer');provider.__file__=original.__file__
    provider.__dict__.update(vars(original))
    for name,value in list(vars(provider).items()):
        if isinstance(value,types.FunctionType) and value.__globals__ is vars(original):
            fn=types.FunctionType(value.__code__,vars(provider),value.__name__,value.__defaults__)
            fn.__kwdefaults__=value.__kwdefaults__;setattr(provider,name,fn)
    provider.HERE=HERE;provider.read=io.read_json;provider.identity=io.identity
    provider.source_preflight=freeze_science.delivery_preflight
    provider.interface_identities=lambda *_: {'markdown':io.identity(HERE/'AM3_FINAL_SOURCE_INTERFACE.md'),
                                             'json':io.identity(HERE/'AM3_FINAL_SOURCE_INTERFACE.json')}
    provider.load_source=resolved_base_freezer
    provider._source_association=freeze_science.source_association
    sys.modules['delay_root_mapping']=root_mapping;sys.modules['delay_final_source']=source_inventory
    sys.modules['delay_freeze']=freeze_science


    m['delay_authority'].identity=io.identity
    return provider

@contextmanager
def pinned_imports(paths):

    import importlib.abc,importlib.util
    class Finder(importlib.abc.MetaPathFinder,importlib.abc.Loader):
        def find_spec(self,fullname,path=None,target=None):
            if fullname not in paths:return None
            return importlib.util.spec_from_loader(fullname,self,origin=str(paths[fullname][0]))
        def create_module(self,spec):return None
        def exec_module(self,module):
            path,pin=paths[module.__name__];item,payload=io.snapshot(path,pin)
            module.__file__=item['path'];exec(compile(payload,item['path'],'exec',dont_inherit=True),vars(module))
            io.snapshot(path,item)
    finder=Finder();sys.meta_path.insert(0,finder)
    try:yield
    finally:sys.meta_path.remove(finder)

@contextmanager
def actual_entry_metadata(host):

    old=host.no_overlap
    require(isinstance(old,types.FunctionType) and old.__closure__ is None,'Exact native no-overlap function required')
    globals_=dict(old.__globals__);globals_['__file__']=str(HERE/'forecast_wrapper.py')
    fn=types.FunctionType(old.__code__,globals_,old.__name__,old.__defaults__);fn.__kwdefaults__=old.__kwdefaults__
    host.no_overlap=fn
    try:yield
    finally:host.no_overlap=old
