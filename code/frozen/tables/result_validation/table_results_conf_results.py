
'Render result fields from explicitly checked numerical inputs.'
from __future__ import annotations
import argparse
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import difflib
import hashlib
import importlib.util
import itertools
from functools import lru_cache
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True

sys.path.append(str(Path(__file__).resolve().parents[2]))
CODE_ROOT = Path(__file__).resolve().parent
MS = CODE_ROOT.parents[1]
PROJ = MS.parent
inference_design = PROJ / 'studies/confirmation/inference_design'
A8_BINDINGS = {'A8_FREEZE.json': '80e95c8db2c85ca38490f443612cda30d7ff33124f33ed87b70d8f8317909162', 'ADDENDUM_A8.md': 'efe1770cd04a44131fda63d3d99f36a7bf521da270adae6ccf8bcbdf054a7f8b', 'RULES_FOR_TABLE_RESULTS.json': 'a7490266709a5607f424154635b77bb8fafcc2139d705541612fa7ed7b00b048', 'RULES_FOR_TABLE_RESULTS.md': '6d8dd278227c7053c316af16686a39e707ce283556aa002ff6a65dc2569fe35a', 'FIXED_FACTS_A8.json': 'cebd9113a4c8c67bb225a4b29dfcba613f0543d7492a83c3f1aa2acfb2f84eb8', 'AUTHOR_CONFIRMATION_A8_SCHEMA.json': 'd1d08bff57dab76dd90219223169eda11e2d1c8f3f2ebd60407b08e89d54aa45'}
E_FREEZE_SHA = '8a5a9a9614498cd3c3113a9fc1cffac5f142d1239ed1dcbbc79f681d605b6194'
ARMS = {'news': [('L_count', 'M'), ('L_chen', 'M')],
        'notice': [('L14', 'M_notice'), ('L_Laz', 'M_notice'), ('L_chen_notice', 'M_notice')]}
CHECKS = ('one_day', 'seven_day', 'hln', 'hac7', 'three_seed', 'family_interval')
CLASSES = ('IMP', 'NULL', 'DET', 'NE')
LAYERS = ('R8', 'DLY8', 'CPS8', 'KCX')
REL_STATES = ('SAME', 'DIFFERENT', 'NOT_RUN', 'NOT_EVALUABLE', 'PENDING', 'NOT_APPLICABLE')
FIELDS = {'arm', 'reference', 'class', 'effect_percent', 'effect_aud', 'family_one_day',
          'family_seven_day', 'per_contrast_seven_day', 'envelope', 'checks',
          'three_seed_class', 'three_seed_effect', 'relations', 'squared_loss',
          'design_rejection_not_reproduced', 'cheap_text', 'reason', 'design_layers', 'delay_classes'}

class FillError(RuntimeError):
    pass

def require(ok, message):
    if not ok:
        raise FillError(message)

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()

def text_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()

def strict_json(path):
    def pairs(items):
        out = {}
        for k, v in items:
            require(k not in out, f'duplicate JSON key: {k}')
            out[k] = v
        return out
    def bad(value):
        raise FillError('non-finite JSON value: ' + value)
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=bad)

@lru_cache(maxsize=1)
def templates():
    return strict_json(MS / 'table_results_templates.json')

def safe_path(root, rel):
    p = (Path(root) / rel).resolve()
    require(p.is_relative_to(Path(root).resolve()), 'freeze path escapes root: ' + rel)
    require(not re.search(r'(?:^|/)(?:host_state|seals?|scores?|predictions?|evaluation|run)(?:/|$)', rel, re.I),
            'prohibited production payload in dependency manifest: ' + rel)
    return p

def verify_manifest(path, root, expected=None):
    require(Path(path).is_file(), 'missing freeze: ' + str(path))
    if expected:
        require(sha256(path) == expected, 'freeze identity drift: ' + str(path))
    f = strict_json(path)
    require(bool(f.get('files')), 'freeze has no files: ' + str(path))
    for group in ('files', 'test_receipts'):
        for rel, entry in f.get(group, {}).items():
            digest = entry['sha256'] if isinstance(entry, dict) else entry
            p = safe_path(root, rel)
            require(p.is_file() and sha256(p) == digest, 'frozen file drift: ' + rel)
    for rel, entry in f.get('external_identities', {}).items():
        p = safe_path(PROJ, rel)
        digest = entry['sha256'] if isinstance(entry, dict) else entry
        require(p.is_file() and sha256(p) == digest, 'external identity drift: ' + rel)
    return f

_E = None

def load_summary_comparisons():
    global _E
    if _E is None:
        f = verify_manifest(MS / 'SUMMARY_COMPARISONS_FREEZE.json', MS, E_FREEZE_SHA)
        require('summary_comparisons_conf_results.py' in f['files'], 'E script not bound')
        name = 'summary_comparisons_conf_results'
        spec = importlib.util.spec_from_file_location(name, MS / 'summary_comparisons_conf_results.py')
        module = importlib.util.module_from_spec(spec)

        sys.modules[name] = module
        spec.loader.exec_module(module)
        module.verify_freeze()
        module.deps()
        _E = module
    return _E

def normalise_fixed_facts(raw):
    require(raw.get('schema')=='FIXED_FACTS_A8_V1', 'unexpected fixed-facts schema')
    values={f['id']:f for f in raw['facts']}
    require(len(values)==len(raw['facts']), 'duplicate fixed-fact identity')
    require(all(isinstance(f.get('display'),str) for f in values.values()), 'fixed-fact display missing')
    sentences=list(raw['rendered_strings'].values())

    return dict(raw,rendered_sentences={'main':sentences,'supplement':sentences})


@lru_cache(maxsize=1)
def fixed_facts_for_tests():
    binding=templates()['fixed_facts_binding']
    path=PROJ/binding['path']
    require(path.is_file() and sha256(path)==binding['sha256'], 'fixed-facts file identity drift')
    return normalise_fixed_facts(strict_json(path))


def timestamp_checks(a8dir=inference_design, frozen=True):

    a8dir = Path(a8dir)
    for name in ('A8_FREEZE.json', 'ADDENDUM_A8.md', 'RULES_FOR_TABLE_RESULTS.json', 'FIXED_FACTS_A8.json'):
        require((a8dir / name).is_file(), 'missing inference_design freeze or fixed-facts file: ' + name)
    ff = None
    if frozen:
        ff = verify_manifest(CODE_ROOT / 'TABLE_RESULTS_FREEZE.json', CODE_ROOT)
        from table_renderer.reference_gate import verify_receipt
        try:verify_receipt(CODE_ROOT/'table_renderer/REFERENCE_GATE_AT_FREEZE.json',ff)
        except (ValueError,OSError,KeyError) as exc:raise FillError('freeze-time reference gate failed: '+str(exc)) from exc
        require(ff.get('state') == 'TABLE_RESULTS_FROZEN_BEFORE_D_SCORES', 'unexpected F freeze state')
        require(ff.get('a8_freeze_sha256') == sha256(a8dir / 'A8_FREEZE.json'), 'inference_design identity not bound by F freeze')
    from table_renderer.constraint_contract import specification2
    specification2_binding=specification2(a8dir)
    if frozen:
        require(specification2_binding is not None, 'effective specification 2 receipt required by F freeze')
        require(ff.get('a8_specification2_freeze_sha256')==specification2_binding['sha256'], 'F freeze does not bind specification 2')
    additions=specification_words(a8dir)
    if frozen and additions:
        require(ff.get('a8_specification1_freeze_sha256')==sha256(a8dir/'ADDENDUM_A8_SPECIFICATION_1_FREEZE.json'), 'F freeze does not bind inference_design specification 1')
    af = verify_manifest(a8dir / 'A8_FREEZE.json', a8dir, A8_BINDINGS['A8_FREEZE.json'])
    for name, digest in A8_BINDINGS.items():
        require(sha256(a8dir/name) == digest, 'inference_design pinned identity drift: '+name)
    rule_text=(a8dir/'RULES_FOR_TABLE_RESULTS.json').read_text().rstrip('\n')
    require('```json\n'+rule_text+'\n```' in (a8dir/'ADDENDUM_A8.md').read_text(), 'inference_design appendix JSON differs from rule sheet')
    T=templates(); rules=strict_json(a8dir/'RULES_FOR_TABLE_RESULTS.json')
    require(T['timestamp_checks']['sha256']==A8_BINDINGS, 'template timestamp_checks drift')
    for key in ('forms','words','replaces_forms','replaces_templates'):
        require(T[key]==rules[key], 'template frozen rule drift: '+key)
    require(T['frozen_templates']==rules['templates'], 'frozen template drift')
    require(sha256(a8dir / 'FIXED_FACTS_A8.json')==templates()['fixed_facts_binding']['sha256'], 'fixed-facts binding drift')
    for name in ('ADDENDUM_A8.md', 'RULES_FOR_TABLE_RESULTS.json', 'FIXED_FACTS_A8.json'):
        require(name in af['files'], 'inference_design freeze does not bind ' + name)
    return {'freeze': ff, 'a8': af, 'rules': strict_json(a8dir / 'RULES_FOR_TABLE_RESULTS.json'),
            'facts': normalise_fixed_facts(strict_json(a8dir / 'FIXED_FACTS_A8.json')),
            'a8_freeze_sha256': sha256(a8dir / 'A8_FREEZE.json'),
            'fixed_facts_sha256': sha256(a8dir / 'FIXED_FACTS_A8.json'),
            'specification2':specification2_binding}


specification1_FILES = {'ADDENDUM_A8_SPECIFICATION_1_PAPER.md': 'd69f2ed46148f94463dc6100d513729ae86a5c53db6fb735ea82210f1d6f9f06', 'freeze_inference_design.py': '6fb4350ccf390a6043393a8364af314692f8d425961d25c588113981bcf2c4b0'}
specification1_ADDITIONS = {'words.PFMIN_C3.NE': 'no evaluable reading',
                       'words.PFMIN_INC_REASON.parity': 'reproduction check failed'}


def specification_words(a8dir=None):

    root = Path(a8dir) if a8dir is not None else inference_design
    receipt = root / 'ADDENDUM_A8_SPECIFICATION_1_FREEZE.json'
    if not receipt.exists(): return {}
    for name, digest in specification1_FILES.items():
        require((root/name).is_file() and sha256(root/name)==digest,
                'inference_design specification 1 pinned file drift: '+name)
    spec = importlib.util.spec_from_file_location('verified_a8_specification1', root/'freeze_inference_design.py')
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    try: rec = helper.verify(receipt, root)
    except (ValueError, OSError, KeyError) as exc:
        raise FillError('inference_design specification 1 verification failed: '+str(exc)) from exc
    require(rec['additions']==specification1_ADDITIONS, 'unexpected inference_design specification 1 additions')
    return {k.split('.')[1]+'.'+k.split('.')[2]:v for k,v in rec['additions'].items()}


def floor_word(group, key, refusal):
    W=templates()['words']
    if key in W[group]: return W[group][key]
    additions=specification_words()
    require(group+'.'+key in additions, refusal)
    return additions[group+'.'+key]

