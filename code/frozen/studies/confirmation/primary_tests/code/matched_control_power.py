"""A2-P1 (ADDENDUM_A2 section B1): power of the frozen notice test at the notice SESOI 0.5%.

Pre-D planning numbers only: reads A1/results/C1_precision_rows_with_sesoi.csv (analog standard errors computed
by A1 on pre-D windows). Formula as A1 C2b: power = Phi(S / se_D - z_{1-0.05/(2m)}), m = 3; HLN version with
Student t (n_D - 1 = 60 df). Descriptive; changes no rule.
"""
import hashlib, json, sys
from pathlib import Path
import pandas as pd
from scipy.stats import norm, t

A2 = Path(__file__).resolve().parents[1]
SRC = A2.parent / 'A1/results/C1_precision_rows_with_sesoi.csv'
S, M, ALPHA = 0.5, 3, 0.05


def main():
    rows = pd.read_csv(SRC)
    notice = rows.loc[rows['task'].eq('notice')].copy()
    z = norm.ppf(1 - ALPHA / (2 * M)); tq = t.ppf(1 - ALPHA / (2 * M), df=60)
    notice['power_at_0p5'] = norm.cdf(S / notice['se_D_pct'] - z)
    notice['power_at_0p5_hln_t'] = t.cdf(S / notice['se_D_pct'] - tq, df=60)
    notice['family_adjusted_halfwidth_pct'] = z * notice['se_D_pct']
    central = notice.loc[notice['central'].astype(str).eq('True')]
    out = {'analysis': 'A2-P1 power of the frozen notice test at SESOI 0.5% (planning, pre-D analogs only)',
           'source': str(SRC), 'source_sha256': hashlib.sha256(SRC.read_bytes()).hexdigest(),
           'formula': 'Phi(0.5/se_D - z_{1-0.05/6}); HLN: Student t with 60 df', 'z': z, 't60': tq,
           'central_rows': central[['window', 'analog', 'seed', 'se_D_pct', 'power_at_0p5', 'power_at_0p5_hln_t',
                                    'family_adjusted_halfwidth_pct']].to_dict('records'),
           'envelope': {'rows': int(len(notice)), 'power_min': float(notice['power_at_0p5'].min()),
                        'power_max': float(notice['power_at_0p5'].max()),
                        'power_median': float(notice['power_at_0p5'].median()),
                        'family_adjusted_halfwidth_min_pct': float(notice['family_adjusted_halfwidth_pct'].min()),
                        'family_adjusted_halfwidth_max_pct': float(notice['family_adjusted_halfwidth_pct'].max()),
                        'rows_with_power_below_0p8': int((notice['power_at_0p5'] < 0.8).sum())},
           'all_rows': notice[['window', 'analog', 'seed', 'central', 'se_D_pct', 'power_at_0p5', 'power_at_0p5_hln_t',
                               'family_adjusted_halfwidth_pct']].to_dict('records')}
    path = A2 / 'results/A2_P1_power_notice_sesoi.json'
    path.write_text(json.dumps(out, indent=2, default=str) + '\n')
    print(json.dumps({k: out[k] for k in ('central_rows', 'envelope')}, indent=1, default=str))


if __name__ == '__main__':
    sys.exit(main())
