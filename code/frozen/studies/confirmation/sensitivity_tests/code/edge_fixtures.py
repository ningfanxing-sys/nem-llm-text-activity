"""Synthetic edge-case fixtures for FILL3a (ADDENDUM_A3 section E). No study data.

Each fixture builds A2-layout primary rows and auxiliary inputs, renders them with the frozen A3 functions and records
the expected abstract core, the §6 headline sentences of the fixture task and the conclusion core.

    python edge_fixtures.py --write   # writes ../EDGE_FIXTURES_SPEC.md and ../tests/edge_fixtures.json
"""
import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
A3_ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('a3_postscore_fixtures', A3_ROOT / 'code/a3_postscore.py')
a3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a3)
A2 = a3.A2
IMP, DET, NULL, NE = a3.IMP, a3.DET, a3.NULL, a3.NE


def row(arm, ref, cls, effect, one95, fam, mean_aud, holm_p, p_raw, seven=None, hln=None, hac=None):
    return {'arm': arm, 'reference': ref, 'decision': cls, 'effect_percent_reference_mae': effect,
            'interval95_one_day': one95, 'interval95_seven_day': seven or one95, 'interval_family_one_day': fam,
            'mean_difference': mean_aud, 'holm_p': holm_p, 'p_two_sided': p_raw,
            'hln_decision': hln or cls, 'hac7_decision': hac or cls}


def slot(arm, ref, mean, p, state='COMPUTED_SECONDARY', **extra):
    return {'arm': arm, 'reference': ref, 'state': state, 'daily_mean_difference': mean, 'p_two_sided': p, **extra}


def combo(source, arm, ref, cls, primary_cls, effect=-1.0, one95=(-2.0, -0.2), fam=(-2.3, 0.1), holm_p=0.01):
    r = {'arm': arm, 'reference': ref, 'decision': cls, 'effect_percent_reference_mae': effect, 'holm_p': holm_p,
         'bootstrap': {'1': {'interval95_percent': list(one95), 'interval_family_adjusted_percent': list(fam)},
                       '7': {'interval95_percent': list(one95)}}}
    r['clause_id'], r['sentence'] = A2.combination_clause(source, r, primary_cls)
    return r


NULL_NEWS = [row('L_count', 'M', NULL, 0.12, [-1.9, 2.1], [-2.2, 2.4], 0.07, 0.8, 0.4),
             row('L_chen', 'M', NULL, -0.3, [-2.2, 1.7], [-2.5, 2.0], -0.17, 0.8, 0.6)]
NULL_NOTICE = [row('L14', 'M_notice', NULL, 0.01, [-0.06, 0.08], [-0.07, 0.09], 0.002, 0.9, 0.7),
               row('L_Laz', 'M_notice', NULL, -0.02, [-0.09, 0.05], [-0.1, 0.06], -0.005, 0.9, 0.5),
               row('L_chen_notice', 'M_notice', NULL, 0.03, [-0.05, 0.1], [-0.06, 0.11], 0.007, 0.9, 0.3)]
PC_PASS = {'readings': {'N2': {'PIPELINE_SENSITIVE_AT_2xMDE': True, 'PIPELINE_ATTENUATES': False, 'SIZE_INFLATED': False},
                        'notice': {'PIPELINE_SENSITIVE_AT_2xMDE': True, 'PIPELINE_ATTENUATES': False, 'SIZE_INFLATED': False}},
           'summary': [{'task': 'news', 'tier': 'N2', 'mult': 2.0, 'replicates': 40, 'detected': 36, 'detection_rate': 0.9,
                        'detection_cp95': [0.763, 0.972], 'delta_pct_median': -6.512, 'uptake_median': 0.611},
                       {'task': 'news', 'tier': 'N2', 'mult': 0.0, 'replicates': 40, 'detected': 0, 'detection_rate': 0.0,
                        'detection_cp95': [0.0, 0.088], 'delta_pct_median': 0.01, 'uptake_median': None},
                       {'task': 'notice', 'tier': 'notice', 'mult': 2.0, 'replicates': 40, 'detected': 40, 'detection_rate': 1.0,
                        'detection_cp95': [0.912, 1.0], 'delta_pct_median': -0.231, 'uptake_median': 0.902},
                       {'task': 'notice', 'tier': 'notice', 'mult': 0.0, 'replicates': 40, 'detected': 1, 'detection_rate': 0.025,
                        'detection_cp95': [0.0006, 0.132], 'delta_pct_median': 0.0, 'uptake_median': None}]}


