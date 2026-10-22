"""CONFX8 measurements under the new memory rule (CONFX8/SPEC.md section 7). Synthetic production shapes only.

    python measure_fit_memory.py --old-root DIR --new-root DIR --scratch DIR --out MEMORY_MEASUREMENTS.json

`--old-root` and `--new-root` are scratch copies of CONF with the pre-CONFX7 and CONFX8 adapters; old RSS guard overridden to 3.5 GiB in this harness only. Each fit runs
`execution_adapter._worker` in a fresh process. The parent samples the worker's RSS and anonymous memory
(`anonymous_memory.anonymous_bytes`, macOS physical footprint) every 50 ms. The new worker also records its own
lifetime anonymous peak. Data generation reuses `CONFX6/audit_resource_guards.make_fit_case`. Only to be run while
no CONF process is running.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, importlib.util, json, os, subprocess, sys, threading, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONF = HERE.parent
PY = sys.executable
MEASUREMENT_OLD_JOB_LIMIT = 3758096384

def measurement_only_old_limit(ex, label):
    # The archived worker checks RSS, not anonymous memory. Never called from production.
    if label == 'old':
        ex.JOB_LIMIT = MEASUREMENT_OLD_JOB_LIMIT
        return {'scope': 'MEASUREMENT_ONLY', 'old_guard_measure': 'RSS', 'limit_bytes': ex.JOB_LIMIT}
    return None
GIB = 1024 ** 3
NOTICE_TRAIN_ROWS, NOTICE_QUERY_ROWS = 894901, 527040


def measurement_binding():
    from measurement_gate import binding
    return binding()

def verify_measurement_roots(old_root, new_root):
    """Code-only identity checks; never reads production features or outputs."""
    digest = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    manifest = json.loads((HERE / 'staging/STAGING_MANIFEST.json').read_text())['files']
    parent = json.loads((CONF / 'CONFX7/AMENDED_ADAPTER_CHAIN.json').read_text())
    # The parent chain is immutable; its freeze is preserved by the CONFX8 installation.
    freeze_path = HERE / 'archive/pre_CONFX8/CONFX2/ADAPTER_FREEZE.json'
    if not freeze_path.exists(): freeze_path = CONF / 'CONFX2/ADAPTER_FREEZE.json'
    if digest(freeze_path) != parent['amended_adapter_freeze']['sha256']:
        raise SystemExit('CONFX7 parent freeze drift')
    frozen = json.loads(freeze_path.read_text())['files']
    for rel, item in {**{k:v for k,v in frozen.items() if k.endswith('.py') and not k.startswith('../')}, **manifest}.items():
        if digest(Path(new_root) / 'CONFX2' / rel) != item['sha256']:
            raise SystemExit('new measurement code drift: ' + rel)
    before = json.loads((CONF / 'CONFX7/BEFORE_IDENTITIES.json').read_text())
    for rel, item in before.items():
        if rel.startswith('CONFX2/') and rel.endswith('.py') and digest(Path(old_root) / rel) != item['sha256']:
            raise SystemExit('pre-CONFX7 measurement code drift: ' + rel)
    for root in (Path(old_root), Path(new_root)):
        for name in ('DESIGN_CONFIG.json', 'FREEZE.json', 'ENCODER_LOCK.json'):
            if digest(root / name) != digest(CONF / name): raise SystemExit('measurement design drift: ' + name)

def audit_module():
    spec = importlib.util.spec_from_file_location('confx6_audit', CONF / 'CONFX6' / 'audit_resource_guards.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def run_fit(code_root, case, folder, out_name):
    """Fresh process: one registered fit through the code root's unchanged-or-amended worker."""
    if case['source'] == 'news':                     # frozen scheduler.worker_init for news workers
        for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
            os.environ[key] = '1'
    sys.path.insert(0, str(Path(code_root) / 'CONFX2'))
    import runtime, execution_adapter as ex  # noqa: E401,E402
    override = measurement_only_old_limit(ex, out_name.removeprefix('out_'))
    folder = Path(folder); bundle = json.loads((folder / 'bundle.json').read_text())
    scheduler = runtime.conf_module('scheduler')
    task = scheduler.FitTask(case['source'], case['origin'] if case['source'] == 'news' else 'prewindow_frozen_C_bank',
                             case['arm'], 20260919)
    permit = runtime.conf_module('guard').ExecutionPermit('SYNTHETIC_ONLY', 'a' * 64, 'b' * 64, True)
    stats = {}
    for p in [Path(item['path']) for item in (bundle['shared_numeric'], bundle['extras_matrix'], bundle['feature_order'])] + [Path(bundle['panel_path'])]:
        s = p.resolve().stat(); stats[str(p.resolve())] = [s.st_size, s.st_mtime_ns]
    rec = ex._worker((task, bundle, 'c' * 64, stats, permit, str(folder / out_name)))
    keep = {k: rec.get(k) for k in ('state', 'error', 'train_rows', 'prediction_rows', 'features', 'runtime_seconds',
                                    'peak_rss_bytes', 'peak_anonymous_bytes', 'model_sha256', 'prediction_sha256',
                                    'prediction_key_sha256', 'train_indices_sha256', 'job_anonymous_limit_bytes')}
    if rec.get('model_path'):
        keep['model_text_sha256'] = hashlib.sha256(Path(rec['model_path']).read_bytes()).hexdigest()
    keep['measurement_only_limit_override'] = override
    print('RESULT ' + json.dumps(keep))


