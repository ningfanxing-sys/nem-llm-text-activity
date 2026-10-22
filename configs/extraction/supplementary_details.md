# Supplementary details

This file accompanies the paper "Do LLM-derived text features improve electricity price forecasts beyond document activity? Evidence from Australia's National Electricity Market" in its code repository. It describes the calculations summarised in the paper. Each heading names the parts of the paper it supplements, and section, appendix, table and equation numbers refer to the paper. All times are AEST (UTC+10) unless marked UTC.

## A.1 Tests (supplements Section 5.2 and Appendix A)

For a forecast horizon of h = 1, the small-sample adjustment of Harvey et al. (1997) multiplies a statistic with variance divisor n by sqrt((n - 1)/n), a factor that the divisor n - 1 of Eq. (2) already absorbs. The Student-t sensitivity therefore changes only the reference distribution, to a Student-t distribution with n - 1 degrees of freedom (60 for notices, 134 for news).

## B.1 Numerical inputs, P5MIN runs, news training labels and LEAR (supplements Appendix B.1)

A price is available at the maximum of its interval end plus five minutes and its last-change time (LASTCHANGED). The other inputs from the regional dispatch summaries (TOTALDEMAND, AVAILABLEGENERATION, DISPATCHABLEGENERATION, NETINTERCHANGE and the DEMANDFORECAST field stored in the historical summaries) are available five minutes after their interval end. Intervention records are removed. Stored values are final, because revision histories are not available. The notice models use the physical inputs of the interval ending five minutes before the issue and 30-minute changes from the interval ending 35 minutes before it. The notice models predict the change from the anchor; adding that change to the anchor gives the price forecast. In the notice window, issues in the last half hour of 31 July, whose targets fall on 1 August, are included.

At the 00:00 issue of the news task, the latest hour of price history consists of the twelve intervals ending 23:00 to 23:55. This hour is used only if all twelve prices are present and the 23:55 price was available by 00:00. The interval ending at 00:00 is never used. The news models receive 72 hourly blocks of numerical history with missingness indicators, and their preprocessing is fitted on data through December 2024.

At each 00:00 issue t, the news models are trained on every complete target day from 1 October 2021 that precedes the issue day. A day is complete when its 72 hourly labels (three regions by 24 hours) are all finite and available strictly before t; a label available exactly at t is excluded. An hourly label is available once all twelve of its five-minute prices are available.

A model with P5MIN inputs uses the run made five minutes before the issue time t and its revision from the run made ten minutes before t. A run enters only if its run time plus five minutes and its last-change time are both at or before t. Runs are joined exactly by run time, target interval and region; a missing run is never replaced by the nearest one.

The LEAR benchmark uses, for each region, the 24 hourly prices of days d-1, d-2, d-3 and d-7 (96 values), 96 missingness indicators and seven day-of-week indicators, 199 inputs in total. A price that is not available at the issue is replaced by the median of its column in the calibration sample. For each hour, inputs and target are scaled by the calibration window's median and median absolute deviation and transformed with the inverse hyperbolic sine (Uniejewski et al., 2018). Least-angle regression (LARS) selects the LASSO penalty using the Akaike information criterion, and the model is refitted by coordinate descent (Lago et al., 2021). Each of the four calibration windows (56, 84, 1,092 and 1,456 days) ends on the latest day before the issue whose 24 hourly targets are all available, and the four forecasts are averaged with equal weights.

## B.2 Document availability, notice links and listing evidence (supplements Appendix B.2)

Each article is held as one saved body with its publication time t_pub and modification time t_mod. Its saved version becomes available at max(t_pub, t_mod) + 5 min, the RE-Price publication-and-edit rule with a five-minute delay. The documents available at issue time t are the articles whose saved version became available in (t - 72 h, t] and whose publication time is at or before t. The archive does not retain the text preceding an article edit, so a saved body may differ from the text that was public before its last edit.

