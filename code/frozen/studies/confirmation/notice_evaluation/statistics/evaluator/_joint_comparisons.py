'Build and validate the joint comparison records.'
from copy import deepcopy
import math
import re

SCHEMA = 'ANCHORREADER_JOINT_RECORD_V1'


PAIRS = (('L14', 'M_notice'), ('L_Laz', 'M_notice'), ('L_chen_notice', 'M_notice'))


ORIGINS = ('specified', 'aligned')


DELAYS = (5, 15, 60)


CHECKS = ('one_day', 'seven_day', 'hln', 'hac7', 'three_seed', 'family_interval')


TIERS = ('FRAGILE_NFC', 'FRAGILE', 'NOT_FULLY_CHECKED', 'ROBUST')


STATES = ('COMPUTED', 'NOT_EVALUABLE', 'NOT_RUN', 'PENDING', 'DEVIATION', 'NOT_RUN_BEFORE_SCORING')


FAILURES = ('TERMINAL_PARITY', 'TERMINAL_COVERAGE', 'TERMINAL_IDENTITY', 'FROZEN_COMPUTATION_CHANGE_REQUIRED')


CLASSES = ('IMP', 'DET', 'NULL', 'NE')


CASES = ('SAME_CLASS_AND_DIRECTION', 'NO_COMMON_INCREMENT', 'OPPOSITE_DIRECTIONS',
         'LIMITED_TO_EVALUABLE_READINGS', 'CORRECTED_NOT_RUN', 'NO_EVALUABLE_RESULT')


DATE_QUALIFIER = 'sensitive to the date correction'


DELAY_QUALIFIER = 'sensitive to notice availability delay'


READING_FIELDS = ('origin', 'delay_minutes', 'arm', 'reference', 'state', 'class', 'direction',
    'estimate_percent', 'mean_difference_aud', 'intervals', 'dm', 'hln', 'hac7', 'checks',
    'frozen_tier', 'claim_tier', 'seven_day_family_dissent', 'seven_day_state', 'seed_check',
    'alert', 'exclusion', 'native_authority', 'reason', 'disposition')


JOINT_FIELDS = ('case', 'result_class', 'direction', 'statement', 'lowest_frozen_tier', 'claim_tier',
    'claim_conditions', 'excluded_conditions', 'sensitivity_qualifiers', 'date_sensitive',
    'delay_sensitive', 'corrected_system_has_result', 'corrected_system_statement',
    'exclusion_scope', 'no_pooled_estimate', 'conditional_only')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(value, pointer=False):
    require(isinstance(value, dict) and set(value) == ({'path', 'sha256', 'pointer'} if pointer else {'path', 'sha256'}),
            'Native identity fields invalid')
    require(isinstance(value['path'], str) and value['path'].startswith('/') and '\x00' not in value['path'],
            'Native identity path must be absolute')
    require(isinstance(value['sha256'], str) and re.fullmatch('[0-9a-f]{64}', value['sha256']),
            'Native identity SHA invalid')
    if pointer:
        require(isinstance(value['pointer'], str) and re.fullmatch('/(?:three_seed/)?reports/[0-2]', value['pointer']),
                'Native row pointer invalid')
    return deepcopy(value)


def number(value):
    require(value is None or (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)),
            'Nonfinite or nonnumeric statistic')
    return value


def interval(value):
    if value is None:
        return None
    require(isinstance(value, (list, tuple)) and len(value) == 2, 'Invalid interval')
    out = [number(v) for v in value]
    require(all(v is not None for v in out) and out[0] <= out[1], 'Invalid interval endpoints')
    return out


def direction(cls):
    return {'IMP': 'IMPROVEMENT', 'DET': 'DETERIORATION', 'NULL': 'NO_RELIABLE_INCREMENT', 'NE': None}.get(cls)


def _condition(row):
    return dict(origin=row['origin'], delay_minutes=row['delay_minutes'])


def _disposition(family, state):
    value = family.get('disposition')
    if state == 'NOT_RUN_BEFORE_SCORING':
        require(isinstance(value, dict) and set(value) == {'procedure_cannot_complete', 'failure_kind'},
                'Clause-5 not-run needs explicit terminal disposition')
        require(value['procedure_cannot_complete'] is True and value['failure_kind'] in FAILURES,
                'Clause-5 not-run is not a terminal frozen-procedure failure')
    else:
        require(value is None, 'Terminal disposition on non-fallback reading')
    return deepcopy(value)


