'Compare notice features and MW parsing on matched saved inputs.'
from __future__ import annotations
import sys
sys.dont_write_bytecode = True

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import re
import resource
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
confirmation = HERE.parent
execution = confirmation / 'execution'
STUDY = confirmation.parent
PROJ = STUDY.parents[1]
HOST_STATE = str((execution / 'host_state').resolve())
AUDIT_LOG = HERE / 'OPENED_PATHS_equivalence.jsonl'

HIST = ('2021-22', '2023', '2024', '2025-11..2026-02')
EXPECTED = {'notices': 16935, 'success': 16461, 'failures': 474}
SLICE_SEED = 20261002
PER_STRATUM = 100
KEYS = ['region', 'issue_time', 'target_time', 'horizon']
notice_extraction = STUDY / 'notice_extraction'
LABELS = notice_extraction / 'results_1_3/labels.parquet'
SCOPE = notice_extraction / 'scope.jsonl'
PREFIX = execution / 'prepared_sources/notice_prefix_keys.parquet'
B1B_KEYS = STUDY / 'B1b/development_metadata.parquet'
L_BLOCK = STUDY / 'notice_fitting/blocks/final/notices_development_L.npy'
F1_INDICES = {'train': STUDY / 'notice_fitting/final/indices/F1_train.npy', 'test': STUDY / 'notice_fitting/final/indices/F1_test.npy'}
ISOBATCH = STUDY / 'ISOBATCH'
ARCHIVED = HERE / 'archive/pre_SPEC_4/execution/notice_label_adapter.py'
ARCHIVED_SHA256 = 'eda051bcf78c286aae251c00902635d633d21b5aca338a29d01303708dcb466f'
STOPWORDS = STUDY / 'word_features/aligned/english_stopwords.txt'
STOPWORDS_SHA256 = 'f6d005956f407dbc6ea32e5ff0c7e8e6f71488d3239b9023efdc7fc139d6375b'
MW_COLUMNS = {'L14': ('nw_res_deficit_mw_local', 'nw_res_min_avail_mw_local'),
              'NPL': ('nw_res_deficit_mw_local', 'nw_res_min_avail_mw_local'),
              'NPP': ('nw_res_deficit_mw_local', 'nw_res_min_avail_mw_local'),
              'L_Laz': ('laz_SizeOfOutage_MW',)}
ROLES_OF_COLUMN = {'nw_res_deficit_mw_local': ['REQUIREMENT', 'AVAILABLE'],
                   'nw_res_min_avail_mw_local': ['AVAILABLE'], 'laz_SizeOfOutage_MW': ['LOSS']}
LAZ_MW_DIAGNOSTICS = ('failure_missing_or_unbound_mw_records', 'known_partial_outage_mw',
                      'known_mw_by_source_fuel', 'complete_outage_mw_available')
RECORD_MW_FIELDS = ('req_mw', 'avail_mw', 'quantity_status')
SIDE_MW_FIELDS = ('bound_loss_mw', 'known_partial_loss_mw', 'rejected_loss_quantity_indices')
ISOBATCH_NUMBER_WITH_UNIT = re.compile(r'^\s*[+-]?(?:\d[\d,]*(?:\.\d+)?|\.\d+)\s*(?:MW|MWh)\s*$', re.I)
SCOPE_NOTICE_ID = re.compile(r'"notice_id":"([^"\\]*)"')
DENIED_COLUMNS = {'y', 'y_true', 'weight', 'price', 'rrp', 'outcome', 'label_available_time'}


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def identity(path):
    p = Path(path).resolve()
    return {'path': str(p), 'sha256': sha256(p), 'bytes': p.stat().st_size}


def install_audit():

    fd = os.open(AUDIT_LOG, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)

    def hook(event, args):
        if event != 'open' or not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        path = os.path.abspath(os.fsdecode(args[0]))
        if path == str(AUDIT_LOG):
            return
        name = Path(path).name
        if (path == HOST_STATE or path.startswith(HOST_STATE + os.sep) or '/semantic_validation/private/' in path
                or name in {'.env', '.netrc'} or '/.llm_client/auth.json' in path or '/Keychains/' in path):
            raise PermissionError('quantity_parsing proof refuses protected path: ' + path)
        os.write(fd, (json.dumps({'time_utc': utc_now(), 'path': path, 'mode': str(args[1]),
                                  'reader': 'spec_4_equivalence'}) + '\n').encode())
    sys.addaudithook(hook)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def parquet_columns(path, columns, **kwargs):

    import pyarrow.parquet as pq
    require(not (set(columns) & DENIED_COLUMNS), 'denied outcome/price column requested')
    with open(path, 'rb') as stream:
        return pq.read_table(stream, columns=list(columns), **kwargs)


sys.path.insert(0, str(execution))
STARTUP = {name: (execution / name).read_bytes() for name in
           ('notice_label_adapter.py', 'runtime.py', 'features_adapter.py', 'feature_storage.py', 'embedding_adapter.py')}


def load_archived_adapter():
    require(sha256(ARCHIVED) == ARCHIVED_SHA256, 'archived pre-quantity_parsing adapter drift')
    spec = importlib.util.spec_from_file_location('_spec_4_pre_nrx_adapter', ARCHIVED)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DigestEncoder:
    'Encode text as a deterministic SHA-256 vector.'

    def encode_corpus(self, text, first_chunk_only=False):
        import numpy as np
        digest = hashlib.shake_256(('1' if first_chunk_only else '0').encode() + b'\0' + str(text).encode()).digest(768)
        vector = (np.frombuffer(digest, dtype='<u2').astype(np.float32) / np.float32(65535.0)) + np.float32(0.5)
        return vector, {'digest_stand_in': True, 'first_chunk_only': bool(first_chunk_only)}


