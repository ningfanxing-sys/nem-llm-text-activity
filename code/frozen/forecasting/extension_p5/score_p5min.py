'Score the P5MIN comparisons on matched forecast keys.'
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
AUTO = HERE.parent
PREP = AUTO.parent
sys.path.insert(0, str(PREP / 'analysis'))
import matched_analysis as ma
er = ma.er
SEEDS = (20260919, 20260920, 20260921)
E3 = ('NP', 'NPL', 'NPR', 'NPP')
BASE = ('N', 'R', 'L', 'P')
CONTRASTS = [('NPL', 'NP'), ('NPL', 'NPP'), ('NP', 'N'), ('NPR', 'NP'), ('NPP', 'NP'), ('NPL', 'NPR')]
MARGIN = 0.005


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


def evaluate(rows, arms):
    er.ARMS, er.CONTRASTS = tuple(arms), tuple(CONTRASTS)
    rows['local_day'] = rows.target_time.dt.tz_convert('Australia/Brisbane').dt.strftime('%Y-%m-%d')
    rows['hgroup'] = np.where(rows.horizon.to_numpy() <= 15, 'h05_15', 'h20_30')
    for a in arms:
        rows[f'{a}_ae'] = np.abs(rows[a].to_numpy('float64') - rows.y_true.to_numpy('float64'))
    masks = er.band_masks(rows)
    metric = er.metrics(rows, masks); days = er._day_units(rows, masks); events, _ = er._event_units(rows)
    iv = er.paired_intervals(days, events, rows, masks)
    return metric, iv, masks


def get(iv, c, band='all', est='weighted_row_mae'):
    r = iv[(iv.band == band) & (iv.contrast == c) & (iv.estimand == est)]
    if r.empty:
        return None
    r = r.iloc[0]
    return dict(estimate=float(r.estimate), ci95=[float(r.ci95_low), float(r.ci95_high)])


def pooled(metric, arms):
    m = metric[metric.scope == 'pooled'].set_index('band')
    return {b: {a: float(m.loc[b, a]) for a in arms if a in m.columns} for b in er.BANDS if b in m.index}


