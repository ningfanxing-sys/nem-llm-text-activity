#!/usr/bin/env python3
"""FILL3d: results fill under the sixth pre-score addendum CONF-A6 (SPEC_FILL3D.md).

Pre-score (stage-2 PREFILL on top of the unchanged FILL3b/FILL3c PREFILL):
    python manuscript_tex/fill3d_conf_results.py --prefill [--coverage F]
    python manuscript_tex/fill3d_conf_results.py --check-prefill [--coverage F]
After scoring (cli.py score -> a2_postscore.py -> a3_postscore.py -> a4_postscore.py --positive-control .. --pcx ..):
    python manuscript_tex/fill3d_conf_results.py --apply --build
    python manuscript_tex/fill3d_conf_results.py --apply --refill --build     # later inputs

FILL3d imports the frozen FILL3c module read-only after FILL3C_FREEZE.json and every file and identity it binds verify
(FILL3c then verifies FILL3b and A5; FILL3b verifies FILL3a, FILL3, FILL2, A4, A3 and A2), and the frozen CONF-A6 rules
after ADDENDUM_A6_FREEZE.json verifies. In memory only it rebinds FILL3b's module names to FILL3d names and installs its
own renderer class (a subclass of FILL3c's), timestamp gate, slot edits and PREFILL equality check. CONF-A6 changes: one
result-state record (RS6) read by the abstract, Table 6, sections 6.2, 6.3, 7.2, the conclusion and Figure 2; the reading
gate; the abstract ladder N0-C5 (never a pointer, never above 250 validator words); the diagnostic wording; the stage-2
PREFILL (title switch, contribution 3, section 4.6, T4/T5, the fifth and sixth addenda in the supplement record and the
audit archive, fixed pre-score facts). FILL3c, FILL3b, FILL3a, FILL3 and FILL2 are never run.
"""
from __future__ import annotations

import argparse
import copy
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
import textwrap

MS = Path(__file__).resolve().parent
PROJ = MS.parent
CONF = PROJ / 'autopilot/q1_audits/CONF'
A5DIR = CONF / 'A5'
A6DIR = CONF / 'A6'
FILL3C_FREEZE_SHA256 = 'edabe2c9a5272443111f89521974d7854b88ac3b9f48ea52d5381d78eb87d1b3'
A6_FREEZE_SHA256 = '49d8a20d5507f6c3530b70ea32808219fe56115fcaae56fb6ff75af11768661d'
FREEZE_NAME = 'FILL3D_FREEZE.json'
SPEC_FREEZE_NAME = 'FILL3D_SPEC_FREEZE.json'
TEMPLATES_NAME = 'fill3d_templates.json'
TEMPLATES_REL = 'manuscript_tex/' + TEMPLATES_NAME
A6_RULES_REL = 'autopilot/q1_audits/CONF/A6/RULES_FOR_FILL3D.json'
NOTE_PREFIX = 'FILL3 CONF fill (FILL3d)'          # kept by the unchanged finalize_MS12_trace.py (FILL[23] CONF fill)
RUNS_ARCHIVE = 'previous_conf_fill3d_runs'
PREVIEW_NAME = 'qa/FILL3D_PREVIEW'
PREFILL_RECEIPT = 'qa/FILL3D_PREFILL_RECEIPT.json'
BUILD_RESULT = 'qa/FILL3D_BUILD_RESULT.json'
PREFILL_TRACE3D = 'FILL3D_PREFILL_TRACE.csv'
PREFILL_NOTE3D = 'MS15 current locator; FILL3d prefill'
WORD_LIMIT = 250
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")
LEVELS = ('N0', 'T1', 'T2', 'T3', 'T4', 'C1', 'C2', 'C3', 'C4', 'C5')
RANK = {lv: i for i, lv in enumerate(LEVELS)}
SOURCES = ('news', 'notice')
CONTENT_ARMS = ('L_chen', 'L_chen_notice')
CLASS_KEYS = {'CONDITIONAL_IMPROVEMENT': 'IMP', 'NO_RELIABLE_INCREMENT_DETECTED': 'NULL', 'CONDITIONAL_DETERIORATION': 'DET'}
LAYERS = ('label_replacement', 'l1_family', 'pd_family', 'first_chunk', 'window_24h', 'official_cap', 'drop_first_seven')
OWN_LAYERS = ('label_replacement', 'l1_family', 'pd_family')
CHECK_ORDER = ('one_day', 'hln', 'hac7', 'seven_day', 'three_seed')
NE_SECTION_FORMS = ('A6H4',)


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


def validator_words(text):
    """validate_MS12.py line 77 count on a plain text."""
    return len(WORD_RE.findall(text))


def join(items):
    items = list(items)
    if not items:
        return ''
    return items[0] if len(items) == 1 else ', '.join(items[:-1]) + ' and ' + items[-1]


