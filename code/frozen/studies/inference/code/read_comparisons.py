
'Read checked forecasts and truth to reproduce statistical comparisons.'
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parents[1]
PROJ = HERE.parents[2]
confirmation = PROJ / 'studies/confirmation'
MS = PROJ / 'tables'
DRAWS, SEED = 100000, 20260925
PAIRS = {'news': [('L_count', 'M'), ('L_chen', 'M')],
         'notice': [('L14', 'M_notice'), ('L_Laz', 'M_notice'), ('L_chen_notice', 'M_notice')]}
CLASS = {'CONDITIONAL_IMPROVEMENT': 'IMP', 'CONDITIONAL_DETERIORATION': 'DET',
         'NO_RELIABLE_INCREMENT_DETECTED': 'NULL', 'NOT_EVALUABLE': 'NE'}
CLASS_INV = {v:k for k,v in CLASS.items()}
CHECKS = ('one_day', 'seven_day', 'hln', 'hac7', 'three_seed', 'family_interval')
CATEGORIES = ('completed', 'completed apart from recorded unavailable configurations',
              'not run (frozen reason)', 'deviation', 'pending (no result file when filled)')
RERUNS = ('report_only_2025_validation', 'secondary_notice', 'secondary_news', 'secondary_LEAR',
          'primary_seed_robustness_notice', 'primary_seed_robustness_news')
DEADLINE_ERRORS = ('No new fitting launches at the 24-hour deadline',
                   '24-hour deadline: unlaunched tasks remain')
LAYERS = ('label_replacement', 'first_chunk', 'window_24h', 'official_cap', 'drop_first_seven',
          'l1_family', 'pd_family')
NATIVE_TABLES = ('primary_seeds', 'combinations', 'cheap', 'secondary_news', 'secondary_notice',
                 'sensitivities', 'diagnostics', 'clipping_news', 'clipping_notice', 'execution')


class Refusal(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise Refusal(message)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def strict_json(path):
    def pairs(items):
        out = {}
        for k, v in items:
            require(k not in out, 'Duplicate JSON key: ' + k)
            out[k] = v
        return out
    def bad(x):
        raise Refusal('Nonfinite JSON: ' + x)
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=bad)


def checked(item):
    require(isinstance(item, dict) and {'path', 'sha256'} <= set(item), 'Path/hash identity required')
    p = Path(item['path'])
    require(p.is_absolute() and p.is_file() and not p.is_symlink(), 'Missing/unsafe input: ' + str(p))
    require(re.fullmatch('[0-9a-f]{64}', item['sha256']) is not None, 'Invalid SHA-256')
    require(sha256(p) == item['sha256'], 'Input SHA-256 mismatch: ' + str(p))
    return p


def identity(path):
    return {'path': str(Path(path).resolve()), 'sha256': sha256(path)}


def utc(value):
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(t.utcoffset() == timedelta(0), 'UTC time required: ' + value)
    return t


_RESOURCE_LAST = (0.0, None)
_RESOURCE_MIN = 100


def resource_gate():
    global _RESOURCE_LAST, _RESOURCE_MIN
    require(os.getpriority(os.PRIO_PROCESS, 0) >= 5, 'Execution/tests require nice >=5')
    if time.monotonic() - _RESOURCE_LAST[0] < 2:
        return _RESOURCE_LAST[1]
    out = subprocess.run(['/usr/bin/memory_pressure'], capture_output=True, text=True, check=True).stdout
    match = re.search(r'System-wide memory free percentage:\s*(\d+)%', out)
    require(match is not None and int(match[1]) >= 25, 'Less than 25% memory free; stop')
    _RESOURCE_LAST = (time.monotonic(), int(match[1]))
    _RESOURCE_MIN = min(_RESOURCE_MIN, int(match[1]))
    if os.environ.get('A8POST_SCRATCH_ROOT'):
        root=Path(os.environ['A8POST_SCRATCH_ROOT']);size=sum(p.stat().st_size for p in root.rglob('*') if p.is_file() and not p.is_symlink())
        require(size<1000000000,'Task scratch reached 1 GB; stop')
    return int(match[1])


def load_module(name, path):
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


CONSUMER_MS = MS / 'table_renderer/result_validation'
BATCH_CODE = PROJ / 'studies/batch_estimation/fitting/code'

