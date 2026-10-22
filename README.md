# Do LLM-derived text features improve electricity price forecasts beyond document activity? Evidence from Australia's National Electricity Market

Data and code for the accompanying paper (2026).

The main estimates read DD/MM/YYYY timestamps inside evaluation-period notices day first, as AEMO writes them. A sensitivity analysis reads them month first (Appendix B.3, Table D1 and Supplement B.3). The two readings differ only in the Event states, Overlap components and Rule parser features of the evaluation window, so the same fitted models produce both sets of forecasts. `dayfirst/` holds the forecasts that depend on these features, with their checks and results. The official export and `seeds_windows/results/` hold the month-first results used in the sensitivity analysis.

The no-text model at seeds 20260920 and 20260921 for both tasks, the seven-day and 24-hour notice activity references and their time-shifted placebos are documented in `seeds_windows/`, with forecasts, activity arrays, code and results. Table 4 and Figure 3 decompose the gain over a no-text model into an activity step and a representation step using seed-averaged forecasts. Table D2, Supplement D.1 and Tables S1–S2 give seed details, comparisons and intervals.

## Verify the reported results

Use Python 3.12 and the dependencies in `requirements.txt`. From this folder, run:

```sh
python3 -B verify/verify_tables.py
shasum -a 256 -c MANIFEST.sha256
```

Verification uses no network, LLM requests or model refitting. It joins forecasts to truth on origin, target time, region and horizon, checks complete daily grids and unit weights, and reconstructs daily losses, paired comparisons, DM tests, Holm adjustments and decisions. Tables 4, 5, 6, A1, D1, D2 and D3 and Supplement Tables S1–S2 are checked against `verify/expected_paper_values.json`. This file records the accompanying paper source's SHA-256, printed cells and numerical prose bindings; the paper source is not distributed here.

The three-seed result is the loss of the mean forecast, with notice mean forecasts cast to float32 as in the frozen scorer. Intervals use 100,000 paired percentile bootstrap draws, seed 20260925, with non-wrapping blocks of one or seven days. The verifier also checks the stored first 2,000 draw indices and values. Printed decimals use their rounding bins and printed inequalities use strict bounds. Supplement B.3's bounds on differences between the two timestamp readings are checked directly.

The verifier prints each check and an overall PASS or FAIL and returns a nonzero exit code on failure. `verify/VERIFICATION_RESULTS.json` records the validation summary. `MANIFEST.sha256` covers every other tracked file. Allow about 0.73 GB of temporary space inside this writable repository; temporary `.recovered-*` directories are removed on completion.

## Recover stored files

Large files use deterministic `gzip -n -9`; streams over 45 MB are split into ordered parts of at most 45,000,000 bytes. `RECOVERY.json` records logical paths, original byte counts, SHA-256 hashes and stored parts. `ORIGINAL_FILES.sha256` lists compressed originals. The verifier and figure wrapper recover their inputs automatically and check original hashes before use.

To recover all compressed originals into a separate tree, run:

```sh
python3 -B verify/recover_files.py --output ../recovered
```

Allow about 0.73 GB additional disk space. Logical filenames below refer to recovered files; `.gz` and `.gz.partNNN` are storage names.

## Contents

| Folder | Contents |
|---|---|
| `code/frozen/` | Extraction, feature, LightGBM, LEAR, P5MIN, scoring, export and plotting source; required project imports. |
| `code/figures/` | Portable figure wrapper and numeric plotting inputs. |
| `configs/` | Design, model and inference settings, specifications, prompts, schemas, feature dictionary, supplementary details, column ordering and raw-source identifiers. |
| `forecasts/conf/`, `forecasts/batch/` | All 36 main and 17 batch forecast panels, including scored seeds and windows. Duplicate model names follow the scorer's selection order. |
| `forecasts/delayed/`, `forecasts/dayfirst_dates/` | Availability-delay forecasts and day-first notice-date forecasts for the sensitivity analysis. |
| `forecasts/truth/`, `forecasts/keys/` | Truth and scoring keys, including training rows: 131,472 news rows and 1,421,941 notice rows. |
| `results/score/` | Official export, computation records and 131 bound score files, including the 214-day news window and sensitivity outputs. |
| `results/seals/`, `results/fits/`, `results/bindings/` | Forecast hashes, fitting records and input/feature specifications. |
| `results/SOURCE_MAP.json` | Source paths, hashes, storage paths, projections and exclusions. |
| `losses/batch/` | Daily losses, subset membership and mean-forecast losses; seed 20260919 daily CSVs are in `results/score/R2_STATE/scored/`. |
| `extraction/notices/` | All 21,470 records: 11,348 training, 796 evaluation-period and 9,326 other saved-prefix notices; labels, scope, evidence quotations, validation failures and clocks. |
| `extraction/news/articles.csv` | 2,506 article IDs, saved clocks, status and failure flags, including 227 terminal failures. |
| `features/news/`, `features/market/` | Derived numeric news features, vocabulary, screening statistics, no-text inputs and AEMO hourly history; `features/news/INDEX.json` maps matrices to keys and columns. |
| `seeds_windows/` | No-text seeds 20260920 and 20260921, seven-day and 24-hour notice activity references and time-shifted placebos, three activity arrays, 298 forecasts and month-first comparison results; see its README. |
| `dayfirst/` | Day-first forecasts of timestamp-dependent notice models, 12 supporting delayed forecasts, equivalence records and results under both readings; see its README. |
| `verify/` | Offline table verifier, recovery utility, expected values and validation summary. |

