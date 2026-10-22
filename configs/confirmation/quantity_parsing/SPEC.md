# Literal MW quantity parsing

This specification defines the notice MW literal parsing rule and is bound by `SPEC_FREEZE.json`. Related implementation details: `paper_plan/task_specs/TASK_SPEC_4_mw_literal_parsing.md`.

## 1. Input format and saved diagnostics

- `execution/notice_label_adapter.py` `scalar()` removes commas and accepts only a bare number (`SCALAR.fullmatch`). notice_extraction 1.3 keeps the source literal in `value_text` and puts the unit in the separate `unit` enum, so the common bound form `447 MW` becomes NaN. The ISOBATCH phase-1 pre-fit audit found this on 2026-10-02 (`ISOBATCH/SLICE_TEST.json` field `mw_binding`; `ISOBATCH/REPORT.md` item D1).
- The saved feature-generation diagnostic predates fitting and scoring. The `cli.py features` attempt started 2026-10-01 23:49 AEST and ended before completion, leaving partial bundles. `PRODUCTION_INTERRUPTION.json` records the attempt.

## 2. Source evidence

- notice_extraction `prompt.txt` (byte-identical in contracts 1.2 and 1.3) tells the extractor to preserve the source number, range and qualifiers literally in `value_text`. It restricts `unit` to MW, MWh, minutes, other or UNKNOWN. It forbids choosing a range midpoint or converting units.
- `CONTRACT_SPECIFICATION_1_1.md` requires every non-UNKNOWN free-text value, including quantity `value_text`, to occur literally in the notice title or body. `validate_notice_label.py` requires the value to occur in its own evidence and a known unit to occur in that evidence.
- A contract-valid MW quantity is therefore a source literal such as `447 MW` with `unit=MW`. The frozen confirmation design requires a finite nonnegative scalar with unit MW for outage MW (`FEATURE_DEFINITIONS.md`, L_Laz MW paragraph). It derives reserve values from the label fields and their supported literal normalization (bridge paragraph).
- Reading the number in front of a token equal to the declared unit is the minimal literal normalization implied by the contract. The bare-number-only check is an interface mismatch, not a feature choice.

## 3. Frozen rule

For a quantity with literal `t = value_text` and declared unit `u = unit`:

1. Let `s = str(t).strip()`.
2. Suppose `u` is a concrete schema unit token (`MW`, `MWh` or `minutes`). Suppose also that `s` fully matches `N\s*U`, ignoring case, where `U` is `re.escape(u)` and `N` is `[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?`. Then set `s` to the `N` part.
3. Apply the pre-quantity_parsing rule unchanged: remove commas, require a full `SCALAR` match, convert with `float`, and require a finite value. For LOSS, also require `>= 0`. Anything else is NaN (UNKNOWN).

Consequences:

- Every literal accepted before quantity_parsing keeps exactly the same value. Bare numbers keep the reference parser, including its comma handling.
- The parser accepts exactly one number, written with no commas or with standard comma thousands separators. Optional whitespace and a token equal to the declared unit may follow, in any letter case. Examples: `447 MW`, `447MW` and `1,186 mw` with `unit=MW`.
- Everything else stays UNKNOWN, as now:
  - ranges;
  - qualifiers (`approximately`, `about`, `less than`, `up to`, `~`, `<`);
  - times or other trailing text (`128 MW at 0730 hrs`);
  - arithmetic and multiple numbers;
  - a unit literal with nonstandard comma grouping;
  - any unit token that differs from the declared unit (`MWh` when `MW` is declared, `megawatts`, `GW`);
  - a suffix when the declared unit is `other`, `UNKNOWN` or missing.

  No unit is converted.
- `_bound_quantities` passes the quantity's declared unit to both of its `scalar` calls. These rules do not change: binding status and reason, role, the `unit == MW` requirement, asset, window, unique value per role, nonnegative LOSS and identity reliability.

## 4. Functions and input checks

Changed:

- `execution/notice_label_adapter.py`: `scalar`, `_bound_quantities` and two constants.
- `execution/runtime.py`: the specification-chain verifier and the chain-root lookup in `validate_permit`.
- `execution/tests/test_execution_specification.py`: chain synthetic inputs.
- Candidate `execution/tests/test_nrx_mw_literal.py`.
- `execution/ADAPTER_FREEZE.json`.
- `HOST_RUN.md` step 3.

Unchanged and verified by hash:

