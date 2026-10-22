"""Synthetic edge-case fixtures for FILL3b (ADDENDUM_A4 section E), built from the real design constants. No study data.

Each fixture builds A2-layout primary rows and A3-layout task records with the frozen A3 functions, adds the A4 inputs
(three-seed family intervals, secondary slot readings, positive-control state with Clopper-Pearson bounds, batch
results limited to the frozen states) and renders the expected abstract (with its ladder level), the section 6 sentences
of the fixture task and the conclusion core with `a4_postscore.render`.

    python edge_fixtures_a4.py --write   # writes ../EDGE_FIXTURES_SPEC_A4.md and ../tests/edge_fixtures_a4.json
"""
import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
A4_ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('a4_postscore_fixtures', A4_ROOT / 'code/a4_postscore.py')
a4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a4)
A3, A2 = a4.A3, a4.A2
IMP, DET, NULL, NE = a4.IMP, a4.DET, a4.NULL, a4.NE

# Real design constants (ADDENDUM_A4 section E).
DESIGN = {'news_days': 214, 'notice_days': 61, 'm': {'news': 2, 'notice': 3}, 'level': A3.LEVEL_TEXT, 'S': A3.SESOI,
          'mde': A3.MDE_PERCENT, 'coverage': {'news': {'matched_keys': 216, 'total_keys': 15408, 'matched_share_percent': 1.4018691588785046,
                                                       'days_with_matched_key': 3, 'n_days': 214}},
          'shift_days': {'news': 214, 'notice': 38}, 'pc_planted_replicates': 40}


def row(arm, ref, cls, effect, one95, fam, mean_aud, holm_p, p_raw, seven=None, hln=None, hac=None, fam7=None):
    """A2 primary-row layout; the seven-day family interval defaults to the one-day one widened by 5% each side."""
    if fam7 is None and fam is not None:
        w = 0.05 * (fam[1] - fam[0])
        fam7 = [fam[0] - w, fam[1] + w]
    return {'arm': arm, 'reference': ref, 'decision': cls, 'effect_percent_reference_mae': effect,
            'interval95_one_day': one95, 'interval95_seven_day': seven or one95, 'interval_family_one_day': fam,
            'interval_family_seven_day': fam7, 'mean_difference': mean_aud, 'holm_p': holm_p, 'p_two_sided': p_raw,
            'hln_decision': hln or cls, 'hac7_decision': hac or cls}


def slot(arm, ref, mean, p, state='COMPUTED_SECONDARY', **extra):
    return {'arm': arm, 'reference': ref, 'state': state, 'daily_mean_difference': mean, 'p_two_sided': p, **extra}


def reading(effect, lo, hi, mean, p, days=None):
    return {'state': 'COMPUTED', 'effect': effect, 'interval95': [lo, hi], 'mean_difference': mean, 'p_two_sided': p,
            'class': A2.decision_class(mean, p), 'days': days}


def combo(source, arm, ref, cls, primary_cls, effect, one95, fam, holm_p):
    r = {'arm': arm, 'reference': ref, 'decision': cls, 'effect_percent_reference_mae': effect, 'holm_p': holm_p,
         'bootstrap': {'1': {'interval95_percent': list(one95), 'interval_family_adjusted_percent': list(fam)},
                       '7': {'interval95_percent': list(one95)}}, 'hln_decision': cls, 'hac7_decision': cls}
    r['clause_id'], r['sentence'] = A2.combination_clause(source, r, primary_cls)
    return r


SECONDARY = {'news': [slot('L_chen', 'P_content', None, None, state='NOT_EVALUABLE_INSUFFICIENT_REGISTERED_BLOCK_SUPPORT'),
                      slot('P_content', 'M', None, None, state='NOT_EVALUABLE_INSUFFICIENT_REGISTERED_BLOCK_SUPPORT'),
                      slot('L_chen', 'P_shift', -0.61, 0.02, days=214),
                      slot('L_chen', 'E_raw', -0.40, 0.03), slot('L_chen', 'W2_D', -0.20, 0.20)],
             'notice': [slot('L_chen_notice', 'P_content', None, None, state='NO_VALID_PERMUTATION'),
                        slot('P_content', 'M_notice', None, None, state='NO_VALID_PERMUTATION'),
                        slot('L_chen_notice', 'P_shift', -0.004, 0.03, days=38)]}