Notices in the training sample enter at their official clock, LASTCHANGED or ISSUE_DATETIME, plus five minutes, rounded up to the five-minute grid. For evaluation-period notices, availability uses the Creation Date C, a0 = ceil5(C + 5 min), where ceil5 maps each time upward to the five-minute grid. The Creation Date is a field in the header of the saved notice text; it is not a file-system time and does not establish the notice's first publication time. A notice with a Creation Date of 10:17, for example, becomes available at 10:25, and at 10:30, 10:40 and 11:25 under the three delays.

The event-state and overlap features are assembled in order of availability. A record j carries its availability time a_j, a stated start s_j, a stated end e_j if one is given, and a closure time c_j, which remains infinite while the record is open. Updates, cancellations and recovery notices close preceding records only after they themselves become available. No subsequent notice therefore revises a preceding information set. Links between notices come from explicit references, compatible dated titles and applicable region-wide releases, subject to checks of type, reserve level and region; an ambiguous link closes no record. For Event states, a record contributes to target time tau, the end of the target interval, at issue time t through the indicator I_j(t, tau):

- bounded record: I_j(t, tau) = 1{a_j <= t < c_j and s_j <= tau < e_j};
- open-ended record: I_j(t, tau) = 1{a_j <= t < min(c_j, a_j + 48 h) and tau >= s_j};
- record with unresolved times: I_j(t, tau) = 0.

The 48-hour limit bounds how long an open-ended record remains current at issue time; it does not impute a physical end. Unknown capacity is not set to zero, a reserve shortfall is not counted as lost generation, and lost megawatts count only when the source binds them to one asset and one window.

Of the 725 notices dated August or September 2026, 712 match a record in AEMO's public notice listing; the 13 unmatched notices and the 71 notices from 27–31 July are not assessed. The listing gives times to the minute, and a notice counts as listed by a given time only if the end of its listing minute is at or before that time. Under this conservative rule, listing evidence covers 142 notices (19.9%) at a0, 243 (34.1%) after five minutes, 402 (56.5%) after 15 minutes and 570 (80.1%) after 60 minutes. The latest listing occurs 714 minutes after a0; measured from the notice's Creation Date to the end of the listing minute, the longest delay is 723.67 minutes.

## B.3 Delayed availability and date parsing (supplements Appendix B.3)

Each main notice comparison is repeated with all evaluation-window notices made available 5, 15 or 60 minutes after a0. Every notice-derived input is rebuilt from the notices available by the delayed time: the activity counts, Event states, Overlap components and the Archive embeddings prefix. The models fitted with seed 20260919 predict without refitting.

The main estimates anchor the DD/MM/YYYY hh:mm:ss timestamps stated inside the 796 evaluation-period notices day first, as AEMO writes them, and a sensitivity analysis anchors them month first. The two readings differ in the Event states features of 29,310, the Overlap components features of 3,456 and the Rule parser features of 17,280 of the 527,040 evaluation forecasts. The training features, the availability times that define the activity counts and the Archive embeddings prefix (Appendix B.2) and the no-text model are the same under both readings, so the same fitted models produce both sets of forecasts.

Across the availability conditions and the two readings, each of the three main notice comparisons changes by less than 0.01 percentage points, and the representation-versus-activity tests have Holm-adjusted p < 10^-7 in every condition (Table D1). Across all reported comparisons, the month-first reading changes the estimates by at most 0.015 percentage points and changes no sign or Holm decision. The replication package gives every comparison under both readings.

## B.4 Training sample and prediction clipping (supplements Appendix B.4)

The notice training sample keeps every training example in connected high-price events, with weight 1, and a one-in-50 hash sample of the others, with weight 50, the inverse of the sampling rate. A high-price event is constructed from five-minute prices above 300 AUD/MWh. Within each region, qualifying intervals form clusters, split at gaps of more than 30 minutes and padded by 30 minutes on each side; clusters are linked when they overlap or lie within 30 minutes of each other in the same or a connected region (QLD1-NSW1, NSW1-VIC1, VIC1-SA1 and VIC1-TAS1). The price histories are built on the full regional grid before the training examples are joined, and training-label eligibility is checked at the earliest origin, so that the missingness of neighbouring prices, including lagged ones, does not depend on future event membership in this event-selected training sample.

Notice price forecasts (the anchor plus the predicted change) are clipped to -1,000 and 17,500 AUD/MWh. These are the limits that the inherited configuration applies to targets from 1 July 2024. News forecasts are not clipped.

