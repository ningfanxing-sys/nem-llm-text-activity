"""CONF-A2 post-score module (ADDENDUM_A2.md, frozen in ADDENDUM_A2_FREEZE.json before this code was written).

Runs after the frozen `CONFX2/cli.py score` has written `scored/SCORE_RECEIPT.json` (FROZEN_SCORE_COMPLETE) and
before the manuscript fill (FILL3). It never refits and never changes a frozen reading. It reads only:
  * `<state>/SEAL.json` and the sealed prediction and truth-panel files it names (SHA-256 checked);
  * `<state>/scored/SCORE_RECEIPT.json` and the score files it lists (SHA-256 checked);
  * the frozen `CONF/code/scoring.py` (SHA-256 checked against `CONF/FREEZE.json`).
It writes only to its own output folder (default `<state>/a2_scored`; `scored/` is refused).

Sections implemented (ADDENDUM_A2): S (combination check), R (robustness label), C (attribution labels and the
P_content unmatched share; notice cheap-text contrasts), B (task SESOI and family-adjusted bounds), U (strictly
unexposed days), W1 (p display). Sentence forms are copied verbatim from Appendix A (`SENTENCES`).

    python a2_postscore.py --state <host_state> [--out <folder>]
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np

A2_ROOT = Path(__file__).resolve().parents[1]
CONF_ROOT = A2_ROOT.parent
ADDENDUM_FREEZE = A2_ROOT / 'ADDENDUM_A2_FREEZE.json'

ALPHA = 0.05
SEED = 20260919
EXTRA_SEEDS = (20260920, 20260921)
KEYS = ['origin', 'target_time', 'region', 'horizon']
CLASSES = ('CONDITIONAL_IMPROVEMENT', 'CONDITIONAL_DETERIORATION', 'NO_RELIABLE_INCREMENT_DETECTED')
FAMILIES = {'news': (('L_count', 'M'), ('L_chen', 'M')),
            'notice': (('L14', 'M_notice'), ('L_Laz', 'M_notice'), ('L_chen_notice', 'M_notice'))}
REFERENCE = {'news': 'M', 'notice': 'M_notice'}
WINDOW = {'news': ('2026-03-01', '2026-09-30', 72), 'notice': ('2026-08-01', '2026-09-30', 8640)}
BENCHMARK = {'news': ('lear', 'LEAR'), 'notice': ('notice', 'NP')}       # (sealed source, arm)
SESOI = {'news': 3.8, 'notice': 0.5}
STRICT_UNEXPOSED = {'news': (('2026-05-19', '2026-06-30'), ('2026-09-24', '2026-09-30')),
                    'notice': (('2026-09-24', '2026-09-30'),)}
STRICT_UNEXPOSED_DAYS = {'news': 50, 'notice': 7}
CONTENT_ARM = {'news': 'L_chen', 'notice': 'L_chen_notice'}
CONTENT_CONTROLS = {'news': (('L_chen', 'P_content'), ('L_chen', 'P_shift')),
                    'notice': (('L_chen_notice', 'P_content'), ('L_chen_notice', 'P_shift'))}
CHEAP_COMPARATORS = {'news': (('L_chen', 'E_raw'), ('L_chen', 'W2_D')),
                     'notice': (('L_chen_notice', 'R'), ('L_chen_notice', 'T'))}
A2_NEW_CONTRASTS = {'notice': (('L_chen_notice', 'R'), ('L_chen_notice', 'T'))}
PCONTENT_SLOT = {'news': ('P_content', 'M'), 'notice': ('P_content', 'M_notice')}

# ---------------------------------------------------------------- Appendix A sentence forms (verbatim)
SENTENCES = {
    'H0': 'These readings are relative to the registered learner and information set: the news reference uses no operator forecasts and the notice reference uses no five-minute pre-dispatch prices.',
    'H1': '{arm} showed no reliable increment over the {activity} reference ({effect}% of the reference error, family-adjusted {level}% interval [{lo}, {hi}]%, Holm-adjusted {p}); {robustness}.',
    'H2': '{arm} improved on the {activity} reference by {abs_effect}% of the reference error (family-adjusted {level}% interval [{lo}, {hi}]%, Holm-adjusted {p}); {robustness}; {attribution}; {benchmark}.',
    'H3': '{arm} was reliably worse than the {activity} reference by {effect}% of the reference error (family-adjusted {level}% interval [{lo}, {hi}]%, Holm-adjusted {p}); {robustness}.',
    'H4': 'The registered comparison of {arm} with the {activity} reference could not be evaluated because {reason}; no confirmation conclusion is drawn.',
    'H5': 'For each structured representation, improvements larger than {X}% of the reference error were excluded at the family-adjusted one-sided {tail}% level, which is {below_or_above} the {S}% smallest effect size of interest for this task.',
    'R1': 'this reading was robust: the one-day and seven-day bootstrap intervals, the small-sample HLN calibration, the HAC7 long-run variance and the three-seed mean all agreed with it in direction and decision',
    'R2': 'this reading was fragile: {dissent_list} did not agree with it in direction or decision',
    'R3': 'its robustness could not be fully checked because {unavailable_list} {was_were} not available ({reason})',
    'R4': 'Every primary reading of the {task} family was robust to the registered checks.',
    'C1': 'it is an increment over the {activity} reference; no registered content control exists for this representation, so it is not attributed to the content',
    'C2': 'it is an increment over the {activity} reference; the registered content controls did not both favour the original content ({failed_list}), so it is not attributed to the content',
    'C3': 'it is an increment over the {activity} reference; the registered content controls could not be evaluated ({reason}), so it is not attributed to the content',
    'C4': 'it is content-specific: the original content also outperformed activity-matched reassigned content (on the {matched_share}% of keys with a matched donor) and content shifted by 28 days; it was not shown to be LLM-specific because {llm_reason}',
    'C5': 'it is LLM-specific: the original content also outperformed activity-matched reassigned content (on the {matched_share}% of keys with a matched donor) and content shifted by 28 days, and the LLM-structured representation outperformed {comparator_list} built from the same {documents}',
    'C6': 'The activity-matched reassignment control found a matched donor for {matched_share}% of the {total_keys} keys; {unmatched_days} of {n_days} days had no matched key.',
    'D1': 'Improvements larger than {X}% of the reference error were excluded at the family-adjusted one-sided {tail}% level, conditional on these fitted predictions; this bound is below the {S}% smallest effect size of interest for this task, so improvements of that size are excluded by this window. This is not an equivalence test and does not show a zero effect.',
    'D2': 'Improvements larger than {X}% of the reference error were excluded at the family-adjusted one-sided {tail}% level, conditional on these fitted predictions; this bound does not exclude improvements as large as the {S}% smallest effect size of interest for this task, so the window is not informative about effects of that size.',
    'D3': 'The increment is statistically reliable under the registered rule but smaller than the {S}% smallest effect size of interest for this task.',
    'D4': 'The increment is statistically reliable and at least as large as the {S}% smallest effect size of interest for this task.',
    'D5': 'The transferred 3.8% value is not informative for the notice task, whose expected bounds are an order of magnitude smaller; the notice reading is compared with 0.5%.',
    'D6': 'The smallest effect size of interest is an interpretation aid and never enters a decision. For news it is 3.8% of the reference error, the smallest text-attributed error reduction with a significance test in the cited electricity forecasting work; for notices it is 0.5%, the practical-effect margin that this line of work fixed for the same five-to-thirty-minute notice task before any confirmation data were read.',
    'B1': 'family-adjusted {level}% interval',
    'B2': 'per-contrast 95% interval',
    'B3': 'Headline intervals are family-adjusted: {level}% two-sided, that is 1 − 0.05/{m} for the {m} registered comparisons of the {task} family; tables also give the per-contrast 95% intervals.',
    'S1': 'the increment persisted when each forecast was averaged with {benchmark} ({effect}% of the combined reference error, family-adjusted {level}% interval [{lo}, {hi}]%, Holm-adjusted {p})',
    'S2': 'when each forecast was averaged with {benchmark}, no reliable increment was detected ({effect}%, family-adjusted {level}% interval [{lo}, {hi}]%, Holm-adjusted {p}), so the increment is stated relative to the registered learner and information set only',
    'S3': 'when each forecast was averaged with {benchmark}, the combination containing {arm} was reliably worse ({effect}%, Holm-adjusted {p})',
    'S4': 'In the secondary combination check with {benchmark}, {arm} showed a reliable favourable difference ({effect}%, Holm-adjusted {p}); this does not change the primary reading.',
    'S5': 'The secondary combination check with {benchmark} also detected no reliable increment for {arm} ({effect}%, Holm-adjusted {p}).',
    'S6': 'In the secondary combination check with {benchmark}, the combination containing {arm} was reliably worse ({effect}%, Holm-adjusted {p}); this does not change the primary reading.',
    'S7': 'The combination check with {benchmark} was not available ({reason}).',
    'U1': 'On the {n} days whose prices had no recorded or unknown prior use ({ranges}), {arm} differed from the {activity} reference by {effect}% (one-day 95% interval [{lo}, {hi}]%, DM {p}); this small descriptive subset does not change any reading.',
    'U2': 'days with no recorded analysis (includes the period of unknown use)',
    'U3': 'days with no recorded or unknown prior use',
    'L1': 'With independently re-extracted test-period labels and the same fitted models, the reading was reproduced ({effect}%, one-day 95% interval [{lo}, {hi}]%).',
    'L2': 'With independently re-extracted test-period labels and the same fitted models, the reading changed from {reading_original} to {reading_replacement} ({effect}%, one-day 95% interval [{lo}, {hi}]%).',
    'L3': 'The label-replacement check was not run ({reason}).',
    'P1': 'A planted-signal check on pre-confirmation windows of the same size added to the activity reference a column equal to the realised target on a random share of {units} and missing elsewhere. A real content signal of the same total size would be noisier than this oracle column, so the detection rate is an upper bound on the sensitivity of the registered test. At twice the minimum detectable effect the column was detected in {k} of {R} replicates ({task}; Clopper–Pearson 95% interval [{lo}, {hi}]), and the permuted null column in {k0} of {R0}.',
    'P2': 'a planted oracle signal of twice the minimum detectable effect was detected in {k}/{R} replicates, an upper bound on sensitivity',
}
ACTIVITY = {'news': 'article activity', 'notice': 'notice activity'}
TASK_NAME = {'news': 'news', 'notice': 'notice'}
LEVEL_TEXT = {'news': '97.5', 'notice': '98.3'}
TAIL_TEXT = {'news': '1.25', 'notice': '0.83'}
BENCHMARK_NAME = {'news': 'the price-only LEAR benchmark', 'notice': 'the P5MIN-augmented reference NP'}
COMPARATOR_NAME = {'E_raw': 'the raw-text embedding', 'W2_D': 'the word-frequency representation',
                   'R': 'the rule parser', 'T': 'the word-frequency representation'}
DOCUMENTS = {'news': 'articles', 'notice': 'notices'}
CHECK_NAME = {'one_day': 'the one-day bootstrap interval', 'hln': 'the small-sample HLN calibration',
              'hac7': 'the HAC7 long-run variance', 'seven_day': 'the seven-day block bootstrap interval',
              'three_seed': 'the three-seed mean'}
CHECK_ORDER = ('one_day', 'hln', 'hac7', 'seven_day', 'three_seed')
CONTROL_NAME = {'P_content': 'the activity-matched reassignment control', 'P_shift': 'the 28-day time-shift control'}
STATE_PHRASE = {'NO_VALID_PERMUTATION': 'no activity-matched donor content was available',
                'NOT_EVALUABLE_WHOLE_STAGE_UNAVAILABLE': 'the control was not run',
                'NOT_EVALUABLE_SHIFT_SUPPORT_GAP': 'no notices were saved for the shifted dates',
                'NOT_EVALUABLE_INSUFFICIENT_REGISTERED_BLOCK_SUPPORT': 'too few days had matched keys',
                'NOT_FOUND': 'the control was not reported', 'UNDEFINED': 'its test statistic was undefined'}
UNAVAILABLE_PHRASE = {'one_day': 'the one-day interval was undefined', 'seven_day': 'the seven-day interval was undefined',
                      'hln': 'the HLN statistic was undefined', 'hac7': 'the HAC7 variance was not positive or the days were not consecutive',
                      'three_seed': 'the extra-seed predictions were not available'}
CLASS_WORDS = {'CONDITIONAL_IMPROVEMENT': 'a reliable increment', 'CONDITIONAL_DETERIORATION': 'a reliable deterioration',
               'NO_RELIABLE_INCREMENT_DETECTED': 'no reliable increment', 'NOT_EVALUABLE': 'not evaluable'}


# ---------------------------------------------------------------- small utilities
def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def finite(x):
    return isinstance(x, (int, float, np.floating)) and not isinstance(x, bool) and math.isfinite(float(x))


def join_list(items):
    items = list(items)
    if not items:
        return ''
    if len(items) == 1:
        return items[0]
    return ', '.join(items[:-1]) + ' and ' + items[-1]


def json_safe(value):
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


def day_list(runs):
    out = []
    for first, last in runs:
        d, end = date.fromisoformat(first), date.fromisoformat(last)
        while d <= end:
            out.append(d.isoformat())
            d += timedelta(days=1)
    return out


# ---------------------------------------------------------------- display (rule W1 and the v1 percentage rule)
def display_p(p, threshold=ALPHA):
    """ADDENDUM_A2 rule W1. Returns the text including 'p' (e.g. 'p = 0.012', 'p < 0.001')."""
    if not finite(p):
        return 'p undefined'
    p = float(p)
    if p < 0.001:
        return 'p < 0.001'
    if p >= 0.995:
        return 'p > 0.99'
    text = f'{p:.3f}'
    if threshold is not None and (float(text) < threshold) != (p < threshold):
        text = f'{p:.4f}'
    return 'p = ' + text


def percent_decimals(width):
    if not finite(width) or width <= 0:
        return 3
    return int(min(6, max(3, 1 - math.floor(math.log10(width)))))


def fmt_effect(value, d):
    if not finite(value):
        return 'undefined'
    text = f'{round(float(value), d):.{d}f}'
    return text[1:] if text.startswith('-') and float(text) == 0 else text


def fmt_interval(interval, d):
    if interval is None:
        return ('undefined', 'undefined')
    lo, hi = interval
    scale = 10 ** d
    texts = (f'{math.floor(lo * scale) / scale:.{d}f}', f'{math.ceil(hi * scale) / scale:.{d}f}')
    return tuple(x[1:] if x.startswith('-') and float(x) == 0 else x for x in texts)


def fmt_bound(x, d):
    if not finite(x):
        return 'undefined'
    scale = 10 ** d
    return f'{math.ceil(float(x) * scale - 1e-12) / scale:.{d}f}'


# ---------------------------------------------------------------- frozen statistical helpers
def load_frozen_scoring(conf_root=CONF_ROOT):
    """Import CONF/code/scoring.py only after its SHA-256 equals the CONF design freeze."""
    conf_root = Path(conf_root)
    frozen = json.loads((conf_root / 'FREEZE.json').read_text())['frozen_files']
    for name in ('code/scoring.py', 'code/guard.py'):
        if sha256(conf_root / name) != frozen[name]['sha256']:
            raise PermissionError('Frozen CONF module drift: ' + name)
    code_dir = str(conf_root / 'code')
    added = code_dir not in sys.path
    if added:
        sys.path.insert(0, code_dir)
    try:
        spec = importlib.util.spec_from_file_location('conf_a2_frozen_scoring', conf_root / 'code/scoring.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if added:
            sys.path.remove(code_dir)
    return module


def hln_p(statistic, n_days):
    if statistic is None or not finite(statistic) or not isinstance(n_days, int) or n_days < 2:
        return None
    from scipy.stats import t
    return float(min(1.0, 2.0 * t.sf(abs(float(statistic)), df=n_days - 1)))


def decision_class(mean, p):
    """Same as the frozen class rule (two-sided p < .05, sign of the mean daily difference)."""
    if p is None or mean is None or not finite(p) or not finite(mean):
        return 'NOT_EVALUABLE'
    if p < ALPHA:
        return 'CONDITIONAL_IMPROVEMENT' if mean < 0 else 'CONDITIONAL_DETERIORATION'
    return 'NO_RELIABLE_INCREMENT_DETECTED'


def family_quantiles(draws, m):
    draws = np.asarray(draws, dtype='float64')
    good = draws[np.isfinite(draws)]
    if not len(good):
        return None
    q = ALPHA / (2 * m)
    return [float(v) for v in np.quantile(good, [q, 1 - q], method='linear')]


def complete_picks(sc, n):
    return {block: sc.block_picks(n, block) for block in (1, 7)}


def subset_picks(sc, day_keys):
    picks = {1: sc.block_picks(len(day_keys), 1, day_keys)}
    try:
        picks[7] = sc.block_picks(len(day_keys), 7, day_keys)
    except ValueError:
        picks[7] = None
    return picks


def contrast_stats(sc, a, b, picks, m_family, gaps=False):
    """One paired contrast with the frozen helpers: DM normal, HAC7, HLN p, 1/7-day bootstrap, family quantiles."""
    a = np.asarray(a, dtype='float64'); b = np.asarray(b, dtype='float64')
    dm = sc.dm_daily(a - b)
    if gaps:
        hac = {'state': 'UNDEFINED_SECONDARY_DATE_GAPS', 'statistic': None, 'p_two_sided': None}
    else:
        hac = sc.dm_daily(a - b, 7)
    out = {'n_days': len(a), 'mean_difference': dm['mean_difference'], 'statistic': dm['statistic'],
           'p_two_sided': dm['p_two_sided'], 'p_improvement': dm['p_improvement'],
           'p_deterioration': dm['p_deterioration'], 'dm_state': dm['state'],
           'hac7_p_two_sided': hac.get('p_two_sided'), 'hac7_state': hac.get('state'),
           'hln_p_two_sided': hln_p(dm['statistic'], len(a)), 'reference_mae': float(b.mean()),
           'arm_mae': float(a.mean()), 'bootstrap': {}}
    for block in (1, 7):
        if picks.get(block) is None:
            out['bootstrap'][str(block)] = {'interval95_percent': None, 'state': 'UNDEFINED_NO_COMPLETE_SEVEN_CALENDAR_DAY_BLOCK'}
            continue
        boot = sc.paired_percent_interval(a, b, picks[block])
        draws = boot.pop('draws')
        degenerate = bool(len(np.unique(np.asarray(picks[block])[:, 0])) == 1 and block == 7)
        boot['interval_family_adjusted_percent'] = family_quantiles(draws, m_family)
        boot['family_m'] = m_family
        boot['tail_draws_expected'] = ALPHA / (2 * m_family) * sc.BOOTSTRAP_DRAWS
        if degenerate:
            boot['state'] = 'NOT_INFORMATIVE_ONE_ADMISSIBLE_SEVEN_DAY_BLOCK'
        out['bootstrap'][str(block)] = boot
    out['effect_percent_reference_mae'] = out['bootstrap']['1'].get('effect_percent_reference_mae')
    return out


def family_inference(sc, losses, pairs, days, m=None, subset=False):
    """Holm (normal), HLN-Holm and HAC7-Holm within a family; frozen picks; family-adjusted intervals."""
    m = m or len(pairs)
    if subset:
        parsed = [date.fromisoformat(d) for d in days]
        gaps = [(x.isoformat(), y.isoformat()) for x, y in zip(parsed, parsed[1:]) if (y - x).days != 1]
        picks = subset_picks(sc, days)
    else:
        gaps = []
        picks = complete_picks(sc, len(days))
    reports = []
    for arm, ref in pairs:
        if arm not in losses or ref not in losses:
            reports.append({'arm': arm, 'reference': ref, 'state': 'NOT_EVALUABLE_INPUT_UNAVAILABLE',
                            'p_two_sided': None, 'hln_p_two_sided': None, 'hac7_p_two_sided': None,
                            'mean_difference': None, 'bootstrap': {'1': {'interval95_percent': None},
                                                                    '7': {'interval95_percent': None}}})
            continue
        r = contrast_stats(sc, losses[arm], losses[ref], picks, m, gaps=bool(gaps))
        r.update(arm=arm, reference=ref, state='COMPUTED')
        reports.append(r)
    for key, out in (('p_two_sided', 'holm_p'), ('hln_p_two_sided', 'hln_holm_p'), ('hac7_p_two_sided', 'hac7_holm_p')):
        adjusted = sc.holm([r.get(key) for r in reports])
        for r, p in zip(reports, adjusted):
            r[out] = p
    for r in reports:
        r['decision'] = decision_class(r.get('mean_difference'), r.get('holm_p'))
        r['hln_decision'] = decision_class(r.get('mean_difference'), r.get('hln_holm_p'))
        r['hac7_decision'] = decision_class(r.get('mean_difference'), r.get('hac7_holm_p'))
    return {'family_m': m, 'days': len(days), 'date_gaps': gaps, 'reports': reports}


# ---------------------------------------------------------------- R. robustness label
def interval_agrees(cls, interval):
    if interval is None or len(interval) != 2 or not all(finite(v) for v in interval):
        return None
    lo, hi = float(interval[0]), float(interval[1])
    if cls == 'CONDITIONAL_IMPROVEMENT':
        return hi < 0
    if cls == 'CONDITIONAL_DETERIORATION':
        return lo > 0
    return lo <= 0 <= hi


def robustness_label(cls, one_day, seven_day, hln_cls, hac7_cls, seed_state, seed_reason=None,
                     seven_day_state=None):
    """ADDENDUM_A2 section R.2. seed_state: SEED_CONSISTENT / SEED_FRAGILE / anything else = unavailable."""
    if cls not in CLASSES:
        return {'label': 'NOT_EVALUABLE', 'checks': {}, 'dissent': [], 'unavailable': [], 'sentence': None}
    checks = {
        'one_day': interval_agrees(cls, one_day),
        'hln': None if hln_cls not in CLASSES else hln_cls == cls,
        'hac7': None if hac7_cls not in CLASSES else hac7_cls == cls,
        'seven_day': None if seven_day_state == 'NOT_INFORMATIVE_ONE_ADMISSIBLE_SEVEN_DAY_BLOCK' else interval_agrees(cls, seven_day),
        'three_seed': {'SEED_CONSISTENT': True, 'SEED_FRAGILE': False}.get(seed_state)}
    dissent = [k for k in CHECK_ORDER if checks[k] is False]
    unavailable = [k for k in CHECK_ORDER if checks[k] is None]
    if dissent:
        label = 'FRAGILE'
        text = SENTENCES['R2'].format(dissent_list=join_list(CHECK_NAME[k] for k in dissent))
        if unavailable:
            text += '; ' + SENTENCES['R3'].format(unavailable_list=join_list(CHECK_NAME[k] for k in unavailable),
                                                  was_were='was' if len(unavailable) == 1 else 'were',
                                                  reason='; '.join(UNAVAILABLE_PHRASE[k] for k in unavailable))
    elif unavailable:
        label = 'NOT_FULLY_CHECKED'
        text = SENTENCES['R3'].format(unavailable_list=join_list(CHECK_NAME[k] for k in unavailable),
                                      was_were='was' if len(unavailable) == 1 else 'were',
                                      reason='; '.join(UNAVAILABLE_PHRASE[k] for k in unavailable))
    else:
        label = 'ROBUST'
        text = SENTENCES['R1']
    return {'label': label, 'checks': checks, 'dissent': dissent, 'unavailable': unavailable, 'sentence': text,
            'recorded_reason': seed_reason}


def seed_rule(primary_cls, primary_mean, seed_cls, seed_mean):
    """A1 SEED_FRAGILE rule: fragile if class or sign of the mean difference differs."""
    if seed_cls is None:
        return 'SEED_ROBUSTNESS_NOT_EVALUABLE'
    sign = lambda v: None if not finite(v) else (v > 0) - (v < 0)
    if seed_cls != primary_cls or sign(seed_mean) != sign(primary_mean):
        return 'SEED_FRAGILE'
    return 'SEED_CONSISTENT'


# ---------------------------------------------------------------- C. attribution
def slot_lookup(secondary, arm, ref):
    for slot in secondary or []:
        if slot.get('arm') == arm and slot.get('reference') == ref:
            return slot
    return None


def favours(slot_like):
    """(state, favourable, unfavourable) for a secondary slot or an A2 contrast report."""
    if slot_like is None:
        return 'NOT_FOUND', False, False
    state = slot_like.get('state')
    if state not in ('COMPUTED_SECONDARY', 'COMPUTED'):
        return state or 'NOT_EVALUABLE', False, False
    mean = slot_like.get('daily_mean_difference', slot_like.get('mean_difference'))
    p = slot_like.get('p_two_sided')
    if not finite(mean) or not finite(p):
        return 'UNDEFINED', False, False
    return 'COMPUTED', bool(mean < 0 and p < ALPHA), bool(mean > 0 and p < ALPHA)


def unmatched_share(source, secondary, total_keys, n_days):
    arm, ref = PCONTENT_SLOT[source]
    slot = slot_lookup(secondary, arm, ref)
    if slot is None or slot.get('state') != 'COMPUTED_SECONDARY':
        return {'state': (slot or {}).get('state', 'NOT_FOUND'), 'total_keys': total_keys, 'n_days': n_days}
    matched = int(slot['matched_keys']); days = int(slot['days'])
    share = 100.0 * matched / total_keys
    out = {'state': 'COMPUTED', 'matched_keys': matched, 'total_keys': total_keys,
           'matched_share_percent': share, 'unmatched_share_percent': 100.0 - share,
           'days_with_matched_key': days, 'days_without_matched_key': n_days - days, 'n_days': n_days}
    out['sentence'] = SENTENCES['C6'].format(matched_share=f'{share:.1f}', total_keys=f'{total_keys:,}',
                                             unmatched_days=n_days - days, n_days=n_days)
    return out


def attribution(source, arm, primary_cls, secondary, cheap_reports, matched):
    """ADDENDUM_A2 section C. cheap_reports: {(arm, comparator): slot or A2 report}."""
    activity = ACTIVITY[source]
    out = {'arm': arm, 'primary_decision': primary_cls}
    controls = {f'{a}-{r}': favours(slot_lookup(secondary, a, r)) for a, r in CONTENT_CONTROLS[source]}
    cheap = {}
    for a, r in CHEAP_COMPARATORS[source]:
        cheap[r] = favours(cheap_reports.get((a, r)))
    out['content_controls'] = {k: {'state': v[0], 'favourable': v[1], 'unfavourable': v[2]} for k, v in controls.items()}
    out['cheap_comparators'] = {k: {'state': v[0], 'favourable': v[1], 'unfavourable': v[2]} for k, v in cheap.items()}
    if primary_cls != 'CONDITIONAL_IMPROVEMENT':
        out.update(label='NOT_APPLICABLE_NO_RELIABLE_INCREMENT', sentence=None)
        return out
    if arm != CONTENT_ARM[source]:
        out.update(label='ACTIVITY_REFERENCE_INCREMENT_NO_CONTROL', sentence=SENTENCES['C1'].format(activity=activity))
        return out
    not_computed = {k: v[0] for k, v in controls.items() if v[0] != 'COMPUTED'}
    if not_computed:
        reason = '; '.join(CONTROL_NAME[k.split('-')[1]] + ': ' + STATE_PHRASE.get(v, 'it was not evaluable')
                           for k, v in not_computed.items())
        out.update(label='CONTENT_NOT_ASSESSABLE', reason=reason, recorded_states=not_computed,
                   sentence=SENTENCES['C3'].format(activity=activity, reason=reason))
        return out
    failed = [k for k, v in controls.items() if not v[1]]
    if failed:
        out.update(label='ACTIVITY_REFERENCE_INCREMENT_CONTROLS_FAILED', failed_controls=failed,
                   sentence=SENTENCES['C2'].format(activity=activity,
                                                   failed_list=join_list(CONTROL_NAME[k.split('-')[1]] for k in failed)))
        return out
    share = matched.get('matched_share_percent')
    share_text = f'{share:.1f}' if finite(share) else 'undefined'
    available = {k: v for k, v in cheap.items() if v[0] == 'COMPUTED'}
    unavailable = [k for k, v in cheap.items() if v[0] != 'COMPUTED']
    beaten = [k for k, v in available.items() if v[1]]
    better = [k for k, v in available.items() if v[2]]
    not_beaten = [k for k, v in available.items() if not v[1] and not v[2]]
    if available and len(beaten) == len(available):
        out.update(label='LLM_SPECIFIC', unavailable_comparators=unavailable,
                   sentence=SENTENCES['C5'].format(matched_share=share_text,
                                                   comparator_list=join_list(COMPARATOR_NAME[k] for k in beaten),
                                                   documents=DOCUMENTS[source]))
        if unavailable:
            out['sentence'] += '; ' + join_list(COMPARATOR_NAME[k] for k in unavailable) + (
                ' was' if len(unavailable) == 1 else ' were') + ' not available'
        return out
    reasons = []
    if not_beaten:
        reasons.append('it did not outperform ' + join_list(COMPARATOR_NAME[k] for k in not_beaten))
    if better:
        reasons.append(join_list(COMPARATOR_NAME[k] for k in better) + ' performed reliably better')
    if unavailable:
        reasons.append(join_list(COMPARATOR_NAME[k] for k in unavailable) + (' was' if len(unavailable) == 1 else ' were') + ' not available')
    out.update(label='CONTENT_SPECIFIC_NOT_LLM_SPECIFIC',
               sentence=SENTENCES['C4'].format(matched_share=share_text, llm_reason='; '.join(reasons)))
    return out


# ---------------------------------------------------------------- B. SESOI per task
def branch_safe_bound(x, d, S):
    """Outward-rounded bound display that stays on the side of S given by the exact value (up to 12 decimals)."""
    for dd in range(d, 13):
        text = fmt_bound(x, dd)
        if (float(text) < S) == (x < S):
            return text
    return fmt_bound(x, 12)


def sesoi_reading(source, cls, effect, fam_one_day, d=3):
    S = SESOI[source]
    out = {'sesoi_percent': S, 'decision': cls}
    if cls == 'NO_RELIABLE_INCREMENT_DETECTED' and fam_one_day is not None:
        x = max(0.0, -float(fam_one_day[0]))
        branch = 'D1' if x < S else 'D2'
        out.update(branch=branch, bound_family_adjusted_percent=x, bound_display=branch_safe_bound(x, d, S),
                   sentence=SENTENCES[branch].format(X=branch_safe_bound(x, d, S), tail=TAIL_TEXT[source], S=S))
    elif cls == 'CONDITIONAL_IMPROVEMENT' and finite(effect):
        branch = 'D3' if abs(float(effect)) < S else 'D4'
        out.update(branch=branch, sentence=SENTENCES[branch].format(S=S))
    else:
        out.update(branch='NONE', sentence=None)
    return out


# ---------------------------------------------------------------- inputs
class Inputs:
    """Verified access to the sealed and scored host files."""

    def __init__(self, state, grid=None):
        self.state = Path(state).resolve()
        self.grid = grid or WINDOW
        self.scored = self.state / 'scored'
        self.seal_path = self.state / 'SEAL.json'
        receipt_path = self.scored / 'SCORE_RECEIPT.json'
        if not self.seal_path.exists() or not receipt_path.exists():
            raise PermissionError('A2 runs only after the frozen score: SEAL.json and scored/SCORE_RECEIPT.json are required')
        self.receipt = json.loads(receipt_path.read_text())
        if self.receipt.get('state') != 'FROZEN_SCORE_COMPLETE':
            raise PermissionError('Frozen score is not complete')
        self.seal_sha256 = sha256(self.seal_path)
        if self.receipt.get('seal_sha256') != self.seal_sha256:
            raise PermissionError('Score receipt does not bind the current SEAL.json')
        self.seal = json.loads(self.seal_path.read_text())
        self.score_files = {Path(f['path']).name: f for f in self.receipt['files']}
        self.read_log = [{'path': str(self.seal_path), 'sha256': self.seal_sha256, 'role': 'seal'},
                         {'path': str(receipt_path), 'sha256': sha256(receipt_path), 'role': 'score_receipt'}]

    def score_file(self, name, required=True):
        ident = self.score_files.get(name)
        if ident is None:
            if required:
                raise FileNotFoundError('Score file not listed in SCORE_RECEIPT: ' + name)
            return None
        path = Path(ident['path'])
        digest = sha256(path)
        if digest != ident['sha256']:
            raise PermissionError('Score file drift: ' + name)
        self.read_log.append({'path': str(path), 'sha256': digest, 'role': 'score_output'})
        return path

    def score_json(self, name, required=True):
        path = self.score_file(name, required)
        return None if path is None else json.loads(path.read_text())

    def daily_losses(self, source):
        import pandas as pd
        frame = pd.read_csv(self.score_file(source + '__DAILY_LOSSES.csv'))
        frame['target_day'] = frame['target_day'].astype(str)
        return frame

    def prediction_identity(self, source, arm, seed=SEED, variant='main'):
        for ident in self.seal['predictions']:
            if (ident.get('source'), ident.get('arm'), ident.get('seed'), ident.get('variant')) == (source, arm, seed, variant):
                return ident
        return None

    def _checked(self, ident, role):
        path = Path(ident['path'])
        digest = sha256(path)
        if digest != ident['sha256']:
            raise PermissionError('Sealed file drift: ' + str(path))
        self.read_log.append({'path': str(path), 'sha256': digest, 'role': role})
        return path

    def truth(self, source):
        """Sealed truth panel (identity bound in SEAL.json), complete D grid in the frozen canonical key order."""
        import pyarrow.parquet as pq
        import pandas as pd
        path = self._checked(self.seal['truth_panels'][source], 'sealed_truth_panel_postscore')
        table = pq.read_table(path, columns=KEYS + ['target_day', 'y', 'weight'])
        frame = table.to_pandas()
        frame['target_day'] = frame['target_day'].astype(str)
        lo, hi, per_day = self.grid[source]
        frame = frame.loc[frame['target_day'].between(lo, hi)]
        frame = coerce_keys(frame).sort_values(KEYS, kind='mergesort').reset_index(drop=True)
        counts = frame.groupby('target_day').size()
        expected = [d.strftime('%Y-%m-%d') for d in pd.date_range(lo, hi, freq='D')]
        if list(counts.index) != expected or not (counts.to_numpy() == per_day).all():
            raise ValueError('Complete registered grid gate failed for ' + source)
        if not np.isfinite(frame['y'].to_numpy()).all() or not (frame['weight'].to_numpy() == 1).all():
            raise ValueError('Finite truth and unit weight gate failed')
        return frame

    def prediction(self, source, arm, truth, seed=SEED, variant='main'):
        import pandas as pd
        ident = self.prediction_identity(source, arm, seed, variant)
        if ident is None:
            return None
        frame = coerce_keys(pd.read_parquet(self._checked(ident, 'sealed_prediction'))).reset_index(drop=True)
        if not frame[KEYS].equals(truth[KEYS]):
            raise ValueError('Sealed prediction keys differ from the truth grid: ' + arm)
        values = frame['prediction'].to_numpy(dtype='float64')
        if not np.isfinite(values).all():
            raise ValueError('Nonfinite sealed prediction: ' + arm)
        return values


def coerce_keys(frame):
    import pandas as pd
    f = frame.copy()
    for col in ('origin', 'target_time'):
        f[col] = pd.to_datetime(f[col], utc=True).astype('datetime64[ns, UTC]')
    f['target_day'] = f['target_day'].astype(str)
    return f


def daily_abs_loss(truth, prediction):
    import pandas as pd
    loss = np.abs(np.asarray(prediction, dtype='float64') - truth['y'].to_numpy(dtype='float64'))
    daily = pd.DataFrame({'day': truth['target_day'].to_numpy(), 'loss': loss}).groupby('day', sort=True)['loss'].mean()
    return list(daily.index), daily.to_numpy(dtype='float64')


# ---------------------------------------------------------------- per-task computations
def primary_section(sc, inputs, source, daily_frame):
    """R, B and C for the primary family, using the frozen score outputs."""
    primary = inputs.score_json(source + '__PRIMARY.json')
    hln = inputs.score_json(source + '__A1_HLN.json')
    seeds = inputs.score_json(source + '__A1_SEED_FRAGILE.json')
    report = inputs.score_json('SCORE_REPORT.json')
    secondary = report[source]['secondary']
    days = daily_frame['target_day'].tolist()
    m = len(FAMILIES[source])
    # Recompute the one-day and seven-day draws from the frozen daily losses and frozen picks; check the saved 95%.
    picks = complete_picks(sc, len(days))
    out = []
    for saved in primary['reports']:
        arm, ref = saved['arm'], saved['reference']
        row = {'arm': arm, 'reference': ref, 'decision': saved.get('primary_decision'),
               'holm_p': saved.get('primary_two_sided_holm_p'), 'mean_difference': saved['dm_p1'].get('mean_difference'),
               'p_two_sided': saved['dm_p1'].get('p_two_sided')}
        if arm in daily_frame and ref in daily_frame:
            recomputed = contrast_stats(sc, daily_frame[arm].to_numpy(), daily_frame[ref].to_numpy(), picks, m)
            for block in ('1', '7'):
                mine = recomputed['bootstrap'][block].get('interval95_percent')
                theirs = (saved['bootstrap'].get(block) or saved['bootstrap'].get(int(block)) or {}).get('interval95_percent')
                if (mine is None) != (theirs is None) or (mine is not None and max(abs(x - y) for x, y in zip(mine, theirs)) > 1e-9):
                    raise ValueError(f'Recomputed {block}-day interval differs from the frozen one: {arm}-{ref}')
            row['effect_percent_reference_mae'] = recomputed['effect_percent_reference_mae']
            row['interval95_one_day'] = recomputed['bootstrap']['1']['interval95_percent']
            row['interval95_seven_day'] = recomputed['bootstrap']['7']['interval95_percent']
            row['interval_family_one_day'] = recomputed['bootstrap']['1']['interval_family_adjusted_percent']
            row['interval_family_seven_day'] = recomputed['bootstrap']['7']['interval_family_adjusted_percent']
        else:
            row.update(effect_percent_reference_mae=None, interval95_one_day=None, interval95_seven_day=None,
                       interval_family_one_day=None, interval_family_seven_day=None)
        hln_row = next((r for r in hln['rows'] if (r['arm'], r['reference']) == (arm, ref)), {})
        seed_row = next((r for r in seeds['rows'] if (r['arm'], r['reference']) == (arm, ref)), {})
        hac_cls = decision_class(row['mean_difference'], saved.get('sensitivity_hac7_two_sided_holm_p'))
        row['hac7_holm_p'] = saved.get('sensitivity_hac7_two_sided_holm_p')
        row['hac7_decision'] = hac_cls
        row['hln_decision'] = hln_row.get('hln_decision')
        row['hln_holm_p'] = hln_row.get('hln_t_holm_p')
        row['three_seed_state'] = seed_row.get('state')
        row['robustness'] = robustness_label(row['decision'], row['interval95_one_day'], row['interval95_seven_day'],
                                             row['hln_decision'], hac_cls, seed_row.get('state'),
                                             seed_row.get('reason'))
        one = row['interval95_one_day']
        row['display_decimals'] = percent_decimals(None if one is None else one[1] - one[0])
        row['sesoi'] = sesoi_reading(source, row['decision'], row['effect_percent_reference_mae'],
                                     row['interval_family_one_day'], row['display_decimals'])
        out.append(row)
    return out, secondary


def cheap_contrasts(sc, source, daily_frame, secondary):
    """News: frozen slots. Notices: A2 contrasts from the frozen daily losses (unadjusted secondary inference)."""
    reports = {}
    days = daily_frame['target_day'].tolist()
    for arm, ref in CHEAP_COMPARATORS[source]:
        if (arm, ref) in A2_NEW_CONTRASTS.get(source, ()):
            if arm in daily_frame and ref in daily_frame:
                r = contrast_stats(sc, daily_frame[arm].to_numpy(), daily_frame[ref].to_numpy(),
                                   complete_picks(sc, len(days)), 1)
                r.update(arm=arm, reference=ref, state='COMPUTED', role='A2_SECONDARY_ATTRIBUTION_CONTRAST')
                reports[(arm, ref)] = r
            else:
                reports[(arm, ref)] = {'arm': arm, 'reference': ref, 'state': 'NOT_EVALUABLE_WHOLE_STAGE_UNAVAILABLE'}
        else:
            reports[(arm, ref)] = slot_lookup(secondary, arm, ref)
    return reports


def combination_section(sc, inputs, source, primary_rows, a1_npm=None):
    """Section S: equal-weight combination contrasts with the task's strong benchmark."""
    bsource, barm = BENCHMARK[source]
    truth = inputs.truth(source)
    b = inputs.prediction(bsource, barm, truth)
    pairs = FAMILIES[source]
    tested = list(dict.fromkeys(x for pair in pairs for x in pair))
    if b is None:
        return {'state': 'NOT_EVALUABLE_BENCHMARK_UNAVAILABLE', 'benchmark': barm,
                'sentence': SENTENCES['S7'].format(benchmark=BENCHMARK_NAME[source],
                                                   reason='the benchmark forecasts were not available'), 'reports': []}
    days, b_loss = daily_abs_loss(truth, b)
    single, combined, combined3 = {}, {}, {}
    seeds_complete = True
    for arm in tested:
        p = inputs.prediction(source, arm, truth)
        if p is None:
            continue
        single[arm] = daily_abs_loss(truth, p)[1]
        combined[arm] = daily_abs_loss(truth, 0.5 * (b + p))[1]
        extra = [inputs.prediction(source, arm, truth, seed=s) for s in EXTRA_SEEDS]
        if any(e is None for e in extra):
            seeds_complete = False
        else:
            mean3 = np.mean([p] + extra, axis=0)
            combined3[arm] = daily_abs_loss(truth, 0.5 * (b + mean3))[1]
    # Cross-check single-arm daily losses with the frozen DAILY_LOSSES.csv.
    frozen = inputs.daily_losses(source)
    if frozen['target_day'].tolist() != days:
        raise ValueError('Daily loss day order differs from the frozen file')
    for arm, values in list(single.items()) + [(barm, b_loss)]:
        if arm in frozen and np.max(np.abs(frozen[arm].to_numpy() - values)) > 1e-9:
            raise ValueError('Recomputed daily loss differs from the frozen DAILY_LOSSES.csv: ' + arm)
    family = family_inference(sc, combined, pairs, days)
    seed_family = family_inference(sc, combined3, pairs, days) if seeds_complete and combined3 else None
    by_primary = {(r['arm'], r['reference']): r for r in primary_rows}
    for r in family['reports']:
        seed_state = 'SEED_ROBUSTNESS_NOT_EVALUABLE'
        if seed_family is not None:
            s = next(x for x in seed_family['reports'] if (x['arm'], x['reference']) == (r['arm'], r['reference']))
            seed_state = seed_rule(r['decision'], r.get('mean_difference'), s['decision'], s.get('mean_difference'))
            r['three_seed'] = {'decision': s['decision'], 'mean_difference': s.get('mean_difference'),
                               'effect_percent_reference_mae': s.get('effect_percent_reference_mae')}
        r['three_seed_state'] = seed_state
        one = r['bootstrap']['1'].get('interval95_percent'); seven = r['bootstrap']['7'].get('interval95_percent')
        r['robustness'] = robustness_label(r['decision'], one, seven, r['hln_decision'], r['hac7_decision'], seed_state,
                                           None if seed_family is not None else 'extra-seed predictions not sealed')
        primary = by_primary.get((r['arm'], r['reference']), {})
        r['primary_decision'] = primary.get('decision')
        r['clause_id'], r['sentence'] = combination_clause(source, r, primary.get('decision'))
    out = {'state': 'COMPUTED', 'benchmark': barm, 'benchmark_mae': float(b_loss.mean()),
           'combined_mae': {k: float(v.mean()) for k, v in combined.items()},
           'single_mae': {k: float(v.mean()) for k, v in single.items()}, 'family': family,
           'three_seed_family_computed': seed_family is not None, 'role': 'A2_SECONDARY_STRONG_BENCHMARK_COMBINATION'}
    if a1_npm is not None:
        out['nested_A1_NPL_minus_NPM'] = a1_npm
    return out


