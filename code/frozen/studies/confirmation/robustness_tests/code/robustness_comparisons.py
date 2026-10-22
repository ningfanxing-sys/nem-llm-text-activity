"""CONF-A4 post-score module (ADDENDUM_A4.md, frozen in ADDENDUM_A4_FREEZE.json before this code was written).

Extends the frozen CONF-A3 module `A3/code/a3_postscore.py` by import (after both A3 freezes verify; A3 in turn verifies
both A2 freezes). Runs after the frozen score, A2 and A3, before the manuscript fill (FILL3b):

    cli.py score -> a2_postscore.py -> a3_postscore.py -> a4_postscore.py --state <host_state> -> FILL3b

It never refits and never changes a frozen reading. Besides what A3 reads it reads: the extra-seed sealed predictions
and the frozen THREE_SEED_MEAN files (three-seed family-adjusted intervals), the frozen secondary slot reports of
M - N, M_notice - N, L_count - N, L_chen - N, LEAR - N and the shift slots, the pre-score coverage file, and when present
the A2BATCH, A2LABEL, positive-control and PCX results. It writes only `<state>/a4_scored/`. Sentence forms are copied
verbatim from Appendix A4 of the addendum.

    python a4_postscore.py --state <host_state> [--out DIR] [--positive-control F] [--pcx F] [--a2batch F] [--a2label F]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
from pathlib import Path
import sys

import numpy as np

A4_ROOT = Path(__file__).resolve().parents[1]
CONF_ROOT = A4_ROOT.parent
A3_ROOT = CONF_ROOT / 'A3'
PROJ = CONF_ROOT.parents[2]
ADDENDUM_FREEZE = A4_ROOT / 'ADDENDUM_A4_FREEZE.json'
AMENDMENT_1_FREEZE = A4_ROOT / 'ADDENDUM_A4_AMENDMENT_1_FREEZE.json'
AMENDMENT_2_FREEZE = A4_ROOT / 'ADDENDUM_A4_AMENDMENT_2_FREEZE.json'
A3_ADDENDUM_FREEZE = A3_ROOT / 'ADDENDUM_A3_FREEZE.json'
A3_CODE_FREEZE = A3_ROOT / 'A3_CODE_AND_RULES_FREEZE.json'
COVERAGE_FILE = CONF_ROOT / 'A3/results/NEWS_MATCHED_COVERAGE.json'
COVERAGE_SHA256 = '78cb6cf60e1d8a335f20aec0d6679e0a41b521d54c46234ad9ac3a213efc2154'
DEFAULT_PC = CONF_ROOT / 'A1/positive_control/run/RESULT_POSITIVE_CONTROL.json'
DEFAULT_PCX = CONF_ROOT / 'A1/positive_control/run_null_ext/RESULT_PC_NULL_EXTENSION.json'
DEFAULT_A2BATCH = PROJ / 'autopilot/q1_audits/A2BATCH/scores/A2BATCH_RESULT.json'
DEFAULT_A2LABEL = PROJ / 'autopilot/q1_audits/A2LABEL/scores/A2LABEL_RESULT.json'
WORD_LIMIT = 250


class A4ConsistencyError(ValueError):
    """An impossible state under the frozen rules (ADDENDUM_A4 rule K); FILL3b must refuse."""


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def load_a3():
    """Import the frozen A3 module only after both A3 freeze records verify (A3 checks the A2 freezes itself)."""
    code_freeze = json.loads(A3_CODE_FREEZE.read_text())
    if sha256(A3_ADDENDUM_FREEZE) != code_freeze['addendum_freeze_sha256']:
        raise PermissionError('A3 addendum freeze drift')
    for name, ident in json.loads(A3_ADDENDUM_FREEZE.read_text())['files'].items():
        if sha256(A3_ROOT / name) != ident['sha256']:
            raise PermissionError('Frozen A3 document drift: ' + name)
    for name, ident in code_freeze['files'].items():
        if sha256(A3_ROOT / name) != ident['sha256']:
            raise PermissionError('Frozen A3 code or rule drift: ' + name)
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('a3_postscore_frozen_for_a4', A3_ROOT / 'code/a3_postscore.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A3 = load_a3()
A2 = A3.A2
IMP, DET, NULL, NE = A3.IMP, A3.DET, A3.NULL, A3.NE
CLASSES = A3.CLASSES

# ---------------------------------------------------------------- Appendix A4 sentence forms (verbatim)
SENTENCES = {
    # AB
    'A4AB_P': 'Large language models can structure electricity-market text, but forecasting gains may reflect text activity or unavailable historical information.',
    'A4AB_DS': "In Australia's National Electricity Market (NEM), we compare language-model extractions of WattClarity news (214 day-ahead issues, March–September 2026) and AEMO market notices (61 days, August–September 2026) with nested references that already contain the numerical inputs and text activity, under saved-version clocks and rules frozen by trusted timestamps before scoring.",
    'A4AB_Y0': "In an internally pre-specified 2025 day-ahead test, adding extracted news labels to the numerical reference changed its mean absolute error by +0.18% (+0.0928 AUD/MWh; one-sided Diebold–Mariano p = 0.61); price-only LEAR, added after that test, changed the reference's error by -21.3% in 2025 (39.73 against 50.51 AUD/MWh){lear_tail}.",
    'A4AB_Y1': "In a pre-specified 2025 test, extracted news labels changed the numerical reference's error by +0.18% (p = 0.61); price-only LEAR changed it by -21.3% in 2025{lear_tail}.",
    'A4AB_Y2': "Price-only LEAR changed the numerical reference's error by -21.3% in 2025{lear_tail}; in 2025, extracted news labels changed it by +0.18% (p = 0.61).",
    'A4LT_OK': ' and by {se}% [{lo}, {hi}] ({class}) in the 2026 news window',
    'A4LT_OKC': ' and by {se}% ({class}) in the 2026 news window',
    'A4LT_NE': ', and its 2026 comparison could not be evaluated ({reason})',
    'A4AB_H0C': 'These readings are relative to the pre-specified learner and information set.',
    'A4AB_A': "For {task_label}, {activity_words} changed the numerical reference's error by {mn}; against it, {clauses}; improvements larger than {X}% were excluded at the family-adjusted one-sided {tail}% level, {below_or_above} {S_phrase}{context}{pc}{task_quals}.",
    'A4AB_ANE': "For {task_label}, {activity_words} changed the numerical reference's error by {mn}; against it, {clauses}.",
    'A4AB_B': 'For {task_label}, against {activity_words}, {clauses}{task_quals}.',
    'A4AB_MN': '{se}% [{lo}, {hi}] ({class})',
    'A4AB_MNC': '{se}% ({class})',
    'A4AB_MNX': 'an amount that could not be evaluated ({reason})',
    'A4AB_C': '{arm_words} changed the error by {se}%{interval} ({class_text}{quals})',
    'A4AB_CX': '{arm_words} could not be evaluated ({reason})',
    'A4AB_CG': '{arm_list} changed the error by {effect_list}{interval_list} ({class_text}{quals})',
    'A4AB_TQ': '; {qualifier} for every {kind} of this task',
    'A4AB_HN': ', but this window cannot distinguish effects as small as the 2025 news contrasts (0.18% and 0.32%) from zero',
    'A4PA_SENS': '; precision-limited: a planted signal of twice the minimum detectable effect was detected in only {k} of {R} replicates, so this does not show that the text lacks such information',
    'A4PA_SIZE': '; the exclusion bound may be too narrow, because the permuted null column was detected in {k0} of {R0} replicates (Clopper–Pearson upper bound {hi0}%), more often than the nominal {nominal}% allows',
    'A4AB_Q1': 'Under the absolute-error training objective, {arm_words} changed the error against the matching activity reference by {se}% [{lo}, {hi}] ({class}, unlike the primary reading); this does not change the primary reading.',
    'A4AB_Q2': 'With pre-dispatch demand and semi-scheduled generation forecasts as additional inputs, {arm_words} changed the error against the matching activity reference by {se}% [{lo}, {hi}] ({class}, unlike the primary reading); this does not change the primary reading.',
    'A4AB_Q1C': 'Under the absolute-error objective, {arm_words} changed the error by {se}% [{lo}, {hi}] ({class}, unlike the primary reading).',
    'A4AB_Q2C': 'With pre-dispatch inputs, {arm_words} changed the error by {se}% [{lo}, {hi}] ({class}, unlike the primary reading).',
    'A4NR': 'The {family_name} secondary family was not run ({reason}).',
    'A4NR_BUDGET': 'it did not fit within the fixed 24-hour batch fitting budget',
    'A4NR_PARITY': 'the pre-specified reproduction check failed',
    'A4DEV': 'The {family_name} secondary family was not completed: its pre-specified fits failed during execution, a deviation from the frozen design, under which only the fitting budget or the reproduction check could stop it.',
    'A4CO_Y': "Price-only LEAR changed the numerical reference's mean absolute error by -21.3% in 2025 (39.73 against 50.51 AUD/MWh){lear_tail}; in an internally pre-specified 2025 test, adding extracted news labels changed it by +0.18%.",
    # CT
    'CT_INC': 'a reliable increment',
    'CT_INC_AUD': 'a reliable increment of {aud} AUD/MWh',
    'CT_PS': 'a primary-seed increment',
    'CT_PS_AUD': 'a primary-seed increment of {aud} AUD/MWh',
    'CT_NULL': 'no reliable increment',
    'CT_DET': 'a reliable deterioration',
    'CT_DET_AUD': 'a reliable deterioration of {aud} AUD/MWh',
    'CT_ZERO': ', although its family-adjusted interval includes zero',
    'Q_ROBUST': 'inferentially robust',
    'Q_DISSENT': 'design dissent: {items}',
    'Q_DISSENT_ITEM': '{sensitivity} gave {class}',
    'Q_FRAG': 'fragile: {checks} disagreed, three-seed mean {ts}',
    'Q_TS_NUM': '{se}% [{lo}, {hi}], {class}',
    'Q_TS_NA': 'not available',
    'Q_NFC': 'not fully checked: {checks} unavailable',
    'Q_ERD': 'extraction-run-dependent: {class} with re-extracted labels',
    'Q_SIZE': 'reliability may be overstated',
    'Q_PREC': 'precision-limited',
    'Q_ATTR': 'an increment over {activity_words} only',
    'Q_NOTASSIGNED': 'attribution and comparison-value classes not assigned',
    'Q_NARROW': ', possibly too narrow',
    'IC_BEYOND': 'interval wholly beyond {S_phrase}',
    'IC_ABOVE': 'point above {S_phrase}, interval straddling it',
    'IC_BELOWPT': 'point below {S_phrase}, interval straddling it',
    'IC_BELOW': 'interval wholly below {S_phrase}',
    'CB_S1': 'persisted when averaged with {bench}, combination {combo_robust}',
    'CB_S2': 'not detected when averaged with {bench}, combination {combo_robust}',
    'CB_S3': 'reliably worse when averaged with {bench}, combination {combo_robust}',
    'CB_S7': 'combination check not available',
    'CB_NEUTRAL': 'averaged with {bench}: {class}, combination {combo_robust}',
    # H
    'A4H1': '{arm} changed the error of the {activity} reference by {se}% (family-adjusted {level}% interval [{lo}, {hi}]%, Holm-adjusted {p}): no reliable increment; {robustness}{qualifiers}.',
    'A4H2': '{arm} changed the error of the {activity} reference by {se}% ({aud} AUD/MWh lower; family-adjusted {level}% interval [{lo}, {hi}]%, Holm-adjusted {p}): a reliable increment{zero}; {robustness}; {attribution}; {sesoi}; {benchmark}{qualifiers}.',
    'A4H2F': '{arm} changed the error of the {activity} reference by {se}% ({aud} AUD/MWh lower; family-adjusted {level}% interval [{lo}, {hi}]%, Holm-adjusted {p}): a primary-seed increment{zero}; {robustness}; {three_seed}; attribution and comparison-value classes not assigned; {benchmark}{qualifiers}.',
    'A4H3': '{arm} changed the error of the {activity} reference by {se}% ({aud} AUD/MWh higher; family-adjusted {level}% interval [{lo}, {hi}]%, Holm-adjusted {p}): a reliable deterioration{zero}; {robustness}{qualifiers}.',
    'A4TS': 'the three-seed mean changed the error by {se}% (family-adjusted {level}% interval [{lo}, {hi}]%, Holm-adjusted {p}): {class}',
    'A4TSX': 'the three-seed mean was not available ({reason})',
    'A4R1': 'this reading was inferentially robust: the one-day and seven-day bootstrap intervals, the small-sample HLN calibration, the HAC7 long-run variance and the three-seed mean all agreed with its decision class',
    'A4R2': 'this reading was fragile: {dissent_list} did not agree with its decision class',
    'A4RD': '; design dissent: {items}',
    'A4RD_ITEM': '{sensitivity} gave {class}',
    'A4R4': 'Every primary reading of the {task_label} family was inferentially robust: it agreed with all five inferential checks.',
    'A4C1': 'it is an increment over the {activity} reference only, because the content controls cannot reach the content-specific level in this design',
    'A4S_NARROW': '; this interval may be too narrow, because the permuted null column was detected more often than the nominal level allows',
    'A4S1': 'the increment persisted when each forecast was averaged with {benchmark} ({effect}% of the combined reference error, family-adjusted {level}% interval [{lo}, {hi}]%, Holm-adjusted {p}; combination {combo_robust})',
    'A4S2': 'when each forecast was averaged with {benchmark}, no reliable increment was detected ({effect}%, family-adjusted {level}% interval [{lo}, {hi}]%, Holm-adjusted {p}; combination {combo_robust}), so the increment is stated relative to the pre-specified learner and information set only',
    'A4S3': 'when each forecast was averaged with {benchmark}, the combination containing {arm} was reliably worse ({effect}%, family-adjusted {level}% interval [{lo}, {hi}]%, Holm-adjusted {p}; combination {combo_robust})',
    'A4SN': 'when each forecast was averaged with {benchmark}, the difference was {effect}% (family-adjusted {level}% interval [{lo}, {hi}]%, Holm-adjusted {p}; combination {combo_robust}): {class}',
    'A4S4': 'In the secondary combination check with {benchmark}, {arm} showed a reliable favourable difference ({effect}%, Holm-adjusted {p}; combination {combo_robust}); this does not change the primary reading.',
    'A4S5': 'The secondary combination check with {benchmark} also detected no reliable increment for {arm} ({effect}%, Holm-adjusted {p}; combination {combo_robust}).',
    'A4S6': 'In the secondary combination check with {benchmark}, the combination containing {arm} was reliably worse ({effect}%, Holm-adjusted {p}; combination {combo_robust}); this does not change the primary reading.',
    'A4T7': 'Robustness gives the inferential label (one-day and seven-day intervals, small-sample HLN calibration, HAC7, three-seed mean) and, after a semicolon, any design sensitivity whose decision class differs (design dissent); all design sensitivities are listed in Table {table_ref}.',
    'A4M_DEF': 'A reading is inferentially robust when the one-day and seven-day bootstrap intervals, the small-sample HLN calibration, the HAC7 long-run variance and the three-seed mean all agree with its decision class; a pre-specified design sensitivity with a different decision class is reported beside it as a design dissent. Attribution, comparison-value classes and the persistence wording of the combination check are given only to inferentially robust increments; a fragile or not fully checked increment is reported as a primary-seed increment together with the three-seed mean\'s estimate, family-adjusted interval and decision class.',
    # T
    'A4C0': 'Content-specific and LLM-specific attribution cannot be reached in this design. For notices, the activity-matched reassignment control has no matched key by construction; for news, its matched keys, computed before scoring from the input-side mask, cover {keys} of {total} keys ({share}%) on {days} of {n_days} days, fewer than the seven days its frozen secondary rule requires, so it is not evaluable. Every reliable increment is therefore described as an increment over its activity reference; the 28-day shift comparison and the cheap-text comparisons are reported beside it as secondary readings, not as attribution levels.',
    'A4PCN': 'not evaluable: no matched key by construction',
    'A4PCW': 'not evaluable: matched keys on {days} of {n_days} days, fewer than the seven required',
    'A4CS': 'Against the same representation built from content shifted by 28 days, {arm} changed the error by {se}% (95% interval [{lo}, {hi}]%, DM {p}{days}): {class}; this secondary reading changes activity timing together with content, so it is not an attribution level.',
    'A4CS_DAYS': ' on the {n} shift-supported days',
    'A4CSX': 'The 28-day shift comparison of {arm} was not evaluable ({reason}).',
    'A4CHS': 'Against cheap-text representations of the same {documents} (secondary, unadjusted), {arm} {cheap_list}.',
    # A
    'A4MN': 'Against the numerical reference, {activity_words} changed the error by {se}% ({aud} AUD/MWh {lower_higher}; unadjusted 95% interval [{lo}, {hi}]%, DM {p}): {class}.',
    'A4MNX': 'The comparison of {activity_words} with the numerical reference was not evaluable ({reason}).',
    'A4MNR_IMP': 'Text activity therefore improved on the numerical reference, while no structured representation improved on text activity.',
    'A4MNR_NULL': 'Neither text activity nor any structured representation improved reliably on its reference.',
    'A4MNR_DET': 'Text activity was reliably worse than the numerical reference, and no structured representation improved on text activity.',
    'A4G1': 'Against the numerical reference, the label-count representation changed the error by {e1}% (unadjusted 95% interval [{l1}, {h1}]%; {c1}), the structured-attribute embedding by {e2}% ([{l2}, {h2}]%; {c2}) and the article activity reference by {e3}% ([{l3}, {h3}]%; {c3}); Table {table_ref} places these text-versus-no-text estimates beside the published no-text-to-text comparisons, whose relative error changes computed from the reported metric pairs range from a 1.37% increase to a 13.90% reduction.',
    'A4LEAR': 'In the 2026 news window, price-only LEAR changed the error of the numerical reference by {se}% ({aud} AUD/MWh {lower_higher}; unadjusted 95% interval [{lo}, {hi}]%, DM {p}): {class}; in 2025 it changed it by -21.3%.',
    'A4LEARX': 'In the 2026 news window, the comparison of price-only LEAR with the numerical reference was not evaluable ({reason}).',
    'A4N2': "This bound is {mde_cmp} the design's minimum detectable effect of 3.11% and {hist_cmp} the 0.18% and 0.32% magnitudes of the 2025 news contrasts; with a power of 2.7% at 0.32%, this window cannot distinguish effects of that size from zero.",
    'A4D1P': 'Improvements larger than {X}% of the reference error were excluded at the family-adjusted one-sided {tail}% level, conditional on these fitted predictions: this fitted system produced no improvement as large as {S_phrase}; because the planted-signal check failed, this does not show that the text lacks such information.',
    'A4D6': 'The comparison values are interpretation aids and never enter a decision. For news, the smallest effect size of interest is 3.8% of the reference error, the smallest text-attributed error reduction with a significance test in the cited electricity forecasting work. For notices, the comparison value is 0.5% of the reference error: the equivalence tolerance of the earlier January–February 2026 notice test (window C), used here as a historical-effect reference; that tolerance was set after development results were known and is not an economic indifference threshold.',
    # P
    'A4P1N': 'For news, each replicated planted-signal fit is one fit at the first analogue issue that predicts all 214 days, an approximation of the daily refits used in the confirmation; one daily-refit replicate per strength and for the null column checks it ({n1}).',
    'A4P1T': 'For {task_label}, at twice the minimum detectable effect the column was detected in {k} of {R} replicates (detection rate under this planting scheme; Clopper–Pearson 95% interval [{lo}, {hi}]), with a median realised change of {delta}% of the reference error and a median uptake of {uptake}% of the planted information; the permuted null column was detected in {k0} of {R0} replicates (Clopper–Pearson 95% interval [{lo0}, {hi0}]% against the nominal {nominal}%).',
    'A4PB_PASS': 'For {task_label}, the permuted null column was detected in {k0} of {R0} replicates, so the size check passed but cannot exclude a false-rejection rate as high as {hi0}% (Clopper–Pearson 95% upper bound; nominal {nominal}%).',
    'A4PB_SIZE': 'its reliability may be overstated, because the permuted null column was detected in {k0} of {R0} replicates (Clopper–Pearson 95% interval [{lo0}, {hi0}]%), more often than the nominal {nominal}% allows',
    'A4PX_RUN': 'The size check uses {R0} permuted-null replicates: {R0a} of the frozen design and {R0b} added by the fourth pre-score addendum before any planted-signal result existed.',
    'A4PX_NOT': 'The pre-specified extension to 200 permuted-null replicates was not run ({reason}); the size check uses the {R0} replicates of the frozen design.',
    # S
    'A4ST_EXEC': "Of the {total} pre-specified fitting and scoring stages (Supplement Table {table_ref}), {done} completed fully, {partial} completed apart from recorded unavailable configurations, {not_run} were not run{not_run_reasons}, {deviation} deviated from the frozen design and {pending} had no result when this version was filled; the predictions of every completed stage were fixed before that stage's scoring read confirmation prices, and the planted-signal check uses pre-confirmation data only.",
}
# Amendment 1 forms (ADDENDUM_A4_AMENDMENT_1.md, verbatim).
AMENDMENT_1 = {
    'A4AB_DS1': "In Australia's National Electricity Market (NEM), we compare language-model extractions of 2026 WattClarity news and AEMO market notices with nested activity references under rules frozen by trusted timestamps.",
    'A4AB_Y3': "Price-only LEAR changed the numerical reference's error by -21.3% in 2025{lear_tail}; 2025 news labels changed it by +0.18% (p = 0.61).",
    'A4AB_AC': "For {task_label}, {activity_words} changed the numerical reference's error by {mn}; against it, {clauses}; improvements above {X}% were excluded (family-adjusted, one-sided {tail}%), {below_or_above} {S_phrase}{context}{pc}{task_quals}.",
    'A4AB_HNC': ', too imprecise to separate the 0.18% and 0.32% 2025 news effects from zero',
    'A4AB_CTXC': ', between the earlier notice gains of 0.097% and 0.154%',
    'A4LT_OKC2': ' and {se}% ({class}) in 2026',
    'A4PA_SENSC': '; precision-limited (planted signal detected in only {k} of {R}), so this does not show that the text lacks such information',
    'A4PA_SIZEC': '; the bound may be too narrow (permuted null column detected in {k0} of {R0}, upper bound {hi0}%)',
    'A4AB_CGS': 'the {short_list} representations changed the error by {effect_list} ({class_text}{quals})',
    'A4NR_BUDGETC': 'fitting budget',
    'A4NR_PARITYC': 'reproduction check failed',
    'A4DEVC': 'The {family_name} secondary family failed during execution, a deviation from the frozen design.',
    'IC_BEYOND_C': 'interval wholly beyond {S}%',
    'IC_ABOVE_C': 'point above {S}%, interval straddling it',
    'IC_BELOWPT_C': 'point below {S}%, interval straddling it',
    'IC_BELOW_C': 'interval wholly below {S}%',
}
AMENDMENT_2 = {
    "CT_NULL2": "no reliable increment detected",
    "A4H1b": "{arm} changed the error of the {activity} reference by {se}% (family-adjusted {level}% interval [{lo}, {hi}]%, Holm-adjusted {p}): no reliable increment detected; {robustness}{qualifiers}.",
    "A4MNR_IMPb": "Text activity therefore improved reliably on the numerical reference, while no reliable increment of a structured representation over text activity was detected.",
    "A4MNR_NULLb": "No reliable improvement was detected for text activity over the numerical reference, nor for any structured representation over text activity.",
    "A4MNR_DETb": "Text activity was reliably worse than the numerical reference, and no reliable increment of a structured representation over text activity was detected.",
    "A4FT": "; the pre-specified test detected this improvement, but it is sensitive to the checks above, so it is not evidence of a robust increment",
    "A4ENV_X": " (the seven-day interval was undefined)",
    "A4MC": "; at the Monte Carlo resolution of 2,000 bootstrap draws this bound cannot be placed on one side of {S_phrase}",
    "A4SUB": "not applicable (descriptive subset)",
    "A4P0": "This check is a pipeline signal-use and negative-control diagnostic: it shows whether the fitted pipeline can use a sparse exact signal and how often a permuted column is detected, not the size or power of the daily test for other representations.",
    "A4PB_DIAG": "For {task_label}, the permuted negative-control column was detected in {k0} of {R0} replicates (Clopper–Pearson 95% interval [{lo0}, {hi0}]%); this diagnostic does not certify the size of the daily test.",
    "A4PB_NEG": "its reliability may be overstated, because the permuted negative-control column was detected in {k0} of {R0} replicates (Clopper–Pearson 95% interval [{lo0}, {hi0}]%), more often than the nominal {nominal}% allows",
    "A4PA_NEG": "; the exclusion bound may be too narrow, because the permuted negative-control column was detected in {k0} of {R0} replicates (Clopper–Pearson upper bound {hi0}%), more often than the nominal {nominal}% allows",
    "A4PA_NEGC": "; the bound may be too narrow (permuted negative-control column detected in {k0} of {R0}, upper bound {hi0}%)",
    "A4PS_NEG": "Because the permuted negative-control column was detected in {k0} of {R0} replicates, more often than the nominal {nominal}% allows, the pipeline may produce spurious detections and the {task_label} exclusion bounds may be too narrow.",
    "A4PS_NEGB": "Because the permuted negative-control column was detected in {k0} of {R0} replicates, more often than the nominal {nominal}% allows, the pipeline may produce spurious detections, and the reliable {task_label} increments are qualified accordingly.",
    "A4PX_RUN2": "The negative-control diagnostic uses {R0} permuted-null replicates: {R0a} of the frozen design and {R0b} added by the fourth pre-score addendum before any planted-signal result existed.",
    "A4PX_NOT2": "The pre-specified extension to 200 permuted-null replicates was not run ({reason}); the negative-control diagnostic uses the {R0} replicates of the frozen design.",
    "A4C0b": "Content-specific attribution cannot be reached in this design, and no increment is described as specific to the language model. For notices, the activity-matched reassignment control has no matched key by construction; for news, its matched keys, computed before scoring from the input-side mask, cover {keys} of {total} keys ({share}%) on {days} of {n_days} days, fewer than the seven days its frozen secondary rule requires, so it is not evaluable. Every reliable increment is therefore described as an increment over its activity reference; the 28-day shift comparison and the comparison with the pre-specified cheap-text representations are reported beside it as secondary readings. All comparisons are predictive, not causal.",
    "A4CHS2": "Against the pre-specified cheap-text representations of the same {documents} (secondary, unadjusted), {arm} {cheap_list}: {cheap_reading}.",
    "A4CHR_BETTER": "better than the pre-specified cheap-text representations",
    "A4CHR_NOT": "not better than the pre-specified cheap-text representations",
    "A4CHR_UND": "undetermined, because a required cheap-text comparator was not available",
    "A4CAP_LEAR": "Because the comparison with price-only LEAR was not available, no reading here applies to a forecaster as strong as that benchmark.",
    "A4CAP_CHEAP": "Because a required cheap-text comparator was not available, these readings say nothing about value over cheaper text representations.",
    "A4CAP_L1": "Because the absolute-error family was not completed, the news readings are specific to the squared-error training objective.",
    "A4CAP_PD": "Because the pre-dispatch family was not completed, the news readings are specific to an information set without operator forecasts.",
    "A4CAP_ALL": "No reading here is a causal effect, a verified real-time trading gain or a cost comparison.",
    "A4AB_PDS": "For 2026 WattClarity news and AEMO market notices in Australia's National Electricity Market (NEM), we test whether language-model extractions improve on nested references holding the numerical inputs and text activity, in a retrospective out-of-sample evaluation locked by trusted timestamps before scoring, conditional on saved versions, declared availability clocks and the pre-specified learner and information set.",
    "A4NTL": "market notices (creation-date surrogate clocks)",
    "A4CLK": "Every notice reading uses the website creation date as a surrogate availability clock, not verified as the publication time.",
    "A4D6b": "The comparison values are interpretation aids and never enter a decision. For news, the literature reference value is 3.8% of the reference error, the smallest text-attributed error reduction with a significance test in the cited electricity forecasting work (day-ahead load, text against no text); it is a published comparison value, not a smallest effect of practical interest for price content beyond activity. For notices, the comparison value is 0.5% of the reference error: the equivalence tolerance of the earlier January–February 2026 notice test (window C), used here as a historical-effect reference; that tolerance was set after development results were known and is not an economic indifference threshold.",
    "CB_S1b": "persisted when each forecast was averaged equally with {bench}, combination {combo_robust}",
    "CB_S2b": "not detected when each forecast was averaged equally with {bench}, combination {combo_robust}",
    "CB_S3b": "reliably worse when each forecast was averaged equally with {bench}, combination {combo_robust}",
    "CB_NEUTRALb": "averaged equally with {bench}: {class}, combination {combo_robust}",
    "A4HR": "Statement-level proportions are descriptive: their judgements cluster within articles, so no interval is given.",
}
SENTENCES.update(AMENDMENT_2)
S_PHRASE = {'news': 'the 3.8% literature reference value', 'notice': A3.S_PHRASE['notice']}      # amendment 2, G8
SHORT_ARM = {'L_count': 'label-count', 'L_chen': 'attribute-embedding', 'L14': 'event-state', 'L_Laz': 'message-count',
             'L_chen_notice': 'notice-embedding'}
SENTENCES.update(AMENDMENT_1)
# Word lists (Appendix A4, verbatim).
CHECK_SHORT = {'one_day': 'one-day interval', 'seven_day': 'seven-day interval', 'hln': 'HLN', 'hac7': 'HAC7', 'three_seed': 'three-seed mean'}
BENCH_ABS = {'news': 'price-only LEAR', 'notice': 'the pre-dispatch-price reference'}
CS_WORDS_A4 = {IMP: 'a reliable improvement', NULL: 'no reliable difference', DET: 'a reliable deterioration', NE: 'not evaluable'}
TS_WORDS_A4 = {IMP: 'a reliable increment', NULL: 'no reliable increment', DET: 'a reliable deterioration'}
# Amendment 2, G1: every no-rejection class word says "detected".
CS_WORDS = {IMP: 'a reliable improvement', NULL: 'no reliable difference detected', DET: 'a reliable deterioration', NE: 'not evaluable'}
TS_WORDS = {IMP: 'a reliable increment', NULL: 'no reliable increment detected', DET: 'a reliable deterioration'}
COMBO_ROBUST = {'ROBUST': 'inferentially robust', 'FRAGILE': 'fragile', 'NOT_FULLY_CHECKED': 'not fully checked'}
MDE_CMP = ('below', 'at or above')
HIST_CMP = ('below both of', 'between', 'at or above both of')
LOWER_HIGHER = ('lower', 'higher')
N1_WORDS = ('it agreed with the replicated tier', 'it disagreed with the replicated tier', 'this check was not available')
TASK_LABEL_ABS = {'news': 'day-ahead news', 'notice': 'market notices (creation-date surrogate clocks)'}     # amendment 2, G8
STAGE_NAMES_NEW = {'A2B-1': 'absolute-error objective and no-tier arms', 'A2B-2': 'pre-dispatch input arms',
                   'A2LABEL': 'label replacement', 'PC': 'planted-signal check', 'PCX': 'planted-signal null extension'}
STAGE_CATEGORIES = ('completed', 'completed apart from recorded unavailable configurations', 'not run', 'deviation', 'pending')
CONF_STAGES = ('primary_news', 'primary_notice', 'report_only_2025_validation', 'secondary_notice', 'secondary_news',
               'secondary_LEAR', 'primary_seed_robustness_notice', 'primary_seed_robustness_news', 'window_24h',
               'first_L_notice', 'first_L_news')
N_STAGES = 16
ACTIVITY_WORDS = {'news': 'article activity', 'notice': 'notice activity'}
MN_PAIR = {'news': ('M', 'N'), 'notice': ('M_notice', 'N')}
SHIFT_PAIR = {'news': ('L_chen', 'P_shift'), 'notice': ('L_chen_notice', 'P_shift')}
HIST_NEWS = (0.18, 0.32)
LAYER2_OWN = ('label_replacement', 'l1_family', 'pd_family')         # rendered by Q2 and by the batch sentences
BANNED_A4 = ('its input data were unavailable', 'improved by', 'Secondary families differed', 'in direction and decision',
             'in direction or decision', 'agreed with it in direction', 'are in Section', 'SESOI', 'upper bound on sensitivity',
             'it is content-specific', 'it is LLM-specific', 'content-specific and LLM-specific', 'content-specific but not',
             'smallest effect size of interest', 'LLM-specific', 'no structured representation improved')
SUPERSEDES = {
    'A4AB_P': ['FILL3a template abstract.s1 (kept verbatim; now an A4 form)'],
    'A4AB_DS': ['FILL3a template abstract.s2'],
    'A4AB_Y0': ['A3Y1', 'A3Y2'], 'A4AB_Y1': ['A3Y1', 'A3Y2'], 'A4AB_Y2': ['A3Y1', 'A3Y2'],
    'A4AB_A': ['A3AB_NULL', 'FILL3a abstract.compact_task/compact_tail/pointer_null_task/minimal_null_task'],
    'A4AB_B': ['A3AB_INC', 'A3AB_OTHER', 'A3AB_OTHERD', 'FILL3a abstract.compact_task/pointer_task/minimal_task/skeleton_task'],
    'A4AB_C': ['A3AB_CL', 'A3AB_CLD', 'A3AB_INC (clause part)', 'FILL3a abstract.compact_inc/compact_null/compact_det/pointer_inc/pointer_other/skeleton_inc'],
    'A4AB_CX': ['A3AB_CLX', 'A3AB_OTHERX', 'FILL3a abstract.compact_ne'],
    'A4AB_Q1': ['A3Q1 (abstract and conclusion only; A3Q1 stays in section 6.3)', 'FILL3a abstract.compact_q/pointer_q/minimal_q'],
    'A4AB_Q2': ['A3Q2 (abstract and conclusion only; A3Q2 stays in section 6.3)', 'FILL3a abstract.compact_q/pointer_q/minimal_q'],
    'A4PA_SENS': ['A3PA_SENS (abstract)', 'FILL3a abstract.minimal_pc_sens'], 'A4PA_SIZE': ['A3PA_SIZE (abstract)', 'FILL3a abstract.minimal_pc_size'],
    'A4NR': ['A2BATCH A7 with A3 STATE_REASON'], 'A4NR_BUDGET': ['A3 STATE_REASON NOT_RUN_BUDGET', 'FILL3a batch_reasons.NOT_RUN_BUDGET'],
    'A4NR_PARITY': ['A3 STATE_REASON NOT_RUN_PARITY_FAILED', 'FILL3a batch_reasons.NOT_RUN_PARITY_FAILED'],
    'A4DEV': ['A3 STATE_REASON NOT_RUN_INPUT_UNAVAILABLE "its input data were unavailable"', 'FILL3a batch_reasons.NOT_RUN_INPUT_UNAVAILABLE'],
    'A4CO_Y': ['A3CO_Y'],
    'A4H1': ['A3H1'], 'A4H2': ['A3H2'], 'A4H2F': ['A3H2 (fragile or not fully checked increments)'], 'A4H3': ['A3H3'],
    'A4R1': ['A2 R1'], 'A4R2': ['A2 R2'], 'A4R4': ['A3R4'], 'A4T7': ['A3T7'],
    'A4C1': ['A3C1', 'A3C2', 'A3C3', 'A2 C4', 'A2 C5 (unreachable)'], 'A4C0': ['A2 C6 (news, pre-score coverage sentence)'],
    'A4S1': ['A2 S1'], 'A4S2': ['A3S2'], 'A4S3': ['A2 S3'], 'A4S4': ['A2 S4'], 'A4S5': ['A2 S5'], 'A4S6': ['A2 S6'],
    'A4G1': ['A3G1'], 'A4N2': ['A3M1 (news only; notices keep A3M1)'], 'A4D1P': ['A3D1 (when the planted-signal check failed)'],
    'A4D6': ['A3D6'], 'A4P1T': ['A3P1T'], 'A4PB_SIZE': ['A3PB_SIZE'],
    'A4ST_EXEC': ['FILL3a template design.execution'],
    'A4PCN': ['every rendered number of a notice P_content row'], 'A4PCW': ['every rendered number of a news P_content row'],
}

# ---------------------------------------------------------------- small helpers
join_list = A2.join_list
finite = A2.finite


def cap(text):
    return text[:1].upper() + text[1:] if text else text


def sfmt(value, d):
    """Signed effect display: '+' for positive, '-' for negative, no sign when it rounds to zero."""
    text = A2.fmt_effect(value, d)
    if text == 'undefined':
        return text
    return '+' + text if float(text) > 0 else text


def validator_words(text):
    """validate_MS12.py line 77 count (regular expression on the plain abstract)."""
    return len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*", text))


def whitespace_words(text):
    return len(text.split())


def decimals(interval):
    return A2.percent_decimals(None if not interval else interval[1] - interval[0])


def clopper_pearson(x, n, level=0.95):
    """Exact copy of the frozen positive-control runner's interval."""
    from scipy.stats import beta
    a = (1 - level) / 2
    lo = 0.0 if x == 0 else float(beta.ppf(a, x, n - x + 1))
    hi = 1.0 if x == n else float(beta.ppf(1 - a, x + 1, n - x))
    return [lo, hi]