def decimal(value, nullable=False):
    if value is None and nullable:
        return None
    require(isinstance(value, str) and bool(re.fullmatch(r'[+-]?\d+(?:\.\d+)?', value)), 'expected signed decimal string')
    try:
        d = Decimal(value)
    except InvalidOperation as exc:
        raise FillError('invalid decimal') from exc
    require(d.is_finite(), 'non-finite decimal')
    return d

def interval(value, nullable=False):
    if value is None and nullable:
        return None
    require(isinstance(value, list) and len(value) == 2, 'interval must have two endpoints')
    lo, hi = map(decimal, value)
    require(lo <= hi, 'interval endpoints out of order')
    return lo, hi

def seven_undefined(c):
    return c['family_seven_day'] is None or c['per_contrast_seven_day'] is None

def robust(c, alert=False):
    return c['class'] != 'NE' and not alert and not seven_undefined(c) and all(c['checks'][k] == 'PASS' for k in CHECKS)

def normalise_stage_row(row):
    row=dict(row)
    if 'post_seal' in row or 'category' in row:
        require('post_seal' in row and 'category' in row and 'postseal' not in row and 'counted_category' not in row, 'mixed stage field names')
        row['postseal']=row.pop('post_seal');row['counted_category']=row.pop('category')
    return row


def clock_reason(clk):
    reasons=templates()['words']['CLK8_REASONS']
    require('reason' not in clk, 'CLK8 reason singleton is inactive')
    codes=clk.get('reason_codes')
    require(isinstance(codes,list) and bool(codes), 'CLK8 ordered reason_codes required')
    allowed=list(reasons)
    require(all(isinstance(c,str) and c in reasons for c in codes), 'unknown CLK8 reason code')
    require(len(set(codes))==len(codes) and codes==sorted(codes,key=allowed.index), 'duplicate or out-of-order CLK8 reasons')
    require(all(c.startswith('N') for c in codes) or codes in (['INPUT'],['FAIL']), 'mixed CLK8 failure reasons')
    vals=[reasons[c] for c in codes]
    return vals[0] if len(vals)==1 else ' and '.join(vals) if len(vals)==2 else ', '.join(vals[:2])+' and other listing problems'


def reason_text(identity):
    return inherited_form(identity) if identity == 'A4NR_BUDGET' else form(identity)


def state_informative(clk):
    return clk['state']=='INFORMATIVE'


def clock_ok(clk):
    require(state_informative(clk), 'CLK8 informative state required')
    return Decimal(clk['listed_by_admission_n']) / Decimal(clk['covered_n']) >= Decimal('0.99')


def validate_clock(clk, record):
    from decimal import ROUND_HALF_UP
    require(type(clk.get('covered_n')) is int and clk['covered_n']>0, 'CLK8 coverage count missing')
    n=clk.get('listed_by_admission_n')
    require(type(n) is int and 0<=n<=clk['covered_n'], 'CLK8 unrounded numerator missing')
    display=(Decimal(n)*100/Decimal(clk['covered_n'])).quantize(Decimal('.1'), rounding=ROUND_HALF_UP)
    require(decimal(clk['public_by_admission'])==display, 'CLK8 display differs from unrounded counts')
    if not clock_ok(clk):
        require('delay60_class' in clk and clk['delay60_class'] in (*CLASSES,None), 'CLK8 LATE needs +60 reading or recorded missing result')
    bound=record.get('clk8_result')
    if bound is not None and 'path' not in bound:
        require(bound.get('coverage',{}).get('covered_notices')==clk['covered_n'], 'CLK8 covered_n differs from CLK8_RESULT.json')
        require(bound.get('listed_by_admission_n')==n, 'CLK8 numerator differs from bound result')


def r8_seeds(record,task,c):
    rows={r['stage']:r for r in map(normalise_stage_row,record['stages'])}
    chosen=record['author_confirmation']['choices']['r8_seeds']
    actual='three' if chosen=='three' and (task=='notice' or rows.get('A8B-R8S',{}).get('counted_category') in CATEGORIES[:2]) else 'single'
    if c['relations']['R8']['state'] in ('SAME','DIFFERENT','NOT_EVALUABLE'):
        require(c['relations']['R8'].get('seeds_run',actual)==actual, 'R8 seeds contradict actual stage disposition')
    return actual


def task_context(record,task):
    t=deepcopy(record['tasks'][task]); rows={r['stage']:r for r in map(normalise_stage_row,record['stages'])}
    t['_r8_seeds']=r8_seeds(record,task,t['contrasts'][0])
    for layer,name in (('R8','A8B-R8N' if task=='notice' else 'A8B-R8'),('DLY8','DLY8')):
        row=rows[name];t['_'+layer.lower()+'_reason']=row.get('reason');t['_'+layer.lower()+'_category']=row['counted_category']
    return t


def relation_reason(rel,layer,t):
    reason=rel.get('reason') or t.get('_'+layer.lower()+'_reason')
    if reason is None and t.get('_'+layer.lower()+'_category')==CATEGORIES[4]:return 'it had no result at the cut-off'
    require(reason is not None, layer+' unavailable reading requires its real frozen reason')
    return reason_text(reason) if reason in templates()['forms'] or reason in ('A4NR_BUDGET','A8NR_RESOURCE_A8AM2') else templates()['words']['PLAIN_INC_REASON'].get(reason,reason)


def cheap_text(c):
    reading={'BETTER':'better','WORSE':'worse','NOTSHOWN':'not shown','NOT_EVALUABLE':'not evaluable','NOT_RUN':'not run'}[c['cheap_text']]
    seed='; primary seed only' if c['class']=='IMP' and not robust(c) else ''
    return reading+' (exploratory: secondary, single seed, unadjusted, not fully checked'+seed+')'


def verify_clock_binding(record):

    clk=record['tasks']['notice']['clk8']; b=record.get('clk8_result')
    if b is None:
        disposition=record.get('clk8_not_run_disposition')
        require(clk['state']=='NOT_RUN' and isinstance(disposition,dict), 'missing CLK8 result needs explicit not-run disposition')
        path=Path(disposition['path'])
        require(path.name=='CLK8_NOT_RUN_DISPOSITION.json' and sha256(path)==disposition['sha256'], 'CLK8 not-run disposition identity drift')
        listed=[d for k in ('T4B','T5') for n,d in record['timestamps'][k]['files'].items() if Path(n).name==path.name]
        require(disposition['sha256'] in listed,'CLK8 not-run disposition not listed in T4B/T5')
        raw=strict_json(path)
        require(raw.get('state')=='NOT_RUN' and raw.get('reason_codes')==['INPUT'] and raw.get('result_absent') is True,
                'CLK8 absent result disposition must explicitly record INPUT and absence')
    else:
        require(isinstance(b,dict), 'CLK8_RESULT.json identity required')
        path=Path(b['path']);require(path.name=='CLK8_RESULT.json' and sha256(path)==b['sha256'], 'CLK8 result identity drift')
        listed=[d for k in ('T4B','T5') for n,d in record['timestamps'][k]['files'].items() if Path(n).name==path.name]
        require(b['sha256'] in listed, 'CLK8 result not listed in T4B/T5')
        if path.resolve().is_relative_to(PROJ):
            from table_renderer.table_contract import CLOCK_SHA
            require(path.resolve()==(inference_design/'CLK8/CLK8_RESULT.json').resolve() and b['sha256']==CLOCK_SHA,'production CLK8 exact identity drift')
        raw=strict_json(path)
        require(b.get('numerator_pointer')=='/listed_by_admission_n','CLK8 native numerator pointer required')
    state=raw['state'];mapped='NOT_RUN' if state=='NOT_RUN_INPUT_MISMATCH' else state
    require(mapped in ('INFORMATIVE','NOT_INFORMATIVE','NOT_RUN') and clk['state']==mapped, 'CLK8 state differs from native result')
    codes=raw['reason_codes']
    require(clk.get('reason_codes')==codes, 'CLK8 reasons differ from native result')
    if mapped=='NOT_RUN':
        require(codes==(['INPUT'] if state=='NOT_RUN_INPUT_MISMATCH' or b is None else ['FAIL']), 'CLK8 exact INPUT/FAIL mapping required')
    if mapped=='NOT_INFORMATIVE':require(codes and all(x in ('N1','N2','N3','N4','N5') for x in codes),'CLK8 NI reasons required')
    if mapped=='INFORMATIVE':require(codes==[], 'CLK8 informative result with reasons')
    else:clock_reason(clk)
    for key,value in {'covered_n':raw.get('coverage',{}).get('covered_notices'),
                      'listed_by_admission_n':raw.get('listed_by_admission_n'),
                      'X':raw.get('X'),'Y':raw.get('Y'),'Z':raw.get('Z'),
                      'reading':raw.get('reading','A8CLK_NR')}.items():
        require(clk.get(key)==value, 'CLK8 '+key+' differs from native result')
    require(clk.get('coverage')==raw.get('coverage'), 'CLK8 coverage object differs from native result')
    require(clk.get('public_by_admission')==raw.get('X') and
            clk.get('maximum_delay_minutes')==(str(raw['Z']) if raw.get('Z') is not None else None),
            'CLK8 X/Z display differs from native result')
    if raw.get('Z') is not None:require(type(raw['Z']) is int and raw['Z']>=0,'CLK8 Z must be a native integer')
    if mapped=='INFORMATIVE':
        validate_clock(clk,record)
        require(clk['reading']==('A8CLK_OK' if clock_ok(clk) else 'A8CLK_LATE'), 'CLK8 native reading contradicts exact counts')


