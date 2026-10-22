
'Fill result tables using the specified primary and secondary comparisons.'
from __future__ import annotations

import argparse
from collections import Counter, OrderedDict
import csv
from datetime import date, datetime, timedelta, timezone
import difflib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

MS = Path(__file__).resolve().parent
PROJ = MS.parent
confirmation = PROJ / 'studies/confirmation'
A7DIR = confirmation / 'A7'
SENSITIVITY_COMPARISONS_FREEZE_SHA256 = '3f273245239ce46ac6c540dc14e3ffe589952077d1b47292bf8d28ffe398ab72'
SENSITIVITY_COMPARISONS_SNAPSHOT_FREEZE_SHA256 = '4a8f3b555e88dcce8e9d7a140329e35510ac3409ea35cbf0acb565060e09d410'
A7_FREEZE_SHA256 = '92d13ab4588f4a2ddd8c4d1da3367062a4b124e46889073473cee3035afb4f17'
A7_SPECIFICATION_1_FREEZE_SHA256 = 'e01df16b84e9d98a4027e312551ae2bbfb01bbae62fe6ec82007885982540fea'
FREEZE_NAME = 'SUMMARY_COMPARISONS_FREEZE.json'
SPEC_FREEZE_NAME = 'SUMMARY_COMPARISONS_SPEC_FREEZE.json'
TEMPLATES_NAME = 'summary_comparisons_templates.json'
TEMPLATES_REL = 'tables/' + TEMPLATES_NAME
A7_RULES_REL = 'studies/confirmation/A7/RULES_FOR_SUMMARY_COMPARISONS.json'
A6_RULES_REL = 'studies/confirmation/A6/RULES_FOR_SENSITIVITY_COMPARISONS.json'
NOTE_PREFIX = 'FILL3 confirmation fill (FILL3e)'
RUNS_ARCHIVE = 'previous_conf_summary_comparisons_runs'
PREVIEW_NAME = 'qa/SUMMARY_COMPARISONS_PREVIEW'
PREFILL_RECEIPT = 'qa/SUMMARY_COMPARISONS_PREFILL_RECEIPT.json'
BUILD_RESULT = 'qa/SUMMARY_COMPARISONS_BUILD_RESULT.json'
PREFILL_TRACE3E = 'SUMMARY_COMPARISONS_PREFILL_TRACE.csv'
PREFILL_NOTE3E = 'MS15 current locator; FILL3e prefill'
WORD_LIMIT = 250
SOURCES = ('news', 'notice')
DEFAULT_AUTHOR_CONFIRMATION = confirmation / 'AUTHOR_CONFIRMATION_A3_A6.json'
AUTHOR_CONFIRMATION = DEFAULT_AUTHOR_CONFIRMATION
MONTHS = ('', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December')
DATES_MARK = 'QQAUTHORDATESQQ'


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


def text_sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def join(items):
    items = list(items)
    if not items:
        return ''
    return items[0] if len(items) == 1 else ', '.join(items[:-1]) + ' and ' + items[-1]


def load_sensitivity_comparisons():

    path = MS / 'SENSITIVITY_COMPARISONS_FREEZE.json'
    require(sha256(path) == SENSITIVITY_COMPARISONS_FREEZE_SHA256, 'SENSITIVITY_COMPARISONS_FREEZE.json identity drift')
    freeze = json.loads(path.read_text())
    for group in ('files', 'test_receipts'):
        for rel, digest in (freeze.get(group) or {}).items():
            require(sha256(MS / rel) == digest, f'FILL3d frozen file drift: {rel}')
    for rel, digest in (freeze.get('external_identities') or {}).items():
        require(sha256(PROJ / rel) == digest, f'FILL3d external identity drift: {rel}')
    require(freeze['files'].get('sensitivity_comparisons_conf_results.py') == sha256(MS / 'sensitivity_comparisons_conf_results.py'), 'sensitivity_comparisons_conf_results.py is not bound by SENSITIVITY_COMPARISONS_FREEZE.json')
    name = 'sensitivity_comparisons_conf_results'
    if name in sys.modules:
        require(Path(sys.modules[name].__file__).resolve() == (MS / 'sensitivity_comparisons_conf_results.py').resolve(), 'Unexpected sensitivity_comparisons module')
        module = sys.modules[name]
    else:
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location(name, MS / 'sensitivity_comparisons_conf_results.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    module.FillError = FillError
    return module


def load_a7():

    path = A7DIR / 'ADDENDUM_A7_FREEZE.json'
    require(sha256(path) == A7_FREEZE_SHA256, 'ADDENDUM_A7_FREEZE.json identity drift')
    for rel, ident in json.loads(path.read_text())['files'].items():
        require(sha256(A7DIR / rel) == ident['sha256'], f'Frozen A7 file drift: {rel}')
    text = (A7DIR / 'RULES_FOR_SUMMARY_COMPARISONS.json').read_text()
    blocks = re.findall(r'```json\n(.*?)\n```', (A7DIR / 'ADDENDUM_A7.md').read_text(), re.S)
    require(len(blocks) == 1 and blocks[0] + '\n' == text, 'RULES_FOR_SUMMARY_COMPARISONS.json differs from the ADDENDUM_A7.md appendix block')
    rules = json.loads(text)
    apath = A7DIR / 'ADDENDUM_A7_SPECIFICATION_1_FREEZE.json'
    require(sha256(apath) == A7_SPECIFICATION_1_FREEZE_SHA256, 'ADDENDUM_A7_SPECIFICATION_1_FREEZE.json identity drift')
    afreeze = json.loads(apath.read_text())
    require(afreeze['binds'].get('studies/confirmation/A7/ADDENDUM_A7_FREEZE.json') == A7_FREEZE_SHA256, 'A7 specification 1 does not bind the A7 freeze')
    for rel, ident in afreeze['files'].items():
        require(sha256(A7DIR / rel) == ident['sha256'], f'Frozen A7 specification file drift: {rel}')
    ablocks = re.findall(r'```json\n(.*?)\n```', (A7DIR / 'ADDENDUM_A7_SPECIFICATION_1.md').read_text(), re.S)
    require(len(ablocks) == 1, 'A7 specification 1 must hold exactly one JSON block')
    amend = json.loads(ablocks[0])
    require(sorted(amend['templates']) == ['auth_slot_marker'] and sorted(amend['forms']) == ['A7AUTH'], 'A7 specification 1 amends other keys than A7 item 2 allows')
    rules['templates'] = dict(rules['templates'], **amend['templates'])
    rules['forms'] = dict(rules['forms'], **amend['forms'])
    rules['specification_1'] = {'freeze_sha256': A7_SPECIFICATION_1_FREEZE_SHA256, 'templates': sorted(amend['templates']), 'forms': sorted(amend['forms'])}
    return rules


F3D = None
F3B = None
A7RULES = None
F7 = None
W7 = None
TP7 = None
ORIG3D = {}


def deps():

    global F3D, F3B, A7RULES, F7, W7, TP7
    if F3D is None:
        F3D = load_sensitivity_comparisons()
        F3B = F3D.deps()
        A7RULES = load_a7()
        F7, W7, TP7 = A7RULES['forms'], A7RULES['words'], A7RULES['templates']
        table = dict(F3D.F6)
        for old, new in A7RULES['replaces_forms'].items():
            if old in table:
                table[old] = F7[new]
        require(table['A6DS3'] == F7['A7DS3'] and table['A6PS_NEG'] == F7['A7PS_NEG'] and table['A6PS_NEGB'] == F7['A7PS_NEGB'],
                'A7 forms not installed in the FILL3d form table')
        F3D.F6 = table
        for key in ('renderer_class', 'Timestamps', 'host_edits', 'prefill_equality'):
            ORIG3D[key] = getattr(F3B, key)
        F3B.TEMPLATES_NAME = TEMPLATES_NAME
        F3B.TEMPLATES_REL = TEMPLATES_REL
        F3B.FREEZE_NAME = FREEZE_NAME
        F3B.NOTE_PREFIX = NOTE_PREFIX
        F3B.RUNS_ARCHIVE = RUNS_ARCHIVE
        F3B.PREVIEW_NAME = PREVIEW_NAME
        F3B.PREFILL_RECEIPT = PREFILL_RECEIPT
        F3B.renderer_class = renderer_class3e
        F3B.Timestamps = Timestamps3e
        F3B.host_edits = host_edits3e
        F3B.prefill_equality = prefill_equality3e
        T3e = json.loads((MS / TEMPLATES_NAME).read_text())
        T3d = json.loads((MS / 'sensitivity_comparisons_templates.json').read_text())
        for block in ('prefill', 'presensitivity_comparisons'):
            require(json.dumps(T3e[block], sort_keys=True) == json.dumps(T3d[block], sort_keys=True),
                    f'summary_comparisons_templates.json {block} block differs from FILL3d\'s: stages 1-2 of the FILL3e PREFILL must equal the FILL3d PREFILL')
        for key, tkey in (('design.timestamps', 'design_timestamps'), ('supplement.timestamp_content.T5', 'timestamp_content_T5'),
                          ('a7.abstract_marker', 'abstract_marker'), ('a7.auth_slot_marker', 'auth_slot_marker'), ('a7.table6_mark_nc', 'table6_mark_nc'),
                          ('a7.s14_note', 's14_note')):
            node = T3e
            for part in key.split('.'):
                node = node[part]
            require(node == TP7[tkey], f'summary_comparisons_templates.json {key} differs from the A7 template {tkey}')
        require(all(b in T3e['banned_added'] for b in W7['K7_BANNED']), 'summary_comparisons_templates.json banned_added lacks an A7 K7 phrase')
        slot = next((s for s in T3e['slots'] if s['id'] == 'disclosure-confirmation'), None)
        require(slot is not None and slot['file'] == 'declarations.tex' and slot['anchor'] == TP7['auth_slot_marker'], 'disclosure-confirmation slot not declared as A7 item 2 (specification 1) requires')
    return F3B


def a4mod():
    return deps().A4MOD


def minus_problems(text, where):

    hits = re.findall(r'\$\[\$\s*-?\d|(?<!\$)\[\s*-\d|,\s*-\d[\d.]*\s*(?:\$\]\$|\])', text)
    return [f'K7.7 {where}: interval endpoint in text mode: {h.strip()!r}' for h in hits[:5]]


def banned_problems(text, where):
    deps()
    return [f'K7.5 {where}: inactive phrase "{b}"' for b in W7['K7_BANNED'] if b in text]


def llm_problems(plain_abstract):
    deps()
    return [] if any(n in plain_abstract for n in W7['LLM_NAMES']) else ['K7.6 the abstract does not name the language model (LLM or language-model)']


def wbai_problems(text, pair_lines, wbai_tex):

    p = []
    for pref in pair_lines:
        lines = [l for l in text.split('\n') if l.startswith(pref)]
        if not lines:
            p.append(f'K7.1 W_Bai row {pref[:40]!r} missing')
        for l in lines:
            cells = l.rstrip()[:-2].rstrip().split(' & ') if l.rstrip().endswith('\\\\') else []
            if len(cells) != 6 or cells[1:5] != ['--', '--', '--', '--'] or cells[5] != wbai_tex:
                p.append(f'K7.1 W_Bai row does not read the pre-score reason: {l[:120]!r}')
    return p


def nc_task(rt):

    return rt.get('scenario') != 'INCOMPLETE' and rt.get('pc') in ('SIZE_FAILS', 'BOTH_FAIL')


def table6_marks(robustness_tests, rs, source):

    deps()
    out = []
    for cell in F3D.table6_plain(robustness_tests, rs, source):
        has = cell['envelope'] != '--'
        out.append(dict(cell, nc=has and nc_task(rs['tasks'][source]), seven=has and cell['seven'], mc=has and cell['mc']))
    return out


def format_dates(isodates):

    ds = sorted({date.fromisoformat(x) for x in isodates})
    years = OrderedDict()
    for d in ds:
        years.setdefault(d.year, OrderedDict()).setdefault(d.month, []).append(d.day)
    return join(join(join(str(x) for x in days) + ' ' + MONTHS[m] for m, days in months.items()) + ' ' + str(y) for y, months in years.items())


def validate_author_confirmation(data):

    deps()
    require(isinstance(data, dict), 'K7.9 author confirmation file is not a JSON object')
    require(isinstance(data.get('recorded_by'), str) and data['recorded_by'].strip(), 'K7.9 author confirmation file lacks recorded_by')
    conf = data.get('confirmations')
    require(isinstance(conf, list) and conf, 'K7.9 author confirmation file lacks confirmations')
    addenda, dates = set(), []
    for i, c in enumerate(conf):
        require(isinstance(c, dict), f'K7.9 confirmation {i} is not an object')
        require(c.get('addendum') in W7['AUTH_ALLOWED'], f"K7.9 confirmation {i} names an unknown addendum {c.get('addendum')!r}")
        try:
            d = date.fromisoformat(str(c.get('date')))
        except ValueError:
            raise FillError(f"K7.9 confirmation {i} date {c.get('date')!r} is not YYYY-MM-DD")
        require(re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(c.get('date'))) is not None, f'K7.9 confirmation {i} date is not YYYY-MM-DD')
        ch = c.get('choices')
        require(isinstance(ch, list) and ch and all(isinstance(x, str) and x.strip() for x in ch), f'K7.9 confirmation {i} has no confirmed choices')
        addenda.add(c['addendum'])
        dates.append(d.isoformat())
    missing = [a for a in W7['AUTH_REQUIRED'] if a not in addenda]
    require(not missing, 'K7.9 author confirmation lacks ' + ', '.join(missing))
    return sorted(addenda), sorted(set(dates))


def author_confirmation(path, ts, listed):

    path = Path(path) if path is not None else None
    require(path is not None and path.is_file(), f'K7.9 author confirmation file missing: {path} (A7 item 2; written before T5 from the author\'s answers)')
    digest = sha256(path)
    try:
        data = json.loads(path.read_text())
    except ValueError:
        raise FillError('K7.9 author confirmation file is not valid JSON')
    addenda, dates = validate_author_confirmation(data)
    labels = sorted({name for p, items in listed.items() if p.endswith('AUTHOR_CONFIRMATION_A3_A6.json') for name, d in items if d == digest},
                    key=lambda n: int(re.match(r'T(\d+)', n).group(1)))
    require(labels, 'T5 (or later) manifest does not cover the current author confirmation file AUTHOR_CONFIRMATION_A3_A6.json (K7.9)')
    label = labels[0]
    t = ts.labels[label]['times']['freetsa']
    bound = (t + timedelta(hours=11)).date()
    require(all(date.fromisoformat(d) <= bound for d in dates), f'K7.9 an author confirmation is dated after the timestamp {label} that lists it')
    src = str(path.relative_to(PROJ)) if path.resolve().is_relative_to(PROJ.resolve()) else str(path.resolve())
    return {'path': str(path), 'src': src, 'sha256': digest, 'label': 'T' + re.match(r'T(\d+)', label).group(1), 'timestamp_utc': t.isoformat(),
            'addenda': addenda, 'dates': dates, 'confirmations': len(data['confirmations']), 'seventh': 'A7' in addenda}


def freeze_identities3e():

    deps()
    require(sha256(A7DIR / 'ADDENDUM_A7_FREEZE.json') == A7_FREEZE_SHA256, 'ADDENDUM_A7_FREEZE.json identity drift')
    a7 = json.loads((A7DIR / 'ADDENDUM_A7_FREEZE.json').read_text())['files']
    hx = F3B.hexcode
    return ('Identity N (seventh addendum) is SHA-256 ' + hx(a7['ADDENDUM_A7.md']['sha256']) + ', identity O (its rule sheet) ' +
            hx(a7['RULES_FOR_SUMMARY_COMPARISONS.json']['sha256']) + ', freeze record ' + hx(A7_FREEZE_SHA256) + '. These are rule identities, not result hashes.')


def snapshot3e(manuscript, P):
    snap = manuscript / P['snapshot']
    manifest = json.loads((manuscript / P['snapshot_manifest']).read_text())
    index = {e['path']: e['sha256'] for e in manifest['entries']}
    require(manifest.get('sensitivity_comparisons_freeze_sha256') == SENSITIVITY_COMPARISONS_SNAPSHOT_FREEZE_SHA256, 'previous_sensitivity_comparisons manifest does not bind the FILL3d freeze')

    def read(rel):
        require(rel in index, f'{rel} is not in the previous_sensitivity_comparisons snapshot manifest')
        require(sha256(snap / rel) == index[rel], f'previous_sensitivity_comparisons snapshot drift: {rel}')
        return (snap / rel).read_text()
    return snap, index, read


def stage3_texts(manuscript, T, base):

    deps()
    P = T['presummary_comparisons']
    snap, index, read_snap = snapshot3e(manuscript, P)
    for rel, digest in P['hash_checks'].items():
        require(sha256(PROJ / rel) == digest, f'Stage-3 text cites a file whose identity changed: {rel}')
    out = {}

    def cur(rel):
        if rel in out:
            return out[rel]
        return base[rel] if rel in base else read_snap(rel)
    subs = {'<<IDENT_A7>>': freeze_identities3e()}
    for e in P['edits']:
        text = cur(e['file'])
        require(text.count(e['old']) == 1, f"Stage-3 prefill anchor {e['id']} must occur exactly once in {e['file']}")
        rep = e['new']
        for k, v in subs.items():
            rep = rep.replace(k, v)
        require('<<' not in rep, f"Unresolved placeholder in stage-3 edit {e['id']}")
        out[e['file']] = text.replace(e['old'], rep)
    for rel, spec in P['new_files'].items():
        require(rel not in index and rel not in base and not (snap / rel).exists(), f'Stage-3 new file already exists: {rel}')
        src = PROJ / spec['from']
        require(sha256(src) == spec['sha256'], f'Frozen addendum text drift: {spec["from"]}')
        out[rel] = F3D.md_to_tex(src.read_text(), spec['heading'], spec['label'])
    return out


def stage3_trace(manuscript, T, base, s3):

    F3A_ = F3B.F3A
    P = T['presummary_comparisons']
    snap, index, read_snap = snapshot3e(manuscript, P)
    prior = F3A_.prior_trace_rows(snap)
    supplied = {}
    for s in P['trace_supplied']:
        for n in s['numbers']:
            supplied[(s['file'], n)] = (s['source_file'], s['source_field'])
    file_sources = P['trace_sources']
    rows, unresolved = [], []

    def carry(old_loc, token, new_loc, note):
        r = prior.get((old_loc, token))
        if r is None:
            return {'location': new_loc, 'number': token, 'source_file': 'tables/' + P['snapshot'] + '/' + old_loc.rsplit(':', 1)[0],
                    'source_field': f"line {old_loc.rsplit(':', 1)[1]}; preserved literal {token}", 'note': PREFILL_NOTE3E + '; ' + note}
        return {'location': new_loc, 'number': token, 'source_file': r['source_file'], 'source_field': r['source_field'],
                'note': PREFILL_NOTE3E + '; ' + note + '; original note: ' + r['note'][:160]}

    for rel, text in sorted(s3.items()):
        if not rel.endswith('.tex'):
            continue
        if rel in base:
            old_lines = base[rel].split('\n')
        elif rel in index:
            old_lines = read_snap(rel).split('\n')
        else:
            old_lines = []
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
                old_toks = F3A_.trace_tokens(old_lines[i]) if i is not None else []
                for tok in F3A_.trace_tokens(line):
                    if (rel, tok) in supplied:
                        src, f = supplied[(rel, tok)]
                        rows.append({'location': new_loc, 'number': tok, 'source_file': src, 'source_field': f, 'note': PREFILL_NOTE3E + '; frozen rule or fact value'})
                    elif tok in old_toks:
                        rows.append(carry(f'{rel}:{i + 1}', tok, new_loc, 'value unchanged on an edited line'))
                    elif rel in file_sources:
                        src, f = file_sources[rel]
                        rows.append({'location': new_loc, 'number': tok, 'source_file': src, 'source_field': f, 'note': PREFILL_NOTE3E + '; fixed text value'})
                    else:
                        unresolved.append(f'{rel}:{j + 1} {tok}')
    require(not unresolved, 'Stage-3 prefill numbers without a trace origin: ' + '; '.join(unresolved[:20]))
    for r in rows:
        for source in r['source_file'].split(';'):
            source = source.strip()
            if source:
                require((Path(source) if Path(source).is_absolute() else PROJ / source).exists(), 'Stage-3 prefill trace source missing: ' + source)
    unique, seen = [], set()
    for r in rows:
        key = tuple(r[k] for k in ('location', 'number', 'source_file', 'source_field', 'note'))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def presummary_comparisons_outputs(manuscript, T, coverage):

    deps()
    out3d, _, _, _ = F3D.presensitivity_comparisons_outputs(manuscript, T, coverage)
    base = {rel: text for rel, text in out3d.items() if not rel.endswith('.csv')}
    s3 = stage3_texts(manuscript, T, base)
    rows = stage3_trace(manuscript, T, base, s3)
    header = ['location', 'number', 'source_file', 'source_field', 'note']
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header, lineterminator='\r\n')
    w.writeheader()
    w.writerows(rows)
    out = dict(out3d)
    out.update(s3)
    out[PREFILL_TRACE3E] = buf.getvalue()
    out['MS15_TRACE.csv'] = out3d['MS15_TRACE.csv'] + ''.join(buf.getvalue().splitlines(keepends=True)[1:])
    return out, out3d, s3, rows


