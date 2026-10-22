'Select the news scoring inputs for the common evaluation window.'
from contextlib import contextmanager
from pathlib import Path
import importlib.util
import sys


_source = Path(__file__).resolve().parent/'news_source.py'
_spec = importlib.util.spec_from_file_location('_r2_consumer_news_source',_source)
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)


def core_task(losses, original_native, sc, source, seal, root):
    ns = S.native_namespace(original_native)
    capture = losses.Capture(sc,source)
    bundles = {}
    writer = ns['_write_inference']
    def write(path,result):
        found = next((b for r,b in capture.calls if r is result),None)
        if found is None: raise ValueError('R2 inference without captured paired losses')
        name = Path(path).name
        found.update(id=source+'/'+name,native_name=name)
        bundles[name] = found
        return writer(path,result)
    ns['_write_inference'] = write
    ns['_primary_sentence'] = lambda *a:''
    Path(root).mkdir(parents=True,exist_ok=True)
    permit = losses.permit(sc,seal)
    manifest = losses.P.strict_json(seal['feature_manifest_path'])
    result = S.score_prefix(ns,capture,source,seal,root,permit,manifest,seal['_state_root'])
    return bundles,result['daily'],result['clips'],result['summaries'][source]


@contextmanager
def scope(producer,contract):

    P = producer.P
    losses = sys.modules.get('frozen_losses')
    prior_losses=losses
    if losses is None:
        losses=P.load_module('frozen_losses',S.source(S.LOSSES))
        sys.modules['frozen_losses']=losses
    if Path(losses.__file__).resolve()!=S.source(S.LOSSES).resolve():
        raise PermissionError('R2 wrong-origin frozen_losses module')
    original_deps, original_build = P.dependencies,P.build
    original_assembly = P.assemble_output
    original_native, original_core = losses.native_functions,losses.core_task
    prior_optional=sys.modules.get('optional_losses')
    changed = []
    def dependencies(*args,**kwargs):
        result = original_deps(*args,**kwargs)
        primary_tests,sensitivity_tests,robustness_tests,sc,F = result
        if not any(obj is primary_tests for obj,_,_ in changed):
            changed.append((primary_tests,'Inputs',primary_tests.Inputs))
            primary_tests.Inputs = S.a2_inputs(primary_tests.Inputs,original_native())
            changed.append((primary_tests,'load_frozen_scoring',primary_tests.load_frozen_scoring))
            old_loader = primary_tests.load_frozen_scoring
            primary_tests.load_frozen_scoring = lambda *a,**k:S.scoring_successor(old_loader(*a,**k))
        if not any(obj is sensitivity_tests for obj,_,_ in changed):
            for name,value in S.a3_successor(sensitivity_tests,primary_tests).items():
                changed.append((sensitivity_tests,name,getattr(sensitivity_tests,name)));setattr(sensitivity_tests,name,value)
        return primary_tests,sensitivity_tests,robustness_tests,S.scoring_successor(sc),F
    def assemble(*args,**kwargs):
        record,evidence=original_assembly(*args,**kwargs)
        evidence['news_source']=contract
        return record,evidence
    try:
        inherited_build=S.ap_build(original_build.__globals__)
        P.dependencies = dependencies
        P.assemble_output=assemble
        P.build = inherited_build

        P.build.__globals__['dependencies'] = dependencies
        P.build.__globals__['assemble_output'] = assemble
        losses.native_functions = lambda:S.native_namespace(original_native())
        losses.core_task = lambda ns,sc,source,seal,root:core_task(
            losses,original_native(),sc,source,seal,root)
        imported=[]
        for name,relative in [('optional_losses',S.OPTIONAL),
                ('batch_layers','studies/inference/code/batch_layers.py'),
                ('squared_replay','studies/inference/code/squared_replay.py'),
                ('supplement','studies/inference/table_inputs/code/supplement.py')]:
            value=sys.modules.get(name)
            if value is None:
                value=P.load_module(name,S.source(relative));sys.modules[name]=value
                imported.append(name)
            if Path(value.__file__).resolve()!=S.source(relative).resolve():
                raise PermissionError('R2 wrong-origin '+name+' module')
            if name=='supplement':
                old_subset=value.descriptive_subset
                changed.append((value,'descriptive_subset',old_subset))
                value.descriptive_subset=lambda layer:layer in ('readmission_free_subset','matched_support_subset') or old_subset(layer)
            elif name!='optional_losses':
                changed.append((value,'native_functions',value.native_functions))
                value.native_functions=losses.native_functions
        optional=sys.modules['optional_losses']
        for name,value in S.optional_successor(optional).items():
            changed.append((optional,name,getattr(optional,name)));setattr(optional,name,value)
        yield producer
    finally:
        P.dependencies,P.build = original_deps,original_build
        P.assemble_output = original_assembly
        losses.native_functions,losses.core_task = original_native,original_core
        for obj,name,value in reversed(changed): setattr(obj,name,value)
        if prior_losses is None:sys.modules.pop('frozen_losses',None)
        if prior_optional is None:sys.modules.pop('optional_losses',None)
        for name in locals().get('imported',[]):sys.modules.pop(name,None)


@contextmanager
def producer_scope(producer,contract):

    parent = producer.R.specified_scope
    @contextmanager
    def specified(f,p=None):
        with parent(f,p):
            with scope(producer,contract):
                yield
    producer.R.specified_scope = specified
    try:
        yield producer
    finally:
        producer.R.specified_scope = parent
