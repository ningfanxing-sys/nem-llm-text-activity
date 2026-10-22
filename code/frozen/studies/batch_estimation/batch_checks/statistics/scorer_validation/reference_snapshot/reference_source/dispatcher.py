'Select the numerical functions for each scoring calculation.'
from pathlib import Path
from contract_io import ContractError,_phase,_json,_snapshot,_canonical
from runtime_entries import _entry,_call
import output_lifecycle as L

def _control(a,role,request):
    _phase(a.project,a.synthetic)
    if role not in {'arm','capture','r2_complete'}:raise ContractError('Unknown callback control')
    fn,pin,row=_entry(a,role)
    if row['family']!='scoring_callback':raise ContractError('Control must be declared scoring_callback code')
    root=_canonical(request['output_root'],a.project)
    with L._producer(a,pin,root,read_ids=request['control_identities'],outputs=request['output_paths'],opaque=True):
        result=fn(association=a,request=request)
    a._ap_runtime.member(pin['path']);return result

def _postscore(a,entry,request,argv):
    _phase(a.project,a.synthetic)
    evidence=request['score_views']
    a.official_views(evidence['original'],evidence['r2'],evidence['execution'])
    if entry in {'AP5','AP6','notice_delays'}:
        route='AP6' if entry in {'AP6','notice_delays'} else 'AP5';a.authorize_ap_route(route)
        role={'AP5':'ap5_science','AP6':'ap6_joint','notice_delays':'rd_joint'}[entry]
        from comparison_adapter import _scope
        result=_call(a,role,association=a,request=request,argv=list(argv),scientific_scope=lambda producer,contract:_scope(a,producer,contract))
        a._check_official_score(a._official_ready);return result

    module=a.load(entry)
    from contextlib import contextmanager
    import sys
    reference_snapshot=sys.argv[:]
    try:
        sys.argv=[str(module.__file__),*argv]
        with a._consumer_execution(entry,producer=(entry=='score_batch')):
            function=request.get('function','main')
            if entry=='runner' and function not in __import__('consumer_roots').RUNNER_SUPPORT:raise ContractError('Runner dispatch exposes export/support only')
            result=getattr(module,function)(**request.get('function_kwargs',{}))
        a._check_official_score(a._official_ready);return result
    finally:sys.argv[:]=reference_snapshot

def _optional(a,request):

    _phase(a.project,a.synthetic);a.verify_t5_coverage()
    if a._official_ready is None:raise ContractError('Optional scoring requires both official views/capture')
    a._check_official_score(a._official_ready)
    from scorer_adapter import _namespace,R2
    with a._source_loading():
        source=a._load_verified(R2)
        primary_tests=a._load_verified('studies/confirmation/primary_tests/code/primary_comparisons.py')
        scoring=a._load_verified('studies/confirmation/code/scoring.py')
    with _namespace(a) as (_,runtime):
        with a._validation():
            from runtime_resolution import _wire,_permit
            permit=_permit(a,_wire(a)['r2'],request['permit_identity'])
        import consumer_roots as C
        pin=dict(path=str(C.LIVE/R2),**a._effective_sources[R2]['identity'])
        root=_canonical(request['output_root'],a.project)
        census=request['output_paths']
        if {Path(x).name for x in census}!={'R2_BATCH.json','DAILY_LOSSES.csv','R2_BATCH_RECEIPT.json','R2_LABEL.json','R2_LABEL_RECEIPT.json'}:
            raise ContractError('Exact separate R2 optional census')
        with L._producer(a,pin,root,read_ids=[request['permit_identity']],sealed_reads=True,outputs=census):
            loader_fn,loader_pin,_=_entry(a,'optional_loader')
            loader=loader_fn(association=a,request=request,primary_tests=primary_tests,permit=permit)
            result=source.score_optional_inputs(primary_tests,scoring,permit,loader,request['batch_seal_identity'],request.get('replacement_identity'),root)


        with a._validation():
            for rname,state in [('R2_BATCH_RECEIPT.json','A2BATCH_SECONDARY_SCORE_COMPLETE'),('R2_LABEL_RECEIPT.json','A2LABEL_COMPLETE')]:
                from contract_io import _identity
                value=_json(_snapshot(_identity(root/rname,root),root))
                if value['state']!=state:raise ContractError('Optional native completion missing')
                if value.get('evaluation_view')!=a._scorer_contract['r2']['evaluation_view']:raise ContractError('Optional R2 marker drift')
                for item in value['files']:
                    actual=_identity(item['path'],root)
                    if item!={k:actual[k] for k in item}:raise ContractError('Optional native receipt identity drift')
                    _snapshot(actual,root)
            if {str(x) for x in root.iterdir()}!=set(census):raise ContractError('Optional extra/omitted output')
        a._check_official_score(a._official_ready);return result
