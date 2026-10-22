"""Write RULES_FOR_FILL3.json from the frozen ADDENDUM_A2 sentence forms (single source: a2_postscore.SENTENCES).

The sentence strings are verified verbatim against the frozen ADDENDUM_A2.md (tests). Abridged abstract forms and
plain-language code phrases are presentation rules added here before any score (frozen with the code, stage 2).
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

A2 = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('a2_postscore', A2 / 'code/a2_postscore.py')
a2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a2)
S = a2.SENTENCES


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def pick(*keys):
    return {k: S[k] for k in keys}


RULES = {
    'about': ('Reading and wording rules for the FILL3 manuscript fill, from the frozen CONF-A2 addendum. Plain language; '
              'no internal codes in rendered text. Values come from <state>/a2_scored/A2_POSTSCORE.json (written by '
              'CONF/A2/code/a2_postscore.py after cli.py score) and from the frozen score outputs. Placeholders are in '
              'braces. Nothing here changes a frozen primary decision.'),
    'sources': {
        'addendum': 'autopilot/q1_audits/CONF/A2/ADDENDUM_A2.md',
        'addendum_sha256': sha(A2 / 'ADDENDUM_A2.md'),
        'addendum_freeze': 'autopilot/q1_audits/CONF/A2/ADDENDUM_A2_FREEZE.json',
        'addendum_freeze_sha256': sha(A2 / 'ADDENDUM_A2_FREEZE.json'),
        'a2batch_spec': 'autopilot/q1_audits/CONF/A2/A2BATCH_SPEC.md',
        'a2batch_spec_sha256': sha(A2 / 'A2BATCH_SPEC.md'),
        'postscore_module': 'autopilot/q1_audits/CONF/A2/code/a2_postscore.py',
        'postscore_module_sha256': sha(A2 / 'code/a2_postscore.py'),
        'a2_output': '<state>/a2_scored/A2_POSTSCORE.json',
        'run_command': ('/Users/stacchining/Documents/thesis/lamp-moe-research/.venv/bin/python '
                        '/Users/stacchining/Documents/thesis/lamp-moe-research/experiments/llm_controlled_study_prep_20260925/'
                        'autopilot/q1_audits/CONF/A2/code/a2_postscore.py --state '
                        '/Users/stacchining/Documents/thesis/lamp-moe-research/experiments/llm_controlled_study_prep_20260925/'
                        'autopilot/q1_audits/CONF/CONFX2/host_state'),
        'order': 'cli.py score (FROZEN_SCORE_COMPLETE) -> a2_postscore.py -> FILL3; A2BATCH and A2LABEL results arrive later and trigger a refill'},

    # ------------------------------------------------------------ display
    'display': {
        'p_value': {
            'rule': ('p < 0.001 -> "p < 0.001"; 0.001 <= p < 0.995 -> three decimals; p >= 0.995 -> "p > 0.99" (never "p = 1"); '
                     'if three decimals would put p on the other side of the threshold used in that sentence (.05, or alpha/m when '
                     'stated), show four decimals. Applies to raw, Holm-adjusted, HLN and HAC7 p values everywhere, including '
                     'tables. No scientific notation (no 10^-15, no 10^-121).'),
            'implementation': 'a2_postscore.display_p',
            'examples': {'0.0': 'p < 0.001', '1e-121': 'p < 0.001', '0.001': 'p = 0.001', '0.61': 'p = 0.610',
                         '0.0496': 'p = 0.0496', '0.0504': 'p = 0.050', '1.0': 'p > 0.99'},
            'adjusted_label': 'write "Holm-adjusted p ..." for adjusted values; never "pooled p = 1"'},
        'bootstrap_counts': 'tail counts stay counts, e.g. "0/2000 draws" with resolution 1/2000; never "p = 0"',
        'percentages': ('v1 rule unchanged: effect half-even, interval endpoints rounded outward, decimals d = clamp(1 - '
                        'floor(log10(one-day 95% width)), 3, 6); no "-0.000" (a2_postscore.fmt_effect/fmt_interval)'),
        'sign_convention': ('effects and intervals are signed changes in % of the named reference error; negative values '
                            'favour the representation. State this once in the methods. "improved by" uses the absolute value.'),
        'bound_display': ('a bound shown next to a SESOI keeps the side of the SESOI given by the exact value (more decimals if '
                          'needed, up to 12; a2_postscore.branch_safe_bound)')},

    # ------------------------------------------------------------ bound levels
    'bound_levels': {
        'news': {'family_m': 2, 'two_sided_level': 0.975, 'one_sided_tail': 0.0125, 'label': S['B1'].format(level='97.5')},
        'notice': {'family_m': 3, 'two_sided_level': 1 - 0.05 / 3, 'one_sided_tail': 0.05 / 6, 'label': S['B1'].format(level='98.3')},
        'tables': S['B2'],
        'rule': ('Headline statements (abstract, section 6 lead sentence, conclusion) use the family-adjusted one-day interval '
                 'and its bound X_fam = max(0, -lower). Tables keep the frozen per-contrast 95% intervals (one-day and seven-day) '
                 'labelled "per-contrast 95% interval", plus a family-adjusted column. Seven-day family-adjusted intervals appear '
                 'in tables only.'),
        'method_sentence_form': S['B3'],
        'fields': 'A2_POSTSCORE.json: tasks.<task>.primary[i].interval_family_one_day, interval95_one_day, interval95_seven_day'},

    # ------------------------------------------------------------ SESOI
    'sesoi': {
        'values_percent': {'news': 3.8, 'notice': 0.5},
        'sentences': pick('D1', 'D2', 'D3', 'D4', 'D5', 'D6'),
        'logic': [
            {'if': 'decision is no reliable increment and the family-adjusted one-day interval is defined', 'then': 'D1 if X_fam < S else D2'},
            {'if': 'decision is a reliable increment', 'then': 'D3 if |effect| < S else D4'},
            {'if': 'reliable deterioration or undefined interval', 'then': 'no SESOI sentence'}],
        'placement': ('After each primary reading in section 6 and in the conclusion; the task-level bound sentence H5 in the '
                      'abstract. D6 once in the methods. D5 once in the supplement next to the frozen A1 3.8% notice output.'),
        'symmetry': 'News and notices use the same sentence forms with their own level, tail and SESOI.',
        'fields': 'tasks.<task>.primary[i].sesoi.{branch, sentence, bound_family_adjusted_percent, bound_display}'},

    # ------------------------------------------------------------ robustness
    'robustness': {
        'checks_in_order': [a2.CHECK_NAME[k] for k in a2.CHECK_ORDER],
        'agreement': {
            'interval': 'reliable increment: upper < 0; reliable deterioration: lower > 0; no reliable increment: interval contains 0',
            'hln_and_hac7': 'Holm-adjusted class with the same family size equals the primary class',
            'three_seed_mean': 'same class and same sign of the mean daily difference (A1 seed rule)'},
        'labels': {'ROBUST': 'all five available and agreeing -> R1',
                   'FRAGILE': 'any disagreement -> R2 listing every dissenting check (R3 appended for unavailable ones)',
                   'NOT_FULLY_CHECKED': 'no disagreement, some unavailable -> R3',
                   'NOT_EVALUABLE': 'primary not evaluable -> H4, no robustness clause'},
        'sentences': pick('R1', 'R2', 'R3', 'R4'),
        'short_words_for_abstract': {'ROBUST': 'robust', 'FRAGILE': 'fragile ({short_list})', 'NOT_FULLY_CHECKED': 'not fully checked'},
        'short_check_names': {'one_day': 'one-day interval', 'hln': 'HLN', 'hac7': 'HAC7', 'seven_day': 'seven-day interval',
                              'three_seed': 'three-seed mean'},
        'placement': ('In the same sentence as every primary reading: abstract, section 6, section 7.2 and the conclusion. '
                      'Section 7.2: one robustness sentence per primary contrast; delete the blanket "all agree" sentence; R4 '
                      'only when every label of that family is ROBUST.'),
        'fields': 'tasks.<task>.primary[i].robustness.{label, dissent, unavailable, sentence}'},

    # ------------------------------------------------------------ attribution
    'attribution': {
        'default_label': 'an increment over the activity reference',
        'logic': [
            {'if': 'primary decision is not a reliable increment', 'then': 'no attribution clause'},
            {'if': 'representation is L_count, L14 or L_Laz', 'then': 'C1'},
            {'if': 'a content control is not evaluable', 'then': 'C3'},
            {'if': 'either control does not favour the original content (mean < 0 and raw DM p < .05)', 'then': 'C2'},
            {'if': 'both controls favour it and every available cheap-text comparator is beaten (at least one available)', 'then': 'C5'},
            {'if': 'both controls favour it, some available comparator not beaten', 'then': 'C4'}],
        'sentences': pick('C1', 'C2', 'C3', 'C4', 'C5', 'C6'),
        'comparator_names': a2.COMPARATOR_NAME,
        'control_names': a2.CONTROL_NAME,
        'short_words_for_abstract': {'C1': 'an increment over the activity reference only', 'C2': 'an increment over the activity reference only',
                                     'C3': 'an increment over the activity reference only', 'C4': 'content-specific',
                                     'C5': 'LLM-specific'},
        'banned_unless_C4_or_C5': ['content increment', 'content increments', 'content-specific', 'semantic increment'],
        'banned_unless_C5': ['LLM-specific', 'LLM increment'],
        'unmatched_share': 'C6 for both tasks in section 6 (or its table note) and the supplement, whatever the reading',
        'fields': 'tasks.<task>.attribution[i].{label, sentence}; tasks.<task>.p_content_unmatched'},

    # ------------------------------------------------------------ strong benchmark (combination)
    'strong_benchmark': {
        'benchmarks': a2.BENCHMARK_NAME,
        'sentences': pick('S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'),
        'logic': [
            {'if': 'primary reliable increment', 'then': 'S1 / S2 / S3 by the combination decision, inside H2'},
            {'if': 'primary no reliable increment', 'then': 'S4 / S5 / S6 by the combination decision, after the reading in section 6 (not in the abstract)'},
            {'if': 'primary deterioration or not evaluable', 'then': 'table only'},
            {'if': 'benchmark unavailable', 'then': 'S7'}],
        'nested_notice_check': ('Report the frozen A1 NPL - NPM reading next to the L14 combination row as its refitted counterpart '
                                '(tasks.notice.combination.nested_A1_NPL_minus_NPM).'),
        'information_set_sentence': S['H0'],
        'fields': 'tasks.<task>.combination.family.reports[i].{decision, robustness, clause_id, sentence}'},

    # ------------------------------------------------------------ headline readings
    'headline': {
        'sentences': pick('H0', 'H1', 'H2', 'H3', 'H4', 'H5'),
        'activity_names': a2.ACTIVITY,
        'rules': [
            'Report every primary contrast on its own; no vote counts ("1/2 tests", "1/3 tests").',
            'Each task is read on its own (frozen A1 per-task rule); no pooled LLM claim.',
            'H0 once in the abstract and once in the conclusion.',
            'H5 when no contrast of the task family is a reliable increment (X is the largest family-adjusted bound).'],
        'abstract_forms': {
            'task_without_increment': ('For {task_label}, no structured representation improved on the {activity} reference ({clauses}); '
                                       'improvements larger than {X}% of the reference error were excluded at the family-adjusted one-sided '
                                       '{tail}% level, {below_or_above} the {S}% smallest effect size of interest{pc_clause}.'),
            'clause': '{arm} {effect}% [{lo}, {hi}], Holm-adjusted {p}, {robust_word}',
            'task_with_increment': ('For {task_label}, {arm} improved on the {activity} reference by {abs_effect}% (family-adjusted {level}% '
                                    'interval [{lo}, {hi}]%, Holm-adjusted {p}); this reading was {robust_word}, {attribution_word}, and '
                                    '{benchmark_word}.'),
            'other_contrasts_in_family': '{arm} showed no reliable increment ({effect}% [{lo}, {hi}], Holm-adjusted {p}, {robust_word}).',
            'benchmark_words': {'S1': 'it persisted when each forecast was averaged with {benchmark}',
                                'S2': 'it was not detected when each forecast was averaged with {benchmark}',
                                'S3': 'the combination with {benchmark} was reliably worse',
                                'S7': 'the combination check was not available'},
            'pc_clause': '; {P2}',
            'task_labels': {'news': 'day-ahead news', 'notice': 'market notices'},
            'note': 'Abridged renderings of H1/H2/H5 with the robustness, attribution and benchmark clauses shortened; numbers and words must match the full forms.'}},

    # ------------------------------------------------------------ positive control
    'positive_control': {
        'sentences': pick('P1', 'P2'),
        'units': {'news': 'region-days', 'notice': 'region-hours'},
        'placement': ('P1 exactly once, in section 6, always (both tasks in one sentence or one per task). P2 in the abstract only '
                      'for a task whose primary family has no reliable increment. No other occurrence; the FILL2 rule that appended a '
                      'sentence after every no-rejection reading is replaced.'),
        'tables': ('Drop the N1 detection rates and their Clopper-Pearson intervals. Report N1 only in the supplement as agreement '
                   'with the replicated (N2) result: "The single exact daily-refit replicate agreed with the replicated result at {list} '
                   'times the minimum detectable effect{disagree_clause}."'),
        'description_fix': ('The planted column is added to the activity reference (M or M_notice) and equals the realised target '
                            '(notices: the residual target) on a random share of units; never call it a "planted content signal" or say '
                            'it was planted into content features.'),
        'fields': 'CONF/A1/positive_control/run/RESULT_POSITIVE_CONTROL.json: tier notice and N2, strength 2, detections x/R, CP interval, null arm'},

    # ------------------------------------------------------------ exposure
    'exposure_sets': {
        'sentences': pick('U1', 'U2', 'U3'),
        'rules': ['Rename every mention of the A1 100-day (news) and 50-day (notice) sets with U2.',
                  'Report the A2 strictly unexposed sets (50 news days, 7 notice days) with U3 and U1 per primary contrast, descriptive only.',
                  'The notice seven-day block interval on 7 days is not informative (single admissible block); do not show it.'],
        'fields': 'tasks.<task>.strictly_unexposed.reports[i]'},

    # ------------------------------------------------------------ label replacement
    'label_replacement': {
        'sentences': pick('L1', 'L2', 'L3'),
        'logic': 'reproduced if decision class and sign equal the primary reading (copy of the A1 seed rule); otherwise L2',
        'placement': 'Next to the robustness clause of each primary reading in section 6; abstract only if L2 occurs for a reliable increment.',
        'framing_sentence': ('The training-period and test-period news labels come from two runs of the same model alias about one day '
                             'apart; their event-type shares differ (total-variation distance 0.161) while impact-tier and statement-kind '
                             'shares are close (0.044 and 0.033), and content changed between the periods too (0.115 between 2021-2024 '
                             'and 2025 within one run), so these shares cannot separate the two causes. The test-period label-replacement '
                             'check measures how much each reading depends on one extraction run.'),
        'framing_source': 'autopilot/q1_audits/PRE2FACTS/MANUSCRIPT_SENTENCES.md items 2-4; RESULTS.json task2_label_distributions',
        'until_run': 'L3 with the reason "it runs as a separate batch after the confirmation chain" until the A2LABEL batch has results'},

    # ------------------------------------------------------------ A2BATCH readings
    'a2batch': {
        'spec': 'autopilot/q1_audits/CONF/A2/A2BATCH_SPEC.md section 7 (verbatim forms A1-A7)',
        'placement': 'Section 6 secondary analyses and the supplement; never in the abstract headline; cannot change a primary reading.',
        'pd_gap_limitation': ('The pre-dispatch bank has no run for the 31 training target days 2 October to 1 November 2022 (the '
                              'official October 2022 archive directory is empty). Under the frozen rule these inputs are missing values '
                              'with no row removed; they also leave the previous-day and previous-week inputs missing for the following '
                              'days, so 38 training target days (2,736 news rows) carry at least one missing pre-dispatch input; the first week '
                              'of October 2021 also lacks previous-week inputs because the bank starts on 1 October 2021. All 214 '
                              'confirmation days are covered.'),
        'pd_gap_source': 'autopilot/q1_audits/PDX/COVERAGE.json (missing_days, D_window)'},

    # ------------------------------------------------------------ limitations and disclosures (plain sentences)
    'limitation_sentences': {
        'notice_clock_type': ('All 725 notices dated 1 August to 30 September 2026 use the website creation date, a surrogate not '
                              'verified as the publication time, as their availability clock, whereas the training notices use the official '
                              'archive clocks; on 65 March-May 2026 notices that carry both clocks the two agree to the second. No registered '
                              'contrast separates this clock-type change.'),
        'notice_clock_source': 'autopilot/q1_audits/PRE2FACTS/MANUSCRIPT_SENTENCES.md item 5',
        'learner_information_set': S['H0'],
        'single_seed_batches': 'The new-fit secondary arms use one seed; their robustness is not fully checked by design.',
        'no_tier_l_chen': 'The impact tier is removed only from the count representation; it remains inside the serialised representation.'},

    # ------------------------------------------------------------ plain phrases for internal codes
    'code_phrases': {
        'CONDITIONAL_IMPROVEMENT': 'a reliable increment', 'CONDITIONAL_DETERIORATION': 'a reliable deterioration',
        'NO_RELIABLE_INCREMENT_DETECTED': 'no reliable increment detected', 'NOT_EVALUABLE': 'not evaluable',
        'E3_SECONDARY_JOINT_CONFIRMED': 'the earlier positive notice finding was reproduced by both registered P5MIN comparisons',
        'E3_SECONDARY_JOINT_NOT_CONFIRMED': 'the earlier positive notice finding was not reproduced by both registered P5MIN comparisons',
        'E3_SECONDARY_JOINT_NOT_EVALUABLE': 'the two registered P5MIN comparisons could not both be evaluated',
        'SEED_DIRECTION_INSTABILITY': 'the sign of at least one primary effect changed under another seed',
        'NO_OBSERVED_SEED_SIGN_REVERSAL': 'no sign change was seen across the three seeds',
        'EXTRA_SEEDS_NOT_AVAILABLE': 'the extra seeds were not run',
        'SEED_FRAGILE': 'the three-seed mean did not reproduce the reading', 'SEED_CONSISTENT': 'the three-seed mean reproduced the reading',
        'SEED_ROBUSTNESS_NOT_EVALUABLE': 'the three-seed mean was not available',
        'NOT_EVALUABLE_SHIFT_SUPPORT_GAP': 'not evaluable on 1-23 August, because no notices were saved for the shifted dates',
        'NO_VALID_PERMUTATION': 'no activity-matched donor content was available',
        'BAI_UNAVAILABLE_TRAINING_PRICE_PREREQUISITE': 'the pre-specified word-frequency arm could not be built (its training-price check cannot pass on 31 December 2024)',
        'BAI_UNAVAILABLE_EMPTY_VOCABULARY': 'the pre-specified word-frequency arm could not be built (no word passed the selection)',
        'W2_D_UNAVAILABLE_EMPTY_VOCABULARY': 'the scale-matched word-frequency arm could not be built (no word passed the selection)',
        'W2_D_UNAVAILABLE_CANDIDATE_GATE': 'the scale-matched word-frequency arm could not be built (too few candidate words)',
        'W2_D_UNAVAILABLE_TRAINING_PRICE_PREREQUISITE': 'the scale-matched word-frequency arm could not be built (training-price check)',
        'UNAVAILABLE_RESOURCE_BUDGET': 'not run within the fitting budget', 'UNAVAILABLE_MODEL_FAILURE': 'unavailable after a model failure',
        'UNAVAILABLE_E3_INPUT_GATE': 'the P5MIN inputs did not pass their completeness check',
        'NOT_EVALUABLE_WHOLE_STAGE_UNAVAILABLE': 'not run', 'NOT_RUN_BUDGET': 'not run within the fitting budget',
        'NOT_RUN_INPUT_UNAVAILABLE': 'not run because its input data were unavailable',
        'NOT_RUN_PARITY_FAILED': 'not run because the reproduction check failed',
        'PIPELINE_SENSITIVE_AT_2xMDE': 'the planted check detected twice the minimum detectable effect in at least 80% of replicates',
        'PIPELINE_SENSITIVITY_LIMITED': 'the planted check detected twice the minimum detectable effect in fewer than 80% of replicates',
        'PIPELINE_ATTENUATES': 'the learner used less than half of the planted information at every strength',
        'SIZE_INFLATED': 'the permuted null column was detected more often than the nominal level allows',
        'N1_AGREES_WITH_N2': 'the exact daily-refit replicate agreed with the replicated result',
        'CONF-A1': 'the pre-score addendum', 'CONF-A2': 'the second pre-score addendum', 'amendment2': 'the template convergence rule',
        'report_only_2025_validation': 'the report-only 2025 validation', 'pre-D': 'before the confirmation window',
        'D (as a period label only)': 'the confirmation window', 'E3': 'the P5MIN-augmented comparison'},
    'banned_strings': ['pre-registered', 'top-venue', 'pre-D', '1/2 tests', '1/3 tests', 'pooled p = 1', 'p = 1', 'planted content signal',
                       'remain pending', 'is planned', 'independent confirmation', '10^{-'],
    'other_template_fixes_for_fill3': [
        'Section 6.1: replace any "planned timestamp" with the actual T4/T5 times read from CONF/TIMESTAMPS/<label>/<label>_RESULT.json.',
        'Section 6 title: "Confirmation results".',
        'Human checks: add result slots; delete "remain pending" once the review files are scored.',
        'Section 7.2: per-contrast robustness sentences (see robustness.placement).']}


def main():
    path = A2 / 'RULES_FOR_FILL3.json'
    path.write_text(json.dumps(RULES, indent=2, ensure_ascii=False) + '\n')
    print(path, sha(path))


if __name__ == '__main__':
    main()
