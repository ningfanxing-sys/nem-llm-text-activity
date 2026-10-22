"""Strict, outcome-blind activation of coordinator-frozen A8 amendment 2."""
import re
import copy
from a8_common import *

DRAFT = 'ADDENDUM_A8_AMENDMENT_2_DRAFT.md'
RECEIPT = 'ADDENDUM_A8_AMENDMENT_2_FREEZE.json'
CONTRIBUTION = "We compare LLM-extracted representations of one news source and of AEMO market notices with nested references that hold the numerical inputs and article or notice counts, under common admission and failure handling, beside cheap-text representations of the same documents and a price-only LEAR benchmark."
REASON = 'A8NR_RESOURCE_A8AM2'
RESOURCE_FORM = 'time and disk limits prevented running it before this version'
RENDERING = 'registered before scoring but not run'
ADMISSION_RULE = 'B2 (R8 notice, 6 fits, under 0.3 h) runs as registered, whenever the batch runs. B4 (R8 news, single seed) gets one admission decision at its own start, after B1–B3. The decision uses the frozen planning formula (A8.2(e)) at the realised speed ρ of the A8BATCH ledger, plus the projected DLY8-R8 runtime. B4 is admitted only if the projected end of B4, plus DLY8-R8, plus the SEAL_A8BATCH steps, is no later than 2026-10-05T18:00Z (2026-10-06 05:00 AEDT). Otherwise B4 reads "registered before scoring but not run" with A8NR_RESOURCE_A8AM2. The decision, its inputs and the projection are written to the batch ledger before any B4 fit. It uses no prediction, loss or outcome. DLY8-R8 needs only the sealed B2 notice models, so it runs whenever B2 completed. R8S is not run (author default single seed).'
AUTHOR_CONDITION = 'A8NR_AUTHOR applies only to R8S, under record 1 choices.r8_seeds = single, the author default single-seed choice. It never applies to B4 or B2. No r8_deferral approval is requested or inferred.'
JOURNAL = 'Only if B4 was not admitted, before any journal submission run the complete frozen A8.1 R8 news and notice families, and DLY8-R8 at delta 0, 5, 15 and 60 minutes; R8S only if separately authorised three seeds. Use seed 20260919 (extra seeds 20260920 and 20260921 only for that authorised variant). Use a separately reviewed, frozen and timestamped journal execution wrapper: the sole permitted code change is a new state root and orchestration, importing the frozen R8 builder, worker, DLY8 rebuild and scorer functions unchanged by hash/AST. Run whole stages to completion without time dropping, record wall time, bind DLY8-R8 to the journal R8 seal, and score with frozen functions at B=100,000. Bind the metadata manifest and training-only Notice Type list frozen before T4B; create new journal-only receipts and seals without overwriting arXiv evidence. Disclose execution after the arXiv CONF score with timestamps, seeds, code and adapter identities, all outcomes and deviations; retain the arXiv registered-not-run reading. This amendment does not authorise journal production.'
METADATA = 'Build the R8 metadata-only manifest and training-only Notice Type list with A8BATCH/A8BATCHFIX4/code/r8_manifest.py before batch freeze and T4B. Bind builder, config, metadata source identities, explicit frozen source coverage and deterministic type mapping. Batch inputs and T4B list all three files: R8_METADATA_MANIFEST.json, NOTICE_TRAINING_TYPES.json and R8_BUILD_RECEIPT.json, plus their immutable config, builder, source and coverage identities. T4B also lists batch-code freeze, amendment-2 draft/helper/activation-code/freeze receipt and author record 1.'
CHANGES = {'A8.1.R8': 'B2 runs; B4 has result-independent time admission under R12b', 'scope': ['R8_news', 'R8S'], 'admission_rule': 'B2 (R8 notice, 6 fits, under 0.3 h) runs as registered, whenever the batch runs. B4 (R8 news, single seed) gets one admission decision at its own start, after B1–B3. The decision uses the frozen planning formula (A8.2(e)) at the realised speed ρ of the A8BATCH ledger, plus the projected DLY8-R8 runtime. B4 is admitted only if the projected end of B4, plus DLY8-R8, plus the SEAL_A8BATCH steps, is no later than 2026-10-05T18:00Z (2026-10-06 05:00 AEDT). Otherwise B4 reads "registered before scoring but not run" with A8NR_RESOURCE_A8AM2. The decision, its inputs and the projection are written to the batch ledger before any B4 fit. It uses no prediction, loss or outcome. DLY8-R8 needs only the sealed B2 notice models, so it runs whenever B2 completed. R8S is not run (author default single seed).', 'journal_requirement': 'Only if B4 was not admitted, before any journal submission run the complete frozen A8.1 R8 news and notice families, and DLY8-R8 at delta 0, 5, 15 and 60 minutes; R8S only if separately authorised three seeds. Use seed 20260919 (extra seeds 20260920 and 20260921 only for that authorised variant). Use a separately reviewed, frozen and timestamped journal execution wrapper: the sole permitted code change is a new state root and orchestration, importing the frozen R8 builder, worker, DLY8 rebuild and scorer functions unchanged by hash/AST. Run whole stages to completion without time dropping, record wall time, bind DLY8-R8 to the journal R8 seal, and score with frozen functions at B=100,000. Bind the metadata manifest and training-only Notice Type list frozen before T4B; create new journal-only receipts and seals without overwriting arXiv evidence. Disclose execution after the arXiv CONF score with timestamps, seeds, code and adapter identities, all outcomes and deviations; retain the arXiv registered-not-run reading. This amendment does not authorise journal production.', 'FILL3f': 'registered before scoring but not run', 'forms.A8CONTRIB1_when_B4_not_admitted': None, 'A8NR_AUTHOR_condition': 'A8NR_AUTHOR applies only to R8S, under record 1 choices.r8_seeds = single, the author default single-seed choice. It never applies to B4 or B2. No r8_deferral approval is requested or inferred.', 'forms.A8NR_RESOURCE_A8AM2': 'time and disk limits prevented running it before this version', 'r8_metadata_manifest_status': 'Build the R8 metadata-only manifest and training-only Notice Type list with A8BATCH/A8BATCHFIX4/code/r8_manifest.py before batch freeze and T4B. Bind builder, config, metadata source identities, explicit frozen source coverage and deterministic type mapping. Batch inputs and T4B list all three files: R8_METADATA_MANIFEST.json, NOTICE_TRAINING_TYPES.json and R8_BUILD_RECEIPT.json, plus their immutable config, builder, source and coverage identities. T4B also lists batch-code freeze, amendment-2 draft/helper/activation-code/freeze receipt and author record 1.', 'coordinator_order': 'author record 1 (2026-10-04T10:13:19Z, already recorded before this amendment) → R8 manifest build → batch freeze → scorer freeze (after FILL3f/interface freeze) → amendment-2 freeze → T4B', 'other_rule_changes': False}
CHANGES["forms.A8CONTRIB1_when_B4_not_admitted"] = CONTRIBUTION
PARENT_HASHES = {'A8_FREEZE.json':'80e95c8db2c85ca38490f443612cda30d7ff33124f33ed87b70d8f8317909162',
                'RULES_FOR_FILL3F.json':'a7490266709a5607f424154635b77bb8fafcc2139d705541612fa7ed7b00b048',
                'ADDENDUM_A8_AMENDMENT_1_FREEZE.json': None}

