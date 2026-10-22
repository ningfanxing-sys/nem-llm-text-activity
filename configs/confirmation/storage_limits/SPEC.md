# CONFX6 specification: feature-storage auxiliary allowance and resource-guard audit (execution amendment 4)

This is a pre-fit, pre-outcome amendment that touches execution resources only. It is frozen in `SPEC_FREEZE.json`
before any code change and before any audit measurement. The chain is original → CONFX3 → CONFX4 → CONFX5 → CONFX6.

What it changes and does not change:
- **Unchanged:** no statistical, design, feature-content or inference rule changes. Every frozen COMPUTE_PLAN rule
  is unchanged, in particular the 2 GiB per-job and 6.6 GiB task-tree RSS stops, the 6.0 GiB throttle, the 24-hour
  budget and the LEAR 0.5 s/pair admission floor.
- **Not read:** no CONF fit, prediction, seal or score exists. No D outcome is read. Under `CONFX2/host_state/` only
  names, sizes and allocated block counts are listed.
- **Not run:** no production command is run.

## 0. Production facts (names, sizes, clocks; coordinator message and logs outside host_state)

- **The failure.** The CONFX5 restart procedure moved 18 notice files out at 2026-10-01T19:43Z. `cli.py features`
  started at 05:43 AEST and stopped at 07:06 AEST in `features_adapter.py` line 691, inside the notice row loop
  (`storage_plan.check('features: remaining bank after coverage notice')`, raised at line 589):
  `DiskSpaceError ... auxiliary cache/coverage exceeded its reserved bytes`. The new CLI receipt
  `FAILED_features_attempt_2026-10-01T21-06-02.995984+00-00.json` was not opened. About 40 GiB is free.
- **The rule that stopped it.** `FeatureDiskPlan` gives the auxiliary category a fixed 512 MiB budget (CONFX3) and
  raises as soon as allocated auxiliary bytes exceed it, whatever the free space.
- **Allocated blocks now** (`st_blocks × 512`):
  - auxiliary 525,684,736 bytes;
  - `embedding_cache/`: 73,938 files (36,969 `.npy` + 36,969 `.json`), 76,465,286 apparent bytes and 302,850,048
    allocated bytes, that is 8,192 bytes per cache entry (one 4 KiB block per file);
  - `notice_coverage.jsonl` 172,941,312;
  - `news_coverage.jsonl` 29,331,456;
  - `NOTICE_DERIVED_DATE_SIDECARS.json` 18,317,312;
  - `W2_D_selection.json` 401,408;
  - the 13+1 news feature orders about 1.6 MB.

  At the stop, a short-lived extra auxiliary file (an atomic-write temporary or a coverage page) must have taken the
  total over 536,870,912. The guard is evaluated every 10,000 notice rows.
- **Progress.** The notice extras are sparse memory maps. Their allocated blocks are 15.5% of the apparent sizes
  (for example 340,664,320 of 2,201,164,796 bytes for `notice__L_chen_notice__main.extras.npy`). The notice pass
  had therefore written about 15% of its 1,421,941 rows. At about 786 bytes per row, a complete notice coverage
  file would be about 1.1 GB on its own.
- **Timeline** (`CONFX2/OPENED_PATHS_host_features.jsonl` clocks):

  | UTC | Event |
  |---|---|
  | 19:43 | start |
  | 19:43–20:15 | W2_D selection and corpus |
  | 20:15:27–20:18:37 | news pass (warm embedding cache) |
  | 20:20:46 | notice pass opened |
  | 21:06:03 | stop |

  The notice pass needed about 45 min for about 15% of its rows.

## 1. Rule: the auxiliary allowance becomes a derived reservation, never a stop

Categories are unchanged: arrays (`*.extras.npy`, `*__shared_numeric.npy`), panel copies and auxiliary (everything
else under `features/`, including `embedding_cache/`, coverage, sidecars, feature orders, masks, selections and
temporaries). The array and panel budgets are unchanged.

1. **Derived auxiliary allowance**, fixed when the plan is made: A = auxiliary bytes allocated at plan time + 2,048 ×
   (news panel rows + notice panel rows). These are 131,472 + 1,421,941 rows in production.
2. **At every checkpoint**, required free space = Σ max(0, budget − allocated) over arrays, panels and auxiliary
   (budget A), plus the unchanged 4 GiB `FEATURE_HEADROOM_BYTES`. A shortfall raises the existing `DiskSpaceError`
   from `require_disk_space`. Allocated auxiliary bytes above A only set the auxiliary reservation to zero and print
   one note to stderr. It is **not** a stop.