def sample(pid, stop, out, code_root):
    import psutil
    sys.path.insert(0, str(Path(code_root) / 'CONFX2'))
    import anonymous_memory as am
    rss = anon = 0
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    while not stop.is_set():
        try:
            rss = max(rss, proc.memory_info().rss)
            a = am.anonymous_bytes(pid)
            if a is not None: anon = max(anon, a)
        except psutil.NoSuchProcess:
            break
        time.sleep(.05)
    out.update(sampled_max_rss_bytes=rss, sampled_max_anonymous_bytes=anon)


def require_idle_host():
    cli = subprocess.run(['/usr/bin/pgrep', '-f', 'CONFX2/cli.py'], capture_output=True, text=True)
    if cli.returncode not in (0, 1): raise SystemExit('cannot verify host liveness; measurement refused')
    if cli.stdout.strip(): raise SystemExit('CONF CLI running; measurement refused')
    pressure = subprocess.run(['/usr/bin/memory_pressure'], capture_output=True, text=True, check=True).stdout
    import re
    free = re.search(r'System-wide memory free percentage: (\d+)%', pressure)
    if not free or int(free.group(1)) < 40: raise SystemExit('memory free below 40%; measurement refused')

def measured(cmd, sampler_root):
    stop = threading.Event(); out = {}; started = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    thread = threading.Thread(target=sample, args=(proc.pid, stop, out, sampler_root)); thread.start()
    stdout, stderr = proc.communicate(); stop.set(); thread.join(); out['wall_seconds'] = time.monotonic() - started
    result = next((json.loads(l[7:]) for l in stdout.splitlines() if l.startswith('RESULT ')), None)
    return {'returncode': proc.returncode, 'result': result, **out, 'stderr_tail': stderr[-1500:] if proc.returncode else None}


