"""Post-CONF-score scoring only. Import is inert; no host paths are opened.

CS8 uses the installed, frozen seal_score pipeline unchanged after task-level
primary-record parity. A8 families use its daily losses and frozen DM/bootstrap
functions with A8's registered 100000 draws and family slots. This emits scorer
inputs for a8_postscore, not primary reading decisions or invented FILL3f prose.
"""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import argparse
import copy
import importlib
import numpy as np
from a8_common import *
from batch_export import FAMILIES

DRAWS = 100000
CLASS = {'CONDITIONAL_IMPROVEMENT':'IMP','CONDITIONAL_DETERIORATION':'DET',
         'NO_RELIABLE_INCREMENT_DETECTED':'NULL','NOT_EVALUABLE':'NE'}

@contextmanager
def settings(scoring, draws=None, source=None, pairs=None):
    names = ['BOOTSTRAP_DRAWS'] + (['NEWS_FAMILY' if source == 'news' else 'NOTICE_FAMILY'] if pairs else [])
    old = {n:getattr(scoring,n) for n in names}
    try:
        if draws is not None:
            scoring.BOOTSTRAP_DRAWS = draws
        if pairs:
            setattr(scoring,names[-1],tuple(pairs))
        yield
    finally:
        for n,v in old.items():
            setattr(scoring,n,v)

def clean_record(native, result):
    """Same persisted fields as frozen _write_inference, preserving binary arrays."""
    arrays = {'picks_'+str(b):p for b,p in result.get('paired_day_picks',{}).items() if p is not None}
    record = dict(result)
    record.pop('paired_day_picks',None)
    record['reports'] = []
    for i,report in enumerate(result['reports']):
        row = dict(report)
        row['bootstrap'] = {}
        for block,boot in report.get('bootstrap',{}).items():
            value = dict(boot)
            draws = value.pop('draws',None)
            if draws is not None:
                arrays[f'contrast_{i}_draws_{block}'] = draws
            row['bootstrap'][block] = value
        record['reports'].append(row)
    return native._json_result(record),arrays

def score_parity(native, recomputed, reference, reference_arrays):
    actual, arrays = clean_record(native,recomputed)
    expected = dict(reference)
    expected.pop('bootstrap_artifact',None)
    require(actual == expected, 'Scoring parity: primary score record mismatch')
    require(set(arrays) == set(reference_arrays), 'Scoring parity: bootstrap array inventory mismatch')
    require(all(bytes_equal(np.asarray(arrays[k]),np.asarray(reference_arrays[k])) for k in arrays),
            'Scoring parity: bootstrap bytes mismatch')
    return True

def verify_main_artifacts(seal):
    items = [*seal['predictions'],*seal['common_keys'].values(),*seal['truth_panels'].values(),
             *seal['coverage_and_matched_masks'],*seal['fit_receipts_and_models'],
             *seal['auxiliary_sources_and_resources'],*(r['receipt_identity'] for r in seal['stage_dispositions'])]
    for item in items:
        checked(item)
    require(sha(seal['feature_manifest_path']) == seal['feature_manifest_sha256'], 'Main scorer feature identity drift')

def task_parity(native, scoring, permit, source, seal, seal_identity, score_files):
    """Reference must be in the verified CONF score receipt, not an arbitrary file."""
    ref = next((i for i in score_files if Path(i['path']).name == source+'__PRIMARY.json'),None)
    require(ref is not None, 'Scoring parity: missing CONF primary score reference')
    reference = read_json(checked(ref))
    panel,days,counts,pred,ids,clips,raw = native._read_task_data(source,seal)
    losses = {arm:native._daily(panel,p)[1] for (arm,seed,var),p in pred.items() if seed == SEED and var == 'main'}
    panel_id = dict(daily_common_key_counts=counts,common_keys_sha256=seal['common_keys'][source]['common_keys_sha256'],
                    sealed_prediction_manifest_sha256=seal_identity['sha256'])
    # Native CONF draw count for EXACT reproduction; 100000 is used only afterwards.
    recomputed = scoring.registered_daily_inference(losses,days,source,permit,panel_id)
    binary = checked(reference['bootstrap_artifact'])
    with np.load(binary,allow_pickle=False) as arrays:
        score_parity(native,recomputed,reference,arrays)
    return dict(state='PASS',reference=ref,bootstrap_artifact=reference['bootstrap_artifact'])

