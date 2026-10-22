# Notice parsing and quantity binding

Specification date: 2026-10-04.

The notice audit records REPORT.md, FINDINGS.json, SYNTHETIC_RESULTS.json and
SYNTHETIC_ADDITIONAL.json describe the parsing and binding cases. quantity_parsing specifies
literal quantity parsing; fit_memory/news_memory specify the related execution settings.
The parsing rules preserve labels, source bytes, input gates, outcomes, windows,
comparison families, contrasts, Holm adjustment, learners, seeds, budgets and drop order.

## Frozen normalization rules

N01: initialize status from notice lifecycle/title afresh for every window. RETURN_TO_SERVICE affects only that window. No additional event-link or asset-scope inference; existing resolver limitations remain disclosed.

N02: existing closing endpoint must agree exactly with a unique source explicit future-action match from the already frozen action_metadata grammar. Only then recover prospective/action evidence; conflicts remain UNKNOWN. Do not derive an action for a window lacking an endpoint. Labels are never edited.

N03: full English Month YYYY is month precision, not an exact physical endpoint: return UNKNOWN. Add complete numeric-token matches to English day-date parsing. Carry one year on the end only for a genuinely yearless Dec–Jan pair. Explicit years and other inversions remain unchanged; existing inclusive-day rule remains.

N04: in MARKET INTERVENTION, an end matching the literal absence-of-sufficient-market-response-by endpoint is a response deadline: replace derived physical end with UNKNOWN, and bounded admission becomes UNKNOWN_INTERVAL. Do not fabricate an open interval or intervention duration.

N05: recognize only the audit's strict contiguous From S to E. The [forecast/actual] capacity reserve requirement is X MW. The minimum capacity reserve available is Y MW template. Require parsed endpoints matching exactly one existing RESERVE window, and exactly one matching source block for that window. Derive the printed scalar pair directly into records, retaining immutable label quantities and window IDs. Ambiguous matching blocks produce UNKNOWN. No nearest-window, midpoint, region or asset inference. Reversed source intervals remain invalid.

N06: reserve scalars require event_family RESERVE; MINIMUM SYSTEM LOAD never projects REQUIREMENT/AVAILABLE as reserve MW. Loss quantities and raw label MW survive.

N08: exact end-of-that/the/this-trading-day phrase is parsed only relative to a paired fully dated clock endpoint. In AEST, trading day is [04:00, next 04:00): endpoint is the first 04:00 strictly after the literal start. Bare-clock/publication-only anchors remain UNKNOWN. Rule evidence: AEMO Bidding and Dispatch technical specification, https://tech-specs.docs.public.aemo.com.au/Content/TSP_EMMS_June2024/Bidding_and_Dispatch.htm (288 period ends 04:05 through 04:00), and AEMO 2022 public operational statement https://aemo.com.au/newsroom/media-release/price-caps-administered-across-multiple-states (trading-day end 04:00). No price observations are used.

N14: notice marker needs a whole-word match. Preserve marked numeric/alphanumeric foreign IDs. Stage a validator copy inside execution (schema path points at original notice_extraction schema); do not replace notice_extraction validator or rejudge its journal.

N15: reject MW/MWh/minutes quantities in temporal fields. If a RESERVE window has one quantity-dimension endpoint and its opposite endpoint uniquely matches a strict source reserve block, use the literal source endpoint. Otherwise UNKNOWN. Add validator endpoint-dimension rejection. No relabelling, re-extraction or retry.

## Feature construction and input records

execution uses the specified notice_records module copy; the source notice_records, notice_extraction and confirmation/code hashes are retained. Runtime exact specified chain becomes original -> shared_storage -> quantity_parsing -> input_definitions -> storage_limits -> fit_memory -> news_memory -> notice_parsing; declared feature change is NOTICE_DETERMINISTIC_PARSING_BINDING_CORRECTION_ONLY. Synthetic chain inputs extend accordingly; all historical declarations/checks remain required.

The existing feature writer recreates news extras, and existing fit receipts bind the whole feature manifest. Prepare a deterministic reuse receipt: retain reference complete manifest by archive, verify every news bundle and vocabulary identity, skip the news writer, and verify retained news files byte-identically before and after. After a candidate complete feature manifest, exact news bundle equality plus design/input identities authorizes only reference-news receipt SHA to candidate manifest SHA compatibility. News fit artifacts remain unchanged; do not rewrite reference receipt hashes. Archive notice fit receipts/artifacts/attempts and stage dispositions before rerun; retain WallLedger accounting/budgets. LEAR is numeric-only and may reuse with its own unchanged hourly identity. Reference news/LEAR failure/admission records may be reused only after the same compatibility proof. Scoring/sealing completion is inactive, never silently accepted.

## Source census and measurement

Read NRX1.3 label columns notice_id, terminal_state, label_json in batches; notice_extraction scope title/body/source clocks; audit diagnostics, source Python and receipts only. No host_state, panels, feature banks, seals, scores, predictions or price data. Census only current confirmation notice_extraction derivation; historical NW/MH banks are lineage/disclosure, not current loader inputs.

Per finding compare reference derivation vs that set alone on every source label (baseline for attribution); also compare the combined parsing rules. Count differing record rows/cells, differing sidecars and notice IDs. Split by audit's training (through 2024-07-31), C (2026-01..02), D lead-in (2026-07-27..31), D (2026-08..09), supplemental and other. Feature census is a specified SOURCE-ONLY PROBE, never actual model-row impact: for each notice use all five regions, issue=max(ceil5(available),ceil5(each known reference/candidate start)), horizons 5,10,15,20,25,30; target=issue+h. Compute reference/candidate L14 and Laz from that notice only. Count changed keys and named feature cells; list IDs. Quantify changed full-stream record inputs separately; no claim about real forecast rows. Validator-only N14 has no feature changes by construction. Labels and Chen content unchanged, and news code/generator unchanged. No additional encoder/LLM or outcome computation.

Measurements use a single process at nice 10, thread caps 1 and RSS <1,500,000,000 bytes.
Before tests, the census and each batch, `memory_pressure | tail -1` must report >=20% free;
otherwise the measurement waits and records the resource condition. If nice is unavailable,
the actual priority is reported. Measurement files and reports are retained within notice_parsing.

## Validation and limitations

Regression assertions must fail on baseline and pass on staging for every scoped finding; UNKNOWN, ambiguity, explicit-year, trading-day endpoint, dimension and genuine-ID negative cases included. Run full confirmation code/test suite in independent code-only replicas with synthetic test data, inherited tests unchanged except extended chain inputs. The validation suite uses synthetic test data and does not run the forecast command-line entry point.

N07 remains an information-loss representation limitation (closure empty windows); N09–N13 and N16 remain disclosure-only. N14 only changes future validator behavior, never historical rejected attempts. No correctness/performance claims for arbitrary semantics, forecast rows or outcomes; a source-only probe is not model evaluation. Exact Month YYYY endpoints remain UNKNOWN. Feature calculation time estimates use saved computation durations. Where notice-only
timestamps are absent, only the documented total-run envelope is identifiable.
