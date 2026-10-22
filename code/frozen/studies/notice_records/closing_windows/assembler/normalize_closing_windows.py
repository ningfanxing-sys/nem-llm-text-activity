'Normalize closing-window starts while retaining the frozen feature functions.'
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

FROZEN_PATH = Path(__file__).resolve().parents[2] / 'event_assembly' / 'assemble_event_features.py'
_spec = importlib.util.spec_from_file_location('_final2_frozen_assembler', FROZEN_PATH)
frozen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(frozen)

COLUMNS = frozen.COLUMNS
resolve_event_states = frozen.resolve_event_states
features = frozen.features
shifted = frozen.shifted


def closure_start_mask(records: pd.DataFrame) -> pd.Series:
    'Select closing records whose action time supplies the window start.'
    return (records['cancel'].eq(True) & records['start_utc'].isna()
            & records['end_utc'].isna() & records['action_effective_utc'].notna())


def normalize_closure_start(records: pd.DataFrame) -> pd.DataFrame:
    out = records.copy()
    mask = closure_start_mask(out)
    if mask.any():
        if not isinstance(out['start_utc'].dtype, pd.DatetimeTZDtype):
            out['start_utc'] = pd.to_datetime(out['start_utc'], utc=True)
        out.loc[mask, 'start_utc'] = out.loc[mask, 'action_effective_utc']
    return out


def rule_records(pop: pd.DataFrame) -> pd.DataFrame:
    return normalize_closure_start(frozen.rule_records(pop))


def llm_records(pop: pd.DataFrame, labels=None):
    records, joined = frozen.llm_records(pop, labels)
    return normalize_closure_start(records), joined


def __getattr__(name):
    return getattr(frozen, name)
