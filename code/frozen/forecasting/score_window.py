'Score saved window forecasts with paired daily tests and bootstrap intervals.'
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PREP = HERE.parent
EXP = PREP.parent
sys.path.insert(0, str(EXP / 'notice_comparison'))
import evaluate_notice_records as er

FREEZE = PREP / 'prospective' / 'SPECIFICATION_1_FREEZE.json'
ARMS = ('N', 'R', 'L', 'P')
SEEDS = (20260919, 20260920, 20260921)
CONTRASTS = (('L', 'N'), ('L', 'P'), ('R', 'N'), ('L', 'R'), ('P', 'N'), ('N', 'Z'))
MARGIN, ALPHA = 0.005, 0.05


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def day_table(rows, mask, first, second):
    days = rows[['local_day']].drop_duplicates().sort_values('local_day')
    sub = rows.loc[mask]
    agg = sub.assign(w=sub.weight, d=sub.weight * (sub[f'{first}_ae'] - sub[f'{second}_ae'])).groupby('local_day', as_index=False)[['w', 'd']].sum()
    return days.merge(agg, on='local_day', how='left').fillna(0)


def draws_day(block):
    picks = np.random.default_rng(er.BOOT_SEED).integers(0, len(block), size=(er.BOOT_DRAWS, len(block)))
    w, d = block.w.to_numpy(), block.d.to_numpy()
    return d[picks].sum(1) / w[picks].sum(1)


def draws_moving(block, length=7):
    'Draw consecutive-day moving blocks for the sensitivity interval.'
    n = len(block); length = min(length, n); k = int(np.ceil(n / length)); rng = np.random.default_rng(er.BOOT_SEED)
    starts = rng.integers(0, n - length + 1, size=(er.BOOT_DRAWS, k))
    idx = (starts[:, :, None] + np.arange(length)[None, None, :]).reshape(er.BOOT_DRAWS, -1)[:, :n]
    w, d = block.w.to_numpy(), block.d.to_numpy()
    return d[idx].sum(1) / w[idx].sum(1)


