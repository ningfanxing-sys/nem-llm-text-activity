'Write checked result records to the export directory.'
import json
from pathlib import Path
from ..input_checks import HERE, require, artificial_accept
from ..numeric.runtime import Runtime, installed
from .delay_adapter import Evaluator
from .specified_scalars import evaluate_artificial, write_artificial as scalar_write
from .projection import project
from .formats import write_artificial as official_write
from .sensitivity_writer import write_artificial as loss_write


def run(*,association,request,argv,scientific_scope):
    installed(association);root=artificial_accept(association.project)
    require(association.synthetic is True and isinstance(argv,list) and not argv and callable(scientific_scope),'Exact artificial AP6 ABI')
    require(request['score_views']==association._official_ready['view_inputs'],'Both current views required')
    values=request['function_kwargs'];require(set(values)=={'scientific_contract','numeric_source','rd_source','receipts','output_directory','loss_exports'},'AP6 exact request census')
    runtime=Runtime(association,values['scientific_contract'])
    numeric_source,rd_source=values['numeric_source'],values['rd_source']
    runtime.verify_rd_eligibility(rd_source,numeric_source,values['receipts'])
    record=runtime.checked_payload(numeric_source);rd=runtime.checked_payload(rd_source)
    original=runtime.verified_original_attachment(record)
    require(all(values['receipts'][view]==association._official_ready['view_inputs'][view]['score_receipt']['sha256']
                for view in ('original','r2')),'Export/current official receipt identity drift')
    exports={task:runtime.checked_payload(values['loss_exports'][task]) for task in ('news','notice')}
    from .sensitivity_validation import validate_publication
    exports=validate_publication(exports,record,numeric_source,runtime)
    qualifications=evaluate_artificial(record,rd,numeric_source=numeric_source,rd_source=rd_source,
        receipts=values['receipts'],evaluator=Evaluator(runtime),runtime=runtime,fixture_root=root)
    output=Path(values['output_directory']);require(output.resolve()==output and output.is_relative_to(root) and not output.exists(),'Fresh detached AP6 directory')

    for item in (numeric_source,rd_source,runtime.contract['original_attachment'],
                 values['loss_exports']['news'],values['loss_exports']['notice'],
                 exports['news']['replay_binding']['numeric_receipt'],
                 exports['news']['replay_binding']['numeric_evidence']):runtime.checked_payload(item)
    runtime.verified_original_attachment(record)
    runtime.reverify_official_views()
    output.mkdir(parents=True,exist_ok=False)
    qualification_source=scalar_write(qualifications,output/'AP_SCORING_SPECIFIED_SCALARS.json',fixture_root=root,reverify=runtime.reverify_official_views)
    census=json.loads(runtime.checked_source(HERE/'SLOT_CENSUS.json'))
    projected=project(record,rd,qualifications=qualifications,qualification_source=qualification_source,census=census,
        numeric_source=numeric_source,rd_source=rd_source,original_source=runtime.contract['original_attachment'],
        original_document=original,receipts=values['receipts'])
    official=official_write(projected,output/'official',fixture_root=root,reverify=runtime.reverify_official_views)
    detached=loss_write(exports,output/'sensitivity_export',fixture_root=root,reverify=runtime.reverify_official_views)
    runtime.reverify_official_views()
    return dict(official=official,specified_scalar_source=qualification_source,sensitivity_export=detached,production_authority=False)