def _different(a, b):
    'Compare matched evaluable sensitivity conditions.'
    if a['state'] != 'COMPUTED' or b['state'] != 'COMPUTED':
        return False
    family_dissent_differs = (a['seven_day_family_dissent'] is not None
        and b['seven_day_family_dissent'] is not None
        and a['seven_day_family_dissent'] != b['seven_day_family_dissent'])
    return (a['class'] != b['class'] or family_dissent_differs or any(a['checks'][k] != b['checks'][k]
        for k in CHECKS if 'UNAVAILABLE' not in (a['checks'][k], b['checks'][k])))


def _classify(rows):
    available = [r for r in rows if r['state'] == 'COMPUTED']
    excluded = [dict(_condition(r), state=r['state'], reason=r['reason']) for r in rows if r['state'] != 'COMPUTED']
    classes = {r['class'] for r in available}
    corrected_available = any(r['origin'] == 'aligned' for r in available)
    corrected_not_run = all(r['state'] in ('NOT_RUN', 'NOT_RUN_BEFORE_SCORING') for r in rows if r['origin'] == 'aligned')
    if not available:
        case, cls, statement = 'NO_EVALUABLE_RESULT', None, 'no evaluable result'
    elif {'IMP', 'DET'} <= classes:
        case, cls, statement = 'OPPOSITE_DIRECTIONS', None, 'no consistent direction'
    elif len(classes) > 1:
        case, cls, statement = 'NO_COMMON_INCREMENT', 'NULL', 'no reliable increment'
    elif corrected_not_run:
        case, cls = 'CORRECTED_NOT_RUN', next(iter(classes))
        statement = {'IMP': 'a reliable increment in the specified readings only',
                     'DET': 'a reliable deterioration in the specified readings only',
                     'NULL': 'no reliable increment in the specified readings'}[cls]
    elif excluded:
        case, cls = 'LIMITED_TO_EVALUABLE_READINGS', next(iter(classes))
        statement = {'IMP': 'a reliable increment in the evaluable conditions only',
                     'DET': 'a reliable deterioration in the evaluable conditions only',
                     'NULL': 'no reliable increment in the evaluable conditions'}[cls]
    else:
        case, cls = 'SAME_CLASS_AND_DIRECTION', next(iter(classes))
        statement = {'IMP': 'a reliable increment', 'DET': 'a reliable deterioration', 'NULL': 'no reliable increment'}[cls]
    slots = {(r['origin'], r['delay_minutes']): r for r in rows}
    date_sensitive = any(_different(slots['specified', d], slots['aligned', d]) for d in DELAYS)
    delay_sensitive = any(_different(slots[o, d], slots[o, other])
        for o in ORIGINS for i, d in enumerate(DELAYS) for other in DELAYS[i+1:])
    tier = min((r['frozen_tier'] for r in available), key=TIERS.index) if available else None
    return dict(case=case, result_class=cls, direction=direction(cls), statement=statement,
        lowest_frozen_tier=tier, claim_tier=tier if cls in ('IMP', 'DET') else None,
        claim_conditions=[_condition(r) for r in available], excluded_conditions=excluded,
        sensitivity_qualifiers=([DATE_QUALIFIER] if date_sensitive else [])+([DELAY_QUALIFIER] if delay_sensitive else []),
        date_sensitive=date_sensitive, delay_sensitive=delay_sensitive,
        corrected_system_has_result=corrected_available,
        corrected_system_statement=None if corrected_available else 'the corrected system has no result',
        exclusion_scope=[_condition(r) for r in available if r['exclusion']['permitted']],
        no_pooled_estimate=True, conditional_only=bool(excluded))