- every other execution code file, test and receipt;
- `confirmation/code`;
- `confirmation/FREEZE.json` and its frozen files;
- notice_extraction labels and contracts;
- panels, pruning, learners, seeds, stages, budgets, and the inference and scoring rules.

An AST comparison must show that no other top-level function, class or constant changed in the two edited modules.

## 5. Specification chain

- Archive the pre-quantity_parsing bytes of every changed file under `quantity_parsing/archive/pre_SPEC_4/`, together with the shared_storage adapter freeze (SHA-256 `31d95d21be89a9a69fd8653d630f2e670fbdb06bac1ede7319b5a43e3072d985`). Record them in `BEFORE_IDENTITIES.json`.
- Write a candidate `execution/ADAPTER_FREEZE.json`:
  - the same `design_freeze` and `execution_rule`;
  - every shared_storage-bound file, plus the quantity_parsing records;
  - an `execution_specification` containing:
    - task `quantity_parsing`;
    - the archived parent freeze;
    - the before identities, the execution note, the spec and proof identities;
    - `no_statistical_design_or_inference_rule_change: true`;
    - `feature_content_change: NRX_MW_LITERAL_PARSING_CORRECTION_ONLY`;
    - the list of MW-dependent columns.
- The runtime starts at the current freeze and follows `parent_adapter_freeze` links back to the input-bound hash. Counted from the input-bound root, the task sequence must be exactly (`shared_storage`, `quantity_parsing`). Each step must satisfy all of the following:
  - The parent, note and before identities verify.
  - The before identities archive the parent freeze at the parent path.
  - `design_freeze` and `execution_rule` are equal to the parent's.
  - The step's own declarations are present.
  - Every file that the parent freeze lists is byte-identical either in the earliest archive at or after that step or, failing that, at its current path.
- The runtime raises `PermissionError` for any of the following:
  - a truncated, skipped, reordered, duplicated, extra or unknown step;
  - drift in an archived or current file;
  - a design or rule change;
  - a missing declaration.
- `validate_permit` resolves only the input-bound adapter-freeze path, and only to the verified chain root. The root is `de80c4e0c3450f3e4383c477c4a3a088cc7d3956835f8ba5e51cf5d78944b394`, archived by shared_storage. The input-freeze and authorization bytes are untouched, and quantity_parsing never opens `host_state/`.
- `SPECIFIED_ADAPTER_CHAIN.json` records the root, shared_storage and quantity_parsing identities.

## 6. Equivalence proof and census (labels and keys only)

**Inputs read:**

- notice_extraction `results_1_3/labels.parquet`:
  - pass 1 reads only `notice_id`, `period` and `scope_group`;
  - pass 2 uses an Arrow row filter, `period` in {`2021-22`, `2023`, `2024`, `2025-11..2026-02`}.
- The lines of `notice_extraction/scope.jsonl` whose top-level `notice_id` is admissible. Other lines are never JSON-parsed.
- `execution/prepared_sources/notice_prefix_keys.parquet` (`notice_id`, `available_utc`), used for the production clock check.
- Frozen code and inputs: the source-relation code, the normalized R wrapper, word_features `selection/C.json` and the stopwords.
- notice_fitting `final/design.json` (F1 index paths only), the two F1 index files, and the `nw_any_local` column of the notice_fitting L block.
- B1b `development_metadata.parquet`, columns `region`, `issue_time`, `target_time` and `horizon` only.

All input identities are hashed, and the slice inputs must equal ISOBATCH `SPEC_FREEZE.json`.

**Never read:** price, `y`/`y_true`, weight or outcome columns; P5MIN; `host_state/`; D-window content.

**Notice stream:** the field mapping of the production `load_host_notices`, restricted to the historical periods. Notices are sorted by (`available_utc`, `notice_id`) and their clocks are checked against the prefix keys. The expected stream is 16,935 notices: 16,461 SUCCESS and 474 terminal failures.

**Census (historical only):**

- (a) A quantity census in the ISOBATCH form, over every quantity of every SUCCESS label:
  - classify by `role` and `unit`;
  - "bound" means BOUND and BOUND_EXPLICIT_SOURCE_SCOPE;
  - "before" means the archived `scalar` returns a finite value; "after" means the normalized `scalar` with the declared unit does; LOSS uses the nonnegative check;
  - the "before" counts replicate the brief's table;
  - recovered = after and not before;
  - lost = before and not after, which must be 0;
  - for literals finite both before and after, a value change must be 0;
  - list every bound MW REQUIREMENT, AVAILABLE or LOSS literal that remains UNKNOWN.
