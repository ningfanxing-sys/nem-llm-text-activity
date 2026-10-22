"""Post-seal scorer: exact A2 functions, separate secondary families, no CONF score access."""
from pathlib import Path
import numpy as np
import pandas as pd
from common import CONF, KEYS, SEED, identity, sha, checked, read_json, write_json, require, module
import sealing
import batch_export

SENTENCES = {
    'L1': 'Under the absolute-error (median) training objective, {arm} {verb} the article-activity reference trained with the same objective ({effect}% of the reference error, per-contrast 95% interval [{lo}, {hi}]%, Holm-adjusted {p} within this secondary family); {robustness}.',
    'PD': 'With AEMO pre-dispatch demand and semi-scheduled generation forecasts as additional inputs, {arm} {verb} the article-activity reference with the same inputs ({effect}% of the reference error, per-contrast 95% interval [{lo}, {hi}]%, Holm-adjusted {p} within this secondary family); {robustness}.',
}
VERBS = {'CONDITIONAL_IMPROVEMENT': 'improved on', 'CONDITIONAL_DETERIORATION': 'was reliably worse than',
         'NO_RELIABLE_INCREMENT_DETECTED': 'showed no reliable increment over'}
FAMILIES = {'L1': (('L_count_L1', 'M_L1'), ('L_chen_L1', 'M_L1')),
            'PD': (('L_count_PD', 'M_PD'), ('L_chen_PD', 'M_PD'))}
DESCRIPTIVE = (('N_L1', 'N'), ('N_PD', 'N'), ('N_L1', 'LEAR'), ('N_PD', 'LEAR'),
               ('L_count_noT', 'M'), ('L_count', 'L_count_noT'))

def helpers():
    a2 = module(CONF / 'A2/code/a2_postscore.py', 'a2batch_original_a2_postscore')
    return a2, a2.load_frozen_scoring(CONF)

def inference(losses, days, a2, sc, dispositions):
    families = {}
    for name, pairs in FAMILIES.items():
        stage = 'A2B-1' if name == 'L1' else 'A2B-2'
        d = dispositions[stage]
        if d['state'] != 'COMPLETE':
            family_name = 'absolute-error objective' if name == 'L1' else 'pre-dispatch input'
            reason = d.get('reason', d['state'])
            families[name] = dict(state=d['state'], reason=reason, family_m=2, reports=[],
                                  sentence=f'The {family_name} secondary family was not run ({reason}).')
            continue
        require(all(x in losses for pair in pairs for x in pair), 'Completed family missing sealed arm')
        family = a2.family_inference(sc, losses, pairs, days)
        family['state'] = 'COMPUTED_SECONDARY'
        for r in family['reports']:
            one = r['bootstrap']['1']; seven = r['bootstrap']['7']
            robustness = a2.robustness_label(r['decision'], one.get('interval95_percent'), seven.get('interval95_percent'),
                r['hln_decision'], r['hac7_decision'], 'SEED_ROBUSTNESS_NOT_EVALUABLE', 'not available (single seed by design)',
                seven.get('state'))
            require(robustness['label'] != 'ROBUST', 'Single-seed batch cannot be fully checked')
            robustness['sentence'] = (robustness['sentence'] or '').replace('extra-seed forecasts were not available', 'single seed by design')
            r['robustness'] = robustness
            r['three_seed_check'] = 'not available (single seed by design)'
            ci = one.get('interval95_percent')
            dplaces = a2.percent_decimals(None if ci is None else ci[1] - ci[0])
            lo, hi = a2.fmt_interval(ci, dplaces)
            r['sentence'] = None if r['decision'] not in VERBS else SENTENCES[name].format(
                arm=r['arm'], verb=VERBS[r['decision']], effect=a2.fmt_effect(r.get('effect_percent_reference_mae'), dplaces),
                lo=lo, hi=hi, p=a2.display_p(r['holm_p']), robustness=robustness['sentence'])
        families[name] = family
    descriptive = []
    picks = a2.complete_picks(sc, len(days))
    for arm, ref in DESCRIPTIVE:
        if arm not in losses or ref not in losses:
            descriptive.append(dict(arm=arm, reference=ref, state='NOT_EVALUABLE_INPUT_OR_WHOLE_STAGE_UNAVAILABLE'))
            continue
        r = a2.contrast_stats(sc, losses[arm], losses[ref], picks, 1)
        r.update(arm=arm, reference=ref, state='COMPUTED_DESCRIPTIVE_UNADJUSTED',
                 descriptive_class=a2.decision_class(r['mean_difference'], r['p_two_sided']))
        descriptive.append(r)
    return families, descriptive

