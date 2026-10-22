'Save the checked notice-delay inputs and their source hashes.'
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import types

sys.dont_write_bytecode = True
HERE = Path(__file__).absolute().parent
AF = HERE.parent
VALIDATION_REL = Path('VALIDATION_FORECAST_BINDING9/full_suite/run2')
DOCUMENTS = ('SPEC.md', 'HOST_PROCEDURE.md', 'T5_ROWS.md', 'T5_ROWS.json',
             'ACTIVATION.template.json', 'AM3_FINAL_SOURCE_INTERFACE.md',
             'AM3_FINAL_SOURCE_INTERFACE.json', 'REPORT.md',
             'SOURCE_ATTESTATION.template.json')
SCOPE = {'window': 'D', 'arms': ['L14', 'L_Laz'], 'corrected_delay_minutes': [5, 15, 60],
         'added_delay_minutes': [15, 60], 'seed': 20260919, 'variant': 'main', 'models_refitted': 0}
FRESH_UTC = '2026-10-05T11:28:31+00:00'


def require(ok, why):
    if not ok:
        raise PermissionError(why)


def read(path):
    from delay_authority import read_json
    return read_json(path)


def source_inventory(here=HERE):
    from delay_authority import identity
    here = Path(here).absolute()
    files = sorted(set([*here.glob('*.py'), *here.joinpath('tests').glob('*.py'),
                        *(here / name for name in DOCUMENTS)]))
    return {str(path.relative_to(here)): identity(path) for path in files}


