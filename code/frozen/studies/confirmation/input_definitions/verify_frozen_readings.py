"""CONFX5 proof that every frozen reading is unchanged on identical synthetic predictions.

The synthetic score fixtures of manuscript_tex/test_fill_conf_results.py (`rich`, `degenerate`,
`confx2_test_fixture`) are built twice from the same deterministic prediction levels: once for the
pre-CONFX5 code with the frozen plan, once for the CONFX5 code with the registered plan (the extra
W2_D/NPM fits get their own levels). Each run is a separate subprocess importing only its own code
root. Every frozen output is compared; the only permitted differences are the CONF-A1 changes named
in CONFX5/SPEC.md section 4 (shift-dependent notice slots on 38 days, the E3 joint reading that uses
them, and added A1 slots, fields, files and descriptive columns). Synthetic data only.

    python verify_frozen_readings.py --pre PRE_ROOT --post POST_ROOT --scratch DIR --out JSON
"""
from __future__ import annotations
import argparse, csv, hashlib, importlib.util, io, json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[3]
FILL_TEST = PROJ / 'manuscript_tex/test_fill_conf_results.py'
PY = sys.executable
FIXTURES = ('rich', 'degenerate', 'null', 'confx2_test_fixture')
SHIFT_ARMS = ('M_shift_notice', 'P_shift', 'NPP')


def worker(code_root, plan_kind, fixture, scratch, out):
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(code_root) / 'CONFX2'))
    import runtime, execution_adapter as ex, seal_score as ss  # noqa: E401
    for module in (runtime, ex, ss):
        assert Path(module.__file__).resolve().is_relative_to(Path(code_root).resolve()), module.__file__
    spec = importlib.util.spec_from_file_location('fill_fixture_source', FILL_TEST)
    fill = importlib.util.module_from_spec(spec); spec.loader.exec_module(fill)
    scheduler = runtime.conf_module('scheduler')

    class Scheduler:
        NEWS_PRIMARY = scheduler.NEWS_PRIMARY
        NEWS_SECONDARY = scheduler.NEWS_SECONDARY + (('W2_D',) if plan_kind == 'amended' else ())
        NOTICE_PRIMARY = scheduler.NOTICE_PRIMARY
        FitTask = scheduler.FitTask
        def plan(self):
            return ex.registered_plan() if plan_kind == 'amended' else scheduler.plan()

    class Runtime:
        def __getattr__(self, name):
            return getattr(runtime, name)
        def conf_module(self, name):
            return Scheduler() if name == 'scheduler' else runtime.conf_module(name)

    frozen_news, frozen_notice = fill.offsets_news, fill.offsets_notice
    def offsets_news(t, kind):
        table = frozen_news(t, kind)
        table['W2_D'] = table['M'] - 0.01 + 0.02 * fill.std_noise(91, len(t))        # registered A1 arm only
        return table
    def offsets_notice(t, kind):
        table = frozen_notice(t, kind)
        table['NPM'] = table['NP'] + 0.01 * fill.std_noise(92, len(t))
        return table
    fill.offsets_news, fill.offsets_notice = offsets_news, offsets_notice
    root = Path(scratch) / (fixture + '__' + plan_kind)
    if fixture == 'confx2_test_fixture':
        features, state, permit = fill.build_confx2_test_fixture(root, Runtime(), ex, ss)
    else:
        fill.stub_complete_grid(ss)
        features, state, permit = fill.build_small_fixture(fixture, root, Runtime(), ex, ss)
    ss.seal(permit, features, state)
    ss.score(permit, features, state)
    scored = state / 'scored'
    files = {}
    for path in sorted(scored.iterdir()):
        if path.suffix == '.json':
            files[path.name] = json.loads(path.read_text())
        elif path.suffix in ('.csv', '.md'):
            files[path.name] = path.read_text()
    Path(out).write_text(json.dumps(files, sort_keys=True))


