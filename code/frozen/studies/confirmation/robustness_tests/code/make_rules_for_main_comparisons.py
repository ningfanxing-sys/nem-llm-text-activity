"""Write RULES_FOR_FILL3B.json and RULES_FOR_FILL3B.md from the frozen A4 forms (copied from the module, which a test
checks against the frozen addendum and amendments).

    python make_rules_for_fill3b.py
"""
import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
A4_ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('a4_postscore_rules', A4_ROOT / 'code/a4_postscore.py')
a4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a4)
A3 = a4.A3
PROJ_REL = 'autopilot/q1_audits/CONF/A4/'

SUPERSEDES_AMENDMENTS = {
    'A4AB_DS1': ['A4AB_DS (amendment 1)'],
    'A4AB_PDS': ['A4AB_P', 'A4AB_DS1', 'A4AB_H0C at levels L2-L6 (amendment 2, G8)', 'FILL3a abstract.s1', 'FILL3a abstract.s2'],
    'A4AB_Y3': ['A4AB_Y2 at L6 (amendment 1)'], 'A4AB_AC': ['A4AB_A at L6 (amendment 1)'],
    'A4AB_HNC': ['A4AB_HN at L6 (amendment 1)'], 'A4AB_CTXC': ['A3AB_CTX at L6 when the bound lies between the gains (amendment 1)'],
    'A4LT_OKC2': ['A4LT_OKC at L6 (amendment 1)'], 'A4PA_SENSC': ['A4PA_SENS at L6 (amendment 1)'],
    'A4AB_CGS': ['A4AB_CG at L6 (amendment 1)'], 'A4NR_BUDGETC': ['A4NR_BUDGET at L6'], 'A4NR_PARITYC': ['A4NR_PARITY at L6'],
    'A4DEVC': ['A4DEV at L6'], 'IC_BEYOND_C': ['IC_BEYOND at L6'], 'IC_ABOVE_C': ['IC_ABOVE at L6'], 'IC_BELOWPT_C': ['IC_BELOWPT at L6'],
    'IC_BELOW_C': ['IC_BELOW at L6'],
    'CT_NULL2': ['CT_NULL (amendment 2, G1)'], 'A4H1b': ['A4H1', 'A3H1', 'A2 H1'],
    'A4MNR_IMPb': ['A4MNR_IMP'], 'A4MNR_NULLb': ['A4MNR_NULL'], 'A4MNR_DETb': ['A4MNR_DET'],
    'A4PB_DIAG': ['A4PB_PASS'], 'A4PB_NEG': ['A4PB_SIZE', 'A3PB_SIZE'], 'A4PA_NEG': ['A4PA_SIZE', 'A3PA_SIZE'],
    'A4PA_NEGC': ['A4PA_SIZEC'], 'A4PS_NEG': ['A3PS_SIZE'], 'A4PS_NEGB': ['A3PS_SIZEB'],
    'A4PX_RUN2': ['A4PX_RUN'], 'A4PX_NOT2': ['A4PX_NOT'], 'A4C0b': ['A4C0', 'A2 C6 (news pre-score coverage sentence)'],
    'A4CHS2': ['A4CHS', 'A3CH', 'A3CH0', 'A2 C5 comparator wording'], 'A4D6b': ['A4D6', 'A3D6', 'A2 D6'],
    'CB_S1b': ['CB_S1'], 'CB_S2b': ['CB_S2'], 'CB_S3b': ['CB_S3'], 'CB_NEUTRALb': ['CB_NEUTRAL'],
    'S_PHRASE.news': ['A3 S_PHRASE news "the 3.8% smallest effect size of interest" (amendment 2, G8)'],
    'A4NTL': ['A3 TASK_LABEL notice in the abstract and conclusion'],
}

