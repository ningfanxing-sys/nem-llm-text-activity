'Check the source metadata accompanying a numerical request.'
from contract_io import ContractError,_json,_snapshot,_identity

def _verify(a,command,item,provenance):
    spec=a._scorer_contract['command_contracts'][command]
    with a._validation():
        value=_json(_snapshot(item,a.project))
        witness=_json(_snapshot(provenance,a.project))
        if value.get('schema')!=spec['schema'] or item['path']!=spec['request_path']:
            raise ContractError('Wrong finite reviewed dispatch request schema/path')
        if witness.get('schema')!='C_SCORING_RUNTIME_REQUEST_ASSOCIATION_V1' or witness.get('source_verified') is not True \
           or witness.get('command')!=command or witness.get('request_identity')!=item \
           or witness.get('t5_binding')!=_identity(a.out/'T5_BINDING.json',a.out):
            raise ContractError('Actual detached runtime request association required')
        producer=a._ap_runtime.member(witness['producer_code']['path'])
        if producer!=witness['producer_code']:raise ContractError('Runtime request producer identity drift')
        family=a._ap_runtime.family(producer['path'])
        if family!=spec['producer_family']:raise ContractError('Wrong runtime request producer family')
        for row in witness['parent_identities']:_snapshot(row,a.project)


        if len(witness['parent_identities'])!=len({r['path'] for r in witness['parent_identities']}) or \
           {r['path'] for r in witness['parent_identities']}!=set(spec['parent_paths']):
            raise ContractError('Runtime request parent census omitted/extra/duplicate')
    return value
