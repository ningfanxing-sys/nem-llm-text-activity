'Compute relative MAE and Diebold–Mariano tests from daily losses.'
from __future__ import annotations
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE / 'p5min_benchmark'
ARMS = ('N', 'R', 'L', 'P', 'Z', 'P5')
PAIRS = (('L', 'N'), ('L', 'R'), ('L', 'P'), ('R', 'N'), ('N', 'Z'), ('N', 'P5'), ('L', 'P5'), ('Z', 'P5'))


def dm(d):
    d = np.asarray(d, float); T = len(d); mu = d.mean(); x = d - mu
    lag = int(math.floor(4 * (T / 100) ** (2 / 9)))
    s = (x @ x) / T
    for k in range(1, lag + 1):
        s += 2 * (1 - k / (lag + 1)) * (x[k:] @ x[:-k]) / T
    stat = mu / math.sqrt(s / T) if s > 0 else float('nan')
    p = math.erfc(abs(stat) / math.sqrt(2))
    return dict(mean_daily_diff=float(mu), dm_stat=float(stat), p_two_sided=float(p), days=T, nw_lag=lag)


def main():
    out = {}
    for name in ('dev', 'window_C'):
        days = pd.read_csv(SRC / f'{name}_day_units.csv')
        res = {}
        for band, b in days.groupby('band', sort=False):
            b = b[b.weight > 0]
            mae = {a: float(b[f'{a}_sae'].sum() / b.weight.sum()) for a in ARMS}
            res[band] = dict(mae=mae, rMAE_vs_persistence={a: mae[a] / mae['Z'] for a in ARMS},
                             dm={f'{x}-{y}': dm((b[f'{x}_sae'] - b[f'{y}_sae']) / b.weight) for x, y in PAIRS})
        out[name] = res
    (HERE / 'SECONDARY_METRICS.json').write_text(json.dumps(out, indent=1, default=float))
    for name in out:
        a = out[name]['all']
        print(name, 'rMAE', {k: round(v, 4) for k, v in a['rMAE_vs_persistence'].items()})
        print(name, 'DM', {k: (round(v['mean_daily_diff'], 4), round(v['dm_stat'], 2), round(v['p_two_sided'], 4)) for k, v in a['dm'].items()})


if __name__ == '__main__':
    main()