def write_presummary_comparisons(manuscript, coverage, check_only=False):
    F3B_ = deps()
    T = F3B_.templates()
    outputs, out3d, s3, rows = presummary_comparisons_outputs(manuscript, T, coverage)
    if check_only:
        diffs = [rel for rel, text in outputs.items() if not (manuscript / rel).is_file() or (manuscript / rel).read_bytes() != text.encode()]
        return {'state': 'PREFILL_EQUAL' if not diffs else 'PREFILL_DIFFERS', 'differs': diffs, 'trace_rows': len(rows), 'stage3_files': sorted(s3)}
    problems, reachable = F3B_.prefill_scan(manuscript, outputs, T)
    require(not problems, 'Prefill text check failed: ' + '; '.join(problems[:12]))
    for rel in reachable:
        text = outputs[rel] if rel in outputs else (manuscript / rel).read_text()
        problems += banned_problems(F3B_.plain_text(text), rel)
    require(not problems, 'K7.5 prefill text check failed: ' + '; '.join(problems[:12]))
    known = {}
    for name, key in ((T['presummary_comparisons']['snapshot_manifest'], 'entries'), (T['presensitivity_comparisons']['snapshot_manifest'], 'entries'), (T['prefill.snapshot_manifest'], 'entries')):
        for e in json.loads((manuscript / name).read_text())[key]:
            known.setdefault(e['path'], set()).add(e['sha256'])
    for name in ('qa/MAIN_COMPARISONS_PREFILL_RECEIPT.json', 'qa/FILL3C_PREFILL_RECEIPT.json', 'qa/SENSITIVITY_COMPARISONS_PREFILL_RECEIPT.json', PREFILL_RECEIPT):
        if (manuscript / name).is_file():
            for rel, digest in json.loads((manuscript / name).read_text()).get('outputs_sha256', {}).items():
                known.setdefault(rel, set()).add(digest)
    for rel, text in outputs.items():
        path = manuscript / rel
        if path.exists():
            require(sha256(path) in {text_sha(text)} | known.get(rel, set()),
                    f'{rel} differs from its previous_sensitivity_comparisons snapshot, from the last FILL3b/FILL3c/FILL3d/FILL3e PREFILL and from this PREFILL; the prefill refuses to overwrite it')
    written = {}
    for rel, text in outputs.items():
        path = manuscript / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
        written[rel] = sha256(path)
    P = T['presummary_comparisons']
    receipt = {'state': 'SUMMARY_COMPARISONS_PREFILL_WRITTEN', 'utc': datetime.now(timezone.utc).isoformat(), 'script_sha256': sha256(Path(__file__)),
               'sensitivity_comparisons_generator_sha256': sha256(MS / 'sensitivity_comparisons_conf_results.py'), 'templates_sha256': sha256(MS / TEMPLATES_NAME),
               'a7_freeze_sha256': A7_FREEZE_SHA256, 'coverage': {'path': str(coverage.path), 'sha256': coverage.sha256},
               'title_variant': T['presensitivity_comparisons.title.active'], 'stage12_files': sorted(rel for rel in out3d if not rel.endswith('.csv')),
               'stage3_edits': [e['id'] for e in P['edits']], 'stage3_new_files': sorted(P['new_files']), 'stage3_files': sorted(s3),
               'stage3_trace_rows': len(rows), 'reachable_sources_scanned': len(reachable), 'outputs_sha256': written,
               'note': "stage 1 is the FILL3b PREFILL and stage 2 the FILL3d PREFILL (generators reused read-only, identical prefill blocks); stage 3 is confirmation-A7 section X'"}
    (manuscript / PREFILL_RECEIPT).parent.mkdir(parents=True, exist_ok=True)
    (manuscript / PREFILL_RECEIPT).write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


