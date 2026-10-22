'Validate the source records required by the numerical input schema.'
from pathlib import Path

def load_scientific_inputs(P, runtime, path, expected, synthetic=False, *, author_validator):
    P.require(P.sha256(path) == expected, 'Input-manifest hash mismatch')
    m = P.strict_json(path)
    items = m['inputs']
    P.require(m.get('synthetic') is True if synthetic else not m.get('synthetic'), 'Synthetic manifest input_checks')
    required = {'seal', 'score_receipt', 'score_report', 'a2', 'a3', 'a4', 'batch', 'batch_seal', 'dly_seal', 'clk8', 'author', 'author_prescore', 'timestamps', 'human_review', 'repins', 'context', 'specification2', 'hrc_review', 'hrc_agreement', 'author_a3_a6'}
    P.require(required <= set(items) and set(items) <= required | {'pc', 'pcx', 'a2batch', 'a2batch_receipt', 'label', 'label_receipt', 'kcx', 'check_window_inputs', 'cps8_selection', 'cps8_selection_receipt'}, 'Missing/unknown V2 input role')
    meta = ('timestamps', 'author', 'author_prescore', 'context', 'specification2', 'human_review', 'repins')
    r = {k: P.strict_json(P.checked(items[k])) for k in meta}
    for label in ('T4', 'T4A', 'T4B', 'T5'):
        P.utc(r['timestamps'][label]['utc'])
    times = r['timestamps']
    score = r['context']['fill_clock']['score_utc']
    P.require(P.utc(times['T4']['utc']) <= P.utc(times['T4A']['utc']) <= P.utc(times['T4B']['utc']) <= P.utc(times['T5']['utc']) < P.utc(score), 'T5 chronology invalid')
    for label, key, filename in (('T4B', 'author', 'AUTHOR_CONFIRMATION_A8.json'), ('T5', 'author_prescore', 'AUTHOR_CONFIRMATION_A8_PRESCORE.json')):
        P.require(times[label]['files'].get(filename) == items[key]['sha256'], 'Author timestamp identity mismatch')
    P.verify_specification2(r['specification2'], items, times, score, synthetic)
    author_validator(association=runtime.association, first=r['author'], second=r['author_prescore'], timestamps=times)
    runtime.verify_scientific_t5()
    for key in ('seal', 'batch_seal', 'dly_seal', 'clk8', 'specification2'):
        P.require(items[key]['sha256'] in times['T5']['files'].values() or (key == 'clk8' and items[key]['sha256'] in times['T4B']['files'].values()), 'Required identity absent from T5: ' + key)
    for key in ('check_window_inputs', 'cps8_selection', 'cps8_selection_receipt'):
        if key in items:
            P.checked(items[key])
            P.require(any((Path(k).resolve() == Path(items[key]['path']).resolve() and v == items[key]['sha256'] for k, v in times['T5']['files'].items())), 'Native metadata exact path absent from T5: ' + key)
    r['score_receipt'] = P.strict_json(P.checked(items['score_receipt']))
    receipt = r['score_receipt']
    P.require(receipt['state'] == 'FROZEN_SCORE_COMPLETE' and receipt['seal_sha256'] == items['seal']['sha256'], 'SCORE_RECEIPT/seal mismatch')
    state = Path(items['seal']['path']).parent
    runtime.verify_official_items(items)
    r['seal'] = P.strict_json(P.checked(items['seal']))
    seal = r['seal']
    r['_seal_path'] = items['seal']['path']
    if synthetic:
        P.require(seal.get('synthetic') is True and state.resolve().is_relative_to(Path('/private/tmp')), 'Synthetic data must be an explicit scratch seal')
    else:
        P.require(seal['state'] == 'ALL_SPECIFIED_PREDICTIONS_SEALED' and seal['sealed_before_outcome_scoring'] is True, 'Production seal invalid')
        P.require(seal.get('partial_predictions_scored') is False, 'Partial predictions in seal')
        P.require(seal['design_freeze_sha256'] == P.sha256(P.confirmation / 'FREEZE.json'), 'Sealed design identity drift')
        P.require(len(seal['completed_input_manifest_sha256']) == 64, 'Sealed input manifest identity absent')
    P.require(P.sha256(seal['feature_manifest_path']) == seal['feature_manifest_sha256'], 'Feature manifest identity drift')
    for i in receipt['files']:
        P.checked(i)
    allowed = {(i['path'], i['sha256']) for i in receipt['files']}
    P.require((items['score_report']['path'], items['score_report']['sha256']) in allowed, 'Score report not receipt-bound')
    for key in set(items) - set(meta) - {'seal', 'score_receipt'}:
        r[key] = P.strict_json(P.checked(items[key]))
    for key in ('a2', 'a3', 'a4'):
        P.require(r[key]['seal_sha256'] == receipt['seal_sha256'], 'Frozen reader seal mismatch: ' + key)
    batch = r['batch']
    P.require(batch['schema'] == 'A8BATCH_POSTSCORE_INPUTS_V1' and batch['state'] == 'A8BATCH_SCORED', 'Batch state/schema invalid')
    P.require(batch['identities']['source_receipt_sha256'] == items['score_receipt']['sha256'], 'Batch/receipt binding drift')
    P.require(batch['seal']['sha256'] == items['batch_seal']['sha256'] and r['batch_seal']['conf_seal_sha256'] == items['seal']['sha256'], 'Batch seal association drift')
    if not synthetic:
        P.require(r['batch_seal']['state'] == 'ALL_A8BATCH_SPECIFIED_PREDICTIONS_SEALED', 'Batch seal invalid')
        P.require(r['batch_seal']['code_freeze']['sha256'] in times['T5']['files'].values(), 'Batch code freeze missing from T5')
        bf = P.strict_json(P.checked(r['batch_seal']['code_freeze']))
        P.require(bf['state'] == 'A8BATCH_CODE_FROZEN_BEFORE_FITTING' and bf.get('frozen') is True, 'Batch code freeze state invalid')
        for rel, digest in bf['code_sha256'].items():
            base = P.BATCH_CODE.parent
            codepath = (base / rel).resolve()
            P.require(codepath.is_relative_to(base), 'Unsafe batch code path')
            P.require(P.sha256(codepath) == digest, 'Batch code bytes drift')
        for item in [*bf['adapter_files'], *bf['external_files'], *bf['specs']['files']]:
            P.checked(item)
        ident = batch.get('scorer_code_freeze')
        P.require(isinstance(ident, dict), 'Batch scorer code freeze absent')
        sf = P.strict_json(P.checked(ident))
        P.require(ident['sha256'] in times['T5']['files'].values(), 'Batch scorer freeze missing from T5')
        P.require(sf['state'] == 'A8_SCORER_CODE_FROZEN_BEFORE_T5', 'Batch scorer freeze state invalid')
        P.require(sf['batch_code_freeze']['sha256'] == r['batch_seal']['code_freeze']['sha256'], 'Batch scorer/fit freeze mismatch')
        for item in [sf['batch_code_freeze'], sf['numerical_inputs'], sf['scorer_bindings'], *sf['files']]:
            P.checked(item)
            P.require(item['sha256'] in times['T5']['files'].values(), 'Batch scorer dependency missing from T5')
        for rel, digest in sf['code_sha256'].items():
            base = P.BATCH_CODE.parent
            p = (base / rel).resolve()
            P.require(p.is_relative_to(base) and P.sha256(p) == digest, 'Batch scorer code bytes drift')
    for key in ('hrc_review', 'hrc_agreement', 'author_a3_a6'):
        P.require(items[key]['sha256'] in times['T5']['files'].values(), 'Native HRC/author output not listed in T5: ' + key)
    if not synthetic:
        if 'a2batch' in r:
            for ident in (r['a2batch']['seal'], r['a2batch']['code_freeze']):
                P.checked(ident)
                P.require(ident['sha256'] in times['T5']['files'].values(), 'A2B prescore identity absent from T5')
        if 'label_receipt' in r:
            replacement = P.strict_json(P.checked(r['label_receipt']['replacement_predictions']))
            P.require(r['label_receipt']['replacement_predictions']['sha256'] in times['T5']['files'].values(), 'Label prediction seal absent from T5')
            P.require(replacement['seal_sha256'] == items['seal']['sha256'], 'Label main seal identity mismatch')
            parity = P.strict_json(P.checked(replacement['parity']))
            P.require(parity['seal_sha256'] == items['seal']['sha256'], 'Label parity seal identity mismatch')
        for ident in batch.get('sealed_inputs', {}).get('DLY8', []):
            P.checked(ident)
            P.require(ident['sha256'] in times['T5']['files'].values(), 'DLY8 prescore seal absent from T5')
    auxiliary = [i for i in r['batch_seal'].get('auxiliary', []) if Path(i['path']).name == 'R8_ADMISSION.json']
    P.require(len(auxiliary) <= 1, 'Duplicate native R8 admission timestamp_checks')
    if 'check_window_inputs' not in r and auxiliary:
        item = auxiliary[0]
        r['check_window_inputs'] = P.strict_json(P.checked(item))
        P.require(any((Path(k).resolve() == Path(item['path']).resolve() and v == item['sha256'] for k, v in times['T5']['files'].items())), 'Native R8 admission exact path absent from T5')
    news = batch.get('families', {}).get('R8_news', {})
    stage = next((row for row in batch.get('canonical_stage_rows', []) if row['stage'] == 'A8B-R8'), r['context']['own_stages'].get('A8B-R8', {}))
    needs_admission = not batch.get('batch_parity_failed', False) and (news.get('state') == 'COMPUTED' or stage.get('reason') == 'A8NR_RESOURCE_A8AM2' or stage.get('counted_category') in P.CATEGORIES[:2])
    P.require(not needs_admission or 'check_window_inputs' in r, 'Native R8 admission timestamp_checks absent before value replay')
    if not synthetic and any((v.get('state') == 'COMPUTED' for v in batch.get('CPS8', {}).values())):
        P.require('cps8_selection' in items and 'cps8_selection_receipt' in items, 'Computed CPS8 needs prescore projection timestamp_checks before value replay')
    if 'cps8_selection' in items and (not synthetic):
        P.require('cps8_selection_receipt' in items, 'CPS8 projection receipt missing')
        from prescore_metadata import verify as verify_selection
        verify_selection(items['cps8_selection'], items['cps8_selection_receipt'], times)
    if 'check_window_inputs' in r:
        from frozen_losses import ast_functions
        import datetime as dt, math
        ns = dict(dt=dt, math=math, require=P.require, DEADLINE='2026-10-05T18:00:00+00:00', PROXY_ROUND_SECONDS=43.488448833, NEWS_ROUNDS=430)
        ast_functions(P.BATCH_CODE / 'check_window_inputs.py', ('decision',), ns)
        raw = r['check_window_inputs']
        expected_admission = ns['decision'](raw['start_utc'], raw['rho'], raw['dly8_r8_seconds'], raw['seal_seconds'])
        P.require(all((raw.get(k) == v for k, v in expected_admission.items())) and raw.get('outcome_access') is False, 'R8 metadata admission projection mismatch')
        if not synthetic:
            P.require(raw.get('projection_inputs', {}).get('evidence'), 'R8 prescore projection evidence missing')
            for item in raw['projection_inputs']['evidence']:
                P.checked(item)
                P.require(item['sha256'] in times['T4B']['files'].values(), 'R8 projection evidence absent from T4B')
    for i in [*seal['predictions'], *seal['truth_panels'].values(), *seal.get('coverage_and_matched_masks', []), *seal.get('common_keys', {}).values(), *seal.get('fit_receipts_and_models', []), *seal.get('auxiliary_sources_and_resources', [])]:
        if 'path' in i:
            P.checked(i)
    if not synthetic:
        for row in seal['stage_dispositions']:
            P.checked(row['receipt_identity'])
    if 'pc' in r:
        r['_pc_path'] = items['pc']['path']
    P.fill_cutoff(r['context']['fill_clock'], m.get('refill', False))
    return (m, r)
