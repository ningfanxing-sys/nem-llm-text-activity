'Check primary and seed-specific comparison metadata.'
import ast
from contextlib import contextmanager
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import math
import sys
import numpy as np
from adapters import exclusive_json
from source_bytes import CoreStop, checked

PRIMARY = 'seed_20260919'
LOCAL = ('seed_20260920', 'seed_20260921', 'three_seed_mean_prediction')


def reference_mae(losses, pairs, stage, output, entry=PRIMARY):
    for reference in dict.fromkeys(ref for _, ref in pairs):

        if reference not in losses:
            continue
        values = np.asarray(losses[reference], dtype='float64')
        with np.errstate(over='ignore', invalid='ignore'):
            mean = float(values.mean()) if values.size else float('nan')
        if not np.isfinite(values).all() or not math.isfinite(mean) or mean <= 0:
            reason = 'DEC13_REFERENCE_DAY_EQUAL_MAE_NOT_FINITE_OR_POSITIVE: '+stage+'/'+reference
            local = entry in LOCAL
            out = Path(output); out.mkdir(parents=True, exist_ok=True)
            record = dict(schema='MINRUN_DEC13_REFERENCE_MAE_REFUSAL_V1',
                state='NOT_EVALUABLE' if local else 'REFUSE', reason=reason, entry=entry,
                stage=stage, reference=reference, reference_day_equal_mae=mean if math.isfinite(mean) else None,
                reference_values_finite=bool(np.isfinite(values).all()),
                required='finite and strictly positive', native_inference_called=False)
            if local:

                count = 1
                while (out/f'REFERENCE_MAE_LOCAL_{count:04d}.json').exists(): count += 1
                exclusive_json(out/f'REFERENCE_MAE_LOCAL_{count:04d}.json', record)
                return record
            exclusive_json(out/'REFERENCE_MAE_REFUSAL.json', record)
            raise CoreStop(reason)
    return None


@lru_cache(maxsize=1)
def score_calls():

    root = Path(__file__).absolute().parent; project = root.parents[3]
    logical = 'studies/confirmation/execution/seal_score.py'
    pin = next(p for p in json.loads((root/'RUNTIME_SOURCES.json').read_bytes())['files']
               if p['logical_path'] == logical)
    tree = ast.parse(checked(dict(pin, path=str(project/pin['path']))))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'score')
    loop = next(n for n in fn.body if isinstance(n, ast.For) and isinstance(n.target, ast.Name)
                and n.target.id == 'source')
    calls = {}
    for statement in loop.body:
        text = ast.unparse(statement)
        role = ('extra' if isinstance(statement, ast.For) and
                isinstance(statement.target, ast.Name) and statement.target.id == 'seed' else
                'three_seed_mean_prediction' if 'SECONDARY_THREE_SEED_EQUAL_PREDICTION_MEAN' in text else PRIMARY)
        for node in ast.walk(statement):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'specified_daily_inference':
                for line in range(node.lineno, node.end_lineno+1): calls[line] = role
    return str(project/logical), calls


class UnavailableSeedSigns:

    def __init__(self, native): self.native = native
    def __getattr__(self, name): return getattr(self.native, name)
    def sign(self, value): return 0 if value is None else self.native.sign(value)


def score_entry():
    path, calls = score_calls()
    frame = sys._getframe(1)
    while frame is not None:
        if frame.f_code.co_filename == path and frame.f_lineno in calls:
            role = calls[frame.f_lineno]
            return ('seed_'+str(frame.f_locals['seed']) if role == 'extra' else role), frame
        frame = frame.f_back
    return PRIMARY, None


class ScoringBoundary:
    def __init__(self, native, stage, output):
        self.native, self.stage, self.output = native, stage, output
    def __getattr__(self, name): return getattr(self.native, name)
    def specified_daily_inference(self, losses, days, task, permit, panel, *, entry=None):
        inferred, frame = score_entry() if entry is None else (entry, None)
        pairs = self.native.NEWS_FAMILY if task == 'news' else self.native.NOTICE_FAMILY
        failure = reference_mae(losses, pairs, self.stage+'/'+task, self.output, inferred)
        if failure is None:
            return self.native.specified_daily_inference(losses, days, task, permit, panel)

        result = self.native.specified_daily_inference({}, days, task, permit, panel)
        result.update(state='NOT_EVALUABLE', reason=failure['reason'], entry=inferred,
                      reference_mae_gate=failure)
        for report in result['reports']:
            report.update(state='NOT_EVALUABLE', reason=failure['reason'])
        if frame is not None and inferred.startswith('seed_'):
            frame.f_globals['np'] = UnavailableSeedSigns(frame.f_globals['np'])
        return result