CHEAP = {'news': {('L_chen', 'E_raw'): SECONDARY['news'][3], ('L_chen', 'W2_D'): SECONDARY['news'][4],
                  ('L_count', 'E_raw'): {'state': 'COMPUTED', 'mean_difference': -0.5, 'p_two_sided': 0.2},
                  ('L_count', 'W2_D'): {'state': 'COMPUTED', 'mean_difference': -0.9, 'p_two_sided': 0.03}},
         'notice': {('L14', 'R'): {'state': 'COMPUTED', 'mean_difference': -0.02, 'p_two_sided': 0.3},
                    ('L14', 'T'): {'state': 'COMPUTED', 'mean_difference': 0.05, 'p_two_sided': 0.01},
                    ('L_Laz', 'R'): {'state': 'COMPUTED', 'mean_difference': -0.01, 'p_two_sided': 0.6},
                    ('L_Laz', 'T'): {'state': 'COMPUTED', 'mean_difference': 0.01, 'p_two_sided': 0.7},
                    ('L_chen_notice', 'R'): {'state': 'COMPUTED', 'mean_difference': -0.02, 'p_two_sided': 0.2},
                    ('L_chen_notice', 'T'): {'state': 'COMPUTED', 'mean_difference': 0.01, 'p_two_sided': 0.7}}}
NULL_NEWS = [row('L_count', 'M', NULL, 0.12, [-1.9, 2.1], [-2.2, 2.4], 0.07, 0.8, 0.4),
             row('L_chen', 'M', NULL, -0.3, [-2.2, 1.7], [-2.5, 2.0], -0.17, 0.8, 0.6)]
NULL_NOTICE = [row('L14', 'M_notice', NULL, 0.01, [-0.06, 0.08], [-0.07, 0.09], 0.002, 0.9, 0.7),
               row('L_Laz', 'M_notice', NULL, -0.02, [-0.09, 0.05], [-0.1, 0.06], -0.005, 0.9, 0.5),
               row('L_chen_notice', 'M_notice', NULL, 0.03, [-0.05, 0.1], [-0.06, 0.11], 0.007, 0.9, 0.3)]
SLOTS = {'news': {'mn': reading(-0.524, -1.102, 0.061, -0.301, 0.08), 'lear': reading(-18.204, -19.880, -16.511, -9.71, 0.0001),
                  'shift': reading(-0.88, -1.62, -0.11, -0.61, 0.02, 214),
                  'tvn': {'L_count-N': reading(-0.401, -1.701, 0.902, -0.23, 0.55), 'L_chen-N': reading(-0.823, -2.101, 0.461, -0.47, 0.21),
                          'M-N': reading(-0.524, -1.102, 0.061, -0.301, 0.08)}},
         'notice': {'mn': reading(-0.0310, -0.0612, -0.0011, -0.0076, 0.04), 'shift': reading(-0.0161, -0.0302, -0.0019, -0.004, 0.03, 38)}}
PC_PASS = {'readings': {'N2': {'PIPELINE_SENSITIVE_AT_2xMDE': True, 'PIPELINE_ATTENUATES': False, 'SIZE_INFLATED': False},
                        'notice': {'PIPELINE_SENSITIVE_AT_2xMDE': True, 'PIPELINE_ATTENUATES': False, 'SIZE_INFLATED': False},
                        'N1_AGREES_WITH_N2': True},
           'summary': [{'task': 'news', 'tier': 'N2', 'mult': 2.0, 'replicates': 40, 'detected': 36, 'detection_rate': 0.9,
                        'detection_cp95': [0.763, 0.972], 'delta_pct_median': -6.512, 'uptake_median': 0.611},
                       {'task': 'news', 'tier': 'N2', 'mult': 0.0, 'replicates': 40, 'detected': 0, 'detection_rate': 0.0,
                        'detection_cp95': [0.0, 0.0881], 'delta_pct_median': 0.01, 'uptake_median': None},
                       {'task': 'notice', 'tier': 'notice', 'mult': 2.0, 'replicates': 40, 'detected': 40, 'detection_rate': 1.0,
                        'detection_cp95': [0.912, 1.0], 'delta_pct_median': -0.231, 'uptake_median': 0.902},
                       {'task': 'notice', 'tier': 'notice', 'mult': 0.0, 'replicates': 40, 'detected': 1, 'detection_rate': 0.025,
                        'detection_cp95': [0.0006, 0.1316], 'delta_pct_median': 0.0, 'uptake_median': None}],
           'pre_d_only': True}