def main(name):
    freeze = json.loads(FREEZE.read_text()) if FREEZE.exists() else {}
    if freeze.get('state') != 'SPECIFICATION_1_FROZEN' or name not in freeze.get('windows', []):
        raise RuntimeError(f'window {name} not admitted by a frozen specification')
    wdir = HERE / 'windows' / name
    out = wdir / 'evaluation'
    er.require(not out.exists(), 'window already scored; no rescore')
    seal = json.loads((wdir / 'run' / 'candidate_seal.json').read_text())
    er.require(seal['state'] == f'WINDOW_{name}_CANDIDATES_SEALED' and seal['target_scoring_before_seal'] is False, 'not sealed')
    er.require(sha(seal['predictions']) == seal['predictions_sha256'], 'prediction hash mismatch')
    build = json.loads((wdir / 'build_receipt.json').read_text())
    er.require(sha(wdir / 'truth.parquet') == build['truth_sha256'], 'truth hash mismatch')
    pred = pd.read_parquet(seal['predictions'])
    truth = pd.read_parquet(wdir / 'truth.parquet')                    # Read truth after validating the saved forecasts.
    for f in (pred, truth):
        for c in ('issue_time', 'target_time'):
            f[c] = pd.to_datetime(f[c], utc=True)
    rows = pred.merge(truth, on=er.KEYS, how='inner', validate='one_to_one')
    er.require(len(rows) == len(pred) == len(truth), 'truth/candidate universe mismatch')
    er.require(rows.weight.eq(1).all(), 'window rows must have weight 1')
    per_seed = [f'{a}_s{s}' for a in ARMS for s in SEEDS]
    er.ARMS, er.CONTRASTS = ARMS + ('Z',) + tuple(per_seed), CONTRASTS
    rows['fold'] = name; rows['q90'] = float(seal['prior_q90'])
    rows['local_day'] = rows.target_time.dt.tz_convert('Australia/Brisbane').dt.strftime('%Y-%m-%d')
    rows['hgroup'] = np.where(rows.horizon.to_numpy() <= 15, 'h05_15', 'h20_30')
    for a in er.ARMS:
        rows[f'{a}_ae'] = np.abs(rows[a].to_numpy('float64') - rows.y_true.to_numpy('float64'))
    masks = er.band_masks(rows)
    metric = er.metrics(rows, masks); days = er._day_units(rows, masks)
    events, coverage = er._event_units(rows)
    intervals = er.paired_intervals(days, events, rows, masks)
    pooled = metric[metric.scope == 'pooled'].set_index('band')
    allmask = masks['all']
    b_ln, b_lp = day_table(rows, allmask, 'L', 'N'), day_table(rows, allmask, 'L', 'P')
    est_ln, est_lp = b_ln.d.sum() / b_ln.w.sum(), b_lp.d.sum() / b_lp.w.sum()
    m_n, m_p = MARGIN * pooled.loc['all', 'N'], MARGIN * pooled.loc['all', 'P']
    d_ln, d_lp = draws_day(b_ln), draws_day(b_lp)
    hyp = {
        f'H1_{name}': dict(statement='L_v2 - N within +/-0.5% of N overall MAE (TOST)', estimate=float(est_ln), margin=float(m_n),
                           estimate_pct_of_N=float(100 * est_ln / pooled.loc['all', 'N']),
                           ci90=[float(np.quantile(d_ln, .05)), float(np.quantile(d_ln, .95))],
                           p=float(max((d_ln >= m_n).mean(), (d_ln <= -m_n).mean()))),
        f'H2_{name}': dict(statement='L_v2 not better than P_v2 by more than 0.5% of P overall MAE', estimate=float(est_lp),
                           bound=float(-m_p), estimate_pct_of_P=float(100 * est_lp / pooled.loc['all', 'P']),
                           ci90=[float(np.quantile(d_lp, .05)), float(np.quantile(d_lp, .95))],
                           p=float((d_lp <= -m_p).mean())),
    }
    order = sorted(hyp, key=lambda h: hyp[h]['p']); running, rejected = 0.0, True
    for i, h in enumerate(order):
        running = min(1.0, max(running, (len(order) - i) * hyp[h]['p']))
        rejected = rejected and hyp[h]['p'] <= ALPHA / (len(order) - i)
        hyp[h].update(holm_p=running, supported=bool(rejected))
    sens = {}
    mv_ln, mv_lp = draws_moving(b_ln), draws_moving(b_lp)
    sens['moving_block_7d'] = {'L-N_ci90': [float(np.quantile(mv_ln, .05)), float(np.quantile(mv_ln, .95))],
                               'L-P_ci90': [float(np.quantile(mv_lp, .05)), float(np.quantile(mv_lp, .95))],
                               'H1_p': float(max((mv_ln >= m_n).mean(), (mv_ln <= -m_n).mean())), 'H2_p': float((mv_lp <= -m_p).mean())}
    sens['mean_single_seed_loss'] = {a: float(np.mean([pooled.loc['all', f'{a}_s{s}'] for s in SEEDS])) for a in ARMS}
    sens['ensemble_loss'] = {a: float(pooled.loc['all', a]) for a in ARMS + ('Z',)}
    sens['L-N_by_seed'] = {str(s): float(pooled.loc['all', f'L_s{s}'] - pooled.loc['all', f'N_s{s}']) for s in SEEDS}
    for label, m in (('notice_active', rows.notice_active.to_numpy(bool)), ('notice_inactive', ~rows.notice_active.to_numpy(bool))):
        entry = dict(rows=int(m.sum()))
        for first, second in (('L', 'N'), ('L', 'P'), ('R', 'N')):
            b = day_table(rows, m, first, second); dd = draws_day(b)
            entry[f'{first}-{second}'] = dict(estimate=float(b.d.sum() / b.w.sum()), ci95=[float(np.quantile(dd, .025)), float(np.quantile(dd, .975))])
        sens[label] = entry
    out.mkdir(parents=True)
    metric.to_csv(out / 'metrics.csv', index=False); intervals.to_csv(out / 'paired_intervals.csv', index=False)
    er.event_metrics(rows).to_csv(out / 'event_equal_metrics.csv', index=False)
    result = dict(window=name, rows=len(rows), days=int(rows.local_day.nunique()), event_coverage=coverage, prior_q90=seal['prior_q90'],
                  hypotheses=hyp, family_holm=order, sensitivity=sens,
                  pooled_mae={b: {a: float(pooled.loc[b, a]) for a in ARMS + ('Z',)} for b in er.BANDS})
    (out / 'WINDOW_RESULT.json').write_text(json.dumps(result, indent=1, default=float))
    print(json.dumps(result, indent=1, default=float))
    show = intervals[intervals.estimand.isin(['weighted_row_mae', 'severe_event_equal_mae'])]
    print(show[['band', 'contrast', 'estimand', 'estimate', 'ci95_low', 'ci95_high']].round(4).to_string(index=False))


if __name__ == '__main__':
    main(sys.argv[1])