# ============================================================================= frozen dependencies
def load_fill3c():
    """FILL3c, imported read-only after FILL3C_FREEZE.json and every file and identity it binds verify (SPEC 1)."""
    path = MS / 'FILL3C_FREEZE.json'
    require(sha256(path) == FILL3C_FREEZE_SHA256, 'FILL3C_FREEZE.json identity drift')
    freeze = json.loads(path.read_text())
    for group in ('files', 'test_receipts'):
        entries = freeze.get(group, {})
        entries = entries if isinstance(entries, dict) else {}
        for rel, digest in entries.items():
            require(sha256(MS / rel) == digest, f'FILL3c frozen file drift: {rel}')
    for rel, digest in (freeze.get('external_identities') or {}).items():
        require(sha256(PROJ / rel) == digest, f'FILL3c external identity drift: {rel}')
    require(freeze['files'].get('fill3c_conf_results.py') == sha256(MS / 'fill3c_conf_results.py'), 'fill3c_conf_results.py is not bound by FILL3C_FREEZE.json')
    name = 'fill3c_conf_results'
    if name in sys.modules:
        require(Path(sys.modules[name].__file__).resolve() == (MS / 'fill3c_conf_results.py').resolve(), 'Unexpected fill3c module')
        return sys.modules[name]
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(name, MS / 'fill3c_conf_results.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    module.FillError = FillError        # FILL3c (and through it FILL3b ... FILL2) raise FILL3d's refusal type (in memory only)
    return module


def load_a6():
    """The frozen CONF-A6 rule sheet after its freeze, the three files it binds and the appendix-block identity verify."""
    path = A6DIR / 'ADDENDUM_A6_FREEZE.json'
    require(sha256(path) == A6_FREEZE_SHA256, 'ADDENDUM_A6_FREEZE.json identity drift')
    for rel, ident in json.loads(path.read_text())['files'].items():
        require(sha256(A6DIR / rel) == ident['sha256'], f'Frozen A6 file drift: {rel}')
    text = (A6DIR / 'RULES_FOR_FILL3D.json').read_text()
    blocks = re.findall(r'```json\n(.*?)\n```', (A6DIR / 'ADDENDUM_A6.md').read_text(), re.S)
    require(len(blocks) == 1 and blocks[0] + '\n' == text, 'RULES_FOR_FILL3D.json differs from the ADDENDUM_A6.md appendix block')
    return json.loads(text)


F3C = None
F3B = None
A6RULES = None
F6 = None                    # A6 forms (verbatim from the frozen rule sheet)
WD = None                    # A6 word lists
TP = None                    # A6 templates
ORIG = {}


def deps():
    """FILL3c (with FILL3b, A5, A4, A3, A2) and the A6 rules, loaded once; FILL3b names rebound to FILL3d names in memory."""
    global F3C, F3B, A6RULES, F6, WD, TP
    if F3C is None:
        F3C = load_fill3c()
        F3B = F3C.deps()
        A6RULES = load_a6()
        F6, WD, TP = A6RULES['forms'], A6RULES['words'], A6RULES['templates']
        for key in ('renderer_class', 'A4Post', 'Timestamps', 'host_edits', 'prefill_equality'):
            ORIG[key] = getattr(F3B, key)
        F3B.TEMPLATES_NAME = TEMPLATES_NAME
        F3B.TEMPLATES_REL = TEMPLATES_REL
        F3B.FREEZE_NAME = FREEZE_NAME
        F3B.NOTE_PREFIX = NOTE_PREFIX
        F3B.RUNS_ARCHIVE = RUNS_ARCHIVE
        F3B.PREVIEW_NAME = PREVIEW_NAME
        F3B.PREFILL_RECEIPT = PREFILL_RECEIPT
        F3B.renderer_class = renderer_class3d
        F3B.Timestamps = Timestamps3d
        F3B.host_edits = host_edits3d
        F3B.prefill_equality = prefill_equality3d
        T3d = json.loads((MS / TEMPLATES_NAME).read_text())
        T3b = json.loads((MS / 'fill3b_templates.json').read_text())
        require(json.dumps(T3d['prefill'], sort_keys=True) == json.dumps(T3b['prefill'], sort_keys=True),
                'fill3d_templates.json prefill block differs from FILL3b\'s: stage 1 of the FILL3d PREFILL must equal the FILL3b PREFILL')
        for key, tkey in (('primary.intro', 'primary_intro'), ('primary.figure_caption', 'figure_caption'), ('secondary.sens_caption', 'sens_caption'),
                          ('supplement_block.attribution_text', 'attribution_text'), ('intro.final_clause', 'intro_final_clause'),
                          ('design.timestamps', 'design_timestamps'), ('supplement.timestamp_content.T5', 'timestamp_content_T5'),
                          ('a6.abstract_marker', 'abstract_marker')):
            node = T3d
            for part in key.split('.'):
                node = node[part]
            require(node == TP[tkey], f'fill3d_templates.json {key} differs from the A6 template {tkey}')
    return F3B


def a4mod():
    return deps().A4MOD


def form(key, **values):
    return F6[key].format(**values)


# ============================================================================= A6 abstract (AB''), production renderer over RS6
def robust_inc(c):
    return c['cls'] == 'IMP' and c['robust'] == 'ROBUST'


def class_text(c, r):
    key = c['cls'] + ('_ROBUST' if c['robust'] == 'ROBUST' else '_OTHER') if c['cls'] in ('IMP', 'DET') else c['cls']
    t = WD['PRIMARY'][key]
    if r >= RANK['C1'] and t.startswith('a '):
        t = t[2:]
    if c['cls'] in ('IMP', 'DET') and c.get('zero'):
        t += '; family-adjusted interval includes zero' if r >= RANK['C1'] else ', although its family-adjusted interval includes zero'
    return t


def rob_quals(c, r):
    lab = c['robust']
    if lab == 'ROBUST':
        return ['inferentially robust'] if r < RANK['T1'] else []
    if r >= RANK['C2']:
        if lab == 'FRAGILE':
            return ['fragile, not fully checked' if c['unavailable'] else 'fragile']
        return ['not fully checked']
    words = WD['TS6C'] if r >= RANK['C1'] else WD['TS6']
    out = []
    if lab == 'FRAGILE':
        ts, tail = c.get('ts'), ''
        if ts == 'NA':
            tail = '' if 'three_seed' in c['unavailable'] else ', three-seed mean not available'
        elif ts and ts != c['cls']:
            tail = ', three-seed mean ' + words[ts]
        out.append('fragile: ' + join(WD['CHECK_SHORT'][k] for k in c['dissent']) + ' disagreed' + tail)
    if c['unavailable']:
        out.append('not fully checked: ' + join(WD['CHECK_SHORT'][k] for k in c['unavailable']) + ' unavailable')
    return out


def quals(source, c, r, conclusion=False):
    q = rob_quals(c, r)
    compact = r >= RANK['C1']
    if c.get('dd'):
        if r >= RANK['C2']:
            q.append('design dissent')
        elif compact:
            q.append('design dissent: ' + join(WD['SENS_COMPACT'][k] for k, _ in c['dd']))
        else:
            q.append('design dissent: ' + join(form('A6RD_ITEM', sensitivity=WD['SENS_LONG'][k], **{'class': WD['TS6'][x]}) for k, x in c['dd']))
    if c.get('erd'):
        q.append('extraction-run-dependent' if r >= RANK['C2'] else
                 'extraction-run-dependent: ' + (WD['TS6C'][c['erd']] if compact else WD['TS6'][c['erd']] + ' with re-extracted labels'))
    bench = WD['BENCH'][source]
    if robust_inc(c):
        q.append(WD['POSITION'][c['ic']].format(S=(WD['S_VALUE'][source] + '%') if compact else WD['S_PHRASE'][source]))
        if r < RANK['C3']:
            if c.get('cb') is None:
                q.append(F6['A6CB_NA'])
            elif c['cbl'] == 'ROBUST':
                q.append((WD['CB_ROBUST_C'] if compact else WD['CB_ROBUST'])[c['cb']].format(bench=bench))
            else:
                q.append(form('A6CB_N', bench=bench, combo_robust=WD['COMBO_LABEL'][c['cbl']],
                              **{'class': (WD['TS6C'] if compact else WD['TS6'])[{'S1': 'IMP', 'S2': 'NULL', 'S3': 'DET'}[c['cb']]]}))
        if not conclusion:
            q.append((WD['CHEAP_C'] if compact else WD['CHEAP_N'])[c['cheap']])
            if c['arm'] in CONTENT_ARMS and r < RANK['T4'] and c.get('shift'):
                s = c['shift']
                q.append(form('A6SHIFT', se=s['se'], **{'class': WD['CS6'][s['cls']]}) if s.get('state') == 'COMPUTED' else F6['A6SHIFTX'])
    elif c['cls'] == 'IMP':
        q.append(F6['A6NA'])
        if r < RANK['C3']:
            if c.get('cbn') is None:
                q.append(F6['A6CB_NA'])
            else:
                w = (WD['TS6C'] if compact else WD['TS6'])[c['cbn']]
                q.append(form('A6CB_N', bench=bench, combo_robust=WD['COMBO_LABEL'][c['cbnl']], **{'class': w}))
    return q


def clause(source, c, r, conclusion=False):
    name = WD['ARM_WORDS'][c['arm']] if conclusion else WD['SHORT'][c['arm']]
    if c['cls'] == 'NE':
        return form('A6CX', name=name, reason=c.get('reason') or 'its pre-specified input or completion gate failed')
    iv = aud = ''
    if robust_inc(c):
        iv = form('A6IV', lo=c['lo'], hi=c['hi'])
        aud = form('A6AUDC' if r >= RANK['C1'] else 'A6AUD', aud=c['aud'])
    return form('A6C', name=name, se=c['se'], interval=iv, aud=aud, class_text=class_text(c, r),
                quals=''.join('; ' + x for x in quals(source, c, r, conclusion)))


def mn_text(t, r):
    mn = t['mn']
    if mn.get('state') != 'COMPUTED':
        return form('A6MNX', reason=mn.get('reason') or 'it was not computed')
    return form('A6MN', se=mn['se'], **{'class': (WD['CS6C'] if r >= RANK['C1'] else WD['CS6'])[mn['cls']]})


def task_alert(t):
    return t['scenario'] != 'INCOMPLETE' and t['pc'] in ('SENSITIVITY_FAILS', 'SIZE_FAILS', 'BOTH_FAIL')


def task_sentence(source, t, r, conclusion=False):
    if t['scenario'] == 'INCOMPLETE':
        if r >= RANK['C5']:
            return form('A6T5_INC', head=WD['HEAD5'][source], reason=WD['INC_REASON5'][t['reason5']])
        return form('A6AB_INC', task_label=WD['TASK_LABEL'][source], reason=t['reason'])
    if r >= RANK['C5']:
        return task5(source, t)
    compact = r >= RANK['C1']
    alert = F6['A6ALERTM'] if (r >= RANK['C4'] and task_alert(t)) else ''
    base = dict(task_label=WD['TASK_LABEL'][source], activity_words=WD['ACTIVITY_WORDS'][source], mn=mn_text(t, r),
                clauses='; '.join(clause(source, c, r, conclusion) for c in t['contrasts']), alert=alert)
    sens_fail = t['pc'] in ('SENSITIVITY_FAILS', 'BOTH_FAIL')
    if t['scenario'] == 'B':
        sens = (F6['A6SENS_BC'] if compact else F6['A6SENS_B']) if (sens_fail and any(c['cls'] == 'NULL' for c in t['contrasts'])) else ''
        return form('A6AB_B', sens=sens, **base)
    if t.get('bound') is None:
        return form('A6AB_ANE', **base)
    X, side, s7, mc = t['bound']
    nc = t['pc'] in ('SIZE_FAILS', 'BOTH_FAIL')
    if compact:
        bound = form('A6BOUND_NCC' if nc else 'A6BOUNDC', X=X, below_or_above=side, S=WD['S_VALUE'][source]) + \
            (F6['A6ENVC'] if s7 else '') + (F6['A6MCC'] if mc else '')
        context = F6['A6HNC'] if source == 'news' else form('A6CTXC', hist_cmp_c=WD['HIST_CMP_C'][t['hist']])
        sens = F6['A6SENS_AC'] if sens_fail else ''
    else:
        bound = form('A6BOUND_NC' if nc else 'A6BOUND', X=X, below_or_above=side, S_phrase=WD['S_PHRASE'][source], tail=WD['TAIL'][source]) + \
            (F6['A6ENV'] if s7 else '') + (form('A6MC', S_phrase=WD['S_PHRASE'][source]) if mc else '')
        context = F6['A6HN'] if source == 'news' else form('A6CTX', hist_cmp=t['hist'])
        sens = F6['A6SENS_A'] if sens_fail else ''
    return form('A6AB_A', bound=bound, context=context, sens=sens, **base)


def marks5(c):
    q = []
    if c['cls'] == 'NE':
        return q
    if c['robust'] == 'FRAGILE':
        q.append('fragile')
        if c.get('unavailable'):
            q.append('not fully checked')
    elif c['robust'] == 'NOT_FULLY_CHECKED':
        q.append('not fully checked')
    if c['cls'] in ('IMP', 'DET') and c.get('zero'):
        q.append('interval includes zero')
    if c.get('erd'):
        q.append('extraction-run-dependent')
    if c['cls'] == 'IMP' and c['robust'] != 'ROBUST':
        q.append('attribution and comparison-value classes not assigned')
    require(all(m in WD['MARK5'] for m in q), 'C5 mark outside MARK5')
    return [m for m in WD['MARK5'] if m in q]


def gkey(c):
    if c['cls'] == 'NE':
        return 'X'
    if c['cls'] == 'NULL':
        return 'N'
    if c['cls'] == 'DET':
        return 'DR' if c['robust'] == 'ROBUST' else 'DP'
    return 'R' if c['robust'] == 'ROBUST' else 'P'


def entry5(source, c, drop):
    name = WD['SHORT'][c['arm']]
    if c['cls'] == 'NE':
        return name
    if robust_inc(c):
        body = form('A6T5_INCR', name=name, se=c['se'], lo=c['lo'], hi=c['hi'], aud=c['aud'], position=WD['POSITION5'][c['ic']],
                    S=WD['S_VALUE'][source], cheap=WD['CHEAP5'][c['cheap']])
    else:
        body = form('A6T5_OTHER', name=name, se=c['se'])
    q = [m for m in marks5(c) if m not in drop]
    return body + (' (' + '; '.join(q) + ')' if q else '')


def task5(source, t):
    mn = t['mn']
    mn5 = form('A6T5_MN', se=mn['se'], **{'class': WD['CS6C'][mn['cls']]}) if mn.get('state') == 'COMPUTED' else F6['A6T5_MNX']
    groups = []
    for key, label in WD['GROUP5']:
        members = [c for c in t['contrasts'] if gkey(c) == key]
        if not members:
            continue
        shared = [m for m in WD['MARK5'] if key != 'X' and len(members) >= 2 and all(m in marks5(c) for c in members)]
        lab = label + (' (all ' + '; '.join(shared) + ')' if shared else '')
        groups.append(lab + ' ' + ', '.join(entry5(source, c, set(shared)) for c in members))
    bound5 = tail5 = ''
    if t['scenario'] == 'A' and t.get('bound') is not None:
        X, side, s7, mc = t['bound']
        side5 = 'below' if side == 'below' else 'not below'
        nc = t['pc'] in ('SIZE_FAILS', 'BOTH_FAIL')
        bound5 = form('A6T5_BOUND_NC' if nc else 'A6T5_BOUND', X=X, side5=side5, S=WD['S_VALUE'][source])
        fl = ([WD['FLAGS5']['seven']] if s7 else []) + ([WD['FLAGS5']['mc']] if mc else [])
        fl.append(WD['FLAGS5']['news_power'] if source == 'news' else WD['FLAGS5']['notice_hist'].format(hist_cmp_c=WD['HIST_CMP_C'][t['hist']]))
        if t['pc'] in ('SENSITIVITY_FAILS', 'BOTH_FAIL'):
            fl.append(WD['FLAGS5']['sens'])
        bound5 += form('A6T5_FLAGS', flags='; '.join(fl))
    elif t['scenario'] == 'B' and t['pc'] in ('SENSITIVITY_FAILS', 'BOTH_FAIL') and any(c['cls'] == 'NULL' for c in t['contrasts']):
        tail5 += F6['A6T5_NULLS']
    if any(c.get('dd') for c in t['contrasts']):
        tail5 += F6['A6T5_DD']
    alert = F6['A6ALERTM'] if task_alert(t) else ''
    return form('A6T5', head=WD['HEAD5'][source], mn5=mn5, groups='; '.join(groups), bound5=bound5, tail5=tail5, alert=alert)


def alert_tasks(tasks):
    a = [s for s in SOURCES if task_alert(tasks[s])]
    if not a:
        return None
    return WD['ALERT_TASKS']['both' if len(a) == 2 else a[0]]


def lear_tail(ex, r):
    lear = ex['lear']
    if lear.get('state') != 'COMPUTED':
        return None if r >= RANK['C4'] else form('A6LT_NE', reason=lear.get('reason') or 'it was not computed')
    if r >= RANK['C4']:
        return form('A6LT3', abs=lear['abs'], lower_higher=lear['lower_higher'], **{'class': WD['CS6C'][lear['cls']]})
    cls = (WD['CS6C'] if r >= RANK['C1'] else WD['CS6'])[lear['cls']]
    return form('A6LT0' if r < RANK['T3'] else 'A6LT1', abs=lear['abs'], lower_higher=lear['lower_higher'], **{'class': cls})


def secondary(ex, r):
    out = []
    diffs = ex['diffs']
    if r < RANK['C1']:
        for d in diffs:
            out.append(form('A6Q1' if d['family'] == 'l1' else 'A6Q2', arm_words=WD['ARM_WORDS'][d['arm']], se=d['se'], lo=d['lo'], hi=d['hi'],
                            **{'class': WD['TS6'][d['cls']]}))
    elif r < RANK['C5']:
        if diffs:
            out.append(form('A6SECC', items='; '.join(form('A6SECC_ITEM', family=WD['FAMILY_C'][d['family']], name=WD['SHORT'][d['arm']], se=d['se'],
                                                            lo=d['lo'], hi=d['hi'], **{'class': WD['TS6C'][d['cls']]}) for d in diffs)))
    elif diffs:
        groups = []
        for cls in ('IMP', 'DET', 'NULL'):
            fams = []
            for fam in ('l1', 'pd'):
                items = [f"{WD['SHORT'][d['arm']]} {d['se']}% [{d['lo']}, {d['hi']}]" for d in diffs if d['cls'] == cls and d['family'] == fam]
                if items:
                    fams.append(WD['FAMILY5'][fam] + ' ' + ' and '.join(items))
            if fams:
                groups.append(WD['TS6C'][cls] + ': ' + ', '.join(fams))
        out.append(form('A6SEC5', groups='; '.join(groups)))
    for fam in ('l1', 'pd'):
        st = ex['batch'].get(fam)
        if isinstance(st, tuple) and st[0] == 'NOT_RUN':
            if r >= RANK['C5']:
                out.append(form('A6NR5', family=WD['FAMILY5'][fam], reason=WD['NR_REASON_C'][st[1]]))
            else:
                out.append(form('A6NR', family_name=WD['FAMILY_NAME'][fam], reason=(WD['NR_REASON_C'] if r >= RANK['C1'] else WD['NR_REASON'])[st[1]]))
        elif st == 'DEVIATION':
            out.append(form('A6DEV5', family=WD['FAMILY5'][fam]) if r >= RANK['C5'] else
                       form('A6DEVC' if r >= RANK['C1'] else 'A6DEV', family_name=WD['FAMILY_NAME'][fam]))
    return out


def any_robust_increment(tasks):
    return any(robust_inc(c) for s in SOURCES for c in tasks[s].get('contrasts', []))


def render_abstract(tasks, ex, level):
    """The abstract at one ladder level (A6 AB''2)."""
    r = RANK[level]
    robinc = any_robust_increment(tasks)
    at = alert_tasks(tasks)
    task_texts = [task_sentence(s, tasks[s], r) for s in SOURCES]
    if r >= RANK['C4']:
        lt = lear_tail(ex, r)
        y = F6['A6Y3NE'] if lt is None else form('A6Y3', lear26=lt)
        if r >= RANK['C5']:
            parts = [F6['A6DS3'], y, F6['A6KEY5_INC'] if robinc else F6['A6KEY5']] + ([F6['A6ALERT3']] if at else []) + task_texts
        else:
            parts = [F6['A6DS3'], y, F6['A6ROB_INC'] if robinc else F6['A6ROB']] + ([F6['A6ALERT3']] if at else []) + task_texts + \
                ([F6['A6ATTR']] if robinc else [])
        return ' '.join(parts + secondary(ex, r))
    design = F6['A6DS1'] if r >= RANK['T2'] else a4mod().SENTENCES['A4AB_PDS']
    year = form('A6Y1' if r >= RANK['T3'] else 'A6Y0', lear26=lear_tail(ex, r))
    parts = [design, year]
    if r >= RANK['T1']:
        parts.append(F6['A6ROB_INC'] if robinc else F6['A6ROB'])
    elif robinc:
        parts.append(F6['A6IVN'])
    parts += task_texts
    if robinc:
        parts.append(F6['A6ATTR'])
    if at:
        parts.append(form('A6ALERT', tasks=at))
    return ' '.join(parts + secondary(ex, r))


def ladder(tasks, ex):
    """A6 AB''2: the first level whose validator count is at most 250; the floor never exceeds 250 (Appendix P)."""
    counts = []
    for lv in LEVELS:
        text = render_abstract(tasks, ex, lv)
        counts.append({'level': lv, 'validator_words': validator_words(text), 'whitespace_words': len(text.split())})
        if counts[-1]['validator_words'] <= WORD_LIMIT:
            return {'level': lv, 'text': text, 'counts': counts}
    raise FillError('ABSTRACT_OVER_250: the A6 floor exceeded 250 validator words (impossible under the A6 proof)')


# ============================================================================= RS6: one result-state record (A6 R)
def cmap(A4, cls):
    return {A4.IMP: 'IMP', A4.NULL: 'NULL', A4.DET: 'DET'}.get(cls)


def cheap_reading(cheap):
    """A6 R3."""
    computed, unavailable = (cheap or {}).get('computed') or {}, (cheap or {}).get('unavailable') or []
    if unavailable or not computed:
        return 'UND'
    if all(v == 'beaten' for v in computed.values()):
        return 'BETTER'
    return 'WORSE' if any(v == 'worse' for v in computed.values()) else 'NOTSHOWN'


COMBO_LABEL_KEY = {'inferentially robust': 'ROBUST', 'fragile': 'FRAGILE', 'not fully checked': 'NOT_FULLY_CHECKED'}


def contrast6(A4, source, info, row, t, ds):
    """RS6 record of one primary contrast (categorical fields for the forms; A4 info and A2 row kept for details)."""
    cls = cmap(A4, info['class'])
    pair = f"{row['arm']}-{row['reference']}"
    layers = {}
    for layer in LAYERS:
        st = (ds.get(pair) or {}).get(layer) or {'state': 'NOT_APPLICABLE'}
        layers[layer] = cmap(A4, st.get('class')) if st.get('state') == 'DIFFERENT' else st.get('state')
    c = {'arm': info['arm'], 'reference': row['reference'], 'cls': cls or 'NE', 'info': info, 'row': row, 'layers': layers}
    if cls is None:
        c['reason'] = info.get('reason')
        return c
    rob = info['robust']
    ts = info.get('ts') or {}
    c.update(robust=rob['label'], dissent=list(rob['dissent']), unavailable=list(rob['unavailable']),
             ts=(cmap(A4, ts.get('class')) or 'NA') if ts.get('state') == 'COMPUTED' else 'NA', zero=bool(info.get('zero')),
             erd=cmap(A4, info.get('label_cls')) if info.get('label_cls') else None,
             dd=[(k, layers[k]) for k in LAYERS if k not in OWN_LAYERS and layers[k] in ('IMP', 'NULL', 'DET')],
             se=info['se'], lo=info['lo'], hi=info['hi'], aud=info['aud'])
    require(c['robust'] in ('ROBUST', 'FRAGILE', 'NOT_FULLY_CHECKED'), f'Unexpected robustness label {c["robust"]} for {pair}')
    require((c['erd'] is None) == (layers['label_replacement'] not in ('IMP', 'NULL', 'DET')),
            f'K6.6 label replacement of {pair} differs between A4 and A3')
    dissent_a4 = sorted(info.get('dissent_items') or [])
    dissent_a3 = sorted(A4.SENTENCES['A4RD_ITEM'].format(sensitivity=A4.A3.SENSITIVITY_NAMES[k], **{'class': A4.A3.CLASS_WORDS[{'IMP': A4.IMP, 'NULL': A4.NULL, 'DET': A4.DET}[x]]})
                        for k, x in c['dd'])
    require(dissent_a4 == dissent_a3, f'K6.6 design dissent of {pair} differs between A4 and A3: {dissent_a4} / {dissent_a3}')
    if cls == 'IMP':
        combo = info.get('combo')
        label = COMBO_LABEL_KEY[info.get('combo_robust') or 'not fully checked']
        if c['robust'] == 'ROBUST':
            key = (combo or {}).get('clause_id')
            c.update(ic=info['sesoi_class'], cb=key if combo is not None and key in ('S1', 'S2', 'S3') else None, cbl=label,
                     cheap=cheap_reading((info.get('attribution') or {}).get('cheap_text')))
        else:
            c.update(cbn=cmap(A4, (combo or {}).get('decision')) if combo is not None else None, cbnl=label)
        if info['arm'] == A4.A2.CONTENT_ARM[source]:
            shift = t.get('shift') or {}
            if shift.get('state') == 'COMPUTED':
                d = A4.decimals(shift.get('interval95'))
                c['shift'] = {'state': 'COMPUTED', 'se': A4.sfmt(shift.get('effect'), d), 'cls': cmap(A4, shift['class'])}
            else:
                c['shift'] = {'state': 'NE'}
    return c


def task6(A4, source, t, rows, ds):
    A3 = A4.A3
    if t['scenario'] == 'INCOMPLETE':
        reason = t['incomplete_reason']
        require(reason in (A3.SENTENCES['A3INC_BUDGET'], A3.SENTENCES['A3INC_FAIL']), 'Unexpected incomplete reason: ' + str(reason))
        return {'scenario': 'INCOMPLETE', 'reason': reason, 'reason5': 'budget' if reason == A3.SENTENCES['A3INC_BUDGET'] else 'fail',
                'pc': (t.get('pc') or {}).get('state', 'NOT_RUN'), 'contrasts': []}
    contrasts = [contrast6(A4, source, info, row, t, ds) for info, row in zip(t['infos'], rows)]
    mn = t['mn']
    if mn.get('state') == 'COMPUTED':
        d = A4.decimals(mn.get('interval95'))
        m = {'state': 'COMPUTED', 'se': A4.sfmt(mn.get('effect'), d), 'cls': cmap(A4, mn['class'])}
        require(m['cls'] is not None, 'Activity-against-numerical class not evaluable although computed')
    else:
        m = {'state': mn.get('state'), 'reason': A4.reason_phrase(mn.get('state'))}
    out = {'scenario': t['scenario'], 'contrasts': contrasts, 'mn': m, 'pc': t['pc']['state'], 'bound': None, 'hist': A3.HIST_CMP[0]}
    if t['scenario'] == 'A' and t.get('bound') is not None:
        X, d, s7, mc = t['bound']
        S = A3.SESOI[source]
        out['bound'] = (A4.A2.branch_safe_bound(X, d, S), 'below' if X < S else 'at or above', bool(s7), bool(mc))
        out['hist'] = A3.hist_cmp(X)
    return out


def extras6(A4, extras):
    A2, A3 = A4.A2, A4.A3
    lear = extras.get('lear') or {}
    if lear.get('state') == 'COMPUTED':
        d = A4.decimals(lear.get('interval95'))
        eff = lear.get('effect')
        require(A2.finite(eff), 'LEAR 2026 effect not finite although computed')
        lear6 = {'state': 'COMPUTED', 'abs': A2.fmt_effect(abs(eff), d), 'lower_higher': 'lower' if eff < 0 else 'higher', 'cls': cmap(A4, lear['class'])}
        require(lear6['cls'] is not None, 'LEAR 2026 class not evaluable although computed')
    else:
        lear6 = {'state': lear.get('state'), 'reason': A4.reason_phrase(lear.get('state'))}
    diffs = [{'family': 'l1' if q['family'] == 'l1_family' else 'pd', 'arm': q['arm'], 'cls': cmap(A4, q['class']), 'se': q['se'], 'lo': q['lo'], 'hi': q['hi']}
             for q in extras['batch_differences']]
    batch = {}
    for fam, key in (('l1', 'l1_family'), ('pd', 'pd_family')):
        rep = ((extras.get('batch') or {}).get('families') or {}).get(A3.BATCH_FAMILY_KEY[key])
        disp = A4.batch_disposition(rep)
        batch[fam] = {'COMPUTED': 'COMPUTED', 'PENDING': 'PENDING', 'DEVIATION': 'DEVIATION'}.get(disp[0]) or ('NOT_RUN', 'budget' if disp[1] == 'A4NR_BUDGET' else 'parity')
    return {'lear': lear6, 'diffs': diffs, 'batch': batch}


def build_rs6(A4, records, design_sensitivities):
    """RS6 for both tasks and the global readings; cross-checks the batch differences against A3's design layers (K6.6)."""
    tasks = {s: task6(A4, s, records['tasks'][s], records['rows'].get(s, []), design_sensitivities.get(s) or {}) for s in SOURCES}
    ex = extras6(A4, records['extras'])
    for c in tasks['news']['contrasts']:
        if c['cls'] == 'NE':
            continue
        for fam, layer in (('l1', 'l1_family'), ('pd', 'pd_family')):
            d = [q for q in ex['diffs'] if q['family'] == fam and q['arm'] == c['arm']]
            if ex['batch'][fam] == 'COMPUTED':
                expected = c['layers'][layer] if c['layers'][layer] in ('IMP', 'NULL', 'DET') else None
                require((d[0]['cls'] if d else None) == expected, f"K6.6 {fam} difference of {c['arm']} differs between A4 and A3")
            else:
                require(not d, f"K6.6 {fam} difference of {c['arm']} without a computed batch family")
    return {'tasks': tasks, 'extras': ex}


# ============================================================================= K6: abstract assertions (A6 K6.1-K6.4)
D1_WORDS = ('the size check', 'false-rejection rate', 'this concerns the power of the test', 'precision-limited', 'may be too narrow',
            'reliability may be overstated', 'an increment over article activity only', 'an increment over notice activity only')
POINTER_WORDS = ('Section', 'Supplement', 'Table', 'reported with', 'reported in')
NEWS_STARTS = ('For day-ahead news, adding', 'The day-ahead news confirmation', 'News (', 'News:')
NOTICE_STARTS = ('For market notices (creation-date surrogate clocks), adding', 'The market notices (creation-date surrogate clocks) confirmation',
                 'Notices (creation-date surrogate clocks) (', 'Notices (creation-date surrogate clocks):')
TAIL_STARTS = ('Each reliable increment', 'For day-ahead news, the pipeline', 'For market notices, the pipeline', 'For day-ahead news and market notices, the pipeline',
               'Under the absolute-error', 'With pre-dispatch', 'Single-seed', 'The absolute-error', 'The pre-dispatch')


def abstract_segments(text):
    def first(starts, frm=0):
        hits = [text.find(s, frm) for s in starts]
        hits = [h for h in hits if h >= 0]
        return min(hits) if hits else -1
    a = first(NEWS_STARTS)
    b = first(NOTICE_STARTS, a + 1 if a >= 0 else 0)
    require(a >= 0 and b > a, 'K6.3 abstract task sentences not found in order (news, then notices)')
    end = first(TAIL_STARTS, b + 1)
    return {'global': text[:a] + ' ' + (text[end:] if end >= 0 else ''), 'news': text[a:b], 'notice': text[b:end if end >= 0 else len(text)]}


def affirmative(text, phrase):
    return len(re.findall(r'(?<!no )(?<!No )\b' + phrase, text))


def gate_problems(text, rs, where):
    """K6.4 type-level reading gate on one rendered text."""
    p = []
    robust = {'IMP': False, 'DET': False}
    combo = {'S1': False, 'S3': False}
    for s in SOURCES:
        for c in rs['tasks'][s]['contrasts']:
            if c['cls'] in ('IMP', 'DET') and c['robust'] == 'ROBUST':
                robust[c['cls']] = True
            if robust_inc(c) and c.get('cbl') == 'ROBUST' and c.get('cb') in combo:
                combo[c['cb']] = True
    if not robust['IMP'] and affirmative(text, r'reliable increments?\b'):
        p.append(f'K6.4 {where}: "reliable increment" without an inferentially robust primary increment')
    if not robust['DET'] and affirmative(text, r'reliable deteriorations?\b'):
        p.append(f'K6.4 {where}: "reliable deterioration" without an inferentially robust primary deterioration')
    if not combo['S1'] and re.search(r'\bpersisted when\b', text):
        p.append(f'K6.4 {where}: "persisted when" without an inferentially robust combination')
    if not combo['S3'] and re.search(r'\breliably worse\b', text):
        p.append(f'K6.4 {where}: "reliably worse" without an inferentially robust combination')
    for w in D1_WORDS:
        if w in text:
            p.append(f'K6.4 {where}: superseded diagnostic or attribution wording "{w}"')
    for bad in (r'\ba reliable improvement\b', r'\bimproved reliably\b', r'\bperformed reliably worse\b', r'showed a reliable favourable difference'):
        if re.search(bad, text):
            p.append(f'K6.4 {where}: gated phrase {bad!r}')
    return p


def required_problems(rs, level, text):
    """K6.3: every required reading of A6 AB''1 at the chosen level."""
    r = RANK[level]
    seg = abstract_segments(text)
    p = []
    g = seg['global']
    if '21.3% lower' not in text:
        p.append('K6.3 2025 LEAR comparison missing')
    lear = rs['extras']['lear']
    if lear.get('state') == 'COMPUTED':
        if lear['abs'] + '% ' + lear['lower_higher'] not in text:
            p.append('K6.3 2026 LEAR estimate missing')
        word = (WD['CS6C'] if r >= RANK['C1'] else WD['CS6'])[lear['cls']]
        if word not in text:
            p.append('K6.3 2026 LEAR class missing')
    elif 'not evaluable' not in text and 'could not be evaluated' not in text:
        p.append('K6.3 2026 LEAR state missing')
    if r >= RANK['T1'] and 'inferentially robust' not in g:
        p.append('K6.3 robustness sentence missing')
    if any_robust_increment(rs['tasks']) and 'content and finer activity structure' not in text:
        p.append('K6.3 attribution sentence missing')
    if alert_tasks(rs['tasks']) and 'type-I error' not in text:
        p.append('K6.3 alert sentence missing')
    for word in ('2026', 'NEM', 'nested', 'imestamp', 'retrospective', 'creation-date surrogate clocks'):
        if word not in text:
            p.append(f'K6.3 scope word "{word}" missing')
    for d in rs['extras']['diffs']:
        names = (WD['SHORT'][d['arm']], WD['ARM_WORDS'][d['arm']])
        if not any(n in g for n in names) or d['se'] + '%' not in g or f"[{d['lo']}, {d['hi']}]" not in g or 'not fully checked' not in g:
            p.append(f"K6.3 batch difference {d['family']} {d['arm']} missing")
    for fam in ('l1', 'pd'):
        st = rs['extras']['batch'][fam]
        if isinstance(st, tuple) and 'not run' not in g:
            p.append(f'K6.3 {fam} not-run sentence missing')
        if st == 'DEVIATION' and 'deviation' not in g:
            p.append(f'K6.3 {fam} deviation sentence missing')
    for s in SOURCES:
        t, sg = rs['tasks'][s], seg[s]
        if t['scenario'] == 'INCOMPLETE':
            if 'incomplete' not in sg or 'not a null result' not in sg:
                p.append(f'K6.3 {s}: incomplete-task sentence missing')
            continue
        mn = t['mn']
        if mn.get('state') == 'COMPUTED':
            word = (WD['CS6C'] if r >= RANK['C1'] else WD['CS6'])[mn['cls']]
            if mn['se'] + '%' not in sg or word not in sg:
                p.append(f'K6.3 {s}: activity reading missing')
        elif 'not evaluable' not in sg and 'could not be evaluated' not in sg:
            p.append(f'K6.3 {s}: activity state missing')
        for c in t['contrasts']:
            if WD['SHORT'][c['arm']] not in sg:
                p.append(f"K6.3 {s} {c['arm']}: not named")
                continue
            if c['cls'] == 'NE':
                continue
            if c['se'] + '%' not in sg:
                p.append(f"K6.3 {s} {c['arm']}: estimate missing")
            cw = {'IMP': 'reliable increment' if robust_inc(c) else 'primary-seed increment',
                  'DET': 'reliable deterioration' if c['robust'] == 'ROBUST' else 'primary-seed deterioration', 'NULL': 'no reliable increment detected'}[c['cls']]
            req = [cw]
            if c['robust'] == 'FRAGILE':
                req.append('fragile')
            if c['unavailable']:
                req.append('not fully checked')
            if r < RANK['T1'] and c['robust'] == 'ROBUST':
                req.append('inferentially robust')
            if c['zero']:
                req.append('interval includes zero')
            if c.get('erd'):
                req.append('extraction-run-dependent')
            if c['cls'] == 'IMP' and c['robust'] != 'ROBUST':
                req.append('attribution and comparison-value classes not assigned')
            if c.get('dd'):
                req.append('design dissent')
            if robust_inc(c):
                req += [f"[{c['lo']}, {c['hi']}]", c['aud']]
                req.append({'BEYOND': 'beyond', 'ABOVE': 'straddling', 'BELOWPT': 'straddling', 'BELOW': 'below'}[c['ic']])
                req.append(WD['CHEAP5' if r >= RANK['C5'] else ('CHEAP_C' if r >= RANK['C1'] else 'CHEAP_N')][c['cheap']])
            for x in req:
                if x not in sg:
                    p.append(f"K6.3 {s} {c['arm']}: '{x}' missing")
        if t['scenario'] == 'A' and t.get('bound') is not None:
            X, side, s7, mc = t['bound']
            nc = t['pc'] in ('SIZE_FAILS', 'BOTH_FAIL')
            need = [X + '%', WD['S_VALUE'][s] + '%', 'no exclusion' if nc else 'excluded']
            if s7:
                need.append('seven-day')
            if mc:
                need.append('Monte Carlo')
            need.append('power' if s == 'news' else 'earlier notice gains')
            if t['pc'] in ('SENSITIVITY_FAILS', 'BOTH_FAIL'):
                need.append('sensitivity-limited')
            for x in need:
                if x not in sg:
                    p.append(f"K6.3 {s}: bound reading '{x}' missing")
            if nc and re.search(r'\bexcluded\b', sg):
                p.append(f'K6.4 {s}: "excluded" after a negative-control failure')
        if t['scenario'] == 'B' and t['pc'] in ('SENSITIVITY_FAILS', 'BOTH_FAIL') and any(c['cls'] == 'NULL' for c in t['contrasts']) and 'sensitivity-limited' not in sg:
            p.append(f'K6.3 {s}: null sensitivity reading missing')
        if task_alert(t) and r >= RANK['C4'] and 'alert' not in sg:
            p.append(f'K6.3 {s}: alert marker missing')
        if task_alert(t) and r < RANK['C4'] and WD['ALERT_TASKS']['news' if s == 'news' else 'notice'] not in g:
            p.append(f'K6.3 {s}: alert sentence does not name the task')
    return p


def check_abstract(rs, level, text):
    """K6.1-K6.4 on the plain abstract; returns the record or raises FillError."""
    problems = []
    words = validator_words(text)
    if words > WORD_LIMIT:
        problems.append(f'K6.1 ABSTRACT_OVER_250: {words} validator words')
    expected = ladder(rs['tasks'], rs['extras'])
    if expected['level'] != level or expected['text'] != text:
        problems.append(f'K6.1 level {level} differs from the ladder rule ({expected["level"]})')
    for w in POINTER_WORDS:
        if w in text:
            problems.append(f'K6.2 pointer word "{w}" in the abstract')
    for b in a4mod().BANNED_A4:
        if b in text:
            problems.append(f'K6.2 A4 banned string "{b}" in the abstract')
    if re.search(r'L_|L14|LLaz|Lchen|P5MIN|\bNP\b', text):
        problems.append('K6.2 arm symbol or internal code in the abstract')
    problems += required_problems(rs, level, text)
    problems += gate_problems(text, rs, 'abstract')
    require(not problems, 'A6 abstract assertions failed: ' + '; '.join(problems[:12]))
    return {'level': level, 'validator_words': words, 'checks': 'K6.1-K6.4 PASS'}


# ============================================================================= plain renderers: sections 6.2, 6.3, 7.2, conclusion (A6 S62-CO)
def robustness6(A4, c):
    info = c['info']
    rob = info['robust']
    A2 = A4.A2
    if rob['label'] == 'ROBUST':
        text = F6['A6R1']
    elif rob['label'] == 'FRAGILE':
        text = form('A6R2', dissent_list=join(A2.CHECK_NAME[k] for k in rob['dissent']))
        if rob['unavailable'] and '; ' in (rob.get('sentence') or ''):
            text += '; ' + rob['sentence'].split('; ', 1)[1]
    else:
        text = rob['sentence']
    if c['dd']:
        text += form('A6RD', items=join(form('A6RD_ITEM', sensitivity=WD['SENS_LONG'][k], **{'class': WD['TS6'][x]}) for k, x in c['dd']))
    return text


def combination6(A4, source, c):
    info = c['info']
    A2, A3 = A4.A2, A4.A3
    combo_row = info.get('combo')
    crob = info.get('combo_robust') or 'not fully checked'
    bench = A2.BENCHMARK_NAME[source]
    if combo_row is None:
        return form('A6S7', benchmark=bench, reason='the combination contrast was not computed'), 'A6S7'
    cls = cmap(A4, combo_row.get('decision'))
    if cls is None:
        return form('A6S7', benchmark=bench, reason='the combination contrast is undefined'), 'A6S7'
    one = combo_row['bootstrap']['1']
    d = A4.decimals(one.get('interval95_percent'))
    lo, hi = A2.fmt_interval(one.get('interval_family_adjusted_percent'), d)
    f = dict(benchmark=bench, effect=A2.fmt_effect(combo_row.get('effect_percent_reference_mae'), d), level=A3.LEVEL_TEXT[source], lo=lo, hi=hi,
             p=A2.display_p(combo_row.get('holm_p')), arm=combo_row['arm'], combo_robust=crob)
    if robust_inc(c) and crob == 'inferentially robust':
        key = {'IMP': 'A6S1', 'NULL': 'A6S2', 'DET': 'A6S3'}[cls]
        return form(key, **f), key
    return form('A6SN', **{'class': WD['TS6'][cls]}, **f), 'A6SN'


def three_seed6(A4, source, info):
    ts = info.get('ts') or {}
    if ts.get('state') == 'COMPUTED':
        d = A4.decimals(ts.get('interval95'))
        lo, hi = A4.A2.fmt_interval(ts.get('interval_family'), d)
        return form('A6TS', se=A4.sfmt(ts.get('effect'), d), level=A4.A3.LEVEL_TEXT[source], lo=lo, hi=hi, p=A4.A2.display_p(ts.get('holm_p')),
                    **{'class': WD['TS6'].get(cmap(A4, ts.get('class')), 'not evaluable')}), 'A6TS'
    return A4.SENTENCES['A4TSX'].format(reason=ts.get('reason', 'the extra-seed predictions were not available')), 'A4TSX'


def contrast_sentence6(A4, source, c, t):
    """One primary contrast sentence of section 6.2 (A6H1-A6H3F, A3H4)."""
    A2, A3 = A4.A2, A4.A3
    info, row = c['info'], c['row']
    if c['cls'] == 'NE':
        return A3.SENTENCES['A3H4'].format(arm=row['arm'], activity=A3.ACTIVITY[source], reason=info['reason']), 'A3H4'
    common = dict(arm=row['arm'], activity=A3.ACTIVITY[source], se=info['se'], aud=info['aud'], level=A3.LEVEL_TEXT[source],
                  lo=info['lo'], hi=info['hi'], p=info['p'], robustness=robustness6(A4, c))
    quals = []
    if c.get('erd'):
        quals.append(form('A6QL', **{'class': WD['TS6'][c['erd']]}))
    zero = A3.zero_clause(source, info['class'], row.get('interval_family_one_day'))
    require(bool(zero) == bool(c['zero']), 'K6.6 zero clause differs from the A4 record for ' + row['arm'])
    if c['cls'] == 'NULL':
        return form('A6H1', qualifiers=''.join('; ' + q for q in quals), **common), 'A6H1'
    if c['cls'] == 'DET':
        if c['robust'] == 'ROBUST':
            return form('A6H3', zero=zero, qualifiers=''.join('; ' + q for q in quals), **common), 'A6H3'
        three, _ = three_seed6(A4, source, info)
        return form('A6H3F', zero=zero, three_seed=three, qualifiers=''.join('; ' + q for q in quals), **common), 'A6H3F'
    pc = t['pc']
    if info.get('size_fail'):
        quals.append(form('A6PB_NEG', **A4.pc_fields_a4(source, pc)))
    bench, _ = combination6(A4, source, c)
    if c['robust'] == 'ROBUST':
        key = c['ic']
        if info.get('size_fail') and key in ('BEYOND', 'BELOW'):
            key += '_NC'
        position = form('A6S_' + key, S_phrase=A4.S_PHRASE[source], S=A3.SESOI[source], tail=A3.TAIL_TEXT[source])
        return form('A6H2', zero=zero, attribution=form('A6C1', activity=A3.ACTIVITY[source]), position=position, benchmark=bench,
                    qualifiers=''.join('; ' + q for q in quals), **common), 'A6H2'
    three, _ = three_seed6(A4, source, info)
    return form('A6H2F', zero=zero, three_seed=three, benchmark=bench, qualifiers=''.join('; ' + q for q in quals),
                test_note=F6['A6FT_F'] if c['robust'] == 'FRAGILE' else F6['A6FT_N'], **common), 'A6H2F'


def increment_readings6(A4, source, c, t, arm_name):
    """A6CS/A4CSX and A6CHS beside an increment (A6SEED when it is not inferentially robust)."""
    A2, A3 = A4.A2, A4.A3
    info, row = c['info'], c['row']
    seed = '' if robust_inc(c) else F6['A6SEED']
    out = []
    if row['arm'] == A2.CONTENT_ARM[source]:
        shift = t.get('shift') or {}
        if shift.get('state') == 'COMPUTED':
            d = A4.decimals(shift.get('interval95'))
            lo, hi = A2.fmt_interval(shift.get('interval95'), d)
            days = A4.SENTENCES['A4CS_DAYS'].format(n=shift['days']) if source == 'notice' and shift.get('days') else ''
            out.append((form('A6CS', arm=arm_name, se=A4.sfmt(shift.get('effect'), d), lo=lo, hi=hi, p=A2.display_p(shift.get('p_two_sided')), days=days, seed=seed,
                             **{'class': WD['CS6'][cmap(A4, shift['class'])]}), 'A6CS'))
        else:
            out.append((A4.SENTENCES['A4CSX'].format(arm=arm_name, reason=A4.reason_phrase(shift.get('state'))), 'A4CSX'))
    cheap = (info.get('attribution') or {}).get('cheap_text')
    if cheap:
        computed, unavailable = cheap.get('computed') or {}, cheap.get('unavailable') or []
        pieces = [form({'beaten': 'A6CH_BEATEN', 'not_beaten': 'A6CH_NOT', 'worse': 'A6CH_WORSE'}[kind],
                       list=join(A2.COMPARATOR_NAME[k] for k, v in computed.items() if v == kind))
                  for kind in ('beaten', 'not_beaten', 'worse') if kind in computed.values()]
        text = join(pieces) if pieces else F6['A6CH_NONE']
        if unavailable:
            text += ('; ' if pieces else ', because ') + join(A2.COMPARATOR_NAME[k] for k in unavailable) + ' ' + A3.was_were(unavailable) + ' not available'
        out.append((form('A6CHS', documents=A2.DOCUMENTS[source], seed=seed, arm=arm_name, cheap_list=text,
                         cheap_reading=F6['A6CHR_' + cheap_reading(cheap)]), 'A6CHS'))
    return out


def section62(A4, F5, source, t, rt, pointer):
    """Section 6.2 sentence list of one task: [(form key, plain text)] in A6 S62 order (`t` A4 record, `rt` RS6 task)."""
    A2, A3 = A4.A2, A4.A3
    if t['scenario'] == 'INCOMPLETE':
        return [('A3H6', A3.SENTENCES['A3H6'].format(task_label=A3.TASK_LABEL[source], reason=t['incomplete_reason']))]
    out = [('A4CLK', A4.SENTENCES['A4CLK'])] if source == 'notice' else []
    for c in rt['contrasts']:
        text, key = contrast_sentence6(A4, source, c, t)
        out.append((key, text))
        if c['cls'] == 'IMP':
            out += [(k, s) for s, k in increment_readings6(A4, source, c, t, c['row']['arm'])]
    out.append(('A3C7', A3.SENTENCES['A3C7']) if source == 'notice' else ('MATCHED', t['matched_sentence']))
    mn = t['mn']
    if mn.get('state') == 'COMPUTED':
        d = A4.decimals(mn.get('interval95'))
        lo, hi = A2.fmt_interval(mn.get('interval95'), d)
        out.append(('A6MN6', form('A6MN6', activity_words=A4.ACTIVITY_WORDS[source], se=A4.sfmt(mn.get('effect'), d), aud=A3.aud(mn.get('mean_difference')),
                                  lower_higher='lower' if (mn.get('mean_difference') or 0) < 0 else 'higher', lo=lo, hi=hi,
                                  p=A2.display_p(mn.get('p_two_sided')), **{'class': WD['CS6'][cmap(A4, mn['class'])]})))
    else:
        out.append(('A4MNX', A4.SENTENCES['A4MNX'].format(activity_words=A4.ACTIVITY_WORDS[source], reason=A4.reason_phrase(mn.get('state')))))
    pc = t['pc']
    nc = pc['state'] in ('SIZE_FAILS', 'BOTH_FAIL')
    sens = pc['state'] in ('SENSITIVITY_FAILS', 'BOTH_FAIL')
    if t['scenario'] == 'A' and t['bound'] is not None:
        X, d, seven_missing, mc = t['bound']
        S = A3.SESOI[source]
        key = 'A6H5_NC' if nc else 'A6H5'
        out.append((key, form(key, X=A2.branch_safe_bound(X, d, S), tail=A3.TAIL_TEXT[source], below_or_above='below' if X < S else 'at or above',
                              S_phrase=A4.S_PHRASE[source], env=F6['A6ENV'] if seven_missing else '',
                              mc=form('A6MC', S_phrase=A4.S_PHRASE[source]) if mc else '', sens=F6['A6H5_SENS'] if sens else '')))
        out.append(('A6BD', form('A6BD', table_ref='{table_ref}')))
        if mn.get('state') == 'COMPUTED':
            mr = cmap(A4, mn.get('class'))
            out.append({'IMP': ('A6MNR_IMP', F6['A6MNR_IMP']), 'NULL': ('A4MNR_NULLb', A4.SENTENCES['A4MNR_NULLb']), 'DET': ('A6MNR_DET', F6['A6MNR_DET'])}[mr])
        if source == 'news':
            out.append(('A6N2', form('A6N2', this_bound=WD['THIS_BOUND']['nc' if nc else 'normal'], mde_cmp=A3.mde_cmp(X, source), hist_cmp=A4.hist_cmp_news(X))))
            if A4.g1_sentence_a4(t['tvn']):
                out.append(('A5G1_MAIN', F5['A5G1_MAIN']))
        else:
            out.append(('A6M1', form('A6M1', nominal=WD['NOMINAL']['nc' if nc else 'normal'], task_label=A3.TASK_LABEL[source],
                                     X=A2.branch_safe_bound(X, d, A3.MDE_PERCENT[source]), mde_cmp=A3.mde_cmp(X, source), mde=A3.MDE_PERCENT[source])))
            out.append(('A3N1', A3.SENTENCES['A3N1'].format(hist_cmp=A3.hist_cmp(X))))
    if source == 'news':
        lear = t.get('lear') or {}
        if lear.get('state') == 'COMPUTED':
            d = A4.decimals(lear.get('interval95'))
            eff = lear.get('effect')
            out.append(('A6LEAR_MAIN', form('A6LEAR_MAIN', abs=A2.fmt_effect(abs(eff), d), lower_higher='lower' if eff < 0 else 'higher',
                                            **{'class': WD['CS6'][cmap(A4, lear['class'])]})))
        else:
            out.append(('A4LEARX', A4.SENTENCES['A4LEARX'].format(reason=A4.reason_phrase(lear.get('state')))))
    if pointer:
        out.append(('A5PC_PTR', F5['A5PC_PTR']))
    conseq = 0
    if pc['state'] == 'NOT_RUN':
        out.append(('A3PS_NOTRUN', A3.SENTENCES['A3PS_NOTRUN'].format(task_label=A3.TASK_LABEL[source], reason=pc['reason'])))
        conseq += 1
    else:
        f = A4.pc_fields_a4(source, pc)
        if t['scenario'] == 'A':
            if sens:
                out.append(('A6PS_SENS', form('A6PS_SENS', **f)))
            if nc:
                out.append(('A6PS_NEG', form('A6PS_NEG', **f)))
        else:
            if sens:
                out.append(('A6PS_SENSB', form('A6PS_SENSB', **f)))
            out.append(('A6PS_NEGB', form('A6PS_NEGB', **f)) if nc else ('A4PB_DIAG', A4.SENTENCES['A4PB_DIAG'].format(**f)))
        if pc.get('attenuates'):
            out.append(('A3PS_ATT', A3.SENTENCES['A3PS_ATT'].format(task_label=A3.TASK_LABEL[source])))
        conseq = int(sens) + int(nc) + int(t['scenario'] == 'B') + int(bool(pc.get('attenuates')))
        if sens or nc:
            out.append(('A6ALERT_S', form('A6ALERT_S', task_label=A3.TASK_LABEL[source])))
        if t['scenario'] == 'A' and pc['state'] == 'PASS' and not conseq:
            out.append(('A5PC_PASS', F5['A5PC_PASS'].format(task_label=A3.TASK_LABEL[source])))
    return out


def batch_qualifiers6(A4, rows, batch):
    """A6Q1S/A6Q2S (A3 batch_sentences logic with the A6 forms)."""
    A2, A3 = A4.A2, A4.A3
    out = []
    pcls = {(r['arm'], r['reference']): r for r in rows}
    for fam, key in (('l1_family', 'A6Q1S'), ('pd_family', 'A6Q2S')):
        rep = ((batch or {}).get('families') or {}).get(A3.BATCH_FAMILY_KEY[fam])
        if not rep or rep.get('state') != 'COMPUTED':
            continue
        by = {(r['arm'], r['reference']): r for r in rep['reports']}
        for pair, bpair in A3.BATCH_PAIRS[fam].items():
            r, p = by.get(bpair), pcls.get(pair)
            if r is None or p is None:
                continue
            bcls = A2.decision_class(r.get('mean_difference'), r.get('holm_p'))
            if bcls in A3.CLASSES and p.get('decision') in A3.CLASSES and bcls != p['decision']:
                one = (r.get('bootstrap') or {}).get('1', {})
                d = A2.percent_decimals(None if not one.get('interval95_percent') else one['interval95_percent'][1] - one['interval95_percent'][0])
                lo, hi = A2.fmt_interval(one.get('interval_family_adjusted_percent'), d)
                out.append((key, form(key, arm_words=A3.ARM_WORDS['news'][pair[0]], effect=A2.fmt_effect(r.get('effect_percent_reference_mae', one.get('effect_percent_reference_mae')), d),
                                      lo=lo, hi=hi, p=A2.display_p(r.get('holm_p')), **{'class': WD['TS6'][cmap(A4, bcls)]})))
    return out


def layer2_sentence6(A4, source, states):
    """A3R5a or A6R5b over A3's layer-2 sensitivities (A3 layer2_sentence logic, A6 forms and words)."""
    A3 = A4.A3
    dissent, available, unavailable = [], [], []
    for name in A3.SENSITIVITY_ORDER[source]:
        rows = [(pair, (st.get(name) or {'state': 'NOT_APPLICABLE'})) for pair, st in states.items()]
        rows = [(pair, s) for pair, s in rows if s['state'] != 'NOT_APPLICABLE']
        if not rows:
            continue
        if all(s['state'] == 'NOT_AVAILABLE' for _, s in rows):
            unavailable.append(A3.SENSITIVITY_NAMES[name])
            continue
        available.append(A3.SENSITIVITY_NAMES[name])
        for pair, s in rows:
            if s['state'] == 'DIFFERENT':
                dissent.append(form('A6R5b_ITEM', arm=pair.split('-')[0], sensitivity=A3.SENSITIVITY_NAMES[name], **{'class': WD['TS6C'][cmap(A4, s['class'])]}))
    clause = ('; ' + join(unavailable) + ' ' + A3.was_were(unavailable) + ' not available') if unavailable else ''
    if dissent:
        return 'A6R5b', form('A6R5b', task_label=A3.TASK_LABEL[source], dissent_items='; '.join(dissent), unavailable_clause=clause)
    if not available:
        return 'A3R5a', None
    return 'A3R5a', A3.SENTENCES['A3R5a'].format(available_list=join(available), task_label=A3.TASK_LABEL[source], unavailable_clause=clause)


def section72(A4, rs, states_by_task):
    out = []
    A3 = A4.A3
    for source in SOURCES:
        rt = rs['tasks'][source]
        if rt['scenario'] == 'INCOMPLETE':
            continue
        cs = rt['contrasts']
        if cs and all(c['cls'] != 'NE' and c['robust'] == 'ROBUST' for c in cs):
            out.append(('A4R4', A4.SENTENCES['A4R4'].format(task_label=A3.TASK_LABEL[source])))
        else:
            items = []
            for c in cs:
                if c['cls'] == 'NE':
                    lab = WD['R4F_LABEL']['NE']
                elif c['robust'] == 'FRAGILE':
                    lab = WD['R4F_LABEL']['FRAGILE_NFC' if c['unavailable'] else 'FRAGILE'].format(
                        dissent=join(WD['CHECK_SHORT'][k] for k in c['dissent']), unavailable=join(WD['CHECK_SHORT'][k] for k in c['unavailable']))
                elif c['robust'] == 'NOT_FULLY_CHECKED':
                    lab = WD['R4F_LABEL']['NOT_FULLY_CHECKED'].format(unavailable=join(WD['CHECK_SHORT'][k] for k in c['unavailable']))
                else:
                    lab = WD['R4F_LABEL']['ROBUST']
                items.append(form('A6R4F_ITEM', arm=c['row']['arm'], label=lab))
            out.append(('A6R4F', form('A6R4F', task_label=A3.TASK_LABEL[source], items=join(items))))
        key, s = layer2_sentence6(A4, source, states_by_task.get(source) or {})
        if s:
            out.append((key, s))
    out.append(('A6R6', F6['A6R6']))
    return out


def conclusion6(A4, rs, records):
    """A6 CO: the conclusion core from RS6 (N0 task sentences with long arm names, then secondary, batch, LEAR, attribution,
    alert and caps)."""
    A3 = A4.A3
    out = []
    robinc = any_robust_increment(rs['tasks'])
    if robinc:
        out.append(('A6IVN', F6['A6IVN']))
    for s in SOURCES:
        out.append(('TASK_N0', task_sentence(s, rs['tasks'][s], RANK['N0'], conclusion=True)))
    for d in rs['extras']['diffs']:
        out.append(('A6Q1' if d['family'] == 'l1' else 'A6Q2', form('A6Q1' if d['family'] == 'l1' else 'A6Q2', arm_words=WD['ARM_WORDS'][d['arm']],
                                                                     se=d['se'], lo=d['lo'], hi=d['hi'], **{'class': WD['TS6'][d['cls']]})))
    for s in SOURCES:
        t = records['tasks'][s]
        for c in rs['tasks'][s]['contrasts']:
            if c['cls'] == 'IMP':
                out += [(k, x) for x, k in increment_readings6(A4, s, c, t, A3.ARM_WORDS[s][c['arm']])]
    out.append(('A3H0', A3.SENTENCES['A3H0']))
    out += [('A4NR/A4DEV', x) for x in A4.batch_texts(records['extras'].get('batch'))]
    out.append(('A6CO_Y', form('A6CO_Y', lear26=lear_tail(rs['extras'], RANK['N0']))))
    if robinc:
        out.append(('A6ATTR', F6['A6ATTR']))
    at = alert_tasks(rs['tasks'])
    if at:
        out.append(('A6ALERT', form('A6ALERT', tasks=at)))
    out += [('A4CAP', x) for x in A4.caps(records['tasks'], records['extras'])]
    return out


def lear_tvn6(A4, t_news):
    """Supplement S7 paragraph items: A6LEAR/A4LEARX and A6G1 (A5 L2-L3 placement kept)."""
    A2, A3 = A4.A2, A4.A3
    out = []
    lear = t_news.get('lear') or {}
    if lear.get('state') == 'COMPUTED':
        d = A4.decimals(lear.get('interval95'))
        lo, hi = A2.fmt_interval(lear.get('interval95'), d)
        eff = lear.get('effect')
        out.append(('A6LEAR', form('A6LEAR', abs=A2.fmt_effect(abs(eff), d), lower_higher='lower' if eff < 0 else 'higher',
                                   aud=A3.aud(lear.get('mean_difference')), lo=lo, hi=hi, p=A2.display_p(lear.get('p_two_sided')),
                                   **{'class': WD['CS6'][cmap(A4, lear['class'])]})))
    else:
        out.append(('A4LEARX', A4.SENTENCES['A4LEARX'].format(reason=A4.reason_phrase(lear.get('state')))))
    tvn = t_news.get('tvn') or {}
    vals = [tvn.get(f'{a}-{b}') or {} for a, b in A3.TEXT_VS_NO_TEXT]
    if all(v.get('state') == 'COMPUTED' for v in vals):
        f = {}
        for i, v in enumerate(vals, 1):
            d = A4.decimals(v.get('interval95'))
            lo, hi = A2.fmt_interval(v.get('interval95'), d)
            f.update({f'e{i}': A4.sfmt(v.get('effect'), d), f'l{i}': lo, f'h{i}': hi, f'c{i}': WD['CS6'][cmap(A4, v['class'])]})
        out.append(('A6G1', form('A6G1', table_ref='{table_ref}', **f)))
    return out


def table6_plain(A4, rs, source):
    """Table 6 word and bound cells of one task from RS6 (A6 T6): {arm: {reading, checks, dissent, envelope, seven, mc}}."""
    out = []
    for c in rs['tasks'][source].get('contrasts', []):
        cell = {'arm': c['arm'], 'reference': c['reference'], 'reading': WD['PRIMARY']['NE'], 'checks': 'not evaluable', 'dissent': '--',
                'envelope': '--', 'seven': False, 'mc': False}
        if c['cls'] != 'NE':
            info = c['info']
            env = info.get('envelope')
            if c['cls'] in ('NULL', 'DET') and env:
                cell['envelope'] = A4.A2.branch_safe_bound(env['U'], info['d'], A4.A2.SESOI[source])
                cell['seven'], cell['mc'] = bool(env.get('seven_missing')), bool(info.get('mc_flag'))
            key = c['cls'] + ('_ROBUST' if c['robust'] == 'ROBUST' else '_OTHER') if c['cls'] in ('IMP', 'DET') else c['cls']
            cell['reading'] = WD['PRIMARY'][key]
            parts = []
            if c['robust'] == 'ROBUST':
                parts.append(WD['TABLE6_CHECKS']['ROBUST'])
            if c['robust'] == 'FRAGILE':
                parts.append(WD['TABLE6_CHECKS']['FRAGILE'].format(dissent=join(WD['CHECK_SHORT'][k] for k in c['dissent'])))
            if c['unavailable']:
                parts.append(WD['TABLE6_CHECKS']['NOT_FULLY_CHECKED'].format(unavailable=join(WD['CHECK_SHORT'][k] for k in c['unavailable'])))
            cell['checks'] = '; '.join(parts)
            items = [f"{WD['SENS_TABLE6'][k]}: {WD['TABLE_CLASS_C'][c['layers'][k]]}" for k in LAYERS if c['layers'][k] in ('IMP', 'NULL', 'DET')]
            cell['dissent'] = '; '.join(items) if items else '--'
        out.append(cell)
    return out


def table7_plain(A4, ds, rows, source):
    """Table 7 cells of one task: {layer: [word per contrast]} (TABLE_CLASS_C for a differing class)."""
    words = {'SAME': 'same class', 'NOT_AVAILABLE': 'not available', 'NOT_APPLICABLE': '--'}
    out = {}
    for layer in LAYERS:
        cells = []
        for r in rows:
            st = (ds.get(f"{r['arm']}-{r['reference']}") or {}).get(layer) or {'state': 'NOT_APPLICABLE'}
            cells.append(WD['TABLE_CLASS_C'][cmap(A4, st['class'])] if st['state'] == 'DIFFERENT' else words.get(st['state'], st['state']))
        out[layer] = cells
    return out


def table8_plain(A4, t_news):
    """Table 8 (published gains) class words of this study's text-versus-no-text rows (CS_TABLE)."""
    tvn = t_news.get('tvn') or {}
    return {key: (WD['CS_TABLE'][cmap(A4, (tvn.get(key) or {}).get('class')) or 'NE'] if (tvn.get(key) or {}).get('state') == 'COMPUTED' else 'estimate not evaluable')
            for key in ('L_count-N', 'L_chen-N', 'M-N')}


def figure2_plain(rows_by_task, combos_by_task):
    """Figure 2 primary and combination rows: thick = family-adjusted one-day, thin = family-adjusted seven-day (A6 F2)."""
    out = []
    for source in SOURCES:
        for r in rows_by_task.get(source, []):
            out.append({'task': source, 'group': 'Primary', 'contrast': f"{r['arm']}-{r['reference']}", 'effect': r.get('effect_percent_reference_mae'),
                        'thick': r.get('interval_family_one_day'), 'thin': r.get('interval_family_seven_day'), 'thin_type': 'family-adjusted seven-day'})
        for c in combos_by_task.get(source, []):
            out.append({'task': source, 'group': 'Combination', 'contrast': f"{c['arm']}-{c['reference']}", 'effect': c.get('effect_percent_reference_mae'),
                        'thick': c['bootstrap']['1'].get('interval_family_adjusted_percent'), 'thin': (c['bootstrap'].get('7') or {}).get('interval_family_adjusted_percent'),
                        'thin_type': 'family-adjusted seven-day'})
    return out


# ============================================================================= md -> LaTeX for the complete addendum texts (A6 X7)
UNICODE_TEX = {'\u2013': '--', '\u2014': '---', '\u2032': "$'$", '\u2033': "$''$", '\u2026': '\\ldots{}', '\u2212': '$-$', '\u2264': '$\\le$',
               '\u2265': '$\\ge$', '\u00a7': '\\S{}', '\u2081': '$_1$', '\u2087': '$_7$', '\u0394': '$\\Delta$', '\u56db': '4', '\u516d': '6', '\u4e03': '7',
               '\u662f': 'shi (yes)', '\u5426': 'fou (no)', '\u2192': '$\\rightarrow$', '\u00d7': '$\\times$', '\u201c': '``', '\u201d': "''",
               '\u2018': '`', '\u2019': "'", '\u221a': '$\\surd$', '\u230a': '$\\lfloor$', '\u230b': '$\\rfloor$', '\u2308': '$\\lceil$', '\u2309': '$\\rceil$'}
TEX_SPECIAL = {'\\': '\\textbackslash{}', '&': '\\&', '%': '\\%', '$': '\\$', '#': '\\#', '_': '\\_', '{': '\\{', '}': '\\}',
               '~': '\\textasciitilde{}', '^': '\\textasciicircum{}'}


def tex_escape(text):
    out = []
    for ch in text:
        if ch in TEX_SPECIAL:
            out.append(TEX_SPECIAL[ch])
        elif ord(ch) > 127:
            require(ch in UNICODE_TEX, f'md_to_tex: unmapped character {ch!r} (U+{ord(ch):04X})')
            out.append(UNICODE_TEX[ch])
        else:
            out.append(ch)
    return ''.join(out)


def tex_inline(text):
    """Inline markdown (code spans, bold, italic) to LaTeX; everything else escaped."""
    parts = re.split(r'(`[^`]*`)', text)
    out = []
    for part in parts:
        if part.startswith('`') and part.endswith('`') and len(part) >= 2:
            out.append('\\texttt{' + tex_escape(part[1:-1]).replace('/', '/\\allowbreak ').replace('\\_', '\\_\\allowbreak ') + '}')
            continue
        t = tex_escape(part)
        t = re.sub(r'\*\*(.+?)\*\*', r'\\textbf{\1}', t)
        t = re.sub(r'(?<![\w*\\])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])', r'\\emph{\1}', t)
        out.append(t)
    return ''.join(out)


def md_to_tex(md, heading, label):
    """Mechanical conversion of a frozen addendum (headings, paragraphs, lists, tables, code blocks); content unchanged."""
    lines = md.split('\n')
    out = ['\\subsubsection{' + heading + '}\\label{' + label + '}', '']
    para, items, kind, table = [], [], None, []
    in_code = False

    def flush_para():
        if para:
            out.append(tex_inline(' '.join(s.strip() for s in para)))
            out.append('')
            para.clear()

    def flush_list():
        nonlocal kind
        if items:
            env = 'enumerate' if kind == 'enum' else 'itemize'
            out.append('\\begin{' + env + '}')
            for it in items:
                out.append('\\item ' + tex_inline(' '.join(s.strip() for s in it)))
            out.append('\\end{' + env + '}')
            out.append('')
            items.clear()
        kind = None

    def flush_table():
        if table:
            rows = [r for r in table if not re.fullmatch(r'\|?\s*:?-{2,}.*', r.strip())]
            cells = [[c.strip() for c in r.strip().strip('|').split('|')] for r in rows]
            n = max(len(c) for c in cells)
            w = '%.3f' % (0.96 / n)
            spec = '@{}' + ('>{\\raggedright\\arraybackslash}p{' + w + '\\linewidth}') * n + '@{}'
            out.append('{\\footnotesize\\setlength{\\tabcolsep}{3pt}')
            out.append('\\begin{longtable}{' + spec + '}')
            out.append('\\toprule')
            for k, c in enumerate(cells):
                c = c + [''] * (n - len(c))
                out.append(' & '.join(tex_inline(x) for x in c) + ' \\\\')
                if k == 0:
                    out.append('\\midrule')
            out.append('\\bottomrule')
            out.append('\\end{longtable}}')
            out.append('')
            table.clear()

    for line in lines:
        if line.startswith('```'):
            flush_para(); flush_list(); flush_table()
            if not in_code:
                out.append('\\begin{flushleft}\\ttfamily\\scriptsize')
                in_code = True
            else:
                out.append('\\end{flushleft}')
                out.append('')
                in_code = False
            continue
        if in_code:
            lead = len(line) - len(line.lstrip(' '))
            body = tex_escape(line.lstrip(' '))
            out.append(('\\hspace*{%.1fem}' % (0.5 * lead) if lead else '') + (body if body else '\\mbox{}') + '\\\\')
            continue
        s = line.rstrip()
        if not s.strip():
            flush_para(); flush_list(); flush_table()
            continue
        if s.startswith('|'):
            flush_para(); flush_list()
            table.append(s)
            continue
        flush_table()
        m = re.match(r'^(#{1,4})\s+(.*)$', s)
        if m:
            flush_para(); flush_list()
            out.append(('\\paragraph{' if len(m.group(1)) >= 2 else '\\paragraph*{') + tex_inline(m.group(2)) + '}')
            continue
        if re.fullmatch(r'-{3,}', s.strip()):
            flush_para(); flush_list()
            continue
        m = re.match(r'^\s*(?:[-*]|(\d+)\.)\s+(.*)$', s)
        if m:
            flush_para()
            k = 'enum' if m.group(1) else 'item'
            if kind not in (None, k):
                flush_list()
            kind = k
            items.append([m.group(2)])
            continue
        if items and line.startswith((' ', '\t')):
            items[-1].append(s)
            continue
        flush_list()
        para.append(s)
    flush_para(); flush_list(); flush_table()
    require(not in_code, 'md_to_tex: unterminated code block')
    return '\n'.join(out).rstrip('\n') + '\n'


# ============================================================================= stage-2 PREFILL (A6 X; SPEC 7)
def freeze_identities():
    """Identity paragraph for the fifth and sixth addenda (J-M), from the verified freeze records."""
    a5 = json.loads((A5DIR / 'ADDENDUM_A5_FREEZE.json').read_text())['files']
    a6 = json.loads((A6DIR / 'ADDENDUM_A6_FREEZE.json').read_text())['files']
    require(sha256(A5DIR / 'ADDENDUM_A5_FREEZE.json') == F3C.A5_FREEZE_SHA256, 'ADDENDUM_A5_FREEZE.json identity drift')
    hx = F3B.hexcode
    return ('Identity J (fifth addendum) is SHA-256 ' + hx(a5['ADDENDUM_A5.md']['sha256']) + ', identity K (its rule sheet) ' +
            hx(a5['RULES_FOR_FILL3C.json']['sha256']) + ', freeze record ' + hx(F3C.A5_FREEZE_SHA256) + '; identity L (sixth addendum) is ' +
            hx(a6['ADDENDUM_A6.md']['sha256']) + ', identity M (its rule sheet) ' + hx(a6['RULES_FOR_FILL3D.json']['sha256']) + ', freeze record ' +
            hx(A6_FREEZE_SHA256) + '. These are rule identities, not result hashes.')


def snapshot3d(manuscript, P):
    snap = manuscript / P['snapshot']
    manifest = json.loads((manuscript / P['snapshot_manifest']).read_text())
    index = {e['path']: e['sha256'] for e in manifest['entries']}
    require(manifest.get('fill3c_freeze_sha256') == FILL3C_FREEZE_SHA256, 'previous_fill3c manifest does not bind the FILL3c freeze')

    def read(rel):
        require(rel in index, f'{rel} is not in the previous_fill3c snapshot manifest')
        require(sha256(snap / rel) == index[rel], f'previous_fill3c snapshot drift: {rel}')
        return (snap / rel).read_text()
    return snap, index, read


def stage2_texts(manuscript, T, s1):
    """{rel: text} of every file stage 2 changes or creates (title switch, edits, new archive files, bibliography entries)."""
    deps()
    P = T['prefill3d']
    snap, index, read_snap = snapshot3d(manuscript, P)
    out = {}

    def cur(rel):
        if rel in out:
            return out[rel]
        return s1[rel] if rel in s1 else read_snap(rel)
    title = P['title']
    require(title['active'] in title['variants'], 'Unknown active title variant')
    old, new = title['variants']['current'], title['variants'][title['active']]
    for rel in title['files']:
        text = cur(rel)
        require(text.count(old) == 1, f'Title phrase must occur exactly once in {rel}')
        out[rel] = text.replace(old, new)
    subs = {'<<IDENT_A5A6>>': freeze_identities()}
    for e in P['edits']:
        text = cur(e['file'])
        require(text.count(e['old']) == 1, f"Stage-2 prefill anchor {e['id']} must occur exactly once in {e['file']}")
        rep = e['new']
        for k, v in subs.items():
            rep = rep.replace(k, v)
        require('<<' not in rep, f"Unresolved placeholder in stage-2 edit {e['id']}")
        out[e['file']] = text.replace(e['old'], rep)
    for rel, spec in P['new_files'].items():
        require(rel not in index and rel not in s1 and not (snap / rel).exists(), f'Stage-2 new file already exists: {rel}')
        src = PROJ / spec['from']
        require(sha256(src) == spec['sha256'], f'Frozen addendum text drift: {spec["from"]}')
        out[rel] = md_to_tex(src.read_text(), spec['heading'], spec['label'])
    for rel, entries in P['bib_append'].items():
        text = cur(rel)
        added = [entry for key, entry in entries if F3B.bib_entry(text, key) is None]
        if added:
            out[rel] = text.rstrip('\n') + '\n\n' + '\n\n'.join(added) + '\n'
    return out


def stage2_trace(manuscript, T, s1, s2):
    """Trace rows for every numeric token on a changed, new or shifted line of a stage-2 .tex file (FILL3b's rule, stage 1 as the base)."""
    F3A_ = F3B.F3A
    P = T['prefill3d']
    snap, index, read_snap = snapshot3d(manuscript, P)
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
            return {'location': new_loc, 'number': token, 'source_file': 'manuscript_tex/' + P['snapshot'] + '/' + old_loc.rsplit(':', 1)[0],
                    'source_field': f"line {old_loc.rsplit(':', 1)[1]}; preserved literal {token}", 'note': PREFILL_NOTE3D + '; ' + note}
        return {'location': new_loc, 'number': token, 'source_file': r['source_file'], 'source_field': r['source_field'],
                'note': PREFILL_NOTE3D + '; ' + note + '; original note: ' + r['note'][:160]}

    for rel, text in sorted(s2.items()):
        if not rel.endswith('.tex'):
            continue
        old_lines = (s1[rel] if rel in s1 else (read_snap(rel) if rel in index else '')).split('\n') if (rel in s1 or rel in index) else []
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
                        rows.append({'location': new_loc, 'number': tok, 'source_file': src, 'source_field': f, 'note': PREFILL_NOTE3D + '; frozen rule or fact value'})
                    elif tok in old_toks:
                        rows.append(carry(f'{rel}:{i + 1}', tok, new_loc, 'value unchanged on an edited line'))
                    elif rel in file_sources:
                        src, f = file_sources[rel]
                        rows.append({'location': new_loc, 'number': tok, 'source_file': src, 'source_field': f, 'note': PREFILL_NOTE3D + '; fixed text value'})
                    else:
                        unresolved.append(f'{rel}:{j + 1} {tok}')
    require(not unresolved, 'Stage-2 prefill numbers without a trace origin: ' + '; '.join(unresolved[:20]))
    for r in rows:
        for source in r['source_file'].split(';'):
            source = source.strip()
            if source:
                require((Path(source) if Path(source).is_absolute() else PROJ / source).exists(), 'Stage-2 prefill trace source missing: ' + source)
    unique, seen = [], set()
    for r in rows:
        key = tuple(r[k] for k in ('location', 'number', 'source_file', 'source_field', 'note'))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def prefill3d_outputs(manuscript, T, coverage):
    """Stage 1 (FILL3b's PREFILL, unchanged) and stage 2 (A6 X); returns (outputs, stage-1 outputs, stage-2 texts, stage-2 rows)."""
    deps()
    s1, _ = F3B.prefill_outputs(manuscript, T, coverage)
    s1_texts = {rel: text for rel, text in s1.items() if not rel.endswith('.csv')}
    s2 = stage2_texts(manuscript, T, s1_texts)
    rows = stage2_trace(manuscript, T, s1_texts, s2)
    header = ['location', 'number', 'source_file', 'source_field', 'note']
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header, lineterminator='\r\n')
    w.writeheader()
    w.writerows(rows)
    out = dict(s1)
    out.update(s2)
    out[PREFILL_TRACE3D] = buf.getvalue()
    out['MS15_TRACE.csv'] = s1['MS15_TRACE.csv'] + ''.join(buf.getvalue().splitlines(keepends=True)[1:])
    return out, s1, s2, rows


