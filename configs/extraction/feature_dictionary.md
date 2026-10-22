Features for "Do LLM-derived text features improve electricity price forecasts beyond document activity?"  
All times are AEST (`Australia/Brisbane`).  
The extraction prompts and schemas are provided in the same folder.

### Common notation and availability

- \(t\): forecast issue time, using AEST (`Australia/Brisbane`).
- \(u\): notice target timestamp, the end of the five-minute dispatch interval.
- **Local/foreign:** the record's region equals/differs from the forecast region.
- **Notice prefix:** unique saved-source notices with `available_utc<=t`, ordered by availability then notice ID. It is an **observed saved-source prefix**, not a certified census of every issued notice.
- **News support:** unique saved article versions with `publication_utc<=t` and `saved_version_available_utc in (t-72h,t]`, ordered by availability then article ID. Availability is `max(publication_utc,modified_utc)+5 minutes`.
- Every content model includes its task's activity-reference columns as well as the shared no-text numerical inputs.
- The dictionary gives the columns before training-period constant/all-missing pruning. Pruning is set once from the training data; it is not selected again on evaluation data.

Notice features consume the stored `available_time_utc` and check it against canonical prefix clocks. In the evaluation window, the underlying timestamp is the **Creation Date** field in the header of the saved notice text, with five minutes added and upward rounding to the five-minute grid; in the training sample, it is the official clock (LASTCHANGED or ISSUE_DATETIME) plus five minutes, rounded up in the same way.

## Notice

### Activity reference: three columns

| Column | One-line definition and source fields | Timing |
|---|---|---|
| `notice_prefix_count` | Number of distinct `notice_id` values in the available saved-source prefix. | Entire prefix with `available_utc<=t`. |
| `notice_arrivals_6h` | Number of distinct `notice_id` values newly available in the preceding six hours. | `available_utc in (t-6h,t]`. |
| `notice_failed_prefix_count` | Number of available notices whose `extraction_status` is not `SUCCESS`. | Entire available prefix; failed notices remain in all content models. |

### Windowed activity reference: three columns

Used in the windowed comparisons (Section 6.1 and Supplement D.1). The seven-day counts W7 and F7 take the places of `notice_prefix_count` and `notice_failed_prefix_count`, and `notice_arrivals_6h` is unchanged; the sensitivity version uses the 24-hour counts W24 and F24. The representation columns are unchanged.

| Column | One-line definition and source fields | Timing |
|---|---|---|
| W7 (W24) | Number of distinct `notice_id` values newly available in the preceding seven days (24 hours). | `available_utc in (t-7d,t]` (`(t-24h,t]`). |
| `notice_arrivals_6h` | As in the activity reference. | `available_utc in (t-6h,t]`. |
| F7 (F24) | Number of those notices whose `extraction_status` is not `SUCCESS`. | Same window as W7 (W24). |

### Event states: 14 columns

Event states uses issue-resolved records, bridged from extraction fields: `impact_windows.region`, `event_family`, `start_text`, `end_text`, `interval_status`, lifecycle, and explicitly bound quantities. Shared source title/type and relation metadata come from the saved notices; missing LLM semantics are not filled from rule-parser guesses.

For active-state columns, records must be available by \(t\), feature eligible, and not cancelled. Bounded intervals satisfy `start<=u<end`. Explicit open intervals have a strict 48-hour issue-freshness limit. Issue-known prospective closures apply at their effective target time. Counts are of resolved normalized records, unlike the distinct-notice counts in Overlap components.