def combination_clause(source, r, primary_cls):
    d = percent_decimals(None if r['bootstrap']['1'].get('interval95_percent') is None else
                         r['bootstrap']['1']['interval95_percent'][1] - r['bootstrap']['1']['interval95_percent'][0])
    effect = fmt_effect(r.get('effect_percent_reference_mae'), d)
    lo, hi = fmt_interval(r['bootstrap']['1'].get('interval_family_adjusted_percent'), d)
    fields = dict(benchmark=BENCHMARK_NAME[source], effect=effect, level=LEVEL_TEXT[source], lo=lo, hi=hi,
                  p=display_p(r.get('holm_p')), arm=r['arm'])
    cls = r['decision']
    if primary_cls == 'CONDITIONAL_IMPROVEMENT':
        key = {'CONDITIONAL_IMPROVEMENT': 'S1', 'NO_RELIABLE_INCREMENT_DETECTED': 'S2',
               'CONDITIONAL_DETERIORATION': 'S3'}.get(cls)
    elif primary_cls == 'NO_RELIABLE_INCREMENT_DETECTED':
        key = {'CONDITIONAL_IMPROVEMENT': 'S4', 'NO_RELIABLE_INCREMENT_DETECTED': 'S5',
               'CONDITIONAL_DETERIORATION': 'S6'}.get(cls)
    else:
        return 'S8', None
    if key is None:
        return 'S7', SENTENCES['S7'].format(benchmark=BENCHMARK_NAME[source], reason='the combination contrast is undefined')
    return key, SENTENCES[key].format(**fields)