def load_a2():
    root = CONF/'A2'
    freeze = read_json(root/'A2_CODE_AND_RULES_FREEZE.json')
    for rel,item in freeze['files'].items():
        require(sha(root/rel) == item['sha256'], 'Frozen A2 scoring helper drift: '+rel)
    return module(root/'code/a2_postscore.py','_a8_frozen_a2')

def fill_fields(a2, row, seed_row=None):
    cls = row['decision']
    seed_cls = None if seed_row is None else seed_row['decision']
    seed_state = a2.seed_rule(cls,row.get('mean_difference'),seed_cls,
                             None if seed_row is None else seed_row.get('mean_difference'))
    one,seven = row['bootstrap']['1'],row['bootstrap']['7']
    label = a2.robustness_label(cls,one.get('interval95_percent'),seven.get('interval95_percent'),
        row['hln_decision'],row['hac7_decision'],seed_state,seven_day_state=seven.get('state'))
    checks = {k:'UNAVAILABLE' if v is None else 'PASS' if v else 'FAIL' for k,v in label['checks'].items()}
    checks['family_interval'] = ('UNAVAILABLE' if one.get('interval_family_adjusted_percent') is None else
        'PASS' if a2.interval_agrees(cls,one['interval_family_adjusted_percent']) else 'FAIL')
    for k in ('one_day','seven_day','hln','hac7','three_seed'):
        checks.setdefault(k,'UNAVAILABLE')
    f1,f7 = one.get('interval_family_adjusted_percent'),seven.get('interval_family_adjusted_percent')
    env = None if f1 is None else max(0.,-min(f1[0],f7[0] if f7 else f1[0]))
    decimal = lambda x:None if x is None else str(float(x))
    interval = lambda x:None if x is None else [decimal(v) for v in x]
    return dict(arm=row['arm'],reference=row['reference'],**{'class':CLASS.get(cls,'NE')},
        effect_percent=decimal(row.get('effect_percent_reference_mae')),effect_aud=decimal(row.get('mean_difference')),
        family_one_day=interval(f1),family_seven_day=interval(f7),per_contrast_seven_day=interval(seven.get('interval95_percent')),
        envelope=decimal(env),checks=checks,three_seed_class=CLASS.get(seed_cls,'NE'),
        three_seed_effect=decimal(None if seed_row is None else seed_row.get('effect_percent_reference_mae')),
        fully_checked=all(v != 'UNAVAILABLE' for v in checks.values()),
        label='ROBUST' if all(v == 'PASS' for v in checks.values()) else
              'FRAGILE_NFC' if 'FAIL' in checks.values() and 'UNAVAILABLE' in checks.values() else
              'FRAGILE' if 'FAIL' in checks.values() else 'NOT_FULLY_CHECKED')

def family_score(native, scoring, permit, source, pairs, seal, predictions, draws=DRAWS, a2=None):
    a2 = a2 or load_a2()
    combined = dict(seal,predictions=predictions)
    panel,days,counts,pred,ids,clips,raw = native._read_task_data(source,combined)
    losses = {arm:native._daily(panel,p)[1] for (arm,seed,var),p in pred.items() if seed == SEED and var == 'main'}
    needed = {a for pair in pairs for a in pair}
    ts = None
    with settings(scoring,draws):
        result = a2.family_inference(scoring,losses,pairs,days)
        if all((a,seed,'main') in pred for a in needed for seed in (SEED,20260920,20260921)):
            means = {a:np.mean([pred[(a,seed,'main')] for seed in (SEED,20260920,20260921)],axis=0) for a in needed}
            if source == 'notice':
                means = {a:v.astype('float32') for a,v in means.items()}
            ts = a2.family_inference(scoring,{a:native._daily(panel,p)[1] for a,p in means.items()},pairs,days)
    result['fill3f_fields'] = [fill_fields(a2,r,None if ts is None else ts['reports'][i]) for i,r in enumerate(result['reports'])]
    result['three_seed'] = ts
    result['bootstrap_draws'] = draws
    return result

