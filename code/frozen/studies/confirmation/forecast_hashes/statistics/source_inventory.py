'Save source identities for numerical forecast calculations.'
from science_contract import SCOPE, CALENDAR_RULE, exact_inventory, require, digest

SCHEMA = 'AF_SCORING_FINAL_SOURCE_CANDIDATE_V1'


def record_source_snapshot(*, historical_t4f, expected_t4f, historical_ov1, expected_ov1,
                        numerical_sources, expected_numerical, own_sources, expected_own,
                        mapping, expected_mapping, selected_speed, expected_speed,
                        adoption, expected_adoption, no_calendar_authority, expected_no_calendar):
    exact_inventory(historical_t4f, expected_t4f)
    exact_inventory(historical_ov1, expected_ov1)
    require(len(historical_t4f) == 47 and len(historical_ov1) == 25,
            'Exact separate T4F47 and OV1 historical inventories')
    exact_inventory(numerical_sources, expected_numerical)
    exact_inventory(own_sources, expected_own)
    require(mapping and mapping == expected_mapping and mapping.get('production_authority') is False,
            'Verified scientific source association required')
    require(selected_speed and selected_speed == expected_speed and
            mapping.get('selected_speed') == selected_speed, 'Selected SPEED3 drift')
    require(adoption and adoption == expected_adoption and
            no_calendar_authority and no_calendar_authority == expected_no_calendar,
            'Actual adopted SCORING and ordered AM1/T4I + AM2/T4J timestamp_checks required')
    return dict(schema=SCHEMA, state='CANDIDATE_NOT_PUBLISHED_NOT_FREEZE',
                historical_snapshot={'T4F47': historical_t4f, 'OV1': historical_ov1},
                source_inventory={'numerical_sources': numerical_sources, 'own_sources': own_sources,
                              'scientific_mapping_sha256': digest(mapping), 'selected_speed': selected_speed},
                adoption=adoption, no_calendar_authority=no_calendar_authority,
                historical_equals_final=False, corrected_scope=SCOPE,
                calendar_rule=CALENDAR_RULE, deadline_aedt=None,
                runtime_sources=None, production_authority=False)


from pathlib import Path
import metadata_io as io
HERE=io.HERE
DOCUMENTS=('SPEC.md','HOST_PROCEDURE.md','T5_ROWS.md','T5_ROWS.json','ACTIVATION.template.json',
 'AM3_FINAL_SOURCE_INTERFACE.md','AM3_FINAL_SOURCE_INTERFACE.json','REPORT.md',
 'SOURCE_ATTESTATION.template.json','C_INTERFACE_CONTRACT.json','SCIENTIFIC_ACCEPTANCE_SPEC.json',
 'SCIENTIFIC_TEST_MIGRATION.json','C_INTERFACE_SOURCE_PINS.json','INHERITED_SOURCE_PINS.json',
 'ACCEPT_PLAN_source.md','RESOURCE_PROJECTION.json','SCIENTIFIC_ACCEPTANCE_SPEC.md',
 'C_SCIENTIFIC_INTERFACE_PROPOSAL.json','PENDING_IDENTITIES_BY_OWNER.json','SOURCE_SEQUENCE_TEXT_ONLY.md',
 'MIGRATION_DEPENDENCY_MAP.json','FREEZE_INPUTS_CANDIDATE.json')


def overlay_source_inventory(here=HERE):
    here=Path(here).absolute()
    files=[*here.glob('*.py'),*(here/'tests').glob('*.py'),*[here/n for n in DOCUMENTS]]
    return {str(p.relative_to(here)):io.identity(p) for p in sorted(set(files))}


