'Write the checked notice deadline source inventory.'
import argparse
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).absolute().parent
SCHEMA = 'FORECAST_BINDING_FINAL_SOURCE_COMMITMENT_V1'
STATE = 'SOURCE_COMMITMENT_NOT_RUNTIME_FREEZE'


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def identity(path):
    from timestamp_checks import identity as exact_identity
    return exact_identity(path)


def read_json(path):
    import timestamp_checks
    def pairs(items):
        result = {}
        for key,value in items:
            require(key not in result, 'Duplicate final-source/interface JSON key')
            result[key] = value
        return result
    return json.loads(timestamp_checks.read_metadata(path),object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(RuntimeError('Nonfinite JSON')))


def overlay_source_inventory(here=HERE):

    here = Path(here).absolute()
    files = [*here.glob('*.py'),*(here/'tests').glob('*.py')]
    files += [here/name for name in ('SPEC.md','HOST_PROCEDURE.md','T5_ROWS.md',
        'T5_ROWS.json','ACTIVATION.template.json','AM3_FINAL_SOURCE_INTERFACE.md',
        'AM3_FINAL_SOURCE_INTERFACE.json','REPORT.md',
        'SOURCE_ATTESTATION.template.json')]
    return {str(p.relative_to(here)): identity(p) for p in sorted(set(files))}


def record_final_source(*, here=HERE):
    import timestamp_checks
    import root_mapping
    import freeze_overlay
    here = Path(here).absolute()
    require(here == Path(timestamp_checks.HERE).absolute(), 'Exact effective overlay source root required')
    historical = timestamp_checks.historical_snapshot(verify_current=True,verify_tsa=True)
    specifications = timestamp_checks.verify_specification()
    require(specifications.get('schema') == 'FORECAST_BINDING7_DEADLINE_AUTHORITY_V2' and
            'new_calendar_deadline' in specifications and specifications['new_calendar_deadline'] is None and
            [row['timestamp']['label'] for row in specifications['ordered_specifications']] == ['T4I','T4J'] and
            specifications.get('calendar_rule') == 'NO_CALENDAR_DEADLINE_CORRECTED_SEAL_PRECEDES_T5',
            'AM1 then AM2 no-calendar timestamp_checks required')
    mapping_path = here/'FINAL_ROOT_MAPPING.json'
    mapping = root_mapping.verify_final_mapping(mapping_path)
    sources = overlay_source_inventory(here)
    preflight = freeze_overlay.source_preflight(here=here)
    require(preflight['sources'] == sources, 'Final source inventory differs from reviewed overlay preflight')
    interface_path = here/'AM3_FINAL_SOURCE_INTERFACE.json'
    interface = read_json(interface_path)
    require(interface.get('schema') == 'FORECAST_BINDING_AM3_FINAL_SOURCE_INTERFACE_V1' and
            interface.get('state') == 'CONTRACT_PENDING_FINAL_SOURCE_COMMITMENT' and
            interface.get('calendar_rule') == 'NO_CALENDAR_DEADLINE_CORRECTED_SEAL_PRECEDES_T5',
            'Exact separate historical/final-source AM3 interface required')
    return dict(schema=SCHEMA,state=STATE,
        historical_snapshot=historical,
        final_base_source_rows=historical['files'],
        overlay_sources=sources,
        test_receipt=preflight['test_receipt'],
        final_root_mapping=identity(mapping_path),
        final_root_mapping_sha256=mapping['root_mapping_sha256'],
        final_consumer_task_revision=mapping['consumer_task_revision'],
        specification_authorities=specifications,
        am3_interface=identity(interface_path),
        calendar_rule='NO_CALENDAR_DEADLINE_CORRECTED_SEAL_PRECEDES_T5',
        deadline_aedt=None,
        runtime_sources=dict(af_code_freeze=None,overlay_freeze=None,overlay_timestamp_binding=None),
        runtime_authority_rule='Pending separately; source commitment never asserts runtime freeze/TSA/host eligibility',
        historical_equals_final=False,
        source_commitment_complete=True,
        numerical_computation_changed=False,
        production_state_reads=0,production_commands_run=0,production_lock_probes=0,
        timestamp_created=False,runtime_freeze_created=False)


def verify_final_source(path=HERE/'FINAL_SOURCE_COMMITMENT.json', *, here=HERE):
    import timestamp_checks
    here = Path(here).absolute()
    require(Path(path).absolute() == here/'FINAL_SOURCE_COMMITMENT.json',
            'Exact final source commitment path required')
    value = read_json(path)
    require(value == record_final_source(here=here), 'Final AF source/mapping/timestamp_checks drift')
    return value


def publish_final_source(*, here=HERE):

    require(os.getpriority(os.PRIO_PROCESS,0) == 20, 'Source publisher requires nice20')
    value = record_final_source(here=here)
    target = Path(here)/'FINAL_SOURCE_COMMITMENT.json'
    payload = (json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode()
    fd = os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444)
    with os.fdopen(fd,'wb') as f:
        f.write(payload); f.flush(); os.fsync(f.fileno())
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--source-publish',action='store_true')
    modes.add_argument('--verify',action='store_true')
    args = parser.parse_args()
    if args.source_publish:
        require(os.environ.get('FORECAST_BINDING_SOURCE_SOURCE_COMMITMENT') == '1',
                'Source-only final source publication')
        publish_final_source()
        print('Final AF sources committed separately from pending runtime freezes')
    else:
        verify_final_source()
        print('Final AF source commitment verified; runtime timestamp_checks remains separate')


if __name__ == '__main__':
    try:
        main()
    except (OSError,ValueError,RuntimeError,KeyError,TypeError) as exc:
        raise SystemExit('forecast_hashes notice_records SOURCE REFUSED: '+str(exc))
