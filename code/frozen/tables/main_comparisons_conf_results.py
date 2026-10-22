#!/usr/bin/env python3
"""FILL3b: pre-score prefill and frozen results fill under the fourth pre-score addendum (SPEC_FILL3B.md).

Pre-score (one source for PREFILL and fill):
    python manuscript_tex/fill3b_conf_results.py --prefill [--coverage F]      # writes the FILL3b PREFILL
    python manuscript_tex/fill3b_conf_results.py --check-prefill [--coverage F]
After scoring (cli.py score -> a2_postscore.py -> a3_postscore.py -> a4_postscore.py --positive-control .. --pcx ..):
    python manuscript_tex/fill3b_conf_results.py --apply --build
    python manuscript_tex/fill3b_conf_results.py --apply --refill --build     # later inputs

FILL3b imports the frozen FILL3a module read-only (FILL3A_FREEZE.json verified), through it FILL3, FILL2, A2 and A3, and
the frozen A4 module after its four freezes verify. Every A4 sentence is re-derived in memory by the frozen
`a4_postscore.run(..., strict=True)` and rendered verbatim (LaTeX conversion and arm-symbol mapping only). FILL3a, FILL3
and FILL2 are never run.
"""
from __future__ import annotations

import argparse
from collections import Counter, OrderedDict
import csv
from datetime import datetime, timezone
import difflib
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np

MS = Path(__file__).resolve().parent
PROJ = MS.parent
LAMP = Path('/Users/stacchining/Documents/thesis/lamp-moe-research')
Q1 = PROJ / 'autopilot/q1_audits'
CONF = Q1 / 'CONF'
A2DIR, A3DIR, A4DIR = CONF / 'A2', CONF / 'A3', CONF / 'A4'
PCXDIR = A4DIR / 'PCX'
DEFAULT_STATE = CONF / 'CONFX2/host_state'
DEFAULT_TS = CONF / 'TIMESTAMPS'
DEFAULT_COVERAGE = A3DIR / 'results/NEWS_MATCHED_COVERAGE.json'
DEFAULT_PC = PCXDIR / 'results/run/RESULT_POSITIVE_CONTROL.json'
DEFAULT_PCX = PCXDIR / 'results/run_null_ext/RESULT_PC_NULL_EXTENSION.json'
DEFAULT_PCX_FREEZE = PCXDIR / 'PCX_FREEZE.json'
DEFAULT_PCX_ARGS = PCXDIR / 'A4_INPUT_ARGS.json'
REVIEW_DIR = PROJ / 'reports/llm_text_quality_completion_20260928/confirmation_review_2026'
FREEZE_NAME = 'FILL3B_FREEZE.json'
SPEC_FREEZE_NAME = 'FILL3B_SPEC_FREEZE.json'
TEMPLATES_NAME = 'fill3b_templates.json'
TRACE_NAME = 'MS12_CONF_TRACE.csv'
RECEIPT_NAME = 'MS12_CONF_FILL_RECEIPT.json'
SNAPSHOT_NAME = 'previous_conf_prefill'
RUNS_ARCHIVE = 'previous_conf_fill3b_runs'
PREVIEW_NAME = 'qa/FILL3B_PREVIEW'
PREFILL_TRACE = 'FILL3B_PREFILL_TRACE.csv'
PREFILL_RECEIPT = 'qa/FILL3B_PREFILL_RECEIPT.json'
NOTE_PREFIX = 'FILL3 CONF fill (FILL3b)'          # kept by the unchanged finalize_MS12_trace.py (FILL[23] CONF fill)
PREFILL_NOTE = 'MS15 current locator; FILL3b prefill'
TAG = ' % numbers traced in ' + TRACE_NAME
TEMPLATES_REL = 'manuscript_tex/' + TEMPLATES_NAME
SOURCES = ('news', 'notice')
FILL3A_FREEZE_SHA256 = '3b3c45b2c29dcb63e0c596cc4d1dd0c10eb4ba7e11341fa4b82e159455dd3c52'
A4_FREEZES = OrderedDict([('ADDENDUM_A4_FREEZE.json', '77a851ef2abc4a0e86a2058435e950d1f2ec6cb7d514c373197de0e48afc8d2a'),
                          ('ADDENDUM_A4_AMENDMENT_1_FREEZE.json', '12e77e818287d86aa67ab57c8b2eef122e0bfb1e283f28f2f196baece489d9a6'),
                          ('ADDENDUM_A4_AMENDMENT_2_FREEZE.json', '05a93d4096f924e54576da24db7e23aa1b6a10ea56f29bc914dac9ebe9127457'),
                          ('A4_CODE_AND_RULES_FREEZE.json', '26707746b984da091dda58eb52e9d050792e4f2a0c7df0bce14569ec1c0762b5')])
A4_MODULE_SHA256 = '324b4cc08ae1f38a8481a7cd3e27133034acc505cf32375c3c261e2caa60bb7b'
A4_RULES_SHA256 = '1b5dd0de949d09f62547988555ea05627058631a18a86d96a1206f4b1d461713'
MS_TEXT_SHA256 = 'bbbcf623bef7b53fe26fc613a2fa4e8fddfc030fe6568a2118d504ad44861235'
REAL_COVERAGE_SHA256 = '78cb6cf60e1d8a335f20aec0d6679e0a41b521d54c46234ad9ac3a213efc2154'
A4_CODE_REL = 'autopilot/q1_audits/CONF/A4/code/a4_postscore.py'
A4_RULES_REL = 'autopilot/q1_audits/CONF/A4/RULES_FOR_FILL3B.json'
A3_CODE_REL = 'autopilot/q1_audits/CONF/A3/code/a3_postscore.py'
GENERATED = {'primary': 'sections/conf_fill/fill3b_primary.tex', 'secondary': 'sections/conf_fill/fill3b_secondary.tex',
             'discussion': 'sections/conf_fill/fill3b_discussion.tex', 'conclusion': 'sections/conf_fill/fill3b_conclusion.tex',
             'supplement': 'supplement_sections/conf_fill/S7_fill3b.tex', 'execution': 'supplement_sections/conf_fill/S9_fill3b_execution.tex',
             'news_review': 'supplement_sections/conf_fill/S5_fill3b_news_review.tex',
             'nrx_review': 'supplement_sections/conf_fill/S6_fill3b_nrx_review.tex',
             'conf_review': 'supplement_sections/conf_fill/S8_fill3b_confirmation_review.tex',
             'agreement': 'supplement_sections/conf_fill/S8_fill3b_agreement.tex', 'forest_data': 'figures/conf_fill/fill3b_forest_data.csv'}
PUBLISHED = {'news': 'supplementary_data/news__CLIPPING.csv', 'notice': 'supplementary_data/notice__CLIPPING.csv'}
FIGURE = 'figures/conf_fill/fill3b_forest.pdf'
LINE_FREE = {'supplement_sections/S7_inference.tex'}
STAGE_TABLE_REF = 'S9.1'
REVIEW_CATEGORIES = {'news': ('news human review', 'news human check'), 'nrx': ('NRX human review',),
                     'conf': ('confirmation human review',), 'agreement': ('second annotator agreement',)}
ARM_RE = re.compile(r'(?<![A-Za-z0-9_])(L_chen_notice|L_count|L_chen|L_Laz|L14)(?![A-Za-z0-9_])')


class FillError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise FillError(message)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def rel_proj(path):
    path = Path(path).resolve()
    return str(path.relative_to(PROJ)) if path.is_relative_to(PROJ) else str(path)


def load_module(name, path):
    sys.dont_write_bytecode = True
    if name in sys.modules:
        require(Path(sys.modules[name].__file__).resolve() == Path(path).resolve(), f'Unexpected module {name}')
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ============================================================================= frozen dependencies
def load_fill3a():
    """FILL3a, imported read-only after FILL3A_FREEZE.json and every file and identity it binds verify (SPEC 1)."""
    path = MS / 'FILL3A_FREEZE.json'
    require(sha256(path) == FILL3A_FREEZE_SHA256, 'FILL3A_FREEZE.json identity drift')
    freeze = json.loads(path.read_text())
    for group in ('files', 'test_receipts'):
        for rel, digest in freeze[group].items():
            require(sha256(MS / rel) == digest, f'FILL3a frozen file drift: {rel}')
    for rel, digest in freeze['external_identities'].items():
        require(sha256(PROJ / rel) == digest, f'FILL3a external identity drift: {rel}')
    f3a = load_module('fill3a_conf_results', MS / 'fill3a_conf_results.py')
    f3a.FillError = FillError            # FILL3a, FILL3 and FILL2 checks raise FILL3b's refusal type (in memory only)
    return f3a


def load_a4():
    """The frozen A4 post-score module after its addendum, amendment and code-and-rules freezes and every bound file verify."""
    for name, digest in A4_FREEZES.items():
        require(sha256(A4DIR / name) == digest, f'{name} identity drift')
        for rel, ident in json.loads((A4DIR / name).read_text())['files'].items():
            require(sha256(A4DIR / rel) == ident['sha256'], f'Frozen A4 file drift: {rel}')
    require(sha256(A4DIR / 'code/a4_postscore.py') == A4_MODULE_SHA256, 'a4_postscore.py identity drift')
    require(sha256(A4DIR / 'RULES_FOR_FILL3B.json') == A4_RULES_SHA256, 'RULES_FOR_FILL3B.json identity drift')
    a4 = load_module('a4_postscore_fill3b', A4DIR / 'code/a4_postscore.py')
    return a4, json.loads((A4DIR / 'RULES_FOR_FILL3B.json').read_text())


class Templates:
    def __init__(self, path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text())

    def __getitem__(self, dotted):
        node = self.data
        for part in dotted.split('.'):
            node = node[part]
        return node

    def get(self, dotted, default=None):
        try:
            return self[dotted]
        except (KeyError, TypeError):
            return default


def templates():
    return Templates(MS / TEMPLATES_NAME)


F3A = None
F3MOD = None
F2MOD = None
A4MOD = None


def deps():
    """FILL3a (with FILL3/FILL2) and A4, loaded once."""
    global F3A, F3MOD, F2MOD, A4MOD
    if F3A is None:
        F3A = load_fill3a()
        F3MOD = F3A.load_fill3()
        F2MOD, _ = F3MOD.load_fill2()
        F3A.F2MOD, F3A.F3MOD, F3MOD.F2MOD = F2MOD, F3MOD, F2MOD
        A4MOD, _ = load_a4()
    return F3A, F3MOD, F2MOD, A4MOD


# ============================================================================= text helpers
def a4_tex(text, symbols=False):
    """LaTeX of one plain A4 sentence by FILL3a's mechanical map (no registration; prefill use)."""
    F3A_, _, _, _ = deps()
    return ''.join(p[1] for p in F3A_.a3_latex_parts(text, symbols))


def plain_text(tex):
    F3A_, _, _, _ = deps()
    return F3A_.plain_text(tex)


def mask(text):
    return re.sub(r'(?<!\\)%.*', '', text)


def ms_text_blocks():
    """Blocks 1 and 4 of the A4 manuscript text (hash-bound in the spec freeze)."""
    path = A4DIR / 'MS_TEXT_FOR_FILL3B.md'
    require(sha256(path) == MS_TEXT_SHA256, 'MS_TEXT_FOR_FILL3B.md identity drift')
    text = path.read_text()
    fences = re.findall(r'```latex\n(.*?)```', text, re.S)
    require(len(fences) == 2, 'MS_TEXT_FOR_FILL3B.md must hold exactly two LaTeX blocks (1 and 4)')
    return fences[0].rstrip('\n'), fences[1].rstrip('\n')


def hexcode(digest):
    return r'\texttt{' + '\\allowbreak '.join(digest[i:i + 16] for i in range(0, len(digest), 16)) + '}'


# ============================================================================= coverage
class Coverage:
    """News matched coverage computed before scoring (a3_postscore.py --coverage-only); SPEC 2.4 of FILL3a, 3.15 here."""

    def __init__(self, path):
        self.path = Path(path)
        self.data = None
        if not self.path.is_file():
            return
        raw = json.loads(self.path.read_text())
        data = raw.get('coverage', raw) if isinstance(raw, dict) else None
        require(isinstance(data, dict) and 'news' in data and 'notice' in data, 'News matched coverage file layout differs from the a3_postscore --coverage-only output')
        news = data['news']
        require(news.get('state') == 'COMPUTED', 'The pre-score news coverage must be computed (A4 section T rests on it)')
        for k in ('matched_keys', 'total_keys', 'days_with_matched_key', 'n_days', 'matched_share_percent'):
            require(k in news, f'Coverage news entry lacks {k}')
        require(abs(news['matched_share_percent'] - 100.0 * news['matched_keys'] / news['total_keys']) <= 1e-9, 'Coverage share differs from its counts')
        self.data = data
        self.sha256 = sha256(self.path)
        self.src = rel_proj(self.path)


def block1_text(cov):
    """A4 block 1 with the coverage numbers from the coverage file and identities H and I from the A4 code freeze."""
    block1, _ = ms_text_blocks()
    n = cov.data['news']
    vals = {'keys': f"{n['matched_keys']:,}", 'total': f"{n['total_keys']:,}", 'share': f"{n['matched_share_percent']:.1f}",
            'days': str(n['days_with_matched_key']), 'n_days': str(n['n_days'])}
    old = 'cover 216 of 15,408 keys (1.4\\%) on 3 of 214 days'
    require(block1.count(old) == 1, 'Block 1 coverage clause not found')
    text = block1.replace(old, f"cover {vals['keys']} of {vals['total']} keys ({vals['share']}\\%) on {vals['days']} of {vals['n_days']} days")
    if cov.sha256 == REAL_COVERAGE_SHA256:
        require(text == block1, 'Block 1 rendered from the real coverage file differs from MS_TEXT_FOR_FILL3B.md')
    code = json.loads((A4DIR / 'A4_CODE_AND_RULES_FREEZE.json').read_text())
    h, i = code['files']['code/a4_postscore.py']['sha256'], code['files']['RULES_FOR_FILL3B.json']['sha256']
    old_hi = 'records identity H (reading code) and identity I (reading-rule sheet).'
    require(text.count(old_hi) == 1, 'Block 1 identity clause not found')
    return text.replace(old_hi, f'records identity H (reading code) as {hexcode(h)} and identity I (reading-rule sheet) as {hexcode(i)}.')


# ============================================================================= prefill (SPEC 2)
def snapshot_check(manuscript, T, rels):
    snap = manuscript / T['prefill.snapshot']
    manifest = json.loads((manuscript / T['prefill.snapshot_manifest']).read_text())
    index = {e['path']: e['sha256'] for e in manifest['entries']}
    for rel in rels:
        require(rel in index, f'{rel} is not in the FILL3a snapshot manifest')
        require(sha256(snap / rel) == index[rel], f'FILL3a snapshot drift: {rel}')
    return snap


def identity_paragraph(snap_text, start):
    """The freeze-identity paragraph of an addendum file, verbatim (the line starting with `start`)."""
    lines = [l for l in snap_text.split('\n') if l.startswith(start)]
    require(len(lines) == 1, f'Identity paragraph not unique: {start[:40]}')
    return lines[0]


def bib_entry(text, key):
    m = re.search(r'(@\w+\{' + re.escape(key) + r',.*?\n\}\n?)', text, re.S)
    return m.group(1).rstrip('\n') if m else None


def prefill_texts(manuscript, T, coverage):
    """{rel: text} of every file the FILL3b prefill writes, generated from the FILL3a snapshot and the templates."""
    _, _, _, A4 = deps()
    require(coverage is not None and coverage.data is not None, 'News matched coverage file missing: the FILL3b prefill renders A4C0b and block 1 from it')
    edits = T['prefill.edits']
    files = sorted({e['file'] for e in edits} | set(T['prefill.bib_files']) | {T['prefill.bib_source'], 'supplement_sections/MS16_second_addendum.tex',
                                                                                'supplement_sections/MS17_third_addendum.tex'})
    snap = snapshot_check(manuscript, T, files)
    block1 = block1_text(coverage)
    _, block4 = ms_text_blocks()
    subs = {'<<BLOCK4>>': block4, '<<A4C0b>>': a4_tex(A4.coverage_sentence(coverage.data))}
    out = {}
    for e in edits:
        text = out.get(e['file'], (snap / e['file']).read_text())
        require(text.count(e['old']) == 1, f"Prefill anchor {e['id']} must occur exactly once in {e['file']}")
        new = e['new']
        for key in re.findall(r'<<A4:(\w+)>>', new):
            new = new.replace(f'<<A4:{key}>>', a4_tex(A4.SENTENCES[key]))
        for key, value in subs.items():
            new = new.replace(key, value)
        require('<<' not in new, f"Unresolved placeholder in prefill edit {e['id']}")
        out[e['file']] = text.replace(e['old'], new)
    idents = {'<<IDENT_MS16>>': identity_paragraph((snap / 'supplement_sections/MS16_second_addendum.tex').read_text(), 'The pre-code addendum freeze records identity A'),
              '<<IDENT_MS17>>': identity_paragraph((snap / 'supplement_sections/MS17_third_addendum.tex').read_text(), 'The pre-code addendum freeze records identity D'),
              '<<IDENT_MS18>>': identity_paragraph(block1, 'Identity G (fourth addendum)')}
    for rel, content in T['prefill.new_files'].items():
        require(not (snap / rel).exists(), f'Prefill new file already exists in the snapshot: {rel}')
        text = content.replace('<<BLOCK1>>', block1)
        for key, value in idents.items():
            text = text.replace(key, value)
        for key in re.findall(r'<<A4:(\w+)>>', text):
            text = text.replace(f'<<A4:{key}>>', a4_tex(A4.SENTENCES[key]))
        require('<<' not in text, f'Unresolved placeholder in prefill new file {rel}')
        out[rel] = text.rstrip('\n') + '\n'
    source_bib = (snap / T['prefill.bib_source']).read_text()
    for rel in T['prefill.bib_files']:
        text = out.get(rel, (snap / rel).read_text())
        added = []
        for key in T['prefill.bib_keys']:
            if bib_entry(text, key) is None:
                entry = bib_entry(source_bib, key)
                require(entry is not None, f'No verified bibliography entry for {key} in {T["prefill.bib_source"]}')
                added.append(entry)
        if added:
            out[rel] = text.rstrip('\n') + '\n\n' + '\n\n'.join(added) + '\n'
    cov_rows = coverage_trace_values(coverage)
    return out, cov_rows


def coverage_trace_values(coverage):
    n = coverage.data['news']
    return [(coverage.src, 'news.matched_keys', f"{n['matched_keys']:,}"), (coverage.src, 'news.total_keys', f"{n['total_keys']:,}"),
            (coverage.src, 'news.matched_share_percent (1 decimal)', f"{n['matched_share_percent']:.1f}"),
            (coverage.src, 'news.days_with_matched_key', str(n['days_with_matched_key'])), (coverage.src, 'news.n_days', str(n['n_days']))]


COVERAGE_LINE_MARKERS = ('its matched keys, computed before scoring from the input-side mask', 'matched keys, computed before scoring from the input-side mask, cover')


