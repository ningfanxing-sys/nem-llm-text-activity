'Check numerical source paths for notice forecast inputs.'
from pathlib import Path
from science_contract import SCOPE,CALENDAR_RULE,digest,require,revision_from_source
from speed_selection import validate_selection
from c_interface_adapter import normalize_documents,read_scientific_authority,NATIVE_REVISION
import metadata_io as io
SCHEMA='AF_SCORING_SCIENTIFIC_ROOT_MAPPING_V2'
HERE=io.HERE


def final_mapping_contract(project=io.PROJ):
    c=Path(project)/'studies/batch_estimation/batch_checks/statistics'
    return dict(schema='AF_SCORING_SCIENTIFIC_C_CONTRACT_V2',consumer_root=str(c),
        callable='consumer_roots.Association (source-only, not release)',task_revision=NATIVE_REVISION,
        authority_path=str(c/'SCIENCE_FREEZE.json'),authority_schema='C_SCORING_SCIENTIFIC_FREEZE_V1',
        acceptance_path=str(c/'SCIENTIFIC_ACCEPTANCE_RECEIPT.json'),acceptance_schema='C_statistics_ACCEPTANCE_V1',
        review_path=str(c/'INDEPENDENT_REVIEW.json'),review_schema='C_SCORING_INDEPENDENT_REVIEW_V1',
        actual_identity=None,source_association_only=True,production_authority=False)


def record_final_mapping(base_mapping,*,expected_base,timestamp_checks,receipt,review,contract,sources,
                         revision_source,selected_speed,expected_speed,speed_receipt):
    require(base_mapping and base_mapping==expected_base,'Unchanged frozen numerical/clock/activity mapping required')
    require(sources==contract.get('sources'),'Exact native tested source inventory required')
    require(revision_from_source(revision_source)==NATIVE_REVISION==contract['revision'],'C code/receipt revision drift')
    validate_selection(selected_speed,expected_speed,speed_receipt)
    c=normalize_documents(timestamp_checks,receipt,review,contract)
    return dict(schema=SCHEMA,state='FINAL_REVIEWED_SCIENTIFIC_SOURCE_MAPPING_NOT_FREEZE',
        root_mapping=base_mapping,root_mapping_sha256=digest(base_mapping),consumer=c,
        consumer_task_revision=NATIVE_REVISION,consumer_scientific_contract=contract,
        selected_speed=selected_speed,corrected_scope=SCOPE,calendar_rule=CALENDAR_RULE,deadline_aedt=None,
        scientific_eligibility_changed=False,production_authority=False,actual_mapping_published=False)


def record_native_final_mapping(base_mapping,**kw):
    kw['timestamp_checks']=kw.pop('native_authority');kw['receipt']=kw.pop('native_acceptance');kw['review']=kw.pop('native_review')
    kw.setdefault('sources',kw['contract']['sources']);kw.setdefault('revision_source',"TASK_REVISION='SCORING_C8B_SCIENCE_V1'\n")
    return record_final_mapping(base_mapping,**kw)


def current_mapping(base_mapping=None,*,synthetic=False,c_root=None):
    io.phase(root=c_root,synthetic=synthetic,source_flag=('FORECAST_BINDING_SOURCE_MAPPING_REFRESH','FORECAST_BINDING_SOURCE_SOURCE_COMMITMENT','FORECAST_BINDING_SOURCE_FREEZE','FORECAST_BINDING_SOURCE_RUN','FORECAST_BINDING_SOURCE_TIMESTAMP_BIND'))
    from runtime_bridge import frozen_modules
    m=frozen_modules();hc=m['forecast_inputs'];sb=m['delay_speed_binding']
    base=base_mapping or hc.root_mapping_contract();hc.verify_root_mapping(base)
    c=read_scientific_authority(c_root or final_mapping_contract()['consumer_root'],synthetic=synthetic)
    speed=sb.verify_speed_delivery();test=sb.read(speed['external_receipts']['clean_speed_suite']['path'])
    source=io.snapshot(Path(c['root'])/'science_contract.py')[1]
    value=record_final_mapping(base,expected_base=hc.root_mapping_contract(),timestamp_checks=c['native_authority'],
        receipt=c['native_acceptance'],review=c['native_review'],contract=c['contract'],
        sources=c['contract']['sources'],revision_source=source,selected_speed=speed,expected_speed=speed,speed_receipt=test)
    value['consumer_authority_identity']=c['authority_identity'];value['contract']=final_mapping_contract()
    if synthetic:value['contract']['consumer_root']=c['root']
    return value


def verify_final_mapping(path=HERE/'FINAL_ROOT_MAPPING.json',*,base_mapping=None,synthetic=False,c_root=None):
    io.phase(root=c_root,synthetic=synthetic,source_flag=('FORECAST_BINDING_SOURCE_MAPPING_REFRESH','FORECAST_BINDING_SOURCE_SOURCE_COMMITMENT','FORECAST_BINDING_SOURCE_FREEZE','FORECAST_BINDING_SOURCE_RUN','FORECAST_BINDING_SOURCE_TIMESTAMP_BIND'))
    value=io.read_json(path);expected=current_mapping(base_mapping,synthetic=synthetic,c_root=c_root)
    require(value==expected,'Published scientific mapping/source/review drift')
    return value


def runtime_mapping(base_mapping=None,*,receipt_path=HERE/'FINAL_ROOT_MAPPING.json',**_):
    value=verify_final_mapping(receipt_path,base_mapping=base_mapping)
    return value['root_mapping']


def refresh(base_mapping=None,*,out=HERE,synthetic=False,c_root=None):
    io.phase(root=c_root or out,synthetic=synthetic,source_flag=('FORECAST_BINDING_SOURCE_MAPPING_REFRESH','FORECAST_BINDING_SOURCE_SOURCE_COMMITMENT','FORECAST_BINDING_SOURCE_FREEZE','FORECAST_BINDING_SOURCE_RUN','FORECAST_BINDING_SOURCE_TIMESTAMP_BIND'))
    value=current_mapping(base_mapping,synthetic=synthetic,c_root=c_root)
    io.write_exclusive(Path(out)/'FINAL_ROOT_MAPPING.json',value,root=out,synthetic=synthetic,
                       flag='FORECAST_BINDING_SOURCE_MAPPING_REFRESH')
    return value


def main():
    io.phase(source_flag=('FORECAST_BINDING_SOURCE_MAPPING_REFRESH','FORECAST_BINDING_SOURCE_SOURCE_COMMITMENT','FORECAST_BINDING_SOURCE_FREEZE','FORECAST_BINDING_SOURCE_RUN','FORECAST_BINDING_SOURCE_TIMESTAMP_BIND'))
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--source-refresh',action='store_true',required=True);p.parse_args()
    refresh()

if __name__=='__main__':main()
