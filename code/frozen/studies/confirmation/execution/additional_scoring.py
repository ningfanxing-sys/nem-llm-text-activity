'Compute additional scoring comparisons and the specified sensitivities.'
from __future__ import annotations

from datetime import date, timedelta
import json
import math
from pathlib import Path


DECISIONS_SHA256 = 'dca801989de8834709e93bb0f57934734411506546e13082bfd8df182dddead5'
SPEC_SHA256 = 'e1622a6adb9a7506ab555444bc799343d65b5f086a7c859e7d7557daa4994a8c'
A1_SOURCE = 'confirmation/A1/DECISIONS_A1_source.md (binding decisions); confirmation/input_definitions/SPEC.md (implementation rules)'
SEED = 20260919
EXTRA_SEEDS = (20260920, 20260921)


A1_SPECIFIED_DISPOSITIONS = (('news', 'W2_D', 'main'), ('notice', 'NPM', 'main'))
A1_SECONDARY_CONTRASTS = {'news': (('W2_D', 'N'), ('W2_D', 'M'), ('L_chen', 'W2_D'), ('W2_D', 'LEAR')),
                          'notice': (('NPM', 'N'), ('NPL', 'NPM'))}
E3_RECLIP_CONTRASTS = (('NPL', 'NP'), ('NPL', 'NPP'), ('NP', 'N'), ('NPP', 'NP'), ('NPL', 'NPM'))


def require_a1_dispositions(manifest):

    present = {(b.get('source'), b.get('arm'), b.get('variant', 'main')) for b in manifest.get('bundles', [])}
    missing = [key for key in A1_SPECIFIED_DISPOSITIONS if key not in present]
    if missing:
        raise PermissionError('Feature manifest lacks the input_definitions (confirmation-A1) dispositions ' + repr(missing) +
                              '; rerun cli.py features under the input_definitions adapters')
    return manifest


SHIFT_DEPENDENT_NOTICE_ARMS = ('M_shift_notice', 'P_shift', 'NPP')
NOTICE_WINDOW = ('2026-08-01', '2026-09-30')
SHIFT_SUPPORT_DAYS = ('2026-08-24', '2026-09-30')
SHIFT_GAP_DAYS = ('2026-08-01', '2026-08-23')
SHIFT_GAP_STATE = 'NOT_EVALUABLE_SHIFT_SUPPORT_GAP'


def shift_dependent(source, arm, reference):
    return source == 'notice' and (arm in SHIFT_DEPENDENT_NOTICE_ARMS or reference in SHIFT_DEPENDENT_NOTICE_ARMS)


def shift_support_mask(panel):
    days = panel['target_day'].astype(str)
    return days.between(*SHIFT_SUPPORT_DAYS).to_numpy()


def shift_slot_fields():
    return {'a1_day_rule': 'SHIFT_SUPPORTED_TARGET_DAYS_ONLY',
            'evaluated_target_days': list(SHIFT_SUPPORT_DAYS), 'evaluated_target_day_count': _span(*SHIFT_SUPPORT_DAYS),
            'not_evaluable_target_days': {'first': SHIFT_GAP_DAYS[0], 'last': SHIFT_GAP_DAYS[1],
                                          'count': _span(*SHIFT_GAP_DAYS), 'state': SHIFT_GAP_STATE,
                                          'reason': 'No notice was saved between 2026-05-18 14:00 and 2026-07-27 00:00 AEST, so '
                                                    'the 28-day-shifted notice inputs of these target days are a source gap; '
                                                    'STUDY_DESIGN section 4 does not allow a gap to be read as zero activity.'},
            'a1_sentence': 'Under confirmation-A1 decision 5 this contrast is evaluated only on the 38 shift-supported target days '
                           '2026-08-24..2026-09-30 with the sealed predictions (no refit); target days 2026-08-01..2026-08-23 '
                           'are NOT_EVALUABLE_SHIFT_SUPPORT_GAP.'}


E3_DAY_RULE = ('E3 joint reading under confirmation-A1 decision 5: NPL−NP on the 61 target days 2026-08-01..2026-09-30 and '
               'NPL−NPP on the 38 shift-supported target days 2026-08-24..2026-09-30.')


EXPOSURE_EXCLUDED_RUNS = {'news': (('2026-05-19', '2026-06-30'), ('2026-07-25', '2026-08-31'), ('2026-09-12', '2026-09-30')),
                          'notice': (('2026-08-01', '2026-08-31'), ('2026-09-12', '2026-09-30'))}
EXPOSURE_EXCLUDED_DAY_COUNTS = {'news': 100, 'notice': 50}
EXPOSURE_RULE = ('Target days with no recorded analysis of D prices in confirmation/A1/DATA_EXPOSURE_LOG.md (summary: no analysis is '
                 'recorded for 19 May-30 June, 25-31 July, August and 12-30 September 2026; the governance record calls '
                 '25 July-23 September "unknown"). Descriptive sensitivity; sealed predictions; no refit.')