## C.1 Prompts, schema fields, extraction runs and worked example (supplements Section 4.1 and Appendix C.1)

### Notice prompt and schema

The notice prompt supplies the title and body of one notice, with its identifier and clocks as metadata. The model must use only the supplied notice, without tools, other notices or outside knowledge. It must not infer prices, price direction or subsequent outcomes, and it must treat instructions in the source as data.

It returns the reporting company, a lifecycle state (NEW, UPDATE, CANCELLATION, CEASED, RECLASSIFICATION or UNKNOWN, set only by an explicit source action), impact windows and quantities.

Each window contains start and end text, a region (one of the five NEM regions or UNKNOWN), an interval status (BOUNDED, OPEN_UNTIL_NOTICE or UNKNOWN), an asset, a fuel stated in the source (coal, gas, oil, hydro, nuclear, wind, solar, battery or other), an event class (failure, planned maintenance, maintenance update or other) and an event family (outage, reserve, constraint, intervention, return to service or other). Each window also contains the six RE-Price attributes: impact timeframe, root cause, affected infrastructure, region, energy resource and operational indicators.

Each quantity retains its literal value, a unit (MW, MWh, minutes or other) and a role (loss, available, requirement, flow, limit, violation or other). It is bound to a window only when the source states the scope explicitly.

Each known value requires evidence spans copied verbatim from the title or body, with each span forming one contiguous passage. Unstated values remain UNKNOWN. Free-text fields (start and end text, asset wording, attribute values and quantity values) reproduce the source character for character; the enumerated fields are classifications that the quoted evidence must support. Dates are anchored afterwards by deterministic code.

### Article prompt and schema

The article prompt supplies one saved article with its identifier and clocks. The model must use only that article, without tools, search, memory of the event, instructions found in the article or inference about future prices. The model assigns an impact tier with a verbatim evidence quote: c1 for major market-disruptive news such as a major generator outage, a large fuel shortage or extreme weather; c2 for an operational signal such as maintenance, a short-term supply constraint or an abnormal market condition; c3 for a policy, regulatory or residential-survey item; or Unknown. The model fills the six RE-Price attributes and extracts up to six operational statements. Each statement has a verbatim quote, a kind (fact, forecast, analysis or unknown), the source to which the article attributes the statement, an event type from a fixed vocabulary, the NEM regions it names, and the event time and magnitude copied from the text. A direction field records physical or operational change and never a price direction.

The verbatim prompts and JSON schemas are in the code repository. For notices, they comprise the prompt, the response schema passed to the model and the full validation schema. For articles, they comprise the prompt template, into which each article is inserted at run time, and the schema.

### Extraction runs, validation and failures

Notices were extracted in one run, from 21:02 UTC on 30 September to 01:55 UTC on 1 October 2026. The notice archive holds 21,470 distinct notices, 11,348 of them in the training sample and 796 from the evaluation period: 725 dated August or September 2026 and 71 from 27–31 July. Articles were extracted in two runs with the same model alias, effort, prompt and schema. A historical run on 29 September 2026, from 18:22 to 21:10 UTC, covered 2,244 articles from September 2021 to February 2026; a 2026 run on 30 September, from 20:21 to 20:37 UTC, covered 286 articles, 24 from February and 262 from March to September. The two runs overlap on the 24 articles from February 2026, whose saved versions are identical, so the inventory holds 2,244 + 286 - 24 = 2,506 distinct articles. For these 24 articles, we use the historical-run extraction and keep the 2026-run extraction, which also succeeded, only as provenance. Across the three runs, extraction required about 28,400 requests, including retries, and about eight hours; the runs used 0.51 billion input tokens, most of them cached, and 14.3 million output tokens.

An offline validator accepts a record only if every evidence span occurs literally in the title or body and the windows, quantity bindings and asset references are structurally consistent. It checks quote provenance and structure but does not assess semantic correctness.