class Timestamps3e:


    def __new__(cls, root, receipt_path, coverage, freeze_name, pcx_freeze=None):
        ts = ORIG3D['Timestamps'](root, receipt_path, coverage, freeze_name, pcx_freeze)
        listed = {}
        for name, entry in ts.labels.items():
            if int(re.match(r'T(\d+)', name).group(1)) < 5:
                continue
            for line in entry['manifest'].read_text().splitlines():
                if line.startswith('#') or not line.strip():
                    continue
                digest, _, path = line.split(None, 2)
                listed.setdefault(path.strip(), []).append((name, digest))
        for name in ('ADDENDUM_A7_FREEZE.json', 'ADDENDUM_A7_SPECIFICATION_1_FREEZE.json'):
            digest = sha256(A7DIR / name)
            require(any(p.endswith('/' + name) and d == digest for p, items in listed.items() for _, d in items),
                    f'T5 (or later) manifest does not cover the current {name}')
        ts.author_confirmation = author_confirmation(AUTHOR_CONFIRMATION, ts, listed)
        return ts


def slot_edit(r, reader, sid, new):

    s = F3B.slot_index(r.T3)[sid]
    rel, old = s['file'], s['anchor']
    text = reader(rel)
    F2 = F3B.F2MOD
    if old in text and '\x00' in new:
        i = text.index(old)
        start, end = text.rfind('\n', 0, i) + 1, text.find('\n', i + len(old))
        end = len(text) if end < 0 else end
        pre, post = text[start:i], text[i + len(old):end]
        if F2.tokens(pre) or F2.tokens(post):
            line = text[:i].count('\n') + 1
            carry = lambda seg: F2.NUMRE.sub(lambda m: r.carry(rel, line, m.group(0).rstrip(',')) + (',' if m.group(0).endswith(',') else ''), seg)
            old, new = pre + old + post, carry(pre) + new + carry(post)
    return (sid, rel, old, new)