def write_prefill3d(manuscript, coverage, check_only=False):
    F3B_ = deps()
    T = F3B_.templates()
    outputs, s1, s2, rows = prefill3d_outputs(manuscript, T, coverage)
    if check_only:
        diffs = [rel for rel, text in outputs.items() if not (manuscript / rel).is_file() or (manuscript / rel).read_bytes() != text.encode()]
        return {'state': 'PREFILL_EQUAL' if not diffs else 'PREFILL_DIFFERS', 'differs': diffs, 'trace_rows': len(rows), 'stage2_files': sorted(s2)}
    problems, reachable = F3B_.prefill_scan(manuscript, outputs, T)
    require(not problems, 'Prefill text check failed: ' + '; '.join(problems[:12]))
    P = T['prefill3d']
    _, index3c, _ = snapshot3d(manuscript, P)
    manifest3a = json.loads((manuscript / T['prefill.snapshot_manifest']).read_text())
    index3a = {e['path']: e['sha256'] for e in manifest3a['entries']}
    last = {}
    for name in ('qa/FILL3B_PREFILL_RECEIPT.json', 'qa/FILL3C_PREFILL_RECEIPT.json', PREFILL_RECEIPT):
        if (manuscript / name).is_file():
            for rel, digest in json.loads((manuscript / name).read_text()).get('outputs_sha256', {}).items():
                last.setdefault(rel, set()).add(digest)
    for rel, text in outputs.items():
        path = manuscript / rel
        if path.exists():
            live = sha256(path)
            require(live in {hashlib.sha256(text.encode()).hexdigest(), index3c.get(rel), index3a.get(rel)} | last.get(rel, set()),
                    f'{rel} differs from its previous_fill3c snapshot, from the last FILL3b/FILL3c/FILL3d PREFILL and from this PREFILL; the prefill refuses to overwrite it')
    written = {}
    for rel, text in outputs.items():
        path = manuscript / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
        written[rel] = sha256(path)
    receipt = {'state': 'FILL3D_PREFILL_WRITTEN', 'utc': datetime.now(timezone.utc).isoformat(), 'script_sha256': sha256(Path(__file__)),
               'fill3b_generator_sha256': sha256(MS / 'fill3b_conf_results.py'), 'templates_sha256': sha256(MS / TEMPLATES_NAME),
               'a6_freeze_sha256': A6_FREEZE_SHA256, 'coverage': {'path': str(coverage.path), 'sha256': coverage.sha256},
               'title_variant': T['prefill3d.title.active'], 'stage1_files': sorted(rel for rel in s1 if not rel.endswith('.csv')),
               'stage2_edits': [e['id'] for e in P['edits']], 'stage2_new_files': sorted(P['new_files']), 'stage2_files': sorted(s2),
               'stage2_trace_rows': len(rows), 'reachable_sources_scanned': len(reachable), 'outputs_sha256': written,
               'note': 'stage 1 is the FILL3b PREFILL (FILL3b generator reused read-only, identical prefill block); stage 2 is CONF-A6 section X'}
    (manuscript / PREFILL_RECEIPT).parent.mkdir(parents=True, exist_ok=True)
    (manuscript / PREFILL_RECEIPT).write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