A notice request that failed in transport was retried up to three times. A notice whose output failed validation was sent once more, unchanged and without error feedback. Both rules applied to every period of the notice archive. Article requests that failed in transport were also retried. When resumed, the historical article run retried documents whose outputs had failed validation: 25 failed validations on 23 articles were followed by another call, and 22 of these articles eventually succeeded. The 2026 article run kept its validation failures as final. In every run, the failure flag marks a document's final, unsuccessful state. A document whose extraction fails remains among the available documents, with unknown content and a failure flag.

Among notices, extraction failed for 543 of the 21,470 in the archive, 297 of the 11,348 in the training sample (2.62%), and 13 of the 725 dated August or September 2026 (1.79%), or 16 of 796 including the notices from 27–31 July (2.01%). Among articles, extraction failed for 201 of the 2,244 in the historical run (8.96%) and 26 of the 286 in the 2026 run; all failures in the latter run were among the 262 articles from March to September (9.92%).

### Worked example

Notice 91525, from the training period, declares a forecast LOR2 condition for Tasmania. Its accepted record has lifecycle NEW, reporting company AEMO and one window, w1, with region TAS1, status BOUNDED, start 0900 hrs and end 1100 hrs on 08/10/2021, event family RESERVE and class OTHER. Asset, fuel and root cause remain UNKNOWN. The attributes retain the stated timeframe, the Tasmanian region and the operational indicator that AEMO is seeking a market response, while affected infrastructure and energy resource stay UNKNOWN. Two quantities, 177 MW with role REQUIREMENT and 164 MW with role AVAILABLE, are bound to w1 by explicit source scope. The start and end text, the attribute values and the two quantity values are verbatim source wording. The lifecycle, region, status, event family and class, and the quantity roles are classifications supported by the quoted evidence. A further sentence gives the latest intervention time as 08/09/2021, which conflicts with the declared window. The record uses the declared window, and the source text is retained verbatim.

## C.2 Encoding and the news word-frequency vocabulary (supplements Appendix C.2)

Archive embeddings, news Embeddings and news Raw embeddings use the sentence encoder all-MiniLM-L6-v2 at revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 (sentence-transformers 5.1.2, Transformers 5.15.1, Torch 2.13.0), with 384 dimensions. At each issue, the available texts are serialised in a specified order. Notice records are ordered by availability time and form a prefix that grows with the archive, from 20,745 records at the first evaluation issue to 21,470 at the last; failed extractions enter as UNKNOWN fields. For the news Embeddings model, the extracted records are ordered by saved-version availability and article identifier, each with its impact tier followed by the six attributes in schema order; failed extractions enter as UNKNOWN fields. The Raw embeddings model instead encodes the titles and bodies of the available articles, in the same article order.

The serialised text is tokenised as one sequence, without truncation, and split into consecutive blocks of at most 254 content tokens, the 256-token limit minus two special tokens. Each block is mean-pooled over its tokens and L2-normalised. The block vectors are averaged with equal weights, and the average is normalised again. An issue without available documents yields a zero vector.

The news Word frequencies model follows Bai et al. (2024). The 456 most frequent title words and the 550 most frequent body words in the training corpus are screened with unit-root and Granger-causality tests on the training data. These vocabulary sizes match those of that study. The screening retains 57 title words and 81 body words.

The file feature_dictionary.md in the code repository defines every column of the activity references, the representations, the P5MIN inputs and the no-text models, including source fields and timing. It also states the news task's rule for when training labels become available.

## D.1 Seeds, windowed notice references and further sensitivity values (supplements Appendix D.1)

Tables 4 and D2 of the paper and Tables S1 and S2 below report the results for the no-text fits at seeds 20260920 and 20260921 and for the windowed notice references. Refitting the no-text model at seed 20260919, for notices and for the first three news issue days, reproduces the saved forecasts exactly.

In the seed-averaged forecasts, sign reversals occur only with the original notice reference, for Event states and Overlap components, and not under the seven-day or 24-hour reference; the news reversal occurs only at seeds 20260919 and 20260920. With seed-averaged forecasts and the seven-day reference, the representation steps of Event states and Archive embeddings are negative with Holm-adjusted p below 0.05 across the three notice representations, and that of Overlap components is not significant (Holm p = 0.074).

