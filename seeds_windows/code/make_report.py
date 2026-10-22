'Write the seed and window result report from saved records.'
from __future__ import annotations
import csv
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from run_posthoc import OUT, confirmation, STATE, read, write, sha, resources

INPUT_FILES = {'PLAN.md', 'PLAN.sha256', 'BRIEF.md', 'run.sh', 'run.log',
               'REPORT_final_message.md', 'job_status.txt'}


def number(value, decimals=5, signed=False):
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return ' Not computed '
    return format(float(value), ('+' if signed else '') + '.' + str(decimals) + 'f')


def yes(value):
    return ' Yes ' if value else ' No '


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                      '| ' + ' | '.join(['---']*len(headers)) + ' |'] +
                     ['| ' + ' | '.join(map(str, row)) + ' |' for row in rows]) + '\n'


def feature_text():
    path = OUT / 'FEATURE_CHECKS.json'
    if not path.exists():
        return ' Window features are unavailable ； the specified checks have not run 。\n'
    f = read(path)
    rows = []
    for group, checks in f['checks'].items():
        rows.extend([group, name, ' PASS ' if passed else ' FAIL '] for name, passed in checks.items())
    return (f" The extraction archive contains  {f['record_count']:,}  records  notice， including  {f['failed_record_count']:,}  extraction failures ；"
            f" Training  {f['training_rows']:,}  rows ， evaluation  {f['evaluation_rows']:,}  rows ，"
            f" total  {f['unique_issue_times']:,}  entries  issue  times 。 The window is open on the left 、 and closed on the right  `(t−window, t]`，"
            'W7/F7  is a seven-day count ，W24/F24  is a 24-hour count ，A6  is the six-hour admission count 。'
            ' Counts are  NEM-wide， and repeat in source row order across  region/horizon。28  days  placebo  reuses the saved  '
            '`features.shift_normalized_clocks`。\n\n' +
            table([' Clock ', ' Check ', ' Result '], rows) +
            '\n Complete checks and feature-array hashes ：[FEATURE_CHECKS.json](FEATURE_CHECKS.json)。\n')


def gate_text():
    g = read(OUT / 'EQUIVALENCE_GATE.json')
    rows = [[r['task_id'], r['rows'], number(r['max_abs_difference'], 12),
             number(r['max_abs_difference_sealed'], 12), number(r['max_abs_difference_raw'], 12)]
            for r in g['fits']]
    state = ' PASS ' if g['state'] == 'PASSED' else ' Failed or incomplete '
    return (f" Equivalence gate ：**{state}**。 The tolerance is  `1e-9`； the largest absolute difference is  "
            f"`{g.get('max_abs_difference', ' Not computed ')}`。 Comparisons cover fitted outputs and saved forecasts ，"
            ' using identical prediction keys ； training-index hashes and parameters are checked 。\n\n' +
            table([' Model / origin ', ' Predictions ', ' Maximum fitted-output difference ', ' Maximum saved-forecast difference ', 'raw  maximum difference '], rows))


