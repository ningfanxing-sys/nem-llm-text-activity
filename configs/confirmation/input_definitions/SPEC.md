# Feature and scoring inputs (execution specification 3)

This specification defines notice parsing, feature generation and input bindings.
`SPEC_FREEZE.json` binds its content. Related implementation details:
`paper_plan/task_specs/TASK_SPEC_5_A1_implementation.md`. Input decisions: `confirmation/A1/DECISIONS_A1_source.md`.

Feature generation and tests use a separate code tree. Input records identify the
corresponding files in `execution/host_state/`; the checks do not read scoring outcomes.

## 0. Feature-generation diagnostics

- Attempt 3 of `cli.py features` (quantity_parsing code) started 2026-10-02 02:40 AEST and stopped at 03:22 AEST with
  `ValueError: Resume panel identity drift` (`features_adapter.py` line 511 in `_write_bundles`, called for the
  notice source at line 676). The CLI wrote `host_state/FAILED_features_attempt_2026-10-01T17-22-08.674747+00-00.json`
  (not opened). Records: saved computation metadata and `execution/host_features_stdout_retry3_20261002.log` (traceback lines only).
- File names now in `host_state/features/`: 13 news bundles (extras + feature order), the news panel copy, news
  shared block, news coverage and P_content mask, `W_Bai_selection.json`, `DISK_PLAN.json`,
  `embedding_cache/`, and the notice files of the interrupted pre-quantity_parsing attempt: `notice_joint.parquet`,
  `notice__shared_numeric.npy`, 14 `notice__*__*.extras.npy`, `notice_coverage.jsonl`, plus
  `NOTICE_DERIVED_DATE_SIDECARS.json` (rewritten at the start of every notice pass). No notice feature order,
  no notice P_content mask, no `manifest.json`, no `COMPLETE_features.json`. No `news__W_Bai__main` bundle
  exists, so the frozen W_Bai vocabulary was empty in that build.
- Code fact: `_write_bundles` copies the panel frame (`reset_index`) before the row generator starts, and the
  notice panel frame is built only from the frozen panels and the P5MIN block. The panel copy therefore cannot
  contain notice_extraction-derived (MW) fields; which column made the copies unequal cannot be established without opening
  host_state files, which this task may not do. The restart procedure below does not depend on that cause.

## 1. W2_D, the scale-matched Bai arm (decision 4)

W2_D = M + the frozen Bai count projection (`features.bai_counts`) over the frozen 72-hour saved-version
support, with a vocabulary selected once on training data at the features step and saved immutably as
`features/W2_D_selection.json` (reused on resume, like `W_Bai_selection.json`). Rule, in order:

1. Training issues: 00:00 AEST of every day 2021-10-01..2024-12-31 (1,188 issues). Corpus: the union of unique
   articles admitted at those issues by the frozen `features.news_support` (72 h), all extraction states, title
   and body text as loaded by the frozen `load_news_articles`. This is the frozen W_Bai corpus.
2. Tokens: frozen `features.bai_tokens` with the hash-checked word_features stopword file; title and body separately
   (WattClarity has no description field).
3. Candidates (W2 rule, NEWSSEC `w2_selection.py`; sizes from Bai et al., IEEE TPWRS 39 (2024) p. 6224:
   456 title and 550 body words): rank each field's eligible tokens by descending corpus count, ties by
   ascending token string; take exactly 456 (title) and 550 (body). Fewer distinct eligible tokens in a field
   gives `W2_D_UNAVAILABLE_CANDIDATE_GATE`; the size is never lowered.
4. Training prices: target days 2021-10-01..2024-12-30 (1,187 days). 2024-12-31 is excluded because its hour-23
   label becomes available at 2025-01-01 00:05 AEST, after the frozen preprocessing cutoff (labels available
   before 2025-01-01 00:00 AEST = 2024-12-31T14:00Z). Each day needs the frozen W_Bai price gate: 72 rows with
   `label_available` < 2024-12-31T14:00Z, regions exactly {NSW1, QLD1, TAS1}, finite `y`, no duplicate
   (day, region, horizon). Daily price = mean over the three regions of each region's mean label (frozen W_Bai
   construction). Any failure gives `W2_D_UNAVAILABLE_TRAINING_PRICE_PREREQUISITE`; no day is dropped.
5. Word series: for each candidate and each of the 1,187 days t, the sum of the word's field counts over the
   frozen 72 h support at issue t (frozen W_Bai construction).
6. Screen: frozen `_stationary` (ADF with constant, AIC lag, difference once if p >= .05) on price and word
   series; align at the final common length; frozen `_granger` with a specified lag of 30 in both directions (the W2
   lag rule; Bai et al. p. 6225 report that 30 lags had the lowest AIC among 1/7/30/90); keep a word iff
   forward p < .05 <= reverse p (Bai et al. p. 6224). An undefined test keeps no word.