def pc_variant(news=None, notice=None):
    pc = json.loads(json.dumps(PC_PASS))
    for source, change in (('news', news), ('notice', notice)):
        if not change:
            continue
        tier = a3.PC_TIER[source]
        rows = {r['mult']: r for r in pc['summary'] if r['task'] == source}
        if 'sens' in change:
            rows[2.0].update(detected=24, detection_rate=0.6, detection_cp95=[0.433, 0.751], delta_pct_median=-2.104, uptake_median=0.21)
            pc['readings'][tier].pop('PIPELINE_SENSITIVE_AT_2xMDE')
            pc['readings'][tier]['PIPELINE_SENSITIVITY_LIMITED'] = True
        if 'size' in change:
            rows[0.0].update(detected=5, detection_rate=0.125, detection_cp95=[0.0419, 0.268])
            pc['readings'][tier]['SIZE_INFLATED'] = True
    return pc


def task(source, rows, *, secondary=(), cheap=None, combination=None, files=None, batch=None, label=None, pc=PC_PASS,
         incomplete=None, matched=None):
    matched = matched or {'matched_share_percent': 41.2}
    robust = {}
    for r in rows:
        three = r.pop('three_seed', r['decision'])
        robust[(r['arm'], r['reference'])] = a3.robustness_a3(r['decision'], r['interval95_one_day'], r['interval95_seven_day'],
                                                               r['hln_decision'], r['hac7_decision'], three)
    cheap = cheap or {}
    attributions = [a3.attribution_a3(source, r['arm'], r['decision'], list(secondary), cheap, matched) for r in rows]
    states = a3.sensitivity_states(source, rows, files or {}, batch, label)
    tvn = None
    if source == 'news':
        bounds = {('L_count', 'N'): 2.871, ('L_chen', 'N'): 3.105, ('M', 'N'): 1.042}
        tvn = {'sentence': a3.g1_sentence(bounds)}
    return a3.task_texts(source, rows, attributions, combination, robust, states, a3.pc_state(source, pc), batch,
                         text_vs_no_text=tvn, incomplete_reason=incomplete)