# ============================================================================= wrapped FILL3c/FILL3b gates
class Timestamps3d:
    """FILL3c's timestamp gate (FILL3b's list with FILL3d's freeze name, plus the A5 freeze), plus the A6 freeze in a T5-or-later manifest."""

    def __new__(cls, root, receipt_path, coverage, freeze_name, pcx_freeze=None):
        ts = ORIG['Timestamps'](root, receipt_path, coverage, freeze_name, pcx_freeze)
        listed = set()
        for name, entry in ts.labels.items():
            if int(re.match(r'T(\d+)', name).group(1)) < 5:
                continue
            for line in entry['manifest'].read_text().splitlines():
                if line.startswith('#') or not line.strip():
                    continue
                digest, _, path = line.split(None, 2)
                if path.strip().endswith('ADDENDUM_A6_FREEZE.json'):
                    listed.add(digest)
        require(sha256(A6DIR / 'ADDENDUM_A6_FREEZE.json') in listed, 'T5 (or later) manifest does not cover the current ADDENDUM_A6_FREEZE.json')
        return ts


def host_edits3d(r, reader, states):
    """FILL3c's slot edits with FILL3d comment texts and the A6 abstract comment."""
    out = []
    for sid, rel, old, new in ORIG['host_edits'](r, reader, states):
        if sid == 'abstract-marker':
            new = r.T3['a6.abstract_marker']
        elif new.lstrip().startswith('%') and '\n' not in new.strip():
            new = new.replace('fill3c_conf_results.py', 'fill3d_conf_results.py').replace('fill3b_conf_results.py', 'fill3d_conf_results.py')
        out.append((sid, rel, old, new))
    return out