7. Columns: title words then body words, each in lexicographic order (frozen convention).
8. No surviving word gives `W2_D_UNAVAILABLE_EMPTY_VOCABULARY`; no replacement rule.

The selection file records rule constants, candidate audit (count, rank, ADF state, both p values, selected),
corpus size and ID hash, price-day span and float64 price hash, and the price ADF state. Feature generator:
`('W2_D','main') = {**M_meta, **bai_counts(support, W2_D vocabulary)}` at every news origin and region, only
when the vocabulary is non-empty; otherwise the manifest carries an explicit W2_D unavailable entry. W2_D is
specified outside `NEWS_ARMS` (the frozen shared_storage proof enumerates `NEWS_ARMS` without a W2_D vocabulary).
W_Bai is unchanged and stays reported unavailable with both A1 reasons.

## 2. NPM (decision 7)

`('NPM','main') = {**P5MIN operator block, **M_notice meta}` inside the E3 branch of `notice_feature_rows`
(appended after NPP), specified width 8 + 3, added to `NOTICE_ARMS`; unavailable with
`UNAVAILABLE_E3_INPUT_GATE` exactly when NP/NPL/NPP are. One pooled fit (seed 20260919).

## 3. Specified plan and budget (decision 4, 7; COMPUTE_PLAN unchanged)

`execution_adapter.specified_plan()` wraps the frozen `scheduler.plan()`; every execution user of the plan
(counted pilots, fit bank, LEAR and subsequent stages, stage-disposition writer, seal) uses it. Changes only:
- `report_only_2025_validation`: + `FitTask('news','2025-01-01','W2_D',20260919,'2025_fixed_validation')`
  (STUDY_DESIGN section 3: one end-2024 fit per base news configuration; A1 paper section (f) cost).
- `secondary_notice`: + NPM (8 -> 9 serial notice fits).
- `secondary_news`: `news_tasks(NEWS_SECONDARY + ('W2_D',))` (1,070 -> 1,284 fits; per origin the frozen five
  then W2_D). Removing the W2_D/NPM tasks must give the frozen plan exactly.
Stage names, order, mandatory flags, primary stages, seeds, learner parameters, the 24-hour budget, ledger,
whole-stage admission and drop order are unchanged. W2_D and NPM fits are inside the same 24-hour rule.
Accounting (specified maximum): 4,311 -> 4,527 LightGBM fits (news 4,289 -> 4,504; notices 22 -> 23).
Batches: per origin ceil(r/4) over runnable tasks (frozen `projected_stage_seconds` after removing
unavailable configurations). The specified count stays 1,501; the realized secondary-news count rises by one
batch per origin when exactly four frozen secondary arms are runnable (for example W_Bai unavailable,
P_content matched). This is reported, not changed.
Fit entrypoints (`counted_pilots`, `run_fits`, `run_lear_and_remaining`) refuse a feature manifest without
W2_D and NPM dispositions; `build_all_features` refuses to return such a manifest on resume.

## 4. Scoring additions (decisions 2, 3, 5, 6, 9, 10)

Implemented in a candidate module `execution/additional_scoring.py`, called from the frozen `score` entrypoint after the frozen
computations; results go to `scored/*__A1_*` files and `SCORE_REPORT.json['A1']`, and a confirmation-A1 section of
`REPORT.md`. Frozen primary computations, families, Holm, intervals and sentences are unchanged.

1. Candidate secondary contrasts, appended after the frozen list: news W2_D-N, W2_D-M, L_chen-W2_D, W2_D-LEAR;
   notices NPM-N, NPL-NPM. Class sentences: W2_D-M "This secondary contrast estimates the increment of
   scale-matched Bai word frequencies beyond article volume."; NPL-NPM "This secondary E3 contrast estimates the
   increment of the L14 notice-content columns beyond notice activity, given the P5MIN block; it does not
   identify a mechanism."; the others use the frozen default/LEAR classes.
2. Shift support (decision 5): every notice secondary contrast with an arm built from 28-day-shifted notice
   inputs (M_shift_notice, P_shift, NPP) is evaluated on target days 2026-08-24..2026-09-30 (38 days) with the
   frozen secondary inference; 2026-08-01..2026-08-23 is recorded as `NOT_EVALUABLE_SHIFT_SUPPORT_GAP`. No refit.
   The frozen E3 joint rule then reads NPL-NP on 61 days and NPL-NPP on 38 days.
3. SEED_FRAGILE (decision 3): per primary contrast, `SEED_FRAGILE` if the seed-20260919 decision class differs
   from the three-seed-mean decision class or the signs of the two mean differences differ;
   `SEED_CONSISTENT` otherwise; `SEED_ROBUSTNESS_NOT_EVALUABLE` without the three-seed mean. Report the three
   single-seed effects and their SD (ddof 1) in % of the reference MAE. The frozen seed flag is kept.
