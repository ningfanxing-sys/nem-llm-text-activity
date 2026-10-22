'Apply common source relations to rule-parser and extracted-label records.'
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
FINAL2_PATH = HERE.parent.parent / 'closing_windows' / 'assembler' / 'normalize_closing_windows.py'
_spec = importlib.util.spec_from_file_location('_final3_parent', FINAL2_PATH)
parent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(parent)
frozen = parent.frozen
v2 = frozen.v2
FROZEN_PATH = parent.FROZEN_PATH

COLUMNS = frozen.COLUMNS
load_population = frozen.load_population
LABELS = frozen.LABELS
features = frozen.features
resolve_event_states = frozen.resolve_event_states
shifted = frozen.shifted
closure_start_mask = parent.closure_start_mask
normalize_closure_start = parent.normalize_closure_start


def shared_relation(text: str, title: str) -> dict:
    'Read common notice references and region metadata for both representations.'
    body = str(text)
    lor = re.search(r'\bLOR\s*([123])\b', body, re.I)
    return dict(
        related_notice_ids=v2._references(body),
        title_key=v2._title_key(title),
        source_body_regions=v2._body_event_regions(body),
        source_lor_level=lor.group(1) if lor else '',
        partial_scope=bool(v2.PARTIAL_SCOPE.search(body)),
        region_release=bool(v2.REGION_RELEASE.search(body)),
        constraint_ids=tuple(sorted({m.group(0).upper() for m in frozen.CONSTRAINT_ID.finditer(body)})),
        negative_state=bool(frozen.NEGATIVE.search(body)),
    )


def relation_scope(status: str, meta: dict) -> str:
    refs = meta['related_notice_ids']
    if status in ('CANCELLATION', 'RECOVERY', 'UPDATE') and refs and meta['partial_scope']:
        return 'NOTICE_PARTIAL'
    if status in ('CANCELLATION', 'RECOVERY') and not refs and meta['region_release']:
        return 'REGION_ALL'
    return 'EVENT'


def _relations(pop: pd.DataFrame) -> dict:
    if pop.notice_id.astype(str).duplicated().any():
        raise ValueError('Duplicate source notice')
    return {str(r.notice_id): shared_relation(r.text, r.title) for r in pop.itertuples(index=False)}


def _apply_shared(records: pd.DataFrame, relation: dict) -> pd.DataFrame:
    out = records.copy()
    for notice_id, positions in out.groupby('notice_id', sort=False).groups.items():
        meta = relation[str(notice_id)]
        for pos in positions:
            for field in ('related_notice_ids', 'title_key', 'source_body_regions',
                          'source_lor_level', 'constraint_ids', 'negative_state'):
                out.at[pos, field] = meta[field]
            out.at[pos, 'relation_scope'] = relation_scope(out.at[pos, 'version_status'], meta)
    return out


def rule_records(pop: pd.DataFrame) -> pd.DataFrame:
    relation = _relations(pop)
    return _apply_shared(parent.rule_records(pop), relation)


def llm_records(pop: pd.DataFrame, labels=None):


    relation = _relations(pop)
    records, joined = parent.llm_records(pop, labels)
    return _apply_shared(records, relation), joined
