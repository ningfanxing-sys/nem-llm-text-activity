'Check scoring completion records and forecast observation times.'
import ast
from copy import deepcopy
from pathlib import Path


def _producer(P):
    if P is None:
        import read_comparisons as P
    return P


def validate_official_score(items, expected_receipt_sha256=None, *, synthetic=False, P=None):

    P=_producer(P)
    roles=('seal','score_receipt','score_report')
    P.require(isinstance(items,dict) and set(roles)<=set(items),'Official score identities absent')
    selected={key:deepcopy(items[key]) for key in roles}
    for item in selected.values():
        P.require(isinstance(item,dict) and {'path','sha256'}<=set(item)<= {'path','sha256','bytes'},'Official score closed identity required')
        if 'bytes' in item:P.require(type(item['bytes']) is int and Path(P.checked(item)).stat().st_size==item['bytes'],'Official score byte count drift')
    path=P.HERE/'code/input_specification.py'
    tree=ast.parse(path.read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='load_inputs_v2')
    starts=[i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Subscript) and isinstance(t.value,ast.Name) and t.value.id=='r' and isinstance(t.slice,ast.Constant) and t.slice.value=='score_receipt' for t in n.targets)]
    ends=[i for i,n in enumerate(fn.body) if any(isinstance(x,ast.Constant) and x.value=='Score report not receipt-bound' for x in ast.walk(n))]
    P.require(len(starts)==len(ends)==1 and starts[0]<=ends[0],'Specified official-score rule input_checks drift')
    namespace=dict(P=P,Path=Path,items=selected,r={},synthetic=synthetic)
    body=deepcopy(fn.body[starts[0]:ends[0]+1])
    exec(compile(ast.Module(body=body,type_ignores=[]),str(path),'exec'),namespace)
    receipt=namespace['r']['score_receipt']
    report=P.strict_json(P.checked(selected['score_report']))
    P.require(report.get('state')=='FROZEN_SCORE_COMPLETE' and report.get('seal_sha256')==receipt['seal_sha256'],'Official score report completion/seal mismatch')
    if expected_receipt_sha256 is not None:
        P.require(selected['score_receipt']['sha256']==expected_receipt_sha256,'Official score/source receipt association drift')
    return selected


def late_capture_authority(raw, observed_utc, cutoff_utc, *, P=None):
    P=_producer(P)
    item=raw.get('late_capture_authority')
    P.require(isinstance(item,dict),'Unapproved late cutoff observation refused')
    timestamp_checks=P.strict_json(P.checked(item))
    required={'schema','state','independent','verified_by','official_score','fill_clock','cutoff_utc','observed_utc','files','no_historic_byte_claim'}
    P.require(set(timestamp_checks)==required and timestamp_checks.get('schema')=='A8POST6A_LATE_CAPTURE_AUTHORITY_V1'
              and timestamp_checks.get('state')=='INDEPENDENT_DISCLOSED_DEVIATION_ACCEPTED'
              and timestamp_checks.get('independent') is True and isinstance(timestamp_checks.get('verified_by'),str)
              and bool(timestamp_checks['verified_by'].strip()) and timestamp_checks.get('no_historic_byte_claim') is True,
              'Independent late capture timestamp_checks required')
    P.require(timestamp_checks['official_score']==raw['official_score'] and timestamp_checks['fill_clock']==raw['fill_clock']
              and P.utc(timestamp_checks['cutoff_utc'])==P.utc(cutoff_utc)
              and P.utc(timestamp_checks['observed_utc'])==P.utc(observed_utc) and timestamp_checks['files']==raw['files'],
              'Late capture timestamp_checks exact observation binding mismatch')
    return deepcopy(item)


def cutoff_snapshot(raw, observed_utc, *, prefix='A8POST5', P=None):
    P=_producer(P)
    required={'schema','source_verified','fill_clock','files','official_score'}
    optional={'late_capture_authority','callback_capture'}
    P.require(isinstance(raw,dict) and required<=set(raw)<=required|optional
              and raw.get('schema')==prefix+'_CUTOFF_CLOCK_V1' and raw.get('source_verified') is True,
              'Reviewed cutoff clock and official score required')
    P.require(not ('late_capture_authority' in raw and 'callback_capture' in raw),'Ambiguous late capture authorities')
    official=validate_official_score(raw['official_score'],P=P)
    callback=None
    if 'callback_capture' in raw:
        from scoring_callback_checks import callback_observation
        callback=callback_observation(raw,official,P)
        observed_utc=callback['observed_utc']
    clock=deepcopy(raw['fill_clock']);clock['filled_utc']=observed_utc
    cut=P.fill_cutoff(clock)
    files=raw['files']
    P.require(isinstance(files,list) and len({i['path'] for i in files})==len(files),'Cutoff duplicate file identity')
    for item in files:P.checked(item)
    observed=P.utc(observed_utc);lateness=(observed-cut).total_seconds()
    timestamp_checks=None
    if observed!=cut:
        if callback is not None:timestamp_checks=deepcopy(raw['callback_capture'])
        else:
            try:timestamp_checks=late_capture_authority(raw,observed.isoformat(),cut.isoformat(),P=P)
            except P.Refusal as error:
                error.cutoff_adverse=dict(schema='A8POST6A_CUTOFF_REFUSAL_V1',state='UNAPPROVED_LATE_OBSERVATION_REFUSED',
                    cutoff_utc=cut.isoformat(),observed_utc=observed.isoformat(),capture_lateness_seconds=lateness,
                    official_score=official,files=deepcopy(files),no_historic_byte_claim=True,
                    reason=str(error),usable_cutoff_snapshot=False)
                raise
    result=dict(schema=prefix+'_CUTOFF_IDENTITIES_V1',state='OUTCOME_BLIND_IDENTITY_OBSERVATION',
        cutoff_utc=cut.isoformat(),observed_utc=observed.isoformat(),capture_lateness_seconds=lateness,
        exact_cutoff_observation=observed==cut,files=deepcopy(files),official_score=official,
        pending_is_negative=False,source_values_decoded=False)
    if timestamp_checks is not None:
        result['capture_authority']=timestamp_checks
        result['capture_authority_kind']='scoring_callback' if callback is not None else 'INDEPENDENT_DISCLOSED_DEVIATION'
    return result