4. HLN (decision 9): same statistic, two-sided p from Student t with n-1 df, Holm per family with the same m;
   a different HLN decision appends the frozen disagreement sentence naming "the HLN t(n-1) Holm sensitivity".
   Raw HLN p is also recorded for every computed secondary contrast.
5. Official cap (decision 6): `official_market_price_cap(target)` by financial year (AEST, frozen input_checks
   convention): FY2023-24 16,600; FY2024-25 17,500; FY2025-26 20,300; FY2026-27 23,200; other years refused.
   Notice sensitivity: sealed `raw_prediction` of each seed-20260919 notice arm re-clipped to
   [-1,000, cap] and cast to float32 like the frozen worker; rescored with the frozen primary inference and the
   E3 contrasts NPL-NP, NPL-NPP, NP-N, NPP-NP, NPL-NPM (shift rule applies), plus the E3 joint reading under
   re-clip. Descriptive counts of changed keys. News: descriptive counts of raw predictions above the official
   cap by date. Window C (20,300) has no sealed raw predictions in confirmation or notice_fitting (notice_fitting stores clipped values only);
   that part is reported as not computable from sealed raw predictions.
6. Exposure-excluded (decision 10): the primary contrasts are recomputed descriptively with the frozen
   secondary inference (gapped-subset rules) on the days with no recorded analysis in DATA_EXPOSURE_LOG:
   news 100 days = 2026-05-19..06-30, 07-25..08-31, 09-12..09-30; notices 50 days = 2026-08-01..08-31,
   09-12..09-30. No refit.
7. SESOI 3.8% (decision 2) sentences, appended after the frozen primary sentence (A1 section (b)):
   no rejection with X < 3.8, no rejection with X >= 3.8, favourable rejection with |effect| < 3.8 or >= 3.8;
   none for deterioration or an undefined interval; the seven-day bound version is labelled secondary.
8. Per-task statement rule (decision 9): each task's family is summarised on its own line; no pooled sentence.

## 5. Restart of step 3 after the failed attempt

Move out of `host_state/features/` to an archive folder outside `host_state` (never delete) every
notice-derived file: `notice_joint.parquet`, `notice__shared_numeric.npy`, every `notice__*.extras.npy`,
every `notice__*.feature_order.json`, `notice_coverage.jsonl`, `notice_P_content_matched.npy`,
`NOTICE_DERIVED_DATE_SIDECARS.json`, and any `*.tmp` left by an interrupted atomic write. Keep and verify:
news panel copy (DataFrame equality), news shared block (float32 bytes), news bundles/coverage/mask
(rewritten), `W_Bai_selection.json` (reused), `embedding_cache/` (per-entry signature and vector hash),
`DISK_PLAN.json` (rewritten). Then rerun the same `cli.py features`. A pure function in `features_adapter`
lists the move-out set from file names only; the machine procedure, the test and HOST_RUN use it.

## 6. Chain, archive, freeze

Archive every changed file and the quantity_parsing freeze under `input_definitions/archive/pre_SPEC_5/`. `runtime.SPECIFICATION_CHAIN`
becomes (shared_storage, quantity_parsing, input_definitions); an input_definitions step must declare `pre_score_addendum = confirmation-A1`, the specified
feature-content change, the added arms {news: [W2_D], notice: [NPM]} and that primary families, contrasts,
Holm, windows, learners, seeds, budget and drop order are unchanged. Every truncated, skipped, reordered,
duplicated, extra or unknown step, archive or in-place drift, design/rule change or missing declaration is
refused. `validate_permit` still resolves only the input-bound root. Candidate `ADAPTER_FREEZE.json`,
`SPECIFIED_ADAPTER_CHAIN.json`, `FINAL_VERIFICATION.json`.

## 7. Tests (synthetic only)

The suite also tests: W2_D rule (ranking, gate, price days, specified lag, equivalence of confirmation ADF/Granger
helpers with the hash-pinned NEWSRUN2 functions, exact count series), NPM bundle, plan counts and batches,
build/resume dispositions, fit refusal, every scoring addition, chain acceptance/rejection, and a synthetic
replica of the production failure (stale notice panel copy -> `Resume panel identity drift` at the notice
pass after a completed news pass -> documented move-out -> rerun equals a clean input_definitions build bit for bit).
The scoring additions also run end to end on the synthetic score synthetic inputs of
`tables/test_fill_conf_results.py` (scratch copy, specified plan). Frozen primary readings must be
identical to the pre-input_definitions code on the same synthetic predictions. No rule changes after any result is seen.