def descriptive_scores(native,scoring,permit,main,batch,inputs):
    """Single-contrast exploratory activity readings and descriptive squared DM."""
    import pandas as pd
    descriptive = {}
    squared = {'primary':{},'R8':{}}
    for source in ('news','notice'):
        panel,days,counts,pred,ids,clips,raw = native._read_task_data(source,dict(main,predictions=[*main['predictions'],*batch['predictions']]))
        daily = {a:native._daily(panel,p)[1] for (a,seed,var),p in pred.items() if seed == SEED and var == 'main'}
        for key,item in inputs['descriptive'].items():
            if item['source'] != source:
                continue
            arm,ref = item['arm'],item['reference']
            if item['state'] != 'READY_FOR_FROZEN_SCORING' or arm not in daily or ref not in daily:
                descriptive[key] = dict(item,reports=[])
                continue
            a2 = load_a2()
            with settings(scoring,DRAWS):
                result = a2.family_inference(scoring,daily,[(arm,ref)],days,m=1)
            descriptive[key] = dict(item,state='COMPUTED',reports=result['reports'],
                                    unadjusted=True,single_seed=True,maximum_reading='NOT_FULLY_CHECKED',exploratory=True)
        square = {}
        for (arm,seed,var),p in pred.items():
            if seed != SEED or var != 'main':
                continue
            loss = np.square(p-panel['y'].to_numpy(dtype='float64'))
            frame = pd.DataFrame(dict(day=panel['target_day'].to_numpy(),loss=loss))
            square[arm] = frame.groupby('day',sort=True).loss.mean().to_numpy(dtype='float64')
        primary = [('L_count','M'),('L_chen','M')] if source == 'news' else [('L14','M_notice'),('L_Laz','M_notice'),('L_chen_notice','M_notice')]
        for name,pairs in [('primary',primary),('R8',FAMILIES['R8_'+source])]:
            rows = []
            for arm,ref in pairs:
                if arm not in square or ref not in square:
                    rows.append(dict(arm=arm,reference=ref,state='NOT_RUN',effect=None))
                    continue
                dm = scoring.dm_daily(square[arm]-square[ref])
                effect = None if square[ref].mean() == 0 else str(float(100*(square[arm].mean()/square[ref].mean()-1)))
                rows.append(dict(arm=arm,reference=ref,state='COMPUTED',effect=effect,dm=dm,descriptive=True))
            squared[name][source] = rows
    return descriptive,squared

def layer_scores(native,scoring,permit,main,batch,inputs,out):
    """DLY8 +5/+15/+60; CPS8 selected vs matching g0, no primary substitution."""
    import cps8_runner as cps
    layers = {'DLY8':{},'CPS8':{}}
    main_pairs = {'news':[('L_count','M'),('L_chen','M')],
                  'notice':[('L14','M_notice'),('L_Laz','M_notice'),('L_chen_notice','M_notice')]}
    for item in inputs['DLY8']:
        rec = read_json(checked(item))
        family = 'primary' if item['mode'] == 1 else 'R8'
        if rec['state'] != 'ALL_DLY8_PREDICTIONS_SEALED':
            layers['DLY8'][family] = dict(state=rec['state'],reports=[],reason=rec.get('reason'))
            continue
        pairs = main_pairs['notice'] if family == 'primary' else FAMILIES['R8_notice']
        layers['DLY8'][family] = {}
        for delta in (5,15,60):
            preds = [dict(i,variant='main') for i in rec['predictions'] if i['delta_minutes'] == delta]
            result = family_score(native,scoring,permit,'notice',pairs,main,preds)
            path = out/('DLY8_'+family+'_'+str(delta)+'.json')
            write_json(path,result,exclusive=True)
            layers['DLY8'][family][str(delta)] = dict(state='COMPUTED',report=identity(path),**result)
    capacity = inputs['CPS8']
    for source in ('news','notice'):
        if capacity['state'] != 'READY_FOR_FROZEN_SCORING':
            layers['CPS8'][source] = dict(state=capacity['state'],reason=capacity.get('reason'),reports=[])
            continue
        if capacity.get(source+'_all_g0_no_D_fit',False):
            layers['CPS8'][source] = dict(state='CAPACITY_SELECTION_KEPT_G0',reports=[])
            continue
        selection = capacity['selected']
        results = {}
        for setting in ('selected','g0'):
            preds = []
            for arm in cps.ARMS[source]:
                g = selection[source+'/'+arm] if setting == 'selected' else 'g0'
                found = [i for i in capacity['predictions'] if i['source'] == source and i['arm'] == cps.encode_arm(arm,g)]
                if source == 'notice' and g == 'g0':
                    found = [i for i in capacity['notice_g0_predictions'] if i['arm'] == arm]
                require(len(found) == 1, 'CPS8 schedule-matched sealed arm missing')
                preds.append(dict(found[0],arm=arm,variant='main'))
            results[setting] = family_score(native,scoring,permit,source,main_pairs[source],main,preds)
        dissent = [x['decision'] != y['decision'] for x,y in zip(results['selected']['reports'],results['g0']['reports'])]
        path = out/('CPS8_'+source+'.json')
        write_json(path,dict(state='COMPUTED',design_dissent=dissent,**results),exclusive=True)
        layers['CPS8'][source] = dict(state='COMPUTED',design_dissent=dissent,report=identity(path),**results)
    return layers