def strict_text(value):
    def pairs(items):
        out = {}
        for k,v in items:
            require(k not in out,'Duplicate amendment key: '+k)
            out[k] = v
        return out
    def invalid(value):
        raise RuntimeError('Nonfinite amendment JSON: '+value)
    return json.loads(value,object_pairs_hook=pairs,parse_constant=invalid)

def strict(path):
    return strict_text(Path(path).read_text())

CANONICAL_BODY_SHA256 = '874aa15be66540d36fc9611700cff3250813b37db2413805e4822e06c64643ea'

def draft_path(here=CONF/'A8'):
    return OUT/'amendment2'/DRAFT if Path(here).resolve() == (CONF/'A8').resolve() else Path(here)/DRAFT

def validate_body(path):
    require(sha(path) == CANONICAL_BODY_SHA256,'Amendment 2 complete canonical body drift')
    return Path(path).read_text()

def record(here=CONF/'A8', helper=OUT/'freeze_a8_amendment2.py'):
    here = Path(here)
    binds = {}
    for name,digest in PARENT_HASHES.items():
        item = identity(here/name)
        require(digest is None or item['sha256'] == digest,'Amendment 2 parent identity drift: '+name)
        binds[name] = item
    parent = CONF/'A8'
    helper1 = module(parent/'freeze_a8_amendment1.py','_a8am2_parent_verify')
    helper1.verify(here/'ADDENDUM_A8_AMENDMENT_1_FREEZE.json',here=parent)
    text = validate_body(draft_path(here))
    require(all(rule in text for rule in (ADMISSION_RULE,CONTRIBUTION,RESOURCE_FORM,AUTHOR_CONDITION,JOURNAL,METADATA)),'Amendment 2 verbatim prose rule/form drift')
    blocks = re.findall(r'```json\n(.*?)\n```',text,re.S)
    require(len(blocks) == 1 and strict_text(blocks[0]) == CHANGES,'Amendment 2 must contain every exact declared deferral/form/author/journal/metadata rule')
    rules = strict(parent/'RULES_FOR_FILL3F.json')
    form = rules['forms']['A8CONTRIB1']
    require(form.replace(' (and, secondarily, richer source metadata)','') == CONTRIBUTION,'Contribution replacement derivation drift')
    require(len(RESOURCE_FORM.split()) <= 12,'Resource reason exceeds frozen word limit')
    author=identity(CONF/'AUTHOR_CONFIRMATION_A8.json')
    author_record=read_json(checked(author))
    require(author['sha256']=='60898ed6b0265eca32eb6522f2e4e2d1b9e09dab97e871e93360f31fec193e44', 'Existing author record 1 identity drift')
    require(author_record['recorded_utc']=='2026-10-04T10:13:19Z', 'Existing author record 1 chronology drift')
    require(author_record['choices']['r8_seeds']=='single','R8S author default requires record 1 single seed')
    return dict(schema='A8_AMENDMENT_2_V1',state='A8_AMENDMENT_2_FROZEN_BEFORE_SCORING',
                frozen_by='coordinator from verified dry-run; separate timestamp/chronology verification required',
                frozen_utc=now(),before_any=['T4B','T5','CONF score'],
                files=[identity(draft_path(here)),identity(helper),identity(Path(__file__))],
                binds=binds,author_record1=author,author_record1_recorded_utc=author_record['recorded_utc'],changes=copy.deepcopy(CHANGES),other_rule_changes=False,
                outcome_access='none; draft and local parent identities only')