def validate_record(record, bindings=None):
    require(record.get('schema') == 'TABLE_RESULTS_A8_V1', 'unsupported read_comparisons interface: TABLE_RESULTS_A8_V1 required')
    require(type(record.get('bootstrap_draws')) is int and record['bootstrap_draws'] == 100000, 'B must be 100000')
    ids = record.get('identities', {})
    require(set(ids) == {'a8_freeze_sha256', 'fixed_facts_sha256', 'summary_comparisons_freeze_sha256', 'source_receipt_sha256'}, 'identity fields missing')
    require(all(isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v) for v in ids.values()), 'invalid identity hash')
    require(ids['summary_comparisons_freeze_sha256'] == E_FREEZE_SHA, 'E freeze identity drift')
    if bindings:
        for k in ('a8_freeze_sha256', 'fixed_facts_sha256'):
            require(ids[k] == bindings[k], k + ' differs from timestamp_checks')
    require(set(record.get('tasks', {})) == set(ARMS), 'both tasks required')
    for task, pairs in ARMS.items():
        t = record['tasks'][task]
        require(type(t.get('complete')) is bool and type(t.get('alert')) is bool, 'invalid task gates')
        require(t.get('secondary_clause') in ('UNCHANGED', 'DIFFERENT', 'NOT_RUN'), 'invalid secondary clause')
        require([(c.get('arm'), c.get('reference')) for c in t['contrasts']] == pairs, 'primary pair order drift')
        for c in t['contrasts']:
            require(FIELDS <= set(c) and set(c) <= FIELDS | {'holm_p','mc_unresolved','r8_result','erd_class','cheap_comparators','benchmark_forms','native_primary'}, 'contrast interface drift: ' + c['arm'])
            require(c['class'] in CLASSES and c['three_seed_class'] in CLASSES, 'invalid class')
            require(set(c['checks']) == set(CHECKS) and all(x in ('PASS','FAIL','UNAVAILABLE') for x in c['checks'].values()), 'six checks required')
            for k in ('effect_percent', 'effect_aud', 'envelope', 'three_seed_effect'):
                decimal(c[k], nullable=c['class'] == 'NE' or k in ('envelope','three_seed_effect'))
            if c['class']=='NE':
                require(all(c[k] is None for k in ('effect_percent','effect_aud','family_one_day','family_seven_day','per_contrast_seven_day','envelope')), 'numeric result for non-evaluable member')
            if c['three_seed_class']=='NE':
                require(c['three_seed_effect'] is None, 'numeric result for unavailable three-seed mean')
            one = interval(c['family_one_day'], nullable=c['class'] == 'NE')
            interval(c['family_seven_day'], nullable=True)
            interval(c['per_contrast_seven_day'], nullable=True)
            if c['class'] in ('IMP','DET'):
                agrees = one is not None and (one[1] < 0 if c['class'] == 'IMP' else one[0] > 0)
                require((c['checks']['family_interval'] == 'PASS') == agrees, 'sixth inferential check contradicts family interval')
            if seven_undefined(c):
                require(c['checks']['seven_day'] == 'UNAVAILABLE', 'seven-day undefined without unavailable check')
            require(set(c['relations']) == set(LAYERS), 'relation clauses missing')
            for layer, rel in c['relations'].items():
                require({'state','class'} <= set(rel) and set(rel) <= {'state','class','fully_checked','seeds_run','reason','g0_class','selected_grid'}, 'relation interface drift')
                require(rel['state'] in REL_STATES and rel['class'] in (*CLASSES, None), 'invalid relation')
                if rel['state'] in ('SAME','DIFFERENT'):
                    require(rel['class'] in CLASSES, 'relation class missing')
                    if layer == 'CPS8':
                        if 'g0_class' in rel:
                            require(rel['g0_class'] in CLASSES, 'CPS8 schedule-matched g0 class invalid')
                            require((rel['class'] == rel['g0_class']) == (rel['state'] == 'SAME'), 'CPS8 selected/g0 relation contradicts state')
                    else:
                        require((rel['class'] == c['class']) == (rel['state'] == 'SAME'), 'relation class contradicts state')
                if task == 'news' and layer == 'DLY8':
                    require(rel['state'] in ('NOT_RUN','NOT_APPLICABLE'), 'notice delay relation applied to news')
                if layer == 'R8':
                    require(type(rel['fully_checked']) is bool, 'R8 fully_checked required')
                    require(r8_seeds(record,task,c) in ('single','three'), 'R8 seeds missing')
                    require(not rel['fully_checked'] or r8_seeds(record,task,c)=='three', 'single-seed R8 cannot be robust')
            require(type(c['design_rejection_not_reproduced']) is bool, 'design rejection gate must be bool')
            require(not c['design_rejection_not_reproduced'] or c['class'] in ('IMP','DET'), 'abstract design dissent without rejection')
            if c['class']!='NE':
                require((decimal(c['effect_percent'])<0 if c['class']=='IMP' else decimal(c['effect_percent'])>0) if c['class'] in ('IMP','DET') else True, 'class/effect sign contradiction')
            require(c['cheap_text'] in ('BETTER','WORSE','NOTSHOWN','NOT_EVALUABLE','NOT_RUN'), 'invalid cheap-text reading')
            require(set(c['squared_loss']) == {'state','effect','p'} and c['squared_loss']['state'] in ('COMPUTED','NOT_RUN'), 'invalid squared-loss descriptive')
            decimal(c['squared_loss']['effect'], nullable=c['squared_loss']['state']=='NOT_RUN')
        clk = t['clk8']
        if task == 'news':
            require(clk is None, 'news CLK8 must be null')
        else:
            require(isinstance(clk,dict) and clk.get('state') in ('INFORMATIVE','NOT_INFORMATIVE','NOT_RUN'), 'CLK8 clause missing')
            rate = decimal(clk.get('public_by_admission'), nullable=clk['state']!='INFORMATIVE')
            decimal(clk.get('maximum_delay_minutes'), nullable=clk['state']!='INFORMATIVE')
            require(rate is None or 0 <= rate <= 100, 'invalid listing percentage')
            if state_informative(clk):
                validate_clock(clk, record)
            else:
                clock_reason(clk)
    require(set(record.get('optional',{})) == {'batch_scoring','ISOBATCH','matched_controls','KCX','R8'} and all(type(v) is bool for v in record['optional'].values()), 'optional result presence fields required')
    require(isinstance(record.get('specified_reading_n0'),str) and record['specified_reading_n0'].strip(), 'full specified RS8 N0 reading missing')
    from table_renderer.constraint_contract import validate_additions
    validate_additions(record)
    validate_presentation(record)
    plain_display_record(record)
    return record

def plain_display_record(record):

    def width(value, limit, label):
        if value is None: return
        decimal(value)
        require(len(value)<=limit and ('.' not in value or len(value.split('.')[-1])<=5), 'outside frozen plain display envelope: '+label)
    if record['lear']['effect'] is not None: width(str(abs(decimal(record['lear']['effect']))),7,'LEAR')
    for task,t in record['tasks'].items():
        width(t['bound'],7,'bound');width(t['mn_effect'],10,'activity effect')
        for c in t['contrasts']:
            for key in ('effect_percent','effect_aud','three_seed_effect'): width(c[key],10,key)
            for key in ('family_one_day','family_seven_day','per_contrast_seven_day'):
                if c[key] is not None:
                    for endpoint in c[key]: width(endpoint,10,key)
        if task=='notice' and state_informative(t['clk8']):
            clk=t['clk8'];width(clk['public_by_admission'],5,'clock share')
            require(len(str(clk['covered_n']))<=5, 'outside frozen plain display envelope: covered_n')
    return record


def words(text):
    return len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*", text))

def join(items):
    items = list(items)
    return ', '.join(items[:-1]) + ' and ' + items[-1] if len(items)>1 else items[0] if items else ''

LEVELS = ('P0', 'P1', 'P2', 'PF', 'PFMIN')
CATEGORIES = ('completed', 'completed apart from recorded unavailable configurations',
              'not run (frozen reason)', 'deviation', 'pending (no result file when filled)')
OWN_STAGES = {'A2B-1','A2B-2','label_scoring','PC','matched_controls','DLY8','KCX'}


def form(identity, **slots):

    T = templates()
    require(identity not in T['replaces_forms'], 'inactive inference_design form: '+identity)
    if identity=='A8NR_RESOURCE_A8AM2':
        from table_renderer.constraint_contract import specification2_form
        require(not slots,'specification 2 reason has no slots');return specification2_form(identity)
    require(identity in T['forms'], 'unknown inference_design form: '+identity)
    pattern = T['forms'][identity]
    names = set(re.findall(r'\{([A-Za-z0-9_]+)\}', pattern))
    require(set(slots) == names, 'form slot mismatch: '+identity)
    for key, value in slots.items():
        require(isinstance(value, str), 'form slot must be text: '+key)
        if key == 'reason':
            allowed = [v for k,v in T['forms'].items() if k.startswith(('A8NR_','A8DEV_'))]
            allowed += [inherited_form('A4NR_BUDGET')]
            allowed += list(T['words']['PLAIN_INC_REASON'].values())
            allowed += list(T['words']['CLK8_REASONS'].values())
            allowed += ['it had no result at the cut-off']
            allowed += list(T['words']['PFMIN_INC_REASON'].values())
            if value not in allowed: allowed += list(specification_words().values())
            if identity in ('A8CLK_NR','A8CLK_NI'):
                import itertools
                allowed += [clock_reason({'reason_codes':list(codes)}) for n in range(1,6) for codes in itertools.combinations(('N1','N2','N3','N4','N5'),n)]
            verified_resource=None
            if value not in allowed:
                from table_renderer.constraint_contract import specification2
                binding=specification2()
                if binding and value==binding['record']['changes']['forms.A8NR_RESOURCE_A8AM2']:allowed.append(value);verified_resource=value
            require(value in allowed and (words(value)<=12 or identity=='A8CLK_NI' or value==verified_resource), 'unfrozen or oversized reason')
    return pattern.format(**slots)


def sentence(identity, **slots):
    s=form(identity, **slots)
    s=s[:1].upper()+s[1:]
    require(words(s)<=35, 'plain sentence over 35 words: '+identity)
    return s


def author_title(record1):
    require(isinstance(record1,dict), 'missing confirmation/AUTHOR_CONFIRMATION_A8.json')
    variant=record1.get('choices',{}).get('title_variant')
    require(variant in ('a8','a8b'), 'invalid inference_design author title choice')
    return form('A8TITLE_'+variant.upper())


@lru_cache(maxsize=1)
def author_schema():
    return strict_json(inference_design/'AUTHOR_CONFIRMATION_A8_SCHEMA.json')