def prefill_trace(manuscript, T, texts, cov_rows):
    """Trace rows for every numeric token on a changed, new or shifted line of a prefill .tex file (FILL3a rule)."""
    F3A_, _, _, _ = deps()
    snap = manuscript / T['prefill.snapshot']
    prior = F3A_.prior_trace_rows(snap)
    supplied = {}
    for s in T['prefill.trace_supplied']:
        for n in s['numbers']:
            supplied[(s['file'], n)] = (s['source_file'], s['source_field'])
    file_sources = T['prefill.trace_sources']
    coverage_values = {v: (src, f) for src, f, v in cov_rows}
    rows, unresolved = [], []

    def carry(old_loc, token, new_loc, note):
        r = prior.get((old_loc, token))
        if r is None:
            return {'location': new_loc, 'number': token, 'source_file': 'manuscript_tex/' + T['prefill.snapshot'] + '/' + old_loc.rsplit(':', 1)[0],
                    'source_field': f"line {old_loc.rsplit(':', 1)[1]}; preserved literal {token}", 'note': PREFILL_NOTE + '; ' + note}
        return {'location': new_loc, 'number': token, 'source_file': r['source_file'], 'source_field': r['source_field'],
                'note': PREFILL_NOTE + '; ' + note + '; original note: ' + r['note'][:160]}

    for rel, text in sorted(texts.items()):
        if not rel.endswith('.tex'):
            continue
        old_lines = (snap / rel).read_text().split('\n') if (snap / rel).exists() else []
        new_lines = text.split('\n')
        matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            for k, j in enumerate(range(j1, j2)):
                line = new_lines[j]
                new_loc = F3A_.doc_prefix(rel) + f'{rel}:{j + 1}'
                if tag == 'equal':
                    i = i1 + k
                    if i == j:
                        continue
                    for tok in F3A_.trace_tokens(line):
                        rows.append(carry(f'{rel}:{i + 1}', tok, new_loc, 'unchanged line carried to its shifted line number'))
                    continue
                i = i1 + k if (tag == 'replace' and i1 + k < i2) else None
                old_line = old_lines[i] if i is not None else ''
                old_toks = F3A_.trace_tokens(old_line)
                for tok in F3A_.trace_tokens(line):
                    if tok in coverage_values and any(m in line for m in COVERAGE_LINE_MARKERS):
                        src, f = coverage_values[tok]
                        rows.append({'location': new_loc, 'number': tok, 'source_file': src, 'source_field': f,
                                     'note': PREFILL_NOTE + '; pre-score coverage from the input-side match mask (a3_postscore.py --coverage-only)'})
                    elif (rel, tok) in supplied:
                        src, f = supplied[(rel, tok)]
                        rows.append({'location': new_loc, 'number': tok, 'source_file': src, 'source_field': f, 'note': PREFILL_NOTE + '; frozen rule or fact value'})
                    elif tok in old_toks:
                        rows.append(carry(f'{rel}:{i + 1}', tok, new_loc, 'value unchanged on an edited line'))
                    elif rel in file_sources:
                        src, f = file_sources[rel]
                        rows.append({'location': new_loc, 'number': tok, 'source_file': src, 'source_field': f, 'note': PREFILL_NOTE + '; fixed text value'})
                    else:
                        unresolved.append(f'{rel}:{j + 1} {tok}')
    require(not unresolved, 'Prefill numbers without a trace origin: ' + '; '.join(unresolved[:20]))
    for r in rows:
        for source in r['source_file'].split(';'):
            source = source.strip()
            if source:
                require((Path(source) if Path(source).is_absolute() else PROJ / source).exists(), 'Prefill trace source missing: ' + source)
    unique, seen = [], set()
    for r in rows:
        key = tuple(r[k] for k in ('location', 'number', 'source_file', 'source_field', 'note'))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def prefill_outputs(manuscript, T, coverage):
    texts, cov_rows = prefill_texts(manuscript, T, coverage)
    rows = prefill_trace(manuscript, T, texts, cov_rows)
    header = ['location', 'number', 'source_file', 'source_field', 'note']
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header, lineterminator='\r\n')
    w.writeheader()
    w.writerows(rows)
    out = dict(texts)
    out[PREFILL_TRACE] = buf.getvalue()
    snap = manuscript / T['prefill.snapshot']
    base = (snap / 'MS15_TRACE.csv').read_bytes().decode()        # keep the csv module's CRLF line ends exactly
    out['MS15_TRACE.csv'] = base + ''.join(buf.getvalue().splitlines(keepends=True)[1:])
    return out, rows


def scan_text(name, plain, T, a4_banned, strict_codes=False, attribution=True, allow=(), skip=()):
    """Rendered-text rules of SPEC section 7 on one plain text; returns problems."""
    F3A_, _, _, _ = deps()
    for a in allow:
        plain = plain.replace(a, ' ')
    problems = []
    for pat in [b for b in F3A_.BANNED3 if b not in skip] + [re.escape(b) for b in T['banned_added']]:
        if re.search(pat, plain):
            problems.append(f'{name}: banned {pat!r}')
    for b in a4_banned:
        if b in plain:
            problems.append(f'{name}: A4 banned string "{b}"')
    for sig, pat in T['superseded_signatures'].items():
        scope = T['superseded_signature_scope'].get(sig)
        if scope and not any(name == s or name.startswith(s) for s in scope):
            continue
        if re.search(pat, plain):
            problems.append(f'{name}: superseded form {sig}')
    reg = plain
    for allowed in T['registered_allowed']:
        reg = re.sub(allowed, '', reg)
    if re.search(r'\bregistered\b', reg):
        problems.append(f'{name}: "registered" for a pre-specified rule')
    if strict_codes:
        m = F3A_.CODE_RE.search(plain)
        if m:
            problems.append(f'{name}: internal code {m.group(0)}')
        m = F3A_.PATH_RE.search(plain)
        if m:
            problems.append(f'{name}: internal path or file name {m.group(0)}')
    if attribution:
        affirm = plain
        for neg in T['attribution_negations']:
            affirm = re.sub(neg, '', affirm)
        for pat in (r'\bit is content-specific', r'content-specific increment', r'\bsemantic increment'):
            if re.search(pat, affirm):
                problems.append(f'{name}: attribution word {pat!r} (unreachable under A4)')
    return problems


def reach_new(reader, entries=('main.tex', 'supplement.tex')):
    """Reachable sources by \\input from the entry files of a text set (prefill: the new structure, not the snapshot's)."""
    seen = OrderedDict()

    def visit(rel):
        rel = rel if rel.endswith('.tex') else rel + '.tex'
        if rel in seen:
            return
        try:
            text = reader(rel)
        except FileNotFoundError:
            return
        seen[rel] = text
        for m in re.finditer(r'\\input\{([^}]*)\}', mask(text)):
            visit(m.group(1))
    for entry in entries:
        visit(entry)
    return seen


def prefill_scan(manuscript, outputs, T):
    """SPEC 2.3: rendered-text rules over the whole reachable PREFILL (comments masked)."""
    _, _, _, A4 = deps()
    snap = manuscript / T['prefill.snapshot']

    def reader(rel):
        return outputs[rel] if rel in outputs else (snap / rel).read_text()
    texts = reach_new(reader)
    problems = []
    for rel, text in texts.items():
        require(not rel.startswith(('audit_archive', 'previous_')), 'Reachable PREFILL source inside the archive or a snapshot: ' + rel)
        problems += scan_text(rel, plain_text(text), T, A4.BANNED_A4, strict_codes=False, skip=(r'is planned',))   # pre-score wording may say "planned" (FILL3a rule)
    for rel in ('supplement_sections/MS16_second_addendum.tex', 'supplement_sections/MS17_third_addendum.tex', 'supplement_sections/MS18_fourth_addendum.tex'):
        require(rel not in texts, 'An addendum text is still reachable from the journal supplement: ' + rel)
    return problems, sorted(texts)


def write_prefill(manuscript, coverage, check_only=False):
    T = templates()
    outputs, rows = prefill_outputs(manuscript, T, coverage)
    if check_only:
        diffs = [rel for rel, text in outputs.items() if not (manuscript / rel).is_file() or (manuscript / rel).read_bytes() != text.encode()]
        return {'state': 'PREFILL_EQUAL' if not diffs else 'PREFILL_DIFFERS', 'differs': diffs, 'trace_rows': len(rows)}
    problems, reachable = prefill_scan(manuscript, outputs, T)
    require(not problems, 'Prefill text check failed: ' + '; '.join(problems[:12]))
    manifest = json.loads((manuscript / T['prefill.snapshot_manifest']).read_text())
    index = {e['path']: e['sha256'] for e in manifest['entries']}
    last_receipt = manuscript / PREFILL_RECEIPT
    last = json.loads(last_receipt.read_text()).get('outputs_sha256', {}) if last_receipt.is_file() else {}
    for rel, text in outputs.items():                 # never overwrite a file edited after the FILL3a snapshot or the last FILL3b PREFILL
        path = manuscript / rel
        if path.exists():
            live = sha256(path)
            require(live in (hashlib.sha256(text.encode()).hexdigest(), index.get(rel), last.get(rel)),
                    f'{rel} differs from its FILL3a snapshot, from the last FILL3b PREFILL and from this PREFILL; the prefill refuses to overwrite it')
    written = {}
    for rel, text in outputs.items():
        path = manuscript / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
        written[rel] = sha256(path)
    receipt = {'state': 'FILL3B_PREFILL_WRITTEN', 'utc': datetime.now(timezone.utc).isoformat(), 'script_sha256': sha256(Path(__file__)),
               'templates_sha256': sha256(MS / TEMPLATES_NAME), 'snapshot_manifest_sha256': sha256(manuscript / T['prefill.snapshot_manifest']),
               'coverage': {'path': str(coverage.path), 'sha256': coverage.sha256}, 'ms_text_sha256': MS_TEXT_SHA256,
               'edits': [e['id'] for e in T['prefill.edits']], 'new_files': sorted(T['prefill.new_files']), 'trace_rows': len(rows),
               'reachable_sources_scanned': len(reachable), 'outputs_sha256': written}
    (manuscript / PREFILL_RECEIPT).parent.mkdir(parents=True, exist_ok=True)
    (manuscript / PREFILL_RECEIPT).write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


# ============================================================================= post-score inputs
class A4Post:
    """Hash-verified A4_POSTSCORE.json re-derived in memory by the frozen A4 module with strict=True (SPEC 3.14)."""

    def __init__(self, a4, scores, state, grid, optional, coverage, rerun=True):
        self.a4 = a4
        self.dir = Path(state).resolve() / 'a4_scored'
        self.path = self.dir / 'A4_POSTSCORE.json'
        receipt_path = self.dir / 'A4_POSTSCORE_RECEIPT.json'
        require(self.path.is_file() and receipt_path.is_file(), 'A4 post-score output missing: run CONF/A4/code/a4_postscore.py after a3_postscore.py')
        self.receipt = json.loads(receipt_path.read_text())
        require(self.receipt.get('state') == 'A4_POSTSCORE_COMPLETE', 'A4 receipt is not complete')
        self.sha256 = sha256(self.path)
        require(self.receipt['output']['sha256'] == self.sha256, 'A4 output hash differs from its receipt')
        require(self.receipt['seal_sha256'] == scores.seal_sha256, 'A4 output does not bind the CONF seal')
        require(self.receipt['module_sha256'] == A4_MODULE_SHA256 and self.receipt['addendum_freeze_sha256'] == A4_FREEZES['ADDENDUM_A4_FREEZE.json'],
                'A4 output was not produced by the frozen A4 module')
        for item in self.receipt['inputs_read']:
            require(sha256(item['path']) == item['sha256'], 'A4 input drift: ' + item['path'])
        self.data = json.loads(self.path.read_text())
        require(self.data.get('primary_decision_rule_changed') is False, 'A4 output does not attest an unchanged primary rule')
        require(self.data.get('seal_sha256') == scores.seal_sha256, 'A4 output seal identity differs')
        require(self.data.get('amendment_1_freeze_sha256') == A4_FREEZES['ADDENDUM_A4_AMENDMENT_1_FREEZE.json']
                and self.data.get('amendment_2_freeze_sha256') == A4_FREEZES['ADDENDUM_A4_AMENDMENT_2_FREEZE.json'], 'A4 output amendment identities differ')
        require(self.data.get('coverage_sha256') == coverage.sha256, 'A4 output was computed with a different coverage file than this fill')
        require(not self.data.get('consistency_violations'), 'A4 output records consistency violations: ' + '; '.join(self.data.get('consistency_violations') or []))
        for key, path in optional.items():
            recorded = self.data['optional_inputs'].get(key)
            now = sha256(path) if path is not None and Path(path).is_file() else None
            require(recorded == now, f'The A4 output was computed with a different {key} input than this fill ({recorded} vs {now}); re-run a4_postscore.py')
        self.src = rel_proj(self.path)
        self.rerun_state = 'NOT_RUN'
        if rerun:
            self.rederive(state, grid, optional, coverage)

    def rederive(self, state, grid, optional, coverage):
        a4 = self.a4
        with tempfile.TemporaryDirectory(prefix='fill3b_a4_rerun_') as tmp:
            try:
                fresh = a4.run(Path(state), out=Path(tmp) / 'a4', grid=grid, pc_path=optional['positive_control'], pcx_path=optional['pcx'],
                               a2batch_path=optional['a2batch'], a2label_path=optional['a2label'], coverage_path=coverage.path,
                               coverage_sha=coverage.sha256, strict=True)
            except a4.A4ConsistencyError as exc:
                raise FillError('A4 consistency (impossible state under the frozen design): ' + str(exc))
        norm = lambda v: json.loads(json.dumps(a4.A2.json_safe(v), sort_keys=True, allow_nan=False))  # noqa: E731
        saved = norm(self.data)
        fresh = norm(fresh)
        for key in sorted(set(saved) | set(fresh)):
            require(saved.get(key) == fresh.get(key), f'A4 {key} block differs from a fresh strict run of the frozen A4 module')
        self.rerun_state = 'EQUAL_TO_FRESH_STRICT_RUN'

    def task(self, source):
        return self.data['tasks'][source]


def check_pair_trace(agreement):
    """SPEC 3.17: contingency tables from pair_trace reproduce every per-field count, prevalence, po, pe and kappa."""
    F3A_, _, _, _ = deps()
    tables = {}
    g = agreement.data['groups']['ALL']
    trace = g.get('pair_trace') or []
    for corpus, m in g['metrics'].items():
        for field, e in m['fields'].items():
            pairs = [(t['author_code'], t['second_code']) for t in trace if t['corpus'] == corpus and t['field'] == field]
            require(len(pairs) == e['paired_n'], f'Agreement pair trace has {len(pairs)} pairs for {corpus} {field}, not {e["paired_n"]}')
            require(sum(a == b for a, b in pairs) == e['equal_n'], f'Agreement pair trace equal count differs for {corpus} {field}')
            ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
            for who, c in (('author', ca), ('second', cb)):
                prev = {k: v['count'] for k, v in e['prevalence'][who].items() if v['count']}
                require(dict(c) == prev, f'Agreement pair trace prevalence differs for {corpus} {field} ({who})')
            if pairs:
                n = len(pairs)
                po = sum(a == b for a, b in pairs) / n
                pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
                kap = None if math.isclose(pe, 1.0, abs_tol=1e-15) else (po - pe) / (1 - pe)
                require((kap is None and e.get('cohens_kappa') is None) or (kap is not None and e.get('cohens_kappa') is not None and abs(kap - e['cohens_kappa']) <= 1e-12),
                        f'Agreement kappa differs from its pair trace for {corpus} {field}')
            tables[(corpus, field)] = Counter(pairs)
    return tables


def parse_tsa_time(text):
    return datetime.strptime(' '.join(str(text).split()), '%b %d %H:%M:%S %Y GMT').replace(tzinfo=timezone.utc)


class Timestamps:
    """FILL3a's timestamp gate with the FILL3b coverage list (SPEC 3.16)."""

    def __init__(self, root, receipt_path, coverage, freeze_name, pcx_freeze=None):
        self.root = Path(root)
        self.labels = OrderedDict()
        dirs = sorted([p for p in self.root.iterdir() if p.is_dir() and re.fullmatch(r'T\d+(?:_PIPELINE_TEST)?', p.name)],
                      key=lambda p: int(re.match(r'T(\d+)', p.name).group(1)))
        score_time = datetime.fromtimestamp(Path(receipt_path).stat().st_mtime, timezone.utc)
        for d in dirs:
            result = d / f'{d.name}_RESULT.json'
            if not result.is_file():
                continue
            data = json.loads(result.read_text())
            manifest = d / data['manifest']
            require(manifest.is_file() and sha256(manifest) == data['manifest_sha256'], f'Timestamp manifest drift for {d.name}')
            times = {}
            for tsa in ('freetsa', 'digicert'):
                e = data['tsa'][tsa]
                require(e.get('http_ok') is True and e.get('verified') is True, f'{d.name} {tsa} token not verified')
                times[tsa] = parse_tsa_time(e['time_stamp'])
                require(times[tsa] < score_time, f'{d.name} {tsa} time is not before the score receipt')
            self.labels[d.name] = {'data': data, 'times': times, 'src': rel_proj(result), 'manifest': manifest}
        for need in ('T4', 'T5'):
            require(need in self.labels, f'Timestamp {need} result missing: T4 and T5 must be taken before scoring')
        listed = {}
        for name, entry in self.labels.items():
            if int(re.match(r'T(\d+)', name).group(1)) < 5:
                continue
            for line in entry['manifest'].read_text().splitlines():
                if line.startswith('#') or not line.strip():
                    continue
                digest, _, path = line.split(None, 2)
                listed.setdefault(path.strip(), set()).add(digest)
        expect = {'manuscript_tex/' + freeze_name: MS / freeze_name}
        for name in A4_FREEZES:
            expect['CONF/A4/' + name] = A4DIR / name
        expect.update({'CONF/A3/ADDENDUM_A3_FREEZE.json': A3DIR / 'ADDENDUM_A3_FREEZE.json',
                       'CONF/A3/A3_CODE_AND_RULES_FREEZE.json': A3DIR / 'A3_CODE_AND_RULES_FREEZE.json',
                       'CONF/A2/ADDENDUM_A2_FREEZE.json': A2DIR / 'ADDENDUM_A2_FREEZE.json',
                       'CONF/A2/A2_CODE_AND_RULES_FREEZE.json': A2DIR / 'A2_CODE_AND_RULES_FREEZE.json',
                       'NEWS_MATCHED_COVERAGE.json': coverage.path})
        if pcx_freeze is not None:
            expect['PCX_FREEZE.json'] = Path(pcx_freeze)
        for suffix, path in expect.items():
            hits = [d for p, ds in listed.items() if p.endswith(suffix) for d in ds]
            require(hits and sha256(path) in hits, f'T5 (or later) manifest does not cover the current {suffix}')
        self.score_time = score_time


