'Cache notice overlap inputs within each forecast origin.'
from __future__ import annotations

import ast
import bisect
import copy
import hashlib
import inspect
import textwrap
from datetime import datetime, timedelta
from functools import lru_cache
from types import SimpleNamespace

import numpy as np
import pandas as pd

from common import resources

FROZEN_LAZ_ASOF_AST_SHA256 = '486834bf9489d15afa5cd09cde31881f9aeb48b3724a8dae63915491fea3d8b3'


class NoEncoder:
    def encode_corpus(self, *args, **kwargs):
        raise RuntimeError('forecast_hashes cannot encode unchanged text')


def _name_assignment(node, name):
    return (isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name)


@lru_cache(maxsize=4)
def make_laz_helpers(frozen_laz_asof):
    'Separate the cached overlap inputs from the target-specific calculation.'
    source = textwrap.dedent(inspect.getsource(frozen_laz_asof))
    module = ast.parse(source)
    if len(module.body) != 1 or not isinstance(module.body[0], ast.FunctionDef):
        raise RuntimeError('AF SPEED3 frozen laz_asof source layout drift')
    function = module.body[0]
    if hashlib.sha256(ast.dump(function, include_attributes=False).encode()).hexdigest() != FROZEN_LAZ_ASOF_AST_SHA256:
        raise RuntimeError('AF SPEED3 frozen laz_asof AST identity drift')
    body = function.body
    if (function.name != 'laz_asof' or function.decorator_list
            or [arg.arg for arg in function.args.args] !=
               ['resolved', 'sides', 'issue', 'target_time', 'region']
            or [arg.arg for arg in function.args.kwonlyargs] != ['permit']
            or len(body) != 12
            or not _name_assignment(body[1], 'lookup')
            or not _name_assignment(body[2], 'now')
            or not _name_assignment(body[3], 'target')
            or not _name_assignment(body[4], 'typed')
            or not isinstance(body[5], ast.For)
            or not isinstance(body[6], ast.Assign)
            or not isinstance(body[-1], ast.Return)):
        raise RuntimeError('AF SPEED3 frozen laz_asof body drift')
    guard = body[0]
    if not (isinstance(guard, ast.Expr) and isinstance(guard.value, ast.Call)
            and isinstance(guard.value.func, ast.Name)
            and guard.value.func.id == 'require_execution'):
        raise RuntimeError('AF SPEED3 frozen laz_asof guard drift')

    prepare = copy.deepcopy(function)
    prepare.name = '_speed3_prepare_laz'
    prepare.args.args = [copy.deepcopy(arg) for arg in function.args.args
                         if arg.arg in ('resolved', 'sides', 'issue')]
    prepare.body = [copy.deepcopy(body[i]) for i in (0, 1, 2, 4, 5)] + [
        ast.Return(value=ast.Name(id='typed', ctx=ast.Load()))]

    evaluate = copy.deepcopy(function)
    evaluate.name = '_speed3_evaluate_laz'
    evaluate.args.args = [ast.arg(arg='typed')] + [
        copy.deepcopy(arg) for arg in function.args.args
        if arg.arg in ('issue', 'target_time', 'region')]
    evaluate.body = [copy.deepcopy(guard), copy.deepcopy(body[3])] + [
        copy.deepcopy(node) for node in body[6:]]
    compiled = ast.set_missing_locations(ast.Module(
        body=[prepare, evaluate], type_ignores=[]))
    namespace = dict(frozen_laz_asof.__globals__)
    exec(compile(compiled, '<AF_SPEED3:frozen-laz-split>', 'exec'), namespace)
    return namespace[prepare.name], namespace[evaluate.name]


def partition_regions(typed):

    by_region = {}
    for row in typed:
        by_region.setdefault(row['region'], []).append(row)
    return by_region


def _explicit_clock_series(series, name):


    return (pd.api.types.is_datetime64_any_dtype(series.dtype)
            and series.dt.tz is not None and str(series.dt.tz) == 'UTC')


