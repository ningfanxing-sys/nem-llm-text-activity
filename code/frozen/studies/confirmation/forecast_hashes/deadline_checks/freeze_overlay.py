'Save validated deadline inputs and their source hashes.'
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
TEST_RECEIPT = 'TEST_RESULTS.json'
DOCUMENTS = ('SPEC.md', 'HOST_PROCEDURE.md', 'T5_ROWS.md', 'T5_ROWS.json',
             'ACTIVATION.template.json', 'AM3_FINAL_SOURCE_INTERFACE.md',
             'AM3_FINAL_SOURCE_INTERFACE.json', 'REPORT.md',
             'SOURCE_ATTESTATION.template.json')


def require(ok, message):
    if not ok:
        raise PermissionError(message)


def read(path):
    from timestamp_checks import read_metadata
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate timestamp_checks JSON key')
            result[key] = value
        return result
    return json.loads(read_metadata(path), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(PermissionError('Nonfinite timestamp_checks JSON')))


def load_source(name, path):
    from timestamp_checks import read_metadata
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(read_metadata(path), str(path), 'exec'), vars(module))
    return module


def source_inventory(here=HERE):
    from timestamp_checks import identity
    here = Path(here).absolute()
    files = sorted(set([*here.glob('*.py'), *here.joinpath('tests').glob('*.py'),
                        *(here / name for name in DOCUMENTS)]))
    require(bool(files), 'Overlay source inventory required')
    return {str(path.relative_to(here)): identity(path) for path in files}


def source_preflight(here=HERE):
    from timestamp_checks import identity
    here = Path(here).absolute()
    sources = source_inventory(here)
    tests_path = here / TEST_RECEIPT
    tests = read(tests_path)
    require(tests.get('schema') == 'FORECAST_BINDING7_FULL_SUITE_RECEIPT_V1'
            and tests.get('task') == 'FORECAST_BINDING7' and tests.get('state') == 'PASS_SYNTHETIC_TESTS'
            and tests.get('failures') == 0 and tests.get('errors') == 0 and tests.get('skipped') == 0
            and tests.get('historical_tests_run') == 118 and tests.get('overlay_tests_run', 0) > 0
            and tests.get('numerical_processes') == 1 and tests.get('full_suite_runs') == 1
            and tests.get('deadline_overlay_covered') is True and tests.get('final_source_interface_covered') is True
            and tests.get('activity_guard_covered') is True and tests.get('before_t5_guard_covered') is True
            and tests.get('production_state_paths_or_locks_probed') is False
            and tests.get('real_lock_acquired') is False and tests.get('real_batch_signalled') is False
            and tests.get('freeze_executed') is False and tests.get('timestamp_executed') is False,
            'One complete passing final-source AF7 synthetic suite required')
    code = {name: row['sha256'] for name, row in sources.items() if name.endswith('.py')}
    require(tests.get('overlay_code_sha256') == code, 'Final overlay code changed after the sole full suite')
    require(tests.get('minimum_memory_free_percent', -1) >= 25
            and tests.get('maximum_synthetic_scratch_bytes', 1000000000) < 1000000000
            and tests.get('scratch_under_1GB') is True
            and all(tests.get(name, {}).get('nice') == 20 for name in
                    ('resources_before_numeric_imports', 'resources_before', 'resources_after')),
            'Final-source suite resource conditions not proven')
    return {'sources': sources, 'test_receipt': identity(tests_path), 'tests': tests}


def interface_identities(here=HERE):
    from timestamp_checks import identity
    return {'markdown': identity(Path(here) / 'AM3_FINAL_SOURCE_INTERFACE.md'),
            'json': identity(Path(here) / 'AM3_FINAL_SOURCE_INTERFACE.json')}


def _utc(value):
    require(isinstance(value, str), 'Actual UTC date required')
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.utcoffset() == dt.timedelta(0), 'Actual date must be UTC')
    return parsed


