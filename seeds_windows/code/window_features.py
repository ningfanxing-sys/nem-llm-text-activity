'Construct seven-day and 24-hour notice activity counts.'
from __future__ import annotations
import time
import numpy as np
import pandas as pd
from run_posthoc import (OUT, STATE, imports, require_gate, read, write, sha,
                         progress, check_resources)


def ns(values):
    return pd.to_datetime(values, utc=True).astype('datetime64[ns, UTC]').astype('int64').to_numpy()


def build():
    require_gate()
    if read(OUT / 'STAGE_a1_notice.json')['state'] != 'COMPLETE':
        raise RuntimeError('Analysis 1 notices must complete before Analysis 2')
    started = time.monotonic()
    check_resources()
    runtime, execution, scheduler, guard = imports()
    from notice_label_adapter import load_host_notices
    f = runtime.conf_module('features')
    official = read(STATE / 'fits/receipts/notice__prewindow_frozen_C_bank__N__s20260919__main.json')
    permit = guard.ExecutionPermit('POSTHOC_20261019_USER_AUTHORIZED',
        official['design_freeze_sha256'], official['completed_input_manifest_sha256'], True)
    freeze = read(STATE / 'COMPLETE_INPUT_FREEZE.json')
    catalog = read(freeze['source_catalog_path'])
    prefix_item = catalog['notice_prefix']
    if sha(prefix_item['path']) != prefix_item['identity']['sha256']:
        raise RuntimeError('Canonical notice prefix hash changed')
    prefix = pd.read_parquet(prefix_item['path'], columns=['notice_id', 'available_utc'])
    label_path = freeze['nrx_labels_path']
    notices = load_host_notices(__import__('pathlib').Path(label_path).parent,
        permit=permit, prefix_clock_rows=prefix.to_dict('records'))
    if {str(n['notice_id']) for n in notices} != set(prefix.notice_id.astype(str)):
        raise RuntimeError('Canonical notice census differs from official source loader')
    if len(notices) != len(prefix) or len({str(n['notice_id']) for n in notices}) != len(notices):
        raise RuntimeError('Duplicate/missing notice IDs')
    clocks = ns([n['available_utc'] for n in notices])
    failed = np.r_[0, np.cumsum([n['extraction_status'] != 'SUCCESS' for n in notices])]
    shifted = ns([f.shift_normalized_clocks({'available_utc': n['available_utc']},
                                           permit=permit)['available_utc'] for n in notices])
    if not np.array_equal(shifted, clocks + pd.Timedelta(days=28).value):
        raise RuntimeError('Frozen placebo clock shift differs from 28 days')
    manifest = read(STATE / 'features/manifest.json')
    bundle = execution.find_bundle(manifest,
        scheduler.FitTask('notice', 'prewindow_frozen_C_bank', 'M_notice', 20260919))
    execution.verify_bundle(bundle)
    if sha(bundle['panel_path']) != bundle['panel_sha256']:
        raise RuntimeError('Frozen notice panel changed')
    origin = ns(pd.read_parquet(bundle['panel_path'], columns=['origin']).origin)
    issues, inverse = np.unique(origin, return_inverse=True)
    checks = {'state': 'RUNNING', 'record_count': len(notices),
        'failed_record_count': int(failed[-1]), 'rows': len(origin),
        'training_rows': bundle['train_rows'], 'evaluation_rows': len(origin)-bundle['train_rows'],
        'unique_issue_times': len(issues), 'availability_clock': 'official load_host_notices available_utc',
        'window_bounds': '(issue - duration, issue]', 'counts_nem_wide': True,
        'source_prefix_sha256': sha(prefix_item['path']), 'source_labels_sha256': sha(label_path),
        'placebo_shift': 'frozen features.shift_normalized_clocks, +28 days on source availability',
        'checks': {}, 'outputs': []}
    (OUT / 'features').mkdir(exist_ok=True)
    no_future = True
    for group, times, old_arm in [('main', clocks, 'M_notice'), ('shift28', shifted, 'M_shift_notice')]:
        progress('features: ' + group + ' exact availability counts')
        end = np.searchsorted(times, issues, side='right')
        left6 = np.searchsorted(times, issues-pd.Timedelta(hours=6).value, side='right')
        left7 = np.searchsorted(times, issues-pd.Timedelta(days=7).value, side='right')
        left24 = np.searchsorted(times, issues-pd.Timedelta(hours=24).value, side='right')
        p, a6, pf = end, end-left6, failed[end]
        w7, w24 = end-left7, end-left24
        f7, f24 = failed[end]-failed[left7], failed[end]-failed[left24]
        original = execution.find_bundle(manifest,
            scheduler.FitTask('notice', 'prewindow_frozen_C_bank', old_arm, 20260919))
        execution.verify_bundle(original)
        old = np.load(original['extras_matrix']['path'], mmap_mode='r', allow_pickle=False)
        tests = {
            'A6_exact_official': bool(np.array_equal(a6[inverse], old[:, 1])),
            'P_exact_official': bool(np.array_equal(p[inverse], old[:, 0])),
            'PF_exact_official': bool(np.array_equal(pf[inverse], old[:, 2])),
            'W24_le_W7_le_P': bool(np.all((w24 <= w7) & (w7 <= p))),
            'F24_le_F7_le_PF': bool(np.all((f24 <= f7) & (f7 <= pf))),
            'no_future_document': bool(np.all(times[np.maximum(end-1, 0)][end > 0] <= issues[end > 0])),
            'same_record_set_as_official': True,
        }
        no_future &= tests['no_future_document']
        for part, selector in [('training', slice(0, bundle['train_rows'])),
                               ('evaluation', slice(bundle['train_rows'], None))]:
            tests[part+'_A6_exact_official'] = bool(np.array_equal(a6[inverse[selector]], old[selector, 1]))
            tests[part+'_W24_le_W7_le_P'] = bool(np.all((w24[inverse[selector]] <= w7[inverse[selector]]) &
                (w7[inverse[selector]] <= old[selector, 0])))
            tests[part+'_F24_le_F7_le_PF'] = bool(np.all((f24[inverse[selector]] <= f7[inverse[selector]]) &
                (f7[inverse[selector]] <= old[selector, 2])))
        checks['checks'][group] = tests

        variants = [('w7' if group == 'main' else 'w7_shift', w7, f7)]
        if group == 'main':
            variants.append(('w24', w24, f24))
        for name, window, failures in variants:
            path = OUT / 'features' / (name + '.activity.npy')
            small = np.column_stack((window[inverse], a6[inverse], failures[inverse])).astype('float32')
            check_resources()
            np.save(path, small, allow_pickle=False)
            checks['outputs'].append({'path': str(path), 'sha256': sha(path),
                'shape': list(small.shape), 'columns': ['W7' if name != 'w24' else 'W24',
                    'official_A6', 'F7' if name != 'w24' else 'F24']})
            del small
    checks['all_checks_pass'] = all(all(v.values()) for v in checks['checks'].values()) and no_future
    checks['runtime_seconds'] = time.monotonic()-started
    import resource, sys
    checks['peak_rss_bytes'] = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024))
    checks['state'] = 'PASS' if checks['all_checks_pass'] else 'FAILED_STOP'
    write(OUT / 'FEATURE_CHECKS.json', checks)
    if not checks['all_checks_pass']:
        raise RuntimeError('Windowed feature checks failed; stop without fitting')
    progress('features: all required checks PASS')
    return checks
