'Normalize notice schedules and completed-return records.'
from pathlib import Path
import importlib.util
import re

import pandas as pd

PROJ = Path(__file__).resolve().parents[4]


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


source_relations = module(PROJ / 'studies/notice_records/source_relations/assembler/assemble_source_relations.py', 'extaudit_private_final3')
frozen = source_relations.frozen
adapter = module(PROJ / 'studies/EXT/E4/notice_final3.py', 'extaudit_private_overlap')
scheduled_overlap = module(Path(__file__).with_name('scheduled_overlap.py'), 'extaudit_corrected_overlap')
_source_windows = frozen.source_windows
_parse_nem = frozen.parse_nem
_rule_records = source_relations.rule_records

COLUMNS = source_relations.COLUMNS
features = source_relations.features
resolve_event_states = source_relations.resolve_event_states
shifted = source_relations.shifted
load_population = source_relations.load_population

NUMERIC_DATE = re.compile(r'(?<!\d)\d{1,2}[/-]\d{1,2}[/-](\d+)(?!\d)')
COMPLETED_RETURN = re.compile(
    r'\bThe\s+outage\s+has\s+been\s+completed\s+and\s+[^.!?]{0,220}?'
    r'\breturned\s+to\s+service\s+at\s+(' + frozen.ENDPOINT + r')', re.I)
CANCELLED_OUTAGE = re.compile(
    r'\bThe\s+outage\s+has\s+been\s+cancelled\s+at\s+(' + frozen.ENDPOINT + r')', re.I)


def parse_nem_reject_malformed_year(text, anchor):

    if isinstance(text, str) and any(len(hit[1]) not in (2, 4) for hit in NUMERIC_DATE.finditer(text)):
        return None, None
    return _parse_nem(text, anchor)


def source_windows_reject_partial_year(title, text):

    rows = _source_windows(title, text)
    aligned = []
    for start, end, offset, evidence, basis in rows:
        if offset is not None and evidence and evidence[-1:].isdigit():
            source = str(text)
            source_end = None
            if basis == 'RULE_UNIQUE_FORECAST_INTERVAL':


                right = [m for m in frozen.FORECAST_END_RE.finditer(source)
                         if m.group(1) == end and 0 < m.start() - offset <= 300
                         and evidence.endswith(m.group(0))]
                if len(right) == 1:
                    source_end = right[0].end()
            elif source[offset:offset + len(evidence)] == evidence:
                source_end = offset + len(evidence)
            trailing = None if source_end is None else re.match(r'\d+', source[source_end:])
            if trailing:
                suffix = trailing[0]
                if isinstance(end, str) and evidence.endswith(end):
                    end += suffix
                elif isinstance(start, str) and evidence.endswith(start):
                    start += suffix
                evidence += suffix
        aligned.append((start, end, offset, evidence, basis))
    return aligned