def source_preflight(here=HERE):
    from delay_authority import identity
    from delay_speed_binding import verify_speed_delivery, speed_source_inventory
    here = Path(here).absolute()
    speed_overlay_binding = verify_speed_delivery()
    speed_sources = speed_source_inventory()
    require(speed_sources == speed_overlay_binding['source_inventory'],
            'Exact speed-overlay source inventory and clean engineering receipt binding required')
    sources = source_inventory(here)
    tests_path = here / VALIDATION_REL / 'TEST_RESULTS.json'
    tests = read(tests_path)
    require(tests.get('schema') == 'FORECAST_BINDING8_FULL_SUITE_RECEIPT_V1'
            and tests.get('task') == 'FORECAST_BINDING8' and tests.get('state') == 'PASS_SYNTHETIC_TESTS'
            and all(type(tests.get(name)) is int and tests[name] == 0
                    for name in ('failures', 'errors', 'skipped'))
            and tests.get('historical_tests_run') == 118
            and tests.get('parent_overlay_tests_run') == 44
            and type(tests.get('delay_overlay_tests_run')) is int and tests['delay_overlay_tests_run'] == 76
            and tests.get('tests_run') == 238
            and tests.get('validation_task') == 'FORECAST_BINDING9'
            and tests.get('test_validation_mode') == 'SINGLE_UNSELECTED_FULL_SUITE'
            and tests.get('selected_tests') is False
            and tests.get('code_unchanged') is True
            and isinstance(tests.get('code_before'), dict)
            and tests['code_before'] == tests.get('code_after')
            and tests.get('tests_run') == 162 + tests['delay_overlay_tests_run']
            and tests.get('full_suite_runs') == 1 and tests.get('numerical_processes') == 1
            and tests.get('synthetic_only') is True,
            'One complete passing historical + parent + corrected-delay synthetic suite required')
    require(all(tests.get(name) is True for name in
                ('activity_guard_covered', 'before_t5_guard_covered', 'deadline_overlay_covered',
                 'final_source_interface_covered', 'corrected_delay_covered',
                 'month_first_specified_delay_parity_covered', 'exact_delay_coverage_covered',
                 'single_seal_covered', 'production_speed_overlay_covered',
                 'speed_overlay_identity_covered', 'speed_clean_receipt_required')),
            'Every inherited and joint-delay gate must be covered by the sole suite')
    require(all(tests.get(name) is False for name in
                ('production_state_paths_or_locks_probed', 'real_lock_acquired', 'real_batch_signalled',
                 'freeze_executed', 'timestamp_executed', 'study_predictions_loaded',
                 'study_models_loaded', 'outcomes_loaded')),
            'Source preparation cannot read real study artifacts or operate production state')
    code = {name: row['sha256'] for name, row in sources.items() if name.endswith('.py')}
    speed_code = {name: row['sha256'] for name, row in speed_sources.items()}
    require(tests.get('speed_overlay_binding') == speed_overlay_binding
            and tests.get('speed_source_sha256') == speed_code
            and tests['code_before'].get('speed') == speed_code,
            'Suite must bind the exact validated speed overlay separately from OV2 sources')
    require(tests.get('overlay_code_sha256') == code
            and tests['code_before'].get('overlay') == code, 'Final delay-overlay code changed after its sole full suite')
    require(tests.get('minimum_memory_free_percent', -1) >= 25
            and tests.get('maximum_synthetic_scratch_bytes', 1000000000) < 1000000000
            and tests.get('scratch_under_1GB') is True
            and type(tests.get('maximum_peak_rss_bytes')) is int
            and tests['maximum_peak_rss_bytes'] < 1500000000
            and all(tests.get(name, {}).get('nice') == 20 for name in
                    ('resources_before_numeric_imports', 'resources_before', 'resources_after')),
            'One-process nice20 / 25 percent free / bounded scratch suite evidence required')
    projection_path = here / VALIDATION_REL / 'RESOURCE_PROJECTION.json'
    projection_id = identity(projection_path)
    projection = read(projection_path)
    require(tests.get('resource_projection') == projection_id
            and projection.get('schema') == 'FORECAST_BINDING8_SYNTHETIC_RESOURCE_PROJECTION_V1'
            and projection.get('synthetic_only') is True and projection.get('numerical_processes') == 1
            and projection.get('models_refitted') == 0 and isinstance(projection.get('measurements'), list)
            and len(projection['measurements']) == 8
            and projection.get('actual_projection_or_model_measured') is False
            and projection.get('additional_rebuilds') == 8 and projection.get('additional_predictions') == 8
            and projection.get('corrected_prediction_files') == 6
            and projection.get('real_host_wall_seconds') == 'U' and projection.get('real_peak_RSS_bytes') == 'U',
            'Exact measured synthetic resource projection with explicit unknown real costs required')
    return {'sources': sources, 'test_receipt': identity(tests_path), 'tests': tests,
            'resource_projection': projection_id, 'speed_overlay_binding': speed_overlay_binding}


def interface_identities(here=HERE):
    from delay_authority import identity
    return {'markdown': identity(Path(here) / 'AM3_FINAL_SOURCE_INTERFACE.md'),
            'json': identity(Path(here) / 'AM3_FINAL_SOURCE_INTERFACE.json')}


def _utc(value):
    require(isinstance(value, str), 'Actual UTC date required')
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, TypeError) as exc:
        raise PermissionError('Invalid actual UTC date') from exc
    require(parsed.utcoffset() == dt.timedelta(0), 'Actual date must be UTC')
    return parsed