PC_SHA = 'f' * 64


def pc_variant(news=None, notice=None):
    pc = json.loads(json.dumps(PC_PASS))
    for source, change in (('news', news), ('notice', notice)):
        if not change:
            continue
        tier = A3.PC_TIER[source]
        rows = {r['mult']: r for r in pc['summary'] if r['task'] == source}
        if 'sens' in change:
            rows[2.0].update(detected=24, detection_rate=0.6, detection_cp95=[0.433, 0.751], delta_pct_median=-2.104, uptake_median=0.21)
            pc['readings'][tier].pop('PIPELINE_SENSITIVE_AT_2xMDE')
            pc['readings'][tier]['PIPELINE_SENSITIVITY_LIMITED'] = True
        if 'size' in change:
            rows[0.0].update(detected=5, detection_rate=0.125, detection_cp95=A4CP(5, 40))
            pc['readings'][tier]['SIZE_INFLATED'] = True
    return pc


def A4CP(k, n):
    return a4.clopper_pearson(k, n)


def pcx(news_k=0, notice_k=0):
    rows = []
    for task, tier, k in (('news', 'N2', news_k), ('notice', 'notice', notice_k)):
        for r in range(41, 201):
            rows.append({'task': task, 'tier': tier, 'replicate': r, 'detected': (r - 41) < k, 'any_direction_rejection': (r - 41) < k,
                         'delta_pct': 0.0, 'dm_p_two_sided': 0.5})
    return {'state': 'PCX_SCORED', 'frozen_result_sha256': PC_SHA, 'rows': rows}


def a3task(source, rows, *, three_seed=None, label=None, files=None, batch=None, combos=()):
    robust, ts_pairs = {}, {}
    for r in rows:
        key = f"{r['arm']}-{r['reference']}"
        tsc = (three_seed or {}).get(r['arm'], r['decision'])
        robust[key] = A3.robustness_a3(r['decision'], r['interval95_one_day'], r['interval95_seven_day'], r['hln_decision'],
                                       r['hac7_decision'], tsc)
    states = A3.sensitivity_states(source, rows, files or {}, batch, label)
    attributions = [A3.attribution_a3(source, r['arm'], r['decision'], SECONDARY[source], CHEAP[source], {'matched_share_percent': None})
                    for r in rows]
    combination = {'state': 'COMPUTED', 'family': {'reports': list(combos)}} if combos else {'state': 'NOT_EVALUABLE_BENCHMARK_UNAVAILABLE'}
    crob = {f"{c['arm']}-{c['reference']}": A3.robustness_a3(c['decision'], c['bootstrap']['1']['interval95_percent'],
                                                             c['bootstrap']['7']['interval95_percent'], c['decision'], c['decision'], c['decision'])
            for c in combos}
    return {'robustness_a3': robust, 'design_sensitivities': {f'{a}-{b}': v for (a, b), v in states.items()},
            'attribution_a3': attributions, 'combination': combination, 'combination_robustness_a3': crob}


def ts_record(rows, three_seed_numbers=None):
    pairs = {}
    for r in rows:
        key = f"{r['arm']}-{r['reference']}"
        if three_seed_numbers and r['arm'] in three_seed_numbers:
            cls, eff, one, fam, holm = three_seed_numbers[r['arm']]
        elif r['decision'] in a4.CLASSES:
            cls, eff, one, fam, holm = r['decision'], r['effect_percent_reference_mae'], r['interval95_one_day'], r['interval_family_one_day'], r['holm_p']
        else:
            continue
        pairs[key] = {'state': 'COMPUTED', 'class': cls, 'effect': eff, 'interval95': one, 'interval_family': fam, 'holm_p': holm}
    return {'state': 'COMPUTED', 'pairs': pairs}


