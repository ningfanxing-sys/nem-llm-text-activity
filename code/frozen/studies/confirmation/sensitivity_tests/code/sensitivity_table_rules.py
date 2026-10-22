"""Write RULES_FOR_FILL3A.json and RULES_FOR_FILL3A.md from the frozen ADDENDUM_A3 forms (single source: a3_postscore).

Every sentence string is verified verbatim against the frozen ADDENDUM_A3.md by the unit tests.
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

A3 = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('a3_postscore_rules', A3 / 'code/a3_postscore.py')
a3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a3)
S = a3.SENTENCES


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def pick(*keys):
    return {k: S[k] for k in keys}


SUPERSEDES = {
    'A3H0': ['A2 H0', 'A2 rules strong_benchmark.information_set_sentence', 'A2 rules limitation_sentences.learner_information_set'],
    'A3H1': ['A2 H1'], 'A3H2': ['A2 H2'], 'A3H3': ['A2 H3'], 'A3H4': ['A2 H4'],
    'A3H4R': ['A2 a2_postscore.headline fixed reason "its registered input or completion gate failed"'],
    'A3H5': ['A2 H5'], 'A3R4': ['A2 R4'],
    'A3C1': ['A2 C1'], 'A3C2': ['A2 C2'], 'A3C3': ['A2 C3'], 'A3C7': ['A2 C6 (notices only; news keeps A2 C6)'],
    'A3S_BEYOND': ['A2 D4'], 'A3S_ABOVE': ['A2 D4'], 'A3S_BELOWPT': ['A2 D3'], 'A3S_BELOW': ['A2 D3'],
    'A3D1': ['A2 D1'], 'A3D2': ['A2 D2'], 'A3D7': ['A2 D1 final sentence (now once per task)'],
    'A3D5': ['A2 D5'], 'A3D6': ['A2 D6'], 'A3B3': ['A2 B3'], 'A3S2': ['A2 S2'],
    'A3P1': ['A2 P1 (first two sentences)'], 'A3P1T': ['A2 P1 (numeric sentence)'], 'A3P2': ['A2 P2'],
    'A3U1N': ['A2 U1 (notices only; news keeps A2 U1)'], 'A3Q5': ['A2BATCH_SPEC section 7 A3'],
    'A3AB_NULL': ['A2 rules headline.abstract_forms.task_without_increment'],
    'A3AB_CL': ['A2 rules headline.abstract_forms.clause'], 'A3AB_INC': ['A2 rules headline.abstract_forms.task_with_increment'],
    'A3AB_OTHER': ['A2 rules headline.abstract_forms.other_contrasts_in_family'],
    'A3R_BATCH': ['A2 rules limitation_sentences.single_seed_batches'],
    'notice_clock_limitation': ['A2 rules limitation_sentences.notice_clock_type'],
    'E3_SECONDARY_JOINT_CONFIRMED': ['A2 rules code_phrases.E3_SECONDARY_JOINT_CONFIRMED'],
    'E3_SECONDARY_JOINT_NOT_CONFIRMED': ['A2 rules code_phrases.E3_SECONDARY_JOINT_NOT_CONFIRMED'],
    'E3_SECONDARY_JOINT_NOT_EVALUABLE': ['A2 rules code_phrases.E3_SECONDARY_JOINT_NOT_EVALUABLE'],
    'BENCHMARK_WORDS.notice': ['A2 BENCHMARK_NAME notice "the P5MIN-augmented reference NP" in the abstract and conclusion'],
    'placement.positive_control': ['A2 rules positive_control.placement'],
    'placement.label_replacement': ['A2 rules label_replacement.placement (abstract only for L2 of a reliable increment)'],
    'placement.robustness_section7_2': ['A2 rules robustness.placement (R4 sentence)'],
    'rule.three_seed_sign': ['A2 R.2 three-seed agreement "same class and same sign" (null readings: class only)'],
    'rule.label_reproduction_sign': ['A2 L.2 "decision class and sign" (class only)']}
SUPERSEDED_BECAUSE_OF_REGISTERED = ['H0', 'H4 (and its fixed reason)', 'R4', 'C1', 'C2', 'C3', 'D3', 'B3', 'S2', 'P1',
                                    'A2BATCH A3', 'limitation_sentences.notice_clock_type', 'limitation_sentences.learner_information_set',
                                    'strong_benchmark.information_set_sentence', 'code_phrases.E3_SECONDARY_JOINT_CONFIRMED',
                                    'code_phrases.E3_SECONDARY_JOINT_NOT_CONFIRMED', 'code_phrases.E3_SECONDARY_JOINT_NOT_EVALUABLE']
KEPT_A2 = ['R1', 'R2', 'R3 (batch reason replaced by "the batch was fitted with one seed by design")', 'C4', 'C5',
           'C6 (news)', 'S1', 'S3', 'S4', 'S5', 'S6', 'S7 (used as a clause inside A3H2)', 'S8', 'U1 (news)', 'U2', 'U3',
           'L1', 'L2', 'L3', 'B1', 'B2', 'A2BATCH A1', 'A2BATCH A2', 'A2BATCH A4', 'A2BATCH A5', 'A2BATCH A6', 'A2BATCH A7',
           'display rules W1 (p values), percentages, bound display', 'code_phrases not listed in supersedes']

RULES = {
    'about': ('Reading and wording rules for FILL3a from the frozen CONF-A3 addendum. They extend RULES_FOR_FILL3.json (A2); '
              'where an A3 form supersedes an A2 form (map "supersedes"), FILL3a renders the A3 form only. Values come from '
              '<state>/a3_scored/A3_POSTSCORE.json (code/a3_postscore.py, run after a2_postscore.py) and from the frozen score '
              'outputs. Placeholders are in braces. Nothing here changes a frozen primary decision.'),
    'sources': {
        'addendum': 'autopilot/q1_audits/CONF/A3/ADDENDUM_A3.md', 'addendum_sha256': sha(A3 / 'ADDENDUM_A3.md'),
        'addendum_freeze': 'autopilot/q1_audits/CONF/A3/ADDENDUM_A3_FREEZE.json',
        'addendum_freeze_sha256': sha(A3 / 'ADDENDUM_A3_FREEZE.json'),
        'postscore_module': 'autopilot/q1_audits/CONF/A3/code/a3_postscore.py',
        'postscore_module_sha256': sha(A3 / 'code/a3_postscore.py'),
        'a2_rules': 'autopilot/q1_audits/CONF/A2/RULES_FOR_FILL3.json',
        'a2_rules_sha256': sha(A3.parent / 'A2/RULES_FOR_FILL3.json'),
        'edge_fixtures': 'autopilot/q1_audits/CONF/A3/EDGE_FIXTURES_SPEC.md and tests/edge_fixtures.json',
        'a3_output': '<state>/a3_scored/A3_POSTSCORE.json',
        'order': 'cli.py score -> a2_postscore.py -> a3_postscore.py -> FILL3a; positive control, A2BATCH and A2LABEL arrive later: rerun a3_postscore.py, then refill',
        'run_command': ('/Users/stacchining/Documents/thesis/lamp-moe-research/.venv/bin/python '
                        '/Users/stacchining/Documents/thesis/lamp-moe-research/experiments/llm_controlled_study_prep_20260925/'
                        'autopilot/q1_audits/CONF/A3/code/a3_postscore.py --state '
                        '/Users/stacchining/Documents/thesis/lamp-moe-research/experiments/llm_controlled_study_prep_20260925/'
                        'autopilot/q1_audits/CONF/CONFX2/host_state'),
        'coverage_command_pre_score': ('/Users/stacchining/Documents/thesis/lamp-moe-research/.venv/bin/python '
                                       '.../CONF/A3/code/a3_postscore.py --coverage-only --feature-root <host_state>/features '
                                       '(reads only the feature manifest, the matched mask and the panel keys)')},
    'sentences': dict(S),
    'word_lists': {'arm_words': a3.ARM_WORDS, 'S_phrase': a3.S_PHRASE, 'benchmark_words': a3.BENCHMARK_WORDS,
                   'class_words': a3.CLASS_WORDS, 'class_phrases': a3.CLASS_PHRASE, 'sensitivity_names': a3.SENSITIVITY_NAMES,
                   'batch_seed_reason': a3.BATCH_SEED_REASON, 'sesoi_class_words': a3.SESOI_CLASS_WORDS,
                   'attribution_status': a3.ATTRIBUTION_STATUS, 'cheap_pieces': a3.CHEAP_PIECES,
                   'comparison_words': {'mde_cmp': a3.MDE_CMP, 'hist_cmp': a3.HIST_CMP, 'pub_cmp': a3.PUB_CMP},
                   'task_labels': a3.TASK_LABEL, 'benchmark_abstract_words_A2': a3.BENCHMARK_ABSTRACT},
    'code_phrases': dict(a3.CODE_PHRASES, **{'E3_comparison_names': {f'{a} - {b}': v for (a, b), v in a3.E3_COMPARISON_NAMES.items()}}),
    'limitation_sentences': {'notice_clock_type': a3.NOTICE_CLOCK_LIMITATION, 'single_seed_batches': S['A3R_BATCH'],
                             'content_controls_scope': S['A3C8'], 'notice_reassignment': S['A3C7']},
    'supersedes': SUPERSEDES,
    'superseded_because_of_registered': SUPERSEDED_BECAUSE_OF_REGISTERED,
    'a2_forms_kept': KEPT_A2,
    'constants': {'sesoi_percent': a3.SESOI, 'mde_percent': a3.MDE_PERCENT,
                  'historical_notice_gains_percent': {'January-February 2026 T-N': 0.097, 'development T-N': 0.154},
                  'published_relative_changes_percent': a3.published_reductions(),
                  'published_reduction_range_percent': [1.0, 13.9], 'published_largest_increase_percent': 1.37,
                  'readmission_free_issue_days': a3.READMISSION_FREE_DAYS, 'readmission_csv_sha256': a3.READMISSION_SHA256,
                  'pd_input_coverage': {'confirmation_days_covered': 214, 'confirmation_days': 214, 'training_gap_days': 31,
                                        'training_gap': '2022-10-02..2022-11-01', 'fields_present': ['TOTALDEMAND', 'UIGF'],
                                        'source': 'autopilot/q1_audits/PDX/COVERAGE.json'},
                  'lear_2025': {'LEAR_MAE': 39.72978780479276, 'N_MAE': 50.513341390499356, 'N_minus_LEAR': 10.783553585706608,
                                'percent_of_N_MAE': 21.3, 'source': 'autopilot/q1_audits/BASE25/scores/BASE25_TEST_A2_RESULT.json'},
                  'test_2025': {'L_minus_N_AUD': 0.092779, 'L_minus_N_percent': 0.1837, 'one_sided_DM_p': 0.6104,
                                'source': 'manuscript_tex/sections/MS13_news_2025.tex line 22, MS12_CORE_TRACE.csv'}},
    'logic': {
        'headline_per_contrast': [
            {'if': 'decision NO_RELIABLE_INCREMENT_DETECTED', 'then': 'A3H1, then A3D1 or A3D2 (bound X_fam vs S); A3D7 once per task after the first'},
            {'if': 'decision CONDITIONAL_IMPROVEMENT', 'then': 'A3H2 with {zero}=A3Z when the family-adjusted interval contains zero, {attribution}=A3C1-A3C3 or A2 C4/C5, {sesoi}=A3S_* class, {benchmark}=A2 S1/S3/S7(clause) or A3S2'},
            {'if': 'decision CONDITIONAL_DETERIORATION', 'then': 'A3H3 with A3Z when its family-adjusted interval contains zero; no SESOI sentence'},
            {'if': 'decision NOT_EVALUABLE', 'then': 'A3H4 with reason A3H4R'},
            {'if': 'task primary stage incomplete (budget or failure before sealing)', 'then': 'A3H6 in section 6 and A3AB_INCOMPLETE in abstract and conclusion with reason A3INC_BUDGET or A3INC_FAIL'}],
        'qualifiers_in_headline': [
            {'if': 'label replacement gives a different decision class', 'then': 'A3QL in the section 6 headline; flag "extraction-run-dependent" in abstract and conclusion (any class)'},
            {'if': 'scenario B and positive-control size fails', 'then': 'A3PB_SIZE on every reliable increment (section 6, abstract, conclusion); A3PS_SIZEB in section 6'},
            {'if': 'scenario B and positive-control sensitivity fails', 'then': 'A3PS_POWER in section 6; flag ", precision-limited" on the null contrasts of that family in abstract and conclusion'},
            {'if': 'scenario A and sensitivity fails', 'then': 'A3PA_SENS on A3H5 and on the abstract and conclusion task sentence; A3PS_SENS in section 6'},
            {'if': 'scenario A and size fails', 'then': 'A3PA_SIZE on A3H5 and on the abstract and conclusion task sentence; A3PS_SIZE in section 6'},
            {'if': 'positive control not run or absent', 'then': 'A3PS_NOTRUN in section 6 only'},
            {'if': 'PIPELINE_ATTENUATES', 'then': 'A3PS_ATT in section 6'}],
        'sesoi_classes': {'variable': 'improvement I = -effect; interval [-hi, -lo] of the family-adjusted one-day interval',
                          'BEYOND': 'lower end of I > S', 'BELOW': 'upper end of I < S',
                          'ABOVE': 'otherwise, point estimate I >= S', 'BELOWPT': 'otherwise, point estimate I < S'},
        'scenario_A_comparisons': {'both tasks': 'A3H5 then A3M1 (task bound vs MDE)', 'notices': 'A3N1 after A3M1; A3AB_CTX in the abstract task sentence',
                                   'news': 'A3G1 after A3M1 (omitted if any of the three unadjusted bounds is undefined)'},
        'attribution': {'C1': 'L_count, L14, L_Laz: A3C1 with the cheap-text clause (new contrasts L_count-E_raw, L_count-W2_D, L14-R, L14-T, L_Laz-R, L_Laz-T)',
                        'L_chen/L_chen_notice': 'A2 C logic; A3C2/A3C3 replace C2/C3; C4/C5 kept; notices always reach A3C3 (no matched key by construction)',
                        'status_word': 'attribution_status word list in abstract and conclusion (always states LLM-specific status)',
                        'coverage_sentence': 'news: A2 C6; notices: A3C7; A3C8 once in section 6.2'},
        'robustness_layers': {
            'layer_1': 'five inferential checks (A2 R) with rule R2: agreement = equal decision class (no sign condition)',
            'layer_2': 'design sensitivities: label replacement, first-chunk encoding, 24-hour window (news), official cap re-clip (notices), first seven notice days dropped (notices), L1 and PD families (news); class under Holm with the primary family size',
            'descriptive_no_class': 'U2, U3, re-admission-free days (A3V1), matched support (A3W1/A3W0)',
            'section_7_2': 'one sentence per primary contrast with the short robustness word; A3R4 only if every primary label is robust; A3R5a or A3R5b per task; A3R6 once',
            'table_7_caption': 'A3T7'},
        'bounds': {'rule': 'one bound type: max(0, -lower) of a labelled interval; family-adjusted for primary, combination, L1, PD and label-replacement families; unadjusted for single secondary contrasts; per-contrast 95% intervals of family members as intervals only',
                   'frozen_per_contrast_reading': 'kept once, verbatim, in the supplement under the label A3B5; never compared with SESOI, history or literature',
                   'methods': 'A3B3 per task and A3B4 once'},
        'secondary_qualifiers': {'L1 or PD class differs': 'A3Q1 / A3Q2 in abstract, section 6.3 and conclusion; A3Q5 in section 6.3 when a primary increment is not reproduced',
                                 'L1 or PD state NOT_RUN_*': 'A2BATCH A7 in section 6.3, in the abstract right after A3H0, and in the conclusion',
                                 'batch result absent': 'FILL3 pending sentence in section 6.3; nothing in abstract or conclusion'},
        'abstract_order': ['problem sentence (unchanged)', 'design sentence (droppable for length)', 'A3Y1', 'A3Y2',
                           'news task sentence(s)', 'notice task sentence(s)', 'A3Q1/A3Q2 sentences', 'A3H0', 'A2BATCH A7 sentences'],
        'abstract_rules': ['words, never arm symbols (no L_count, L_chen, L14, L_Laz, NP, P5MIN, Lchen, LLaz)', 'limit 250 words: drop the design sentence first, never A3Y1, A3Y2, task sentences, qualifiers or A3H0',
                           'drop the review-state closing sentence', 'no vote counts, no pooled LLM claim'],
        'conclusion_order': ['task sentences (same as the abstract)', 'A3Q1/A3Q2', 'A3H0', 'A2BATCH A7', 'A3CO_Y', 'existing historical-evidence sentences, last'],
        'subsets': {'notice strictly unexposed': 'A3U1N (no p value)', 'news strictly unexposed': 'A2 U1',
                    're-admission-free issue days (news)': 'A3V1, supplement', 'matched support (news)': 'A3W1 or A3W0, supplement; notices A3C7'},
        'published_gains_table': ('Add three rows (this study: label-count, structured-attribute and article-activity arms against '
                                  'the numerical reference; MAE pair; unadjusted bound) and a column "relative change, computed from the '
                                  'reported pair" for every row; replace the note "percentage reductions are included only when stated in '
                                  'the source" with "relative changes are computed from the reported metric pairs".')},
    'banned_strings_added': ['registered (except a notice registration clock)', 'upper bound on sensitivity', 'robust to the registered checks',
                             'practical-effect margin', '0.5% smallest effect size of interest'],
}


def write():
    (A3 / 'RULES_FOR_FILL3A.json').write_text(json.dumps(RULES, indent=2, ensure_ascii=False) + '\n')
    md = ['# Rules for FILL3a (short guide)', '',
          'Machine-readable: `RULES_FOR_FILL3A.json`. Every sentence form is copied verbatim from the frozen `ADDENDUM_A3.md`,'
          ' Appendix A3 (a test checks this). A3 extends A2 (`../A2/RULES_FOR_FILL3.json`); an A3 form named in `supersedes`'
          ' replaces the A2 form, which FILL3a must no longer render. Numbers come from `<state>/a3_scored/A3_POSTSCORE.json`.', '',
          '## 1. Order', '', '`cli.py score` -> `a2_postscore.py` -> `a3_postscore.py --state .../CONFX2/host_state` -> FILL3a. '
          'Later inputs (positive control, A2BATCH, A2LABEL): rerun `a3_postscore.py`, then refill. Before scoring, the '
          'orchestrator may run `a3_postscore.py --coverage-only --feature-root <host_state>/features` (matched-mask counts only) '
          'to write the news reassignment coverage into PREFILL; notices have no matched key by construction (A3C7).', '',
          '## 2. Headline per primary contrast (section 6)', '',
          '| Decision | Form | Inside the sentence |', '|---|---|---|',
          '| no reliable increment | A3H1, then A3D1/A3D2 | robustness; qualifiers (extraction-run-dependent) |',
          '| reliable increment | A3H2 | A3Z if the family-adjusted interval contains zero; robustness; attribution with LLM status (A3C1-A3C3, A2 C4/C5); SESOI class (A3S_*); benchmark (A2 S1/S3, S7 as clause, A3S2); qualifiers (A3QL, A3PB_SIZE) |',
          '| reliable deterioration | A3H3 | A3Z; robustness; qualifiers |', '| not evaluable | A3H4 with A3H4R | - |',
          '| task incomplete | A3H6 (section 6), A3AB_INCOMPLETE (abstract, conclusion) | reason A3INC_BUDGET or A3INC_FAIL |', '',
          'Per task after the readings: A3D7 once (after the first A3D1/A3D2), coverage sentence (news A2 C6; notices A3C7), A3H5 with'
          ' positive-control clauses in scenario A, A3M1, then A3N1 (notices) or A3G1 (news), then the positive-control sentences'
          ' (A3P1T and A3PS_*), then A3Q1/A3Q2/A3Q5/A7. A3P1 and A3C8 appear once in section 6.2.', '',
          '## 3. Positive control (table K1 of the addendum)', '',
          'Pass = frozen PIPELINE_SENSITIVE_AT_2xMDE (rate >= 0.80 and CP lower >= 0.50) and not SIZE_INFLATED (null CP lower <= 0.05/(2m)); A3 re-derives both from the summary and refuses a mismatch. Never "upper bound"; say "detection rate under this planting scheme" and give the median realised change and uptake.', '',
          '## 4. Robustness in two layers', '',
          '- Layer 1 (five inferential checks): A2 R1-R3; agreement = same decision class (no sign condition for null readings).',
          '- Layer 2 (design sensitivities with a decision rule): A3R5a/A3R5b per task; descriptive subsets carry no class (A3R6).',
          '- A3R4 only if all labels of the family are robust; "robust to the registered checks" is withdrawn; Table 7 caption A3T7.', '',
          '## 5. Bounds and comparison values', '',
          '- One bound type: family-adjusted for family members, unadjusted for single secondary contrasts (A3B4); the frozen per-contrast reading appears once in the supplement under A3B5.',
          '- News: "the 3.8% smallest effect size of interest". Notices: "the 0.5% historical-effect reference" (window-C tolerance; set after development results; not an economic threshold; A3D6).',
          '- Scenario A: A3M1 (MDE 3.11% / 0.124%), A3N1 (notices: 0.097% and 0.154%), A3G1 (news: unadjusted L_count-N, L_chen-N, M-N bounds beside the published-gains table, with computed relative changes).',
          '- Scenario B: interval class against S (A3S_BEYOND, A3S_ABOVE, A3S_BELOWPT, A3S_BELOW) and the AUD/MWh magnitude.', '',
          '## 6. Abstract and conclusion', '',
          '- Abstract: problem and design sentences, A3Y1, A3Y2, task sentences (A3AB_NULL or A3AB_INC + A3AB_OTHER*), A3Q1/A3Q2, A3H0, A7. Words only; 250 words; drop only the design sentence; no review-state sentence.',
          '- Conclusion: the task sentences first, then A3Q1/A3Q2, A3H0, A7, A3CO_Y, then the historical evidence.', '',
          '## 7. Terminology', '', '"pre-specified" replaces "registered" in every A3 form. Superseded because of this word: ' +
          ', '.join(SUPERSEDED_BECAUSE_OF_REGISTERED) + '.', '',
          '## 8. Edge fixtures', '', '`EDGE_FIXTURES_SPEC.md` lists twelve synthetic cases with the exact expected abstract core,'
          ' section 6 sentences, section 7.2 sentences and conclusion core; FILL3a must reproduce them.', '']
    (A3 / 'RULES_FOR_FILL3A.md').write_text('\n'.join(md))


if __name__ == '__main__':
    write()
    print(sha(A3 / 'RULES_FOR_FILL3A.json'))