def additional_acceptance(path, *, schema, preflight, parents, historical, specifications,
                          decision, mapping_identity, commitment_identity, frozen_delay_sources, here=HERE):

    from delay_authority import CALENDAR_RULE, identity
    value = read(path)
    require(value.get('schema') == schema and value.get('state') == 'ACCEPTED_FOR_SOURCE_FREEZE',
            'Genuine original-named AF5 owner acceptance schema/state required')
    expected = {'delay_overlay_reviewed_sources': preflight['sources'],
                'delay_overlay_test_receipt': preflight['test_receipt'],
                'delay_resource_projection': preflight['resource_projection'],
                'speed_overlay_binding': preflight['speed_overlay_binding'],
                'frozen_delay_sources': frozen_delay_sources,
                'deadline_overlay_delivery': parents['parent_overlay_delivery'],
                'deadline_overlay_sources': parents['parent_overlay_files'],
                'historical_T4F': historical, 'specification_authority': specifications,
                'review8_decision_authority': decision, 'final_root_mapping': mapping_identity,
                'final_source_interface': interface_identities(here),
                'final_source_commitment': commitment_identity, 'corrected_delay_scope': SCOPE,
                'calendar_rule': CALENDAR_RULE}
    require(all(value.get(name) == item for name, item in expected.items()),
            'Owner acceptance must bind exact historical parents, new sources, authorities, mapping and joint scope')
    require(_utc(FRESH_UTC) <= _utc(value.get('recorded_utc')) <= dt.datetime.now(dt.timezone.utc)
            and isinstance(value.get('owner'), str) and value['owner'].strip(),
            'Actual fresh owner acceptance must follow the T4K decision')
    if schema == 'FORECAST_BINDING5_REVIEW_ACCEPTANCE_V1':
        require(value.get('independent') is True and all(value.get(name) is True for name in
                    ('date_delay_joint_validation_reviewed', 'all_earlier_gates_preserved',
                     'month_first_specified_delay_parity_reviewed', 'exact_delay_coverage_reviewed',
                     'single_corrected_seal_reviewed')),
                'Independent full date-delay parity/coverage/single-seal and preserved-gate review required')
    else:
        require(value.get('scientific_eligibility_changed') is False
                and all(value.get(name) is True for name in
                    ('corrected_delay_interface_reviewed', 'specified_and_corrected_readings_reported',
                     'joint_weakest_reading_rule_reviewed', 'primary_seed_only_not_inherited_seed_checks',
                     'corrected_seal_must_precede_T5', 't5_metadata_payload_split_reviewed')),
                'Consumer must accept joint corrected-delay reading, weakest claim and separate runtime chronology')
    return identity(path)


def source_attestation(path):
    from delay_authority import identity
    value = read(path)
    require(value.get('schema') == 'FORECAST_BINDING8_SOURCE_PRE_FREEZE_ATTESTATION_V1'
            and value.get('state') == 'AFTER_BATCH_BEFORE_T5'
            and all(value.get(name) is True for name in
                    ('batch_finished', 'dly8_r8_finished', 'no_fit_or_rebuild_overlap', 'before_T5', 'no_scores_seen'))
            and isinstance(value.get('recorded_by'), str) and value['recorded_by'].strip(),
            'Truthful source natural-completion/order attestation required')
    require(_utc(FRESH_UTC) <= _utc(value.get('recorded_utc')) <= dt.datetime.now(dt.timezone.utc),
            'Source attestation must follow T4K')
    return identity(path)


def write_exclusive(path, value):
    path = Path(path).absolute()
    require(path.parent == HERE or path.is_relative_to(Path('/private/tmp')),
            'Exclusive freeze/binding write escaped additive overlay or synthetic scratch')
    payload = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n').encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def load_source(name, path):
    from delay_authority import read_metadata
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(read_metadata(path), str(path), 'exec'), vars(module))
    return module


def _source_association(committed, preflight, parents, mapping_identity):
    require(committed.get('schema') == 'FORECAST_BINDING_FINAL_SOURCE_COMMITMENT_V2'
            and committed.get('overlay_sources') == preflight['sources']
            and committed.get('parent_overlay_sources') == parents['parent_overlay_files']
            and committed.get('parent_overlay_source_rows') == parents['parent_overlay_source_rows']
            and committed.get('parent_overlay_delivery') == parents['parent_overlay_delivery']
            and committed.get('resource_projection') == preflight['resource_projection']
            and committed.get('speed_overlay_binding') == preflight['speed_overlay_binding']
            and committed.get('final_root_mapping') == mapping_identity,
            'Final source commitment must separate exact T4F/OV1/OV2 sources and actual final mapping')