def strict_unexposed_section(sc, source, daily_frame):
    """Section U: descriptive recomputation on the strictly unexposed days."""
    keep = day_list(STRICT_UNEXPOSED[source])
    if len(keep) != STRICT_UNEXPOSED_DAYS[source]:
        raise ValueError('Strictly unexposed day list drift')
    sub = daily_frame.loc[daily_frame['target_day'].isin(keep)].reset_index(drop=True)
    if sub['target_day'].tolist() != keep:
        raise ValueError('Strictly unexposed days missing from the frozen daily losses')
    losses = {c: sub[c].to_numpy() for c in sub.columns if c != 'target_day'}
    fam = family_inference(sc, losses, FAMILIES[source], keep, m=1, subset=True)
    ranges = join_list(f'{a} to {b}' for a, b in STRICT_UNEXPOSED[source])
    for r in fam['reports']:
        r.pop('holm_p', None); r.pop('hln_holm_p', None); r.pop('hac7_holm_p', None)
        r['decision'] = None; r['hln_decision'] = None; r['hac7_decision'] = None
        one = r['bootstrap']['1'].get('interval95_percent')
        d = percent_decimals(None if one is None else one[1] - one[0])
        lo, hi = fmt_interval(one, d)
        r['descriptive_word'] = ('favourable difference observed' if finite(r.get('mean_difference')) and finite(r.get('p_two_sided'))
                                 and r['p_two_sided'] < ALPHA and r['mean_difference'] < 0 else
                                 'unfavourable difference observed' if finite(r.get('mean_difference')) and finite(r.get('p_two_sided'))
                                 and r['p_two_sided'] < ALPHA and r['mean_difference'] > 0 else 'no reliable difference detected')
        r['sentence'] = SENTENCES['U1'].format(n=len(keep), ranges=ranges, arm=r['arm'], activity=ACTIVITY[source],
                                               effect=fmt_effect(r.get('effect_percent_reference_mae'), d), lo=lo, hi=hi,
                                               p=display_p(r.get('p_two_sided')))
        if source == 'notice':
            r['hac7_note'] = 'computed as frozen on a contiguous 7-day subset (n = 7); not interpretable as a dependence check'
    return {'role': 'A2_STRICTLY_UNEXPOSED_DESCRIPTIVE', 'set_name': SENTENCES['U3'], 'renamed_A1_set': SENTENCES['U2'],
            'days': len(keep), 'day_runs': [list(r) for r in STRICT_UNEXPOSED[source]], 'date_gaps': fam['date_gaps'],
            'reports': fam['reports'], 'decision_rule': 'none (descriptive only)'}