def check_pcx(args):
    """SPEC 3.13: PCX inputs bind their base result, their freeze and the host's A4 input arguments."""
    pc, pcx = Path(args.positive_control), Path(args.pcx)
    out = {'pcx_used': pcx.is_file(), 'pcx_freeze': None}
    args_file = Path(args.pcx_args)
    if args_file.is_file():
        given = json.loads(args_file.read_text())
        require(Path(given.get('positive_control', '')).resolve() == pc.resolve() and Path(given.get('pcx', '')).resolve() == pcx.resolve(),
                'A4_INPUT_ARGS.json names other positive-control or PCX files than this fill')
    if not pcx.is_file():
        return out
    require(pc.is_file(), 'A PCX result is present without its positive-control base result')
    data = json.loads(pcx.read_text())
    require(data.get('frozen_result_sha256') == sha256(pc), 'The PCX result does not bind the positive-control base result')
    freeze = Path(args.pcx_freeze)
    require(freeze.is_file(), 'PCX_FREEZE.json missing: the PCX extension must be frozen before it is used')
    recorded = (data.get('identities') or {}).get('pcx_freeze_sha256')
    require(recorded is None or recorded == sha256(freeze), 'The PCX result binds another PCX freeze than PCX_FREEZE.json')
    out['pcx_freeze'] = freeze
    return out


def PR(width):
    """A right-aligned paragraph column (numbers under a wrapped header)."""
    return '>{\\raggedleft\\arraybackslash}p{' + width + '\\linewidth}'


def PW(width):
    """A ragged-right paragraph column of a given fraction of the line width (explicit widths; RULE B-11)."""
    return '>{\\raggedright\\arraybackslash}p{' + width + '\\linewidth}'


