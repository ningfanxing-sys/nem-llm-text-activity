'Check numerical input metadata and required resource measurements.'
import ast
import hashlib
import json
import math
from pathlib import Path
import re

PROPOSAL_SCHEMA = 'AF_SCORING_PROPOSED_C_SCIENTIFIC_CONTRACT_V1'
RECEIPT_SCHEMA = 'AF_SCORING_SOURCE_ONLY_ACCEPTANCE_V1'
SCOPE = {'window': 'D', 'arms': ['L14', 'L_Laz'], 'delay_minutes': [5, 15, 60],
         'seed': 20260919, 'variant': 'main', 'models_refitted': 0}
CALENDAR_RULE = 'NO_CALENDAR_DEADLINE_CORRECTED_SEAL_PRECEDES_T5'


def require(ok, message):
    if not ok:
        raise PermissionError('AF SCORING SCIENCE REFUSED: ' + message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def identity_shape(value):
    require(type(value) is dict and set(value) == {'path', 'bytes', 'sha256'},
            'Exact path/bytes/SHA identity required')
    require(type(value['path']) is str and value['path'] and
            '..' not in Path(value['path']).parts and
            type(value['bytes']) is int and value['bytes'] > 0 and
            type(value['sha256']) is str and re.fullmatch('[0-9a-f]{64}', value['sha256']),
            'Malformed identity')
    return value


def exact_inventory(actual, expected):
    require(type(actual) is dict and actual and actual == expected,
            'Exact selected source inventory required; no wildcard timestamp_checks')
    for row in actual.values():
        identity_shape(row)
    return actual


def resource_receipt(value):
    require(type(value) is list and value, 'Observed resource checkpoints required')
    for row in value:
        require(type(row.get('nice')) is int and row['nice'] == 20 and
                type(row.get('processes')) is int and row['processes'] == 1 and
                type(row.get('memory_free_percent')) in (int, float) and
                math.isfinite(row['memory_free_percent']) and 25 <= row['memory_free_percent'] <= 100 and
                type(row.get('peak_rss_bytes')) is int and
                0 <= row['peak_rss_bytes'] < 1_500_000_000 and
                type(row.get('scratch_bytes')) is int and
                0 <= row['scratch_bytes'] < 1_000_000_000,
                'Inherited nice20/one-process/25%-free/RSS/scratch gate')


def clean_receipt(value, *, schema, revision, sources, test_ids):
    require(type(value) is dict and value.get('schema') == schema and
            value.get('task_revision') == revision and value.get('state') == 'PASS' and
            all(type(value.get(k)) is int and value[k] == 0
                for k in ('failures', 'errors', 'skipped')) and
            value.get('selected_tests') is False and value.get('synthetic_only') is True and
            value.get('source_before') == sources == value.get('source_after') and
            type(value.get('tests_run')) is int and value['tests_run'] == len(test_ids) and
            value.get('test_ids') == test_ids and len(set(test_ids)) == len(test_ids) > 0,
            'Exact clean full source-only receipt/revision/census required')
    require(all(value.get(k) is False for k in
                ('host_executed', 'freeze_created', 'timestamp_created', 'production_authority')),
            'Source receipt cannot grant runtime timestamp_checks')
    require(type(value.get('breaches')) is list and value['breaches'] == [],
            'Explicit empty violation ledger required')
    require(value.get('campaign_stopped') is False and
            type(value.get('checkpoint_persistence_errors')) is list and value['checkpoint_persistence_errors']==[],
            'Stopped campaign or unrecorded checkpoint cannot be accepted')
    resource_receipt(value.get('resources'))


def revision_from_source(source):

    values = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and
                t.id == 'TASK_REVISION' for t in node.targets):
            values.append(ast.literal_eval(node.value))
    require(len(values) == 1 and type(values[0]) is str and values[0],
            'One literal C TASK_REVISION required')
    return values[0]


def validate_science_authority(timestamp_checks, receipt, review, contract, *, sources, revision_source):

    require(contract.get('schema') == PROPOSAL_SCHEMA and contract.get('stable') is True,
            'Stable owner-agreed scientific API required')
    require(contract.get('owner_agreed') is True and contract.get('api_schema') and
            contract.get('authority_schema') and contract.get('review_schema') and
            contract.get('receipt_schema') and contract.get('revision') and
            contract.get('callable') and contract.get('test_ids'), 'Incomplete C scientific API')
    exact_inventory(sources, contract.get('sources'))
    revision = revision_from_source(revision_source)
    require(revision == contract['revision'], 'C code/contract TASK_REVISION drift')
    require(timestamp_checks.get('schema') == contract['authority_schema'] and
            timestamp_checks.get('api_schema') == contract['api_schema'] and
            timestamp_checks.get('task_revision') == revision and
            timestamp_checks.get('scientific_only') is True and
            timestamp_checks.get('independently_reviewed') is True and
            timestamp_checks.get('sources') == sources and
            timestamp_checks.get('callable') == contract['callable'] and
            timestamp_checks.get('scientific_scope') == contract.get('scientific_scope'),
            'Exact reviewed C scientific timestamp_checks required')
    clean_receipt(receipt, schema=contract['receipt_schema'], revision=revision,
                  sources=sources, test_ids=contract['test_ids'])
    require(review.get('schema') == contract['review_schema'] and
            review.get('task_revision') == revision and
            review.get('state') == 'FREEZE-READY' and review.get('independent') is True and
            review.get('reviewer') and review.get('reviewer') != review.get('producer') and
            review.get('sources') == sources and review.get('authority_sha256') == digest(timestamp_checks) and
            review.get('receipt_sha256') == digest(receipt) and
            review.get('scientific_only') is True,
            'Absent/stale/self-issued/wrong scientific independent review')
    return {'authority_sha256': digest(timestamp_checks), 'receipt_sha256': digest(receipt),
            'review_sha256': digest(review), 'task_revision': revision}
