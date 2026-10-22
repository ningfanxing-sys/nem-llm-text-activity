'Apply the frozen loss calculations to synthetic test data.'
from __future__ import annotations
import argparse
import ast
from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
import re
import numpy as np

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]
START, END = '2026-05-19', '2026-09-30'
WINDOW_START = '2026-03-01'
CUTOFF = '2026-05-18'
RECORD_PATH = 'paper_plan/luna_cutoff_20261008/evidence/MODEL_CUTOFF_RECORD.json'
RECORD_SHA = 'd32e1da83ecbd9083dd43735edd3131357afeb03c8a4007254c33997f8797737'
PAGE_SHA = 'efb95e473a811ad36452a8b5f560e820b8b03bde18a9a462ba3b18348630d87f'
OFFICIAL_URL = 'https://developers.openai.com/api/docs/models/gpt-6-luna.md'
CUTOFF_QUOTE = 'May 18, 2026 knowledge cutoff'
PAIRS = (('L_count', 'M'), ('L_chen', 'M'))
PINS = {
    'studies/inference/code/read_comparisons.py': '4dbfbde7f54e31e5dd86ae6bcdbb8bd1b1764eba96cdc022090ac93601c9e6f6',
    'studies/confirmation/primary_tests/code/primary_comparisons.py': '3a913e58473abb10519afd10094477bf2d2ef62a1a1ccfdb76250f4f7229d32e',
    'studies/confirmation/code/scoring.py': '56c6a938a1537853b359a1f592e6b2b7f26fd5dfd491fc7f5705ec4d8852786f',
}
CLASSES = {'CONDITIONAL_IMPROVEMENT', 'CONDITIONAL_DETERIORATION',
           'NO_RELIABLE_INCREMENT_DETECTED', 'NOT_EVALUABLE'}
NOTICE_FACT = ("The notice window, 1 August to 30 September 2026, lies entirely after the "
               "vendor-stated 18 May 2026 knowledge cutoff of gpt-6-luna; the alias is "
               "unversioned, and the vendor statement does not verify the cutoff of the executed model.")
SUFFIX = ' This qualifier changes no primary class and cannot rescue a failed primary family.'


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def calendar_days(first, last):
    first, last = date.fromisoformat(first), date.fromisoformat(last)
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def official_evidence():
    raw = (PROJ / RECORD_PATH).read_bytes()
    if sha256_bytes(raw) != RECORD_SHA:
        raise PermissionError('Official cutoff record SHA-256 drift')
    record = json.loads(raw)
    page = (PROJ / 'paper_plan/luna_cutoff_20261008/evidence/luna_model.md').read_bytes()
    return record, page


def verify_evidence(record=None, page_bytes=None):
    official, saved = official_evidence()
    if record is None and page_bytes is None:
        record, page_bytes = official, saved
    if record != official or not isinstance(page_bytes, bytes):
        raise PermissionError('Exact official cutoff record identity is required')
    luna = record['records']['gpt-6-luna']
    required = dict(record_id='cutoff_luna', model='gpt-6-luna', url=OFFICIAL_URL,
                    quoted_sentence=CUTOFF_QUOTE, knowledge_cutoff=CUTOFF,
                    saved_page='luna_model.md', saved_page_sha256=PAGE_SHA,
                    saved_page_line=25)
    if any(luna.get(k) != v for k, v in required.items()) \
            or CUTOFF_QUOTE != 'May 18, 2026 knowledge cutoff' \
            or sha256_bytes(page_bytes) != PAGE_SHA \
            or page_bytes.decode('utf-8').splitlines()[24] != '- ' + CUTOFF_QUOTE:
        raise PermissionError('Official cutoff fields, exact quote or page identity conflict')
    return dict(url=luna['url'], quote=luna['quoted_sentence'], sha256=PAGE_SHA,
                cutoff=luna['knowledge_cutoff'], model=luna['model'],
                source_record=RECORD_PATH, source_record_sha256=RECORD_SHA,
                unversioned_alias=True, vendor_statement_only=True)


