'Prepare matched notice feature matrices and fitting inputs.'
from __future__ import annotations

import gc
import json
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner as r
import numpy as np
import pandas as pd

OUT = r.OUT
FINAL3 = r.FINAL3


def guard():
    assert r.read(OUT / 'PREPARATION_FREEZE.json')['protocol_sha256'] == r.sha(OUT / 'PROTOCOL_RF2.md')
    frozen = r.read(FINAL3 / 'FREEZE.json')
    for path, expected in frozen['files'].items():
        source = Path(path)
        if not source.is_absolute():
            source = FINAL3 / source
        assert r.sha(source) == expected, ('source_relations freeze mismatch', path)
    return frozen


def blocks():
    frozen = guard()
    m = r.module(FINAL3 / 'assembler/assemble_source_relations.py', 'rf_frozen_final3_assembler')
    assert len(m.COLUMNS) == 14
    checks = {}
    records = {}
    for arm in r.ARMS:
        path = FINAL3 / f'records/{arm}.parquet'
        assert r.sha(path) == frozen['files'][f'records/{arm}.parquet']
        rec = pd.read_parquet(path)
        records[arm] = rec
        for period in ('development', 'C'):
            keys = pd.read_parquet(r.B1B / f'{period}_metadata.parquet', columns=r.KEYS)
            feature = m.features(keys, rec)
            assert list(feature.columns) == list(m.COLUMNS)
            matrix = feature.to_numpy(dtype=np.float32, copy=True)
            assert matrix.shape == (len(keys), 14)
            target = r.matrix_path('final', period, arm)
            target.parent.mkdir(parents=True, exist_ok=True)
            assert not target.exists(), target
            np.save(target, matrix)
            checks[f'{period}_{arm}'] = dict(
                rows=len(matrix), columns=list(feature.columns), dtype=str(matrix.dtype),
                source_record_sha256=r.sha(path), matrix_sha256=r.sha(target),
                key_file_sha256=r.sha(r.B1B / f'{period}_metadata.parquet'))
            del keys, feature, matrix
            gc.collect()
            r.log('blocks_complete', arm=arm, period=period)
        del rec
        gc.collect()
    pd.testing.assert_frame_equal(records['P'], m.shifted(records['L'], 28))
    r.write('BLOCKS.json', dict(
        passed=True, representation='source_relations', final3_freeze_sha256=r.sha(FINAL3 / 'FREEZE.json'),
        records={arm: len(records[arm]) for arm in r.ARMS}, checks=checks,
        seconds=time.monotonic() - r.START, peak_rss_bytes=r.rss()))


