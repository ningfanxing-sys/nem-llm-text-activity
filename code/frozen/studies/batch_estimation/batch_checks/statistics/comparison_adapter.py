'Connect checked comparison inputs to numerical evaluation functions.'
import contextlib
from contract_io import ContractError
from runtime_entries import _entry

@contextlib.contextmanager
def _scope(a,producer,contract):
    if a._official_ready is None:raise ContractError('Both official receipts/capture required')
    a._check_official_score(a._official_ready)
    assembly,assembly_pin,_=_entry(a,'numeric_assembly')
    validator,validator_pin,_=_entry(a,'author_validation')


    P=producer.P
    original_deps,original_assembly=P.dependencies,P.assemble_output
    def deps(*args,**kwargs):
        kwargs['consumer']=False
        return original_deps(*args,**kwargs)
    def assemble(*args,**kwargs):
        return assembly(association=a,args=args,kwargs=kwargs,scientific_contract=contract,author_validator=validator)
    with a._source_loading():branch=a._load_verified('comparison_inputs/code/consumer_branch.py')
    P.dependencies=deps;P.assemble_output=assemble
    try:


        with branch.scope(producer,contract):yield producer
        a._ap_runtime.member(assembly_pin['path']);a._ap_runtime.member(validator_pin['path'])
        a._check_official_score(a._official_ready)
    finally:P.dependencies=original_deps;P.assemble_output=original_assembly