def relation(primary_class, score_class, fully_checked=None):
    require(primary_class in ('IMP','NULL','DET','NE'), 'Invalid primary class')
    result = dict(state='NOT_EVALUABLE' if score_class == 'NE' else
                  ('SAME' if primary_class == score_class else 'DIFFERENT'), **{'class':score_class})
    if fully_checked is not None:
        result['fully_checked'] = fully_checked
    return result

RELATION_STATES = ('SAME','DIFFERENT','NOT_RUN','NOT_EVALUABLE','PENDING','NOT_APPLICABLE')

def state_relation(state,score_class=None):
    require(state in RELATION_STATES,'Unregistered relation state')
    return dict(state=state,**{'class':score_class})

def fill3f_overlay(base, scored):
    """Keep the upstream A8 primary/RS8 record; add only batch relation readings.

    a8_postscore remains responsible for the full N0 prose and recomputing A4
    caps/three-seed/dependence readings from CS8. This explicit adapter uses the
    SPEC_FILL3F field names; it never synthesises a primary class or N0 sentence.
    """
    require(base.get('schema') == 'FILL3F_A8_V1' and base.get('bootstrap_draws') == DRAWS,
            'Upstream A8 RS8 record with B=100000 required')
    require(set(base['tasks']) == {'news','notice'} and isinstance(base['registered_reading_n0'],str)
            and base['registered_reading_n0'].strip(), 'Full registered N0 reading required')
    out = copy.deepcopy(base)
    for task in ('news','notice'):
        family = scored['families']['R8_'+task]
        capacity = scored['CPS8'][task]
        delayed = scored['DLY8'].get('primary',{}) if task == 'notice' else {}
        for index,c in enumerate(out['tasks'][task]['contrasts']):
            if family['state'] == 'COMPUTED':
                r = family['fill3f_fields'][index]
                report = family.get('reports',[])[index] if family.get('reports') else r
                if 'arm' in report or 'reference' in report:
                    require(report.get('arm','').removesuffix('+') == c['arm'] and report.get('reference','').removesuffix('+').replace('M+_n','M_notice') == c['reference'],'Overlay contrast arm/reference order drift')
                c['relations']['R8'] = dict(relation(c['class'],r['class'],r['label'] == 'ROBUST' and not family['single_seed']),seeds_run='single' if family['single_seed'] else 'three')
            else:
                chosen = out.get('author_confirmation',{}).get('choices',{}).get('r8_seeds','single')
                seed_stage = next((r for r in out.get('stages',[]) if r['stage'] == 'A8B-R8S'),{})
                actual = 'three' if chosen == 'three' and (task == 'notice' or seed_stage.get('counted_category') in ('completed','completed apart from recorded unavailable configurations')) else 'single'
                c['relations']['R8'] = dict(state='PENDING' if family['state'].startswith('PENDING') else
                        'NOT_EVALUABLE' if family['state'] == 'DEVIATION' else 'NOT_RUN',
                        **{'class':None},fully_checked=False,seeds_run=actual)
            if task == 'news':
                c['relations']['DLY8'] = state_relation('NOT_APPLICABLE')
            elif '15' in delayed:
                cls = delayed['15']['fill3f_fields'][index]['class']
                c['relations']['DLY8'] = relation(c['class'],cls)
            else:
                state = delayed.get('state','NOT_RUN')
                c['relations']['DLY8'] = state_relation('PENDING' if state.startswith('PENDING') else
                    'NOT_EVALUABLE' if state in ('A8DLY_DEV','DEVIATION') else 'NOT_RUN')
            if capacity['state'] == 'COMPUTED':
                chosen = capacity['selected']['fill3f_fields'][index]['class']
                control = capacity['g0']['fill3f_fields'][index]['class']
                c['relations']['CPS8'] = dict(state='NOT_EVALUABLE' if chosen == 'NE' or control == 'NE' else
                     'SAME' if chosen == control else 'DIFFERENT',**{'class':chosen})
            else:
                c['relations']['CPS8'] = state_relation('NOT_APPLICABLE' if capacity['state'] == 'CAPACITY_SELECTION_KEPT_G0' else
                    'PENDING' if capacity['state'].startswith('PENDING') else
                    'NOT_EVALUABLE' if capacity['state'] == 'DEVIATION' else 'NOT_RUN')
            c['design_rejection_not_reproduced'] = c['class'] in ('IMP','DET') and (bool(c.get('design_layers')) or any(
                v['state'] == 'DIFFERENT' and v.get('class') not in (None,'NE',c['class'])
                for k,v in c['relations'].items() if k in ('DLY8','CPS8','KCX')))
    return out

