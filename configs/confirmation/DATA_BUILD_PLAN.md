# CONF data build plan: freeze before values

This file specifies the separate execution task. CONF opened source protocols,
parser code, schemas and metadata inventories; no price, demand, P5MIN value,
forecast value or label outcome was decoded from either confirmation window.
Every opened design path is recorded in `OPENED_PATHS.jsonl`. Only opaque-byte
hashing, schema/key metadata and source counts are allowed until the completed
input manifest is frozen. `code/panel_build.py` is import-safe and requires a
separate execution permit for any scientific build.

## News panel and historical bridge

Reuse DAPANEL's frozen projection and extend the dispatch-backed news panel with
DATA26 numeric sources for **2026-02-22..2026-09-30**. Feb22..28 supplies the
seven-day weekly-naive lead-in; March1..September30 has **214 issue days** at
00:00 fixed AEST and **15,408 keys** (214×NSW1/QLD1/TAS1×24). Feb22 lead-in
rows may lack their own full preceding history; they are not confirmation issues.
The primary March1 issue has the requisite past 72 hours in the DATA26 range.
Do not treat source-slice metadata as evidence that pre-Feb22 values were audited.

DAPANEL ends in December2025, while daily expanding fits also require eligible
January–February2026 prior days. Bind the existing official Jan/Feb monthly
sources from C's historical source manifests before reading them, build an
identical DAPANEL **Jan/Feb bridge**, and preserve any duplicated Feb22..28 keys
for exact identity checks. No prior day is silently omitted because an old panel
stopped earlier. The benchmark's 1456-day past window is covered structurally by
the existing 2021-10 onward source period; finiteness and legal clocks remain a
post-freeze gate.

DATA26 `numeric/INVENTORY.json` and `numeric/FILE_INVENTORY.json` identify
monthly official MMSDM PRICE/REGIONSUM archives through August, then September
DISPATCHIS Archive/Current files. Select this fixed inventory relation, not a
later value-based source priority. Verify every file's size/hash and member
identity against the completed manifest immediately before streaming it.
No full archive CSV is loaded: process projected chunks of at most 10,000 rows,
one archive reader at a time. September overlapping keys are reported by
DATA26; exact projected records collapse and conflicting projected records
stop the build. Do not choose a later revision to resolve a conflict.

Filter PRICE RUNNO=1 and INTERVENTION=0; REGIONSUM INTERVENTION=0. Use fixed
AEST UTC+10, stored as UTC. PRICE projection: region, interval end, RRP,
LASTCHANGED; availability max(end+5min,LASTCHANGED), with no missing-clock
fallback. Physical projection: TOTALDEMAND, AVAILABLEGENERATION,
DISPATCHABLEGENERATION, NETINTERCHANGE and DEMANDFORECAST; availability end+5min,
the B3 proxy, not authenticated first-publication availability. There is no
target-day physical forecast input and no P5MIN in N or any text arm.

Each target hour averages exactly twelve dispatch intervals ending hour+5min
through hour+60min. Thus **September30 hour23 requires the price key ending
2026-10-01 00:00 AEST**. DATA26 reports collecting this boundary Current source,
but the execution task must prove its complete key/schema/hash identity and
finite target/clock after freeze. September30 forecasts concern September30
hours, not October1 target-day prices. Missing boundary stops the complete
214-day gate; do not shrink the window or silently append an unselected archive.

For lag k=1..72, history comprises ends issue−k hours through
issue−(k−1)hours−5min. This is DAPANEL/NEWSD's five-minute-offset history, not
ordinary target-hour aggregation. Each field needs twelve finite, issue-legal
constituents; otherwise NaN and mask zero, preserving every target key. Keep the
same 432 values, 432 observed masks, known calendar/region/horizon indicators
and column order. Audit clocks/source IDs do not enter a learner. The weekly
naive uses the ordinary same-region/hour mean seven AEST days earlier only
if it is complete and issue-legal. Training a pooled day requires all 72 labels
and their recorded availability strictly before the current origin.