def envelope(row):
    """Amendment 2 G3: conservative envelope of the one-day and seven-day family-adjusted intervals."""
    f1, f7 = row.get('interval_family_one_day'), row.get('interval_family_seven_day')
    if not f1 or not all(finite(v) for v in f1):
        return None
    ok7 = bool(f7) and all(finite(v) for v in f7)
    lo = min(float(f1[0]), float(f7[0])) if ok7 else float(f1[0])
    hi = max(float(f1[1]), float(f7[1])) if ok7 else float(f1[1])
    return {'U': max(0.0, -lo), 'lo': lo, 'hi': hi, 'seven_missing': not ok7}


def order_stat_range(draws, q):
    """Distribution-free 95% order-statistic interval of the q-quantile of the finite draws (amendment 2, G3)."""
    x = np.sort(np.asarray([v for v in draws if finite(v)], dtype='float64'))
    B = len(x)
    if B == 0:
        return None
    c = 1.96 * math.sqrt(B * q * (1 - q))
    r_lo = max(1, int(math.floor(B * q - c)))
    r_hi = min(B, int(math.ceil(B * q + c)) + 1)
    return [float(x[r_lo - 1]), float(x[r_hi - 1])]


def mc_flag_from_ranges(lower_ranges, S):
    """True when the envelope bound U lies on different sides of S across the Monte Carlo ranges of the lower ends."""
    ranges = [r for r in lower_ranges if r]
    if not ranges:
        return False
    u_small = max(0.0, -max(r[1] for r in ranges))
    u_large = max(0.0, -min(r[0] for r in ranges))
    return (u_small < S) != (u_large < S)