def prefill_equality3d(manuscript, reader, T, coverage, slot_files):
    """K6.8: every host file of the fill and every stage-2 file equals the FILL3d PREFILL (stage 2, else stage 1, else the snapshot)."""
    outputs, s1, s2, _ = prefill3d_outputs(manuscript, T, coverage)
    snap = manuscript / T['prefill.snapshot']
    checked = []
    for rel in sorted(set(slot_files) | {r for r in outputs if r.endswith('.tex')}):
        expected = outputs[rel] if rel in outputs else ((snap / rel).read_text() if (snap / rel).is_file() else None)
        require(expected is not None, f'No prefill or snapshot text for {rel}')
        live = reader(rel) if rel in slot_files else (manuscript / rel).read_text()
        require(live == expected, f'PREFILL_DRIFT: {rel} differs from the FILL3d prefill generated from the frozen templates')
        checked.append(rel)
    return checked


# ============================================================================= renderer (FILL3c's class subclassed; A6 sections)
def renderer_class3d(F3A_, F3, F2, A4):
    Base = F3C.renderer_class3c(F3A_, F3, F2, A4)
    IMP, DET, NULL = A4.IMP, A4.DET, A4.NULL
    PW, PR = F3B.PW, F3B.PR
    TAG = F3B.TAG
    A4CODE = F3B.A4_CODE_REL

    class Fill3d(Base):
        def setup3b(self, a4post, coverage, pcx_info, conf_review, agreement, pair_tables):
            Base.setup3b(self, a4post, coverage, pcx_info, conf_review, agreement, pair_tables)
            ds = {}
            for s in SOURCES:
                ds[s] = self.a3post.task(s).get('design_sensitivities') or {}
            self.ds6 = ds
            self.rs6 = build_rs6(A4, self.records, ds)
            self.a6_checks = Counter()
            self.a6_keys = {}

        # ------------------------------------------------------------------ helpers
        def fixed6(self, text, key, symbols=False):
            """A fixed A6 form or word list entry; numerals traced to the frozen A6 rule sheet."""
            parts = F3A_.a3_latex_parts(text, symbols)
            tex = ''.join(self.R(p[1], A6_RULES_REL, key, 'fixed numeral of the frozen A6 form') if p[0] == 'num' else p[1] for p in parts)
            require(F3A_.flat(self.R.peek(tex)) == F3A_.flat(text), f'A6 fixed text {key} conversion differs')
            self.a6_checks['A6 fixed texts'] += 1
            return tex

        def a6t(self, key, **values):
            """An A6 LaTeX template with <<placeholders>>; fixed segments with numerals registered to the rule sheet."""
            template = TP[key]
            parts = re.split(r'<<(\w+)>>', template)
            require(set(values) == set(parts[1::2]), f'A6 template {key} values differ from placeholders')
            out = []
            for i, part in enumerate(parts):
                if i % 2:
                    out.append(str(values[part]))
                elif part:
                    out.append(self.R(part, A6_RULES_REL, 'templates.' + key, 'fixed A6 template text') if F2.tokens(part) else part)
            return ''.join(out)

        def esc6(self, text, key):
            e = F2.esc(text)
            return self.R(e, A6_RULES_REL, key, 'fixed A6 word list entry') if F2.tokens(e) else e

        def sent6(self, key, text, field, symbols=True, table_ref=None):
            self.a6_keys[key] = self.a6_keys.get(key, 0) + 1
            return self.a4s(text, field + f' ({key})', symbols=symbols, table_ref=table_ref)

        # ------------------------------------------------------------------ abstract (RULE D-1)
        def abstract3b(self):
            rs = self.rs6
            res = ladder(rs['tasks'], rs['extras'])
            self.a4_abstract_level = self.a4['abstract']['level']
            self.k6 = check_abstract(rs, res['level'], res['text'])
            tex = self.a4s(res['text'], f"abstract (A6 level {res['level']}, from RS6 of the strict re-run)", symbols=False)
            words = F2.abstract_words(self.R.peek(tex))
            require(words == validator_words(res['text']), f"Rendered A6 abstract has {words} validator words, the plain text {validator_words(res['text'])}")
            require(words <= WORD_LIMIT, f'ABSTRACT_OVER_250: {words} validator words (A6 K6.1, never waived)')
            self.abstract_level, self.abstract_counts, self.abstract_over_limit = res['level'], res['counts'], False
            self.abstract_words_final = words
            self.a5_level_used = False
            self.abstract_plain = res['text']
            self.k5 = {'superseded_by': 'A6 K6', **self.k6}
            return tex

        # ------------------------------------------------------------------ section 6.2 (RULE D-2)
        def task_sentences_a4(self, source):
            t = self.records['tasks'][source]
            rt = self.rs6['tasks'][source]
            pc_any = any((self.a4['tasks'][s].get('positive_control') or {}).get('state', 'NOT_RUN') != 'NOT_RUN' for s in SOURCES)
            pointer = False
            if pc_any and not self.p1_done and t['scenario'] != 'INCOMPLETE':
                pointer, self.p1_done = True, True
            items = section62(A4, F3C.F, source, t, rt, pointer)
            alerts = sum(1 for k, _ in items if k == 'A6ALERT_S')
            require(alerts == (1 if task_alert(rt) else 0), f'K6.5 {source}: {alerts} alert sentences in section 6.2')
            self.s62_plain = getattr(self, 's62_plain', {})
            self.s62_plain[source] = items
            parts = []
            for i, (key, s) in enumerate(items):
                ref = '\\ref{tab:ms14-published-gains}' if key == 'A5G1_MAIN' else ('\\ref{tab:fill3b-primary}' if key == 'A6BD' else None)
                parts.append(self.sent6(key, s, f'rs6.{source}.section6_2[{i}]', table_ref=ref))
            return parts

        def primary_section(self):
            self.p1_done = False
            return Base.primary_section(self)

        def primary_table3b(self):
            rows, marks = [], {'seven': False, 'mc': False}
            for source in SOURCES:
                d = self.task_decimals(source)
                cells6 = table6_plain(A4, self.rs6, source)
                for i, (c, r) in enumerate(zip(self.primary[source], self.a2[source]['primary'])):
                    base = f'tasks.{source}.primary[{i}]'
                    eff = self.num(self.A2.fmt_effect(r.get('effect_percent_reference_mae'), d), base + '.effect_percent_reference_mae', f'{d} decimals (task column rule)')
                    cell = cells6[i] if i < len(cells6) else None
                    require(cell is None or (cell['arm'], cell['reference']) == (c.arm, c.ref), 'K6.6 Table 6 row order differs from RS6')
                    env_cell, reading, checks, dissent = '--', 'not evaluable', 'not evaluable', '--'
                    if cell is not None:
                        if cell['envelope'] != '--':
                            env_cell = self.R(cell['envelope'], self.a4post.src, f'{base} envelope U (A4 amendment 2 G3)', 'U = max(0, -l1, -l7) of the family-adjusted one-day and seven-day intervals; A2 branch_safe_bound')
                            if cell['seven']:
                                env_cell += '$^{a}$'
                                marks['seven'] = True
                            if cell['mc']:
                                env_cell += '$^{b}$'
                                marks['mc'] = True
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
            cap = self.a6t('table6_caption', marks=mark_tex, table_ref='\\ref{tab:fill3b-sensitivity}')
            spec = '@{}' + PW('.107') + PR('.112') + PR('.075') + PW('.082') + PR('.077') + PR('.07') + PW('.085') + PW('.11') + PW('.125') + '@{}'
            head = self.a6t('table6_header')
            return ('\\begin{table}[htbp]\\centering\\scriptsize\\setlength{\\tabcolsep}{' + self.layout('2pt') + '}\n\\caption{' + cap + '}\\label{tab:fill3b-primary}\n'
                    '\\begin{tabular}{' + spec + '}\\toprule\n' + head + '\n\\midrule\n' + '\n'.join(rows) + '\n\\bottomrule\\end{tabular}\\end{table}\n')

        # ------------------------------------------------------------------ section 6.3 (RULE D-5)
        def e3_line3b(self):
            state = self.report['notice'].get('e3_joint_state', 'E3_SECONDARY_JOINT_NOT_EVALUABLE')
            if state == 'E3_SECONDARY_JOINT_CONFIRMED':
                return 'Under the frozen joint rule, ' + self.fixed6(F6['A6E3C'], 'forms.A6E3C') + ' (Supplement~S7).'
            return Base.e3_line3b(self)

        def batch_text3b(self):
            if self.batch is None:
                return self.t3b('secondary.batch_pending')
            out = []
            for k, (key, s) in enumerate(batch_qualifiers6(A4, self.a2['news']['primary'], self.batch.data)):
                out.append(self.sent6(key, s, f'rs6.news.section6_3.batch[{k}]'))
            t = self.a3post.texts('news')
            for k, s in enumerate(t['section6']):
                if s.startswith('The primary increment of '):
                    out.append(self.a3s(s, f'tasks.news.texts.section6[{k}]'))
            for s, field in self.a4_batch_texts():
                out.append(self.a4s(s, field, symbols=False))
            out.append(self.a3fixed(self.A3.SENTENCES['A3R_BATCH'], 'A3R_BATCH'))
            return ' '.join(out)

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
                        word = WD['TABLE_CLASS_C'][cmap(A4, st['class'])]
                    cells.append(F2.esc(word))
                label = self.R(F2.esc(label), F3B.TEMPLATES_REL, 'sens_table.' + key, 'fixed FILL3d template text') if F2.tokens(label) else F2.esc(label)
                rows.append(' & '.join([label] + cells) + r' \\')
            w = '%.2f' % (0.74 / max(1, len(cols)))
            spec = '@{}' + PW('.14') + PW(w) * len(cols) + '@{}'
            return ('\\begin{table}[htbp]\\centering\\footnotesize\\setlength{\\tabcolsep}{' + self.layout('3pt') + '}\n\\caption{' + self.t3b('secondary.sens_caption') + '}\\label{tab:fill3b-sensitivity}\n'
                    '\\begin{tabular}{' + spec + '}\\toprule\n' + head + '\n\\midrule\n' + '\n'.join(rows) + '\n\\bottomrule\\end{tabular}\\end{table}\n')

        # ------------------------------------------------------------------ section 7.2 and conclusion (RULES D-6, D-7)
        def discussion_section(self):
            out = [self.t3b('discussion.heading')]
            states = {}
            for s in SOURCES:
                rows = self.a2[s]['primary']
                ds = self.a3post.task(s).get('design_sensitivities') or {}
                states[s] = {f"{r['arm']}-{r['reference']}": ds.get(f"{r['arm']}-{r['reference']}", {}) for r in rows}
            items = section72(A4, self.rs6, states)
            self.s72_plain = items
            sentences = [self.sent6(key, s, f'rs6.section7_2[{k}]') for k, (key, s) in enumerate(items)]
            sentences.append(self.t3b('discussion.closing'))
            out.append(' '.join(sentences))
            return '\n'.join(out) + '\n'

        def conclusion(self):
            items = conclusion6(A4, self.rs6, self.records)
            self.conclusion_plain = items
            return ' '.join(self.sent6(key, s, f'rs6.conclusion[{k}]', symbols=False) for k, (key, s) in enumerate(items)) + '\n'

        # ------------------------------------------------------------------ supplement S7 block (RULE D-8)
        def lear_tvn_paragraph(self):
            items = lear_tvn6(A4, self.records['tasks']['news'])
            num = self.T3['a5.published_gains_table_number']
            out = []
            for i, (key, s) in enumerate(items):
                ref = None
                if '{table_ref}' in s:
                    tex = self.R(num, F3B.TEMPLATES_REL, 'a5.published_gains_table_number', 'main-article number of tab:ms14-published-gains (checked against main.aux)')
                    ref = (tex + ' of the main article', num + ' of the main article')
                out.append(self.sent6(key, s, f'rs6.news.supplement_lear_tvn[{i}]', symbols=False, table_ref=ref))
            return (self.T3['a5.supp_lear_tvn_heading'] + ' ' + ' '.join(out)) if out else ''

        def supplement_block3b(self):
            S = 'supplement_block.'
            out = [self.t3b(S + 'heading'), self.t3b(S + 'intro'), '', self.t3b(S + 'primary_heading'), self.t3b(S + 'primary_text')]
            out.append(self.supp_primary_tables3b())
            out.append('')
            out.append(self.t3b(S + 'attribution_text'))
            out.append(self.t3b(S + 'secondary_heading'))
            out.append(self.t3b(S + 'secondary_text'))
            out.append(self.combination_table3b())
            out.append(self.cheap_table3b())
            for source in SOURCES:
                out.append(self.all_secondary_table3b(source))
            para = self.lear_tvn_paragraph()
            if para:
                out.append(para)
                out.append('')
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
            text = Base.supp_primary_tables3b(self)
            for cls in (IMP, NULL, DET):
                old = F2.esc(A4.TS_WORDS.get(cls))
                new = F2.esc(WD['TABLE_CLASS_C'][cmap(A4, cls)])
                text = text.replace('$]$, ' + old + ' &', '$]$, ' + new + ' &')
            require(not re.search(r'\$\]\$, (?:a reliable increment|a reliable deterioration) &', text), 'K6.4 three-seed class words not gated in the seeds table')
            return text

        def combination_table3b(self):
            text = Base.combination_table3b(self)
            out = []
            for line in text.split('\n'):
                if line.rstrip().endswith(r'\\') and ' & ' in line:
                    cells = line.rstrip()[:-2].rstrip().split(' & ')
                    if len(cells) == 7 and cells[5] in {F2.esc(A4.TS_WORDS[k]) for k in (IMP, NULL, DET)}:
                        cls = {F2.esc(A4.TS_WORDS[k]): k for k in (IMP, NULL, DET)}[cells[5]]
                        cells[5] = F2.esc(WD['TABLE_CLASS_C'][cmap(A4, cls)])
                        line = ' & '.join(cells) + r' \\'
                out.append(line)
            return '\n'.join(out)

        def a3_report_cells_d(self, rep, base, d):
            cells = Base.a3_report_cells_d(self, rep, base, d)
            cls = self.A2.decision_class(rep.get('mean_difference'), rep.get('p_two_sided'))
            cells[-1] = F2.esc(WD['CS_TABLE'].get(cmap(A4, cls) or 'NE', 'not evaluable'))
            return cells

        def all_secondary_table3b(self, source):
            text = Base.all_secondary_table3b(self, source)
            out = []
            for line in text.split('\n'):
                for k in (IMP, NULL, DET):
                    old = ' & ' + F2.esc(A4.CS_WORDS[k]) + r' \\'
                    if line.endswith(old):
                        line = line[:-len(old)] + ' & ' + F2.esc(WD['CS_TABLE'][cmap(A4, k)]) + r' \\'
                if line.startswith(self.pair('W_Bai', 'M')):
                    cells = line[:-2].rstrip().split(' & ')
                    if len(cells) == 6 and cells[1:5] == ['--', '--', '--', '--']:
                        line = ' & '.join(cells[:1] + ['--', '--', '--', '--', self.esc6(F6['A6WBAI'], 'forms.A6WBAI')]) + r' \\'
                        self.a6_checks['W_Bai rows'] += 1
                out.append(line)
            return '\n'.join(out)

        def supp_sens_table3b(self):
            text = Base.supp_sens_table3b(self)
            for k in (IMP, NULL, DET):
                text = text.replace('; ' + F2.esc(A4.TS_WORDS[k]) + ' &', '; ' + F2.esc(WD['TABLE_CLASS_C'][cmap(A4, k)]) + ' &')
                text = text.replace('; ' + F2.esc(A4.TS_WORDS[k]) + r' \\', '; ' + F2.esc(WD['TABLE_CLASS_C'][cmap(A4, k)]) + r' \\')
            return text

        def subset_text(self):
            out = []
            news = self.a3post.task('news')
            for j in range(len(self.a2['news']['strictly_unexposed']['reports'])):
                out.append(self.u1('news', j))
            strict = self.a3post.task('notice')['strictly_unexposed_a3']
            ranges = join(f'{a} to {b}' for a, b in self.A2.STRICT_UNEXPOSED['notice'])
            for k, r in enumerate(strict['reports']):
                one = r['bootstrap']['1'].get('interval95_percent')
                d = self.A2.percent_decimals(None if one is None else one[1] - one[0])
                plain = form('A6U1N', n=strict['days'], ranges=ranges, arm=r['arm'], activity=self.A3.ACTIVITY['notice'],
                             effect=self.A2.fmt_effect(r.get('effect_percent_reference_mae'), d))
                out.append(self.a3s(plain, f'tasks.notice.strictly_unexposed_a3.reports[{k}] (A6U1N)'))
            for k, r in enumerate((news.get('readmission_free_subset') or {}).get('reports', [])):
                out.append(self.a3s(r['sentence'], f'tasks.news.readmission_free_subset.reports[{k}].sentence'))
            out.append(self.fixed6(F6['A6R6'], 'forms.A6R6'))
            return ' '.join(out)

        def pc_supplement3b(self):
            """FILL3b's planted-signal record with A6P1, A6P1N and the capacity sentence (A6 S62, D5)."""
            out = [self.fixed6(F6['A6P1'], 'forms.A6P1')]
            for k, s in self.pick_a4('news', 'A4P0'):
                out.append(self.a4s(s, f'tasks.news.section6[{k}]', symbols=False))
            if self.pick_a4('news', 'A4P1N'):
                n1 = self.records['tasks']['news']['pc'].get('n1_agrees')
                plain = form('A6P1N', n1=A4.N1_WORDS[0] if n1 is True else (A4.N1_WORDS[1] if n1 is False else A4.N1_WORDS[2]))
                out.append(self.sent6('A6P1N', plain, 'rs6.news.planted_signal', symbols=False))
            for source in SOURCES:
                for key in ('A4P1T', 'A4PX_RUN2', 'A4PX_NOT2'):
                    for k, s in self.pick_a4(source, key):
                        out.append(self.a4s(s, f'tasks.{source}.section6[{k}]', symbols=False))
            out.append('Table~\\ref{supp:tab:fill3b-pc} gives every strength.')
            caps = [r for r in self.pc.data['summary'] if r['tier'] == 'CAP']
            out.append(self.fixed6(F6['A6CAP'] if caps else F6['A6CAPX'], 'forms.A6CAP' if caps else 'forms.A6CAPX'))
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
                                        self.R(f"{r['uptake_median']:.3f}", src, field + '.uptake_median', '3 decimals') if F3B.finite(r.get('uptake_median')) else '--']) + r' \\')
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

        def label_paragraph3a(self):
            """FILL3a's label paragraph with gated reading words (A6 G): the primary class by its robustness, the replacement class in TS6 words."""
            if self.label is None or not self.label.scored:
                return Base.label_paragraph3a(self)
            out = []
            for source in SOURCES:
                cs = self.rs6['tasks'][source].get('contrasts', [])
                for i, r in enumerate(self.a2[source]['primary']):
                    st = self.a3post.task(source)['design_sensitivities'][f"{r['arm']}-{r['reference']}"]['label_replacement']
                    rep = self.label.data['families'][source]['reports'][i]
                    require((rep['arm'], rep['reference']) == (r['arm'], r['reference']), 'A2LABEL family order differs')
                    one = rep['bootstrap']['1'].get('interval95_percent')
                    d = self.decimals(one)
                    base = f'families.{source}.reports[{i}]'
                    e_txt = self.A2.fmt_effect(rep.get('effect_percent_reference_mae'), d)
                    lo, hi = self.A2.fmt_interval(one, d)
                    latex = dict(effect=self.num(e_txt, base + '.effect_percent_reference_mae', f'{d} decimals', self.label.src),
                                 lo=self.num(lo, base + '.bootstrap.1.interval95_percent[0]', 'outward', self.label.src),
                                 hi=self.num(hi, base + '.bootstrap.1.interval95_percent[1]', 'outward', self.label.src))
                    plain = dict(effect=e_txt, lo=lo, hi=hi)
                    pair = self.pair(r['arm'], r['reference'])
                    if st.get('state') == 'SAME':
                        out.append(pair + ': ' + self.form('L1', latex, plain))
                    elif st.get('state') == 'DIFFERENT':
                        c6 = cs[i] if i < len(cs) else {'cls': 'NE'}
                        if c6['cls'] in ('IMP', 'DET'):
                            orig = WD['PRIMARY'][c6['cls'] + ('_ROBUST' if c6['robust'] == 'ROBUST' else '_OTHER')]
                        else:
                            orig = WD['PRIMARY'].get(c6['cls'], 'not evaluable')
                        repl = WD['TS6'][cmap(A4, st['class'])]
                        latex.update(reading_original=orig, reading_replacement=repl)
                        plain.update(reading_original=orig, reading_replacement=repl)
                        out.append(pair + ': ' + self.form('L2', latex, plain))
                    else:
                        out.append(pair + ': not evaluable under the replacement labels.')
            return ' '.join(out)

        def batches_supplement3b(self):
            text = Base.batches_supplement3b(self)
            for k in (IMP, NULL, DET):
                text = text.replace(' & ' + F2.esc(A4.TS_WORDS.get(k)) + ' & ', ' & ' + F2.esc(WD['TABLE_CLASS_C'][cmap(A4, k)]) + ' & ')
            return text

        def batch_forms3b(self):
            text = Base.batch_forms3b(self)
            text = text.replace(' improved on the article-activity reference', ' ' + F6['A6BV_IMP'] + ' the article-activity reference')
            text = text.replace(' performed reliably worse than the article-activity reference', ' ' + F6['A6BV_DET'] + ' the article-activity reference')
            return text

        def pg_rows(self):
            rows = Base.pg_rows(self)
            for key in rows:
                for k in (IMP, NULL, DET):
                    rows[key] = rows[key].replace('$]$\\%, ' + F2.esc(A4.CS_WORDS[k]) + ' &', '$]$\\%, ' + F2.esc(WD['CS_TABLE'][cmap(A4, k)]) + ' &')
            return rows

        def agreement_table(self):
            """FILL3b's agreement table with the paired codes mapped through AGREEMENT_CODES before escaping (A6 X14)."""
            g = self.agreement.data['groups']['ALL']['metrics']
            src = self.agreement.src
            code = lambda c: F2.esc(WD['AGREEMENT_CODES'].get(c, c))  # noqa: E731
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
                        items = [code(c) + ' ' + self.R(str(pv[c]['count']), src, base + f'.prevalence.{who}.{c}.count', 'count') for c in sorted(pv) if pv[c]['count']]
                        prev.append(', '.join(items) if items else '--')
                    pairs = self.pair_tables.get((corpus, f), Counter())
                    cont = ', '.join(code(a) + '/' + code(b) + ' ' + self.R(str(c), src, base + f' pair_trace ({a},{b})', 'count of paired codes') for (a, b), c in sorted(pairs.items()))
                    rows.append(' & '.join([('News' if corpus == 'news' else 'Notices') + ': ' + F2.esc(names.get(f, f)), raw, rate, ci, po, pe, ktxt, prev[0], prev[1], cont or '--']) + r' \\')
            head = r'Field & $k/n$ & Agree (\%) & Wilson 95\% & $p_o$ & $p_e$ & $\kappa$ & Author codes & Second codes & Paired codes (author/second) \\'
            spec = '@{}' + PW('.11') + 'rrlrrr' + PW('.09') + PW('.09') + PW('.16') + '@{}'
            cap = self.t3b('human.agreement_caption')
            head = self.fx3b(head, 'agreement header')
            self.a6_checks['agreement codes mapped'] += 1
            return ('{\\footnotesize\\setlength{\\tabcolsep}{' + self.layout('3pt') + '}\n\\begin{longtable}{' + self.layout(spec) + '}\n\\caption{' + cap + '}\\label{supp:tab:fill3b-agreement}\\\\\n\\toprule\n' + head +
                    '\n\\midrule\n\\endfirsthead\n\\toprule\n' + head + '\n\\midrule\n\\endhead\n\\bottomrule\n\\endfoot\n' + '\n'.join(rows) + '\n\\end{longtable}}\n')

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
            require(len(rows) >= 2, 'T4 and T5 rows required')
            return rows[0] + '\n' + ' '.join(rows[1:]) + TAG

        # ------------------------------------------------------------------ Figure 2 (RULE D-4)
        def forest_rows3b(self):
            rows = Base.forest_rows3b(self)
            for r in rows:
                if r.get('pcontent'):
                    r['thin_type'] = None
                    continue
                r['thin_type'] = 'per-contrast seven-day 95%'
                if r['group'] == 'Primary':
                    a2r = next(x for x in self.a2[r['task']]['primary'] if (x['arm'], x['reference']) == (r['arm'], r['ref']))
                    r['thin'] = a2r.get('interval_family_seven_day')
                    r['thin_type'] = 'family-adjusted seven-day'
                elif r['group'] == 'Combination':
                    comb = self.a2[r['task']]['combination']['family']['reports']
                    rep = next(x for x in comb if (x['arm'], x['reference']) == (r['arm'], r['ref']))
                    r['thin'] = (rep.get('bootstrap') or {}).get('7', {}).get('interval_family_adjusted_percent')
                    r['thin_type'] = 'family-adjusted seven-day'
            return rows

        def forest(self):
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import matplotlib.ticker
            from matplotlib.lines import Line2D
            import numpy as np
            matplotlib.rcParams.update({'pdf.fonttype': 42, 'font.size': 7.5, 'axes.linewidth': 0.6, 'svg.hashsalt': 'fill3d'})
            rows = self.forest_rows3b()
            heights = [max(2.0, 0.21 * sum(1 for r in rows if r['task'] == s) + 1.1) for s in SOURCES]
            fig, axes = plt.subplots(1, 2, figsize=(7.2, max(heights)))
            notes = []
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
                        wrapped = '\n'.join(textwrap.wrap(r['pcontent'], 46))
                        notes.append(ax.text(xmin + 0.02 * (xmax - xmin), yy, wrapped, va='center', ha='left', fontsize=5.0, color='0.35', linespacing=0.95))
                        continue
                    if r['effect'] is None or r['thick'] is None:
                        notes.append(ax.text(xmin + 0.02 * (xmax - xmin), yy, 'not computed', va='center', ha='left', fontsize=6.0, color='0.35'))
                        continue
                    ax.plot(r['thick'], [yy + 0.08, yy + 0.08], color='#1f4e79', lw=2.6, solid_capstyle='butt', gid='interval')
                    if r['thin'] is not None:
                        ax.plot(r['thin'], [yy - 0.18, yy - 0.18], color='#7f7f7f', lw=1.0, solid_capstyle='butt', gid='interval')
                    ax.plot([r['effect']], [yy + 0.08], 'o', color='black', ms=3.0, zorder=3, gid='interval')
                S = self.A2.SESOI[source]
                ax.axvline(0, color='0.2', lw=0.6)
                ytop, ybot = (max(prim_y) + 0.5, min(prim_y) - 0.5) if prim_y else (0.5, -0.5)
                top_band = (y[0] + 0.85) if len(y) else 1.0
                if xmin <= -S <= xmax:
                    ax.plot([-S, -S], [ybot, ytop], color='#a33', lw=0.8, ls='--')
                else:
                    edge = xmin if -S < xmin else xmax
                    notes.append(ax.annotate(f'$-{S:g}\\%$ (off axis)', xy=(edge, top_band), xytext=(edge + (0.22 if edge == xmin else -0.22) * (xmax - xmin), top_band),
                                             fontsize=6.0, color='#a33', ha='left' if edge == xmin else 'right', va='center',
                                             arrowprops=dict(arrowstyle='->', color='#a33', lw=0.8)))
                ax.set_xlim(xmin, xmax)
                ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(nbins=4))
                ax.set_ylim((y[-1] - 1.0) if len(y) else -1, top_band + 0.55)
                ax.set_yticks(y)
                ax.set_yticklabels(labels)
                ax.set_title('Day-ahead news' if source == 'news' else 'Market notices')
                ax.set_xlabel('% of the reference error')
                groups = [r['group'] for r in sub]
                for k in range(1, len(groups)):
                    if groups[k] != groups[k - 1]:
                        ax.axhline((y[k] + y[k - 1]) / 2, color='0.85', lw=0.5)
            fig.legend(handles=[Line2D([0], [0], color='#1f4e79', lw=2.6, label=TP['figure_legend_thick']),
                                Line2D([0], [0], color='#7f7f7f', lw=1.0, label=TP['figure_legend_thin'])],
                       loc='lower center', ncol=1, fontsize=6.2, frameon=False)
            fig.tight_layout(rect=(0, 0.11, 1, 1))
            fig.canvas.draw()
            self.figure_overlaps = overlap_problems(fig, axes, notes)
            require(not self.figure_overlaps, 'K6.7 Figure 2 overlap: ' + '; '.join(self.figure_overlaps[:6]))
            buf = io.BytesIO()
            fig.savefig(buf, format='pdf', metadata={'CreationDate': None, 'Creator': 'fill3d_conf_results.py', 'Producer': None})
            plt.close(fig)
            out = io.StringIO()
            w = csv.writer(out)
            w.writerow(['task', 'group', 'contrast', 'effect_percent', 'thick_type', 'thick_lo', 'thick_hi', 'seven_day_lo', 'seven_day_hi', 'thin_type', 'note', 'source_file', 'source_field'])
            for r in rows:
                w.writerow([r['task'], r['group'], f"{r['arm']}-{r['ref']}", r['effect'], r['thick_type'], *(r['thick'] or [None, None]), *(r['thin'] or [None, None]),
                            r.get('thin_type'), r.get('pcontent', ''), r['src'], r['field']])
            self.figure_rows = rows
            return buf.getvalue(), out.getvalue()

    return Fill3d