def parent_baseline(code_root):
    """Anonymous footprint of an orchestrator-like process: CLI imports plus a 30-bundle manifest in memory."""
    code = ('import sys, json; sys.path.insert(0, %r)\n'
            'import runtime, execution_adapter, seal_score, psutil, pandas, numpy, anonymous_memory as am, os\n'
            'manifest = {"bundles": [{"columns": ["c%%d" %% i for i in range(1258)], "pruned_names": [], '
            '"original_columns": ["c%%d" %% i for i in range(1258)]} for _ in range(30)]}\n'
            'print("RESULT " + json.dumps({"anonymous": am.anonymous_bytes(os.getpid()), "rss": psutil.Process().memory_info().rss}))\n'
            % str(Path(code_root) / 'CONFX2'))
    out = subprocess.run([PY, '-B', '-c', code], capture_output=True, text=True, check=True).stdout
    return next(json.loads(l[7:]) for l in out.splitlines() if l.startswith('RESULT '))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode')
    s = sub.add_parser('fit'); s.add_argument('--code-root'); s.add_argument('--case'); s.add_argument('--folder'); s.add_argument('--out-name')
    parser.add_argument('--old-root'); parser.add_argument('--new-root'); parser.add_argument('--scratch'); parser.add_argument('--out')
    args = parser.parse_args()
    if args.mode == 'fit':
        return run_fit(args.code_root, json.loads(args.case), args.folder, args.out_name)
    require_idle_host()
    verify_measurement_roots(args.old_root, args.new_root)
    audit = audit_module()
    scratch = Path(args.scratch); scratch.mkdir(parents=True, exist_ok=False)
    news_shared, news_wide, notice_shared, notice_wide, notice_l14 = 872, 386, 61, 387, 17
    cases = [
        ({'name': 'news_L_chen_last_origin_full_shape', 'source': 'news', 'arm': 'L_chen', 'origin': '2026-09-30',
          'shared': news_shared, 'extras': news_wide}, ('old', 'new')),
        ({'name': 'news_N_last_origin_full_shape', 'source': 'news', 'arm': 'N', 'origin': '2026-09-30',
          'shared': news_shared, 'extras': 0}, ('new',)),
        ({'name': 'notice_L_chen_notice_R225000', 'source': 'notice', 'arm': 'L_chen_notice', 'train_rows': 225000,
          'query_rows': round(225000 * NOTICE_QUERY_ROWS / NOTICE_TRAIN_ROWS), 'shared': notice_shared, 'extras': notice_wide}, ('old', 'new')),
        ({'name': 'notice_L_chen_notice_R450000', 'source': 'notice', 'arm': 'L_chen_notice', 'train_rows': 450000,
          'query_rows': round(450000 * NOTICE_QUERY_ROWS / NOTICE_TRAIN_ROWS), 'shared': notice_shared, 'extras': notice_wide}, ('new',)),
        ({'name': 'notice_L14_R450000', 'source': 'notice', 'arm': 'L14', 'train_rows': 450000,
          'query_rows': round(450000 * NOTICE_QUERY_ROWS / NOTICE_TRAIN_ROWS), 'shared': notice_shared, 'extras': notice_l14}, ('new',)),
        # Full production notice rows: measured directly because the idle 8 GiB host allows it (new worker only).
        ({'name': 'notice_L_chen_notice_full_rows', 'source': 'notice', 'arm': 'L_chen_notice', 'train_rows': NOTICE_TRAIN_ROWS,
          'query_rows': NOTICE_QUERY_ROWS, 'shared': notice_shared, 'extras': notice_wide}, ('new',))]
    result = {'task': 'CONFX8', 'time_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'synthetic_only': True,
              'old_root': args.old_root, 'new_root': args.new_root, 'parent_baseline': parent_baseline(args.new_root),
              'cases': [], 'binding': measurement_binding(),
              'measurement_only_old_limit_bytes': MEASUREMENT_OLD_JOB_LIMIT}
    for case, roots in cases:
        require_idle_host()
        folder = scratch / case['name']
        made = subprocess.run([PY, '-B', str(CONF / 'CONFX6' / 'audit_resource_guards.py'), 'make', '--code-root', args.new_root,
                               '--case', json.dumps(case), '--folder', str(folder)], capture_output=True, text=True, check=True)
        entry = {'case': case, 'data': json.loads(made.stdout.strip().splitlines()[-1]), 'runs': {}}
        for label in roots:
            require_idle_host()
            root = args.old_root if label == 'old' else args.new_root
            entry['runs'][label] = measured([PY, '-B', __file__, 'fit', '--code-root', root, '--case', json.dumps(case),
                                             '--folder', str(folder), '--out-name', 'out_' + label], args.new_root)
            r = entry['runs'][label]
            print(json.dumps({'case': case['name'], 'code': label, 'state': (r['result'] or {}).get('state'),
                              'rss': r.get('sampled_max_rss_bytes'), 'anonymous': r.get('sampled_max_anonymous_bytes'),
                              'worker_anonymous_peak': (r['result'] or {}).get('peak_anonymous_bytes'),
                              'runtime': (r['result'] or {}).get('runtime_seconds')}), flush=True)
        if 'old' in entry['runs'] and 'new' in entry['runs']:
            o, n = entry['runs']['old']['result'] or {}, entry['runs']['new']['result'] or {}
            entry['bit_identity'] = {k: o.get(k) == n.get(k) and o.get(k) is not None for k in
                                     ('model_sha256', 'model_text_sha256', 'prediction_sha256', 'prediction_key_sha256',
                                      'train_indices_sha256', 'train_rows', 'prediction_rows', 'features')}
        result['cases'].append(entry)
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'written': args.out}))


if __name__ == '__main__':
    main()