def day_set(record=None, page_bytes=None):
    evidence = verify_evidence(record, page_bytes)
    first = max(date.fromisoformat(WINDOW_START),
                date.fromisoformat(evidence['cutoff']) + timedelta(days=1))
    days = calendar_days(first.isoformat(), END)
    if len(days) != 135 or days[0] != START or days[-1] != '2026-09-30':
        raise PermissionError('Cutoff-derived days conflict with specified constants')
    return days


def identity_machinery():
    'Read the checked JSON and hash-validation functions.'
    return _ast_load('studies/inference/code/read_comparisons.py',
                     ('sha256', 'checked', 'strict_json'), (),
                     dict(Path=Path, hashlib=hashlib, re=re, json=json,
                          require=_require, Refusal=PermissionError))


def _require(ok, message):
    if not ok:
        raise PermissionError(message)


def verify_identity(payload, identity):

    _require(isinstance(payload, dict) and payload.get('synthetic') is True,
             'Production closed: official inputs require the inference V2 timestamp_checks chain')
    gate = identity_machinery()

    def checked_fixture(item):
        _require(isinstance(item, dict) and isinstance(item.get('path'), str),
                 'Synthetic path/hash identity required')
        _fixture_path(item['path'])
        return gate.checked(item)

    manifest = gate.strict_json(checked_fixture(identity))
    _require(manifest.get('schema') == 'PCN_SYNTHETIC_AUTHORITY_V1'
             and manifest.get('synthetic') is True, 'Explicit synthetic timestamp_checks required')
    items = manifest.get('inputs', {})
    _require(set(items) == {'payload', 'primary', 'receipt'}, 'Synthetic timestamp_checks roles mismatch')
    receipt = gate.strict_json(checked_fixture(items['receipt']))
    _require(receipt.get('schema') == 'PCN_SYNTHETIC_RECEIPT_V1'
             and receipt.get('synthetic') is True, 'Synthetic receipt required')
    allowed = {(i['path'], i['sha256']) for i in receipt.get('files', [])}
    for role in ('payload', 'primary'):
        item = items[role]
        _require((item['path'], item['sha256']) in allowed, 'Input not receipt-bound: ' + role)
    specified = gate.strict_json(checked_fixture(items['payload']))
    primary = gate.strict_json(checked_fixture(items['primary']))
    _require(specified == payload, 'Receipt-bound complete payload mismatch')
    _require(primary == payload.get('primary'), 'Specified primary identity mismatch')
    _require(payload.get('issue_days') == calendar_days(WINDOW_START, END),
             'Specified full-window support must be exactly 214 issue days')
    return dict(schema='PCN_SYNTHETIC_VERIFIED_IDENTITY_V1', synthetic=True,
                manifest=dict(identity), inputs=items, official_authority=False,
                mechanism='inference checked/strict_json + manifest SHA + receipt path/hash membership')


def _ast_load(relative, names, constants, namespace):
    path = PROJ / relative
    source = path.read_bytes()
    if sha256_bytes(source) != PINS[relative]:
        raise PermissionError('Frozen source drift: ' + relative)
    tree = ast.parse(source, filename=str(path))
    selected = []
    found = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            selected.append(node); found.add(node.name)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id in constants:
            namespace[node.targets[0].id] = ast.literal_eval(node.value)
    if found != set(names) or not set(constants) <= namespace.keys():
        raise PermissionError('Frozen pure-function census mismatch')
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), namespace)
    return SimpleNamespace(**namespace)