def host_edits3e(r, reader, states):

    out = []
    for sid, rel, old, new in ORIG3D['host_edits'](r, reader, states):
        if sid == 'abstract-marker':
            new = r.T3['a7.abstract_marker']
        elif new.lstrip().startswith('%') and '\n' not in new.strip():
            new = new.replace('sensitivity_comparisons_conf_results.py', 'summary_comparisons_conf_results.py')
        out.append((sid, rel, old, new))
    out.append(slot_edit(r, reader, 'disclosure-confirmation', r.author_confirmation_tex()))
    return out


def prefill_equality3e(manuscript, reader, T, coverage, slot_files):

    outputs, _, _, _ = presummary_comparisons_outputs(manuscript, T, coverage)
    snap, index, read_snap = snapshot3e(manuscript, T['presummary_comparisons'])
    checked = []
    for rel in sorted(set(slot_files) | {r for r in outputs if r.endswith('.tex')}):
        expected = outputs[rel] if rel in outputs else (read_snap(rel) if rel in index else None)
        require(expected is not None, f'No prefill or snapshot text for {rel}')
        live = reader(rel) if rel in slot_files else (manuscript / rel).read_text()
        require(live == expected, f'PREFILL_DRIFT: {rel} differs from the FILL3e prefill generated from the frozen templates')
        checked.append(rel)
    return checked


def set_intervals(text):

    return re.subn(r'\$\[\$(\x00\d+\x01), (\x00\d+\x01)\$\]\$', '[$\\1$, $\\2$]', text)