| Column | One-line definition and source fields | Timing |
|---|---|---|
| `nw_res_local` | Count of active local records with normalized `kind=RESERVE`, from `event_family` and region. | Active-state rule above. |
| `nw_res_foreign` | Count of active RESERVE records in the other regions. | Active-state rule above. |
| `nw_con_local` | Count of active local `kind=CONSTRAINT` records. | Active-state rule above. |
| `nw_con_foreign` | Count of active CONSTRAINT records in the other regions. | Active-state rule above. |
| `nw_int_local` | Count of active local `kind=INTERVENTION` records. | Active-state rule above. |
| `nw_out_local` | Count of active local `kind=OUTAGE` records, including the return-to-service mapping. | Active-state rule above. |
| `nw_out_foreign` | Count of active OUTAGE records in the other regions. | Active-state rule above. |
| `nw_any_local` | Count of all active local eligible records, including `OTHER`. | Active-state rule above. |
| `nw_res_deficit_mw_local` | Maximum finite `req_mw-avail_mw` among active local RESERVE records; negative deficits are retained; absent finite pairs give NaN. | Active-state rule; quantities must be source-supported and bound. |
| `nw_res_min_avail_mw_local` | Minimum finite `avail_mw` among active local RESERVE records; absent values give NaN. | Active-state rule. |
| `nw_minutes_since_start_local` | Minutes from the earliest start among active local records to \(u\); no active local record gives NaN. | Uses target time, not elapsed time since issue. |
| `nw_minutes_to_end_local` | Minutes from \(u\) to the latest bounded end among active local records; NaN if any relevant open interval is active or no end exists. | Active-state rule. |
| `nw_new_local_6h` | Count of distinct eligible notice/region groups that became available within six hours with `cancel=false`; this includes eligible updates, not only lifecycle `NEW`. | `available_utc in (t-6h,t]`; no target-overlap requirement. |
| `nw_cancel_local_6h` | Count of distinct eligible notice/region groups that became available within six hours with `cancel=true`. | `available_utc in (t-6h,t]`; no target-overlap requirement. |

### Overlap components: eight columns

Records are resolved using only issue-visible updates and closures. They must have the forecast region, availability by \(t\), feature eligibility, a supported start, and overlap delivery interval **`[u-5min,u)`**: `event_start<u` and `event_end>u-5min`. Explicit open records also require issue freshness under 48 hours. Each count deduplicates `notice_id` within that component.

| Column | One-line definition and source fields |
|---|---|
| `laz_UMM` | Distinct overlapping eligible source notices, including supported-interval `OTHER`/unknown-class messages. |
| `laz_Failure` | Distinct overlapping notices with explicit `event_class=FAILURE`. |
| `laz_NuclearFailure` | Failure count with explicit `fuel_type=NUCLEAR`. |
| `laz_HydroFailure` | Failure count with explicit `fuel_type=HYDRO`. |
| `laz_CoalFailure` | Failure count with explicit `fuel_type=COAL`. |
| `laz_failure_coal_gas_oil` | Failure count with explicit fuel in `{COAL,GAS,OIL}`. |
| `laz_failure_nuclear_hydro` | Failure count with explicit fuel in `{NUCLEAR,HYDRO}`. |
| `laz_SizeOfOutage_MW` | Sum of unique, explicitly bound finite nonnegative LOSS quantities in MW across independent failures; NaN if a relevant failure lacks reliable event/asset identity or usable binding; no failures gives zero. |

MW source fields are `quantities.window_id`, `asset_id`, `binding_status`, `binding_reason`, `role`, `unit`, and `value_text`. A qualifying LOSS requires explicit source-scope binding and matching non-unknown asset identity. Fuel is not inferred from asset names. Updates of the same event/asset do not duplicate capacity.

### Archive embeddings: construction

The source is the **entire available notice prefix**, ordered by availability and notice ID. Within a notice, `nrx_label.impact_windows` retain schema order. Each window serializes these attributes, in order:

```text
impact_timeframe=value
root_cause=value
affected_infrastructure=value
region=value
energy_resource=value
operational_indicators=value
```

Attribute values come from `impact_windows[].attributes[name]`, taking the nested `value` where applicable. Fields are separated by one newline; windows/notices contribute blocks separated by two newlines. Failed extraction or a notice with no windows contributes all six literal `UNKNOWN` fields. No impact tier is invented for notices.