def validate_embedded_capture(snapshot, official, fill_clock, *, P=None):

    P=_producer(P)
    P.require(snapshot.get('official_score')==official,'Cutoff/official score exact identities mismatch')
    validate_official_score(official,P=P)
    P.require(snapshot.get('exact_cutoff_observation') is False,'Embedded timestamp_checks requires a late capture')
    kind=snapshot.get('capture_authority_kind')
    P.require(kind in ('INDEPENDENT_DISCLOSED_DEVIATION','scoring_callback')
              and isinstance(snapshot.get('capture_authority'),dict),
              'Late cutoff lacks embedded accepted capture timestamp_checks')
    for item in snapshot['files']:P.checked(item)
    original=None
    if 'clock_identity' in snapshot:


        original=P.strict_json(P.checked(snapshot['clock_identity']))
        key='late_capture_authority' if kind=='INDEPENDENT_DISCLOSED_DEVIATION' else 'callback_capture'
        other='callback_capture' if kind=='INDEPENDENT_DISCLOSED_DEVIATION' else 'late_capture_authority'
        required={'schema','source_verified','fill_clock','files','official_score'}
        P.require(isinstance(original,dict) and set(original)==required|{key}
                  and original.get('schema')=='A8POST5_CUTOFF_CLOCK_V1'
                  and original.get('source_verified') is True and other not in original
                  and validate_official_score(original.get('official_score'),P=P)==official
                  and original.get('files')==snapshot['files']
                  and original.get(key)==snapshot['capture_authority'],
                  'Original capture clock/timestamp_checks identity binding mismatch')
    raw=dict(official_score=official,fill_clock=fill_clock,files=snapshot['files'])
    if kind=='INDEPENDENT_DISCLOSED_DEVIATION':
        raw['late_capture_authority']=snapshot['capture_authority']
        timestamp_checks=P.strict_json(P.checked(raw['late_capture_authority']))
        capture_clock=timestamp_checks.get('fill_clock')
        P.require(isinstance(capture_clock,dict),'Original capture clock required')
        P.require(validate_official_score(timestamp_checks.get('official_score'),P=P)==official,
                  'Original capture official score triplet drift')
        raw['official_score']=deepcopy(timestamp_checks['official_score'])
        if original is not None:
            P.require(original.get('fill_clock')==capture_clock
                      and original.get('official_score')==timestamp_checks['official_score'],
                      'Original capture clock identity drift')
        raw['fill_clock']=deepcopy(capture_clock)
        late_capture_authority(raw,snapshot['observed_utc'],snapshot['cutoff_utc'],P=P)
        clock=deepcopy(capture_clock);clock['filled_utc']=snapshot['observed_utc']
        P.require(P.fill_cutoff(clock)==P.utc(snapshot['cutoff_utc']),'Original capture cutoff drift')
    elif kind=='scoring_callback':
        from scoring_callback_checks import callback_observation
        if original is not None:raw['fill_clock']=deepcopy(original['fill_clock'])
        raw['callback_capture']=snapshot['capture_authority']
        checked=callback_observation(raw,official,P)
        P.require(P.utc(checked['observed_utc'])==P.utc(snapshot['observed_utc']),'Callback saved observation drift')
        capture_clock=raw['fill_clock']
        clock=deepcopy(capture_clock);clock['filled_utc']=checked['observed_utc']
        P.require(P.fill_cutoff(clock)==P.utc(snapshot['cutoff_utc']),'Original callback cutoff drift')
    for key in ('score_utc','authorised_runs'):
        P.require(key in fill_clock and key in capture_clock and fill_clock[key]==capture_clock[key],
                  'Refill fixed cutoff input drift: '+key)
    P.require(P.fill_cutoff(fill_clock,refill=True)==P.utc(snapshot['cutoff_utc']),
              'Refill cutoff differs from original capture')