def headline(source, rows, attribution_rows, combination):
    """Appendix A headline sentences for each primary contrast and the task bound (H0-H5)."""
    activity = ACTIVITY[source]
    attr = {r['arm']: r for r in attribution_rows}
    combo = {}
    if combination.get('state') == 'COMPUTED':
        combo = {(r['arm'], r['reference']): r for r in combination['family']['reports']}
    out = []
    no_increment_bounds = []
    for row in rows:
        cls = row['decision']
        one = row.get('interval95_one_day')
        d = percent_decimals(None if one is None else one[1] - one[0])
        lo, hi = fmt_interval(row.get('interval_family_one_day'), d)
        fields = dict(arm=row['arm'], activity=activity, effect=fmt_effect(row.get('effect_percent_reference_mae'), d),
                      abs_effect=fmt_effect(None if not finite(row.get('effect_percent_reference_mae')) else
                                            abs(row['effect_percent_reference_mae']), d),
                      level=LEVEL_TEXT[source], lo=lo, hi=hi, p=display_p(row.get('holm_p')),
                      robustness=row['robustness']['sentence'])
        if cls in ('NO_RELIABLE_INCREMENT_DETECTED', 'CONDITIONAL_DETERIORATION') and row.get('interval_family_one_day'):
            no_increment_bounds.append((max(0.0, -float(row['interval_family_one_day'][0])), d))
        if cls == 'NO_RELIABLE_INCREMENT_DETECTED':
            text = SENTENCES['H1'].format(**fields)
        elif cls == 'CONDITIONAL_IMPROVEMENT':
            c = combo.get((row['arm'], row['reference']))
            bench = (c or {}).get('sentence') or SENTENCES['S7'].format(benchmark=BENCHMARK_NAME[source],
                                                                       reason=combination.get('state', 'not computed'))
            text = SENTENCES['H2'].format(attribution=attr[row['arm']]['sentence'], benchmark=bench, **fields)
        elif cls == 'CONDITIONAL_DETERIORATION':
            text = SENTENCES['H3'].format(**fields)
        else:
            text = SENTENCES['H4'].format(arm=row['arm'], activity=activity, reason='its registered input or completion gate failed')
        out.append({'arm': row['arm'], 'reference': row['reference'], 'decision': cls, 'sentence': text,
                    'sesoi_sentence': row['sesoi'].get('sentence')})
    task_bound = None
    # H5: no contrast of the family shows a reliable increment; the bound is the largest over the evaluable contrasts.
    if no_increment_bounds and not any(r['decision'] == 'CONDITIONAL_IMPROVEMENT' for r in rows):
        x = max(b for b, _ in no_increment_bounds)
        d = max(dd for _, dd in no_increment_bounds)
        task_bound = SENTENCES['H5'].format(X=branch_safe_bound(x, d, SESOI[source]), tail=TAIL_TEXT[source],
                                            S=SESOI[source], below_or_above='below' if x < SESOI[source] else 'at or above')
    robust_all = all(r['robustness']['label'] == 'ROBUST' for r in rows)
    return {'contrasts': out, 'task_bound_sentence': task_bound, 'information_set_sentence': SENTENCES['H0'],
            'all_robust_sentence': SENTENCES['R4'].format(task=TASK_NAME[source]) if robust_all else None,
            'bound_label_sentence': SENTENCES['B3'].format(level=LEVEL_TEXT[source], m=len(FAMILIES[source]),
                                                           task=TASK_NAME[source])}