EXPOSURE_WORDING = ('a retrospective out-of-sample confirmation for this study, part of whose window had been examined '
                    'earlier elsewhere in the project (confirmation/A1/DATA_EXPOSURE_LOG.md)')


def _span(first, last):
    return (date.fromisoformat(last) - date.fromisoformat(first)).days + 1


def exposure_excluded_days(source):
    days = []
    for first, last in EXPOSURE_EXCLUDED_RUNS[source]:
        d = date.fromisoformat(first)
        while d <= date.fromisoformat(last):
            days.append(d.isoformat()); d += timedelta(days=1)
    if len(days) != EXPOSURE_EXCLUDED_DAY_COUNTS[source] or days != sorted(set(days)):
        raise ValueError('Frozen exposure-excluded day list drift')
    return days


OFFICIAL_MARKET_PRICE_CAP = (('2023-07-01', '2024-07-01', 16600.), ('2024-07-01', '2025-07-01', 17500.),
                             ('2025-07-01', '2026-07-01', 20300.), ('2026-07-01', '2027-07-01', 23200.))
OFFICIAL_MARKET_FLOOR = -1000.
WINDOW_C_RECLIP_STATE = ('NOT_COMPUTABLE_FROM_SEALED_RAW_PREDICTIONS: window C (FY2025-26 cap 20,300) has no sealed raw '
                         'prediction in confirmation; notice_fitting/final/predictions stores only the clipped prediction for each arm and seed.')


def official_market_price_cap(target):
    import numpy as np
    import pandas as pd
    local = pd.to_datetime(pd.Series(target), utc=True).dt.tz_convert('Australia/Brisbane')
    cap = np.full(len(local), np.nan)
    for first, end, value in OFFICIAL_MARKET_PRICE_CAP:
        lo, hi = pd.Timestamp(first, tz='Australia/Brisbane'), pd.Timestamp(end, tz='Australia/Brisbane')
        cap[((local >= lo) & (local < hi)).to_numpy()] = value
    if np.isnan(cap).any():
        raise ValueError('Official market price cap is not specified for a target date (only FY2023-24..FY2026-27)')
    return cap


def official_reclip(raw_prediction, target):
    'Clip to each target-date cap and cast the result to float32.'
    import numpy as np
    raw = np.asarray(raw_prediction, dtype='float64')
    if not np.isfinite(raw).all():
        raise ValueError('Sealed raw prediction must be finite')
    return np.clip(raw, OFFICIAL_MARKET_FLOOR, official_market_price_cap(target)).astype('float32')


HLN_NAME = 'the HLN t(n−1) Holm sensitivity'


def hln_p_two_sided(statistic, n_days):

    if statistic is None or not isinstance(n_days, int) or n_days < 2:
        return None
    if not math.isfinite(float(statistic)):
        return None
    from scipy.stats import t
    return float(min(1.0, 2.0 * t.sf(abs(float(statistic)), df=n_days - 1)))


def decision_class(mean, p):
    if p is None or mean is None or not math.isfinite(p) or not math.isfinite(mean):
        return 'NOT_EVALUABLE'
    if p < .05:
        return 'CONDITIONAL_IMPROVEMENT' if mean < 0 else 'CONDITIONAL_DETERIORATION'
    return 'NO_RELIABLE_INCREMENT_DETECTED'


def hln_family(reports, holm):
    'Compute Student-t(n−1) p-values and adjust them within each Holm family.'
    raw = [hln_p_two_sided(r['dm_p1'].get('statistic'), r['dm_p1'].get('n_days')) for r in reports]
    adjusted = holm(raw)
    rows = []
    for r, p, adj in zip(reports, raw, adjusted):
        mean = r['dm_p1'].get('mean_difference')
        decision = decision_class(mean, adj)
        agrees = decision == r.get('primary_decision')
        rows.append({'arm': r['arm'], 'reference': r['reference'], 'n_days': r['dm_p1'].get('n_days'),
                     'df': None if r['dm_p1'].get('n_days') is None else r['dm_p1']['n_days'] - 1,
                     'statistic': r['dm_p1'].get('statistic'), 'hln_t_p_two_sided': p, 'hln_t_holm_p': adj,
                     'hln_decision': decision, 'primary_decision': r.get('primary_decision'),
                     'agrees_with_primary_decision': agrees,
                     'disagreement_sentence': None if agrees else
                         'The nominal DM decision is not supported consistently by ' + HLN_NAME +
                         '. This disagreement limits the robustness of the conclusion; the primary decision and every '
                         'sensitivity are retained.'})
    return {'analysis_role': 'A1_DECLARED_SENSITIVITY_HLN_T', 'family_size': len(reports), 'rows': rows,
            'rule': 'confirmation-A1 decision 9: frozen statistic sqrt(n) mean/sd (equal to HLN S1* at h = 1); two-sided p from '
                    'Student t with n-1 df; Holm per family with the frozen size; the primary normal-calibrated decision '
                    'is unchanged.'}


