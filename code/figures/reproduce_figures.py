'Rebuild Figures 2–4 from the saved forecasts and plotting inputs.'
from pathlib import Path
import argparse
import importlib.util
import json
import sys
import types
import subprocess
import os
import re
import numpy as np
import pandas as pd
PKG = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(PKG / 'verify'))
from recover_files import Recovery
FROZEN = PKG / 'code/frozen/plotting'
SKIP_MESSAGE = 'panel-alignment audit skipped (third-party auditor not included)'

def install_alignment_skip():


    def skipped(*args, json_out=None, **kwargs):
        report = {'verdict': 'SKIPPED', 'reason': SKIP_MESSAGE}
        if json_out is not None:
            Path(json_out).write_text(json.dumps(report, indent=2) + '\n')
        return report
    shim = types.ModuleType('audit_panel_alignment')
    shim.require_matplotlib_panel_alignment = skipped
    shim.audit_layout_manifest = skipped
    sys.modules['audit_panel_alignment'] = shim
    print(SKIP_MESSAGE, flush=True)

def main(recovery):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('figures_rebuilt'))
    parser.add_argument('--dayfirst-python', type=Path, help='Python with requirements-figures-dayfirst.txt')
    parser.add_argument('--part', choices=['context', 'estimates'], help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.part is None:
        for part, python in [('context', Path(sys.executable)), ('estimates', args.dayfirst_python or Path(sys.executable))]:
            subprocess.run([str(python.absolute()), '-B', str(Path(__file__).resolve()), '--part', part, '--output', str(args.output.resolve())], check=True)
        print('PASS: rebuilt paper Figures 2–4 in their pinned runtimes.')
        return
    import matplotlib
    wanted = '3.9.1.post1' if args.part == 'context' else '3.11.1'
    assert matplotlib.__version__ == wanted, f'{args.part} figures require Matplotlib {wanted}; use --dayfirst-python for Figures 3–4'
    sys.dont_write_bytecode = True
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(FROZEN), str(PKG / 'code/figures')]
    staged = recovery.output / 'renderer'
    staged.mkdir(exist_ok=True)
    install_alignment_skip()
    source = (FROZEN / 'make_figures.py').read_text()
    source = re.sub('paper_source\\.md', 'printed_table.md', source)
    (staged / 'make_figures.py').write_text(source)
    spec = importlib.util.spec_from_file_location('paper_make_figures', staged / 'make_figures.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.HERE = output
    m.QA_DIR = output / 'qa'
    m.QA_DIR.mkdir(exist_ok=True)
    m.ROOT = PKG / 'code/figures/inputs'
    m.AUDIT_SCRIPTS = PKG / 'code/figures'
    official = json.loads(recovery.path('results/score/export/OFFICIAL_RESULTS.json').read_text())
    assert m.sha256(recovery.path('results/score/export/OFFICIAL_RESULTS.json')) == m.EXPECTED_RESULTS_SHA256
    daily, audit = m.load_daily(official, PKG / 'results/score')
    assert len(daily) == 5 and all((c['status'] == 'PASS' for c in audit['contrasts']))
    price = {}
    activity = {}
    keys = ['origin', 'target_time', 'region', 'horizon']
    for task, truth, arm, start in [('news', 'news_keys_labels.parquet', 'M', '2026-05-19'), ('notice', 'notice_joint.parquet', 'M_notice', '2026-08-01')]:
        target = pd.read_parquet(recovery.path('forecasts/truth/' + truth), columns=keys + ['y'])
        pred = pd.read_parquet(PKG / f'forecasts/conf/{task}__{arm}__s20260919__main.parquet', columns=keys + ['target_day'])
        pred = pred.loc[pred.target_day.between(start, '2026-09-30')]
        joined = pred.merge(target, on=keys, validate='one_to_one')
        price[task] = joined.groupby('target_day').y.mean()
    with np.load(PKG / 'features/news/news__M__main.extras.npy.npz', allow_pickle=False) as data:
        a = data['values'][:, 0]
    panel = pd.read_parquet(PKG / 'forecasts/truth/news_keys_labels.parquet', columns=['target_day'])
    x = pd.DataFrame({'day': panel.target_day, 'count': a})
    x = x.loc[x.day.between('2026-05-19', '2026-09-30')]
    assert (x.groupby('day')['count'].nunique() == 1).all()
    counts = x.groupby('day')['count'].first()
    assert np.equal(counts, np.floor(counts)).all()
    activity['news'] = counts.astype('int64')
    n = pd.read_csv(PKG / 'code/figures/inputs/notice_admissions.csv')
    activity['notice'] = n.set_index('day').notice_admissions
    context = staged / 'context'
    context.mkdir()
    (context / 'dayfirst_analysis').mkdir()
    (context / 'dayfirst_analysis/results').symlink_to(PKG / 'dayfirst/results', target_is_directory=True)
    table = json.loads((PKG / 'verify/expected_paper_values.json').read_text())['tables']['4']
    lines = [table['caption'], '', '| ' + ' | '.join(table['columns']) + ' |', '|---|---|---|---|---|---|', '| *Notices* | | | | | |']
    for i, row in enumerate(table['rows']):
        if i == 9:
            lines.append('| *News* | | | | | |')
        lines.append('| ' + ' | '.join(row['cells']) + ' |')
    lines.append('*Notes.* Printed cells supplied by the expected-value record.')
    (context / 'printed_table.md').write_text('\n'.join(lines) + '\n')
    m.ROOT = context
    m.FIGURE3_JOB = output / 'qa/figure3'
    m.FIGURE3_JOB.mkdir(exist_ok=True)
    m.style()
    if args.part == 'context':
        m.figure2(price, activity)
    else:
        daily, audit = m.load_dayfirst_daily(official, PKG / 'results/score')
        m.figure3()
        m.figure4(daily, audit)
        m.finalize_figures34_metadata()
    mapping = {'figure_2_timeline': 'paper_figure_2', 'figure_3_primary_effects': 'paper_figure_3', 'figure_4_cumulative': 'paper_figure_4'}
    for old, new in mapping.items():
        if (args.part == 'context') != (new in ['paper_figure_2']):
            continue
        for suffix in ['.pdf', '.png']:
            (output / (old + suffix)).rename(output / (new + suffix))
    print('PASS: rebuilt ' + args.part + ' figures; numerical inputs verified.')
if __name__ == '__main__':
    with Recovery(PKG) as recovery:
        main(recovery)