def run_task(sc, inputs, source):
    daily = inputs.daily_losses(source)
    lo, hi, per_day = inputs.grid[source]
    n_days = len(daily)
    rows, secondary = primary_section(sc, inputs, source, daily)
    matched = unmatched_share(source, secondary, n_days * per_day, n_days)
    cheap = cheap_contrasts(sc, source, daily, secondary)
    attribution_rows = [attribution(source, r['arm'], r['decision'], secondary, cheap, matched) for r in rows]
    a1_npm = slot_lookup(secondary, 'NPL', 'NPM') if source == 'notice' else None
    combination = combination_section(sc, inputs, source, rows, a1_npm)
    strict = strict_unexposed_section(sc, source, daily)
    new_contrasts = {f'{a}-{r}': cheap[(a, r)] for a, r in A2_NEW_CONTRASTS.get(source, ())}
    return {'primary': rows, 'attribution': attribution_rows, 'p_content_unmatched': matched,
            'cheap_text_comparators': {f'{a}-{r}': (v if isinstance(v, dict) else None) for (a, r), v in cheap.items()},
            'a2_new_secondary_contrasts': new_contrasts, 'combination': combination, 'strictly_unexposed': strict,
            'headline': headline(source, rows, attribution_rows, combination),
            'sesoi': {'value_percent': SESOI[source], 'methods_sentence': SENTENCES['D6'],
                      'notice_transfer_sentence': SENTENCES['D5'] if source == 'notice' else None}}


