'Dispatch a numerical calculation using checked input records.'
import importlib.util
import os
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent


def package(association):
    if os.environ.get('SCORING_PHASE','prepare') not in ('accept','source_runtime'):
        raise ValueError('Prepare: AP dispatcher cannot execute')
    mod=sys.modules.get(type(association).__module__)
    if mod is None or getattr(mod,'ACTIVE',None) is not association or type(association) is not getattr(mod,'Association',None):
        raise ValueError('Actual installed C association required')
    association.verify_code(mod.__file__);association.verify_t5_coverage()
    association._ap_runtime.member(__file__)
    if association._official_ready is None:raise ValueError('Both official views/capture required')
    association._check_official_score(association._official_ready)
    name='_ap_scoring_checked';path=HERE/'__init__.py'
    if name in sys.modules:
        module=sys.modules[name]
        if Path(module.__file__).resolve()!=path:raise ValueError('Cached AP package origin drift')
    else:
        association._ap_runtime.member(path)
        spec=importlib.util.spec_from_file_location(name,path,submodule_search_locations=[str(HERE)])
        module=importlib.util.module_from_spec(spec);sys.modules[name]=module
        spec.loader.exec_module(module)
    association._ap_runtime.member(path)
    return name


def ap5_science(*,association,request,argv,scientific_scope):
    name=package(association)
    bridge=__import__(name+'.numeric.bridge',fromlist=['run'])
    return bridge.run(association=association,request=request,argv=argv,scientific_scope=scientific_scope)


def numeric_assembly(*,association,args,kwargs,scientific_contract,author_validator):
    name=package(association)
    bridge=__import__(name+'.numeric.bridge',fromlist=['assemble'])
    return bridge.assemble(association=association,args=args,kwargs=kwargs,
                          scientific_contract=scientific_contract,author_validator=author_validator)


def author_validation(*,association,first,second,timestamps):
    name=package(association)
    bridge=__import__(name+'.numeric.bridge',fromlist=['validate_authors'])
    return bridge.validate_authors(association=association,first=first,second=second,timestamps=timestamps)


def optional_loader(*,association,request,primary_tests,permit):
    name=package(association)
    bridge=__import__(name+'.numeric.bridge',fromlist=['optional'])
    return bridge.optional(association=association,request=request,primary_tests=primary_tests,permit=permit)