def validate_authors(first, second, timestamps):
    from datetime import datetime, date
    schema=author_schema()
    for obj, key in ((first,'record_1'),(second,'record_2')):
        require(isinstance(obj,dict) and set(schema[key]['required_keys'])<=set(obj), 'missing inference_design author record keys: '+key)
        require(bool(obj['recorded_by']), 'empty author record provenance')
        try:
            d=date.fromisoformat(obj['author_local_date']); dt=datetime.fromisoformat(obj['recorded_utc'].replace('Z','+00:00'))
            require(dt.utcoffset().total_seconds()==0, 'author record must use UTC')
        except (ValueError,TypeError,AttributeError):
            raise FillError('invalid author record date')
        label='T4B' if key=='record_1' else 'T5'
        require(label in timestamps and d<=date.fromisoformat(timestamps[label]['local_date']), 'author record after '+label)
    require(first['choices'].get('r8_seeds')=='single','RUNBOOK I19: current arXiv R12b accepts single-seed R8 only')
    require(first['choices'].get('kcx')=='not_run' and first['choices'].get('public_registration')=='b_private_timestamps_only', 'source R6: KCX and public registration branch refused')
    require(first['a8_freeze_sha256']==A8_BINDINGS['A8_FREEZE.json'], 'author inference_design freeze identity drift')
    fields=schema['record_1']['fields']
    for k,spec in fields['choices'].items():
        require(first['choices'].get(k) in spec['allowed'], 'invalid author choice: '+k)
    instruction=first['instructions'].get('resource_only_continuation',{})
    spec=fields['instructions']['resource_only_continuation']
    require(instruction.get('value') is True and instruction.get('meaning_text')==spec['meaning_text'] and bool(instruction.get('author_words')), 'missing author continuation instruction')
    correction=first['statements'].get('extraction_model_correction')
    if isinstance(correction,dict):correction=correction.get('value')
    require(correction=='confirmed', 'missing extraction-model statement')
    entries=[e for e in first['confirmations'] if e.get('addendum')=='inference_design']
    require(len(entries)==1 and entries[0]['date']==first['author_local_date'] and bool(entries[0]['choices']), 'invalid inference_design confirmation entry')
    for obj,label,filename in ((first,'T4B','AUTHOR_CONFIRMATION_A8.json'),(second,'T5','AUTHOR_CONFIRMATION_A8_PRESCORE.json')):
        digest=timestamps[label]['files'].get(filename)
        require(isinstance(digest,str) and re.fullmatch('[0-9a-f]{64}',digest), 'author record not listed in '+label)
    require(second['record_1_sha256']==timestamps['T4B']['files']['AUTHOR_CONFIRMATION_A8.json'], 'record 2 first-record identity drift')
    kcx=second['kcx'];has=kcx.get('kcx_api_key_supplied_before_T5')
    require(type(has) is bool, 'invalid KCX key attestation')
    cap=kcx.get('kcx_spend_cap_usd')
    require((has and type(cap) in (int,float) and cap>0) or (not has and cap is None), 'invalid KCX spend cap')
    reg=second['registration']; vals=[reg.get(k) for k in ('registration_repository','registration_identifier','registration_embargo')]
    require(all(v is None for v in vals) or (vals[0] in ('OSF','Zenodo') and isinstance(vals[1],str) and bool(vals[1]) and type(vals[2]) is bool), 'inconsistent deposit record')
    if first['choices']['public_registration']=='b_private_timestamps_only':require(all(v is None for v in vals), 'private variant with public deposit')
    require(all(second['statements'].get(k) is True for k in schema['record_2']['fields']['statements']), 'missing inference_design prescore review statements')
    return author_title(first)


def author_context(confdir, timestamps):

    confdir=Path(confdir)
    names=('AUTHOR_CONFIRMATION_A8.json','AUTHOR_CONFIRMATION_A8_PRESCORE.json')
    require(all((confdir/n).is_file() for n in names), 'missing confirmation/AUTHOR_CONFIRMATION_A8.json or prescore record')
    first,second=(strict_json(confdir/n) for n in names)
    for n,label in zip(names,('T4B','T5')):
        require(sha256(confdir/n)==timestamps[label]['files'].get(n), 'author record SHA differs from '+label)
    validate_authors(first,second,timestamps)
    return first,second


def stage_rows(record):
    W=templates()['words']['STAGE_TABLE']
    three=record['author_confirmation']['choices']['r8_seeds']=='three'
    expected=[x.split(' (only')[0] for x in W['rows'] if three or not x.startswith('A8B-R8S')]
    rows=list(map(normalise_stage_row,record['stages']))
    require([x.get('stage') for x in rows]==expected, 'stage table must have 21 or 22 rows in frozen order')
    for row in rows:
        require(set(row)=={'stage','conf','postseal','counted_category','reason','rerun_trigger'} or set(row)=={'stage','conf','postseal','counted_category','reason','rerun_trigger','conf_reason'}, 'stage disposition interface drift')
        stage=row['stage']; own=stage in OWN_STAGES or stage.startswith('A8B-')
        require(row['counted_category'] in CATEGORIES, 'invalid stage counted category')
        if own:
            require(row['conf']=='--' and row['postseal']==row['counted_category'], 'own stage must use post-seal disposition')
            require(row['rerun_trigger'] is None, 'own stage cannot be CS8 rerun')
        elif row['postseal']!='--':
            require(stage in W['rerun_eligible'], 'stage not eligible for rerun')
            require(row['rerun_trigger'] in ('UNAVAILABLE_RESOURCE_BUDGET','No new fitting launches at the 24-hour deadline','24-hour deadline: unlaunched tasks remain'), 'unfrozen CS8 rerun trigger')
            require(row['conf']=='not run (frozen reason)' and row['counted_category']==row['postseal'], 'rerun counted from wrong disposition')
        else:
            require(row['conf']==row['counted_category'] and row['rerun_trigger'] is None, 'main-chain counted disposition drift')
        require(row['conf'] in (*CATEGORIES,'--') and row['postseal'] in (*CATEGORIES,'--'), 'invalid disposition')
        if row['counted_category']=='not run (frozen reason)':
            require((row['reason'] in templates()['forms'] or row['reason']=='A8NR_RESOURCE_A8AM2') and row['reason'].startswith('A8NR_') if own else row['reason']==('A8NR_PARITY' if row['postseal']!='--' and record.get('batch_parity_failed') is True else 'A4NR_BUDGET'), 'not-run stage needs frozen reason for its chain')
        if stage in ('A2B-1','A2B-2') and not record['optional']['batch_scoring']:
            require(row['counted_category']==CATEGORIES[-1], 'absent batch_scoring must be pending')
        if stage=='matched_controls' and record['pc_state']!='NOT_RUN_REPIN' and row['counted_category']==CATEGORIES[2]:require(row['reason']=='A8NR_BATCH_BUDGET', 'matched_controls extension not-run needs batch-budget reason')
        if stage=='KCX' and record['author_confirmation']['choices']['kcx']=='not_run':
            require(row['counted_category']==CATEGORIES[2] and row['reason']=='A8NR_AUTHOR', 'KCX author not-run branch drift')
    require(len(rows)==W['n_stages']['r8_three' if three else 'r8_single'], 'stage count drift')
    if record['pc_state']=='NOT_RUN_REPIN':
        require(all(x['counted_category']==CATEGORIES[2] and x['reason']=='A8NR_REPIN' for x in rows if x['stage'] in ('PC','matched_controls')), 'PC re-pin not-run disposition drift')
    elif record['pc_state']!='RESULT':
        require(all(x['counted_category']==CATEGORIES[4] for x in rows if x['stage'] in ('PC','matched_controls')), 'PC/matched_controls must be pending while base has no result')
    else:
        require(next(x['counted_category'] for x in rows if x['stage']=='PC') in CATEGORIES[:2], 'PC result requires a completed base disposition')
    return rows


def stage_text(record):
    rows=stage_rows(record); counts={c:sum(x['counted_category']==c for x in rows) for c in CATEGORIES}
    reruns=sum(x['postseal']!='--' and x['stage'] in templates()['words']['STAGE_TABLE']['rerun_eligible'] for x in rows)
    return form('A8ST_EXEC',total=str(len(rows)),table_ref='\\ref{supp:tab:table_results-stages}',done=str(counts[CATEGORIES[0]]),
                partial=str(counts[CATEGORIES[1]]),not_run=str(counts[CATEGORIES[2]]),deviation=str(counts[CATEGORIES[3]]),pending=str(counts[CATEGORIES[4]]),
                rerun=form('A8ST_RERUN',k=str(reruns)) if reruns else '',
                not_run_reasons=' ('+join(sorted(set(reason_text(x['reason']) for x in rows if x['counted_category']==CATEGORIES[2])))+')' if counts[CATEGORIES[2]] else '')


def human_review_sentences(record):

    from datetime import datetime
    h=record['human_review'];score=datetime.fromisoformat(h['score_utc'].replace('Z','+00:00'))
    def pre(item):
        v=h[item];time=v['completed_utc']
        if not time:return False
        t=datetime.fromisoformat(time.replace('Z','+00:00'))
        return t<score and t<=datetime.fromisoformat(record['timestamps']['T5']['utc'].replace('Z','+00:00')) and v['listed_in_T5'] is True
    output=[];missing=[k for k in ('review','second','agreement') if not pre(k)]
    if not missing:
        identity='A8HRC_PRE30' if h['path']=='original' and pre('historical') else 'A8HRC_PRE'
        require(h['path']!='original' or pre('historical'), 'original HRC path requires historical review before T5')
        output.append(form(identity,n_items='40',n_second='30',n_pairs='30' if identity=='A8HRC_PRE30' else '10'))
    else:
        require(h['deviation_record_listed_in_T5'] is True, 'HRC timing deviation lacks dated T5 record')
        what=join(templates()['words']['HRC_WHAT'][k] for k in missing)
        slots={'What':what[:1].upper()+what[1:],'was_were':'was' if len(missing)==1 else 'were'}
        output.append(form('A8HRC_DEV',**slots))


        for k in missing:
            v=h[k];name=templates()['words']['HRC_WHAT'][k];name=name[:1].upper()+name[1:]
            if v['completed_utc']:
                require(datetime.fromisoformat(v['completed_utc'].replace('Z','+00:00'))>score, 'unlisted prescore HRC completion cannot be relabelled postscore')
                output.append(form('A8HRC_POST_D',What=name,was_were='was' if k in ('review','agreement') else 'were'))
            else:output.append(form('A8HRC_PENDING_D',What=name))
    if h['path']=='HRC-inference_design':
        if h['historical']['completed_utc']:
            require(datetime.fromisoformat(h['historical']['completed_utc'].replace('Z','+00:00'))>score, 'historical HRC timing does not match postscore branch')
            output.append(form('A8HRC_POST',what='100 news articles, 60 notices and 20 historical pairs'))
        else:output.append(form('A8HRC_PENDING'))
    output.append(form('A8HRC_AID'))
    if h['further_aid']:
        require(isinstance(h['further_aid'],str), 'invalid further aid disclosure')
        output.append(form('A8HRC_AID_DEV',aid=h['further_aid']))
    return output


def registration_sentences(record, floor=False):
    first=record['author_confirmation'];second=record['author_prescore'];reg=second['registration']
    public=first['choices']['public_registration']=='a_deposit_before_T5' and reg['registration_identifier'] is not None
    if floor:return [sentence('PFMIN_EV_PUBLIC' if public else 'PFMIN_EV_PRIVATE')]
    return [sentence('A8EV_PUBLIC',embargo=form('A8EV_EMBARGO') if reg['registration_embargo'] else '') if public else sentence('A8EV_PRIVATE'),sentence('A8EXP_S')]


def registration_fixed(record):
    reg=record['author_prescore']['registration'];choice=record['author_confirmation']['choices']['public_registration']
    if choice=='a_deposit_before_T5' and reg['registration_identifier'] is not None:
        slots=dict(repository=reg['registration_repository'],identifier=reg['registration_identifier'],embargo=form('A8EV_EMBARGO') if reg['registration_embargo'] else '')
        return [form('A8REG_PUBLIC',**slots),form('A8CONTRIB2_PUBLIC',**slots)]
    out=[form('A8CONTRIB2_PRIVATE'),form('A8LIM_PRIVATE')]
    if choice=='a_deposit_before_T5':out.append(form('A8REG_FALLBACK'))
    return out


