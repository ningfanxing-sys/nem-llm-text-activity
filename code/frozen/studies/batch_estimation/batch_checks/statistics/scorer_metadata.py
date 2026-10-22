'Associate scorer metadata keys with their saved source records.'
from pathlib import Path
from types import FunctionType
from contract_io import ContractError,_snapshot,_json

SCHEMA='C_SCORING_SCORER_METADATA_V1'
STATE='A8_SCORER_CODE_FROZEN_BEFORE_T5'

def _verify(a,module,path=None):
    target=Path(path or a.out/'SCORER_CODE_FREEZE.json')
    with a._validation():
        item=a._authority_files.get(str(target))
        if item is None:raise ContractError('Scorer metadata not independently T5-bound')
        actual=_json(_snapshot(item,a.out))
        if actual.get('schema')!=SCHEMA or actual.get('state')!=STATE:raise ContractError('Scientific scorer metadata missing/unfrozen')
        import datetime as dt
        frozen=dt.datetime.fromisoformat(actual['frozen_utc'].replace('Z','+00:00'));t5=dt.datetime.fromisoformat(a._t5_value['utc'].replace('Z','+00:00'))
        if frozen.utcoffset()!=dt.timedelta(0) or not frozen<t5:raise ContractError('Scorer metadata must freeze strictly before actual T5')
        if 'table_results_freeze' in actual:raise ContractError('Whole FILL timestamp_checks cannot enter scientific scorer metadata')
        if actual['numerical_inputs']['path']!=str(a.out/'SCIENCE_FREEZE.json'):
            raise ContractError('Wrong distinct scientific timestamp_checks')
        for row in (actual['numerical_inputs'],actual['batch_code_freeze'],actual['scorer_bindings'],*actual['files']):
            _snapshot(row,a.project)
    original=module.__dict__['_scoring_original_verify']
    parent_read=original.__globals__['read_json']
    def read(p):
        if Path(p)==target:return dict(actual,table_results_freeze=actual['numerical_inputs'])
        return parent_read(p)
    fn=FunctionType(original.__code__,dict(original.__globals__,read_json=read),original.__name__,(target,),original.__closure__)
    fn.__kwdefaults__=original.__kwdefaults__
    value=fn(target)
    if value.get('code_sha256')!=actual['code_sha256']:raise ContractError('Native scorer computation/source inventory drift')
    return actual

def _install(a,module):
    if '_scoring_original_verify' in vars(module):return
    module.__dict__['_scoring_original_verify']=module.verify
    module.OUT=Path(a.out)
    def verify(path=None):return _verify(a,module,path)
    module.verify=verify
    def no_writer(*args,**kwargs):raise ContractError('Freezing is source-only, outside consumer API')
    module.candidate=no_writer;module.create=no_writer

def _proposal(a,common,bindings_id,test_provenance_id,scientific_authority_id):

    with a._validation():
        import consumer_roots as C
        code_identity=dict(path=str(C.LIVE/C.B_REL/'CODE_FREEZE.json'),**a.lock['authorities'][C.B_REL+'/CODE_FREEZE.json'])
        frozen=_json(_snapshot(code_identity,C.LIVE))
        original_tests=frozen['test_receipts_provenance']['tests']
        if original_tests['path']!=str(C.LIVE/C.B_REL/'TEST_RESULTS.json') or original_tests!=test_provenance_id:
            raise ContractError('Exact original declared test provenance required')
        bindings=_json(_snapshot(bindings_id,a.out));tests=_json(_snapshot(test_provenance_id,C.LIVE))
        if bindings.get('schema')!='C_SCORING_SCORER_BINDINGS_V1' or bindings.get('source_reviewed') is not True:
            raise ContractError('Reviewed distinct scorer bindings required')
        if bindings.get('scientific_authority_contract')!=dict(path=str(a.out/'SCIENCE_FREEZE.json'),schema='C_SCORING_SCIENTIFIC_FREEZE_V1',state='SCIENTIFIC_CONSUMER_FROZEN_BEFORE_T5'):
            raise ContractError('Wrong finite scientific timestamp_checks source contract')
        if tests.get('passed') is not True or tests.get('scorer_code_sha256')!=common.code_hashes('scorer'):
            raise ContractError('Frozen original exact scorer/parity test provenance required')
        timestamp_checks=_json(_snapshot(scientific_authority_id,a.out))
        if scientific_authority_id['path']!=str(a.out/'SCIENCE_FREEZE.json') or timestamp_checks.get('schema')!='C_SCORING_SCIENTIFIC_FREEZE_V1' or timestamp_checks.get('state')!='SCIENTIFIC_CONSUMER_FROZEN_BEFORE_T5':
            raise ContractError('Canonical completed distinct scientific timestamp_checks required')
        paths=common.code_files('scorer');keys={str(p.relative_to(a.b)) for p in paths}
        if len(paths)!=len(keys) or set(tests['scorer_code_sha256'])!=keys:raise ContractError('Exact original scorer inventory required')
        from contract_io import _identity
        for p in paths:
            actual=_identity(p,a.b)
            if actual['sha256']!=tests['scorer_code_sha256'][str(p.relative_to(a.b))] or actual!=a._authority_files.get(str(p)):
                raise ContractError('Scorer source lacks exact checked original timestamp_checks')
        return dict(schema=SCHEMA,state='SCIENTIFIC_SCORER_METADATA_PROPOSAL_NOT_FREEZE',
                    numerical_inputs=scientific_authority_id,scorer_bindings=bindings_id,
                    batch_code_freeze=common.identity(a.b/'CODE_FREEZE.json'),
                    code_sha256=common.code_hashes('scorer'),files=[common.identity(p) for p in common.code_files('scorer')],
                    test_provenance=test_provenance_id,production_fits=0)
