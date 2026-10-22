'Score paired daily losses after checking every required forecast seal.'
from __future__ import annotations
import gzip
import importlib.util
import json
from pathlib import Path
import sys
import time
import numpy as np
import pandas as pd
from run_posthoc import (OUT, STUDY, STATE, confirmation, imports, require_gate, read, write,
                         sha, progress, check_resources)

SEEDS = (20260919, 20260920, 20260921)
KEYS = ['origin', 'target_time', 'region', 'horizon']
REPS = {'news': ('L_count', 'L_chen'), 'notice': ('L14', 'L_Laz', 'L_chen_notice')}
NAMES = {'L_count': 'Fields', 'L_chen': 'Embeddings', 'L14': 'Event states',
         'L_Laz': 'Overlap components', 'L_chen_notice': 'Archive embeddings'}
REF = {'news': 'M', 'notice': 'M_notice'}
PACKAGE = STUDY / 'paper_plan/replication_package_20261017/repo'


def import_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seal_all():
    require_gate()
    expected = {'no_text_notice': 2, 'w7': 12, 'w24': 12, 'w7_shift': 2, 'no_text_news': 270}
    for stage in ('no_text_notice', 'a2_notice', 'no_text_news'):
        if read(OUT / ('STAGE_' + stage + '.json'))['state'] != 'COMPLETE':
            raise RuntimeError('Scoring blocked by incomplete stage: ' + stage)
    seal = {'state': 'ALL_POSTHOC_PREDICTIONS_SEALED', 'plan_sha256': sha(OUT / 'PLAN.md'),
            'predictions': [], 'fits': [], 'feature_checks_sha256': sha(OUT / 'FEATURE_CHECKS.json')}
    for group, count in expected.items():
        receipts = sorted((OUT / 'fits' / group / 'receipts').glob('*.json'))
        if len(receipts) != count:
            raise RuntimeError('Fixed fit count differs: ' + group)
        actual_tasks = set()
        for path in receipts:
            r = read(path)
            if r['state'] != 'COMPLETE' or sha(r['prediction_path']) != r['prediction_sha256']:
                raise RuntimeError('Unsealed or altered forecast: ' + str(path))
            seal['fits'].append({'path': str(path), 'sha256': sha(path)})
            actual_tasks.add((r['task']['task'], r['task']['origin'], r['task']['arm'], r['task']['seed']))
            seal['predictions'].append({'group': group, **r['task'], 'path': r['prediction_path'],
                'sha256': r['prediction_sha256'], 'rows': r['prediction_rows']})
        if group == 'no_text_news':
            wanted_tasks = {('news', day, 'N', seed) for day in
                pd.date_range('2026-05-19', '2026-09-30').strftime('%Y-%m-%d') for seed in SEEDS[1:]}
        else:
            arms = (('N',) if group == 'no_text_notice' else ('M_shift_notice', 'P_shift')
                    if group == 'w7_shift' else ('M_notice', *REPS['notice']))
            seeds = SEEDS[1:] if group == 'no_text_notice' else SEEDS[:1] if group == 'w7_shift' else SEEDS
            wanted_tasks = {('notice', 'prewindow_frozen_C_bank', arm, seed) for arm in arms for seed in seeds}
        if actual_tasks != wanted_tasks:
            raise RuntimeError('Fixed task population mismatch before sealing: ' + group)
    if len(seal['predictions']) != 298:
        raise RuntimeError('Seed and window scientific fit population must be exactly 298')
    write(OUT / 'SEAL_POSTHOC.json', seal)
    return seal