def create(review_acceptance, consumer_acceptance, attestation):
    require(os.environ.get('FORECAST_BINDING_SOURCE_FREEZE') == '1', 'Source-only future freeze action')
    sys.path.insert(0, str(AF / 'code'))
    from delay_authority import (CALENDAR_RULE, historical_snapshot, identity, verify_specification,
                                 verify_decision, verify_unchanged_parents, verify_frozen_delay_sources)
    from common import resources
    from delay_final_source import verify_final_source
    from delay_root_mapping import runtime_mapping, verify_final_mapping
    from run_bound_forecasts import no_overlap
    from forecast_inputs import root_mapping_contract
    resources()
    preflight = source_preflight()
    parents = verify_unchanged_parents()
    historical, specifications, decision = historical_snapshot(), verify_specification(), verify_decision()
    frozen_delay_sources = verify_frozen_delay_sources()
    mapping_path = HERE / 'FINAL_ROOT_MAPPING.json'
    verify_final_mapping(mapping_path)
    mapping = runtime_mapping(root_mapping_contract())
    mapping_id = identity(mapping_path)
    source_path = HERE / 'FINAL_SOURCE_COMMITMENT.json'
    committed = verify_final_source(source_path)
    _source_association(committed, preflight, parents, mapping_id)
    source_id = identity(source_path)
    kwargs = dict(preflight=preflight, parents=parents, historical=historical, specifications=specifications,
                  decision=decision, mapping_identity=mapping_id, commitment_identity=source_id,
                  frozen_delay_sources=frozen_delay_sources)
    review = additional_acceptance(review_acceptance, schema='FORECAST_BINDING5_REVIEW_ACCEPTANCE_V1', **kwargs)
    consumer = additional_acceptance(consumer_acceptance, schema='FORECAST_BINDING5_CONSUMER_ACCEPTANCE_V1', **kwargs)
    attestation_id = source_attestation(attestation)


    no_overlap(mapping)
    base = load_source('_forecast_binding8_original_freezer', AF / 'freeze_forecast_binding.py')
    original = base.create(review_acceptance, consumer_acceptance)
    require(original['root_mapping'] == mapping, 'Unchanged original freezer used a different final mapping')
    require(source_preflight() == preflight and verify_unchanged_parents() == parents,
            'Old or additive source/test drift during original freeze')
    require(verify_frozen_delay_sources() == frozen_delay_sources, 'Frozen DLY8 source drift during original freeze')
    require(identity(source_path) == source_id and identity(mapping_path) == mapping_id,
            'Final commitment or mapping changed during original freeze')
    value = {'schema': 'FORECAST_BINDING8_DELAY_OVERLAY_FREEZE_V1',
             'state': 'FORECAST_BINDING8_ADDITIVE_DELAY_OVERLAY_FROZEN',
             'utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'files': preflight['sources'],
             'test_receipt': preflight['test_receipt'], 'unchanged_parents': parents,
             'resource_projection': preflight['resource_projection'],
             'speed_overlay_binding': preflight['speed_overlay_binding'],
             'historical_T4F': historical, 'specification_authority': specifications,
             'review8_decision_authority': decision, 'calendar_rule': CALENDAR_RULE,
             'frozen_delay_sources': frozen_delay_sources,
             'corrected_delay_scope': SCOPE, 'root_mapping': mapping,
             'final_root_mapping': mapping_id, 'final_source_interface': interface_identities(),
             'final_source_commitment': source_id, 'base_code_freeze': identity(AF / 'CODE_FREEZE.json'),
             'independent_review': review, 'consumer_acceptance': consumer,
             'source_attestation': attestation_id, 'models_refitted': 0,
             'predictions_run': False, 'scoring_run': False, 'timestamp_generated': False,
             'historical_AF_bytes_changed': False, 'deadline_overlay_bytes_changed': False}
    write_exclusive(HERE / 'OVERLAY_FREEZE.json', value)
    return value


