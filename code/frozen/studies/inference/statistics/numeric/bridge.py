'Connect comparison records to numerical calculation functions.'
import ast
from contextlib import contextmanager
from copy import deepcopy
import inspect
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from ..input_checks import HERE, require, checked_bytes, artificial_accept
from .runtime import Runtime, installed
from .assembly import assemble_numeric
from . import writer
from ..exporter.sensitivity_export import task_pair_export


def parent(association):
    installed(association)
    P=sys.modules.get('read_comparisons')
    if P is None:
        reference_snapshot=sys.path[:]
        try:
            sys.path.insert(0,str(HERE.parent/'code'))
            with association._source_loading():
                P=association._load_verified('studies/inference/code/read_comparisons.py')
        finally:sys.path[:]=reference_snapshot
    require(P is not None and Path(P.__file__).resolve()==HERE.parent/'code/read_comparisons.py',
            'Verified inherited AP namespace required')
    association.verify_code(P.__file__)
    return P


def validate_authors(*,association,first,second,timestamps):
    installed(association)
    rt=Runtime(association,dict(schema='AP_SCORING_SCIENTIFIC_EXECUTION_CONTRACT_V1',r2_source_contract={}))
    schema=json.loads(rt.checked_source(HERE/'numeric/AUTHOR_CONFIRMATION_A8_SCHEMA.json'))
    namespace=dict(require=require,FillError=ValueError,re=re,author_schema=lambda:deepcopy(schema),
                   A8_BINDINGS={'A8_FREEZE.json':'80e95c8db2c85ca38490f443612cda30d7ff33124f33ed87b70d8f8317909162'})
    data=rt.checked_source(HERE/'numeric/inherited_authors.py')
    exec(compile(data,str(HERE/'numeric/inherited_authors.py'),'exec'),namespace)
    result=namespace['validate_authors'](first,second,timestamps)
    rt.checked_source(HERE/'numeric/inherited_authors.py');rt.reverify_official_views()
    return result


@contextmanager
def specified_scope(P,runtime):

    previous=P.load_inputs
    runtime.P=P
    P.load_inputs=lambda path,digest,synthetic=False:runtime.load_scientific_inputs(path,digest,synthetic)
    try:yield SimpleNamespace(P=P)
    finally:P.load_inputs=previous


def assemble(*,association,args,kwargs,scientific_contract,author_validator):
    P=parent(association);runtime=Runtime(association,scientific_contract,author_validator);runtime.P=P
    runtime.reverify_official_views()
    record,evidence=assemble_numeric(P,*args,**kwargs,checked_source=runtime.checked_source)
    bound=inspect.signature(assemble_numeric).bind(P,*args,**kwargs,checked_source=runtime.checked_source)
    bundles,replay=bound.arguments['bundles'],bound.arguments['replay_evidence']
    metadata=runtime.verified_sens35_metadata(bundles,replay);missing=runtime.native_unavailable_series()
    record['sens35_detached_losses']=task_pair_export(bundles,replay,metadata,missing)
    record['original_news_214']=runtime.verified_original_attachment()
    record['original_news_214_source']=deepcopy(runtime.contract['original_attachment'])
    record['limitations']=runtime.verified_limitations()
    evidence['execution_authority']=runtime.public_execution_provenance()
    from ..exporter.sensitivity_export import replay_binding
    record['sens35_replay_binding']=replay_binding(record['sens35_detached_losses'],evidence)
    runtime.reverify_official_views();return record,evidence


def run(*,association,request,argv,scientific_scope):
    installed(association)
    require(isinstance(argv,list) and not argv and callable(scientific_scope),'Exact AP5 source ABI, no legacy CLI')
    require(request.get('schema')=='C_SCORING_POSTSCORE_REQUEST_V1' and request['score_views']==association._official_ready['view_inputs'],'Exact co-verified scientific request')
    require(association.synthetic is True,'Real AP5 execution waits separate released owner/output contract')
    contract=request['function_kwargs']['scientific_contract']
    old_path=sys.path[:];old_modules=dict(sys.modules);P=None;original_build=None
    try:
        sys.path.insert(0,str(HERE.parent/'code'))
        P=parent(association);original_build=P.build


        validator=__import__('runtime_entries')._entry(association,'author_validation')[0]
        runtime=Runtime(association,contract,validator);runtime.P=P
        root=artificial_accept(association.project)
        path=Path(contract['manifest']['path']);runtime.verify_manifest_location(path,root)
        with specified_scope(P,runtime) as producer:
            with scientific_scope(producer,contract):
                record,evidence=P.build(path,contract['manifest']['sha256'],chunk=contract['chunk'],
                    gate=P.resource_gate,synthetic=True,production=False)
        runtime.reverify_official_views()
        receipt=writer.write_artificial(record,evidence,contract['output_directory'],fixture_root=root,reverify=runtime.reverify_official_views)

        from ..exporter.sensitivity_export import write_replay_artificial
        from ..input_checks import source_identity
        files={Path(x['path']).name:x for x in receipt['files']}
        losses=write_replay_artificial(record['sens35_detached_losses'],Path(contract['output_directory'])/'losses',
            fixture_root=root,reverify=runtime.reverify_official_views,record=record,evidence=evidence,
            numeric_source=files['SCORING_NUMERIC.json'],numeric_evidence=files['SCORING_NUMERIC_EVIDENCE.json'],
            numeric_receipt=source_identity(Path(contract['output_directory'])/'SCORING_NUMERIC_RECEIPT.json'))
        return dict(record=record,evidence=evidence,numeric_receipt=receipt,loss_exports=losses)
    finally:
        if P is not None and original_build is not None:P.build=original_build
        sys.path[:]=old_path
        for name in set(sys.modules)-set(old_modules):sys.modules.pop(name,None)
        sys.modules.update(old_modules)


def optional(*,association,request,primary_tests,permit):
    installed(association);P=parent(association)
    require(permit is not None,'Native independently validated permit required')
    association.verify_code(inspect.getsourcefile(primary_tests.Inputs))
    with association._source_loading():
        source=association._load_verified('comparison_inputs/code/news_source.py')
        losses=association._load_verified('studies/inference/code/frozen_losses.py')
        klass=source.a2_inputs(primary_tests.Inputs,losses.native_functions())
        state=Path(association._official_ready['view_inputs']['original']['seal']['path']).parent
        loader=klass(state)
    receipt_id=association._official_ready['view_inputs']['r2']['score_receipt']
    contract=dict(schema='AP_SCORING_SCIENTIFIC_EXECUTION_CONTRACT_V1',r2_source_contract={})
    runtime=Runtime(association,contract)
    receipt=runtime.checked_payload(receipt_id)
    require(receipt['seal_sha256']==loader.seal_sha256,'R2 optional canonical seal drift')
    loader.receipt=receipt;loader.score_files={Path(x['path']).name:x for x in receipt['files']}
    association._check_official_score(association._official_ready)
    return loader