PER_TASK_RULE = ('Each task is read and reported on its own. No sentence pools the news and notice families into a general '
                 'claim about LLM-processed content; with two families each at alpha = .05, the chance that at least one '
                 'rejects when both global nulls hold is up to 1 - 0.95^2 = 9.75% under independence (confirmation-A1 decision 9).')


def per_task_statements(primary_by_source):
    lines = []
    for source, label in (('news', 'News task'), ('notice', 'Notice task')):
        reports = primary_by_source.get(source)
        if not reports:
            lines.append(label + ': NOT_EVALUABLE (no saved primary family).')
            continue
        parts = '; '.join(r['arm'] + '−' + r['reference'] + ': ' + str(r.get('primary_decision', 'NOT_EVALUABLE'))
                          for r in reports)
        lines.append(f'{label} (specified Holm family of {len(reports)}, read on its own): {parts}.')
    lines.append(PER_TASK_RULE)
    return lines


SESOI_PERCENT = 3.8
SESOI_TEXT = {
    'NO_REJECTION_BOUND_BELOW_SESOI':
        'This conditional one-sided 97.5% bound ({x}%) is below the pre-specified smallest effect size of interest (3.8%, '
        'the smallest significance-tested text gain reported in the cited top-venue electricity forecasting work); '
        'improvements of that size are not supported by this window, conditional on these fitted predictions. This is not '
        'an equivalence test and does not show a zero effect.',
    'NO_REJECTION_BOUND_AT_OR_ABOVE_SESOI':
        'This conditional bound ({x}%) does not exclude improvements as large as the smallest effect size of interest '
        '(3.8%); the window is uninformative about effects of that size.',
    'IMPROVEMENT_BELOW_SESOI':
        'The increment is statistically reliable under the specified rule but smaller than the smallest effect size of '
        'interest (3.8%).',
    'IMPROVEMENT_AT_OR_ABOVE_SESOI':
        'The increment is statistically reliable and at least as large as the smallest effect size of interest (3.8%).'}


def _number(value):
    return format(value, '.12g') if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else 'undefined'


def _bootstrap(report, block):
    items = report.get('bootstrap', {})
    return items.get(str(block), items.get(block, {})) or {}


def _interval(report, block):
    value = _bootstrap(report, block).get('interval95_percent')
    if isinstance(value, (list, tuple)) and len(value) == 2 and all(isinstance(x, (int, float)) and math.isfinite(x) for x in value):
        return list(value)
    return None


def sesoi_reading(report):

    decision = report.get('primary_decision')
    one, seven = _interval(report, 1), _interval(report, 7)
    effect = _bootstrap(report, 1).get('effect_percent_reference_mae')
    out = {'arm': report['arm'], 'reference': report['reference'], 'sesoi_percent': SESOI_PERCENT,
           'primary_decision': decision}
    if decision == 'NO_RELIABLE_INCREMENT_DETECTED' and one is not None:
        x = max(0.0, -one[0])
        branch = 'NO_REJECTION_BOUND_BELOW_SESOI' if x < SESOI_PERCENT else 'NO_REJECTION_BOUND_AT_OR_ABOVE_SESOI'
        out.update(branch=branch, bound_percent=x, sentence=SESOI_TEXT[branch].format(x=_number(x)))
        if seven is not None:
            x7 = max(0.0, -seven[0])
            b7 = 'NO_REJECTION_BOUND_BELOW_SESOI' if x7 < SESOI_PERCENT else 'NO_REJECTION_BOUND_AT_OR_ABOVE_SESOI'
            out.update(seven_day_branch=b7, seven_day_bound_percent=x7,
                       seven_day_sentence='Seven-day block bound (secondary): ' + SESOI_TEXT[b7].format(x=_number(x7)))
        else:
            out.update(seven_day_branch='NO_SESOI_SENTENCE_UNDEFINED_INTERVAL', seven_day_sentence=None)
    elif decision == 'CONDITIONAL_IMPROVEMENT' and isinstance(effect, (int, float)) and math.isfinite(effect):
        branch = 'IMPROVEMENT_BELOW_SESOI' if abs(effect) < SESOI_PERCENT else 'IMPROVEMENT_AT_OR_ABOVE_SESOI'
        out.update(branch=branch, effect_percent=effect, sentence=SESOI_TEXT[branch])
    elif decision == 'CONDITIONAL_DETERIORATION':
        out.update(branch='NOT_APPLICABLE_DETERIORATION', sentence=None)
    else:
        out.update(branch='NO_SESOI_SENTENCE_UNDEFINED_INTERVAL', sentence=None)
    return out