def record_final_source(*,here=HERE,synthetic=False,c_root=None):
    io.phase(root=here,synthetic=synthetic,source_flag=('FORECAST_BINDING_SOURCE_SOURCE_COMMITMENT','FORECAST_BINDING_SOURCE_FREEZE','FORECAST_BINDING_SOURCE_RUN','FORECAST_BINDING_SOURCE_TIMESTAMP_BIND'))
    from runtime_bridge import frozen_modules
    import root_mapping,freeze_science
    m=frozen_modules();a=m['delay_authority'];here=Path(here)
    parents=a.verify_unchanged_parents();historical=a.historical_snapshot(verify_current=True,verify_tsa=True)
    specifications=a.verify_specification();decision=a.verify_decision();dly=a.verify_frozen_delay_sources()
    validate_source_authorities(specifications,decision,io.read_json(here/'AM3_FINAL_SOURCE_INTERFACE.json'))
    require(parents.get('schema')=='FORECAST_BINDING8_UNCHANGED_PARENT_SOURCES_V1' and parents.get('parent_overlay_files')
            and parents.get('parent_overlay_source_rows') and historical['files']==parents['historical_T4F']['files'],
            'Exact historical T4F/OV1 separation required')
    mapping=root_mapping.verify_final_mapping(here/'FINAL_ROOT_MAPPING.json',synthetic=synthetic,c_root=c_root)
    preflight=freeze_science.delivery_preflight(here)
    c=mapping['consumer'];timestamp_checks=c['native_authority']
    c_root=Path(mapping['contract']['consumer_root']);c_rows={}
    for rel,pin in timestamp_checks['files'].items():
        item=dict(path=str(c_root/rel),**pin);io.snapshot(item['path'],item);c_rows[rel]=item
    sources=overlay_source_inventory(here);require(sources==preflight['sources'],'Scientific source inventory drift')
    return dict(schema='AF_SCORING_FINAL_SOURCE_COMMITMENT_V2',state='SOURCE_COMMITMENT_NOT_RUNTIME_FREEZE',
        historical_snapshot=historical,final_base_source_rows=historical['files'],
        parent_overlay_sources=parents['parent_overlay_files'],parent_overlay_source_rows=parents['parent_overlay_source_rows'],
        parent_overlay_delivery=parents['parent_overlay_delivery'],overlay_sources=sources,
        test_receipt=preflight['test_receipt'],resource_projection=preflight['resource_projection'],
        speed_overlay_binding=preflight['speed_overlay_binding'],final_root_mapping=io.identity(here/'FINAL_ROOT_MAPPING.json'),
        final_root_mapping_sha256=mapping['root_mapping_sha256'],final_consumer_task_revision=mapping['consumer_task_revision'],
        consumer_scientific_source_rows=c_rows,consumer_scientific_authority=mapping['consumer_authority_identity'],
        specification_authorities=specifications,review8_decision_authority=decision,frozen_delay_sources=dly,
        am3_interface=io.identity(here/'AM3_FINAL_SOURCE_INTERFACE.json'),calendar_rule=CALENDAR_RULE,deadline_aedt=None,
        corrected_delay_minutes=[5,15,60],corrected_arms=['L14','L_Laz'],historical_equals_final=False,
        source_commitment_complete=True,runtime_sources=None,models_refitted=0,
        production_authority=False,runtime_freeze_created=False,timestamp_created=False)


def verify_final_source(path=HERE/'FINAL_SOURCE_COMMITMENT.json',*,here=HERE,synthetic=False,c_root=None):
    io.phase(root=here,synthetic=synthetic,source_flag=('FORECAST_BINDING_SOURCE_SOURCE_COMMITMENT','FORECAST_BINDING_SOURCE_FREEZE','FORECAST_BINDING_SOURCE_RUN','FORECAST_BINDING_SOURCE_TIMESTAMP_BIND'))
    value=io.read_json(path);require(value==record_final_source(here=here,synthetic=synthetic,c_root=c_root),'Scientific final-source/mapping/C drift')
    return value


def publish_final_source(*,here=HERE):
    io.phase(source_flag='FORECAST_BINDING_SOURCE_SOURCE_COMMITMENT')
    value=record_final_source(here=here)
    io.write_exclusive(Path(here)/'FINAL_SOURCE_COMMITMENT.json',value,root=here,
                       flag='FORECAST_BINDING_SOURCE_SOURCE_COMMITMENT')
    return value


def main():
    io.phase(source_flag='FORECAST_BINDING_SOURCE_SOURCE_COMMITMENT')
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--source-publish',action='store_true',required=True);p.parse_args()
    publish_final_source()


def validate_source_authorities(specifications,decision,interface):

    require(specifications.get('schema')=='FORECAST_BINDING7_DEADLINE_AUTHORITY_V2'
            and specifications.get('calendar_rule')==CALENDAR_RULE and 'new_calendar_deadline' in specifications
            and specifications['new_calendar_deadline'] is None
            and [r['timestamp']['label'] for r in specifications['ordered_specifications']]==['T4I','T4J'],
            'Exact ordered AM1/T4I and AM2/T4J no-calendar timestamp_checks')
    require(decision.get('schema')=='FORECAST_BINDING8_REVIEW8_DECISION_AUTHORITY_V1'
            and decision.get('delay_minutes')==[15,60] and decision.get('corrected_arms')==['L14','L_Laz']
            and decision.get('primary_seed')==20260919 and decision.get('variant')=='main'
            and decision.get('window')=='D' and decision.get('models_refitted')==0,
            'Unchanged D1.1 scientific scope')
    require(interface.get('schema')=='AF_SCORING_AM3_FINAL_SOURCE_INTERFACE_V2'
            and interface.get('state')=='CONTRACT_PENDING_FINAL_SOURCE_COMMITMENT'
            and interface.get('calendar_rule')==CALENDAR_RULE and interface.get('corrected_delay_minutes')==[5,15,60]
            and interface.get('corrected_arms')==['L14','L_Laz'],'Exact separate historical/final interface')

if __name__=='__main__':main()