def without(value, keys):
    if isinstance(value, dict):
        return {k: without(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, list):
        return [without(v, keys) for v in value]
    return value


def csv_rows(text, keep=None):
    rows = list(csv.DictReader(io.StringIO(text)))
    return [r for r in rows if keep is None or keep(r)]


def compare(pre, post):
    checks, differences = [], []
    def check(name, ok, detail=None):
        checks.append({'check': name, 'equal': bool(ok)})
        if not ok:
            differences.append({'check': name, 'detail': detail})
    volatile = {'panel_identity', 'bootstrap_artifact'}
    for name, value in pre.items():
        if name.endswith('.json') and name != 'SCORE_REPORT.json' and name != 'SCORE_RECEIPT.json':
            shifted = '__SECONDARY__' in name and any(arm in name.split('__SECONDARY__')[1].replace('.json', '').split('__')
                                                      for arm in SHIFT_ARMS) and name.startswith('notice')
            if shifted:
                check(name + ' (A1 shift rule, expected change)', True)
                continue
            check(name, without(value, volatile) == without(post.get(name), volatile), name)
    report_pre, report_post = pre['SCORE_REPORT.json'], post['SCORE_REPORT.json']
    for source in ('news', 'notice'):
        a, b = report_pre[source], report_post[source]
        for key in ('sensitivities', 'seed_robustness', 'family_size', 'main_seed'):
            check(f'{source}.{key}', a.get(key) == b.get(key), key)
        check(f'{source}.primary_path file name', Path(a['primary_path']).name == Path(b['primary_path']).name)
        if 'weekly_naive' in a:
            wa, wb = a['weekly_naive'], b['weekly_naive']
            check(f'{source}.weekly_naive state/mae', all(wa.get(k) == wb.get(k) for k in ('state', 'mae', 'missing_keys')), (wa, wb))
            check(f'{source}.weekly_naive rMAE of frozen arms', all(wb.get('rmae', {}).get(arm) == value
                                                                    for arm, value in wa.get('rmae', {}).items()), (wa, wb))
        for arm, value in a['pooled_mae'].items():
            check(f'{source}.pooled_mae.{arm}', value == b['pooled_mae'].get(arm), arm)
        slots = {(s['arm'], s['reference']): s for s in b['secondary']}
        frozen_pairs = [(s['arm'], s['reference']) for s in a['secondary']]
        check(f'{source}.frozen secondary slot order preserved', [(s['arm'], s['reference']) for s in b['secondary']][:len(frozen_pairs)] == frozen_pairs)
        for s in a['secondary']:
            key = (s['arm'], s['reference']); other = slots[key]
            if source == 'notice' and (key[0] in SHIFT_ARMS or key[1] in SHIFT_ARMS):
                check(f'{source}.{key} evaluated on the A1 shift-supported days (expected change)',
                      other.get('a1_day_rule') == 'SHIFT_SUPPORTED_TARGET_DAYS_ONLY' and
                      (other['state'] != 'COMPUTED_SECONDARY' or other['days'] == 38), other)
                continue
            fields = ('state', 'reading', 'daily_mean_difference', 'p_two_sided', 'matched_keys', 'days')
            check(f'{source}.secondary {key}', all(s.get(f) == other.get(f) for f in fields), (s, other))
        check(f'{source}.severe event-equal losses for frozen arms',
              all(b['severe_events'].get('event_equal_losses', {}).get(arm) == value
                  for arm, value in a['severe_events'].get('event_equal_losses', {}).items()))
    if 'e3_joint_state' in report_pre['notice']:
        checks.append({'check': 'notice.e3_joint_state', 'pre': report_pre['notice']['e3_joint_state'],
                       'post': report_post['notice']['e3_joint_state'], 'note': 'A1 decision 5 may change this reading'})
    validation_pre = {r['arm']: r for r in report_pre['validation_2025']}
    validation_post = {r['arm']: r for r in report_post['validation_2025']}
    check('validation_2025 frozen arms', all(validation_post.get(arm) == row for arm, row in validation_pre.items()))
    check('stage dispositions: same stage names and states', [(d['stage'], d['state']) for d in report_pre['stage_dispositions']] ==
          [(d['stage'], d['state']) for d in report_post['stage_dispositions']])
    for source in ('news', 'notice'):
        daily_pre, daily_post = csv_rows(pre[source + '__DAILY_LOSSES.csv']), csv_rows(post[source + '__DAILY_LOSSES.csv'])
        check(f'{source}.daily losses of frozen arms', all({k: r1[k] for k in r1} == {k: r2[k] for k in r1}
                                                          for r1, r2 in zip(daily_pre, daily_post)) and len(daily_pre) == len(daily_post))
        frozen_arms = {r['arm'] for r in csv_rows(pre[source + '__CLIPPING.csv'])}
        check(f'{source}.clipping rows of frozen arms', csv_rows(pre[source + '__CLIPPING.csv']) ==
              csv_rows(post[source + '__CLIPPING.csv'], lambda r: r['arm'] in frozen_arms))
        frozen_arms = {r['arm'] for r in csv_rows(pre[source + '__REGION_HORIZON_MAE.csv'])}
        check(f'{source}.region/horizon MAE of frozen arms', csv_rows(pre[source + '__REGION_HORIZON_MAE.csv']) ==
              csv_rows(post[source + '__REGION_HORIZON_MAE.csv'], lambda r: r['arm'] in frozen_arms))
        primary = pre[source + '__PRIMARY.json']['reports']
        sys.path.insert(0, str(Path(ARGS.post) / 'CONFX2'))
        import report_adapter
        for r in primary:
            sentence = report_adapter.primary_sentence(r, source)
            check(f'{source}.frozen primary sentence {r["arm"]} in both reports',
                  sentence in pre['REPORT_zh.md'] and sentence in post['REPORT_zh.md'])
    check('A1 section only in the CONFX5 report', 'A1' not in report_pre and 'A1' in report_post)
    return checks, differences


def code_identities(root):
    """SHA-256 of every Python file the workers can import, plus the frozen design files used."""
    root = Path(root)
    paths = [*root.glob('CONFX2/*.py'), *root.glob('CONFX2/tests/*.py'), *root.glob('code/*.py'),
             root / 'DESIGN_CONFIG.json', root / 'FREEZE.json']
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def main():
    global ARGS
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode')
    w = sub.add_parser('worker'); w.add_argument('--code-root'); w.add_argument('--plan'); w.add_argument('--fixture')
    w.add_argument('--scratch'); w.add_argument('--out')
    parser.add_argument('--pre'); parser.add_argument('--post'); parser.add_argument('--scratch'); parser.add_argument('--out')
    ARGS = parser.parse_args()
    if ARGS.mode == 'worker':
        return worker(ARGS.code_root, ARGS.plan, ARGS.fixture, ARGS.scratch, ARGS.out)
    scratch = Path(ARGS.scratch); scratch.mkdir(parents=True, exist_ok=False)
    result = {'purpose': __doc__.split('\n')[0], 'synthetic_only': True, 'pre_code_root': ARGS.pre, 'post_code_root': ARGS.post,
              'fill_fixture_source': {'path': str(FILL_TEST), 'sha256': hashlib.sha256(FILL_TEST.read_bytes()).hexdigest()},
              'fixtures': {}, 'code_identities': {label: code_identities(root) for label, root in (('pre', ARGS.pre), ('post', ARGS.post))}}
    for fixture in FIXTURES:
        outputs = {}
        for label, root, plan in (('pre', ARGS.pre, 'frozen'), ('post', ARGS.post, 'amended')):
            out = scratch / f'{fixture}__{label}.json'
            subprocess.run([PY, '-B', __file__, 'worker', '--code-root', root, '--plan', plan, '--fixture', fixture,
                            '--scratch', str(scratch / 'runs'), '--out', str(out)], check=True)
            outputs[label] = json.loads(out.read_text())
        checks, differences = compare(outputs['pre'], outputs['post'])
        a1 = outputs['post']['SCORE_REPORT.json']['A1']
        result['fixtures'][fixture] = {'state': 'PASS' if not differences else 'FAIL', 'checks': len(checks),
            'unexpected_differences': differences, 'e3_joint': [c for c in checks if c.get('check') == 'notice.e3_joint_state'],
            'new_files': sorted(set(outputs['post']) - set(outputs['pre'])),
            'a1_summary': {'seed_fragile': {s: [r['state'] for r in a1['tasks'][s]['seed_fragile']['rows']] for s in ('news', 'notice')},
                           'hln_agrees': {s: [r['agrees_with_primary_decision'] for r in a1['tasks'][s]['hln']['rows']] for s in ('news', 'notice')},
                           'sesoi_branches': {s: [r['branch'] for r in a1['tasks'][s]['sesoi']] for s in ('news', 'notice')},
                           'exposure_days': {s: a1['tasks'][s]['exposure_excluded']['days'] for s in ('news', 'notice')},
                           'official_cap_e3_joint': a1['tasks']['notice']['official_cap'].get('e3_joint_state'),
                           'w2_d': a1['w2_d'], 'npm': a1['npm'], 'lear_convergence': a1['lear_convergence_diagnostic'].get('state'),
                           'per_task_statements': a1['per_task_statements']}}
    result['state'] = 'PASS' if all(f['state'] == 'PASS' for f in result['fixtures'].values()) else 'FAIL'
    Path(ARGS.out).write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + '\n')
    print(json.dumps({'state': result['state'], 'fixtures': {k: (v['state'], v['checks']) for k, v in result['fixtures'].items()}}))


if __name__ == '__main__':
    main()