@contextmanager
def capture_boundary(L):

    old = L.Capture
    class Capture(old):
        def save(self, *args, **kwargs):
            result = super().save(*args, **kwargs)
            if result.get('reference_mae_gate'):
                self.calls[-1][1].update(state='NOT_EVALUABLE', losses={},
                    reason=result['reason'], native_status='NOT_EVALUABLE',
                    reference_mae_gate=result['reference_mae_gate'])
                if result['entry'] == 'three_seed_mean_prediction':

                    self.calls[0][1]['mean_prediction_failure'] = result['reference_mae_gate']
            return result
    L.Capture = Capture
    try: yield
    finally: L.Capture = old


def primary_bundle(fn, stage, output):
    def call(primary_tests, sc, bundle):
        if bundle['state'] != 'COMPUTED': return fn(primary_tests, sc, bundle)
        tag = bundle['id'].split('/')[-1]
        if tag != 'primary' and tag not in LOCAL: return fn(primary_tests, sc, bundle)
        entry = tag if tag in LOCAL else PRIMARY
        failure = reference_mae(bundle['losses'], bundle['pairs'], stage+'/'+bundle['id'], output, entry)
        if failure:
            clean = dict(bundle, state='NOT_EVALUABLE', losses={}, mean_prediction_losses=None,
                         reason=failure['reason'])
            return fn(primary_tests, sc, clean)
        mean_failure = bundle.get('mean_prediction_failure')
        if mean_failure:
            result = fn(primary_tests, sc, dict(bundle, mean_prediction_losses=None))
            result['three_seed'] = fn(primary_tests, sc, dict(bundle, state='NOT_EVALUABLE', losses={},
                mean_prediction_losses=None, reason=mean_failure['reason']))
            return result
        if bundle.get('mean_prediction_losses') is not None:
            failure = reference_mae(bundle['mean_prediction_losses'], bundle['pairs'],
                stage+'/'+bundle['id']+'/mean', output, 'three_seed_mean_prediction')
            if failure:
                clean = dict(bundle, mean_prediction_losses=None)
                result = fn(primary_tests, sc, clean)

                mean = dict(clean, state='NOT_EVALUABLE', losses={}, reason=failure['reason'])
                result['three_seed'] = fn(primary_tests, sc, mean)
                return result
        return fn(primary_tests, sc, bundle)
    return call


@contextmanager
def ap_boundary(P, output):
    from native_entries import boundary_function
    original = P.build
    dependencies = original.__globals__['dependencies']
    def guarded_dependencies(*args, **kwargs):
        primary_tests, sensitivity_tests, robustness_tests, sc, F = dependencies(*args, **kwargs)
        return primary_tests, sensitivity_tests, robustness_tests, ScoringBoundary(sc, 'AP_R2', output), F
    P.build = boundary_function(original, dependencies=guarded_dependencies,
        compute_bundle=primary_bundle(original.__globals__['compute_bundle'], 'AP_R2', output))
    try: yield
    finally: P.build = original


def sens35_boundary(exports, module, output):

    for task, export in exports.items():
        for tag, bundle in export['series'].items():
            if module.series_disposition(bundle, tag)['state'] == 'COMPUTED':
                failure = reference_mae(bundle['losses'], module.TASKS[task]['pairs'],
                                        'SENS35/'+task+'/'+tag, output, tag)
                if failure:
                    original = {k:deepcopy(bundle.get(k)) for k in ('state','native_status','frozen_parity','reason')}
                    bundle.update(state='NOT_EVALUABLE', native_status='NOT_EVALUABLE', losses={},
                        reason=failure['reason'], reference_mae_gate=failure, reference_mae_original_status=original)