def overlap_problems(fig, axes, notes):
    """K6.7: annotation boxes must not overlap each other, a tick label or a plotted interval (display coordinates)."""
    renderer = fig.canvas.get_renderer()
    problems = []
    fb = fig.bbox
    for lg in fig.legends:
        e = lg.get_window_extent(renderer)
        if e.x0 < fb.x0 or e.x1 > fb.x1 or e.y0 < fb.y0:
            problems.append('legend outside the figure')
        for ax in axes:
            if e.overlaps(ax.get_window_extent(renderer)) or any(e.overlaps(t.get_window_extent(renderer)) for t in ax.get_xticklabels() if t.get_text()) \
                    or e.overlaps(ax.xaxis.label.get_window_extent(renderer)):
                problems.append('legend overlaps an axis')
    boxes = [(n, n.get_window_extent(renderer)) for n in notes]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if boxes[i][1].overlaps(boxes[j][1]):
                problems.append(f'annotations overlap: {boxes[i][0].get_text()[:30]!r} / {boxes[j][0].get_text()[:30]!r}')
    for ax in axes:
        xt = [t.get_window_extent(renderer) for t in ax.get_xticklabels() if t.get_text()]
        for a, b in zip(xt, xt[1:]):
            if a.overlaps(b):
                problems.append('x tick labels overlap')
        ticks = [t.get_window_extent(renderer) for t in ax.get_yticklabels()]
        lines = [ln.get_window_extent(renderer) for ln in ax.lines if ln.get_gid() == 'interval']
        for n, b in boxes:
            if n.axes is not ax:
                continue
            for tb in ticks:
                if b.overlaps(tb):
                    problems.append(f'annotation {n.get_text()[:30]!r} overlaps a tick label')
            for lb in lines:
                if b.overlaps(lb):
                    problems.append(f'annotation {n.get_text()[:30]!r} overlaps an interval line')
    return problems