def _sign(value):
    if value is None or not math.isfinite(value):
        return None
    return (value > 0) - (value < 0)


def _reading_text(report):
    one = _interval(report, 1)
    return (str(report.get('primary_decision', 'NOT_EVALUABLE')) + ', ' +
            _number(_bootstrap(report, 1).get('effect_percent_reference_mae')) + '%, one-day interval ' +
            ('[' + ','.join(_number(v) for v in one) + ']%' if one is not None else 'undefined'))


def seed_fragility(primary_reports, three_seed_reports, seed_reports, reason=None):
    'Compare the signs and decisions of the primary seed and mean forecast.'
    rows = []
    for index, report in enumerate(primary_reports):
        key = (report['arm'], report['reference'])
        effects = {str(SEED): _bootstrap(report, 1).get('effect_percent_reference_mae')}
        for seed, result in sorted((seed_reports or {}).items()):
            match = [r for r in result['reports'] if (r['arm'], r['reference']) == key]
            effects[str(seed)] = _bootstrap(match[0], 1).get('effect_percent_reference_mae') if match else None
        finite = [v for v in effects.values() if isinstance(v, (int, float)) and math.isfinite(v)]
        sd = None
        if len(finite) == 3:
            mean = sum(finite) / 3
            sd = math.sqrt(sum((v - mean) ** 2 for v in finite) / 2)
        row = {'arm': key[0], 'reference': key[1], 'single_seed_effects_percent_reference_mae': effects,
               'single_seed_effect_sd_percent': sd, 'seed_20260919_decision': report.get('primary_decision'),
               'seed_20260919_mean_difference': report['dm_p1'].get('mean_difference')}
        if three_seed_reports is None:
            row.update(state='SEED_ROBUSTNESS_NOT_EVALUABLE',
                       reason=reason or 'the three-seed equal prediction mean was not computed',
                       sentence='SEED_ROBUSTNESS_NOT_EVALUABLE: ' + (reason or 'the three-seed equal prediction mean was not computed') + '.')
            rows.append(row); continue
        other = three_seed_reports[index]
        if (other['arm'], other['reference']) != key:
            raise ValueError('Three-seed family order differs from the primary family')
        row.update(three_seed_mean_decision=other.get('primary_decision'),
                   three_seed_mean_difference=other['dm_p1'].get('mean_difference'))
        fragile = (other.get('primary_decision') != report.get('primary_decision') or
                   _sign(other['dm_p1'].get('mean_difference')) != _sign(report['dm_p1'].get('mean_difference')))
        if fragile:
            row.update(state='SEED_FRAGILE', sentence=(
                'SEED_FRAGILE: the specified seed-20260919 reading [' + _reading_text(report) +
                '] is not reproduced by the three-seed mean [' + _reading_text(other) +
                ']; the result is reported as seed-fragile and is not described as a robust increment.'))
        else:
            row.update(state='SEED_CONSISTENT', sentence=(
                'SEED_CONSISTENT: the specified seed-20260919 reading [' + _reading_text(report) +
                '] is reproduced in sign and decision class by the three-seed mean [' + _reading_text(other) +
                ']; this is not proof of seed invariance, and the frozen per-seed sign check is reported separately.'))
        rows.append(row)
    return {'analysis_role': 'A1_REPORTING_RULE_SEED_FRAGILE', 'rows': rows,
            'rule': 'confirmation-A1 decision 3: SEED_FRAGILE if the seed-20260919 decision class and the three-seed-mean decision '
                    'class differ, or the signs of their mean differences differ; the frozen decision rule is unchanged.'}


def w_bai_note(state):
    return ('W_Bai is reported unavailable under confirmation-A1 decision 4, for two reasons: (1) the frozen selection '
            'returned ' + str(state) + '; the frozen code requires every day 2021-10-01..2024-12-31 to have 72 labels '
            'available before 2024-12-31T14:00Z, which 2024-12-31 can never meet (its last hourly label is available at '
            '2025-01-01 00:05 AEST); (2) independently of that input_checks, the frozen thresholds (title >= 200, body >= 5,000) '
            'select a single candidate ("nsw") on the 1,349-article training corpus, and it fails the bilateral Granger '
            "filter (A1 results C5 and C5b). The frozen W_Bai code is unchanged; the specified W2_D arm uses Bai's "
            'stated vocabulary sizes instead.')


def json_safe(value):
    import numpy as np
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def dumps(value):
    return json.dumps(json_safe(value), sort_keys=True, ensure_ascii=False, allow_nan=False)
