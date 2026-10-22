'Check the schema of numerical input metadata.'
from copy import deepcopy
from datetime import datetime, timedelta
from evaluator.validation import exact_identity, require


def utc(value):
    require(isinstance(value, str), 'UTC string required')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.utcoffset() == timedelta(0), 'Aware zero-offset UTC required')
    return parsed


def validate_authority_candidate(bundle, expected):

    require(expected.get('contract_status') == 'INDEPENDENTLY_REVIEWED_FINAL', 'C/AF scientific interface pending')
    require(set(bundle) == {'reader_freeze', 'numerical_inputs', 'acceptance', 'specification3',
        'corrected_seal', 't5', 'original_capture', 'r2_execution', 'source_evidence'}, 'Authority role census')
    timestamp_checks = bundle['numerical_inputs']
    require(timestamp_checks['schema'] == expected['c_schema'] and timestamp_checks['state'] == expected['c_state'], 'Scientific C schema/state')
    require(timestamp_checks['files'] == expected['c_inventory'] and timestamp_checks['independent_review'] == expected['c_review'],
            'Exact independent C inventory/review association')
    freeze = bundle['reader_freeze']
    require(freeze['schema'] == 'RD_SCORING_SCIENTIFIC_FREEZE_V1' and
        freeze['state'] == 'RD_SCIENTIFIC_FROZEN_BEFORE_T5', 'notice_delays scientific timestamp_checks schema/state')
    require(freeze['files'] == expected['rd_inventory'] and
        freeze['source_functions'] == expected['source_functions'] and
        freeze['delay_source_functions'] == expected['delay_source_functions'], 'Frozen notice/source identity drift')
    require(freeze['news_source'] == expected['news_source'] and
        freeze['forecast_binding_sources'] == expected['forecast_binding_sources'], 'Independent news/AF source identity drift')
    acceptance, specification, seal, t5 = (bundle[k] for k in ('acceptance', 'specification3', 'corrected_seal', 't5'))
    for item in (expected['reader_freeze_identity'], expected['scientific_authority_identity'],
        expected['specification3_identity'], expected['acceptance_identity'], seal['identity']):
        exact_identity(item)
    require(acceptance['schema'] == 'ANCHORREADER_ACCEPTANCE_V1' and
        acceptance['state'] == 'INDEPENDENT_PRESCORE_ACCEPTANCE' and acceptance['independent'] is True
        and isinstance(acceptance['verified_by'], str) and acceptance['verified_by'].strip(), 'Independent reader acceptance')
    require(acceptance['verified_by'] not in ('RD7', 'AP6B2', 'numeric producer'), 'Producer self-approval refused')
    for name, item in (('scorer_freeze', expected['reader_freeze_identity']), ('corrected_seal', seal['identity']),
        ('specification3', expected['specification3_identity'])):
        require(acceptance[name + '_sha256'] == item['sha256'], 'Acceptance identity mismatch: ' + name)
    require(specification['schema'] == expected['am3_schema'] and specification['state'] == expected['am3_state'] and
        specification['decision_sha256'] == expected['decision_sha256'] and
        specification['scientific_authority_identity'] == expected['scientific_authority_identity'], 'Real AM3/scientific association')
    require(utc(freeze['frozen_utc']) < utc(t5['utc']) < utc(bundle['r2_execution']['score_complete_utc']) and
        utc(timestamp_checks['frozen_utc']) < utc(t5['utc']), 'Freeze/T5/score chronology')
    require(utc(seal['completed_utc']) <= utc(seal['verified_utc']) < utc(t5['utc']) and
        utc(acceptance['corrected_seal_verified_utc']) == utc(seal['verified_utc']) and
        utc(acceptance['accepted_utc']) < utc(t5['utc']) and utc(specification['approved_utc']) < utc(t5['utc']),
        'Actual corrected seal/verification/AM3/acceptance must precede T5')
    require(bundle['original_capture']['state'] == expected['capture_state'] and
        utc(bundle['original_capture']['complete_utc']) < utc(bundle['r2_execution']['start_utc']) and
        bundle['r2_execution']['evaluation_view'] == expected['r2_marker'], 'Original capture then verified R2 execution')
    rows = t5['files']
    require(isinstance(rows, list) and len(rows) == len({r['path'] for r in rows}), 'Exact independent T5 census')
    for item in rows:
        exact_identity(item)
    require(all(item in rows for item in expected['required_T5_identities']), 'Required actual T5 identity missing')
    require(bundle['source_evidence'] == expected['source_evidence'], 'Exact timestamp_checks/source evidence association')
    return dict(schema='RD_SCORING_NECESSARY_METADATA_CHECKS_V1', structural_checks=True,
        eligibility_granted=False, production_authority=False,
        independent_external_verification_required=True, inherited_scientific_sources=deepcopy(freeze['source_functions']))


def runtime_entry(*args, **kwargs):

    if not args and not kwargs:
        raise RuntimeError('PENDING_OWNER_CONTRACT: exact C dispatcher arguments required')
    from dispatcher_entry import rd_joint
    return rd_joint(*args, **kwargs)