def main(run=None, out=None):
    run = Path(run) if run else HERE / 'run'
    freeze = json.loads((HERE / 'E3_FREEZE.json').read_text())
    if freeze['protocol_sha256'] != sha(HERE / 'PROTOCOL_E3.md'):
        raise RuntimeError('E3 protocol changed after freeze')
    out = Path(out) if out else HERE / 'evaluation'
    er.require(not out.exists(), 'E3 already scored')
    seal = json.loads((run / 'seal.json').read_text())
    er.require(seal['state'] == 'E3_CANDIDATES_SEALED' and seal['target_scoring_before_seal'] is False, 'not sealed')

    v2g = json.loads((AUTO / 'run_forecasts' / 'candidate_bank_seal.json').read_text())
    pre = ma.candidates('validate_old')
    e3cols = list(E3) + [f'{a}_s{s}' for a in E3 for s in SEEDS]
    for e3, eg in zip(seal['dev'], v2g['files']):
        er.require(e3['fold'] == eg['fold'], 'fold order differs')
        a = ma._frame(e3['path'], e3['sha256'], e3['rows'], e3cols)
        b = ma._frame(eg['path'], eg['sha256'], eg['rows'], list(BASE))
        er.require(a[ma.KEYS].equals(b[ma.KEYS]), 'dev keys differ')
        pre.candidates[e3['fold']] = a.assign(**{x: b[x].to_numpy() for x in BASE})
    arms = list(BASE) + list(E3)
    er.ARMS = tuple(arms)
    rows = er._truth(pre)
    rows['weight'] = np.where(rows.event_replay_flag.to_numpy() == 1, 1.0, 50.0)
    dev_metric, dev_iv, _ = evaluate(rows, arms)
    dev_seed = {f'{a}_s{s}': float((rows.weight * np.abs(rows[f'{a}_s{s}'] - rows.y_true)).sum() / rows.weight.sum()) for a in E3 for s in SEEDS}

    ws = json.loads((AUTO / 'windows' / 'C' / 'run' / 'candidate_seal.json').read_text())
    er.require(sha(ws['predictions']) == ws['predictions_sha256'], 'window-C base prediction hash mismatch')
    build = json.loads((AUTO / 'windows' / 'C' / 'build_receipt.json').read_text())
    er.require(sha(AUTO / 'windows' / 'C' / 'truth.parquet') == build['truth_sha256'], 'window-C truth hash mismatch')
    base = pd.read_parquet(ws['predictions'], columns=list(er.KEYS) + list(BASE) + ['Z'])
    e3w = pd.read_parquet(seal['window_C']['path'], columns=list(er.KEYS) + e3cols)
    er.require(sha(seal['window_C']['path']) == seal['window_C']['sha256'], 'window E3 predictions changed')
    truth = pd.read_parquet(AUTO / 'windows' / 'C' / 'truth.parquet')
    for f in (base, e3w, truth):
        for c in ('issue_time', 'target_time'):
            f[c] = pd.to_datetime(f[c], utc=True)
    w = e3w.merge(base, on=list(er.KEYS), validate='one_to_one').merge(truth, on=list(er.KEYS), validate='one_to_one')
    er.require(len(w) == len(truth) == seal['window_C']['rows'], 'window rows differ')
    w['fold'] = 'C'; w['q90'] = float(ws['prior_q90'])
    if 'weight' not in w.columns:
        w['weight'] = 1.0
    er.require(bool((w.weight == 1.0).all()), 'window rows must have weight 1')
    win_metric, win_iv, win_masks = evaluate(w, arms + ['Z'])
    win_seed = {f'{a}_s{s}': float(np.abs(w[f'{a}_s{s}'] - w.y_true).mean()) for a in E3 for s in SEEDS}

    d_lnp, d_lpp, c_lnp = get(dev_iv, 'NPL-NP'), get(dev_iv, 'NPL-NPP'), get(win_iv, 'NPL-NP')
    increment = d_lnp['ci95'][1] < 0 and d_lpp['ci95'][1] < 0 and c_lnp['estimate'] < 0
    win_pooled = pooled(win_metric, arms + ['Z'])
    margin = MARGIN * win_pooled['all']['NP']
    b = day_table(w, win_masks['all'], 'NPL', 'NP'); dd = draws_day(b)
    ci90 = [float(np.quantile(dd, .05)), float(np.quantile(dd, .95))]
    result = dict(
        reading='LLM increment on top of P5MIN' if increment else 'no LLM increment on top of P5MIN',
        rule='dev NPL-NP 95% < 0 AND dev NPL-NPP 95% < 0 AND window C NPL-NP estimate < 0',
        primary=dict(dev_NPL_NP=d_lnp, dev_NPL_NPP=d_lpp, window_C_NPL_NP=c_lnp),
        equivalence_window_C=dict(estimate=float(b.d.sum() / b.w.sum()), ci90=ci90, margin=float(margin),
                                  within_margin=bool(ci90[0] > -margin and ci90[1] < margin), np_mae=win_pooled['all']['NP']),
        dev={f'{x}-{y}': get(dev_iv, f'{x}-{y}') for x, y in CONTRASTS},
        window_C={f'{x}-{y}': get(win_iv, f'{x}-{y}') for x, y in CONTRASTS},
        dev_bands={c: {bd: get(dev_iv, c, bd) for bd in ('high_q90', 'y_le_300', 'y_300_to_5000', 'y_gt_5000')} for c in ('NP-N', 'NPL-NP')},
        window_C_bands={c: {bd: get(win_iv, c, bd) for bd in ('high_q90', 'y_le_300', 'y_300_to_5000', 'y_gt_5000')} for c in ('NP-N', 'NPL-NP')},
        event_equal={part: {c: get(iv, c, 'y_gt_5000_event_identified', 'severe_event_equal_mae') for c in ('NP-N', 'NPL-NP')}
                     for part, iv in (('dev', dev_iv), ('window_C', win_iv))},
        pooled_mae=dict(dev=pooled(dev_metric, arms), window_C=win_pooled),
        per_seed_mae=dict(dev=dev_seed, window_C=win_seed),
        per_seed_contrasts={part: {c: {str(sd): seed[f'{x}_s{sd}'] - seed[f'{y}_s{sd}'] for sd in SEEDS}
                                   for c, (x, y) in (('NPL-NP', ('NPL', 'NP')), ('NPL-NPP', ('NPL', 'NPP')))}
                            for part, seed in (('dev', dev_seed), ('window_C', win_seed))},
        p5_coverage=dict(dev=json.loads((run / 'design_binding.json').read_text()).get('p5_coverage_dev_bank'),
                         window_C=seal['window_C'].get('p5_coverage')))
    out.mkdir(parents=True)
    dev_iv.to_csv(out / 'dev_paired_intervals.csv', index=False); win_iv.to_csv(out / 'window_C_paired_intervals.csv', index=False)
    dev_metric.to_csv(out / 'dev_metrics.csv', index=False); win_metric.to_csv(out / 'window_C_metrics.csv', index=False)
    (out / 'E3_RESULT.json').write_text(json.dumps(result, indent=1, default=float))
    print(json.dumps({k: result[k] for k in ('reading', 'primary', 'equivalence_window_C', 'dev', 'window_C', 'dev_bands', 'window_C_bands', 'event_equal')}, indent=1, default=float))


if __name__ == '__main__':
    main()