def cs8_dispositions(stages, parity):
    out = {}
    for row in stages:
        if not row['stage'].startswith('CS8_'):
            continue
        source = 'notice' if 'notice' in row['stage'] else 'news'
        state = row['state']
        if state in COMPLETE and parity[source]['state'] != 'PASS':
            state = 'DEVIATION_SCORING_PARITY'
        if state == 'DEVIATION_SCORING_PARITY':
            row = dict(row,reason='A8DEV_SCORING_PARITY',deviation_detail='its completed post-seal re-run deviated in scoring parity')
        out[row['stage'][4:]] = dict(row,stage=row['stage'][4:],state=state,scoring_parity=parity[source],
             score_eligible=state in COMPLETE,category='completed apart from recorded unavailable configurations'
             if state == COMPLETE[1] else 'completed' if state == 'COMPLETE' else 'not run (frozen reason)' if rerun_eligible_state(row) else 'deviation')
    return out

def rerun_eligible_state(row):
    from runner import rerun_eligible
    return row['state'].startswith('NOT_RUN') or rerun_eligible(row)

def stage_reason(row):
    """Return frozen reason IDs, never free-form runtime exception prose."""
    from runner import rerun_eligible
    require(row['state'] != 'UNAVAILABLE_INPUT_PREREQUISITE','Unruled UNAVAILABLE_INPUT_PREREQUISITE; coordinator dated reason required')
    if (row.get('reason') or '').startswith(('A8NR_','A8DEV_')):
        return row['reason']
    state = row['state']
    if state == 'DEVIATION_SCORING_PARITY':
        return 'A8DEV_SCORING_PARITY'
    if state == 'NOT_RUN_A8_AMENDMENT_2':
        from a8_amendment2 import REASON
        return REASON
    if 'PARITY' in state:
        return 'A8NR_PARITY'
    if rerun_eligible(row):
        return 'A4NR_BUDGET'
    if state.startswith('NOT_RUN'):
        require(state == 'NOT_RUN_BUDGET','Missing frozen not-run reason: '+state)
        return 'A8NR_BATCH_BUDGET'
    if state == 'UNAVAILABLE_INPUT_PREREQUISITE':
        raise RuntimeError('Unruled UNAVAILABLE_INPUT_PREREQUISITE disposition; coordinator dated reason required')
    if state.startswith(('INCOMPLETE','DEVIATION')):
        return 'A8DEV_RERUN' if row.get('stage','').startswith(('CS8_','B0')) or row.get('scoring_parity') else None
    return row.get('reason')