def additional_acceptance(path, *, schema, preflight, authorities, historical, mapping_identity, here=HERE):

    from timestamp_checks import CALENDAR_RULE, identity
    value = read(path)
    require(value.get('schema') == schema and value.get('state') == 'ACCEPTED_FOR_SOURCE_FREEZE',
            'Genuine original AF5 owner acceptance schema/state required')
    require(value.get('overlay_reviewed_sources') == preflight['sources']
            and value.get('overlay_test_receipt') == preflight['test_receipt']
            and value.get('specification_authority') == authorities
            and value.get('historical_T4F') == historical
            and value.get('final_root_mapping') == mapping_identity
            and value.get('final_source_interface') == interface_identities(here)
            and value.get('calendar_rule') == CALENDAR_RULE,
            'Owner acceptance must cover exact overlay, ordered authorities, history and final mapping/interface')
    require(_utc('2026-10-05T10:32:37+00:00') <= _utc(value.get('recorded_utc'))
            <= dt.datetime.now(dt.timezone.utc),
            'Fresh owner acceptance must follow specification 2 timestamp_checks')
    require(isinstance(value.get('owner'), str) and value['owner'].strip(), 'Actual acceptance owner required')
    if schema == 'FORECAST_BINDING5_REVIEW_ACCEPTANCE_V1':
        require(value.get('independent') is True and value.get('calendar_only_change_reviewed') is True
                and value.get('earlier_gates_unchanged') is True,
                'Independent calendar-only AST/byte and unchanged-gate review required')
    else:
        require(value.get('scientific_eligibility_changed') is False
                and value.get('corrected_seal_must_precede_T5') is True
                and value.get('t5_metadata_payload_split_reviewed') is True,
                'Consumer must accept unchanged eligibility and corrected-seal-before-T5 interface')
    return identity(path)


def source_attestation(path):
    from timestamp_checks import identity
    value = read(path)
    require(value.get('schema') == 'FORECAST_BINDING7_SOURCE_PRE_FREEZE_ATTESTATION_V1'
            and value.get('state') == 'AFTER_BATCH_BEFORE_T5'
            and all(value.get(name) is True for name in
                    ('batch_finished', 'dly8_r8_finished', 'no_fit_or_rebuild_overlap', 'before_T5', 'no_scores_seen'))
            and isinstance(value.get('recorded_by'), str) and value['recorded_by'].strip(),
            'Truthful source natural-completion/order attestation required')
    require(_utc('2026-10-05T10:32:37+00:00') <= _utc(value.get('recorded_utc'))
            <= dt.datetime.now(dt.timezone.utc),
            'Source attestation must follow specification 2')
    return identity(path)