def validate_presentation(record):
    for k in ('author_confirmation','author_prescore','timestamps','stages','human_review','lear','pc_state','stage_table_ref','specified_reading_2000','cps8_kept_all','kept_alert_sentences','pv'):
        require(k in record, 'missing inference_design presentation input: '+k)
    validate_authors(record['author_confirmation'],record['author_prescore'],record['timestamps'])
    stages={row['stage']:row for row in stage_rows(record)};human_review_sentences(record)
    if record['cps8_kept_all']:require(stages['A8B-CPS8']['counted_category'] in CATEGORIES[:2], 'CPS8 kept-g0 claim without completed stage')
    require(record['pc_state'] in ('RESULT','PENDING','SPEED_PENDING','NOT_RUN_REPIN'), 'invalid planted-signal state')
    require(bool(record['specified_reading_2000']), 'frozen 2000-draw reading missing')
    lear=record['lear'];require(lear.get('class') in CLASSES, 'invalid LEAR class')
    decimal(lear['effect'],nullable=lear['class']=='NE')
    if lear['class']!='NE':require(len(str(abs(decimal(lear['effect']))))<=7, 'LEAR effect outside proven numeral width')
    require(not any(t['alert'] or t['signal_failed'] for t in record['tasks'].values()) or record['pc_state']=='RESULT', 'planted-signal result contradicts pending state')
    for task,t in record['tasks'].items():
        if t['alert']:
            expected=inherited_form('A6ALERT_S',task_label=kept_task_label(task))
            require(record['kept_alert_sentences'].get(task)==[expected], 'kept alert sentences must equal frozen A6ALERT_S for this task')
        else:require(not record['kept_alert_sentences'].get(task), 'alert sentence without an alert')
        require(t['reason'] in templates()['words']['PLAIN_INC_REASON'], 'unfrozen incomplete-task reason')
        for k in ('bound','mn_effect'):decimal(t[k],nullable=True)
        require(t.get('mn_class') in CLASSES, 'invalid activity/numeric class')
        require(type(t['signal_failed']) is bool, 'invalid planted-signal reading')
        if t['secondary_clause']=='DIFFERENT':require(t.get('secondary_differing_arms') and set(t['secondary_differing_arms']) <= {c['arm'] for c in t['contrasts']}, 'secondary dissent must name only differing members')
        require(t['secondary_check'] in templates()['words']['PLAIN_CHECK_NAMES'], 'unfrozen secondary check name')
        for c in t['contrasts']:
            if c['relations']['KCX']['state'] in ('SAME','DIFFERENT'):
                require(record['optional']['KCX'] and stages['KCX']['counted_category'] in CATEGORIES[:2] and record['author_confirmation']['choices']['kcx']=='run_if_key_before_T5' and record['author_prescore']['kcx']['kcx_api_key_supplied_before_T5'] is True, 'KCX relation without authorised completed result')
            if c['relations']['R8']['state'] in ('SAME','DIFFERENT'):
                require(record['optional']['R8'] and stages['A8B-R8N' if task=='notice' else 'A8B-R8']['counted_category'] in CATEGORIES[:2], 'R8 relation without completed result')
            if c['relations']['R8']['fully_checked']:
                require(record['author_confirmation']['choices']['r8_seeds']=='three', 'R8 robustness without author three-seed choice')
            require(c['reason'] in templates()['words']['PLAIN_INC_REASON'], 'unfrozen unevaluable reason')
            require(isinstance(c['design_layers'],list) and len(set(c['design_layers']))==len(c['design_layers']) and all(k in templates()['words']['PLAIN_LAYER'] and k not in ('windowed_activity','kcx','dly8_15','cps8') for k in c['design_layers']), 'unfrozen design layer')
            expected_dissent = c['class'] in ('IMP','DET') and (bool(c['design_layers']) or any(c['relations'][k]['state']=='DIFFERENT' and c['relations'][k]['class']!=c['class'] for k in ('DLY8','CPS8','KCX')))
            require(c['design_rejection_not_reproduced']==expected_dissent, 'design rejection non-reproduction contradicts inference_design layers')
            require(set(c['delay_classes'])=={'5','15','60'} and all(v in (*CLASSES,None) for v in c['delay_classes'].values()), 'DLY8 delay classes missing')
            for k in ('effect_percent','three_seed_effect'):
                if c[k] is not None:require(len(c[k])<=10 and ('.' not in c[k] or len(c[k].split('.')[-1])<=5), 'effect outside proven numeral width')
        if task=='notice' and t['clk8']['state']=='INFORMATIVE':
            require(type(t['clk8']['covered_n']) is int and t['clk8']['covered_n']>0, 'CLK8 coverage required from frozen result')
            require(0<=decimal(t['clk8']['maximum_delay_minutes']) and len(t['clk8']['maximum_delay_minutes'])<=5, 'clock delay outside proof width')
        if not any(c['class']=='IMP' for c in t['contrasts']) and t['bound'] is not None:
            require(0<=decimal(t['bound']) and len(t['bound'])<=7, 'bound outside proof width')


def class_key(c,t):
    if c['class']=='IMP' and t['alert']:return 'IMP_NC'
    if c['class'] in ('IMP','DET'):return c['class']+'_ROBUST' if robust(c,t['alert']) else c['class']+'_OTHER'
    return c['class']


def clk_sentence(t, floor=False):
    clk=t['clk8'];W=templates()['words']
    state=clk['state']
    if floor:
        key='NR' if state=='NOT_RUN' else 'NI' if state=='NOT_INFORMATIVE' else 'OK' if clock_ok(clk) else 'LATE'
        return W['PFMIN_CLK'][key].format(X=clk.get('public_by_admission'),Y=str(100-decimal(clk['public_by_admission'])) if state=='INFORMATIVE' else '',Z=clk.get('maximum_delay_minutes'))
    if state=='INFORMATIVE':
        if clock_ok(clk):return sentence('A8CLK_OK',X=clk['public_by_admission'],n=str(clk['covered_n']))
        return sentence('A8CLK_LATE',Y=str(100-decimal(clk['public_by_admission'])),n=str(clk['covered_n']),Z=clk['maximum_delay_minutes'])
    reason=clock_reason(clk)
    return sentence('A8CLK_NR' if state=='NOT_RUN' else 'A8CLK_NI',reason=reason)


def contrast_sentence(c,T,floor=False,alert=False):
    t={'alert':alert};W=T['words'];seven=form('A8SEVEN') if seven_undefined(c) and c['class']!='NE' else ''
    name=T['names'][c['arm']];name=name[:1].upper()+name[1:]
    if c['class']=='NE':return sentence('A8ITEM_NE',Name=name,reason=W['PLAIN_INC_REASON'][c['reason']])
    if c['class']=='NULL':return sentence('A8ITEM_NULL',Name=name,e=c['effect_percent'],seven=seven)
    slots=dict(Name=name,e=c['effect_percent'],cls=W['PLAIN_CLASS'][class_key(c,t)],seven=seven)
    if floor:return sentence('A8ITEM_REJ_NOINT',**slots)
    return sentence('A8ITEM_REJ',**slots,lo=c['family_one_day'][0],hi=c['family_one_day'][1],aud=c['effect_aud'])


def member_sentences(c,T,level,alert):
    W=T['words'];out=[]
    out.append(contrast_sentence(c,T,level!='P0',alert))
    fails=[W['PLAIN_CHECKS'][k] for k in CHECKS if c['checks'][k]=='FAIL'];missing=[W['PLAIN_CHECKS'][k] for k in CHECKS if c['checks'][k]=='UNAVAILABLE']
    if c['class']!='NE':
        if level in ('P2','PF') and (fails or missing):out.append(sentence('A8CHECKS_P2'))
        elif fails and missing:
            for i in range(0,max(len(fails),len(missing)),3):
                f,m=fails[i:i+3],missing[i:i+3]
                if f and m:out.append(sentence('A8CHECKS_BOTH',checks=join(f),unavailable=join(m)))
                elif f:out.append(sentence('A8CHECKS_FAIL',checks=join(f)))
                elif m:out.append(sentence('A8CHECKS_NFC',unavailable=join(m)))
        elif fails:
            for i in range(0,len(fails),3):out.append(sentence('A8CHECKS_FAIL',checks=join(fails[i:i+3])))
        elif missing:
            for i in range(0,len(missing),3):out.append(sentence('A8CHECKS_NFC',unavailable=join(missing[i:i+3])))
        elif level=='P0' and c['class'] in ('IMP','DET') and not alert:out.append(sentence('A8CHECKS_ROBUST'))
    if c['class'] in ('IMP','DET') and not robust(c,alert) and c['three_seed_class']!=c['class']:
        slots={'c3':W['PLAIN_C3'][c['three_seed_class']]}
        if level in ('P0','P1') and c['three_seed_effect'] is not None:out.append(sentence('A8SEED',**slots,e3=c['three_seed_effect']))
        else:out.append(sentence('A8SEED_NOEST',**slots))
    return out


def relation_sentences(task,t,T,level):
    W=T['words'];out=[];cs=t['contrasts']
    for c in cs:
        name=T['names'][c['arm']]
        if c['class'] in ('IMP','DET'):
            change='reduction' if c['class']=='IMP' else 'increase'
            r=c['relations']['R8'];phrase=None
            if c['class']=='IMP' and r['state']=='SAME' and level!='PF':
                identity='A8R8_SAME_ROBUST' if r['fully_checked'] and not t.get('alert',False) else 'A8R8_SAME_THREE' if t.get('_r8_seeds',r.get('seeds_run','single'))=='three' else 'A8R8_SAME'
                phrase=form(identity)
            elif r['state']=='DIFFERENT':phrase=form('A8R8_NOTREP')
            elif r['state'] in ('NOT_RUN','NOT_APPLICABLE'):out.append(sentence('A8R8_NR',reason=relation_reason(r,'R8',t)))
            elif r['state']=='NOT_EVALUABLE':out.append(sentence('A8R8_NE',reason=relation_reason(r,'R8',t)))
            if phrase:out.append(sentence('A8REL',change=change,names=name,was_were='was',phrase=phrase))
            for layer,identity in (('DLY8','A8DLY15_NOTREP'),('KCX','A8KCX_NOTREP')):
                r=c['relations'][layer]
                phrase=form(identity) if r['state']=='DIFFERENT' and r['class']!=c['class'] else form('A8KCX_SAME') if c['class']=='IMP' and layer=='KCX' and r['state']=='SAME' and level!='PF' else None
                if phrase:out.append(sentence('A8REL',change=change,names=name,was_were='was',phrase=phrase))
        if c['class'] in ('IMP','DET'):
            for k in list(dict.fromkeys(c['design_layers']+(['cps8'] if c['relations']['CPS8']['state']=='DIFFERENT' and c['relations']['CPS8']['class']!=c['class'] else []))):
                out.append(sentence('A8REL',change='reduction' if c['class']=='IMP' else 'increase',names=name,was_were='was',phrase=form('A8DISSENT',layer=W['PLAIN_LAYER'][k])))
        if task=='notice' and t['clk8']['state']=='INFORMATIVE' and not clock_ok(t['clk8']):
            ds=c['delay_classes']
            if all(ds[k] is not None for k in ('15','60')):
                if level!='PF' or any(ds[k]!=c['class'] for k in ('15','60')):
                    out.append(sentence('A8DLY_LATE',name=name,c15=W['PLAIN_C3'][ds['15']],c60=W['PLAIN_C3'][ds['60']]))
            else:
                if t.get('_dly8_category')==CATEGORIES[3]:out.append(sentence('A8DLY_DEV'))
                else:out.append(sentence('A8DLY_NR',reason=W['PLAIN_INC_REASON'][c['reason']] if c['class']=='NE' else relation_reason(c['relations']['DLY8'],'DLY8',t)))
    return list(dict.fromkeys(out))