def normalize_explicit_completed_return(records, pop):

    out = records.copy()
    recovery_first = set()
    extra_controls = []
    source = {str(row.notice_id): row for row in pop.itertuples(index=False)}
    for notice, indices in out.groupby('notice_id', sort=False).groups.items():
        row = source[str(notice)]
        recovery_matches = list(COMPLETED_RETURN.finditer(str(row.text)))
        cancel_matches = list(CANCELLED_OUTAGE.finditer(str(row.text)))
        matches = recovery_matches + cancel_matches
        if len(matches) != 1:
            continue
        instant, precision = _parse_nem(matches[0][1], row.anchor_local)
        if instant is None:
            continue
        action = (instant - frozen.NEM_OFFSET).tz_localize('UTC')
        if action > row.available_utc:
            continue
        group = out.loc[indices]
        status = 'RECOVERY' if recovery_matches else 'CANCELLATION'
        if not group.kind.eq('OUTAGE').all():
            continue
        bounded = group.loc[group.temporal_status.eq('BOUNDED')]
        if bounded.cancel.any() or len(bounded[['start_utc', 'end_utc']].drop_duplicates()) != 1:
            continue
        other = group.loc[~group.temporal_status.eq('BOUNDED')]
        ordinary_action = other.window_derivation.eq('RULE_EVENT_AT_VERB') & other.start_utc.eq(action) & other.end_utc.isna()
        closing_action = other.window_derivation.eq('RULE_EXPLICIT_CLOSING_TIME') & other.cancel & other.action_effective_utc.eq(action) & other.end_utc.isna()
        if not (ordinary_action | closing_action).all():
            continue
        if status == 'RECOVERY' and other.empty:
            continue
        known_actions = group.action_effective_utc.dropna()
        if len(known_actions) and not known_actions.eq(action).all():
            continue
        if status == 'RECOVERY' and not bounded.start_utc.le(action).all():
            continue
        out.loc[bounded.index, 'feature_eligible'] = False
        out.loc[bounded.index, 'admission_reason'] = 'EXPLICIT_CLOSED_OUTAGE_HISTORICAL_DIAGNOSTIC'
        out.loc[other.index, 'version_status'] = status
        out.loc[other.index, 'cancel'] = True
        out.loc[other.index, 'action_effective_utc'] = action
        out.loc[other.index, 'action_time_reason'] = 'EXPLICIT_SINGLE_OUTAGE_CLOSING_ACTION'
        meta = source_relations.shared_relation(row.text, row.title)
        out.loc[other.index, 'relation_scope'] = source_relations.relation_scope(status, meta)
        recovery_first.update(other.index)
        if other.empty:


            for _, base in bounded.drop_duplicates('region').iterrows():
                control = base.to_dict()
                control.update(version_status=status, cancel=True, start_utc=action, end_utc=pd.NaT,
                               raw_start_text=None, raw_end_text=None, temporal_status='CLOSING_INSTANT_ONLY',
                               feature_eligible=True, admission_reason='REGIONAL_RECORD',
                               action_effective_utc=action, action_evidence=matches[0][0],
                               action_anchor_basis=precision, action_time_reason='EXPLICIT_SINGLE_OUTAGE_CLOSING_ACTION',
                               window_evidence=matches[0][0], window_derivation='RULE_EXPLICIT_CLOSING_TIME',
                               start_anchor_basis='UNKNOWN', end_anchor_basis='UNKNOWN', end_is_open=False,
                               clock_reason_codes='[]', relation_scope=source_relations.relation_scope(status, meta))
                extra_controls.append(control)
    if extra_controls:
        first_extra = len(out)
        out = pd.concat([out, pd.DataFrame(extra_controls, columns=out.columns)], ignore_index=True)
        for field in ['available_utc', 'start_utc', 'end_utc', 'action_effective_utc']:
            out[field] = pd.to_datetime(out[field], utc=True)
        recovery_first.update(range(first_extra, len(out)))


    order = []
    for _, indices in out.groupby('notice_id', sort=False).groups.items():
        order.extend(i for i in indices if i in recovery_first)
        order.extend(i for i in indices if i not in recovery_first)
    return out.loc[order].reset_index(drop=True)


def rule_records(pop, reject_partial_year=True, completed_recovery=True):


    old_windows, old_parse = frozen.source_windows, frozen.parse_nem
    try:
        if reject_partial_year:
            frozen.source_windows = source_windows_reject_partial_year
            frozen.parse_nem = parse_nem_reject_malformed_year
        result = _rule_records(pop)
    finally:
        frozen.source_windows, frozen.parse_nem = old_windows, old_parse
    if completed_recovery:
        result = normalize_explicit_completed_return(result, pop)
    return result


def features_overlap(namespace, keys, records, hours, eligibility_gate=True, prospective_gate=True):


    resolved = namespace.resolve_event_states(records)
    if eligibility_gate:
        eligible = resolved.region.isin(namespace.REGIONS)
        if 'feature_eligible' in resolved:
            eligible &= resolved.feature_eligible.astype(bool)
        resolved = resolved.loc[eligible].copy()
    return scheduled_overlap.features_overlap(namespace, keys, resolved, hours, prospective_gate=prospective_gate)


def load_final3():

    namespace = adapter.load_final3()
    namespace.rule_records = rule_records
    namespace.corrected_features_overlap = features_overlap
    return namespace