def gated_labels():
    import pyarrow as pa
    import pyarrow.compute as pc
    keys = parquet_columns(LABELS, ['notice_id', 'period', 'scope_group'])
    ids = [str(x) for x in keys.column('notice_id').to_pylist()]
    periods = keys.column('period').to_pylist()
    groups = keys.column('scope_group').to_pylist()
    require(len(set(ids)) == len(ids), 'notice_extraction notice IDs are not unique')
    admissible = {i for i, p in zip(ids, periods) if p in HIST}
    require(all(g == 'FINAL3_HISTORICAL' for p, g in zip(periods, groups) if p in HIST), 'historical scope group drift')
    require(all(g != 'FINAL3_HISTORICAL' for p, g in zip(periods, groups) if p not in HIST), 'later scope group drift')
    table = parquet_columns(LABELS, ['notice_id', 'period', 'terminal_state', 'label_json'])
    table = table.filter(pc.is_in(table['period'], value_set=pa.array(list(HIST))))
    require(table.num_rows == len(admissible), 'historical row filter count differs')
    labels = {}
    for nid, period, state, text in zip(table['notice_id'].to_pylist(), table['period'].to_pylist(),
                                        table['terminal_state'].to_pylist(), table['label_json'].to_pylist()):
        require(period in HIST, 'non-historical notice_extraction row materialised')
        labels[str(nid)] = (state, json.loads(text) if text is not None else None)
    receipt = {'rows_total': len(ids), 'rows_admissible': len(admissible),
               'rows_excluded_content_not_materialized': len(ids) - len(admissible),
               'excluded_periods': sorted(set(periods) - set(HIST)),
               'terminal_state_counts': dict(Counter(state for state, _ in labels.values()))}
    return ids, admissible, labels, receipt


def gated_scope_rows(all_ids, admissible):

    rows, seen, parsed = [], set(), 0
    with open(SCOPE, 'r', encoding='utf-8') as stream:
        for line in stream:
            match = SCOPE_NOTICE_ID.search(line)
            require(match is not None, 'scope line without a top-level notice_id token')
            nid = match.group(1)
            require(nid not in seen, 'duplicate scope notice_id')
            seen.add(nid)
            if nid not in admissible:
                continue
            row = json.loads(line)
            parsed += 1
            require(str(row['notice_id']) == nid and row.get('period') in HIST, 'scope line identity/period drift')
            rows.append(row)
    require(seen == set(all_ids), 'scope/labels ID census mismatch')
    return rows, {'scope_lines': len(seen), 'scope_lines_parsed': parsed,
                  'scope_lines_not_parsed': len(seen) - parsed}


def map_host_notices(rows, labels, clock_map, f):

    out = []
    for n in rows:
        nid = str(n['notice_id'])
        if nid not in labels:
            raise ValueError('notice_extraction missing terminal census label: ' + nid)
        status, label = labels[nid]
        clock = n['clocks']
        available = clock.get('available_time_utc')
        if not available:
            raise ValueError('notice_extraction source missing official availability clock')
        if clock_map:
            if nid not in clock_map:
                raise ValueError('notice_extraction scope absent from canonical prefix: ' + nid)
            expected = clock_map[nid].get('available_utc', clock_map[nid].get('available_time_utc'))
            if f.utc(expected) != f.utc(available):
                raise ValueError('notice_extraction/prefix clock conflict: ' + nid)
        out.append({**n, 'available_utc': available, 'notice_type': n.get('source_notice_type', ''),
                    'anchor_local': clock.get('raw_time_local'),
                    'extraction_status': 'SUCCESS' if status == 'SUCCESS' else 'TERMINAL_FAILURE', 'nrx_label': label})
    if {str(n['notice_id']) for n in out} != set(labels):
        raise ValueError('notice_extraction scope/labels census mismatch')
    return sorted(out, key=lambda n: (f.utc(n['available_utc']), str(n['notice_id'])))