def build_joint_record(readings, bindings):

    require(isinstance(bindings, dict) and bindings, 'Joint timestamp_checks bindings are required')
    bound = {k: identity(v) for k, v in bindings.items()}
    require(all(isinstance(k, str) and bool(k.strip()) for k in bound), 'Invalid binding role')
    require(isinstance(readings, (list, tuple)) and len(readings) == 18, 'Joint record requires all six slots for three contrasts')
    census = {}
    for row in readings:
        validate_reading(row)
        key = row['arm'], row['reference'], row['origin'], row['delay_minutes']
        require(key not in census, 'Duplicate joint reading condition')
        census[key] = deepcopy(row)
    contrasts = []
    for arm, ref in PAIRS:
        rows = []
        for origin in ORIGINS:
            for delay in DELAYS:
                key = arm, ref, origin, delay
                require(key in census, 'Missing joint reading condition')
                rows.append(census[key])
        contrasts.append(dict(arm=arm, reference=ref, readings=rows, joint=_classify(rows)))
    result = dict(schema=SCHEMA, task='notice', family_m=3, delays_minutes=list(DELAYS),
        bindings=bound, contrasts=contrasts)
    validate_joint_record(result)
    return result


def _keys(value, keys, label):
    require(isinstance(value, dict) and set(value) == set(keys), label+' fields invalid')