def write_exclusive(path, value):
    payload = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n').encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def create(review_acceptance, consumer_acceptance, attestation):
    require(os.environ.get('FORECAST_BINDING_SOURCE_FREEZE') == '1', 'Source-only future freeze action')
    sys.path.insert(0, str(AF / 'code'))
    from timestamp_checks import CALENDAR_RULE, historical_snapshot, identity, verify_specification
    from common import resources
    from source_inventory import verify_final_source
    from run_bound_forecasts import no_overlap
    from forecast_inputs import root_mapping_contract
    from root_mapping import runtime_mapping, verify_final_mapping
    resources()
    preflight = source_preflight()
    historical = historical_snapshot()
    authorities = verify_specification()
    mapping_path = HERE / 'FINAL_ROOT_MAPPING.json'
    verify_final_mapping(mapping_path)
    mapping = runtime_mapping(root_mapping_contract())
    mapping_id = identity(mapping_path)
    source_path = HERE / 'FINAL_SOURCE_COMMITMENT.json'
    committed = verify_final_source(source_path)
    require(committed.get('overlay_sources') == preflight['sources']
            and committed.get('final_root_mapping') == mapping_id,
            'Source-only commitment must bind this exact final overlay and mapping')
    source_id = identity(source_path)
    review = additional_acceptance(review_acceptance, schema='FORECAST_BINDING5_REVIEW_ACCEPTANCE_V1',
                                  preflight=preflight, authorities=authorities, historical=historical,
                                  mapping_identity=mapping_id)
    consumer = additional_acceptance(consumer_acceptance, schema='FORECAST_BINDING5_CONSUMER_ACCEPTANCE_V1',
                                    preflight=preflight, authorities=authorities, historical=historical,
                                    mapping_identity=mapping_id)
    attestation_id = source_attestation(attestation)


    no_overlap(mapping)
    base = load_source('_forecast_binding7_original_freezer', AF / 'freeze_forecast_binding.py')
    original = base.create(review_acceptance, consumer_acceptance)
    require(original['root_mapping'] == mapping, 'Original base freeze used a different final mapping')
    require(source_preflight() == preflight, 'Overlay source/test drift during base freeze')
    require(identity(source_path) == source_id and identity(mapping_path) == mapping_id,
            'Source commitment or final mapping changed during base freeze')
    value = {'schema': 'FORECAST_BINDING7_OVERLAY_FREEZE_V1', 'state': 'FORECAST_BINDING7_ADDITIVE_OVERLAY_FROZEN',
             'utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'files': preflight['sources'],
             'test_receipt': preflight['test_receipt'], 'historical_T4F': historical,
             'specification_authority': authorities, 'calendar_rule': CALENDAR_RULE,
             'root_mapping': mapping, 'final_root_mapping': mapping_id,
             'final_source_interface': interface_identities(), 'final_source_commitment': source_id,
             'base_code_freeze': identity(AF / 'CODE_FREEZE.json'), 'independent_review': review,
             'consumer_acceptance': consumer, 'source_attestation': attestation_id,
             'models_refitted': 0, 'predictions_run': False, 'scoring_run': False,
             'timestamp_generated': False, 'historical_AF_bytes_changed': False}
    write_exclusive(HERE / 'OVERLAY_FREEZE.json', value)
    return value


def verify_overlay_freeze():
    from timestamp_checks import CALENDAR_RULE, historical_snapshot, identity, verify_specification
    from source_inventory import verify_final_source
    from root_mapping import runtime_mapping
    frozen = read(HERE / 'OVERLAY_FREEZE.json')
    require(frozen.get('schema') == 'FORECAST_BINDING7_OVERLAY_FREEZE_V1'
            and frozen.get('state') == 'FORECAST_BINDING7_ADDITIVE_OVERLAY_FROZEN'
            and frozen.get('calendar_rule') == CALENDAR_RULE
            and frozen.get('models_refitted') == 0 and frozen.get('historical_AF_bytes_changed') is False,
            'Exact additive runtime overlay freeze required')
    preflight = source_preflight()
    require(frozen.get('files') == preflight['sources'] and frozen.get('test_receipt') == preflight['test_receipt'],
            'Frozen final overlay source/test drift')
    historical, authorities = historical_snapshot(), verify_specification()
    mapping = runtime_mapping()
    mapping_id = identity(HERE / 'FINAL_ROOT_MAPPING.json')
    committed = verify_final_source(HERE / 'FINAL_SOURCE_COMMITMENT.json')
    require(committed.get('overlay_sources') == preflight['sources']
            and committed.get('final_root_mapping') == mapping_id,
            'Final source-only commitment does not match runtime source/mapping')
    source_id = identity(HERE / 'FINAL_SOURCE_COMMITMENT.json')
    require(frozen.get('historical_T4F') == historical and frozen.get('specification_authority') == authorities
            and frozen.get('root_mapping') == mapping and frozen.get('final_root_mapping') == mapping_id
            and frozen.get('final_source_interface') == interface_identities()
            and frozen.get('final_source_commitment') == source_id
            and frozen.get('base_code_freeze') == identity(AF / 'CODE_FREEZE.json'),
            'Frozen history, timestamp_checks, final-source, mapping or base freeze drift')
    for key, schema in [('independent_review', 'FORECAST_BINDING5_REVIEW_ACCEPTANCE_V1'),
                        ('consumer_acceptance', 'FORECAST_BINDING5_CONSUMER_ACCEPTANCE_V1')]:
        row = frozen[key]
        require(additional_acceptance(row['path'], schema=schema, preflight=preflight, authorities=authorities,
                                     historical=historical, mapping_identity=mapping_id) == row,
                'Frozen owner acceptance changed')
    require(source_attestation(frozen['source_attestation']['path']) == frozen['source_attestation'],
            'Source completion/order attestation changed')
    base = read(AF / 'CODE_FREEZE.json')
    require(base.get('state') == 'FORECAST_BINDING_CODE_FROZEN_FOR_SOURCE' and base.get('root_mapping') == mapping
            and base.get('independent_review') == frozen['independent_review']
            and base.get('consumer_acceptance') == frozen['consumer_acceptance'], 'Base/overlay freeze association mismatch')
    require(_utc(frozen['utc']) >= _utc(read(frozen['source_attestation']['path'])['recorded_utc']),
            'Overlay freeze cannot precede source completion evidence')
    return frozen