# ============================================================================= renderer
def renderer_class(F3A_, F3, F2, A4):
    Base = F3A_.renderer_class(F3, F2)
    IMP, DET, NULL, NE = A4.IMP, A4.DET, A4.NULL, A4.NE

    class Fill3b(Base):
        def setup3b(self, a4post, coverage, pcx_info, conf_review, agreement, pair_tables):
            self.A4, self.a4post, self.news_coverage, self.pcx_info = A4, a4post, coverage, pcx_info
            self.a4 = a4post.data
            self.conf_review, self.agreement, self.pair_tables = conf_review, agreement, pair_tables
            self.a4_checks = Counter()
            self.rs = {}
            for s in self.a4['result_states']:
                if s.get('role') == 'primary':
                    self.rs[(s['task'], s['contrast'])] = s
            for source in SOURCES:
                rows = self.a4['tasks'][source].get('primary_rows', [])
                a2rows = self.a2[source]['primary']
                if self.a4['tasks'][source]['scenario'] != 'INCOMPLETE':
                    require([(r['arm'], r['reference']) for r in rows] == [(r['arm'], r['reference']) for r in a2rows], 'A4 primary rows differ from A2')
                    for a, b in zip(rows, a2rows):
                        require(a.get('decision') == b.get('decision'), 'A4 primary decision differs from A2 for ' + a['arm'])

        # ------------------------------------------------------------------ A4 sentence -> LaTeX (RULE B-2)
        def a4s(self, text, field, symbols=True, table_ref=None):
            plain = text if table_ref is None else text.replace('{table_ref}', '\x02')
            parts = F3A_.a3_latex_parts(plain, symbols)
            out = []
            for p in parts:
                if p[0] == 'num':
                    out.append(self.R(p[1], self.a4post.src, field, f'token {p[2]} of the A4 sentence (frozen A4 rendering, strict re-run)'))
                elif p[0] == 'arm' and F2.tokens(p[1]):
                    out.append(self.R(p[1], F3.DESIGN_REL, 'arm identifier', 'arm name; digits are part of the identifier'))
                else:
                    out.append(p[1])
            tex = ''.join(out)
            if table_ref is not None:
                tex_ref, plain_ref = table_ref if isinstance(table_ref, tuple) else (table_ref, table_ref)
                tex = tex.replace('\x02', tex_ref)
                plain = text.replace('{table_ref}', plain_ref)
            require(F3A_.flat(self.R.peek(tex)) == F3A_.flat(plain), f'A4 sentence conversion differs:\n{self.R.peek(tex)}\n{plain}')
            self.a4_checks['A4 sentences'] += 1
            return tex

        def layout(self, text):
            """Typesetting lengths and column widths carry digits: registered as layout, not results (trace rule)."""
            return self.R(text, 'manuscript_tex/fill3b_conf_results.py', 'table layout', 'typesetting length or column width; not a result') if F2.tokens(text) else text

        def fx3b(self, text, key):
            """Inline fixed text of this frozen script: registered whole when it carries numerals and no placeholder."""
            if '\x00' in text or not F2.tokens(text):
                return text
            return self.R(text, 'manuscript_tex/fill3b_conf_results.py', key, 'fixed FILL3b text (frozen script)')

        def a4fixed(self, key, symbols=False):
            text = A4.SENTENCES[key]
            parts = F3A_.a3_latex_parts(text, symbols)
            tex = ''.join(self.R(p[1], A4_CODE_REL, f'SENTENCES[{key}]', 'fixed numeral of the frozen A4 sentence form') if p[0] == 'num' else p[1] for p in parts)
            require(F3A_.flat(self.R.peek(tex)) == F3A_.flat(text), f'A4 fixed sentence {key} conversion differs')
            self.a4_checks['A4 fixed sentences'] += 1
            return tex

        def t3b(self, key, **values):
            template = self.T3[key]
            parts = re.split(r'<<(\w+)>>', template)
            require(set(values) == set(parts[1::2]), f'Template {key} values differ from placeholders')
            out = []
            for i, part in enumerate(parts):
                if i % 2:
                    out.append(str(values[part]))
                elif part:
                    out.append(self.R(part, TEMPLATES_REL, key, 'fixed FILL3b template text') if F2.tokens(part) else part)
            return ''.join(out)

        t3a = t3b

        def scenario(self, source):
            return self.a4['tasks'][source]['scenario']

        def state_of(self, source, i):
            r = self.row(source, i)
            return self.rs.get((source, f"{r['arm']}-{r['reference']}"), {})

        def gating(self, source, i):
            g = self.a4['tasks'][source].get('gating') or []
            return g[i] if i < len(g) else {}

        # ------------------------------------------------------------------ words from the result-state record (RULE B-1)
        def class_word(self, source, i):
            st, g = self.state_of(source, i), self.gating(source, i)
            cls = st.get('primary_class')
            if cls == IMP:
                return A4.SENTENCES['CT_INC'] if g.get('strong_labels_assigned') else A4.SENTENCES['CT_PS']
            if cls == DET:
                return A4.SENTENCES['CT_DET']
            if cls == NULL:
                return A4.SENTENCES['CT_NULL2']
            return 'not evaluable'

        def robust_words(self, source, i):
            st = self.state_of(source, i)
            label = st.get('inference_agreement')
            parts = []
            if label == 'ROBUST':
                parts.append(A4.SENTENCES['Q_ROBUST'])
            elif label == 'FRAGILE':
                parts.append('fragile: ' + A4.join_list(A4.CHECK_SHORT[k] for k in st.get('dissenting_checks', [])) + ' disagreed')
                if st.get('unavailable_checks'):
                    parts.append(A4.SENTENCES['Q_NFC'].format(checks=A4.join_list(A4.CHECK_SHORT[k] for k in st['unavailable_checks'])))
            elif label == 'NOT_FULLY_CHECKED':
                parts.append(A4.SENTENCES['Q_NFC'].format(checks=A4.join_list(A4.CHECK_SHORT[k] for k in st.get('unavailable_checks', []))))
            else:
                parts.append('not evaluable')
            if st.get('design_dissent'):
                parts.append(A4.SENTENCES['Q_DISSENT'].format(items=A4.join_list(st['design_dissent'])))
            return '; '.join(parts)

        def task_decimals(self, source, key='interval95_one_day'):
            ds = [self.decimals(r.get(key)) for r in self.a2[source]['primary'] if r.get(key)]
            return max(ds) if ds else 2

        # ------------------------------------------------------------------ section 6.2 (RULE B-5)
        def primary_section(self):
            out = [self.t3b('primary.intro') + ' ' + self.a3fixed(self.A3.SENTENCES['A3C8'], 'A3C8'), '']
            self.p1_done = False
            for source in SOURCES:
                heading = self.t3b('primary.task_heading', task_label='Day-ahead news' if source == 'news' else 'Market notices')
                out.append(heading + ' ' + ' '.join(self.task_sentences_a4(source)))
                out.append('')
            out.append(self.primary_table3b())
            out.append('\\begin{figure}[htbp]\\centering\n\\includegraphics[width=\\linewidth]{' + FIGURE[:-4] + '}\n\\caption{' + self.t3b('primary.figure_caption') +
                       '}\\label{fig:fill3b-forest}\n\\end{figure}\n')
            return '\n'.join(out) + '\n'

        PC_PREFIXES = ('For day-ahead news, at twice', 'For market notices, at twice', 'The planted-signal check was not run')

        def task_sentences_a4(self, source):
            pc_any = any((self.a4['tasks'][s].get('positive_control') or {}).get('state', 'NOT_RUN') != 'NOT_RUN' for s in SOURCES)
            parts = []
            for i, s in enumerate(self.a4['tasks'][source]['section6']):
                if s.startswith(self.PC_PREFIXES) and not self.p1_done and pc_any:
                    parts.append(self.a3fixed(self.A3.SENTENCES['A3P1'], 'A3P1'))
                    self.p1_done = True
                ref = '\\ref{tab:ms14-published-gains}' if '{table_ref}' in s else None
                parts.append(self.a4s(s, f'tasks.{source}.section6[{i}]', table_ref=ref))
            return parts

        def primary_table3b(self):
            rows = []
            for source in SOURCES:
                d = self.task_decimals(source)
                for i, (c, r) in enumerate(zip(self.primary[source], self.a2[source]['primary'])):
                    base = f'tasks.{source}.primary[{i}]'
                    eff = self.num(self.A2.fmt_effect(r.get('effect_percent_reference_mae'), d), base + '.effect_percent_reference_mae', f'{d} decimals (task column rule)')
                    rows.append(' & '.join([self.pair(c.arm, c.ref), self.aud(c), eff,
                                            self.cell_interval(r.get('interval_family_one_day'), d, base + '.interval_family_one_day'),
                                            self.cell_p(r.get('holm_p'), base + '.holm_p'), F2.esc(self.class_word(source, i)),
                                            F2.esc(self.robust_words(source, i))]) + r' \\')
                if source == 'news':
                    rows.append(r'\midrule')
            a4t7 = self.a4s(self.a4['table6_caption'], 'table6_caption', symbols=False, table_ref='\\ref{tab:fill3b-sensitivity}')
            spec = '@{}' + PW('.12') + 'rr' + PW('.19') + 'r' + PW('.12') + PW('.17') + '@{}'
            return ('\\begin{table}[htbp]\\centering\\footnotesize\\setlength{\\tabcolsep}{' + self.layout('3pt') + '}\n\\caption{' + self.t3b('primary.table_caption', A4T7=a4t7) + '}\\label{tab:fill3b-primary}\n'
                    '\\begin{tabular}{' + spec + '}\\toprule\n'
                    + self.t3b('primary.table_header') + '\n\\midrule\n' + '\n'.join(rows) + '\n\\bottomrule\\end{tabular}\\end{table}\n')

        # ------------------------------------------------------------------ section 6.3 (RULE B-6)
        def e3_line3b(self):
            state = self.report['notice'].get('e3_joint_state', 'E3_SECONDARY_JOINT_NOT_EVALUABLE')
            phrase = self.A3.CODE_PHRASES.get(state)
            require(phrase is not None, f'No A3 plain phrase for the joint state {state!r}')
            if '{failed_list}' in phrase:
                failed = []
                for pair, name in self.A3.E3_COMPARISON_NAMES.items():
                    c = self.secondary['notice'].get(pair)
                    if c is None or isinstance(c, dict) or c.branch != 'FAVORABLE':
                        failed.append(name)
                phrase = phrase.format(failed_list=F3A_.join_list(failed) if failed else 'neither comparison')
            return 'Under the frozen joint rule, ' + self.a3fixed(phrase, 'CODE_PHRASES.' + state) + ' (Supplement~S7).'

        def a4_batch_texts(self):
            """A4NR/A4DEV sentences: the frozen batch_texts, which must appear in conclusion_core (RULE B-6)."""
            texts = A4.batch_texts(self.batch.data if self.batch is not None else None)
            core = self.a4['conclusion_core']
            for t in texts:
                require(t in core, 'A4 batch sentence missing from the conclusion core: ' + t)
            return [(t, f'conclusion_core[{core.index(t)}]') for t in texts]

        def batch_text3b(self):
            if self.batch is None:
                return self.t3b('secondary.batch_pending')
            out = []
            t = self.a3post.texts('news')
            for k, s in enumerate(t.get('qualifiers', [])):
                out.append(self.a3s(s, f'tasks.news.texts.qualifiers[{k}]'))
            for k, s in enumerate(t['section6']):
                if s.startswith('The primary increment of '):
                    out.append(self.a3s(s, f'tasks.news.texts.section6[{k}]'))
            for s, field in self.a4_batch_texts():
                out.append(self.a4s(s, field, symbols=False))
            out.append(self.a3fixed(self.A3.SENTENCES['A3R_BATCH'], 'A3R_BATCH'))
            if self.batch.data['families']['PD']['state'] == 'COMPUTED':
                out.append(self.verbatim(self.RULES['a2batch']['pd_gap_limitation'], 'a2batch.pd_gap_limitation', 'autopilot/q1_audits/CONF/A2/RULES_FOR_FILL3.json', 'verbatim A2 limitation sentence'))
            return ' '.join(out)

        def label_main3b(self):
            if self.label is None or not self.label.scored:
                return self.label_paragraph3a()
            return ''

        def sens_table3b(self):
            names = self.T3['sens_table']
            cols = [(s, i) for s in SOURCES for i in range(len(self.a2[s]['primary']))]
            head = 'Design sensitivity & ' + ' & '.join(self.pair(self.row(s, i)['arm'], self.row(s, i)['reference']) for s, i in cols) + r' \\'
            rows = []
            for key, label in names.items():
                cells = []
                for s, i in cols:
                    r = self.row(s, i)
                    st = self.a3post.task(s)['design_sensitivities'][f"{r['arm']}-{r['reference']}"].get(key, {'state': 'NOT_APPLICABLE'})
                    word = self.T3['sens_cells'][st['state']]
                    if st['state'] == 'DIFFERENT':
                        word = self.A3.CLASS_WORDS[st['class']]
                    cells.append(F2.esc(word))
                label = self.R(F2.esc(label), TEMPLATES_REL, 'sens_table.' + key, 'fixed FILL3b template text') if F2.tokens(label) else F2.esc(label)
                rows.append(' & '.join([label] + cells) + r' \\')
            w = '%.2f' % (0.74 / max(1, len(cols)))
            spec = '@{}' + PW('.14') + PW(w) * len(cols) + '@{}'
            return ('\\begin{table}[htbp]\\centering\\footnotesize\\setlength{\\tabcolsep}{' + self.layout('3pt') + '}\n\\caption{' + self.t3b('secondary.sens_caption') + '}\\label{tab:fill3b-sensitivity}\n'
                    '\\begin{tabular}{' + spec + '}\\toprule\n' + head + '\n\\midrule\n'
                    + '\n'.join(rows) + '\n\\bottomrule\\end{tabular}\\end{table}\n')

        def secondary_section(self):
            lab = self.label_main3b()
            out = [self.t3b('secondary.intro') + ' ' + self.e3_line3b(), '',
                   self.t3b('secondary.label_heading') + ' ' + self.batch_text3b() + ((' ' + lab) if lab else ''), '',
                   self.t3b('secondary.sens_heading') + ' ' + self.t3b('secondary.sens_intro'), '', self.sens_table3b()]
            return '\n'.join(out) + '\n'

        # ------------------------------------------------------------------ section 7.2 and conclusion (RULES B-7, B-8)
        def discussion_section(self):
            out = [self.t3b('discussion.heading')]
            sentences = []
            for source in SOURCES:
                for k, s in enumerate(self.a4['tasks'][source].get('section7_2', [])):
                    sentences.append(self.a4s(s, f'tasks.{source}.section7_2[{k}]'))
            sentences.append(self.a3fixed(self.A3.SENTENCES['A3R6'], 'A3R6'))
            sentences.append(self.t3b('discussion.closing'))
            out.append(' '.join(sentences))
            return '\n'.join(out) + '\n'

        def conclusion(self):
            core = self.a4['conclusion_core']
            return ' '.join(self.a4s(s, f'conclusion_core[{k}]', symbols=False) for k, s in enumerate(core)) + '\n'

        # ------------------------------------------------------------------ abstract (RULE B-3)
        def abstract3b(self):
            ab = self.a4['abstract']
            tex = self.a4s(ab['text'], 'abstract.text', symbols=False)
            words = F2.abstract_words(self.R.peek(tex))
            counts = {c['level']: c['validator_words'] for c in ab['counts']}
            level = ab['level']
            expected = counts.get(level) if level != 'L7' else ab['counts'][-1]['validator_words']
            require(words == expected, f'Rendered abstract has {words} validator words, A4 counted {expected} at {level}')
            self.abstract_level, self.abstract_counts, self.abstract_over_limit = level, ab['counts'], bool(ab.get('abstract_over_limit'))
            require(self.abstract_over_limit == (level == 'L7'), 'A4 abstract level and over-limit flag disagree')
            self.abstract_words_final = words
            return tex

        def highlight3b(self):
            H = 'highlight.'
            incs = {s: [i for i, r in enumerate(self.a2[s]['primary']) if r['decision'] == IMP] for s in SOURCES}
            if not incs['news'] and not incs['notice']:
                text = self.T3[H + 'none']
            elif incs['news'] and incs['notice']:
                text = self.T3[H + 'both']
            else:
                s = 'news' if incs['news'] else 'notice'
                i = incs[s][0]
                robust = all(self.gating(s, j).get('strong_labels_assigned') for j in incs[s])
                cls = self.T3[H + 'cls.robust'] if robust else self.T3[H + 'cls.other']
                plain = self.T3['plain_arm'][self.row(s, i)['arm']] if len(incs[s]) == 1 else 'representation'
                text = self.T3[H + ('news_only' if s == 'news' else 'notice_only')].replace('<<plain>>', plain).replace('<<cls>>', cls)
            if len(text) > 85:
                text = self.T3[H + 'fallback']
            require(not re.search(r'\d', text) and len(text) <= 85, 'Highlight must carry no number and at most 85 characters')
            return text

        # ------------------------------------------------------------------ section 6.1 (RULE B-4)
        def execution_sentence3b(self):
            ref = self.R(STAGE_TABLE_REF, TEMPLATES_REL, 'execution.table_ref', 'Supplement Table S9.1: the stage table is the first table of section S9 (SPEC_FILL3B RULE B-4)')
            return self.a4s(self.a4['execution_sentence'], 'execution_sentence', symbols=False, table_ref=(ref, STAGE_TABLE_REF)) + TAG

        def timestamp_sentence(self):
            names = list(self.ts.labels)
            labels = self.ts_short(names[0]) + '--' + self.ts_short(names[-1])
            day = lambda n: self.ts.labels[n]['times']['freetsa']  # noqa: E731
            fmt = lambda n: self.R(f"{day(n).day} {day(n).strftime('%B %Y, %H:%M:%S')}", self.ts.labels[n]['src'], 'tsa.freetsa.time_stamp', 'FreeTSA time (UTC)')  # noqa: E731
            return self.t3b('design.timestamps', labels=labels, t4='T4', t5='T5', time4=fmt('T4'), time5=fmt('T5')) + TAG

        def timestamp_caption(self):
            groups = OrderedDict()
            for name in self.ts.labels:
                groups.setdefault(self.ts.labels[name]['times']['freetsa'].date(), []).append(name)
            items = []
            for date_, names in groups.items():
                first, last = self.ts_short(names[0]), self.ts_short(names[-1])
                lab = first if first == last else (first + '--' + last if len(names) > 2 else first + ' and ' + last)
                when = self.R(f'{date_.day} {date_.strftime("%B %Y")}', self.ts.labels[names[0]]['src'], 'tsa.freetsa.time_stamp', 'UTC date of the timestamp')
                items.append(lab + ' on ' + when)
            return self.t3b('supplement.timestamp_caption', dates=', '.join(items)) + TAG

        def timestamp_rows(self):
            rows = []
            for name in self.ts.labels:
                k = int(re.match(r'T(\d+)', name).group(1))
                if k < 4:
                    continue
                short = self.ts_short(name)
                content = F2.esc(self.T3['supplement.timestamp_content'].get(short, self.T3['supplement.timestamp_content.other']))
                files = self.R(f"{self.ts.labels[name]['data']['files']:,}", self.ts.labels[name]['src'], 'files', 'manifest file count')
                rows.append(self.t3b('supplement.timestamp_row', label=short, content=content, files=files,
                                     free=self.ts_time(name, 'freetsa'), digi=self.ts_time(name, 'digicert')))
            return ' '.join(rows) + TAG

        # ------------------------------------------------------------------ human reviews (RULE B-13)
        def rate_range(self, items, names, src, field_fmt, key='rate'):
            """'from x% (a) to y% (b)' or a single value when both ends print equal (RULE B-13)."""
            if not items:
                return 'over no determinate field'
            lo_f = min(items, key=lambda k: items[k][key])
            hi_f = max(items, key=lambda k: items[k][key])
            lo = self.pct1(items[lo_f][key], src, field_fmt.format(lo_f))
            hi = self.pct1(items[hi_f][key], src, field_fmt.format(hi_f))
            if f"{100 * items[lo_f][key]:.1f}" == f"{100 * items[hi_f][key]:.1f}":
                same = [names.get(k, k) for k in items if f"{100 * items[k][key]:.1f}" == f"{100 * items[lo_f][key]:.1f}"]
                return lo + '\\% (' + F3A_.join_list(same) + ')' if len(same) < len(items) else lo + '\\% in every determinate field'
            return 'from ' + lo + '\\% (' + names.get(lo_f, lo_f) + ') to ' + hi + '\\% (' + names.get(hi_f, hi_f) + ')'

        def news_review_sentence(self):
            rv = self.reviews3['news']
            d, src = rv.data, rv.src
            a = d['strata']['ALL']
            fe = {k: v for k, v in a['statement_field_error'].items() if v.get('rate') is not None}
            v = {}
            for key, short in (('hallucination', 'h'), ('omission', 'o'), ('impact_level_error', 't')):
                item = a[key]
                v[short] = self.R(f"{item['errors_or_yes']}/{item['determinate_n']}", src, f'strata.ALL.{key}.errors_or_yes/determinate_n', 'count')
                v[short + '_rate'] = self.pct1(item['rate'], src, f'strata.ALL.{key}.rate')
                v[short + '_ci'] = self.ci1(item['wilson_95'], src, f'strata.ALL.{key}.wilson_95')
            ef = d['extraction_failure']
            return self.t3b('human.news', failed=self.R(f"{ef['sample']['errors_or_yes']}/{ef['sample']['determinate_n']}", src, 'extraction_failure.sample', 'count'),
                            pop=self.R(f"{ef['population']['errors_or_yes']}/{ef['population']['determinate_n']:,}", src, 'extraction_failure.population.errors_or_yes/determinate_n', 'count'),
                            labelled=self.R(str(d['labelled_articles']), src, 'labelled_articles', 'count'),
                            f_range=self.rate_range(fe, self.T3['human.field_names_news'], src, 'strata.ALL.statement_field_error.{}.rate'),
                            A4HR=self.a4fixed('A4HR'), **v) + TAG

        def news_review_table(self):
            rv = self.reviews3['news']
            a = rv.data['strata']['ALL']
            rows = []
            for key, name in (('hallucination', 'Article hallucination'), ('omission', 'Article omission'), ('impact_level_error', 'Impact-tier error')):
                it = a[key]
                rows.append(' & '.join([name] + self.rate_cells(it['errors_or_yes'], it['determinate_n'], it['rate'], it['wilson_95'], rv.src, f'strata.ALL.{key}')) + r' \\')
            for field, it in a['statement_field_error'].items():
                rows.append(' & '.join(['Statement field: ' + F2.esc(self.T3['human.field_names_news'].get(field, field))] +
                                       self.rate_cells_noint(it['errors_or_yes'], it['determinate_n'], it['rate'], rv.src, f'strata.ALL.statement_field_error.{field}')) + r' \\')
            for key, name in (('sample', 'Extraction failures, sample'), ('population', 'Extraction failures, population')):
                it = rv.data['extraction_failure'][key]
                rows.append(' & '.join([name] + self.rate_cells(it['errors_or_yes'], it['determinate_n'], it['rate'], it['wilson_95'], rv.src, f'extraction_failure.{key}')) + r' \\')
            return self.table3b('supp:tab:fill3b-news-review', self.t3b('human.news_caption'), r'Measure & $k/n$ & Rate (\%) & Wilson 95\% \\', rows, 'lrrl')

        def nrx_review_table(self):
            text = Base.nrx_review_table(self)
            return text.replace('supp:tab:fill3-nrx-review', 'supp:tab:fill3b-nrx-review')

        def rate_cells_noint(self, k, n, rate, src, field):
            if not n:
                return [self.R(f'{k}/{n}', src, field, 'count'), 'NA', 'no interval']
            return [self.R(f'{k}/{n}', src, field, 'count'), self.pct1(rate, src, field + '.rate'), 'no interval']

        def conf_sentence(self):
            d, src = self.conf_review.data, self.conf_review.src
            a = d['news']['strata']['ALL']
            fe = {k: v for k, v in a['statement_field_error'].items() if v.get('rate') is not None}
            n = d['notices']['strata']['ALL']
            ff = {k: v for k, v in n['fields'].items() if v.get('error_rate') is not None}
            v = {}
            for key, short in (('hallucination', 'h'), ('omission', 'o'), ('impact_level_error', 't')):
                item = a[key]
                v[short] = self.R(f"{item['errors_or_yes']}/{item['determinate_n']}", src, f'news.strata.ALL.{key}.errors_or_yes/determinate_n', 'count')
                v[short + '_rate'] = self.pct1(item['rate'], src, f'news.strata.ALL.{key}.rate') if item.get('rate') is not None else 'NA'
                v[short + '_ci'] = self.ci1(item['wilson_95'], src, f'news.strata.ALL.{key}.wilson_95') if item.get('wilson_95') else 'no interval'
            s7 = n['seven_field_total']
            v.update(n_art=self.R(str(a['article_count']), src, 'news.strata.ALL.article_count', 'count'),
                     n_not=self.R(str(n['notice_count']), src, 'notices.strata.ALL.notice_count', 'count'),
                     k7n7=self.R(f"{s7['errors']}/{s7['determinate_denominator']}", src, 'notices.strata.ALL.seven_field_total.errors/determinate_denominator', 'count'),
                     rate7=self.pct1(s7['error_rate'], src, 'notices.strata.ALL.seven_field_total.error_rate') if s7.get('error_rate') is not None else 'NA',
                     f_range=self.rate_range(fe, self.T3['human.field_names_news'], src, 'news.strata.ALL.statement_field_error.{}.rate'),
                     g_range=self.rate_range(ff, self.T3['human.field_names_nrx'], src, 'notices.strata.ALL.fields.{}.error_rate', key='error_rate'),
                     A4HR=self.a4fixed('A4HR'))
            return self.t3b('human.conf', **v) + TAG

        def conf_table(self):
            d, src = self.conf_review.data, self.conf_review.src
            a = d['news']['strata']['ALL']
            rows = []
            for key, name in (('hallucination', 'News: article hallucination'), ('omission', 'News: article omission'), ('impact_level_error', 'News: impact-tier error')):
                it = a[key]
                rows.append(' & '.join([name] + self.rate_cells(it['errors_or_yes'], it['determinate_n'], it['rate'], it['wilson_95'], src, f'news.strata.ALL.{key}')) + r' \\')
            for f, it in a['statement_field_error'].items():
                rows.append(' & '.join(['News statement field: ' + F2.esc(self.T3['human.field_names_news'].get(f, f))] +
                                       self.rate_cells_noint(it['errors_or_yes'], it['determinate_n'], it['rate'], src, f'news.strata.ALL.statement_field_error.{f}')) + r' \\')
            n = d['notices']['strata']['ALL']
            for f, it in n['fields'].items():
                rows.append(' & '.join(['Notice field: ' + F2.esc(self.T3['human.field_names_nrx'].get(f, f))] +
                                       self.rate_cells(it['errors'], it['determinate_denominator'], it['error_rate'], it['wilson_95'], src, f'notices.strata.ALL.fields.{f}')) + r' \\')
            s7 = n['seven_field_total']
            rows.append(' & '.join(['Notices: seven earlier fields, total', self.R(f"{s7['errors']}/{s7['determinate_denominator']}", src, 'notices.strata.ALL.seven_field_total', 'count'),
                                    self.pct1(s7['error_rate'], src, 'notices.strata.ALL.seven_field_total.error_rate') if s7.get('error_rate') is not None else 'NA', 'no interval']) + r' \\')
            return self.table3b('supp:tab:fill3b-confirmation-review', self.t3b('human.conf_caption'), r'Measure & $k/n$ & Rate (\%) & Wilson 95\% \\', rows, 'lrrl')

        def kappa_text(self, kap, src, field):
            return 'undefined' if kap is None else self.R(f'{kap:.2f}' if kap >= 0 else f'$-{abs(kap):.2f}$', src, field, '2 decimals')

        def agreement_sentence(self):
            g = self.agreement.data['groups']['ALL']['metrics']
            src = self.agreement.src
            v = {}
            for corpus, key in (('news', 'news'), ('notice', 'not')):
                fields = g[corpus]['fields']
                raw = {f: e['raw_agreement'] for f, e in fields.items() if e.get('raw_agreement') is not None}
                kap = {f: e['cohens_kappa'] for f, e in fields.items() if e.get('cohens_kappa') is not None}
                lo_f, hi_f = min(raw, key=raw.get), max(raw, key=raw.get)
                lo = self.pct1(raw[lo_f], src, f'groups.ALL.metrics.{corpus}.fields.{lo_f}.raw_agreement')
                if f'{100 * raw[lo_f]:.1f}' == f'{100 * raw[hi_f]:.1f}':
                    v[key + '_range'] = lo + '\\%'
                else:
                    v[key + '_range'] = lo + '\\% to ' + self.pct1(raw[hi_f], src, f'groups.ALL.metrics.{corpus}.fields.{hi_f}.raw_agreement') + '\\%'
                undefined = len(fields) - len(kap)
                if kap:
                    klo, khi = min(kap, key=kap.get), max(kap, key=kap.get)
                    a_ = self.kappa_text(kap[klo], src, f'groups.ALL.metrics.{corpus}.fields.{klo}.cohens_kappa')
                    if f'{kap[klo]:.2f}' == f'{kap[khi]:.2f}':
                        kt = a_ + ' in every field with a defined value'
                    else:
                        kt = 'from ' + a_ + ' to ' + self.kappa_text(kap[khi], src, f'groups.ALL.metrics.{corpus}.fields.{khi}.cohens_kappa')
                else:
                    kt = 'undefined for every field'
                if undefined and kap:
                    kt += ', undefined for ' + self.R(str(undefined), src, f'groups.ALL.metrics.{corpus}.fields (kappa null count)', 'count') + (' field' if undefined == 1 else ' fields')
                v[key + '_k'] = kt
            return self.t3b('human.agreement', **v) + TAG

        def agreement_table(self):
            g = self.agreement.data['groups']['ALL']['metrics']
            src = self.agreement.src
            names = {'hallucination': 'hallucination', 'omission': 'omission', 'impact_code': 'impact tier'} | self.T3['human.field_names_news'] | self.T3['human.field_names_nrx']
            rows = []
            for corpus in ('news', 'notice'):
                for f, e in g[corpus]['fields'].items():
                    base = f'groups.ALL.metrics.{corpus}.fields.{f}'
                    n, k = e['paired_n'], e['equal_n']
                    raw = self.R(f'{k}/{n}', src, base + '.equal_n/paired_n', 'count')
                    rate = self.pct1(e['raw_agreement'], src, base + '.raw_agreement') if n else 'NA'
                    ci = self.ci1(e['wilson_95'], src, base + '.wilson_95') if e.get('wilson_95') else '--'
                    po = self.R(f'{k / n:.2f}', src, base + '.equal_n/paired_n (po)', '2 decimals') if n else '--'
                    pe = self.R(f"{e['expected_agreement']:.2f}", src, base + '.expected_agreement', '2 decimals') if n and e.get('expected_agreement') is not None else '--'
                    ktxt = self.kappa_text(e.get('cohens_kappa'), src, base + '.cohens_kappa')
                    prev = []
                    for who in ('author', 'second'):
                        pv = e['prevalence'][who]
                        items = [F2.esc(c) + ' ' + self.R(str(pv[c]['count']), src, base + f'.prevalence.{who}.{c}.count', 'count') for c in sorted(pv) if pv[c]['count']]
                        prev.append(', '.join(items) if items else '--')
                    pairs = self.pair_tables.get((corpus, f), Counter())
                    cont = ', '.join(F2.esc(a) + '/' + F2.esc(b) + ' ' + self.R(str(c), src, base + f' pair_trace ({a},{b})', 'count of paired codes') for (a, b), c in sorted(pairs.items()))
                    rows.append(' & '.join([('News' if corpus == 'news' else 'Notices') + ': ' + F2.esc(names.get(f, f)), raw, rate, ci, po, pe, ktxt, prev[0], prev[1], cont or '--']) + r' \\')
            head = r'Field & $k/n$ & Agree (\%) & Wilson 95\% & $p_o$ & $p_e$ & $\kappa$ & Author codes & Second codes & Paired codes (author/second) \\'
            spec = '@{}' + PW('.11') + 'rrlrrr' + PW('.09') + PW('.09') + PW('.16') + '@{}'
            cap = self.t3b('human.agreement_caption')
            head = self.fx3b(head, 'agreement header')
            return ('{\\footnotesize\\setlength{\\tabcolsep}{' + self.layout('3pt') + '}\n\\begin{longtable}{' + self.layout(spec) + '}\n\\caption{' + cap + '}\\label{supp:tab:fill3b-agreement}\\\\\n\\toprule\n' + head +
                    '\n\\midrule\n\\endfirsthead\n\\toprule\n' + head + '\n\\midrule\n\\endhead\n\\bottomrule\n\\endfoot\n' + '\n'.join(rows) + '\n\\end{longtable}}\n')

        def cell_interval(self, interval, d, field, src=None):
            """Interval cell with text brackets so that a narrow column can break after the comma (RULE B-11 layout)."""
            if interval is None:
                return '--'
            lo, hi = self.A2.fmt_interval(interval, d)
            return self.R('[$' + lo + '$, $' + hi + '$]', src or self.a2post.src, field, 'endpoints rounded outward (A2 fmt_interval)')

        def table3b(self, label, caption, header, rows, spec, size='footnotesize'):
            """A supplement table as a longtable at footnotesize with narrow column gaps, never resized (RULE B-11)."""
            require('X' not in spec, 'Supplement longtables take explicit column widths')
            caption, header = self.fx3b(caption, label + ' caption'), self.fx3b(header, label + ' header')
            return ('{\\' + size + '\\setlength{\\tabcolsep}{' + self.layout('3pt') + '}\n\\begin{longtable}{' + self.layout('@{}' + spec + '@{}') + '}\n\\caption{' + caption + '}\\label{' + label + '}\\\\\n'
                    '\\toprule\n' + header + '\n\\midrule\n\\endfirsthead\n\\toprule\n' + header + '\n\\midrule\n\\endhead\n\\bottomrule\n\\endfoot\n'
                    + '\n'.join(rows) + '\n\\end{longtable}}\n')

        # ------------------------------------------------------------------ published-gains rows (RULE B-12)
        def pg_rows(self):
            tvn = self.a4['tasks']['news']['slots'].get('tvn') or {}
            pm = self.report['news'].get('pooled_mae', {})
            out = {}
            for key, arm in (('count', 'L_count'), ('chen', 'L_chen'), ('act', 'M')):
                n, a = pm.get('N'), pm.get(arm)
                lab = {'count': 'label counts', 'chen': 'structured attributes', 'act': 'article activity'}[key]
                tex = {'count': r'L_{\mathrm{count}}', 'chen': r'L_{\mathrm{chen}}', 'act': 'M'}[key]
                if not (finite(n) and finite(a)):
                    out[key] = f'This study: {lab} & Confirmation MAE, $N\\rightarrow {tex}$: not computed & not computed &'
                    continue
                src = self.s.src('SCORE_REPORT.json')
                nm = self.R(f'{n:.3f}', src, 'news.pooled_mae.N', '3 decimals')
                am = self.R(f'{a:.3f}', src, f'news.pooled_mae.{arm}', '3 decimals')
                change = 100.0 * (a - n) / n
                ch = self.R(f'${change:+.2f}$', src, f'100*(news.pooled_mae.{arm}-news.pooled_mae.N)/news.pooled_mae.N', 'relative change from the reported pair, 2 decimals')
                sl = tvn.get(f'{arm}-N') or {}
                if sl.get('state') == 'COMPUTED':
                    d = self.decimals(sl.get('interval95'))
                    lo, hi = self.A2.fmt_interval(sl.get('interval95'), d)
                    base = f'tasks.news.slots.tvn.{arm}-N'
                    est = (self.R('$' + A4.sfmt(sl.get('effect'), d) + '$', self.a4post.src, base + '.effect', f'{d} decimals (A4 sfmt)') + '\\% $[$' +
                           self.R(lo, self.a4post.src, base + '.interval95[0]', 'outward') + ', ' + self.R(hi, self.a4post.src, base + '.interval95[1]', 'outward') +
                           '$]$\\%, ' + F2.esc(A4.CS_WORDS[sl['class']]))
                else:
                    est = 'estimate not evaluable'
                out[key] = f'This study: {lab} & Confirmation MAE $' + nm + '\\rightarrow ' + am + '$; estimate ' + est + ' & MAE ' + ch + '\\% &'
            return out

        # ------------------------------------------------------------------ supplement S7 block
        def supplement_block3b(self):
            S = 'supplement_block.'
            out = [self.t3b(S + 'heading'), self.t3b(S + 'intro'), '', self.t3b(S + 'primary_heading'), self.t3b(S + 'primary_text')]
            out.append(self.supp_primary_tables3b())
            out.append('\\paragraph{Frozen per-contrast reading} ' + self.a3fixed(self.A3.SENTENCES['A3B5'], 'A3B5') + ' ' + self.per_contrast_record())
            out.append('')
            out.append('\\paragraph{Notice comparison value} ' + self.a3fixed(self.A3.SENTENCES['A3D5'], 'A3D5') + ' ' + self.a1_notice_sesoi3a())
            out.append('')
            out.append(self.t3b(S + 'attribution_text'))
            out.append(self.t3b(S + 'secondary_heading'))
            out.append(self.t3b(S + 'secondary_text'))
            out.append(self.combination_table3b())
            out.append(self.cheap_table3b())
            for source in SOURCES:
                out.append(self.all_secondary_table3b(source))
            out.append('\\FloatBarrier')
            out.append(self.t3b(S + 'sens_heading'))
            out.append(self.t3b(S + 'sens_text') + ' ' + self.subset_text())
            out.append(self.supp_sens_table3b())
            out.append('\\FloatBarrier')
            out.append(self.t3b(S + 'diag_heading'))
            out.append(self.diagnostics3b())
            if self.pc is not None:
                out.append(self.t3b(S + 'pc_heading'))
                out.append(self.pc_supplement3b())
            out.append(self.t3b(S + 'batch_heading'))
            out.append(self.batches_supplement3b())
            out.append('\\FloatBarrier')
            out.append(self.t3b(S + 'prov_heading'))
            out.append('\\begin{sloppypar}' + self.t3b(S + 'prov', seal=F2.hexcode(self.s.seal_sha256),
                                 files=self.count(len(self.s.receipt['files']), F2.trace_path(self.s.scored / 'SCORE_RECEIPT.json'), 'len(files)', 'score files'),
                                 receipt=F2.hexcode(self.s.receipt_sha256), a2=F2.hexcode(self.a2post.sha256), a3=F2.hexcode(self.a3post.sha256),
                                 a4=F2.hexcode(self.a4post.sha256)) + '\\end{sloppypar}')
            return '\n'.join(out) + '\n'

        def supp_primary_tables3b(self):
            rows_a, rows_b, seeds = [], [], []
            for source in SOURCES:
                d = self.task_decimals(source)
                ts = (self.a4['tasks'][source].get('three_seed') or {})
                for i, (c, r) in enumerate(zip(self.primary[source], self.a2[source]['primary'])):
                    base = f'tasks.{source}.primary[{i}]'
                    src = F2.trace_path(self.s.scored / c.file)
                    ref_mae = self.R(f"{c.b1['reference_mae']:.3f}", src, f'reports[{i}].bootstrap.1.reference_mae', '3 decimals') if finite(c.b1.get('reference_mae')) else '--'
                    rows_a.append(' & '.join([self.pair(c.arm, c.ref), self.count(c.dm.get('n_days'), src, f'reports[{i}].dm_p1.n_days'), ref_mae, self.aud(c),
                                              self.num(self.A2.fmt_effect(r.get('effect_percent_reference_mae'), d), base + '.effect_percent_reference_mae', f'{d} decimals (task column rule)'),
                                              self.cell_interval(r.get('interval95_one_day'), d, base + '.interval95_one_day'),
                                              self.cell_interval(r.get('interval_family_one_day'), d, base + '.interval_family_one_day')]) + r' \\')
                    rows_b.append(' & '.join([self.pair(c.arm, c.ref), self.cell_interval(r.get('interval95_seven_day'), d, base + '.interval95_seven_day'),
                                              self.cell_interval(r.get('interval_family_seven_day'), d, base + '.interval_family_seven_day'),
                                              self.cell_p(r.get('p_two_sided'), base + '.p_two_sided'), self.cell_p(r.get('holm_p'), base + '.holm_p'),
                                              self.cell_p(r.get('hln_holm_p'), base + '.hln_holm_p'), self.cell_p(r.get('hac7_holm_p'), base + '.hac7_holm_p')]) + r' \\')
                    key = f'{c.arm}-{c.ref}'
                    t = (ts.get('pairs') or {}).get(key) if ts.get('state') == 'COMPUTED' else None
                    if t:
                        tb = f'tasks.{source}.three_seed.pairs.{key}'
                        lo, hi = self.A2.fmt_interval(t.get('interval_family'), d)
                        three = (self.R('$' + A4.sfmt(t.get('effect'), d) + '$', self.a4post.src, tb + '.effect', f'{d} decimals') + ' $[$' +
                                 self.R(lo, self.a4post.src, tb + '.interval_family[0]', 'outward') + ', ' + self.R(hi, self.a4post.src, tb + '.interval_family[1]', 'outward') +
                                 '$]$, ' + F2.esc(A4.TS_WORDS.get(t.get('class'), 'not evaluable')))
                    else:
                        three = 'not available'
                    frag = self.seedfrag[source]['rows'][i]
                    sign_only = self.a3post.task(source)['seed_sign_only'].get(f'{c.arm}-{c.ref}')
                    state = 'same class, opposite sign' if sign_only else {'SEED_CONSISTENT': 'consistent', 'SEED_FRAGILE': 'different class', 'SEED_ROBUSTNESS_NOT_EVALUABLE': 'not available'}[frag['state']]
                    three_w = self.T3['class_words'].get(frag.get('three_seed_mean_decision') or '', 'n/a')
                    seeds.append(' & '.join([self.pair(c.arm, c.ref)] + [self.seed_effect(source, i, s) for s in (F2.SEED,) + F2.EXTRA_SEEDS] +
                                            [self.seed_sd(source, i), three, state]) + r' \\')
                if source == 'news':
                    for rr in (rows_a, rows_b, seeds):
                        rr.append(r'\midrule')
            t1 = self.table3b('supp:tab:fill3b-primary-a', 'Primary families, effects and one-day intervals (main seed): days; reference MAE (AUD/MWh); daily mean difference (AUD/MWh); effect in percent of the reference MAE; per-contrast 95\\% and family-adjusted (97.5\\% news, 98.3\\% notices) one-day bootstrap intervals.',
                              r'Contrast & Days & Ref.\ MAE & $\Delta$ & Effect & One-day 95\% & Family-adjusted one-day \\', rows_a, PW('.14') + 'rrrr' + PW('.20') + PW('.20'))
            t2 = self.table3b('supp:tab:fill3b-primary-b', 'Primary families, seven-day intervals and tests (main seed): per-contrast 95\\% and family-adjusted seven-day intervals, raw two-sided DM $p$ and Holm-adjusted DM, HLN and HAC7 $p$; the inferential robustness label is in Table~6 of the main article.',
                              r'Contrast & Seven-day 95\% & Family-adjusted seven-day & DM $p$ & Holm $p$ & HLN $p$ & HAC7 $p$ \\', rows_b, PW('.14') + PW('.20') + PW('.20') + 'rrrr')
            t4 = self.table3b('supp:tab:fill3b-seeds', 'Seeds: single-seed effects (percent of the reference MAE) of the primary seed and the two extra seeds, their standard deviation (ddof 1), the three-seed mean prediction\'s effect, family-adjusted interval and decision class, and the seed check, which compares decision classes (a sign change within the same class does not make a reading fragile).',
                              r'Contrast & 20260919 & 20260920 & 20260921 & SD & Three-seed mean & Seed check \\', seeds, PW('.14') + 'rrrr' + PW('.30') + PW('.12'))
            t3 = ''
            return t1 + t2 + t3 + t4

        def pcontent_cells(self, source, n_cols):
            text = F2.esc(self.a4['table_cells']['pcontent'][source])
            text = self.R(text, self.a4post.src, f'table_cells.pcontent.{source}', 'A4PCN/A4PCW cell (RULE B-9)') if F2.tokens(text) else text
            return [r'\multicolumn{' + str(n_cols) + r'}{l}{' + text + '}']

        def combination_table3b(self):
            rows = []
            for source in SOURCES:
                comb = self.a2[source]['combination']
                if comb.get('state') != 'COMPUTED':
                    rows.append(source + r' & \multicolumn{6}{l}{' + self.verbatim(comb['sentence'], f'tasks.{source}.combination.sentence') + r'} \\')
                    continue
                reps = comb['family']['reports']
                ds = [self.decimals(r['bootstrap']['1'].get('interval95_percent')) for r in reps]
                d = max(ds) if ds else 2
                crob = self.a3post.task(source).get('combination_robustness_a3', {})
                for j, r in enumerate(reps):
                    base = f'tasks.{source}.combination.family.reports[{j}]'
                    lab = (crob.get(f"{r['arm']}-{r['reference']}") or {}).get('label')
                    rows.append(' & '.join([self.combo_tex(r['arm'], r['reference']),
                                            self.num(self.A2.fmt_effect(r.get('effect_percent_reference_mae'), d), base + '.effect_percent_reference_mae', f'{d} decimals (table column rule)'),
                                            self.cell_interval(r['bootstrap']['1'].get('interval_family_adjusted_percent'), d, base + '.bootstrap.1.interval_family_adjusted_percent'),
                                            self.cell_interval(r['bootstrap']['7'].get('interval95_percent'), d, base + '.bootstrap.7.interval95_percent'),
                                            self.cell_p(r.get('holm_p'), base + '.holm_p'),
                                            F2.esc(A4.TS_WORDS.get(r.get('decision'), 'not evaluable')),
                                            F2.esc(A4.COMBO_ROBUST.get(lab, 'not evaluable'))]) + r' \\')
            return self.table3b('supp:tab:fill3b-combination', 'Strong-benchmark combination check: each forecast averaged equally with the price-only LEAR benchmark (news) or the P5MIN-augmented reference NP (notices). Effect in percent of the combined reference error; family-adjusted one-day and per-contrast seven-day intervals; Holm-adjusted $p$; decision class and the combination\'s own inferential robustness label.',
                                r'Contrast & Effect (\%) & Family-adjusted & Seven-day 95\% & Holm $p$ & Class & Robustness \\', rows,
                                PW('.16') + 'r' + PW('.18') + PW('.18') + 'r' + PW('.12') + PW('.12'))

        def cheap_table3b(self):
            rows = []
            for source in SOURCES:
                items = list(self.a3post.task(source)['a3_new_cheap_contrasts'].items())
                ds = [self.decimals(((rep.get('bootstrap') or {}).get('1') or {}).get('interval95_percent')) for _, rep in items if rep.get('state') == 'COMPUTED']
                d = max(ds) if ds else 2
                for key, rep in items:
                    a, b = key.split('-')
                    if rep.get('state') == 'COMPUTED':
                        rows.append(' & '.join([source, self.pair(a, b)] + self.a3_report_cells_d(rep, f'tasks.{source}.a3_new_cheap_contrasts.{key}', d)) + r' \\')
                    else:
                        rows.append(' & '.join([source, self.pair(a, b), '--', '--', '--', '--', self.plain_state(rep.get('state', 'NOT_RECORDED'))]) + r' \\')
            return self.table3b('supp:tab:fill3b-cheap', 'Cheap-text comparisons of the third addendum: each primary representation against representations built from the same documents (unadjusted, complete windows, frozen daily inference); result words are those of single secondary contrasts.',
                                r'Task & Contrast & Days & Effect (\%) & One-day 95\% & DM $p$ & Result \\', rows, 'lllllll')

        def a3_report_cells_d(self, rep, base, d):
            one = (rep.get('bootstrap') or {}).get('1', {}).get('interval95_percent')
            days = self.R(str(rep['n_days']), self.a3post.src, base + '.n_days', 'days') if rep.get('n_days') is not None else '--'
            eff = self.R('$' + self.A2.fmt_effect(rep.get('effect_percent_reference_mae'), d) + '$', self.a3post.src, base + '.effect_percent_reference_mae', f'{d} decimals (table column rule)')
            iv = self.cell_interval(one, d, base + '.bootstrap.1.interval95_percent', self.a3post.src)
            p = self.cell_p(rep.get('p_two_sided'), base + '.p_two_sided', self.a3post.src)
            cls = self.A2.decision_class(rep.get('mean_difference'), rep.get('p_two_sided'))
            return [days, eff, iv, p, F2.esc(A4.CS_WORDS.get(cls, 'not evaluable'))]

        def all_secondary_table3b(self, source):
            rows, marked = [], False
            items = list(self.secondary[source].items())
            ds = [self.decimals(c.i1) for _, c in items if not isinstance(c, dict) and c.i1]
            d = max(ds) if ds else 2
            for key, c in items:
                mark = self.dagger(c)
                marked = marked or bool(mark)
                if 'P_content' in key:
                    require(isinstance(c, dict), f'Evaluable P_content slot {key} rendered (impossible state, A4 K4.1)')
                    rows.append(' & '.join([self.pair(*key) + mark] + self.pcontent_cells(source, 5)) + r' \\')
                    continue
                if isinstance(c, dict):
                    rows.append(' & '.join([self.pair(*key) + mark, '--', '--', '--', '--', self.plain_state(c.get('state'))]) + r' \\')
                    continue
                src = F2.trace_path(self.s.scored / c.file)
                days = self.count(c.slot['days'], self.s.src('SCORE_REPORT.json'), f'{source}.secondary[{key[0]}-{key[1]}].days')
                eff = self.num(self.A2.fmt_effect(c.effect, d), 'reports[0].bootstrap.1.effect_percent_reference_mae', f'{d} decimals (table column rule)', src) if finite(c.effect) else 'undefined'
                iv = self.cell_interval(c.i1, d, 'reports[0].bootstrap.1.interval95_percent', src)
                p = self.cell_p(c.dm.get('p_two_sided'), 'reports[0].dm_p1.p_two_sided', src)
                cls = self.A2.decision_class(c.mean, c.dm.get('p_two_sided'))
                rows.append(' & '.join([self.pair(*key) + mark, days, eff, iv, p, F2.esc(A4.CS_WORDS.get(cls, 'not evaluable'))]) + r' \\')
            note = ' $^{\\dagger}$Evaluated on the target days with shifted-source support only.' if marked else ''
            return self.table3b(f'supp:tab:fill3b-secondary-{source}', ('News' if source == 'news' else 'Notice') + ' secondary contrasts (frozen slots, main seed): days, effect in percent of the second-named arm with its per-contrast one-day 95\\% interval, raw DM $p$ and the result word of a single secondary contrast (seven-day intervals are in the score files). Unadjusted; no secondary contrast can change a primary reading; reassignment rows are not evaluable.' + note,
                                r'Contrast & Days & Effect (\%) & One-day 95\% & DM $p$ & Result \\', rows, PW('.20') + 'rr' + PW('.22') + 'r' + PW('.28'))

        def supp_sens_table3b(self):
            """Matrix of sensitivities (rows) by primary contrast (columns): effect and class; descriptive subsets carry A4SUB (RULE B-10)."""
            cols = [(s_, i) for s_ in SOURCES for i in range(len(self.a2[s_]['primary']))]
            sub = F2.esc(A4.SENTENCES['A4SUB'])
            words = {'FAVORABLE': A4.TS_WORDS[IMP], 'UNFAVORABLE': A4.TS_WORDS[DET], 'NO_RELIABLE': A4.TS_WORDS[NULL], 'UNDEFINED': 'not evaluable'}
            matrix = OrderedDict()
            for seed in F2.EXTRA_SEEDS:
                cells = {}
                for source in SOURCES:
                    fname = f'{source}__SEED_{seed}.json'
                    if not self.s.has(fname):
                        continue
                    for j, rep in enumerate(self.s.json(fname)['reports']):
                        c = F2.Contrast(source, rep, fname, j, True)
                        for i, r in enumerate(self.a2[source]['primary']):
                            if (r['arm'], r['reference']) == (c.arm, c.ref):
                                cells[(source, i)] = (c.effect, F2.esc(A4.TS_WORDS.get(rep.get('primary_decision'), 'not evaluable')), self.s.src(fname), f'reports[{j}].bootstrap.1.effect_percent_reference_mae')
                matrix[('seed', seed)] = cells
            for name, cells in self.sensitivity_matrix().items():
                if name == 'U3':
                    continue                     # the strictly unexposed subset is stated once, by its own sentences below the table
                matrix[('sens', name)] = {k: (eff, sub if name in ('U2', 'U3') else F2.esc(words[cls]), src, field + ' effect') for k, (eff, iv, cls, src, field) in cells.items()}
            rows = []
            for (kind, name), cells in matrix.items():
                label = 'seed ' + self.R(str(name), F3.DESIGN_REL, 'seeds_extra', 'pre-specified extra seed') if kind == 'seed' else self.tn(name)
                row = [label]
                for s_, i in cols:
                    if (s_, i) not in cells:
                        row.append('--')
                        continue
                    eff, word, src, field = cells[(s_, i)]
                    d = self.task_decimals(s_)
                    e = self.num(self.A2.fmt_effect(eff, d), field, f'{d} decimals', src) if finite(eff) else 'undefined'
                    row.append(e + '; ' + word)
                rows.append(' & '.join(row) + r' \\')
            head = 'Sensitivity & ' + ' & '.join(self.pair(self.row(s_, i)['arm'], self.row(s_, i)['reference']) for s_, i in cols) + r' \\'
            w = '%.2f' % (0.74 / max(1, len(cols)))
            return self.table3b('supp:tab:fill3b-sensitivity', 'Pre-specified sensitivities of the primary contrasts: effect (percent of the reference error) and decision class with the extra seeds (fixed-family Holm), the 24-hour news window, first-chunk encoding, the first seven notice days dropped, the official-cap re-clip of notice predictions and label replacement when run; the descriptive subset of days with no recorded analysis, which includes the period of unknown use, carries no decision class, and the stricter subset of days with no recorded or unknown prior use is stated in the text. One-day intervals are in the score files.',
                                head, rows, PW('.15') + PW(w) * len(cols))

        def diagnostics3b(self):
            src = self.s.src('SCORE_REPORT.json')
            ev = {s: self.report[s].get('severe_events', {}) for s in SOURCES}
            severe = []
            for s in SOURCES:
                n = ev[s].get('events', 0)
                severe.append(f'The inherited connected severe-event rule records {self.count(n, src, f"{s}.severe_events.events")} connected ' + ('event' if n == 1 else 'events') + (' for news.' if s == 'news' else ' for notices.'))
            lear = (self.a1 or {}).get('lear_convergence_diagnostic') or {}
            if lear.get('state') == 'DESCRIPTIVE_ONLY':
                lear_text = ('Confirmation LEAR solver diagnostic (descriptive): ' + self.count(lear['cd_nonconverged_hour_fits'], src, 'A1.lear_convergence_diagnostic.cd_nonconverged_hour_fits') +
                             ' of ' + self.count(lear['hour_fits'], src, 'A1.lear_convergence_diagnostic.hour_fits') + ' hour fits recorded a coordinate-descent convergence warning and ' +
                             self.count(lear['hour_fits_with_lars_convergence_warning'], src, 'A1.lear_convergence_diagnostic.hour_fits_with_lars_convergence_warning') +
                             ' a LARS convergence warning; none is fatal under the template rule.')
            else:
                lear_text = 'Confirmation LEAR solver diagnostic: ' + self.plain_state(lear.get('state', 'NOT_RECORDED')) + '.'
            return '\n'.join(['Section~\\ref{supp:execution} gives the stage dispositions and the clipping record of every arm, seed and variant.',
                              self.coverage_sentence('news') + ' ' + self.coverage_sentence('notice') + ' ' + self.clipping_sentence('news') + ' ' +
                              self.clipping_sentence('notice') + ' ' + ' '.join(severe) + ' ' + lear_text, ''])

        # ------------------------------------------------------------------ planted-signal record (RULE B-15)
        def pick_a4(self, source, key):
            """The A4 section-6 sentence of one form, verbatim (prefix of the frozen form up to its first placeholder)."""
            prefix = A4.SENTENCES[key].replace('{task_label}', self.A3.TASK_LABEL[source]).split('{')[0]
            require(len(prefix) > 20, 'A4 form prefix too short to identify ' + key)
            hits = [(k, s) for k, s in enumerate(self.a4['tasks'][source]['section6']) if s.startswith(prefix)]
            return hits

        def pc_supplement3b(self):
            out = [self.a3fixed(self.A3.SENTENCES['A3P1'], 'A3P1')]
            news6 = self.a4['tasks']['news']['section6']
            for key in ('A4P0', 'A4P1N'):
                for k, s in self.pick_a4('news', key):
                    out.append(self.a4s(s, f'tasks.news.section6[{k}]', symbols=False))
            for source in SOURCES:
                for key in ('A4P1T', 'A4PX_RUN2', 'A4PX_NOT2'):
                    for k, s in self.pick_a4(source, key):
                        out.append(self.a4s(s, f'tasks.{source}.section6[{k}]', symbols=False))
            out.append('Table~\\ref{supp:tab:fill3b-pc} gives every strength.')
            rows = []
            for i, r in enumerate(self.pc.data['summary']):
                if r['tier'] == 'N1':
                    continue
                src, field = self.pc.src, f'summary[{i}]'
                lo, hi = r['detection_cp95']
                if r['mult'] == 0.0:
                    strength = self.R(f"null, frozen {r['replicates']}", src, field + '.replicates', 'frozen null replicates')
                else:
                    strength = self.R(f"{r['mult']:g}", src, field + '.mult', 'planted strength') + ' $\\times$ MDE'
                rows.append(' & '.join([F2.esc(r['task']), F2.esc({'notice': 'notices', 'N2': 'news, replicated', 'CAP': 'news, capacity'}[r['tier']]), strength,
                                        self.R(f"{r['detected']}/{r['replicates']}", src, field + '.detected/replicates', 'count'),
                                        self.R(f'[{math.floor(lo * 1000) / 1000:.3f}, {math.ceil(hi * 1000) / 1000:.3f}]', src, field + '.detection_cp95', 'outward 3 decimals'),
                                        self.count(r['any_direction_rejections'], src, field + '.any_direction_rejections'),
                                        self.R('$' + self.A2.fmt_effect(r['delta_pct_median'], 3) + '$', src, field + '.delta_pct_median', '3 decimals'),
                                        self.R(f"{r['uptake_median']:.3f}", src, field + '.uptake_median', '3 decimals') if finite(r.get('uptake_median')) else '--']) + r' \\')
            for source in SOURCES:
                pc = self.a4['tasks'][source].get('positive_control') or {}
                if pc.get('extension') != 'RUN':
                    continue
                base = f'tasks.{source}.positive_control'
                lo, hi = pc['cp0']
                rows.append(' & '.join([source, 'notices' if source == 'notice' else 'news, replicated',
                                        self.R(self.T3['supplement_block.pc_null_ext'] + f" ({pc['R0']})", self.a4post.src, base + '.R0', 'all null replicates (frozen and extension)'),
                                        self.R(f"{pc['k0']}/{pc['R0']}", self.a4post.src, base + '.k0/R0', 'count'),
                                        self.R(f'[{math.floor(lo * 1000) / 1000:.3f}, {math.ceil(hi * 1000) / 1000:.3f}]', self.a4post.src, base + '.cp0', 'outward 3 decimals'),
                                        '--', '--', '--']) + r' \\')
            table = self.table3b('supp:tab:fill3b-pc', 'Planted-signal check, a pipeline signal-use and negative-control diagnostic, on pre-confirmation windows of confirmation size: a column equal to the realised target (notices: residual target) on a random share of units, added to the activity reference; detections over replicates (detection rate under this planting scheme) with Clopper--Pearson 95\\% intervals, any-direction rejections, median realised effect (percent of the reference MAE) and median uptake; with the null extension, the permuted negative-control column over all null replicates.',
                                 r'Task & Tier & Strength & Detected & CP 95\% & Any direction & Median $\Delta$ & Uptake \\', rows, 'llllllll')
            n1 = [r for r in self.pc.data['summary'] if r['tier'] == 'N1' and r['mult'] > 0]
            n2 = {r['mult']: r for r in self.pc.data['summary'] if r['tier'] == 'N2' and r['mult'] > 0}
            agree = [r['mult'] for r in n1 if r['mult'] in n2 and (r['detection_rate'] >= .5) == (n2[r['mult']]['detection_rate'] >= .5)]
            dis = [r['mult'] for r in n1 if r['mult'] in n2 and r['mult'] not in agree]
            text = ''
            if n1:
                lst = self.R(F3A_.join_list(f'{m:g}' for m in agree) or 'none of the', self.pc.src, 'summary (tier N1 vs N2)', 'strengths where N1 agrees with N2')
                dclause = (' and disagreed at ' + self.R(F3A_.join_list(f'{m:g}' for m in dis), self.pc.src, 'summary (tier N1 vs N2)', 'strengths of disagreement')) if dis else ''
                text = self.t3b('supplement_block.n1', list=lst, disagree_clause=dclause)
            return '\n'.join([' '.join(out), table, text, ''])

        def batches_supplement3b(self):
            out = []
            if self.label is not None and self.label.scored:
                rows = []
                for s in SOURCES:
                    d = self.task_decimals(s)
                    for i, rep in enumerate(self.label.data['families'][s]['reports']):
                        one = rep['bootstrap']['1'].get('interval95_percent')
                        base = f'families.{s}.reports[{i}]'
                        st = self.a3post.task(s)['design_sensitivities'][f"{rep['arm']}-{rep['reference']}"]['label_replacement']
                        rows.append(' & '.join([self.pair(rep['arm'], rep['reference']),
                                                self.num(self.A2.fmt_effect(rep.get('effect_percent_reference_mae'), d), base + '.effect_percent_reference_mae', f'{d} decimals', self.label.src),
                                                self.cell_interval(one, d, base + '.bootstrap.1.interval95_percent', self.label.src),
                                                F2.esc(A4.TS_WORDS.get(rep['decision'], 'not evaluable')), {'SAME': 'reproduced', 'DIFFERENT': 'changed'}.get(st.get('state'), 'not evaluable')]) + r' \\')
                out.append(self.label_paragraph3a())
                out.append('Table~\\ref{supp:tab:fill3b-label} gives the primary contrasts with re-extracted labels.')
                out.append(self.table3b('supp:tab:fill3b-label', 'Primary contrasts with independently re-extracted test-period labels and the same fitted models; a reading is reproduced when its decision class is unchanged (third addendum, class-only agreement).',
                                        r'Contrast & Effect (\%) & One-day 95\% & Class & Reading \\', rows, 'lllll'))
            else:
                out.append(self.label_paragraph3a())
            if self.batch is not None:
                out.append(self.batch_forms3b())
                out.append(self.batch_descriptive())
            else:
                out.append(self.t3b('secondary.batch_pending'))
            return ' '.join(o for o in out if o) + '\n'

        def batch_forms3b(self):
            """The per-arm A2BATCH forms (moved from the main text; SPEC RULE B-6)."""
            out = []
            d = self.batch.data
            spec_text = ' '.join((A2DIR / 'A2BATCH_SPEC.md').read_text().split())
            forms = {'L1': 'Under the absolute-error (median) training objective, {arm} {verb} the article-activity reference trained with the same objective ({effect}% of the reference error, per-contrast 95% interval [{lo}, {hi}]%, Holm-adjusted {p} within this secondary family); {robustness}.',
                     'PD': 'With AEMO pre-dispatch demand and semi-scheduled generation forecasts as additional inputs, {arm} {verb} the article-activity reference with the same inputs ({effect}% of the reference error, per-contrast 95% interval [{lo}, {hi}]%, Holm-adjusted {p} within this secondary family); {robustness}.'}
            rob = self.a3post.task('news').get('batch_robustness_a3', {})
            for fam, key in (('L1', 'A1'), ('PD', 'A2')):
                require(' '.join(forms[fam].split()) in spec_text, f'A2BATCH form {key} not verbatim in the frozen spec')
                f = d['families'][fam]
                if f['state'] != 'COMPUTED':
                    continue
                for j, rep in enumerate(f['reports']):
                    cls = self.A2.decision_class(rep.get('mean_difference'), rep.get('holm_p'))
                    require(cls == rep['decision'], f'A2BATCH {fam} decision differs from the frozen class rule')
                    rb = rob.get(f"{fam}:{rep['arm']}-{rep['reference']}")
                    require(rb is not None, 'A3 batch robustness missing for ' + rep['arm'])
                    one = rep['bootstrap']['1'].get('interval95_percent')
                    dd = self.decimals(one)
                    base = f'families.{fam}.reports[{j}]'
                    e_txt = self.A2.fmt_effect(rep.get('effect_percent_reference_mae'), dd)
                    lo, hi = self.A2.fmt_interval(one, dd)
                    ptex_, ptxt = self.ptex(rep.get('holm_p'), base + '.holm_p', self.batch.src)
                    verb = {'NO_RELIABLE_INCREMENT_DETECTED': 'showed no reliable increment over', 'CONDITIONAL_IMPROVEMENT': 'improved on',
                            'CONDITIONAL_DETERIORATION': 'performed reliably worse than'}.get(cls, 'could not be compared with')
                    latex = dict(arm=self.arm(rep['arm']), verb=verb, effect=self.num(e_txt, base + '.effect_percent_reference_mae', f'{dd} decimals', self.batch.src),
                                 lo=self.num(lo, base + '.bootstrap.1.interval95_percent[0]', 'outward', self.batch.src),
                                 hi=self.num(hi, base + '.bootstrap.1.interval95_percent[1]', 'outward', self.batch.src), p=ptex_, robustness=F2.esc(rb['sentence'] or ''))
                    plain = dict(arm=rep['arm'], verb=verb, effect=e_txt, lo=lo, hi=hi, p=ptxt, robustness=rb['sentence'] or '')
                    out.append(self.form(key, latex, plain, template=forms[fam], src='autopilot/q1_audits/CONF/A2/A2BATCH_SPEC.md'))
            return ' '.join(out)

        # ------------------------------------------------------------------ supplement S9 (RULES B-4, B-14)
        def execution_block3b(self):
            S = 'supplement_block.'
            src = self.a4post.src
            disp = {d.get('stage'): d for d in self.report.get('stage_dispositions', [])}
            rows = []
            for k, st in enumerate(self.a4['stage_table']):
                name = self.T3['stage_names'].get(st['stage']) or self.T3['stage_names_new'].get(st['stage'])
                require(name is not None, f"No plain name for stage {st['stage']!r}")
                d = disp.get(st['stage'])
                phrases = {**self.RULES['code_phrases'], **self.T3['plain_states']}
                if st.get('reason') and st['stage'] in ('A2B-1', 'A2B-2'):
                    why = F2.esc(st['reason'])
                elif d is not None:
                    unav = d.get('unavailable_configurations') or []
                    why = self.plain_state(d.get('state')) + (('; ' + '; '.join(self.plain_state(state) for state in sorted({u.get('state') for u in unav}))) if unav else '')
                elif st.get('state') in phrases:
                    why = self.plain_state(st['state'])
                elif st.get('state') in (self.T3.get('batch_reasons') or {}):
                    why = F2.esc(self.T3['batch_reasons'][st['state']])
                elif st.get('state'):
                    why = 'state recorded in the stage receipt'
                else:
                    why = 'no result file when this version was filled'
                fits = self.count(len(d.get('registered_tasks', [])), self.s.src('SCORE_REPORT.json'), f"stage_dispositions[{st['stage']}].registered_tasks") if d is not None else '--'
                sname = F2.esc(name)
                sname = self.R(sname, TEMPLATES_REL, 'stage_names.' + st['stage'], 'plain stage name') if F2.tokens(sname) else sname
                rows.append(' & '.join([sname, F2.esc(st['category']), why, fits]) + r' \\')
            stages = self.table3b('supp:tab:fill3b-stages', self.t3b(S + 'stage_caption'), self.T3[S + 'stage_header'], rows, PW('.27') + PW('.22') + PW('.34') + PR('.07'))
            out = [stages]
            for source in SOURCES:
                out.append(self.clipping_table3b(source))
            return '\n'.join(out) + '\n'

        def clipping_table3b(self, source):
            S = 'supplement_block.'
            rows = []
            for r in self.clipping_rows(source, main_only=False):
                src = self.s.src(source + '__CLIPPING.csv')
                var = F2.esc(r['variant'])
                var = self.R(var, src, 'variant', 'variant name; digits are part of the name') if F2.tokens(var) else var
                cells = [self.arm(r['arm']) if r['arm'] in F2.ARM_TEX else F2.esc(r['arm']), self.R(str(r['seed']), src, 'seed', 'seed'), var]
                for k in ('eligible_predictions', 'clipping_operations', 'raw_below_lower', 'raw_above_upper', 'final_lower_hits', 'final_upper_hits'):
                    cells.append(self.count(int(float(r[k])), src, f"{r['arm']}|{r['seed']}|{r['variant']}: {k}"))
                rows.append(' & '.join(cells) + r' \\')
            pub = PUBLISHED[source]
            digest = sha256(self.s.scored / (source + '__CLIPPING.csv'))
            cap = self.t3b(S + 'clip_caption', task='News' if source == 'news' else 'Notice', file=F2.esc(pub), sha=F2.hexcode(digest))
            head = self.T3[S + 'clip_header']
            return ('{\\footnotesize\\setlength{\\tabcolsep}{' + self.layout('3pt') + '}\n\\begin{longtable}{' + self.layout('@{}' + PW('.15') + 'rl' + PR('.085') * 6 + '@{}') + '}\n\\caption{' + cap + '}\\label{supp:tab:fill3b-clipping-' + source + '}\\\\\n\\toprule\n' + head +
                    '\n\\midrule\n\\endfirsthead\n\\toprule\n' + head + '\n\\midrule\n\\endhead\n\\bottomrule\n\\endfoot\n' + '\n'.join(rows) + '\n\\end{longtable}}\n')

        # ------------------------------------------------------------------ forest figure (RULE B-5)
        def forest_rows3b(self):
            rows = self.forest_rows3a()
            for r in rows:
                if r['ref'] == 'P_content' or r['arm'] == 'P_content':
                    r.update(effect=None, thick=None, thin=None, pcontent=self.a4['table_cells']['pcontent'][r['task']],
                             src=self.a4post.src, field=f"table_cells.pcontent.{r['task']}")
            return rows

        def forest(self):
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            matplotlib.rcParams.update({'pdf.fonttype': 42, 'font.size': 7.5, 'axes.linewidth': 0.6, 'svg.hashsalt': 'fill3b'})
            rows = self.forest_rows3b()
            heights = [max(2.0, 0.21 * sum(1 for r in rows if r['task'] == s) + 0.9) for s in SOURCES]
            fig, axes = plt.subplots(1, 2, figsize=(7.2, max(heights)))
            for ax, source in zip(axes, SOURCES):
                sub = [r for r in rows if r['task'] == source]
                y = np.arange(len(sub))[::-1].astype(float)
                labels, vals = [], [0.0]
                for r in sub:
                    for iv in (r['thick'], r['thin']):
                        if iv:
                            vals += [float(v) for v in iv]
                lo, hi = min(vals), max(vals)
                pad = 0.08 * (hi - lo if hi > lo else 1.0)
                xmin, xmax = lo - pad, hi + pad
                prim_y = [yy for yy, r in zip(y, sub) if r['group'] == 'Primary']
                for yy, r in zip(y, sub):
                    comb = r['group'] == 'Combination'
                    labels.append(('$C(' if comb else '$') + F2.ARM_TEX[r['arm']] + (')-C(' if comb else '-') + F2.ARM_TEX[r['ref']] + (')$' if comb else '$'))
                    if r.get('pcontent'):
                        ax.text((xmin + xmax) / 2, yy, r['pcontent'], va='center', ha='center', fontsize=5.6, color='0.35')
                        continue
                    if r['effect'] is None or r['thick'] is None:
                        ax.text((xmin + xmax) / 2, yy, 'not computed', va='center', ha='center', fontsize=6.5, color='0.35')
                        continue
                    ax.plot(r['thick'], [yy + 0.08, yy + 0.08], color='#1f4e79', lw=2.6, solid_capstyle='butt')
                    if r['thin'] is not None:
                        ax.plot(r['thin'], [yy - 0.18, yy - 0.18], color='#7f7f7f', lw=1.0, solid_capstyle='butt')
                    ax.plot([r['effect']], [yy + 0.08], 'o', color='black', ms=3.0, zorder=3)
                S = self.A2.SESOI[source]
                ax.axvline(0, color='0.2', lw=0.6)
                ytop, ybot = (max(prim_y) + 0.5, min(prim_y) - 0.5) if prim_y else (0.5, -0.5)
                if xmin <= -S <= xmax:
                    ax.plot([-S, -S], [ybot, ytop], color='#a33', lw=0.8, ls='--')
                else:
                    edge = xmin if -S < xmin else xmax
                    ymid = (ytop + ybot) / 2
                    ax.annotate(f'$-{S:g}\\%$ (off axis)', xy=(edge, ymid), xytext=(edge + (0.18 if edge == xmin else -0.18) * (xmax - xmin), ymid),
                                fontsize=6.5, color='#a33', ha='left' if edge == xmin else 'right', va='center', arrowprops=dict(arrowstyle='->', color='#a33', lw=0.8))
                ax.set_xlim(xmin, xmax)
                ax.set_ylim((y[-1] - 1.0) if len(y) else -1, (y[0] + 0.7) if len(y) else 1)
                ax.set_yticks(y)
                ax.set_yticklabels(labels)
                ax.set_title('Day-ahead news' if source == 'news' else 'Market notices')
                ax.set_xlabel('% of the reference error')
                groups = [r['group'] for r in sub]
                for k in range(1, len(groups)):
                    if groups[k] != groups[k - 1]:
                        ax.axhline((y[k] + y[k - 1]) / 2, color='0.85', lw=0.5)
            from matplotlib.lines import Line2D
            fig.legend(handles=[Line2D([0], [0], color='#1f4e79', lw=2.6, label='primary/combination: family-adjusted one-day; others: per-contrast one-day 95%'),
                                Line2D([0], [0], color='#7f7f7f', lw=1.0, label='per-contrast seven-day 95%')],
                       loc='lower center', ncol=2, fontsize=6.5, frameon=False)
            fig.tight_layout(rect=(0, 0.06, 1, 1))
            buf = io.BytesIO()
            fig.savefig(buf, format='pdf', metadata={'CreationDate': None, 'Creator': 'fill3b_conf_results.py', 'Producer': None})
            plt.close(fig)
            out = io.StringIO()
            w = csv.writer(out)
            w.writerow(['task', 'group', 'contrast', 'effect_percent', 'thick_type', 'thick_lo', 'thick_hi', 'seven_day_lo', 'seven_day_hi', 'note', 'source_file', 'source_field'])
            for r in rows:
                w.writerow([r['task'], r['group'], f"{r['arm']}-{r['ref']}", r['effect'], r['thick_type'], *(r['thick'] or [None, None]), *(r['thin'] or [None, None]),
                            r.get('pcontent', ''), r['src'], r['field']])
            self.figure_rows = rows
            return buf.getvalue(), out.getvalue()

    return Fill3b


