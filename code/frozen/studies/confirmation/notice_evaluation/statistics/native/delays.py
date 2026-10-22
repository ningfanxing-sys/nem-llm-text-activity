'Apply notice availability delays and compare reproduced values.'
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from . import reader as R


DELAYS = (5, 15, 60)

DELTA_RULE = 'FROZEN_DLY8_DELTA_ADDED_TO_AVAILABLE_UTC_UNCHANGED'

@contextmanager
def frozen_batch(M, gate):

    with R.import_path(R.AP/'code'):
        import batch_layers
    previous = M.P.resource_gate
    M.P.resource_gate = gate
    try:
        yield batch_layers
    finally:
        M.P.resource_gate = previous

def specified_delays(records):
    items = [item for item in records['batch']['sealed_inputs']['DLY8'] if item['mode'] == 1]
    R.require(len(items) == 1, 'Exact specified primary DLY8 terminal required')
    receipt = R.read_json(R.checked(items[0]))
    R.require(receipt.get('state') == 'ALL_DLY8_PREDICTIONS_SEALED' and
              receipt.get('delays_minutes') == [5, 15, 60] and receipt.get('models_refitted') == 0,
              'Specified DLY8 scope or terminal drift')
    census = [(item.get('arm'), item.get('delta_minutes')) for item in receipt['predictions']]
    R.require(len(census) == 15 and set(census) == {(arm,d) for arm in R.ARMS for d in DELAYS},
              'Specified DLY8 arm/delay census drift')
    selected = {}
    for delay in (15, 60):
        rows = [i for i in receipt['predictions'] if i['delta_minutes'] == delay]
        for row in rows:
            R.require(row.get('source') == 'notice' and row.get('seed') == 20260919 and
                      row.get('variant') == 'delay'+str(delay) and row.get('rows') == 527040,
                      'Specified delayed prediction scope drift')
            R.checked(row)
        selected[str(delay)] = rows
    return selected, items[0]

def delayed_view(main, specified, extension, delay):

    R.require(delay in (15,60) and extension.get('schema') == 'FORECAST_BINDING_CORRECTED_DELAYS_V1' and
              extension.get('delta_rule') == DELTA_RULE, 'Corrected delay schema/clock drift')
    outputs = extension['predictions'][str(delay)]
    R.require(set(outputs) == set(R.ARMS) and len(specified) == len(R.ARMS), 'Corrected delayed arm census drift')
    refs = {item['arm']:item for item in specified}
    R.require(set(refs) == set(R.ARMS), 'Specified delayed arm census drift')
    selected, substitutions = [], []
    for arm in R.ARMS:
        original, row = refs[arm], outputs[arm]
        R.require(original.get('variant') == 'delay'+str(delay) and original.get('delta_minutes') == delay and
                  original.get('seed') == 20260919 and original.get('source') == 'notice', 'Specified delayed identity scope drift')
        if arm in R.AFFECTED:
            item = row['identity']
            R.require(row.get('mode') == 'CORRECTED_DLY8_D_SUBSTITUTION' and
                      row.get('specified_identity') == original, 'Corrected delayed specified identity drift')
            R.require(item.get('arm') == arm and item.get('source') == 'notice' and item.get('seed') == 20260919 and
                      item.get('variant') == 'delay'+str(delay) and item.get('delta_minutes') == delay and
                      item.get('model_variant') == 'main' and item.get('rows') == 527040 and item.get('window') == 'D',
                      'Corrected delayed arm/seed/delay/coverage drift')
            cov = extension['coverage'][str(delay)][arm]
            R.require(cov.get('rows') == 527040 and cov.get('keys_equal') is True and
                      cov.get('specified_identity') == original and cov.get('corrected_identity') == item and
                      cov.get('mode') == 'EXACT_SPECIFIED_DLY8_D_KEYS', 'Corrected delayed coverage drift')
            substitutions.append(dict(arm=arm, specified=original, aligned=item))
        else:
            R.require(row == dict(mode='REUSE_BY_IDENTITY', identity=original), 'Unaffected delayed arm substitution')
            item = original
        R.checked(item)
        selected.append(dict(item, variant='main'))
    specified_view = dict(main, predictions=[dict(refs[arm],variant='main') for arm in R.ARMS])
    return specified_view, dict(main,predictions=selected), substitutions

def verify_delay_rows(M, main_view, corrected_view, extension, delay, gate):

    import pandas as pd
    with R.forecast_binding_verifier() as ps:
        receipt = R.read_json(R.checked(extension['parity']))
        for arm in R.AFFECTED:
            gate()
            a = next(i for i in main_view['predictions'] if i['arm'] == arm)
            b = next(i for i in corrected_view['predictions'] if i['arm'] == arm)
            original = pd.read_parquet(R.checked(a)); aligned = pd.read_parquet(R.checked(b))
            expected = receipt['arms'][str(delay)][arm]


            result = R.substitute_rows(M.native, original, aligned, arm, aligned[R.KEYS+['target_day']])
            R.require(all(result[col].dtype == aligned[col].dtype and
                          result[col].to_numpy().tobytes() == aligned[col].to_numpy().tobytes()
                          for col in R.VALUES), 'Corrected delayed full-D row replacement drift')
            full = ps.parity(original, original)
            R.require(full == expected['specified_full_predictions'], 'Specified delayed prediction receipt drift')
            R.require(ps.key_identity(aligned) == expected['full_grid_keys'], 'Corrected delayed full key identity drift')
    return dict(state='PASS', delay_minutes=delay, support='AF8_PER_DELAY_RETAINED_FEATURE_SUPPORT')

