'Write the source inventory for delayed notice forecasts.'
import argparse
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).absolute().parent
SCHEMA = 'FORECAST_BINDING_FINAL_SOURCE_COMMITMENT_V2'
STATE = 'SOURCE_COMMITMENT_NOT_RUNTIME_FREEZE'
CALENDAR_RULE = 'NO_CALENDAR_DEADLINE_CORRECTED_SEAL_PRECEDES_T5'
DOCUMENTS = ('SPEC.md','HOST_PROCEDURE.md','T5_ROWS.md','T5_ROWS.json',
             'ACTIVATION.template.json','AM3_FINAL_SOURCE_INTERFACE.md',
             'AM3_FINAL_SOURCE_INTERFACE.json','REPORT.md',
             'SOURCE_ATTESTATION.template.json')


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def identity(path):
    from delay_authority import identity as exact_identity
    return exact_identity(path)


def read_json(path):
    from delay_authority import read_metadata
    def pairs(items):
        value = {}
        for key,item in items:
            require(key not in value,'Duplicate source/interface JSON key')
            value[key] = item
        return value
    return json.loads(read_metadata(path),object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(RuntimeError('Nonfinite JSON')))


def overlay_source_inventory(here=HERE):
    here = Path(here).absolute()
    files = [*here.glob('*.py'),*(here/'tests').glob('*.py')]
    files += [here/name for name in DOCUMENTS]
    return {str(p.relative_to(here)):identity(p) for p in sorted(set(files))}


def record_final_source(*, here=HERE):
    import delay_authority as timestamp_checks
    import delay_root_mapping as root_mapping
    import delay_freeze as freeze
    here = Path(here).absolute()
    require(here == Path(timestamp_checks.HERE).absolute(),'Exact final delay-overlay root required')
    parents = timestamp_checks.verify_unchanged_parents()
    historical = timestamp_checks.historical_snapshot(verify_current=True,verify_tsa=True)
    specifications = timestamp_checks.verify_specification()
    require(specifications.get('schema') == 'FORECAST_BINDING7_DEADLINE_AUTHORITY_V2' and
            specifications.get('calendar_rule') == CALENDAR_RULE and
            'new_calendar_deadline' in specifications and specifications['new_calendar_deadline'] is None and
            [row['timestamp']['label'] for row in specifications['ordered_specifications']] == ['T4I','T4J'],
            'Exact ordered AM1/AM2 no-calendar authorities required')
    decision = timestamp_checks.verify_decision()
    require(decision.get('schema') == 'FORECAST_BINDING8_REVIEW8_DECISION_AUTHORITY_V1' and
            decision.get('delay_minutes') == [15,60] and
            decision.get('corrected_arms') == ['L14','L_Laz'] and
            decision.get('primary_seed') == 20260919 and
            decision.get('variant') == 'main' and decision.get('window') == 'D' and
            decision.get('models_refitted') == 0,
            'Exact DEC D1.1 specified delay/arm/model scope required')
    frozen_delay_sources = timestamp_checks.verify_frozen_delay_sources()
    mapping_path = here/'FINAL_ROOT_MAPPING.json'
    mapping = root_mapping.verify_final_mapping(mapping_path)
    require(mapping['contract']['fill_relative_path'] == root_mapping.FILL_REL,
            'Final notice_constraints C mapping required')
    sources = overlay_source_inventory(here)
    preflight = freeze.source_preflight(here=here)
    require(preflight['sources'] == sources,'Reviewed delay-overlay source inventory mismatch')
    interface_path = here/'AM3_FINAL_SOURCE_INTERFACE.json'
    interface = read_json(interface_path)
    require(interface.get('schema') == 'FORECAST_BINDING_AM3_FINAL_SOURCE_INTERFACE_V2' and
            interface.get('state') == 'CONTRACT_PENDING_FINAL_SOURCE_COMMITMENT' and
            interface.get('calendar_rule') == CALENDAR_RULE and
            interface.get('corrected_delay_minutes') == [5,15,60] and
            interface.get('corrected_arms') == ['L14','L_Laz'],
            'Exact additive three-clock final-source interface required')
    require(parents.get('schema') == 'FORECAST_BINDING8_UNCHANGED_PARENT_SOURCES_V1' and
            parents.get('parent_overlay_files') and parents.get('parent_overlay_source_rows') and
            historical['files'] == parents['historical_T4F']['files'],
            'Historical T4F/OV1 delivery separation required')
    return dict(schema=SCHEMA,state=STATE,historical_snapshot=historical,
        final_base_source_rows=historical['files'],
        parent_overlay_sources=parents['parent_overlay_files'],
        parent_overlay_source_rows=parents['parent_overlay_source_rows'],
        parent_overlay_delivery=parents['parent_overlay_delivery'],
        parent_overlay_test_receipt=parents['parent_overlay_test_receipt'],
        overlay_sources=sources,test_receipt=preflight['test_receipt'],
        resource_projection=preflight['resource_projection'],
        speed_overlay_binding=preflight['speed_overlay_binding'],
        final_root_mapping=identity(mapping_path),
        final_root_mapping_sha256=mapping['root_mapping_sha256'],
        final_consumer_task_revision=mapping['consumer_task_revision'],
        specification_authorities=specifications,review8_decision_authority=decision,
        frozen_delay_sources=frozen_delay_sources,
        am3_interface=identity(interface_path),calendar_rule=CALENDAR_RULE,deadline_aedt=None,
        corrected_delay_minutes=[5,15,60],corrected_arms=['L14','L_Laz'],
        runtime_sources=dict(af_code_freeze=None,delay_overlay_freeze=None,
                                delay_overlay_timestamp_binding=None),
        runtime_authority_rule='Pending separately; historical snapshots and source commitment are never runtime eligibility',
        historical_equals_final=False,source_commitment_complete=True,
        frozen_numerical_functions_changed=False,models_refitted=0,
        production_state_reads=0,production_commands_run=0,production_lock_probes=0,
        timestamp_created=False,runtime_freeze_created=False)