# ============================================================================= host edits (declared slots)
def slot_index(T):
    return {s['id']: s for s in T['slots']}


def host_edits(r, reader, states):
    """(slot id, file, exact old text, new text). Every old text is a declared FILL3b slot anchor (SPEC 4)."""
    T = r.T3
    S = slot_index(T)
    abstract_line = reader('sections/abstract.tex').split('\n')[0]
    pending = r.review_key()
    any_scored = len(pending) < 4
    edits = []

    def e(sid, new, old=None):
        s = S[sid]
        rel, old = s['file'], old if old is not None else s['anchor']
        text = reader(rel)
        if old in text and '\x00' in new:
            i = text.index(old)
            start, end = text.rfind('\n', 0, i) + 1, text.find('\n', i + len(old))
            end = len(text) if end < 0 else end
            pre, post = text[start:i], text[i + len(old):end]
            if F2MOD.tokens(pre) or F2MOD.tokens(post):
                line = text[:i].count('\n') + 1
                carry = lambda seg: F2MOD.NUMRE.sub(lambda m: r.carry(rel, line, m.group(0).rstrip(',')) + (',' if m.group(0).endswith(',') else ''), seg)  # noqa: E731
                old, new = pre + old + post, carry(pre) + new + carry(post)
        edits.append((sid, rel, old, new))

    e('abstract', r.abstract3b() + TAG, old=abstract_line)
    e('abstract-marker', '% Abstract rendered by fill3b_conf_results.py from the frozen fourth-addendum readings (A4 abstract ladder).')
    e('highlight', '\\item ' + r.highlight3b())
    e('intro-pending', r.t3b('intro.pending_clause'))
    e('intro-marker', r.t3b('intro.marker'))
    e('intro-final', r.t3b('intro.final_clause'))
    e('design-caption', r.t3b('design.caption'))
    e('design-execution', '\\end{table}\n' + r.execution_sentence3b() + '\n')
    e('design-timestamps', r.timestamp_sentence())
    e('design-e3-marker', 'cannot isolate their contributions.\n' + r.t3b('design.e3_marker') + '\n')
    e('design-diagnostics', r.t3b('design.diagnostics'))
    e('news-results-marker', '\\input{' + GENERATED['primary'][:-4] + '}')
    e('news-results-pending', r.t3b('news_results.pending_line'))
    e('notice-results-marker', '\\input{' + GENERATED['secondary'][:-4] + '}')
    e('notice-e3-marker', r.t3b('notice_results.e3_comment'))
    e('notice-a1-marker', r.t3b('notice_results.a1_marker'))
    e('notice-a1-secondary-marker', r.t3b('notice_results.a1_secondary_marker'))
    if states['POSITIVE_CONTROL'] == 'FILLED':
        e('notice-pc-marker', r.t3b('notice_results.pc_marker'))
        e('supp-pc-reserved', r.t3b('supplement.pc_reserved_new'))
    e('discussion-lear', r.t3b('discussion.lear'))
    e('discussion-rule', r.t3b('discussion.rule'))
    e('discussion-marker', '\\input{' + GENERATED['discussion'][:-4] + '}')
    e('conclusion-marker', '\\input{' + GENERATED['conclusion'][:-4] + '}')
    e('conclusion-pending', r.t3b('conclusion.pending_line'))
    e('conclusion-hist-2025', '')
    e('conclusion-hist-final', '')
    if states['BASE25'] == 'FILLED':
        e('base25-marker', '% Post hoc 2025 benchmark values above verified against the hash-checked BASE25 result by fill3b_conf_results.py; the fixed table is in Supplement S5.')
    if any_scored:
        if pending:
            word = 'is' if len(pending) == 1 else 'are'
            e('human-intro', r.t3b('human.intro.some', pending=F3A.join_list(pending), is_are=word))
            e('discussion-review', r.t3b('discussion.review.some', pending=F3A.join_list(pending), is_are=word))
        else:
            e('human-intro', r.t3b('human.intro.all'))
            e('discussion-review', r.t3b('discussion.review.all'))
    if states['REVIEW_NEWS'] == 'REPORTED':
        e('human-news', r.news_review_sentence().replace(' % numbers traced in MS12_CONF_TRACE.csv', TAG))
        e('supp-news-review', r.t3b('human.s5_line').replace('supp:tab:fill3-news-review', 'supp:tab:fill3b-news-review') + '\n\\input{' + GENERATED['news_review'][:-4] + '}')
        e('supp-news-check', r.t3b('human.marker_news_check').replace('fill3a', 'fill3b'))
    if states['REVIEW_NRX'] == 'REPORTED':
        e('human-nrx', r.nrx_review_sentence().replace(' % numbers traced in MS12_CONF_TRACE.csv', TAG))
        e('supp-nrx-review', r.t3b('human.s6_line').replace('supp:tab:fill3-nrx-review', 'supp:tab:fill3b-nrx-review') + '\n\\input{' + GENERATED['nrx_review'][:-4] + '}')
    if states['REVIEW_CONF'] == 'REPORTED':
        e('human-conf', r.conf_sentence())
        e('supp-conf-review', '\\input{' + GENERATED['conf_review'][:-4] + '}')
    if states['AGREEMENT'] == 'REPORTED':
        e('human-agreement', r.agreement_sentence())
        e('supp-agreement', '\\input{' + GENERATED['agreement'][:-4] + '}')
    e('supp-reading-guide', r.t3b('supplement.reading_guide_new'))
    e('supp-access', r.t3b('supplement.access_new'))
    e('supp-s1', r.t3b('supplement.s1_new'))
    e('supp-s7-lear', r.t3b('supplement.s7_lear_new'))
    e('supp-s7-input', '\\input{supplement_sections/archive/round2_dependence}\n\\input{' + GENERATED['supplement'][:-4] + '}\n\\FloatBarrier')
    e('supp-ts-caption', r.timestamp_caption())
    e('supp-ts-row', r.timestamp_rows())
    e('supp-planned', r.t3b('supplement.planned_new'))
    e('supp-s8', r.t3b('supplement.s8_new'))
    e('supp-s9', '\\input{' + GENERATED['execution'][:-4] + '}')
    pg = r.pg_rows()
    for k in ('count', 'chen', 'act'):
        e('pg-row-' + k, pg[k])
    e('pg-marker', '% Rows for this study rendered by fill3b_conf_results.py.')
    e('pg-note', 'The rows for this study are text-versus-no-text contrasts of the confirmation window.')
    return edits