3. **Recorded plan.** `DISK_PLAN.json` records the rule name, A, the measured auxiliary bytes at plan time, the
   per-row constant and the row counts. Planned bytes = arrays + 2 × panel copies + A. The fixed 512 MiB constant is
   removed.
4. **Standalone path.** The single-source `_write_bundles` path (no joint plan) is unchanged.

**Justification.**
- **Purpose.** The guard exists to stop cleanly before the disk fills, while the remaining array writes still fit.
  The real condition is free space at each checkpoint against the remaining committed bytes plus headroom.
- **Remaining arrays stay protected.** They stay reserved at every checkpoint (budget − allocated). Auxiliary
  overspend reduces measured free space and is therefore seen at the next checkpoint. Between checkpoints (10,000
  rows) auxiliary growth is about 20 MB at the measured rates, far below the 4 GiB headroom.
- **Not a false stop.** A stop then means the disk is actually short.
- **The constant.** The constant 2,048 bytes per panel row is derived from the production allocation above:
  - notice coverage about 786 B/row;
  - news coverage 223 B/row;
  - embedding cache 8,192 allocated bytes per entry, about 195 B/row over the bank so far;
  - sidecars, orders and selections about 13 B/row.

  Together that is ≤ about 1.1 KB/row, so 2,048 leaves about 1.8 times margin. Because A is a reservation and not a
  stop, an underestimate cannot stop the run while the disk is ample. An overestimate only matters when the disk is
  already within about 3 GB of the true need.
- **Kind of rule.** This is an execution-only resource rule, a project choice like CONFX3's. It is not a research
  method, so no top-venue template applies.

## 2. Audit of every remaining resource guard and fixed allowance (production sizes)

Path: counted-pilots → fit-bank → lear → seal → score. Inputs:
- file names and sizes under `host_state/features/` (column counts follow from the `.npy` sizes and row counts);
- the code;
- the frozen DESIGN_CONFIG and COMPUTE_PLAN;
- BASE25 LEAR records (names, sizes and the counts in its test log);
- synthetic measurements.

A guard **trips falsely** if it can stop the run while the real resource is adequate.
- **Adapter-level allowances** that can trip falsely are fixed in CONFX6.
- **Frozen COMPUTE_PLAN rules are not changed.** If the audit projects that one will be reached, CONFX6 reports the
  measurement and the options for a separate decision.

Items:
1. **Features:** the new rule above; the rglob cost per checkpoint.
2. **Fit-bank disk plan** (`fit_disk_plan` + 3 GiB headroom) per stage and per wave. Production shapes for every
   registered stage come from file sizes, with unpruned columns as upper bounds. These are compared with free space
   after the feature rerun.
3. **Memory**, the frozen COMPUTE_PLAN rules: per live worker 2 GiB RSS, task tree 6.6 GiB, throttle 6.0 GiB, pilot
   projection 768 MiB, stage projection max(peaks) × 1.08 × shape growth. Synthetic measurement with the real
   `execution_adapter._worker`, run in a fresh subprocess from a scratch copy of the installed code (no live log is
   touched). Peak RSS is read as the worker records it (ru_maxrss), plus psutil RSS/USS sampling every 50 ms.
   - (a) **News at full production shape:** 131,400 training rows (the last origin) × 1,258 unpruned columns
     (872 shared + 386 extras), 72 query rows, news parameters.
   - (b) **Notices at the largest width:** 448 columns (61 shared + 387 extras), notice parameters (n_jobs 6),
     training rows R ∈ {75,000, 150,000, 225,000} with query rows 0.589 R (the production ratio 527,040/894,901).
     A least-squares line in R is extrapolated to R = 894,901 and 527,040 query rows. Also a narrow notice arm (78
     columns) at R = 225,000.
   - The real `_worker` with unchanged code is used, so the measured quantity is exactly the one the frozen guards
     test. Synthetic values only.
4. **LEAR:** per-job persistent reservation 2 MiB against the measured BASE25 receipt and model sizes and the
   recorded warning counts. One synthetic daily job through `lear_adapter_confx5.daily_forecast`, measuring receipt
   bytes and worker RSS.
5. **Seal:** no disk guard. Sizes of `sealed/` copies and `SEAL.json` from registered shapes. A synthetic parquet of
   the notice prediction schema at 527,040 rows is measured.
6. **Score:** no disk or memory guard. Memory and output sizes are estimated from shapes.
7. **Fitting ledger:** heartbeat rewrite size; no guard.