def loader_parity(fa, f, permit, scratch):

    import pandas as pd
    root = scratch / 'loader_parity' / 'results_1_3'
    root.mkdir(parents=True)
    scope = []
    for nid, when, local in (('9101', '2026-01-02T00:05:00Z', '2026-01-02 10:03:00'),
                             ('9100', '2026-01-02T00:05:00Z', '2026-01-02 10:01:00'),
                             ('9102', '2026-01-01T23:55:00Z', None)):
        clocks = {'available_time_utc': when, 'timezone_contract': 'Australia/Brisbane'}
        if local:
            clocks['raw_time_local'] = local
        scope.append({'notice_id': nid, 'title': 'Synthetic ' + nid, 'body': 'Body\n' + nid, 'period': HIST[-1],
                      'source_notice_type': 'RESERVE NOTICE', 'clocks': clocks})
    (root.parent / 'scope.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in scope))
    label = {'notice_id': '9100', 'quantities': [{'value_text': '447 MW'}]}
    pd.DataFrame([{'notice_id': '9100', 'terminal_state': 'SUCCESS', 'label_json': json.dumps(label)},
                  {'notice_id': '9101', 'terminal_state': 'TERMINAL_FAILURE', 'label_json': None},
                  {'notice_id': '9102', 'terminal_state': 'SUCCESS', 'label_json': json.dumps({**label, 'notice_id': '9102'})}]
                 ).to_parquet(root / 'labels.parquet')
    prefix = [{'notice_id': r['notice_id'], 'available_utc': r['clocks']['available_time_utc']} for r in scope]
    production = fa.load_host_notices(root, permit=permit, prefix_clock_rows=prefix)
    labels = {'9100': ('SUCCESS', label), '9101': ('TERMINAL_FAILURE', None),
              '9102': ('SUCCESS', {**label, 'notice_id': '9102'})}
    gated = map_host_notices(scope, labels, {r['notice_id']: r for r in prefix}, f)
    require(production == gated, 'gated notice mapping differs from production load_host_notices')
    return {'synthetic_notices': len(gated), 'equal_to_production_load_host_notices': True}


def quantity_census(notices, old, new):
    import numpy as np
    counts, remaining = Counter(), []
    lost = changed_value = 0
    for n in notices:
        label = n['nrx_label']
        if not label:
            continue
        for index, q in enumerate(label.get('quantities', [])):
            role, unit, value = str(q.get('role')), str(q.get('unit')), q.get('value_text', '')
            bound = q.get('binding_status') == 'BOUND' and q.get('binding_reason') == 'BOUND_EXPLICIT_SOURCE_SCOPE'
            nonnegative = role == 'LOSS'
            reference_snapshot = old.scalar(value, nonnegative=nonnegative)
            after = new.scalar(value, nonnegative=nonnegative, unit=q.get('unit'))
            form = ('adapter_scalar' if math.isfinite(old.scalar(value)) else
                    'number_with_unit_text' if ISOBATCH_NUMBER_WITH_UNIT.match(str(value)) else
                    'UNKNOWN' if value == 'UNKNOWN' else 'other_text')
            counts[(role, unit, bound, n['extraction_status'], form, math.isfinite(reference_snapshot), math.isfinite(after))] += 1
            if math.isfinite(reference_snapshot) and not math.isfinite(after):
                lost += 1
            if math.isfinite(reference_snapshot) and math.isfinite(after) and np.float64(reference_snapshot).tobytes() != np.float64(after).tobytes():
                changed_value += 1
            if bound and unit == 'MW' and role in ('REQUIREMENT', 'AVAILABLE', 'LOSS') and not math.isfinite(after):
                remaining.append({'notice_id': str(n['notice_id']), 'quantity_index': index, 'role': role,
                                  'value_text': value, 'isobatch_form': form})
    rows = [dict(zip(('role', 'unit', 'bound', 'extraction_status', 'isobatch_form', 'accepted_before',
                      'accepted_after', 'n'), (*key, n))) for key, n in sorted(counts.items(), key=lambda kv: tuple(map(str, kv[0])))]
    table = {}
    for role in ('REQUIREMENT', 'AVAILABLE', 'LOSS'):
        sel = [r for r in rows if r['role'] == role and r['unit'] == 'MW' and r['bound']]
        total = sum(r['n'] for r in sel)
        forms = Counter()
        for r in sel:
            forms[r['isobatch_form']] += r['n']
        reference_snapshot = sum(r['n'] for r in sel if r['accepted_before'])
        after = sum(r['n'] for r in sel if r['accepted_after'])
        table[role] = {'bound_MW_quantities': total, 'isobatch_forms': dict(sorted(forms.items())),
                       'accepted_before': reference_snapshot, 'accepted_after': after,
                       'recovered': sum(r['n'] for r in sel if r['accepted_after'] and not r['accepted_before']),
                       'lost': sum(r['n'] for r in sel if r['accepted_before'] and not r['accepted_after']),
                       'still_unknown_after': total - after,
                       'recovered_among_isobatch_number_with_unit_text': sum(
                           r['n'] for r in sel if r['isobatch_form'] == 'number_with_unit_text' and r['accepted_after']),
                       'not_recovered_among_isobatch_number_with_unit_text': sum(
                           r['n'] for r in sel if r['isobatch_form'] == 'number_with_unit_text' and not r['accepted_after'])}
    totals = {'quantities': sum(counts.values()),
              'accepted_before': sum(r['n'] for r in rows if r['accepted_before']),
              'accepted_after': sum(r['n'] for r in rows if r['accepted_after']),
              'lost_literals': lost, 'changed_values_for_literals_accepted_before_and_after': changed_value,
              'from_terminal_failure_labels': sum(r['n'] for r in rows if r['extraction_status'] != 'SUCCESS')}
    return {'rows': rows, 'bound_mw_table': table, 'totals': totals, 'still_unknown_bound_mw_literals': remaining}


def canon(value):
    import numpy as np
    import pandas as pd
    if value is None:
        return None
    if value is pd.NaT:
        return 'NaT'
    if isinstance(value, pd.Timestamp):
        return 'TS:' + value.isoformat()
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return 'F:' + float(value).hex()
    if isinstance(value, (tuple, list)):
        return [canon(v) for v in value]
    if isinstance(value, dict):
        return {str(k): canon(v) for k, v in value.items()}
    return 'S:' + str(value) if isinstance(value, str) else 'R:' + repr(value)


def column_digest(series):
    payload = json.dumps([canon(v) for v in series.tolist()], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def finite(value):
    return value is not None and isinstance(value, (int, float)) and math.isfinite(value)


def transition(old_value, new_value):
    old_ok, new_ok = finite(old_value), finite(new_value)
    if old_ok and new_ok:
        return 'unchanged_finite' if float(old_value) == float(new_value) else 'finite_to_other_finite'
    if old_ok:
        return 'finite_to_nan'
    if new_ok:
        return 'nan_to_finite'
    return 'nan_unchanged'


def compare_records(old_records, new_records, old_sides, new_sides):
    import numpy as np
    require(list(old_records.columns) == list(new_records.columns), 'record column order differs')
    require(len(old_records) == len(new_records) and old_records.index.equals(new_records.index), 'record rows differ')
    columns = {}
    for name in old_records.columns:
        same_dtype = str(old_records[name].dtype) == str(new_records[name].dtype)
        equal = same_dtype and old_records[name].equals(new_records[name])
        digest_equal = column_digest(old_records[name]) == column_digest(new_records[name])
        columns[name] = {'dtype_equal': same_dtype, 'series_equal': bool(equal), 'canonical_digest_equal': digest_equal}
    non_mw_ok = all(v['dtype_equal'] and v['series_equal'] and v['canonical_digest_equal']
                    for k, v in columns.items() if k not in RECORD_MW_FIELDS)
    changed_record_columns = sorted(k for k, v in columns.items()
                                    if not (v['series_equal'] and v['canonical_digest_equal']))
    require(len(old_sides) == len(new_sides), 'sidecar count differs')
    side_keys_ok = True
    side_non_mw_ok = True
    changed_side_fields = Counter()
    for a, b in zip(old_sides, new_sides):
        if list(a) != list(b):
            side_keys_ok = False
        for key in a:
            if json.dumps(canon(a[key]), sort_keys=True) != json.dumps(canon(b.get(key)), sort_keys=True):
                changed_side_fields[key] += 1
                if key not in SIDE_MW_FIELDS:
                    side_non_mw_ok = False

    roles = {}
    for field, role in (('req_mw', 'REQUIREMENT'), ('avail_mw', 'AVAILABLE')):
        counts = Counter(transition(o, n) for o, n in zip(old_records[field].tolist(), new_records[field].tolist()))
        roles[role] = dict(counts)
    status = Counter((o, n) for o, n in zip(old_records.quantity_status, new_records.quantity_status) if o != n)
    loss = {'windows_with_bound_loss_old': sum(bool(s['bound_loss_mw']) for s in old_sides),
            'windows_with_bound_loss_new': sum(bool(s['bound_loss_mw']) for s in new_sides),
            'accepted_loss_quantities_old': sum(len(s['bound_loss_mw']) for s in old_sides),
            'accepted_loss_quantities_new': sum(len(s['bound_loss_mw']) for s in new_sides),
            'windows_with_rejected_loss_old': sum(bool(s['rejected_loss_quantity_indices']) for s in old_sides),
            'windows_with_rejected_loss_new': sum(bool(s['rejected_loss_quantity_indices']) for s in new_sides)}
    subset_ok = all(set(map(tuple, a['bound_loss_mw'])) <= set(map(tuple, b['bound_loss_mw'])) and
                    set(b['rejected_loss_quantity_indices']) <= set(a['rejected_loss_quantity_indices'])
                    for a, b in zip(old_sides, new_sides))
    finite_changed = sum(1 for field in ('req_mw', 'avail_mw')
                         for o, n in zip(old_records[field].tolist(), new_records[field].tolist())
                         if finite(o) and finite(n) and np.float64(o).tobytes() != np.float64(n).tobytes())
    return {'record_rows': len(old_records), 'record_columns': len(old_records.columns),
            'record_columns_changed': changed_record_columns,
            'record_non_mw_columns_identical': bool(non_mw_ok), 'sidecars': len(old_sides),
            'sidecar_key_order_identical': side_keys_ok, 'sidecar_non_mw_fields_identical': side_non_mw_ok,
            'sidecar_fields_changed': dict(changed_side_fields), 'reserve_role_transitions': roles,
            'quantity_status_transitions': {f'{o}->{n}': c for (o, n), c in sorted(status.items())},
            'loss': loss, 'old_loss_subset_and_rejected_superset': subset_ok,
            'record_finite_values_changed_to_other_finite': finite_changed, 'columns': columns}


def window_summaries(records, sides):
    import numpy as np
    import pandas as pd
    eligible = records.loc[records.kind.eq('RESERVE') & records.feature_eligible.astype(bool)]
    req = pd.to_numeric(eligible.req_mw, errors='coerce').to_numpy(float)
    avail = pd.to_numeric(eligible.avail_mw, errors='coerce').to_numpy(float)
    failures = [s for s in sides if s['event_class'] == 'FAILURE']
    return {'reserve': {'eligible_reserve_records': len(eligible), 'req_finite': int(np.isfinite(req).sum()),
                        'avail_finite': int(np.isfinite(avail).sum()),
                        'both_finite': int((np.isfinite(req) & np.isfinite(avail)).sum())},
            'failure': {'failure_windows': len(failures),
                        'with_bound_loss_mw': sum(1 for s in failures if s['bound_loss_mw']),
                        'with_rejected_loss_quantity': sum(1 for s in failures if s['rejected_loss_quantity_indices']),
                        'known_asset_and_no_rejected_loss': sum(1 for s in failures if s['asset_id'] != 'UNKNOWN'
                                                                 and not s['rejected_loss_quantity_indices']),
                        'known_partial_loss_mw_sum': float(sum(s['known_partial_loss_mw'] for s in failures))}}


def anchor_keys(old_records, new_records, old_sides, new_sides, regions):
    'Select the specified forecast key for each affected historical window.'
    import pandas as pd
    old_by = {(s['notice_id'], s['nrx_window_id']): s for s in old_sides}
    rec_by = {(str(r['notice_id']), str(r['nrx_window_id'])): r for r in new_records.to_dict('records')}
    anchors, considered = [], []
    for s in new_sides:
        key = (s['notice_id'], s['nrx_window_id'])
        reference_snapshot = old_by[key]
        if s['event_class'] != 'FAILURE':
            continue
        if (s['bound_loss_mw'] == reference_snapshot['bound_loss_mw'] and
                s['rejected_loss_quantity_indices'] == reference_snapshot['rejected_loss_quantity_indices']):
            continue
        r = rec_by[key]
        eligible = (bool(r['feature_eligible']) and r['region'] in regions and pd.notna(r['start_utc'])
                    and r['temporal_status'] in ('BOUNDED', 'OPEN_UNTIL_NOTICE'))
        considered.append({'notice_id': key[0], 'nrx_window_id': key[1], 'eligible_for_anchor': eligible,
                           'region': r['region'], 'temporal_status': r['temporal_status'],
                           'bound_loss_mw_old': reference_snapshot['bound_loss_mw'], 'bound_loss_mw_new': s['bound_loss_mw'],
                           'rejected_old': reference_snapshot['rejected_loss_quantity_indices'],
                           'rejected_new': s['rejected_loss_quantity_indices']})
        if not eligible:
            continue
        issue = max(pd.Timestamp(r['available_utc']), pd.Timestamp(r['start_utc'])).tz_convert('UTC').ceil('5min')
        anchors.append({'region': r['region'], 'issue_time': issue, 'target_time': issue + pd.Timedelta(minutes=5),
                        'horizon': 5, 'anchor_notice_id': key[0], 'anchor_window_id': key[1]})
    frame = pd.DataFrame(anchors, columns=['region', 'issue_time', 'target_time', 'horizon',
                                           'anchor_notice_id', 'anchor_window_id'])
    frame = frame.drop_duplicates(subset=['region', 'issue_time', 'target_time', 'horizon']).reset_index(drop=True)
    return frame, considered


def isobatch_slice(f):

    import numpy as np
    import pandas as pd
    column = list(f.L14_COLUMNS).index('nw_any_local')
    l_block = np.load(L_BLOCK, mmap_mode='r')
    rng = np.random.default_rng(SLICE_SEED)
    chosen = []
    for part in ('train', 'test'):
        ids = np.load(F1_INDICES[part])
        active = np.asarray(l_block[ids, column] > 0)
        for flag in (True, False):
            pool = ids[active == flag]
            pick = np.sort(rng.choice(pool, size=PER_STRATUM, replace=False))
            chosen += [(int(i), part, bool(flag)) for i in pick]
    rows = pd.DataFrame(chosen, columns=['row', 'part', 'final3_l_active'])
    require(rows.row.is_unique, 'slice rows overlap')
    rows = rows.sort_values('row').reset_index(drop=True)
    development = parquet_columns(B1B_KEYS, KEYS).to_pandas()
    require(len(development) == 894901, 'development key count differs')
    keys = development.iloc[rows.row.to_numpy()].reset_index(drop=True)
    for name in ('issue_time', 'target_time'):
        keys[name] = pd.to_datetime(keys[name], utc=True).astype('datetime64[ns, UTC]')
    keys['horizon'] = keys['horizon'].astype(int)
    return rows, keys


def run_generator(fa, adapter, panel, notices, cache, source_relations, aligned, vocabulary, stopwords):
    import numpy as np
    with patch.object(fa, 'normalize_notices', adapter.normalize_notices), patch.object(fa, 'laz_asof', adapter.laz_asof):
        yielded = list(fa.notice_feature_rows(panel, notices, permit=PERMIT, encoder=DigestEncoder(),
                                              cache_directory=cache / 'embedding_cache', source_relations=source_relations,
                                              scheduled_notice_features=aligned, vocabulary=vocabulary,
                                              stopwords=stopwords, p5min_columns=['p5_synthetic']))
    order = [key for key in yielded[0][1]]
    names = {key: list(yielded[0][1][key]) for key in order}
    matrices = {key: np.full((len(panel), len(names[key])), np.nan, dtype=np.float32) for key in order}
    filled = np.zeros(len(panel), dtype=np.int64)
    batches = []
    for indices, extras, coverage in yielded:
        require(list(extras) == order and all(list(extras[k]) == names[k] for k in order), 'arm/column order drift')
        for key in order:
            for j, name in enumerate(names[key]):
                matrices[key][indices, j] = np.broadcast_to(np.asarray(extras[key][name], dtype=np.float32), len(indices))
        filled[indices] += 1
        batches.append((np.asarray(indices).tolist(), coverage))
    require((filled == 1).all(), 'every panel row must be yielded exactly once')
    sidecar = (cache / 'NOTICE_DERIVED_DATE_SIDECARS.json').read_bytes()
    return {'order': order, 'names': names, 'matrices': matrices, 'batches': batches, 'sidecar': sidecar}


def mask_laz_diagnostics(coverage):
    out = dict(coverage)
    out['L_Laz'] = [{k: (None if k in LAZ_MW_DIAGNOSTICS else v) for k, v in report.items()}
                    for report in coverage.get('L_Laz', [])]
    return out


def value(x):
    return None if not math.isfinite(float(x)) else float(x)


def jsonable(obj):
    'Convert NumPy scalars to JSON values and reject non-finite numbers.'
    import numpy as np
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        require(math.isfinite(float(obj)), 'non-finite value in result')
        return float(obj)
    if obj is None or isinstance(obj, str):
        return obj
    return str(obj)


def compare_projections(old, new, panel, sets):
    import numpy as np
    require(old['order'] == new['order'] and old['names'] == new['names'], 'arm/variant or column order differs')
    require([b[0] for b in old['batches']] == [b[0] for b in new['batches']], 'yielded row indices differ')
    arms, changed_cells = {}, []
    non_mw_identical = True
    for key in old['order']:
        arm, variant = key
        columns = {}
        for j, name in enumerate(old['names'][key]):
            a = old['matrices'][key][:, j]
            b = new['matrices'][key][:, j]
            differs = a.view(np.uint32) != b.view(np.uint32)
            specified = name in MW_COLUMNS.get(arm, ()) and variant == 'main'
            if differs.any() and not specified:
                non_mw_identical = False
            if specified:
                rows = np.flatnonzero(differs)
                kinds = Counter()
                for i in rows:
                    kind = transition(value(a[i]), value(b[i]))
                    kinds[kind] += 1
                    changed_cells.append({'arm': arm, 'variant': variant, 'column': name, 'row': int(i),
                                          'set': sets[i], 'region': panel.region.iloc[i],
                                          'issue_time': str(panel.origin.iloc[i]),
                                          'target_time': str(panel.target_time.iloc[i]),
                                          'horizon': int(panel.horizon.iloc[i]),
                                          'old': value(a[i]), 'new': value(b[i]), 'transition': kind,
                                          'roles': ROLES_OF_COLUMN[name]})
                columns[name] = {'changed_cells': int(differs.sum()), 'transitions': dict(kinds),
                                 'roles': ROLES_OF_COLUMN[name],
                                 'finite_old': int(np.isfinite(a).sum()), 'finite_new': int(np.isfinite(b).sum())}
            elif differs.any():
                columns[name] = {'UNREGISTERED_CHANGE_cells': int(differs.sum())}
        arms[arm + '__' + variant] = {'columns': len(old['names'][key]), 'bit_identical_columns':
                                      sum(1 for j in range(len(old['names'][key])) if
                                          np.array_equal(old['matrices'][key][:, j].view(np.uint32),
                                                         new['matrices'][key][:, j].view(np.uint32))),
                                      'mw_or_changed_columns': columns}
    coverage_equal = all(json.dumps(mask_laz_diagnostics(a[1]), sort_keys=True, default=str) ==
                         json.dumps(mask_laz_diagnostics(b[1]), sort_keys=True, default=str)
                         for a, b in zip(old['batches'], new['batches']))
    laz_reports_changed = sum(json.dumps(a[1].get('L_Laz'), sort_keys=True, default=str) !=
                              json.dumps(b[1].get('L_Laz'), sort_keys=True, default=str)
                              for a, b in zip(old['batches'], new['batches']))
    return {'arm_variants': len(old['order']), 'rows': len(panel), 'non_mw_columns_bit_identical': non_mw_identical,
            'arms': arms, 'coverage_identical_except_laz_mw_diagnostics': coverage_equal,
            'coverage_batches_with_laz_mw_diagnostic_changes': laz_reports_changed,
            'derived_date_sidecar_bytes_identical': old['sidecar'] == new['sidecar'],
            'derived_date_sidecar_sha256': hashlib.sha256(new['sidecar']).hexdigest(),
            'changed_cells': changed_cells}


def describe(matrix):
    import numpy as np
    ok = np.isfinite(matrix)
    return {'nonzero': int(np.count_nonzero(matrix[ok])), 'nan': int((~ok).sum()),
            'min': float(matrix[ok].min()) if ok.any() else None, 'max': float(matrix[ok].max()) if ok.any() else None}


def isobatch_descriptives(run, slice_rows):

    recorded = json.loads((ISOBATCH / 'SLICE_TEST.json').read_text())['descriptives']
    sources = {'L14iso': ('L14', 'main'), 'P14iso': ('NPP', 'main'), 'LLaziso': ('L_Laz', 'main'),
               'Mnotice': ('M_notice', 'main')}
    result = {}
    for block, key in sources.items():
        names = run['names'][key]
        for column, stats in recorded[block].items():
            name = column[len(block) + 1:]
            mine = describe(run['matrices'][key][slice_rows, names.index(name)])
            result[column] = {'isobatch': stats, 'spec_4_old_adapter': mine, 'equal': mine == stats}
    return {'columns': len(result), 'equal_columns': sum(v['equal'] for v in result.values()),
            'unequal_columns': sorted(k for k, v in result.items() if not v['equal']), 'detail': result}


def new_descriptives(run, slice_rows):
    out = {}
    for key, columns in MW_COLUMNS.items():
        for name in columns:
            out[key + '__' + name] = describe(run['matrices'][(key, 'main')][slice_rows,
                                                                            run['names'][(key, 'main')].index(name)])
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scratch', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=HERE / 'EQUIVALENCE_RESULTS.json')
    args = parser.parse_args()
    install_audit()
    started = time.monotonic()
    timings = {}
    spec_freeze = json.loads((HERE / 'SPEC_FREEZE.json').read_text())
    require(spec_freeze['spec_sha256'] == sha256(HERE / 'SPEC.md'), 'SPEC.md hash drift')
    import numpy as np
    import pandas as pd
    global PERMIT
    import runtime
    import notice_label_adapter as new
    import features_adapter as fa
    f = runtime.conf_module('features')
    guard = runtime.conf_module('guard')
    PERMIT = guard.ExecutionPermit('SPEC_4_EQUIVALENCE_PROOF', sha256(confirmation / 'FREEZE.json'),
                                   sha256(HERE / 'SPEC_FREEZE.json'), True)
    old = load_archived_adapter()
    require(Path(new.__file__).resolve() == (execution / 'notice_label_adapter.py').resolve(), 'wrong corrected adapter')
    require(fa.normalize_notices is new.normalize_notices and fa.laz_asof is new.laz_asof, 'generator not bound to corrected adapter')
    scratch = args.scratch.resolve() / ('spec_4_equivalence_' + utc_now().replace(':', '-'))
    scratch.mkdir(parents=True, exist_ok=False)


    isobatch_inputs = {Path(item['path']).resolve(): item for item in
                       json.loads((ISOBATCH / 'SPEC_FREEZE.json').read_text())['inputs'] if 'path' in item}
    inputs = {name: identity(path) for name, path in [
        ('nrx_labels', LABELS), ('nrx_scope', SCOPE), ('notice_prefix_keys', PREFIX), ('b1b_development_keys', B1B_KEYS),
        ('rf2_l_block', L_BLOCK), ('f1_train_indices', F1_INDICES['train']), ('f1_test_indices', F1_INDICES['test']),
        ('tfn2_stopwords', STOPWORDS), ('tfn2_vocabulary', STUDY / 'word_features/aligned/selection/C.json'),
        ('isobatch_slice_test', ISOBATCH / 'SLICE_TEST.json'), ('isobatch_spec_freeze', ISOBATCH / 'SPEC_FREEZE.json'),
        ('archived_pre_spec_4_nrx_adapter', ARCHIVED)]}
    slice_input_match = {}
    for name in ('b1b_development_keys', 'rf2_l_block', 'f1_train_indices', 'f1_test_indices', 'nrx_labels'):
        frozen = isobatch_inputs.get(Path(inputs[name]['path']))
        slice_input_match[name] = bool(frozen) and frozen.get('sha256') == inputs[name]['sha256']
    require(all(slice_input_match.values()), 'slice inputs differ from ISOBATCH frozen inputs: ' + repr(slice_input_match))
    require(inputs['tfn2_stopwords']['sha256'] == STOPWORDS_SHA256, 'frozen stopword drift')
    catalog_prefix = json.loads((execution / 'prepared_sources/source_catalog.json').read_text())['notice_prefix']['identity']
    require(catalog_prefix['sha256'] == inputs['notice_prefix_keys']['sha256'], 'prefix keys differ from the source catalog')


    t = time.monotonic()
    parity = loader_parity(fa, f, PERMIT, scratch)
    all_ids, admissible, labels, label_receipt = gated_labels()
    scope_rows, scope_receipt = gated_scope_rows(all_ids, admissible)
    prefix_rows = parquet_columns(PREFIX, ['notice_id', 'available_utc']).to_pylist()
    clock_map = {str(r['notice_id']): r for r in prefix_rows}
    require({str(r['notice_id']) for r in prefix_rows} == set(all_ids), 'prefix/labels ID census mismatch')
    notices = map_host_notices(scope_rows, labels, clock_map, f)
    del scope_rows, prefix_rows, clock_map
    success = sum(n['extraction_status'] == 'SUCCESS' for n in notices)
    stream = {'notices': len(notices), 'success': success, 'terminal_failures': len(notices) - success,
              'latest_available_utc': str(max(f.utc(n['available_utc']) for n in notices)),
              'labels': label_receipt, 'scope': scope_receipt, 'loader_parity': parity}
    require((stream['notices'], stream['success'], stream['terminal_failures']) ==
            (EXPECTED['notices'], EXPECTED['success'], EXPECTED['failures']), 'historical stream counts differ')
    timings['stream_seconds'] = time.monotonic() - t


    t = time.monotonic()
    census = quantity_census(notices, old, new)
    source_relations = fa.load_final3(permit=PERMIT)
    old_records, old_sides = old.normalize_notices(notices, source_relations, permit=PERMIT)
    new_records, new_sides = new.normalize_notices(notices, source_relations, permit=PERMIT)
    records = compare_records(old_records, new_records, old_sides, new_sides)
    summaries = {'old': window_summaries(old_records, old_sides), 'new': window_summaries(new_records, new_sides)}
    anchors, anchor_candidates = anchor_keys(old_records, new_records, old_sides, new_sides, set(f.REGIONS))
    del old_records, new_records, old_sides, new_sides
    timings['census_and_records_seconds'] = time.monotonic() - t


    rows, slice_keys = isobatch_slice(f)
    panel = (pd.concat([slice_keys[KEYS], anchors[KEYS]], ignore_index=True) if len(anchors)
             else slice_keys[KEYS].copy())
    for name in ('issue_time', 'target_time'):
        panel[name] = pd.to_datetime(panel[name], utc=True).astype('datetime64[ns, UTC]')
    panel['horizon'] = panel['horizon'].astype(int)
    sets = ['F1_slice'] * len(slice_keys) + ['LAZ_ANCHOR'] * len(anchors)
    panel = panel.rename(columns={'issue_time': 'origin'})
    panel['p5_synthetic'] = np.arange(len(panel), dtype=np.float32)
    panel = panel[['origin', 'target_time', 'region', 'horizon', 'p5_synthetic']].reset_index(drop=True)
    for name in panel.columns:
        require(name not in DENIED_COLUMNS, 'denied column in panel')
    slice_rows = np.arange(len(slice_keys))

    stops = frozenset(STOPWORDS.read_text().splitlines())
    vocabulary = fa.load_notice_vocabulary(permit=PERMIT)
    aligned = fa.load_corrected_rule(permit=PERMIT)
    runs = {}
    for name, adapter in (('old', old), ('new', new)):
        t = time.monotonic()
        cache = scratch / name
        cache.mkdir()
        runs[name] = run_generator(fa, adapter, panel, notices, cache, source_relations, aligned, vocabulary, stops)
        timings[name + '_generator_seconds'] = time.monotonic() - t
    projections = compare_projections(runs['old'], runs['new'], panel, sets)
    diagnostics = isobatch_descriptives(runs['old'], slice_rows)
    descriptives = {'old': new_descriptives(runs['old'], slice_rows), 'new': new_descriptives(runs['new'], slice_rows)}
    laz_finite_unchanged = all(c['transition'] in ('nan_to_finite',) for c in projections['changed_cells']
                               if c['column'] == 'laz_SizeOfOutage_MW')

    temporary_bytes = sum(p.stat().st_size for p in scratch.rglob('*') if p.is_file())
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    completion = {name: (execution / name).read_bytes() for name in STARTUP}
    require(completion == STARTUP, 'tested adapter source changed during the proof')
    tested_sources = {name: {'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content),
                             'startup_completion_bytes_equal': True} for name, content in STARTUP.items()}
    criteria = {
        'P1_records_and_sidecars_identical_except_mw_fields': bool(
            records['record_non_mw_columns_identical'] and set(records['record_columns_changed']) <= set(RECORD_MW_FIELDS)
            and records['sidecar_key_order_identical'] and records['sidecar_non_mw_fields_identical']),
        'P2_projections_bit_identical_except_specified_mw_columns': projections['non_mw_columns_bit_identical'],
        'P3_coverage_identical_except_laz_mw_diagnostics': projections['coverage_identical_except_laz_mw_diagnostics'],
        'P4_derived_date_sidecar_bytes_identical': projections['derived_date_sidecar_bytes_identical'],
        'P5_no_lost_or_changed_literal': census['totals']['lost_literals'] == 0 and
                                         census['totals']['changed_values_for_literals_accepted_before_and_after'] == 0,
        'limits_peak_rss_and_temporary_bytes': peak_rss <= 1500000000 and temporary_bytes <= 300000000}
    expected_by_code = {
        'record_finite_req_avail_never_change_to_other_finite': records['record_finite_values_changed_to_other_finite'] == 0,
        'old_accepted_losses_subset_of_new_and_rejected_superset': records['old_loss_subset_and_rejected_superset'],
        'laz_size_cells_change_only_from_nan_to_finite': laz_finite_unchanged}
    result = {
        'task': 'quantity_parsing', 'time_utc': utc_now(),
        'state': 'PASS' if all(criteria.values()) else 'FAIL',
        'criteria': criteria, 'expected_by_code_analysis': expected_by_code,
        'spec_sha256': spec_freeze['spec_sha256'], 'spec_freeze': identity(HERE / 'SPEC_FREEZE.json'),
        'inputs': inputs, 'slice_inputs_equal_isobatch_frozen_inputs': slice_input_match,
        'historical_stream': stream, 'quantity_census': census, 'window_summaries': summaries,
        'record_comparison': records,
        'slice': {'rule': 'ISOBATCH SPEC PC18', 'seed': SLICE_SEED, 'rows': len(slice_keys),
                  'strata': rows.groupby(['part', 'final3_l_active']).size().rename('n').reset_index().to_dict('records'),
                  'row_indices_sha256': hashlib.sha256(rows.row.to_numpy(dtype=np.int64).tobytes()).hexdigest(),
                  'latest_issue_time': str(slice_keys.issue_time.max())},
        'laz_anchor_keys': {'rule': 'SPEC section 6 supplementary anchors', 'keys': len(anchors),
                            'changed_failure_windows': len(anchor_candidates),
                            'candidates': anchor_candidates,
                            'anchors': anchors.assign(issue_time=anchors.issue_time.astype(str),
                                                      target_time=anchors.target_time.astype(str)).to_dict('records')},
        'projection_comparison': projections,
        'mw_column_descriptives_on_slice': descriptives,
        'isobatch_descriptive_diagnostic': diagnostics,
        'tested_source_identities': tested_sources,
        'encoder': 'Deterministic SHA-256 digest stand-in for MiniLM; identical for both runs; no model loaded',
        'operator_block': 'one synthetic float32 column (row index) so that NP/NPL/NPP run; P5MIN not read',
        'outcome_price_y_weight_columns_read': [], 'host_state_opened': False, 'production_commands_run': [],
        'fits': 0, 'scores': 0, 'peak_rss_bytes': int(peak_rss), 'temporary_bytes': temporary_bytes,
        'temporary_limit_bytes': 300000000, 'timings_seconds': timings,
        'runtime_seconds': time.monotonic() - started, 'opened_path_log': str(AUDIT_LOG)}
    trash = shutil.which('trash') or ('/usr/bin/trash' if Path('/usr/bin/trash').exists() else None)
    if trash:
        subprocess.run([trash, str(scratch)], check=True)
        result['temporary_files_moved_to_trash'] = not scratch.exists()
    else:
        result['temporary_files_moved_to_trash'] = False
        result['temporary_directory_left_in_scratch'] = str(scratch)
    runtime.atomic_json(args.out, jsonable(result))
    print(json.dumps({'state': result['state'], 'criteria': criteria, 'expected_by_code': expected_by_code,
                      'peak_rss_bytes': result['peak_rss_bytes'], 'temporary_bytes': temporary_bytes,
                      'runtime_seconds': round(result['runtime_seconds'], 1), 'out': str(args.out)}, indent=1))
    if result['state'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