W7(t) and W24(t) count the notices that became available in the seven days and in the 24 hours up to the issue time t, on the availability clock of P(t), and F7(t) and F24(t) count the failed extractions among them. Like P(t) and P_F(t), they are NEM-wide, repeated for every region (Eq. B.1) and limited to the saved notices. For issue times before 3 August 2026, and before 31 August for the time-shifted placebos, the seven-day window reaches back into the archive gap that ends on 26 July, and the counts include no notices from that gap. In the windowed references, A6(t) is unchanged, W24(t) ≤ W7(t) ≤ P(t) and F24(t) ≤ F7(t) ≤ P_F(t) on every training and evaluation row, and no count includes a notice that became available after t. The time-shifted placebos rebuild the seven-day reference and the Archive embeddings model from the notices available 28 days before the issue, with the clock shift of the original placebos, and are scored on the 38 placebo days of Table 5.

On these days, the Archive embeddings model with the seven-day reference has a 0.044% higher MAE than its time-shifted placebo (p = 0.726; 95% seven-day block interval -0.202% to 0.282%). When both are rebuilt from the notices available 28 days before the issue, the Archive embeddings model has a 0.219% higher MAE than the seven-day reference (p = 0.099; 95% seven-day block interval 0.022% to 0.321%).

At seed 20260919, the 95% seven-day block intervals of the net change against the no-text model are -0.036% to 0.463% for Event states, -0.012% to 0.449% for Overlap components and -0.370% to 0.010% for Archive embeddings.

On the extended 214-day news window, the HAC7 p for Fields is 0.148.

**Table S1.** Seven-day block-bootstrap intervals for Table 4 (seed-averaged forecasts): change in MAE (%) with its 95% interval in brackets; negative values favour the model with more inputs.

| Representation | Activity reference | Activity step (M vs N) | Representation step (L vs M) | Net change (L vs N) |
|---|---|---|---|---|
| *Notices* | | | | |
| Event states | Original | +0.224 [+0.003 to +0.437] | -0.143 [-0.205 to -0.097] | +0.081 [-0.167 to +0.306] |
|  | Seven-day window | +0.081 [+0.014 to +0.136] | -0.141 [-0.180 to -0.071] | -0.060 [-0.118 to +0.006] |
|  | 24-hour window | +0.107 [+0.071 to +0.136] | -0.212 [-0.259 to -0.159] | -0.106 [-0.150 to -0.056] |
| Overlap components | Original | +0.224 [+0.003 to +0.437] | -0.004 [-0.062 to +0.036] | +0.219 [-0.029 to +0.445] |
|  | Seven-day window | +0.081 [+0.014 to +0.136] | +0.047 [-0.032 to +0.129] | +0.128 [+0.044 to +0.196] |
|  | 24-hour window | +0.107 [+0.071 to +0.136] | +0.017 [-0.057 to +0.079] | +0.124 [+0.048 to +0.183] |
| Archive embeddings | Original | +0.224 [+0.003 to +0.437] | -0.517 [-0.652 to -0.315] | -0.295 [-0.487 to -0.035] |
|  | Seven-day window | +0.081 [+0.014 to +0.136] | -0.521 [-0.787 to -0.158] | -0.440 [-0.750 to -0.036] |
|  | 24-hour window | +0.107 [+0.071 to +0.136] | -0.448 [-0.627 to -0.211] | -0.342 [-0.536 to -0.092] |
| *News* | | | | |
| Fields | 72-hour counts | -3.03 [-5.28 to -1.04] | +12.50 [-0.73 to +34.64] | +9.09 [-3.95 to +30.11] |
| Embeddings | 72-hour counts | -3.03 [-5.28 to -1.04] | -0.53 [-4.09 to +2.96] | -3.55 [-7.60 to +0.34] |

**Table S2.** Representation step (L vs M) and net change (L vs N) at each seed: change in MAE (%) with the nominal two-sided DM p in parentheses. Table D2 of the paper gives the activity steps at each seed.