def fixtures():
    F = {}
    # 1 reliable deterioration (news), scenario A
    rows = [row('L_count', 'M', NULL, 0.4, [-1.5, 2.3], [-1.8, 2.6], 0.23, 0.6, 0.6),
            row('L_chen', 'M', DET, 3.1, [1.2, 5.0], [0.9, 5.3], 1.78, 0.002, 0.001)]
    F['reliable_deterioration'] = ('news', 'News: L_count no reliable increment; L_chen reliably worse (robust).', rows, {})
    # 2 mixed family (news), scenario B
    rows = [row('L_count', 'M', IMP, -4.6, [-7.0, -2.1], [-7.4, -1.7], -2.64, 0.002, 0.001),
            row('L_chen', 'M', DET, 2.9, [0.9, 4.8], [0.6, 5.1], 1.66, 0.004, 0.004)]
    F['mixed_family'] = ('news', 'News: L_count reliable increment (no content control); L_chen reliably worse.', rows,
                         {'cheap': {('L_count', 'E_raw'): {'state': 'COMPUTED', 'mean_difference': -1.1, 'p_two_sided': 0.01},
                                    ('L_count', 'W2_D'): {'state': 'NOT_EVALUABLE_WHOLE_STAGE_UNAVAILABLE'}},
                          'combination': {'state': 'COMPUTED', 'family': {'reports': [combo('news', 'L_count', 'M', IMP, IMP, -2.0, (-3.1, -0.9), (-3.4, -0.6), 0.004)]}}})
    # 3 undefined arm (notices), scenario A
    rows = [NULL_NOTICE[0], row('L_Laz', 'M_notice', NE, None, None, None, None, None, None), NULL_NOTICE[2]]
    F['undefined_arm'] = ('notice', 'Notices: L_Laz not evaluable (input gate); the other two no reliable increment.', rows, {})
    # 4 incomplete confirmation (news)
    F['incomplete_confirmation'] = ('news', 'News: primary fits did not finish within the 24-hour budget.', [], {'incomplete': a3.SENTENCES['A3INC_BUDGET']})
    # 5 seed-fragile increment (notices)
    r = row('L14', 'M_notice', IMP, -0.31, [-0.48, -0.15], [-0.52, -0.11], -0.0755, 0.003, 0.001)
    r['three_seed'] = NULL
    F['seed_fragile_increment'] = ('notice', 'Notices: L14 reliable increment, three-seed mean no reliable increment.',
                                   [r, NULL_NOTICE[1], NULL_NOTICE[2]],
                                   {'cheap': {('L14', 'R'): {'state': 'COMPUTED', 'mean_difference': -0.02, 'p_two_sided': 0.3},
                                              ('L14', 'T'): {'state': 'COMPUTED', 'mean_difference': 0.05, 'p_two_sided': 0.01}},
                                    'combination': {'state': 'COMPUTED', 'family': {'reports': [combo('notice', 'L14', 'M_notice', NULL, IMP, -0.05, (-0.2, 0.1), (-0.25, 0.15), 0.4)]}}})
    # 6 single-extraction increment (news): label replacement turns the increment into no reliable increment
    rows = [NULL_NEWS[0], row('L_chen', 'M', IMP, -4.2, [-6.6, -1.9], [-6.9, -1.5], -2.41, 0.001, 0.0005)]
    label = {'state': 'A2LABEL_SCORED', 'families': {'news': {'reports': [
        {'arm': 'L_count', 'reference': 'M', 'decision': NULL, 'mean_difference': 0.05},
        {'arm': 'L_chen', 'reference': 'M', 'decision': NULL, 'mean_difference': -0.8}]}}}
    sec = [slot('L_chen', 'P_content', -0.5, 0.01), slot('L_chen', 'P_shift', -0.6, 0.02),
           slot('L_chen', 'E_raw', -0.4, 0.03), slot('L_chen', 'W2_D', -0.2, 0.2)]
    F['single_extraction_increment'] = ('news', 'News: L_chen reliable increment, content-specific but not LLM-specific; re-extracted labels give no reliable increment.',
                                        rows, {'label': label, 'secondary': sec,
                                               'cheap': {('L_chen', 'E_raw'): sec[2], ('L_chen', 'W2_D'): sec[3]},
                                               'combination': {'state': 'COMPUTED', 'family': {'reports': [combo('news', 'L_chen', 'M', IMP, IMP, -1.9, (-3.0, -0.7), (-3.3, -0.4), 0.006)]}}})
    # 7a positive-control sensitivity failure, scenario A (news)
    F['pc_failure_scenario_A'] = ('news', 'News: both null; planted signal detected in 24 of 40 replicates (sensitivity fails).',
                                  [dict(r) for r in NULL_NEWS], {'pc': pc_variant(news={'sens'})})
    # 7b positive-control size failure, scenario B (notices)
    rows = [row('L14', 'M_notice', IMP, -0.62, [-0.8, -0.44], [-0.84, -0.4], -0.151, 0.0005, 0.0001),
            NULL_NOTICE[1], NULL_NOTICE[2]]
    F['pc_failure_scenario_B'] = ('notice', 'Notices: L14 reliable increment; the permuted null column is over-rejected (size fails).',
                                  rows, {'pc': pc_variant(notice={'size'}),
                                         'cheap': {('L14', 'R'): {'state': 'COMPUTED', 'mean_difference': -0.08, 'p_two_sided': 0.004},
                                                   ('L14', 'T'): {'state': 'COMPUTED', 'mean_difference': -0.06, 'p_two_sided': 0.02}},
                                         'combination': {'state': 'COMPUTED', 'family': {'reports': [combo('notice', 'L14', 'M_notice', IMP, IMP, -0.3, (-0.45, -0.15), (-0.5, -0.1), 0.001)]}}})
    # 8 PD family not run (news), L1 family differs for L_chen
    batch = {'families': {'L1': {'state': 'COMPUTED', 'reports': [
        {'arm': 'L_count_L1', 'reference': 'M_L1', 'mean_difference': 0.1, 'holm_p': 0.7, 'effect_percent_reference_mae': 0.2,
         'bootstrap': {'1': {'interval95_percent': [-1.6, 2.0], 'interval_family_adjusted_percent': [-1.9, 2.3]}}},
        {'arm': 'L_chen_L1', 'reference': 'M_L1', 'mean_difference': -1.9, 'holm_p': 0.02, 'effect_percent_reference_mae': -3.4,
         'bootstrap': {'1': {'interval95_percent': [-5.9, -0.9], 'interval_family_adjusted_percent': [-6.3, -0.5]}}}]},
        'PD': {'state': 'NOT_RUN_BUDGET', 'reason': 'budget'}}}
    F['pd_family_not_run'] = ('news', 'News: both null; the L1 family finds an increment for L_chen; the PD family was not run (budget).',
                              [dict(r) for r in NULL_NEWS], {'batch': batch})
    # 9 Holm rejection whose family-adjusted interval covers zero (news)
    rows = [row('L_count', 'M', IMP, -3.9, [-6.0, -1.8], [-6.3, -1.5], -2.24, 0.002, 0.001),
            row('L_chen', 'M', IMP, -2.0, [-3.9, -0.1], [-4.2, 0.2], -1.15, 0.03, 0.03)]
    F['holm_rejection_interval_covers_zero'] = ('news', 'News: both Holm rejections; L_chen family-adjusted interval [-4.2, 0.2] includes zero.', rows,
                                                {'cheap': {('L_count', 'E_raw'): {'state': 'COMPUTED', 'mean_difference': -0.5, 'p_two_sided': 0.2},
                                                           ('L_count', 'W2_D'): {'state': 'COMPUTED', 'mean_difference': -0.9, 'p_two_sided': 0.03}},
                                                 'secondary': [slot('L_chen', 'P_content', -0.3, 0.2), slot('L_chen', 'P_shift', -0.6, 0.01)]})
    # 10a SESOI classes, news: beyond and straddling with the point above
    rows = [row('L_count', 'M', IMP, -6.8, [-9.2, -4.6], [-9.6, -4.2], -3.9, 0.0004, 0.0002),
            row('L_chen', 'M', IMP, -4.5, [-7.9, -1.2], [-8.3, -0.8], -2.58, 0.004, 0.004)]
    F['sesoi_beyond_and_straddle_above'] = ('news', 'News SESOI classes: L_count wholly beyond 3.8%; L_chen point above 3.8% with a straddling interval.', rows,
                                            {'secondary': [slot('L_chen', 'P_content', -1.0, 0.01), slot('L_chen', 'P_shift', -1.1, 0.01),
                                                           slot('L_chen', 'E_raw', -0.9, 0.02), slot('L_chen', 'W2_D', -0.8, 0.03)],
                                             'cheap': {('L_chen', 'E_raw'): slot('L_chen', 'E_raw', -0.9, 0.02), ('L_chen', 'W2_D'): slot('L_chen', 'W2_D', -0.8, 0.03),
                                                       ('L_count', 'E_raw'): {'state': 'COMPUTED', 'mean_difference': -0.4, 'p_two_sided': 0.04},
                                                       ('L_count', 'W2_D'): {'state': 'COMPUTED', 'mean_difference': -0.2, 'p_two_sided': 0.3}}})
    # 10b SESOI classes, notices: wholly below and straddling with the point below
    rows = [row('L14', 'M_notice', IMP, -0.21, [-0.33, -0.09], [-0.36, -0.06], -0.051, 0.001, 0.0004),
            NULL_NOTICE[1],
            row('L_chen_notice', 'M_notice', IMP, -0.41, [-0.79, -0.06], [-0.86, -0.02], -0.1, 0.03, 0.03)]
    F['sesoi_below_and_straddle_below'] = ('notice', 'Notice SESOI classes: L14 wholly below 0.5%; L_chen_notice point below 0.5% with a straddling interval.', rows,
                                           {'secondary': [{'arm': 'L_chen_notice', 'reference': 'P_content', 'state': 'NO_VALID_PERMUTATION'},
                                                          slot('L_chen_notice', 'P_shift', -0.05, 0.02)],
                                            'cheap': {('L14', 'R'): {'state': 'COMPUTED', 'mean_difference': -0.03, 'p_two_sided': 0.04},
                                                      ('L14', 'T'): {'state': 'COMPUTED', 'mean_difference': -0.01, 'p_two_sided': 0.6},
                                                      ('L_chen_notice', 'R'): {'state': 'COMPUTED', 'mean_difference': -0.02, 'p_two_sided': 0.2},
                                                      ('L_chen_notice', 'T'): {'state': 'COMPUTED', 'mean_difference': 0.01, 'p_two_sided': 0.7}}})
    return F