def timestamp_required_identities(frozen):
    from timestamp_checks import identity
    rows = [identity(HERE / 'OVERLAY_FREEZE.json'), frozen['base_code_freeze'],
            frozen['final_source_commitment'], frozen['final_root_mapping'], *frozen['files'].values(),
            frozen['test_receipt'], frozen['independent_review'], frozen['consumer_acceptance'],
            frozen['source_attestation']]
    for row in frozen['specification_authority']['ordered_specifications']:
        rows.append(row['specification'])
    rows.append(frozen['specification_authority']['erratum']['identity'])
    unique = {}
    for row in rows:
        require(row['path'] not in unique or unique[row['path']] == row,
                'Conflicting duplicate timestamp source identity')
        unique[row['path']] = row
    return [unique[path] for path in sorted(unique)]


def verify_overlay_release():
    from timestamp_checks import identity, verify_timestamp_bundle
    frozen = verify_overlay_freeze()
    binding_path = HERE / 'OVERLAY_TIMESTAMP_BINDING.json'
    binding_id = identity(binding_path)
    binding = read(binding_path)
    require(binding.get('schema') == 'FORECAST_BINDING7_OVERLAY_TIMESTAMP_BINDING_V1'
            and binding.get('state') == 'VERIFIED_EXISTING_SOURCE_TIMESTAMP'
            and binding.get('overlay_freeze') == identity(HERE / 'OVERLAY_FREEZE.json')
            and binding.get('final_source_commitment') == frozen['final_source_commitment'],
            'Verified overlay timestamp/source binding required')
    required = timestamp_required_identities(frozen)
    verified = verify_timestamp_bundle(binding['label'], required)
    require(binding.get('verification') == verified, 'Actual overlay RFC3161 evidence drift')
    require(all(_utc(value['utc']) > _utc(frozen['utc']) for value in verified['tsa'].values()),
            'Both overlay TSA responses must follow the actual runtime freeze')
    require(identity(binding_path) == binding_id, 'Overlay timestamp binding changed during verification')
    return {'overlay_freeze': identity(HERE / 'OVERLAY_FREEZE.json'), 'overlay_timestamp_binding': binding_id,
            'final_root_mapping': frozen['final_root_mapping'], 'historical_T4F': frozen['historical_T4F'],
            'specification_authority': frozen['specification_authority'],
            'final_source_commitment': frozen['final_source_commitment']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-freeze', action='store_true')
    parser.add_argument('--review-acceptance', type=Path, required=True)
    parser.add_argument('--consumer-acceptance', type=Path, required=True)
    parser.add_argument('--source-attestation', type=Path, required=True)
    args = parser.parse_args()
    require(args.source_freeze, 'Explicit --source-freeze required')
    result = create(args.review_acceptance, args.consumer_acceptance, args.source_attestation)
    print(json.dumps({'state': result['state'], 'timestamp_generated': False}))


if __name__ == '__main__':
    main()