# ============================================================================= K6 on the resolved texts (gate, alerts, one source)
def k6_text_check(r, resolved, edits):
    F3B_ = deps()
    problems, checked = [], 0
    texts = {rel: text for rel, text in resolved.items() if rel.endswith('.tex') and rel in F3B_.GENERATED.values()}
    for sid, rel, old, new in edits:
        texts[f'{rel} (slot {sid})'] = r.R.peek(new) if '\x00' in new else new
    for name, text in texts.items():
        plain = F3B_.plain_text(text)
        problems += gate_problems(plain, r.rs6, name)
        checked += 1
    primary = F3B_.plain_text(resolved[F3B_.GENERATED['primary']])
    for s in SOURCES:
        want = 1 if task_alert(r.rs6['tasks'][s]) else 0
        label = a4mod().A3.TASK_LABEL[s]
        got = primary.count(f'For {label}, the pipeline diagnostic raised a pre-specified alert')
        if got != want:
            problems.append(f'K6.5 {s}: {got} alert sentences in section 6.2 (expected {want})')
    concl = F3B_.plain_text(resolved[F3B_.GENERATED['conclusion']])
    if alert_tasks(r.rs6['tasks']) and concl.count('the pipeline diagnostic raised a pre-specified alert') != 1:
        problems.append('K6.5 conclusion: one alert sentence required')
    seeds = sum(1 for s in SOURCES for c in r.rs6['tasks'][s]['contrasts'] if c['cls'] == 'IMP' and not robust_inc(c))
    needs_seed = any(c['cls'] == 'IMP' and not robust_inc(c) and ((c['info'].get('attribution') or {}).get('cheap_text') or c.get('shift', {}).get('state') == 'COMPUTED')
                     for s in SOURCES for c in r.rs6['tasks'][s]['contrasts'])
    if seeds and needs_seed and 'primary seed only' not in primary:
        problems.append('K6.4 "primary seed only" missing beside a primary-seed increment')
    require(not problems, 'A6 K6 rendering assertions failed: ' + '; '.join(problems[:12]))
    return {'state': 'K6.4-K6.6 PASS', 'texts_checked': checked}