def mc_flags(sc, daily_frame, rows, source):
    """Per primary contrast: Monte Carlo ranges of the family-adjusted lower ends and the A4MC flag."""
    days = daily_frame['target_day'].tolist()
    picks = A2.complete_picks(sc, len(days))
    m = len(A2.FAMILIES[source])
    q = A2.ALPHA / (2 * m)
    out = {}
    for r in rows:
        arm, ref = r['arm'], r['reference']
        if arm not in daily_frame or ref not in daily_frame:
            continue
        a, b = daily_frame[arm].to_numpy(), daily_frame[ref].to_numpy()
        ranges = {}
        for block in (1, 7):
            if picks.get(block) is None:
                continue
            draws = sc.paired_percent_interval(a, b, picks[block])['draws']
            ranges[str(block)] = order_stat_range(draws, q)
        out[f'{arm}-{ref}'] = {'lower_end_mc_range': ranges,
                               'flag': mc_flag_from_ranges(list(ranges.values()), A3.SESOI[source])}
    return out


def hist_cmp_news(x):
    lo, hi = HIST_NEWS
    return HIST_CMP[0] if x < lo else (HIST_CMP[1] if x < hi else HIST_CMP[2])


# ---------------------------------------------------------------- secondary slots (frozen reports)
def slot_reading(inputs, secondary, arm, ref):
    """Estimate, unadjusted 95% interval, DM p and single-contrast class of a frozen secondary slot."""
    slot = A2.slot_lookup(secondary, arm, ref)
    if not slot or slot.get('state') != 'COMPUTED_SECONDARY':
        return {'state': (slot or {}).get('state', 'NOT_FOUND'), 'arm': arm, 'reference': ref}
    rep = None
    path = slot.get('report_path')
    if path and Path(path).name in inputs.score_files:
        rep = inputs.score_json(Path(path).name)['reports'][0]
    if rep is None:
        return {'state': 'NOT_FOUND', 'arm': arm, 'reference': ref}
    dm = rep.get('dm_p1') or {}
    one = (rep.get('bootstrap') or {}).get('1') or (rep.get('bootstrap') or {}).get(1) or {}
    mean, p = dm.get('mean_difference'), dm.get('p_two_sided')
    return {'state': 'COMPUTED', 'arm': arm, 'reference': ref, 'mean_difference': mean, 'p_two_sided': p,
            'effect': one.get('effect_percent_reference_mae'), 'interval95': one.get('interval95_percent'),
            'class': A2.decision_class(mean, p), 'days': slot.get('days')}