def validate_reading(row):

    _keys(row, READING_FIELDS, 'Reading')
    require(row['origin'] in ORIGINS and type(row['delay_minutes']) is int and row['delay_minutes'] in DELAYS,
            'Reading condition invalid')
    require((row['arm'], row['reference']) in PAIRS and row['state'] in STATES, 'Reading pair/state invalid')
    require(row['class'] is None or row['class'] in CLASSES, 'Class invalid')
    require(row['direction'] == direction(row['class']), 'Direction contradicts frozen class')
    identity(row['native_authority'], pointer=True)
    index = PAIRS.index((row['arm'], row['reference']))
    require(row['native_authority']['pointer'] == '/reports/'+str(index), 'Reading timestamp_checks points to another pair')
    _keys(row['intervals'], ('per_contrast_one_day', 'per_contrast_seven_day', 'family_one_day',
        'family_seven_day', 'family_m', 'two_sided_level', 'one_sided_level'), 'Intervals')
    for key in ('per_contrast_one_day', 'per_contrast_seven_day', 'family_one_day', 'family_seven_day'):
        interval(row['intervals'][key])
    require(row['intervals']['family_m'] == 3 and row['intervals']['two_sided_level'] == 1-.05/3
        and row['intervals']['one_sided_level'] == 1-.05/6, 'Frozen family level drift')
    _keys(row['dm'], ('state', 'statistic', 'raw_p_two_sided', 'holm_p'), 'DM')
    _keys(row['hln'], ('decision', 'raw_p_two_sided', 'holm_p', 'dissent'), 'HLN')
    _keys(row['hac7'], ('state', 'decision', 'raw_p_two_sided', 'holm_p', 'dissent'), 'HAC7')
    require(all(value is None or isinstance(value, str)
        for value in (row['dm']['state'], row['hac7']['state'], row['seven_day_state'])), 'Diagnostic state type invalid')
    number(row['estimate_percent']); number(row['mean_difference_aud']); number(row['dm']['statistic'])
    for layer in ('dm', 'hln', 'hac7'):
        for field in ('raw_p_two_sided', 'holm_p'):
            value = number(row[layer][field])
            require(value is None or 0 <= value <= 1, 'P value outside probability range')
    _keys(row['checks'], CHECKS, 'Checks')
    require(all(v in ('PASS', 'FAIL', 'UNAVAILABLE') for v in row['checks'].values()), 'Unknown check status')
    for field in ('frozen_tier', 'claim_tier'):
        require(row[field] is None or row[field] in TIERS, 'Unknown tier')
    for layer in ('hln', 'hac7'):
        require(row[layer]['decision'] is None or row[layer]['decision'] in CLASSES, 'Diagnostic class invalid')
        value = row[layer]['dissent']
        require(value is None or type(value) is bool, 'Diagnostic dissent must be nullable Boolean')
        require(value == (None if row['checks'][layer] == 'UNAVAILABLE' else row['checks'][layer] == 'FAIL'),
                'Diagnostic dissent contradicts frozen check')
    require(row['seven_day_family_dissent'] is None or type(row['seven_day_family_dissent']) is bool,
            'Family-seven-day dissent must be nullable Boolean')
    _keys(row['seed_check'], ('availability', 'label', 'class', 'timestamp_checks'), 'Seed check')
    seed = row['seed_check']
    require(seed['availability'] in ('AVAILABLE', 'UNAVAILABLE'), 'Seed availability invalid')
    if seed['availability'] == 'AVAILABLE':
        require(row['origin'] == 'specified' and seed['class'] in ('IMP', 'DET', 'NULL')
            and seed['label'] == 'own specified seed check', 'Inherited or invalid seed evidence')
        identity(seed['timestamp_checks'], pointer=True)
        require(seed['timestamp_checks'] == dict(row['native_authority'], pointer='/three_seed/reports/'+str(index)),
                'Seed evidence belongs to a different reading')
        require(row['checks']['three_seed'] != 'UNAVAILABLE', 'Available seed marked unavailable')
    else:
        require(seed['class'] is None and seed['timestamp_checks'] is None and seed['label'] == 'primary seed only'
            and row['checks']['three_seed'] == 'UNAVAILABLE', 'Unavailable seed inherited evidence')
    require(type(row['alert']) is bool, 'Alert invalid')
    _keys(row['exclusion'], ('permitted', 'upper_percent', 'one_sided_level', 'conditions', 'timestamp_checks'), 'Exclusion')
    exclusion = row['exclusion']
    require(type(exclusion['permitted']) is bool, 'Exclusion permitted flag invalid')
    number(exclusion['upper_percent']); number(exclusion['one_sided_level'])
    if exclusion['permitted']:
        require(row['state'] == 'COMPUTED' and row['class'] in ('NULL', 'DET') and not row['alert'],
                'Exclusion claim allowed under invalid state/class/alert')
        require(exclusion['upper_percent'] is not None and exclusion['upper_percent'] >= 0
            and exclusion['one_sided_level'] == row['intervals']['one_sided_level']
            and exclusion['timestamp_checks'] == row['native_authority']
            and exclusion['conditions'] == ['sealed primary-seed predictions', 'daily resampling',
                                           'one-day/seven-day frozen family interval envelope'],
                'Exclusion lacks its own reading conditions/timestamp_checks')
    else:
        require(exclusion['upper_percent'] is None and exclusion['one_sided_level'] is None
            and exclusion['timestamp_checks'] is None and exclusion['conditions'] == [], 'Forbidden exclusion has numerical evidence')
    if row['state'] == 'COMPUTED':
        require(row['class'] in ('IMP', 'DET', 'NULL') and row['frozen_tier'] in TIERS, 'Computed reading is not evaluable')
        expected = ('FRAGILE_NFC' if 'FAIL' in row['checks'].values() and 'UNAVAILABLE' in row['checks'].values() else
            'FRAGILE' if 'FAIL' in row['checks'].values() else 'NOT_FULLY_CHECKED' if 'UNAVAILABLE' in row['checks'].values() else 'ROBUST')
        require(row['frozen_tier'] == expected, 'Tier contradicts frozen six checks')
        require(row['claim_tier'] == (row['frozen_tier'] if row['class'] in ('IMP', 'DET') else None),
                'Null claim cannot carry robust wording')
    else:
        require(row['class'] in (None, 'NE') and row['frozen_tier'] is None and row['claim_tier'] is None,
                'Uncomputed reading carries class or tier')
        require(row['estimate_percent'] is None and row['mean_difference_aud'] is None
            and all(row['intervals'][k] is None for k in ('per_contrast_one_day', 'per_contrast_seven_day', 'family_one_day', 'family_seven_day'))
            and all(v is None for v in row['dm'].values()) and all(v is None for v in row['hln'].values())
            and all(v is None for v in row['hac7'].values()) and row['seven_day_family_dissent'] is None
            and row['seven_day_state'] is None and all(v == 'UNAVAILABLE' for v in row['checks'].values()),
                'Uncomputed reading carries numerical/check evidence')
        require(isinstance(row['reason'], str) and bool(row['reason'].strip()), 'Uncomputed reason missing')
    require(row['reason'] is None or isinstance(row['reason'], str), 'Reason invalid')
    _disposition(row, row['state'])
    require(row['state'] != 'NOT_RUN_BEFORE_SCORING' or row['origin'] == 'aligned', 'Specified clause-5 fallback invalid')
    return True


