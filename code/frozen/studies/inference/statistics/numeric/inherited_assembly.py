'Extract the numerical definitions used to assemble results.'
from pathlib import Path
from copy import deepcopy

def assembly_prefix(primary_tests, sensitivity_tests, robustness_tests, frozen, F, manifest, inputs, bundles, current, saved_2000, replay_evidence, chunk=512, gate=None):
    sc = ChunkedScoring(frozen, DRAWS, chunk, gate)
    batch, context = (inputs['batch'], inputs['context'])
    context['design_states'] = {}
    context['cheap_states'] = {}
    context['secondary_clause'] = {}
    context['secondary_check'] = {}
    context['secondary_differing_arms'] = {}
    for task in PAIRS:
        rows = current[task + '/primary']['reports']
        files = {}
        for layer, key in (('first_chunk', 'first_L'), ('window_24h', 'window_24h'), ('official_cap', 'official_cap'), ('drop_first_seven', 'drop_first_seven')):
            f = current[task + '/' + layer]
            files[key] = dict(reports=[dict(r, dm_p1=dict(mean_difference=r.get('mean_difference'), p_two_sided=r.get('p_two_sided')), primary_decision=r['decision']) for r in f['reports']])
        label = current[task + '/label_replacement']
        label_input = dict(state='A2LABEL_SCORED', families={task: label}) if label['state'] == 'COMPUTED' else None
        from reading_propagation import batch_reading
        ds = sensitivity_tests.sensitivity_states(task, rows, files, batch=batch_reading(sensitivity_tests, current, inputs), label=label_input)
        context['design_states'][task] = {a + '-' + b: states for (a, b), states in ds.items()}
        cheap = current[task + '/cheap']
        cheap_rows = cheap.get('reports', [])
        computed_cheap = {r['reference']: 'beaten' if r['decision'] == robustness_tests.IMP else 'worse' if r['decision'] == robustness_tests.DET else 'not beaten' for r in cheap_rows}
        key = robustness_tests.cheap_reading_key(dict(computed=computed_cheap, unavailable=[] if cheap_rows else ['missing']))
        cheap_state = 'BETTER' if key == 'A4CHR_BETTER' else 'WORSE' if key == 'A4CHR_NOT' and 'worse' in computed_cheap.values() else 'NOTSHOWN' if key == 'A4CHR_NOT' else 'NOT_EVALUABLE' if cheap['state'] != 'NOT_RUN' else 'NOT_RUN'
        context['cheap_states'][task] = {r['arm'] + '-' + r['reference']: cheap_state if r['arm'] == primary_tests.CONTENT_ARM[task] else 'NOT_EVALUABLE' for r in rows}
        differing = [r['arm'] for r in rows if any((v['state'] == 'DIFFERENT' for v in ds[r['arm'], r['reference']].values()))]
        context['secondary_clause'][task] = 'DIFFERENT' if differing else 'NOT_RUN'
        context['secondary_check'][task] = 'secondary_family'
        context['secondary_differing_arms'][task] = differing
    from reading_propagation import assemble
    propagation = assemble(primary_tests, sensitivity_tests, robustness_tests, current, inputs, context['design_states'])
    for task in PAIRS:
        pc = propagation['details'][task]['pc']
        alert = pc['state'] in ('SIZE_FAILS', 'BOTH_FAIL')
        context['pc_flags'][task] = dict(alert=alert, signal_failed=pc['state'] in ('SENSITIVITY_FAILS', 'BOTH_FAIL'))
        if alert:
            context['pc_flags'][task]['negative_control'] = dict(k0=pc['k0'], R0=pc['R0'], lo0=f'{100 * pc['cp0'][0]:.2f}', hi0=f'{100 * pc['cp0'][1]:.2f}')
    if any((propagation['details'][t]['pc']['state'] != 'NOT_RUN' for t in PAIRS)):
        context['pc_state'] = 'RESULT'
    return (propagation, sc)