def reason_phrase(state):
    return A2.STATE_PHRASE.get(state, 'it was not computed')


# ---------------------------------------------------------------- F2: three-seed family intervals
def three_seed_family(sc, inputs, source):
    """Family-adjusted intervals of the frozen three-seed equal prediction mean (sealed predictions only)."""
    frozen = inputs.score_json(source + '__THREE_SEED_MEAN.json', required=False)
    if frozen is None:
        return {'state': 'NOT_AVAILABLE', 'reason': 'the extra-seed predictions were not available'}
    truth = inputs.truth(source)
    pairs = A2.FAMILIES[source]
    arms = list(dict.fromkeys(a for pair in pairs for a in pair))
    daily = {}
    for arm in arms:
        preds = [inputs.prediction(source, arm, truth, seed=s) for s in (A2.SEED,) + A2.EXTRA_SEEDS]
        if any(p is None for p in preds):
            return {'state': 'NOT_AVAILABLE', 'reason': 'the extra-seed predictions were not available'}
        mean = np.mean(preds, axis=0)
        if source == 'notice':
            mean = mean.astype('float32')
        days, daily[arm] = A2.daily_abs_loss(truth, mean)
    picks = A2.complete_picks(sc, len(days))
    m = len(pairs)
    out = {}
    for saved in frozen['reports']:
        pair = (saved['arm'], saved['reference'])
        if pair not in pairs:
            continue
        r = A2.contrast_stats(sc, daily[pair[0]], daily[pair[1]], picks, m)
        theirs = ((saved.get('bootstrap') or {}).get('1') or (saved.get('bootstrap') or {}).get(1) or {}).get('interval95_percent')
        mine = r['bootstrap']['1'].get('interval95_percent')
        if (mine is None) != (theirs is None) or (mine is not None and max(abs(x - y) for x, y in zip(mine, theirs)) > 1e-9):
            raise ValueError('Recomputed three-seed interval differs from the frozen THREE_SEED_MEAN file: ' + '-'.join(pair))
        out['-'.join(pair)] = {'state': 'COMPUTED', 'class': saved.get('primary_decision'), 'holm_p': saved.get('primary_two_sided_holm_p'),
                               'mean_difference': (saved.get('dm_p1') or {}).get('mean_difference'),
                               'effect': r['effect_percent_reference_mae'], 'interval95': mine,
                               'interval_family': r['bootstrap']['1'].get('interval_family_adjusted_percent')}
    return {'state': 'COMPUTED', 'pairs': out}


# ---------------------------------------------------------------- P: positive control with CP bounds and PCX
def pc_state_a4(source, pc_result, pcx_result=None, pc_sha=None):
    """A3 frozen reading (re-derived) plus the null CP interval; PCX extension to 200 null replicates when bound."""
    base = A3.pc_state(source, pc_result)
    if base['state'] == 'NOT_RUN':
        return {**base, 'extension': 'NOT_APPLICABLE'}
    rows = {float(r['mult']): r for r in pc_result['summary'] if r['task'] == source and r['tier'] == A3.PC_TIER[source]}
    null = rows[0.0]
    out = dict(base)
    out['cp0'] = list(null['detection_cp95'])
    out['frozen_k0'], out['frozen_R0'] = base['k0'], base['R0']
    out['extension'] = 'NOT_RUN'
    out['extension_reason'] = 'no extension result was available at the time of the fill'
    ext = None
    if pcx_result is not None:
        if pcx_result.get('frozen_result_sha256') != pc_sha:
            raise A4ConsistencyError('PCX result does not bind the frozen positive-control result')
        ext = [r for r in pcx_result.get('rows', []) if r.get('task') == source and r.get('tier') == A3.PC_TIER[source]]
        reps = sorted(int(r['replicate']) for r in ext)
        if reps != list(range(41, 201)):
            raise A4ConsistencyError('PCX replicates must be exactly 41..200 for ' + source)
    if ext is not None:
        k_ext = int(sum(bool(r['detected']) for r in ext))
        out.update(k0=base['k0'] + k_ext, R0=base['R0'] + len(ext), extension='RUN', k0_extension=k_ext, R0_extension=len(ext))
        out['cp0'] = clopper_pearson(out['k0'], out['R0'])
        out['lo0'] = out['cp0'][0]
        sens = base['state'] in ('PASS', 'SIZE_FAILS')
        inflated = bool(out['cp0'][0] > base['nominal'])
        out['state'] = {(True, False): 'PASS', (False, False): 'SENSITIVITY_FAILS', (True, True): 'SIZE_FAILS',
                        (False, True): 'BOTH_FAIL'}[(sens, inflated)]
        out['frozen_state'] = base['state']
    out['n1_agrees'] = (pc_result.get('readings') or {}).get('N1_AGREES_WITH_N2')
    return out


def pc_fields_a4(source, pc):
    f = A3.pc_fields(source, pc)
    f.update(k0=pc['k0'], R0=pc['R0'], lo0=f"{100 * pc['cp0'][0]:.2f}", hi0=f"{100 * pc['cp0'][1]:.2f}")
    return f


def pc_sentences(source, scenario, pc):
    """Section 6 planted-signal sentences (A4P1T, A3PS_*, A4PB_PASS, A4PX_*)."""
    if pc['state'] == 'NOT_RUN':
        return [A3.SENTENCES['A3PS_NOTRUN'].format(task_label=A3.TASK_LABEL[source], reason=pc['reason'])]
    f = pc_fields_a4(source, pc)
    out = [SENTENCES['A4P1T'].format(**f)]
    if pc.get('extension') == 'RUN':
        out.append(SENTENCES['A4PX_RUN2'].format(R0=pc['R0'], R0a=pc['frozen_R0'], R0b=pc['R0_extension']))
    else:
        out.append(SENTENCES['A4PX_NOT2'].format(reason=pc.get('extension_reason'), R0=pc['R0']))
    sens_fail = pc['state'] in ('SENSITIVITY_FAILS', 'BOTH_FAIL')
    size_fail = pc['state'] in ('SIZE_FAILS', 'BOTH_FAIL')
    if scenario == 'A':
        if sens_fail:
            out.append(A3.SENTENCES['A3PS_SENS'].format(**f))
        if size_fail:
            out.append(SENTENCES['A4PS_NEG'].format(**f))
    else:
        if sens_fail:
            out.append(A3.SENTENCES['A3PS_POWER'].format(**f))
        if size_fail:
            out.append(SENTENCES['A4PS_NEGB'].format(**f))
        else:
            out.append(SENTENCES['A4PB_DIAG'].format(**f))
    if pc.get('attenuates'):
        out.append(A3.SENTENCES['A3PS_ATT'].format(task_label=A3.TASK_LABEL[source]))
    return out


# ---------------------------------------------------------------- K1: batch dispositions
def batch_disposition(fam_rep):
    """'COMPUTED', 'PENDING', ('NOT_RUN', reason key), ('DEVIATION',) or raises for an impossible state."""
    if not fam_rep:
        return ('PENDING',)
    state = fam_rep.get('state')
    if state == 'COMPUTED':
        return ('COMPUTED',)
    source_state = fam_rep.get('source_state', state)
    if state == 'NOT_RUN_BUDGET' and source_state in ('NOT_RUN_BUDGET', 'INCOMPLETE_BUDGET'):
        return ('NOT_RUN', 'A4NR_BUDGET')
    if state == 'NOT_RUN_PARITY_FAILED':
        return ('NOT_RUN', 'A4NR_PARITY')
    if state == 'NOT_RUN_INPUT_UNAVAILABLE' and source_state == 'INCOMPLETE_FAILURE':
        return ('DEVIATION',)
    raise A4ConsistencyError(f'Impossible batch family state under the frozen design: {state} / {source_state}')


def batch_texts(batch, compact=False):
    """Not-run and deviation sentences for the L1 and PD families (rule K1; compact forms at L6, amendment 1)."""
    out = []
    for fam in ('l1_family', 'pd_family'):
        rep = ((batch or {}).get('families') or {}).get(A3.BATCH_FAMILY_KEY[fam])
        disp = batch_disposition(rep)
        name = A3.BATCH_FAMILY_NAME[fam]
        if disp[0] == 'NOT_RUN':
            out.append(SENTENCES['A4NR'].format(family_name=name, reason=SENTENCES[disp[1] + ('C' if compact else '')]))
        elif disp[0] == 'DEVIATION':
            out.append(SENTENCES['A4DEVC' if compact else 'A4DEV'].format(family_name=name))
    return out


def batch_differences(source, rows, batch):
    """Per (family, arm) whose batch class differs from the primary class: values for A4AB_Q1/A4AB_Q2."""
    out = []
    if source != 'news':
        return out
    pcls = {(r['arm'], r['reference']): r.get('decision') for r in rows}
    for fam, key in (('l1_family', 'Q1'), ('pd_family', 'Q2')):
        rep = ((batch or {}).get('families') or {}).get(A3.BATCH_FAMILY_KEY[fam])
        if batch_disposition(rep)[0] != 'COMPUTED':
            continue
        by = {(r['arm'], r['reference']): r for r in rep['reports']}
        for pair, bpair in A3.BATCH_PAIRS[fam].items():
            r = by.get(bpair)
            if r is None or pcls.get(pair) not in CLASSES:
                continue
            bcls = A2.decision_class(r.get('mean_difference'), r.get('holm_p'))
            if bcls not in CLASSES or bcls == pcls[pair]:
                continue
            one = (r.get('bootstrap') or {}).get('1', {})
            d = decimals(one.get('interval95_percent'))
            lo, hi = A2.fmt_interval(one.get('interval_family_adjusted_percent'), d)
            effect = r.get('effect_percent_reference_mae', one.get('effect_percent_reference_mae'))
            out.append({'family': fam, 'key': key, 'arm': pair[0], 'class': bcls, 'effect': effect,
                        'se': sfmt(effect, d), 'lo': lo, 'hi': hi, 'mean_difference': r.get('mean_difference')})
    return out


def q_sentence(source, q, compact):
    key = ('A4AB_' + q['key'] + ('C' if compact else ''))
    return SENTENCES[key].format(arm_words=A3.ARM_WORDS[source][q['arm']], se=q['se'], lo=q['lo'], hi=q['hi'],
                                 **{'class': TS_WORDS[q['class']]})


# ---------------------------------------------------------------- per-contrast state
def contrast_state(source, row, rob, dissent_items, label_cls, ts, combo_row, combo_rob, pc, scenario, attribution):
    """Everything the abstract, section 6 and conclusion need for one primary contrast."""
    cls = row.get('decision')
    info = {'arm': row['arm'], 'words': A3.ARM_WORDS[source][row['arm']], 'class': cls, 'source': source}
    if cls not in CLASSES:
        info['reason'] = row.get('not_evaluable_reason') or A3.SENTENCES['A3H4R']
        return info
    d = decimals(row.get('interval95_one_day'))
    lo, hi = A2.fmt_interval(row.get('interval_family_one_day'), d)
    effect = row.get('effect_percent_reference_mae')
    fam = row.get('interval_family_one_day')
    info.update(d=d, lo=lo, hi=hi, se=sfmt(effect, d), effect=effect, aud=A3.aud(row.get('mean_difference')),
                p=A2.display_p(row.get('holm_p')), zero=bool(A3.zero_clause(source, cls, fam)), robust=rob,
                dissent_items=dissent_items, label_cls=label_cls)
    size_fail = pc.get('state') in ('SIZE_FAILS', 'BOTH_FAIL')
    sens_fail = pc.get('state') in ('SENSITIVITY_FAILS', 'BOTH_FAIL')
    info['robust_ok'] = rob['label'] == 'ROBUST'
    info['size_fail'] = size_fail and cls == IMP and scenario == 'B'
    info['prec'] = sens_fail and cls == NULL and scenario == 'B'
    info['ts'] = ts
    env = envelope(row)
    info['envelope'] = env
    info['mc_flag'] = bool(row.get('_mc_flag'))
    if cls == IMP:
        info['sesoi_class'] = A3.sesoi_increment_class(effect, [env['lo'], env['hi']] if env else fam, A3.SESOI[source])
        info['combo'] = combo_row
        info['combo_robust'] = combo_rob
        info['attribution'] = attribution
    return info