Post-freeze build PASS requires all 15,408 targets and their recorded clocks
to exist, no conflicting keys, and all reported masks to match the frozen
history rule. Missing legal weekly-naive values make its corresponding
benchmark/rMAE diagnostic unavailable; they do not discard primary target
keys or block a text-arm fit. Target/key/clock conflicts stop fitting; preserve exact gaps,
hashes and diagnostics. Existing archive versions are not certified original
publications. DATA26's complete key coverage is not a finite-value or revision
consistency result.

## Notices: frozen historic training and full evaluation

The fixed training population is exactly RF2's C training membership, sourced
from the **NW PHYS 2021-10..2023-12 development bank**. This follows
`autopilot/run_window.py` and
`../notice_window_llm_increment_20260924/run_nw_phys.py`; 2022-07..2023-12 is the
F1–F6 **test** range, not the complete C training range. Rebuild all notice arms
from the same historical source population using new NRX luna schema labels,
but preserve keys, original event-replay/ordinary training weights **1/50**,
numeric B4 corrections, fix-G graph legality, residual y−legal_anchor target,
training-only pruning and RF2's learner. Verify every historical training label
clock is strictly before the earliest primary-window origin under B6, preserving
all C train IDs; any unresolved clock/membership mismatch stops the fit.

The source-only `NRX/SCOPE_RECEIPT.json` supports this choice: its
`counts_by_source_month_aest` has nonempty saved sources in all **27** months
2021-10..2023-12, and its grouped counts give **6,911** notices in2021–22 plus
**4,437** in2023 (**11,348** combined). These are normalization-scope counts,
not label-validation success or a public completeness certificate. The receipt
binds the original M463 corrected registry by SHA-256
`6b81530382a9c3d538265850e877f611c6be5257e46075ded74de5b411ff4b6d`.
No final NRX label outcome was opened to justify this training choice.

Historical saved-registry support is an execution gate: every expected source
notice ID in the frozen original registry/catalogue must survive normalization,
every retained historical training month must have source-backed notice support
and the assembler's required pre-origin history must exist. Terminal extraction
failure is unavailable label, not no-event. Do not infer zero activity from a
missing registry partition. These gates establish the saved-source design's
support; they do **not** certify a complete census of all public historical
notices. This limitation is reported even if catalogue identity passes.

No 2024/2025/2026 row is appended to notice training. In particular, DATA26
reports 2026-03/04 ID-span proportions about32–44%, May/July many observation-gap
days and June no records. Exclude March–July as training sources; the ratios
do not authorize coding an unobserved day as zero. November2025–February2026
also lacks a source-completeness certificate, and is unnecessary under the
fixed-bank rule. The historic registry supports one frozen transfer fit; it
does not justify periodic adaptation through incompletely observed periods.

Build raw numeric/notice support over **2026-07-27..2026-09-30**, with July27..31
as notice lead-in. The primary target-time window is August1..September30,
**61 AEST target days**. Preserve RF2/C's target-time keys: five regions, each
five-minute interval beginning at August1 00:00 and ending before October1
00:00, six horizons5/10/15/20/25/30 minutes, unit evaluation weights;
**527,040 keys** =61×288×5×6. Earliest issues occur July31 23:30; they use the
registered July27 lead-in. Never use severe-event selection or hash subsampling
to select confirmation keys. The sole notice-window sensitivity removes
target days August1..7 and reuses already sealed predictions on August8 onward;
it is not a refit or a source-gap repair.

Reuse B4 strict sequence/graph availability and whole-sequence anchor fallback,
RF2 numeric/physical order, and B6 strictly-before training-label rule.
`oos_bank.py` is a structural source for full key generation, but its legacy
whole-CSV readers and end+5min-only price clock are not an execution shortcut:
stream the frozen sources and enforce B4's source-aware numeric contract.
Main PRICE values/anchors/lags require availability<=issue; physical fields use
their end+5 proxy. Retain assembler FINAL3's common source relations and
arm-pure schema semantics, with NRX metadata clocks explicitly retaining their
original identities; a creation-clock surrogate is not proof of publication.
Source coverage under the author-fixed July27 onward eligibility remains
conditional on DATA26's saved sources, not a complete public-notice certificate.