The whole serialized prefix is tokenized before partitioning. Encoder: `sentence-transformers/all-MiniLM-L6-v2`, immutable revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`; 384-dimensional CPU float32 output. Contiguous non-overlapping blocks contain at most 254 content tokens, then receive two special tokens. Each block uses attention-masked mean-token pooling and L2 normalization; all block vectors receive equal weight, followed by final L2 normalization. An empty corpus gives a 384-zero vector. The shorter final block has equal weight.

### Rule parser: columns

Rule parser has the same **14 column names and numerical definitions** listed for Event states:

```text
nw_res_local, nw_res_foreign, nw_con_local, nw_con_foreign,
nw_int_local, nw_out_local, nw_out_foreign, nw_any_local,
nw_res_deficit_mw_local, nw_res_min_avail_mw_local,
nw_minutes_since_start_local, nw_minutes_to_end_local,
nw_new_local_6h, nw_cancel_local_6h
```

Its semantic records are parsed from the source `title`, `body`/`text`, `notice_type`, `available_utc`, and `anchor_local`. Malformed partial-year dates are rejected, and historical outages explicitly reported as completed, recovered or cancelled are closed by that report. The projection is the **point-target** projection, with the same prefix and state timing as Event states. Rule parser also includes all three Activity-reference columns.

### Word frequencies: vocabulary, selection, and counts

| Column | One-line definition | Source and timing |
|---|---|---|
| `tfn2_title_lack` | Raw count of token `lack`. | Notice titles available in `(t-24h,t]`. |
| `tfn2_title_level` | Raw count of token `level`. | Same. |
| `tfn2_title_lor1` | Raw count of token `lor1`. | Same. |
| `tfn2_title_reserve` | Raw count of token `reserve`. | Same. |
| `tfn2_title_stpasa` | Raw count of token `stpasa`. | Same. |

There are **no retained body-word columns**. The vocabulary is selected on the training sample by the rules below.

Tokenization lowercases text, uses `[a-z0-9]+`, removes tokens shorter than three characters, pure numbers, and the pinned English stopwords. Selection uses historical training only: title corpus occurrences >=200, body >=5000; ADF with constant and AIC lag selection, differencing once when *p*>=.05; bilateral Granger tests at specified lag 30; retain only forward *p*<.05 and reverse *p*>=.05. The saved selection records 91 title candidates, 23 body candidates, and five selected title words. Its source-availability span is `2021-09-29 15:20:00+00:00` through `2023-12-31 13:15:00+00:00`.

These are raw frequencies, without TF-IDF, polarity weights, or extra word lags. The model also includes the three Activity-reference columns.

### P5MIN columns: eight columns

For a notice issue \(t\) and target \(u\), the main operator forecast comes from run **\(t-5\) minutes**. A record is used only if its availability `max(RUN_DATETIME+5min,LASTCHANGED)<=t`; the source run must also satisfy `run+5min<=t`. Intervention records are excluded.

| Column | One-line definition and source fields |
|---|---|
| `p5_rrp` | `RRP` for target \(u\) from available run \(t-5min\). |
| `p5_gap` | `p5_rrp-legal_anchor`, using float64 subtraction before float32 output. |
| `p5_rev` | Target-\(u\) RRP from run \(t-5min\) minus its available value from run \(t-10min\). |
| `p5_max_run` | Maximum available finite RRP across the 12 stored target slots of run \(t-5min\). |
| `p5_demand` | `TOTALDEMAND` for \(u\) from available run \(t-5min\). |
| `p5_margin` | `AVAILABLEGENERATION-TOTALDEMAND` for that run and target. |
| `p5_netinterchange` | `NETINTERCHANGE` for that run and target. |
| `p5_nbr_rrp` | Mean finite available target-\(u\) RRP from run \(t-5min\) across neighboring regions. |

Neighbors: NSW1->QLD1,VIC1; QLD1->NSW1; SA1->VIC1; TAS1->VIC1; VIC1->NSW1,SA1,TAS1. Missing required records yield NaN. Training uses the P5MIN runs of October 2021-December 2023.

## News

### Activity reference: two columns

| Column | One-line definition and source fields | Timing |
|---|---|---|
| `article_count` | Count of available unique saved article versions, identified by `article_id`. | Common news support `(t-72h,t]`, publication<=\(t\). |
| `extraction_failed_count` | Count whose `extraction_status` is not `SUCCESS`. | Same support; failed articles remain in all content models. |

### Fields: 34 columns

All columns use the common news support. Tier, event-type, and region counts contribute **at most once per article per category**. Statement-kind and target-day counts count statements. Failed extraction increments only `tier_Unknown` in this 34-column block and invents no statements.

| Column | One-line definition and source fields |
|---|---|
| `tier_c1` | Count of articles with `impact_level=c1`: major market-disruptive source-text category. |
| `tier_c2` | Count with `impact_level=c2`: operational-signal category. |
| `tier_c3` | Count with `impact_level=c3`: policy, regulation, or residential-survey category. |
| `tier_Unknown` | Count with `impact_level=Unknown`, plus available failed extractions. |
| `event_GENERATOR_OUTAGE` | Count of articles with at least one statement classified `event_type=GENERATOR_OUTAGE`. |
| `event_FUEL_SHORTAGE` | Count with at least one `FUEL_SHORTAGE` statement. |
| `event_EXTREME_WEATHER` | Count with at least one `EXTREME_WEATHER` statement. |
| `event_MAINTENANCE` | Count with at least one `MAINTENANCE` statement. |
| `event_SUPPLY_CONSTRAINT` | Count with at least one `SUPPLY_CONSTRAINT` statement. |
| `event_ABNORMAL_MARKET_CONDITION` | Count with at least one `ABNORMAL_MARKET_CONDITION` statement. |
| `event_NETWORK` | Count with at least one `NETWORK` statement. |
| `event_DEMAND` | Count with at least one `DEMAND` statement. |
| `event_RENEWABLE` | Count with at least one `RENEWABLE` statement. |
| `event_RESERVE` | Count with at least one `RESERVE` statement. |
| `event_POLICY` | Count with at least one `POLICY` statement. |
| `event_REGULATION` | Count with at least one `REGULATION` statement. |
| `event_RESIDENTIAL_SURVEY` | Count with at least one `RESIDENTIAL_SURVEY` statement. |
| `event_OTHER` | Count with at least one `OTHER` statement. |
| `event_Unknown` | Count with at least one explicit `Unknown` event-type statement. |
| `kind_FACT` | Number of statements with `kind=FACT`. |
| `kind_FORECAST` | Number of statements with `kind=FORECAST`. |
| `kind_ANALYSIS` | Number of statements with `kind=ANALYSIS`. |
| `kind_UNKNOWN` | Number of statements with `kind=UNKNOWN`. |
| `region_NSW1` | Count of articles whose union of statement `regions` includes NSW1. |
| `region_QLD1` | Count whose union includes QLD1. |
| `region_SA1` | Count whose union includes SA1. |
| `region_TAS1` | Count whose union includes TAS1. |
| `region_VIC1` | Count whose union includes VIC1. |
| `forecast_target_day` | Number of FORECAST statements whose supported parsed `event_time_text` interval includes the target day, endpoints inclusive. |
| `forecast_target_day_NSW1` | Target-day FORECAST statement count naming NSW1 in `regions`. |
| `forecast_target_day_QLD1` | Target-day FORECAST statement count naming QLD1. |
| `forecast_target_day_SA1` | Target-day FORECAST statement count naming SA1. |
| `forecast_target_day_TAS1` | Target-day FORECAST statement count naming TAS1. |
| `forecast_target_day_VIC1` | Target-day FORECAST statement count naming VIC1. |

The source fields are article-level `impact_level` and `statements_json[].{event_type,kind,regions,event_time_text}`. Target-day membership uses the pinned `absolute_interval` parser; unsupported or unresolved date text contributes no target-day count. Tiers are textual classifications, not observed price effects, and receive no ordinal weights.

### Embeddings: construction

Use the common available article set and order. Each article serializes:

```text
impact_level=value
impact_timeframe=value
root_cause=value
affected_infrastructure=value
region=value
energy_resource=value
operational_indicators=value
```

`impact_level` comes from the article; the six remaining fields come from `attributes_json`. Fields are separated by newlines and articles by two newlines. A failed article contributes all seven literal `UNKNOWN` fields. Statements and evidence arrays are not serialized into this representation.

Concatenate the entire available corpus before tokenization, then use the same frozen MiniLM revision, 254-token chunking, pooling, normalization, and 384-dimensional output described for Archive embeddings. The model includes both news Activity-reference columns.

### Raw embeddings: construction

Use the same available IDs, versions, and article order as news Embeddings. Serialize each raw `title`, then two newlines, then raw `body`; separate articles by two newlines. Failed-extraction articles retain their raw text. Apply the same frozen MiniLM and whole-corpus chunking construction. The model includes both news Activity-reference columns.

### Word frequencies

Each column has the form **`bai_title_<word>`** or **`bai_body_<word>`** and is the raw count of that word in the corresponding field across the common available 72-hour news support. The two lists below enumerate every retained word column.

**57 title words:**

```text
0mw, 16th, 17th, 19th, 23rd, actual, almost, also, april, bidding,
blast, broken, contingency, crisis, early, end, ever, farm, five,
forecasts, glitch, going, grid, hill, hydro, initial, level, longer,
looking, lower, lowest, minimum, minutes, monthly, msl1, near, oct,
october, one, overnight, past, peak, preliminary, presentation,
range, rare, recapping, regions, running, sat, saturday, side,
storm, systems, tasmania, tight, weeks
```

**81 body words:**

```text
17th, 25th, almost, average, better, capacity, chart, compared,
constraints, contract, copy, cost, costs, could, curtailment, daily,
dropped, due, even, extreme, factor, far, farms, find, friday, get,
good, grid, however, important, increasing, investment, like,
likely, load, loss, lower, lowest, make, many, minimum, month,
negative, nemreview, network, occurred, october, operational,
outcomes, output, people, point, portfolio, possible, project,
projects, quarter, recent, regional, renewable, saturday, saw,
scale, september, shedding, significant, slightly, solar, started,
system, systems, tas, temperature, term, trading, transmission,
vre, wind, would, yet, zero
```

Tokenization is the same lowercase, stopword-filtered `[a-z0-9]+` rule described above. The selected vocabulary uses the following rules:

- Its corpus is the union of unique articles available at training issues `2021-10-01..2024-12-31`, including all extraction states.
- Candidates are the **456 most frequent title tokens** and **550 most frequent body tokens**. Ranking is descending corpus count, with ascending lexical token order for ties.
- Selection uses price target days `2021-10-01..2024-12-30`, with labels strictly before `2024-12-31T14:00:00Z`. Daily prices are region means followed by an equal mean over NSW1, QLD1, and TAS1.
- Word series are raw counts over each training issue's rolling 72-hour support.
- ADF uses a constant and AIC lag; difference once if *p*>=.05. Undefined/constant series retain no word.
- Bilateral OLS Granger tests use **specified lag 30**; retain forward *p*<.05 and reverse *p*>=.05.
- The selected vocabulary remains frozen through news daily refits. The model also includes both news Activity-reference columns.

## no-text model inputs

### Notice numerical inputs

The 61 numerical inputs below are common to notice models. Prices come from dispatch `RRP`; physical fields come from regional dispatch summaries. Price availability is `max(interval_end+5min,LASTCHANGED)`; physical-summary availability is `interval_end+5min`. Intervention records are removed; price records require `RUNNO=1`.

| Column(s) | One-line definition and timing |
|---|---|
| `horizon` | Forecast lead in minutes, one of 5, 10, 15, 20, 25, 30. |
| `legal_anchor` | Latest finite price in the whole price sequence whose availability is <=\(t\). |
| `price_lag_5m` | Available RRP for interval ending \(t-10min\). |
| `price_lag_10m` | Available RRP for interval ending \(t-15min\). |
| `price_lag_30m` | Available RRP for interval ending \(t-35min\). |
| `price_lag_60m` | Available RRP for interval ending \(t-65min\). |
| `ramp_5m` | `legal_anchor-price_lag_5m`. |
| `ramp_10m` | `legal_anchor-price_lag_10m`. |
| `ramp_30m` | `legal_anchor-price_lag_30m`. |
| `ramp_60m` | `legal_anchor-price_lag_60m`. |
| `recent_volatility` | Sample standard deviation across anchor and the four named price lags, with available-value handling inherited from pandas. |
| `observed_pos300` | Indicator `legal_anchor>300`. |
| `observed_pos1000` | Indicator `legal_anchor>1000`. |
| `observed_pos5000` | Indicator `legal_anchor>5000`. |
| `price_seq_00` ... `price_seq_23` | Twenty-four consecutive five-minute prices ending at the anchor's interval, oldest to newest; an incomplete or unavailable sequence is replaced by repeated anchor values. |
| `price_sequence_mask` | One if all 24 sequence prices are finite and available by \(t\); zero otherwise. |
| `price_seq_ramp_last` | Last sequence price minus its preceding sequence price. |
| `price_seq_volatility` | Population standard deviation of the 23 adjacent sequence changes. |
| `calendar_hour_sin`, `calendar_hour_cos` | Sine/cosine of issue-local fractional hour, period 24. |
| `calendar_weekday_sin`, `calendar_weekday_cos` | Sine/cosine of issue-local weekday, period 7. |
| `calendar_month_sin`, `calendar_month_cos` | Sine/cosine of issue-local month minus one, period 12. |
| `region_code` | Index in `(NSW1,QLD1,SA1,TAS1,VIC1)`. |
| `horizon_code` | Index in `(5,10,15,20,25,30)`. |
| `horizon_group` | Groups 5/10->0, 15/20->1, 25/30->2. |
| `graph_neighbor_anchor_mean` | Mean of neighboring regions' latest available anchors. |
| `graph_neighbor_ramp_mean` | Mean neighbor anchor minus neighbor RRP at \(t-10min\), over finite differences. |
| `graph_source_mask` | One only when every required neighbor anchor and ramp is finite. |
| `phys_totaldemand` | `TOTALDEMAND` at interval ending \(t-5min\), available by \(t\). |
| `phys_availablegeneration` | `AVAILABLEGENERATION` at that interval. |
| `phys_dispatchablegeneration` | `DISPATCHABLEGENERATION` at that interval. |
| `phys_netinterchange` | `NETINTERCHANGE` at that interval. |
| `phys_demandforecast` | Historical-summary `DEMANDFORECAST` at that interval. |
| `phys_margin` | `AVAILABLEGENERATION-TOTALDEMAND` at \(t-5min\). |
| `phys_demand_change_30m` | Demand at \(t-5min\) minus demand at \(t-35min\). |
| `phys_margin_change_30m` | Margin at \(t-5min\) minus margin at \(t-35min\). |

For the sequence range, the complete column names are `price_seq_00`, `01`, `02`, `03`, `04`, `05`, `06`, `07`, `08`, `09`, `10`, `11`, `12`, `13`, `14`, `15`, `16`, `17`, `18`, `19`, `20`, `21`, `22`, `23`, each with the `price_seq_` prefix.

Notice models predict the residual from `legal_anchor`; the anchor is added back to produce the price forecast. They train once on the notice training sample, October 2021-December 2023, with the sampling weights of Appendix B.4. They do not refit during the notice evaluation window.

### News numerical inputs

The schema contains **872 numerical inputs** before frozen pruning. Indexed definitions below enumerate the complete generated column families.

| Column(s) | One-line definition and source fields | Timing |
|---|---|---|
| `region_code` | Index in `(NSW1,QLD1,TAS1)`. | Known at issue. |
| `horizon` | Target-hour index 0 through 23. | Known at midnight issue. |
| `target_hour_sin`, `target_hour_cos` | Sine/cosine of target-hour index, period 24. | Known target calendar. |
| `target_weekday_sin`, `target_weekday_cos` | Sine/cosine of issue/target day's local weekday, period 7. | Known target calendar. |
| `target_month_sin`, `target_month_cos` | Sine/cosine of local month minus one, period 12. | Known target calendar. |
| `price_lag_01` ... `price_lag_72` | Hourly mean of dispatch `RRP` for each historical block. | Block \(k\) contains interval ends \(t-k\,h+j*5min\), \(j=0..11\), all available by \(t\). |
| `phys_totaldemand_lag_01` ... `phys_totaldemand_lag_72` | Hourly mean of historical `TOTALDEMAND`. | Same blocks, own availability clocks. |
| `phys_availablegeneration_lag_01` ... `phys_availablegeneration_lag_72` | Hourly mean of historical `AVAILABLEGENERATION`. | Same. |
| `phys_dispatchablegeneration_lag_01` ... `phys_dispatchablegeneration_lag_72` | Hourly mean of historical `DISPATCHABLEGENERATION`. | Same. |
| `phys_netinterchange_lag_01` ... `phys_netinterchange_lag_72` | Hourly mean of historical `NETINTERCHANGE`. | Same. |
| `phys_demandforecast_lag_01` ... `phys_demandforecast_lag_72` | Hourly mean of the `DEMANDFORECAST` field stored in historical summaries. | Same. |
| Each preceding lag column plus `_observed` | One if all 12 component records for that field/block are finite and available by \(t\); otherwise zero and the corresponding mean is NaN. | Same. |

In every lag family, the suffix runs through **every zero-padded integer `01..72`**. Thus there are 432 history values and 432 corresponding observation masks, plus eight calendar/key inputs.

At midnight, lag block 1 contains interval ends **23:00 through 23:55**. The interval ending at midnight is not used. No P5MIN, operator price forecast, or target-day exogenous forecast is included.

## News training-label availability rule

At each news midnight origin \(t\), the pooled daily-refit training set contains **all complete eligible target days from 1 October 2021 onward strictly before the origin day**. A day enters only when:

1. It has all **72 rows**, three regions x 24 target hours.
2. Every target value is finite.
3. Every row has a recorded, nonmissing `label_available` timestamp **strictly before \(t\)**.

A label available exactly at the origin is excluded. The rule can include 2025 history, January-February 2026 history, and preceding evaluation-window days. Each historical example's features are built at that example's own issue clock. Vocabulary and pruning remain frozen from training issues through 2024.

The executable availability rule is:

```python
origin = pd.Timestamp(task.origin, tz='Australia/Brisbane').tz_convert('UTC')
legal = clocks.notna().to_numpy() & (clocks < origin).to_numpy() & np.isfinite(panel['y'].to_numpy())
support = pd.DataFrame({'day': day, 'legal': legal}).groupby('day', sort=True)['legal'].agg(['size', 'sum'])
eligible = support.index[(support['size'] == 72) & (support['sum'] == 72) &
                          (support.index >= '2021-10-01') & (support.index < task.origin)]
train = np.flatnonzero(np.isin(day, eligible))
```

Each hourly target label is the mean of its twelve five-minute prices. Its availability is the **maximum availability among those twelve prices**, and the label is defined only when all twelve prices and clocks are present. Each price becomes available at the maximum of its interval end plus five minutes and LASTCHANGED:

```python
avail[...,0] = np.where((lc!=NAT)&ok, np.maximum(ends+FIVE,lc), NAT)
complete = valid.all(axis=-1)
means = np.where(complete, np.where(valid,v,0).sum(axis=-1)/12, np.nan)
clock = np.where(complete, a.max(axis=-1), NAT)
```

Target-hour construction uses interval ends from hour start +5 minutes through hour end. Consequently, a preceding calendar day is not automatically eligible: every one of its hourly labels must pass the strict availability gate.

