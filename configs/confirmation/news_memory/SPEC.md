# CONFX8 specification: news per-fit resource limit (execution amendment 6)

[KEEP_ACTIVE] This specification is hashed in SPEC_FREEZE.json before implementation or tests. Chain: input-bound
original → CONFX3 → CONFX4 → CONFX5 → CONFX6 → CONFX7 → CONFX8. Install uses CONFX7's non-switch pattern.

**Decision / template rule.** The author's CONFX8 instruction of 2026-10-04 authorizes an execution resource
adjustment only. No research method, model input, parameter, feature name/value, prediction arithmetic, clipping,
receipt schema, stage order, origin barrier, wall ledger, 24-hour budget or whole-stage drop rule changes.
No installed frozen file is modified during preparation. Installation and production-shape measurements belong
to the coordinator. No host_state, seal, score or production prediction is read during preparation.

## 1. Reason and exact constants

CONFX7/MEMORY_MEASUREMENTS.json records full news banks of 131,472 rows, last origin 2026-09-30:
news L_chen (872 + 386 columns) new and old FAILED_RESOURCE; news N (872 columns) new FAILED_RESOURCE.
The author's supplied sampled peaks are about 3.02, 2.89 and 2.31 GiB. The JSON's larger worker lifetime peaks
are 3,300,741,536 bytes for new L_chen and 2,487,864,800 bytes for new N; the old L_chen sampled peak is
3,106,836,848 bytes. Use the larger worker lifetime peaks for conservative projections.
The same JSON records the old notice R225000 pair as FAILED_RESOURCE under its old 2 GiB RSS guard; the new
notice cases are COMPLETE. New notice full-row worker lifetime peak is 2,096,369,600 bytes (sampled peak
1,838,337,792 bytes). These distinctions correct rounded sampled versus lifetime figures, without reading outputs.
The author reports measure_speed_a3 stopped at the 2 GiB anonymous limit; its two A3 output files are absent.

- Add NEWS_JOB_LIMIT = 3,758,096,384 bytes (3.5 GiB). job_limit('news') returns it, both live and receipt guards.
  This is about 15% above the supplied 3.02 GiB sampled maximum and 13.9% above the recorded lifetime maximum.
- JOB_LIMIT = 2,147,483,648 bytes remains for LEAR; NOTICE_JOB_LIMIT = TREE_LIMIT remains 6.6 GiB
  (int value 7,086,696,038 bytes). TREE_LIMIT = 6.6 × 1024³ and THROTTLE = 6.0 × 1024³ remain unchanged.
- Admission remains max(measured tree, parent + reserved running projections) + incoming projection < TREE_LIMIT.
  The up-to-seven news pool and three LEAR subjob workers remain unchanged.

## 2. News projections, same admission rule

Current _projected_anonymous is measured-class peak × 1.08 × max(1, bank cells / recorded cells), but its empty
record default is 512 MiB and counted-pilots supplies 768 MiB. Neither bounds these measured news peaks.
Add fixed resource-only reference constants: NEWS_REFERENCE_ROWS = 131472; NEWS_REFERENCE_PEAKS =
{'news_wide': 3300741536, 'news_narrow': 2487864800}; NEWS_REFERENCE_COLUMNS = {'news_wide': 1258,
'news_narrow': 872}. A news class projection has a lower bound of its reference peak × 1.08 ×
max(1, current bank cells / reference cells), with the unchanged cells-growth rule. Existing measured-record
projections may exceed this floor and still win. Notice/LEAR projection paths are byte-for-byte preserved.
Counted news pilots receive this same projection rather than 768 MiB; their serial order is preserved.
No scheduler source, admission formula, runtime estimate, record collection or worker computation changes.
CONF/CONFX2/scheduler.py does not exist; runtime resolves the frozen CONF/code/scheduler.py.

## 3. Measurement-only override and bit-identity proof

