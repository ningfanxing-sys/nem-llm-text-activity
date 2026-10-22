'Select the checked scoring functions for the evaluation window.'
import contextlib
import importlib.util
from pathlib import Path
import sys
from types import FunctionType
from contract_io import ContractError, _canonical, _snapshot, _json, _identity, _phase
import output_lifecycle as L

NATIVE='studies/confirmation/execution/seal_score.py'
RUNTIME='studies/confirmation/execution/runtime.py'
R2='comparison_inputs/code/news_source.py'

@contextlib.contextmanager
def _namespace(a):
    reference_snapshot=sys.path[:]
    sys.path[:0]=[str(a.project/'studies/confirmation/execution'),str(a.project/'studies/confirmation/code')]
    try:
        with a._source_loading():
            native=a._load_verified(NATIVE);runtime=a._load_verified(RUNTIME)
        yield dict(vars(native)),runtime
    finally:sys.path[:]=reference_snapshot

def _seal_bridge(namespace,association):

    if association.get('schema')!='C_SCORING_R2_STATE_SEAL_ASSOCIATION_V1' or association.get('source_reviewed') is not True \
       or association.get('resolution')!='EXACT_IN_PROCESS_ORIGINAL_SEAL_ONLY':
        raise ContractError('Reviewed fresh-state seal association required')
    fresh=_canonical(association['state_root']);original=_canonical(association['seal_identity']['path'])
    if fresh==original.parent or (fresh/'SEAL.json').exists():raise ContractError('Ambiguous/aliased fresh R2 state seal')
    base=namespace['Path']
    class SealPath(type(Path())):
        def __new__(cls,*args):return super().__new__(cls,*args)
        def __truediv__(self,part):
            p=Path(str(self))/part
            return base(original) if p==fresh/'SEAL.json' else SealPath(p)
        def joinpath(self,*parts):
            p=Path(str(self)).joinpath(*parts)
            return base(original) if p==fresh/'SEAL.json' else SealPath(p)
    ns=dict(namespace);parent=namespace['verify_seal']
    clone=FunctionType(parent.__code__,dict(parent.__globals__,Path=SealPath),parent.__name__,parent.__defaults__,parent.__closure__)
    clone.__kwdefaults__=parent.__kwdefaults__
    ns['verify_seal']=clone;ns['Path']=SealPath


    parent_sha=namespace['sha256']
    def sha(path):
        p=Path(path)
        return parent_sha(original if p==fresh/'SEAL.json' else path)
    ns['sha256']=sha
    return ns

def _original_capture(a,request):

    from runtime_entries import _entry
    _,producer,_=_entry(a,'capture')
    with a._validation():
        execution=_json(_snapshot(request['capture_evidence'],a.project))
        clock=_json(_snapshot(execution['original_clock'],a.project))
        capture=_json(_snapshot(execution['original_capture'],a.project))
        armed=_json(_snapshot(clock['armed'],a.project))
        plan=_snapshot(clock['plan'],a.project)
        callback=a._ap_runtime.member(str(a.q/a._science_policy['families']['scoring_callback']['freeze']))
        frozen=_json(_snapshot(callback,a.project))
        if frozen.get('plan')!=clock['plan'] or armed.get('plan')!=clock['plan']:
            raise ContractError('Capture callback plan/freeze lineage')
        if execution.get('producer_code')!=producer or execution.get('callback_freeze')!=callback:
            raise ContractError('Capture producer/freeze lineage')
        if clock.get('state')!='POSTSCORE_CLOCK_ASSOCIATION_VERIFIED' or clock.get('source_verified') is not True \
           or clock.get('retrospective_reconstruction_authorised') is not False:
            raise ContractError('Missing honest native original completion')
        cp=a._scorer_contract['capture_contract']
        if capture.get('schema')!=cp['schema'] or capture.get('state')!=cp['state'] or capture.get('clock_association')!=execution['original_clock'] \
           or capture.get('source_values_decoded') is not False or capture.get('pending_is_negative') is not False:
            raise ContractError('Immediate opaque capture invalid')
        import science_contract as S
        complete=clock['completion_evidence'];argv=a._scorer_contract['original']['argv']
        if complete.get('kind')!='SOURCE_OBSERVED_SPECIFIED_COMMAND_EXIT' or complete.get('argv')!=argv \
           or complete.get('exit_status')!=0 or complete.get('receipt_contents_decoded') is not False \
           or complete.get('no_postscore_launches_confirmed') is not True:
            raise ContractError('Original exit/embargo invalid')
        if armed.get('state')!='ARMED_AFTER_T5_BEFORE_SCORE' or armed.get('score_argv')!=argv \
           or armed.get('callback_freeze')!=callback or armed.get('score_receipt_absent') is not True \
           or armed.get('no_postscore_launches_confirmed') is not True:
            raise ContractError('Original arming invalid')
        t5=_identity(a.out/'T5_BINDING.json',a.out)
        if clock['t5_binding']!=t5 or armed['t5_binding']!=t5 or clock['plan'] not in a._t5_value['files']:
            raise ContractError('Capture actual T5 drift')
        core=__import__('runtime_sources')._Core(vars(sys.modules[a.__class__.__module__]))
        import datetime as dt
        cutoff=max(S._utc(core,clock['score_complete_utc']),dt.datetime(2026,10,6,1,tzinfo=dt.timezone.utc))
        if S._utc(core,capture['cutoff_utc'])!=cutoff or S._utc(core,capture['observed_utc'])<cutoff or not(S._utc(core,clock['callback_ready_utc'])<=S._utc(core,capture['observed_utc'])<=S._utc(core,execution['capture_complete_utc'])):
            raise ContractError('Native cutoff/capture chronology')
        rows=capture.get('files',[])
        S._capture_census(a,core,clock,capture,cp)
        if len(rows)!=len({x['path'] for x in rows}):raise ContractError('Capture duplicate identity')
        for row in rows:_snapshot(row,a.project)
        if clock['conf_score_receipt']!=execution['original_receipt']:raise ContractError('Captured original receipt drift')
        from runtime_resolution import _wire
        original=_wire(a)['original'];seal=original['seal_identity']
        completion=L._complete(a,Path(original['receipt_path']).parent,execution['original_receipt'],state='FROZEN_SCORE_COMPLETE',seal_sha256=seal['sha256'])
        completion['seal']=seal
        return execution,completion

