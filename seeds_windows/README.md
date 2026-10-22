# Seeds and windowed notice activity references

This folder provides the no-text model at seeds 20260920 and 20260921 for both tasks, notice activity references using seven-day and 24-hour windows, and their time-shifted placebos. Forecasts are averaged across three seeds before losses are computed.

The official export and this folder's results use the month-first reading of evaluation-period notice timestamps. `../dayfirst/` supplies the timestamp-dependent notice forecasts and results with the day-first reading used for the main estimates. The same fitted models produce both forecast sets. News results, activity counts and Archive embeddings inputs are shared.

| Path | Contents |
|---|---|
| `forecasts/` | 298 forecast files: two notice no-text panels, 270 daily news no-text panels, 24 windowed-reference panels and two seven-day placebo panels. Index and hashes bind every file. |
| `features/` | Seven-day, 24-hour and shifted seven-day activity arrays. |
| `results/` | Daily losses, paired comparisons, reversals, Holm decisions and fitting resources. |
| `code/` | Fitting, activity construction, scoring and reporting scripts for the study layout. |
| `EQUIVALENCE_GATE.json`, `FEATURE_CHECKS.json` | Baseline prediction equivalence, feature identities, shapes and path bindings. |
| `DECISIONS.json`, `FINAL_CHECKS.json` | Analysis decisions and output checks. |
| `DIFFERENCES.md`, `PROVENANCE.json`, `INPUT_RECORDS.json` | Data delivery, source digests and input locations. |

Table 4 and Figure 3 use seed-averaged activity, representation and net steps. Table D2 gives activity steps and sign reversals by seed. Supplement D.1 and Tables S1–S2 give intervals and seed details. The main notice cells use `../dayfirst/results/`; this folder's month-first comparisons support the timestamp sensitivity analysis.

Run `python3 -B verify/verify_tables.py` from the repository root. It reconstructs every daily MAE, comparison, seven-day interval and decision from forecasts, common keys and truth using the frozen DM and bootstrap functions. It verifies the main printed cells through the day-first results.

The scripts require the original study layout identified in `PROVENANCE.json`, separately reconstructed full feature matrices, training inputs and frozen execution dependencies. `run_posthoc.py` changes only the additional no-text seeds or specified activity columns; `window_features.py` builds activity arrays; `score_posthoc.py` scores forecasts; `make_report.py` formats results. Use a separate staging tree to resolve study-relative locations.
