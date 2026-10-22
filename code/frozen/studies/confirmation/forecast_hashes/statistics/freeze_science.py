'Save validated numerical sources and their input records.'
from pathlib import Path
from contextlib import ExitStack
from science_contract import RECEIPT_SCHEMA,clean_receipt,exact_inventory,require,digest
import metadata_io as io
TASK_REVISION='AF9_statistics_V3'
HERE=io.HERE


def source_preflight(receipt,*,sources,expected_sources,test_ids,selected_speed,expected_speed,
                     stable_c_contract,suite_manifest=None):
    require(isinstance(suite_manifest,dict) and suite_manifest.get('state')=='EXACT_SOURCE_SCIENTIFIC_CENSUS'
            and suite_manifest.get('test_ids')==test_ids and suite_manifest.get('sources')==sources
            and suite_manifest.get('mixed_test_migrations_pending')==0
            and suite_manifest.get('legacy_scientific_gates_covered') is True
            and suite_manifest.get('removed_writing_roots_unavailable_test_required') is True,
            'Exact scientific census/migrations required; seam tests alone cannot pass')
    exact_inventory(sources,expected_sources)
    require(stable_c_contract.get('stable') is True and stable_c_contract.get('owner_agreed') is True
            and stable_c_contract.get('source_inventory_finalization_pending',False) is False,
            'Delivered scientific C source contract required')
    require(selected_speed and selected_speed==expected_speed,'Selected speed drift')
    clean_receipt(receipt,schema=RECEIPT_SCHEMA,revision=TASK_REVISION,sources=sources,test_ids=test_ids)
    require(receipt.get('selected_speed')==selected_speed
            and receipt.get('c_scientific_contract_sha256')==digest(stable_c_contract)
            and receipt.get('removed_writing_roots_unavailable') is True,
            'New exact C/speed and removed-writing acceptance required; obsolete AF8B/AF9 refused')
    return dict(sources=sources,tests=receipt,selected_speed=selected_speed,runtime_authority=False)


def delivery_preflight(here=HERE):
    from source_inventory import overlay_source_inventory
    from runtime_bridge import frozen_modules
    m=frozen_modules();speed=m['delay_speed_binding'].verify_speed_delivery()
    sources=overlay_source_inventory(here);spec=io.read_json(Path(here)/'SCIENTIFIC_ACCEPTANCE_SPEC.json')
    contract=io.read_json(Path(here)/'C_INTERFACE_CONTRACT.json')
    path=Path(here)/'VALIDATION_SCORING/full3/SCIENTIFIC_ACCEPTANCE_RECEIPT.json'
    receipt=io.read_json(path)
    manifest=dict(spec,state='EXACT_SOURCE_SCIENTIFIC_CENSUS',sources=sources)
    result=source_preflight(receipt,sources=sources,expected_sources=sources,test_ids=spec['test_ids'],
        selected_speed=speed,expected_speed=speed,stable_c_contract=contract,suite_manifest=manifest)
    result.update(test_receipt=io.identity(path),resource_projection=io.identity(Path(here)/'RESOURCE_PROJECTION.json'),
                  speed_overlay_binding=speed)
    return result


def source_association(committed,preflight,parents,mapping_identity):
    require(committed.get('schema')=='AF_SCORING_FINAL_SOURCE_COMMITMENT_V2'
            and committed.get('overlay_sources')==preflight['sources']
            and committed.get('parent_overlay_sources')==parents['parent_overlay_files']
            and committed.get('parent_overlay_source_rows')==parents['parent_overlay_source_rows']
            and committed.get('parent_overlay_delivery')==parents['parent_overlay_delivery']
            and committed.get('resource_projection')==preflight['resource_projection']
            and committed.get('speed_overlay_binding')==preflight['speed_overlay_binding']
            and committed.get('final_root_mapping')==mapping_identity,
            'Scientific final source/historical/speed/mapping association drift')


def create(review_acceptance,consumer_acceptance,attestation):
    io.phase(source_flag='FORECAST_BINDING_SOURCE_FREEZE')
    from runtime_bridge import frozen_modules,delay_freezer_provider,metadata_aliases
    m=frozen_modules();m['common'].resources()
    provider=delay_freezer_provider()
    with metadata_aliases([provider,m['common'],m['run_bound_forecasts'],m['delay_authority']]):
        return provider.create(review_acceptance,consumer_acceptance,attestation)


def verify_delay_freeze():
    io.phase(source_flag=('FORECAST_BINDING_SOURCE_FREEZE','FORECAST_BINDING_SOURCE_RUN','FORECAST_BINDING_SOURCE_TIMESTAMP_BIND'))
    from runtime_bridge import frozen_modules,delay_freezer_provider,metadata_aliases
    m=frozen_modules();provider=delay_freezer_provider()
    with metadata_aliases([provider,m['common'],m['run_bound_forecasts'],m['delay_authority']]):return provider.verify_delay_freeze()


def timestamp_required_identities(frozen):
    from runtime_bridge import delay_freezer_provider
    provider=delay_freezer_provider();rows=provider.timestamp_required_identities(frozen)
    committed=io.read_json(frozen['final_source_commitment']['path'])
    rows += list(committed['consumer_scientific_source_rows'].values())
    rows += [committed['consumer_scientific_authority']]
    unique={}
    for row in rows:
        require(row['path'] not in unique or unique[row['path']]==row,'Conflicting scientific timestamp member')
        unique[row['path']]=row
    return [unique[k] for k in sorted(unique)]


def verify_delay_release():
    io.phase(source_flag='FORECAST_BINDING_SOURCE_RUN')
    from runtime_bridge import frozen_modules,delay_freezer_provider,metadata_aliases
    m=frozen_modules();provider=delay_freezer_provider()
    provider.timestamp_required_identities=timestamp_required_identities
    with metadata_aliases([provider,m['common'],m['run_bound_forecasts'],m['delay_authority']]):return provider.verify_delay_release()


def main():
    io.phase(source_flag='FORECAST_BINDING_SOURCE_FREEZE')
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--source-freeze',action='store_true',required=True)
    for n in ('review-acceptance','consumer-acceptance','source-attestation'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();create(a.review_acceptance,a.consumer_acceptance,a.source_attestation)

if __name__=='__main__':main()