def renderer_class3e(F3A_, F3, F2, robustness_tests):
    Base = ORIG3D['renderer_class'](F3A_, F3, F2, robustness_tests)
    IMP, DET, NULL = robustness_tests.IMP, robustness_tests.DET, robustness_tests.NULL
    PW = F3B.PW
    WD, TP = F3D.WD, F3D.TP

    class Fill3e(Base):
        def setup3b(self, a4post, coverage, pcx_info, conf_review, agreement, pair_tables):
            Base.setup3b(self, a4post, coverage, pcx_info, conf_review, agreement, pair_tables)
            self.a7_checks = Counter()
            self.k7_expect = {}

        def fixed7(self, text, key, symbols=False):

            parts = F3A_.a3_latex_parts(text, symbols)
            tex = ''.join(self.R(p[1], A7_RULES_REL, key, 'fixed numeral of the frozen A7 form') if p[0] == 'num' else
                          self.R(p[1], F3.DESIGN_REL, 'arm identifier', 'arm name; digits are part of the identifier') if (p[0] == 'arm' and F2.tokens(p[1])) else p[1]
                          for p in parts)
            require(F3A_.flat(self.R.peek(tex)) == F3A_.flat(text), f'A7 fixed text {key} conversion differs')
            self.a7_checks['A7 fixed texts'] += 1
            return tex


        def a3fixed(self, text, key, symbols=True):
            if key == 'A3C8':
                require(text == self.sensitivity_tests.SENTENCES['A3C8'], 'A3C8 differs from the frozen sensitivity_tests sentence')
                self.a7_checks['A7C8 in place of A3C8'] += 1
                return self.fixed7(F7['A7C8'], 'forms.A7C8', symbols=symbols)
            return Base.a3fixed(self, text, key, symbols)


        def plain_state(self, state):
            if state == 'BAI_UNAVAILABLE_TRAINING_PRICE_PREREQUISITE':
                text = F2.esc(F7['A7WBAI_STAGE'])
                self.a7_checks['A7WBAI_STAGE'] += 1
                return self.R(text, A7_RULES_REL, 'forms.A7WBAI_STAGE', 'fixed A7 form (replaces the primary_tests code phrase)') if F2.tokens(text) else text
            return Base.plain_state(self, state)


        def abstract3b(self):
            tex = Base.abstract3b(self)
            problems = llm_problems(self.abstract_plain)
            require(not problems, '; '.join(problems))
            self.k7_abstract = 'K7.6 PASS'
            return tex


        def primary_table3b(self):
            rows, marks = [], {'seven': False, 'mc': False, 'nc': False}
            self.k7_expect['nc_cells'] = 0
            for source in SOURCES:
                d = self.task_decimals(source)
                cells6 = table6_marks(robustness_tests, self.rs6, source)
                for i, (c, r) in enumerate(zip(self.primary[source], self.a2[source]['primary'])):
                    base = f'tasks.{source}.primary[{i}]'
                    eff = self.num(self.primary_tests.fmt_effect(r.get('effect_percent_reference_mae'), d), base + '.effect_percent_reference_mae', f'{d} decimals (task column rule)')
                    cell = cells6[i] if i < len(cells6) else None
                    require(cell is None or (cell['arm'], cell['reference']) == (c.arm, c.ref), 'K6.6 Table 6 row order differs from RS6')
                    env_cell, reading, checks, dissent = '--', 'not evaluable', 'not evaluable', '--'
                    if cell is not None:
                        if cell['envelope'] != '--':
                            env_cell = self.R(cell['envelope'], self.a4post.src, f'{base} envelope U (robustness_tests specification 2 G3)', 'U = max(0, -l1, -l7) of the family-adjusted one-day and seven-day intervals; primary_tests branch_safe_bound')
                            if cell['seven']:
                                env_cell += '$^{a}$'
                                marks['seven'] = True
                            if cell['mc']:
                                env_cell += '$^{b}$'
                                marks['mc'] = True
                            if cell['nc']:
                                env_cell += '$^{c}$'
                                marks['nc'] = True
                                self.k7_expect['nc_cells'] += 1
                                self.a7_checks['Table 6 mark c'] += 1
                        reading = F2.esc(cell['reading'])
                        checks = F2.esc(cell['checks'])
                        dissent = self.esc6(cell['dissent'], 'words.SENS_TABLE6/TABLE_CLASS_C') if cell['dissent'] != '--' else '--'
                        self.a6_checks['Table 6 rows from RS6'] += 1
                    rows.append(' & '.join([self.pair(c.arm, c.ref), self.aud(c), eff,
                                            self.cell_interval(r.get('interval_family_one_day'), d, base + '.interval_family_one_day'),
                                            env_cell, self.cell_p(r.get('holm_p'), base + '.holm_p'), reading, checks, dissent]) + r' \\')
                if source == 'news':
                    rows.append(r'\midrule')
            mark_text = (TP['table6_mark_seven'] if marks['seven'] else '') + (TP['table6_mark_mc'] if marks['mc'] else '')
            mark_tex = self.R(mark_text, A6_RULES_REL, 'templates.table6_mark_*', 'fixed A6 template text') if F2.tokens(mark_text) else mark_text
            if marks['nc']:
                nc_text = TP7['table6_mark_nc']
                mark_tex += self.R(nc_text, A7_RULES_REL, 'templates.table6_mark_nc', 'fixed A7 template text') if F2.tokens(nc_text) else nc_text
            self.k7_expect['nc_caption'] = marks['nc']
            cap = self.a6t('table6_caption', marks=mark_tex, table_ref='\\ref{tab:main_comparisons-sensitivity}')
            spec = '@{}' + PW('.107') + F3B.PR('.112') + F3B.PR('.075') + PW('.082') + F3B.PR('.077') + F3B.PR('.07') + PW('.085') + PW('.11') + PW('.125') + '@{}'
            head = self.a6t('table6_header')
            return ('\\begin{table}[htbp]\\centering\\scriptsize\\setlength{\\tabcolsep}{' + self.layout('2pt') + '}\n\\caption{' + cap + '}\\label{tab:main_comparisons-primary}\n'
                    '\\begin{tabular}{' + spec + '}\\toprule\n' + head + '\n\\midrule\n' + '\n'.join(rows) + '\n\\bottomrule\\end{tabular}\\end{table}\n')


        def a2_notice_rows(self, extra, d):
            out = []
            for key, rep in extra:
                a, b = key.split('-')
                base = f'tasks.notice.a2_new_secondary_contrasts.{key}'
                pair = self.pair(a, b) + '$^{\\ddagger}$'
                if not isinstance(rep, dict) or rep.get('state') != 'COMPUTED':
                    out.append(' & '.join([pair, '--', '--', '--', '--', self.plain_state((rep or {}).get('state', 'NOT_RECORDED'))]) + r' \\')
                    self.a7_checks['second-addendum notice rows (not computed)'] += 1
                    continue
                one = ((rep.get('bootstrap') or {}).get('1') or {}).get('interval95_percent')
                days = self.R(str(rep['n_days']), self.a2post.src, base + '.n_days', 'days') if rep.get('n_days') is not None else '--'
                eff = self.num(self.primary_tests.fmt_effect(rep.get('effect_percent_reference_mae'), d), base + '.effect_percent_reference_mae', f'{d} decimals (table column rule)')
                iv = self.cell_interval(one, d, base + '.bootstrap.1.interval95_percent')
                p = self.cell_p(rep.get('p_two_sided'), base + '.p_two_sided')
                cls = self.primary_tests.decision_class(rep.get('mean_difference'), rep.get('p_two_sided'))
                word = WD['CS_TABLE'][F3D.cmap(robustness_tests, cls)] if cls in (IMP, NULL, DET) else robustness_tests.CS_WORDS.get(cls, 'not evaluable')
                out.append(' & '.join([pair, days, eff, iv, p, F2.esc(word)]) + r' \\')
                self.a7_checks['second-addendum notice rows'] += 1
            return out

        def all_secondary_table3b(self, source):

            rows, marked = [], False
            items = list(self.secondary[source].items())
            extra = list((self.a2['notice'].get('a2_new_secondary_contrasts') or {}).items()) if source == 'notice' else []
            ds = [self.decimals(c.i1) for _, c in items if not isinstance(c, dict) and c.i1]
            ds += [self.decimals(((rep.get('bootstrap') or {}).get('1') or {}).get('interval95_percent')) for _, rep in extra
                   if isinstance(rep, dict) and rep.get('state') == 'COMPUTED' and ((rep.get('bootstrap') or {}).get('1') or {}).get('interval95_percent')]
            d = max(ds) if ds else 2
            after = tuple(W7['A2_SLOTS_AFTER'])
            placed = False
            wbai_prefixes = []
            for key, c in items:
                mark = self.dagger(c)
                marked = marked or bool(mark)
                if W7['WBAI_ARM'] in key:
                    require(isinstance(c, dict), f'K7.1 W_Bai slot {key[0]}-{key[1]} is computed although the frozen word screen selected no word before scoring')
                    rows.append(' & '.join([self.pair(*key) + mark, '--', '--', '--', '--', self.esc6(F3D.F6['A6WBAI'], 'forms.A6WBAI')]) + r' \\')
                    wbai_prefixes.append(self.pair(*key) + mark)
                    self.a7_checks['W_Bai rows'] += 1
                elif 'P_content' in key:
                    require(isinstance(c, dict), f'Evaluable P_content slot {key} rendered (impossible state, robustness_tests K4.1)')
                    rows.append(' & '.join([self.pair(*key) + mark] + self.pcontent_cells(source, 5)) + r' \\')
                elif isinstance(c, dict):
                    rows.append(' & '.join([self.pair(*key) + mark, '--', '--', '--', '--', self.plain_state(c.get('state'))]) + r' \\')
                else:
                    src = F2.trace_path(self.s.scored / c.file)
                    days = self.count(c.slot['days'], self.s.src('SCORE_REPORT.json'), f'{source}.secondary[{key[0]}-{key[1]}].days')
                    eff = self.num(self.primary_tests.fmt_effect(c.effect, d), 'reports[0].bootstrap.1.effect_percent_reference_mae', f'{d} decimals (table column rule)', src) if F3B.finite(c.effect) else 'undefined'
                    iv = self.cell_interval(c.i1, d, 'reports[0].bootstrap.1.interval95_percent', src)
                    p = self.cell_p(c.dm.get('p_two_sided'), 'reports[0].dm_p1.p_two_sided', src)
                    cls = self.primary_tests.decision_class(c.mean, c.dm.get('p_two_sided'))
                    word = WD['CS_TABLE'][F3D.cmap(robustness_tests, cls)] if cls in (IMP, NULL, DET) else robustness_tests.CS_WORDS.get(cls, 'not evaluable')
                    rows.append(' & '.join([self.pair(*key) + mark, days, eff, iv, p, F2.esc(word)]) + r' \\')
                if source == 'notice' and tuple(key) == after and extra:
                    rows += self.a2_notice_rows(extra, d)
                    placed = True
            require(not extra or placed, 'K7.4 the L_chen_notice-P_content slot is missing: the second addendum\'s notice rows have no frozen place')
            self.k7_expect.setdefault('wbai_prefixes', {})[source] = wbai_prefixes
            if source == 'notice':
                self.k7_expect['a2_rows'] = [k for k, _ in extra]
            note = ' $^{\\dagger}$Evaluated on the target days with shifted-source support only.' if marked else ''
            caption = self.fx3b(('News' if source == 'news' else 'Notice') + ' secondary contrasts (frozen slots, main seed): days, effect in percent of the second-named arm with its per-contrast one-day 95\\% interval, raw DM $p$ and the result word of a single secondary contrast (seven-day intervals are in the score files). Unadjusted; no secondary contrast can change a primary reading; reassignment rows are not evaluable.' + note,
                                f'supp:tab:main_comparisons-secondary-{source} caption')
            if extra:
                caption += TP7['s14_note']
            return self.table3b(f'supp:tab:main_comparisons-secondary-{source}', caption, r'Contrast & Days & Effect (\%) & One-day 95\% & DM $p$ & Result \\', rows,
                                PW('.20') + 'rr' + PW('.22') + 'r' + PW('.28'))


        def supp_primary_tables3b(self):
            text, n = set_intervals(Base.supp_primary_tables3b(self))
            self.a7_checks['math-mode interval endpoints (seeds table)'] += n
            self.k7_expect['seeds_tables'] = text
            return text

        def pg_rows(self):
            rows = Base.pg_rows(self)
            for key in rows:
                rows[key], n = set_intervals(rows[key])
                self.a7_checks['math-mode interval endpoints (published-gains rows)'] += n
            return rows


        def author_confirmation_tex(self):
            ac = getattr(self.ts, 'author_confirmation', None)
            require(ac is not None, 'K7.9 the author confirmation was not verified by the timestamp gate')
            dates = format_dates(ac['dates'])
            seventh = F7['A7AUTH_SEVENTH'] if ac['seventh'] else F7['A7AUTH_NO7']
            plain = F7['A7AUTH'].format(dates=DATES_MARK, label=ac['label'], seventh=seventh)
            require(not F2.tokens(plain.replace(DATES_MARK, '')), 'A7AUTH carries an untraced numeral')
            dates_tex = self.R(dates, ac['src'], 'confirmations[*].date', f"author confirmation dates (A7 item 2), listed in pre-score timestamp {ac['label']}")
            self.author_confirmation_plain = plain.replace(DATES_MARK, dates)
            self.a7_checks['author-confirmation slot'] += 1
            return F2.esc(plain).replace(F2.esc(DATES_MARK), dates_tex)

    return Fill3e