class Forecasts:
    def __init__(self, seal, native):
        self.native = native
        self.new = seal['predictions']
        self.entries = {}
        self.used = {}
        for tag, file in [('conf', 'SEAL.json.gz'), ('batch', 'SEAL_BATCH.json.gz')]:
            path = PACKAGE / 'results/seals' / file
            with gzip.open(path, 'rt') as stream:
                saved = json.load(stream)
            self.used[str(path)] = sha(path)
            for e in saved['predictions']:
                if e['source'] not in ('notice', 'news'):
                    continue
                key = (e['source'], e['arm'], int(e['seed']), e['variant'])
                self.entries[key] = {**e, 'path': str(PACKAGE / 'forecasts' / tag / Path(e['path']).name)}
        self.panels = {}
        source_map_path = PACKAGE / 'results/SOURCE_MAP.json'
        recovery_path = PACKAGE / 'RECOVERY.json'
        source_map = read(source_map_path)
        recovery = {r['path']: r for r in read(recovery_path)['files']}
        self.used[str(source_map_path)] = sha(source_map_path)
        self.used[str(recovery_path)] = sha(recovery_path)
        truth_delivery = []
        for task, filename, start, days, count in [
                ('notice', 'notice_joint.parquet', '2026-08-01', 61, 8640),
                ('news', 'news_keys_labels.parquet', '2026-05-19', 135, 72)]:
            relative = 'forecasts/truth/' + filename
            requested = PACKAGE / relative
            binding = [r for r in source_map if r['destination'] == relative]
            if len(binding) != 1 or not binding[0]['byte_identical']:
                raise RuntimeError('Missing exact official truth binding: ' + relative)
            binding = binding[0]
            path = requested
            mode = 'packaged_read_only_copy'
            if not path.exists():
                recovered = recovery[relative]
                if (recovered['sha256'], recovered['bytes']) != (binding['sha256'], binding['bytes']):
                    raise RuntimeError('Compressed truth identity conflicts with source map')


                path = STUDY / binding['source']
                mode = 'byte_identical_official_original_read_only_in_place'
            if path.stat().st_size != binding['bytes'] or sha(path) != binding['sha256']:
                raise RuntimeError('Official truth bytes differ from packaged identity: ' + task)
            truth_delivery.append({'task': task, 'requested': str(requested), 'used': str(path),
                'mode': mode, 'bytes': binding['bytes'], 'sha256': binding['sha256']})
            panel = pd.read_parquet(path, columns=KEYS+['target_day', 'y', 'weight'])
            panel = native.normalize(panel.loc[panel.target_day.astype(str).between(start, '2026-09-30')])
            expected_days = pd.date_range(start, '2026-09-30').strftime('%Y-%m-%d').tolist()
            counts = panel.groupby('target_day', sort=True).size()
            if list(counts.index) != expected_days or len(counts) != days or not counts.eq(count).all():
                raise RuntimeError('Incomplete frozen common daily key grid: ' + task)
            if panel.duplicated(KEYS).any() or not panel.weight.eq(1).all() or not np.isfinite(panel.y).all():
                raise RuntimeError('Frozen truth/key/weight gate failed: ' + task)
            key_path = PACKAGE / 'forecasts/keys' / (task + '__COMMON_KEYS.parquet')
            key_frame = native.normalize(pd.read_parquet(key_path))
            key_frame = key_frame.loc[key_frame.target_day.between(start, '2026-09-30')].reset_index(drop=True)
            if not key_frame[KEYS].equals(panel[KEYS]):
                raise RuntimeError('Truth differs from frozen common-key artifact: ' + task)
            self.used[str(key_path)] = sha(key_path)
            self.panels[task] = panel
            self.used[str(path)] = sha(path)
        write(OUT / 'TRUTH_DELIVERY.json', {'state': 'EXACT_FROZEN_BYTES_VERIFIED', 'files': truth_delivery})
        self.cache = {}

    def load(self, task, arm, seed, group='original'):
        panel = self.panels[task]
        if group == 'original' and (arm != 'N' or seed == 20260919):
            entry = self.entries[(task, arm, seed, 'main')]
            if sha(entry['path']) != entry['sha256']:
                raise RuntimeError('Frozen forecast hash mismatch: ' + entry['path'])
            paths = [entry['path']]
        else:
            wanted_group = 'no_text_' + task if group == 'original' else group
            entries = [x for x in self.new if x['group'] == wanted_group and x['task'] == task
                       and x['arm'] == arm and x['seed'] == seed]
            wanted = 135 if task == 'news' else 1
            if len(entries) != wanted:
                raise RuntimeError('New forecast population mismatch: ' + str((task, arm, seed, group)))
            paths = [x['path'] for x in entries]
        frames = []
        for path in paths:
            frames.append(pd.read_parquet(path, columns=KEYS+['target_day', 'prediction']))
            self.used[str(path)] = sha(path)
        f = self.native.normalize(pd.concat(frames, ignore_index=True))
        f = f.loc[f.target_day.between(panel.target_day.min(), panel.target_day.max())].reset_index(drop=True)
        if not f[KEYS].equals(panel[KEYS]) or not f.target_day.equals(panel.target_day):
            raise RuntimeError('Forecast differs from exact common keys: ' + str((task, arm, seed, group)))
        prediction = f.prediction.to_numpy(dtype='float64')
        if not np.isfinite(prediction).all():
            raise RuntimeError('Nonfinite predictions')
        return prediction

    def losses(self, task, arm, seed, group='original', placebo=False):
        key = (task, arm, seed, group, placebo)
        if key not in self.cache:
            if seed == 'mean':
                prediction = np.mean([self.load(task, arm, s, group) for s in SEEDS], axis=0)
                if task == 'notice':
                    prediction = prediction.astype('float32')
            else:
                prediction = self.load(task, arm, seed, group)
            panel = self.panels[task]
            mask = panel.target_day.ge('2026-08-24').to_numpy() if placebo else None
            days, losses = self.native._daily(panel, prediction, mask)
            if len(days) != (38 if placebo else 61 if task == 'notice' else 135):
                raise RuntimeError('Daily aggregation shortened the fixed window')
            self.cache[key] = (days, losses)
        return self.cache[key]