LOGIC = {
    'order': 'cli.py score -> a2_postscore.py -> a3_postscore.py -> a4_postscore.py --state <host_state> -> FILL3b; later inputs (positive control, PCX, A2BATCH, A2LABEL): rerun a3_postscore.py and a4_postscore.py, then refill',
    'result_states': 'Every class, qualifier and number rendered by FILL3b comes from A4_POSTSCORE.json: result_states, tasks.<task>.section6, abstract.text, conclusion_core, methods_sentences, table_cells, stage_table, execution_sentence. No class word, qualifier or bound is recomputed in FILL3b.',
    'abstract': 'Render abstract.text verbatim (LaTeX conversion only); the level and both word counts are in abstract.level/abstract.counts. L7 = overflow recorded with all qualifiers kept; validate_MS12 abstract-length assertion is then the only permitted validation failure and must be reported to the author. No pointer, no symbol, no "Section".',
    'abstract_order': 'A4AB_PDS; A4AB_Y0/Y1/Y2/Y3 with the 2026 LEAR tail; news task sentence; notice task sentence (label "market notices (creation-date surrogate clocks)"); A4AB_Q1/Q2 (or compact) for each news representation whose absolute-error or pre-dispatch class differs; A3H0 at L0-L1 only; A4NR/A4DEV (or compact).',
    'qualifier_retention_order': ['robustness (inferentially robust [+ design dissent] | fragile: checks disagreed, three-seed mean class [numbers at L0-L2] | not fully checked: checks unavailable)',
                                  'extraction-run-dependent: class with re-extracted labels',
                                  'reliability may be overstated (B increments, negative-control failure) | precision-limited (B nulls, sensitivity failure)',
                                  'attribution (robust increments only): an increment over {activity} only',
                                  'interval class (robust increments only), ", possibly too narrow" on negative-control failure',
                                  'combination: persisted/not detected/reliably worse when each forecast was averaged equally with {bench}, combination {robust word}; fragile increments: neutral reading'],
    'ladder': {'L0': 'A4AB_Y0, A3H0, full clauses (intervals, AUD/MWh, three-seed numbers, passing planted-signal clause), full batch sentences',
               'L1': 'A4AB_Y1', 'L2': 'A3H0 dropped (A4AB_PDS carries the information set)', 'L3': 'A4AB_Y2; no AUD/MWh, no three-seed numbers, no passing planted-signal clause',
               'L4': 'no intervals for null clauses and for activity against the numerical reference',
               'L5': 'identical null clauses merged (A4AB_CG); task-level qualifiers once (A4AB_TQ); compact batch sentences A4AB_Q1C/Q2C',
               'L6': 'no intervals for increment and deterioration clauses; amendment-1 compact fixed forms (A4AB_Y3, A4AB_AC, A4AB_HNC, A4AB_CTXC, A4LT_OKC2, A4PA_SENSC, A4PA_NEGC, A4AB_CGS with short arm words, compact batch reasons, IC_*_C)',
               'L7': 'L6 text unchanged; abstract_over_limit true'},
    'section6_order_per_task': 'notices: A4CLK first; then per primary contrast in family order A4H1b/A4H2/A4H2F/A4H3/A3H4 (+ A3D1/A4D1P/A3D2 with the envelope bound after each null, A3D7 once; A4CS and A4CHS2 after each increment); news A3W0 (matched support) or notices A3C7; A4MN; scenario A: A3H5, A4MNR_*b, news A4N2 and A4G1, notices A3M1 and A3N1; news A4LEAR; planted-signal sentences A4P1T, A4PX_*, A3PS_SENS/A4PS_NEG (A) or A3PS_POWER/A4PS_NEGB/A4PB_DIAG (B), A3PS_ATT; news A4P1N and A4P0. Section 6.3 keeps A3Q1/A3Q2/A3Q5 and the batch tables; the secondary readings of increments are not repeated there.',
    'gating': 'Attribution (A4C1), interval class and the persistence wording only for inferentially robust increments; fragile or not fully checked increments use A4H2F with A4TS, the fixed not-assigned phrase, A4SN and A4FT.',
    'attribution': 'Content-specific and LLM-specific levels are unreachable (coverage: news 3 of 214 days; notices none by construction). The 28-day shift comparison and the cheap-text reading (required set; missing comparator = undetermined) are secondary readings beside increments, never in the abstract.',
    'bounds': 'Every exclusion bound and interval class uses the envelope of the one-day and seven-day family-adjusted intervals (U = max{0, -l1, -l7}); displayed headline interval stays the one-day family-adjusted one; A4ENV_X when the seven-day interval is undefined; A4MC when the Monte Carlo order-statistic range of U straddles the comparison value.',
    'pcontent_cells': 'Notice P_content rows render table_cells.pcontent.notice; news P_content rows render table_cells.pcontent.news; no number or interval for these rows in any table or figure.',
    'descriptive_subsets': 'Class columns of exposure, re-admission, matched-support and seven-day notice subsets render "not applicable (descriptive subset)"; never "favourable", "unfavourable" or "reliable".',
    'stage_table': '16 rows in this order: CONF stages ' + ', '.join(a4.CONF_STAGES) + '; A2B-1; A2B-2; A2LABEL; PC; PCX. Categories: ' + '; '.join(a4.STAGE_CATEGORIES) + '. The section 6.1 count sentence is execution_sentence (A4ST_EXEC).',
    'caps': 'Conclusion ends with the A4CAP_* sentences of conclusion_core; the discussion may not claim value for a strong forecaster when A4CAP_LEAR applies, value over cheap text when A4CAP_CHEAP applies, objective-independence when A4CAP_L1 applies, or operator-information-independence when A4CAP_PD applies; never causal effects, real-time trading gains or cost comparisons.',
    'human_review': 'Statement-level review rates: descriptive k/n only, with A4HR; article-level rates keep Wilson intervals; second-annotator kappa with per-field contingency tables from pair_trace, n, po, pe and both prevalences; no kappa interval.',
    'clipping': 'Publish the frozen scored/<task>__CLIPPING.csv files unchanged as machine-readable supplementary files with SHA-256 values and one supplement table per task listing every arm, seed and variant.',
    'consistency': 'Run a4_postscore.run with strict=True (default): any K4 violation raises A4ConsistencyError and FILL3b must refuse.',
}