# ============================================================================= outputs, refill, freeze, build (FILL3c's with FILL3d names)
def write_outputs(manuscript, scores, r, a2post, a3post, a4post, resolved, binary, trace, words, edits, freeze, refill_of=None):
    F3B_ = deps()
    snapshot = manuscript / F3B_.SNAPSHOT_NAME
    require(not snapshot.exists(), f'{snapshot} exists: the manuscript was already filled (use --refill for a FILL3d fill)')
    for rel in list(F3B_.GENERATED.values()) + [F3B_.FIGURE] + list(F3B_.PUBLISHED.values()):
        require(not (manuscript / rel).exists(), 'Generated file already exists: ' + rel)
    require(not (manuscript / F3B_.TRACE_NAME).exists() and not (manuscript / F3B_.RECEIPT_NAME).exists(), 'Existing CONF trace/receipt')
    hosts = sorted({rel for _, rel, _, _ in edits})
    snapshot.mkdir()
    manifest = {}
    for rel in hosts:
        dst = snapshot / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manuscript / rel, dst)
        manifest[rel] = sha256(dst)
    (snapshot / 'MANIFEST.json').write_text(json.dumps({'purpose': 'pre-fill copies of every host file edited by fill3d_conf_results.py', 'files_sha256': manifest}, indent=2) + '\n')
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
    receipt = {'state': 'CONF_RESULTS_FILLED', 'fill_step': 'FILL3d', 'utc': datetime.now(timezone.utc).isoformat(),
               'script_sha256': sha256(Path(__file__)), 'fill3c_script_sha256': sha256(MS / 'fill3c_conf_results.py'),
               'freeze_sha256': sha256(MS / FREEZE_NAME) if (MS / FREEZE_NAME).is_file() else None, 'fill3c_freeze_sha256': FILL3C_FREEZE_SHA256,
               'a6_freeze_sha256': A6_FREEZE_SHA256, 'a5_freeze_sha256': F3C.A5_FREEZE_SHA256, 'freeze': freeze, 'templates_sha256': sha256(MS / TEMPLATES_NAME),
               'manuscript': str(manuscript), 'scored_directory': str(scores.scored), 'score_receipt_sha256': scores.receipt_sha256, 'seal_sha256': scores.seal_sha256,
               'a2_postscore_sha256': a2post.sha256, 'a3_postscore_sha256': a3post.sha256, 'a4_postscore_sha256': a4post.sha256,
               'score_files_verified': len(scores.files), 'frozen_adapter_cross_checks': r.cross_checks, 'a1_cross_checks': r.a1_checks,
               'a2_sentence_checks': Counter(r.sentence_checks), 'a3_sentence_checks': r.a3_checks, 'a4_sentence_checks': r.a4_checks,
               'a6_checks': r.a6_checks, 'a6_form_counts': r.a6_keys, 'k4_rendering': 'PASS', 'k6': r.k6, 'k6_text': r.k6_text,
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
    require(receipt.get('fill_step') == 'FILL3d', 'The manuscript was not filled by FILL3d; --refill refuses')
    for rel, digest in receipt['outputs_sha256'].items():
        require((manuscript / rel).is_file() and sha256(manuscript / rel) == digest, f'{rel} changed after the FILL3d fill; --refill refuses')
    reader, manifest = F3B_.snapshot_reader(manuscript)
    return receipt, reader, manifest


def verify_freeze():
    path = MS / FREEZE_NAME
    require(path.is_file(), FREEZE_NAME + ' missing: FILL3d must be frozen before use')
    freeze = json.loads(path.read_text())
    require(freeze.get('state') == 'FILL3D_FROZEN_BEFORE_CONF_SCORES', 'Unexpected FILL3d freeze state')
    for rel, digest in freeze['files'].items():
        require(sha256(MS / rel) == digest, f'{rel} differs from its FILL3d freeze hash')
    for rel, digest in freeze.get('external_identities', {}).items():
        require(sha256(PROJ / rel) == digest, f'{rel} differs from the identity recorded in the FILL3d freeze')
    require(freeze['files'].get(Path(__file__).name) == sha256(Path(__file__)), 'fill3d_conf_results.py is not bound by FILL3D_FREEZE.json')
    return freeze


def build(manuscript):
    """The unchanged build script after refreshing supplement.aux; every validation must pass (no abstract tolerance: K6.1)."""
    deps()
    env = {**os.environ, 'TECTONIC_CACHE_DIR': '/tmp/task_a_tectonic_cache'}
    subprocess.run(['/usr/bin/nice', '-n', '10', '/opt/homebrew/bin/tectonic', '-X', 'compile', str(manuscript / 'supplement.tex'), '--keep-logs', '--keep-intermediates'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, check=True)
    aux = (manuscript / 'supplement.aux').read_text(errors='replace')
    m = re.search(r'\\newlabel\{supp:tab:fill3b-stages\}\{\{([^}]*)\}', aux)
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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    F3B_ = deps()
    parser.add_argument('--state', type=Path, default=F3B_.DEFAULT_STATE)
    parser.add_argument('--manuscript', type=Path, default=MS)
    parser.add_argument('--base25-root', type=Path, default=F3B_.Q1 / 'BASE25')
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
    parser.add_argument('--a2batch', type=Path, default=F3B_.Q1 / 'A2BATCH/scores/A2BATCH_RESULT.json')
    parser.add_argument('--a2label', type=Path, default=F3B_.Q1 / 'A2LABEL/scores/A2LABEL_RESULT.json')
    parser.add_argument('--test-keys-per-day', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--prefill', action='store_true', help='write the FILL3d PREFILL (stage 1 = FILL3b PREFILL, stage 2 = CONF-A6 section X; pre-score)')
    parser.add_argument('--check-prefill', action='store_true', help='regenerate the PREFILL in memory and compare with the manuscript')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--refill', action='store_true')
    args = parser.parse_args(argv)
    manuscript = args.manuscript.resolve()
    if args.prefill or args.check_prefill:
        coverage = F3B_.Coverage(args.coverage)
        result = write_prefill3d(manuscript, coverage, check_only=args.check_prefill)
        print(json.dumps({k: result[k] for k in result if k != 'outputs_sha256'}, indent=2))
        return 0 if result['state'] in ('FILL3D_PREFILL_WRITTEN', 'PREFILL_EQUAL') else 3
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
    r.k6_text = k6_text_check(r, resolved, edits)
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