def stage_table(main_rows, cs8, batch_rows, own, three=False):
    """A8's 21/22 rows; batch disposition controls re-run stage counts."""
    categories = ('completed','completed apart from recorded unavailable configurations',
                  'not run (frozen reason)','deviation','pending (no result file when filled)')
    def category(row):
        if row.get('category') in categories:
            return row['category']
        state = row['state']
        if state == 'COMPLETE':
            return categories[0]
        if state == 'COMPLETE_WITH_UNAVAILABLE_CONFIGURATIONS':
            return categories[1]
        if state.startswith('PENDING'):
            return categories[4]
        from runner import rerun_eligible
        if state.startswith(('NOT_RUN','UNAVAILABLE_RESOURCE_BUDGET','UNAVAILABLE_INPUT_PREREQUISITE')) or rerun_eligible(row):
            return categories[2]
        return categories[3]
    rows = []
    main_order = ('primary_news','primary_notice','report_only_2025_validation','secondary_notice',
                  'secondary_news','secondary_LEAR','primary_seed_robustness_notice',
                  'primary_seed_robustness_news','window_24h','first_L_notice','first_L_news')
    indexed = {r['stage']:r for r in main_rows}
    require(set(indexed) == set(main_order) and len(indexed) == len(main_rows),'FILL3f main stage census drift')
    for name in main_order:
        row = indexed[name]
        alt = cs8.get(row['stage'])
        from runner import rerun_trigger
        final = row if alt is None else alt
        rows.append(dict(stage=row['stage'],conf=category(row),postseal='--' if alt is None else category(alt),
                         counted_category=category(final),reason=stage_reason(final),conf_reason=stage_reason(row),
                         rerun_trigger=None if alt is None else rerun_trigger(row)))
    batch = {r['stage']:r for r in batch_rows}
    # CPS8 has several execution sub-stages but exactly one reporting row.
    if 'CPS8' in batch:
        capacity = batch['CPS8']
    else:
        parts = [batch.get(n,dict(state='INCOMPLETE_FAILURE')) for n in
                 ('CPS8_selection_news','CPS8_selection_notice','CPS8_D_news','CPS8_D_notice')]
        capacity = dict(state='COMPLETE_WITH_UNAVAILABLE_CONFIGURATIONS' if all(p['state'] in COMPLETE for p in parts) and any(p['state'] == COMPLETE[1] for p in parts) else
                             'COMPLETE' if all(p['state'] in COMPLETE for p in parts) else 'DEVIATION')
    new = dict(own)
    new.update({'A8B-R8N':batch['R8_notice'],'A8B-CPS8':capacity,'A8B-R8':batch['R8_news']})
    if three:
        new['A8B-R8S'] = batch['R8_news_seeds']
    names = ['A2B-1','A2B-2','A2LABEL','PC','PCX','A8B-R8N','A8B-CPS8','A8B-R8']
    if three:
        names.append('A8B-R8S')
    names += ['DLY8','KCX']
    for name in names:
        require(name in new, 'Own-run disposition required for stage table: '+name)
        cat = category(new[name])
        rows.append(dict(stage=name,conf='--',postseal=cat,counted_category=cat,reason=stage_reason(new[name]),rerun_trigger=None))
    require(len(rows) == (22 if three else 21) and len({r['stage'] for r in rows}) == len(rows), 'A8 stage count drift')
    counts = {cat:sum(r['counted_category'] == cat for r in rows) for cat in categories}
    require(sum(counts.values()) == len(rows), 'A8 stage count conservation failure')
    return dict(rows=rows,counts=counts,n_stages=len(rows),rerun_stages=len(cs8))

def dly_stage(primary,r8):
    """Frozen DLY8_SPEC: primary determines failure; R8 can only make it partial."""
    if primary['state'] == 'ALL_DLY8_PREDICTIONS_SEALED':
        return dict(state='COMPLETE' if r8['state'] == 'ALL_DLY8_PREDICTIONS_SEALED' else COMPLETE[1])
    if primary['state'] == 'NOT_RUN_PARITY_FAILED':
        return dict(state='NOT_RUN_PARITY_FAILED',reason='A8NR_PARITY')
    if primary['state'] in ('A8DLY_DEV','DEVIATION'):
        return dict(state='DEVIATION',reason=None)
    require(primary['state'].startswith('PENDING'),'Nonterminal DLY8 cannot be scored')
    return dict(state='PENDING')

def composite_seal(A,main,batch,dispositions):
    composite = copy.deepcopy(main)
    wanted = set()
    for name,jobs,_ in A.execution.registered_plan():
        row = dispositions.get(name)
        if row and row['score_eligible']:
            wanted.update((t.task,t.arm,t.seed,t.variant) for t in jobs)
    composite['predictions'] = [i for i in main['predictions'] if
        (i['source'],i['arm'],i['seed'],i['variant']) not in wanted]
    composite['predictions'] += [i for i in batch['predictions'] if
        (i['source'],i['arm'],i['seed'],i['variant']) in wanted]
    composite['fit_receipts_and_models'] += batch['fit_receipts_and_models']
    composite['stage_dispositions'] = [dispositions.get(r['stage'],r) for r in main['stage_dispositions']]
    return composite

def frozen_cs8_score(A,native,permit,state,main,batch,dispositions):
    """Run the frozen complete reporting/reading pipeline in an isolated own root.

    Main primary predictions stay byte-identical. Only eligible, whole CS8 stages
    replace their original dispositions; no partial predictions are substituted.
    """
    import shutil
    from unittest.mock import patch
    root = Path(state)/'scoring/CS8'
    root.mkdir(parents=True,exist_ok=True)
    main_path = checked(batch['conf_seal'])
    seal_path = root/'SEAL.json'
    if not seal_path.exists():
        atomic_copy(main_path,seal_path)  # primary panel identity remains the CONF seal digest
    require(sha(seal_path) == batch['conf_seal_sha256'], 'CS8 main seal copy drift')
    if (root/'scored').exists() and not (root/'scored/SCORE_RECEIPT.json').exists():
        retained = root/'failed_attempts'/uuid.uuid4().hex
        retained.parent.mkdir(exist_ok=True)
        os.rename(root/'scored',retained)
    composite = composite_seal(A,main,batch,dispositions)
    # Every candidate is still sealed, identity checked above. Frozen verification
    # is applied to the two source seals before this in-memory union is supplied.
    with patch.object(native,'verify_seal',return_value=composite):
        result = native.score(permit,Path(main['feature_manifest_path']).parent,root)
    return dict(score_report=identity(root/'scored/SCORE_REPORT.json'),
                score_receipt=identity(root/'scored/SCORE_RECEIPT.json'),
                summary=result,source_seals=[batch['conf_seal'],identity(Path(state)/'SEAL_A8BATCH.json')])