def verify_final_source(path=HERE/'FINAL_SOURCE_COMMITMENT.json', *, here=HERE):
    here = Path(here).absolute()
    require(Path(path).absolute() == here/'FINAL_SOURCE_COMMITMENT.json',
            'Exact final delay-overlay commitment path required')
    value = read_json(path)
    require(value == record_final_source(here=here),'Final delay source/mapping/timestamp_checks drift')
    return value


def publish_final_source(*, here=HERE):
    require(os.getpriority(os.PRIO_PROCESS,0) == 20,'Source publisher requires nice20')
    value = record_final_source(here=here)
    target = Path(here)/'FINAL_SOURCE_COMMITMENT.json'
    payload = (json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode()
    fd = os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444)
    with os.fdopen(fd,'wb') as f:
        f.write(payload); f.flush(); os.fsync(f.fileno())
    return value


def main():
    import types
    sys.path.insert(0,str(HERE.parent/'code'))
    for alias,name in (('delay_authority','timestamp_checks.py'),('delay_root_mapping','root_mapping.py'),
                       ('delay_speed_binding','speed_binding.py'),
                       ('delay_final_source','source_inventory.py'),('delay_freeze','freeze_delay.py')):
        if alias not in sys.modules:
            module = types.ModuleType(alias); module.__file__ = str(HERE/name)
            sys.modules[alias] = module
            exec(compile((HERE/name).read_bytes(),str(HERE/name),'exec'),module.__dict__)
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--source-publish',action='store_true')
    modes.add_argument('--verify',action='store_true')
    args = parser.parse_args()
    if args.source_publish:
        require(os.environ.get('FORECAST_BINDING_SOURCE_SOURCE_COMMITMENT') == '1',
                'Source-only final source publication')
        publish_final_source()
        print('T4F/OV1 historical sources and OV2 final sources committed separately from runtime freeze')
    else:
        verify_final_source()
        print('Final delay source commitment verified; runtime timestamp_checks remains separate')


if __name__ == '__main__':
    try:
        main()
    except (OSError,ValueError,RuntimeError,KeyError,TypeError) as exc:
        raise SystemExit('FORECAST_BINDING8 notice_records SOURCE REFUSED: '+str(exc))