def run(state, out=None, conf_root=CONF_ROOT, grid=None):
    state = Path(state).resolve()
    out = Path(out).resolve() if out else state / 'a2_scored'
    if out == (state / 'scored').resolve() or (state / 'scored').resolve() in out.parents:
        raise PermissionError('A2 never writes into the frozen scored/ folder')
    freeze = json.loads(ADDENDUM_FREEZE.read_text())
    for name, ident in freeze['files'].items():
        if sha256(A2_ROOT / name) != ident['sha256']:
            raise PermissionError('Frozen A2 document drift: ' + name)
    sc = load_frozen_scoring(conf_root)
    inputs = Inputs(state, grid)
    result = {'analysis': 'CONF-A2 post-score readings (secondary and reporting; no primary decision changes)',
              'addendum_freeze_sha256': sha256(ADDENDUM_FREEZE), 'module_sha256': sha256(Path(__file__)),
              'seal_sha256': inputs.seal_sha256, 'tasks': {}}
    for source in ('news', 'notice'):
        result['tasks'][source] = run_task(sc, inputs, source)
    result['inputs_read'] = inputs.read_log
    result['primary_decision_rule_changed'] = False
    out.mkdir(parents=True, exist_ok=True)
    path = out / 'A2_POSTSCORE.json'
    path.write_text(json.dumps(json_safe(result), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n')
    receipt = {'state': 'A2_POSTSCORE_COMPLETE', 'output': {'path': str(path), 'sha256': sha256(path)},
               'seal_sha256': inputs.seal_sha256, 'addendum_freeze_sha256': sha256(ADDENDUM_FREEZE),
               'module_sha256': sha256(Path(__file__)), 'inputs_read': inputs.read_log}
    (out / 'A2_POSTSCORE_RECEIPT.json').write_text(json.dumps(json_safe(receipt), indent=2, sort_keys=True) + '\n')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    result = run(args.state, args.out)
    print(json.dumps({'state': 'A2_POSTSCORE_COMPLETE', 'tasks': list(result['tasks'])}))


if __name__ == '__main__':
    main()