def parity_by_task(native,scoring,permit,main,source_seal,files):
    parity = {}
    for source in ('news','notice'):
        try:
            parity[source] = task_parity(native,scoring,permit,source,main,source_seal,files)
        except Exception as exc:
            parity[source] = dict(state='DEVIATION_SCORING_PARITY',reason=str(exc))
    return parity

def score(state, code, A, main_score_receipt):
    from batch_export import verify_seal,export_score_inputs
    state = Path(state)
    from a8_freeze import validate_t5_binding
    validate_t5_binding(code,state)
    if state.resolve() == (OUT/'state').resolve():
        from scorer_freeze import verify as verify_scorer
        verify_scorer()
        code = dict(code,loss_exporter_freeze=identity(OUT/'SCORER_CODE_FREEZE.json'))
    batch = verify_seal(state)
    main = read_json(checked(batch['conf_seal']))
    verify_main_artifacts(main)
    require(batch['adapter_freeze_sha256'] == code['adapter_freeze_sha256'], 'Scorer adapter drift')
    receipt = read_json(checked(main_score_receipt))
    require(receipt['state'] == 'FROZEN_SCORE_COMPLETE' and receipt['seal_sha256'] == batch['conf_seal_sha256'],
            'Completed CONF score receipt bound to the main seal required')
    for i in receipt['files']:
        checked(i)
    native = importlib.import_module('seal_score')
    require(Path(native.__file__).resolve().parent == A.root, 'Frozen scorer import drift')
    permit = replace(A.runtime.validate_permit(),predictions_sealed=True)
    scoring = A.runtime.conf_module('scoring')
    parity = parity_by_task(native,scoring,permit,main,batch['conf_seal'],receipt['files'])
    dispositions = cs8_dispositions(batch['stage_dispositions'],parity)
    out = state/'scoring'
    out.mkdir(exist_ok=True)
    write_json(out/'SCORING_PARITY.json',parity,exclusive=True)
    # The registered CS8 scoring functions retain their native B for reproduction;
    # a8_postscore recomputes A8 interval layers at B=100000 from the bound predictions.
    cs8 = frozen_cs8_score(A,native,permit,state,main,batch,dispositions)
    from loss_export import export_losses
    losses = export_losses(native,A,composite_seal(A,main,batch,dispositions),batch['conf_seal_sha256'],
                           state/'scoring/A8POST_LOSS_EXPORT.json',code)
    # New wrapper receipt binds the immutable native receipt and additive losses;
    # no frozen native result or already sealed receipt is rewritten.
    native_receipt = cs8['score_receipt']
    wrapper = dict(read_json(checked(native_receipt)))
    wrapper['native_score_receipt'] = native_receipt
    wrapper['files'] = [*wrapper['files'],native_receipt,identity(losses)]
    wrapper_path = out/'CS8_SCORE_RECEIPT_WITH_LOSSES.json'
    write_json(wrapper_path,wrapper,exclusive=True)
    cs8['score_receipt'] = identity(wrapper_path)
    cs8['loss_export'] = identity(losses)
    inputs = export_score_inputs(state)
    families = {}
    for name,pairs in FAMILIES.items():
        source = name.removeprefix('R8_')
        row = next(r for r in batch['stage_dispositions'] if r['stage'] == name)
        if row['state'] not in COMPLETE:
            families[name] = dict(state='NOT_RUN' if row['state'].startswith('NOT_RUN') else 'DEVIATION',reason=row.get('reason'),reports=[])
            continue
        result = family_score(native,scoring,permit,source,pairs,dict(main,_identity_sha256=batch['conf_seal_sha256']),
                              [*main['predictions'],*batch['predictions']])
        saved = result
        write_json(out/(name+'.json'),saved,exclusive=True)
        families[name] = dict(state='COMPUTED',reports=saved['reports'],fill3f_fields=saved['fill3f_fields'],three_seed=saved['three_seed'],report=identity(out/(name+'.json')),
             family_m=len(pairs),single_seed=not any(i['seed'] != SEED and i['arm'] in {a for p in pairs for a in p}
                                                   for i in batch['predictions']))
    layers = layer_scores(native,scoring,permit,main,batch,inputs,out)
    descriptive,squared = descriptive_scores(native,scoring,permit,main,batch,inputs)
    own = code.get('own_stage_dispositions')
    if own is None:
        own = {n:dict(state='PENDING') for n in ('A2B-1','A2B-2','A2LABEL','PC','PCX','KCX')}
        # Coordinator R6/R10 keeps the optional KCX turn unreachable.
        own['KCX'] = dict(state='NOT_RUN',reason='A8NR_AUTHOR')
    own = dict(own,DLY8=dly_stage(*[read_json(checked(i)) for i in inputs['DLY8']]))
    registered_three = any(r['stage'] == 'R8_news_seeds' for r in batch['stage_dispositions'])
    canonical = stage_table(main['stage_dispositions'],dispositions,batch['stage_dispositions'],own,registered_three)
    payload = dict(schema='A8BATCH_POSTSCORE_INPUTS_V1',state='A8BATCH_SCORED',bootstrap_draws=DRAWS,
        identities=dict(a8_freeze_sha256=sha(CONF/'A8/A8_FREEZE.json'),fixed_facts_sha256=sha(CONF/'A8/FIXED_FACTS_A8.json'),
                        source_receipt_sha256=main_score_receipt['sha256']),
        conf_seal_sha256=batch['conf_seal_sha256'],code_freeze=batch['code_freeze'],
        scorer_code_freeze=identity(OUT/'SCORER_CODE_FREEZE.json') if (OUT/'SCORER_CODE_FREEZE.json').exists() else None,
        loss_export=identity(losses),seal=identity(state/'SEAL_A8BATCH.json'),
        scoring_parity=parity,CS8=dict(stage_dispositions=dispositions,**cs8),families=families,
        descriptive=descriptive,squared_loss=squared,CPS8=layers['CPS8'],DLY8=layers['DLY8'],sealed_inputs=inputs,stage_dispositions=batch['stage_dispositions'],
        canonical_stage_rows=canonical['rows'],stage_counts=canonical['counts'],rerun_stages=canonical['rerun_stages'],
        batch_parity_failed=batch.get('batch_state') == 'NOT_RUN_PARITY_FAILED',
        canonical_stage_scope='scoring-time rows; own postscore rows require terminal receipts at fill',
        stage_id_map={'R8_notice':'A8B-R8N','R8_news':'A8B-R8','R8_news_seeds':'A8B-R8S','CPS8':'A8B-CPS8','PCX_extension':'PCX',
                      **{n:'A8B-CPS8' for n in ('CPS8_selection_news','CPS8_selection_notice','CPS8_D_news','CPS8_D_notice')}},
        stage_table_builder='stage_table(main_rows, CS8.stage_dispositions, batch_rows, own_run_dispositions, three)',
        fill3f_field_names=dict(relation=['state','class','fully_checked','seeds_run'],checks=['one_day','seven_day','hln','hac7','three_seed','family_interval']),
        primary_readings_replaced=False,partial_predictions_scored=False)
    write_json(out/'A8BATCH_POSTSCORE_INPUTS.json',payload,exclusive=True)
    return payload

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--conf-score-receipt',required=True)
    parser.add_argument('--rs8-base',help='Verified upstream FILL3F_A8_V1 record; no primary inference by this adapter')
    args = parser.parse_args()
    require(args.execute, 'Scoring needs separate post-T5 coordinator execution')
    import a8_freeze,a8_adapter
    a8_adapter.install_audit(OUT/'state')
    code = a8_freeze.verify()
    # ExecutionPermit validates T5 in the frozen CONF guard before any outcome read.
    A = a8_adapter.load(code['adapter_root'],expected=code['adapter_freeze_sha256'],preverified=True)
    a8_adapter.relocate(A,OUT/'state')
    payload = score(OUT/'state',code,A,identity(args.conf_score_receipt))
    if args.rs8_base:
        base_id = identity(args.rs8_base)
        base = read_json(checked(base_id))
        write_json(OUT/'state/scoring/FILL3F_BATCH_RELATIONS.json',fill3f_overlay(base,payload),exclusive=True)