def frozen_machinery():
    'Extract the frozen numerical functions after checking their source hashes.'
    env = dict(np=np, math=math, date=date)
    sc = _ast_load('studies/confirmation/code/scoring.py',
                   ('dm_daily', 'holm', 'block_picks', 'paired_percent_interval'),
                   ('BOOTSTRAP_DRAWS', 'BOOTSTRAP_SEED', 'NEWS_FAMILY'), env.copy())
    a2 = _ast_load('studies/confirmation/primary_tests/code/primary_comparisons.py',
                   ('finite', 'hln_p', 'decision_class', 'family_quantiles', 'complete_picks',
                    'subset_picks', 'contrast_stats', 'family_inference', 'json_safe'),
                   ('ALPHA',), dict(env, Path=Path))
    if sc.NEWS_FAMILY != PAIRS or sc.BOOTSTRAP_DRAWS != 2000 \
            or sc.BOOTSTRAP_SEED != 20260925 or a2.ALPHA != .05:
        raise PermissionError('Frozen inference parameters drift')
    return sc, a2


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def relation(primary, subset):

    if primary.get('class') not in CLASSES or not finite(primary.get('mean_difference')) \
            or primary['class'] == 'NOT_EVALUABLE':
        return 'NOT_EVALUABLE', 'the full-window primary reading was not evaluable'
    if subset.get('state') != 'COMPUTED':
        return 'NOT_EVALUABLE', 'a required frozen daily loss series was unavailable'
    if not finite(subset.get('reference_mae')) or subset['reference_mae'] <= 0:
        return 'NOT_EVALUABLE', 'the post-cutoff reference mean absolute error was not positive'
    if subset.get('decision') == 'NOT_EVALUABLE' or not finite(subset.get('mean_difference')):
        return 'NOT_EVALUABLE', 'the post-cutoff daily test variance was undefined'
    p, s = primary['mean_difference'], subset['mean_difference']
    if p == 0 or s == 0:
        return 'NO_DIRECTION', None
    if (p < 0) != (s < 0):
        return 'OPPOSITE_DIRECTION', None
    if primary['class'] == subset['decision']:
        return 'SAME_DIRECTION_SAME_CLASS', None
    if subset['decision'] == 'NO_RELIABLE_INCREMENT_DETECTED':
        return 'SAME_DIRECTION_WEAKER_CLASS', None
    return 'SAME_DIRECTION_STRONGER_COMPARISON_CLASS', None


def sentence(arm, state, reason=None):
    lead = f'For {arm} versus M, the post-cutoff news reading on issue days 19 May to 30 September 2026 '
    endings = {
        'SAME_DIRECTION_SAME_CLASS': 'has the same direction and the same comparison class as the full-window reading.',
        'SAME_DIRECTION_WEAKER_CLASS': 'has the same direction but a weaker comparison class than the full-window reading.',
        'OPPOSITE_DIRECTION': 'has the opposite direction to the full-window reading.',
        'SAME_DIRECTION_STRONGER_COMPARISON_CLASS': 'has the same direction but a stronger comparison class than the full-window reading; it supplies no upgrade of the primary claim.',
        'NO_DIRECTION': 'has no directional comparison because at least one mean loss difference is zero.',
    }
    if state == 'NOT_EVALUABLE':
        if not reason:
            raise ValueError('Not-evaluable sentence must name its reason')
        return lead + 'is not evaluable because ' + reason + '.' + SUFFIX
    return lead + endings[state] + SUFFIX