Output: `RESOURCE_GUARD_AUDIT.json` (script `audit_resource_guards.py`), summarised in `EXECUTION_NOTE.md`.

## 3. Restart of step 3

- **No move-out.** The CONFX5 run wrote `notice_joint.parquet` and `notice__shared_numeric.npy` from the current
  inputs with the current panel code. The rerun verifies them (DataFrame equality, float32 bytes). It recreates every
  extras matrix, coverage file, feature order and mask, and rewrites the date sidecar and `DISK_PLAN.json`. It
  reuses `W_Bai_selection.json` and `W2_D_selection.json` (immutable) and checks every embedding-cache entry before
  use.
- **The same command is rerun.** A stop in a later attempt during the notice pass leaves the same kind of state and
  is resumed the same way. The CONFX5 move-out applied only to files written by older adapters.
- **Time.** The rerun skips the W2_D selection (about 32 min) and reuses all cached embeddings. The notice pass is
  the long part: about 45 min reached about 15% of its rows, and a linear extrapolation is about 5 h. The rerun
  repeats the first 15% with warm-cache hits and still has to embed the remaining notice texts. The audit states an
  estimate with this uncertainty, not "about 80 minutes".

## 4. Tests (synthetic only)

1. **Exact reproduction.** The archived pre-CONFX6 `features_adapter.py` (loaded from
   `CONFX6/archive/pre_CONFX6/`) runs `_write_bundles` for a notice source of at least 10,000 rows. Before the run,
   20,000 cache-like small files (production sizes 1,664/258 bytes, each one allocated block) sit in the features
   directory, and the coverage of each row group is padded so that allocated auxiliary bytes pass 512 MiB inside the
   row loop. The result must be `DiskSpaceError` "... remaining bank after coverage notice: auxiliary cache/coverage
   exceeded its reserved bytes", with ample free disk.
2. **The same state then passes.** The CONFX6 module completes, with no file moved. Its arrays, feature orders,
   panel copy, mask and coverage equal a clean CONFX6 run of the same input bit for bit.
3. **Real shortage still stops.** CONFX6 with `shutil.disk_usage` patched below the requirement stops with the real
   free-space `DiskSpaceError`, before any write of the next checkpoint.
4. **Plan record.** The plan records the derived allowance. The joint plan of `build_all_features` writes the new
   `DISK_PLAN.json` fields. No fixed 512 MiB remains.
5. **Arrays stay reserved.** The CONFX3 unit test of the auxiliary stop is replaced by its CONFX6 form: remaining
   arrays and panels stay reserved, and auxiliary overspend is not a stop.
6. **In-place restart.** A synthetic `build_all_features` stopped by an injected `DiskSpaceError` in the notice row
   loop, after a complete news pass, is rerun in place with nothing moved. It completes and equals a clean build.
7. **Chain.** Input-bound → CONFX3 → CONFX4 → CONFX5 → CONFX6 is accepted. Truncated, skipped, reordered,
   duplicated, extra and unknown steps are refused, as are intermediate roots and mutated or missing CONFX6
   declarations. CONFX5 declaration mutations are still refused.
8. **Whole suite.** The whole suite is run unchanged otherwise.

## 5. Chain and records

- **Declaration.** `runtime.AMENDMENT_CHAIN = ('CONFX3','CONFX4','CONFX5','CONFX6')`. A CONFX6 step must declare
  `no_statistical_design_or_feature_content_change = True` and
  `execution_resource_rule = 'FEATURE_AUXILIARY_ALLOWANCE_DERIVED_RESERVATION_NOT_A_STOP'`.
- **Archive.** Changed files and the CONFX5 freeze are archived under `CONFX6/archive/pre_CONFX6/`. The new freeze,
  `AMENDED_ADAPTER_CHAIN.json`, `FINAL_VERIFICATION.json`, `EXECUTION_NOTE.md` and `EXECUTION_DIFF.patch` are written.
- **Host files.** `HOST_RUN.md` step 3 records this failure and the restart. `CONFX6/host_chain_CONFX6.sh` resumes
  steps 4–7 only after a `COMPLETE_features.json` carrying the CONFX6 freeze.
- **Code scope.** The changed code is limited to `features_adapter.py` (`FeatureDiskPlan`, `build_all_features`, two
  new constants and a helper) and `runtime.py` (chain and declaration), plus tests. Any further change found
  necessary by the audit is added only through a frozen addendum to this specification.