def validate_joint_record(record):
    _keys(record, ('schema', 'task', 'family_m', 'delays_minutes', 'bindings', 'contrasts'), 'Joint record')
    require(record['schema'] == SCHEMA and record['task'] == 'notice' and record['family_m'] == 3
        and record['delays_minutes'] == list(DELAYS), 'Joint schema/family identity drift')
    require(isinstance(record['bindings'], dict) and record['bindings'], 'Joint bindings missing')
    for role, value in record['bindings'].items():
        require(isinstance(role, str) and bool(role.strip()), 'Binding role invalid')
        identity(value)
    require(isinstance(record['contrasts'], list) and len(record['contrasts']) == 3, 'Joint contrast census invalid')
    for index, contrast in enumerate(record['contrasts']):
        _keys(contrast, ('arm', 'reference', 'readings', 'joint'), 'Joint contrast')
        require((contrast['arm'], contrast['reference']) == PAIRS[index], 'Joint pair census/order invalid')
        rows = contrast['readings']
        require(isinstance(rows, list) and len(rows) == 6, 'Joint reading-slot census invalid')
        for slot, row in enumerate(rows):
            validate_reading(row)
            require((row['arm'], row['reference']) == PAIRS[index]
                and (row['origin'], row['delay_minutes']) == (ORIGINS[slot//3], DELAYS[slot%3]),
                'Joint slot identity/order mismatch')
        _keys(contrast['joint'], JOINT_FIELDS, 'Joint classification')
        require(contrast['joint'] == _classify(rows), 'Joint claim does not follow weaker readings')
    return True


def reading_from_family(M, family, origin, delay, native_authority, alert=False):
    'Read the three notice comparisons from one checked family.'
    require(origin in ORIGINS and type(delay) is int and delay in DELAYS, 'Unknown reading condition')
    require(isinstance(alert, bool), 'Alert must be Boolean')
    base = identity(native_authority)
    require(tuple(tuple(p) for p in M.P.PAIRS['notice']) == PAIRS, 'Frozen notice pair census drift')
    state = family.get('state', 'COMPUTED')
    require(state in STATES, 'Unknown family disposition')
    require(state != 'NOT_RUN_BEFORE_SCORING' or origin == 'aligned', 'Clause-5 fallback applies to corrected system only')
    reason = family.get('reason')
    require(reason is None or (isinstance(reason, str) and bool(reason.strip())), 'Reason must be nonempty text')
    if state != 'COMPUTED':
        require(reason is not None, 'Uncomputed family requires a recorded reason')
    disposition = _disposition(family, state)
    require(family.get('family_m', 3) == 3, 'Notice family adjustment must stay at three')
    reports = family.get('reports', [])
    require(not reports or tuple((r['arm'], r['reference']) for r in reports) == PAIRS, 'Native notice row census/order mismatch')
    if state == 'COMPUTED':
        require(len(reports) == 3, 'Computed notice family requires three rows')
    seeds = []
    if origin == 'specified' and state == 'COMPUTED' and family.get('three_seed'):
        seed_family = family['three_seed']
        require(seed_family.get('state', 'COMPUTED') in STATES, 'Invalid specified seed disposition')
        if seed_family.get('state', 'COMPUTED') == 'COMPUTED':
            seeds = seed_family.get('reports', [])
            require(tuple((r['arm'], r['reference']) for r in seeds) == PAIRS,
                    'Specified seed row census/order mismatch')
    output = []
    for index, (arm, ref) in enumerate(PAIRS):
        timestamp_checks = dict(base, pointer='/reports/'+str(index))
        row = deepcopy(reports[index]) if reports else {}
        cls = M.P.CLASS[row['decision']] if state == 'COMPUTED' else None
        evaluated = state == 'COMPUTED' and cls != 'NE'
        row_state = 'COMPUTED' if evaluated else 'NOT_EVALUABLE' if state == 'COMPUTED' else state
        own_reason = row.get('reason') or row.get('state') if row_state == 'NOT_EVALUABLE' and reason is None else reason
        if row_state == 'NOT_EVALUABLE' and not own_reason:
            own_reason = 'NOT_EVALUABLE'
        seed_row = seeds[index] if seeds and evaluated else None
        seed_available = bool(seed_row and M.P.CLASS.get(seed_row.get('decision')) in ('IMP', 'DET', 'NULL'))
        if seed_row and not seed_available:
            seed_row = None
        if evaluated:
            if 'interval_family_one_day' not in row:
                row = M.P.native_row(row)
            checks, tier, _ = M.P.six_checks(M.primary_tests, M.sensitivity_tests, row, seed_row)
            checks = dict(checks)
            require(set(checks) == set(CHECKS) and tier in TIERS, 'Frozen six-check contract drift')
            boot = row['bootstrap']
            seven_state = boot['7'].get('state', 'COMPUTED')
            seven_agrees = M.primary_tests.interval_agrees(row['decision'], row.get('interval_family_seven_day'))
            if seven_state in ('NOT_INFORMATIVE_ONE_ADMISSIBLE_SEVEN_DAY_BLOCK',
                               'UNDEFINED_NO_COMPLETE_SEVEN_CALENDAR_DAY_BLOCK'):
                seven_agrees = None
            seven_dissent = None if seven_agrees is None else not seven_agrees
            envelope = M.robustness_tests.envelope(row)
        else:
            checks, tier, seven_state, seven_dissent, envelope = {k: 'UNAVAILABLE' for k in CHECKS}, None, None, None, None
        def value(key):
            return number(row.get(key)) if evaluated else None
        def class_value(key):
            return M.P.CLASS.get(row.get(key)) if evaluated else None
        def dissent(key):
            return None if checks[key] == 'UNAVAILABLE' else checks[key] == 'FAIL'
        exclusion_allowed = bool(evaluated and cls in ('NULL', 'DET') and not alert and envelope is not None)
        out = dict(origin=origin, delay_minutes=delay, arm=arm, reference=ref, state=row_state,
            **{'class': cls, 'direction': direction(cls)},
            estimate_percent=value('effect_percent_reference_mae'), mean_difference_aud=value('mean_difference'),
            intervals=dict(per_contrast_one_day=interval(row.get('interval95_one_day')) if evaluated else None,
                per_contrast_seven_day=interval(row.get('interval95_seven_day')) if evaluated else None,
                family_one_day=interval(row.get('interval_family_one_day')) if evaluated else None,
                family_seven_day=interval(row.get('interval_family_seven_day')) if evaluated else None,
                family_m=3, two_sided_level=1-M.primary_tests.ALPHA/3, one_sided_level=1-M.primary_tests.ALPHA/(2*3)),
            dm=dict(state=row.get('dm_state') if evaluated else None, statistic=value('statistic'),
                raw_p_two_sided=value('p_two_sided'), holm_p=value('holm_p')),
            hln=dict(decision=class_value('hln_decision'), raw_p_two_sided=value('hln_p_two_sided'),
                holm_p=value('hln_holm_p'), dissent=dissent('hln')),
            hac7=dict(state=row.get('hac7_state') if evaluated else None, decision=class_value('hac7_decision'),
                raw_p_two_sided=value('hac7_p_two_sided'), holm_p=value('hac7_holm_p'), dissent=dissent('hac7')),
            checks=checks, frozen_tier=tier, claim_tier=tier if cls in ('IMP', 'DET') else None,
            seven_day_family_dissent=seven_dissent, seven_day_state=seven_state,
            seed_check=dict(availability='AVAILABLE' if seed_available else 'UNAVAILABLE',
                label='primary seed only' if origin == 'aligned' or not seed_available else 'own specified seed check',
                **{'class': M.P.CLASS[seed_row['decision']] if seed_available else None},
                timestamp_checks=dict(base, pointer='/three_seed/reports/'+str(index)) if seed_available else None),
            alert=alert,
            exclusion=dict(permitted=exclusion_allowed,
                upper_percent=number(envelope['U']) if exclusion_allowed else None,
                one_sided_level=1-M.primary_tests.ALPHA/(2*3) if exclusion_allowed else None,
                conditions=['sealed primary-seed predictions', 'daily resampling',
                            'one-day/seven-day frozen family interval envelope'] if exclusion_allowed else [],
                timestamp_checks=timestamp_checks if exclusion_allowed else None),
            native_authority=timestamp_checks, reason=own_reason, disposition=disposition)
        validate_reading(out)
        output.append(out)
    return output
