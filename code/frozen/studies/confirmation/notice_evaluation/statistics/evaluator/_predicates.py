'Check scoring metadata and comparison eligibility.'
from copy import deepcopy
from decimal import Decimal
from . import _scalar as F

def require(value, message):
    F.require(value, 'validation_group_11 joint: ' + message)


def admission_label(delay):

    require(delay in (5, 15, 60), 'unknown admission-delay slot')
    return 'a0' if delay == 5 else 'a0+' + str(delay)


def _interval_candidate(values, *, arm, reference, origin, delay, block, level, timestamp_checks):
    if values is None:
        return None
    require(isinstance(values, list) and len(values) == 2, 'result interval shape')
    low, high = (Decimal(str(x)) for x in values)
    require(low.is_finite() and high.is_finite() and low <= high, 'result interval endpoints')
    return dict(arm=arm, reference=reference, origin=origin, delay_minutes=delay,
                admission_label=None if delay is None else admission_label(delay),
                block_days=block, nominal_level=level, interval=deepcopy(values),
                timestamp_checks=deepcopy(timestamp_checks))


def weakest_reading(candidates, result_class):

    if not candidates: return None
    require(result_class in ('IMP', 'DET', 'NULL', 'NE', None), 'weakest-reading class')

    def key(item):
        low, high = (Decimal(str(x)) for x in item['interval'])


        return (high, high-low) if result_class == 'IMP' else (-low, high-low) if result_class in ('DET','NULL') else (high-low, -low)
    return deepcopy(max(candidates, key=key))


def reliable_support(contrast, alert=False, *, joint=False):

    result_class=contrast['joint']['result_class'] if joint else contrast['class']
    rejecting=result_class in ('IMP','DET')
    if joint:
        conditions=contrast['joint']['claim_conditions']
        rows=[row for row in contrast['readings'] if dict(origin=row['origin'],delay_minutes=row['delay_minutes']) in conditions]
        checks_agree=bool(rows) and all(all(value=='PASS' for value in row['checks'].values()) for row in rows)
        intervals=[row['intervals']['family_seven_day'] for row in rows]
    else:
        rows=[contrast];checks_agree=all(value=='PASS' for value in contrast['checks'].values())
        intervals=[contrast['family_seven_day']]
    seven_excludes=bool(intervals) and all(values is not None and
        (Decimal(str(values[1]))<0 or Decimal(str(values[0]))>0) for values in intervals)
    seven_available=bool(rows) and all((row.get('per_contrast_seven_day') if not joint else row['intervals'].get('per_contrast_seven_day')) is not None for row in rows)
    seven_agrees=rejecting and bool(intervals) and all(values is not None and (Decimal(str(values[1]))<0 if result_class=='IMP' else Decimal(str(values[0]))>0) for values in intervals)
    reliable=rejecting and not alert and checks_agree and seven_excludes and seven_agrees and seven_available
    return dict(schema='TABLE_RESULTS_DEC9B_RELIABLE_SUPPORT_V1',rejecting=rejecting,
        six_checks_agree=checks_agree,family_seven_day_excludes_zero=seven_excludes,family_seven_day_direction_agrees=seven_agrees,seven_day_check_available=seven_available,
        alert=bool(alert),reliable=reliable,decision_class_unchanged=result_class,
        insufficient_support=rejecting and not reliable,
        native_conditions=deepcopy(contrast['joint']['claim_conditions']) if joint else ['specified'])


def seven_day_definedness(contrast, *, joint=False):
    'Check interval availability for each comparison and its family.'
    rows = contrast['readings'] if joint else [contrast]
    conditions = []
    for row in rows:
        evaluated = row.get('state', 'COMPUTED') == 'COMPUTED' and row['class'] not in ('NE', None)
        values = row['intervals'] if joint else row
        if evaluated:
            conditions.append(dict(origin=row['origin'] if joint else 'specified',
                delay_minutes=row['delay_minutes'] if joint else None,
                per_contrast_seven_day_present=values.get('per_contrast_seven_day') is not None,
                family_seven_day_present=values.get('family_seven_day') is not None,
                timestamp_checks=deepcopy(row.get('native_authority'))))
    affected = [dict(origin=row['origin'], delay_minutes=row['delay_minutes']) for row in conditions
                if not row['per_contrast_seven_day_present'] or not row['family_seven_day_present']]
    return dict(schema='TABLE_RESULTS_A8_D6_DEFINEDNESS_V1', affected=bool(affected),
                conditions=conditions, affected_conditions=affected)


def specified_primary_seed(original, task, *, timestamp_checks=None, source_pointer=None):
    'Check the primary-seed estimate against its saved comparison row.'
    cls = original['class']
    mean_class = original['three_seed_class']
    required = cls in ('IMP', 'DET') and not F.robust(original, task['alert']) and mean_class != cls
    bound = deepcopy(timestamp_checks)
    if bound is not None and source_pointer is not None:
        bound.update(pointer=source_pointer)
    return dict(schema='TABLE_RESULTS_A8_D2_ORIGINAL_SEED_V1', primary_class=cls,
        **{'class':mean_class}, effect_percent=deepcopy(original['three_seed_effect']),
        required=required, origin='specified', delay_minutes=5 if original['reference']=='M_notice' else None,
        timestamp_checks=bound, source_pointer=source_pointer)