def stage_projection(stage_names, main, batch, own, three, parity, deferred):
    expected = [x for x in stage_names if three or not x.startswith('A8B-R8S')]
    require(len(main) == 11 and len({r['stage'] for r in main}) == 11, 'Main stage census invalid')
    indexed = {r['stage']: r for r in main}
    require(set(indexed) == set(expected[:11]), 'Main stage inventory drift')
    cs8 = batch['CS8']['stage_dispositions']
    require(set(cs8) <= set(RERUNS), 'Ineligible re-run stage')
    out = []
    for name in expected[:11]:
        row, alt = (indexed[name], cs8.get(name))
        trigger = rerun_trigger(row)
        require(alt is None or trigger is not None, 'Re-run without frozen trigger: ' + name)
        require(not (name in RERUNS and trigger and (alt is None)), 'Required CS8 disposition missing: ' + name)
        c, post = (category(row), '--')
        reason = 'A4NR_BUDGET' if c == CATEGORIES[2] else None
        if alt is not None:
            tasks = ('news', 'notice') if name == 'report_only_2025_validation' else ('notice',) if 'notice' in name else ('news',)
            post = category(alt)
            if alt.get('state') == 'NOT_RUN_PARITY_FAILED':
                post = CATEGORIES[2]
            elif any((parity[t]['state'] != 'PASS' for t in tasks)):
                post = CATEGORIES[3]
                require(not alt.get('score_eligible'), 'Scoring parity failure with score-eligible CS8 stage')
            reason = alt.get('reason') if post != CATEGORIES[2] or alt.get('reason') == 'A8NR_PARITY' else 'A4NR_BUDGET'
        out.append(dict(stage=name, conf=c, postseal=post, counted_category=c if post == '--' else post, reason=reason, conf_reason='A4NR_BUDGET' if c == CATEGORIES[2] else row.get('reason'), rerun_trigger=trigger if alt is not None else None))
    for name in expected[11:]:
        require(name in own, 'Missing own-stage disposition: ' + name)
        r = own[name]
        c = category(r)
        if deferred and name.startswith('A8B-R8'):
            require(c == CATEGORIES[2] and r.get('reason') in ('A8NR_AUTHOR', 'A8NR_RESOURCE_A8AM2'), 'R8 specification-2 disposition mismatch')
        out.append(dict(stage=name, conf='--', postseal=c, counted_category=c, reason=r.get('reason'), rerun_trigger=None))
    counts = {c: sum((r['counted_category'] == c for r in out)) for c in CATEGORIES}
    require(sum(counts.values()) == len(out) == (22 if three else 21), 'Count conservation failed')
    return out

def timestamp_checks(inputs, manifest, name):
    if name in manifest['inputs']:
        item = manifest['inputs'][name]
        P.checked(item)
        P.require(any((Path(k).resolve() == Path(item['path']).resolve() and v == item['sha256'] for k, v in inputs['timestamps']['T5']['files'].items())), name + ' exact path absent from T5')
        return dict(item, data=inputs[name])
    filename = {'check_window_inputs': 'R8_ADMISSION.json', 'cps8_selection': 'CPS8_SELECTION.json'}[name]
    candidates = [i for i in inputs['batch_seal'].get('auxiliary', []) if Path(i['path']).name == filename]
    P.require(len(candidates) == 1, 'Missing native ' + filename)
    i = candidates[0]
    data = P.strict_json(P.checked(i))
    P.require(any((Path(k).resolve() == Path(i['path']).resolve() and v == i['sha256'] for k, v in inputs['timestamps']['T5']['files'].items())), filename + ' exact path absent from T5')
    return dict(i, data=data)

def square(row):
    if row and row.get('state') == 'COMPUTED' and (row.get('dm', {}).get('p_two_sided') is not None) and (row.get('effect') is not None):
        return dict(state='COMPUTED', effect=P.decimal(float(row['effect'])), p=P.decimal(row['dm']['p_two_sided'], 12))
    return dict(state='NOT_RUN', effect=None, p=None, reason=(row or {}).get('reason', 'fail'))