def task_tail_sentences(task,t,T,level):
    W=T['words'];out=[];cs=t['contrasts']
    if not any(c['class']=='IMP' for c in cs) and t['bound'] is not None:
        out.append(sentence('A8BOUND_NC' if t['alert'] else 'A8BOUND',X=t['bound'],seven=form('A8SEVEN') if any(c['class']!='NE' and seven_undefined(c) for c in cs) else '',sens=form('A8SENS_A') if t['signal_failed'] else ''))
    elif t['signal_failed']:

        out.append(form('A8SENS_B')[2:].capitalize()+'.')
    if level=='P0' and t['mn_effect'] is not None:out.append(sentence('A8MN',activity_words=W['PLAIN_ACTIVITY'][task],mn=t['mn_effect'],cls=W['PLAIN_C3'][t['mn_class']]))
    return out


def task_sentences(task,t,T,floor=False,level=None):
    level=level or ('PF' if floor else 'P0');t=deepcopy(t);W=T['words'];cs=t['contrasts'];out=[]
    if task=='notice':out.append(clk_sentence(t))
    if not t['complete']:
        out.append(sentence('A8AB_INC',task_label=W['PLAIN_TASK_LABEL'][task],reason=W['PLAIN_INC_REASON'][t['reason']]))
        return out
    out.append(sentence('A8HEAD',task_head=W['PLAIN_TASK_HEAD'][task],n_words=W['PLAIN_NUMBER'][str(len(cs))],activity_ref=W['PLAIN_ACTIVITY_REF'][task]))
    merged=set()
    for c in cs:
        if level in ('P2','PF') and c['class']=='NULL':
            state=seven_undefined(c)
            if state in merged:continue
            merged.add(state);group=[x for x in cs if x['class']=='NULL' and seven_undefined(x)==state]
            pending=[]
            for member in group:
                trial=pending+[member]
                def merged_text(items):
                    names=join(T['names'][x['arm']] for x in items);names=names[:1].upper()+names[1:]
                    return form('A8ITEM_NULLS',Names=names,values=', '.join(x['effect_percent']+'%' for x in items),seven=form('A8SEVEN') if state else '')
                if pending and words(merged_text(trial))>35:out.append(merged_text(pending));pending=[member]
                else:pending=trial
            if pending:out.append(merged_text(pending))

            if any(any(v!='PASS' for v in x['checks'].values()) for x in group):out.append(sentence('A8CHECKS_P2'))
            continue
        out+=member_sentences(c,T,level,t['alert'])
    out+=relation_sentences(task,t,T,level)
    out+=task_tail_sentences(task,t,T,level)
    return out


def secondary_sentences(record, floor=False):
    T=templates();tasks=[(task,t) for task,t in record['tasks'].items() if not any(c['class']=='IMP' for c in t['contrasts'])]
    if not tasks:return []
    differing=[(task,t) for task,t in tasks if t['secondary_clause']=='DIFFERENT']
    if differing:
        if floor:return [sentence('PFMIN_SEC_DIFF')]
        return [sentence('A8SEC_DIFF',check=T['words']['PLAIN_CHECK_NAMES'][t['secondary_check']],names=join(T['names'][arm] for arm in t.get('secondary_differing_arms',[]))) for task,t in differing]
    return [sentence(('PFMIN_SEC_NA' if floor else 'A8SEC_NA') if any(t['secondary_clause']=='NOT_RUN' for _,t in tasks) else ('PFMIN_SEC_SAME' if floor else 'A8SEC_SAME'))]


def pfmin_item(c,t):
    W=templates()['words'];name=W['PFMIN_NAMES'][c['arm']]
    if c['class']=='NE':return form('PFMIN_ITEM_NE',name=name)
    ck=class_key(c,t).replace('_OTHER','');seed=''
    if c['class'] in ('IMP','DET') and not robust(c,t['alert']) and c['three_seed_class']!=c['class']:
        c3=floor_word('PFMIN_C3',c['three_seed_class'],'PFMIN cannot encode unavailable differing three-seed class; upstream N0 required')
        seed=form('PFMIN_SEED',c3=c3)
    return form('PFMIN_ITEM',name=name,e=c['effect_percent'],cls=W['PFMIN_CLASS'][ck],seed=seed)


def pfmin_render(record):
    T=templates();W=T['words'];parts=[sentence('PFMIN_DS'),*registration_sentences(record,True),sentence('PFMIN_CUT')]
    lear=record['lear']
    parts.append(sentence('PFMIN_LEAR_NE') if lear['class']=='NE' else sentence('PFMIN_LEAR',abs=str(abs(decimal(lear['effect']))),lower_higher='lower' if decimal(lear['effect'])<0 else 'higher',cls=W['PFMIN_CLASS_LEAR'][lear['class']]))
    task_text={};seven=[];notrobust=False;key_layers=set();notrep=False
    for task,t in record['tasks'].items():
        ss=[]
        if task=='notice':ss.append(clk_sentence(t,True))
        if not t['complete']:
            reason=floor_word('PFMIN_INC_REASON',t['reason'],'no frozen PFMIN incomplete reason for '+t['reason'])
            ss.append(sentence('PFMIN_INC',head=W['PFMIN_HEAD'][task],reason=reason))
        else:
            items=[]
            for c in t['contrasts']:
                name=W['PFMIN_NAMES'][c['arm']]
                items.append(pfmin_item(c,t))
                if c['class']=='NE':continue
                if seven_undefined(c):seven.append(name)
                notrobust |= c['class'] in ('IMP','DET') and (not all(v=='PASS' for v in c['checks'].values()) or seven_undefined(c))
                for layer in ('R8','DLY8','KCX'):
                    if c['class'] in ('IMP','DET') and c['relations'][layer]['state']=='DIFFERENT':key_layers.add(layer)
                if c['class'] in ('IMP','DET') and (c['design_layers'] or c['relations']['CPS8']['state']=='DIFFERENT' and c['relations']['CPS8']['class']!=c['class']):notrep=True
                if task=='notice' and c['class'] in ('IMP','DET') and any(v is not None and v!=c['class'] for k,v in c['delay_classes'].items() if k=='15' or k=='60' and state_informative(t['clk8']) and not clock_ok(t['clk8'])):key_layers.add('DLY8')
            ss.append(sentence('PFMIN_TASK',head=W['PFMIN_HEAD'][task],items='; '.join(items)))
            if not any(c['class']=='IMP' for c in t['contrasts']) and t['bound'] is not None:
                ss.append(sentence('PFMIN_BOUND_NC' if t['alert'] else 'PFMIN_BOUND',head=W['PFMIN_HEAD'][task],X=t['bound'],seven=form('PFMIN_SEVEN') if any(seven_undefined(c) for c in t['contrasts'] if c['class']!='NE') else '',sens=form('PFMIN_SENS') if t['signal_failed'] else ''))
            elif t['signal_failed']:ss.append(sentence('PFMIN_NULL_SENS',head=W['PFMIN_HEAD'][task]))
        task_text[task]=' '.join(ss);parts+=ss
    if seven:parts.append(sentence('PFMIN_SEVEN_S',names=join(seven)))
    if notrobust:parts.append(sentence('PFMIN_NOTROBUST'))
    if key_layers:parts.append(sentence('PFMIN_NOTREP_KEY',key=join(W['PFMIN_KEY_LAYERS'][k] for k in ('R8','DLY8','KCX') if k in key_layers)))
    elif notrep:parts.append(sentence('PFMIN_NOTREP'))
    alerts=[k for k,t in record['tasks'].items() if t['alert']]
    if alerts:parts.append(sentence('PFMIN_ALERT',tasks=W['PFMIN_ALERT_TASKS']['both' if len(alerts)==2 else alerts[0]]))
    elif record['pc_state']!='RESULT':parts.append(sentence('PFMIN_PCNR'))
    if any(c['class']=='IMP' for t in record['tasks'].values() for c in t['contrasts']):parts.append(sentence('PFMIN_ATTR'))
    parts+=secondary_sentences(record,True)
    return pack(parts,task_text,'PFMIN')


def pack(parts,tasks,level):
    text=' '.join(parts)
    require(all(words(s)<=35 for s in parts), 'plain sentence over 35 words')
    return {'text':text,'tasks':tasks,'words':words(text),'characters':len(text),'sentence_max':max(map(words,parts)), 'sentences':parts,'level':level,'floor':level=='PFMIN'}


def plain_render(record,floor=False,level=None):
    level=level or ('PFMIN' if floor else 'P0')
    if level=='PFMIN':return pfmin_render(record)
    T=templates();W=T['words'];parts=[form('A8DS'),*registration_sentences(record),sentence('A8CUT_S')]

    parts=[s for p in parts for s in re.split(r'(?<=[.!?])\s+(?=[A-Z])',p)]
    lear=record['lear'];parts.append(sentence('A8LEAR_NE',reason=W['PLAIN_INC_REASON'][lear['reason']]) if lear['class']=='NE' else sentence('A8LEAR',abs=str(abs(decimal(lear['effect']))),lower_higher='lower' if decimal(lear['effect'])<0 else 'higher',cls=W['PLAIN_LEAR_CLASS'][lear['class']]))
    tasks={}
    for task,t in record['tasks'].items():
        ss=task_sentences(task,task_context(record,task),T,level=level);tasks[task]=' '.join(ss);parts+=ss
    if record['pc_state']!='RESULT':parts.append(sentence('A8PCNR'))
    alerts=[k for k,t in record['tasks'].items() if t['alert']]
    if alerts:parts.append(sentence('A8ALERT',tasks=W['PFMIN_ALERT_TASKS']['both' if len(alerts)==2 else alerts[0]]))
    if any(c['class']=='IMP' for t in record['tasks'].values() for c in t['contrasts']):parts.append(sentence('A8ATTR'))
    parts+=secondary_sentences(record)
    return pack(parts,tasks,level)


def render(record):
    validate_record(record)
    for level in LEVELS:
        result=plain_render(record,level=level)
        if result['words']<=250 and result['characters']<=1920:return result
    raise FillError('ABSTRACT_LIMIT: no frozen level meets 250 words and 1920 characters')

def tex(text):
    substitutions = {'\\':r'\textbackslash{}','{':r'\{','}':r'\}','%':r'\%','&':r'\&','#':r'\#','_':r'\_','$':r'\$','~':r'\textasciitilde{}','^':r'\textasciicircum{}'}
    return ''.join(substitutions.get(ch,ch) for ch in text)

