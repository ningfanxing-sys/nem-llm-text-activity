'Compare the source inventory with the required record structure.'
from datetime import datetime, timedelta
from pathlib import Path
from evaluator.validation import require, exact_identity

SCHEMA = 'RD_SCORING_SCIENTIFIC_FREEZE_V1'
STATE = 'RD_SCIENTIFIC_FROZEN_BEFORE_T5'
REVISION = 'RD7_statistics_V2'


def validate_layout(freeze, census, root):
    require(freeze.get('schema') == SCHEMA and freeze.get('state') == STATE, 'notice_delays scientific schema/state')
    value = freeze.get('frozen_utc')
    require(isinstance(value, str), 'Actual frozen UTC required')
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(stamp.utcoffset() == timedelta(0), 'Aware zero-offset frozen UTC required')
    require(isinstance(census, list) and census and len(census) == len(set(census)), 'Independent file census')
    require(freeze.get('declared_census') == census, 'Declared file census differs from owner/C policy')
    rows = freeze.get('files')
    require(isinstance(rows, list) and len(rows) == len(census), 'Absolute bytes/SHA list required')
    root = Path(root)
    require(root.is_absolute() and root == root.resolve(), 'Canonical inventory base')
    expected = [str(root/name) for name in census]
    require(len(expected) == len(set(expected)), 'Duplicate file census alias')
    for name, row in zip(census, rows):
        require(isinstance(name, str) and name == Path(name).as_posix() and not Path(name).is_absolute()
            and '..' not in Path(name).parts and '.' not in Path(name).parts, 'Canonical relative census leaf')
        exact_identity(row)
    require([r['path'] for r in rows] == expected, 'Exact file inventory order/census')
    return dict(source_layout_verified=True, freeze_permitted=False, actual_T5_grant=False)


def require_clean_receipt(receipt, sources, test_ids):
    require(receipt.get('schema') == 'RD_SCORING_SOURCE_ACCEPTANCE_V1'
        and receipt.get('task_revision') == REVISION and receipt.get('state') == 'CLEAN_FULL_PASS',
        'Same-version clean full scientific receipt required')
    require(test_ids and len(test_ids) == len(set(test_ids)) and receipt.get('test_ids') == test_ids
        and receipt.get('started_test_ids') == test_ids and receipt.get('tests_run') == len(test_ids)
        and receipt.get('selected_tests') == [] and receipt.get('full_suite_runs') == 1,
        'Exact full test census; selected/partial/duplicate receipt refused')
    require(receipt.get('sources_before') == sources == receipt.get('sources_after'), 'Delivered tested source drift')
    require(all(receipt.get(k) == [] and type(receipt.get(k)) is list
        for k in ('errors', 'failures', 'skipped', 'resource_breaches', 'checkpoint_persistence_errors'))
        and receipt.get('campaign_stopped') is False, 'Failure/skip/resource ledger refusal')
    require(receipt.get('removed_writing_roots_unavailable') is True
        and receipt.get('production_payload_reads') == 0 and receipt.get('production_commands_run') == 0,
        'Source-only and removed-writing evidence required')
    resources = receipt.get('resources', {})
    require(resources.get('numerical_processes') == 1 and resources.get('required_nice') == 20
        and resources.get('minimum_observed_memory_free_percent', -1) >= 25
        and resources.get('peak_observed_resident_bytes', 10**10) < 1_500_000_000
        and resources.get('maximum_observed_scratch_bytes', 10**10) < 1_000_000_000,
        'Inherited resource gates')
    return dict(clean_source_receipt=True, freeze_permitted=False, independent_review_required=True)