def task(source, rows, *, three_seed=None, three_seed_numbers=None, label=None, files=None, batch=None, combos=(), pc=PC_PASS,
         pcx_result=None, incomplete=None):
    t3 = a3task(source, rows, three_seed=three_seed, label=label, files=files, batch=batch, combos=combos)
    pc_state = a4.pc_state_a4(source, pc, pcx_result, PC_SHA)
    matched = A3.SENTENCES['A3W0'].format(n=DESIGN['coverage']['news']['days_with_matched_key']) if source == 'news' else A3.SENTENCES['A3C7']
    return a4.build_task(source, rows, t3, ts_record(rows, three_seed_numbers), pc_state, SLOTS[source], matched,
                         incomplete_reason=incomplete)


def batch_result(l1=None, pd=None):
    fams = {}
    for key, spec_ in (('L1', l1), ('PD', pd)):
        if spec_ is None:
            continue
        if isinstance(spec_, tuple):
            fams[key] = {'state': spec_[0], 'source_state': spec_[1], 'reason': 'recorded', 'reports': []}
        else:
            fams[key] = {'state': 'COMPUTED', 'reports': spec_}
    return {'families': fams}


def brow(arm, ref, mean, holm_p, effect, one95, fam95):
    return {'arm': arm, 'reference': ref, 'mean_difference': mean, 'holm_p': holm_p, 'effect_percent_reference_mae': effect,
            'bootstrap': {'1': {'interval95_percent': list(one95), 'interval_family_adjusted_percent': list(fam95)}}}


L1_NULL = [brow('L_count_L1', 'M_L1', 0.1, 0.7, 0.2, (-1.6, 2.0), (-1.9, 2.3)), brow('L_chen_L1', 'M_L1', -0.2, 0.6, -0.3, (-2.1, 1.5), (-2.4, 1.8))]
PD_NULL = [brow('L_count_PD', 'M_PD', 0.05, 0.8, 0.1, (-1.5, 1.7), (-1.8, 2.0)), brow('L_chen_PD', 'M_PD', -0.1, 0.7, -0.2, (-1.9, 1.5), (-2.2, 1.8))]
PD_DIFF = [PD_NULL[0], brow('L_chen_PD', 'M_PD', -1.9, 0.02, -3.4, (-5.9, -0.9), (-6.3, -0.5))]
L1_DIFF_BOTH = [brow('L_count_L1', 'M_L1', -1.2, 0.03, -2.1, (-3.9, -0.4), (-4.2, -0.1)), brow('L_chen_L1', 'M_L1', -1.9, 0.02, -3.4, (-5.9, -0.9), (-6.3, -0.5))]
PD_DIFF_BOTH = [brow('L_count_PD', 'M_PD', -1.1, 0.04, -2.0, (-3.8, -0.3), (-4.1, -0.1)), brow('L_chen_PD', 'M_PD', -1.8, 0.02, -3.2, (-5.6, -0.8), (-6.0, -0.4))]