def resource_text():
    rows = []
    gate = read(OUT / 'EQUIVALENCE_GATE.json')
    if gate['fits']:
        rows.append([' Equivalence gate ', len(gate['fits']), number(gate.get('runtime_seconds'), 2),
                     number(max(r['peak_rss_bytes'] for r in gate['fits'])/1024**3, 3),
                     number(max(r['peak_anonymous_bytes'] for r in gate['fits'])/1024**3, 3)])
    checks = OUT / 'FEATURE_CHECKS.json'
    if checks.exists():
        c = read(checks)
        rows.append([' Window feature construction and checks ', '0  fits ', number(c['runtime_seconds'], 2),
                     number(c['peak_rss_bytes']/1024**3, 3), ' Not measured separately '])
    for key, name in [('no_text_notice', 'Analysis 1 notices'), ('a2_notice', 'Analysis 2 notices'),
                      ('no_text_news', 'Analysis 1 news')]:
        p = OUT / ('STAGE_' + key + '.json')
        if p.exists():
            s = read(p)
            rows.append([name, s['fits'], number(s['runtime_seconds'], 2),
                         number(s['peak_rss_bytes']/1024**3, 3), number(s['peak_anonymous_bytes']/1024**3, 3)])
    if (OUT / 'DECISIONS.json').exists():
        s = read(OUT / 'DECISIONS.json')
        rows.append([' Forecast storage 、 scoring ', '0  fits ', number(s['runtime_seconds'], 2),
                     number(s['peak_rss_bytes']/1024**3, 3), ' Not measured separately '])
    text = table([' Stage ', ' Completed fits ', ' Wall seconds ', ' Maximum per-fit  RSS / GiB', ' Maximum per-fit anonymous memory  / GiB'], rows)
    all_fit = list((OUT / 'fits').glob('*/receipts/*.json'))
    records = [read(p) for p in all_fit]
    completed = [r for r in records if r.get('state') == 'COMPLETE']
    monitored = [r for r in completed if 'min_available_ram_fraction' in r]
    monitored += gate['fits']
    if monitored:
        text += (f"\n Minimum available  RAM  fraction ："
                 f"{min(r['min_available_ram_fraction'] for r in monitored)*100:.4f}%；"
                 f" minimum free disk ：{min(r['min_free_disk_bytes'] for r in monitored)/1024**3:.4f} GiB。\n")
    text += ('\nNotice  fits run sequentially 、`n_jobs=6`；news  uses one thread per fit ， with at most two same-origin  worker，'
             ' with available  RAM  below  15%  allowing at most three  worker  as specified 。 The two task fits do not overlap 。'
             ' Memory uses recorded  macOS lifetime physical-footprint  and  RSS  records ； Table memory is the largest per-fit value within each stage ，'
             ' concurrent  news  process memory is reported separately 。 Per-fit records are in  `fits/*/receipts/`  and  '
             '[results/fit_resources.csv](results/fit_resources.csv)。\n')
    return text


def list_written():
    names = sorted(str(p.relative_to(OUT)) for p in OUT.rglob('*')
                   if p.is_file() and str(p.relative_to(OUT)) not in INPUT_FILES
                   and not p.name.endswith('.tmp'))
    for name in ('REPORT.md', 'FILES_WRITTEN.csv'):
        if name not in names:
            names.append(name)
    return sorted(names)


def finish(text):
    names = list_written()
    text += (f"\n##  Output files \n\n Paths are relative to  `posthoc_20261019/`， total  {len(names)}  files 。"
             ' Input files  PLAN、 hashes 、BRIEF  and execution wrappers are inputs ； using the saved  confirmation  repository data 。'
             ' The machine-readable list is in  [FILES_WRITTEN.csv](FILES_WRITTEN.csv)。\n\n')
    text += '\n'.join('- `' + name + '`' for name in names) + '\n'
    (OUT / 'REPORT.md').write_text(text)
    with (OUT / 'FILES_WRITTEN.csv').open('w', newline='') as stream:
        w = csv.writer(stream)
        w.writerow(['relative_path', 'bytes', 'sha256'])
        for name in names:
            p = OUT / name

            w.writerow([name, p.stat().st_size if p.exists() and name != 'FILES_WRITTEN.csv' else '',
                        sha(p) if p.exists() and name != 'FILES_WRITTEN.csv' else 'SELF'])


