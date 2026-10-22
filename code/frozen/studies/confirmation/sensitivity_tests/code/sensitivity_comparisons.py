"""CONF-A3 post-score module (ADDENDUM_A3.md, frozen in ADDENDUM_A3_FREEZE.json before this code was written).

Extends the frozen CONF-A2 module `A2/code/a2_postscore.py` by import (after its freeze is verified). Runs after the
frozen score and after A2, before the manuscript fill (FILL3a):

    cli.py score  ->  a2_postscore.py  ->  a3_postscore.py --state <host_state>  ->  FILL3a

It never refits and never changes a frozen reading. Besides what A2 reads it reads: the frozen score files of the
design sensitivities, the feature manifest / matched mask / panel keys bound by SEAL.json, the frozen PRE2FACTS
re-admission CSV and, when present, the positive-control, A2BATCH and A2LABEL results. It writes only
`<state>/a3_scored/` (refuses `scored/` and `a2_scored/`). Sentence forms are copied verbatim from Appendix A3.

    python a3_postscore.py --state <host_state> [--out DIR] [--positive-control F] [--a2batch F] [--a2label F]
    python a3_postscore.py --coverage-only --feature-root <host_state>/features   # matched-mask counts, no outcome
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np

A3_ROOT = Path(__file__).resolve().parents[1]
CONF_ROOT = A3_ROOT.parent
A2_ROOT = CONF_ROOT / 'A2'
PROJ = CONF_ROOT.parents[2]
ADDENDUM_FREEZE = A3_ROOT / 'ADDENDUM_A3_FREEZE.json'
A2_CODE_FREEZE = A2_ROOT / 'A2_CODE_AND_RULES_FREEZE.json'
A2_ADDENDUM_FREEZE = A2_ROOT / 'ADDENDUM_A2_FREEZE.json'
READMISSION_CSV = PROJ / 'autopilot/q1_audits/PRE2FACTS/READMISSION_PAIRS.csv'
READMISSION_SHA256 = '92c87559fb21104ca040f3ee66f4d84161a2f46f1ff3eb12e2422e226dcbd536'
READMISSION_FREE_DAYS = 109
DEFAULT_PC = CONF_ROOT / 'A1/positive_control/run/RESULT_POSITIVE_CONTROL.json'
DEFAULT_A2BATCH = PROJ / 'autopilot/q1_audits/A2BATCH/scores/A2BATCH_RESULT.json'
DEFAULT_A2LABEL = PROJ / 'autopilot/q1_audits/A2LABEL/scores/A2LABEL_RESULT.json'


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def load_a2():
    """Import the frozen A2 module only after A2's two freeze records verify."""
    code_freeze = json.loads(A2_CODE_FREEZE.read_text())
    if sha256(A2_ADDENDUM_FREEZE) != code_freeze['addendum_freeze_sha256']:
        raise PermissionError('A2 addendum freeze drift')
    for name, ident in json.loads(A2_ADDENDUM_FREEZE.read_text())['files'].items():
        if sha256(A2_ROOT / name) != ident['sha256']:
            raise PermissionError('Frozen A2 document drift: ' + name)
    for name, ident in code_freeze['files'].items():
        if sha256(A2_ROOT / name) != ident['sha256']:
            raise PermissionError('Frozen A2 code or rule drift: ' + name)
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('a2_postscore_frozen_for_a3', A2_ROOT / 'code/a2_postscore.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A2 = load_a2()
IMP, DET, NULL, NE = 'CONDITIONAL_IMPROVEMENT', 'CONDITIONAL_DETERIORATION', 'NO_RELIABLE_INCREMENT_DETECTED', 'NOT_EVALUABLE'
CLASSES = (IMP, DET, NULL)

# ---------------------------------------------------------------- Appendix A3 sentence forms (verbatim)
SENTENCES = {
    # H
    'A3H0': 'These readings are relative to the pre-specified learner and information set: the primary news reference uses no operator forecasts and the primary notice reference uses no five-minute pre-dispatch prices.',
    'A3H1': '{arm} showed no reliable increment over the {activity} reference ({effect}% of the reference error, family-adjusted {level}% interval [{lo}, {hi}]%, Holm-adjusted {p}); {robustness}{qualifiers}.',
    'A3H2': '{arm} improved on the {activity} reference by {abs_effect}% of the reference error ({abs_aud} AUD/MWh; family-adjusted {level}% interval [{lo}, {hi}]%, Holm-adjusted {p}){zero}; {robustness}; {attribution}; {sesoi}; {benchmark}{qualifiers}.',
    'A3H3': '{arm} performed reliably worse than the {activity} reference by {effect}% of the reference error ({abs_aud} AUD/MWh; family-adjusted {level}% interval [{lo}, {hi}]%, Holm-adjusted {p}){zero}; {robustness}{qualifiers}.',
    'A3H4': 'The pre-specified comparison of {arm} with the {activity} reference could not be evaluated because {reason}; no confirmation conclusion is drawn for it.',
    'A3H4R': 'its pre-specified input or completion gate failed',
    'A3H5': 'For each structured representation, improvements larger than {X}% of the reference error were excluded at the family-adjusted one-sided {tail}% level, which is {below_or_above} {S_phrase}{task_qualifiers}.',
    'A3H6': 'The {task_label} confirmation is incomplete because {reason}; under the frozen protocol this is an incomplete confirmation, not a null result, and no confirmation reading is reported for this task.',
    'A3Z': "; Holm's sequential rule rejected this comparison, but its family-adjusted {level}% interval includes zero, so the size of the {direction} is not bounded away from zero at the family level",
    'A3QL': 'this reading was extraction-run-dependent: with independently re-extracted test-period labels and the same fitted models it became {reading_replacement}',
    'A3INC_BUDGET': 'its pre-specified primary fits did not finish within the fixed 24-hour fitting budget',
    'A3INC_FAIL': 'its pre-specified primary fits failed before sealing',
    'A3S2': 'when each forecast was averaged with {benchmark}, no reliable increment was detected ({effect}%, family-adjusted {level}% interval [{lo}, {hi}]%, Holm-adjusted {p}), so the increment is stated relative to the pre-specified learner and information set only',
    # S
    'A3S_BEYOND': 'its family-adjusted interval lies wholly beyond {S_phrase}, so improvements smaller than {S}% are excluded at the family-adjusted one-sided {tail}% level',
    'A3S_ABOVE': 'its point estimate exceeds {S_phrase}, but its family-adjusted interval straddles that value, so this window cannot tell whether the increment is larger or smaller than {S}%',
    'A3S_BELOWPT': 'its point estimate is below {S_phrase}, but its family-adjusted interval straddles that value, so this window cannot tell whether the increment is larger or smaller than {S}%',
    'A3S_BELOW': 'its family-adjusted interval lies wholly below {S_phrase}, so improvements as large as {S}% are excluded at the family-adjusted one-sided {tail}% level',
    'A3D1': 'Improvements larger than {X}% of the reference error were excluded at the family-adjusted one-sided {tail}% level, conditional on these fitted predictions; this bound is below {S_phrase}, so improvements of that size are excluded by this window.',
    'A3D2': 'Improvements larger than {X}% of the reference error were excluded at the family-adjusted one-sided {tail}% level, conditional on these fitted predictions; this bound does not exclude improvements as large as {S_phrase}, so the window is not informative about effects of that size.',
    'A3D7': 'None of these bounds is an equivalence test, and none shows a zero effect.',
    'A3D6': 'The comparison values are interpretation aids and never enter a decision. For news, the smallest effect size of interest is 3.8% of the reference error, the smallest text-attributed error reduction with a significance test in the cited electricity forecasting work. For notices, the comparison value is 0.5% of the reference error: the equivalence tolerance of the earlier pre-confirmation window-C notice test, used here as a historical-effect reference; that tolerance was set after development results were known and is not an economic indifference threshold.',
    'A3D5': 'The transferred 3.8% value is not informative for the notice task, whose expected bounds are an order of magnitude smaller; the notice reading is compared with the 0.5% historical-effect reference, with the earlier notice text effects and with the minimum detectable effect.',
    'A3M1': "The largest family-adjusted bound of the {task_label} family, {X}%, is {mde_cmp} the design's minimum detectable effect of {mde}%.",
    'A3N1': 'It is {hist_cmp} the earlier word-frequency gains over the numerical reference of 0.097% (January–February 2026) and 0.154% (development); those gains come from other windows, labels and a text-versus-no-text comparison, so they are a reference, not a test.',
    'A3G1': 'Against the numerical reference, improvements larger than {X_count}% for the label-count representation, {X_chen}% for the structured-attribute embedding and {X_act}% for the article activity reference were excluded at the unadjusted one-sided 2.5% level; Table {table_ref} places these text-versus-no-text bounds beside the published no-text-to-text comparisons, whose relative error changes computed from the reported metric pairs range from a 1.37% increase to a 13.90% reduction, and the larger structured-representation bound is {pub_cmp}.',
    # C
    'A3C1': 'it is an increment over the {activity} reference; no pre-specified content control exists for this representation, so it is not attributed to the content and was not shown to be LLM-specific; {cheap}',
    'A3C2': 'it is an increment over the {activity} reference; the pre-specified content controls did not both favour the original content ({failed_list}), so it is not attributed to the content and was not shown to be LLM-specific; {cheap}',
    'A3C3': 'it is an increment over the {activity} reference; the pre-specified content controls could not be evaluated ({reason}), so it is not attributed to the content and was not shown to be LLM-specific; {cheap}',
    'A3CH': 'against cheap-text representations of the same {documents}, it {cheap_list}',
    'A3CH0': 'no cheap-text comparison from the same {documents} was available',
    'A3C7': 'For notices, the activity-matched reassignment control has no matched key by construction: each notice representation encodes the full saved prefix, so an earlier prefix with the same count contains the same notices, which the donor rule excludes; the notice content-specific label therefore cannot be reached.',
    'A3C8': 'Content controls exist only for the two structured-attribute embeddings. For the label-count representation, the event-state representation and the message, failure and fuel-group counts, activity-matched reassignment or 28-day shifting would require new features, so their increments are described relative to activity only and compared with cheap-text representations of the same documents.',
    # R
    'A3R4': 'Every primary reading of the {task_label} family agreed with all five inferential checks.',
    'A3R5a': 'Every available pre-specified design sensitivity with a decision rule ({available_list}) gave the same decision class as the primary readings of the {task_label} family{unavailable_clause}.',
    'A3R5b': 'Pre-specified design sensitivities changed the decision class of these {task_label} readings: {dissent_items}{unavailable_clause}.',
    'A3R6': 'The exposure, re-admission and matched-support subsets are descriptive and carry no decision class.',
    'A3T7': 'Robustness lists the inferential checks that disagree with the primary reading (one-day and seven-day intervals, small-sample HLN calibration, HAC7, three-seed mean); design sensitivities are listed in Table {table_ref}.',
    'A3R_BATCH': 'The new-fit secondary arms use one seed by design, so their three-seed check is not available and their best robustness label is not fully checked.',
    # B
    'A3B3': 'Headline intervals are family-adjusted: {level}% two-sided, that is 1 − 0.05/{m} for the {m} pre-specified comparisons of the {task_label} family; tables also give the per-contrast 95% intervals.',
    'A3B4': 'Every exclusion bound is the conditional one-sided bootstrap bound max(0, −lower endpoint) of a labelled interval: family-adjusted for the primary, combination, absolute-error, pre-dispatch and label-replacement families, and unadjusted for single secondary comparisons; per-contrast 95% intervals of family members appear as intervals only.',
    'A3B5': 'Frozen per-contrast reading (nominal 95% interval, not family-adjusted; the headline bound is the family-adjusted one):',
    # P
    'A3P1': 'A planted-signal check on pre-confirmation windows of the same size added to the activity reference a column equal to the realised target on a random share of region-days (news) or region-hours (notices) and missing elsewhere. Detection rates below refer to this sparse, exact planting scheme and are described by the realised effect, because a real content signal with the same realised effect could be easier or harder to detect.',
    'A3P1T': 'For {task_label}, at twice the minimum detectable effect the column was detected in {k} of {R} replicates (detection rate under this planting scheme; Clopper–Pearson 95% interval [{lo}, {hi}]), with a median realised change of {delta}% of the reference error and a median uptake of {uptake}% of the planted information; the permuted null column was detected in {k0} of {R0} replicates (Clopper–Pearson lower bound {lo0}% against the nominal {nominal}%).',
    'A3P2': 'a planted signal of twice the minimum detectable effect was detected in {k} of {R} replicates (median realised change {delta}%)',
    'A3PA_SENS': 'these null readings are precision-limited, because a planted signal of twice the minimum detectable effect was detected in only {k} of {R} replicates',
    'A3PA_SIZE': 'the exclusion bound may be too narrow, because the permuted null column was detected in {k0} of {R0} replicates, more often than the nominal {nominal}% allows',
    'A3PB_SIZE': 'its reliability may be overstated, because the permuted null column was detected in {k0} of {R0} replicates, more often than the nominal {nominal}% allows',
    'A3PS_SENS': 'Because the planted signal of twice the minimum detectable effect was detected in only {k} of {R} replicates, the null readings of the {task_label} family are precision-limited: the pipeline may miss increments of that size.',
    'A3PS_SIZE': 'Because the permuted null column was detected in {k0} of {R0} replicates, more often than the nominal {nominal}% allows, the test may reject too often and the {task_label} exclusion bounds may be too narrow.',
    'A3PS_POWER': 'The planted signal of twice the minimum detectable effect was detected in only {k} of {R} replicates for {task_label}; this concerns the power of the test, does not change the reliable increment, and makes the null readings of this family precision-limited.',
    'A3PS_SIZEB': 'Because the permuted null column was detected in {k0} of {R0} replicates, more often than the nominal {nominal}% allows, the test may reject too often, and the reliable {task_label} increments are qualified accordingly.',
    'A3PS_ATT': 'For {task_label}, the learner used less than half of the planted information at every strength, so information carried by the inputs may be under-used by this learner.',
    'A3PS_NOTRUN': 'The planted-signal check was not run for {task_label} ({reason}); the sensitivity of the test pipeline is not documented for this task.',
    # Q
    'A3Q1': 'Under the absolute-error training objective, {arm_words} {class_phrase} the article activity reference trained with the same objective ({effect}% of the reference error, family-adjusted 97.5% interval [{lo}, {hi}]%, Holm-adjusted {p} within that secondary family), unlike the primary reading; this secondary result does not change the primary reading.',
    'A3Q2': 'With pre-dispatch demand and semi-scheduled generation forecasts as additional inputs, {arm_words} {class_phrase} the article activity reference with the same inputs ({effect}% of the reference error, family-adjusted 97.5% interval [{lo}, {hi}]%, Holm-adjusted {p} within that secondary family), unlike the primary reading; this secondary result does not change the primary reading.',
    'A3Q5': 'The primary increment of {primary_arm} was not detected {condition}; it is stated relative to the pre-specified learner and information set.',
    # AB
    'A3Y1': 'In an internally pre-specified 2025 day-ahead test, adding extracted news labels to the numerical reference changed its mean absolute error by +0.18% (+0.0928 AUD/MWh; one-sided Diebold–Mariano p = 0.61).',
    'A3Y2': 'In the same year, price-only LEAR, added after that test, had a 21.3% lower mean absolute error than the numerical reference (39.73 against 50.51 AUD/MWh).',
    'A3AB_NULL': 'For {task_label}, no structured representation improved on the {activity} reference ({clauses}; family-adjusted {level}% intervals); improvements larger than {X}% of the reference error were excluded at the family-adjusted one-sided {tail}% level, {below_or_above} {S_phrase}{context}{pc}.',
    'A3AB_CL': '{arm_words} {effect}% [{lo}, {hi}], Holm-adjusted {p}, {robust_word}{flags}',
    'A3AB_CLD': '{arm_words} reliably worse by {effect}% [{lo}, {hi}], Holm-adjusted {p}, {robust_word}{flags}',
    'A3AB_CLX': '{arm_words} not evaluable ({reason})',
    'A3AB_CTX': ', and {hist_cmp} the earlier notice text gains of 0.097% and 0.154%',
    'A3AB_INC': 'For {task_label}, {arm_words} improved on the {activity} reference by {abs_effect}% of the reference error ({abs_aud} AUD/MWh; family-adjusted {level}% interval [{lo}, {hi}]%, Holm-adjusted {p}){zero_short}; it was {robust_word} and {attribution_status}; {sesoi_word}; {benchmark_word}{flags}.',
    'A3AB_OTHER': '{Arm_words} showed no reliable increment ({effect}% [{lo}, {hi}], Holm-adjusted {p}, {robust_word}{flags}).',
    'A3AB_OTHERD': '{Arm_words} performed reliably worse ({effect}% [{lo}, {hi}], Holm-adjusted {p}, {robust_word}{flags}).',
    'A3AB_OTHERX': '{Arm_words} could not be evaluated ({reason}).',
    'A3AB_INCOMPLETE': 'The {task_label} confirmation is incomplete because {reason}; no confirmation reading is reported for it, and this is not a null result.',
    'A3CO_Y': "The numerical reference was itself weaker than a standard price benchmark: in 2025, price-only LEAR had a 21.3% lower mean absolute error (39.73 against 50.51 AUD/MWh), and adding extracted news labels changed the reference's error by +0.18% in an internally pre-specified test.",
    # U, V, W
    'A3U1N': 'On the {n} days whose prices had no recorded or unknown prior use ({ranges}), {arm} differed from the {activity} reference by {effect}% (one-day 95% interval [{lo}, {hi}]%); with seven days no p value is reported, and this small descriptive subset does not change any reading.',
    'A3V1': 'On the {n} issue days whose admitted articles included no re-admitted older article, {arm} differed from the {activity} reference by {effect}% (one-day 95% interval [{lo}, {hi}]%, DM {p}); this descriptive subset does not change any reading.',
    'A3W1': 'On the {matched_keys} keys ({matched_share}%) of {n} days where the activity-matched reassignment control found a donor, {arm} differed from the {activity} reference by {effect}% (one-day 95% interval [{lo}, {hi}]%, DM {p}); this descriptive recomputation places the primary contrast on the support of the content control and does not change any reading.',
    'A3W0': 'The activity-matched reassignment control found matched keys on only {n} days, too few for the frozen seven-day rule, so the primary contrasts are not recomputed on its support.',
}
# Word lists and fixed phrases (Appendix A3, lists W and X; verbatim).
ARM_WORDS = {'news': {'L_count': 'the label-count representation', 'L_chen': 'the structured-attribute embedding',
                      'M': 'the article activity reference', 'N': 'the numerical reference',
                      'E_raw': 'the raw-text embedding', 'W2_D': 'the word-frequency representation', 'LEAR': 'price-only LEAR'},
             'notice': {'L14': 'the event-state representation', 'L_Laz': 'the message, failure and fuel-group counts',
                        'L_chen_notice': 'the structured-attribute notice embedding', 'M_notice': 'the notice activity reference',
                        'N': 'the numerical reference', 'R': 'the rule parser', 'T': 'the word-frequency representation'}}
S_PHRASE = {'news': 'the 3.8% smallest effect size of interest', 'notice': 'the 0.5% historical-effect reference'}
BENCHMARK_WORDS = {'news': 'price-only LEAR', 'notice': 'the reference augmented with five-minute pre-dispatch prices'}
CLASS_WORDS = {IMP: 'a reliable increment', DET: 'a reliable deterioration', NULL: 'no reliable increment', NE: 'not evaluable'}
CLASS_PHRASE = {IMP: 'improved on', NULL: 'showed no reliable increment over', DET: 'performed reliably worse than'}
SENSITIVITY_NAMES = {'label_replacement': 'independently re-extracted test-period labels', 'first_chunk': 'first-chunk encoding',
                     'window_24h': 'the 24-hour article window', 'official_cap': 'the official price-cap re-clip',
                     'drop_first_seven': 'dropping the first seven notice days', 'l1_family': 'the absolute-error training objective',
                     'pd_family': 'pre-dispatch forecasts as additional inputs'}
BATCH_SEED_REASON = 'the batch was fitted with one seed by design'
SESOI_CLASS_WORDS = {'BEYOND': 'its interval lies wholly beyond {S_phrase}',
                     'ABOVE': 'its point estimate exceeds {S_phrase} but its interval straddles it',
                     'BELOWPT': 'its point estimate is below {S_phrase} and its interval straddles it',
                     'BELOW': 'its interval lies wholly below {S_phrase}'}
ATTRIBUTION_STATUS = {'C1': 'an increment over the {activity} reference only, not shown to be LLM-specific',
                      'C4': 'content-specific but not shown to be LLM-specific', 'C5': 'content-specific and LLM-specific'}
CHEAP_PIECES = {'beaten': 'outperformed {list}', 'not_beaten': 'did not outperform {list}', 'worse': 'performed reliably worse than {list}'}
MDE_CMP = ('below', 'at or above')
HIST_CMP = ('below both of', 'between', 'at or above both of')
PUB_CMP = ('smaller than every published reduction', 'within the range of the published reductions',
           'larger than every published reduction')
CODE_PHRASES = {
    'E3_SECONDARY_JOINT_CONFIRMED': 'the earlier positive notice finding was reproduced: both pre-specified pre-dispatch-price comparisons showed a reliable favourable difference',
    'E3_SECONDARY_JOINT_NOT_CONFIRMED': 'the earlier positive notice finding was not reproduced: {failed_list} did not show a reliable favourable difference',
    'E3_SECONDARY_JOINT_NOT_EVALUABLE': 'the two pre-specified pre-dispatch-price comparisons could not both be evaluated',
    'SEED_SIGN_ONLY': 'the three-seed mean had the opposite sign but the same decision class'}
E3_COMPARISON_NAMES = {('NPL', 'NP'): 'the comparison with the pre-dispatch-price reference',
                       ('NPL', 'NPP'): 'the comparison with 28-day-shifted notices'}
NOTICE_CLOCK_LIMITATION = ('All 725 notices dated 1 August to 30 September 2026 use the website creation date, a surrogate not verified '
                           'as the publication time, as their availability clock, whereas the training notices use the official '
                           'archive clocks; on 65 March-May 2026 notices that carry both clocks the two agree to the second. No '
                           'pre-specified contrast separates this clock-type change.')
# Constants fixed in the addendum (sections S and A).
TASK_LABEL = {'news': 'day-ahead news', 'notice': 'market notices'}
DOCUMENTS = A2.DOCUMENTS
ACTIVITY = A2.ACTIVITY
LEVEL_TEXT, TAIL_TEXT = A2.LEVEL_TEXT, A2.TAIL_TEXT
SESOI = A2.SESOI
FAMILIES = A2.FAMILIES
MDE_PERCENT = {'news': 3.11, 'notice': 0.124}
HISTORICAL_NOTICE_GAINS = (0.097, 0.154)          # |T - N| % of N's MAE: January-February 2026, development (supplement S3)
PUBLISHED_RELATIVE_CHANGES = {                      # % reduction of MAE, computed from the reported pairs (tab:ms14-published-gains)
    'Huang2026': [(20.76, 20.25)], 'Chen2026': [(27.27, 23.48)], 'Lu2025': [(69.34, 63.10), (50.58, 45.45)],
    'Wang2025': [(0.304, 0.296), (0.301, 0.298), (0.292, 0.296)]}
CHEAP_A3 = {'news': {'L_count': ('E_raw', 'W2_D'), 'L_chen': ('E_raw', 'W2_D')},
            'notice': {'L14': ('R', 'T'), 'L_Laz': ('R', 'T'), 'L_chen_notice': ('R', 'T')}}
A3_NEW_CONTRASTS = {'news': (('L_count', 'E_raw'), ('L_count', 'W2_D')),
                    'notice': (('L14', 'R'), ('L14', 'T'), ('L_Laz', 'R'), ('L_Laz', 'T'))}
TEXT_VS_NO_TEXT = (('L_count', 'N'), ('L_chen', 'N'), ('M', 'N'))
PC_TIER = {'news': 'N2', 'notice': 'notice'}
PC_M = {'news': 2, 'notice': 3}
SENSITIVITY_ORDER = {'news': ('label_replacement', 'first_chunk', 'window_24h', 'l1_family', 'pd_family'),
                     'notice': ('label_replacement', 'first_chunk', 'official_cap', 'drop_first_seven')}
BATCH_PAIRS = {'l1_family': {('L_count', 'M'): ('L_count_L1', 'M_L1'), ('L_chen', 'M'): ('L_chen_L1', 'M_L1')},
               'pd_family': {('L_count', 'M'): ('L_count_PD', 'M_PD'), ('L_chen', 'M'): ('L_chen_PD', 'M_PD')}}
BATCH_FAMILY_KEY = {'l1_family': 'L1', 'pd_family': 'PD'}
BATCH_FAMILY_NAME = {'l1_family': 'absolute-error objective', 'pd_family': 'pre-dispatch input'}
BATCH_CONDITION = {'l1_family': 'under the absolute-error training objective',
                   'pd_family': 'with pre-dispatch forecasts as additional inputs'}
STATE_REASON = {'NOT_RUN_BUDGET': 'not run within the fitting budget', 'NOT_RUN_INPUT_UNAVAILABLE': 'its input data were unavailable',
                'NOT_RUN_PARITY_FAILED': 'the reproduction check failed', 'ABSENT': 'no result was available at the time of the fill'}


# ---------------------------------------------------------------- small helpers
join_list = A2.join_list
finite = A2.finite


def cap(text):
    return text[:1].upper() + text[1:] if text else text


def holm_adjust(p_values):
    """Exact copy of the frozen CONF `scoring.holm` (undefined p keeps its slot as 1)."""
    raw = [1.0 if p is None else float(p) for p in p_values]
    order = sorted(range(len(raw)), key=lambda i: raw[i])
    adjusted, running = [None] * len(raw), 0.0
    for rank, index in enumerate(order):
        running = max(running, (len(raw) - rank) * raw[index])
        adjusted[index] = min(1.0, running)
    return [None if p is None else float(adjusted[i]) for i, p in enumerate(p_values)]


def interval_parts(row, interval_key='interval_family_one_day'):
    one = row.get('interval95_one_day')
    d = A2.percent_decimals(None if one is None else one[1] - one[0])
    lo, hi = A2.fmt_interval(row.get(interval_key), d)
    return d, lo, hi


def aud(value):
    return 'undefined' if not finite(value) else f'{abs(float(value)):.4f}'


PLURAL_NAMES = {'independently re-extracted test-period labels', 'pre-dispatch forecasts as additional inputs'}


def was_were(items):
    items = list(items)
    return 'was' if len(items) == 1 and items[0] not in PLURAL_NAMES else 'were'


# ---------------------------------------------------------------- R1/R2: robustness, class-only agreement
def class_agrees(primary_cls, other_cls):
    """Rule R2: agreement is equality of decision class; for no-rejection readings the sign is ignored."""
    if primary_cls not in CLASSES or other_cls not in CLASSES:
        return None
    return primary_cls == other_cls


def robustness_a3(cls, one_day, seven_day, hln_cls, hac7_cls, three_seed_cls, seven_day_state=None, batch=False,
                  seed_reason=None):
    """A2 R.2 five checks with the A3 class-only seed rule; batch seed reason per K2."""
    if cls not in CLASSES:
        return {'label': 'NOT_EVALUABLE', 'checks': {}, 'dissent': [], 'unavailable': [], 'sentence': None}
    checks = {'one_day': A2.interval_agrees(cls, one_day),
              'hln': class_agrees(cls, hln_cls), 'hac7': class_agrees(cls, hac7_cls),
              'seven_day': None if seven_day_state == 'NOT_INFORMATIVE_ONE_ADMISSIBLE_SEVEN_DAY_BLOCK' else A2.interval_agrees(cls, seven_day),
              'three_seed': None if batch else class_agrees(cls, three_seed_cls)}
    dissent = [k for k in A2.CHECK_ORDER if checks[k] is False]
    unavailable = [k for k in A2.CHECK_ORDER if checks[k] is None]
    reasons = dict(A2.UNAVAILABLE_PHRASE)
    if batch:
        reasons['three_seed'] = BATCH_SEED_REASON
    r3 = None
    if unavailable:
        r3 = A2.SENTENCES['R3'].format(unavailable_list=join_list(A2.CHECK_NAME[k] for k in unavailable),
                                       was_were=was_were(unavailable), reason='; '.join(reasons[k] for k in unavailable))
    if dissent:
        label = 'FRAGILE'
        text = A2.SENTENCES['R2'].format(dissent_list=join_list(A2.CHECK_NAME[k] for k in dissent)) + ('; ' + r3 if r3 else '')
    elif unavailable:
        label, text = 'NOT_FULLY_CHECKED', r3
    else:
        label, text = 'ROBUST', A2.SENTENCES['R1']
    short = {'ROBUST': 'robust', 'NOT_FULLY_CHECKED': 'not fully checked'}.get(
        label, 'fragile (' + join_list(SHORT_CHECK[k] for k in dissent) + ')')
    return {'label': label, 'checks': checks, 'dissent': dissent, 'unavailable': unavailable, 'sentence': text,
            'short_word': short, 'recorded_reason': seed_reason}


SHORT_CHECK = {'one_day': 'one-day interval', 'hln': 'HLN', 'hac7': 'HAC7', 'seven_day': 'seven-day interval',
               'three_seed': 'three-seed mean'}


def seed_sign_only(primary_cls, primary_mean, three_seed_cls, three_seed_mean):
    """A1 SEED_FRAGILE triggered by sign alone (same class): reported with the X phrase, not as fragile."""
    if primary_cls not in CLASSES or three_seed_cls not in CLASSES or primary_cls != three_seed_cls:
        return False
    s = lambda v: None if not finite(v) else (v > 0) - (v < 0)
    return s(primary_mean) != s(three_seed_mean)


# ---------------------------------------------------------------- R4: Holm rejection with a family interval covering zero
def zero_clause(source, cls, family_interval):
    if cls not in (IMP, DET) or family_interval is None or not all(finite(v) for v in family_interval):
        return ''
    lo, hi = float(family_interval[0]), float(family_interval[1])
    if lo <= 0.0 <= hi:
        return SENTENCES['A3Z'].format(level=LEVEL_TEXT[source], direction='increment' if cls == IMP else 'deterioration')
    return ''


def covers_zero(family_interval):
    return family_interval is not None and all(finite(v) for v in family_interval) and family_interval[0] <= 0.0 <= family_interval[1]


# ---------------------------------------------------------------- C5 / S: SESOI classes and comparison values
def sesoi_increment_class(effect, family_interval, S):
    """Lakens et al. 2018 Fig. 1: interval of the improvement I = -effect against S (family-adjusted interval)."""
    if not finite(effect) or family_interval is None or not all(finite(v) for v in family_interval):
        return None
    i_low, i_high, i_point = -float(family_interval[1]), -float(family_interval[0]), -float(effect)
    if i_low > S:
        return 'BEYOND'
    if i_high < S:
        return 'BELOW'
    return 'ABOVE' if i_point >= S else 'BELOWPT'


def sesoi_clause(source, cls_key):
    key = {'BEYOND': 'A3S_BEYOND', 'ABOVE': 'A3S_ABOVE', 'BELOWPT': 'A3S_BELOWPT', 'BELOW': 'A3S_BELOW'}[cls_key]
    return SENTENCES[key].format(S_phrase=S_PHRASE[source], S=SESOI[source], tail=TAIL_TEXT[source])


def sesoi_null_sentence(source, family_interval, d):
    if family_interval is None or not all(finite(v) for v in family_interval):
        return None, None
    x = max(0.0, -float(family_interval[0]))
    key = 'A3D1' if x < SESOI[source] else 'A3D2'
    return key, SENTENCES[key].format(X=A2.branch_safe_bound(x, d, SESOI[source]), tail=TAIL_TEXT[source],
                                      S_phrase=S_PHRASE[source])


def mde_cmp(x, source):
    return MDE_CMP[0] if x < MDE_PERCENT[source] else MDE_CMP[1]


def hist_cmp(x):
    lo, hi = HISTORICAL_NOTICE_GAINS
    return HIST_CMP[0] if x < lo else (HIST_CMP[1] if x < hi else HIST_CMP[2])


def published_reductions():
    return {k: [round(100.0 * (a - b) / a, 2) for a, b in pairs] for k, pairs in PUBLISHED_RELATIVE_CHANGES.items()}


def pub_cmp(x):
    values = [v for vs in published_reductions().values() for v in vs]
    positive = [v for v in values if v > 0]
    if x < min(positive):
        return PUB_CMP[0]
    return PUB_CMP[1] if x <= max(positive) else PUB_CMP[2]


# ---------------------------------------------------------------- C: attribution with LLM-specific status
def cheap_clause(source, arm, cheap_reports):
    computed, unavailable = {}, []
    for comp in CHEAP_A3[source][arm]:
        state, fav, unfav = A2.favours(cheap_reports.get((arm, comp)))
        if state == 'COMPUTED':
            computed[comp] = 'beaten' if fav else ('worse' if unfav else 'not_beaten')
        else:
            unavailable.append(comp)
    if not computed:
        return SENTENCES['A3CH0'].format(documents=DOCUMENTS[source]), computed, unavailable
    pieces = [CHEAP_PIECES[kind].format(list=join_list(A2.COMPARATOR_NAME[c] for c, v in computed.items() if v == kind))
              for kind in ('beaten', 'not_beaten', 'worse') if kind in computed.values()]
    text = SENTENCES['A3CH'].format(documents=DOCUMENTS[source], cheap_list=join_list(pieces))
    if unavailable:
        text += '; ' + join_list(A2.COMPARATOR_NAME[c] for c in unavailable) + ' ' + was_were(unavailable) + ' not available'
    return text, computed, unavailable


def attribution_a3(source, arm, cls, secondary, cheap_reports, matched):
    """A2 C logic with A3C1-A3C3 (pre-specified wording, explicit LLM status, cheap-text clause)."""
    out = A2.attribution(source, arm, cls, secondary, cheap_reports, matched)
    activity = ACTIVITY[source]
    if cls != IMP:
        out.update(a3_form=None, status_word=None)
        return out
    cheap, computed, unavailable = cheap_clause(source, arm, cheap_reports)
    out['cheap_text'] = {'computed': computed, 'unavailable': unavailable, 'clause': cheap}
    label = out['label']
    if label == 'ACTIVITY_REFERENCE_INCREMENT_NO_CONTROL':
        out.update(a3_form='A3C1', sentence=SENTENCES['A3C1'].format(activity=activity, cheap=cheap))
    elif label == 'ACTIVITY_REFERENCE_INCREMENT_CONTROLS_FAILED':
        failed = join_list(A2.CONTROL_NAME[k.split('-')[1]] for k in out['failed_controls'])
        out.update(a3_form='A3C2', sentence=SENTENCES['A3C2'].format(activity=activity, failed_list=failed, cheap=cheap))
    elif label == 'CONTENT_NOT_ASSESSABLE':
        out.update(a3_form='A3C3', sentence=SENTENCES['A3C3'].format(activity=activity, reason=out['reason'], cheap=cheap))
    elif label == 'CONTENT_SPECIFIC_NOT_LLM_SPECIFIC':
        out['a3_form'] = 'C4'
    elif label == 'LLM_SPECIFIC':
        out['a3_form'] = 'C5'
    status_key = out['a3_form'] if out['a3_form'] in ('C4', 'C5') else 'C1'
    out['status_word'] = ATTRIBUTION_STATUS[status_key].format(activity=activity)
    return out


# ---------------------------------------------------------------- K1: positive control
def clopper_lower_ok(cp, threshold):
    return cp is not None and cp[0] >= threshold


def pc_state(source, result):
    """Re-derive the frozen A1 readings for one task (tier N2 or notice) and require agreement."""
    if result is None:
        return {'state': 'NOT_RUN', 'reason': STATE_REASON['ABSENT']}
    tier = PC_TIER[source]
    reading = (result.get('readings') or {}).get(tier)
    if reading is None or reading == 'NOT_RUN':
        return {'state': 'NOT_RUN', 'reason': 'the frozen run recorded no result for this task'}
    rows = {float(r['mult']): r for r in result['summary'] if r['task'] == source and r['tier'] == tier}
    top, null = rows.get(2.0), rows.get(0.0)
    if top is None or null is None:
        raise ValueError('Positive-control summary lacks the f = 2 or the null row: ' + source)
    sens = bool(top['detection_rate'] >= 0.80 and top['detection_cp95'][0] >= 0.50)
    nominal = 0.05 / (2 * PC_M[source])
    inflated = bool(null['detection_cp95'][0] > nominal)
    if sens != bool(reading.get('PIPELINE_SENSITIVE_AT_2xMDE', False)) or inflated != bool(reading.get('SIZE_INFLATED')):
        raise ValueError('Re-derived positive-control reading differs from the frozen reading: ' + source)
    state = {(True, False): 'PASS', (False, False): 'SENSITIVITY_FAILS', (True, True): 'SIZE_FAILS',
             (False, True): 'BOTH_FAIL'}[(sens, inflated)]
    return {'state': state, 'k': int(top['detected']), 'R': int(top['replicates']), 'cp': list(top['detection_cp95']),
            'delta': top.get('delta_pct_median'), 'uptake': top.get('uptake_median'), 'k0': int(null['detected']),
            'R0': int(null['replicates']), 'lo0': null['detection_cp95'][0], 'nominal': nominal,
            'attenuates': bool(reading.get('PIPELINE_ATTENUATES'))}


def pc_fields(source, pc):
    return dict(task_label=TASK_LABEL[source], k=pc['k'], R=pc['R'], lo=f"{pc['cp'][0]:.3f}", hi=f"{pc['cp'][1]:.3f}",
                delta=A2.fmt_effect(pc['delta'], 3), uptake='undefined' if not finite(pc['uptake']) else f"{100 * pc['uptake']:.1f}",
                k0=pc['k0'], R0=pc['R0'], lo0=f"{100 * pc['lo0']:.2f}", nominal=TAIL_TEXT[source])


def pc_placements(source, scenario, pc):
    """Table K1. scenario 'A' (no reliable increment) or 'B'."""
    out = {'section6': [], 'abstract_clauses': [], 'increment_flag': None, 'null_flag': '', 'task_bound_clauses': []}
    if pc['state'] == 'NOT_RUN':
        out['section6'].append(SENTENCES['A3PS_NOTRUN'].format(task_label=TASK_LABEL[source], reason=pc['reason']))
        return out
    f = pc_fields(source, pc)
    out['section6'].append(SENTENCES['A3P1T'].format(**f))
    sens_fail = pc['state'] in ('SENSITIVITY_FAILS', 'BOTH_FAIL')
    size_fail = pc['state'] in ('SIZE_FAILS', 'BOTH_FAIL')
    if scenario == 'A':
        if pc['state'] == 'PASS':
            out['abstract_clauses'].append(SENTENCES['A3P2'].format(**f))
        if sens_fail:
            out['abstract_clauses'].append(SENTENCES['A3PA_SENS'].format(**f))
            out['task_bound_clauses'].append(SENTENCES['A3PA_SENS'].format(**f))
            out['section6'].append(SENTENCES['A3PS_SENS'].format(**f))
        if size_fail:
            out['abstract_clauses'].append(SENTENCES['A3PA_SIZE'].format(**f))
            out['task_bound_clauses'].append(SENTENCES['A3PA_SIZE'].format(**f))
            out['section6'].append(SENTENCES['A3PS_SIZE'].format(**f))
    else:
        if sens_fail:
            out['section6'].append(SENTENCES['A3PS_POWER'].format(**f))
            out['null_flag'] = ', precision-limited'
        if size_fail:
            out['increment_flag'] = SENTENCES['A3PB_SIZE'].format(**f)
            out['section6'].append(SENTENCES['A3PS_SIZEB'].format(**f))
    if pc.get('attenuates'):
        out['section6'].append(SENTENCES['A3PS_ATT'].format(task_label=TASK_LABEL[source]))
    return out


# ---------------------------------------------------------------- R1 layer 2: design sensitivities
def class_under_family(pairs, primary, changed, holm=holm_adjust):
    """Holm over the primary family with the changed contrasts replaced: {pair: class} for the changed pairs."""
    means, ps = [], []
    for pair in pairs:
        mean, p = changed.get(pair, primary[pair])
        means.append(mean); ps.append(p)
    adjusted = holm(ps)
    return {pair: A2.decision_class(m, p) for pair, m, p in zip(pairs, means, adjusted) if pair in changed}


def report_mean_p(report):
    dm = report.get('dm_p1') or {}
    mean = dm.get('mean_difference', report.get('mean_difference'))
    p = dm.get('p_two_sided', report.get('p_two_sided'))
    return mean, p


def sensitivity_states(source, primary_rows, files, batch=None, label=None):
    """Per primary contrast and sensitivity: SAME / DIFFERENT / NOT_AVAILABLE / NOT_APPLICABLE with the class."""
    pairs = list(FAMILIES[source])
    primary = {(r['arm'], r['reference']): (r.get('mean_difference'), r.get('p_two_sided')) for r in primary_rows}
    pcls = {(r['arm'], r['reference']): r.get('decision') for r in primary_rows}
    result = {pair: {} for pair in pairs}

    def put(name, classes, applicable):
        for pair in pairs:
            if pair not in applicable:
                result[pair][name] = {'state': 'NOT_APPLICABLE'}
            elif classes is None or pair not in classes or classes[pair] not in CLASSES or pcls[pair] not in CLASSES:
                result[pair][name] = {'state': 'NOT_AVAILABLE'}
            else:
                result[pair][name] = {'state': 'SAME' if classes[pair] == pcls[pair] else 'DIFFERENT', 'class': classes[pair]}

    # label replacement (A2LABEL; own Holm, re-derived from mean and Holm p)
    lab = None
    if label and label.get('state') == 'A2LABEL_SCORED':
        lab = {(r['arm'], r['reference']): A2.decision_class(r.get('mean_difference'), r.get('holm_p', r.get('p_holm')))
               if r.get('holm_p', r.get('p_holm')) is not None else r.get('decision')
               for r in label['families'][source]['reports']}
    put('label_replacement', lab, pairs)
    # first-chunk encoding (only the embedding contrast changes)
    content = (A2.CONTENT_ARM[source], A2.REFERENCE[source])
    fl = files.get('first_L')
    classes = None
    if fl and fl.get('reports'):
        rep = next((r for r in fl['reports'] if (r['arm'], r['reference']) == content), None)
        if rep is not None and all(finite(v) for v in report_mean_p(rep)):
            classes = class_under_family(pairs, primary, {content: report_mean_p(rep)})
    put('first_chunk', classes, [content])
    if source == 'news':
        w = files.get('window_24h')
        classes = None
        if w and w.get('reports'):
            changed = {(r['arm'], r['reference']): report_mean_p(r) for r in w['reports'] if (r['arm'], r['reference']) in pairs}
            if len(changed) == len(pairs) and all(all(finite(v) for v in mp) for mp in changed.values()):
                classes = class_under_family(pairs, primary, changed)
        put('window_24h', classes, pairs)
        for fam in ('l1_family', 'pd_family'):
            classes = None
            fam_rep = ((batch or {}).get('families') or {}).get(BATCH_FAMILY_KEY[fam]) or {}
            if fam_rep.get('state') == 'COMPUTED':
                by = {(r['arm'], r['reference']): r for r in fam_rep['reports']}
                classes = {}
                for pair, bpair in BATCH_PAIRS[fam].items():
                    r = by.get(bpair)
                    classes[pair] = None if r is None else A2.decision_class(r.get('mean_difference'), r.get('holm_p'))
            put(fam, classes, pairs)
    else:
        rc = files.get('official_cap')
        classes = None
        if rc and rc.get('reports'):
            classes = {(r['arm'], r['reference']): r.get('primary_decision') for r in rc['reports']}
        put('official_cap', classes, pairs)
        d7 = files.get('drop_first_seven')
        classes = None
        if d7 and d7.get('reports'):
            changed = {(r['arm'], r['reference']): report_mean_p(r) for r in d7['reports']}
            if all(pair in changed for pair in pairs) and all(all(finite(v) for v in changed[pair]) for pair in pairs):
                classes = class_under_family(pairs, primary, changed)
        put('drop_first_seven', classes, pairs)
    return result


def layer2_sentence(source, states, arm_symbol=None):
    """A3R5a / A3R5b for one task."""
    arm_symbol = arm_symbol or (lambda a: a)
    names = SENSITIVITY_ORDER[source]
    dissent, available, unavailable = [], [], []
    for name in names:
        rows = [(pair, st[name]) for pair, st in states.items() if st[name]['state'] != 'NOT_APPLICABLE']
        if not rows:
            continue
        if all(s['state'] == 'NOT_AVAILABLE' for _, s in rows):
            unavailable.append(SENSITIVITY_NAMES[name]); continue
        available.append(SENSITIVITY_NAMES[name])
        for pair, s in rows:
            if s['state'] == 'DIFFERENT':
                dissent.append(f"{arm_symbol(pair[0])} under {SENSITIVITY_NAMES[name]} ({CLASS_WORDS[s['class']]})")
    clause = ('; ' + join_list(unavailable) + ' ' + was_were(unavailable) + ' not available') if unavailable else ''
    if dissent:
        return 'A3R5b', SENTENCES['A3R5b'].format(task_label=TASK_LABEL[source], dissent_items='; '.join(dissent),
                                                  unavailable_clause=clause)
    if not available:
        return 'A3R5a', None
    return 'A3R5a', SENTENCES['A3R5a'].format(available_list=join_list(available), task_label=TASK_LABEL[source],
                                              unavailable_clause=clause)


# ---------------------------------------------------------------- K2: secondary qualifiers
def label_change(pair, states):
    s = states.get(pair, {}).get('label_replacement', {})
    return s.get('class') if s.get('state') == 'DIFFERENT' else None


def batch_sentences(source, primary_rows, batch):
    """A3Q1/A3Q2 for differing classes, A3Q5 relation sentences, A7 for families not run (news only)."""
    out = {'qualifiers': [], 'relations': [], 'not_run': []}
    if source != 'news':
        return out
    pcls = {(r['arm'], r['reference']): r for r in primary_rows}
    for fam, key in (('l1_family', 'A3Q1'), ('pd_family', 'A3Q2')):
        fam_rep = ((batch or {}).get('families') or {}).get(BATCH_FAMILY_KEY[fam])
        if not fam_rep:
            continue                      # batch result not yet available: FILL3's pending sentence, no A7
        if fam_rep.get('state') != 'COMPUTED':
            state = fam_rep.get('state')
            reason = STATE_REASON.get(state) or fam_rep.get('reason') or 'not run'
            out['not_run'].append(A2BATCH_A7.format(family_name=BATCH_FAMILY_NAME[fam], reason=reason))
            continue
        by = {(r['arm'], r['reference']): r for r in fam_rep['reports']}
        for pair, bpair in BATCH_PAIRS[fam].items():
            r, p = by.get(bpair), pcls.get(pair)
            if r is None or p is None:
                continue
            bcls = A2.decision_class(r.get('mean_difference'), r.get('holm_p'))
            if bcls in CLASSES and p.get('decision') in CLASSES and bcls != p['decision']:
                one = (r.get('bootstrap') or {}).get('1', {})
                d = A2.percent_decimals(None if not one.get('interval95_percent') else one['interval95_percent'][1] - one['interval95_percent'][0])
                lo, hi = A2.fmt_interval(one.get('interval_family_adjusted_percent'), d)
                out['qualifiers'].append(SENTENCES[key].format(
                    arm_words=ARM_WORDS[source][pair[0]], class_phrase=CLASS_PHRASE[bcls],
                    effect=A2.fmt_effect(r.get('effect_percent_reference_mae', one.get('effect_percent_reference_mae')), d),
                    lo=lo, hi=hi, p=A2.display_p(r.get('holm_p'))))
                if p['decision'] == IMP and bcls != IMP:
                    out['relations'].append(SENTENCES['A3Q5'].format(primary_arm=pair[0], condition=BATCH_CONDITION[fam]))
    return out


A2BATCH_A7 = 'The {family_name} secondary family was not run ({reason}).'      # A2BATCH_SPEC.md section 7, A7 (kept)


def batch_robustness(batch):
    """Rule K2/R2 for the L1 and PD families: class-only checks, three-seed check unavailable by design."""
    out = {}
    for fam, key in BATCH_FAMILY_KEY.items():
        rep = ((batch or {}).get('families') or {}).get(key) or {}
        if rep.get('state') != 'COMPUTED':
            continue
        for r in rep['reports']:
            cls = A2.decision_class(r.get('mean_difference'), r.get('holm_p'))
            hln = A2.decision_class(r.get('mean_difference'), r.get('hln_holm_p'))
            hac = A2.decision_class(r.get('mean_difference'), r.get('hac7_holm_p'))
            boot = r.get('bootstrap') or {}
            out[f"{key}:{r['arm']}-{r['reference']}"] = robustness_a3(
                cls, (boot.get('1') or {}).get('interval95_percent'), (boot.get('7') or {}).get('interval95_percent'),
                hln, hac, None, batch=True)
    return out


# ---------------------------------------------------------------- headline, abstract and conclusion
def combination_text(source, combo_row, primary_cls):
    """A2 S-clauses with A3S2 in place of S2."""
    if combo_row is None:
        return as_clause(A2.SENTENCES['S7'].format(benchmark=A2.BENCHMARK_NAME[source],
                                                   reason='the combination contrast was not computed')), 'S7'
    key, text = combo_row.get('clause_id'), combo_row.get('sentence')
    if key == 'S7':
        text = as_clause(text)
    if key == 'S2':
        d, lo, hi = interval_parts({'interval95_one_day': combo_row['bootstrap']['1'].get('interval95_percent'),
                                    'interval_family_one_day': combo_row['bootstrap']['1'].get('interval_family_adjusted_percent')})
        text = SENTENCES['A3S2'].format(benchmark=A2.BENCHMARK_NAME[source], effect=A2.fmt_effect(combo_row.get('effect_percent_reference_mae'), d),
                                        level=LEVEL_TEXT[source], lo=lo, hi=hi, p=A2.display_p(combo_row.get('holm_p')))
    return text, key


def as_clause(sentence):
    """A2 S7 is a full sentence; inside A3H2 it is used as a clause (lower-case start, no final period)."""
    return sentence[:1].lower() + sentence[1:].rstrip('.') if sentence else sentence


BENCHMARK_ABSTRACT = {'S1': 'it persisted when each forecast was averaged with {benchmark}',
                      'S2': 'it was not detected when each forecast was averaged with {benchmark}',
                      'S3': 'the combination with {benchmark} was reliably worse',
                      'S7': 'the combination check was not available'}


def contrast_texts(source, row, attribution, combo_row, robustness, label_cls, pc_place, arm_symbol=None):
    """§6 headline (A3H1-A3H4) plus abstract clause pieces for one primary contrast."""
    arm_symbol = arm_symbol or (lambda a: a)
    cls = row.get('decision')
    words = ARM_WORDS[source][row['arm']]
    if cls not in CLASSES:
        reason = row.get('not_evaluable_reason') or SENTENCES['A3H4R']
        return {'form': 'A3H4', 'section6': SENTENCES['A3H4'].format(arm=arm_symbol(row['arm']), activity=ACTIVITY[source], reason=reason),
                'clause_null': SENTENCES['A3AB_CLX'].format(arm_words=words, reason=reason),
                'other': SENTENCES['A3AB_OTHERX'].format(Arm_words=cap(words), reason=reason)}
    d, lo, hi = interval_parts(row)
    effect = row.get('effect_percent_reference_mae')
    fam = row.get('interval_family_one_day')
    common = dict(arm=arm_symbol(row['arm']), activity=ACTIVITY[source], effect=A2.fmt_effect(effect, d),
                  abs_effect=A2.fmt_effect(None if not finite(effect) else abs(effect), d), abs_aud=aud(row.get('mean_difference')),
                  level=LEVEL_TEXT[source], lo=lo, hi=hi, p=A2.display_p(row.get('holm_p')), robustness=robustness['sentence'])
    quals, flags_clause, flags_inc = [], '', ''
    if label_cls:
        quals.append(SENTENCES['A3QL'].format(reading_replacement=CLASS_WORDS[label_cls]))
        flags_clause += ', extraction-run-dependent'
        flags_inc += '; this reading was extraction-run-dependent (with re-extracted test-period labels it became ' + CLASS_WORDS[label_cls] + ')'
    zero = zero_clause(source, cls, fam)
    out = {'zero': bool(zero)}
    if cls == NULL:
        flags_clause += pc_place.get('null_flag', '')
        out.update(form='A3H1', section6=SENTENCES['A3H1'].format(qualifiers=''.join('; ' + q for q in quals), **common))
        key, sentence = sesoi_null_sentence(source, fam, d)
        out.update(sesoi_form=key, sesoi_sentence=sentence)
        rw = dict(arm_words=words, effect=common['effect'], lo=lo, hi=hi, p=common['p'], robust_word=robustness['short_word'], flags=flags_clause)
        out['clause_null'] = SENTENCES['A3AB_CL'].format(**rw)
        out['other'] = SENTENCES['A3AB_OTHER'].format(Arm_words=cap(words), **{k: v for k, v in rw.items() if k != 'arm_words'})
    elif cls == DET:
        if zero:
            flags_clause += ', family-adjusted interval includes zero'
        out.update(form='A3H3', section6=SENTENCES['A3H3'].format(zero=zero, qualifiers=''.join('; ' + q for q in quals), **common))
        rw = dict(arm_words=words, effect=common['effect'], lo=lo, hi=hi, p=common['p'], robust_word=robustness['short_word'], flags=flags_clause)
        out['clause_null'] = SENTENCES['A3AB_CLD'].format(**rw)
        out['other'] = SENTENCES['A3AB_OTHERD'].format(Arm_words=cap(words), **{k: v for k, v in rw.items() if k != 'arm_words'})
    else:
        sclass = sesoi_increment_class(effect, fam, SESOI[source])
        bench, bkey = combination_text(source, combo_row, cls)
        if pc_place.get('increment_flag'):
            quals.append(pc_place['increment_flag'])
            flags_inc += '; ' + pc_place['increment_flag']
        out.update(form='A3H2', sesoi_class=sclass, benchmark_clause=bkey,
                   section6=SENTENCES['A3H2'].format(zero=zero, attribution=attribution['sentence'],
                                                     sesoi=sesoi_clause(source, sclass), benchmark=bench,
                                                     qualifiers=''.join('; ' + q for q in quals), **common))
        out['increment'] = SENTENCES['A3AB_INC'].format(
            task_label=TASK_LABEL[source], arm_words=words, activity=ACTIVITY[source], abs_effect=common['abs_effect'],
            abs_aud=common['abs_aud'], level=LEVEL_TEXT[source], lo=lo, hi=hi, p=common['p'],
            zero_short=', although the family-adjusted interval includes zero' if zero else '',
            robust_word=robustness['short_word'], attribution_status=attribution['status_word'],
            sesoi_word=SESOI_CLASS_WORDS[sclass].format(S_phrase=S_PHRASE[source]),
            benchmark_word=BENCHMARK_ABSTRACT.get(bkey, BENCHMARK_ABSTRACT['S7']).format(benchmark=BENCHMARK_WORDS[source]),
            flags=flags_inc)
    return out


def task_bound(source, rows):
    bounds = []
    for r in rows:
        if r.get('decision') in (NULL, DET) and r.get('interval_family_one_day'):
            d, _, _ = interval_parts(r)
            bounds.append((max(0.0, -float(r['interval_family_one_day'][0])), d))
    if not bounds:
        return None, None
    return max(b for b, _ in bounds), max(d for _, d in bounds)


def task_texts(source, rows, attributions, combination, robust, states, pc, batch, matched=None, text_vs_no_text=None,
               incomplete_reason=None, arm_symbol=None, coverage_sentence=None):
    """All A3 sentences for one task: §6 list, abstract/conclusion task sentences, §7.2 sentences."""
    if incomplete_reason:
        return {'scenario': 'INCOMPLETE', 'section6': [SENTENCES['A3H6'].format(task_label=TASK_LABEL[source], reason=incomplete_reason)],
                'abstract': [SENTENCES['A3AB_INCOMPLETE'].format(task_label=TASK_LABEL[source], reason=incomplete_reason)],
                'qualifiers': [], 'not_run': [], 'section7_2': []}
    scenario = 'B' if any(r.get('decision') == IMP for r in rows) else 'A'
    place = pc_placements(source, scenario, pc)
    combo = {}
    if (combination or {}).get('state') == 'COMPUTED':
        combo = {(r['arm'], r['reference']): r for r in combination['family']['reports']}
    attr = {a['arm']: a for a in attributions}
    per = []
    for r in rows:
        pair = (r['arm'], r['reference'])
        per.append(contrast_texts(source, r, attr.get(r['arm'], {}), combo.get(pair), robust[pair],
                                  label_change(pair, states), place, arm_symbol))
    section6 = []
    d7_done = False
    for t in per:
        section6.append(t['section6'])
        if t.get('sesoi_sentence'):
            section6.append(t['sesoi_sentence'])
            if not d7_done:
                section6.append(SENTENCES['A3D7']); d7_done = True
    if source == 'notice':
        section6.append(SENTENCES['A3C7'])
    elif coverage_sentence:
        section6.append(coverage_sentence)            # A2 C6, unchanged, for news
    X, d = task_bound(source, rows)
    abstract = []
    if scenario == 'A':
        if X is not None:
            xb = A2.branch_safe_bound(X, d, SESOI[source])
            bo = 'below' if X < SESOI[source] else 'at or above'
            section6.append(SENTENCES['A3H5'].format(X=xb, tail=TAIL_TEXT[source], below_or_above=bo, S_phrase=S_PHRASE[source],
                                                     task_qualifiers=''.join('; ' + c for c in place['task_bound_clauses'])))
            section6.append(SENTENCES['A3M1'].format(task_label=TASK_LABEL[source], X=A2.branch_safe_bound(X, d, MDE_PERCENT[source]),
                                                     mde_cmp=mde_cmp(X, source), mde=MDE_PERCENT[source]))
            if source == 'notice':
                section6.append(SENTENCES['A3N1'].format(hist_cmp=hist_cmp(X)))
            elif text_vs_no_text and text_vs_no_text.get('sentence'):
                section6.append(text_vs_no_text['sentence'])
            clauses = '; '.join(t['clause_null'] for t in per)
            context = SENTENCES['A3AB_CTX'].format(hist_cmp=hist_cmp(X)) if source == 'notice' else ''
            abstract.append(SENTENCES['A3AB_NULL'].format(
                task_label=TASK_LABEL[source], activity=ACTIVITY[source], clauses=clauses, level=LEVEL_TEXT[source], X=xb,
                tail=TAIL_TEXT[source], below_or_above=bo, S_phrase=S_PHRASE[source], context=context,
                pc=''.join('; ' + c for c in place['abstract_clauses'])))
        else:
            abstract.extend(t['other'] for t in per)
    else:
        abstract.extend(t['increment'] for t in per if t['form'] == 'A3H2')
        abstract.extend(t['other'] for t in per if t['form'] != 'A3H2')
    section6.extend(place['section6'])
    bsent = batch_sentences(source, rows, batch)
    section6.extend(bsent['qualifiers'] + bsent['relations'] + bsent['not_run'])
    s72 = []
    if rows and all(robust[(r['arm'], r['reference'])]['label'] == 'ROBUST' for r in rows):
        s72.append(SENTENCES['A3R4'].format(task_label=TASK_LABEL[source]))
    key, sentence = layer2_sentence(source, states, arm_symbol)
    if sentence:
        s72.append(sentence)
    return {'scenario': scenario, 'section6': section6, 'abstract': abstract, 'qualifiers': bsent['qualifiers'],
            'not_run': bsent['not_run'], 'section7_2': s72, 'positive_control': place, 'task_bound': X,
            'contrasts': per}


def abstract_core(tasks):
    """Mandatory abstract elements (2)-(5) in order; FILL3a prepends the problem and design sentences."""
    out = [SENTENCES['A3Y1'], SENTENCES['A3Y2']]
    for source in ('news', 'notice'):
        out.extend(tasks[source]['abstract'])
    for source in ('news', 'notice'):
        out.extend(tasks[source]['qualifiers'])
    out.append(SENTENCES['A3H0'])
    for source in ('news', 'notice'):
        out.extend(tasks[source]['not_run'])
    return out


def conclusion_core(tasks):
    out = []
    for source in ('news', 'notice'):
        out.extend(tasks[source]['abstract'])
    for source in ('news', 'notice'):
        out.extend(tasks[source]['qualifiers'])
    out.append(SENTENCES['A3H0'])
    for source in ('news', 'notice'):
        out.extend(tasks[source]['not_run'])
    out.append(SENTENCES['A3CO_Y'])
    return out


# ---------------------------------------------------------------- C1: new cheap-text contrasts (frozen daily losses)
def new_cheap_contrasts(sc, source, daily_frame, a2_cheap):
    """A3 contrasts plus A2's L_chen comparators: {(arm, comparator): report or frozen slot}."""
    reports = dict(a2_cheap)
    days = daily_frame['target_day'].tolist()
    for arm, ref in A3_NEW_CONTRASTS[source]:
        if arm in daily_frame and ref in daily_frame:
            r = A2.contrast_stats(sc, daily_frame[arm].to_numpy(), daily_frame[ref].to_numpy(), A2.complete_picks(sc, len(days)), 1)
            r.update(arm=arm, reference=ref, state='COMPUTED', role='A3_SECONDARY_CHEAP_TEXT_CONTRAST')
            reports[(arm, ref)] = r
        else:
            reports[(arm, ref)] = {'arm': arm, 'reference': ref, 'state': 'NOT_EVALUABLE_WHOLE_STAGE_UNAVAILABLE'}
    return reports


def g1_sentence(bounds, table_ref='{table_ref}'):
    """A3G1; None when any of the three bounds is undefined (the table then shows the row as not computed)."""
    values = [bounds.get(pair) for pair in TEXT_VS_NO_TEXT]
    if any(v is None or not finite(v) for v in values):
        return None
    return SENTENCES['A3G1'].format(X_count=A2.fmt_bound(values[0], 3), X_chen=A2.fmt_bound(values[1], 3),
                                    X_act=A2.fmt_bound(values[2], 3), table_ref=table_ref, pub_cmp=pub_cmp(max(values[:2])))


# ---------------------------------------------------------------- V1 and W: descriptive subsets
def readmission_free_days(csv_path=READMISSION_CSV, expected_sha=READMISSION_SHA256):
    import pandas as pd
    if sha256(csv_path) != expected_sha:
        raise PermissionError('Frozen PRE2FACTS re-admission file drift')
    issued = set(pd.read_csv(csv_path, usecols=['issue_date_aest'])['issue_date_aest'].astype(str))
    days = A2.day_list((('2026-03-01', '2026-09-30'),))
    keep = [d for d in days if d not in issued]
    if len(keep) != READMISSION_FREE_DAYS:
        raise ValueError('Re-admission-free day count differs from the addendum')
    return keep


def subset_reports(sc, source, daily_frame, keep, sentence_key):
    sub = daily_frame.loc[daily_frame['target_day'].isin(keep)].reset_index(drop=True)
    if sub['target_day'].tolist() != keep:
        raise ValueError('Subset days missing from the frozen daily losses')
    losses = {c: sub[c].to_numpy() for c in sub.columns if c != 'target_day'}
    fam = A2.family_inference(sc, losses, FAMILIES[source], keep, m=1, subset=True)
    for r in fam['reports']:
        for k in ('holm_p', 'hln_holm_p', 'hac7_holm_p', 'decision', 'hln_decision', 'hac7_decision'):
            r.pop(k, None)
        one = r['bootstrap']['1'].get('interval95_percent')
        d = A2.percent_decimals(None if one is None else one[1] - one[0])
        lo, hi = A2.fmt_interval(one, d)
        r['sentence'] = SENTENCES[sentence_key].format(n=len(keep), arm=r['arm'], activity=ACTIVITY[source],
                                                       effect=A2.fmt_effect(r.get('effect_percent_reference_mae'), d),
                                                       lo=lo, hi=hi, p=A2.display_p(r.get('p_two_sided')))
    return {'days': len(keep), 'date_gaps': fam['date_gaps'], 'reports': fam['reports'], 'decision_rule': 'none (descriptive only)'}


def notice_u1n(strict):
    """Rule R6: the 7-day notice subset loses its p value (A3U1N replaces A2 U1)."""
    ranges = join_list(f'{a} to {b}' for a, b in A2.STRICT_UNEXPOSED['notice'])
    for r in strict['reports']:
        one = r['bootstrap']['1'].get('interval95_percent')
        d = A2.percent_decimals(None if one is None else one[1] - one[0])
        lo, hi = A2.fmt_interval(one, d)
        r['sentence_a3'] = SENTENCES['A3U1N'].format(n=strict['days'], ranges=ranges, arm=r['arm'], activity=ACTIVITY['notice'],
                                                     effect=A2.fmt_effect(r.get('effect_percent_reference_mae'), d), lo=lo, hi=hi)
        r['p_value_reported'] = False
    return strict


def _feature_bundle(manifest, source):
    found = [b for b in manifest.get('bundles', []) if b.get('source') == source and b.get('arm') == 'P_content'
             and b.get('variant', 'main') == 'main']
    return found[0] if len(found) == 1 else None


def pcontent_coverage(feature_root, expected_manifest_sha=None):
    """Matched-mask counts per task from the feature manifest only (no prediction, truth or loss is opened)."""
    import pandas as pd
    path = Path(feature_root) / 'manifest.json'
    if expected_manifest_sha is not None and sha256(path) != expected_manifest_sha:
        raise PermissionError('Feature manifest identity differs from SEAL.json')
    manifest = json.loads(path.read_text())
    out = {}
    for source, lo in (('news', '2026-03-01'), ('notice', '2026-08-01')):
        b = _feature_bundle(manifest, source)
        if b is None or not b.get('matched_mask_path'):
            out[source] = {'state': 'NO_MATCHED_MASK'}; continue
        if sha256(b['matched_mask_path']) != b['matched_mask_sha256'] or sha256(b['panel_path']) != b['panel_sha256']:
            raise PermissionError('Matched mask or panel identity drift: ' + source)
        mask = np.load(b['matched_mask_path'], allow_pickle=False).astype(bool)
        keys = pd.read_parquet(b['panel_path'], columns=['target_day'])
        keys['target_day'] = keys['target_day'].astype(str)
        sel = keys['target_day'].between(lo, '2026-09-30').to_numpy()
        days = keys.loc[sel, 'target_day'].to_numpy()
        m = mask[sel]
        matched_days = sorted(set(days[m]))
        n_days = len(set(days))
        out[source] = {'state': 'COMPUTED', 'matched_keys': int(m.sum()), 'total_keys': int(sel.sum()),
                       'matched_share_percent': 100.0 * float(m.sum()) / float(sel.sum()) if sel.sum() else None,
                       'days_with_matched_key': len(matched_days), 'n_days': n_days,
                       'bundle_state': b.get('state')}
    return out


def matched_support_section(sc, inputs, source, matched_info):
    """C4: L_count-M and L_chen-M on the matched keys of P_content - M (news); notices: A3C7."""
    if source == 'notice':
        return {'state': 'NO_MATCHED_KEY_BY_CONSTRUCTION', 'sentence': SENTENCES['A3C7']}
    import pandas as pd
    seal = inputs.seal
    fpath = Path(seal.get('feature_manifest_path', ''))
    if not fpath.exists() or sha256(fpath) != seal.get('feature_manifest_sha256'):
        return {'state': 'NOT_AVAILABLE_FEATURE_MANIFEST'}
    b = _feature_bundle(json.loads(fpath.read_text()), 'news')
    if b is None or not b.get('matched_mask_path'):
        return {'state': 'NOT_AVAILABLE_NO_MATCHED_MASK'}
    if sha256(b['matched_mask_path']) != b['matched_mask_sha256'] or sha256(b['panel_path']) != b['panel_sha256']:
        raise PermissionError('Matched mask or panel identity drift')
    inputs.read_log.append({'path': b['matched_mask_path'], 'sha256': b['matched_mask_sha256'], 'role': 'matched_mask'})
    truth = inputs.truth('news')
    keys = A2.coerce_keys(pd.read_parquet(b['panel_path'], columns=A2.KEYS + ['target_day']))
    keys['matched'] = np.load(b['matched_mask_path'], allow_pickle=False).astype(bool)
    keys = keys.loc[keys['target_day'].between('2026-03-01', '2026-09-30')].sort_values(A2.KEYS, kind='mergesort').reset_index(drop=True)
    if not keys[A2.KEYS].equals(truth[A2.KEYS]):
        raise ValueError('Matched mask keys differ from the truth grid')
    mask = keys['matched'].to_numpy()
    days_all = truth['target_day'].to_numpy()
    days = sorted(set(days_all[mask]))
    if len(days) < 7:
        return {'state': 'TOO_FEW_DAYS', 'days': len(days), 'sentence': SENTENCES['A3W0'].format(n=len(days))}
    losses = {}
    for arm in ('M', 'L_count', 'L_chen'):
        pred = inputs.prediction('news', arm, truth)
        if pred is None:
            return {'state': 'NOT_AVAILABLE_PREDICTION', 'arm': arm}
        frame = pd.DataFrame({'day': days_all[mask], 'loss': np.abs(pred[mask] - truth['y'].to_numpy(dtype='float64')[mask])})
        losses[arm] = frame.groupby('day', sort=True)['loss'].mean().to_numpy(dtype='float64')
    fam = A2.family_inference(sc, losses, FAMILIES['news'], days, m=1, subset=True)
    share = 100.0 * mask.sum() / len(mask)
    for r in fam['reports']:
        for k in ('holm_p', 'hln_holm_p', 'hac7_holm_p', 'decision', 'hln_decision', 'hac7_decision'):
            r.pop(k, None)
        one = r['bootstrap']['1'].get('interval95_percent')
        d = A2.percent_decimals(None if one is None else one[1] - one[0])
        lo, hi = A2.fmt_interval(one, d)
        r['sentence'] = SENTENCES['A3W1'].format(matched_keys=f'{int(mask.sum()):,}', matched_share=f'{share:.1f}', n=len(days),
                                                 arm=r['arm'], activity=ACTIVITY['news'],
                                                 effect=A2.fmt_effect(r.get('effect_percent_reference_mae'), d), lo=lo, hi=hi,
                                                 p=A2.display_p(r.get('p_two_sided')))
    return {'state': 'COMPUTED', 'matched_keys': int(mask.sum()), 'matched_share_percent': share, 'days': len(days),
            'date_gaps': fam['date_gaps'], 'reports': fam['reports']}


# ---------------------------------------------------------------- run
def _optional_json(path):
    if path is None or not Path(path).exists():
        return None, None
    return json.loads(Path(path).read_text()), sha256(path)


def _sensitivity_files(inputs, source):
    files = {'first_L': inputs.score_json(f'{source}__first_L.json', required=False)}
    if source == 'news':
        files['window_24h'] = inputs.score_json('news__24h.json', required=False)
    else:
        files['official_cap'] = inputs.score_json('notice__A1_OFFICIAL_CAP_RECLIP_PRIMARY.json', required=False)
        files['drop_first_seven'] = inputs.score_json('notice__DROP_FIRST_SEVEN_DAYS.json', required=False)
    return files


def _unadjusted_bound(inputs, slot):
    """Unadjusted bound of a frozen secondary slot from its saved report (rule R5: unadjusted label)."""
    path = slot.get('report_path')
    if not path or Path(path).name not in inputs.score_files:
        return None
    rep = inputs.score_json(Path(path).name)['reports'][0]
    one = (rep.get('bootstrap') or {}).get('1') or (rep.get('bootstrap') or {}).get(1) or {}
    interval = one.get('interval95_percent')
    return None if not interval else max(0.0, -float(interval[0]))


def run_task_a3(sc, inputs, source, a2_task, pc_result=None, batch=None, label=None):
    daily = inputs.daily_losses(source)
    rows = a2_task['primary']
    seeds = inputs.score_json(source + '__A1_SEED_FRAGILE.json')
    seed_rows = {(r['arm'], r['reference']): r for r in seeds['rows']}
    robust, sign_only = {}, {}
    for r in rows:
        pair = (r['arm'], r['reference'])
        s = seed_rows.get(pair, {})
        robust[pair] = robustness_a3(r['decision'], r.get('interval95_one_day'), r.get('interval95_seven_day'),
                                     r.get('hln_decision'), r.get('hac7_decision'), s.get('three_seed_mean_decision'),
                                     seed_reason=s.get('reason'))
        sign_only[pair] = seed_sign_only(r['decision'], r.get('mean_difference'), s.get('three_seed_mean_decision'),
                                         s.get('three_seed_mean_difference'))
    report = inputs.score_json('SCORE_REPORT.json')
    secondary = report[source]['secondary']
    a2_cheap = {}
    for a, ref in A2.CHEAP_COMPARATORS[source]:
        key = f'{a}-{ref}'
        a2_cheap[(a, ref)] = (a2_task['cheap_text_comparators'] or {}).get(key) or A2.slot_lookup(secondary, a, ref)
    cheap = new_cheap_contrasts(sc, source, daily, a2_cheap)
    attributions = [attribution_a3(source, r['arm'], r['decision'], secondary, cheap, a2_task['p_content_unmatched']) for r in rows]
    files = _sensitivity_files(inputs, source)
    states = sensitivity_states(source, rows, files, batch, label)
    tvn = None
    if source == 'news':
        bounds = {}
        for arm, ref in TEXT_VS_NO_TEXT:
            slot = A2.slot_lookup(secondary, arm, ref)
            bounds[(arm, ref)] = None if not slot or slot.get('state') != 'COMPUTED_SECONDARY' else _unadjusted_bound(inputs, slot)
        tvn = {'bounds': {f'{a}-{b}': v for (a, b), v in bounds.items()}, 'sentence': g1_sentence(bounds)}
    pc = pc_state(source, pc_result)
    texts = task_texts(source, rows, attributions, a2_task['combination'], robust, states, pc, batch, text_vs_no_text=tvn,
                       coverage_sentence=(a2_task['p_content_unmatched'] or {}).get('sentence'))
    out = {'robustness_a3': {f'{a}-{b}': v for (a, b), v in robust.items()},
           'seed_sign_only': {f'{a}-{b}': v for (a, b), v in sign_only.items()},
           'attribution_a3': attributions,
           'a3_new_cheap_contrasts': {f'{a}-{b}': cheap[(a, b)] for a, b in A3_NEW_CONTRASTS[source]},
           'design_sensitivities': {f'{a}-{b}': v for (a, b), v in states.items()},
           'positive_control': pc, 'texts': texts, 'text_vs_no_text': tvn,
           'matched_support': matched_support_section(sc, inputs, source, a2_task['p_content_unmatched'])}
    if source == 'news':
        out['readmission_free_subset'] = subset_reports(sc, source, daily, readmission_free_days(), 'A3V1')
    else:
        out['strictly_unexposed_a3'] = notice_u1n(json.loads(json.dumps(A2.json_safe(a2_task['strictly_unexposed']))))
    combo = a2_task['combination']
    if (combo or {}).get('state') == 'COMPUTED':
        out['combination_robustness_a3'] = {
            f"{r['arm']}-{r['reference']}": robustness_a3(r['decision'], r['bootstrap']['1'].get('interval95_percent'),
                                                         r['bootstrap']['7'].get('interval95_percent'), r.get('hln_decision'),
                                                         r.get('hac7_decision'), (r.get('three_seed') or {}).get('decision'))
            for r in combo['family']['reports']}
    if source == 'news' and batch:
        out['batch_robustness_a3'] = batch_robustness(batch)
    return out


def run(state, out=None, conf_root=CONF_ROOT, grid=None, pc_path=DEFAULT_PC, a2batch_path=DEFAULT_A2BATCH,
        a2label_path=DEFAULT_A2LABEL):
    state = Path(state).resolve()
    out = Path(out).resolve() if out else state / 'a3_scored'
    for forbidden in ('scored', 'a2_scored'):
        f = (state / forbidden).resolve()
        if out == f or f in out.parents:
            raise PermissionError('A3 never writes into ' + forbidden + '/')
    freeze = json.loads(ADDENDUM_FREEZE.read_text())
    for name, ident in freeze['files'].items():
        if sha256(A3_ROOT / name) != ident['sha256']:
            raise PermissionError('Frozen A3 document drift: ' + name)
    sc = A2.load_frozen_scoring(conf_root)
    inputs = A2.Inputs(state, grid)
    pc_result, pc_sha = _optional_json(pc_path)
    batch, batch_sha = _optional_json(a2batch_path)
    label, label_sha = _optional_json(a2label_path)
    result = {'analysis': 'CONF-A3 post-score readings (secondary and reporting; no primary decision changes)',
              'addendum_freeze_sha256': sha256(ADDENDUM_FREEZE), 'module_sha256': sha256(Path(__file__)),
              'a2_module_sha256': sha256(A2_ROOT / 'code/a2_postscore.py'), 'seal_sha256': inputs.seal_sha256,
              'optional_inputs': {'positive_control': pc_sha, 'a2batch': batch_sha, 'a2label': label_sha}, 'tasks': {}}
    saved_a2 = state / 'a2_scored' / 'A2_POSTSCORE.json'
    a2_tasks = {s: A2.run_task(sc, inputs, s) for s in ('news', 'notice')}
    if saved_a2.exists():
        saved = json.loads(saved_a2.read_text())['tasks']
        if json.loads(json.dumps(A2.json_safe(a2_tasks), sort_keys=True)) != saved:
            raise ValueError('Saved A2 output differs from the frozen A2 re-run')
    for source in ('news', 'notice'):
        result['tasks'][source] = run_task_a3(sc, inputs, source, a2_tasks[source], pc_result, batch, label)
    result['abstract_core'] = abstract_core({s: result['tasks'][s]['texts'] for s in ('news', 'notice')})
    result['conclusion_core'] = conclusion_core({s: result['tasks'][s]['texts'] for s in ('news', 'notice')})
    result['methods_sentences'] = [SENTENCES['A3D6'], SENTENCES['A3B4']] + [
        SENTENCES['A3B3'].format(level=LEVEL_TEXT[s], m=len(FAMILIES[s]), task_label=TASK_LABEL[s]) for s in ('news', 'notice')]
    result['fixed_sentences'] = {'A3C8': SENTENCES['A3C8'], 'A3R6': SENTENCES['A3R6'], 'A3D5': SENTENCES['A3D5'],
                                 'A3R_BATCH': SENTENCES['A3R_BATCH'], 'A3P1': SENTENCES['A3P1'],
                                 'notice_clock_limitation': NOTICE_CLOCK_LIMITATION}
    result['inputs_read'] = inputs.read_log
    result['primary_decision_rule_changed'] = False
    out.mkdir(parents=True, exist_ok=True)
    path = out / 'A3_POSTSCORE.json'
    path.write_text(json.dumps(A2.json_safe(result), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n')
    receipt = {'state': 'A3_POSTSCORE_COMPLETE', 'output': {'path': str(path), 'sha256': sha256(path)},
               'seal_sha256': inputs.seal_sha256, 'addendum_freeze_sha256': sha256(ADDENDUM_FREEZE),
               'module_sha256': sha256(Path(__file__)), 'inputs_read': inputs.read_log,
               'optional_inputs': result['optional_inputs']}
    (out / 'A3_POSTSCORE_RECEIPT.json').write_text(json.dumps(A2.json_safe(receipt), indent=2, sort_keys=True) + '\n')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--state', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--positive-control', type=Path, default=DEFAULT_PC)
    parser.add_argument('--a2batch', type=Path, default=DEFAULT_A2BATCH)
    parser.add_argument('--a2label', type=Path, default=DEFAULT_A2LABEL)
    parser.add_argument('--coverage-only', action='store_true')
    parser.add_argument('--feature-root', type=Path)
    args = parser.parse_args(argv)
    if args.coverage_only:
        print(json.dumps(pcontent_coverage(args.feature_root), indent=1))
        return
    result = run(args.state, args.out, pc_path=args.positive_control, a2batch_path=args.a2batch, a2label_path=args.a2label)
    print(json.dumps({'state': 'A3_POSTSCORE_COMPLETE', 'tasks': list(result['tasks'])}))


if __name__ == '__main__':
    main()