def _run_r2(a,request):
    _phase(a.project,a.synthetic);a.verify_t5_coverage();a.authorize_ap_route('AP5')
    from runtime_resolution import _wire,_permit
    resolved=_wire(a);wire=resolved['r2'];root=_canonical(wire['state_root'],a.project)
    if request.get('schema')!='C_SCORING_R2_DISPATCH_REQUEST_V1' or request['state_root']!=str(root) or request['feature_root']!=wire['feature_root']:raise ContractError('R2 dispatch request/state')
    if (wire.get('permit_identity') is not None and request['permit_identity']!=wire['permit_identity']) or request['seal_association']!=wire['state_seal_association']:
        raise ContractError('Actual R2 permit/state association differs from reviewed contract')
    with a._validation():
        captured,original=_original_capture(a,request)
        _snapshot(request['permit_identity'],a.project)
        _snapshot(wire['seal_identity'],a.project)


    with _namespace(a) as (ns,runtime):
        with a._validation():
            permit=_permit(a,wire,request['permit_identity'])
        ns=_seal_bridge(ns,wire['state_seal_association'])
        with a._source_loading():r2=a._load_verified(R2)
        pin=a._effective_sources[R2]['identity'];code=dict(path=str(__import__('consumer_roots').LIVE/R2),**pin)
        import datetime as dt
        started=dt.datetime.now(dt.timezone.utc).isoformat()
        if dt.datetime.fromisoformat(started)<=dt.datetime.fromisoformat(captured['capture_complete_utc'].replace('Z','+00:00')):raise ContractError('R2 before immediate capture')
        try:
            with L._producer(a,code,root,read_ids=[wire['seal_identity'],request['permit_identity']],sealed_reads=True):
                result=r2.official_score(ns,permit,Path(request['feature_root']),root)
                with a._validation():
                    receipt_id=_identity(Path(wire['receipt_path']),root)
                    completed=L._complete(a,root/'scored',receipt_id,state='FROZEN_SCORE_COMPLETE',seal_sha256=wire['seal_identity']['sha256'],marker=wire['evaluation_view'])
                    if {p.name for p in root.iterdir()}!={'scored'}:raise ContractError('Unsealed extra fresh-state output')
        except BaseException:
            a._official_ready=None;a.revoke_ap_route();raise
        ended=dt.datetime.now(dt.timezone.utc).isoformat()
        completed['seal']=wire['seal_identity']

        from runtime_entries import _call
        fn,callback_code,_=__import__('runtime_entries')._entry(a,'r2_complete')
        callback_scope=resolved['completion_scope']
        with a._validation():
            clock=_json(_snapshot(captured['original_clock'],a.project))
            controls=[captured['original_clock'],captured['original_capture'],clock['armed'],clock['plan'],*callback_scope.get('control_identities',[])]
            indexed={x['path']:x for x in controls}
            if set(indexed)!=set(callback_scope['control_paths']):raise ContractError('Completion control census omitted/extra')
        with L._producer(a,callback_code,Path(callback_scope['output_root']),read_ids=[receipt_id,*indexed.values()],outputs=callback_scope['output_paths'],opaque=True):
            execution=fn(association=a,original_capture=captured,r2_receipt=receipt_id,r2_start_utc=started,r2_complete_utc=ended,actual_permit_identity=request['permit_identity'])
        a._ap_runtime.member(callback_code['path'])
        a.official_views(original,completed,execution)
        return result