def score():
    start = time.monotonic()
    check_resources()
    sealed = seal_all()
    progress('score: all 298 new forecasts sealed; starting fixed comparisons')
    runtime, execution, scheduler, guard = imports()
    import seal_score as native
    frozen_scoring = runtime.conf_module('scoring')
    post = import_file('_posthoc_frozen_a8_bootstrap', STUDY / 'studies/inference/code/read_comparisons.py')
    scoring = post.ChunkedScoring(frozen_scoring, draws=100000, chunk=512, gate=check_resources)
    forecasts = Forecasts(sealed, native)
    (OUT / 'results').mkdir(exist_ok=True)
    rows, reversals, placebos = [], [], []

    def comparison(analysis, task, seed, representation, step, arm, reference,
                   arm_group='original', reference_group='original', placebo=False):
        days, a = forecasts.losses(task, arm, seed, arm_group, placebo)
        b_days, b = forecasts.losses(task, reference, seed, reference_group, placebo)
        if days != b_days:
            raise RuntimeError('Paired day keys mismatch')
        dm = frozen_scoring.dm_daily(a-b)
        interval = scoring.paired_percent_interval(a, b, scoring.block_picks(len(days), 7, days))
        if dm['state'] != 'DEFINED' or interval['undefined_draws']:
            raise RuntimeError('Fixed inference undefined; no substitute permitted')
        lo, hi = interval['interval95_percent']
        return {'analysis': analysis, 'task': task, 'seed': seed, 'representation': representation,
            'representation_name': NAMES.get(representation, representation), 'step': step,
            'arm': arm, 'reference': reference, 'arm_group': arm_group, 'reference_group': reference_group,
            'n_days': len(days), 'mae': float(a.mean()), 'reference_mae': float(b.mean()),
            'delta_mae': dm['mean_difference'], 'delta_percent': interval['effect_percent_reference_mae'],
            'p_nominal': dm['p_two_sided'], 'interval95_low_percent': lo, 'interval95_high_percent': hi,
            'bootstrap_draws': 100000, 'bootstrap_seed': 20260925, 'bootstrap_block_days': 7}

    for analysis, tasks, group in [('a1', ('notice', 'news'), 'original'),
                                    ('a2_w7', ('notice',), 'w7'), ('a2_w24', ('notice',), 'w24')]:
        for task in tasks:
            for seed in (*SEEDS, 'mean'):
                for representation in REPS[task]:
                    activity = comparison(analysis, task, seed, representation, 'activity', REF[task], 'N', group)
                    representation_step = comparison(analysis, task, seed, representation, 'representation',
                        representation, REF[task], group, group)
                    net = comparison(analysis, task, seed, representation, 'net', representation, 'N', group)
                    rows.extend([activity, representation_step, net])
                    reversals.append({'analysis': analysis, 'task': task, 'seed': seed,
                        'representation': representation, 'representation_name': NAMES[representation],
                        'net_delta_percent': net['delta_percent'],
                        'representation_delta_percent': representation_step['delta_percent'],
                        'reversal': bool(np.sign(net['delta_percent']) != np.sign(representation_step['delta_percent']))})
                progress('score: complete ' + analysis + ' ' + task + ' seed=' + str(seed))
    placebos.append(comparison('a2_w7_placebo', 'notice', 20260919, 'L_chen_notice',
        'unshifted_vs_shifted_archive', 'L_chen_notice', 'P_shift', 'w7', 'w7_shift', True))
    placebos.append(comparison('a2_w7_placebo', 'notice', 20260919, 'L_chen_notice',
        'shifted_archive_vs_shifted_activity', 'P_shift', 'M_shift_notice', 'w7_shift', 'w7_shift', True))
    df, rev, pl = pd.DataFrame(rows), pd.DataFrame(reversals), pd.DataFrame(placebos)
    mean_w7 = df.loc[(df.analysis == 'a2_w7') & (df.seed == 'mean') & (df.step == 'representation')].copy()
    mean_w7['p_holm_notice_family'] = frozen_scoring.holm(mean_w7.p_nominal.tolist())
    mean_w7['robust_gain'] = (mean_w7.delta_percent < 0) & (mean_w7.p_holm_notice_family < .05)
    robust = []
    for task, representations in REPS.items():
        for representation in representations:
            orig = rev.loc[(rev.analysis == 'a1') & (rev.task == task) & (rev.seed == 'mean') &
                           (rev.representation == representation)].iloc[0]
            window = (rev.loc[(rev.analysis == 'a2_w7') & (rev.seed == 'mean') &
                             (rev.representation == representation)].iloc[0] if task == 'notice' else orig)
            robust.append({'task': task, 'representation': representation,
                'representation_name': NAMES[representation], 'original_mean_reversal': bool(orig.reversal),
                'w7_mean_reversal': bool(window.reversal),
                'robust_reversal': bool(orig.reversal and window.reversal),
                'news_reference_unchanged_by_analysis2': task == 'news'})
    robust_df = pd.DataFrame(robust)
    for name, table in [('analysis1_comparisons', df.loc[df.analysis == 'a1']),
                        ('analysis2_comparisons', df.loc[df.analysis != 'a1']),
                        ('reversals', rev), ('placebo_comparisons', pl),
                        ('robust_reversals', robust_df), ('robust_notice_gains', mean_w7)]:
        table.to_csv(OUT / 'results' / (name + '.csv'), index=False)
    daily = []
    for (task, arm, seed, group, placebo), (days, losses) in forecasts.cache.items():
        daily.extend({'task': task, 'arm': arm, 'seed': seed, 'group': group, 'placebo': placebo,
            'target_day': day, 'daily_mae': float(loss)} for day, loss in zip(days, losses))
    pd.DataFrame(daily).to_csv(OUT / 'results/daily_losses.csv', index=False)
    fit_rows = []
    for item in sealed['fits']:
        r = read(item['path'])
        fit_rows.append({'group': r['posthoc_group'], 'task_id': r['task_id'],
            'runtime_seconds': r['runtime_seconds'], 'wrapper_runtime_seconds': r['wrapper_runtime_seconds'],
            'peak_rss_bytes': r['peak_rss_bytes'], 'peak_anonymous_bytes': r['peak_anonymous_bytes'],
            'min_available_ram_fraction': r['min_available_ram_fraction'],
            'min_free_disk_bytes': r['min_free_disk_bytes']})
    pd.DataFrame(fit_rows).to_csv(OUT / 'results/fit_resources.csv', index=False)
    for name, path in [('dm_daily_and_holm', confirmation / 'code/scoring.py'),
                       ('daily_aggregation', confirmation / 'execution/seal_score.py'),
                       ('bootstrap', STUDY / 'studies/inference/code/read_comparisons.py')]:
        forecasts.used[str(path)] = sha(path)
    write(OUT / 'SCORING_INPUTS.json', forecasts.used)
    decisions = {'state': 'COMPLETE', 'robust_reversals_count': int(robust_df.robust_reversal.sum()),
        'robust_notice_gains_all_three': bool(mean_w7.robust_gain.all()),
        'robust_notice_gains_count': int(mean_w7.robust_gain.sum()),
        'notice_reversals_disappear_under_w7': not bool(rev.loc[(rev.analysis == 'a2_w7') &
            (rev.seed == 'mean')].reversal.any()),
        'rule1_all_seeds_means_windows_reported': True,
        'rule5_no_additional_variants': True,
        'runtime_seconds': time.monotonic()-start}
    import resource
    decisions['peak_rss_bytes'] = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024))
    write(OUT / 'DECISIONS.json', decisions)
    progress('score: COMPLETE; fixed decision rules recorded')
    return decisions


if __name__ == '__main__':
    score()
