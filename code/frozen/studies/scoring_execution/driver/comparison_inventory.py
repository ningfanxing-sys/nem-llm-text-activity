'Complete the comparison inventory from checked numerical records.'
from copy import deepcopy
from source_bytes import require


def absent(key, pairs, days, row, provenance):
    state = row['state']
    require(not state.startswith(('COMPLETE', 'COMPUTED', 'READY')),
            'Missing computed native family: '+key)
    reason = row.get('reason') or row.get('error') or state
    require(isinstance(reason, str) and bool(reason), 'Missing native disposition reason: '+key)
    effective = ('PENDING' if state.startswith('PENDING') else
                 'DEVIATION' if 'PARITY' in state or state.startswith('DEVIATION') else
                 'NOT_RUN' if state.startswith('NOT_RUN') else 'NOT_EVALUABLE')
    return dict(id=key, task=key.split('/')[0], state=effective, losses={},
                pairs=deepcopy(pairs), family_m=len(pairs), days=list(days),
                reason=reason, native_disposition=state, native_status=effective,
                frozen_parity='NOT_RUN' if effective == 'NOT_RUN' else None,
                disposition_source=deepcopy(provenance))


def complete(P, inputs, bundles, records, evidence):

    census = P.strict_json(P.HERE/'statistics/SLOT_CENSUS.json')
    pairs = {}
    for slot in census['forest']:
        pair = [slot['arm'], slot['reference']]
        ps = pairs.setdefault(slot['family_key'], [])
        if pair not in ps: ps.append(pair)
    full = inputs.score_json('SCORE_REPORT.json')
    report_id = inputs.score_files['SCORE_REPORT.json']
    additions = []
    for key, ps in pairs.items():
        if key in bundles: continue
        task, layer = key.split('/', 1)
        days = bundles[task+'/primary']['days']
        if layer in ('seed_20260920', 'seed_20260921'):
            name = 'primary_seed_robustness_'+task
            rows = [r for r in inputs.seal['stage_dispositions'] if r['stage'] == name]
            require(len(rows) == 1, 'Native extra-seed disposition census: '+task)
            row = rows[0]
            require(row['state'] not in ('COMPLETE', 'COMPLETE_WITH_UNAVAILABLE_CONFIGURATIONS'),
                    'Complete seed stage lacks native seed result: '+key)
            provenance = dict(receipt=records['batch']['CS8']['score_receipt'],
                              effective_stage=deepcopy(row))
        elif layer.startswith('native:'+task+'__SECONDARY__'):
            arm, reference = layer.split('__')[2:]
            rows = [r for r in full[task]['secondary']
                    if (r['arm'], r['reference']) == (arm, reference)]
            require(len(rows) == 1, 'Native secondary disposition census: '+key)
            row = rows[0]
            provenance = dict(receipt=report_id, pointer='/'+task+'/secondary/'+
                              str(full[task]['secondary'].index(row)))
        elif layer.startswith('native:notice__A1_OFFICIAL_CAP_RECLIP__'):
            arm, reference = layer.split('__')[2:]
            rows = full['A1']['tasks']['notice']['official_cap']['e3']
            found = [r for r in rows if (r['arm'], r['reference']) == (arm, reference)]
            require(len(found) == 1, 'Native official-cap disposition census: '+key)
            row = found[0]
            provenance = dict(receipt=report_id, pointer='/A1/tasks/notice/official_cap/e3/'+str(rows.index(row)))
        else:
            raise ValueError('Missing native family without explicit disposition source: '+key)
        bundles[key] = absent(key, ps, days, row, provenance)
        additions.append(dict(key=key, state=bundles[key]['state'], source=provenance))


    for task in P.PAIRS:
        mean_name = task+'__THREE_SEED_MEAN.json'
        if mean_name not in evidence['native']:
            fragile = inputs.score_json(task+'__A1_SEED_FRAGILE.json')
            reasons = {r.get('reason') for r in fragile['rows']}
            require(len(reasons) == 1 and None not in reasons and '' not in reasons and
                    all(r.get('three_seed_mean_decision') is None for r in fragile['rows']),
                    'Missing native mean without unavailable mean timestamp_checks: '+task)
            row = dict(state='NOT_EVALUABLE', reason=next(iter(reasons)))
            evidence['native'][mean_name] = absent(task+'/three_seed_mean_prediction',
                [list(p) for p in P.PAIRS[task]], bundles[task+'/primary']['days'], row,
                dict(receipt=inputs.score_files[task+'__A1_SEED_FRAGILE.json'], pointer='/rows'))
        key = task+'/R8'; family = records['batch']['families']['R8_'+task]
        if key not in bundles:
            require(family['state'] != 'COMPUTED', 'Missing computed R8 replay: '+task)

            from batch_layers import specified_families
            ps = [list(p) for p in specified_families()['R8_'+task]]
            rows = [r for r in records['batch_seal']['stage_dispositions'] if r['stage'] == 'R8_'+task]
            require(len(rows) == 1 and rows[0]['state'].startswith('NOT_RUN') and
                    rows[0].get('reason') == family.get('reason'), 'R8 native disposition association: '+task)
            bundles[key] = absent(key, ps, bundles[task+'/primary']['days'], family,
                dict(receipt=rows[0]['receipt_identity'], effective_stage=deepcopy(rows[0])))
            additions.append(dict(key=key, state=bundles[key]['state'], source=bundles[key]['disposition_source']))
    require(set(pairs) <= set(bundles), 'AP fixed forest family census incomplete')
    evidence['native_disposition_census'] = dict(schema='MINRUN_AP_NATIVE_DISPOSITION_CENSUS_V1',
        forest_slots=len(census['forest']), forest_families=len(pairs), additions=additions,
        no_statistics_added=True)
    return bundles