def render_all():
    out = {}
    base_news = task('news', [dict(r) for r in NULL_NEWS])
    base_notice = task('notice', [dict(r) for r in NULL_NOTICE])
    for name, (source, description, rows, opts) in fixtures().items():
        texts = task(source, [dict(r) for r in rows], **opts)
        tasks = {'news': base_news, 'notice': base_notice}
        tasks[source] = texts
        out[name] = {'task': source, 'description': description, 'scenario': texts['scenario'],
                     'abstract_core': a3.abstract_core(tasks), 'section6': texts['section6'],
                     'section7_2': texts['section7_2'], 'conclusion_core': a3.conclusion_core(tasks)}
    return out


def write():
    rendered = render_all()
    (A3_ROOT / 'tests/edge_fixtures.json').write_text(json.dumps(rendered, indent=1, ensure_ascii=False) + '\n')
    lines = ['# Edge-case fixtures for FILL3a (CONF-A3, section E)', '',
             'Synthetic inputs only. Each fixture renders one task through the frozen A3 functions '
             '(`code/a3_postscore.py`: `task_texts`, `abstract_core`, `conclusion_core`); the other task is the baseline '
             'null reading below. FILL3a must reproduce every sentence exactly, after LaTeX conversion and the arm-symbol '
             'mapping of §6 (arm symbols appear only in §6 and §7.2; the abstract and conclusion use words). '
             '`tests/edge_fixtures.json` holds the same texts and `tests/test_a3_units.py::test_edge_fixtures_render` '
             'checks them. Inputs are built in `code/edge_fixtures.py` (rows in the A2 `primary` layout).', '',
             'Baseline other task: news L_count 0.12% and L_chen -0.30% (both no reliable increment, robust); notices L14 '
             '0.01%, L_Laz -0.02%, L_chen_notice 0.03% (all no reliable increment, robust); positive control passes '
             '(news 36/40, notices 40/40; null 0/40 and 1/40).', '',
             'Placement: the abstract is the problem and design sentences (unchanged) followed by `abstract_core`; the '
             'conclusion is `conclusion_core` followed by the existing historical sentences; §6 lists the headline and '
             'qualifier sentences of the fixture task in order; §7.2 lists the robustness-layer sentences. `{table_ref}` '
             'is filled by FILL3a with the LaTeX reference.', '']
    for i, (name, f) in enumerate(rendered.items(), 1):
        lines += [f'## {i}. {name.replace("_", " ")} ({f["task"]}, scenario {f["scenario"]})', '', f['description'], '',
                  '**Abstract (core, in order)**', ''] + [f'- {s}' for s in f['abstract_core']] + [
                  '', '**§6 (fixture task, in order)**', ''] + [f'- {s}' for s in f['section6']] + [
                  '', '**§7.2**', ''] + [f'- {s}' for s in f['section7_2']] + [
                  '', '**Conclusion (core, in order)**', ''] + [f'- {s}' for s in f['conclusion_core']] + ['']
    (A3_ROOT / 'EDGE_FIXTURES_SPEC.md').write_text('\n'.join(lines))
    return rendered


if __name__ == '__main__':
    if '--write' in sys.argv:
        r = write()
        print(json.dumps({k: v['scenario'] for k, v in r.items()}))
    else:
        print(json.dumps(render_all(), indent=1, ensure_ascii=False)[:3000])