def full_window_candidates(resolved, panel):
    'Select a stable superset of notice records for the evaluation window.'
    required = {'feature_eligible', 'available_utc', 'cancel', 'start_utc',
                'end_utc', 'temporal_status'}
    if not required.issubset(resolved.columns):
        return resolved
    if not {'origin', 'target_time'}.issubset(panel.columns) or panel.empty:
        return resolved
    for name in ('origin', 'target_time'):
        if not _explicit_clock_series(panel[name], name) or panel[name].isna().any():
            return resolved
    for name in ('available_utc', 'start_utc', 'end_utc'):
        if not _explicit_clock_series(resolved[name], name):
            return resolved
    if 'close_utc' in resolved and not _explicit_clock_series(resolved['close_utc'], 'close_utc'):
        return resolved
    try:
        issue_min, issue_max = panel.origin.min(), panel.origin.max()
        target_min, target_max = panel.target_time.min(), panel.target_time.max()
        eligible = resolved.feature_eligible.astype(bool) & (resolved.available_utc <= issue_max) & ~resolved.cancel
        eligible &= resolved.start_utc.notna() & (resolved.start_utc < target_max)
        eligible &= resolved.end_utc.isna() | (resolved.end_utc > target_min - pd.Timedelta(minutes=5))
        if 'close_utc' in resolved:
            eligible &= resolved.close_utc.isna() | (resolved.close_utc > issue_min)
        eligible &= ~((resolved.temporal_status == 'OPEN_UNTIL_NOTICE') &
                      ((issue_min - resolved.available_utc) >= pd.Timedelta(hours=48)))
        return resolved.loc[eligible]
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):


        return resolved


class _FreshRecordView:

    def __init__(self, active, templates, positions):
        self.active = active
        self.templates = templates
        self.positions = positions

    def to_dict(self, orient='dict', *args, **kwargs):
        if orient == 'records' and not args and not kwargs:
            return [dict(self.templates[int(position)]) for position in self.positions]
        return self.active.to_dict(orient, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.active, name)


class PassRecordCache:

    def __init__(self, candidates):
        self.source = candidates
        self.templates = None
        self.index = None
        self.columns = None
        self.dtypes = None
        try:
            if (type(candidates) is not pd.DataFrame or not candidates.index.is_unique
                    or not candidates.columns.is_unique
                    or isinstance(candidates.index, pd.MultiIndex)
                    or getattr(candidates.index.dtype, 'kind', None) not in ('i', 'u')
                    or not all(isinstance(name, str) for name in candidates.columns)):
                return
            for name in ('available_utc', 'start_utc', 'end_utc'):
                if name not in candidates or not _explicit_clock_series(candidates[name], name):
                    return
            if 'close_utc' in candidates and not _explicit_clock_series(candidates['close_utc'], 'close_utc'):
                return
            self.index = candidates.index.copy(deep=True)
            self.columns = candidates.columns.copy(deep=True)
            self.dtypes = candidates.dtypes.copy(deep=True)
            self.templates = candidates.to_dict('records')
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            self.templates = None

    def wrap(self, active):
        if self.templates is None or type(active) is not pd.DataFrame:
            return active
        try:
            if (not active.index.is_unique or not active.columns.is_unique
                    or not active.columns.equals(self.columns)
                    or not active.dtypes.equals(self.dtypes)
                    or not self.source.index.equals(self.index)
                    or not self.source.columns.equals(self.columns)
                    or not self.source.dtypes.equals(self.dtypes)):
                return active
            positions = self.index.get_indexer(active.index)
            if (positions < 0).any():
                return active
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            return active
        return _FreshRecordView(active, self.templates, positions)


def _typed_filter_domain(row):
    'Filter normalized records with explicit UTC availability and validity clocks.'
    try:
        required = {'available_utc', 'start_utc', 'end_utc', 'region',
                    'event_class', 'closed_asof_issue', 'feature_eligible', 'interval_status'}
        if not required.issubset(row):
            return False
        if (not isinstance(row['closed_asof_issue'], (bool, np.bool_))
                or not isinstance(row['feature_eligible'], (bool, np.bool_))
                or not isinstance(row['region'], str)
                or not isinstance(row['event_class'], str)
                or not isinstance(row['interval_status'], str)):
            return False
        for name in ('available_utc', 'start_utc', 'end_utc'):
            value = row.get(name)
            if name != 'available_utc' and value is None:
                continue
            if (value is pd.NaT or type(value) not in (datetime, pd.Timestamp)
                    or value.tzinfo is None or value.utcoffset() != timedelta(0)):
                return False
        return True
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return False