def claim_registry(record, rendered):
    T=templates();out={'global/abstract/reading':rendered['text']}
    for task,t in record['tasks'].items():
        p0=' '.join(task_sentences(task,task_context(record,task),T,level='P0'))
        out[f'{task}/task/reading']=rendered['tasks'][task]
        out[f'{task}/task/lead']=p0

        conclusion=p0
        if any(c['class']=='IMP' for c in t['contrasts']):
            conclusion+=' '+form('A8CONC_QUAL',increments='increment' if sum(c['class']=='IMP' for c in t['contrasts'])==1 else 'increments',exposure=form('A8EXPOSURE'),cutoff=form('A8CUTOFF'))
        out[f'{task}/task/conclusion']=conclusion
        for c in t['contrasts']:
            key=f"{task}/{c['arm']}-{c['reference']}/"
            q=form('A8SEVEN') if c['class']!='NE' and seven_undefined(c) else ''
            out.update({key+'class':T['words']['PLAIN_CLASS'][class_key(c,t)]+q,
                        key+'robustness':__import__('table_renderer.complete_fill',fromlist=['six_label']).six_label(c,t),
                        key+'effectPercent':c['effect_percent']+'%'+q if c['effect_percent'] is not None else 'not evaluable',
                        key+'effectAUD':c['effect_aud']+' AUD/MWh'+q if c['effect_aud'] is not None else 'not evaluable',
                        key+'interval':'['+', '.join(c['family_one_day'])+']%'+q if c['family_one_day'] else 'not evaluable',
                        key+'envelope':c['envelope']+'%'+q if c['envelope'] is not None else 'unavailable',
                        key+'reading':contrast_sentence(c,T,False,t['alert']),key+'qualifiers':q})
    return out

def claim_definitions(registry):
    lines = ['% Generated from RS8; immutable after scoring.']
    for key, value in registry.items():
        require(bool(re.fullmatch(r'[A-Za-z0-9_+/-]+',key)), 'unsafe claim key')
        lines.append(r'\expandafter\def\csname Dres@'+key+r'\endcsname{'+claim_tex(value)+'}')
    return '\n'.join(lines)+'\n'

def postscore_diff(reference_snapshot, after, registry, record, facts):
    from check_table_sources import source_problems, macro_calls
    from table_results_diff import changed_paragraphs
    changes = []
    require(set(reference_snapshot)==set(after), 'postscore edits may not add or remove files')
    for rel in sorted(reference_snapshot):
        old, new = reference_snapshot[rel], after[rel]
        require(macro_calls(old)==macro_calls(new), 'postscore claim macro changed: '+rel)
        require(all(not source_problems(p,registry,record,facts) for p in changed_paragraphs(old,new)), 'postscore claim edit refused: '+rel)
        if old!=new:
            changes.append({'file':rel,'old_sha256':text_hash(old),'new_sha256':text_hash(new),
                            'diff':''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))})
    return changes

def frozen_template(name, **slots):
    pattern=templates()['frozen_templates'][name]
    require(set(re.findall(r'<<([a-z0-9_]+)>>',pattern))==set(slots), 'frozen template slot mismatch: '+name)
    for key,value in slots.items():pattern=pattern.replace('<<'+key+'>>',value)
    return pattern


def prospective_sentence(record):
    pv=record['pv']
    if pv is None:return ''
    from datetime import datetime
    require(pv['verified_both_authorities'] is True and pv['lists_design_files'] is True, 'PV_T0a verification missing')
    require(datetime.fromisoformat(pv['utc'].replace('Z','+00:00'))<datetime.fromisoformat(record['human_review']['score_utc'].replace('Z','+00:00')), 'PV_T0a must precede score receipt')
    return form('A8PV',label=pv['label'],identifier='; '+pv['identifier'] if pv['identifier'] else '')


@lru_cache(maxsize=4096)
def inherited_form(identity, **slots):

    f=strict_json(inference_design/'A8_FREEZE.json')
    for rel in ('studies/confirmation/robustness_tests/RULES_FOR_MAIN_COMPARISONS.json','studies/confirmation/sensitivity_tests/RULES_FOR_FILL3A.json','studies/confirmation/A6/RULES_FOR_SENSITIVITY_COMPARISONS.json'):
        path=PROJ/rel
        require(sha256(path)==f['binds'][rel], 'inherited rule identity drift')
        sheet=strict_json(path)

        for values in sheet.values():
            if isinstance(values,dict) and isinstance(values.get(identity),str):
                pattern=values[identity]


                slots={k:v.removesuffix('.') if '{'+k+'};' in pattern else v for k,v in slots.items()}
                return pattern.format(**slots)
    raise FillError('missing inherited frozen form: '+identity)


def branch_sentences(record):
    rows={x['stage']:x for x in stage_rows(record)};out=[]
    if not record['optional']['batch_scoring']:out.append(form('A8PEND_A2B'))
    if not record['optional']['ISOBATCH']:out.append(form('A8PEND_ISO'))
    pc=record['pc_state']
    if pc!='RESULT':
        reason=form('A8NR_SPEED') if pc=='SPEED_PENDING' else form('A8NR_REPIN') if pc=='NOT_RUN_REPIN' else 'it had no result at the cut-off'
        out.append(form('A8PEND_PC',reason=reason))
        if pc in ('SPEED_PENDING','NOT_RUN_REPIN'):out += [inherited_form('A3PS_NOTRUN',task_label=kept_task_label(task),reason=reason) for task in ARMS]
    elif rows['matched_controls']['counted_category']==CATEGORIES[2]:
        out.append(inherited_form('A4PX_NOT2',reason=form(rows['matched_controls']['reason']),R0='40'))
    kcx=rows['KCX']
    if kcx['counted_category']==CATEGORIES[2]:out.append(form('A8KCX_NR',reason=form(kcx['reason'])))
    elif kcx['counted_category']==CATEGORIES[3]:
        require(kcx['reason'] in ('A8DEV_CAP','A8DEV_API'), 'KCX deviation needs frozen reason')
        out.append(form('A8KCX_DEV',reason=form(kcx['reason'])))
    elif kcx['counted_category']==CATEGORIES[4]:out.append(form('A8KCX_PENDING'))
    if rows['A8B-R8']['counted_category']==CATEGORIES[2]:out.append('For day-ahead news, '+form('A8R8_NR',reason=reason_text(rows['A8B-R8']['reason'])))
    dly=rows['DLY8']
    if dly['counted_category']==CATEGORIES[2]:out.append(form('A8DLY_NR',reason=form(dly['reason'])))
    elif dly['counted_category']==CATEGORIES[3]:out.append(form('A8DLY_DEV'))
    if record['cps8_kept_all']:out += [form('A8CPS_KEPT',task_label=kept_task_label(task)) for task in ARMS]
    for row in rows.values():
        if row['rerun_trigger'] and row['counted_category']==CATEGORIES[3]:pass
    return out


def conclusion_caps(record):
    rows={x['stage']:x for x in stage_rows(record)};bad=lambda s:rows[s]['counted_category'] not in CATEGORIES[:2]
    out=[]
    if bad('secondary_LEAR'):out.append(inherited_form('A4CAP_LEAR'))
    if bad('secondary_news') or bad('secondary_notice'):out.append(inherited_form('A4CAP_CHEAP'))
    if bad('A2B-1'):out.append(inherited_form('A4CAP_L1'))
    if bad('A2B-2'):out.append(inherited_form('A4CAP_PD'))
    if record['pc_state']!='RESULT':out.append(form('A8PCNR'))
    alerts=[task for task,t in record['tasks'].items() if t['alert']]
    if alerts:out.append(inherited_form('A6ALERT',tasks=join({'news':'day-ahead news','notice':'5–30-minute notices'}[task] for task in alerts)))
    out.append(inherited_form('A4CAP_ALL'))
    out.append(inherited_form('A6ATTR'))
    return out