def prediction_losses(seal, truth, days, a2, validation=False):
    losses = {}
    for item in seal['predictions']:
        if item.get('source') not in ('news', 'lear') or item.get('seed') != SEED:
            continue
        if item.get('variant', 'main') != ('2025_fixed_validation' if validation else 'main'):
            continue
        f = sealing.normalize(pd.read_parquet(checked(item)))
        require(f[KEYS + ['target_day']].equals(truth[KEYS + ['target_day']]), 'Sealed score keys differ: ' + item['arm'])
        require(np.isfinite(f.prediction.to_numpy()).all(), 'Nonfinite sealed score prediction')
        actual_days, loss = a2.daily_abs_loss(truth, f.prediction.to_numpy(dtype='float64'))
        require(actual_days == days, 'Daily loss domain drift')
        require(item['arm'] not in losses, 'Duplicate scored arm')
        losses[item['arm']] = loss
    return losses

def score(state, conf_seal_path, days):
    state = Path(state)
    seal = sealing.verify(state)  # MUST precede every truth read.
    dest = state / 'scored'
    receipt_path = dest / 'SCORE_RECEIPT.json'
    if receipt_path.exists():
        receipt = read_json(receipt_path)
        require(receipt['seal_sha256'] == sha(state / 'SEAL_A2BATCH.json') and receipt['conf_seal_sha256'] == sha(conf_seal_path), 'Score resume seal drift')
        for item in receipt['files']:
            checked(item)
        result = read_json(dest / 'SCORE.json')
        batch_export.export_scored(state, conf_seal_path, result)
        return result
    conf_seal = read_json(conf_seal_path)
    inputs = read_json(state / 'BATCH_INPUT_FREEZE.json')
    require(inputs['conf_seal']['sha256'] == sha(conf_seal_path), 'CONF seal differs from prefit batch input')
    require(conf_seal['state'] == 'ALL_REGISTERED_PREDICTIONS_SEALED' and conf_seal['sealed_before_outcome_scoring'], 'Invalid CONF seal')
    a2, sc = helpers()
    panel = pd.read_parquet(checked(seal['truth_panels']['news']), columns=KEYS + ['target_day', 'y', 'weight'])
    truth = sealing.normalize(panel.loc[panel.target_day.astype(str).isin(days)])
    sealing.grid(truth, days)
    require(np.isfinite(truth.y.to_numpy()).all() and (truth.weight.to_numpy() == 1).all(), 'Finite truth/unit weight gate')
    losses = prediction_losses(seal, truth, days, a2)
    # Only registered sealed reference forecasts; no CONF result/score file.
    references = dict(conf_seal, predictions=[p for p in conf_seal['predictions'] if p.get('arm') in ('N', 'M', 'L_count', 'L_chen', 'LEAR')])
    require(conf_seal['truth_panels']['news']['sha256'] == seal['truth_panels']['news']['sha256'], 'CONF/batch truth identity mismatch')
    losses.update(prediction_losses(references, truth, days, a2))
    dispositions = {d['stage']: d for d in seal['stage_dispositions']}
    families, descriptive = inference(losses, days, a2, sc, dispositions)
    primary = a2.family_inference(sc, losses, (('L_count', 'M'), ('L_chen', 'M')), days)
    primary_by_arm = {r['arm']: r for r in primary['reports']}
    relations = []
    for name, family in families.items():
        for r in family['reports']:
            p_arm = r['arm'].rsplit('_', 1)[0]
            p_cls = primary_by_arm[p_arm]['decision']
            condition = 'under the absolute-error training objective' if name == 'L1' else 'with pre-dispatch forecasts as additional inputs'
            if p_cls == 'CONDITIONAL_IMPROVEMENT' and r['decision'] == 'NO_RELIABLE_INCREMENT_DETECTED':
                relations.append(f'The primary increment of {p_arm} was not detected {condition}; it is stated relative to the registered learner and information set.')
            elif p_cls == 'NO_RELIABLE_INCREMENT_DETECTED' and r['decision'] == 'CONDITIONAL_IMPROVEMENT':
                relations.append('This secondary result does not change the primary reading.')
    by_pair = {(r['arm'], r['reference']): r for r in descriptive}
    def percent(pair):
        return a2.fmt_effect(by_pair[pair].get('effect_percent_reference_mae'), 3)
    descriptions = []
    if all(by_pair[p].get('state') == 'COMPUTED_DESCRIPTIVE_UNADJUSTED' for p in DESCRIPTIVE[:4]):
        descriptions.append('The median-objective numerical reference differed from N by ' + percent(('N_L1', 'N')) +
            '% and from LEAR by ' + percent(('N_L1', 'LEAR')) + '%; the pre-dispatch-augmented reference differed from N by ' +
            percent(('N_PD', 'N')) + '% and from LEAR by ' + percent(('N_PD', 'LEAR')) + '% (descriptive, unadjusted).')
    if all(by_pair[p].get('state') == 'COMPUTED_DESCRIPTIVE_UNADJUSTED' for p in DESCRIPTIVE[4:]):
        # Registered contrast L_count - noT has the opposite sign to removal's change,
        # and a noT denominator. A6 delta is removal's change relative to L_count.
        delta = 100 * (losses['L_count_noT'].mean() - losses['L_count'].mean()) / losses['L_count'].mean() if losses['L_count'].mean() > 0 else None
        descriptions.append('Without the four impact-tier counts, the count representation differed from the article-activity reference by ' +
            percent(('L_count_noT', 'M')) + '% (DM ' + a2.display_p(by_pair[('L_count_noT', 'M')]['p_two_sided']) +
            '); removing the tier counts changed its error by ' + a2.fmt_effect(delta, 3) + '% (descriptive, unadjusted).')
    validation = {}
    validation_days = pd.date_range('2025-01-01', '2025-12-31').strftime('%Y-%m-%d').tolist()
    if any(p['variant'] == '2025_fixed_validation' for p in seal['predictions']):
        vtruth = sealing.normalize(panel.loc[panel.target_day.astype(str).isin(validation_days)])
        sealing.grid(vtruth, validation_days)
        require(np.isfinite(vtruth.y.to_numpy()).all() and (vtruth.weight.to_numpy() == 1).all(), 'Validation truth/weight gate')
        vloss = prediction_losses(seal, vtruth, validation_days, a2, validation=True)
        validation = {a: dict(mae=float(v.mean()), role='REPORT_ONLY_SELECTS_NOTHING') for a, v in vloss.items()}
    result = dict(state='A2BATCH_SECONDARY_SCORE_COMPLETE', families=families, descriptive=descriptive,
                  descriptive_sentences=descriptions, primary_relations=relations, validation_2025=validation,
                  sesoi_and_attribution_not_applied=True, primary_reading_unchanged=True,
                  limitations=['one seed', 'PD operator forecasts augment the information set; N_PD is not independent N',
                               'PD clock and hour aggregation are project choices', 'impact tier remains in L_chen serialisation',
                               'execution follows the CONF chain; all choices frozen before T5'])
    dest.mkdir(parents=True, exist_ok=True)
    write_json(dest / 'SCORE.json', a2.json_safe(result), exclusive=True)
    pd.DataFrame(dict(target_day=days, **losses)).to_csv(dest / 'DAILY_LOSSES.csv', index=False)
    write_json(receipt_path, dict(state=result['state'], seal_sha256=sha(state / 'SEAL_A2BATCH.json'),
        conf_seal_sha256=sha(conf_seal_path), functions=identity(CONF / 'A2/code/a2_postscore.py'),
        files=[identity(dest / name) for name in ('SCORE.json', 'DAILY_LOSSES.csv')]), exclusive=True)
    batch_export.export_scored(state, conf_seal_path, a2.json_safe(result))
    return result
