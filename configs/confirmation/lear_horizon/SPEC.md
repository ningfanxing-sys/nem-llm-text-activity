# CONFX8B：seal-only LEAR horizon lossless dtype supplement

[KEEP_ACTIVE] Additive execution amendment to CONFX8. Preparation writes only this
directory and synthetic scratch. The coordinator freezes and timestamps this
supplement before any production seal. This document is not a freeze receipt.

## Binding reason and adoption

Binding source: `../CONFX8/SEAL_DIAG_REPORT_zh.md`, proposal A:

> 只在 `source == 'lear'` 分支，将已验证为完整 0–23 整数的 `horizon` 无损转换为 canonical news 的 `int16`，随后继续所有既有严格检查。

The same report says:

> 不得称为纯 resource-limit change。

This is an execution IO/key serialization amendment, with resource admission
guards, and no statistical change. It is a post-fit, pre-score supplement, not a
fit-time preregistration or an amendment of resource limits. Its authorisation is
the explicit CONFX8B task selecting proposal A and an in-process wrapper calling
`cli.main(['seal'])`. That task supersedes A's suggested directory, independent
seal copy, and T4C label: use CONFX8B, the original frozen seal with a temporary
coerce wrapper, and **T4S**. No author signature, blind-review adjudication, freeze,
trusted timestamp or production success is claimed during preparation. Retain
SEALDIAG's exposure disclosure; this engineering task does not adjudicate it.

SEALDIAG is the source for 15,408 matched keys, int16 canonical news versus int64
LEAR, equal values/order/dates. This task does not reread those real keys or any
CONF prediction, truth, price, score or human-review workbook. Static identities
are pinned in SOURCE_IDENTITIES.json, with the installed ADAPTER_FREEZE identity
taken from CONFX8/AMENDED_ADAPTER_CHAIN.json and cli/seal identities taken from the
existing installed freeze. Exact bytes and AST of those files remain unchanged.

## Exact scope and refusals

`seal_lear_horizon.py` is the only new production entrypoint. First verify the
installed ADAPTER_FREEZE.json, cli.py and seal_score.py; verify this additive
freeze, its test receipts and parent evidence; cryptographically verify both
existing timestamp authorities' T4S replies and supplement/parent coverage.
Imports disable bytecode. The frozen runtime still validates its entire original
CONFX3–CONFX8 chain and all original permit/input gates inside cli.dispatch.
CONFX8B does not alter runtime.AMENDMENT_CHAIN or the installed adapter freeze.