def k7_text_check(r, resolved, edits):
    F3B_ = deps()
    F2 = F3B_.F2MOD
    problems = []
    G = F3B_.GENERATED
    supp = resolved[G['supplement']]
    primary = resolved[G['primary']]
    execution = resolved[G['execution']]

    wbai_tex = F2.esc(F3D.F6['A6WBAI'])
    for source in SOURCES:
        prefixes = [r.R.peek(p) for p in (r.k7_expect.get('wbai_prefixes') or {}).get(source, [])]
        problems += wbai_problems(supp, prefixes, wbai_tex)
    if 'could not be built (its training-price check' in execution:
        problems.append('K7.1 the primary_tests Bai code phrase is rendered in the stage table')
    if r.a7_checks.get('A7WBAI_STAGE') and F2.esc(F7['A7WBAI_STAGE']) not in execution:
        problems.append('K7.1 A7WBAI_STAGE missing from the stage table')

    caption_has = TP7['table6_mark_nc'] in primary
    got = primary.count('$^{c}$') - (1 if caption_has else 0)
    if got != r.k7_expect.get('nc_cells', 0):
        problems.append(f"K7.2 Table 6 carries {got} marks c (expected {r.k7_expect.get('nc_cells', 0)})")
    if caption_has != bool(r.k7_expect.get('nc_caption')) or caption_has != (got > 0):
        problems.append('K7.2 Table 6 caption mark c does not match the cells')

    for row in getattr(r, 'figure_rows', []):
        if row['group'] == 'Primary':
            label, where, text = r.R.peek(r.pair(row['arm'], row['ref'])), 'Table 6', primary
        elif row['group'] == 'Combination':
            label, where, text = r.R.peek(r.combo_tex(row['arm'], row['ref'])), 'Table S7.11', supp
        else:
            label, where, text = r.R.peek(r.pair(row['arm'], row['ref'])), 'the supplement tables', supp
        if label not in text:
            problems.append(f"K7.3 Figure 2 row {row['arm']}-{row['ref']} has no row in {where}")
    a2 = r.k7_expect.get('a2_rows') or []
    if a2:
        lines = supp.split('\n')
        anchor = r.R.peek(r.pair(*W7['A2_SLOTS_AFTER']))
        pos = [i for i, l in enumerate(lines) if l.startswith(anchor)]
        rows = [i for key in a2 for i, l in enumerate(lines) if l.startswith(r.R.peek(r.pair(*key.split('-'))) + '$^{\\ddagger}$')]
        if len(pos) != 1 or len(rows) != len(a2) or rows != list(range(pos[0] + 1, pos[0] + 1 + len(a2))):
            problems.append('K7.4 the second addendum\'s notice rows are not directly after the L_chen_notice-P_content row')
        if TP7['s14_note'] not in supp:
            problems.append('K7.4 caption note of the second addendum\'s rows missing')

    texts = {rel: text for rel, text in resolved.items() if rel.endswith('.tex') and rel in G.values()}
    for sid, rel, old, new in edits:
        texts[f'{rel} (slot {sid})'] = r.R.peek(new) if '\x00' in new else new
    for name, text in texts.items():
        problems += banned_problems(F3B_.plain_text(text), name)
    problems += minus_problems(r.R.peek(r.k7_expect.get('seeds_tables', '')), 'supplement primary and seeds tables')
    pg = [r.R.peek(new) for sid, rel, old, new in edits if sid.startswith('pg-row-')]
    for k, text in enumerate(pg):
        problems += minus_problems(text, f'published-gains row {k}')

    n = sum(1 for sid, _, _, _ in edits if sid == 'disclosure-confirmation')
    if n != 1:
        problems.append(f'K7.9 {n} author-confirmation slot edits')
    decl = resolved.get('declarations.tex')
    if decl is not None and TP7['auth_slot_marker'] in decl:
        problems.append('K7.9 the author-confirmation slot marker is still in the declaration')
    require(not problems, 'A7 K7 rendering assertions failed: ' + '; '.join(problems[:12]))
    return {'state': 'K7.1-K7.9 PASS', 'texts_checked': len(texts), 'nc_cells': r.k7_expect.get('nc_cells', 0),
            'second_addendum_rows': len(a2), 'figure_rows_checked': len(getattr(r, 'figure_rows', []))}