def parity_family(M, replay, main, predictions, key):

    bundle = replay.family(M.primary_tests, M.sc, 'notice', R.PAIRS, main, predictions, key)
    bundle['family_m'] = 3
    R.require(bundle.get('frozen_parity') == 'PASS', 'Delayed dense/prefix parity unavailable')
    prefix = M.P.compute_bundle(M.primary_tests, M.P.ChunkedScoring(M.sc,2000,512),bundle)
    dense = M.BS.family_score(M.native,M.sc,None,'notice',R.PAIRS,main,predictions,2000,M.primary_tests)
    M.L.a2_parity(prefix,dense,key+'/complete-prefix')
    for a,b in zip(prefix['reports'],dense['reports']):
        R.require(all(a[field] == b[field] for field in ('decision','hln_decision','hac7_decision')),
                  'Delayed frozen class parity failed')

    import numpy as np
    for block in (1,7):
        exact = M.sc.block_picks(len(bundle['days']),block)
        parts = []
        for start,chunk in M.P.PickPlan(len(bundle['days']),block,100000,days=bundle['days'],chunk=512).chunks():
            parts.append(chunk[:min(len(chunk),2000-start)])
            if start+len(chunk) >= 2000: break
        R.require(np.concatenate(parts).tobytes() == np.asarray(exact).tobytes(), 'Delayed bootstrap seed/prefix drift')
    return bundle, dict(state='PASS', dense_B2000=True, prefix_B2000=True, exact_pick_prefix=True)

def current_family(M, bundle, gate):
    M.G.require_before_large([bundle])
    return M.P.compute_bundle(M.primary_tests,M.P.ChunkedScoring(M.sc,100000,512,gate),bundle)

def specified_current_parity(M, family, saved, delay):
    R.require(family.get('state') == 'COMPUTED' and saved.get('state') == 'COMPUTED' and
              len(family['reports']) == len(saved['reports']) == 3, 'Specified delayed reading unavailable')
    M.L.a2_parity(family,saved,'specified/delay'+str(delay)+'/B100000')
    R.require(all(all(a[field] == b[field] for field in ('arm','reference','decision','hln_decision','hac7_decision'))
                  for a,b in zip(family['reports'],saved['reports'])), 'Specified delayed class/family drift')

def specified_main_current_parity(M, family, saved_task):
    seed_rows = (family.get('three_seed') or {}).get('reports',[])
    R.require(len(family['reports']) == len(saved_task['contrasts']) == 3, 'Specified main contrast census drift')
    for i,(row,saved) in enumerate(zip(family['reports'],saved_task['contrasts'])):
        checks,_,_ = M.P.six_checks(M.primary_tests,M.sensitivity_tests,row,seed_rows[i] if seed_rows else None)
        R.require((row['arm'],row['reference']) == (saved['arm'],saved['reference']) and
                  M.P.CLASS[row['decision']] == saved['class'] and checks == saved['checks'] and
                  M.P.interval_strings(row['interval_family_one_day']) == saved['family_one_day'] and
                  M.P.interval_strings(row['interval_family_seven_day']) == saved['family_seven_day'] and
                  M.P.decimal(row.get('effect_percent_reference_mae')) == saved['effect_percent'] and
                  M.P.decimal(row.get('holm_p'),12) == saved['holm_p'], 'Specified main B100000 reading parity failed')

def uncomputed_family(state, reason, disposition=None):

    return dict(state=state,reason=reason,disposition=disposition,family_m=3,three_seed=None,
                reports=[dict(arm=arm,reference=ref,state=state,reason=reason) for arm,ref in R.PAIRS])

def compute_delays(M, main, specified, aligned, saved_delays, gate, main_reference=None):

    families, proofs = {}, {}
    with frozen_batch(M,gate) as replay:
        for delay in DELAYS:
            bundle,proof = parity_family(M,replay,main,specified[str(delay)]['predictions'],'notice/specified_'+str(delay))
            family = current_family(M,bundle,gate)
            if delay == 5 and main_reference is not None:
                specified_main_current_parity(M,family,main_reference)
            elif delay != 5:
                specified_current_parity(M,family,saved_delays[str(delay)],delay)
            families['specified/'+str(delay)] = family
            proofs['specified/'+str(delay)] = proof
        for delay in DELAYS:
            try:
                bundle,proof = parity_family(M,replay,main,aligned[str(delay)]['predictions'],'notice/corrected_'+str(delay))
                R.require(not bundle.get('mean_prediction_losses'), 'Corrected seed checks cannot be inherited')
                families['aligned/'+str(delay)] = current_family(M,bundle,gate)
            except (R.Refusal,M.P.Refusal,ValueError,KeyError,TypeError) as exc:
                families['aligned/'+str(delay)] = uncomputed_family('DEVIATION','SCORING_PARITY_FAILURE')
                proof = dict(state='DEVIATION',reason='SCORING_PARITY_FAILURE',explanation=str(exc),numeric_suppressed=True)
            proofs['aligned/'+str(delay)] = proof
    return families, proofs