def fixtures():
    F = {}
    F['pd_same_class'] = ('news', 'News null; the absolute-error and pre-dispatch families both run and agree with the primary class.',
                          [dict(r) for r in NULL_NEWS], {'batch': batch_result(L1_NULL, PD_NULL)})
    F['pd_different_class'] = ('news', 'News null; the pre-dispatch family finds an increment for the structured-attribute embedding.',
                               [dict(r) for r in NULL_NEWS], {'batch': batch_result(L1_NULL, PD_DIFF)})
    F['interval_straddles_reference'] = ('news', 'News: robust increment whose point estimate exceeds 3.8% but whose interval straddles it.',
                                         [dict(NULL_NEWS[0]), row('L_chen', 'M', IMP, -4.5, [-7.9, -1.2], [-8.3, -0.8], -2.58, 0.004, 0.004)],
                                         {'combos': [combo('news', 'L_chen', 'M', IMP, IMP, -2.0, (-3.1, -0.9), (-3.4, -0.6), 0.004)]})
    F['reliable_deterioration'] = ('news', 'News: the structured-attribute embedding is reliably worse (robust); the label-count representation shows none.',
                                   [row('L_count', 'M', NULL, 0.4, [-1.5, 2.3], [-1.8, 2.6], 0.23, 0.6, 0.6),
                                    row('L_chen', 'M', DET, 3.1, [1.2, 5.0], [0.9, 5.3], 1.78, 0.002, 0.001)], {})
    F['mixed_family'] = ('news', 'News: label-count increment (robust, no content control) and structured-attribute deterioration.',
                         [row('L_count', 'M', IMP, -4.6, [-7.0, -2.1], [-7.4, -1.7], -2.64, 0.002, 0.001),
                          row('L_chen', 'M', DET, 2.9, [0.9, 4.8], [0.6, 5.1], 1.66, 0.004, 0.004)],
                         {'combos': [combo('news', 'L_count', 'M', IMP, IMP, -2.0, (-3.1, -0.9), (-3.4, -0.6), 0.004)]})
    F['undefined_arm'] = ('notice', 'Notices: the message, failure and fuel-group counts are not evaluable; the other two show no reliable increment.',
                          [dict(NULL_NOTICE[0]), row('L_Laz', 'M_notice', NE, None, None, None, None, None, None), dict(NULL_NOTICE[2])], {})
    F['incomplete_confirmation'] = ('news', 'News primary fits did not finish within the 24-hour budget.', [],
                                    {'incomplete': A3.SENTENCES['A3INC_BUDGET']})
    F['holm_clause'] = ('news', 'News: two Holm rejections; the structured-attribute family-adjusted interval includes zero.',
                        [row('L_count', 'M', IMP, -3.9, [-6.0, -1.8], [-6.3, -1.5], -2.24, 0.002, 0.001),
                         row('L_chen', 'M', IMP, -2.0, [-3.9, -0.1], [-4.2, 0.2], -1.15, 0.03, 0.03)],
                        {'combos': [combo('news', 'L_count', 'M', IMP, IMP, -2.0, (-3.1, -0.9), (-3.4, -0.6), 0.004),
                                    combo('news', 'L_chen', 'M', NULL, IMP, -0.6, (-1.8, 0.5), (-2.0, 0.7), 0.3)]})
    F['fragile_three_seed_deterioration'] = (
        'news', 'News: the structured-attribute embedding is a primary-seed increment; HLN disagrees and the three-seed mean is a reliable deterioration.',
        [dict(NULL_NEWS[0]), row('L_chen', 'M', IMP, -4.667, [-4.86, -4.47], [-4.887, -4.456], -2.36, 0.001, 0.0005, hln=NULL)],
        {'three_seed': {'L_chen': DET}, 'three_seed_numbers': {'L_chen': (DET, 0.512, [0.11, 0.91], [0.05, 0.97], 0.02)},
         'combos': [combo('news', 'L_chen', 'M', NULL, IMP, -0.6, (-1.8, 0.5), (-2.0, 0.7), 0.3)]})
    F['planted_signal_failure_scenario_A'] = ('news', 'News null; the planted signal is detected in 24 of 40 replicates (sensitivity fails).',
                                              [dict(r) for r in NULL_NEWS], {'pc': pc_variant(news={'sens'})})
    F['size_failure_scenario_B'] = ('notice', 'Notices: robust event-state increment; the 200-replicate null column is over-detected (9 of 200).',
                                    [row('L14', 'M_notice', IMP, -0.62, [-0.8, -0.44], [-0.84, -0.4], -0.151, 0.0005, 0.0001),
                                     dict(NULL_NOTICE[1]), dict(NULL_NOTICE[2])],
                                    {'pcx_result': pcx(news_k=0, notice_k=8),
                                     'combos': [combo('notice', 'L14', 'M_notice', IMP, IMP, -0.3, (-0.45, -0.15), (-0.5, -0.1), 0.001)]})
    F['batch_not_run_and_deviation'] = ('news', 'News null; the absolute-error family did not fit the budget and the pre-dispatch family failed during execution.',
                                        [dict(r) for r in NULL_NEWS],
                                        {'batch': batch_result(('NOT_RUN_BUDGET', 'INCOMPLETE_BUDGET'), ('NOT_RUN_INPUT_UNAVAILABLE', 'INCOMPLETE_FAILURE'))})
    return F