Only direct calls from the pinned `seal_score.seal` code object at its LEAR raw
coerce site (line 152) can cast. Canonical news must remain numpy int16 (line 140
and the LEAR site's canonical news object). Other arms/sources, validation,
normalize, verify_seal and score retain the original coerce behavior. A LEAR
numpy int16 frame is returned unchanged by the cast helper. Any other LEAR dtype
must be an integer dtype, nonmissing, every value in 0–23, and exactly equal to
the int16 cast converted back to its original dtype. Floating types, even values
that look integral, object/bool, nulls, out-of-range values and failed round trips
refuse. Integer nullable/unsigned types are allowed only under the same proof.

The only added data assignment is `result['horizon'] = converted`, in a shallow
copy after validation. The helper reads only horizon. No other column is accessed
or assigned, no row/index/order is changed, no new arithmetic touches a prediction.
The original coerce still performs its timestamp/day normalisation on its own
copy. The original exact KEYS/target_day comparison, complete grid, finite
prediction, model/scaling hashes, fit receipts, stage population, permit, audit,
host lock, immutable SEAL and retry verification all remain executed as before.
No fitting, subset, replacement benchmark, new clipping, weighting, contrast,
margin, seed, date, family, multiplicity or outcome/reading change is introduced.

Every actual cast is durably logged before the cast frame is passed to the
original coerce: source, arm, seed, variant, from_dtype, to_dtype, row_count and
UTC time, under CAST_LOG.json runs. Logging failure refuses through the original
CLI exception handler. Failed runs and their cast attempts remain in the log;
only a SUCCESS run asserts completion. A separate supplement lock serialises
log writers; the original CLI host lock remains authoritative for seal dispatch.
The original coerce is restored on every exit.

The only accepted cosmetic error is the exact `AttributeError: 'list' object has
no attribute 'get'` at the frozen cli.main code object, line 81, after run_cli's
call frame, with no dispatch/additional/chained exception frames, a completed
result local, and a newly existing SEAL.json. This is the in-process equivalent
of incident's module:84 → main:81 traceback; there is no module:84 frame when
calling main directly. Preexisting SEAL cannot justify suppressing that error.
Everything else propagates. No exception value that might contain study data
is copied into CAST_LOG; the original registered failure receipts are unchanged.

## Synthetic proof and host order

One lightweight test process, nice 5 (retain/use 20 if 5 refused), memory_pressure
free >=25% before and between tests, scratch <1 GB. The harness copies static
adapter Python sources into scratch; it never invokes production main, freeze,
seal, scoring or reads live host_state. In the replica it runs the actual frozen
CLI main/dispatch, seal, complete_grid, key/day/finite/model checks, file writes,
failure handler and lock on synthetic state. Synthetic plan/permit/reusable and
feature-location gates are replaced explicitly, not represented as production
validation. Full news/LEAR keys (15,408) retain the original complete_grid gate.
The unrelated notice canonical fixture is compact (30 keys); its fixture-only
admission asserts exact frame identity instead of the full notice calendar.
No claim of full notice-domain validation is made; no fit runs. An earlier
full-notice fixture attempt was interrupted at frozen complete_grid's datetime
formatting cost; TEST_ATTEMPT_1_INTERRUPTED.json preserves this preparation event.
The first completed suite then refused at an erroneously pinned line 153 instead
of 152; its six errors and receipts remain in test_attempt_2. The final suite
corrects only this wrapper guard, checks the call-site AST and requires the
specific frozen rejection message for key/day/finite/model faults.

Prove int64 LEAR fails the frozen seal then passes the wrapper; synthetic sealed
parquet bytes equal the frozen seal on the same LEAR candidate written int16;
prediction/raw_prediction float64 bits and all other columns remain unchanged;
N int16 output equals frozen baseline; float/null/range/key/day/time/finite/model
faults refuse; frozen file drift refuses; unrelated coerce callers are untouched;
cosmetic error handling is restricted; log IO and canonical dtype failures stop.
AST_SCOPE_PROOF records the helper's sole data assignment and unchanged installed
source/AST identities. Tests also reject supplement/T4S identity and certificate
failures using synthetic metadata and mocked cryptographic subprocess results.

Host sequence: run freeze_confx8b.py once → obtain **T4S**, roots
`CONF/CONFX8B CONF/CONFX8` → run this wrapper seal → check SEAL.json file existence
only. The wrapper writes supplemental execution provenance with SEAL existence,
not its content/hash. The frozen seal itself performs its registered opaque
hashes and finite prediction checks only during the later authorised host run.
Preparation does not run the freeze or trusted timestamp, create CAST_LOG, or
claim SEAL exists. Future score remains a separate registered operation.

## Interpretation and traceability

Passing synthetic proofs establishes serialization equivalence under the fixture,
not a production seal, production model validity or scientific result. Population
and all-or-unavailable rules remain unchanged. Actual LEAR, combinations and A4
caps remain governed by original gates after successful complete production seal;
no cap is declared removed in advance. Sources: COMMON_RULES.md and addendum;
CONFX8/SPEC.md, SEAL_DIAG_REPORT_zh.md, SEAL_DIAG_EXPOSURE.md,
AMENDED_ADAPTER_CHAIN.json, HOST_INCIDENT_20261004_fitbank_print.md;
CONFX2/ADAPTER_FREEZE.json, cli.py and seal_score.py; the existing
CONF/TIMESTAMPS/make_timestamp.py syntax/certificate verification.