# ============================================================================= checks, plan
def check_anchors(edits, texts):
    located = []
    for sid, rel, old, _ in edits:
        require(rel in texts, f'Slot file not reachable from main.tex or supplement.tex: {rel}')
        require(not rel.startswith('audit_archive'), 'FILL3b never writes into the audit archive at fill time')
        hits = sum(text.count(old) for text in texts.values())
        require(hits == 1 and texts[rel].count(old) == 1, f'Slot anchor must occur exactly once in the reachable sources (found {hits}): {sid} {rel}: {old[:90]!r}')
        if old.lstrip().startswith('% PENDING'):
            require(any(l.rstrip() == old.rstrip() for l in texts[rel].splitlines()), f'Marker is not a whole line: {old[:80]!r}')
        located.append({'slot': sid, 'file': rel, 'line': texts[rel][:texts[rel].index(old)].count('\n') + 1, 'anchor': old[:160]})
    return located


def cap_problems(text, T, caps_applied):
    """SPEC section 7: claims excluded by the conclusion caps (cap sentences themselves removed first)."""
    for key in ('A4CAP_LEAR', 'A4CAP_CHEAP', 'A4CAP_L1', 'A4CAP_PD', 'A4CAP_ALL'):
        text = text.replace(A4MOD.SENTENCES[key], ' ')
    problems = []
    for key, pats in T['cap_claims'].items():
        if key != 'always' and key not in caps_applied:
            continue
        for pat in pats:
            m = re.search(pat, text)
            if m:
                problems.append(f'claim excluded by {key}: {m.group(0)!r}')
    return problems