A seal is a saved list of forecast files and hashes frozen before scoring. A receipt records a computation and its input and output hashes. Each `.npy.npz` contains one losslessly stored member, `values.npy`. News matrices follow the news truth-panel row order. Feature columns and masks are in `configs/news/`; the bindings and frozen feature-storage code specify the inputs. Deposited evidence retains its source identities. Portable entry points use repository-relative locations.

## Models and paper items

| Code | Model |
|---|---|
| `N` | No-text model |
| `M_notice`, `M` | Notice and news activity references |
| `L14`, `L_Laz`, `L_chen_notice` | Event states, Overlap components and Archive embeddings (notices) |
| `R`, `T` | Rule parser and Word frequencies (notices) |
| `L_count`, `L_chen` | Fields and Embeddings (news) |
| `E_raw`, `W2_D` | Raw embeddings and Word frequencies (news) |
| `M_shift_notice`, `M_shift`, `P_shift` | Time-shifted activity and representation placebos |
| `NP`, `NPM`, `NPL`, `NPP` | LightGBM + P5MIN; activity and Event states additions; time-shifted placebo |
| `LEAR` | LEAR price-history benchmark |
| `M+_n`, `L14+`, `L_Laz+`, `L_chen_notice+` | Alternative activity reference and representation additions (Table D1) |
| `M0_n`, `M+0_n` | Descriptive references without the failed-prefix count |
| `P_content` | Activity-matched past-only reassignment; not evaluable with the available support |
| `s20260919/20/21` | Training seeds 20260919, 20260920 and 20260921 |

Table 5 uses 61 notice target days; its placebo comparisons use 38 complete days, 24 August–30 September. Table 6 uses 135 news issue days, 19 May–30 September. Table A1 gives HAC7 and Student-t sensitivities and bootstrap intervals. Table D1 covers seeds, mean forecasts, squared losses, excluded first days, alternative activity metadata, timestamp readings and availability delays. Table D3 covers P5MIN additions and news comparisons with LEAR. Design and extraction specifications supply Tables 2, B1 and C1.

## Rebuild Figures 2–4

```sh
python3 -B code/figures/reproduce_figures.py --dayfirst-python dayfirst-env/bin/python --output figures_rebuilt
```

Figure 2 shows the evaluation windows and daily context, Figure 3 the seed-averaged decomposition, and Figure 4 cumulative daily MAE differences. Figure 2 uses Matplotlib 3.9.1.post1 (`requirements.txt`); Figures 3–4 use Matplotlib 3.11.1 (`requirements-figures-dayfirst.txt`). Supply the second environment with `--dayfirst-python`. The wrapper runs the stages sequentially with the plotting functions and built-in geometry checks. Numerical inputs and Table 4 rounding are checked before plotting.

Figure 1 is a study-design diagram with no plotting code.

The third-party panel-alignment auditor is excluded and explicitly reports `SKIPPED`. Additional PDF checks are not run. Font availability and numerical-library versions can affect PDF bytes.

## Rebuild from raw data

LightGBM is 4.6.0. The MiniLM encoder is `sentence-transformers/all-MiniLM-L6-v2`, revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, with sentence-transformers 5.1.2. Complete input bindings are in `results/bindings/COMPLETE_INPUT_FREEZE.json`. Use a separate staging tree and `results/SOURCE_MAP.json` to resolve the frozen fitting and scoring scripts' locations.

1. Obtain the AEMO DISPATCHPRICE, regional dispatch-summary and P5MIN_REGIONSOLUTION inputs identified in the source catalogue. Build panels for the design periods using AEST (UTC+10) and the specified availability delays.
2. Rebuild notice features from `extraction/notices/` with the frozen feature adapters and prompt/schema, retaining terminal failures. Main estimates read evaluation-period notice timestamps day first; month-first inputs supply the sensitivity analysis. Training features are shared.
3. For news, `article_id` is the WattClarity post ID; obtain articles from that source. Saved clocks and sample ownership are in `extraction/news/articles.csv`. Retain failures and use the frozen vocabulary, encoder and training-only pruning/imputation rules.
4. Use the frozen execution adapter: daily expanding news fits on past-legal complete days; notice fits use 894,901 training rows and event weights, one fit per arm and seed. The P5MIN extension uses the eight-column forecast join. LEAR uses four calibration windows and the specified convergence and averaging rules.
5. Set forecasts before scoring, apply notice clipping and leave news unclipped. The scoring kernels and portable verifier reconstruct daily losses and reported comparisons.

LLM extraction cannot be replayed bit for bit because the client exposes no seed or pinned-revision setting. Saved inputs and numerical environments can affect refitting. Frozen forecasts and truth reproduce the reported results.

## Rights and exclusions

WattClarity article bodies, titles, summaries, quotations and extracted statements are excluded. The package contains article identifiers and derived numeric features. Individual annotation workbooks and identities are excluded; aggregate and anonymized paired coding results remain in the frozen export. Raw AEMO archives, encoder weights, Python environments, full notice feature matrices and fitted model binaries are excluded. The source catalogue and bindings identify these inputs. Credentials and extraction-client configuration are excluded.

Contains AEMO material © Australian Energy Market Operator Limited, used under AEMO's copyright permissions. AEMO material occurs in notice scope and labels, forecast truth, market features and raw-source identifiers. The projected notice scope removes e-mail-pattern occurrences and records its source hash.

Authored code uses MIT (`LICENSE`); authored replication data and documentation use CC BY 4.0 (`LICENSE-DATA`). Third-party material retains its rights and notices (`THIRD_PARTY_NOTICES.md`).