def verify_delay_freeze():
    from delay_authority import (CALENDAR_RULE, historical_snapshot, identity, verify_specification,
                                 verify_decision, verify_unchanged_parents, verify_frozen_delay_sources)
    from delay_final_source import verify_final_source
    from delay_root_mapping import runtime_mapping
    frozen = read(HERE / 'OVERLAY_FREEZE.json')
    require(frozen.get('schema') == 'FORECAST_BINDING8_DELAY_OVERLAY_FREEZE_V1'
            and frozen.get('state') == 'FORECAST_BINDING8_ADDITIVE_DELAY_OVERLAY_FROZEN'
            and frozen.get('calendar_rule') == CALENDAR_RULE
            and frozen.get('corrected_delay_scope') == SCOPE and frozen.get('models_refitted') == 0
            and frozen.get('historical_AF_bytes_changed') is False
            and frozen.get('deadline_overlay_bytes_changed') is False,
            'Exact additive runtime delay freeze required')
    preflight, parents = source_preflight(), verify_unchanged_parents()
    historical, specifications, decision = historical_snapshot(), verify_specification(), verify_decision()
    mapping = runtime_mapping()
    mapping_id = identity(HERE / 'FINAL_ROOT_MAPPING.json')
    source_path = HERE / 'FINAL_SOURCE_COMMITMENT.json'
    committed = verify_final_source(source_path)
    _source_association(committed, preflight, parents, mapping_id)
    source_id = identity(source_path)
    frozen_delay_sources = verify_frozen_delay_sources()
    expected = dict(files=preflight['sources'], test_receipt=preflight['test_receipt'],
                    resource_projection=preflight['resource_projection'],
                    speed_overlay_binding=preflight['speed_overlay_binding'],
                    unchanged_parents=parents, historical_T4F=historical,
                    specification_authority=specifications, review8_decision_authority=decision,
                    frozen_delay_sources=frozen_delay_sources,
                    root_mapping=mapping, final_root_mapping=mapping_id,
                    final_source_interface=interface_identities(), final_source_commitment=source_id,
                    base_code_freeze=identity(AF / 'CODE_FREEZE.json'))
    require(all(frozen.get(name) == item for name, item in expected.items()),
            'Runtime delay freeze history/source/decision/mapping association drift')
    kwargs = dict(preflight=preflight, parents=parents, historical=historical, specifications=specifications,
                  decision=decision, mapping_identity=mapping_id, commitment_identity=source_id,
                  frozen_delay_sources=frozen_delay_sources)
    for name, schema in [('independent_review', 'FORECAST_BINDING5_REVIEW_ACCEPTANCE_V1'),
                         ('consumer_acceptance', 'FORECAST_BINDING5_CONSUMER_ACCEPTANCE_V1')]:
        row = frozen[name]
        require(additional_acceptance(row['path'], schema=schema, **kwargs) == row,
                'Frozen joint-delay owner acceptance changed')
    require(source_attestation(frozen['source_attestation']['path']) == frozen['source_attestation'],
            'Frozen completion/order attestation changed')
    base = read(AF / 'CODE_FREEZE.json')
    require(base.get('state') == 'FORECAST_BINDING_CODE_FROZEN_FOR_SOURCE'
            and base.get('root_mapping') == mapping
            and base.get('independent_review') == frozen['independent_review']
            and base.get('consumer_acceptance') == frozen['consumer_acceptance'],
            'Original AF5/runtime delay freeze association mismatch')
    require(_utc(frozen['utc']) >= _utc(read(frozen['source_attestation']['path'])['recorded_utc']),
            'Delay overlay freeze cannot precede source completion evidence')
    return frozen


