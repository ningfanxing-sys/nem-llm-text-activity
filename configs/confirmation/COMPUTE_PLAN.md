# CONF fitting budget and deterministic scheduling

Design-only: no CONF fit, scoring run, window feature build or outcome read occurred in preparation. Counts below are arithmetic from the fixed design; runtime figures are identified historical metadata receipts or explicitly labelled scenarios, not measured 2026 performance.

## Model accounting

News fits pool three regions and 24 horizons in one LightGBM per arm/origin, daily expanding past-only refits. The primary is seed20260919. The 2025 report-only validation uses nine fixed models fitted at 2025-01-01 from label-legal 2021-10..2024-12 history and predicts the full year without updating; nothing is selected from its outcomes. It is not 365 new refits per arm. Notices retains RF2's pooled learner over five regions and six horizons, once per arm/seed on the frozen C training bank; it is **not** 30 separate fits per arm. Unit weights apply to the confirmation window, while the inherited training bank preserves its original replay/ordinary weights 1/50.

| Fixed stage (execution priority) | Fits/jobs | Model-estimation accounting |
| --- | ---: | --- |
| Primary notices: N, M_notice, L14, L_Laz, L_chen_notice | 5 | pooled LightGBM fits |
| Primary news: N, M, L_count, L_chen, 214 daily origins | 856 | 4×214 pooled LightGBM fits |
| Report-only 2025 validation, nine base news arms | 9 | fixed LightGBM fits |
| Secondary notices: M_shift_notice, R, T, P_shift, P_content, NP, NPL, NPP | 8 | pooled LightGBM fits |
| Secondary news: M_shift, E_raw, W_Bai, P_shift, P_content | 1,070 | 5×214 pooled LightGBM fits |
| LEAR full four-window benchmark | 214 daily jobs | 214×3regions×24hours×4windows = 61,632 LARS-AIC/coordinate-descent **pairs**, 123,264 estimator fits |
| Primary notice extra seeds20/21: M_notice, L14, L_Laz, L_chen_notice | 8 | shared activity baseline included |
| Primary news extra seeds20/21: M, L_count, L_chen | 1,284 | 3×2×214 pooled fits; shared M included |
| 24-hour window sensitivity: M, L_count, L_chen | 642 | 3×214 fits; N reused unchanged |
| First-L sensitivity notices: L_chen_notice | 1 | pooled fit |
| First-L sensitivity news: L_chen, E_raw | 428 | 2×214 fits |
| **Maximum registered LightGBM accounting** | **4,311** | **4,289 news +22 notices** |

The nominal 61 target days produce no additional notice refits. Dropping the first seven target days, clipping counts, daily/monthly coverage and connected-event tables require no new fits. The LEAR fit pairs cannot be conflated with pooled LightGBM fits. All four windows (56/84/1092/1456 days) form one indivisible registered benchmark; if it cannot complete, report it unavailable with the resource receipt rather than report a selected-window LEAR.

## Measured historical anchors

Only runtime, rows, features and RSS metadata were inspected from these sources; no forecast values or scores were read.

| Metadata source | Historical measured item |
| --- | --- |
| NEWSRUN/newsrun2_dayahead_bank/RESOURCE9_COUNTED_PILOT.json | P__2025-07-31, 100,368 training rows, 906 features, **43.488448833 s**, worker peak2,198,831,104bytes; task-tree peak2,477,244,416bytes |
| NEWSRUN/newsrun2_dayahead_bank/RESOURCE8_COUNTED_PILOT.json | P_quote__2025-07-30, 100,296 rows, 906 features, **44.202065958 s**, worker peak1,717,714,944bytes |
| NEWSRUN/newsrun2_dayahead_bank/FIT_SUMMARY.json | v9 invocation **16,326.232838 s =4.535 h**, max_workers4; 2,562 total completed/reused fits. This invocation resumed earlier work, so 2,562/duration is **not** a valid throughput estimate. |
| RF2/resource/final_C_L_20260919.log.json | Whole historical child job **30.984190041 s**, parent+child RSS957,546,496bytes |
| RF2/resource/final_C_P_20260919.log.json | Whole historical child job **32.073859750 s**, parent+child RSS1,046,528,000bytes |

NEWSRUN/EXECUTION_RESOURCE_AMENDMENT_9.md documents four performance cores and the seven-arm barrier's two rounds with four workers versus three rounds with three workers. Its v9 scheduler is the structural template. CONF uses exactly four **news** workers, single-threaded fits. Notice parameters preserve RF2 n_jobs=6; notice fits are serial and never overlap the news pool, avoiding an unregistered learner-thread change. LEAR daily jobs are serial in this skeleton; parallel hour subjobs require a separately documented resource-only implementation receipt and must preserve deterministic fits.

The historical v9 pilot exceeded 2GiB worker RSS, so it does not prove compliance for CONF's 1.5–2GiB job goal or four-worker feasibility with 384 extra encoder dimensions. CONF requires bounded/memmapped numeric blocks, float32 model matrices, one active origin, lazy labels, measured task-tree admission and counted first fits. A job reaching 2GiB or a task tree reaching6.6GiB stops with a resource failure receipt; no statistical simplification follows. At6.0GiB the current news origin throttles to one worker, as in v9. Every launch requires current measured RSS plus projected incoming-worker lifetime RSS below6.6GiB. At each origin the adapter updates the projected peak from previous counted receipts, matrix-shape growth and an8% reserve; model fitting remains unchanged.