def retained_typed_rows_by_region(typed):

    result = {}
    for row in typed:
        if _typed_filter_domain(row) and (
                row.get('closed_asof_issue', False) or not row['feature_eligible']
                or row.get('start_utc') is None
                or row['interval_status'] not in ('OPEN_UNTIL_NOTICE', 'BOUNDED')):
            continue
        result.setdefault(row['region'], []).append(row)
    return result


def structural_adapter(A, arms, scratch, checkpoints):

    f = A.features
    prepare, evaluate = make_laz_helpers(f.laz_asof) if 'L_Laz' in arms else (None, None)

    def rows(panel, notices, *, permit, source_relations, **unused):
        f.require_execution(permit)
        records, sides = f.normalize_notices(notices, source_relations, permit=permit)
        checkpoints.append(resources(scratch))
        keys = panel[['origin', 'target_time', 'region']].rename(columns={'origin': 'issue_time'})
        l14 = f.f.l14_projection(records, keys, source_relations.features, permit=permit) if 'L14' in arms else None
        resolved = source_relations.resolve_event_states(records) if 'L_Laz' in arms else None
        if resolved is not None:
            resolved = full_window_candidates(resolved, panel)
        record_cache = PassRecordCache(resolved) if resolved is not None else None
        side_lookup = {(side['notice_id'], side['nrx_window_id']): side for side in sides}
        clocks = [f.f.utc(n['available_utc']) for n in notices]
        failures = np.r_[0, np.cumsum([n['extraction_status'] != 'SUCCESS' for n in notices])]
        for number, (origin, frame) in enumerate(panel.groupby('origin', sort=True)):
            now = f.f.utc(origin)
            end = bisect.bisect_right(clocks, now)
            meta = {'notice_prefix_count': end,
                    'notice_arrivals_6h': end - bisect.bisect_right(clocks, now - pd.Timedelta(hours=6)),
                    'notice_failed_prefix_count': int(failures[end])}
            if resolved is not None:
                active = f._active_laz(resolved, origin, frame.target_time.min(), frame.target_time.max())
                active_keys = set(zip(active.notice_id.astype(str), active.nrx_window_id.astype(str)))
                active_sides = [side_lookup[key] for key in active_keys]
                typed = prepare(record_cache.wrap(active), active_sides, origin, permit=permit)
                typed_by_region = retained_typed_rows_by_region(typed)
            for region, regional in frame.groupby('region', sort=True):
                indices = regional.index.to_numpy()
                extras = {}
                if l14 is not None:
                    block = l14.loc[indices].to_numpy(dtype=np.float32)
                    extras[('L14', 'main')] = {
                        **meta, **{column: block[:, j] for j, column in enumerate(l14.columns)}}
                if resolved is not None:
                    typed = typed_by_region.get(region, ())
                    by_target = {}
                    for target in regional.target_time.drop_duplicates():
                        output, _report = evaluate(typed, origin, target, region, permit=permit)
                        by_target[target] = output
                    columns = f.f.LAZ_COLUMNS
                    block = np.asarray([[by_target[row.target_time][column] for column in columns]
                                        for row in regional.itertuples(index=False)], dtype=np.float32)
                    extras[('L_Laz', 'main')] = {
                        **meta, **{column: block[:, j] for j, column in enumerate(columns)}}
                yield indices, extras, {}
            if number % 48 == 0:
                checkpoints.append(resources(scratch))


    proxy = SimpleNamespace(**vars(f))
    proxy.notice_feature_rows = rows
    proxy.build_encoder = lambda **kwargs: NoEncoder()
    return SimpleNamespace(features=proxy, storage=A.storage, execution=A.execution)