def render_bundle(record, bindings):
    validate_record(record,bindings)
    if 'author_confirmation' in bindings:
        require(record['author_confirmation']==bindings['author_confirmation'] and record['author_prescore']==bindings['author_prescore'], 'RS8 author choice differs from named confirmation records')
    result=render(record);registry=claim_registry(record,result);T=templates()
    n0=record['specified_reading_n0']
    from check_table_sources import banned_problems
    if not record.get('n0_forms'):require(not banned_problems(n0), 'banned phrase in specified RS8 reading')
    macro=lambda task,pair,field:r'\Dres{'+task+'}{'+pair+'}{'+field+'}'
    registry['global/stages/reading']=stage_text(record)
    registry['global/branches/reading']=' '.join(branch_sentences(record))
    registry['global/hrc/reading']=' '.join(human_review_sentences(record))
    registry['global/registration/reading']=' '.join(registration_fixed(record))
    registry['global/conclusion/caps']=' '.join(conclusion_caps(record))
    if prospective_sentence(record):registry['global/pv/reading']=prospective_sentence(record)
    registry['global/author/reading']=form('A8AUTH',date=record['author_confirmation']['author_local_date'],date2=record['author_prescore']['author_local_date'],label4b='T4B',label5='T5')
    rows=[];detail=[]
    for task,t in record['tasks'].items():
        for c in t['contrasts']:
            pair=c['arm']+'-'+c['reference'];key=task+'/'+pair+'/'
            rows.append(tex(task+' '+pair)+' & '+' & '.join(macro(task,pair,k) for k in ('effectAUD','effectPercent','interval','envelope','reading'))+r' \\')
            registry[key+'cheap']='not assigned under a negative-control alert' if t['alert'] else cheap_text(c)
            if c['class']=='IMP' and not robust(c,t['alert']) and not t['alert']:pass
            sq=c['squared_loss']
            registry[key+'squared']=(form('A8SQ',arm=T['names'][c['arm']],activity=T['words']['PLAIN_ACTIVITY'][task].removeprefix('the ').removesuffix(' reference'),e=sq['effect'],p=sq['p']) if sq['state']=='COMPUTED' else 'Squared-loss descriptive: pending (no result file at fill time)')
            detail += [macro(task,pair,'cheap')+r'\par']
    stage_lines=[]
    for i,row in enumerate(stage_rows(record)):
        for k in ('conf','postseal','counted_category'):
            value=row[k]
            if value==CATEGORIES[2]:
                reason=row.get('conf_reason') if k=='conf' and row['postseal']!='--' else row['reason']
                if reason is None and k=='conf':reason='A4NR_BUDGET'
                value='not run ('+reason_text(reason)+')'
            registry[f'global/stage{i}/{k}']=value
        stage_lines.append(tex(stage_name(row['stage']))+' & '+' & '.join(macro('global','stage'+str(i),k) for k in ('conf','postseal','counted_category'))+r' \\')
    out={'TABLE_RESULTS_RS8_N0.txt':n0,'TABLE_RESULTS_RS8_N0.tex':tex(n0)+'\n',
         'TABLE_RESULTS_RS8_2000.tex':tex('Frozen 2,000-draw reading')+r'\par'+'\n'+tex(rename_rendered(record['specified_reading_2000']))+'\n',
         'arxiv_abstract.txt':result['text']+'\n',
         'TABLE_RESULTS_abstract.tex':macro('global','abstract','reading')+'\n',
         'TABLE_RESULTS_leads.tex':'\n\n'.join(macro(task,'task','lead') for task in ARMS)+'\n',
         'TABLE_RESULTS_conclusion.tex':'\n\n'.join(macro(task,'task','conclusion') for task in ARMS)+'\n'+macro('global','conclusion','caps')+'\n',
         'TABLE_RESULTS_fixed.tex':'\n'.join(macro('global',k,'reading')+r'\par' for k in ('registration','hrc','author'))+'\n',
         'TABLE_RESULTS_title.tex':r'\title{'+tex(author_title(record['author_confirmation']))+'}\n',
         'TABLE_RESULTS_tables.tex':r'\begin{longtable}{lllllp{.35\linewidth}}'+'\n'+r'Task and contrast & AUD/MWh & Effect & Family interval & Envelope & Reading \\'+'\n'+'\n'.join(rows)+'\n'+r'\end{longtable}'+'\n'+'\n'.join(detail)+'\n'+macro('global','branches','reading')+'\n',
         'TABLE_RESULTS_stages.tex':r'\begin{longtable}{lp{.2\linewidth}p{.2\linewidth}p{.2\linewidth}}'+'\n'+r'\caption{'+tex(T['frozen_templates']['stage_table_caption'])+'}\\label{supp:tab:table_results-stages}\\\\'+'\n'+'Stage & Main fitting chain (confirmation) & Post-seal batch or own run & Category \\\\'+'\n'+'\n'.join(stage_lines)+'\n'+r'\end{longtable}'+'\n'+macro('global','stages','reading')+'\n',
         'TABLE_RESULTS_LAT8.tex':'\n' + tex('Capture-latency diagnostic: pending (no result file when filled); descriptive only.')+'\n'}
    status_rows=[]
    stage_by_name={x['stage']:x for x in stage_rows(record)}
    for key,present in record['optional'].items():
        state='result present; see full reading record under the frozen rules' if present else T['absent'][key]
        if key in ('KCX','matched_controls','R8'):
            counted_category=stage_by_name['A8B-R8' if key=='R8' else key]['counted_category']
            if counted_category==CATEGORIES[4]:state='pending (no result file at fill time)'
            elif counted_category==CATEGORIES[3]:state='deviation from the frozen design'
        registry['global/'+key+'/status']=state
        status_rows.append(tex({'batch_scoring':'Batch-context label comparison','ISOBATCH':'Isolated-label comparison','matched_controls':'Planted-signal null extension','KCX':'Known-cutoff label replacement','R8':'Richer source-metadata reference'}[key])+': '+macro('global',key,'status')+r'\par')
    out['TABLE_RESULTS_statuses.tex']='\n'.join(status_rows)+'\n'
    out['TABLE_RESULTS_captions.tex']=frozen_template('table6_caption',marks=T['frozen_templates']['table6_mark_seven'] if any(c['class']!='NE' and seven_undefined(c) for t in record['tasks'].values() for c in t['contrasts']) else '',table_ref='\\ref{tab:main_comparisons-sensitivity}')+'\n'+frozen_template('figure_caption')+'\n'+frozen_template('primary_intro')+'\n'
    if prospective_sentence(record):out['TABLE_RESULTS_fixed.tex']+=macro('global','pv','reading')+'\n'
    out['TABLE_RESULTS_claim_values.tex']=claim_definitions(registry)
    require(isinstance(bindings['facts'].get('rendered_sentences'),dict), 'require rendered_sentences by document')
    expected={doc:[registry[task+'/task/lead'] for task in ARMS] for doc in ('main','supplement')}
    expected['main'] += [result['text'],registry['global/registration/reading'],registry['global/hrc/reading'],registry['global/author/reading']]
    expected['supplement'] += [n0,'Frozen 2,000-draw reading',rename_rendered(record['specified_reading_2000']),stage_text(record),registry['global/branches/reading']]
    manifest={'schema':'K8_EXPECTATIONS_V1','record':record,'registry':registry,'expected':expected,'facts':bindings['facts'],
              'abstract_words':result['words'],'abstract_characters':result['characters'],'abstract_text':result['text'],'abstract_level':result['level'],
              'floor':result['floor'],'authority_sha256':A8_BINDINGS,'title':author_title(record['author_confirmation'])}
    from table_renderer.complete_fill import complete_bundle
    return complete_bundle(record, bindings, out, manifest)

def stage_name(stage):
    names=templates()['words']['STAGE_TABLE']['names_new']
    old={'primary_news':'Primary news','primary_notice':'Primary notices','report_only_2025_validation':'Report-only 2025 validation',
         'secondary_news':'Secondary news family','secondary_notice':'Secondary notice family','secondary_LEAR':'Price-only benchmark',
         'primary_seed_robustness_news':'News seed check','primary_seed_robustness_notice':'Notice seed check','window_24h':'Twenty-four-hour window',
         'first_L_news':'First news chunk','first_L_notice':'First notice chunk','A2B-1':'Alternative objective family','A2B-2':'Pre-dispatch family',
         'label_scoring':'Independent label replacement','PC':'Planted-signal check','matched_controls':'Planted-signal null extension'}
    require(stage in names or stage in old, 'unknown stage display name')
    return names.get(stage,old.get(stage))


def rename_rendered(text):
    from table_renderer.prepare_table_fields import named
    return named(text,source=False)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--a8-postscore',type=Path,required=True)
    p.add_argument('--source-receipt',type=Path,required=True,help='completed SCORE_RECEIPT, source post-T5 slot only')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--refill',type=Path,help='previous F copy; only specified later inputs may change')
    p.add_argument('--later-inputs',type=Path)
    p.add_argument('--score-source-anchor',type=Path,required=True,help='source snapshot bound to SCORE_RECEIPT')
    p.add_argument('--render-figure',action='store_true',required=True,help='required for the complete source fill; frozen E numeric figure generator')
    p.add_argument('--timestamps',type=Path,required=True,help='verified T4B/T5 author-record coverage, UTC and local dates')
    a=p.parse_args(argv)
    bindings=timestamp_checks()
    first,second=author_context(inference_design.parent,strict_json(a.timestamps))
    bindings.update(author_confirmation=first,author_prescore=second)
    E=load_summary_comparisons()
    record=strict_json(a.read_comparisons)
    require(record['timestamps']==strict_json(a.timestamps), 'timestamp coverage drift')
    receipt=strict_json(a.source_receipt)
    require(record['identities']['source_receipt_sha256']==sha256(a.source_receipt), 'source receipt identity drift')
    require(receipt.get('state')=='FROZEN_SCORE_COMPLETE', 'completed SCORE_RECEIPT required; standalone FILL3f needs no E receipt')
    verify_clock_binding(record)
    from table_renderer.complete_fill import validate_complete_inputs
    validate_complete_inputs(record,refill=bool(a.refill))
    if a.refill:
        old=strict_json(a.refill/'TABLE_RESULTS_K8_EXPECTATIONS.json')
        require(old['record']['identities']['source_receipt_sha256']==record['identities']['source_receipt_sha256'], 'refill changed primary score receipt')
        require(a.later_inputs is not None, 'refill requires specified later-input identities')
    files,manifest=render_bundle(record,bindings)
    from table_renderer.prepare_table_fields import generate
    _,prefill,sources=generate(record['author_confirmation'],return_sources=True,record=record)
    manifest['prefill_sha256']=prefill['proposed_outputs_sha256']
    from table_results_diff import audit
    anchor=strict_json(a.score_source_anchor)
    before_root=a.refill if a.refill else MS
    reference_snapshot={rel:(before_root/rel).read_text() for rel in anchor['source_sha256']}
    combined={**sources,**files}

    planned=dict(manifest,generated_sha256={rel:text_hash(text) for rel,text in combined.items()})
    diff=audit(reference_snapshot,combined,planned,anchor,'refill' if a.refill else 'fill',strict_json(a.later_inputs) if a.later_inputs else None)
    manifest['postscore_changed']=diff['postscore_changed']
    files=combined
    require(not a.out.exists(), 'output already exists; refuse overwrite')
    a.out.mkdir(parents=True)
    for rel,text in files.items():
        q=a.out/rel;q.parent.mkdir(parents=True,exist_ok=True);q.write_text(text)
    import shutil
    from check_arxiv import graphic_dependencies
    graphics,_=graphic_dependencies(MS,'\n'.join(sources.values()))
    for q in graphics:
        dest=a.out/q.relative_to(MS);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(q,dest)
    for rel in ('claims.sty','check_arxiv.py'):
        shutil.copyfile(MS/rel,a.out/rel)

    if a.render_figure:
        from table_renderer.complete_fill import inherited_figure
        pdf,csv_text=inherited_figure(record)
        (a.out/'figures').mkdir(exist_ok=True)
        (a.out/'figures/TABLE_RESULTS_forest.pdf').write_bytes(pdf)
        (a.out/'TABLE_RESULTS_forest.csv').write_text(csv_text)
    (a.out/'TABLE_RESULTS_POSTSCORE_DIFF.json').write_text(json.dumps(diff,indent=2)+'\n')
    (a.out/'TABLE_RESULTS_RECEIPT.json').write_text(json.dumps({'schema':'TABLE_RESULTS_SOURCE_FILL_RECEIPT_V1','state':'STANDALONE_SOURCE_FILL_COMPLETE','source_receipt_sha256':sha256(a.source_receipt),'postscore_sha256':sha256(a.read_comparisons),'timestamps_sha256':sha256(a.timestamps),'generated_sha256':manifest['generated_sha256'],'prefill_sha256':manifest['prefill_sha256']},indent=2)+'\n')
    import csv,io
    trace=io.StringIO();w=csv.DictWriter(trace,fieldnames=['file','category','score_receipt_sha256','old_sha256','new_sha256']);w.writeheader();w.writerows({k:r[k] for k in w.fieldnames} for r in diff['changes'])
    (a.out/'TABLE_RESULTS_PSB_TRACE.csv').write_text(trace.getvalue())
    from table_renderer.copy_support import install_support
    install_support(a.out,manifest)
    (a.out/'TABLE_RESULTS_K8_EXPECTATIONS.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'state':'STANDALONE_SOURCE_FILL_COMPLETE','outputs':{r:sha256(a.out/r) for r in files},'abstract_words':manifest['abstract_words']},indent=2))
    return 0


def kept_task_label(task):
    sheet=strict_json(PROJ/'studies/confirmation/A6/RULES_FOR_SENSITIVITY_COMPARISONS.json')
    return sheet['words']['TASK_LABEL'][task]

def claim_tex(value):
    from table_renderer.tex_values import claim_tex as convert
    return convert(value)

if __name__=='__main__':
    try: sys.exit(main())
    except (FillError,OSError,KeyError,ValueError,TypeError) as exc:
        print('FILL REFUSED: '+str(exc),file=sys.stderr)
        sys.exit(2)
