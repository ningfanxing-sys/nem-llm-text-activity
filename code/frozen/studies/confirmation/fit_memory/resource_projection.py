"""CONFX7 addendum 4 section 4 decision with a structural trend fit (metadata and synthetic benchmark only).

    python a4_projection.py --inputs structural.npz --progress features_progress.log --bench bench_slice.json \
        --calls production_calls.json [--extra-point "21:08 43.9" ...] --out A4_DECISION.json

The CONFX6 notice loop's cost at an origin is: base work + tokenizing its changed prefixes (2 x main + 1 x shift
tokens; json+SHA-256 chunk keying is proportional to the same tokens). `a4_structural_inputs.py` writes the
per-origin rows and tokenized-token work for all 160,383 production origins (notice clocks, per-notice token counts,
B1b issue times, confirmation grid). The progress log (rows written, %) is mapped to origin indices (B1b is sorted by
issue time; the panel is train then confirmation), and the costs are fitted by least squares over its intervals:
- model R: seconds per row + seconds per token;
- model O: seconds per origin + seconds per token.
Both project the remaining time of the running loop and the base work an addendum-4 restart would redo for all rows.
Addendum-4 total = 40 min startup + base work of the full panel + encoding (max seconds per call over dense slices x
all production calls + chunks + checks) + 10 min finish. Switch iff addendum-4 total + overhead < remaining - 60 min
under both models (and every proof passes).
"""
import argparse, datetime as dt, json
import numpy as np
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for k in ('inputs', 'progress', 'bench', 'calls', 'out'): p.add_argument('--' + k, required=True)
    p.add_argument('--extra-point', action='append', default=[]); p.add_argument('--overhead-minutes', type=float, default=50.)
    a = p.parse_args()
    d = np.load(a.inputs); nrows, work, cum = d['nrows'], d['work'].astype(float), d['cum_rows']; total = cum[-1]
    pts = [('2026-10-02 ' + x.split()[0], float(x.split()[1])) for x in a.extra_point]
    for line in Path(a.progress).read_text().splitlines():
        s = line.split()
        if len(s) >= 4 and s[2] == 'rows_written_pct':
            pts.append(('2026-' + s[0] + ' ' + s[1], float(s[3])))
    parse = lambda s: dt.datetime.strptime(s if s.count(':') == 2 else s + ':00', '%Y-%m-%d %H:%M:%S')
    pts = sorted((parse(t), v) for t, v in pts)
    idx = lambda q: int(np.searchsorted(cum, q / 100 * total, side='right'))
    cr, cw, co = np.r_[0, cum], np.r_[0, np.cumsum(work)], np.r_[0, np.arange(1, len(cum) + 1)]
    rows = [(idx(p0), idx(p1), (t1 - t0).total_seconds()) for (t0, p0), (t1, p1) in zip(pts, pts[1:]) if p1 > p0]
    y = np.array([r[2] for r in rows]); i_now = idx(pts[-1][1]); train_end = int(np.searchsorted(cum, 894901, side='left')) + 1
    bench = json.loads(Path(a.bench).read_text()); calls = json.loads(Path(a.calls).read_text())
    spc = max(s['seconds_per_call'] for s in bench['slices'])
    encoding = spc * calls['encode_calls'] + 5522 * 0.25 + (calls['main_changes'] // 500 + calls['shift_changes'] // 500 + 2) * 15.
    models = {}
    for name, base_col in (('R_rows_plus_tokens', cr), ('O_origins_plus_tokens', co)):
        X = np.array([[base_col[i1] - base_col[i0], cw[i1] - cw[i0]] for i0, i1, _ in rows])
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        pred = X @ coef
        remaining = coef[0] * (base_col[-1] - base_col[i_now]) + coef[1] * (cw[-1] - cw[i_now])
        base_full = coef[0] * base_col[-1]
        a4 = 40 * 60 + base_full + encoding + 10 * 60
        models[name] = {'coefficients': [float(c) for c in coef], 'rmse_minutes': float(np.sqrt(np.mean((pred - y) ** 2)) / 60),
                        'observed_vs_fitted_minutes': [[round(o / 60, 1), round(f / 60, 1)] for o, f in zip(y, pred)],
                        'remaining_hours': remaining / 3600,
                        'remaining_train_hours': (coef[0] * (base_col[train_end] - base_col[i_now]) + coef[1] * (cw[train_end] - cw[i_now])) / 3600,
                        'projected_end': (pts[-1][0] + dt.timedelta(seconds=remaining)).isoformat(),
                        'addendum_4_hours': a4 / 3600, 'addendum_4_base_hours': base_full / 3600,
                        'switch': bool(a4 + a.overhead_minutes * 60 < remaining - 3600)}
    out = {'time_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'progress_points': [[t.isoformat(), v] for t, v in pts],
           'current_progress_pct': pts[-1][1], 'current_origin_index': i_now, 'current_main_prefix': int(d['end'][i_now]),
           'addendum_4_encoding_hours': encoding / 3600, 'addendum_4_seconds_per_call_bound': spc, 'production_calls': calls,
           'overhead_hours': a.overhead_minutes / 60, 'models': models,
           'naive_rates_for_comparison': {'latest_interval_pp_per_min': (pts[-1][1] - pts[-2][1]) / ((pts[-1][0] - pts[-2][0]).total_seconds() / 60),
                                         'mean_rate_last_80_min_pp_per_min': None},
           'decision_rule': 'switch iff every proof passes and addendum-4 total + overhead < remaining - 60 min (both models)',
           'switch': all(m['switch'] for m in models.values())}
    last80 = [x for x in pts if (pts[-1][0] - x[0]).total_seconds() <= 80 * 60]
    out['naive_rates_for_comparison']['mean_rate_last_80_min_pp_per_min'] = (last80[-1][1] - last80[0][1]) / max((last80[-1][0] - last80[0][0]).total_seconds() / 60, 1)
    Path(a.out).write_text(json.dumps(out, indent=2) + '\n')
    print(json.dumps({k: {kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items() if kk in ('remaining_hours', 'addendum_4_hours', 'switch', 'projected_end')}
                      for k, v in models.items()}), 'switch', out['switch'])


if __name__ == '__main__':
    main()