| Representation | Activity reference | Step | Seed 20260919 | Seed 20260920 | Seed 20260921 |
|---|---|---|---|---|---|
| *Notices* | | | | | |
| Event states | Original | L vs M | -0.303 (<0.001) | +0.066 (0.136) | -0.214 (<0.001) |
|  |  | L vs N | +0.242 (0.037) | +0.175 (0.141) | -0.149 (0.285) |
|  | Seven-day window | L vs M | -0.063 (0.084) | -0.146 (0.001) | -0.241 (<0.001) |
|  |  | L vs N | +0.170 (<0.001) | -0.090 (0.032) | -0.250 (<0.001) |
|  | 24-hour window | L vs M | -0.221 (<0.001) | -0.349 (<0.001) | -0.117 (0.003) |
|  |  | L vs N | -0.026 (0.433) | +0.089 (0.046) | -0.383 (<0.001) |
| Overlap components | Original | L vs M | -0.284 (<0.001) | +0.299 (<0.001) | -0.017 (0.705) |
|  |  | L vs N | +0.260 (0.012) | +0.408 (0.003) | +0.049 (0.716) |
|  | Seven-day window | L vs M | -0.041 (0.493) | +0.063 (0.129) | +0.090 (0.030) |
|  |  | L vs N | +0.192 (<0.001) | +0.119 (0.002) | +0.081 (0.066) |
|  | 24-hour window | L vs M | -0.285 (<0.001) | -0.072 (0.093) | +0.395 (<0.001) |
|  |  | L vs N | -0.091 (0.019) | +0.367 (<0.001) | +0.128 (0.004) |
| Archive embeddings | Original | L vs M | -0.747 (<0.001) | -0.027 (0.785) | -0.492 (<0.001) |
|  |  | L vs N | -0.205 (0.041) | +0.082 (0.619) | -0.427 (0.010) |
|  | Seven-day window | L vs M | -0.124 (0.512) | -0.419 (0.009) | -0.882 (<0.001) |
|  |  | L vs N | +0.109 (0.559) | -0.363 (0.034) | -0.891 (<0.001) |
|  | 24-hour window | L vs M | -0.588 (<0.001) | -0.357 (0.023) | -0.321 (0.004) |
|  |  | L vs N | -0.394 (<0.001) | +0.081 (0.575) | -0.586 (<0.001) |
| *News* | | | | | |
| Fields | 72-hour counts | L vs M | +11.41 (0.043) | +16.10 (0.040) | +9.80 (0.093) |
|  |  | L vs N | +7.43 (0.204) | +10.94 (0.146) | +8.43 (0.144) |
| Embeddings | 72-hour counts | L vs M | +1.17 (0.558) | +0.43 (0.801) | -1.61 (0.465) |
|  |  | L vs N | -2.45 (0.305) | -4.03 (0.034) | -2.84 (0.176) |

## D.2 Placebo MAE levels and further placebo contrasts (supplements Appendix D.2)

Every time-shifted model, including the one in the P5MIN extension, is fitted separately. The extracted records keep their other fields while their source clocks and event dates move forward by 28 days. The encoder is unchanged. On the 38 notice target days from 24 August, the MAEs are 9.5384 for the no-text model, 9.5709 for the activity reference and 9.5192 for Archive embeddings. Rebuilt from the notices available 28 days before the issue, the activity reference and the Archive embeddings model have MAEs of 9.5533 and 9.5906.

In a descriptive comparison of the daily losses, without a test, the Archive embeddings model has a 0.540% lower MAE than the activity reference on these days. The activity reference has a 0.184% higher MAE than its time-shifted placebo. The time-shifted activity reference does not differ significantly from the no-text model (+0.157%, p = 0.22). The time-shifted Archive embeddings model has a 0.547% higher MAE than the no-text model and a 0.390% higher MAE than the time-shifted activity reference (p < 0.001 for both). The Archive embeddings model has a 0.745% lower MAE than its time-shifted placebo (95% one-day block interval -0.998% to -0.499%; p < 0.001).

In the news placebos, the time-shifted activity reference and the time-shifted Embeddings model have MAEs of 25.190 and 25.310, against 23.925 for the activity reference and 24.205 for Embeddings. The time-shifted Embeddings model does not differ significantly from the time-shifted activity reference (+0.478%, p = 0.90), and the difference between Embeddings and its time-shifted placebo is not significant (p = 0.253).
