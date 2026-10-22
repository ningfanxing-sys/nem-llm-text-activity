# Day-first evaluation-period notice timestamps

This folder contains forecasts of notice models whose evaluation features depend on timestamps inside the notices, computed with the day-first reading used for the main estimates. AEMO writes these DD/MM/YYYY timestamps day first. The month-first reading is the sensitivity analysis in Appendix B.3, Table D1 and Supplement B.3; its forecasts are in the official export inputs and `../seeds_windows/`.

Only Event states, Overlap components and Rule parser features differ in the evaluation window. Training features, availability times, activity counts and Archive embeddings inputs are shared. The same fitted models produce both forecast sets. NPL and the shifted notice placebo use the corresponding Event states inputs.

| Path | Contents |
|---|---|
| `predictions/` | 35 forecast panels for main, further-seed, windowed, alternative-reference and delayed notice comparisons, with hashes. |
| `supporting_forecasts/` | 12 supporting delayed alternative-reference panels, index and hashes. |
| `results/` | Main and sensitivity comparisons, daily losses, both bootstrap block lengths, seed decisions and figure inputs. Parsing comparisons pair the two readings. |
| `PREDICTIONS.json`, `MODEL_INVENTORY.csv` | Forecast/model identities and saved model population; 91 inventory rows describe 58 model instances. |
| `EQUIVALENCE.json`, `FEATURE_CHANGES.json` | 37 zero-difference equivalence checks and feature-row counts under both readings. |
| `OFFICIAL_SPECS.json`, `OFFICIAL_DAYFIRST.json` | Official comparison definitions and results under both readings. |
| `code/` | Feature, prediction and scoring scripts for the study layout. |
| `PROVENANCE.json`, `INPUT_RECORDS.json`, `DIFFERENCES.md` | Source digests, input locations and data delivery. |

The portable verifier joins every forecast to truth and common keys, reconstructs daily losses, averages forecasts before mean-forecast losses, and applies the frozen DM, Holm and bootstrap functions. It checks printed main estimates and the month-first numbers and bounds in the sensitivity analysis. Figures 3–4 read this folder's checked results.

From the repository root, run:

```sh
python3 -B verify/verify_tables.py
(cd dayfirst/predictions && shasum -a 256 -c SHA256SUMS)
(cd dayfirst/supporting_forecasts && shasum -a 256 -c SHA256SUMS)
```

Packaged forecast paths are repository-relative. Model and omitted-feature paths identify study inputs; source digests remain recorded. Full feature matrices, embeddings and saved models are excluded. Prediction scripts require those inputs in a separate staging tree; verification and figure reproduction use included forecasts and results without refitting.
