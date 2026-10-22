import json, sys
import numpy as np, pandas as pd
sys.path.insert(0, 'runtime/structural_checks/execution')
import runtime; runtime.PROJ = __import__('pathlib').Path('.')
import notice_label_adapter as nrx
from transformers import AutoTokenizer
from pathlib import Path
f = runtime.conf_module('features'); guard = runtime.conf_module('guard')
permit = guard.ExecutionPermit('SYNTHETIC_ONLY', 'a' * 64, 'b' * 64, True)
cat = json.load(open('studies/confirmation/execution/prepared_sources/source_catalog.json'))
rows = pd.read_parquet(cat['notice_prefix']['path'], columns=['notice_id', 'available_utc']).to_dict('records')
notices = nrx.load_host_notices(runtime.PROJ / 'studies/notice_extraction/results_1_3', permit=permit, prefix_clock_rows=rows)
lock = json.load(open('studies/confirmation/ENCODER_LOCK.json'))
tok = AutoTokenizer.from_pretrained(Path('.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/snapshots') / lock['revision'], local_files_only=True, use_fast=True)
lens = np.array([len(tok.encode(f.chen_notice_text([n], permit=permit), add_special_tokens=False, truncation=False)) for n in notices])
T = np.r_[0, np.cumsum(lens)]
clocks = np.array([pd.Timestamp(f.utc(n['available_utc'])).value for n in notices])
meta = pd.read_parquet('studies/B1b/development_metadata.parquet', columns=['issue_time'])['issue_time']
it = pd.to_datetime(meta, utc=True)
print('B1b issue_time sorted:', bool(it.is_monotonic_increasing))
counts = it.value_counts().sort_index()
import panels_adapter as Pn
ev = pd.concat([Pn.notice_keys(d.strftime('%Y-%m-%d'), (d + pd.Timedelta(days=1)).strftime('%Y-%m-%d'))['origin'] for d in pd.date_range('2026-08-01', '2026-09-30', freq='D')])
evc = pd.to_datetime(ev, utc=True).value_counts().sort_index()
origins = pd.DatetimeIndex(list(counts.index) + list(evc.index)); nrows = np.r_[counts.to_numpy(), evc.to_numpy()]
order = np.argsort(origins.asi8, kind='stable'); origins = origins[order]; nrows = nrows[order]
end = np.searchsorted(clocks, origins.asi8, side='right'); shift = np.searchsorted(clocks, origins.asi8 - 28 * 86400 * 10**9, side='right')
mch = np.r_[1, np.diff(end) != 0]; sch = np.r_[1, np.diff(shift) != 0]
work = mch * 2 * T[end] + sch * T[shift]
cum_rows = np.cumsum(nrows); total = cum_rows[-1]
np.savez('runtime/structural_checks/structural.npz', nrows=nrows, work=work, cum_rows=cum_rows, end=end, shift=shift)
print(json.dumps({'total_rows': int(total), 'origins': len(origins), 'total_token_work': int(work.sum()),
                  'eval_token_work': int(work[len(counts):].sum()), 'train_rows': int(counts.sum())}))
