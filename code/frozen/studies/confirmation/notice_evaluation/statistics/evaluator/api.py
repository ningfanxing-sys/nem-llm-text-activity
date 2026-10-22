'Check numerical projections of synthetic evaluation inputs.'
from copy import deepcopy
from decimal import Decimal
import os
from pathlib import Path
from . import _predicates as P
from . import _joint_comparisons as J
from .validation import require, validate_joint, validate_scalar, exact_identity

BINDING_ROLES = {'decision', 'manifest', 'timestamp_result', 'specified_receipt',
    'corrected_receipt', 'corrected_seal', 'scorer_freeze', 't5_projection', 'main_reading'}


def permitted_bound(candidates):

    return deepcopy(max(candidates, key=lambda x: Decimal(str(x['upper_percent'])), default=None))


def _artificial_boundary(root, provenance):
    require(os.environ.get('SCORING_PHASE', 'prepare') == 'accept', 'Prepare: numerical evaluation forbidden')
    root = Path(root)
    require(root.is_absolute() and root == root.resolve() and root.is_relative_to(Path('/private/tmp')),
            'Artificial fixture root must be /private/tmp')
    require(provenance.get('synthetic_only') is True, 'Explicit artificial provenance required')
    return root


def _native_provenance(record, task, provenance, root):
    require(set(record['bindings']) == BINDING_ROLES, 'Nine binding census')
    require(set(provenance) == {'synthetic_only', 'bindings', 'native_rows', 'specified_record',
        'specified_seed_rows', 'source_receipt_sha256'}, 'Provenance fields')
    require(provenance['bindings'] == record['bindings'], 'Native binding association')
    expected = {}
    for contrast in record['contrasts']:
        for row in contrast['readings']:
            key = row['arm'] + '/' + row['origin'] + '/' + str(row['delay_minutes'])
            expected[key] = row['native_authority']
    require(provenance['native_rows'] == expected, 'Native pointer/census/provenance mismatch')
    for item in [*record['bindings'].values(), *expected.values()]:
        raw = item['path'];path = Path(raw)
        require(raw == str(path) and '..' not in path.parts and path.resolve() == path
            and all(not p.is_symlink() for p in (path, *path.parents)) and path.is_relative_to(root),
                'Native provenance alias/outside artificial fixture')
    specified = exact_identity(provenance['specified_record'])
    specified_path = Path(specified['path'])
    require(specified_path.resolve() == specified_path and specified_path.is_relative_to(root)
        and all(not p.is_symlink() for p in (specified_path, *specified_path.parents)), 'Specified record not artificial')
    require(isinstance(provenance['source_receipt_sha256'], str) and len(provenance['source_receipt_sha256']) == 64
        and all(x in '0123456789abcdef' for x in provenance['source_receipt_sha256']), 'Source receipt SHA')
    require(isinstance(task, dict) and {'alert', 'contrasts'} <= set(task) and type(task['alert']) is bool,
            'Specified task schema/alert')
    require(isinstance(task['contrasts'], list) and len(task['contrasts']) == 3, 'Specified primary census')
    seeds = provenance['specified_seed_rows']
    require(isinstance(seeds, list) and len(seeds) == 3, 'Original primary seed provenance census')
    for index, (raw, contrast, seed) in enumerate(zip(task['contrasts'], record['contrasts'], seeds)):
        validate_scalar(raw)
        require((raw['arm'], raw['reference']) == J.PAIRS[index], 'Original primary pair/order')
        require(isinstance(seed, dict) and set(seed) == {'class', 'effect_percent', 'timestamp_checks'}, 'Seed provenance fields')
        require(seed['class'] == raw['three_seed_class'] and seed['effect_percent'] == raw['three_seed_effect'],
                'Original primary seed mean/class drift')

        require(seed['timestamp_checks'] == dict(path=specified['path'], sha256=specified['sha256'],
            pointer='/tasks/notice/contrasts/' + str(index)), 'Own original primary seed provenance')
        main = contrast['readings'][0]
        if main['state'] == 'COMPUTED':
            require(raw['class'] == main['class'], 'Original primary class not the same specified main reading')
            check = main['seed_check']
            require((check['class'] if check['availability'] == 'AVAILABLE' else 'NE') == raw['three_seed_class'],
                    'Original mean not the same specified reading')
        require(all(r['alert'] == task['alert'] for r in contrast['readings']), 'Alert association drift')


def project_joint(record, specified_task, provenance, schema, *, fixture_root):

    root = _artificial_boundary(fixture_root, provenance)
    validate_joint(record, schema)
    _native_provenance(record, specified_task, provenance, root)
    output, conditions = [], []
    for index, contrast in enumerate(record['contrasts']):
        candidates, exclusions = [], []
        for row in contrast['readings']:
            conditions.append(deepcopy(row))
            for block, field in ((1, 'family_one_day'), (7, 'family_seven_day')):
                item = P._interval_candidate(row['intervals'][field], arm=row['arm'], reference=row['reference'],
                    origin=row['origin'], delay=row['delay_minutes'], block=block,
                    level=row['intervals']['two_sided_level'], timestamp_checks=row['native_authority'])
                if item is not None:
                    candidates.append(item)
            if row['exclusion']['permitted'] and not row['alert']:
                exclusions.append(dict(arm=row['arm'], reference=row['reference'],
                    origin=row['origin'], delay_minutes=row['delay_minutes'],
                    upper_percent=row['exclusion']['upper_percent'], nominal_level=row['exclusion']['one_sided_level'],
                    timestamp_checks=deepcopy(row['exclusion']['timestamp_checks']), scope=deepcopy(row['exclusion']['conditions'])))
        timestamp_checks = {k: provenance['specified_record'][k] for k in ('path', 'sha256')}
        timestamp_checks['source_receipt_sha256'] = provenance['source_receipt_sha256']
        output.append(dict(arm=contrast['arm'], reference=contrast['reference'],
            joint_case=deepcopy(contrast['joint']), native_classes=[r['class'] for r in contrast['readings']],
            six_check_tiers=[r['frozen_tier'] for r in contrast['readings']], interval_candidates=candidates,
            weakest_reading=P.weakest_reading(candidates, contrast['joint']['result_class']),
            permitted_bound=permitted_bound(exclusions),
            reliable_verdict=P.reliable_support(contrast, specified_task['alert'], joint=True),
            seven_day_definedness=P.seven_day_definedness(contrast, joint=True),
            specified_primary_seed=P.specified_primary_seed(specified_task['contrasts'][index], specified_task,
                timestamp_checks=timestamp_checks, source_pointer='/tasks/notice/contrasts/' + str(index))))
    return dict(schema='RD_SCORING_NOTICE_SCALAR_PROJECTION_V1', notice_conditions=conditions, joint_contrasts=output,
        provenance=deepcopy(provenance), production_authority=False, external_eligibility='NOT_GRANTED',
        no_new_statistics=True)