def timestamp_required_identities(frozen):
    from delay_authority import identity
    rows = [identity(HERE / 'OVERLAY_FREEZE.json'), frozen['base_code_freeze'],
            frozen['final_source_commitment'], frozen['final_root_mapping'], *frozen['files'].values(),
            frozen['test_receipt'], frozen['independent_review'], frozen['consumer_acceptance'],
            frozen['resource_projection'],
            *frozen['speed_overlay_binding']['source_inventory'].values(),
            *frozen['speed_overlay_binding']['evidence_inventory'].values(),
            frozen['source_attestation'], frozen['unchanged_parents']['parent_overlay_delivery'],
            *frozen['unchanged_parents']['parent_overlay_source_rows'],
            *frozen['frozen_delay_sources'].values(),
            frozen['review8_decision_authority']['decision']]
    rows += [item['specification'] for item in frozen['specification_authority']['ordered_specifications']]
    rows.append(frozen['specification_authority']['erratum']['identity'])
    unique = {}
    for row in rows:
        require(row['path'] not in unique or unique[row['path']] == row, 'Conflicting duplicate timestamp source identity')
        unique[row['path']] = row
    return [unique[path] for path in sorted(unique)]


def verify_delay_release():
    from delay_authority import identity, verify_timestamp_bundle
    frozen = verify_delay_freeze()
    binding_path = HERE / 'OVERLAY_TIMESTAMP_BINDING.json'
    binding_id = identity(binding_path)
    binding = read(binding_path)
    require(binding.get('schema') == 'FORECAST_BINDING8_DELAY_OVERLAY_TIMESTAMP_BINDING_V1'
            and binding.get('state') == 'VERIFIED_EXISTING_SOURCE_TIMESTAMP'
            and binding.get('overlay_freeze') == identity(HERE / 'OVERLAY_FREEZE.json')
            and binding.get('final_source_commitment') == frozen['final_source_commitment']
            and binding.get('review8_decision_authority') == frozen['review8_decision_authority']
            and binding.get('speed_overlay_binding') == frozen['speed_overlay_binding'],
            'Verified existing delay timestamp/source/decision binding required')
    verified = verify_timestamp_bundle(binding['label'], timestamp_required_identities(frozen))
    require(binding.get('verification') == verified
            and all(_utc(row['utc']) > _utc(frozen['utc']) for row in verified['tsa'].values()),
            'Both actual delay TSA responses must follow the bound runtime freeze')
    require(identity(binding_path) == binding_id, 'Delay timestamp binding changed during verification')
    return {'overlay_freeze': identity(HERE / 'OVERLAY_FREEZE.json'),
            'overlay_timestamp_binding': binding_id, 'final_root_mapping': frozen['final_root_mapping'],
            'historical_T4F': frozen['historical_T4F'], 'unchanged_parents': frozen['unchanged_parents'],
            'specification_authority': frozen['specification_authority'],
            'review8_decision_authority': frozen['review8_decision_authority'],
            'speed_overlay_binding': frozen['speed_overlay_binding'],
            'final_source_commitment': frozen['final_source_commitment'], 'corrected_delay_scope': SCOPE}


def bootstrap_cli():

    sys.path.insert(0, str(AF / 'code'))
    for alias, name in [('delay_authority', 'timestamp_checks.py'), ('delay_root_mapping', 'root_mapping.py'),
                        ('delay_speed_binding', 'speed_binding.py'),
                        ('delay_final_source', 'source_inventory.py'), ('delay_freeze', 'freeze_delay.py')]:
        if alias not in sys.modules:
            module = types.ModuleType(alias)
            module.__file__ = str(HERE / name)
            sys.modules[alias] = module
            exec(compile((HERE / name).read_bytes(), str(HERE / name), 'exec'), vars(module))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-freeze', action='store_true')
    parser.add_argument('--review-acceptance', type=Path, required=True)
    parser.add_argument('--consumer-acceptance', type=Path, required=True)
    parser.add_argument('--source-attestation', type=Path, required=True)
    args = parser.parse_args()
    require(args.source_freeze, 'Explicit --source-freeze required')
    bootstrap_cli()
    value = create(args.review_acceptance, args.consumer_acceptance, args.source_attestation)
    print(json.dumps({'state': value['state'], 'timestamp_generated': False}))


if __name__ == '__main__':
    main()