def heavy_worst_case():
    """Both tasks: every primary contrast a fragile, extraction-run-dependent increment; size fails; both batch families differ."""
    label = {'state': 'A2LABEL_SCORED', 'families': {
        'news': {'reports': [{'arm': 'L_count', 'reference': 'M', 'decision': NULL, 'mean_difference': 0.05},
                             {'arm': 'L_chen', 'reference': 'M', 'decision': NULL, 'mean_difference': -0.2}]},
        'notice': {'reports': [{'arm': a, 'reference': 'M_notice', 'decision': NULL, 'mean_difference': 0.0}
                               for a in ('L14', 'L_Laz', 'L_chen_notice')]}}}
    news_rows = [row('L_count', 'M', IMP, -1.23, [-2.4, 0.1], [-2.501, 0.031], -0.71, 0.03, 0.02, hln=NULL, hac=NULL),
                 row('L_chen', 'M', IMP, -1.31, [-2.5, 0.2], [-2.611, 0.041], -0.75, 0.03, 0.02, hln=NULL, hac=NULL)]
    notice_rows = [row(a, 'M_notice', IMP, -0.051, [-0.11, 0.01], [-0.121, 0.012], -0.012, 0.03, 0.01, hln=NULL, hac=NULL)
                   for a in ('L14', 'L_Laz', 'L_chen_notice')]
    ts_news = {a: (DET, 0.512, [0.11, 0.91], [0.05, 0.97], 0.02) for a in ('L_count', 'L_chen')}
    ts_notice = {a: (DET, 0.041, [0.01, 0.07], [0.005, 0.077], 0.02) for a in ('L14', 'L_Laz', 'L_chen_notice')}
    batch = batch_result(L1_DIFF_BOTH, PD_DIFF_BOTH)
    pcx_result = pcx(news_k=9, notice_k=8)
    combos_news = [combo('news', a, 'M', NULL, IMP, -0.6, (-1.8, 0.5), (-2.0, 0.7), 0.3) for a in ('L_count', 'L_chen')]
    combos_notice = [combo('notice', a, 'M_notice', NULL, IMP, -0.01, (-0.03, 0.01), (-0.04, 0.02), 0.3) for a in ('L14', 'L_Laz', 'L_chen_notice')]
    pc = pc_variant()
    tn = task('news', news_rows, three_seed={a: DET for a in ts_news}, three_seed_numbers=ts_news, label=label, batch=batch,
              combos=combos_news, pc=pc, pcx_result=pcx_result)
    to = task('notice', notice_rows, three_seed={a: DET for a in ts_notice}, three_seed_numbers=ts_notice, label=label,
              combos=combos_notice, pc=pc, pcx_result=pcx_result)
    return {'news': tn, 'notice': to}, {'news': news_rows, 'notice': notice_rows}, batch


