'Load the checked sensitivity validators.'
import re
import numpy as np
from ..input_checks import require
from .sensitivity_export import SEEDS, SERIES, MEAN_DEFINITION, ARMS as TASK_ARMS, days
TASKS={t:dict(days=days(t),keys_per_day=72 if t=='news' else 8640,arms=TASK_ARMS[t]) for t in ('news','notice')}
DAYS=days('news')

def sha_value(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None

def series_disposition(bundle, tag):

    state, parity = (bundle.get('state'), bundle.get('frozen_parity'))
    native = bundle.get('native_status', state)
    require(state in ('COMPUTED', 'NOT_RUN', 'NOT_EVALUABLE', 'DEVIATION', 'PENDING'), 'Unknown native series status')
    require(isinstance(native, str) and bool(native), 'Nonempty native status required')
    computed = state == 'COMPUTED' and parity == 'PASS' and (native == 'COMPUTED')
    if tag == SERIES[0]:
        require(computed, f'Primary-seed completion/parity failure: state={state}, native_status={native}, parity={parity}, reason={bundle.get('reason', '')}')
    if computed:
        effective = 'COMPUTED'
    else:
        require(isinstance(bundle.get('reason'), str) and bool(bundle['reason']), 'Native failure reason required')
        not_run = state == 'NOT_RUN' and native == 'NOT_RUN' and (parity in (None, 'NOT_RUN'))
        effective = 'NOT_RUN' if not_run else 'NOT_EVALUABLE'
    return dict(state=effective, native_status=native, native_parity=parity, reason=bundle.get('reason', ''))

def validate_export(export, expected_task=None, metadata_only=False):
    require(export.get('schema') == 'SENS35_TASK_LOSSES_V2', 'Wrong loss export schema')
    task = export.get('task')
    require(task in TASKS and (expected_task is None or task == expected_task), 'Wrong task export')
    config = TASKS[task]
    days, n = (config['days'], len(config['days']))
    require(export.get('days') == days, 'Missing, extra, duplicate or unordered task days')
    view = export.get('evaluation_view', {})
    require(view.get('schema') == 'PCPRIMARY_R2_NEWS_EVALUATION_V1' and view.get('issue_days') == DAYS and (view.get('primary_days') == 135) and (view.get('sealed_domain_days') == 214) and sha_value(view.get('scientific_source_sha256')), 'Wrong R2 evaluation view')
    require(export.get('daily_common_key_counts') == [config['keys_per_day']] * n, 'Task common grid attestation failed')
    for field in ('common_keys_sha256', 'sealed_prediction_manifest_sha256', 'r2_score_receipt_sha256', 'main_daily_csv_sha256'):
        require(sha_value(export.get(field)), 'Missing export identity: ' + field)
    require(export.get('main_daily_csv_parity') == 'PASS', 'Main daily CSV parity required')
    series = export.get('series', {})
    require(set(series) == set(SERIES), 'Missing/extra seed or mean disposition')
    dispositions = {}
    for tag in SERIES:
        bundle = series[tag]
        require(bundle.get('days') == days, 'Missing/extra days in ' + tag)
        require(bundle.get('seeds') == (list(SEEDS) if tag == SERIES[-1] else [int(tag[5:])]), 'Wrong seed definition: ' + tag)
        dispositions[tag] = series_disposition(bundle, tag)
    if metadata_only:
        return
    for tag in SERIES:
        bundle = series[tag]
        if dispositions[tag]['state'] != 'COMPUTED':
            continue
        if tag == SERIES[-1]:
            require(bundle.get('loss_definition') == MEAN_DEFINITION, 'Mean-prediction losses required')
        require(set(bundle.get('losses', {})) == set(config['arms']), 'Exact primary arms required')
        for arm, values in bundle['losses'].items():
            require(isinstance(values, list) and len(values) == n and all((isinstance(v, (int, float)) and (not isinstance(v, bool)) for v in values)), 'Daily loss shape/type mismatch: ' + tag + '/' + arm)
            x = np.asarray(values, dtype='float64')
            require(np.isfinite(x).all() and (x >= 0).all(), 'Invalid absolute daily losses')
