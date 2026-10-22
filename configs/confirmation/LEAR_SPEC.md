# Registered LEAR benchmark

This is a numeric benchmark for the news day-ahead task. It is secondary and is
not a text arm. It has no role in feature choice, stopping a primary family, or
changing any reading rule. No calibration, prediction or scoring was performed
in CONF. The separate execution task must verify the complete input freeze
before invoking the guarded `code/lear.py` functions.

## Published template and pinned implementation

Lago, Marcjasz, De Schutter and Weron, *Applied Energy* 293 (2021), 116983,
DOI [10.1016/j.apenergy.2021.116983](https://doi.org/10.1016/j.apenergy.2021.116983),
printed pp.7–9 (§4.2 and Eq.2–4), specifies median/MAD standardization followed
by asinh, 24 separate hourly LASSO models, daily recalibration, and LARS
selection of the L1 penalty by in-sample AIC followed by coordinate-descent
LASSO at that penalty. Printed pp.7 and 14 (§5.12 and §6.1.1) specify four
calibration lengths: **56, 84, 1092 and 1456 days**, with their forecasts combined
by an unweighted arithmetic mean. Printed p.13 (§5.6) motivates daily refitting.
The downloaded published PDF is `evidence/lago2021_published.pdf`, from
[the author's site](https://jesuslago.com/wp-content/uploads/1-s2.0-S0306261921004529-main-1.pdf).

The authors' implementation at GitHub revision
`47d6e0629f65ebd19d3c12cb5689dbad0c2ea078` was checked, without running it:
[`_lear.py`](https://github.com/jeslago/epftoolbox/blob/47d6e0629f65ebd19d3c12cb5689dbad0c2ea078/epftoolbox/models/_lear.py)
and [`_wrangling.py`](https://github.com/jeslago/epftoolbox/blob/47d6e0629f65ebd19d3c12cb5689dbad0c2ea078/epftoolbox/data/_wrangling.py).
Local snapshots and their hashes enter the design freeze. Inputs and target
outputs are transformed column by column; seven weekday indicators are left
untransformed. Both LARS and coordinate descent use max_iter=2500. Coordinate
descent uses fit_intercept=True, tol=1e-4 and cyclic selection, without tuning.

The installed scikit-learn is 1.8.0. Its `LassoLarsIC` default OLS noise estimator
rejects the short 56/84-day designs when predictor count exceeds sample count.
To avoid a silent method change, this registration pins the **2021-era AIC
formula**, verified against official [scikit-learn 0.24.2 source](https://github.com/scikit-learn/scikit-learn/blob/0.24.2/sklearn/linear_model/_least_angle.py):

`AIC(alpha) = n * mean(residual(alpha)^2) / (var(centered_y) + eps64) + 2 * df(alpha)`.

The centered LARS input is L2-normalized column by column, corresponding to that
version's `normalize=True`; zero-norm columns use divisor one. The degrees of
freedom count coefficients with absolute value above float64 epsilon. The first
minimum in path order determines alpha. That alpha enters coordinate-descent
Lasso on the asinh inputs, following the official two-stage implementation.
No cross-validation, BIC, alternate solver, or alpha fallback is permitted.
This compatibility port is a fixed implementation choice, not a new top-venue
forecasting prescription. Its local source snapshot is
`evidence/sklearn0242_least_angle.py`.

## Issue-legal adaptation

Use NSW1, QLD1 and TAS1, each with 24 hourly forecasts at 00:00 fixed AEST, on
every issue date 2026-03-01..2026-09-30. Labels and paired evaluation keys equal
the NEWSD/DAPANEL news task. This forecast horizon does not imply a NEM cleared
day-ahead market. The published benchmark's regional hourly formulation is
preserved; pooled LightGBM text arms are an explicitly different learner.

Lago Eq.3 includes price profiles for days d−1, d−2, d−3 and d−7, six 24-hour
profiles of two exogenous day-ahead forecast variables at d/d−1/d−7, and seven
weekday indicators (247 features). This project has **no issue-legal day-d
exogenous forecast profiles**. Omit all six exogenous forecast blocks, leaving
96 conventional lagged-hour price values plus seven weekday indicators. Do not
substitute realized demand, realized weather, P5MIN or hypothetical forecasts.
Report the benchmark as **LEAR, issue-legal price-only adaptation**. This
information-set deviation has no exact top-venue template.

Every lagged price profile uses the ordinary 12-interval hourly price definition,
but only if all constituent values are finite and their saved-source availability
is at or before that row's issue. For a price interval, availability is
max(interval end+5 minutes, LASTCHANGED); unknown clock is unavailable. The final
hour of d−1 can therefore be unavailable at midnight. Do not use a future price
or retrospectively backfill it. Fill unavailable predictor values with the
corresponding feature's median from the **current, past-only calibration set**,
and append one missingness indicator per price feature (96 additional columns,
**199 total inputs**). All-missing calibration columns use fixed zero fill and
are recorded. This is an issue-legality adaptation, not Lago's exact complete
price-profile design.

For each origin and region, end the calibration window at the latest day for
which all 24 recorded label clocks are strictly before the issue. It will often
end at d−2 under the midnight latency contract. Take exactly the preceding
56/84/1092/1456 **consecutive calendar days**, including that endpoint. An
internally missing or nonfinite target day makes the full benchmark unavailable;
do not silently replace it by an older day, shorten a window or average fewer
than four forecasts. Prior 2026 labels may enter later historical refits only
after they become label-legal, under the separately authorized execution task.
No 2026 value is read during this design.

Fit imputation, input scaling and target scaling anew on that calibration set;
these are LEAR model-estimation steps required by its rolling template. They are
not Bai vocabulary/Granger selection, which remains frozen on 2021-10..2024-12.
Scale = median(abs(x−median(x))) / 0.6744897501960817; transform = asinh of
the centered/scaled input and inverse = sinh times scale plus median. A zero MAD
uses fixed scale one and is counted. Weekday and missingness indicators stay
untransformed. No target clipping/transform fallback is allowed. Nonconvergence
or nonfinite inverse-transform predictions makes the registered benchmark
unavailable, with all failures reported; it cannot choose a favorable substitute.

## Fits and execution boundary

The 214 confirmation issues require 214×3×24×4 = **61,632 LARS/AIC + coordinate
descent fit pairs** (123,264 estimator stages), each deterministic without a
seed sensitivity. One region/window job runs its 24 hours serially; at most four
jobs share an origin, and the origin barrier completes before the next day.
The largest 1456×199 float64 input is about 2.32 MB; no 24×4 full-window copies
are kept concurrently. Record each window's cutoff, input/target scaling hashes,
alpha, path size, convergence, model/prediction hash, runtime and peak RSS. Equal
window weights are fixed at 1/4 after inverse transformation into price units.

LEAR is one all-or-unavailable registered benchmark. Its run can be omitted as
a whole under the pre-frozen compute-tier deadline in the main protocol; that
does not authorize dropping an individual window, date, region or hour. No
additional 2025 LEAR rerun is required by CONF: 2025 is report-only, using already
seen validation evidence, with no selection. An optional later validation
reproduction would be separately authorized and would not alter this design.
