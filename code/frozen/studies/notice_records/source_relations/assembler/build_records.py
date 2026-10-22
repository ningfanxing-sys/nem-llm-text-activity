'Build notice records with shared source relations and check every field.'
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import resource
import sys

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
sys.dont_write_bytecode = True

import pandas as pd
import numpy as np
import assemble_source_relations as m

OUT = Path(__file__).resolve().parents[1]
FINAL2 = OUT.parent / 'closing_windows'
MAX_RSS = 2 * 1024**3
SCHEMA_FIELDS = ('region', 'kind', 'version_status', 'start_utc', 'end_utc', 'req_mw',
                 'avail_mw', 'quantity_status', 'cancel', 'temporal_status',
                 'feature_eligible', 'action_effective_utc', 'prospective_action',
                 'source_category', 'admission_reason', 'raw_region', 'normalized_region',
                 'region_derivation', 'region_evidence', 'directional_links_json',
                 'raw_start_text', 'raw_end_text', 'end_is_open', 'window_derivation',
                 'window_evidence', 'start_anchor_basis', 'end_anchor_basis',
                 'clock_reason_codes', 'action_time_reason', 'action_evidence',
                 'action_anchor_basis', 'raw_m331_windows_json',
                 'raw_m331_quantities_json')
RELATION_FIELDS = ('related_notice_ids', 'title_key', 'source_body_regions',
                   'source_lor_level', 'constraint_ids', 'negative_state', 'relation_scope')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda: f.read(1 << 20), b''):
            h.update(part)
    return h.hexdigest()


def same_values(a, b):
    def norm(value):
        if isinstance(value, (tuple, list, np.ndarray)):
            return tuple(value)
        return value
    aa = a.map(norm) if a.dtype == object else a
    bb = b.map(norm) if b.dtype == object else b
    return aa.eq(bb).fillna(False) | (aa.isna() & bb.isna())


def check_rss():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if value >= MAX_RSS:
        raise MemoryError(f'peak RSS {value} >= {MAX_RSS}')
    return value


def main():
    spec = json.loads((OUT / 'SPEC_FREEZE.json').read_text())
    assert spec['spec_sha256'] == sha(OUT / 'SPEC.md')
    parent = json.loads((FINAL2 / 'FREEZE.json').read_text())
    assert parent['state'] == 'FINAL2_FEATURE_INVARIANT_RECORDS_FROZEN_BEFORE_PACKAGE'
    for arm in 'RLP':
        p = FINAL2 / 'records' / f'{arm}.parquet'
        assert sha(p) == parent['files'][str(p)]

    pop = m.load_population()
    labels = pd.read_parquet(m.LABELS, columns=['notice_id', 'notice_type',
        'impact_windows_json', 'lifecycle', 'quantities_json', 'evidence_spans_json',
        'propagation_paths_json'])
    labels['notice_id'] = labels.notice_id.astype(str)
    r = m.rule_records(pop)
    l, joined = m.llm_records(pop, labels)
    p = m.shifted(l, 28)
    assert joined == len(pop)
    pd.testing.assert_frame_equal(p, m.shifted(l, 28))
    frames = {'R': r, 'L': l, 'P': p}
    del pop, labels
    check_rss()


    rmeta = r.groupby('notice_id', sort=False).first()
    lmeta = l.groupby('notice_id', sort=False).first()
    for notice_id in rmeta.index.intersection(lmeta.index):
        for field in RELATION_FIELDS[:-1]:
            if rmeta.at[notice_id, field] != lmeta.at[notice_id, field]:
                raise AssertionError(f'arm-asymmetric shared relation {notice_id} {field}')

    (OUT / 'records').mkdir(exist_ok=True)
    changes = []
    result = {'state': 'PASS', 'final2_freeze_sha256': sha(FINAL2 / 'FREEZE.json'),
              'population_notices': len(rmeta.index.union(lmeta.index)),
              'source_relation_same_when_both_have_rows': True,
              'P_is_L_shifted_28_days': True, 'arms': {}}
    for arm, frame in frames.items():
        old = pd.read_parquet(FINAL2 / 'records' / f'{arm}.parquet')
        if len(old) != len(frame) or list(old.columns) != list(frame.columns):
            raise AssertionError(f'{arm} row count or column order changed')
        fields = {}
        for field in old.columns:
            flags = same_values(old[field], frame[field])
            count = int((~flags).sum())
            if count:
                fields[field] = count
                changes.append(dict(arm=arm, field=field, changed_rows=count,
                                    first_notice_id=str(frame.loc[~flags, 'notice_id'].iloc[0])))
                if arm in 'LP' and field in SCHEMA_FIELDS:
                    raise AssertionError(f'{arm} schema content changed: {field} ({count})')
                if arm == 'R' and field not in RELATION_FIELDS:
                    raise AssertionError(f'R changed outside shared relation metadata: {field}')
        target = OUT / 'records' / f'{arm}.parquet'
        frame.to_parquet(target, index=False)
        result['arms'][arm] = {'records': len(frame), 'notices': int(frame.notice_id.nunique()),
                              'changed_fields': fields, 'record_sha256': sha(target),
                              'parent_record_sha256': sha(FINAL2 / 'records' / f'{arm}.parquet')}
        del old
        check_rss()
    with (OUT / 'RECORD_DIFFERENCES.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['arm', 'field', 'changed_rows', 'first_notice_id'])
        writer.writeheader(); writer.writerows(changes)
    result['peak_rss_bytes'] = check_rss()
    (OUT / 'RECORD_COMPARISON.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'state': result['state'], 'changes': {a: v['changed_fields']
        for a, v in result['arms'].items()}, 'peak_rss_bytes': result['peak_rss_bytes']}))


if __name__ == '__main__':
    main()