def q1_text(info, level):
    """Robustness qualifier (AB4 item 1) and the design dissent."""
    rob = info['robust']
    parts = []
    if rob['label'] == 'ROBUST':
        parts.append(SENTENCES['Q_ROBUST'])
    elif rob['label'] == 'FRAGILE':
        three = info.get('ts') or {}
        if three.get('state') == 'COMPUTED':
            d = decimals(three.get('interval95'))
            lo, hi = A2.fmt_interval(three.get('interval_family'), d)
            ts_text = (SENTENCES['Q_TS_NUM'].format(se=sfmt(three.get('effect'), d), lo=lo, hi=hi, **{'class': TS_WORDS.get(three.get('class'), 'not evaluable')})
                       if level <= 2 else TS_WORDS.get(three.get('class'), 'not evaluable'))
        else:
            ts_text = SENTENCES['Q_TS_NA']
        parts.append(SENTENCES['Q_FRAG'].format(checks=join_list(CHECK_SHORT[k] for k in rob['dissent']), ts=ts_text))
        if rob['unavailable']:
            parts.append(SENTENCES['Q_NFC'].format(checks=join_list(CHECK_SHORT[k] for k in rob['unavailable'])))
    else:
        parts.append(SENTENCES['Q_NFC'].format(checks=join_list(CHECK_SHORT[k] for k in rob['unavailable'])))
    if info.get('dissent_items'):
        parts.append(SENTENCES['Q_DISSENT'].format(items=join_list(info['dissent_items'])))
    return parts


def quals_for(info, level, drop=()):
    """Qualifiers in the AB4 retention order; `drop` removes those stated once per task at L5."""
    source = info['source']
    q = q1_text(info, level)
    if info.get('label_cls'):
        q.append(SENTENCES['Q_ERD'].format(**{'class': TS_WORDS[info['label_cls']]}))
    if info.get('size_fail') and 'size' not in drop:
        q.append(SENTENCES['Q_SIZE'])
    if info.get('prec') and 'prec' not in drop:
        q.append(SENTENCES['Q_PREC'])
    if info['class'] == IMP:
        bench = BENCH_ABS[source]
        combo = info.get('combo')
        crob = info.get('combo_robust') or 'not fully checked'
        if info['robust_ok']:
            q.append(SENTENCES['Q_ATTR'].format(activity_words=ACTIVITY_WORDS[source]))
            ic = (SENTENCES['IC_' + info['sesoi_class'] + '_C'].format(S=A3.SESOI[source]) if level >= 6
                  else SENTENCES['IC_' + info['sesoi_class']].format(S_phrase=S_PHRASE[source]))
            if info.get('size_fail'):
                ic += SENTENCES['Q_NARROW']
            q.append(ic)
            key = (combo or {}).get('clause_id')
            if combo is None or key not in ('S1', 'S2', 'S3'):
                q.append(SENTENCES['CB_S7'])
            else:
                q.append(SENTENCES['CB_' + key + 'b'].format(bench=bench, combo_robust=crob))
        else:
            if 'notassigned' not in drop:
                q.append(SENTENCES['Q_NOTASSIGNED'])
            if combo is None or combo.get('decision') not in CLASSES:
                q.append(SENTENCES['CB_S7'])
            else:
                q.append(SENTENCES['CB_NEUTRALb'].format(bench=bench, combo_robust=crob, **{'class': TS_WORDS[combo['decision']]}))
    return q


def class_text(info, level):
    cls = info['class']
    aud = level <= 2
    if cls == IMP:
        key = ('CT_INC' if info['robust_ok'] else 'CT_PS') + ('_AUD' if aud else '')
    elif cls == DET:
        key = 'CT_DET' + ('_AUD' if aud else '')
    else:
        key = 'CT_NULL2'
    text = SENTENCES[key].format(aud=info.get('aud'))
    if cls in (IMP, DET) and info.get('zero'):
        text += SENTENCES['CT_ZERO']
    return text


def show_interval(info, level):
    if info['class'] == NULL:
        return level <= 3
    return level <= 5


def abstract_clause(info, level, drop=()):
    if info['class'] not in CLASSES:
        return SENTENCES['A4AB_CX'].format(arm_words=info['words'], reason=info['reason'])
    interval = f" [{info['lo']}, {info['hi']}]" if show_interval(info, level) else ''
    quals = ''.join('; ' + q for q in quals_for(info, level, drop))
    return SENTENCES['A4AB_C'].format(arm_words=info['words'], se=info['se'], interval=interval,
                                      class_text=class_text(info, level), quals=quals)


def task_clauses(infos, level):
    """Contrast clauses of one task; at L5 identical null clauses are merged and shared qualifiers stated once."""
    drop, task_quals = set(), ''
    if level >= 5:
        incs = [i for i in infos if i['class'] == IMP]
        if len(incs) >= 2 and all(i.get('size_fail') for i in incs):
            drop.add('size'); task_quals += SENTENCES['A4AB_TQ'].format(qualifier=SENTENCES['Q_SIZE'], kind='increment')
        ps = [i for i in incs if not i['robust_ok']]
        if len(ps) >= 2:
            drop.add('notassigned'); task_quals += SENTENCES['A4AB_TQ'].format(qualifier=SENTENCES['Q_NOTASSIGNED'], kind='primary-seed increment')
        nulls = [i for i in infos if i['class'] == NULL]
        if len(nulls) >= 2 and all(i.get('prec') for i in nulls):
            drop.add('prec'); task_quals += SENTENCES['A4AB_TQ'].format(qualifier=SENTENCES['Q_PREC'], kind='null reading')
    clauses, merged = [], set()
    if level >= 5:
        groups = {}
        for idx, i in enumerate(infos):
            if i['class'] == NULL:
                groups.setdefault(tuple(quals_for(i, level, drop)), []).append(idx)
        for key, idxs in groups.items():
            if len(idxs) >= 2:
                merged.update(idxs[1:])
                members = [infos[k] for k in idxs]
                if level >= 6:
                    clauses.append((idxs[0], SENTENCES['A4AB_CGS'].format(
                        short_list=join_list(SHORT_ARM[m['arm']] for m in members), effect_list=join_list(m['se'] + '%' for m in members),
                        class_text=SENTENCES['CT_NULL2'], quals=''.join('; ' + q for q in key))))
                else:
                    clauses.append((idxs[0], SENTENCES['A4AB_CG'].format(
                        arm_list=join_list(m['words'] for m in members), effect_list=join_list(m['se'] + '%' for m in members),
                        interval_list='', class_text=SENTENCES['CT_NULL2'], quals=''.join('; ' + q for q in key))))
                merged.add(idxs[0])
    for idx, i in enumerate(infos):
        if idx not in merged:
            clauses.append((idx, abstract_clause(i, level, drop)))
    clauses.sort()
    return [c for _, c in clauses], task_quals


def mn_text(mn, level):
    if mn.get('state') != 'COMPUTED':
        return SENTENCES['A4AB_MNX'].format(reason=reason_phrase(mn.get('state')))
    d = decimals(mn.get('interval95'))
    se = sfmt(mn.get('effect'), d)
    if level >= 4:
        return SENTENCES['A4AB_MNC'].format(se=se, **{'class': CS_WORDS[mn['class']]})
    lo, hi = A2.fmt_interval(mn.get('interval95'), d)
    return SENTENCES['A4AB_MN'].format(se=se, lo=lo, hi=hi, **{'class': CS_WORDS[mn['class']]})


def task_sentence(source, t, level):
    """One abstract task sentence at a ladder level (also the conclusion at L0)."""
    if t['scenario'] == 'INCOMPLETE':
        return A3.SENTENCES['A3AB_INCOMPLETE'].format(task_label=TASK_LABEL_ABS[source], reason=t['incomplete_reason'])
    clauses, task_quals = task_clauses(t['infos'], level)
    if t['scenario'] == 'B':
        return SENTENCES['A4AB_B'].format(task_label=TASK_LABEL_ABS[source], activity_words=ACTIVITY_WORDS[source],
                                         clauses='; '.join(clauses), task_quals=task_quals)
    mn = mn_text(t['mn'], level)
    if t['bound'] is None:
        return SENTENCES['A4AB_ANE'].format(task_label=TASK_LABEL_ABS[source], activity_words=ACTIVITY_WORDS[source], mn=mn,
                                           clauses='; '.join(clauses))
    X, d, seven_missing, mc = t['bound']
    S = A3.SESOI[source]
    extra = (SENTENCES['A4ENV_X'] if seven_missing else '') + (SENTENCES['A4MC'].format(S_phrase=S_PHRASE[source]) if mc else '')
    if level >= 6:
        context = SENTENCES['A4AB_HNC'] if source == 'news' else (SENTENCES['A4AB_CTXC'] if A3.hist_cmp(X) == A3.HIST_CMP[1]
                                                                    else A3.SENTENCES['A3AB_CTX'].format(hist_cmp=A3.hist_cmp(X)))
    else:
        context = SENTENCES['A4AB_HN'] if source == 'news' else A3.SENTENCES['A3AB_CTX'].format(hist_cmp=A3.hist_cmp(X))
    pc = t['pc']
    pcs = ''
    if pc['state'] == 'PASS' and level <= 2:
        pcs += '; ' + A3.SENTENCES['A3P2'].format(**pc_fields_a4(source, pc))
    if pc['state'] in ('SENSITIVITY_FAILS', 'BOTH_FAIL'):
        pcs += SENTENCES['A4PA_SENSC' if level >= 6 else 'A4PA_SENS'].format(**pc_fields_a4(source, pc))
    if pc['state'] in ('SIZE_FAILS', 'BOTH_FAIL'):
        pcs += SENTENCES['A4PA_NEGC' if level >= 6 else 'A4PA_NEG'].format(**pc_fields_a4(source, pc))
    return SENTENCES['A4AB_AC' if level >= 6 else 'A4AB_A'].format(task_label=TASK_LABEL_ABS[source], activity_words=ACTIVITY_WORDS[source], mn=mn,
                                     clauses='; '.join(clauses), X=A2.branch_safe_bound(X, d, S), tail=A3.TAIL_TEXT[source],
                                     below_or_above='below' if X < S else 'at or above', S_phrase=S_PHRASE[source],
                                     context=extra + context, pc=pcs, task_quals=task_quals)


def lear_tail(lear, compact):
    if lear.get('state') != 'COMPUTED':
        return SENTENCES['A4LT_NE'].format(reason=reason_phrase(lear.get('state')))
    d = decimals(lear.get('interval95'))
    se = sfmt(lear.get('effect'), d)
    if compact:
        return SENTENCES['A4LT_OKC2'].format(se=se, **{'class': CS_WORDS[lear['class']]})
    lo, hi = A2.fmt_interval(lear.get('interval95'), d)
    return SENTENCES['A4LT_OK'].format(se=se, lo=lo, hi=hi, **{'class': CS_WORDS[lear['class']]})


def abstract_at(tasks, extras, level):
    y = {0: 'A4AB_Y0', 1: 'A4AB_Y1', 2: 'A4AB_Y1'}.get(level, 'A4AB_Y3' if level >= 6 else 'A4AB_Y2')
    parts = [SENTENCES['A4AB_PDS'], SENTENCES[y].format(lear_tail=lear_tail(extras['lear'], level >= 6))]
    for source in ('news', 'notice'):
        parts.append(task_sentence(source, tasks[source], level))
    for q in extras['batch_differences']:
        parts.append(q_sentence('news', q, compact=level >= 5))
    if level <= 1:
        parts.append(A3.SENTENCES['A3H0'])
    parts.extend(batch_texts(extras['batch'], compact=True) if level >= 6 else extras['batch_texts'])
    return ' '.join(parts)


def abstract_ladder(tasks, extras):
    """Rule AB5: first level whose validator count is at most 250; otherwise L7 (L6 text, overflow recorded)."""
    counts = []
    for level in range(7):
        text = abstract_at(tasks, extras, level)
        counts.append({'level': f'L{level}', 'validator_words': validator_words(text), 'whitespace_words': whitespace_words(text)})
        if counts[-1]['validator_words'] <= WORD_LIMIT:
            return {'level': f'L{level}', 'text': text, 'counts': counts, 'abstract_over_limit': False}
    return {'level': 'L7', 'text': text, 'counts': counts, 'abstract_over_limit': True}


# ---------------------------------------------------------------- section 6
def robustness_sentence(rob, dissent_items):
    if rob['label'] == 'ROBUST':
        text = SENTENCES['A4R1']
    elif rob['label'] == 'FRAGILE':
        text = SENTENCES['A4R2'].format(dissent_list=join_list(A2.CHECK_NAME[k] for k in rob['dissent']))
        if rob['unavailable'] and '; ' in rob['sentence']:
            text += '; ' + rob['sentence'].split('; ', 1)[1]
    else:
        text = rob['sentence']
    if dissent_items:
        text += SENTENCES['A4RD'].format(items=join_list(dissent_items))
    return text