def generate():
    d = read(OUT / 'DECISIONS.json')
    if d['state'] != 'COMPLETE':
        raise RuntimeError('Complete fixed-plan decisions required before final report')
    text = '# 2026-10-19  Seed and activity-window analysis \n\n'
    text += (f" Robust reversals  **{d['robust_reversals_count']} / 5**；"
             f" Three  notice  representation gains beyond activity satisfy the robust-gain rule ：**{yes(d['robust_notice_gains_all_three'])}**"
             f"（ satisfying  {d['robust_notice_gains_count']} / 3）。 Results follow  PLAN  rules 。\n\n")
    text += '##  Equivalence gate \n\n' + gate_text()
    text += ('\n##  Scoring definitions \n\n Loss is absolute error ， using fixed  AEST target day  aggregation ， followed by paired comparisons 。'
             'Notice  is  61  days 、 per day  8,640  keys ；news  is  2026-05-19  to  09-30  of  135  days 、 per day  72  keys 。'
             'DM  uses a two-sided standard normal reference distribution 、 variance divisor  n−1、 without autocovariance terms ； Table  p  values are  nominal。'
             ' Intervals use  100,000  draws 、seed=20260925、 seven-day non-circular paired moving-block  bootstrap  of  95%  percentile intervals 。'
             ' Three-seed results average predictions before computing loss ；notice  means are cast to  float32。'
             " Negative  Δ%  indicates that the left model's  MAE  is lower 。 The specified  notice  robust-gain rule adjusts three  p  with  Holm  adjustment 。\n")
    reversals = pd.read_csv(OUT / 'results/reversals.csv', dtype={'seed': str})
    steps = {'activity': ' Activity step ', 'representation': ' Representation step ', 'net': ' Net change '}
    for filename, title in [('analysis1_comparisons.csv', 'Analysis 1： Complete  no-text  seed comparisons '),
                            ('analysis2_comparisons.csv', 'Analysis 2： window  notice  activity reference ')]:
        frame = pd.read_csv(OUT / 'results' / filename, dtype={'seed': str})
        text += '\n## ' + title + '\n'
        for (analysis, task, seed), subset in frame.groupby(['analysis', 'task', 'seed'], sort=False):
            text += '\n### ' + analysis + ' / ' + task + ' / ' + (' Three-seed mean prediction ' if seed == 'mean' else seed) + '\n\n'
            values = []
            for row in subset.itertuples(index=False):
                reversal = '—'
                if row.step == 'net':
                    r = reversals.loc[(reversals.analysis == analysis) & (reversals.task == task) &
                        (reversals.seed == seed) & (reversals.representation == row.representation)].iloc[0]
                    reversal = yes(r.reversal)
                values.append([row.representation_name, steps[row.step], number(row.mae, 5),
                    number(row.reference_mae, 5), number(row.delta_percent, 5, True),
                    format(row.p_nominal, '.6g'), '['+number(row.interval95_low_percent, 5)+', '+
                    number(row.interval95_high_percent, 5)+']', reversal])
            text += table([' Representation ', ' Step ', 'MAE', ' Reference  MAE', 'Δ%', 'p', '95%  Seven-day interval  / %', ' Reversal '], values)
    text += '\n## Analysis 2： Fixed  38  days  placebo  Comparison \n\n'
    text += ' Only  W7、seed 20260919；2026-08-24  to  09-30  of  38  entries  target day， with the specified  Table 4  the same 。\n\n'
    p = pd.read_csv(OUT / 'results/placebo_comparisons.csv')
    placebo_names = {'unshifted_vs_shifted_archive': 'Archive embeddings  versus  28  day-shifted  Archive embeddings',
                     'shifted_archive_vs_shifted_activity': ' Shifted  Archive embeddings  versus shifted activity '}
    text += table([' Comparison ', 'MAE', ' Reference  MAE', 'Δ%', 'p', '95%  Seven-day interval  / %'],
        [[placebo_names[r.step], number(r.mae, 5), number(r.reference_mae, 5), number(r.delta_percent, 5, True),
          format(r.p_nominal, '.6g'), '['+number(r.interval95_low_percent, 5)+', '+number(r.interval95_high_percent, 5)+']']
         for r in p.itertuples(index=False)])
    text += '\n##  Decision rules \n\n'
    robust = pd.read_csv(OUT / 'results/robust_reversals.csv')
    gains = pd.read_csv(OUT / 'results/robust_notice_gains.csv')
    text += '1.  All seeds 、 three-seed means 、W7  and  W24  are reported ； without selection by results 。\n\n'
    text += f"2.  Robust reversals  **{d['robust_reversals_count']} / 5**。News  activity reference in  Analysis 2  is fixed 。\n\n"
    text += table([' Task ', ' Representation ', ' Original-reference mean reversal ', 'W7  Mean reversal ', ' Robust reversal '],
        [[r.task, r.representation_name, yes(r.original_mean_reversal), yes(r.w7_mean_reversal), yes(r.robust_reversal)]
         for r in robust.itertuples(index=False)])
    text += ('\n3. W7  under three-seed mean forecasts ，notice  representation steps are negative and the three-representation  Holm p < 0.05  results are listed below ；'
             f" Three  notice  all gains are robust ：**{yes(d['robust_notice_gains_all_three'])}**。\n\n")
    text += table([' Representation ', ' Representation step  Δ%', 'nominal p', 'Holm p', ' Satisfies robust-gain rule '],
        [[r.representation_name, number(r.delta_percent, 5, True), format(r.p_nominal, '.6g'),
          format(r.p_holm_notice_family, '.6g'), yes(r.robust_gain)] for r in gains.itertuples(index=False)])
    text += ('\n4. Notice  Reversals under  W7  three-seed means all disappear ：**'+yes(d['notice_reversals_disappear_under_w7'])+'**。'
             + (' Under the rule ， the reference-reversal conclusion depends on the  news  Task 。' if d['notice_reversals_disappear_under_w7'] else
                ' The condition is not met 。') + '\n\n5.  The specified windows 、 seeds 、 features and models are fixed 。\n')
    text += '\n##  Feature checks \n\n' + feature_text()
    text += '\n##  Runtime 、 memory and computation details \n\n' + resource_text()
    text += ('\n Statistical definitions follow the specification 。 The saved scheduler uses  confirmation， the execution  runner：'
             ' calls the saved  `_worker`， with in-memory audit destinations and input interfaces 。Analysis 1  varies only  seed；'
             'Analysis 2  replaces only activity counts ，A6  and representation columns 、 training selection 、 weights 、 parameters 、 and prediction keys remain fixed 。'
             ' Large matrices and  embeddings  use read-only memory mapping ， without extra disk copies 。'
             ' Repository  notice truth  uses split  gzip， Scoring reads the  SOURCE_MAP/RECOVERY  hash-verified  '
             'confirmation  source ， without decompression 、 copying or replacing  truth； Input locations are in  TRUTH_DELIVERY.json。'
             ' Execution  bare nohup  attempts before  Python  initialization ended ， then used  bash wait； without fitting 。'
             ' See  [DIFFERENCES.md](DIFFERENCES.md)  and  [RUNBOOK.md](RUNBOOK.md)。\n')
    if (OUT / 'FINAL_CHECKS.json').exists():
        verified = read(OUT / 'FINAL_CHECKS.json')
        text += ('\n Final checks ： Specified table row counts 、 the activity-plus-representation net-change identity 、 resource limits 、'
                 "PLAN/ code / and feature hashes all pass 。14  representation comparisons' estimates and  nominal p  agree with the saved results ，"
                 f" the maximum absolute difference is  `{verified['max_official_parity_absolute_difference']:.17g}`。"
                 ' Records are in  [FINAL_CHECKS.json](FINAL_CHECKS.json)。 Computations use the saved data and numerical fitting / scoring ，'
                 ' without network access 、LLM  requests or re-encoding 。\n')
    finish(text)