def plan(manuscript, r, generated, edits, reader, binary, T):
    texts, trace = {}, []
    for sid, rel, old, new in edits:
        if rel not in texts:
            texts[rel] = reader(rel)
        require(texts[rel].count(old) == 1, f'Expected exactly one occurrence in {rel} of: {old[:90]!r}')
        if '\x00' not in new:
            require(not F2MOD.tokens(new), f'Placeholder-free replacement in {rel} contains an untraced number: {new[:90]!r}')
        texts[rel] = texts[rel].replace(old, new)
    resolved = {}
    for rel, text in texts.items():
        resolved[rel], rows = r.R.resolve(rel, text, full=False)
        trace.extend(rows)
    for rel, text in generated.items():
        if rel.endswith('.csv'):
            resolved[rel] = text
            continue
        resolved[rel], rows = r.R.resolve(rel, text)
        trace.extend(rows)
    for rel in texts:
        before, after = reader(rel).count('\n'), resolved[rel].count('\n')
        require(before == after or (rel in LINE_FREE and after == before + 1), f'Line count changed in {rel}: {before} -> {after}')
        old_lines, new_lines = reader(rel).split('\n'), resolved[rel].split('\n')
        for n, (a, b) in enumerate(zip(old_lines, new_lines), 1):
            lost = Counter(F2MOD.tokens(a)) - Counter(F2MOD.tokens(b))
            if lost and a != b:
                r.retired.append({'location': f'{rel}:{n}', 'tokens': sorted(lost.elements())})
    for rel, text in resolved.items():
        require('\x00' not in text and '\x01' not in text, 'Unresolved placeholder in ' + rel)
        require('PENDING: CONF results' not in text and 'PENDING: CONF-A1 results' not in text, 'CONF marker survives in ' + rel)
    words = F2MOD.abstract_words(resolved['sections/abstract.tex'])
    require(words <= 250 or r.abstract_over_limit, f'Abstract would have {words} words (limit 250) without the A4 L7 record')
    abstract_plain = re.sub(r'(?<!\\)%.*', '', resolved['sections/abstract.tex'])
    require(not re.search(r'FINAL3|\bCONF\b|\bNRX\b|\bE3\b|\bH1\b|\bMS12\b|content increments?|pre-D|\d/\d tests|P5MIN|\bNP\b|L14|LLaz|Lchen|L_\{|L\\_|remain pending|reviews are reported|Section',
                          abstract_plain), 'Internal code, arm symbol, pointer, vote count or review-state sentence in the abstract')
    highlights = [line[6:] for line in resolved['highlights.tex'].splitlines() if line.startswith('\\item ')]
    require(3 <= len(highlights) <= 5 and all(len(s) <= 85 for s in highlights), 'Highlight length/count rule violated')
    all_scored = not r.review_key()
    caps_applied = {k for k in ('A4CAP_LEAR', 'A4CAP_CHEAP', 'A4CAP_L1', 'A4CAP_PD') if A4MOD.SENTENCES[k] in r.a4['conclusion_core']}
    problems, rendered_plain = [], []
    for rel, text in resolved.items():
        if rel.endswith('.tex') and rel in generated:
            p = plain_text(text)
            rendered_plain.append(p)
            problems += scan_text(rel, p, T, A4MOD.BANNED_A4, strict_codes=True, allow=tuple(PUBLISHED.values()))
            problems += [rel + ': ' + x for x in cap_problems(p, T, caps_applied)]
    for sid, rel, old, new in edits:
        p = plain_text(r.R.peek(new) if '\x00' in new else new)
        rendered_plain.append(p)
        problems += scan_text(rel + ' (slot ' + sid + ')', p, T, A4MOD.BANNED_A4, strict_codes=True, allow=tuple(PUBLISHED.values()))
        problems += [rel + ': ' + x for x in cap_problems(p, T, caps_applied)]
    require(not problems, 'Rendered text check failed: ' + '; '.join(problems[:12]))
    violations = A4MOD.consistency_violations(r.a4, r.news_coverage.data['news'], rendered=rendered_plain)
    require(not violations, 'A4 K4 assertions failed on the FILL3b rendering: ' + '; '.join(violations[:12]))
    full = F3MOD.reachable(manuscript, reader)
    for rel in full:
        text = resolved.get(rel, full[rel])
        plain = plain_text(text)
        p = scan_text(rel, plain, T, A4MOD.BANNED_A4, strict_codes=False, attribution=True)
        require(not p, 'Reachable source check failed: ' + '; '.join(p[:8]))
        if all_scored:
            require('remain pending' not in plain, f'"remain pending" remains in {rel} after the reviews were scored')
    for rel, text in resolved.items():
        require(not re.search(r'strict-forward|legal(?:ly available)? anchor|\bTODO\b|\?\?', re.sub(r'(?<!\\)%.*', '', text), re.I), 'Prohibited wording in ' + rel)
    for rel in list(resolved) + list(binary):
        require(not rel.startswith(('audit_archive', 'previous_')), 'FILL3b never writes into the audit archive or a snapshot')
    return resolved, trace, words


# ============================================================================= render, write, refill
def review_slots(texts):
    found = {k: [] for k in REVIEW_CATEGORIES}
    for rel, text in texts.items():
        for n, line in enumerate(text.splitlines(), 1):
            m = re.match(r'\s*%\s*PENDING:\s*(.+?)(?:\s+--\s|$)', line)
            if not m:
                continue
            for kind, cats in REVIEW_CATEGORIES.items():
                if m.group(1).strip() in cats:
                    found[kind].append(f'{rel}:{n}')
    return found


def prefill_equality(manuscript, reader, T, coverage, slot_files):
    """SPEC 4: every pre-fill host file the fill touches equals the prefill generator's output (or the snapshot)."""
    texts, _ = prefill_texts(manuscript, T, coverage)
    snap = manuscript / T['prefill.snapshot']
    checked = []
    for rel in sorted(slot_files | {r for r in texts if r.endswith('.tex') and not r.startswith('audit_archive')}):
        expected = texts[rel] if rel in texts else ((snap / rel).read_text() if (snap / rel).is_file() else None)
        require(expected is not None, f'No prefill or snapshot text for {rel}')
        require(reader(rel) == expected, f'PREFILL_DRIFT: {rel} differs from the FILL3b prefill generated from the frozen templates')
        checked.append(rel)
    return checked