def main():
    sentences = dict(a4.SENTENCES)
    supersedes = {**{k: v for k, v in a4.SUPERSEDES.items()}, **SUPERSEDES_AMENDMENTS}
    fixtures = json.loads((A4_ROOT / 'tests/edge_fixtures_a4.json').read_text())
    rules = {
        'about': 'Reading and wording rules for FILL3b from the frozen CONF-A4 addendum and its amendments 1 and 2. They extend RULES_FOR_FILL3A.json (A3) and RULES_FOR_FILL3.json (A2); a form named in "supersedes" replaces the listed forms, which FILL3b must no longer render. Values come from <state>/a4_scored/A4_POSTSCORE.json. Nothing here changes a frozen primary decision.',
        'sources': {
            'addendum': PROJ_REL + 'ADDENDUM_A4.md', 'addendum_sha256': a4.sha256(A4_ROOT / 'ADDENDUM_A4.md'),
            'addendum_freeze_sha256': a4.sha256(A4_ROOT / 'ADDENDUM_A4_FREEZE.json'),
            'amendment_1': PROJ_REL + 'ADDENDUM_A4_AMENDMENT_1.md', 'amendment_1_freeze_sha256': a4.sha256(A4_ROOT / 'ADDENDUM_A4_AMENDMENT_1_FREEZE.json'),
            'amendment_2': PROJ_REL + 'ADDENDUM_A4_AMENDMENT_2.md', 'amendment_2_freeze_sha256': a4.sha256(A4_ROOT / 'ADDENDUM_A4_AMENDMENT_2_FREEZE.json'),
            'postscore_module': PROJ_REL + 'code/a4_postscore.py', 'a3_rules': 'autopilot/q1_audits/CONF/A3/RULES_FOR_FILL3A.json',
            'coverage_file': 'autopilot/q1_audits/CONF/A3/results/NEWS_MATCHED_COVERAGE.json', 'coverage_sha256': a4.COVERAGE_SHA256,
            'edge_fixtures': PROJ_REL + 'EDGE_FIXTURES_SPEC_A4.md and tests/edge_fixtures_a4.json',
            'fixed_text': PROJ_REL + 'MS_TEXT_FOR_FILL3B.md',
            'run_command': '/Users/stacchining/Documents/thesis/lamp-moe-research/.venv/bin/python /Users/stacchining/Documents/thesis/lamp-moe-research/experiments/llm_controlled_study_prep_20260925/autopilot/q1_audits/CONF/A4/code/a4_postscore.py --state /Users/stacchining/Documents/thesis/lamp-moe-research/experiments/llm_controlled_study_prep_20260925/autopilot/q1_audits/CONF/CONFX2/host_state'},
        'sentences': sentences,
        'word_lists': {'check_short': a4.CHECK_SHORT, 'benchmark_words_abstract': a4.BENCH_ABS, 'single_secondary_classes': a4.CS_WORDS,
                       'primary_like_classes': a4.TS_WORDS, 'combination_robustness': a4.COMBO_ROBUST, 'mde_cmp': a4.MDE_CMP,
                       'hist_cmp': a4.HIST_CMP, 'lower_higher': a4.LOWER_HIGHER, 'n1_words': a4.N1_WORDS, 'short_arm_L6': a4.SHORT_ARM,
                       'S_phrase': a4.S_PHRASE, 'task_label_abstract': a4.TASK_LABEL_ABS, 'stage_names_new': a4.STAGE_NAMES_NEW,
                       'stage_categories': a4.STAGE_CATEGORIES},
        'supersedes': supersedes,
        'supersedes_amendments': SUPERSEDES_AMENDMENTS,
        'logic': LOGIC,
        'constants': {'word_limit_validator': a4.WORD_LIMIT, 'n_stages': a4.N_STAGES, 'conf_stages': a4.CONF_STAGES,
                      'coverage_news': {'matched_keys': 216, 'total_keys': 15408, 'days': 3, 'n_days': 214},
                      'historical_news_magnitudes_percent': list(a4.HIST_NEWS), 'power_at_0_32_percent': 2.7,
                      'pc_null_extension': {'replicates_total': 200, 'added': 160, 'news_extra_hours_two_workers': 1.07,
                                            'notice_extra_hours': 1.42, 'size_flag_threshold_detections': {'news': 7, 'notice': 6},
                                            'flag_probability_at_true_rate_5_percent': {'R0_40': 0.323, 'news_R0_200': 0.876, 'notice_R0_200': 0.938}},
                      'pre2facts_307_vs_286': {'admitted': 307, 'labels_2026_run': 258, 'labels_training_run': 49, 'training_only_readmitted': 40,
                                               'february_both_runs': 9, 'extracted_2026': 286, 'never_admitted': 19}},
        'banned_strings_added': list(a4.BANNED_A4),
        'consistency_assertions': ['K4.1 impossible states (field-gate batch state; evaluable P_content slot; class/mean or class/Holm disagreement; coverage file vs matched support)',
                                   'K4.2 class versus effect sign for every row showing a class',
                                   'K4.3 Holm clause exactly where the family-adjusted interval of a rejection contains zero',
                                   'K4.4 stage-table conservation (16 rows; categories sum; every CONF stage recorded)',
                                   'K4.5 abstract: every required qualifier present (abstract_required); no pointer',
                                   'K4.6 banned rendered strings'],
        'fixtures': {k: {'scenario': v['scenario'], 'abstract_level': v['abstract_level'],
                         'validator_words_final': v['abstract_counts'][-1]['validator_words']} for k, v in fixtures.items()},
    }
    (A4_ROOT / 'RULES_FOR_FILL3B.json').write_text(json.dumps(rules, indent=1, ensure_ascii=False) + '\n')
    lv = '\n'.join(f"| {k} | {v['scenario']} | {v['abstract_level']} | {v['validator_words_final']} |" for k, v in rules['fixtures'].items())
    md = f"""# Rules for FILL3b (short guide)

Machine-readable: `RULES_FOR_FILL3B.json`. Every sentence form is copied verbatim from the frozen `ADDENDUM_A4.md` (Appendix A4) and its frozen amendments 1 and 2 (a test checks this). A4 extends A3 (`../A3/RULES_FOR_FILL3A.json`) and A2; a form listed in `supersedes` replaces the named forms, which FILL3b must no longer render. Numbers, classes and qualifiers come only from `<state>/a4_scored/A4_POSTSCORE.json`.

## 1. Order
`cli.py score` -> `a2_postscore.py` -> `a3_postscore.py` -> `a4_postscore.py --state .../CONFX2/host_state` -> FILL3b. Later inputs (positive control, PCX, A2BATCH, A2LABEL): rerun A3 and A4, then refill. `a4_postscore.run` is strict by default: any K4 violation raises `A4ConsistencyError`; FILL3b refuses.

## 2. One result-state record
FILL3b reads `result_states`, `tasks.<task>.section6`, `abstract`, `conclusion_core`, `methods_sentences`, `table_cells`, `stage_table` and `execution_sentence`. It recomputes no class word, qualifier or bound. Descriptive subsets render "not applicable (descriptive subset)" in class columns. P_content rows render only `table_cells.pcontent` (notices: "not evaluable: no matched key by construction"; news: "not evaluable: matched keys on 3 of 214 days, fewer than the seven required"), with no interval in Figure 2.

## 3. Abstract
`abstract.text` verbatim (LaTeX conversion only). Order: A4AB_PDS (scope and design); 2025 and 2026 LEAR sentence; news task; notice task (label names the creation-date surrogate clock); differing absolute-error or pre-dispatch classes with direction, magnitude and interval; A3H0 at L0-L1; batch not-run or deviation sentences. Qualifier order inside each clause: robustness (with three-seed class), extraction-run-dependent, reliability/precision, attribution, interval class, combination. No pointer, no symbol. Ladder L0-L6 shortens fixed text and numbers only; L7 renders L6 and records the overflow (only validate_MS12's abstract-length assertion may fail, and the author is told).

## 4. Section 6 and conclusion
Sign convention everywhere: "changed the error of the ... reference by -x% (... interval [l, u]%)". Null: "no reliable increment detected". Fragile or not fully checked increments: A4H2F (primary-seed increment, three-seed estimate, family-adjusted interval and class, "attribution and comparison-value classes not assigned", neutral combination reading, A4FT). Robust increments: A4H2 with A4C1, envelope interval class and combination wording with its robustness word. Exclusion bounds use U = max{{0, -l1, -l7}} (one-day and seven-day family-adjusted lower ends), with A4ENV_X and A4MC clauses when they apply. Scenario A adds A4MN and A4MNR_*b per task, A4N2 and A4G1 (news), A3M1 and A3N1 (notices); A4LEAR always for news. The planted-signal check is a pipeline signal-use and negative-control diagnostic (A4P0); negative-control failure keeps the A3 consequences with A4 wording. The conclusion is `conclusion_core` (task sentences at L0, batch sentences, shift and cheap-text readings, A3H0, batch sentences, A4CO_Y, caps), then the existing historical sentences.

## 5. Batch, stage table, caps
L1/PD not run only with "it did not fit within the fixed 24-hour batch fitting budget" or "the pre-specified reproduction check failed"; an execution failure is A4DEV (deviation); "its input data were unavailable" is banned and its field-gate state stops A4. The 16-row stage table and `execution_sentence` replace FILL3a's "{{done}} of {{total}}". Caps (A4CAP_*) bound the discussion.

## 6. Fixed text
`MS_TEXT_FOR_FILL3B.md`: the S7.6 fourth-addendum subsection, methods sentences, and the exact location and replacement of every fixed-text sync item (seed rule, S5.3, notice comparison value, window C, section 6.1 pointers, M_notice cumulative counts, audit-archive A7 supersession table, literature reference value, 307 versus 286, kappa tables, human-review statement intervals, clipping files).

## 7. Edge fixtures and abstract levels (validator words at the chosen level)

| Fixture | Scenario | Level | Words |
|---|---|---|---|
{lv}

`EDGE_FIXTURES_SPEC_A4.md` gives every expected abstract, section 6 list and conclusion; FILL3b must reproduce them exactly.
"""
    (A4_ROOT / 'RULES_FOR_FILL3B.md').write_text(md)
    print(json.dumps({'sentences': len(sentences), 'supersedes': len(supersedes)}))


if __name__ == '__main__':
    main()