def stopped():
    stop = read(OUT / 'STOP.json')
    text = '# 2026-10-19  Seed and window analysis ： Stop report \n\n'
    text += '** The specified analysis is incomplete ， Further fitting and scoring have stopped 。**\n\n'
    text += f" Stopped stage ：`{stop['stage']}`。 Reason ：`{stop['error']}`。 The specified windows 、 seeds 、 models and scoring remain fixed 。\n\n"
    text += '##  Equivalence gate \n\n' + gate_text()
    text += ('\n## Analysis 1、Analysis 2  and decisions \n\n'
             ' Completed predictions and receipts are retained ； Scoring follows fitting ， incomplete specifications are not scored 。'
             ' Each  seed  and three-seed mean activity steps 、 Representation step 、 Net change 、MAE、Δ%、p、 intervals and reversal indicators are incomplete 。'
             ' Robust reversal count ：** Not computed ， cannot be recorded as  0**。Notice  whether gains are robust ：** Undetermined ， cannot be recorded as No **。'
             'PLAN  Decision rules  1–4  incomplete ； Rule  5  The specification is fixed 。\n')
    text += '\n##  Feature checks \n\n' + feature_text()
    text += '\n##  Recorded resources and computation details \n\n' + resource_text()
    text += '\n Resources at stopping ：\n\n```json\n'+json.dumps(stop.get('resources'), ensure_ascii=False, indent=2)+'\n```\n'
    text += ('\n The analysis is incomplete under the recorded stopping condition ； using the saved  PLAN  materials 。 execution  runner  details are in  '
             '[DIFFERENCES.md](DIFFERENCES.md)， Exact commands are in  [RUNBOOK.md](RUNBOOK.md)。\n')
    finish(text)


if __name__ == '__main__':
    stopped() if '--stopped' in sys.argv else generate()
