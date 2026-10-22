
'Test scoring path associations with synthetic inputs.'
from __future__ import annotations
import ast
import contextlib
import copy
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import types
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fixture_api as C
BASE_PROJECT = None

class FixturePath(type(Path())):


    def __new__(cls, *args):
        p = Path(*args)
        if BASE_PROJECT is not None and p.is_relative_to(C.LIVE):
            p = BASE_PROJECT / p.relative_to(C.LIVE)
        return super().__new__(cls, p)

    def __init__(self, *args):
        p = Path(*args)
        if BASE_PROJECT is not None and p.is_relative_to(C.LIVE):
            p = BASE_PROJECT / p.relative_to(C.LIVE)
        super().__init__(p)

    def __truediv__(self, key):
        return FixturePath(Path(str(self)) / key)

    def joinpath(self, *args):
        return FixturePath(Path(str(self)).joinpath(*args))

def dump(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')

def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

def baseline_patch(module):
    module.Path = FixturePath
    for key, value in list(vars(module).items()):
        if isinstance(value, Path):
            setattr(module, key, FixturePath(value))
    for value in vars(module).values():
        if isinstance(value, types.FunctionType) and value.__module__ == module.__name__:
            if value.__defaults__:
                value.__defaults__ = tuple((FixturePath(v) if isinstance(v, Path) else v for v in value.__defaults__))
            if value.__kwdefaults__:
                value.__kwdefaults__ = {k: FixturePath(v) if isinstance(v, Path) else v for k, v in value.__kwdefaults__.items()}

@contextlib.contextmanager
def baseline(association):
    global BASE_PROJECT
    association.sources()
    BASE_PROJECT = association.project
    reference_snapshot, old_path = (dict(sys.modules), sys.path[:])
    old_get = importlib.machinery.SourceFileLoader.get_code
    old_exec = importlib.machinery.SourceFileLoader.exec_module

    def get_code(loader, fullname):
        p = Path(loader.path).resolve()
        if p.is_relative_to(C.LIVE) and p.parent != HERE:
            association.verify_code(p)
            return compile(p.read_bytes(), str(p), 'exec', dont_inherit=True)
        return old_get(loader, fullname)

    def exec_module(loader, module):
        result = old_exec(loader, module)
        p = Path(loader.path).resolve()
        if p.is_relative_to(C.LIVE) and p.parent != HERE:
            baseline_patch(module)
        return result
    importlib.machinery.SourceFileLoader.get_code = get_code
    importlib.machinery.SourceFileLoader.exec_module = exec_module
    for name, module in list(sys.modules.items()):
        p = getattr(module, '__file__', None)
        if p and Path(p).resolve().is_relative_to(C.LIVE) and (Path(p).resolve().parent != HERE):
            del sys.modules[name]
    sys.path[:0] = [str(C.LIVE / C.B_REL / 'code'), str(C.LIVE / 'studies/inference/code'), str(C.LIVE / 'studies/source_bindings'), str(C.LIVE / 'fixtures/REMOVED_WRITING_ROOT')]

    def load(entry):
        p = C.LIVE / C.ENTRIES.get(entry, entry)
        spec = importlib.util.spec_from_file_location(p.stem, p)
        m = importlib.util.module_from_spec(spec)
        sys.modules[p.stem] = m
        spec.loader.exec_module(m)
        baseline_patch(m)
        if entry=='scorer_freeze':
            import scorer_metadata
            original=m.verify
            def verify(path=None):
                target=Path(path or association.out/'SCORER_CODE_FREEZE.json')
                actual=C.read(target)
                from types import FunctionType
                parent_read=original.__globals__['read_json']
                def read(p):return dict(actual,table_results_freeze=actual['numerical_inputs']) if Path(p)==target else parent_read(p)
                clone=FunctionType(original.__code__,dict(original.__globals__,read_json=read),original.__name__,(target,),original.__closure__)
                clone(target)
                return actual
            m.verify=verify
        return m
    try:
        yield load
    finally:
        importlib.machinery.SourceFileLoader.get_code = old_get
        importlib.machinery.SourceFileLoader.exec_module = old_exec
        sys.path[:] = old_path
        for name, module in list(sys.modules.items()):
            p = getattr(module, '__file__', None)
            if p and Path(p).resolve().is_relative_to(C.LIVE) and (Path(p).resolve().parent != HERE):
                del sys.modules[name]
        for name, module in reference_snapshot.items():
            if name not in sys.modules:
                sys.modules[name] = module
        BASE_PROJECT = None

class InheritedSuite:

    def refuse(self, fn, needle=None):
        try:
            fn()
        except (C.Refusal, RuntimeError, FileNotFoundError, IsADirectoryError, PermissionError, KeyError, ValueError) as e:
            if needle:
                assert needle in str(e), (needle, str(e))
            return dict(exception=type(e).__name__, reason=str(e).replace(str(self.scratch), '<synthetic_scratch>'))
        raise AssertionError('Expected refusal, operation accepted')

    def fixture(self):
        for rel in [*self.a.lock['sources'], *self.a.lock['authorities'], *self.a._ancestor_sources]:
            dst = self.project / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(C.LIVE / rel, dst)
        code_parent = C.read(C.LIVE / C.B_REL / 'CODE_FREEZE.json')
        code_tests = code_parent['test_receipts_provenance']['tests']
        assert Path(code_tests['path']) == C.LIVE / C.B_REL / 'TEST_RESULTS.json'
        original_code_tests = C.checked(code_tests)
        shutil.copyfile(original_code_tests, self.b / 'TEST_RESULTS.json')
        assert C.identity(self.b / 'TEST_RESULTS.json') == dict(code_tests, path=str(self.b / 'TEST_RESULTS.json'))
        for p in (C.LIVE / C.B_REL / 'tests').glob('*.py'):
            dst = self.b / 'tests' / p.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dst)
        for name in ('freeze_a8batch.py', 'freeze_a8_specification2.py', 'host_run_a8batch.sh', 'freeze_a8scorer.py', 'host_postscore_a8batch.sh'):
            shutil.copyfile(C.LIVE / C.B_REL / name, self.b / name)
        shutil.copytree(self.b / 'code', self.a.q / 'batch_estimation/code', dirs_exist_ok=True)
        for rel in ('studies/confirmation/inference_design/AUTHOR_CONFIRMATION_A8_SCHEMA.json', 'studies/confirmation/inference_design/A8_FREEZE.json', 'studies/confirmation/robustness_tests/RULES_FOR_MAIN_COMPARISONS.json', 'studies/confirmation/sensitivity_tests/RULES_FOR_FILL3A.json', 'studies/confirmation/A6/RULES_FOR_SENSITIVITY_COMPARISONS.json'):
            p = self.project / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(C.LIVE / rel, p)
        repin_metadata = []
        for rel, entry in [('label_scoring', 'a2label_predict.py'), ('confirmation/robustness_tests/matched_controls', 'pcx_runner.py')]:
            root = self.a.q / rel / 'REPIN_SPEC_8'
            dump(root / 'SOURCE_BINDING.json', dict(old=str(self.scratch / 'old' / rel), batch='matched_controls'))
            dump(root / 'REPIN_FREEZE.json', {'synthetic_only': True})
            dump(root / 'PCX_FREEZE.json', {'synthetic_only': True})
            repin_metadata.extend((root / name for name in ('SOURCE_BINDING.json', 'REPIN_FREEZE.json', 'PCX_FREEZE.json')))
        for name in ('REPORT.md', 'FILES.sha256', 'FINAL_CHECK.json', 'T5_REQUIRED_STAGED.txt', 'SOURCE_ORDER_source.md', 'READER_ARGV.json', 'IDENTITY_COVERAGE.json', 'SOURCE_RULING_20261004.md', 'R11_PROOF.json', 'REAL_LEGACY_REPLAY_SET2.json', 'IDENTITY_ASSOCIATION_PLAN_SET4.json', 'RUNBOOK_RESOLUTIONS_SET4_source.md', 'TEST_SUMMARY_SET4.json'):
            p = self.a.q / 'source_bindings' / name
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.suffix == '.json':
                dump(p, {'synthetic_only': True})
            else:
                p.write_text('SYNTHETIC metadata\n')
            repin_metadata.append(p)
        self.repin_fixture_identity = C.identity(self.a.q / 'source_bindings/FINAL_CHECK.json')
        self.repin_metadata_identities = [C.identity(p) for p in repin_metadata]
        conf = self.scratch / 'project/fixtures/official/SEAL.json'
        conf_feature = conf.parent / 'features/manifest.json'
        dump(conf_feature, {'synthetic_only': True, 'bundles': []})
        dump(conf, {'synthetic': True, 'truth_panels': {}, 'auxiliary': self.repin_metadata_identities, 'feature_manifest_path': str(conf_feature), 'feature_manifest_sha256': C.sha(conf_feature)})
        score_report = conf.parent / 'scored/SCORE_REPORT.json'
        dump(score_report, {'synthetic_only': True, 'state': 'FROZEN_SCORE_COMPLETE'})
        score_receipt = conf.parent / 'scored/SCORE_RECEIPT.json'
        dump(score_receipt, {'state': 'FROZEN_SCORE_COMPLETE', 'seal_sha256': C.sha(conf), 'files': [C.identity(score_report)]})
        self.official_items = dict(seal=C.identity(conf), score_receipt=C.identity(score_receipt), score_report=C.identity(score_report))
        self.official_snapshots = {p: p.read_bytes() for p in (conf, conf_feature, score_receipt, score_report)}
        manifest = self.d / 'state/features/manifest.json'
        dump(manifest, {'synthetic': True, 'bundles': []})
        probe = {'synthetic_only': True, 'reports': [], 'values': [1, 2, 3]}
        dump(self.d / 'state/PARITY_DATA.json', probe)
        dump(self.d / 'cps8/CPS8_SELECTION.json', {'state': 'SYNTHETIC', 'selected': {'news/M': 'g0', 'news/L_count': 'g1', 'news/L_chen': 'g2', 'notice/M_notice': 'g0', 'notice/L14': 'g1', 'notice/L_Laz': 'g2', 'notice/L_chen_notice': None}})
        stages = []
        for name in ('R8_news', 'R8_notice', 'CPS8'):
            p = self.d / 'state/stages' / (name + '.json')
            row = dict(stage=name, state='NOT_RUN_BUDGET', reason='SYNTHETIC_NOT_RUN', eligible_tasks=[])
            dump(p, row)
            stages.append(dict(row, receipt_identity=C.identity(p)))
        code = self.b / 'CODE_FREEZE.json'
        seal = dict(state='ALL_A8BATCH_SPECIFIED_PREDICTIONS_SEALED', sealed_before_outcome_scoring=True, conf_seal=C.identity(conf), conf_seal_sha256=C.sha(conf), code_freeze=C.identity(code), adapter_freeze_sha256='a' * 64, feature_manifest_path=str(manifest), feature_manifest_sha256=C.sha(manifest), fit_receipts_and_models=[], predictions=[], auxiliary=[C.identity(self.d / 'cps8/CPS8_SELECTION.json'), C.identity(self.d / 'state/PARITY_DATA.json')], stage_dispositions=stages, truth_panels={}, drop_order=['R8_news_seeds', 'R8_news', 'CPS8', 'PCX_extension'], outcome_scoring_performed=False, partial_predictions_scored=False)
        dump(self.d / 'state/SEAL_BATCH.json', seal)
        self.seal = seal
        for mode, name in ((1, 'PRIMARY'), (2, 'R8')):
            root = self.d / 'dly8' / ('mode' + str(mode))
            attempt = root / 'attempts/synthetic_success'
            arms = ['M_notice', 'L14']
            source = seal['conf_seal'] if mode == 1 else C.identity(self.d / 'state/SEAL_BATCH.json')
            binding = {'main_conf_seal': seal['conf_seal'], 'source_seal': source, 'synthetic_only': True}
            pp = attempt / 'PARITY_DELTA0.json'
            dump(pp, dict(state='PASS', binding=binding, checks=[dict(arm=a, features_byte_equal=True, predictions_byte_equal=True) for a in arms]))
            predictions = []
            for delta in (5, 15, 60):
                for arm in arms:
                    p = attempt / ('notice__' + arm + '__delay' + str(delta) + '.parquet')
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(b'SYNTHETIC_UNSCORED_PLACEHOLDER\n')
                    predictions.append(dict(C.identity(p), delta_minutes=delta, arm=arm, rows=2))
            releases = []
            for delta in (0, 5, 15, 60):
                p = attempt / ('delta' + str(delta)) / 'MATRIX_RELEASE.json'
                matrices = [dict(path=str(p.parent / (arm + '.npy')), sha256='b' * 64, bytes=144, shape=[2, 3], dtype='float32', arm=arm) for arm in arms]
                dump(p, dict(state='COMPLETED_DELTA_RELEASE', binding=binding, matrices=matrices))
                releases.append(C.identity(p))
            row = dict(state='ALL_DLY8_PREDICTIONS_SEALED', models_refitted=0, delays_minutes=[5, 15, 60], arms=arms, binding=binding, parity=C.identity(pp), predictions=predictions)
            receipt = root / 'DELAY_RECEIPT.json'
            dump(receipt, row)
            dump(root / 'MATRIX_EVIDENCE_SEAL.json', dict(state='REGENERABLE_MATRICES_SEALED', binding=binding, family_receipt=C.identity(receipt), releases=releases))
            dump(self.d / 'dly8' / ('DLY8_SEAL_' + name + '.json'), dict(state='DLY8_SEALED_BEFORE_SCORING', receipt=C.identity(receipt), models_refitted=0, conf_seal_sha256=seal['conf_seal_sha256'], adapter_freeze_sha256=seal['adapter_freeze_sha256'], source_seal=source))
        for root in ('state', 'dly8', 'cps8'):
            shutil.copytree(self.d / root, self.b / root)
        self.clone_bytes = {str(p.relative_to(self.d)): C.sha(p) for root in ('state', 'dly8', 'cps8') for p in (self.d / root).rglob('*') if p.is_file()}
        assert all((C.sha(self.b / rel) == sha for rel, sha in self.clone_bytes.items()))
        self.snapshots = {p: p.read_bytes() for root in ('state', 'dly8', 'cps8') for p in (self.d / root).rglob('*') if p.is_file()}
        self._science_fixture()
        return dict(exact_cloned_files=len(self.clone_bytes), mock_prediction_payloads=True)

    def restore(self):
        for root in ('state', 'dly8', 'cps8'):
            shutil.rmtree(self.d / root, ignore_errors=True)
        for p, data in self.snapshots.items():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        self.a.sealed.clear()

    def remove_b_outputs(self):
        for root in ('state', 'dly8', 'cps8'):
            shutil.rmtree(self.b / root, ignore_errors=True)

    def operations(self, load, associated):
        import numpy as np
        import pandas as pd
        results = {}
        common = load('batch_inputs')
        state = common.OUT / 'state'
        results['batch_inputs'] = encoded(common.read_json(state / 'PARITY_DATA.json'))
        score = load('score_batch')
        native = types.SimpleNamespace(_json_result=lambda x: x)
        raw = {'reports': [{'arm': 'L14', 'bootstrap': {'1': {'draws': np.array([1.0, 2.0]), 'count': 2}}}], 'paired_day_picks': {'1': np.array([[0, 1]], dtype='int64')}, 'state': 'SYNTHETIC'}
        prepared, arrays = score.clean_record(native, raw)
        score.score_parity(native, raw, prepared, arrays)
        results['score_batch'] = encoded(prepared) + b''.join((arrays[k].tobytes() for k in sorted(arrays)))
        sys.path[:0] = [str(C.LIVE / 'studies/confirmation/code'), str(C.LIVE / 'studies/confirmation/execution')]
        sc = load('studies/confirmation/code/scoring.py')
        a2 = load('studies/confirmation/primary_tests/code/primary_comparisons.py')
        ss = load('studies/confirmation/execution/seal_score.py')
        days = pd.date_range('2026-08-01', periods=14).strftime('%Y-%m-%d').tolist()
        panel = pd.DataFrame({'target_day': days, 'y': np.arange(14, dtype='float64')})
        pvalues = {('M_notice', score.SEED, 'main'): panel.y.to_numpy() + np.linspace(1.0, 3.0, 14), ('L14', score.SEED, 'main'): panel.y.to_numpy() + np.linspace(0.8, 2.8, 14), ('L_Laz', score.SEED, 'main'): panel.y.to_numpy() + np.linspace(1.4, 3.1, 14), ('L_chen_notice', score.SEED, 'main'): panel.y.to_numpy() + np.linspace(1.1, 2.9, 14)}
        family_native = types.SimpleNamespace(_read_task_data=lambda *args: (panel, days, [1] * 14, pvalues, {}, [], {}), _daily=ss._daily, _json_result=a2.json_safe)
        family = score.family_score(family_native, sc, None, 'notice', sc.NOTICE_FAMILY, {}, [], a2=a2)
        assert family['bootstrap_draws'] == 100000 and sc.BOOTSTRAP_DRAWS == 2000 and (sc.BOOTSTRAP_SEED == 20260925)
        family_clean, family_arrays = score.clean_record(family_native, family)
        results['a8batch_score_100000_draw_family'] = encoded(family_clean) + b''.join((family_arrays[k].tobytes() for k in sorted(family_arrays)))
        sf = load('scorer_freeze')
        results['scorer_freeze'] = encoded(sf.verify())
        le = load('loss_export')
        daily = types.SimpleNamespace(_daily=lambda panel, p, mask: (['2026-08-01', '2026-08-02'], np.abs(np.asarray(p) - np.array([1.0, 2.0]))))
        results['loss_export'] = encoded(le.bundle(daily, 'notice', 'primary', None, ['2026-08-01', '2026-08-02'], [('L14', 'M_notice')], {'L14': [2.0, 4.0], 'M_notice': [1.0, 5.0]}))
        host = load('check_scoring_context')
        host.now = lambda: '2026-10-05T01:02:03+00:00'
        log = self.scratch / 'same_destination/POSTSCORE_HOST_LOG.jsonl'
        steps = {k: dict(authorised=k != 'KCX', repin_verified=False, bindings=[], argv=[]) for k in host.ORDER}
        host.run_order(steps, dict(rho=2.0, state='NOT_ADMITTED'), None, str(log), call=lambda *a, **k: (_ for _ in ()).throw(AssertionError('Host child invoked')))
        cutoff_bytes = str(host.fill_cutoff('2026-10-05T00:00:00+00:00', [None])).encode()
        results['check_scoring_context'] = lambda: log.read_bytes() + (log.parent / 'POSTSCORE_TURN_STATE.json').read_bytes() + cutoff_bytes
        repin = load('check_scoring_bindings')
        repin.visibility({'code_sha256': {'code/runner.py': C.sha(C.LIVE / C.B_REL / 'code/runner.py')}})
        results['check_scoring_bindings'] = b'visibility:PASS'
        pcx = load('check_matched_controls')
        att = dict(path=str(self.scratch / 'shared/attestation.json'), sha256='c' * 64)
        results['check_matched_controls'] = encoded(pcx.commands('base', att, python='/synthetic/python') + pcx.commands('extension', att, python='/synthetic/python'))
        runner = load('runner')
        frame = pd.DataFrame(dict(origin=['2026-08-01T00:00:00Z'], target_time=['2026-08-01T00:05:00Z'], region=['NSW1'], horizon=[5], target_day=['2026-08-01'], prediction=np.array([1.0], dtype='float32')))
        results['runner'] = encoded(dict(prediction_parity=runner.prediction_parity(frame, frame.copy()), admission=runner.optional_admission(200.0, {'R8_news': 100.0, 'CPS8': 50.0}, rho=1.0)))
        be = load('batch_export')
        results['batch_export'] = encoded(be.family_inputs('R8_notice', {'state': 'NOT_RUN_BUDGET', 'reason': 'SYNTHETIC'}, []))
        post = load('read_comparisons')
        dest = self.scratch / 'same_destination/a8post'
        post.write_output(str(dest), {'state': 'SYNTHETIC_ONLY', 'values': [1, 2, 3]}, dict(synthetic_only=True, inputs=dict(self.official_items, scientific_views=self.views)))
        results['read_comparisons'] = b''.join(((dest / n).read_bytes() for n in ('A8_POSTSCORE.json', 'A8_POSTSCORE_EVIDENCE.json', 'A8_POSTSCORE_RECEIPT.json')))
        outer = load('repin_outer')
        outer.verify_a8_visibility({'code_sha256': {'code/runner.py': C.sha(C.LIVE / C.B_REL / 'code/runner.py')}})
        results['repin_outer'] = b'visibility:PASS'
        listing = load('t5_listing')

        def fake_repin(stage):
            item = dict(self.repin_fixture_identity)
            return dict(delivery_files=[], source_files=[], retained_files=[], adapter_files=[], old_freeze=item, tests=item, batch='matched_controls')
        listing.B.verify_repin = fake_repin
        results['t5_listing'] = listing.listing().encode()
        projection = load('cps8_projection')
        cp_dest = self.scratch / 'same_destination/CPS8_METADATA.json'
        cp_receipt = cp_dest.with_suffix('.receipt.json')
        cp_source = projection.P.identity(common.OUT / 'cps8/CPS8_SELECTION.json')
        cp_output, cp_binding = projection.project(cp_source, cp_dest)
        bound = projection.P.strict_json(cp_receipt)
        times = {'T5': {'files': {i['path']: i['sha256'] for i in (cp_source, cp_output, cp_binding, bound['adapter'])}}}
        checked = projection.verify(cp_output, cp_binding, times)
        assert checked == projection.normalize_selection(projection.P.strict_json(cp_source['path']))
        results['cps8_projection'] = cp_dest.read_bytes()
        self.cps_projection_evidence['D' if associated else 'SET4'] = dict(normalize_project_verify_invoked=True, output_sha256=C.sha(cp_dest), receipt_sha256=C.sha(cp_receipt), source_path=cp_source['path'], destination_path=cp_output['path'], receipt_path=cp_binding['path'], all_four_exact_T5_identities_checked=True, outcome_access=bound['outcome_access'])
        for entry in C.ENTRIES:
            m = load(entry)
            resolved = m.Path(str(C.LIVE / C.B_REL / 'state/PARITY_DATA.json'))
            expected = (self.d if associated else self.b) / 'state/PARITY_DATA.json'
            assert Path(resolved) == expected, (entry, str(resolved), str(expected))
            assert resolved.read_bytes() == self.snapshots[self.d / 'state/PARITY_DATA.json'], entry
            for root in ('state', 'dly8', 'cps8'):
                assert Path(m.Path(str(C.LIVE / C.B_REL / root))) == (self.d if associated else self.b) / root, entry
        results['path_resolution_all_entries'] = encoded({'entries': list(C.ENTRIES), 'all_three_roots': True})
        return results

    def parity_test(self):
        with self.active_t5_fixture():
            old = self.b / 'SCORER_CODE_FREEZE.json'
            data = old.read_bytes()
            shutil.copyfile(self.out / 'SCORER_CODE_FREEZE.json', old)
            try:
                return self._parity_test()
            finally:
                old.write_bytes(data)

    def _parity_test(self):
        shutil.rmtree(self.scratch / 'same_destination', ignore_errors=True)
        with baseline(self.a) as load:
            frozen = self.operations(load, False)
        frozen = {k: value() if callable(value) else value for k, value in frozen.items()}
        self.remove_b_outputs()
        self.a.ambiguity()
        shutil.rmtree(self.scratch / 'same_destination', ignore_errors=True)
        with self.a.installed():
            mapped = self.operations(self.a.load, True)
        mapped = {k: value() if callable(value) else value for k, value in mapped.items()}
        assert set(frozen) == set(mapped)
        self.parity = {k: dict(bytes_equal=frozen[k] == mapped[k], bytes=len(frozen[k]), sha256=hashlib.sha256(frozen[k]).hexdigest()) for k in frozen}
        assert all((x['bytes_equal'] for x in self.parity.values())), self.parity
        self.mocks = ['Baseline Path class relocates only LIVE project to private tmp; no D routing.', 'loss_export.bundle: synthetic native._daily callback supplied as documented function input; no production inference.', 'score_batch.clean_record/score_parity: synthetic native._json_result identity callback.', 'check_scoring_context.now is fixed in BOTH fixtures; call callback raises if any host child is attempted.', 't5_listing.B.verify_repin returns the SAME synthetic dependency identity precomputed outside ACTIVE during fixture construction in BOTH runs; real re-pin validity is not claimed.', 'score_batch.family_score: ONLY data-reader callback supplies synthetic 14-day rows; frozen seal_score._daily and primary_tests/confirmation DM/Holm/HLN/HAC7/bootstrap/reading helpers execute unchanged at 100000 draws, seed20260925.', 'FILL3f fixture generated by existing synthetic harness; five full frozen plain rendering levels and numeric-domain gate execute; complete producer timestamp_checks/receipt validity is not inferred.', 'CPS projection verifies original normalize/project/verify with explicit synthetic four-file T5 identities; no real timestamp issuance is claimed.', 'DLY parquet-named fixtures are unscored placeholder bytes; no model fit or production scoring.']
        return dict(consumer_surfaces=13, deterministic_comparisons=len(self.parity), path_entry_count=len(C.ENTRIES), literal_byte_parity=True)

    def export_test(self):
        with self.active_t5_fixture():
            return self._export_test()

    def _export_test(self):
        for root in ('state', 'dly8', 'cps8'):
            shutil.copytree(self.d / root, self.b / root, dirs_exist_ok=True)

        def relocate(value):
            if isinstance(value, dict):
                return {k: relocate(v) for k, v in value.items()}
            if isinstance(value, list):
                return [relocate(v) for v in value]
            if isinstance(value, str) and value.startswith(str(self.d) + '/'):
                return str(self.b) + value[len(str(self.d)):]
            return value
        dump(self.b / 'state/SEAL_BATCH.json', relocate(C.read(self.b / 'state/SEAL_BATCH.json')))
        for mode in (1, 2):
            p = self.b / ('dly8/mode' + str(mode) + '/DELAY_RECEIPT.json')
            v = relocate(C.read(p))
            if mode == 2:
                v['binding']['source_seal'] = C.identity(self.b / 'state/SEAL_BATCH.json')
            dump(p, v)
        baseline_guard = {'active': False, 'blocked': 0}

        def audit(event, args):
            if baseline_guard['active'] and event == 'open' and args and isinstance(args[0], (str, bytes, os.PathLike)):
                p = Path(os.fsdecode(args[0])).absolute()
                if p.is_relative_to(self.d):
                    baseline_guard['blocked'] += 1
                    raise AssertionError('SET4 export baseline attempted to read D: ' + str(p))
        sys.addaudithook(audit)

        def export(load):
            common = load('batch_inputs')
            runner = load('runner')
            load('batch_export')
            dly = load(C.B_REL + '/code/rebuild_delayed_features.py')
            calls = []
            state = common.OUT / 'state'
            runner.host_context = lambda: (types.SimpleNamespace(execution=types.SimpleNamespace(exclusive_state=lambda state: contextlib.nullcontext())), state)
            dly.launch_mode = lambda mode, context: calls.append(mode)
            result = runner.finish_sealed()
            assert calls == [2]
            return (result, (state / 'score_inputs/A8BATCH_INPUTS.json').read_bytes())
        try:
            with baseline(self.a) as load:
                baseline_guard['active'] = True
                try:
                    frozen, raw_b = export(load)
                finally:
                    baseline_guard['active'] = False
            self.remove_b_outputs()
            with self.a.installed():
                common = self.a.load('batch_inputs')
                runner = self.a.load('runner')
                self.a.load('batch_export')
                dly = self.a.load(C.B_REL + '/code/rebuild_delayed_features.py')
                calls = []
                state = common.OUT / 'state'
                runner.host_context = lambda: (types.SimpleNamespace(execution=types.SimpleNamespace(exclusive_state=lambda state: contextlib.nullcontext())), state)
                dly.launch_mode = lambda mode, context: calls.append(mode)
                mapped = runner.finish_sealed()
                assert calls == [2]
                old_binding_refusal = self.refuse(self.a.source_delivery, 'Supplemental evidence chain incomplete')
                generated = Path(state) / 'score_inputs/A8BATCH_INPUTS.json'
                revisions = list((generated.parent / 'revisions').glob('A8BATCH_INPUTS.json.atomic.*'))
                assert len(revisions) == 1, 'Expected one original exclusive-writer retained hardlink'
                retained = revisions[0]
                assert retained.parent == self.d / 'state/score_inputs/revisions'
                assert re.fullmatch('A8BATCH_INPUTS\\.json\\.atomic\\.[a-z0-9_]{8}', retained.name)
                gs, rs = (generated.stat(), retained.stat())
                assert (gs.st_dev, gs.st_ino, gs.st_size) == (rs.st_dev, rs.st_ino, rs.st_size)
                with self.a._validation():
                    generated_id = C.identity(generated)
                    retained_id = C.identity(retained)
                assert generated_id['bytes'] == retained_id['bytes'] and generated_id['sha256'] == retained_id['sha256']
                with self.a._metadata_access():
                    supplemental = C.read(self.out / 'OUTPUT_EVIDENCE_BINDINGS.json')
                    assert supplemental['source_reviewed'] is True and supplemental['scientific_eligibility_changed'] is False
                    assert not any((i['identity']['path'] == str(retained) for i in supplemental['files']))
                    supplemental['files'].append(dict(role='RETAINED_EXCLUDED', identity=retained_id))
                    dump(self.out / 'OUTPUT_EVIDENCE_BINDINGS.json', supplemental)
                self.renew_temporary_T5(self.a)
                raw_d = (state / 'score_inputs/A8BATCH_INPUTS.json').read_bytes()
            keys = ('state', 'conf_seal_sha256', 'families', 'descriptive', 'CPS8', 'production_score_performed', 'statistics_computed')
            scientific_b = {k: frozen[k] for k in keys}
            scientific_d = {k: mapped[k] for k in keys}
            assert encoded(scientific_b) == encoded(scientific_d)
            assert raw_b != raw_d, 'Root-bearing export identities should differ'
            self.export_evidence = dict(frozen_export_invoked=True, runner_finish_sealed_invoked=True, scientific_fields_byte_equal=True, SET4_baseline_D_opens=baseline_guard['blocked'], SET4_baseline_identities_reassociated_to_B=True, scientific_field_names=list(keys), scientific_fields_sha256=hashlib.sha256(encoded(scientific_b)).hexdigest(), full_export_bytes_equal=False, full_SET4_sha256=hashlib.sha256(raw_b).hexdigest(), full_D_sha256=hashlib.sha256(raw_d).hexdigest(), source_revision_binding=dict(old_binding_refusal=old_binding_refusal, retained_identity=retained_id, same_inode_bytes_SHA_as_generated=True, reviewed_role='RETAINED_EXCLUDED', removed=False, original_source_delivery_T5_reverified=True), exact_difference='seal identity path and DLY8 receipt identity paths/hashes encode different output roots', lifecycle_mocks=['host_context returns synthetic state and no-op exclusive_state', 'rebuild_delayed_features.launch_mode only records mode2; no prediction or fit execution'])
            return self.export_evidence
        finally:
            self.remove_b_outputs()

    def t5_commitment_case(self, variant='valid'):
        with self.t5_fixture() as (a, proposal, *unused):
            roots = a.t5_roots()
            commitment = self.out / 'T5_IDENTITY_COMMITMENTS.json'
            if variant in ('missing_member', 'member_SHA_drift', 'unreviewed', 'duplicate_member', 'unsafe_path', 'eligibility_changed', 'wrong_batch'):
                if variant == 'missing_member':
                    proposal['files'].pop()
                if variant == 'member_SHA_drift':
                    proposal['files'][0]['sha256'] = '0' * 64
                if variant == 'unreviewed':
                    proposal['source_reviewed'] = False
                if variant == 'duplicate_member':
                    proposal['files'].append(copy.deepcopy(proposal['files'][0]))
                if variant == 'unsafe_path':
                    proposal['files'][0]['path'] = str(self.scratch / 'outside_project.json')
                if variant == 'eligibility_changed':
                    proposal['scientific_eligibility_changed'] = True
                if variant == 'wrong_batch':
                    proposal['batch_seal']['sha256'] = '0' * 64
                dump(commitment, proposal)
            files = [C.identity((a.q / rel).resolve()) for rel in roots]
            tsa = []
            for index in (1, 2):
                p = a.q / 'confirmation/TIMESTAMPS' / ('SYNTHETIC_T5_' + str(index) + '.json')
                dump(p, {'synthetic_only': True, 'not_a_real_timestamp': True})
                tsa.append(C.identity(p))
            if variant == 'missing_envelope_T5':
                files = [i for i in files if i['path'] != str(commitment)]
            dump(self.out / 'T5_BINDING.json', dict(state='T5_VERIFIED', source_verified=True, files=files, tsa_receipts=tsa))
            if variant == 'envelope_SHA_drift':
                commitment.write_text(commitment.read_text() + '\n')
            if variant == 'payload_SHA_drift':
                p = next((Path(i['path']) for i in proposal['files'] if Path(i['path']).suffix == '.parquet'))
                p.write_bytes(b'SYNTHETIC changed prediction\n')
            if variant == 'missing_envelope':
                commitment.unlink()
            with a.installed():
                if variant != 'valid':
                    return self.refuse(a.verify_t5_coverage)
                a.verify_t5_coverage()
                indexed = {i['path']: i for i in proposal['files']}
                assert all((indexed[str(p)] == C.identity(p) for p in a.prescore_paths()))
            return dict(original_source_delivery_and_frozen_seal_validators_run=True, all_pre_score_exact_identities_checked=len(proposal['files']), envelope_itself_in_actual_T5=True, raw_payload_files_required_as_direct_T5_roots=False, real_timestamp_validity_claimed=False)

    def metadata_boundaries(self):

        a = C.Association(self.project, synthetic=True)
        forbidden = [self.project / n / 'example.json' for n in ('private', '.aws', '.llm_client', '.git', '__pycache__', 'a1_paper_not_frozen', 'host_state', 'scoring', 'scored', 'predictions', 'prediction', 'sealed', 'evaluation', 'run', 'run_null_ext')]
        forbidden += [self.out / n for n in ('.env', '.env.local', 'auth.json', '.DS_Store', 'OPENED_PATHS.jsonl', 'SEAL_EXTRA.json', 'A8_POSTSCORE.json', 'SCORE_RECEIPT.json', 'INPUTS_V2.json', 'predictions.csv', 'SCORES.csv')]
        forbidden += [a.q / 'confirmation/TIMESTAMPS/T4D.json', self.d / 'state/model.pkl', self.d / 'state/unknown.json', self.d / 'dly8/mode1/attempts/synthetic/notice__M_notice__delay5.parquet', self.d / 'dly8/embedding_cache/corpora' / ('a' * 64 + '.npy')]
        forbidden += [a.q / n for n in ('confirmation/models/model.txt', 'confirmation/model/metadata.json', 'confirmation/metadata/model.txt', 'confirmation/artifacts/weights.bin', 'confirmation/artifacts/weights.pt')]
        accepted = [self.d / n for n in ('DISK_FREEZE.json', 'T4C_BINDING.json', 'T4C_ROOTS.json', 'state/SEAL_BATCH.json', 'state/B0_REPRODUCTION.json', 'state/R8_ADMISSION.json', 'dly8/DELAY_FORECAST_SEAL.json', 'dly8/DLY8_SEAL_R8.json', 'dly8/mode1/MATRIX_EVIDENCE_SEAL.json', 'dly8/mode1/attempts/example/delta0/MATRIX_RELEASE.json', 'dly8/mode1/DELAY_RECEIPT.json', 'cps8/CPS8_SELECTION.json', 'REMEDY_LOG.md')]
        accepted += [self.out / 'T5_IDENTITY_COMMITMENTS.json', self.out / 'SCORER_CODE_FREEZE.json', self.b / 'code/score_batch.py']
        assert all((not a.metadata_root(p) for p in forbidden)), [str(p) for p in forbidden if a.metadata_root(p)]
        assert all((a.metadata_root(p) for p in accepted)), [str(p) for p in accepted if not a.metadata_root(p)]
        return dict(forbidden_paths_refused=len(forbidden), allowed_metadata_paths=len(accepted), filesystem_reads=0, private_tmp_prefix_does_not_disable_valid_synthetic_metadata=True)

    def journal_test(self, variant='valid'):

        self.restore()
        t5 = self.out / 'T5_BINDING.json'
        old = t5.read_bytes() if t5.exists() else None
        post = self.d / 'state/postscore'
        post.mkdir(parents=True)
        for name in ('POSTSCORE_HOST_LOG.jsonl', 'POSTSCORE_TURN_STATE.json'):
            (post / name).write_text('SYNTHETIC mutable journal\n')
        revision = post / 'revisions' / ('POSTSCORE_TURN_STATE.json.' + 'a' * 32)
        revision.parent.mkdir()
        revision.write_text('SYNTHETIC prior turn\n')
        files = [C.identity(C.LIVE / C.B_REL / 'code/check_scoring_context.py'), C.identity(self.out / 'SCORER_CODE_FREEZE.json')]
        tsa = []
        for index in (1, 2):
            p = self.scratch / 'shared' / ('synthetic_tsa_' + str(index) + '.json')
            dump(p, {'synthetic_only': True})
            tsa.append(C.identity(p))
        gate = dict(state='T5_VERIFIED', source_verified=True, files=files, tsa_receipts=tsa)
        if variant == 'missing_producer':
            gate['files'] = files[1:]
        if variant == 'missing_scorer':
            gate['files'] = files[:1]
        if variant == 'one_tsa':
            gate['tsa_receipts'] = tsa[:1]
        if variant == 'unverified':
            gate['source_verified'] = False
        if variant == 'unknown':
            (post / 'POSTSCORE_UNKNOWN.json').write_text('{}\n')
        if variant == 'bad_revision':
            (post / 'revisions/POSTSCORE_TURN_STATE.json.not_uuid').write_text('{}\n')
        if variant != 'missing_T5':
            dump(t5, gate)
        elif t5.exists():
            t5.unlink()
        try:
            if variant == 'valid':
                self.source_delivery()
                assert not any((p in self.a.sealed for p in (post / 'POSTSCORE_HOST_LOG.jsonl', post / 'POSTSCORE_TURN_STATE.json', revision)))
                return dict(known_journals_accepted=2, UUID_revision_accepted=True, producer_scorer_bound=True, two_TSA_identities_checked=True, immutable_T5_outputs_changed=False, timestamp_validity_claimed=False)
            return self.refuse(self.source_delivery)
        finally:
            if old is None:
                if t5.exists():
                    t5.unlink()
            else:
                t5.write_bytes(old)
            self.restore()

    def support_context(self, operation):
        a = C.Association(self.project, synthetic=True)
        a.synthetic = False
        a._released = True
        result = self.refuse(lambda: a.load('runner') if operation == 'load' else a.source_delivery(), 'requires this installed association')
        assert not a.imported and (not a.sealed), 'Out-of-context API touched consumer/output state'
        return dict(result, imported_files=0, sealed_outputs=0)

    def host_parent_fixture(self, a):


        def pin(p):
            row = C.identity(p)
            row.pop('path')
            return row
        for root in (a.f1, a.f2):
            shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True)
        for name in ('DISK_FREEZE.json', 'T4C_BINDING.json'):
            dump(a.d / name, {'synthetic_only': True, 'metadata_anchor': name})

        def native_names(n):
            source = C.LIVE / (C.F1_REL if n == 1 else C.F2_REL) / ('freeze_set' + str(n) + '.py')
            a.verify_code(source)
            tree = ast.parse(source.read_bytes())
            return ast.literal_eval(next((node.value for node in tree.body if isinstance(node, ast.Assign) and any((isinstance(t, ast.Name) and t.id == 'FILES' for t in node.targets)))))
        f1_names = native_names(1)
        for name in f1_names:
            dump(a.f1 / name, {'synthetic_only': True, 'metadata_anchor': name})
        dump(a.f1 / 'SET1_FREEZE.json', dict(state='FROZEN_DISKSET1', utc='2026-10-05T00:00:00+00:00', files={name: pin(a.f1 / name) for name in f1_names}, parents={str(p): pin(p) for p in (a.d / 'DISK_FREEZE.json', a.d / 'T4C_BINDING.json')}))
        tsa = []
        for index in (1, 2):
            p = a.q / 'confirmation/TIMESTAMPS' / ('SYNTHETIC_PARENT_TSA_' + str(index) + '.json')
            dump(p, {'synthetic_only': True, 'not_a_real_timestamp': True})
            tsa.append(C.identity(p))
        dump(a.f1 / 'T4D_BINDING.json', dict(label='T4D', state='T4D_VERIFIED', source_verified=True, utc='2026-10-05T00:01:00+00:00', set1_freeze=C.identity(a.f1 / 'SET1_FREEZE.json'), files=[C.identity(a.f1 / 'SET1_FREEZE.json')], tsa_receipts=tsa))
        names = native_names(2)
        for name in names:
            dump(a.f2 / name, {'synthetic_only': True, 'metadata_anchor': name})
        historical = dict(path=str(a.d / 'dly8/mode1/STOPPED_FOR_REMEDY.json'), sha256='3' * 64, bytes=100)
        dump(a.f2 / 'FAILURE_BINDING.json', {'failure': historical, 'synthetic_only': True})
        parents = {str(p): pin(p) for p in (a.f1 / 'SET1_FREEZE.json', a.f1 / 'T4D_BINDING.json')}
        dump(a.f2 / 'PARENT_PINS.json', parents)
        dump(a.f2 / 'SET2_FREEZE.json', dict(state='FROZEN_DISKSET2', utc='2026-10-05T00:02:00+00:00', files={name: pin(a.f2 / name) for name in names}, parents=parents, parent_labels=['T4B', 'T4C', 'T4D'], next_binding='T4E', failure=historical))
        dump(a.f2 / 'T4E_BINDING.json', dict(label='T4E', state='T4E_VERIFIED', source_verified=True, utc='2026-10-05T00:03:00+00:00', set2_freeze=C.identity(a.f2 / 'SET2_FREEZE.json'), files=[C.identity(a.f2 / 'SET2_FREEZE.json')], tsa_receipts=tsa))
        return dict(set1_freeze=C.identity(a.f1 / 'SET1_FREEZE.json'), t4d_binding=C.identity(a.f1 / 'T4D_BINDING.json'), set2_freeze=C.identity(a.f2 / 'SET2_FREEZE.json'), t4e_binding=C.identity(a.f2 / 'T4E_BINDING.json'))

    def host_parents(self, variant='valid'):
        a = C.Association(self.project, synthetic=True)
        old = {p: p.read_bytes() for root in (a.f1, a.f2) for p in root.rglob('*') if p.is_file()}
        anchors = {p: p.read_bytes() if p.exists() else None for p in (a.d / 'DISK_FREEZE.json', a.d / 'T4C_BINDING.json')}
        binding = self.host_parent_fixture(a)
        try:
            if variant.startswith('missing_'):
                Path(binding[variant.removeprefix('missing_')]['path']).unlink()
            elif variant == 'wrong_parent_path':
                binding['set1_freeze'] = binding['set2_freeze']
            elif variant == 'freeze_SHA_drift':
                binding['set2_freeze']['sha256'] = '0' * 64
            elif variant == 'frozen_code_drift':
                (a.f2 / 'host_wrapper_set2.py').write_bytes(b'SYNTHETIC changed code\n')
            elif variant == 'parent_identity_drift':
                (a.d / 'T4C_BINDING.json').write_bytes(b'SYNTHETIC changed parent\n')
            elif variant == 'SET1_wrong_inventory':
                p = a.f1 / 'SET1_FREEZE.json'
                row = C.read(p)
                row['files'].pop('host_wrapper_set1.py')
                dump(p, row)
                binding['set1_freeze'] = C.identity(p)
                stamp = C.read(a.f1 / 'T4D_BINDING.json')
                stamp['set1_freeze'] = C.identity(p)
                stamp['files'] = [C.identity(p)]
                dump(a.f1 / 'T4D_BINDING.json', stamp)
                binding['t4d_binding'] = C.identity(a.f1 / 'T4D_BINDING.json')
            elif variant in ('T4D_wrong_label', 'T4D_chronology', 'T4D_unverified', 'T4D_one_TSA', 'T4D_duplicate_TSA'):
                p = a.f1 / 'T4D_BINDING.json'
                row = C.read(p)
                if variant.endswith('wrong_label'):
                    row['label'] = 'T4E'
                if variant.endswith('chronology'):
                    row['utc'] = '2026-10-04T00:00:00+00:00'
                if variant.endswith('unverified'):
                    row['source_verified'] = False
                if variant.endswith('one_TSA'):
                    row['tsa_receipts'] = row['tsa_receipts'][:1]
                if variant.endswith('duplicate_TSA'):
                    row['tsa_receipts'] = [row['tsa_receipts'][0]] * 2
                dump(p, row)
                binding['t4d_binding'] = C.identity(p)
            elif variant in ('T4E_wrong_label', 'T4E_chronology', 'T4E_unverified', 'T4E_one_TSA', 'T4E_duplicate_TSA', 'T4E_missing_freeze_coverage'):
                p = a.f2 / 'T4E_BINDING.json'
                row = C.read(p)
                if variant.endswith('wrong_label'):
                    row['label'] = 'T4D'
                if variant.endswith('chronology'):
                    row['utc'] = '2026-10-05T00:02:00+00:00'
                if variant.endswith('unverified'):
                    row['source_verified'] = False
                if variant.endswith('one_TSA'):
                    row['tsa_receipts'] = row['tsa_receipts'][:1]
                if variant.endswith('duplicate_TSA'):
                    row['tsa_receipts'] = [row['tsa_receipts'][0]] * 2
                if variant.endswith('missing_freeze_coverage'):
                    row['files'] = []
                dump(p, row)
                binding['t4e_binding'] = C.identity(p)
            elif variant in ('SET2_wrong_labels', 'SET2_missing_parent', 'SET2_wrong_inventory', 'SET2_unfrozen', 'SET2_bad_timezone', 'SET2_historical_pin_drift'):
                p = a.f2 / 'SET2_FREEZE.json'
                row = C.read(p)
                if variant.endswith('wrong_labels'):
                    row['parent_labels'] = ['T4B', 'T4D', 'T4C']
                if variant.endswith('missing_parent'):
                    row['parents'].pop(str(a.f1 / 'T4D_BINDING.json'))
                if variant.endswith('wrong_inventory'):
                    row['files'].pop('host_wrapper_set2.py')
                if variant.endswith('unfrozen'):
                    row['state'] = 'NOT_FROZEN'
                if variant.endswith('bad_timezone'):
                    row['utc'] = '2026-10-05T10:02:00+10:00'
                if variant.endswith('historical_pin_drift'):
                    row['failure']['sha256'] = '4' * 64
                dump(p, row)
                binding['set2_freeze'] = C.identity(p)
                stamp = C.read(a.f2 / 'T4E_BINDING.json')
                stamp['set2_freeze'] = C.identity(p)
                stamp['files'] = [C.identity(p)]
                dump(a.f2 / 'T4E_BINDING.json', stamp)
                binding['t4e_binding'] = C.identity(a.f2 / 'T4E_BINDING.json')
            if variant == 'valid':
                assert a.verify_host_parents(binding) is True
                return dict(F1_F2_frozen_identity_and_parent_chain_checked=True, T4D_T4E_labels_chronology_checked=True, fake_TSA_identity_count_per_label=2, real_TSA_verification_claimed=False, synthetic_boundary='explicit private/tmp association with exact SYNTHETIC_ONLY marker')
            return self.refuse(lambda: a.verify_host_parents(binding))
        finally:
            for root in (a.f1, a.f2):
                shutil.rmtree(root, ignore_errors=True)
            for p, data in old.items():
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
            for p, data in anchors.items():
                if data is None:
                    if p.exists():
                        p.unlink()
                else:
                    p.write_bytes(data)

    def support_ambiguity(self):
        p = self.b / 'state/API_AMBIGUOUS.json'
        dump(p, {'synthetic_only': True})
        a = C.Association(self.project, synthetic=True)
        a.synthetic = False
        a.release = lambda: setattr(a, '_released', True)

        def enter():
            with a.installed():
                raise AssertionError('Direct support API admitted ambiguous SET4 output')
        try:
            result = self.refuse(enter, 'Ambiguous SET4 production output')
            assert C.ACTIVE is None and (not a.imported)
            return dict(result, before_active_and_import=True, mock='release represents an already verified synthetic release; no production gate bypass exists')
        finally:
            self.remove_b_outputs()

    def installed_API_repro(self, variant='missing_matrix'):

        self.restore()
        a = C.Association(self.project, synthetic=True)
        a.synthetic = False
        a.release = lambda: setattr(a, '_released', True)
        unknown = self.d / 'state/UNSEALED_REVIEW_PROBE.json'
        if variant == 'missing_matrix':
            (self.d / 'dly8/mode1/MATRIX_EVIDENCE_SEAL.json').unlink()
        if variant in ('unknown_output', 'missing_batch'):
            dump(unknown, {'synthetic_only': True, 'must_not_be_read': True})
        if variant == 'missing_batch':
            (self.d / 'state/SEAL_BATCH.json').unlink()
        guard = {'active': False, 'reads': 0}

        def audit(event, args):
            if guard['active'] and event == 'open' and args and isinstance(args[0], (str, bytes, os.PathLike)) and (Path(os.fsdecode(args[0])).absolute() == unknown):
                guard['reads'] += 1
                raise AssertionError('Unsealed reviewer payload opened before API refusal')
        sys.addaudithook(audit)
        try:
            with a.installed():
                guard['active'] = True
                try:
                    if variant == 'missing_batch':
                        result = self.refuse(lambda: a.load('batch_inputs').read_json(unknown))
                    else:
                        result = self.refuse(lambda: a.load('batch_export').export_score_inputs(a.d / 'state'))
                finally:
                    guard['active'] = False
            assert not guard['reads'] and (not (self.d / 'state/score_inputs/A8BATCH_INPUTS.json').exists())
            assert not a.sealed and (not a._parsed), 'Failed source_delivery retained partial trusted membership'
            return dict(result, production_installed_load_branch=True, export_written=False, unsealed_payload_reads=0, failed_attempt_trusted_membership_empty=True, mocks=['only release parent-timestamp_checks prerequisite set to already verified within explicit private/tmp fixture'])
        finally:
            guard['active'] = False
            self.restore()

    def same_object_supplemental_removed(self):
        self.restore()
        import tests_r8bpre
        with tests_r8bpre.four_remedies(self) as f:
            a = f['a']
            binding = f['binding']
            p = self.d / 'state/REVIEW_SUPPLEMENTAL.json'
            f['dump'](p, {'synthetic_only': True})
            rows = [*f['rows'], dict(role='OPERATIONAL_EVIDENCE', identity=C.identity(p))]
            history = a.operational_history(rows)
            complete = a.remedy_history(rows)
            f['dump'](binding, dict(schema='A8DISK_OUTPUT_EVIDENCE_IDENTITIES_V1', source_reviewed=True, batch_seal=C.identity(self.d / 'state/SEAL_BATCH.json'), scientific_eligibility_changed=False, files=rows, operational_history=history, remedy_history=complete))
            parent_inventory = {}
            for n in range(2, 6):
                for path in (f['files'][n][0], f['roots'][n] / ('FAILURE_BINDING.json' if n == 2 else 'FAILURE_BINDINGS.json')):
                    parent_inventory[str(path)] = C.identity(path)
            a.synthetic = False
            a.release = lambda: setattr(a, '_released', True)
            with a.installed():
                a._authority_files.update(parent_inventory)
                a.source_delivery()
                assert p in a.sealed and binding in a.sealed
            binding.unlink()
            with a.installed():
                a._authority_files.update(parent_inventory)
                result = self.refuse(a.source_delivery, 'Unsealed D outputs')
            assert not a.sealed and (not a._parsed), 'Failed retry retained historical trusted membership'
            return dict(result, same_object=True, prior_good_source_delivery=True, removed_binding_not_cached=True, trusted_membership_empty_after_failure=True, production_source_delivery_branch=True, original_operational_history_validator_executed=True, four_honest_remedy_validator_executed=True, mocks=['only prior parent release and its exact owned F2-F5 freeze/failure timestamp_checks identities are inert premises'])

    def external_helper_contract(self, helper='read_json', variant='replaced'):

        self.restore()
        a = C.Association(self.project, synthetic=True)
        a.synthetic = False
        a.release = lambda: setattr(a, '_released', True)
        outside = a.q / 'confirmation' / ('UNSEALED_CAPTURED_' + helper + '.json')
        first = b'{"synthetic_only":true,"value":123}\n'
        second = b'{"synthetic_only":true,"value":456}\n'
        outside.write_bytes(first)
        destination = self.scratch / ('UNPUBLISHED_COPY_' + variant + '_' + helper + '.json')
        alias = None
        parent_alias = None
        try:
            with a.installed():
                a.source_delivery()
                fn = getattr(a.load('batch_inputs'), helper)
            reference_snapshot = C.identity(outside)
            outside.write_bytes(second)
            after = C.identity(outside)
            assert reference_snapshot['bytes'] == after['bytes'] == 36 and reference_snapshot['sha256'] != after['sha256']
            source = outside
            if variant == 'leaf_alias':
                alias = self.scratch / ('outside_alias_' + helper + '.json')
                alias.symlink_to(outside)
                source = alias
            elif variant == 'parent_alias':
                parent_alias = self.scratch / ('outside_alias_parent_' + helper)
                parent_alias.symlink_to(outside.parent, target_is_directory=True)
                source = parent_alias / outside.name
            elif variant == 'named':
                outside.unlink()
                specified = self.d / 'state/PARITY_DATA.json'
                original = specified.read_bytes()
                specified.rename(outside)
                specified.write_bytes(original)
                outside.write_bytes(b'{"synthetic_only":true,"values":[999]}\n')
            probe = {'active': False, 'opens': 0}
            prohibited = {Path(source).absolute(), outside.absolute()}

            def audit(event, args):
                if probe['active'] and event == 'open' and args and isinstance(args[0], (str, bytes, os.PathLike)) and (Path(os.fsdecode(args[0])).absolute() in prohibited):
                    probe['opens'] += 1
                    raise AssertionError('Public helper opened outside-chain result before refusal')
            sys.addaudithook(audit)
            try:
                with a.installed():
                    a.source_delivery()
                    assert str(outside.resolve()) not in a._verified_files
                    probe['active'] = True
                    result = self.refuse(lambda: fn(source, destination) if helper == 'atomic_copy' else fn(source))
            finally:
                probe['active'] = False
            assert probe['opens'] == 0 and (not destination.exists())
            return dict(result, helper=helper, variant=variant, captured_before_mutation=True, global_original_source_delivery_valid_before_actual_read=True, outside_identity_never_in_manifest=True, same_size_replacement_bytes=36 if variant != 'named' else None, unknown_payload_open_attempts=0, copied_output_published=False, production_public_API_branch=True, mocks=['only parent release already-verified premise in explicit private/tmp fixture'])
        finally:
            for p in (alias, parent_alias, outside, destination):
                if p is not None and (p.exists() or p.is_symlink()):
                    p.unlink()
            self.restore()

    def specified_external_helper(self, helper='read_json'):
        self.restore()
        a = C.Association(self.project, synthetic=True)
        a.synthetic = False
        a.release = lambda: setattr(a, '_released', True)
        p = Path(self.seal['conf_seal']['path'])
        expected = C.identity(p)
        value = C.read(p)
        with a.installed():
            a.source_delivery()
            assert a._verified_files[str(p)] == expected
            fn = getattr(a.load('batch_inputs'), helper)
            actual = fn(p)
        assert actual == {'read_json': value, 'sha': expected['sha256'], 'identity': expected}[helper]
        return dict(helper=helper, original_bound_external_CONF_identity_accepted=True, bytes_SHA_checked=True, production_public_API_branch=True, mocks=['only temporary already-verified release parent premise'])

    def specified_alias_refusal(self, parent=False):
        self.restore()
        a = C.Association(self.project, synthetic=True)
        a.synthetic = False
        a.release = lambda: setattr(a, '_released', True)
        p = Path(self.seal['conf_seal']['path'])
        alias = self.scratch / ('specified_parent_alias' if parent else 'specified_leaf_alias.json')
        alias.symlink_to(p.parent if parent else p, target_is_directory=parent)
        source = alias / p.name if parent else alias
        results = []
        try:
            with a.installed():
                a.source_delivery()
                assert str(p) in a._verified_files
                common = a.load('batch_inputs')
                for helper in ('read_json', 'sha', 'identity', 'atomic_copy'):
                    fn = getattr(common, helper)
                    destination = self.scratch / ('SPECIFIED_ALIAS_NO_COPY_' + helper + '.json')
                    results.append(self.refuse(lambda fn=fn, destination=destination: fn(source, destination) if helper == 'atomic_copy' else fn(source)))
                    assert not destination.exists()
            return dict(specified_target_identity_valid=True, parent_directory_alias=parent, helpers_refused=4, refusals=results, symlink_alias_never_authorizes_specified_target=True)
        finally:
            alias.unlink()
            self.restore()

    def interpreter_basename_metadata(self):

        with self.active_t5_fixture() as a:
            argv = [sys.executable, '-B', str(HERE / C.FIT_SHIMS['check_scoring_context']), '--execute']
            executable = Path(sys.executable)
            protected = {executable.absolute(), executable.resolve()}
            probe = {'active': False, 'opens': 0}

            def audit(event, args):
                if probe['active'] and event == 'open' and args and isinstance(args[0], (str, bytes, os.PathLike)) and (Path(os.fsdecode(args[0])).absolute() in protected):
                    probe['opens'] += 1
                    raise AssertionError('Readonly argv classification opened interpreter bytes')
            sys.addaudithook(audit)
            try:
                with baseline(a) as load:
                    overlap = load('studies/source_bindings/overlap.py')
                    runner = load('runner')
                    probe['active'] = True
                    expected = (overlap.script_command(argv), runner.fitting_argv(argv), overlap.Path(sys.executable).name)
                    probe['active'] = False
                with a.installed():
                    a.verify_t5_coverage()
                    overlap = a.load('studies/source_bindings/overlap.py')
                    runner = a.load('runner')
                    probe['active'] = True
                    actual = (overlap.script_command(argv), runner.fitting_argv(argv), overlap.Path(sys.executable).name)
                    probe['active'] = False
                assert actual == expected and actual[0] is not None and (actual[1] is True)
                assert actual[2] == executable.name and probe['opens'] == 0
                return dict(original_overlap_and_runner_predicates_equal=True, interpreter_is_symlink=executable.is_symlink(), original_basename_preserved=True, interpreter_payload_opens=0, actual_execution=False, valid_T5_before_probe=True)
            finally:
                probe['active'] = False

    def raw_specified_alias_refusal(self, parent=False):

        with self.active_t5_fixture() as a:
            target = Path(self.seal['conf_seal']['path'])
            alias = self.scratch / ('raw_specified_parent_alias' if parent else 'raw_specified_leaf_alias.json')
            alias.symlink_to(target.parent if parent else target, target_is_directory=parent)
            source = alias / target.name if parent else alias
            probe = {'active': False, 'opens': 0}
            results = []
            prohibited = {source.absolute(), target.absolute()}

            def audit(event, args):
                if probe['active'] and event == 'open' and args and isinstance(args[0], (str, bytes, os.PathLike)) and (Path(os.fsdecode(args[0])).absolute() in prohibited):
                    probe['opens'] += 1
                    raise AssertionError('Raw original helper opened alias or specified target before refusal')
            sys.addaudithook(audit)
            try:
                with a.installed():
                    a.verify_t5_coverage()
                    common = a.load('batch_inputs')
                    assert str(target) in a._verified_files
                    raw = common._module
                    for helper in ('read_json', 'sha', 'identity', 'atomic_copy'):
                        fn = getattr(raw, helper)
                        destination = self.scratch / ('RAW_ALIAS_UNPUBLISHED_' + str(parent) + '_' + helper + '.json')
                        probe['active'] = True
                        try:
                            results.append(self.refuse(lambda fn=fn, destination=destination: fn(source, destination) if helper == 'atomic_copy' else fn(source), 'symlink'))
                        finally:
                            probe['active'] = False
                        assert not destination.exists()
                assert probe['opens'] == 0
                return dict(raw_original_reexported_helpers=True, ConsumerModule_preflight_bypassed_for_regression=True, specified_target_and_T5_valid=True, parent_directory_alias=parent, helpers_refused=4, refusals=results, alias_or_target_payload_opens=0, copied_outputs_published=0)
            finally:
                probe['active'] = False
                alias.unlink()

    def explicit_code_authorities(self):
        self.restore()
        a = C.Association(self.project, synthetic=True)
        a.synthetic = False
        a.release = lambda: setattr(a, '_released', True)
        source = C.LIVE / C.ENTRIES['batch_inputs']
        freeze = self.b / 'CODE_FREEZE.json'
        source_id = C.identity(source)
        freeze_value = C.read(freeze)
        freeze_id = C.identity(freeze)
        with a.installed():
            common = a.load('batch_inputs')
            assert common.sha(source) == source_id['sha256']
            assert common.identity(source) == source_id
            assert common.read_json(freeze) == freeze_value
            assert common.sha(freeze) == freeze_id['sha256']
        return dict(exact_original_source_and_freeze_metadata_identities_accepted=4, production_public_API_branch=True, mocks=['only verified temporary release premise'])

    def external_native_reader_contract(self, kind='numpy'):

        import functools
        with self.active_t5_fixture() as a:
            p = a.q / 'confirmation' / ('UNSEALED_NATIVE_EXTERNAL_' + kind + '.bin')
            specified = Path(self.seal['conf_seal']['path'])
            p.write_bytes(b'X' * specified.stat().st_size)
            assert p.stat().st_size == specified.stat().st_size and p.stat().st_ino != specified.stat().st_ino
            alias = self.scratch / ('native_external_alias_' + kind)
            alias.symlink_to(p)
            stream = p.open('rb')

            class FDProxy:
                name = str(specified)

                @property
                def closed(self):
                    return stream.closed

                def readable(self):
                    return stream.readable()

                def fileno(self):
                    return stream.fileno()

                def read(self, *args, **kwargs):
                    return stream.read(*args, **kwargs)

                def seek(self, *args, **kwargs):
                    return stream.seek(*args, **kwargs)

                def tell(self):
                    return stream.tell()

            class NameOnly:
                name = str(specified)
                closed = False

                def readable(self):
                    return True

                def read(self, *args, **kwargs):
                    raise AssertionError('Name-only untracked reader used')
            if kind == 'numpy':
                import numpy as owner
                name = 'load'
                invoke = lambda source: owner.load(source)
            elif kind == 'pandas':
                import pandas as owner
                name = 'read_csv'
                invoke = lambda source: owner.read_csv(source)
            elif kind == 'joblib':
                import joblib as owner
                name = 'load'
                invoke = lambda source: owner.load(source)
            else:
                import lightgbm
                owner = lightgbm.Booster
                name = '__init__'
                invoke = (lambda source: owner(model_file=source)) if kind == 'lightgbm_keyword' else lambda source: owner(None, None, source)
            original = getattr(owner, name)
            native_calls = []

            @functools.wraps(original)
            def sink(*args, **kwargs):
                native_calls.append(True)
                raise AssertionError('Native reader reached unknown actual input')
            setattr(owner, name, sink)
            try:
                results = []
                with a.installed():
                    a.verify_t5_coverage()
                    assert str(specified) in a._verified_files and str(p) not in a._verified_files
                    for variant, source in (('path', p), ('leaf_alias', alias), ('real_FD_spoofed_name', FDProxy()), ('name_without_FD', NameOnly())):
                        result = self.refuse(lambda source=source: invoke(source))
                        results.append(dict(variant=variant, refusal=result))
                assert not native_calls
                return dict(native_reader=kind, actual_argument_variants=4, refusals=results, original_source_delivery_and_T5_valid=True, native_parser_initializer_calls=0, spoofed_payload_same_size_as_specified=True, actual_file_FD_identity_cannot_be_replaced_by_name=True, mocks=['only native parser/initializer replaced by failing inert sink; real synthetic chain/T5 validators execute'])
            finally:
                setattr(owner, name, original)
                stream.close()
                alias.unlink()
                p.unlink()

    def mixed_mode_unknown_payload(self, create=False):

        with self.active_t5_fixture() as a:
            p = a.q / 'confirmation' / ('UNSEALED_MIXED_CREATE.json' if create else 'UNSEALED_MIXED_EXISTING.json')
            original = b'{"synthetic_only":true,"value":123}\n'
            if not create:
                p.write_bytes(original)
            else:
                assert not p.exists()
            probe = {'active': False, 'opens': 0}

            def audit(event, args):
                if probe['active'] and event == 'open' and args and isinstance(args[0], (str, bytes, os.PathLike)) and (Path(os.fsdecode(args[0])).absolute() == p):
                    probe['opens'] += 1
                    raise AssertionError('Mixed mode opened unknown payload before refusal')
            sys.addaudithook(audit)
            try:
                with a.installed():
                    a.verify_t5_coverage()
                    common = a.load('batch_inputs')
                    assert str(p) not in a._verified_files
                    probe['active'] = True
                    result = self.refuse(lambda: Path(p).open('w+b') if create else common.Path(p).open('r+b'))
            finally:
                probe['active'] = False
            assert probe['opens'] == 0
            if create:
                assert not p.exists()
            else:
                assert p.read_bytes() == original
                p.unlink()
            return dict(result, mode='w+b' if create else 'r+b', raw_Path=create, original_source_delivery_and_T5_valid=True, unknown_payload_open_attempts=0, unknown_output_created=False, original_unknown_bytes_unchanged=True)

    def private_loader_requires_internal_context(self):
        a = C.Association(self.project, synthetic=True)
        a.synthetic = False
        a.release = lambda: setattr(a, '_released', True)
        with a.installed():
            result = self.refuse(lambda: a._load_verified('batch_inputs'))
        assert not a.imported, 'Private loader imported a consumer outside validation/preparation'
        return dict(result, private_loader_not_public_bypass=True, mocks=['only temporary verified release premise'])

    def unauthorized_T5_row(self, variant='model_dir'):
        with self.t5_fixture() as (a, proposal, *unused):
            rel = {'model_dir': 'confirmation/models/model.txt', 'model_name': 'confirmation/metadata/model.txt', 'model_singular_dir': 'confirmation/model/metadata.json', 'bin_payload': 'confirmation/artifacts/weights.bin', 'pt_payload': 'confirmation/artifacts/weights.pt', 'extra_metadata': 'confirmation/ADDED_REVIEW_METADATA.json'}[variant]
            p = a.q / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'SYNTHETIC non-authorized fixture only\n')
            descriptor = C.identity(p)
            proposal['files'].append(descriptor)
            dump(self.out / 'T5_IDENTITY_COMMITMENTS.json', proposal)
            guard = {'active': True, 'opens': 0, 'hashes': 0}
            old_sha = C.sha

            def audit(event, args):
                if guard['active'] and event == 'open' and args and isinstance(args[0], (str, bytes, os.PathLike)) and (Path(os.fsdecode(args[0])).absolute() == p):
                    guard['opens'] += 1
                    raise AssertionError('Unauthorized model/payload opened during metadata enumeration')

            def sha(path):
                if Path(path) == p:
                    guard['hashes'] += 1
                    raise AssertionError('Unauthorized model/payload hashed during metadata enumeration')
                return old_sha(path)
            sys.addaudithook(audit)
            C.sha = sha
            try:
                result = self.refuse(a.t5_roots)
            finally:
                guard['active'] = False
                C.sha = old_sha
            assert guard['opens'] == guard['hashes'] == 0
            return dict(result, unauthorized_row=rel, payload_open_attempts=0, payload_hash_attempts=0, original_authorized_proposal_unchanged=True, model_contents_are_synthetic_only=True)

    def public_API_drift_after_load(self, captured=False):
        self.restore()
        a = C.Association(self.project, synthetic=True)
        a.synthetic = False
        a.release = lambda: setattr(a, '_released', True)
        p = self.d / 'state/PARITY_DATA.json'
        try:
            with a.installed():
                common = a.load('batch_inputs')
                reader = common.read_json
                assert reader(p) == {'synthetic_only': True, 'reports': [], 'values': [1, 2, 3]}
            p.write_bytes(b'{"synthetic_only":true,"values":[99]}\n')
            with a.installed():
                result = self.refuse(lambda: reader(p) if captured else common.read_json(p))
            assert not a.sealed and (not a._parsed), 'Payload drift left trusted membership cached'
            return dict(result, returned_module_call_checked=not captured, captured_callable_checked=captured, initial_specified_payload_read=True, changed_payload_returned=False, mocks=['only production release prerequisite uses fake verified temporary parent premise'])
        finally:
            self.restore()

    def unverified_D_payload_open(self, kind='direct', drift=False):
        self.restore()
        a = C.Association(self.project, synthetic=True)
        a.synthetic = False
        a.release = lambda: setattr(a, '_released', True)
        p = self.d / 'state/PARITY_DATA.json'
        try:
            if drift:
                with a.installed():
                    a.source_delivery()
                p.write_bytes(b'{"synthetic_only":true,"values":[99]}\n')
            else:
                (self.d / 'dly8/mode1/MATRIX_EVIDENCE_SEAL.json').unlink()
            with a.installed():
                if kind == 'direct':
                    result = self.refuse(lambda: open(str(p), 'rb').read())
                else:
                    routed = C.RoutedPath(str(C.LIVE / C.B_REL / 'state/PARITY_DATA.json'))
                    assert Path(routed) == p
                    result = self.refuse(routed.read_bytes)
            return dict(result, open_kind=kind, prior_successful_source_delivery=drift, unverified_payload_returned=False, production_installed_branch=True, mocks=['only parent release prerequisite is temporary already-verified premise'])
        finally:
            self.restore()

    def late_SET4_appearance(self):
        self.restore()
        self.remove_b_outputs()
        a = C.Association(self.project, synthetic=True)
        a.synthetic = False
        a.release = lambda: setattr(a, '_released', True)
        candidate = self.scratch / 'late_SET4_candidate.json'
        dump(candidate, {'synthetic_only': True})
        destination = self.b / 'state/LATE_REVIEW_AMBIGUITY.json'
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with a.installed():
                common = a.load('batch_inputs')
                os.rename(candidate, destination)
                result = self.refuse(lambda: common.read_json(self.d / 'state/PARITY_DATA.json'), 'Ambiguous SET4')
            assert not a.sealed and (not a._parsed)
            return dict(result, output_appeared_during_installed_context=True, public_call_rechecks_ambiguity=True, SET4_contents_opened_by_consumer=False, mocks=['only parent release premise; atomic rename is an owned temporary synthetic producer event'])
        finally:
            self.remove_b_outputs()
            self.restore()

    def native_reader_refusal(self, kind='numpy'):
        import functools
        self.restore()
        a = C.Association(self.project, synthetic=True)
        a.synthetic = False
        a.release = lambda: setattr(a, '_released', True)
        p = self.d / 'state/UNSEALED_NATIVE_READER_PROBE.bin'
        p.write_bytes(b'SYNTHETIC no native parser may see this\n')
        if kind == 'numpy':
            import numpy as owner
            name = 'load'
            call = lambda: owner.load(str(p))
        elif kind == 'pandas':
            import pandas as owner
            name = 'read_csv'
            call = lambda: owner.read_csv(str(p))
        elif kind == 'joblib':
            import joblib as owner
            name = 'load'
            call = lambda: owner.load(str(p))
        else:
            import lightgbm
            owner = lightgbm.Booster
            name = '__init__'
            call = (lambda: owner(model_file=str(p))) if kind == 'lightgbm_keyword' else lambda: owner(None, None, str(p))
        original = getattr(owner, name)
        native_calls = []

        @functools.wraps(original)
        def sink(*args, **kwargs):
            native_calls.append(True)
            raise AssertionError('Native reader/initializer reached unverified payload')
        setattr(owner, name, sink)
        try:
            with a.installed():
                result = self.refuse(call)
            assert not native_calls
            return dict(result, native_reader=kind, native_parser_or_initializer_calls=0, model_values_read=False, production_installed_branch=True, mocks=['only already-verified parent release premise; native parser/initializer replaced by failing inert sink'])
        finally:
            setattr(owner, name, original)
            self.restore()

    def producer_lifecycle(self, failure=False):
        with self.active_t5_fixture() as a:
            p = self.d / 'state/scoring/SYNTHETIC_INFLIGHT.json'
            p.parent.mkdir(parents=True, exist_ok=True)

            class DeliberateProducerFailure(Exception):
                pass
            try:
                with a.installed():
                    common = a.load('batch_inputs')
                    captured = common.read_json
                    try:
                        with a._consumer_execution('score_batch', producer=True):
                            p.write_bytes(b'{"synthetic_only":true}\n')
                            assert p.read_bytes() == b'{"synthetic_only":true}\n'
                            assert a._producer_seal['files'][str(p)] == C.identity(p)
                            refused = self.refuse(lambda: captured(p))
                            if failure:
                                raise DeliberateProducerFailure()
                    except DeliberateProducerFailure:
                        assert failure
                    assert a._producer_entry is None and (not a._producer_paths) and (a._producer_seal is None)
                    after = self.refuse(p.read_bytes)
                return dict(other_public_consumer_refusal=refused, after_scope_refusal=after, failed_producer=failure, inflight_identity_readable_only_inside_private_producer_fixture=True, authority_revoked_after_scope=True, real_original_scoring_main_executed=False, durable_score_receipt_written=False, mocks=['explicit private temporary producer lifecycle instrument; synthetic metadata T5; no scoring/fitting kernel or real publication'])
            finally:
                self.restore()

    def producer_initialization_failure(self):
        with self.active_t5_fixture() as a:

            class InitializationFailure(Exception):
                pass
            original = C.identity
            yielded = False

            def identity(path):
                if Path(path) == C.LIVE / C.ENTRIES['score_batch']:
                    raise InitializationFailure('synthetic producer identity initialization failure')
                return original(path)
            with a.installed():
                C.identity = identity
                try:
                    try:
                        with a._consumer_execution('score_batch', producer=True):
                            yielded = True
                    except InitializationFailure:
                        pass
                    else:
                        raise AssertionError('Producer initialization fault not reached')
                finally:
                    C.identity = original
                assert not yielded and a._producer_entry is None and (not a._producer_paths) and (a._producer_seal is None)
                assert a._guard_depth == 0 and a._validation_depth == 0 and (a._guard_t5 is False)
            return dict(private_producer_initialization_failure_cleanup=True, scope_body_entered=False, producer_and_guard_authority_revoked=True, real_original_scoring_main_executed=False, mocks=['identity fault only at original scorer source identity inside temporary producer initialization'])

    def isolator_policy(self, unknown_fd=False):
        import consumer_review_isolator as isolator
        guard = isolator.current_isolator()
        if unknown_fd:
            return self.refuse(lambda: guard.canonical('child', dir_fd=-9999, event='test_unknown_fd'), 'Unknown descriptor')
        root = self.scratch / 'isolator_fd_cleanup'
        root.mkdir()
        child = root / 'child'
        child.mkdir()
        (child / 'probe.txt').write_text('SYNTHETIC owned cleanup\n')
        descriptor = os.open(root, os.O_RDONLY)
        try:
            assert guard.canonical('child/probe.txt', dir_fd=descriptor, event='test_specified_fd') == child / 'probe.txt'
        finally:
            os.close(descriptor)
        shutil.rmtree(root)
        assert not root.exists()
        return dict(specified_directory_FD_resolved=True, recursive_owned_cleanup_completed=True, reviewer_compatible_isolator_active=True, live_payload_reads=0)

    def isolator_audit_default_FD(self):
        import consumer_review_isolator as isolator
        guard = isolator.current_isolator()
        p = self.scratch / 'uncreated_audit_default_fd_probe'
        guard.audit('os.mkdir', (str(p), 448, -1))
        guard.audit('os.remove', (str(p), -1))
        guard.audit('os.rmdir', (str(p), -1))
        assert guard.canonical(str(p), dir_fd=-2, event='test_native_AT_FDCWD') == p
        assert not p.exists()
        return dict(Python_audit_omitted_directory_FD=-1, native_Darwin_AT_FDCWD=-2, policy_only_default_FD_events=3, filesystem_mutations=0, unknown_FD_refusal_covered_separately=True)

    def controller_routes(self):
        with self.active_t5_fixture():
            return self._controller_routes()

    def _controller_routes(self):
        a = C.Association(self.project, synthetic=True)
        dispatch = self.load_launch()
        calls = []
        old_run = subprocess.run
        old_exec = os.execve

        def run_sink(command, *args, **kwargs):
            calls.append(('run', list(command)))
            return subprocess.CompletedProcess(command, 0, stdout='SYNTHETIC capture', stderr='')

        def exec_sink(path, command, env):
            calls.append(('exec', list(command)))
        subprocess.run = run_sink
        os.execve = exec_sink
        try:
            with a.installed():
                runner = a.load('runner')
                overlap = a.load('studies/source_bindings/overlap.py')
                a._released = True
                try:
                    for entry, shim in C.FIT_SHIMS.items():
                        args = ['--execute'] + (['--phase', 'extension'] if entry == 'check_matched_controls' else [])
                        original = [sys.executable, '-B', '-P', str(C.LIVE / C.ENTRIES[entry]), *args]
                        expected = [sys.executable, '-B', '-P', str(HERE / shim), *args]
                        subprocess.run(original, check=False, capture_output=True, text=True)
                        a.synthetic = False
                        try:
                            os.execve(sys.executable, original, {'SYNTHETIC_ONLY': '1'})
                        finally:
                            a.synthetic = True
                        assert calls[-2:] == [('run', expected), ('exec', expected)]
                        parsed = overlap.script_command(expected)
                        assert parsed and Path(parsed[0]) == HERE / shim
                        assert runner.fitting_argv(expected) and dispatch.controller_visible(a, entry, expected)
                        assert not dispatch.controller_visible(a, entry, [sys.executable, '-B', str(HERE / shim)])
                        generic = [sys.executable, '-B', str(HERE / 'dispatch.py'), '--consumer', entry, '--', '--execute']
                        assert not runner.fitting_argv(generic) and (not dispatch.controller_visible(a, entry, generic))
                        assert not dispatch.controller_visible(a, entry, ['zsh', '-lc', 'python ' + str(HERE / shim) + ' --execute'])
                    assert not dispatch.controller_visible(a, 'check_scoring_context', [sys.executable, '-B', str(HERE / C.FIT_SHIMS['check_matched_controls']), '--execute'])
                finally:
                    a.synthetic = True
            return dict(controller_shims=4, rewritten_run_calls=4, rewritten_exec_calls=4, flags_arguments_exact=True, original_frozen_visibility_predicates=True, generic_invisible_and_opaque_argv_refused=True, host_children_executed=0, mocks=['subprocess.run and os.execve old functions are inert capture sinks', 'production exec branch selected only inside synthetic fixture active context'])
        finally:
            subprocess.run = old_run
            os.execve = old_exec

    def generic_controller_entry(self):
        with self.active_t5_fixture():
            return self._generic_controller_entry()

    def _generic_controller_entry(self):
        a = C.Association(self.project, synthetic=True)
        dispatch = self.load_launch()
        old_argv = sys.argv[:]
        old_exec = os.execve
        old_factory = dispatch.Association

        class Captured(Exception):
            pass
        calls = []

        def sink(path, command, env):
            calls.append(list(command))
            raise Captured()
        try:
            with a.installed():
                fake = types.SimpleNamespace(release=lambda: None, ambiguity=lambda: None, installed=lambda **kwargs: contextlib.nullcontext(), source_delivery=lambda: None, verify_t5_coverage=lambda: None, load=a.load)
                dispatch.Association = lambda: fake
                os.execve = sink
                for entry, shim in C.FIT_SHIMS.items():
                    extra = ['--execute'] + (['--phase', 'extension'] if entry == 'check_matched_controls' else [])
                    sys.argv = [str(HERE / 'dispatch.py'), '--consumer', entry, '--', *extra]
                    try:
                        dispatch.main()
                    except Captured:
                        pass
                    else:
                        raise AssertionError('Generic fitting controller did not re-exec to visible shim')
                    assert calls[-1] == [sys.executable, '-B', str(HERE / shim), *extra]
                    sys.argv = [str(HERE / shim), '--', '--execute']
                    self.refuse(lambda entry=entry: dispatch.main(entry), 'Controller kernel argv must retain')
                sys.argv = [str(HERE / 'check_scoring_context.py'), '--consumer', 'check_matched_controls', '--', '--execute']
                self.refuse(lambda: dispatch.main('check_scoring_context'), 'Controller shim entry cannot change')
                sys.argv = [str(HERE / 'dispatch.py'), '--consumer', 'check_scoring_context', '--']
                self.refuse(dispatch.main, 'Original controller --execute is required')
            return dict(generic_reexec_shims=4, forced_shim_kernel_visibility_refusals=4, conflicting_consumer_refused=True, missing_execute_refused=True, actual_kernel_run_tests_argv_not_misidentified=True, host_children_executed=0, mocks=['isolated main factory skips synthetic release/source_delivery/T5 gates', 'execve capture sink raises before any real execution'])
        finally:
            sys.argv = old_argv
            os.execve = old_exec
            dispatch.Association = old_factory

    def overlap_snapshot(self, unknown=False):
        self.restore()
        binding = self.out / 'OUTPUT_EVIDENCE_BINDINGS.json'
        old = binding.read_bytes() if binding.exists() else None
        p = self.d / 'state' / ('UNKNOWN_PROCESS_AUDIT.jsonl' if unknown else 'PROCESS_OVERLAP_AUDIT.jsonl')
        p.write_text('SYNTHETIC preT5 overlap event\n')
        snapshot = self.out / 'evidence_snapshots/PROCESS_OVERLAP_AUDIT_PRET5.jsonl'
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, snapshot)
        dump(binding, dict(schema='A8DISK_OUTPUT_EVIDENCE_IDENTITIES_V1', source_reviewed=True, batch_seal=C.identity(self.d / 'state/SEAL_BATCH.json'), scientific_eligibility_changed=False, files=[dict(role='OPERATIONAL_LIVE', identity=C.identity(p), snapshot=C.identity(snapshot))]))
        try:
            if unknown:
                return self.refuse(self.source_delivery, 'Unknown mutable operational file')
            self.source_delivery()
            reference_snapshot = C.identity(snapshot)
            p.write_text('SYNTHETIC preT5 overlap event\nSYNTHETIC later overlap event\n')
            self.a.sealed.clear()
            self.source_delivery()
            assert C.identity(snapshot) == reference_snapshot and snapshot in self.a.sealed and (p not in self.a.sealed)
            return dict(known_overlap_snapshot_checked=True, live_journal_can_advance=True, snapshot_bytes_unchanged=True, scientific_eligibility_changed=False, unknown_operational_files_accepted=False)
        finally:
            if old is None:
                if binding.exists():
                    binding.unlink()
            else:
                binding.write_bytes(old)
            snapshot.unlink()
            self.restore()

    def cache_fixture(self, kind):
        import numpy as np
        root = self.d / 'dly8/embedding_cache'
        revision = 'synthetic_pinned_revision'
        if kind == 'corpus':
            signature = dict(revision=revision, content_budget=254, text_sha256=hashlib.sha256(b'SYNTHETIC corpus').hexdigest(), first_chunk_only=False, dimension=384, dtype='float32')
            key = hashlib.sha256(encoded(signature)).hexdigest()
            vector = root / 'corpora' / (key + '.npy')
            value = dict(signature=signature, encoding={'synthetic_only': True})
        else:
            key = hashlib.sha256(b'[1,2,3]').hexdigest()
            vector = root / 'chunks' / revision / (key + '.npy')
            value = dict(revision=revision, token_ids_sha256=key, token_count=3)
        vector.parent.mkdir(parents=True, exist_ok=True)
        np.save(vector, np.zeros(384, dtype='float32'), allow_pickle=False)
        sidecar = vector.with_suffix('.json')
        dump(sidecar, dict(value, vector_sha256=C.sha(vector)))
        return (vector, sidecar)

    def cache_pair_case(self, kind, variant='valid'):
        self.restore()
        vector, sidecar = self.cache_fixture(kind)
        if variant == 'missing_sidecar':
            sidecar.unlink()
        if variant == 'missing_vector':
            vector.unlink()
        if variant == 'vector_drift':
            vector.write_bytes(b'SYNTHETIC drifted vector bytes\n')
        if variant == 'wrong_key':
            value = C.read(sidecar)
            if kind == 'corpus':
                value['signature']['text_sha256'] = '0' * 64
            else:
                value['token_ids_sha256'] = '0' * 64
            dump(sidecar, value)
        if variant == 'wrong_revision':
            value = C.read(sidecar)
            value['revision'] = 'wrong_revision'
            dump(sidecar, value)
        if variant == 'escape':
            vector = self.d / 'state/escaped_cache.npy'
        if variant == 'symlink':
            target = self.scratch / 'shared/outside-cache.npy'
            target.write_bytes(vector.read_bytes())
            vector.unlink()
            vector.symlink_to(target)
        try:
            if variant == 'valid':
                import numpy as np
                old_load = np.load
                np.load = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('Vector values decoded'))
                try:
                    assert self.a.cache_pair(vector) == (vector, sidecar)
                    assert self.a.cache_pair(sidecar) == (vector, sidecar)
                finally:
                    np.load = old_load
                return dict(kind=kind, native_sidecar_key_and_SHA_checked=True, vector_values_decoded=False, encoder_calls=0)
            return self.refuse(lambda: self.a.cache_pair(vector if variant != 'missing_vector' else sidecar))
        finally:
            self.restore()

    def metadata_and_cache_proposal(self, wrong_producer=False):
        self.restore()
        binding = self.out / 'OUTPUT_EVIDENCE_BINDINGS.json'
        old = binding.read_bytes() if binding.exists() else None
        if binding.exists():
            binding.unlink()
        template = self.out / 'OUTPUT_EVIDENCE_BINDINGS.afterseal.template.json'
        old_template = template.read_bytes() if template.exists() else None
        spec = importlib.util.spec_from_file_location('a8consumer_test_bind_evidence', HERE / 'bind_evidence.py')
        binder = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = binder
        spec.loader.exec_module(binder)
        paths = [self.d / 'state' / n for n in ('DLY8_LAUNCH.json', 'BATCH_STATUS.json', 'RESOURCE_REMEDY.json')]
        paths += [self.d / 'state' / n / 'synthetic_remedy_1.json' for n in ('remedies', 'remedies_used', 'remedied_attempts')]
        paths += [self.d / 'dly8' / ('mode' + str(mode)) / 'STOPPED_FOR_REMEDY.json' for mode in (1, 2)]
        paths += [self.d / 'dly8/embedding_cache/MISSING_CORPORA.jsonl']
        log = self.d / 'REMEDY_LOG.md'
        old_log = log.read_bytes() if log.exists() else None
        paths.append(log)
        for p in paths:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('{}\n')
            assert binder.known_metadata(self.a, p)
        assert not binder.known_metadata(self.a, self.d / 'state/UNREGISTERED_REMEDY.json')
        assert not binder.known_metadata(self.a, self.d / 'state/remedies/invalid.name.json')
        assert not binder.known_metadata(self.a, self.d / 'state/REMEDY_LOG.md')
        assert not binder.known_metadata(self.a, self.d / 'ARBITRARY_REMEDY.md')
        pairs = [self.cache_fixture(kind) for kind in ('corpus', 'chunk')]
        binder.Association = lambda: self.a
        stream = io.StringIO()
        try:
            with contextlib.redirect_stdout(stream):
                binder.propose()
            assert 'Proposal only;' in stream.getvalue() and (not binding.exists())
            proposal = C.read(template)
            assert proposal['scientific_eligibility_changed'] is False and proposal['source_reviewed'] is False
            rows = proposal['files']
            by_path = {Path(row['identity']['path']): row for row in rows}
            assert len(rows) == len(paths) + 4 and all((by_path[p]['role'] == 'OPERATIONAL_EVIDENCE' for p in paths))
            for pair in pairs:
                for p in pair:
                    assert by_path[p]['role'] == 'PRODUCER_SIDECAR_CACHE' and by_path[p]['sidecar'] == C.identity(pair[1])
            proposal['source_reviewed'] = True
            if wrong_producer:
                row = next((row for row in rows if row['role'] == 'PRODUCER_SIDECAR_CACHE'))
                row['producer_sources'] = []
            dump(binding, proposal)
            if wrong_producer:
                return self.refuse(self.source_delivery, 'Cache sidecar/producer association drift')
            self.source_delivery()
            assert all((p in self.a.sealed for p in paths + [p for pair in pairs for p in pair]))
            return dict(original_proposal_function=True, known_metadata_files=len(paths), cache_pairs=2, cache_rows=4, opaque_metadata_and_sidecar_files_sealed=True, scientific_eligibility_changed=False, vector_values_decoded=False, mocks=['binder factory selects explicit synthetic private/tmp association', 'source_reviewed=True applied only to temporary proposal to test census membership'])
        finally:
            if old is None:
                if binding.exists():
                    binding.unlink()
            else:
                binding.write_bytes(old)
            if old_template is None:
                if template.exists():
                    template.unlink()
            else:
                template.write_bytes(old_template)
            if old_log is None:
                if log.exists():
                    log.unlink()
            else:
                log.write_bytes(old_log)
            self.restore()

    def operational_history_case(self, variant='valid'):

        self.restore()
        a = C.Association(self.project, synthetic=True)
        binding = self.out / 'OUTPUT_EVIDENCE_BINDINGS.json'
        failure = a.f2 / 'FAILURE_BINDING.json'
        log = self.d / 'REMEDY_LOG.md'
        template = self.out / 'OUTPUT_EVIDENCE_BINDINGS.afterseal.template.json'
        old = {p: p.read_bytes() if p.exists() else None for p in (binding, failure, log, template)}
        if binding.exists():
            binding.unlink()
        if template.exists():
            template.unlink()
        stopped = self.d / 'dly8/mode1/STOPPED_FOR_REMEDY.json'
        dump(stopped, {'state': 'SYNTHETIC_ORIGINAL_IMPLEMENTATION_DEFECT', 'synthetic_only': True})
        historical = C.identity(stopped)
        retained = self.d / 'dly8/mode1/revisions' / ('STOPPED_FOR_REMEDY.json.' + 'b' * 32)
        retained.parent.mkdir(parents=True, exist_ok=True)
        retained.write_bytes(stopped.read_bytes())
        dump(stopped, {'state': 'SYNTHETIC_REPLACEMENT_CURRENT_FAILURE', 'synthetic_only': True})
        dump(failure, {'failure': historical, 'synthetic_only': True})
        log.write_text('# Synthetic implementation remedy history\n')
        operational = [stopped, log]
        for name in ('remedies', 'remedies_used', 'remedied_attempts'):
            p = self.d / 'state' / name / 'DLY8_mode1.json'
            dump(p, {'synthetic_only': True})
            operational.append(p)
        rows = [dict(role='OPERATIONAL_EVIDENCE', identity=C.identity(p)) for p in operational]
        rows.append(dict(role='RETAINED_EXCLUDED', identity=C.identity(retained)))
        original_checked = C.checked
        historical_checks = []

        def guard(item):
            if item == historical:
                historical_checks.append(item)
                raise AssertionError('Historical failure identity was checked against overwritten current path')
            return original_checked(item)
        C.checked = guard
        try:
            if variant == 'missing_retained':
                rows = rows[:-1]
            if variant == 'retained_SHA_drift':
                retained.write_bytes(b'SYNTHETIC corrupt retained bytes\n')
            if variant == 'current_role_wrong':
                rows[0]['role'] = 'RETAINED_EXCLUDED'
            if variant == 'missing_marker_pair':
                (self.d / 'state/remedied_attempts/DLY8_mode1.json').unlink()
            if variant == 'wrong_historical_path':
                pin = copy.deepcopy(historical)
                pin['path'] = str(self.d / 'dly8/mode2/STOPPED_FOR_REMEDY.json')
                dump(failure, {'failure': pin})
            if variant == 'duplicate_row':
                rows.append(copy.deepcopy(rows[0]))
            if variant in ('missing_retained', 'retained_SHA_drift', 'current_role_wrong', 'missing_marker_pair', 'wrong_historical_path', 'duplicate_row'):
                return self.refuse(lambda: a.operational_history(rows))
            history = a.operational_history(rows)
            assert history['original_failure'] == historical and history['current_failure'] == C.identity(stopped)
            assert history['original_failure'] != history['current_failure'] and history['retained_original'] == [C.identity(retained)]
            if variant == 'valid':
                spec = importlib.util.spec_from_file_location('a8consumer_test_history_binder', HERE / 'bind_evidence.py')
                binder = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = binder
                spec.loader.exec_module(binder)
                binder.Association = lambda: a
                with contextlib.redirect_stdout(io.StringIO()):
                    binder.propose()
                proposed = C.read(template)
                assert proposed['source_reviewed'] is False and proposed['operational_history'] == history
                by_path = {row['identity']['path']: row for row in proposed['files']}
                assert by_path[str(stopped)]['role'] == 'OPERATIONAL_EVIDENCE'
                assert by_path[str(retained)]['role'] == 'RETAINED_EXCLUDED'
                assert by_path[str(log)]['role'] == 'OPERATIONAL_EVIDENCE'
            if variant == 'arbitrary_md':
                other = self.d / 'state/ARBITRARY_REMEDY.md'
                other.write_text('SYNTHETIC unknown Markdown\n')
                rows.append(dict(role='OPERATIONAL_EVIDENCE', identity=C.identity(other)))
            if variant == 'history_envelope_drift':
                history['resource_only'] = True
            dump(binding, dict(schema='A8DISK_OUTPUT_EVIDENCE_IDENTITIES_V1', source_reviewed=True, batch_seal=C.identity(self.d / 'state/SEAL_BATCH.json'), scientific_eligibility_changed=False, files=rows, operational_history=history))
            with a.installed():
                if variant != 'valid':
                    return self.refuse(a.source_delivery)
                a.source_delivery()
            assert not historical_checks and all((p in a.sealed for p in [*operational, retained]))
            return dict(current_STOPPED_role='OPERATIONAL_EVIDENCE', historical_revision_role='RETAINED_EXCLUDED', exact_REMEDY_LOG_md_accepted=True, historical_identity_checks_at_overwritten_current_path=0, retained_original_bytes_checked=True, original_and_current_SHA_differ=True, scientific_eligibility_changed=False, actual_proposal_current_vs_historical_roles_checked=True)
        finally:
            C.checked = original_checked
            for p, data in old.items():
                if data is None:
                    if p.exists():
                        p.unlink()
                else:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(data)
            self.restore()

    def source_delivery(self):
        with self.a.installed():
            self.a.source_delivery()
        return dict(bound_exact_files=len(self.a.sealed), successful_families=2, matrix_release_receipts=8)

    def mutate_refusal(self, path, change, needle=None, reseal_release=False):
        self.restore()
        if callable(change):
            change(path)
        elif change is None:
            path.unlink()
        else:
            path.write_bytes(change)
        if reseal_release:
            root = self.d / 'dly8/mode1'
            value = C.read(root / 'MATRIX_EVIDENCE_SEAL.json')
            value['releases'] = [C.identity(Path(i['path'])) for i in value['releases']]
            dump(root / 'MATRIX_EVIDENCE_SEAL.json', value)
        try:
            return self.refuse(self.source_delivery, needle)
        finally:
            self.restore()

    def repin_whole_token_source_root(self):
        a = C.Association(self.project, synthetic=True)
        with a.installed(preparation=True):
            q = C.RepinQ(a.q)
            one = q / 'batch_estimation/code/runner.py'
            many = q / 'batch_estimation' / 'code' / 'runner.py'
            assert one == many == a.b / 'code/runner.py'
            actual = C.identity(one)
            expected = a.lock['sources'][C.B_REL + '/code/runner.py']['identity']
            assert actual == dict(path=str(one), **expected)
            assert q / 'confirmation/inference_design' == a.q / 'confirmation/inference_design'
        return dict(whole_token_component_token_same_exact_SET4_source=True, bytes_sha_verified=True, computation_changed=False)

    def g39_proposal_refusal(self):
        a = C.Association(self.project, synthetic=True)
        paths = ['studies/inference/table_inputs/code/producer.py', 'studies/inference/a8post6/code/joint_passthrough.py', 'studies/inference/a8post6/CODE_FREEZE.json']
        reference_snapshot = dict(a.imported) if isinstance(a.imported, dict) else set(a.imported)
        results = [self.refuse(lambda rel=rel: a.verify_code(C.LIVE / rel), 'Unpinned/drifted') for rel in paths]
        assert a.imported == reference_snapshot and (not any(('/inference/table_inputs/' in rel or '/inference/a8post6/' in rel for rel in a.lock['sources'])))
        return dict(no_authority_granted=True, implemented_AP_permission=True, AP5_AP6_ungranted_imports_still_refused=True, AP_file_contents_read=False, results=results, notice_constraints_accessed=False)

    def marker_refusal(self):
        p = self.project / 'SYNTHETIC_ONLY.json'
        dump(p, {'synthetic_only': False})
        try:
            return self.refuse(lambda: C.Association(self.project, synthetic=True), 'Synthetic association')
        finally:
            dump(p, {'synthetic_only': True})

    def source_drift(self):
        a = C.Association(self.project, synthetic=True)
        rel = next(iter(a.lock['sources']))
        a.lock['sources'][rel]['identity']['sha256'] = '0' * 64
        return self.refuse(a.sources, 'Source drift')

    def wrong_prediction_root(self):
        self.restore()
        rogue = self.scratch / 'shared/rogue.parquet'
        rogue.write_bytes(b'SYNTHETIC wrong root\n')
        value = copy.deepcopy(self.seal)
        value['predictions'] = [C.identity(rogue)]
        dump(self.d / 'state/SEAL_BATCH.json', value)
        try:
            return self.refuse(self.source_delivery)
        finally:
            self.restore()

    def artifact_check(self):
        assert self.initial_artifacts == {n: C.sha(HERE / n) for n in self.initial_artifacts}, 'Association/test artifact changed during run; re-run required'
        assert self.initial_spec == C.identity(HERE / 'SYNTHETIC_SPEC.md'), 'Synthetic specification changed during run'
        self.a.sources()
        return dict(sha256_current=True)

    def fallback(self):
        with self.active_t5_fixture():
            return self._fallback()

    def _fallback(self):
        reasons = []
        with self.a.installed():
            for entry in C.ENTRIES:
                m = self.a.load(entry)
                for root in ('state', 'dly8', 'cps8'):
                    p = self.b / root / 'NEVER_OPEN.json'
                    reasons.append(self.refuse(lambda p=p: open(str(p), 'rb'), 'No silent SET4 fallback'))
                    lexical = self.b / 'code/..' / root / 'NEVER_OPEN.json'
                    reasons.append(self.refuse(lambda p=lexical: open(str(p), 'rb'), 'No silent SET4 fallback'))
                resolved = m.Path(str(self.b / 'state/PARITY_DATA.json'))
                assert Path(resolved) == self.d / 'state/PARITY_DATA.json', (entry, str(resolved), str(self.d / 'state/PARITY_DATA.json'))
        return dict(entries=len(C.ENTRIES), blocked_builtin_opens=len(reasons))

    def import_gate(self):
        a = C.Association(self.project, synthetic=True)
        a.synthetic = False
        return self.refuse(lambda: a.load('runner'), 'Verify release before importing')

    def install_gate(self):
        a = C.Association(self.project, synthetic=True)
        a.synthetic = False

        def enter():
            with a.installed():
                raise AssertionError('Release bypassed')
        return self.refuse(enter, 'Missing/unsafe bound file')

    def child_refusal(self):
        with self.a.installed():
            return self.refuse(lambda: os.execve(sys.executable, [sys.executable, '-c', 'raise SystemExit(1)'], {}), 'Synthetic test cannot exec')