def render(args, manuscript, reader=None, previous_inputs=None):
    reader = reader or (lambda rel: (manuscript / rel).read_text())
    F3A_, F3, F2, A4 = deps()
    a2mod, rules = F3.load_a2()
    a3mod, rules3 = F3A_.load_a3()
    T = templates()
    scores = F2.Scores(args.state)
    adapter = F2.frozen_adapter()
    a1mod, scoring = F2.frozen_a1()
    require(scores.report.get('A1') is not None, 'SCORE_REPORT.json has no pre-score addendum section')
    a2post = F3.A2Post(a2mod, scores, Path(args.state), rerun=True, test_keys_per_day=getattr(args, 'test_keys_per_day', None))
    pcx_info = check_pcx(args)
    optional3 = {'positive_control': (args.positive_control, 'pc'), 'a2batch': (args.a2batch, 'a2batch'), 'a2label': (args.a2label, 'a2label')}
    a3post = F3A_.A3Post(a3mod, scores, Path(args.state), a2post, optional3, rerun=True)
    coverage = Coverage(args.coverage)
    require(coverage.data is not None, 'News matched coverage file missing: it must be computed and time-stamped before scoring (a3_postscore.py --coverage-only)')
    opt4 = {'positive_control': args.positive_control if Path(args.positive_control).is_file() else None,
            'pcx': args.pcx if Path(args.pcx).is_file() else None,
            'a2batch': args.a2batch if Path(args.a2batch).is_file() else None,
            'a2label': args.a2label if Path(args.a2label).is_file() else None}
    a4post = A4Post(A4, scores, Path(args.state), a2post.grid, opt4, coverage, rerun=True)
    base25 = F2.Base25(args.base25_root) if (Path(args.base25_root) / F2.BASE25_RESULT).exists() else None
    pc = F2.PositiveControl(args.positive_control) if Path(args.positive_control).exists() else None
    reviews = {'news': F3.Review('news', args.news_review_scores), 'nrx': F3.Review('nrx', args.nrx_review_scores)}
    conf_review, agreement = F3A_.ConfReview(args.conf_review_scores), F3A_.Agreement(args.agreement)
    pair_tables = check_pair_trace(agreement) if agreement.scored else {}
    texts = F3.reachable(manuscript, reader)
    slots = review_slots(texts)
    for kind, scored in (('news', reviews['news'].scored), ('nrx', reviews['nrx'].scored), ('conf', conf_review.scored), ('agreement', agreement.scored)):
        require(bool(slots[kind]) or not scored, f'{kind} review is scored but its manuscript slot is not pending: it was filled by hand; FILL3b refuses to duplicate it')
        require(scored or slots[kind], f'{kind} review is not scored but its manuscript slot is not pending')
    timestamps = Timestamps(args.timestamps, scores.scored / 'SCORE_RECEIPT.json', coverage, FREEZE_NAME, pcx_info['pcx_freeze'])
    batch = F3.Batch(args.a2batch, scores) if Path(args.a2batch).exists() else None
    label = F3.Label(args.a2label, scores) if Path(args.a2label).exists() else None
    traces = F3.trace_index(manuscript)
    Fill3b = renderer_class(F3A_, F3, F2, A4)
    r = Fill3b(scores, adapter, F2.Templates(MS / F2.TEMPLATES_NAME), a1=a1mod, holm=scoring, base25=base25, pc=pc,
               reviews={'news': 'PENDING', 'nrx': 'PENDING'}, note_prefix=NOTE_PREFIX)
    r.setup(T, a2mod, rules, a2post, reviews, timestamps, batch, label, manuscript, reader, traces)
    r.setup3a(a3mod, rules3, a3post, coverage, conf_review, agreement)
    r.setup3b(a4post, coverage, pcx_info, conf_review, agreement, pair_tables)
    states = OrderedDict([('CONF', 'FILLED'), ('A1', 'FILLED'), ('A2', 'FILLED'), ('A3', 'FILLED'), ('A4', 'FILLED'),
                          ('BASE25', 'FILLED' if base25 else 'PENDING_INPUT_ABSENT'),
                          ('POSITIVE_CONTROL', 'FILLED' if pc else 'PENDING_INPUT_ABSENT'),
                          ('PCX', 'FILLED' if pcx_info['pcx_used'] else 'PENDING_INPUT_ABSENT'),
                          ('REVIEW_NEWS', 'REPORTED' if reviews['news'].scored else 'PENDING'),
                          ('REVIEW_NRX', 'REPORTED' if reviews['nrx'].scored else 'PENDING'),
                          ('REVIEW_CONF', 'REPORTED' if conf_review.scored else 'PENDING'),
                          ('AGREEMENT', 'REPORTED' if agreement.scored else 'PENDING'),
                          ('A2BATCH', 'FILLED' if batch else 'PENDING_INPUT_ABSENT'),
                          ('A2LABEL', ('FILLED' if label.scored else 'RECORDED_NOT_RUN') if label else 'PENDING_INPUT_ABSENT')])
    base25_proof = F3.base25_host_proof(base25, reader, traces) if base25 else None
    generated = {GENERATED['primary']: r.primary_section(), GENERATED['secondary']: r.secondary_section(),
                 GENERATED['discussion']: r.discussion_section(), GENERATED['conclusion']: r.conclusion(),
                 GENERATED['supplement']: r.supplement_block3b(), GENERATED['execution']: r.execution_block3b()}
    if reviews['news'].scored:
        generated[GENERATED['news_review']] = r.news_review_table()
    if reviews['nrx'].scored:
        generated[GENERATED['nrx_review']] = r.nrx_review_table()
    if conf_review.scored:
        generated[GENERATED['conf_review']] = r.conf_table()
    if agreement.scored:
        generated[GENERATED['agreement']] = r.agreement_table()
    pdf, data_csv = r.forest()
    generated[GENERATED['forest_data']] = data_csv
    binary = {FIGURE: pdf}
    for source in SOURCES:
        binary[PUBLISHED[source]] = (scores.scored / (source + '__CLIPPING.csv')).read_bytes()
    edits = host_edits(r, reader, states)
    located = check_anchors(edits, texts)
    checked = prefill_equality(manuscript, reader, T, coverage, {rel for _, rel, _, _ in edits})
    if previous_inputs is not None:
        for key in ('seal_sha256', 'score_receipt_sha256', 'a2_postscore_sha256'):
            now = {'seal_sha256': scores.seal_sha256, 'score_receipt_sha256': scores.receipt_sha256, 'a2_postscore_sha256': a2post.sha256}[key]
            require(previous_inputs.get(key) == now, f'--refill requires identical CONF and A2 inputs ({key} changed)')
    r.inputs = {'a2_postscore': {'path': str(a2post.path), 'sha256': a2post.sha256, 'rerun': a2post.rerun_state},
                'a3_postscore': {'path': str(a3post.path), 'sha256': a3post.sha256, 'rerun': a3post.rerun_state},
                'a4_postscore': {'path': str(a4post.path), 'sha256': a4post.sha256, 'rerun': a4post.rerun_state},
                'coverage': {'path': str(coverage.path), 'sha256': coverage.sha256},
                'base25': None if base25 is None else {'path': str(base25.path), 'sha256': base25.sha256, 'host_proof': base25_proof},
                'positive_control': None if pc is None else {'path': str(pc.path), 'sha256': pc.sha256},
                'pcx': None if not pcx_info['pcx_used'] else {'path': str(args.pcx), 'sha256': sha256(args.pcx), 'freeze': str(pcx_info['pcx_freeze']),
                                                             'freeze_sha256': sha256(pcx_info['pcx_freeze'])},
                'reviews': {k: {'path': str(v.path), 'scored': v.scored, 'sha256': getattr(v, 'sha256', None)} for k, v in
                            {**reviews, 'conf': conf_review, 'agreement': agreement}.items()},
                'timestamps': {k: {'src': v['src'], 'freetsa': v['times']['freetsa'].isoformat(), 'digicert': v['times']['digicert'].isoformat()} for k, v in timestamps.labels.items()},
                'a2batch': None if batch is None else {'path': str(batch.path), 'sha256': batch.sha256},
                'a2label': None if label is None else {'path': str(label.path), 'sha256': label.sha256, 'state': label.data['state']},
                'components': states, 'slots': located, 'prefill_equal_files': checked, 'review_slots_before': slots,
                'published_files': {PUBLISHED[s]: sha256(scores.scored / (s + '__CLIPPING.csv')) for s in SOURCES}}
    return r, scores, a2post, a3post, a4post, generated, binary, edits, states, T


def write_outputs(manuscript, scores, r, a2post, a3post, a4post, resolved, binary, trace, words, edits, freeze, refill_of=None):
    snapshot = manuscript / SNAPSHOT_NAME
    require(not snapshot.exists(), f'{snapshot} exists: the manuscript was already filled (use --refill for a FILL3b fill)')
    for rel in list(GENERATED.values()) + [FIGURE] + list(PUBLISHED.values()):
        require(not (manuscript / rel).exists(), 'Generated file already exists: ' + rel)
    require(not (manuscript / TRACE_NAME).exists() and not (manuscript / RECEIPT_NAME).exists(), 'Existing CONF trace/receipt')
    hosts = sorted({rel for _, rel, _, _ in edits})
    snapshot.mkdir()
    manifest = {}
    for rel in hosts:
        dst = snapshot / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manuscript / rel, dst)
        manifest[rel] = sha256(dst)
    (snapshot / 'MANIFEST.json').write_text(json.dumps({'purpose': 'pre-fill copies of every host file edited by fill3b_conf_results.py', 'files_sha256': manifest}, indent=2) + '\n')
    outputs = {}
    for rel, text in resolved.items():
        path = manuscript / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        outputs[rel] = sha256(path)
    for rel, data in binary.items():
        path = manuscript / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        outputs[rel] = sha256(path)
    for source in SOURCES:
        require(outputs[PUBLISHED[source]] == sha256(scores.scored / (source + '__CLIPPING.csv')), 'Published clipping file differs from the frozen score output')
    with (manuscript / TRACE_NAME).open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['location', 'number', 'source_file', 'source_field', 'note'])
        w.writeheader()
        w.writerows(trace)
    slot_texts = [{'slot': sid, 'file': rel, 'old': old, 'new': r.R.peek(new) if '\x00' in new else new} for sid, rel, old, new in edits]
    receipt = {'state': 'CONF_RESULTS_FILLED', 'fill_step': 'FILL3b', 'utc': datetime.now(timezone.utc).isoformat(),
               'script_sha256': sha256(Path(__file__)), 'freeze_sha256': sha256(MS / FREEZE_NAME) if (MS / FREEZE_NAME).is_file() else None,
               'freeze': freeze, 'templates_sha256': sha256(MS / TEMPLATES_NAME), 'manuscript': str(manuscript),
               'scored_directory': str(scores.scored), 'score_receipt_sha256': scores.receipt_sha256, 'seal_sha256': scores.seal_sha256,
               'a2_postscore_sha256': a2post.sha256, 'a3_postscore_sha256': a3post.sha256, 'a4_postscore_sha256': a4post.sha256,
               'score_files_verified': len(scores.files), 'frozen_adapter_cross_checks': r.cross_checks, 'a1_cross_checks': r.a1_checks,
               'a2_sentence_checks': Counter(r.sentence_checks), 'a3_sentence_checks': r.a3_checks, 'a4_sentence_checks': r.a4_checks,
               'k4_rendering': 'PASS', 'inputs': r.inputs, 'abstract_words': words, 'abstract_level': r.abstract_level,
               'abstract_counts': r.abstract_counts, 'abstract_over_limit': r.abstract_over_limit,
               'trace_rows': len(trace), 'retired_host_tokens': r.retired, 'outputs_sha256': outputs, 'slot_texts': slot_texts,
               'generated_files': sorted([rel for rel in resolved if rel not in {e[1] for e in edits}] + list(binary)),
               'snapshot': SNAPSHOT_NAME + '/MANIFEST.json', 'refill_of': refill_of, 'stage_table_ref': STAGE_TABLE_REF}
    (manuscript / RECEIPT_NAME).write_text(json.dumps(receipt, indent=2, default=str) + '\n')
    return receipt


def snapshot_reader(manuscript):
    snapshot = manuscript / SNAPSHOT_NAME
    manifest = json.loads((snapshot / 'MANIFEST.json').read_text())['files_sha256']
    for rel, digest in manifest.items():
        require(sha256(snapshot / rel) == digest, 'Snapshot drift: ' + rel)

    def reader(rel):
        return (snapshot / rel).read_text() if rel in manifest else (manuscript / rel).read_text()
    return reader, manifest


def prepare_refill(manuscript):
    receipt_path = manuscript / RECEIPT_NAME
    require(receipt_path.is_file(), 'No fill receipt: run the normal command instead of --refill')
    receipt = json.loads(receipt_path.read_text())
    require(receipt.get('fill_step') == 'FILL3b', 'The manuscript was not filled by FILL3b; --refill refuses')
    for rel, digest in receipt['outputs_sha256'].items():
        require((manuscript / rel).is_file() and sha256(manuscript / rel) == digest, f'{rel} changed after the FILL3b fill; --refill refuses')
    reader, manifest = snapshot_reader(manuscript)
    return receipt, reader, manifest


def archive_previous_fill(manuscript, receipt, manifest):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = manuscript / RUNS_ARCHIVE / stamp
    require(not target.exists(), 'Archive folder exists: ' + str(target))
    target.mkdir(parents=True)
    hosts = set(manifest)
    for rel in receipt['outputs_sha256']:
        if rel in hosts:
            continue
        dst = target / 'generated' / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        (manuscript / rel).rename(dst)
    for rel in hosts:
        dst = target / 'filled_hosts' / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        (manuscript / rel).rename(dst)
    for name in (TRACE_NAME, RECEIPT_NAME):
        (manuscript / name).rename(target / name)
    (manuscript / SNAPSHOT_NAME).rename(target / SNAPSHOT_NAME)
    for rel in hosts:
        shutil.copy2(target / SNAPSHOT_NAME / rel, manuscript / rel)
        require(sha256(manuscript / rel) == manifest[rel], 'Restored host differs from the snapshot: ' + rel)
    return str(target)


def verify_freeze():
    path = MS / FREEZE_NAME
    require(path.is_file(), FREEZE_NAME + ' missing: FILL3b must be frozen before use')
    freeze = json.loads(path.read_text())
    require(freeze.get('state') == 'FILL3B_FROZEN_BEFORE_CONF_SCORES', 'Unexpected FILL3b freeze state')
    for rel, digest in freeze['files'].items():
        require(sha256(MS / rel) == digest, f'{rel} differs from its FILL3b freeze hash')
    for rel, digest in freeze.get('external_identities', {}).items():
        require(sha256(PROJ / rel) == digest, f'{rel} differs from the identity recorded in the FILL3b freeze')
    require(freeze['files'].get(Path(__file__).name) == sha256(Path(__file__)), 'fill3b_conf_results.py is not bound by FILL3B_FREEZE.json')
    return freeze


# ============================================================================= build (L7-aware)
VALIDATE_ASSERT = 'assert abstract_words<=250,abstract_words'


def build(manuscript, receipt):
    """Run the unchanged build script after refreshing supplement.aux; at L7 the abstract-length assertion is the only permitted failure."""
    env = {**os.environ, 'TECTONIC_CACHE_DIR': '/tmp/task_a_tectonic_cache'}
    subprocess.run(['/usr/bin/nice', '-n', '10', '/opt/homebrew/bin/tectonic', '-X', 'compile', str(manuscript / 'supplement.tex'), '--keep-logs', '--keep-intermediates'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, check=True)
    aux = (manuscript / 'supplement.aux').read_text(errors='replace')
    m = re.search(r'\\newlabel\{supp:tab:fill3b-stages\}\{\{([^}]*)\}', aux)
    stage_ref = m.group(1) if m else None
    proc = subprocess.run(['/usr/bin/nice', '-n', '10', '/bin/zsh', str(manuscript / 'build_MS12.sh')], capture_output=True, text=True)
    result = {'build_exit': proc.returncode, 'stage_table_number': stage_ref, 'stage_table_ok': stage_ref == STAGE_TABLE_REF}
    if proc.returncode != 0:
        tail = (proc.stdout + proc.stderr)[-3000:]
        result['build_tail'] = tail
        if receipt.get('abstract_over_limit') and 'abstract_words' in tail and 'AssertionError' in tail:
            src = (manuscript / 'validate_MS12.py').read_text()
            require(src.count(VALIDATE_ASSERT) == 1, 'validate_MS12.py abstract assertion not found')
            relaxed = src.replace(VALIDATE_ASSERT, 'pass  # L7: abstract-length assertion disabled for this one check (A4 AB5)')
            code = ('import sys; sys.path.insert(0, %r); src = %r\nexec(compile(src, "validate_MS12.py (L7, abstract-length assertion disabled)", "exec"), '
                    '{"__file__": %r, "__name__": "__main__"})' % (str(manuscript), relaxed, str(manuscript / 'validate_MS12.py')))
            p2 = subprocess.run(['/usr/bin/nice', '-n', '10', '/Users/stacchining/Documents/thesis/lamp-moe-research/.venv/bin/python', '-B', '-c', code],
                                cwd=str(manuscript), capture_output=True, text=True)
            result['l7_relaxed_validation_exit'] = p2.returncode
            result['l7_relaxed_validation_tail'] = (p2.stdout + p2.stderr)[-1500:]
            result['state'] = 'BUILT_L7_ABSTRACT_OVER_LIMIT_ONLY' if p2.returncode == 0 else 'BUILD_FAILED'
        else:
            result['state'] = 'BUILD_FAILED'
    else:
        result['state'] = 'BUILT'
    if result['state'].startswith('BUILT') and not result['stage_table_ok']:
        result['state'] = 'BUILT_STAGE_TABLE_NUMBER_MISMATCH'
    (manuscript / 'qa').mkdir(exist_ok=True)
    (manuscript / 'qa/FILL3B_BUILD_RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--state', type=Path, default=DEFAULT_STATE)
    parser.add_argument('--manuscript', type=Path, default=MS)
    parser.add_argument('--base25-root', type=Path, default=Q1 / 'BASE25')
    parser.add_argument('--positive-control', type=Path, default=DEFAULT_PC)
    parser.add_argument('--pcx', type=Path, default=DEFAULT_PCX)
    parser.add_argument('--pcx-freeze', type=Path, default=DEFAULT_PCX_FREEZE)
    parser.add_argument('--pcx-args', type=Path, default=DEFAULT_PCX_ARGS)
    parser.add_argument('--news-review-scores', type=Path, default=PROJ / 'reports/llm_text_quality_completion_20260928/news_validation_v4/SCORES.json')
    parser.add_argument('--nrx-review-scores', type=Path, default=LAMP / 'reports/llm_text_quality_completion_20260928/semantic_validation_nrx/human_review/SCORES.json')
    parser.add_argument('--conf-review-scores', type=Path, default=REVIEW_DIR / 'SCORES.json')
    parser.add_argument('--agreement', type=Path, default=REVIEW_DIR / 'SECOND_ANNOTATOR_AGREEMENT.json')
    parser.add_argument('--coverage', type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument('--timestamps', type=Path, default=DEFAULT_TS)
    parser.add_argument('--a2batch', type=Path, default=Q1 / 'A2BATCH/scores/A2BATCH_RESULT.json')
    parser.add_argument('--a2label', type=Path, default=Q1 / 'A2LABEL/scores/A2LABEL_RESULT.json')
    parser.add_argument('--test-keys-per-day', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--prefill', action='store_true', help='write the FILL3b PREFILL from the FILL3a snapshot and the frozen templates (pre-score)')
    parser.add_argument('--check-prefill', action='store_true', help='regenerate the PREFILL in memory and compare with the manuscript')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--refill', action='store_true')
    args = parser.parse_args(argv)
    manuscript = args.manuscript.resolve()
    if args.prefill or args.check_prefill:
        deps()
        coverage = Coverage(args.coverage)
        result = write_prefill(manuscript, coverage, check_only=args.check_prefill)
        print(json.dumps({k: result[k] for k in result if k != 'outputs_sha256'}, indent=2))
        return 0 if result['state'] in ('FILL3B_PREFILL_WRITTEN', 'PREFILL_EQUAL') else 3
    freeze = verify_freeze()
    reader, previous = None, None
    if args.refill:
        require(args.apply, '--refill requires --apply')
        old_receipt, reader, manifest = prepare_refill(manuscript)
        previous = {k: old_receipt.get(k) for k in ('seal_sha256', 'score_receipt_sha256', 'a2_postscore_sha256')}
    r, scores, a2post, a3post, a4post, generated, binary, edits, states, T = render(args, manuscript, reader, previous)
    rd = reader or (lambda rel: (manuscript / rel).read_text())
    resolved, trace, words = plan(manuscript, r, generated, edits, rd, binary, T)
    if r.abstract_over_limit:
        print('AUTHOR NOTICE: the abstract reached level L7 (A4 AB5): every qualifier is kept and it has ' + str(words) +
              ' validator words; validate_MS12 will fail only on its abstract-length assertion. Choose a journal or ask the editor.', file=sys.stderr)
    if not args.apply:
        preview = manuscript / PREVIEW_NAME
        require(not preview.exists(), f'{preview} exists; move it to the Trash before a new preview')
        for rel, text in resolved.items():
            (preview / rel).parent.mkdir(parents=True, exist_ok=True)
            (preview / rel).write_text(text)
        for rel, data in binary.items():
            (preview / rel).parent.mkdir(parents=True, exist_ok=True)
            (preview / rel).write_bytes(data)
        print(json.dumps({'state': 'PREVIEW_ONLY', 'preview': str(preview), 'trace_rows': len(trace), 'abstract_words': words,
                          'abstract_level': r.abstract_level, 'abstract_over_limit': r.abstract_over_limit, 'components': states}, indent=2))
        return 0
    refill = None
    if args.refill:
        refill = archive_previous_fill(manuscript, old_receipt, manifest)
    receipt = write_outputs(manuscript, scores, r, a2post, a3post, a4post, resolved, binary, trace, words, edits, freeze, refill)
    print(json.dumps({k: receipt[k] for k in ('state', 'fill_step', 'trace_rows', 'abstract_words', 'abstract_level', 'abstract_over_limit')}
                     | {'components': states, 'refill_archive': refill}, indent=2))
    if args.build:
        b = build(manuscript, receipt)
        print(json.dumps({k: v for k, v in b.items() if not k.endswith('tail')}, indent=2))
        if not b['state'].startswith('BUILT') or b['state'] == 'BUILT_STAGE_TABLE_NUMBER_MISMATCH':
            print('BUILD FAILED: see qa/FILL3B_BUILD_RESULT.json', file=sys.stderr)
            return 4
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except FillError as exc:
        print('FILL REFUSED: ' + str(exc), file=sys.stderr)
        sys.exit(2)