Copy CONFX7's six cases, seeds, shapes, generation and comparisons without changing them. Old means pre-CONFX7,
not pre-CONFX8. Scratch old roots restore CONFX7/archive/pre_CONFX7 files; new roots overlay CONFX8 staging.
In the CONFX8 measurement harness only, set the old execution_adapter.JOB_LIMIT to 3.5 GiB for both old/new
pair reference runs (news L_chen and notice R225000). The old guard remains RSS; the override is explicitly
recorded as measurement-only and never appears in production code. A full-shape old/new news pair must both
COMPLETE and match booster text SHA-256, model SHA-256, prediction parquet SHA-256, keys, training indices,
row counts and feature count. Notice R225000 at full width must do the same; its >200000 training rows exercise
sampled binning. Full-row notice remains new-only. Other cases and speed comparisons remain CONFX7-identical.
Outputs belong exclusively to CONFX8. Missing, failed, wrong-shape, stale or non-identical measurements refuse
the gate. The gate also requires news 4-versus-7 and LEAR serial-versus-1/3 comparisons and both feasibility files.
Production-shape evidence is pending coordinator execution; small-shape tests cannot substitute for it.

## 4. Feature completion, chain, provenance

The feature path stays byte-identical to the installed non-switch CONFX7 path. Its exception relative to CONFX6
remains only the proven resume comparison. Accept a COMPLETE_features receipt bound to CONFX8, CONFX7, or the
registered CONFX6 freeze 51c4f1b8278be8a1fcb152f632ccab5f4c6e0722ee24ba4130822c040498c77c with the retained
CONFX7 proof and verified CONFX7→CONFX8 parent links. Refuse older, unknown, missing or unsupported chains.
runtime.AMENDMENT_CHAIN gains CONFX8 and its declaration requires no_statistical_design_or_feature_content_change
= True and execution_resource_rule = NEWS_PER_FIT_ANONYMOUS_3_5_GIB_MEASURED_PROJECTION_FLOORS.
Archive changed files, HOST_RUN.md and the CONFX7 adapter freeze before replacement. Freeze preserves every
existing ancestor-bound file, adds CONFX8 artifacts, and verifies the exact chain, frozen design and test identities.
T3 continuity keeps CONFX7's preserved T3 bytes and records CONFX8's immediate parent separately. T4 must timestamp
the installed amendment and new gate/proof records before the coordinator starts the chain; it does not replace T3.

## 5. Concurrency, feasibility and tests

CONFX7/FEASIBILITY_24H.json projects 20.97814072136349 hours, at most two news fits per origin (one in first-L),
and likely whole-stage drops of window_24h and first_L_news. It assumes successful fits and is not executable
evidence under the old 2 GiB limit. Raising the stop makes completion possible; it does not raise the task-tree
ceiling or guarantee 24-hour completion. Reference projections plus the parent may admit fewer than two wide
fits. Recompute both estimates from successful CONFX8 measurements; retain all adverse findings.
The feasibility arithmetic, stage accounting, drop order and assumptions are copied from CONFX7, renamed only.

Tests use synthetic small shapes and nice 10: exact limits and hard stops; class floors, growth and reserved
admission; pilot projections; old override confinement; small old/new identity; completion-chain refusals;
unchanged CONFX7 suite on its own replica; amended complete suite with only obsolete constant/chain expectations
updated. At most one full-shape synthetic fit may run at once and only with memory_pressure free >=40%; heavy
production-shape measurement is deferred to the coordinator on the idle host. No production CLI or install runs.

**Traceability.** Facts: CONFX7/MEMORY_MEASUREMENTS.json, CONFX7/FEASIBILITY_24H.json, supplied failure account.
Rules/templates: CONFX7/SPEC.md and addenda 1–4, CONFX7 scripts, installed CONFX2 sources, CONF/code/scheduler.py,
COMMON_RULES.md. Installation, host update and amendment freeze are supplied as scripts and are not run here.