def render_all():
    out = {}
    base = {'news': task('news', [dict(r) for r in NULL_NEWS]), 'notice': task('notice', [dict(r) for r in NULL_NOTICE])}
    base_rows = {'news': [dict(r) for r in NULL_NEWS], 'notice': [dict(r) for r in NULL_NOTICE]}
    for name, (source, description, rows, opts) in fixtures().items():
        batch = opts.get('batch')
        t = task(source, [dict(r) for r in rows], **opts)
        tasks, rows_by = dict(base), dict(base_rows)
        tasks[source], rows_by[source] = t, [dict(r) for r in rows]
        extras = {'lear': SLOTS['news']['lear'], 'batch_differences': a4.batch_differences('news', rows_by['news'], batch),
                  'batch_texts': a4.batch_texts(batch), 'batch': batch}
        r = a4.render(tasks, extras, rows_by)
        out[name] = {'task': source, 'description': description, 'scenario': t['scenario'], 'abstract_level': r['abstract']['level'],
                     'abstract_counts': r['abstract']['counts'], 'abstract': r['abstract']['text'], 'abstract_required': r['abstract_required'],
                     'section6': r['section6'][source], 'conclusion_core': r['conclusion_core']}
    tasks, rows_by, batch = heavy_worst_case()
    extras = {'lear': SLOTS['news']['lear'], 'batch_differences': a4.batch_differences('news', rows_by['news'], batch),
              'batch_texts': a4.batch_texts(batch), 'batch': batch}
    r = a4.render(tasks, extras, rows_by)
    out['abstract_fallback_L7'] = {'task': 'both', 'description': 'Heaviest combination: five fragile, extraction-run-dependent increments, size failure in both tasks and four differing batch contrasts.',
                                   'scenario': 'B', 'abstract_level': r['abstract']['level'], 'abstract_counts': r['abstract']['counts'],
                                   'abstract': r['abstract']['text'], 'abstract_required': r['abstract_required'],
                                   'section6': r['section6']['news'] + r['section6']['notice'], 'conclusion_core': r['conclusion_core']}
    return out


def write():
    rendered = render_all()
    (A4_ROOT / 'tests/edge_fixtures_a4.json').write_text(json.dumps(rendered, indent=1, ensure_ascii=False) + '\n')
    lines = ['# Edge-case fixtures for FILL3b (CONF-A4, section E)', '',
             'Synthetic inputs built from the real design constants: news 214 days (m = 2, family-adjusted 97.5%, comparison value '
             '3.8%, MDE 3.11%), notices 61 days (m = 3, 98.3%, 0.5%, MDE 0.124%); news P_content matched on 3 of 214 days (216 of '
             '15,408 keys), so its slots are not evaluable; notice P_content has no matched key by construction; the notice shift '
             'comparison has 38 supported days; batch families are computed, not run (budget or reproduction check) or deviate '
             '(execution failure) only; the planted-signal check has 40 planted replicates and 40 or, with the extension, 200 null '
             'replicates. Each fixture renders one task through the frozen A4 functions (`code/a4_postscore.py`: `build_task`, '
             '`render`); the other task is the baseline null reading (news +0.120% and -0.300%; notices +0.010%, -0.020% and +0.030%; '
             'all inferentially robust; the planted-signal check passes with 36 of 40 and 40 of 40, null 0 of 40 and 1 of 40). The '
             'activity-versus-numerical, LEAR and shift readings are fixed synthetic values (news M - N -0.524% [-1.102, 0.061]; '
             'LEAR - N -18.204% [-19.880, -16.511]; notices M_notice - N -0.0310% [-0.0612, -0.0011]).', '',
             'FILL3b must reproduce every sentence exactly, after LaTeX conversion and the arm-symbol mapping of section 6 (symbols '
             'only in section 6; abstract and conclusion use words). `{table_ref}` is filled by FILL3b. `tests/edge_fixtures_a4.json` '
             'holds the same texts and `tests/test_a4_units.py::test_edge_fixtures_render` checks them.', '']
    for i, (name, f) in enumerate(rendered.items(), 1):
        counts = '; '.join(f"{c['level']} {c['validator_words']}/{c['whitespace_words']}" for c in f['abstract_counts'])
        lines += [f'## {i}. {name.replace("_", " ")} ({f["task"]}, scenario {f["scenario"]})', '', f['description'], '',
                  f'**Abstract** (level {f["abstract_level"]}; validator/whitespace words by level: {counts})', '', f['abstract'], '',
                  '**Section 6 (fixture task, in order)**', ''] + [f'- {s}' for s in f['section6']] + [
                  '', '**Conclusion (core, in order)**', ''] + [f'- {s}' for s in f['conclusion_core']] + ['']
    (A4_ROOT / 'EDGE_FIXTURES_SPEC_A4.md').write_text('\n'.join(lines))
    return rendered


if __name__ == '__main__':
    if '--write' in sys.argv:
        r = write()
        print(json.dumps({k: (v['scenario'], v['abstract_level']) for k, v in r.items()}))
    else:
        print(json.dumps({k: (v['scenario'], v['abstract_level']) for k, v in render_all().items()}, indent=1))