def combination_text_a4(source, combo_row, combo_rob, robust_ok, arm_symbol):
    if combo_row is None:
        return A3.as_clause(A2.SENTENCES['S7'].format(benchmark=A2.BENCHMARK_NAME[source], reason='the combination contrast was not computed'))
    one = combo_row['bootstrap']['1']
    d = decimals(one.get('interval95_percent'))
    lo, hi = A2.fmt_interval(one.get('interval_family_adjusted_percent'), d)
    f = dict(benchmark=A2.BENCHMARK_NAME[source], effect=A2.fmt_effect(combo_row.get('effect_percent_reference_mae'), d),
             level=A3.LEVEL_TEXT[source], lo=lo, hi=hi, p=A2.display_p(combo_row.get('holm_p')), combo_robust=combo_rob,
             arm=arm_symbol(combo_row['arm']))
    cls = combo_row.get('decision')
    if cls not in CLASSES:
        return A3.as_clause(A2.SENTENCES['S7'].format(benchmark=A2.BENCHMARK_NAME[source], reason='the combination contrast is undefined'))
    if not robust_ok:
        return SENTENCES['A4SN'].format(**f, **{'class': TS_WORDS[cls]})
    return SENTENCES[{IMP: 'A4S1', NULL: 'A4S2', DET: 'A4S3'}[cls]].format(**f)


def section6_contrast(source, info, row, pc, arm_symbol):
    arm = arm_symbol(row['arm'])
    if info['class'] not in CLASSES:
        return SENTENCES_A3('A3H4').format(arm=arm, activity=A3.ACTIVITY[source], reason=info['reason'])
    rob = info['robust']
    common = dict(arm=arm, activity=A3.ACTIVITY[source], se=info['se'], aud=info['aud'], level=A3.LEVEL_TEXT[source],
                  lo=info['lo'], hi=info['hi'], p=info['p'], robustness=robustness_sentence(rob, info['dissent_items']))
    quals = []
    if info.get('label_cls'):
        quals.append(A3.SENTENCES['A3QL'].format(reading_replacement=TS_WORDS[info['label_cls']]))
    zero = A3.zero_clause(source, info['class'], row.get('interval_family_one_day'))
    if info['class'] == NULL:
        return SENTENCES['A4H1b'].format(qualifiers=''.join('; ' + q for q in quals), **common)
    if info['class'] == DET:
        return SENTENCES['A4H3'].format(zero=zero, qualifiers=''.join('; ' + q for q in quals), **common)
    if info.get('size_fail'):
        quals.append(SENTENCES['A4PB_NEG'].format(**pc_fields_a4(source, pc)))
    bench = combination_text_a4(source, info.get('combo'), info.get('combo_robust') or 'not fully checked', info['robust_ok'], arm_symbol)
    if info['robust_ok']:
        key = {'BEYOND': 'A3S_BEYOND', 'ABOVE': 'A3S_ABOVE', 'BELOWPT': 'A3S_BELOWPT', 'BELOW': 'A3S_BELOW'}[info['sesoi_class']]
        sesoi = A3.SENTENCES[key].format(S_phrase=S_PHRASE[source], S=A3.SESOI[source], tail=A3.TAIL_TEXT[source])
        sesoi += SENTENCES['A4S_NARROW'] if info.get('size_fail') else ''
        return SENTENCES['A4H2'].format(zero=zero, attribution=SENTENCES['A4C1'].format(activity=A3.ACTIVITY[source]),
                                        sesoi=sesoi, benchmark=bench, qualifiers=''.join('; ' + q for q in quals), **common)
    ts = info.get('ts') or {}
    if ts.get('state') == 'COMPUTED':
        d = decimals(ts.get('interval95'))
        lo, hi = A2.fmt_interval(ts.get('interval_family'), d)
        three = SENTENCES['A4TS'].format(se=sfmt(ts.get('effect'), d), level=A3.LEVEL_TEXT[source], lo=lo, hi=hi,
                                         p=A2.display_p(ts.get('holm_p')), **{'class': TS_WORDS.get(ts.get('class'), 'not evaluable')})
    else:
        three = SENTENCES['A4TSX'].format(reason=ts.get('reason', 'the extra-seed predictions were not available'))
    return SENTENCES['A4H2F'].format(zero=zero, three_seed=three, benchmark=bench,
                                     qualifiers=''.join('; ' + q for q in quals) + SENTENCES['A4FT'], **common)


def SENTENCES_A3(key):
    return A3.SENTENCES[key]


def secondary_increment_readings(source, info, row, shift, cheap, arm_symbol):
    """A4CS and A4CHS beside a reliable increment (section T)."""
    arm = arm_symbol(row['arm'])
    out = []
    if row['arm'] == A2.CONTENT_ARM[source]:
        if shift.get('state') == 'COMPUTED':
            d = decimals(shift.get('interval95'))
            lo, hi = A2.fmt_interval(shift.get('interval95'), d)
            days = SENTENCES['A4CS_DAYS'].format(n=shift['days']) if source == 'notice' and shift.get('days') else ''
            out.append(SENTENCES['A4CS'].format(arm=arm, se=sfmt(shift.get('effect'), d), lo=lo, hi=hi,
                                                p=A2.display_p(shift.get('p_two_sided')), days=days,
                                                **{'class': CS_WORDS[shift['class']]}))
        else:
            out.append(SENTENCES['A4CSX'].format(arm=arm, reason=reason_phrase(shift.get('state'))))
    if cheap:
        computed, unavailable = cheap.get('computed') or {}, cheap.get('unavailable') or []
        pieces = [A3.CHEAP_PIECES[kind].format(list=join_list(A2.COMPARATOR_NAME[c] for c, v in computed.items() if v == kind))
                  for kind in ('beaten', 'not_beaten', 'worse') if kind in computed.values()]
        text = join_list(pieces) if pieces else 'could not be compared'
        if unavailable:
            text += ('; ' if pieces else ', because ') + join_list(A2.COMPARATOR_NAME[c] for c in unavailable) + ' ' + A3.was_were(unavailable) + ' not available'
        out.append(SENTENCES['A4CHS2'].format(documents=A2.DOCUMENTS[source], arm=arm, cheap_list=text,
                                             cheap_reading=SENTENCES[cheap_reading_key(cheap)]))
    return out


def cheap_reading_key(cheap):
    """Amendment 2 G6: fixed required set; a missing required comparator gives 'undetermined'."""
    computed, unavailable = cheap.get('computed') or {}, cheap.get('unavailable') or []
    if unavailable or not computed:
        return 'A4CHR_UND'
    return 'A4CHR_BETTER' if all(v == 'beaten' for v in computed.values()) else 'A4CHR_NOT'


def mn_section(source, mn):
    if mn.get('state') != 'COMPUTED':
        return SENTENCES['A4MNX'].format(activity_words=ACTIVITY_WORDS[source], reason=reason_phrase(mn.get('state')))
    d = decimals(mn.get('interval95'))
    lo, hi = A2.fmt_interval(mn.get('interval95'), d)
    return SENTENCES['A4MN'].format(activity_words=ACTIVITY_WORDS[source], se=sfmt(mn.get('effect'), d), aud=A3.aud(mn.get('mean_difference')),
                                    lower_higher=LOWER_HIGHER[0] if (mn.get('mean_difference') or 0) < 0 else LOWER_HIGHER[1],
                                    lo=lo, hi=hi, p=A2.display_p(mn.get('p_two_sided')), **{'class': CS_WORDS[mn['class']]})


def lear_section(lear):
    if lear.get('state') != 'COMPUTED':
        return SENTENCES['A4LEARX'].format(reason=reason_phrase(lear.get('state')))
    d = decimals(lear.get('interval95'))
    lo, hi = A2.fmt_interval(lear.get('interval95'), d)
    return SENTENCES['A4LEAR'].format(se=sfmt(lear.get('effect'), d), aud=A3.aud(lear.get('mean_difference')),
                                      lower_higher=LOWER_HIGHER[0] if (lear.get('mean_difference') or 0) < 0 else LOWER_HIGHER[1],
                                      lo=lo, hi=hi, p=A2.display_p(lear.get('p_two_sided')), **{'class': CS_WORDS[lear['class']]})


def g1_sentence_a4(tvn, table_ref='{table_ref}'):
    vals = [tvn.get(f'{a}-{b}') or {} for a, b in A3.TEXT_VS_NO_TEXT]
    if any(v.get('state') != 'COMPUTED' for v in vals):
        return None
    f = {}
    for i, v in enumerate(vals, 1):
        d = decimals(v.get('interval95'))
        lo, hi = A2.fmt_interval(v.get('interval95'), d)
        f.update({f'e{i}': sfmt(v.get('effect'), d), f'l{i}': lo, f'h{i}': hi, f'c{i}': CS_WORDS[v['class']]})
    return SENTENCES['A4G1'].format(table_ref=table_ref, **f)


def task_section6(source, t, rows, arm_symbol):
    """Section 6 sentence list of one task, in the A4 placement order."""
    if t['scenario'] == 'INCOMPLETE':
        return [A3.SENTENCES['A3H6'].format(task_label=A3.TASK_LABEL[source], reason=t['incomplete_reason'])]
    out, d7 = ([SENTENCES['A4CLK']] if source == 'notice' else []), False
    pc = t['pc']
    pc_fail = pc['state'] in ('SENSITIVITY_FAILS', 'SIZE_FAILS', 'BOTH_FAIL')
    for info, row in zip(t['infos'], rows):
        out.append(section6_contrast(source, info, row, pc, arm_symbol))
        if info['class'] == NULL and info.get('envelope'):
            env = info['envelope']
            X = env['U']
            S = A3.SESOI[source]
            xb = A2.branch_safe_bound(X, info['d'], S)
            if X < S:
                sent = (SENTENCES['A4D1P'].format(X=xb, tail=A3.TAIL_TEXT[source], S_phrase=S_PHRASE[source]) if (pc_fail and t['scenario'] == 'A')
                        else A3.SENTENCES['A3D1'].format(X=xb, tail=A3.TAIL_TEXT[source], S_phrase=S_PHRASE[source]))
            else:
                sent = A3.SENTENCES['A3D2'].format(X=xb, tail=A3.TAIL_TEXT[source], S_phrase=S_PHRASE[source])
            extra = (SENTENCES['A4ENV_X'] if env['seven_missing'] else '') + (SENTENCES['A4MC'].format(S_phrase=S_PHRASE[source]) if info.get('mc_flag') else '')
            out.append(sent[:-1] + extra + '.' if extra else sent)
            if not d7:
                out.append(A3.SENTENCES['A3D7']); d7 = True
        if info['class'] == IMP:
            out.extend(secondary_increment_readings(source, info, row, t['shift'], (info.get('attribution') or {}).get('cheap_text'), arm_symbol))
    out.append(A3.SENTENCES['A3C7'] if source == 'notice' else t['matched_sentence'])
    out.append(mn_section(source, t['mn']))
    if t['scenario'] == 'A' and t['bound'] is not None:
        X, d, seven_missing, mc = t['bound']
        S = A3.SESOI[source]
        pc_clauses = []
        if pc['state'] in ('SENSITIVITY_FAILS', 'BOTH_FAIL'):
            pc_clauses.append(A3.SENTENCES['A3PA_SENS'].format(**pc_fields_a4(source, pc)))
        if pc['state'] in ('SIZE_FAILS', 'BOTH_FAIL'):
            pc_clauses.append(SENTENCES['A4PA_NEG'][2:].format(**pc_fields_a4(source, pc)))
        out.append(A3.SENTENCES['A3H5'].format(X=A2.branch_safe_bound(X, d, S), tail=A3.TAIL_TEXT[source],
                                               below_or_above='below' if X < S else 'at or above', S_phrase=S_PHRASE[source],
                                               task_qualifiers=''.join('; ' + c for c in pc_clauses)))
        mr = {IMP: 'A4MNR_IMPb', NULL: 'A4MNR_NULLb', DET: 'A4MNR_DETb'}.get(t['mn'].get('class'))
        if t['mn'].get('state') == 'COMPUTED' and mr:
            out.append(SENTENCES[mr])
        if source == 'news':
            out.append(SENTENCES['A4N2'].format(mde_cmp=A3.mde_cmp(X, source), hist_cmp=hist_cmp_news(X)))
            g1 = g1_sentence_a4(t['tvn'])
            if g1:
                out.append(g1)
        else:
            out.append(A3.SENTENCES['A3M1'].format(task_label=A3.TASK_LABEL[source], X=A2.branch_safe_bound(X, d, A3.MDE_PERCENT[source]),
                                                   mde_cmp=A3.mde_cmp(X, source), mde=A3.MDE_PERCENT[source]))
            out.append(A3.SENTENCES['A3N1'].format(hist_cmp=A3.hist_cmp(X)))
    if source == 'news':
        out.append(lear_section(t['lear']))
    out.extend(pc_sentences(source, t['scenario'], pc))
    if source == 'news' and pc['state'] != 'NOT_RUN':
        n1 = pc.get('n1_agrees')
        out.append(SENTENCES['A4P1N'].format(n1=N1_WORDS[0] if n1 is True else (N1_WORDS[1] if n1 is False else N1_WORDS[2])))
        out.append(SENTENCES['A4P0'])
    return out