def run_reading(payload, identity, evidence_record, evidence_page):
    'Compute the cutoff-based comparison on synthetic test data.'
    frozen_identity = verify_identity(payload, identity)
    _require(isinstance(evidence_record, dict) and isinstance(evidence_page, bytes),
             'Official record and page bytes are required')
    evidence = verify_evidence(evidence_record, evidence_page)
    sc, a2 = frozen_machinery()
    days = payload.get('issue_days', [])
    if not isinstance(days, list) or any(not isinstance(d, str) for d in days):
        raise ValueError('ISO issue days are required')
    parsed = [date.fromisoformat(d) for d in days]
    if parsed != sorted(set(parsed)) or any(d.isoformat() != s for d, s in zip(parsed, days)):
        raise ValueError('Issue days must be canonical, unique and chronological')
    if any(d < date(2026, 3, 1) or d > date(2026, 9, 30) for d in parsed):
        raise ValueError('Input day outside the specified news window')
    losses = payload.get('losses')
    primary = payload.get('primary')
    if not isinstance(losses, dict) or not isinstance(primary, dict) or set(primary) != {a for a, _ in PAIRS}:
        raise ValueError('Both frozen primary comparison records are required')
    for values in losses.values():
        if not isinstance(values, list) or len(values) != len(days) \
                or any(not finite(x) or x < 0 for x in values):
            raise ValueError('Daily absolute losses must be complete finite nonnegative arrays')
    keep = day_set(evidence_record, evidence_page)
    missing = sorted(set(keep) - set(days))
    if missing:
        records = [{'arm': arm, 'reference': ref, 'state': 'NOT_EVALUABLE',
                    'reason': 'required post-cutoff issue days were missing from the frozen daily losses',
                    'missing_days': missing} for arm, ref in PAIRS]
    else:
        indices = {d: i for i, d in enumerate(days)}
        sub = {arm: np.asarray([values[indices[d]] for d in keep]) for arm, values in losses.items()}
        fam = a2.family_inference(sc, sub, PAIRS, keep, m=1, subset=True)
        records = []
        for r in fam['reports']:
            state, reason = relation(primary[r['arm']], r)


            clean = {k: v for k, v in r.items() if k not in {
                'decision', 'hln_decision', 'hac7_decision', 'holm_p', 'hln_holm_p', 'hac7_holm_p'}}
            records.append(dict(arm=r['arm'], reference=r['reference'], state=state, reason=reason,
                                statistics=a2.json_safe(clean)))
    for r in records:
        r['sentence'] = sentence(r['arm'], r['state'], r.get('reason'))
    return dict(schema='PCN_READING_PAPER_V1', synthetic=payload.get('synthetic') is True,
                role='DESCRIPTIVE_QUALIFIER', confirmatory_class_allowed=False,
                primary_class_changed=False, six_inferential_check=False,
                issue_days=keep, n_days=len(keep), input_identity=frozen_identity,
                evidence=evidence, source_pins=PINS,
                inference_parameters=dict(m=1, subset=True, bootstrap_draws=2000,
                                          bootstrap_seed=20260925, blocks=[1, 7], alpha=.05),
                readings=records, sentence=' '.join(r['sentence'] for r in records))


def _fixture_path(value):
    path = Path(value).resolve()
    if not (path.is_relative_to(HERE) or path.is_relative_to(Path('/private/tmp'))):
        raise PermissionError('Fixture CLI reads only task-owned or /tmp files')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic-fixture', required=True, help='JSON fixture envelope; no production path accepted')
    parser.add_argument('--fixture-manifest-sha256', required=True, help='Expected synthetic timestamp_checks manifest digest')
    parser.add_argument('--output', required=True, help='Task-owned JSON output')
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    if not output.is_relative_to(HERE) or output.exists():
        raise PermissionError('Output must be a new file in the task directory')
    envelope = json.loads(_fixture_path(args.synthetic_fixture).read_text())
    if envelope.get('schema') != 'PCN_SYNTHETIC_FIXTURE_V1' or envelope.get('payload', {}).get('synthetic') is not True:
        raise PermissionError('Pre-score CLI refuses non-synthetic inputs')
    ident = envelope.get('input_identity')
    _require(isinstance(ident, dict) and ident.get('sha256') == args.fixture_manifest_sha256,
             'Expected synthetic manifest SHA mismatch')
    record = envelope.get('cutoff_record')
    page = envelope.get('cutoff_page_utf8')
    result = run_reading(envelope['payload'], envelope.get('input_identity'), record,
                         page.encode() if isinstance(page, str) else None)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(result['sentence'])


if __name__ == '__main__':
    main()