def write_outputs(manuscript, scores, r, a2post, a3post, a4post, resolved, binary, trace, words, edits, freeze, refill_of=None):
    F3B_ = deps()
    snapshot = manuscript / F3B_.SNAPSHOT_NAME
    require(not snapshot.exists(), f'{snapshot} exists: the manuscript was already filled (use --refill for a FILL3e fill)')
    for rel in list(F3B_.GENERATED.values()) + [F3B_.FIGURE] + list(F3B_.PUBLISHED.values()):
        require(not (manuscript / rel).exists(), 'Generated file already exists: ' + rel)
    require(not (manuscript / F3B_.TRACE_NAME).exists() and not (manuscript / F3B_.RECEIPT_NAME).exists(), 'Existing confirmation trace/receipt')
    hosts = sorted({rel for _, rel, _, _ in edits})
    snapshot.mkdir()
    manifest = {}
    for rel in hosts:
        dst = snapshot / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manuscript / rel, dst)
        manifest[rel] = sha256(dst)
    (snapshot / 'MANIFEST.json').write_text(json.dumps({'purpose': 'pre-fill copies of every host file edited by summary_comparisons_conf_results.py', 'files_sha256': manifest}, indent=2) + '\n')
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
    for source in F3B_.SOURCES:
        require(outputs[F3B_.PUBLISHED[source]] == sha256(scores.scored / (source + '__CLIPPING.csv')), 'Published clipping file differs from the frozen score output')
    with (manuscript / F3B_.TRACE_NAME).open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['location', 'number', 'source_file', 'source_field', 'note'])
        w.writeheader()
        w.writerows(trace)
    slot_texts = [{'slot': sid, 'file': rel, 'old': old, 'new': r.R.peek(new) if '\x00' in new else new} for sid, rel, old, new in edits]
    ac = r.ts.author_confirmation
    receipt = {'state': 'CONF_RESULTS_FILLED', 'fill_step': 'FILL3e', 'utc': datetime.now(timezone.utc).isoformat(),
               'script_sha256': sha256(Path(__file__)), 'sensitivity_comparisons_script_sha256': sha256(MS / 'sensitivity_comparisons_conf_results.py'),
               'freeze_sha256': sha256(MS / FREEZE_NAME) if (MS / FREEZE_NAME).is_file() else None, 'sensitivity_comparisons_freeze_sha256': SENSITIVITY_COMPARISONS_FREEZE_SHA256,
               'a7_freeze_sha256': A7_FREEZE_SHA256, 'a6_freeze_sha256': F3D.A6_FREEZE_SHA256, 'a5_freeze_sha256': F3D.F3C.A5_FREEZE_SHA256, 'freeze': freeze,
               'templates_sha256': sha256(MS / TEMPLATES_NAME), 'a7_inactive_forms': A7RULES['replaces_forms'],
               'manuscript': str(manuscript), 'scored_directory': str(scores.scored), 'score_receipt_sha256': scores.receipt_sha256, 'seal_sha256': scores.seal_sha256,
               'a2_postscore_sha256': a2post.sha256, 'a3_postscore_sha256': a3post.sha256, 'a4_postscore_sha256': a4post.sha256,
               'score_files_verified': len(scores.files), 'frozen_adapter_cross_checks': r.cross_checks, 'a1_cross_checks': r.a1_checks,
               'a2_sentence_checks': Counter(r.sentence_checks), 'a3_sentence_checks': r.a3_checks, 'a4_sentence_checks': r.a4_checks,
               'a6_checks': r.a6_checks, 'a6_form_counts': r.a6_keys, 'a7_checks': r.a7_checks, 'k4_rendering': 'PASS', 'k6': r.k6, 'k6_text': r.k6_text,
               'k7_text': r.k7_text, 'k7_abstract': getattr(r, 'k7_abstract', None), 'author_confirmation': {k: ac[k] for k in ('path', 'sha256', 'label', 'addenda', 'dates', 'seventh')},
               'figure_overlaps': r.figure_overlaps, 'inputs': r.inputs, 'abstract_words': words, 'abstract_level': r.abstract_level,
               'a4_abstract_level': r.a4_abstract_level, 'abstract_counts': r.abstract_counts, 'abstract_over_limit': False,
               'trace_rows': len(trace), 'retired_host_tokens': r.retired, 'outputs_sha256': outputs, 'slot_texts': slot_texts,
               'generated_files': sorted([rel for rel in resolved if rel not in {e[1] for e in edits}] + list(binary)),
               'snapshot': F3B_.SNAPSHOT_NAME + '/MANIFEST.json', 'refill_of': refill_of, 'stage_table_ref': F3B_.STAGE_TABLE_REF}
    (manuscript / F3B_.RECEIPT_NAME).write_text(json.dumps(receipt, indent=2, default=str) + '\n')
    return receipt


def prepare_refill(manuscript):
    F3B_ = deps()
    receipt_path = manuscript / F3B_.RECEIPT_NAME
    require(receipt_path.is_file(), 'No fill receipt: run the normal command instead of --refill')
    receipt = json.loads(receipt_path.read_text())
    require(receipt.get('fill_step') == 'FILL3e', 'The manuscript was not filled by FILL3e; --refill refuses')
    for rel, digest in receipt['outputs_sha256'].items():
        require((manuscript / rel).is_file() and sha256(manuscript / rel) == digest, f'{rel} changed after the FILL3e fill; --refill refuses')
    reader, manifest = F3B_.snapshot_reader(manuscript)
    return receipt, reader, manifest


def verify_freeze():
    path = MS / FREEZE_NAME
    require(path.is_file(), FREEZE_NAME + ' missing: FILL3e must be frozen before use')
    freeze = json.loads(path.read_text())
    require(freeze.get('state') == 'SUMMARY_COMPARISONS_FROZEN_BEFORE_CONF_SCORES', 'Unexpected FILL3e freeze state')
    for rel, digest in freeze['files'].items():
        require(sha256(MS / rel) == digest, f'{rel} differs from its FILL3e freeze hash')
    for rel, digest in freeze.get('external_identities', {}).items():
        require(sha256(PROJ / rel) == digest, f'{rel} differs from the identity recorded in the FILL3e freeze')
    require(freeze['files'].get(Path(__file__).name) == sha256(Path(__file__)), 'summary_comparisons_conf_results.py is not bound by SUMMARY_COMPARISONS_FREEZE.json')
    return freeze