def section7_2(source, t, a3_s72):
    out = []
    if t['scenario'] != 'INCOMPLETE' and t['infos'] and all(i.get('robust', {}).get('label') == 'ROBUST' for i in t['infos']):
        out.append(SENTENCES['A4R4'].format(task_label=A3.TASK_LABEL[source]))
    out.extend(s for s in a3_s72 if not s.startswith('Every primary reading of the'))
    return out


# ---------------------------------------------------------------- per-task assembly
def design_dissent(states, pair):
    items = []
    for name, st in (states.get(pair) or {}).items():
        if name in LAYER2_OWN or st.get('state') != 'DIFFERENT':
            continue
        items.append(SENTENCES['A4RD_ITEM'].format(sensitivity=A3.SENSITIVITY_NAMES[name], **{'class': A3.CLASS_WORDS[st['class']]}))
    return items


def build_task(source, rows, a3_task, ts, pc, slots, matched_sentence, incomplete_reason=None):
    """A4 task record from A2 primary rows, the A3 task output and the A4 additions (also used by the fixtures)."""
    if incomplete_reason:
        return {'scenario': 'INCOMPLETE', 'incomplete_reason': incomplete_reason, 'infos': [], 'pc': pc}
    scenario = 'B' if any(r.get('decision') == IMP for r in rows) else 'A'
    combo = {}
    if ((a3_task.get('combination') or {}).get('state')) == 'COMPUTED':
        combo = {(r['arm'], r['reference']): r for r in a3_task['combination']['family']['reports']}
    crob = a3_task.get('combination_robustness_a3') or {}
    attr = {a['arm']: a for a in a3_task.get('attribution_a3', [])}
    infos = []
    for r in rows:
        pair = (r['arm'], r['reference'])
        key = f'{pair[0]}-{pair[1]}'
        rob = a3_task['robustness_a3'][key]
        states = {pair: a3_task['design_sensitivities'].get(key, {})}
        lab = states[pair].get('label_replacement', {})
        label_cls = lab.get('class') if lab.get('state') == 'DIFFERENT' else None
        cr = crob.get(key)
        infos.append(contrast_state(source, r, rob, design_dissent(states, pair), label_cls,
                                    (ts.get('pairs') or {}).get(key) if ts.get('state') == 'COMPUTED' else {'state': 'NOT_AVAILABLE', 'reason': ts.get('reason')},
                                    combo.get(pair), COMBO_ROBUST.get((cr or {}).get('label')), pc, scenario, attr.get(r['arm'])))
    bound = task_bound_a4(rows, infos)
    return {'scenario': scenario, 'infos': infos, 'pc': pc, 'mn': slots['mn'], 'lear': slots.get('lear', {}),
            'shift': slots.get('shift', {}), 'tvn': slots.get('tvn', {}), 'bound': bound,
            'matched_sentence': matched_sentence}


def task_bound_a4(rows, infos):
    """Largest envelope bound U over the evaluable contrasts without an increment, with its decimals and flags."""
    best = None
    for r, info in zip(rows, infos):
        env = info.get('envelope')
        if r.get('decision') in (NULL, DET) and env:
            cand = (env['U'], decimals(r.get('interval95_one_day')), env['seven_missing'], info.get('mc_flag', False))
            if best is None or cand[0] > best[0]:
                best = cand
    if best is None:
        return None
    d = max(decimals(r.get('interval95_one_day')) for r, i in zip(rows, infos) if r.get('decision') in (NULL, DET) and i.get('envelope'))
    return (best[0], d, best[2], best[3])


# ---------------------------------------------------------------- K3: stage table
def stage_table(score_report, batch, label, pc_present, pcx_present):
    rows = []
    disp = {d.get('stage'): d for d in (score_report or {}).get('stage_dispositions', [])}
    unexpected = sorted(set(disp) - set(CONF_STAGES))
    for name in CONF_STAGES:
        d = disp.get(name)
        state = (d or {}).get('state')
        cat = ('pending' if d is None else 'completed' if state == 'COMPLETE' else
               'completed apart from recorded unavailable configurations' if state in ('COMPLETE_WITH_UNAVAILABLE_CONFIGURATIONS', 'COMPLETE_WITH_FAILURES') else 'not run')
        rows.append({'stage': name, 'state': state, 'category': cat, 'reason': (d or {}).get('reason')})
    for stage, fam in (('A2B-1', 'l1_family'), ('A2B-2', 'pd_family')):
        rep = ((batch or {}).get('families') or {}).get(A3.BATCH_FAMILY_KEY[fam])
        disposition = batch_disposition(rep)
        cat = {'COMPUTED': 'completed', 'PENDING': 'pending', 'NOT_RUN': 'not run', 'DEVIATION': 'deviation'}[disposition[0]]
        rows.append({'stage': stage, 'state': (rep or {}).get('state'), 'category': cat,
                     'reason': SENTENCES[disposition[1]] if disposition[0] == 'NOT_RUN' else None})
    lab_state = (label or {}).get('state')
    rows.append({'stage': 'A2LABEL', 'state': lab_state, 'category': 'pending' if label is None else
                 ('completed' if lab_state == 'A2LABEL_SCORED' else 'not run'), 'reason': (label or {}).get('reason')})
    rows.append({'stage': 'PC', 'state': 'SCORED' if pc_present else None, 'category': 'completed' if pc_present else 'pending', 'reason': None})
    rows.append({'stage': 'PCX', 'state': 'SCORED' if pcx_present else None, 'category': 'completed' if pcx_present else 'pending', 'reason': None})
    if len(rows) != N_STAGES:
        raise A4ConsistencyError('Stage table must have 16 rows')
    for r in rows:
        r['unexpected_conf_stages'] = unexpected
    return rows


def execution_sentence(rows, table_ref='{table_ref}'):
    count = {c: sum(r['category'] == c for r in rows) for c in STAGE_CATEGORIES}
    reasons = sorted({r['reason'] for r in rows if r['category'] == 'not run' and r['stage'] in ('A2B-1', 'A2B-2') and r.get('reason')})
    return SENTENCES['A4ST_EXEC'].format(total=len(rows), table_ref=table_ref, done=count['completed'],
                                         partial=count['completed apart from recorded unavailable configurations'],
                                         not_run=count['not run'], not_run_reasons=(' (' + '; '.join(reasons) + ')') if reasons else '',
                                         deviation=count['deviation'], pending=count['pending']), count


# ---------------------------------------------------------------- K4: consistency assertions
def consistency_violations(result, coverage=None, rendered=None):
    """Rule K4. `result` is the A4 output (or its task records); `rendered` optional extra texts. Returns a list."""
    v = []
    for source, task in result['tasks'].items():
        for row in task.get('primary_rows', []):
            cls, mean, holm = row.get('decision'), row.get('mean_difference'), row.get('holm_p')
            if cls == IMP and (not finite(mean) or mean >= 0):
                v.append(f'K4.1 {source} {row["arm"]}: increment with mean difference {mean}')
            if cls == DET and (not finite(mean) or mean <= 0):
                v.append(f'K4.1 {source} {row["arm"]}: deterioration with mean difference {mean}')
            if cls in (IMP, DET) and not (finite(holm) and holm < A2.ALPHA):
                v.append(f'K4.1 {source} {row["arm"]}: rejection class with Holm p {holm}')
            if cls == NULL and finite(holm) and holm < A2.ALPHA:
                v.append(f'K4.1 {source} {row["arm"]}: no rejection with Holm p {holm}')
            eff = row.get('effect_percent_reference_mae')
            if cls == IMP and finite(eff) and eff >= 0 or cls == DET and finite(eff) and eff <= 0:
                v.append(f'K4.2 {source} {row["arm"]}: class and effect sign disagree')
        for key, slot in (task.get('pcontent_slots') or {}).items():
            if slot.get('state') == 'COMPUTED_SECONDARY':
                if source == 'notice':
                    v.append(f'K4.1 notice {key}: P_content slot evaluable although no key can match by construction')
                elif coverage is not None and coverage.get('days_with_matched_key', 0) < 7:
                    v.append(f'K4.1 news {key}: P_content slot evaluable although the coverage file has fewer than seven days')
        for label_row in task.get('class_rows', []):
            cls, eff = label_row.get('class'), label_row.get('effect')
            if cls in (IMP,) and finite(eff) and eff >= 0 or cls == DET and finite(eff) and eff <= 0:
                v.append(f'K4.2 {source} {label_row.get("name")}: class and effect sign disagree')
        for s in task.get('section6', []):
            for b in BANNED_A4:
                if b in s:
                    v.append(f'K4.6 {source} section 6 contains "{b}"')
        for info in task.get('infos_flat', []):
            zero_needed = info.get('zero')
            s6 = info.get('section6', '')
            if info['class'] in (IMP, DET):
                if zero_needed and "Holm's sequential rule rejected" not in s6:
                    v.append(f'K4.3 {source} {info["arm"]}: missing Holm clause')
                if not zero_needed and "Holm's sequential rule rejected" in s6:
                    v.append(f'K4.3 {source} {info["arm"]}: Holm clause without a zero-covering interval')
    rows = result.get('stage_table') or []
    if rows:
        counts = result.get('stage_counts') or {}
        if len(rows) != N_STAGES or sum(counts.get(c, 0) for c in STAGE_CATEGORIES) != N_STAGES:
            v.append('K4.4 stage counts are not conserved')
        if rows[0].get('unexpected_conf_stages'):
            v.append('K4.4 unexpected CONF stages: ' + ', '.join(rows[0]['unexpected_conf_stages']))
        if any(r['category'] == 'pending' for r in rows if r['stage'] in CONF_STAGES):
            v.append('K4.4 a CONF stage has no recorded disposition after scoring')
    ab = result.get('abstract') or {}
    text = ab.get('text', '')
    for b in BANNED_A4 + ('Section',):
        if b in text:
            v.append(f'K4.5/K4.6 abstract contains "{b}"')
    for req in result.get('abstract_required', []):
        if req not in text:
            v.append(f'K4.5 abstract lacks required qualifier "{req}"')
    for t in (rendered or []):
        for b in BANNED_A4:
            if b in t:
                v.append(f'K4.6 rendered text contains "{b}"')
    return v


def required_qualifiers(tasks):
    """Exact substrings that must appear in the abstract for every contrast (rule K4.5)."""
    req = []
    for source, t in tasks.items():
        for info in t.get('infos', []):
            if info['class'] not in CLASSES:
                continue
            rob = info['robust']
            if rob['label'] == 'FRAGILE':
                req.append('fragile: ' + join_list(CHECK_SHORT[k] for k in rob['dissent']) + ' disagreed')
            elif rob['label'] == 'NOT_FULLY_CHECKED':
                req.append('not fully checked: ' + join_list(CHECK_SHORT[k] for k in rob['unavailable']) + ' unavailable')
            else:
                req.append(SENTENCES['Q_ROBUST'])
            if info.get('label_cls'):
                req.append('extraction-run-dependent: ' + A3.CLASS_WORDS[info['label_cls']])
            if info.get('size_fail'):
                req.append(SENTENCES['Q_SIZE'])
            if info.get('prec'):
                req.append(SENTENCES['Q_PREC'])
            if info['class'] == IMP:
                if info['robust_ok']:
                    req.append(SENTENCES['Q_ATTR'].format(activity_words=ACTIVITY_WORDS[source]))
                    req.append({'BEYOND': 'interval wholly beyond', 'ABOVE': 'interval straddling it', 'BELOWPT': 'interval straddling it',
                                'BELOW': 'interval wholly below'}[info['sesoi_class']])
                else:
                    req.append(SENTENCES['CT_PS'])
                    req.append(SENTENCES['Q_NOTASSIGNED'])
            if info['class'] in (IMP, DET) and info.get('zero'):
                req.append('although its family-adjusted interval includes zero')
    return list(dict.fromkeys(req))


# ---------------------------------------------------------------- assembly for one rendering (fixtures and run)
def render(tasks, extras, rows_by_task, arm_symbol=None):
    """Abstract (ladder), section 6, section 7.2 and conclusion from A4 task records."""
    arm_symbol = arm_symbol or (lambda a: a)
    ladder = abstract_ladder(tasks, extras)
    sec6 = {s: task_section6(s, tasks[s], rows_by_task.get(s, []), arm_symbol) for s in ('news', 'notice')}
    conclusion = [task_sentence(s, tasks[s], 0) for s in ('news', 'notice')]
    conclusion += [q_sentence('news', q, compact=False) for q in extras['batch_differences']]
    for s in ('news', 'notice'):
        t = tasks[s]
        for info, row in zip(t.get('infos', []), rows_by_task.get(s, [])):
            if info['class'] == IMP:
                conclusion += secondary_increment_readings(s, info, row, t['shift'], (info.get('attribution') or {}).get('cheap_text'),
                                                           lambda a, s=s: A3.ARM_WORDS[s][a])
    conclusion.append(A3.SENTENCES['A3H0'])
    conclusion.extend(extras['batch_texts'])
    conclusion.append(SENTENCES['A4CO_Y'].format(lear_tail=lear_tail(extras['lear'], False)))
    conclusion.extend(caps(tasks, extras))
    return {'abstract': ladder, 'section6': sec6, 'conclusion_core': conclusion,
            'abstract_required': required_qualifiers(tasks), 'result_states': result_states(tasks, rows_by_task)}