## E3 only, post-freeze

P5MIN may enter only secondary NP/NPL/NPP. Bind the DATA26 P5MIN strict-reader
freeze and source manifest first; use the existing B5/E3 run-time/target-time/
region join and availability gate. Forecast runs must be available at the issue,
with no future run or realized target field admitted. DATA26 reports complete
keys but has not inspected forecast values or LASTCHANGED clocks; execution must
validate them under the unchanged E3 contract. A missing legal E3 input blocks
E3, never changes the main N keys or imports P5MIN to the independent baseline.

## Connected severe events: descriptive only, after the prediction seal

The fixed event rule is the existing `regional_clusters` /
`assign_system_events` in
`/Users/stacchining/Documents/thesis/lamp-moe-research/scripts/pivot_az/audit_historical_support.py`,
SHA-256 `91d09205238aba52e6655a0c31597d3e3cbdd15c6e0ce070471609374e554b14`.
This is a project diagnostic with no claimed top-venue template. After all
registered predictions are sealed, read the already frozen five-minute PRICE
targets and retain **price>5000** severe intervals (strict inequality). Within
each region, start a new cluster only when consecutive severe intervals are
more than **30 minutes** apart. Link two regional clusters when their time
spans overlap or lie within **30 minutes**, and their regions are the same or
directly connected by one of the fixed undirected edges **QLD1–NSW1,
NSW1–VIC1, VIC1–SA1, VIC1–TAS1**. Connected system events are the transitive
union of these links, sorted by first start and region for stable IDs. Do not
reuse historical event IDs or adjust the threshold/link rule from window results.

Generate events separately inside the fixed news March1..September30 and
notice August1..September30 target intervals, using all five source-backed regions for the event graph; news losses attach
only NSW1/QLD1/TAS1 forecast keys, and notice losses attach all five. No event outside the registered
target interval is appended, and boundary-truncated components are flagged.
For news, admit a five-minute event interval iff its **interval start** lies in
[2026-03-01 00:00, 2026-10-01 00:00) AEST: the interval-end grid is therefore
March1 00:05 through October1 00:00 inclusive. For notices, use the exact
registered **interval-end target grid** [2026-08-01 00:00, 2026-10-01 00:00)
AEST, ending September30 23:55. These distinct boundary rules follow each
task's pre-frozen target assignment; they are not selected from severe prices.
An event-level row lists its start/end, connected regions, severe-interval
count, unique matched target keys, maximum price, and each primary arm's paired
absolute-loss difference and reference-relative percentage on the matched keys.
For news, match a severe five-minute interval to the ordinary target hour
containing its **interval start**; for notices, match its exact interval-end
target and preserve all six horizons. Multiple severe intervals mapping to one
news hour do not duplicate the forecast key. Report the table even if it is
empty. No event-level p value, selected event exclusion, confidence claim, new
fit or primary-family reclassification follows this descriptive table.

## Frozen dependency boundary

Before any article/notice feature build or numeric value read, complete the
already specified new NEWSX v4 extraction and NRX source/receipt identities,
then freeze the final path/hash manifest and extraction failure IDs in a separate
execution input freeze that references CONF's immutable `FREEZE.json`. Pending
NRX results cannot be represented by a fake hash or mutable directory hash.
NEWSX contract/input normalization/host command and MiniLM revision/tokenizer
are specified by the main protocol and `FEATURE_SPEC_CONF.md`; this panel plan
does not select an alternative from extraction or forecast results. Pre-window
articles are extracted in the same fixed run. Any design change requires a
prospective amendment while the confirmation outcomes remain unopened.