def verify(path,here=CONF/'A8',helper=OUT/'freeze_a8_amendment2.py'):
    require(Path(path).resolve() == (Path(here)/RECEIPT).resolve(),'Amendment 2 receipt must be at its effective path')
    frozen = strict(path)
    expected = record(here,helper)
    require(set(frozen) == set(expected),'Amendment 2 field set differs')
    for k in expected:
        require(k == 'frozen_utc' or frozen[k] == expected[k],'Amendment 2 receipt drift: '+k)
    require(isinstance(frozen['frozen_utc'],str),'Amendment 2 freeze time invalid')
    try:
        stamp = dt.datetime.fromisoformat(frozen['frozen_utc'].replace('Z','+00:00'))
    except (ValueError,TypeError) as exc:
        raise RuntimeError('Amendment 2 freeze time invalid') from exc
    require(stamp.utcoffset() == dt.timedelta(0),'Amendment 2 freeze time must be UTC')
    require(stamp > dt.datetime.fromisoformat(expected['author_record1_recorded_utc'].replace('Z','+00:00')), 'Amendment 2 must follow existing author record 1')
    return frozen

def r8_policy(here=CONF/'A8',helper=OUT/'freeze_a8_amendment2.py'):
    path = Path(here)/RECEIPT
    if not path.exists():
        return dict(run=True,amendment=None,reason=None,execution_ready=False)
    verify(path,here,helper)
    return dict(run=True,admission_rule='R12b',amendment=identity(path),reason=REASON,rendering=RENDERING)

def author_reason(author,draft=CONF/'A8'/DRAFT,stage=None):
    # No arbitrary words/choice_index can manufacture author approval of B4.
    if stage == 'R8_news_seeds' and author.get('choices',{}).get('r8_seeds') == 'single':
        return 'A8NR_AUTHOR'
    return REASON