## Hours: explicit planning scenarios

There is no measured CONF-window runtime, no measured384-dimensional-arm runtime and no measured adapted-LEAR throughput. The following are planning scenarios using the historical43.488448833-second news pilot **without claiming transfer**. Per-origin barriers cost one round for four main arms, two rounds for five secondary arms, two rounds for six extra-seed fits, one round for three24h fits and one round for twofirst-L fits. The nine2025 validation fits need three rounds. Thus all4289 news fits need **1,501 rounds** (214×7+3), not4289/4 rounds.

| Assumed seconds per news round | Primary856 fits | Main+secondary+validation (645 rounds) | All4289 news fits (1501 rounds) |
| --- | ---: | ---: | ---: |
| Historical-pilot proxy43.488448833s | 2.585h | 7.792h | 18.132h |
| Explicit2× proxy86.976897666s | 5.170h | 15.583h | 36.265h |

These scenarios exclude preparation/embedding/extraction, notices and LEAR. Scaling22 notice jobs by the32.073859750-second historical job gives **0.196h**, also only a proxy, because new representations differ. The complete LEAR benchmark has61,632pairs: at an **assumed**, unmeasured0.1/0.5/1.0seconds per pair, fitting is1.712/8.560/17.120h, respectively. This arithmetic shows why LEAR cannot be assumed free and why the complete registered maximum may exceed24h. No run has been dropped during this design task.

## Hard budget and fixed whole-run drop rule

The budget is about **24hours of fitting wall time**, including counted pilots and retained failed/abandoned fit attempts, across all fitting invocations; resumes do not reset it. Source parsing, extraction and embedding are separately accounted and may not conceal fitting time. Work follows the table's fixed order, primary then secondary then sensitivities. Before each stage, estimate completion using runtime/RSS/shape **metadata only**, never errors, prices, effects, p values, clipping counts or any diagnostic. Use the largest counted relevant per-job duration×1.25 safety reserve and the registered barrier-round count; unknown optional runtime is not assumed zero.

One counted first LEAR daily job may establish its duration; charge its time to the total. Its future conservative daily estimate is max(1.25×the measured complete288-pair pilot duration,288×0.5seconds). The0.5seconds/pair floor is a fixed **unmeasured project planning choice**, not a performance fact; it prevents unknown LEAR cost being treated as negligible. Admit the remaining LEAR benchmark only if its whole214-day/four-window completion estimate fits the remaining budget. Otherwise retain its pilot receipt and mark the entire benchmark `UNAVAILABLE_RESOURCE_BUDGET`, without scoring the partial predictions. The same completeness rule applies to every optional stage. An unavailable W_Bai due to a frozen source/preprocessing prerequisite is reported unavailable, not replaced with an improvised vocabulary.

At each stage, if its conservative completion estimate exceeds the remaining budget, drop that **entire** stage and continue in fixed order to a later stage only if the later whole stage fits. This can retain a cheap later sensitivity after an expensive unavailable benchmark; it never promotes that sensitivity to primary. Expected budget omissions, in fixed last-priority order, are first-L news, first-L notices,24h, extra-seed news, extra-seed notices, then unavailable expensive LEAR/secondary stages as dictated by the forward admission rule. Do not choose omissions from results. Mandatory primary stages cannot be dropped: if they cannot finish, stop and report confirmation incomplete.

No new fit launches at the24h deadline; already running jobs drain and write receipts, causing at most one currently admitted wave's documented small overrun. A stage interrupted by deadline/memory failure is incomplete and cannot produce a window score. No partial214-day news arm, shortened61-day notice result, subset ofLEAR windows, different seed or adjusted horizon is substituted. Completing a stage produces sealed predictions; all scheduled stages finish or receive explicit unavailable receipts before any outcome scoring task. Resource-only continuation beyond this budget requires a separate author instruction and never alters the frozen statistical design.

## Implementation and receipts

`code/scheduler.py` supplies the v9-style four-worker origin barrier, serial notice/LEAR paths, fixed plan/counts, metadata-only admission calculation, memory throttle/stop and a24h deadline. It uses spawn with max_tasks_per_child=1: each news fit gets a fresh worker, a resource-only adaptation of v9's bounded persistent pool. Startup cost is charged to measured fitting wall time. Its CLI prints the plan only and exposes no fitting command. Future execution must supply a frozen fitter adapter, exact parameter dictionaries, source/input and feature hashes, label-legal cutoff updates and receipt writer, and load an ExecutionPermit through code/guard.py; no legacy module is imported here because legacy imports may read data. Both public fitting paths enforce that permit before launching callbacks. Save perfit origin, seed, arm, variant, eligible rows, feature order, train cutoff, training-label clock maximum, runtime, peak RSS, model/prediction hashes and input manifest hashes. Reuse only exact unchanged N matrices/models under hash and prediction-equality checks; otherwise count/refit them. Do not call scoring from a scheduler.

Traceability: counts are products of author-fixed214days/windows/arms and the registered scopes in PROTOCOL_CONF.md; pooled notice accounting and6threads come from RF2/runner.py → autopilot/run_window.py → sibling notice_window_llm_increment_20260924/run_nw.py. Parameter identity is required against RF2's frozen design; no larger/smaller learner or optimization is selected to meet time.