def dependencies(consumer=True):

    require(np.__version__ == '1.26.4', 'inference_design requires numpy 1.26.4')
    pins = strict_json(HERE / 'DEPENDENCY_PINS.json')['files']
    for rel, digest in pins.items():
        if not consumer and rel.startswith('tables/'):continue
        require((PROJ / rel).resolve().is_relative_to(PROJ), 'Dependency escapes project')
        require(sha256(PROJ / rel) == digest, 'Dependency drift (review/re-pin before T5): ' + rel)
    from frozen_losses import ast_functions
    for rel,names in strict_json(HERE/'DEPENDENCY_PINS.json').get('exact_ast',{}).items():

        import ast,hashlib
        nodes={n.name:n for n in ast.parse((PROJ/rel).read_text()).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
        for name,digest in names.items():require(name in nodes and hashlib.sha256(ast.dump(nodes[name],include_attributes=False).encode()).hexdigest()==digest,'Frozen AST dependency drift: '+rel+'/'+name)
    frozen = strict_json(confirmation / 'FREEZE.json')['frozen_files']
    for rel in ('code/scoring.py', 'code/guard.py'):
        require(sha256(confirmation / rel) == frozen[rel]['sha256'], 'Frozen scoring drift')
    adapter=strict_json(confirmation/'execution/ADAPTER_FREEZE.json')
    for rel in ('seal_score.py','additional_scoring.py','report_adapter.py','execution_adapter.py'):
        require(sha256(confirmation/'execution'/rel)==adapter['files'][rel]['sha256'],'Frozen native adapter drift: '+rel)
    a4freeze = strict_json(confirmation / 'robustness_tests/A4_CODE_AND_RULES_FREEZE.json')
    for rel, item in a4freeze['files'].items():
        require(sha256(confirmation / 'robustness_tests' / rel) == item['sha256'], 'Frozen robustness_tests drift: ' + rel)
    robustness_tests = load_module('_a8post_frozen_a4', confirmation / 'robustness_tests/code/robustness_comparisons.py')
    robustness_tests.verify_a4_documents()
    sys.path.insert(0, str(confirmation / 'code'))
    try:
        sc = load_module('_a8post_frozen_scoring', confirmation / 'code/scoring.py')
    finally:
        sys.path.pop(0)
    if str(MS) not in sys.path:
        sys.path.append(str(MS))
    if not consumer:return robustness_tests.primary_tests,robustness_tests.sensitivity_tests,robustness_tests,sc,None

    if str(CONSUMER_MS) not in sys.path:sys.path.insert(0,str(CONSUMER_MS))
    F = load_module('table_results_conf_results', CONSUMER_MS / 'table_results_conf_results.py')
    sys.modules['table_results_conf_results'] = F
    return robustness_tests.primary_tests, robustness_tests.sensitivity_tests, robustness_tests, sc, F


class PickPlan:
    'Generate row-major, non-circular bootstrap picks lazily.'
    def __init__(self, n, block, draws, days=None, chunk=512, gate=None):
        require(block in (1, 7) and n >= block and draws > 0 and 1 <= chunk <= 2048,
                'Invalid specified bootstrap shape')
        self.n, self.block, self.draws, self.chunk, self.gate = n, block, draws, chunk, gate
        self.admissible = np.arange(n - block + 1)
        if days is not None:
            parsed = [date.fromisoformat(d) for d in days]
            require(len(parsed) == n and parsed == sorted(set(parsed)), 'Bootstrap dates invalid')
            self.admissible = np.asarray([i for i in self.admissible
                if (parsed[i + block - 1] - parsed[i]).days == block - 1], dtype=int)
            if not len(self.admissible):
                raise ValueError('No complete consecutive-calendar block for this subset')

    def chunks(self):
        rng = np.random.default_rng(SEED)
        for start in range(0, self.draws, self.chunk):
            if self.gate:
                self.gate()
            count = min(self.chunk, self.draws - start)
            starts = rng.choice(self.admissible, size=(count, math.ceil(self.n / self.block)))
            yield start, (starts[..., None] + np.arange(self.block)).reshape(count, -1)[:, :self.n]

    def __array__(self, dtype=None):


        require(self.draws * self.n * 8 < 512 * 1024**2, 'Bootstrap array exceeds inference_design memory cap')
        out = np.empty((self.draws, self.n), dtype=np.int64)
        for start, chunk in self.chunks():
            out[start:start + len(chunk)] = chunk
        return out.astype(dtype, copy=False) if dtype is not None else out


class ChunkedScoring:
    'Generate paired bootstrap draws in chunks and take full-vector linear quantiles.'
    def __init__(self, frozen, draws=DRAWS, chunk=512, gate=None):
        self.frozen, self.BOOTSTRAP_DRAWS, self.chunk, self.gate = frozen, draws, chunk, gate
        self.dm_daily, self.holm = frozen.dm_daily, frozen.holm

    def block_picks(self, n, block, day_keys=None):
        return PickPlan(n, block, self.BOOTSTRAP_DRAWS, day_keys, self.chunk, self.gate)

    def paired_percent_interval(self, loss_a, loss_b, picks):
        a, b = np.asarray(loss_a, dtype='float64'), np.asarray(loss_b, dtype='float64')
        require(a.shape == b.shape and a.ndim == 1 and len(a) == picks.n and
                np.isfinite(a).all() and np.isfinite(b).all() and (a >= 0).all() and (b >= 0).all(),
                'Complete nonnegative paired daily losses required')
        denominator = float(b.mean())
        effect = None if denominator <= 0 else 100.0 * float((a - b).mean()) / denominator
        draws = np.full(picks.draws, np.nan)
        for start, ix in picks.chunks():
            sampled_b = b[ix].mean(axis=1)
            sampled_delta = (a[ix] - b[ix]).mean(axis=1)
            finite = np.isfinite(sampled_b) & (sampled_b > 0)
            target = draws[start:start + len(ix)]
            target[finite] = 100.0 * sampled_delta[finite] / sampled_b[finite]
        good = draws[np.isfinite(draws)]
        return dict(effect_percent_reference_mae=effect,
                    interval95_percent=np.quantile(good, [.025, .975], method='linear').tolist() if len(good) else None,
                    reference_mae=denominator, finite_draws=len(good), undefined_draws=len(draws)-len(good),
                    draws=draws, bootstrap_nonpositive_effect_count=int(np.sum(good <= 0)),
                    monte_carlo_resolution=1 / self.BOOTSTRAP_DRAWS)


def native_row(row):
    out = dict(row)
    for key, block, field in (('interval95_one_day', '1', 'interval95_percent'),
                             ('interval95_seven_day', '7', 'interval95_percent'),
                             ('interval_family_one_day', '1', 'interval_family_adjusted_percent'),
                             ('interval_family_seven_day', '7', 'interval_family_adjusted_percent')):
        out[key] = row['bootstrap'][block].get(field)
    return out


def compute_bundle(primary_tests, sc, bundle):
    require(bundle['state'] in ('COMPUTED', 'NOT_RUN', 'PENDING', 'DEVIATION', 'NOT_EVALUABLE'),
            'Invalid loss-export disposition')
    if bundle['state'] != 'COMPUTED':
        require(not bundle.get('losses') and not bundle.get('mean_prediction_losses'),
                'Numerical losses in uncomputed bundle')
        if bundle['id'].endswith('/primary'):
            out=primary_tests.family_inference(sc,{},bundle['pairs'],bundle['days'])
            out.update(state=bundle['state'],reports=[native_row(r) for r in out['reports']],reason=bundle.get('reason'),three_seed=None)
            return out
        return dict(state=bundle['state'], reports=[], reason=bundle.get('reason'))
    days = bundle['days']
    require(days and days == sorted(set(days)), 'Daily-loss dates missing/duplicated/unordered')
    losses = {a: np.asarray(v, dtype='float64') for a, v in bundle['losses'].items()}
    require(all(v.shape == (len(days),) and np.isfinite(v).all() and (v >= 0).all() for v in losses.values()),
            'Daily loss array invalid')
    pairs = [tuple(p) for p in bundle['pairs']]
    require(pairs and len(set(pairs)) == len(pairs), 'Family pair census invalid')
    if bundle.get('unadjusted'):
        # Leave cheap-text and single secondary comparisons outside the primary Holm family.

        out = dict(family_m=1, days=len(days), date_gaps=[], reports=[])
        for pair in pairs:
            one = primary_tests.family_inference(sc, losses, [pair], days, m=1, subset=bundle.get('subset', False))
            out['reports'].extend(one['reports'])
            out['date_gaps'] = one['date_gaps']
    else:
        out = primary_tests.family_inference(sc, losses, pairs, days, m=bundle.get('family_m'), subset=bundle.get('subset', False))
    out['state'] = 'COMPUTED'
    out['reports'] = [native_row(r) for r in out['reports']]
    mean = bundle.get('mean_prediction_losses')
    if mean is not None:
        require(bundle.get('mean_prediction_loss_definition') == 'daily loss of the mean prediction; not mean arm loss',
                'Three-seed export must be loss of the mean prediction')
        extra = dict(bundle, losses=mean, mean_prediction_losses=None)
        out['three_seed'] = compute_bundle(primary_tests, sc, extra)
    else:
        out['three_seed'] = None
    return out


def check_parity(primary_tests, sensitivity_tests, robustness_tests, computed, a2, a3, a4):
    'Compare reproduced readings with their saved values before resampling.'
    require(not a4.get('consistency_violations'), 'robustness_tests strict reading has violations')
    for task in PAIRS:
        if computed[task+'/primary']['state']!='COMPUTED':continue
        rows = computed[task + '/primary']['reports']
        require([(r['arm'], r['reference']) for r in rows] == PAIRS[task], 'Primary pair census drift')
        saved = a2['tasks'][task]['primary']
        saved4 = a4['tasks'][task]['primary_rows']
        require(len(saved) == len(rows) == len(saved4), 'Saved primary census mismatch')
        for r, s, s4 in zip(rows, saved, saved4):
            for k in ('arm', 'reference', 'decision', 'holm_p', 'mean_difference',
                      'effect_percent_reference_mae', 'interval95_one_day', 'interval95_seven_day',
                      'interval_family_one_day', 'interval_family_seven_day'):
                require(k in s and k in s4, 'Missing frozen parity field: ' + k)
                def equal(a, b):
                    if isinstance(a, (float, list)) and b is not None:
                        return a == b
                    return a == b
                require(equal(r.get(k), s[k]) and equal(r.get(k), s4[k]), 'Frozen 2000 parity failed: ' + task + '/' + k)
            seed = (computed[task + '/primary'].get('three_seed') or {}).get('reports', [])
            ts = seed[rows.index(r)]['decision'] if seed else None
            rob = sensitivity_tests.robustness_a3(r['decision'], r['interval95_one_day'], r['interval95_seven_day'],
                r['hln_decision'], r['hac7_decision'], ts, seven_day_state=r['bootstrap']['7'].get('state'))
            sr = a3['tasks'][task]['robustness_a3'][r['arm'] + '-' + r['reference']]
            require(primary_tests.json_safe(rob) == sr, 'Frozen sensitivity_tests 2000 parity failed')

            require(robustness_tests.envelope(r) == robustness_tests.envelope(s4), 'Frozen robustness_tests envelope parity failed')
    require(isinstance(a4.get('abstract', {}).get('text'), str) and a4['abstract']['text'].strip(),
            'Strict robustness_tests frozen 2000 reading missing')
    return a4['abstract']['text']


def six_checks(primary_tests, sensitivity_tests, row, seed_row):
    rob = sensitivity_tests.robustness_a3(row['decision'], row.get('interval95_one_day'), row.get('interval95_seven_day'),
        row.get('hln_decision'), row.get('hac7_decision'), None if seed_row is None else seed_row['decision'],
        seven_day_state=row['bootstrap']['7'].get('state'))
    checks = {k: 'UNAVAILABLE' if rob['checks'].get(k) is None else 'PASS' if rob['checks'][k] else 'FAIL'
              for k in CHECKS[:-1]}
    value = primary_tests.interval_agrees(row['decision'], row.get('interval_family_one_day'))
    checks['family_interval'] = 'UNAVAILABLE' if value is None else 'PASS' if value else 'FAIL'
    label = ('FRAGILE_NFC' if 'FAIL' in checks.values() and 'UNAVAILABLE' in checks.values() else
             'FRAGILE' if 'FAIL' in checks.values() else 'NOT_FULLY_CHECKED' if 'UNAVAILABLE' in checks.values() else 'ROBUST')
    return checks, label, rob


def decimal(x, digits=5, outward=None):
    if x is None:
        return None
    require(np.isfinite(x), 'Nonfinite numeric output')
    scale = 10**digits
    v = math.floor(x*scale)/scale if outward == 'lo' else math.ceil(x*scale)/scale if outward == 'hi' else x
    out = f'{v:.{digits}f}'
    return out[1:] if out.startswith('-') and float(out) == 0 else out


def interval_strings(value):
    return None if value is None else [decimal(value[0], outward='lo'), decimal(value[1], outward='hi')]


def relation(primary, family, index, **fields):
    if family.get('state') != 'COMPUTED':
        raw = family.get('state', 'PENDING')
        state = 'PENDING' if raw.startswith('PENDING') else raw if raw in ('NOT_RUN','NOT_EVALUABLE') else 'NOT_EVALUABLE' if raw.startswith('DEVIATION') else 'NOT_RUN' if raw.startswith('NOT_RUN') else 'NOT_EVALUABLE'
        return dict(state=state, **{'class': None}, **fields,
                    **({'reason': family['reason']} if family.get('reason') else {}))
    require(len(family['reports']) > index, 'Relation family census mismatch')
    cls = CLASS[family['reports'][index]['decision']]
    return dict(state='NOT_EVALUABLE' if cls == 'NE' else 'SAME' if cls == primary else 'DIFFERENT',
                **{'class': None if cls == 'NE' else cls}, **fields)


def rerun_trigger(row):
    if row['state'] == 'UNAVAILABLE_RESOURCE_BUDGET':
        return row['state']
    if row['state'] == 'UNAVAILABLE_RESOURCE_FAILURE':
        reason = row.get('reason', '')
        if 'MemoryError' in reason:
            return None
        for text in DEADLINE_ERRORS:
            if reason in (text, "TimeoutError('" + text + "')", 'TimeoutError: ' + text):
                return text
    return None


def category(row):
    if row.get('category') in CATEGORIES:
        return row['category']
    state = row['state']
    if state in ('COMPLETE', 'COMPUTED'):
        return CATEGORIES[0]
    if state == 'COMPLETE_WITH_UNAVAILABLE_CONFIGURATIONS':
        return CATEGORIES[1]
    if state.startswith('PENDING'):
        return CATEGORIES[4]
    if state.startswith('NOT_RUN') or rerun_trigger(row):
        return CATEGORIES[2]
    return CATEGORIES[3]


def stages(F, main, batch, own, three, parity, deferred):
    expected = [x.split(' (only')[0] for x in F.templates()['words']['STAGE_TABLE']['rows']
                if three or not x.startswith('A8B-R8S')]
    require(len(main) == 11 and len({r['stage'] for r in main}) == 11, 'Main stage census invalid')
    indexed = {r['stage']: r for r in main}
    require(set(indexed) == set(expected[:11]), 'Main stage inventory drift')
    cs8 = batch['CS8']['stage_dispositions']
    require(set(cs8) <= set(RERUNS), 'Ineligible re-run stage')
    out = []
    for name in expected[:11]:
        row, alt = indexed[name], cs8.get(name)
        trigger = rerun_trigger(row)
        require(alt is None or trigger is not None, 'Re-run without frozen trigger: ' + name)
        require(not (name in RERUNS and trigger and alt is None), 'Required CS8 disposition missing: ' + name)
        c, post = category(row), '--'
        reason = 'A4NR_BUDGET' if c == CATEGORIES[2] else None
        if alt is not None:
            tasks = ('news', 'notice') if name == 'report_only_2025_validation' else ('notice',) if 'notice' in name else ('news',)
            post = category(alt)
            if alt.get('state')=='NOT_RUN_PARITY_FAILED':post=CATEGORIES[2]
            elif any(parity[t]['state'] != 'PASS' for t in tasks):
                post = CATEGORIES[3]
                require(not alt.get('score_eligible'), 'Scoring parity failure with score-eligible CS8 stage')
            reason = alt.get('reason') if post != CATEGORIES[2] or alt.get('reason')=='A8NR_PARITY' else 'A4NR_BUDGET'
        out.append(dict(stage=name, conf=c, postseal=post, counted_category=c if post == '--' else post,
                        reason=reason, conf_reason='A4NR_BUDGET' if c==CATEGORIES[2] else row.get('reason'), rerun_trigger=trigger if alt is not None else None))
    for name in expected[11:]:
        require(name in own, 'Missing own-stage disposition: ' + name)
        r = own[name]
        c = category(r)
        if deferred and name.startswith('A8B-R8'):
            require(c == CATEGORIES[2] and r.get('reason') in ('A8NR_AUTHOR','A8NR_RESOURCE_A8AM2'), 'R8 specification-2 disposition mismatch')
        out.append(dict(stage=name, conf='--', postseal=c, counted_category=c,
                        reason=r.get('reason'), rerun_trigger=None))
    counts = {c: sum(r['counted_category'] == c for r in out) for c in CATEGORIES}
    require(sum(counts.values()) == len(out) == (22 if three else 21), 'Count conservation failed')
    return out


def fill_cutoff(clock, refill=False):
    score = utc(clock['score_utc'])
    deadline = datetime(2026, 10, 6, 1, tzinfo=timezone.utc)
    runs = clock['authorised_runs']
    ends = [utc(r['terminal_utc']) for r in runs.values() if r.get('terminal_utc')]
    terminal = max(ends + [score]) if len(ends) == len(runs) else deadline
    cutoff = max(score, min(terminal, deadline))
    require(utc(clock['filled_utc']) >= cutoff, 'Fill precedes frozen cutoff')
    for name, time in clock.get('input_completed_utc', {}).items():
        require(refill or utc(time) <= cutoff, 'Later input requires refill: ' + name)
    return cutoff


def load_specification2_activation():

    previous=sys.modules.get('batch_inputs');paths=list(sys.path)
    try:
        sys.path.insert(0,str(BATCH_CODE))
        common=load_module('batch_inputs',BATCH_CODE/'batch_inputs.py')
        sys.modules['batch_inputs']=common
        return load_module('_a8post_specification2',BATCH_CODE/'batch_definitions.py')
    finally:
        sys.path[:]=paths
        if previous is None:sys.modules.pop('batch_inputs',None)
        else:sys.modules['batch_inputs']=previous


def verify_specification2(record, items, timestamps, score_utc, synthetic=False):
    require(record['schema'] == 'A8_SPECIFICATION_2_V1' and
            record['state'] == 'A8_SPECIFICATION_2_FROZEN_BEFORE_SCORING', 'Specification 2 not effective')
    for item in [*record['files'], *record['binds'].values()]:checked(item)
    if not synthetic:
        path=checked(items['specification2'])
        require(path.resolve()==(confirmation/'inference_design/ADDENDUM_A8_SPECIFICATION_2_FREEZE.json').resolve(), 'Specification 2 effective path required')
        activation_path=BATCH_CODE/'batch_definitions.py'
        require(any(Path(i['path']).resolve()==activation_path.resolve() and i['sha256']==sha256(activation_path) for i in record['files']),'Specification activation code not bound')
        activation=load_specification2_activation()
        require(activation.verify(path,confirmation/'inference_design',BATCH_CODE.parent/'freeze_a8_specification2.py')==record, 'Specification 2 verifier disagreement')
    else:
        require(record['changes']['scope']==['R8_news','R8S'] and record['changes']['other_rule_changes'] is False,'Synthetic specification scope drift')
    require(record['other_rule_changes'] is False, 'Specification 2 changes other rules')
    for item in [*record['files'], *record['binds'].values()]:
        checked(item)
    for name in ('A8_FREEZE.json', 'RULES_FOR_TABLE_RESULTS.json', 'ADDENDUM_A8_SPECIFICATION_1_FREEZE.json'):
        require(record['binds'][name]['sha256'] == sha256(confirmation / 'inference_design' / name), 'Specification 2 parent mismatch')
    stamp = utc(record['frozen_utc'])
    require(stamp < utc(score_utc) and stamp <= utc(timestamps['T4B']['utc']), 'Specification 2 chronology invalid')
    digest = items['specification2']['sha256']
    require(all(digest in timestamps[t]['files'].values() for t in ('T4B', 'T5')), 'Specification 2 not listed in T4B/T5')
    for item in record['files']:
        require(all(item['sha256'] in timestamps[t]['files'].values() for t in ('T4B','T5')),
                'Specification 2 file not listed in T4B/T5: '+Path(item['path']).name)
    return True


def load_inputs(manifest_path, expected, synthetic=False):
    preview = strict_json(manifest_path)
    if preview.get('schema') == 'A8POST_INPUTS_V2':
        from input_specification import load_inputs_v2
        return load_inputs_v2(manifest_path, expected, synthetic)
    require(synthetic, 'Loss-export V1 retired; production requires A8POST_INPUTS_V2')
    """Explicit identities, no globbing/fallback to live host directories."""
    require(sha256(manifest_path) == expected, 'Input-manifest hash mismatch')
    m = strict_json(manifest_path)
    require(m.get('schema') == 'A8POST_INPUTS_V1', 'Unsupported input manifest')
    require(synthetic or not m.get('synthetic'), 'Synthetic manifest forbidden in production CLI')
    required = {'score_receipt', 'score_report', 'a2', 'a3', 'a4', 'batch', 'batch_seal',
                'dly_seal', 'clk8', 'author', 'author_prescore', 'timestamps', 'human_review',
                'repins', 'loss_export', 'context', 'specification2'}
    require(set(m['inputs']) == required, 'Missing/unknown input role')

    records = {name: strict_json(checked(item)) for name, item in m['inputs'].items()}
    receipt, batch = records['score_receipt'], records['batch']
    require(receipt['state'] == 'FROZEN_SCORE_COMPLETE', 'confirmation score incomplete')
    require(batch['schema'] == 'A8BATCH_POSTSCORE_INPUTS_V1' and batch['state'] == 'A8BATCH_SCORED',
            'Batch scorer input schema/state invalid')
    require(batch['identities']['source_receipt_sha256'] == m['inputs']['score_receipt']['sha256'],
            'Batch/confirmation receipt mismatch')
    require(batch['seal']['sha256'] == m['inputs']['batch_seal']['sha256'], 'Batch seal mismatch')
    require(records['batch_seal']['conf_seal_sha256'] == receipt['seal_sha256'], 'confirmation/batch seal association mismatch')
    allowed = {(i['path'], i['sha256']) for i in receipt['files']}
    cs8receipt = batch['CS8'].get('score_receipt')
    if cs8receipt:
        r = strict_json(checked(cs8receipt))
        require(r['state'] == 'FROZEN_SCORE_COMPLETE', 'CS8 score incomplete')
        allowed |= {(i['path'], i['sha256']) for i in r['files']}
    for key in ('score_report', 'loss_export'):
        i = m['inputs'][key]
        require((i['path'], i['sha256']) in allowed, 'Unbound score artifact: ' + key)

    for i in receipt['files']:
        checked(i)
    for key in ('a2', 'a3', 'a4'):
        require(records[key]['seal_sha256'] == receipt['seal_sha256'], 'Post-score source identity mismatch: ' + key)
    for label in ('T4', 'T4A', 'T4B', 'T5'):
        require(label in records['timestamps'], 'Required timestamp missing: ' + label)
        utc(records['timestamps'][label]['utc'])
    for label, key, filename in (('T4B', 'author', 'AUTHOR_CONFIRMATION_A8.json'),
                                 ('T5', 'author_prescore', 'AUTHOR_CONFIRMATION_A8_PRESCORE.json')):
        require(records['timestamps'][label]['files'].get(filename) == m['inputs'][key]['sha256'], 'Author timestamp identity mismatch')
    require(utc(records['timestamps']['T5']['utc']) < utc(records['context']['fill_clock']['score_utc']), 'T5 must precede score')
    verify_specification2(records['specification2'], m['inputs'], records['timestamps'], records['context']['fill_clock']['score_utc'], synthetic)
    export = records['loss_export']
    require(export['schema'] == 'A8POST_LOSS_EXPORT_V1' and export['source_seal_sha256'] == receipt['seal_sha256'],
            'Daily-loss export source mismatch')
    require(export.get('production_export_authorised') is True, 'Loss-export producer specification not authorised')
    if not synthetic:

        freeze_item = export.get('exporter_freeze')
        require(freeze_item is not None, 'Separately approved pre-score exporter freeze required')
        exporter = strict_json(checked(freeze_item))
        require(exporter.get('schema') == 'A8POST_LOSS_EXPORT_FREEZE_V1' and
                exporter.get('author_approved_before_score') is True, 'Exporter specification not approved')
        require(utc(exporter['frozen_utc']) <= utc(records['timestamps']['T5']['utc']), 'Exporter frozen after T5')
        require(freeze_item['sha256'] in records['timestamps']['T5']['files'].values(), 'Exporter freeze not listed in T5')
        require(exporter.get('files'), 'Exporter freeze has no code/specification identities')
        for i in exporter['files']:
            checked(i)
    require(len(export['bundles']) == len({b['id'] for b in export['bundles']}), 'Duplicate loss-export bundle')
    for key in ('clk8', 'batch_seal', 'dly_seal', 'specification2'):
        require(m['inputs'][key]['sha256'] in records['timestamps']['T5']['files'].values() or
                (key == 'clk8' and m['inputs'][key]['sha256'] in records['timestamps']['T4B']['files'].values()),
                'Required evidence not listed in T5: ' + key)
    fill_cutoff(records['context']['fill_clock'], m.get('refill', False))
    return m, records


def clock_record(raw, item):
    state=raw.get('state')
    if 'reason_codes' in raw:
        mapped='NOT_RUN' if state=='NOT_RUN_INPUT_MISMATCH' else state
        require(mapped in ('INFORMATIVE','NOT_INFORMATIVE','NOT_RUN'),'CLK8 result state invalid')
        if raw.get('Z') is not None:require(type(raw['Z']) is int and raw['Z']>=0,'CLK8 Z must be the native integer')
        return dict(state=mapped,reason_codes=raw['reason_codes'],coverage=raw.get('coverage'),
            covered_n=(raw.get('coverage') or {}).get('covered_notices'),listed_by_admission_n=raw.get('listed_by_admission_n'),
            X=raw.get('X'),Y=raw.get('Y'),Z=raw.get('Z'),reading=raw.get('reading','A8CLK_NR'),
            public_by_admission=raw.get('X'),maximum_delay_minutes=str(raw['Z']) if raw.get('Z') is not None else None,
            delay60_class=None)
    native=raw.get('consumer_clock',raw);state=native['state']
    if state!='INFORMATIVE':return dict(state=state,reason=native['reason'],reason_codes=[native['reason']],public_by_admission=None,maximum_delay_minutes=None)
    covered,n=raw['coverage']['covered_notices'],raw['listed_by_admission_n']
    require(type(covered) is int and type(n) is int and 0<=n<=covered and covered>0,'CLK8 count invalid')
    display=str((Decimal(n)*100/Decimal(covered)).quantize(Decimal('.1'),rounding=ROUND_HALF_UP))
    return dict(state=state,public_by_admission=display,maximum_delay_minutes=decimal(float(raw['maximum_delay_minutes']),0,'hi'),covered_n=covered,listed_by_admission_n=n,delay60_class=None)


def delayed_family(delayed, delta):

    return delayed.get(str(delta),delayed if 'state' in delayed else dict(state='NOT_RUN',reason='A8NR_PARITY'))


def capacity_relation(cls, cp, index):
    if cp['state']=='COMPUTED':
        selected,g0=cp['selected'],cp['g0']
        s,g=CLASS[selected['reports'][index]['decision']],CLASS[g0['reports'][index]['decision']]
        return dict(state='NOT_EVALUABLE' if 'NE' in (s,g) else 'SAME' if s==g else 'DIFFERENT',**{'class':None if 'NE' in (s,g) else s},g0_class=g)
    if cp['state']=='CAPACITY_SELECTION_KEPT_G0':
        return dict(state='NOT_EVALUABLE' if cls=='NE' else 'SAME',**{'class':None if cls=='NE' else cls},g0_class=cls)
    return relation(cls,cp,index)


def output_contrast(primary_tests, sensitivity_tests, robustness_tests, sc, bundle, family, index, task, batch, context):
    row = family['reports'][index]
    seed = (family.get('three_seed') or {}).get('reports', [])
    seed_row = seed[index] if seed else None
    checks, label, rob = six_checks(primary_tests, sensitivity_tests, row, seed_row)
    cls = CLASS[row['decision']]
    env = robustness_tests.envelope(row)
    delayed = batch['DLY8'].get('primary', {}) if task == 'notice' else {}
    delays = {str(d): None for d in (5, 15, 60)}
    for d in delays:
        if d in delayed and delayed[d]['state'] == 'COMPUTED':
            delays[d] = CLASS[delayed[d]['reports'][index]['decision']]
    rel = {'R8': dict(state='NOT_RUN', **{'class': None}, fully_checked=False, seeds_run='single', reason='A8NR_AUTHOR'),
           'DLY8': relation(cls, delayed_family(delayed,15), index)
                   if task == 'notice' else dict(state='NOT_APPLICABLE', **{'class': None}),
           'KCX': relation(cls, context['optional_families'][task]['KCX'], index)}
    rel['CPS8']=capacity_relation(cls,batch['CPS8'][task],index)
    if rel['DLY8']['state'] not in ('SAME','DIFFERENT'):delays={d:None for d in delays}
    square = batch['squared_loss']['primary'][task][index]
    if family['state']!='COMPUTED':
        square.update(state='NOT_RUN',effect=None,dm={},reason='A8NR_PARITY')
    require((square['arm'], square['reference']) == (row['arm'], row['reference']), 'Squared-loss pair order mismatch')
    sq = dict(state=square['state'], effect=decimal(float(square['effect'])) if square.get('effect') is not None else None,
              p=decimal(square.get('dm', {}).get('p_two_sided'), 12))
    pair = row['arm'] + '-' + row['reference']
    design = context['design_states'][task][pair]
    dissent = [k for k in LAYERS if design.get(k, {}).get('state') == 'DIFFERENT']
    mc_ranges = []
    if cls != 'NE':
        for block in (1, 7):
            try:
                picks = sc.block_picks(len(bundle['days']), block, bundle['days'] if bundle.get('subset') else None)
            except ValueError:
                continue
            values = sc.paired_percent_interval(bundle['losses'][row['arm']], bundle['losses'][row['reference']], picks)['draws']
            mc_ranges.append(robustness_tests.order_stat_range(values, .05/(2*family['family_m'])))
    return dict(arm=row['arm'], reference=row['reference'], **{'class': cls},
                effect_percent=decimal(row.get('effect_percent_reference_mae')) if cls != 'NE' else None,
                effect_aud=decimal(row.get('mean_difference')) if cls != 'NE' else None,
                family_one_day=interval_strings(row.get('interval_family_one_day')) if cls != 'NE' else None,
                family_seven_day=interval_strings(row.get('interval_family_seven_day')) if cls != 'NE' else None,
                per_contrast_seven_day=interval_strings(row.get('interval95_seven_day')) if cls != 'NE' else None,
                envelope=decimal(env['U'], 3, 'hi') if env and cls != 'NE' else None,
                checks=checks, three_seed_class=CLASS[seed_row['decision']] if seed_row else 'NE',
                three_seed_effect=decimal(seed_row.get('effect_percent_reference_mae')) if seed_row and seed_row['decision'] != 'NOT_EVALUABLE' else None,
                relations=rel, squared_loss=sq, design_layers=dissent,
                design_rejection_not_reproduced=cls in ('IMP', 'DET') and (bool(dissent) or any(rel[k]['state'] == 'DIFFERENT' for k in ('DLY8', 'KCX')) or (rel['CPS8']['state']=='DIFFERENT' and rel['CPS8']['class']!=cls)),
                cheap_text=context['cheap_states'][task][pair], reason=context['task_reasons'][task], delay_classes=delays,
                holm_p=decimal(row.get('holm_p'), 12) if cls != 'NE' else None, mc_unresolved=robustness_tests.mc_flag_from_ranges(mc_ranges, sensitivity_tests.SESOI[task]))


def form_sequence(F, record, families):

    entries = []
    def emit(name, **slots):
        slots = {k: str(v) for k, v in slots.items()}
        entries.append(dict(id=name, slots=slots))
    def frm(name, **slots):
        return F.form(name, **slots) if name in F.templates()['forms'] else F.inherited_form(name, **slots)
    T = F.templates()
    emit('A4AB_PDS')
    lear = record['lear']
    lt = frm('A6LT_NE', reason=T['words']['PLAIN_INC_REASON'][lear['reason']]) if lear['class'] == 'NE' else frm('A6LT0',
        abs=str(abs(F.decimal(lear['effect']))), lower_higher='lower' if F.decimal(lear['effect']) < 0 else 'higher',
        **{'class': T['words']['PLAIN_C3'][lear['class']]})
    emit('A6Y0', lear26=lt)
    for task, t in record['tasks'].items():
        if task == 'notice':

            clk = t['clk8']
            if clk['state'] == 'INFORMATIVE':
                if F.clock_ok(clk):
                    emit('A8CLK_OK', X=clk['public_by_admission'], n=clk['covered_n'])
                else:
                    emit('A8CLK_LATE', Y=decimal(100-float(clk['public_by_admission']), 3), Z=clk['maximum_delay_minutes'], n=clk['covered_n'])
            else:
                emit('A8CLK_NI' if clk['state'] == 'NOT_INFORMATIVE' else 'A8CLK_NR', reason=F.clock_reason(clk))
        for c in t['contrasts']:
            name = T['names'][c['arm']]
            activity = T['words']['PLAIN_ACTIVITY_REF'][task].removesuffix(' reference')
            if c['class'] == 'NE':
                emit('A8H4', arm=name, activity=activity, reason=T['words']['PLAIN_INC_REASON'][c['reason']])
                continue
            checks = c['checks']
            passed = all(x == 'PASS' for x in checks.values())
            fail = [T['words']['CHECKS6'][k] for k in CHECKS if checks[k] == 'FAIL']
            unavailable = [T['words']['CHECKS6'][k] for k in CHECKS if checks[k] == 'UNAVAILABLE']
            robustness = ('all six uncertainty checks agreed with the decision class' if t['alert'] else frm('A8R1')) if passed else ('fragile: ' + F.join(fail) + ' did not agree with its decision class' if fail else '')
            if unavailable:
                robustness += ('; ' if robustness else '') + 'not fully checked: ' + F.join(unavailable) + ' unavailable'
            seven = frm('A8SEVEN') if F.seven_undefined(c) else ''
            zero = frm('A8Z', level='97.5' if task == 'news' else '98.3') if c['class'] in ('IMP', 'DET') and F.decimal(c['family_one_day'][0]) <= 0 <= F.decimal(c['family_one_day'][1]) else ''
            slots = dict(arm=name, activity=activity, se=c['effect_percent'], level='97.5' if task == 'news' else '98.3',
                lo=c['family_one_day'][0], hi=c['family_one_day'][1], p='p = ' + c['holm_p'], robustness=robustness, qualifiers=seven)
            if c['class'] != 'NULL':
                slots.update(aud=str(abs(F.decimal(c['effect_aud']))), zero=zero)
            if c['class'] == 'IMP' and t['alert']:
                nc = t['negative_control']
                emit('A8H2_NC', **slots, k0=nc['k0'], R0=nc['R0'], lo0=nc['lo0'], hi0=nc['hi0'])
                emit('A8NA_NC')
            else:
                if c['class'] in ('IMP', 'DET') and not passed:
                    slots['three_seed'] = T['words']['PLAIN_C3'][c['three_seed_class']]
                    if c['class'] == 'IMP':
                        slots['benchmark'] = 'the strong-benchmark and combination readings are reported beside this contrast'
                        slots['test_note'] = frm('A6FT_F' if fail else 'A6FT_N')
                    emit('A6H2F' if c['class'] == 'IMP' else 'A6H3F', **slots)
                elif c['class'] == 'IMP':
                    slots.update(attribution='an increment over the activity reference only; content and finer activity structure are not separable',
                                 position='comparison-value class not assigned' if not passed else T['forms']['A8D9'],
                                 benchmark='the strong-benchmark and combination readings are reported beside this contrast')
                    emit('A6H2', **slots)
                else:
                    emit({'NULL': 'A6H1', 'DET': 'A6H3'}[c['class']], **slots)
            if c['class'] in ('IMP', 'DET') and not passed:
                emit('A8SEED_NOEST', c3=T['words']['PLAIN_C3'][c['three_seed_class']])
            for layer in ('R8', 'DLY8', 'KCX'):
                r = c['relations'][layer]
                if layer == 'DLY8' and task == 'news':
                    continue
                if r['state'] in ('NOT_RUN', 'NOT_EVALUABLE'):
                    if layer == 'R8':
                        emit('A8R8_NR', reason=F.reason_text(r.get('reason', 'A8NR_AUTHOR')))
                elif r['state'] in ('SAME', 'DIFFERENT') and c['class'] in ('IMP', 'DET'):
                    if layer == 'DLY8' and r['state'] == 'SAME':
                        continue
                    phrase = frm({'R8': 'A8R8_NOTREP' if r['state'] == 'DIFFERENT' else 'A8R8_SAME',
                                  'DLY8': 'A8DLY15_NOTREP',
                                  'KCX': 'A8KCX_NOTREP' if r['state'] == 'DIFFERENT' else 'A8KCX_SAME'}[layer])
                    emit('A8REL', change='reduction' if c['class'] == 'IMP' else 'increase', names=name, was_were='was', phrase=phrase)
            emit('A8CHS', documents='articles' if task == 'news' else 'notices',
                seed='; primary seed only' if c['class'] == 'IMP' and not passed else '', arm=name,
                cheap_list='was ' + {'BETTER':'better','WORSE':'worse','NOTSHOWN':'not shown to differ','NOT_EVALUABLE':'not evaluable','NOT_RUN':'not run'}[c['cheap_text']],
                cheap_reading='not assigned under a negative-control alert' if t['alert'] else c['cheap_text'])
        evaluable = [c for c in t['contrasts'] if c['class'] != 'NE']
        if t['bound'] is not None and not any(c['class'] == 'IMP' for c in t['contrasts']):
            ne = [T['names'][c['arm']] for c in t['contrasts'] if c['class'] == 'NE']
            emit('A8H5_NC' if t['alert'] else 'A8H5', names=F.join(T['names'][c['arm']] for c in evaluable),
                 X=t['bound'], tail='98.75' if task == 'news' else '99.17',
                 below_or_above='below' if float(t['bound']) < (3.8 if task == 'news' else .5) else 'above',
                 S_phrase=('3.8' if task == 'news' else '0.5')+'% of the reference error',
                 env=frm('A8SEVEN') if any(F.seven_undefined(c) for c in evaluable) else '',
                 mc=frm('A8MC', S_phrase=('3.8' if task == 'news' else '0.5')+'% of the reference error') if any(c['mc_unresolved'] for c in evaluable) else '',
                 sens=frm('A8SENS_A') if t['signal_failed'] else '', ne=frm('A8H5_NE', ne_names=F.join(ne)) if ne else '')
    emit('A8LEVELS')
    emit('A8SHARED')
    record['n0_forms'] = entries
    record['specified_reading_n0'] = ' '.join(frm(e['id'], **e['slots']) for e in entries)
    return entries


def table_records(computed, clipping, stages_):

    groups = {k: [] for k in NATIVE_TABLES}
    forest = []
    for key, family in computed.items():
        task, layer = key.split('/', 1)
        group = 'primary_seeds' if layer == 'primary' else 'combinations' if layer.startswith('combination') else 'cheap' if layer == 'cheap' else 'sensitivities' if layer in LAYERS else 'diagnostics' if layer in ('subsets', 'report_2025') else 'secondary_' + task
        if group not in groups:
            group = 'diagnostics'
        if family['state'] != 'COMPUTED':
            groups[group].append([task, layer, family['state'], family.get('reason') or '', '', '', '', ''])
            continue
        for r in family['reports']:
            family_interval = layer in ('primary', 'combination', 'l1_family', 'pd_family')
            iv1 = r['bootstrap']['1'].get('interval_family_adjusted_percent' if family_interval else 'interval95_percent')
            iv7 = r['bootstrap']['7'].get('interval_family_adjusted_percent' if family_interval else 'interval95_percent')
            groups[group].append([task, layer, r['arm']+'-'+r['reference'], CLASS[r['decision']],
                decimal(r.get('effect_percent_reference_mae')) or 'not evaluable',
                json.dumps(interval_strings(iv1)), json.dumps(interval_strings(iv7)), decimal(r.get('holm_p'), 12) or 'undefined'])
            forest.append(dict(task=task, group='Primary' if layer == 'primary' else 'Combination' if layer == 'combination' else 'Secondary',
                arm=r['arm'], ref=r['reference'], effect=r.get('effect_percent_reference_mae'), thick=iv1, thin=iv7,
                src='inference current reading', field=key+'/'+r['arm'], pcontent=None, bootstrap_draws=DRAWS))
        for r in (family.get('three_seed') or {}).get('reports', []):
            groups['primary_seeds'].append([task, layer+' three-seed mean', r['arm']+'-'+r['reference'], CLASS[r['decision']],
                decimal(r.get('effect_percent_reference_mae')) or 'not evaluable', json.dumps(interval_strings(r['interval_family_one_day'])),
                json.dumps(interval_strings(r['interval_family_seven_day'])), decimal(r.get('holm_p'), 12) or 'undefined'])
    for task in PAIRS:
        require(task in clipping and isinstance(clipping[task], list), 'Missing native clipping table')
        groups['clipping_'+task] = [[str(v) for v in row] for row in clipping[task]]
    groups['execution'] = [[r[k] or '' for k in ('stage', 'conf', 'postseal', 'counted_category', 'reason', 'rerun_trigger')] for r in stages_]
    tables = []
    for name in NATIVE_TABLES:
        require(groups[name], 'Native table has no rows: ' + name)
        width = len(groups[name][0])
        require(all(len(r) == width for r in groups[name]), 'Native table row width mismatch')
        tables.append(dict(id=name, location='S9' if name.startswith('clipping') or name == 'execution' else 'S7',
            label='supp:tab:a8post-'+name, caption='Current '+name.replace('_', ' ')+' readings, B = 100000.',
            header=' & '.join(['Field '+str(i+1) for i in range(width)])+r' \\', spec='l'*width, bootstrap_draws=DRAWS, rows=groups[name]))
    return tables, forest


def build(manifest_path, expected, chunk=512, gate=resource_gate, synthetic=False, production=False):
    require(synthetic or production, "Prediction replay requires --production; development is synthetic only")
    if gate:
        gate()
    if production:
        require(sha256(manifest_path)==expected,'Input-manifest hash mismatch')
        require(strict_json(manifest_path).get('schema')=='A8POST_INPUTS_V2','Production requires direct frozen-loader V2 replay')
    primary_tests, sensitivity_tests, robustness_tests, frozen, F = dependencies()
    manifest, inputs = load_inputs(manifest_path, expected, synthetic)
    require(not production or manifest['schema']=='A8POST_INPUTS_V2','Production requires direct frozen-loader V2 replay')
    replay_evidence = None
    if manifest['schema'] == 'A8POST_INPUTS_V2':
        import tempfile
        from frozen_losses import replay, complete_bundles
        state = Path(manifest['inputs']['seal']['path']).parent
        scratch = Path(tempfile.mkdtemp(prefix='A8POST3_REPLAY_',dir=os.environ.get('A8POST_SCRATCH_ROOT'))) / 'replay'
        generated, replay_evidence = replay(state, scratch, primary_tests, sensitivity_tests, robustness_tests, frozen, inputs, synthetic)
        generated = complete_bundles(primary_tests,sensitivity_tests,robustness_tests,frozen,generated,inputs,replay_evidence)
        bundle_list = list(generated.values())
        inputs['loss_export'] = dict(bundles=bundle_list,clipping=replay_evidence['clipping'])
    else:
        bundle_list = inputs['loss_export']['bundles']
    for b in bundle_list:
        raw=b['state']
        if raw not in ('COMPUTED','NOT_RUN','PENDING','DEVIATION','NOT_EVALUABLE'):
            b['native_disposition']=raw;b['state']='PENDING' if raw.startswith('PENDING') else 'DEVIATION' if 'PARITY' in raw or raw.startswith('DEVIATION') else 'NOT_RUN' if raw.startswith('NOT_RUN') else 'NOT_EVALUABLE'
    singles = {'cheap', 'shift', 'mn', 'lear', 'combination_benchmark', 'subsets'}
    bundles = {b['id']: dict(b, unadjusted=b.get('unadjusted',False) or b['id'].split('/',1)[1] in singles) for b in bundle_list}

    required_layers = {'primary', 'combination', 'combination_benchmark', 'cheap', 'shift', 'mn', 'report_2025',
                       'label_replacement', 'first_chunk', 'window_24h', 'official_cap', 'drop_first_seven', 'l1_family', 'pd_family', 'subsets'}
    for task in PAIRS:
        require({task+'/'+s for s in required_layers} <= set(bundles), 'Missing sufficient-statistic/disposition bundle: '+task)
        require([tuple(p) for p in bundles[task+'/primary']['pairs']] == PAIRS[task], 'Specified primary family changed')
        start, end = ('2026-03-01', '2026-09-30') if task == 'news' else ('2026-08-01', '2026-09-30')
        require(bundles[task+'/primary']['days'] == primary_tests.day_list([(start, end)]), 'Primary day census drift')
    sc2000 = ChunkedScoring(frozen, 2000, chunk, gate)
    old = {k: compute_bundle(primary_tests, sc2000, b) for k, b in bundles.items()}
    saved_2000 = check_parity(primary_tests, sensitivity_tests, robustness_tests, old, inputs['a2'], inputs['a3'], inputs['a4'])
    if replay_evidence is not None:
        from parity_gate import require_before_large
        require_before_large(bundles.values())
    sc = ChunkedScoring(frozen, DRAWS, chunk, gate)
    current = {k: compute_bundle(primary_tests, sc, b) for k, b in bundles.items()}
    if replay_evidence is not None:
        from batch_layers import propagate
        propagate(primary_tests,current,inputs)
    return assemble_output(primary_tests,sensitivity_tests,robustness_tests,frozen,F,manifest,inputs,bundles,current,saved_2000,replay_evidence,chunk,gate)


def assemble_output(primary_tests,sensitivity_tests,robustness_tests,frozen,F,manifest,inputs,bundles,current,saved_2000,replay_evidence,chunk=512,gate=resource_gate):
    sc=ChunkedScoring(frozen,DRAWS,chunk,gate)
    batch, context = inputs['batch'], inputs['context']

    context['design_states'] = {}
    context['cheap_states'] = {}
    context['secondary_clause'] = {}
    context['secondary_check'] = {}
    context['secondary_differing_arms'] = {}
    for task in PAIRS:
        rows = current[task+'/primary']['reports']
        files = {}
        for layer, key in (('first_chunk','first_L'), ('window_24h','window_24h'),
                           ('official_cap','official_cap'), ('drop_first_seven','drop_first_seven')):
            f = current[task+'/'+layer]

            files[key] = dict(reports=[dict(r, dm_p1=dict(mean_difference=r.get('mean_difference'),
                p_two_sided=r.get('p_two_sided')), primary_decision=r['decision']) for r in f['reports']])
        label = current[task+'/label_replacement']
        label_input = dict(state='A2LABEL_SCORED', families={task:label}) if label['state']=='COMPUTED' else None
        from reading_propagation import batch_reading
        ds = sensitivity_tests.sensitivity_states(task, rows, files, batch=batch_reading(sensitivity_tests,current,inputs), label=label_input)
        context['design_states'][task] = {a+'-'+b:states for (a,b),states in ds.items()}
        cheap = current[task+'/cheap']
        cheap_rows = cheap.get('reports', [])
        computed_cheap = {r['reference']: ('beaten' if r['decision']==robustness_tests.IMP else 'worse' if r['decision']==robustness_tests.DET else 'not beaten') for r in cheap_rows}
        key = robustness_tests.cheap_reading_key(dict(computed=computed_cheap, unavailable=[] if cheap_rows else ['missing']))
        cheap_state = ('BETTER' if key=='A4CHR_BETTER' else 'WORSE' if key=='A4CHR_NOT' and 'worse' in computed_cheap.values()
                       else 'NOTSHOWN' if key=='A4CHR_NOT' else 'NOT_EVALUABLE' if cheap['state'] != 'NOT_RUN' else 'NOT_RUN')
        context['cheap_states'][task] = {r['arm']+'-'+r['reference']: cheap_state if r['arm']==primary_tests.CONTENT_ARM[task] else 'NOT_EVALUABLE' for r in rows}
        differing = [r['arm'] for r in rows if any(v['state']=='DIFFERENT' for v in ds[(r['arm'],r['reference'])].values())]
        context['secondary_clause'][task] = 'DIFFERENT' if differing else 'NOT_RUN'
        context['secondary_check'][task] = 'secondary_family'
        context['secondary_differing_arms'][task] = differing
    from reading_propagation import assemble
    propagation=assemble(primary_tests,sensitivity_tests,robustness_tests,current,inputs,context['design_states'])
    for task in PAIRS:
        pc=propagation['details'][task]['pc']
        alert=pc['state'] in ('SIZE_FAILS','BOTH_FAIL')
        context['pc_flags'][task]=dict(alert=alert,signal_failed=pc['state'] in ('SENSITIVITY_FAILS','BOTH_FAIL'))
        if alert:context['pc_flags'][task]['negative_control']=dict(k0=pc['k0'],R0=pc['R0'],lo0=f"{100*pc['cp0'][0]:.2f}",hi0=f"{100*pc['cp0'][1]:.2f}")
    if any(propagation['details'][t]['pc']['state']!='NOT_RUN' for t in PAIRS):context['pc_state']='RESULT'
    record = dict(schema='TABLE_RESULTS_A8_V1', bootstrap_draws=DRAWS,
        identities=dict(a8_freeze_sha256=F.A8_BINDINGS['A8_FREEZE.json'], fixed_facts_sha256=F.A8_BINDINGS['FIXED_FACTS_A8.json'],
                        summary_comparisons_freeze_sha256=F.E_FREEZE_SHA, source_receipt_sha256=manifest['inputs']['score_receipt']['sha256']),
        tasks={}, optional=context['optional'], author_confirmation=inputs['author'], author_prescore=inputs['author_prescore'],
        timestamps=inputs['timestamps'], human_review=inputs['human_review'], specified_reading_2000=F.rename_plain(saved_2000) if hasattr(F,'rename_plain') else saved_2000,
        pc_state=context['pc_state'], stage_table_ref='supp:tab:table_results-stages', cps8_kept_all=context['cps8_kept_all'],
        kept_alert_sentences={}, pv=context['pv'], seventh_separate_approval=context['seventh_separate_approval'],
        fill_clock=context['fill_clock'], deviations=context['deviations'])
    from robustness_fields import prepare_stages
    prepare_stages(inputs)
    record['stages'] = stages(F, inputs['score_report']['stage_dispositions'], batch, context['own_stages'],
        record['author_confirmation']['choices']['r8_seeds'] == 'three', batch['scoring_parity'], False)
    for task in PAIRS:
        family = current[task+'/primary']
        if family['state']!='COMPUTED':
            context['task_complete'][task]=False;context['task_reasons'][task]='parity' if family.get('reason')=='A8NR_PARITY' else 'fail'
        cs = [output_contrast(primary_tests, sensitivity_tests, robustness_tests, sc, bundles[task+'/primary'], family, i, task, batch, context) for i in range(len(PAIRS[task]))]
        mn = current[task+'/mn']
        mr = mn['reports'][0] if mn['state'] == 'COMPUTED' else None
        bound = [float(c['envelope']) for c in cs if c['class'] in ('NULL', 'DET') and c['envelope'] is not None]
        alert, failed = context['pc_flags'][task]['alert'], context['pc_flags'][task]['signal_failed']
        t = dict(complete=context['task_complete'][task], alert=alert, contrasts=cs,
            secondary_clause=context['secondary_clause'][task], secondary_check=context['secondary_check'][task],
            reason=context['task_reasons'][task], bound=decimal(max(bound), 3, 'hi') if bound else None, signal_failed=failed,
            mn_effect=decimal(mr.get('effect_percent_reference_mae')) if mr else None, mn_class=CLASS[mr['decision']] if mr else 'NE',
            clk8=clock_record(inputs['clk8'], manifest['inputs']['clk8']) if task == 'notice' else None)
        if t['secondary_clause'] == 'DIFFERENT':
            t['secondary_differing_arms'] = context['secondary_differing_arms'][task]
        if alert:
            t['negative_control'] = context['pc_flags'][task]['negative_control']
            record['kept_alert_sentences'][task] = [F.inherited_form('A6ALERT_S', task_label=F.templates()['words']['PLAIN_TASK_LABEL'][task])]
        record['tasks'][task] = t
    record['squared_not_run_reasons']={t:{r['arm']+'-'+r['reference']:r.get('reason','A8NR_PARITY') for r in batch['squared_loss']['primary'][t] if r['state']=='NOT_RUN'} for t in PAIRS}
    lr = current.get('news/lear', dict(state='NOT_RUN', reports=[]))
    r = lr['reports'][0] if lr['state'] == 'COMPUTED' else None
    record['lear'] = {'class': CLASS[r['decision']] if r else 'NE', 'effect': decimal(r['effect_percent_reference_mae'], 3) if r else None,
                      'reason': context['task_reasons']['news']}
    if Path(manifest['inputs']['clk8']['path']).name=='CLK8_NOT_RUN_DISPOSITION.json':
        record['clk8_not_run_disposition']=manifest['inputs']['clk8']
    else:
        record['clk8_result'] = dict(manifest['inputs']['clk8'], numerator_pointer='/listed_by_admission_n',
            coverage=inputs['clk8']['coverage'], listed_by_admission_n=inputs['clk8'].get('listed_by_admission_n'))
    if manifest['schema']=='A8POST_INPUTS_V2':
        from native_tables import table_records as complete_tables
        record['source_tables'], record['forest_rows']=complete_tables(primary_tests,sensitivity_tests,robustness_tests,F,current,inputs['loss_export']['clipping'],record['stages'],propagation)
        from consumer_fields import fill
        fill(F,primary_tests,sensitivity_tests,robustness_tests,record,inputs,manifest,current,propagation)
        from robustness_fields import align
        align(F,primary_tests,sensitivity_tests,robustness_tests,record,inputs,manifest,current,propagation)
        for row in record['forest_rows']:
            if row['group']=='Primary':
                c=next(c for c in record['tasks'][row['task']]['contrasts'] if c['arm']==row['arm'] and c['reference']==row['ref'])
                row.update(effect=c['effect_percent'],thick=c['family_one_day'],thin=c['family_seven_day'])
        from reading_rules import form_sequence as full_n0
        full_n0(F,record,current,propagation)
    else:
        record['source_tables'], record['forest_rows']=table_records(current,inputs['loss_export']['clipping'],record['stages'])
        form_sequence(F,record,current)
    caps=propagation['caps']
    from jsonschema import Draft202012Validator
    schema = strict_json(CONSUMER_MS / 'A8_POSTSCORE_INTERFACE.json')
    errors = list(Draft202012Validator(schema).iter_errors(record))
    require(not errors, 'TABLE_RESULTS interface schema violation: '+('; '.join(e.message for e in errors[:3])))
    F.validate_record(record)
    from table_renderer.complete_fill import validate_complete_inputs
    validate_complete_inputs(record, refill=manifest.get('refill', False))
    evidence = dict(schema='A8POST_READING_EVIDENCE_V1', inputs=manifest['inputs'],
                    dependency_pins_sha256=sha256(HERE/'DEPENDENCY_PINS.json'), frozen_2000_parity='PASS' if all(b.get('frozen_parity')!='DEVIATION' for b in bundles.values()) else 'DEVIATION_BUNDLES_SUPPRESSED',
                    current_draws=DRAWS, stage_counts={c:sum(x['counted_category']==c for x in record['stages']) for c in CATEGORIES},
                    A8ST_EXEC=F.stage_text(record), recomputed_conclusion_caps=F.conclusion_caps(record),
                    frozen_A4_caps=caps, bootstrap_memory_limit_bytes=512*1024**2,
                    relation_mapping='PENDING retained; DEVIATION -> NOT_EVALUABLE with native reason; stage retains disposition')
    if replay_evidence is not None:
        evidence['loss_replay']= {k:v for k,v in replay_evidence.items() if k not in ('native','reader','clipping')}
    evidence['frozen_propagation']=primary_tests.json_safe(propagation)
    evidence['rerun_count_all_batch_dispositions'] = sum(x['stage'] in RERUNS and x['postseal']!='--' for x in record['stages'])
    evidence['rerun_count_F_fully_completed'] = sum(x['stage'] in RERUNS and x['postseal']!='--' and x['counted_category']==CATEGORIES[0] for x in record['stages'])
    require(evidence['rerun_count_all_batch_dispositions'] == sum(x['stage'] in RERUNS and x['postseal']!='--' for x in F.stage_rows(record)), 'R5 all-disposition rerun count mismatch')
    return record, evidence


def write_output(out, record, evidence):
    out = Path(out)
    require(not out.exists(), 'Output exists; refuse overwrite')

    out.mkdir(parents=True)
    for name, value in (('A8_POSTSCORE.json', record), ('A8_POSTSCORE_EVIDENCE.json', evidence)):
        with (out/name).open('x') as f:
            json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
            f.write('\n')
    with (out/'A8_POSTSCORE_RECEIPT.json').open('x') as f:
        json.dump(dict(state='A8_POSTSCORE_COMPLETE', outputs=[identity(out/'A8_POSTSCORE.json'), identity(out/'A8_POSTSCORE_EVIDENCE.json')]), f, indent=2)
        f.write('\n')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--production', action='store_true', required=True)
    p.add_argument('--inputs', type=Path, required=True)
    p.add_argument('--inputs-sha256', required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--chunk', type=int, default=512)
    a = p.parse_args(argv)
    try:
        require(not a.out.exists(), 'Output exists; refuse overwrite')

        from freeze_inference import verify
        freeze = verify(HERE/'A8POST_CODE_FREEZE.json')
        require(freeze.get('freeze_readiness') == 'READY_FOR_T5_FREEZE',
                'Staging implementation blocked; resolve PROPOSED_INTERFACE_CHANGES before production freeze')
        record, evidence = build(a.inputs, a.inputs_sha256, a.chunk, production=a.production)
        write_output(a.out, record, evidence)
        print(json.dumps({'state': 'A8_POSTSCORE_COMPLETE', 'output': identity(a.out/'A8_POSTSCORE.json')}))
    except (Refusal, OSError, KeyError, ValueError, RuntimeError) as exc:
        print('inference REFUSED: '+str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