def caps(tasks, extras):
    """Amendment 2 G7: conclusion caps for incomplete key comparisons (A4CAP_ALL always last)."""
    out = []
    if (extras.get('lear') or {}).get('state') != 'COMPUTED' or not extras.get('combination_ok', True):
        out.append(SENTENCES['A4CAP_LEAR'])
    undetermined = any(cheap_reading_key((i.get('attribution') or {}).get('cheap_text') or {}) == 'A4CHR_UND'
                       for t in tasks.values() for i in t.get('infos', []) if i['class'] == IMP)
    if undetermined:
        out.append(SENTENCES['A4CAP_CHEAP'])
    for fam, key in (('l1_family', 'A4CAP_L1'), ('pd_family', 'A4CAP_PD')):
        rep_ = ((extras.get('batch') or {}).get('families') or {}).get(A3.BATCH_FAMILY_KEY[fam])
        if batch_disposition(rep_)[0] != 'COMPUTED':
            out.append(SENTENCES[key])
    out.append(SENTENCES['A4CAP_ALL'])
    return out


def result_states(tasks, rows_by_task):
    """Amendment 2 G2: one record per primary contrast and per secondary reading, read by every output."""
    out = []
    for source, t in tasks.items():
        n_days = 214 if source == 'news' else 61
        for info, row in zip(t.get('infos', []), rows_by_task.get(source, [])):
            rob = info.get('robust') or {}
            out.append({'task': source, 'role': 'primary', 'contrast': f"{row['arm']}-{row['reference']}", 'primary_class': info['class'],
                        'inference_agreement': rob.get('label'), 'dissenting_checks': rob.get('dissent', []),
                        'unavailable_checks': rob.get('unavailable', []), 'design_dissent': info.get('dissent_items', []),
                        'extraction_run_dependent': info.get('label_cls'),
                        'attribution_eligibility': ('eligible: increment over the activity reference only' if info['class'] == IMP and info.get('robust_ok')
                                                    else 'not assigned' if info['class'] == IMP else 'not applicable'),
                        'support': {'days': n_days} if info['class'] in CLASSES else 'none',
                        'unavailability': info.get('reason'), 'confirmatory_class_allowed': True})
        for name in ('mn', 'lear', 'shift'):
            slot = t.get(name) or {}
            if not slot:
                continue
            ok = slot.get('state') == 'COMPUTED'
            out.append({'task': source, 'role': 'single secondary', 'contrast': name, 'primary_class': slot.get('class') if ok else NE,
                        'support': {'days': slot.get('days') or n_days} if ok else 'none',
                        'unavailability': None if ok else reason_phrase(slot.get('state')), 'confirmatory_class_allowed': True})
        out.append({'task': source, 'role': 'descriptive subset', 'contrast': 'exposure, re-admission and matched-support subsets',
                    'primary_class': SENTENCES['A4SUB'], 'confirmatory_class_allowed': False})
        out.append({'task': source, 'role': 'single secondary', 'contrast': 'P_content rows',
                    'primary_class': NE, 'support': 'none', 'unavailability': SENTENCES['A4PCN'] if source == 'notice' else 'fewer than seven matched days',
                    'confirmatory_class_allowed': False})
    return out


def coverage_record(path=COVERAGE_FILE, expected_sha=COVERAGE_SHA256):
    if sha256(path) != expected_sha:
        raise PermissionError('Pre-score coverage file drift')
    return json.loads(Path(path).read_text())


def coverage_sentence(cov):
    n = cov['news']
    return SENTENCES['A4C0b'].format(keys=f"{n['matched_keys']:,}", total=f"{n['total_keys']:,}", share=f"{n['matched_share_percent']:.1f}",
                                     days=n['days_with_matched_key'], n_days=n['n_days'])


def pcontent_cells(cov):
    n = cov['news']
    return {'notice': SENTENCES['A4PCN'], 'news': SENTENCES['A4PCW'].format(days=n['days_with_matched_key'], n_days=n['n_days'])}


# ---------------------------------------------------------------- run
def verify_a4_documents():
    """The addendum and amendment 1 must equal their freeze records, and the amendment must bind the addendum freeze."""
    for freeze_path in (ADDENDUM_FREEZE, AMENDMENT_1_FREEZE, AMENDMENT_2_FREEZE):
        for name, ident in json.loads(freeze_path.read_text())['files'].items():
            if sha256(A4_ROOT / name) != ident['sha256']:
                raise PermissionError('Frozen A4 document drift: ' + name)
    if json.loads(AMENDMENT_1_FREEZE.read_text())['addendum_freeze_sha256'] != sha256(ADDENDUM_FREEZE):
        raise PermissionError('Amendment 1 does not bind the frozen addendum')
    a2f = json.loads(AMENDMENT_2_FREEZE.read_text())
    if a2f['addendum_freeze_sha256'] != sha256(ADDENDUM_FREEZE) or a2f['amendment_1_freeze_sha256'] != sha256(AMENDMENT_1_FREEZE):
        raise PermissionError('Amendment 2 does not bind the frozen addendum and amendment 1')


def _optional_json(path):
    if path is None or not Path(path).exists():
        return None, None
    return json.loads(Path(path).read_text()), sha256(path)


def run(state, out=None, conf_root=CONF_ROOT, grid=None, pc_path=DEFAULT_PC, pcx_path=DEFAULT_PCX, a2batch_path=DEFAULT_A2BATCH,
        a2label_path=DEFAULT_A2LABEL, coverage_path=COVERAGE_FILE, coverage_sha=COVERAGE_SHA256, strict=True):
    state = Path(state).resolve()
    out = Path(out).resolve() if out else state / 'a4_scored'
    for forbidden in ('scored', 'a2_scored', 'a3_scored'):
        f = (state / forbidden).resolve()
        if out == f or f in out.parents:
            raise PermissionError('A4 never writes into ' + forbidden + '/')
    verify_a4_documents()
    cov = coverage_record(coverage_path, coverage_sha)
    sc = A2.load_frozen_scoring(conf_root)
    inputs = A2.Inputs(state, grid)
    pc_result, pc_sha = _optional_json(pc_path)
    pcx_result, pcx_sha = _optional_json(pcx_path)
    batch, batch_sha = _optional_json(a2batch_path)
    label, label_sha = _optional_json(a2label_path)
    a2_tasks = {s: A2.run_task(sc, inputs, s) for s in ('news', 'notice')}
    a3_tasks = {s: A3.run_task_a3(sc, inputs, s, a2_tasks[s], pc_result, batch, label) for s in ('news', 'notice')}
    saved_a3 = state / 'a3_scored' / 'A3_POSTSCORE.json'
    if saved_a3.exists():
        saved = json.loads(saved_a3.read_text())['tasks']
        if json.loads(json.dumps(A2.json_safe(a3_tasks), sort_keys=True)) != saved:
            raise ValueError('Saved A3 output differs from the frozen A3 re-run with the same optional inputs')
    report = inputs.score_json('SCORE_REPORT.json')
    tasks, rows_by_task, records = {}, {}, {}
    for source in ('news', 'notice'):
        secondary = report[source]['secondary']
        rows = [dict(r) for r in a2_tasks[source]['primary']]
        mc = mc_flags(sc, inputs.daily_losses(source), rows, source)
        for r in rows:
            r['_mc_flag'] = (mc.get(f"{r['arm']}-{r['reference']}") or {}).get('flag', False)
        rows_by_task[source] = rows
        slots = {'mn': slot_reading(inputs, secondary, *MN_PAIR[source]),
                 'shift': slot_reading(inputs, secondary, *SHIFT_PAIR[source])}
        if source == 'news':
            slots['lear'] = slot_reading(inputs, secondary, 'LEAR', 'N')
            slots['tvn'] = {f'{a}-{b}': slot_reading(inputs, secondary, a, b) for a, b in A3.TEXT_VS_NO_TEXT}
        ts = three_seed_family(sc, inputs, source)
        pc = pc_state_a4(source, pc_result, pcx_result, pc_sha)
        ms = a3_tasks[source]['matched_support']
        if source == 'news':
            if ms.get('state') in ('TOO_FEW_DAYS', 'COMPUTED') and ms.get('days') != cov['news']['days_with_matched_key']:
                raise A4ConsistencyError('Matched-support days differ from the pre-score coverage file')
            matched_sentence = ms.get('sentence') or A3.SENTENCES['A3W0'].format(n=cov['news']['days_with_matched_key'])
        else:
            matched_sentence = A3.SENTENCES['A3C7']
        tasks[source] = build_task(source, rows, dict(a3_tasks[source], combination=a2_tasks[source]['combination']), ts, pc, slots,
                                   matched_sentence)
        pslots = {f"{s['arm']}-{s['reference']}": s for s in secondary if 'P_content' in (s.get('arm'), s.get('reference'))}
        records[source] = {'three_seed': ts, 'positive_control': pc, 'slots': slots, 'pcontent_slots': pslots, 'monte_carlo': mc}
    extras = {'lear': tasks['news'].get('lear', {}), 'batch_differences': batch_differences('news', rows_by_task['news'], batch),
              'batch_texts': batch_texts(batch), 'batch': batch,
              'combination_ok': (a2_tasks['news'].get('combination') or {}).get('state') == 'COMPUTED'}
    rendered = render(tasks, extras, rows_by_task)
    stages = stage_table(report, batch, label, pc_result is not None, pcx_result is not None)
    exec_sentence, counts = execution_sentence(stages)
    result = {'analysis': 'CONF-A4 post-score readings (reporting, gating and consistency; no primary decision changes)',
              'addendum_freeze_sha256': sha256(ADDENDUM_FREEZE), 'amendment_1_freeze_sha256': sha256(AMENDMENT_1_FREEZE),
              'amendment_2_freeze_sha256': sha256(AMENDMENT_2_FREEZE),
              'module_sha256': sha256(Path(__file__)),
              'a3_module_sha256': sha256(A3_ROOT / 'code/a3_postscore.py'), 'seal_sha256': inputs.seal_sha256,
              'coverage_sha256': coverage_sha,
              'optional_inputs': {'positive_control': pc_sha, 'pcx': pcx_sha, 'a2batch': batch_sha, 'a2label': label_sha},
              'tasks': {}, 'abstract': rendered['abstract'], 'abstract_required': rendered['abstract_required'],
              'conclusion_core': rendered['conclusion_core'], 'stage_table': stages, 'stage_counts': counts,
              'execution_sentence': exec_sentence,
              'methods_sentences': [SENTENCES['A4D6b'], SENTENCES['A4M_DEF'], coverage_sentence(cov), SENTENCES['A4HR']],
              'result_states': rendered['result_states'],
              'table_cells': {'pcontent': pcontent_cells(cov)}, 'table6_caption': SENTENCES['A4T7']}
    for source in ('news', 'notice'):
        t = tasks[source]
        infos_flat = []
        for info, row, s6 in zip(t.get('infos', []), rows_by_task[source], rendered['section6'][source]):
            infos_flat.append({'arm': info['arm'], 'class': info['class'], 'zero': info.get('zero', False), 'section6': s6})
        result['tasks'][source] = {
            'scenario': t['scenario'], 'section6': rendered['section6'][source],
            'section7_2': section7_2(source, t, a3_tasks[source]['texts']['section7_2']),
            'primary_rows': rows_by_task[source], 'infos_flat': infos_flat,
            'gating': [{'arm': i['arm'], 'class': i['class'], 'robust_label': (i.get('robust') or {}).get('label'),
                        'strong_labels_assigned': bool(i['class'] == IMP and i.get('robust_ok'))} for i in t.get('infos', [])],
            **records[source]}
    violations = consistency_violations(result, cov['news'])
    result['consistency_violations'] = violations
    if violations and strict:
        raise A4ConsistencyError('; '.join(violations))
    result['inputs_read'] = inputs.read_log
    result['primary_decision_rule_changed'] = False
    out.mkdir(parents=True, exist_ok=True)
    path = out / 'A4_POSTSCORE.json'
    path.write_text(json.dumps(A2.json_safe(result), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n')
    receipt = {'state': 'A4_POSTSCORE_COMPLETE', 'output': {'path': str(path), 'sha256': sha256(path)},
               'seal_sha256': inputs.seal_sha256, 'addendum_freeze_sha256': sha256(ADDENDUM_FREEZE),
               'module_sha256': sha256(Path(__file__)), 'inputs_read': inputs.read_log, 'optional_inputs': result['optional_inputs'],
               'abstract_level': rendered['abstract']['level'], 'abstract_over_limit': rendered['abstract']['abstract_over_limit']}
    (out / 'A4_POSTSCORE_RECEIPT.json').write_text(json.dumps(A2.json_safe(receipt), indent=2, sort_keys=True) + '\n')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--positive-control', type=Path, default=DEFAULT_PC)
    parser.add_argument('--pcx', type=Path, default=DEFAULT_PCX)
    parser.add_argument('--a2batch', type=Path, default=DEFAULT_A2BATCH)
    parser.add_argument('--a2label', type=Path, default=DEFAULT_A2LABEL)
    args = parser.parse_args(argv)
    result = run(args.state, args.out, pc_path=args.positive_control, pcx_path=args.pcx, a2batch_path=args.a2batch,
                 a2label_path=args.a2label)
    print(json.dumps({'state': 'A4_POSTSCORE_COMPLETE', 'abstract_level': result['abstract']['level']}))


if __name__ == '__main__':
    main()