def inputs():
    guard()
    files = {FINAL3 / 'FREEZE.json', FINAL3 / 'assembler/assemble_source_relations.py',
             FINAL3.parent / 'closing_windows/assembler/normalize_closing_windows.py',
             FINAL3.parent / 'event_assembly/assemble_event_features.py'}
    files.update(FINAL3 / f'records/{arm}.parquet' for arm in r.ARMS)
    files.update(FINAL3 / f'features/{arm}_{period}.parquet' for arm in r.ARMS
                 for period in ('development', 'C'))
    files.update({r.RF / 'FREEZE.json', r.RF / 'INPUT_MANIFEST.json',
                  r.RF / 'OUTPUT_MANIFEST.json', r.RF / 'final/design.json',
                  r.RF / 'final/candidate_seal.json',
                  r.RF / 'N_REUSE.json',
                  r.RF / 'scoring/final/SCORE.json',
                  r.RF / 'scoring/final/SCORE_VALIDATION.json'})
    files.update(r.RF / f'blocks/final/notices_{period}_R.npy'
                 for period in ('development', 'C'))
    for fold in r.FOLDS:
        files.add(r.RF / f'final/predictions/{fold}.parquet')
        for seed in r.SEEDS:
            files.update({r.RF / f'final/models/{fold}_R_s{seed}.txt',
                          r.RF / f'final/predictions/{fold}_R_s{seed}.parquet',
                          r.RF / f'receipts/final_{fold}_R_{seed}.json'})
    for scope in ('development', 'C'):
        for length in (1, 3, 7, 14):
            files.update({r.RF / f'scoring/final/{scope}_{length}d_picks.npy',
                          r.RF / f'scoring/final/{scope}_{length}d_draws.npz'})
    files.update({r.forecast_replication / 'corrected_numeric.npy', r.forecast_replication / 'numeric_C.npy',
                  r.B1B / 'development_metadata.parquet', r.B1B / 'C_metadata.parquet',
                  r.B1B / 'OUTPUT_MANIFEST.json',
                  r.label_availability / 'BOUNDARY.json', r.V3 / 'INPUT_MANIFEST.json', r.V3 / 'FREEZE.json',
                  r.PROJ / 'paper_plan/task_specs/COMMON_RULES.md'})
    for fold in r.FOLDS:
        ref = r.reference(fold)
        files.update({ref / 'design.json', ref / 'candidate_seal.json', r.reference_prediction(fold)})
        for seed in r.SEEDS:
            files.add(ref / f'models/{fold}_N_s{seed}.txt')
        if fold != 'C':
            for part in ('train', 'test'):
                files.add(r.label_availability / f'input_checks/{part}_indices_{fold}.npy')

    score = OUT / 'scoring/score.py'
    if score.exists():
        scorer = r.module(score, 'rf_score_dependency_capture')
        files.update(scorer.er.BANK / f'{month}.parquet' for month in r.rn.MONTHS)
        files.update({r.AUTO / 'windows/C/truth.parquet',
                      r.AUTO / 'windows/C/build_receipt.json',
                      r.forecast_replication / 'SCORE_INPUT_MANIFEST.json',
                      r.forecast_replication / 'scoring/aligned/SCORE.json',
                      r.label_availability / 'resolved/main/scores/SCORE.json',
                      OUT.parent / 'forecast_sensitivity/sensitivity/RESULT.json',
                      r.V3 / 'IDENTITY.json',
                      r.V3 / 'scoring/identity/SCORE.json',
                      r.V3 / 'scoring/identity/SCORE_VALIDATION.json',
                      r.V3 / 'scoring/resolved/SCORE.json',
                      r.V3 / 'scoring/resolved/SCORE_VALIDATION.json'})
        for base in (r.label_availability / 'resolved/main/scores', OUT.parent / 'forecast_sensitivity/sensitivity',
                     r.V3 / 'scoring/identity', r.V3 / 'scoring/resolved'):
            files.update(base.glob('*_picks.npy'))
            files.update(base.glob('*_draws.npz'))
    for mod in list(sys.modules.values()):
        path = getattr(mod, '__file__', None)
        if path and path.endswith('.py') and str(r.PROJ.parents[1]) in path and not path.startswith(str(OUT)):
            files.add(Path(path).resolve())
    final = r.module(FINAL3 / 'assembler/assemble_source_relations.py', 'rf_final3_code_capture')
    files.update({final.FROZEN_PATH, Path(final.frozen.v2.__file__), Path(final.frozen.sealed_nw.__file__)})
    rows = {}
    for path in sorted(files):
        path = Path(path).resolve()
        rows[str(path)] = dict(sha256=r.sha(path), bytes=path.stat().st_size)


    v3 = r.read(r.V3 / 'INPUT_MANIFEST.json')['files']
    comparisons = {}
    for path in [r.forecast_replication / 'corrected_numeric.npy', r.forecast_replication / 'numeric_C.npy',
                 r.B1B / 'development_metadata.parquet', r.B1B / 'C_metadata.parquet',
                 *[r.label_availability / f'input_checks/{part}_indices_{fold}.npy'
                   for fold in r.FOLDS if fold != 'C' for part in ('train', 'test')]]:
        path = str(path)
        comparisons[path] = rows[path]['sha256'] == v3[path]['sha256']
    assert all(comparisons.values()), 'numeric, metadata or label_availability input_checks source changed from V3'
    r.write('INPUT_MANIFEST.json', dict(files=rows,
        created_utc=pd.Timestamp.now(tz='UTC').isoformat(),
        v3_numeric_metadata_masks_identical=all(comparisons.values()),
        v3_source_comparisons=comparisons))


def finalize():
    guard()
    assert r.read(OUT / 'BLOCKS.json')['passed']
    assert (OUT / 'final/design.json').exists()
    manifest = r.read(OUT / 'INPUT_MANIFEST.json')['files']
    for path, item in manifest.items():
        assert r.sha(path) == item['sha256'], path
    files = {}
    for root in (OUT / 'blocks/final', OUT / 'final/indices'):
        for path in sorted(root.rglob('*')):
            if path.is_file():
                files[str(path.relative_to(OUT))] = dict(sha256=r.sha(path), bytes=path.stat().st_size)
    for path in (OUT / 'BLOCKS.json', OUT / 'final/design.json'):
        files[str(path.relative_to(OUT))] = dict(sha256=r.sha(path), bytes=path.stat().st_size)
    assert len([p for p in files if p.startswith('blocks/final/')]) == 6
    assert len([p for p in files if p.startswith('final/indices/')]) == 14
    r.write('PREPARATION.json', dict(passed=True, files=files,
        final3_freeze_sha256=r.sha(FINAL3 / 'FREEZE.json'),
        protocol_sha256=r.sha(OUT / 'PROTOCOL_RF2.md'),
        input_manifest_sha256=r.sha(OUT / 'INPUT_MANIFEST.json'),
        created_utc=pd.Timestamp.now(tz='UTC').isoformat()))


if __name__ == '__main__':
    stage = sys.argv[1]
    assert stage in {'blocks', 'inputs', 'finalize'}
    try:
        globals()[stage]()
    except Exception as exc:
        r.write(f'failures/{time.time_ns()}_prepare_{stage}.json',
                dict(error=repr(exc), argv=sys.argv))
        raise
