# Fitting memory settings (execution specification 5)

The specification is bound by `SPEC_FREEZE.json`. The calculation chain is
original → shared_storage → quantity_parsing → input_definitions → storage_limits → fit_memory.

The memory configuration dated 2026-10-02 combines storage_limits options 1 + 2 + 3.
It preserves the models, learner parameters, features, statistics, 24-hour budget,
time accounting and drop order. COMPUTE_PLAN records these resource settings.
The feature-generation record uses the storage_limits content hash `51c4f1b8…`.
Measurements and tests use a separate code tree and validate the
`execution/cli.py` input identities before installation.

## 1. Measurement (option 3)

The module `execution/anonymous_memory.py`, provides the measures.
- **What counts.** Anonymous (non-file-backed) resident memory: on macOS the physical footprint
  (`proc_pid_rusage`, `RUSAGE_INFO_V4.ri_phys_footprint`); on Linux `/proc/<pid>/status` RssAnon.
- **What does not count.** Memory-mapped file pages, because the OS can reclaim them.
- **Peak per worker.** On macOS, `ri_lifetime_max_phys_footprint` of the worker itself. On Linux, `VmHWM` serves as
  a conservative upper bound.
- **Basis.** Probe on this machine (2026-10-02): a child that wrote and read a 300 MB memory map had 312 MiB RSS but a
  22 MiB footprint. A 286 MiB anonymous allocation raised the footprint to 308 MiB. The lifetime maximum kept 308 MiB
  after the free.
- **Records.** Every fit receipt (news, notice and LEAR) records `peak_rss_bytes` (unchanged, `ru_maxrss`) and
  `peak_anonymous_bytes`. Group records hold the tree and worker peaks of both measures, and heartbeats hold both
  measures per worker.

## 2. Limits and admission (option 1)

- **Per-fit anonymous stop.** News and LEAR keep 2 GiB (`JOB_LIMIT`). Notices get 6.6 GiB (`NOTICE_JOB_LIMIT` =
  `TREE_LIMIT`), because notice fits are serial with 6 learner threads and never overlap the news pool. The stop
  applies live (`_fit_group`) and to the worker's own peak (`FAILED_RESOURCE`).
- **Task tree.** The parent, workers and resource tracker together:
  - a hard stop at 6.6 GiB anonymous (`MemoryError`, workers terminated, unchanged handling);
  - a throttle to one worker at 6.0 GiB anonymous (unchanged rule).
- **Admission per task.** The next task starts only if the current tree anonymous memory plus that task's projection
  is below 6.6 GiB. Otherwise the group waits for a running fit, or raises if none is running (unchanged).
- **Projection.** It is 1.08 × the largest recorded anonymous peak among same-source records of the task's memory
  class × max(1, task bank cells / largest recorded cells of that class).
  - Cells are rows × columns. Bank rows are the specified matrix rows (unchanged growth bound).
  - The memory classes are: news wide (specified extras ≥ 384 columns: L_chen, E_raw, P_shift, P_content and their
    24 h / first_L variants), news narrow (all other news arms), notice, and LEAR.
  - With no record of the class, the largest same-source record is used. With no record at all, the existing
    defaults apply (768 MiB for counted pilots, 512 MiB in stages).
  - Older records without `peak_anonymous_bytes` count with their RSS, which is conservative.

  This lowers the news concurrency only where wide arms need it.
- **Unchanged.** The frozen scheduler (`projected_stage_seconds`, four news workers as target, the origin barrier),
  the wall ledger, the 24-hour budget and the whole-stage admission and drop order are unchanged. Slower batches may
  drop more optional stages, which the decision accepts.

## 3. Worker memory reduction (option 2), outputs bit-identical

In `execution_adapter._worker`:
1. After `select_rows`, extract the training target, the weights, the query result keys and, for notices, the query
   anchors and target times. Release the panel and clocks before the fit.
2. Assemble only the training matrix before the fit.
3. After `save_model`, release the training matrix (close its memory map, remove the scratch file) and LightGBM's
   training dataset (`free_dataset`).
4. Only then assemble the query matrix and predict.

Nothing else changes: model inputs, parameters, feature names, prediction arithmetic, clipping and the receipt
fields. **Proof:**
- the booster text (bytes and SHA-256), the prediction parquet SHA-256 and the receipt fields of the pre-fit_memory and
  fit_memory workers are identical on the same synthetic bundle;
- this holds for a news wide case at full production shape (131,472 rows; 872 + 386 columns; last origin) and a
  notice wide case at production width (61 + 387 columns) with more than 200,000 training rows, so LightGBM's sampled
  binning path is used;
- small unit cases are in the suite.

## 4. Feature completion bound to storage_limits (no feature-code change)