- (b) Records and sidecars over the full historical stream:
  - RESERVE feature-eligible records with finite req, avail or both;
  - FAILURE windows with bound loss MW, with a rejected LOSS index, or with reliable-identity inputs;
  - transitions by role.

**Slice:** the ISOBATCH F1 slice (ISOBATCH SPEC PC18). `default_rng(20261002)` draws 100 rows per stratum, taking F1 train then test, and within each the active rows (`nw_any_local > 0`) then the inactive rows. The slice has 400 rows.

**Supplementary L_Laz anchor keys:** one key per historical FAILURE window whose sidecar loss fields change, provided the window is feature-eligible, has a known region and start, and is BOUNDED or OPEN_UNTIL_NOTICE. Each key is:

- region = the window's region;
- issue = ceil5(max(`available_utc`, `start_utc`));
- target = issue + 5 minutes;
- horizon 5.

Duplicate keys are dropped. Every projection is computed per key or per origin, so both key sets may share one panel.

**Computation:** run the unchanged `features_adapter.notice_feature_rows` on a keys-only panel: origin, `target_time`, region and horizon, plus one synthetic float32 operator column so that NP, NPL and NPP run. Run it twice:

- once with the archived pre-quantity_parsing `normalize_notices` and `laz_asof`;
- once with the normalized adapter.

Both runs share the same FINAL3 module, rule wrapper, vocabulary and stopwords. A deterministic SHA-256 digest encoder stands in for MiniLM, so the model encodes no study text. Each run has its own temporary cache.

**Pass criteria:**

- P1 Records are identical except `req_mw`, `avail_mw` and `quantity_status`. Sidecars are identical except `bound_loss_mw`, `known_partial_loss_mw` and `rejected_loss_quantity_indices`.
- P2 Across all 14 notice arm/variants, the yielded keys, column order and indices are identical. Every column is float32-bit identical except the MW-dependent columns:
  - L14, NPL and NPP: `nw_res_deficit_mw_local` and `nw_res_min_avail_mw_local`;
  - L_Laz: `laz_SizeOfOutage_MW`.
- P3 Generator coverage is identical except the L_Laz report fields `failure_missing_or_unbound_mw_records`, `known_partial_outage_mw`, `known_mw_by_source_fuel` and `complete_outage_mw_available`.
- P4 The bytes of the derived-date sidecar are identical.
- P5 The census shows no lost literal and no changed literal value.
- P6 The news path cannot reach the changed function:
  - Over the execution production modules and `confirmation/code`, the static reverse reference closure of `notice_label_adapter.scalar` is disjoint from the forward closure of `news_feature_rows` and from every news function.
  - In `build_all_features`, every news write comes before the first notice_extraction call.
  - With every `notice_label_adapter` entry point replaced by a raising sentinel, the unchanged news generator on the synthetic synthetic input completes and is bit-identical to an unpoisoned run.

**Reported, not pass or fail:**

- every changed MW cell (key, reference value, candidate value) with its transition class;
- counts by role;
- agreement of the reference-adapter run with the ISOBATCH slice descriptives, as a diagnostic (ISOBATCH used the FINAL3 whitespace-normalized population text, while production uses the notice_extraction scope text);
- two checks that the code predicts must hold: no record's finite req or avail changes to a different finite value, and no finite L_Laz cell changes.

A finite-to-NaN transition is possible under the unchanged unique-value rule and is reported, not treated as an error.

**Limits:**

- peak RSS at most 1.5 GB;
- temporary files at most 300,000,000 bytes, kept in the temporary folder and moved to the Trash after use;
- every opened path is logged, and any open under `host_state/` aborts the run.

## 7. Tests

The full execution suite runs through the unchanged `run_tests.py`. It includes the candidate tests:

- the rule;
- the monotonicity check against the archived adapter;
- projections;
- the news sentinel;
- resume after an interrupted notice pass;
- the receipt behaviour for a non-`Exception` interrupt;
- chain acceptance and rejection.

Every test must pass with no source drift.

## 8. Resuming feature construction

The decision is made from code and from file names under `host_state/` only. It considers:

- whether `features/manifest.json` exists;
- the overwrite and reuse semantics of `_write_bundles`;
- the verification of the embedding cache;
- the disk accounting.

A synthetic test must show the following. Interrupt an reference-adapter notice pass, then resume in place with the normalized adapter. The result must equal a clean build with the normalized adapter, bit for bit.

No rule changes after any result is seen. Results are reported as found.
