"""CONFX7 diagnosis of `Resume panel identity drift` on synthetic notice panels with the production schema
(CONFX7/SPEC_ADDENDUM_2_RESUME_IDENTITY.md).

    python diagnose_resume_drift.py run --old-root DIR [--new-root DIR] --scratch DIR --out RESUME_DRIFT_DIAGNOSIS.json

`--old-root` / `--new-root` are scratch copies of CONF holding the CONFX6 and CONFX7 adapters (`DIR/CONFX2`).
- make-panels (child process): writes notices_train.parquet, notices.parquet, notice_p5_train.parquet,
  notice_p5.parquet and manifest.json with the real CONFX2 panel code. The training loop of
  `panels_adapter.build_panels` is executed verbatim (its source lines are extracted and exec'd) on synthetic
  development metadata that carries the Arrow types of `B1b/development_metadata.parquet` (schema only). The
  confirmation rows come from the real `notice_keys` and `build_notice_numeric` on an in-memory `RawStore` filled
  with synthetic values.
- build-panel (child process): executes verbatim the notice-frame lines of `features_adapter.build_all_features`,
  its P5 lines, the `_write_bundles` prefix and the `_write_bundles` write/compare lines of the given code root.
- run: two independent panel builds; process 1 writes the panel copy; process 2 (another PYTHONHASHSEED) rebuilds
  the panel and runs the CONFX6 resume check against that copy; with `--new-root`, process 3 runs the CONFX7 check.
No study value is read: the frozen numeric column names come from RF2/final/design.json (design file).
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, subprocess, sys, textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[3]
DESIGN = PROJ / 'autopilot/q1_audits/RF2/final/design.json'
METADATA_ARROW_TYPES = {'region': 'string', 'issue_time': 'timestamp[us, tz=UTC]', 'target_time': 'timestamp[us, tz=UTC]',
                        'horizon': 'int16', 'y_true': 'double', 'label_available_time': 'timestamp[us, tz=UTC]',
                        'legal_anchor': 'double', 'weight': 'float', 'bank_month': 'string', 'event_replay_flag': 'float'}


def block(source, first, last, occurrence=1):
    """Exact source lines from the `occurrence`-th line starting with `first` to the next line starting with `last`."""
    lines = source.splitlines()
    i = [k for k, line in enumerate(lines) if line.startswith(first)][occurrence - 1]
    j = next(k for k in range(i + 1, len(lines)) if lines[k].startswith(last))
    return '\n'.join(lines[i:j + 1])


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_panels(code, out, train_rows, days, seed):
    import numpy as np, pandas as pd, pyarrow as pa, pyarrow.parquet as pq
    sys.path.insert(0, str(code))
    import panels_adapter as P
    out.mkdir(parents=True, exist_ok=False)
    rng = np.random.default_rng(seed)
    numeric = json.loads(DESIGN.read_text())['numeric_names']
    raw = P.RawStore(P.aest('2026-07-30'), P.aest('2026-08-01') + pd.Timedelta(days=days + 1), out=None)
    raw.values[...] = rng.normal(90., 40., raw.values.shape)
    raw.values[:, :200, 5] = np.nan                                  # one physical source missing early on
    raw.values[:, rng.random(raw.n) < .02, 2] = np.nan               # sporadic gaps
    raw.price_clock[...] = raw.start + np.arange(raw.n, dtype='int64') * P.FIVE + P.FIVE
    raw.seen[...] = True
    writer = ewriter = None; rows = 0
    for first in pd.date_range('2026-08-01', periods=days, freq='D'):
        keys = P.notice_keys(first.strftime('%Y-%m-%d'), (first + pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
        frame = P.build_notice_numeric(raw, keys, numeric); rows += len(frame)
        writer = P._append(writer, out / 'notices.parquet', frame)
        values = rng.normal(80., 30., (len(frame), 8)); values[rng.random(values.shape) < .01] = np.nan
        ewriter = P._append(ewriter, out / 'notice_p5.parquet', pd.DataFrame(values, columns=P.P5_COLUMNS).astype('float32'))
    writer.close(); ewriter.close()
    n = train_rows
    issue = pd.Timestamp('2021-10-02T00:00:00Z') + pd.to_timedelta(np.sort(rng.integers(0, 800 * 288, n)) * 5, unit='min')
    horizon = rng.choice([5, 10, 15, 20, 25, 30], n).astype('int16')
    target = issue + pd.to_timedelta(horizon.astype('int64'), unit='min')
    flag = (rng.random(n) < .3).astype('float32')
    table = pa.table({
        'region': pa.array(rng.choice(list(P.REGIONS), n), pa.string()),
        'issue_time': pa.array(issue.as_unit('us'), pa.timestamp('us', tz='UTC')),
        'target_time': pa.array(target.as_unit('us'), pa.timestamp('us', tz='UTC')),
        'horizon': pa.array(horizon, pa.int16()),
        'y_true': pa.array(rng.normal(90., 50., n), pa.float64()),
        'label_available_time': pa.array((target + pd.Timedelta(minutes=5)).as_unit('us'), pa.timestamp('us', tz='UTC')),
        'legal_anchor': pa.array(rng.normal(90., 40., n), pa.float64()),
        'weight': pa.array(np.where(flag > .5, 1., 50.).astype('float32'), pa.float32()),
        'bank_month': pa.array(np.asarray(target.tz_convert(P.TZ).strftime('%Y-%m')), pa.string()),
        'event_replay_flag': pa.array(flag, pa.float32())})
    if {f.name: str(f.type) for f in table.schema} != METADATA_ARROW_TYPES:
        raise ValueError('synthetic metadata does not carry the production Arrow types')
    meta = out / 'synthetic_development_metadata.parquet'
    pq.write_table(table, meta)
    matrix = rng.normal(0., 1., (n, len(numeric))).astype('float32'); matrix[rng.random(matrix.shape) < .03] = np.nan
    p5train = rng.normal(80., 30., (n, 8)).astype('float32')
    loop = block(Path(P.__file__).read_text(),
                 " for batch in pf.iter_batches(batch_size=10000,columns=['region','issue_time'", ' writer.close();ewriter.close()')
    namespace = dict(vars(P)); namespace.update(pf=pq.ParquetFile(meta), writer=None, ewriter=None, offset=0, train_rows=0,
                                                 first_issue=P.aest('2026-07-31 23:30'), matrix=matrix, p5train=p5train,
                                                 numeric=numeric, out=out)
    exec(textwrap.dedent(loop), namespace)
    (out / 'manifest.json').write_text(json.dumps({
        'state': 'PANELS_COMPLETE_VALIDATED', 'numeric_columns': {'news': P.NEWS_NUMERIC, 'notices': numeric},
        'p5_columns': P.P5_COLUMNS, 'e3_state': 'READY', 'synthetic': True,
        'notice_p5_train': {'path': str((out / 'notice_p5_train.parquet').resolve())},
        'notice_p5': {'path': str((out / 'notice_p5.parquet').resolve())},
        'train_rows': namespace['train_rows'], 'confirmation_rows': rows}, indent=1))
    print('RESULT ' + json.dumps({'train_rows': namespace['train_rows'], 'confirmation_rows': rows,
                                  'verbatim_training_loop_sha256': hashlib.sha256(loop.encode()).hexdigest()}))


def build_panel(code, panels_root, out, write_copy):
    import numpy as np, pandas as pd, pyarrow as pa
    sys.path.insert(0, str(code))
    import features_adapter as A
    source = Path(A.__file__).read_text()
    lines = {'frame': block(source, "    train=pd.read_parquet(panels_root/'notices_train.parquet')",
                            "    notice['target_day']=notice.target_day.astype(str).str[:10]"),
             'p5': block(source, "    p5cols=panel_manifest.get('p5_columns',panel_manifest.get('p5min_columns',[]))",
                         '        del p5_joint,p5_train,p5_evaluation', 2),
             'prefix': block(source, '    out=Path(out);panel=panel.reset_index(drop=True)',
                             "    if 'day' not in panel:panel['day']=panel.target_day"),
             'write_or_compare': block(source, "    panel_path=out/(source+'_joint.parquet' if source=='notice' else 'news_keys_labels.parquet')",
                                       '    elif ')}
    ns = dict(vars(A)); ns.update(panels_root=Path(panels_root), panel_manifest=json.loads((Path(panels_root) / 'manifest.json').read_text()))
    exec(textwrap.dedent(lines['frame']), ns)
    exec(textwrap.dedent(lines['p5']), ns)
    ns.update(panel=ns['notice'], out=Path(out), source='notice')
    exec(textwrap.dedent(lines['prefix']), ns)
    panel = ns['panel']; Path(out).mkdir(parents=True, exist_ok=True)
    train, evaluation = ns['train'], ns['evaluation']
    clocks = {}
    for col in ('origin', 'target_time', 'label_available', 'issue_time'):
        clocks[col] = {'training_panel': str(train[col].dtype) if col in train else None,
                       'confirmation_panel': str(evaluation[col].dtype) if col in evaluation else None,
                       'after_concat': str(pd.concat([train[[c for c in [col] if c in train]], evaluation[[col]]], ignore_index=True)[col].dtype),
                       'in_panel': str(panel[col].dtype)}
    path = Path(out) / 'notice_joint.parquet'
    existed = path.exists()
    try:
        exec(textwrap.dedent(lines['write_or_compare']), ns)
        check = 'EQUAL_REUSED' if existed else 'WROTE'
    except ValueError as exc:
        check = 'DRIFT: ' + str(exc)
    stored = pd.read_parquet(path)
    differing = {}
    for col in panel.columns:
        if col not in stored.columns:
            differing[col] = 'missing in stored copy'
        elif stored[col].dtype != panel[col].dtype:
            same_values = bool((pd.to_datetime(panel[col], utc=True) == stored[col]).all()) if 'datetime' in str(stored[col].dtype) else None
            differing[col] = {'stored_dtype': str(stored[col].dtype), 'panel_dtype': str(panel[col].dtype),
                              'all_instants_equal': same_values}
        elif not stored[col].equals(panel[col]):
            differing[col] = {'dtype': str(panel[col].dtype), 'values_differ': True}
    result = {'pythonhashseed': os.environ.get('PYTHONHASHSEED'), 'code_root': str(code), 'rows': len(panel),
              'columns': len(panel.columns), 'check': check, 'read_back_DataFrame_equals': bool(stored.equals(panel)),
              'columns_differing_after_read_back': differing, 'clock_columns': clocks,
              'stored_copy_sha256': sha(path), 'versions': {'pandas': pd.__version__, 'pyarrow': pa.__version__, 'numpy': np.__version__},
              'verbatim_line_sha256': {k: hashlib.sha256(v.encode()).hexdigest() for k, v in lines.items()},
              'write_or_compare_lines': lines['write_or_compare']}
    if write_copy:
        panel.to_parquet(write_copy, index=False, compression='zstd')
        result['own_copy_sha256'] = sha(write_copy)
    print('RESULT ' + json.dumps(result))


def child(args, env_seed):
    env = dict(os.environ, PYTHONHASHSEED=str(env_seed))
    done = subprocess.run([sys.executable, '-B', __file__] + args, capture_output=True, text=True, env=env)
    if done.returncode:
        raise RuntimeError(done.stderr[-3000:])
    return next(json.loads(l[7:]) for l in done.stdout.splitlines() if l.startswith('RESULT '))


def run(old_root, new_root, scratch, out):
    scratch = Path(scratch); scratch.mkdir(parents=True, exist_ok=False)
    old, new = str(Path(old_root) / 'CONFX2'), (str(Path(new_root) / 'CONFX2') if new_root else None)
    builds = [child(['make-panels', '--code', old, '--out', str(scratch / name)], seed) for name, seed in (('panels_a', 11), ('panels_b', 12))]
    files = ['notices_train.parquet', 'notices.parquet', 'notice_p5_train.parquet', 'notice_p5.parquet']
    identical_panels = {f: sha(scratch / 'panels_a' / f) == sha(scratch / 'panels_b' / f) for f in files}
    features = scratch / 'features'
    p1 = child(['build-panel', '--code', old, '--panels', str(scratch / 'panels_a'), '--out', str(features),
                '--write-copy', str(scratch / 'own_copy_p1.parquet')], 1)
    p2 = child(['build-panel', '--code', old, '--panels', str(scratch / 'panels_b'), '--out', str(features),
                '--write-copy', str(scratch / 'own_copy_p2.parquet')], 2)
    p3 = child(['build-panel', '--code', new, '--panels', str(scratch / 'panels_b'), '--out', str(features)], 3) if new else None
    deterministic = all(identical_panels.values()) and p1['own_copy_sha256'] == p2['own_copy_sha256'] == p1['stored_copy_sha256']
    result = {'task': 'CONFX7', 'time_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'synthetic_only': True,
              'host_state_contents_read': False, 'window_outcomes_read': False, 'script_sha256': sha(__file__),
              'panel_builds': builds, 'independent_panel_files_byte_identical': identical_panels,
              'process_1_write_and_read_back': p1, 'process_2_confx6_resume_check': p2, 'process_3_confx7_resume_check': p3,
              'findings': {
                  'notice_panel_build_deterministic': deterministic,
                  'confx6_resume_check_false_mismatch': p2['check'].startswith('DRIFT') and deterministic and
                      set(p2['columns_differing_after_read_back']) == {'label_available'} and
                      p2['columns_differing_after_read_back']['label_available'].get('all_instants_equal') is True,
                  'confx7_resume_check_reuses_identical_copy': None if p3 is None else p3['check'] == 'EQUAL_REUSED'}}
    Path(out).write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result['findings']))


def main():
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest='mode', required=True)
    m = sub.add_parser('make-panels'); m.add_argument('--code', required=True); m.add_argument('--out', required=True)
    m.add_argument('--train-rows', type=int, default=30000); m.add_argument('--days', type=int, default=3); m.add_argument('--seed', type=int, default=20261002)
    b = sub.add_parser('build-panel'); b.add_argument('--code', required=True); b.add_argument('--panels', required=True)
    b.add_argument('--out', required=True); b.add_argument('--write-copy')
    r = sub.add_parser('run'); r.add_argument('--old-root', required=True); r.add_argument('--new-root'); r.add_argument('--scratch', required=True)
    r.add_argument('--out', required=True)
    a = p.parse_args()
    if a.mode == 'make-panels':
        make_panels(Path(a.code), Path(a.out), a.train_rows, a.days, a.seed)
    elif a.mode == 'build-panel':
        build_panel(Path(a.code), a.panels, a.out, a.write_copy)
    else:
        run(a.old_root, a.new_root, a.scratch, a.out)


if __name__ == '__main__':
    main()
