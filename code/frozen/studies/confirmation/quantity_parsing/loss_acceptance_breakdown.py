"""Post-proof descriptive decomposition (not pre-registered): why recovered LOSS
literals are or are not accepted under the unchanged binding/asset rules.

Historical periods only, labels only (the gated loader of verify_mw_equivalence).
It explains a census count; it changes no rule and reads no outcome.

    python -B loss_acceptance_breakdown.py
"""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True

import json
import math
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import verify_mw_equivalence as V  # noqa: E402


def main():
    V.install_audit()
    import runtime
    import nrx_adapter as new
    f = runtime.conf_module('features')
    old = V.load_archived_adapter()
    all_ids, admissible, labels, _ = V.gated_labels()
    rows, _ = V.gated_scope_rows(all_ids, admissible)
    prefix = V.parquet_columns(V.PREFIX, ['notice_id', 'available_utc']).to_pylist()
    notices = V.map_host_notices(rows, labels, {str(r['notice_id']): r for r in prefix}, f)
    reasons = Counter()
    for n in notices:
        label = n['nrx_label']
        if not label or n['extraction_status'] != 'SUCCESS':
            continue
        windows = {str(w['window_id']): w for w in label.get('impact_windows', [])}
        for q in label.get('quantities', []):
            if q.get('role') != 'LOSS' or q.get('unit') != 'MW':
                continue
            if not (q.get('binding_status') == 'BOUND' and q.get('binding_reason') == 'BOUND_EXPLICIT_SOURCE_SCOPE'):
                continue
            text = q.get('value_text', '')
            if math.isfinite(old.scalar(text, nonnegative=True)) or not math.isfinite(new.scalar(text, nonnegative=True, unit='MW')):
                continue
            window = windows.get(str(q.get('window_id')))
            window_asset = f.value(window['asset_id']) if window else 'NO_WINDOW'
            event_class = f.value(window['event_class']) if window else 'NO_WINDOW'
            reason = ('accepted' if window_asset != 'UNKNOWN' and f.value(q.get('asset_id')) == window_asset else
                      'window_asset_UNKNOWN' if window_asset == 'UNKNOWN' else 'quantity_asset_differs_from_window')
            reasons[(reason, event_class)] += 1
    result = {'task': 'CONFX4', 'state': 'DESCRIPTIVE', 'pre_registered': False,
              'scope': 'Bound LOSS quantities with unit MW recovered by the corrected parser, historical periods only',
              'rule': 'unchanged _bound_quantities LOSS acceptance: bound, unit MW, finite nonnegative, window asset '
                      'known and equal to the quantity asset',
              'recovered_loss_literals': sum(reasons.values()),
              'by_reason_and_window_event_class': [{'reason': r, 'window_event_class': c, 'n': k}
                                                   for (r, c), k in sorted(reasons.items())],
              'outcome_price_y_columns_read': [], 'host_state_opened': False}
    totals = Counter()
    for (reason, _), count in reasons.items():
        totals[reason] += count
    result['by_reason'] = dict(sorted(totals.items()))
    runtime.atomic_json(HERE / 'LOSS_ACCEPTANCE_BREAKDOWN.json', result)
    print(json.dumps({k: result[k] for k in ('recovered_loss_literals', 'by_reason', 'by_reason_and_window_event_class')}))


if __name__ == '__main__':
    main()