def build(manuscript):

    deps()
    env = {**os.environ, 'TECTONIC_CACHE_DIR': 'runtime/tex_cache'}
    subprocess.run(['/usr/bin/nice', '-n', '10', '/opt/homebrew/bin/tectonic', '-X', 'compile', str(manuscript / 'supplement.tex'), '--keep-logs', '--keep-intermediates'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, check=True)
    aux = (manuscript / 'supplement.aux').read_text(errors='replace')
    m = re.search('\\\\newlabel\\{supp:tab:main_comparisons-stages\\}\\{\\{([^}]*)\\}', aux)
    stage_ref = m.group(1) if m else None
    proc = subprocess.run(['/usr/bin/nice', '-n', '10', '/bin/zsh', str(manuscript / 'build_MS12.sh')], capture_output=True, text=True)
    result = {'build_exit': proc.returncode, 'stage_table_number': stage_ref, 'stage_table_ok': stage_ref == F3B.STAGE_TABLE_REF}
    main_aux = (manuscript / 'main.aux').read_text(errors='replace') if (manuscript / 'main.aux').exists() else ''
    m2 = re.search(r'\\newlabel\{tab:ms14-published-gains\}\{\{([^}]*)\}', main_aux)
    expected = json.loads((MS / TEMPLATES_NAME).read_text())['a5']['published_gains_table_number']
    result.update(published_gains_table_number=m2.group(1) if m2 else None, published_gains_table_ok=bool(m2) and m2.group(1) == expected)
    if proc.returncode != 0:
        result['build_tail'] = (proc.stdout + proc.stderr)[-3000:]
        result['state'] = 'BUILD_FAILED'
    elif not result['stage_table_ok']:
        result['state'] = 'BUILT_STAGE_TABLE_NUMBER_MISMATCH'
    else:
        result['state'] = 'BUILT' if result['published_gains_table_ok'] else 'BUILT_TABLE_NUMBER_MISMATCH'
    (manuscript / 'qa').mkdir(exist_ok=True)
    (manuscript / BUILD_RESULT).write_text(json.dumps(result, indent=2) + '\n')
    return result


def main(argv=None):
    global AUTHOR_CONFIRMATION
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    F3B_ = deps()
    parser.add_argument('--state', type=Path, default=F3B_.DEFAULT_STATE)
    parser.add_argument('--manuscript', type=Path, default=MS)
    parser.add_argument('--base25-root', type=Path, default=F3B_.STUDY / 'BASE25')
    parser.add_argument('--positive-control', type=Path, default=F3B_.DEFAULT_PC)
    parser.add_argument('--pcx', type=Path, default=F3B_.DEFAULT_PCX)
    parser.add_argument('--pcx-freeze', type=Path, default=F3B_.DEFAULT_PCX_FREEZE)
    parser.add_argument('--pcx-args', type=Path, default=F3B_.DEFAULT_PCX_ARGS)
    parser.add_argument('--news-review-scores', type=Path, default=PROJ / 'reports/llm_text_quality_completion_20260928/news_validation_v4/SCORES.json')
    parser.add_argument('--nrx-review-scores', type=Path, default=F3B_.LAMP / 'reports/llm_text_quality_completion_20260928/semantic_validation_nrx/human_review/SCORES.json')
    parser.add_argument('--conf-review-scores', type=Path, default=F3B_.REVIEW_DIR / 'SCORES.json')
    parser.add_argument('--agreement', type=Path, default=F3B_.REVIEW_DIR / 'SECOND_ANNOTATOR_AGREEMENT.json')
    parser.add_argument('--coverage', type=Path, default=F3B_.DEFAULT_COVERAGE)
    parser.add_argument('--timestamps', type=Path, default=F3B_.DEFAULT_TS)
    parser.add_argument('--a2batch', type=Path, default=F3B_.STUDY / 'batch_scoring/scores/A2BATCH_RESULT.json')
    parser.add_argument('--a2label', type=Path, default=F3B_.STUDY / 'label_scoring/scores/A2LABEL_RESULT.json')
    parser.add_argument('--author-confirmation', type=Path, default=DEFAULT_AUTHOR_CONFIRMATION)
    parser.add_argument('--test-keys-per-day', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--prefill', action='store_true', help="write the FILL3e PREFILL (stage 1 = FILL3b, stage 2 = FILL3d, stage 3 = confirmation-A7 section X'; pre-score)")
    parser.add_argument('--check-prefill', action='store_true', help='regenerate the PREFILL in memory and compare with the manuscript')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--refill', action='store_true')
    args = parser.parse_args(argv)
    manuscript = args.manuscript.resolve()
    if args.prefill or args.check_prefill:
        coverage = F3B_.Coverage(args.coverage)
        result = write_presummary_comparisons(manuscript, coverage, check_only=args.check_prefill)
        print(json.dumps({k: result[k] for k in result if k != 'outputs_sha256'}, indent=2))
        return 0 if result['state'] in ('SUMMARY_COMPARISONS_PREFILL_WRITTEN', 'PREFILL_EQUAL') else 3
    AUTHOR_CONFIRMATION = args.author_confirmation
    freeze = verify_freeze()
    reader, previous = None, None
    if args.refill:
        require(args.apply, '--refill requires --apply')
        old_receipt, reader, manifest = prepare_refill(manuscript)
        previous = {k: old_receipt.get(k) for k in ('seal_sha256', 'score_receipt_sha256', 'a2_postscore_sha256')}
    r, scores, a2post, a3post, a4post, generated, binary, edits, states, T = F3B_.render(args, manuscript, reader, previous)
    rd = reader or (lambda rel: (manuscript / rel).read_text())
    resolved, trace, words = F3B_.plan(manuscript, r, generated, edits, rd, binary, T)
    require(words <= WORD_LIMIT, f'ABSTRACT_OVER_250: {words} validator words in the resolved abstract (A6 K6.1, never waived)')
    r.k6_text = F3D.k6_text_check(r, resolved, edits)
    resolved_all = dict(resolved)
    for sid, rel, old, new in edits:
        if rel not in resolved_all:
            resolved_all[rel] = rd(rel).replace(old, r.R.peek(new) if '\x00' in new else new, 1)
    r.k7_text = k7_text_check(r, resolved_all, edits)
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
                          'abstract_level': r.abstract_level, 'a4_abstract_level': r.a4_abstract_level, 'components': states}, indent=2))
        return 0
    refill = None
    if args.refill:
        refill = F3B_.archive_previous_fill(manuscript, old_receipt, manifest)
    receipt = write_outputs(manuscript, scores, r, a2post, a3post, a4post, resolved, binary, trace, words, edits, freeze, refill)
    print(json.dumps({k: receipt[k] for k in ('state', 'fill_step', 'trace_rows', 'abstract_words', 'abstract_level', 'a4_abstract_level')}
                     | {'components': states, 'refill_archive': refill}, indent=2))
    if args.build:
        b = build(manuscript)
        print(json.dumps({k: v for k, v in b.items() if not k.endswith('tail')}, indent=2))
        if b['state'] != 'BUILT':
            print('BUILD FAILED: see ' + BUILD_RESULT, file=sys.stderr)
            return 4
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except FillError as exc:
        print('FILL REFUSED: ' + str(exc), file=sys.stderr)
        sys.exit(2)