def r8_fields(F, record, inputs, manifest, current):
    batch = inputs['batch']
    rows = {r['stage']: r for r in record['stages']}
    record['r8_seed_disposition'] = dict(state='NOT_RUN', reason='A8NR_AUTHOR', seeds='single')
    record['optional']['R8'] = any((batch.get('families', {}).get('R8_' + t, {}).get('state') == 'COMPUTED' for t in P.PAIRS))
    b4 = rows['A8B-R8']
    record.pop('check_window_inputs', None)
    if not record['batch_parity_failed'] and (b4['reason'] == 'A8NR_RESOURCE_A8AM2' or b4['counted_category'] in P.CATEGORIES[:2]):
        record['check_window_inputs'] = timestamp_checks(inputs, manifest, 'check_window_inputs')
    for task, t in record['tasks'].items():
        family = current.get(task + '/R8', batch.get('families', {}).get('R8_' + task, dict(state='PENDING', reports=[])))
        stage = rows['A8B-R8' if task == 'news' else 'A8B-R8N']
        for i, c in enumerate(t['contrasts']):
            rel = P.relation(c['class'], family, i, fully_checked=False, seeds_run='single')
            if rel['state'] not in ('SAME', 'DIFFERENT'):
                rel['class'] = None
            if stage['counted_category'] in P.CATEGORIES[2:]:
                rel.update(state={P.CATEGORIES[2]: 'NOT_RUN', P.CATEGORIES[3]: 'NOT_EVALUABLE', P.CATEGORIES[4]: 'PENDING'}[stage['counted_category']], reason=stage['reason'])
            c['relations']['R8'] = rel
            c.pop('r8_result', None)
            if rel['state'] in ('SAME', 'DIFFERENT'):
                r = family['reports'][i]
                saved = batch.get('squared_loss', {}).get('R8', {}).get(task, [])
                c['r8_result'] = dict(effect_percent=P.decimal(r.get('effect_percent_reference_mae')), family_one_day=P.interval_strings(r.get('interval_family_one_day')), holm_p=P.decimal(r.get('holm_p'), 12), label='NOT_FULLY_CHECKED', squared_loss=square(saved[i] if len(saved) > i else None))
        t.pop('r8_descriptive', None)
        if stage['counted_category'] in P.CATEGORIES[:2]:
            schedule = {'news': [('M0', 'N'), ('M', 'M0'), ('M+0', 'N'), ('M+', 'M+0'), ('M+', 'M')], 'notice': [('M0_n', 'N'), ('M_notice', 'M0_n'), ('M+0_n', 'N'), ('M+_n', 'M+0_n'), ('M+_n', 'M_notice')]}[task]
            values = {}
            for key, (arm, ref) in zip(('m0_n', 'm_m0', 'mp0_n', 'mp_mp0', 'mp_m'), schedule):
                fam = current.get(task + '/R8_desc/' + arm + '-' + ref, {})
                if fam.get('state') == 'COMPUTED' and fam.get('reports'):
                    values[key] = P.decimal(fam['reports'][0].get('effect_percent_reference_mae'))
            if len(values) == 5 and all((v is not None for v in values.values())):
                t['r8_descriptive'] = values
            else:
                P.require(stage['counted_category'] != P.CATEGORIES[0], 'Completed R8 missing parity-verified descriptive census')
    delayed = batch.get('DLY8', {}).get('R8', {})
    fams = [current.get('notice/DLY8_R8_' + str(d), delayed.get(str(d), delayed)) for d in (5, 15, 60)]
    if rows['A8B-R8N']['counted_category'] == P.CATEGORIES[2] and record['batch_parity_failed']:
        record['dly8_r8'] = dict(state='NOT_RUN', reason='A8NR_PARITY', contrasts={})
    elif all((f.get('state') == 'COMPUTED' for f in fams)):
        record['dly8_r8'] = dict(state='COMPUTED', reason=None, contrasts={c['arm']: {str(d): P.CLASS[f['reports'][i]['decision']] for d, f in zip((5, 15, 60), fams)} for i, c in enumerate(record['tasks']['notice']['contrasts'])})
    else:
        f = next((f for f in fams if f.get('state') != 'COMPUTED'))
        state = f.get('state', 'PENDING')
        state = 'DEVIATION' if state.startswith('DEVIATION') else 'NOT_RUN' if state.startswith('NOT_RUN') else 'PENDING'
        record['dly8_r8'] = dict(state=state, reason=f.get('reason'), contrasts={})
    primary = batch.get('DLY8', {}).get('primary', {})
    if all((primary.get(str(d), {}).get('state') == 'COMPUTED' for d in (5, 15, 60))):
        cat = P.CATEGORIES[0] if record['dly8_r8']['state'] == 'COMPUTED' else P.CATEGORIES[1]
        rows['DLY8'].update(counted_category=cat, postseal=cat)

def prepare_stages(inputs):

    batch = inputs['batch']
    own = inputs['context']['own_stages']
    for row in batch.get('canonical_stage_rows', []):
        if row['stage'] in ('A8B-R8N', 'A8B-R8', 'A8B-CPS8', 'DLY8'):
            own[row['stage']] = dict(state='PENDING', category=row['counted_category'], reason=row.get('reason'))
    if batch.get('batch_parity_failed') or any((r['state'] != 'PASS' for r in batch['scoring_parity'].values())):
        for name in own:
            if name.startswith('A8B-'):
                own[name] = dict(state='NOT_RUN', reason='A8NR_PARITY')
        for row in batch['CS8']['stage_dispositions'].values():
            row.update(state='NOT_RUN_PARITY_FAILED', reason='A8NR_PARITY', score_eligible=False)

def selection_projection(F, primary_tests, sensitivity_tests, robustness_tests, record, inputs, manifest, current, prop):
    r8_fields(F, record, inputs, manifest, current)
    record['clk8_details'] = {k: deepcopy(inputs['clk8'].get(k, {})) for k in ('overall', 'by_month')}
    record['cps8_selection'] = None
    rows = {r['stage']: r for r in record['stages']}
    if rows['A8B-CPS8']['counted_category'] in P.CATEGORIES[:2]:
        record['cps8_selection'] = timestamp_checks(inputs, manifest, 'cps8_selection')
        data = record['cps8_selection']['data']
        P.require(set(data) == set(P.PAIRS), 'CPS8 requires normalized native per-task selection artifact')
        for task, t in record['tasks'].items():
            for c in t['contrasts']:
                rel = c['relations']['CPS8']
                g = data[task][c['arm']]
                if rel['state'] in ('SAME', 'DIFFERENT'):
                    if g is None or data[task][c['reference']] is None:
                        rel.update(state='NOT_EVALUABLE', reason='fail', **{'class': None})
                    else:
                        rel['selected_grid'] = g