- **Feature path unchanged.** `features_adapter.py` and the feature path stay byte-identical to storage_limits. The feature
  path is:
  - `features_adapter.py`, `feature_storage.py`, `embedding_adapter.py`, `notice_label_adapter.py`, `panels_adapter.py`,
    `additional_scoring.py`, `cli.py` and `confirmation/code`;
  - the `runtime.py` definitions other than `SPECIFICATION_CHAIN`, `_specification_declared` and the candidate fit_memory constant.
    These must be AST-identical.
- **Recorded proof.** `UNCHANGED_CODE.json` records `feature_path_identical_to_spec_6`.
- **Rule** (`fit_memory/features_completion_rule.py`, used by `host_chain_SPEC_7.sh`). `COMPLETE_features.json` is
  accepted for the fit steps iff its `adapter_freeze_sha256` either:
  - equals the fit_memory freeze in `fit_memory/SPECIFIED_ADAPTER_CHAIN.json`, or
  - equals the storage_limits freeze `51c4f1b8278be8a1fcb152f632ccab5f4c6e0722ee24ba4130822c040498c77c`, and
    `UNCHANGED_CODE.json` has `state == PASS` and `feature_path_identical_to_spec_6 == true`, and the fit_memory chain
    step's parent freeze is that storage_limits freeze.

  Anything else is refused with the reason. The rule is tested with synthetic receipts.

## 5. Source hashes and execution records

- **Declaration.** `runtime.SPECIFICATION_CHAIN` gains `'fit_memory'`. A fit_memory step must declare
  `no_statistical_design_or_feature_content_change = True` and
  `execution_resource_rule = 'FIT_MEMORY_ANONYMOUS_LIMITS_WIDE_ARM_ADMISSION_QUERY_AFTER_FIT'`.
- **Archive and freeze.** Pre-fit_memory files and the storage_limits freeze are archived under `fit_memory/archive/pre_SPEC_7/`.
  Candidate `ADAPTER_FREEZE.json`, `SPECIFIED_ADAPTER_CHAIN.json`, `FINAL_VERIFICATION.json` and `EXECUTION_NOTE.md` are
  written. A T3 continuity record lists the T3-listed files fit_memory changes and their preserved copies.
- **Machine files.** `HOST_RUN.md` step 3/4 is updated. `fit_memory/host_chain_SPEC_7.sh` waits for the features step,
  applies the rule of section 4, runs counted-pilots → fit-bank → lear → seal, and stops before score. The source starts
  it.

## 6. Tests (synthetic only)

Whole suite plus:
1. **Measures.** On macOS the anonymous measure excludes a memory-mapped file and counts an anonymous allocation;
   the lifetime peak is kept.
2. **Limits.** Per-source limits apply: news 2 GiB, notice 6.6 GiB, LEAR 2 GiB. A live overrun of a worker or of
   the tree is still a hard stop.
3. **Admission.** It lowers concurrency for wide news arms (a synthetic projection table) and not for narrow ones.
   Narrow tasks do not inherit wide peaks.
4. **Receipts.** They carry both measures, including LEAR.
5. **Bit identity.** Reference (archived) and candidate `_worker` give identical model text, model hash and predictions on news
   and notice cases.
6. **Completion rule.** Accepted: the fit_memory freeze, and the storage_limits freeze with proof. Refused: the storage_limits freeze
   without proof, input_definitions/older or unknown freezes, and a missing field.
7. **Chain.** A five-step chain with refusals of truncated, skipped, reordered, duplicated, extra and unknown steps,
   of intermediate roots, and of mutated or missing fit_memory declarations.

## 7. Memory measurements on synthetic data at study dimensions

These run only while no confirmation process is running, after the features rerun, because the machine has 8 GiB.
- **Cases:**
  - news L_chen, last origin, full shape (reference and candidate worker);
  - news N, full shape (candidate worker);
  - notice L_chen_notice width with R = 225,000 and R = 450,000 training rows and query = 0.589 R (reference and candidate at
    225,000; candidate at 450,000);
  - notice L14 width at 450,000 (candidate).
- **Extrapolation.** Notice anonymous peaks are extrapolated linearly in R above the 200,000-row sampling saturation
  to R = 894,901.
- **Outputs:**
  - the anonymous and RSS peaks;
  - the bit-identity results;
  - the expected admitted concurrency per news stage (simulating the section 2 rule with the measured peaks and the
    parent footprint);
  - the per-stage runtime from the measured per-fit runtimes;
  - an updated 24-hour feasibility estimate under the unchanged admission formula, naming the stages likely dropped.

  They go to `MEMORY_MEASUREMENTS.json` and `FEASIBILITY_24H.json`. Measurement processes may exceed the 1.5 GB
  guideline; that is reported.
