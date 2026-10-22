'Assemble the statistical readings for the reported comparisons.'
from copy import deepcopy
import read_comparisons as P


def batch_reading(sensitivity_tests,current,inputs):

    raw=deepcopy(inputs.get('a2batch') or {'families':{}})
    for layer in ('l1_family','pd_family'):
        key=sensitivity_tests.BATCH_FAMILY_KEY[layer]
        b=current.get('news/'+layer)
        if b and b['state']=='COMPUTED':raw['families'][key]=b
        elif key not in raw['families']:
            own=inputs['context']['own_stages'][{'l1_family':'A2B-1','pd_family':'A2B-2'}[layer]]
            state=(b or {}).get('state',own['state'])
            if state.startswith('PENDING'):state='PENDING'
            raw['families'][key]=(None if state=='PENDING' else
                dict(state='NOT_RUN_PARITY_FAILED' if state=='DEVIATION' or (b or {}).get('reason')=='A8NR_PARITY' else 'NOT_RUN_BUDGET',reports=[]))
    return raw


def assemble(primary_tests,sensitivity_tests,robustness_tests,current,inputs,design):
    batch=batch_reading(sensitivity_tests,current,inputs)
    tasks={};details={};rows_by_task={}
    pcraw=inputs.get('pc');pcx=inputs.get('pcx')
    pcsha=P.sha256(inputs['_pc_path']) if inputs.get('_pc_path') else None
    for task in P.PAIRS:
        f=current[task+'/primary'];rows=f['reports'];rows_by_task[task]=rows
        seed=(f.get('three_seed') or {}).get('reports',[])
        robust={}
        for i,r in enumerate(rows):
            checks,label,rob=P.six_checks(primary_tests,sensitivity_tests,r,seed[i] if seed else None)
            rob=deepcopy(rob);rob['label']='FRAGILE' if label=='FRAGILE_NFC' else label
            robust[r['arm']+'-'+r['reference']]=rob
        cheap={}
        for r in current[task+'/cheap'].get('reports',[]):cheap[(r['arm'],r['reference'])]=dict(r,state='COMPUTED')


        secondary=[]
        for name,fam in current.items():
            if not name.startswith(task+'/native:') or '__SECONDARY__' not in name:continue
            for r in fam.get('reports',[]):
                secondary.append(dict(arm=r['arm'],reference=r['reference'],
                    state='COMPUTED_SECONDARY' if fam['state']=='COMPUTED' else 'NOT_EVALUABLE_WHOLE_STAGE_UNAVAILABLE',
                    daily_mean_difference=r.get('mean_difference'),p_two_sided=r.get('p_two_sided'),days=fam.get('days')))

        present={(r['arm'],r['reference']) for r in secondary}
        secondary.extend(deepcopy(r) for r in inputs['score_report'].get(task,{}).get('secondary',[]) if (r['arm'],r['reference']) not in present)
        matched=inputs['a2']['tasks'][task].get('p_content_unmatched') or {'state':'NOT_AVAILABLE','matched_keys':0,'total_keys':0,'matched_share_percent':0.,'days_with_matched_key':0}
        attrs=[sensitivity_tests.attribution_a3(task,r['arm'],r['decision'],secondary,cheap,matched) for r in rows]
        combo=current[task+'/combination']
        crob={}
        if combo['state']=='COMPUTED':
            ss=(combo.get('three_seed') or {}).get('reports',[])
            for i,r in enumerate(combo['reports']):
                r['clause_id'],r['sentence']=primary_tests.combination_clause(task,r,rows[i]['decision'])
                checks,label,rob=P.six_checks(primary_tests,sensitivity_tests,r,ss[i] if ss else None)
                rob=deepcopy(rob);rob['label']='FRAGILE' if label=='FRAGILE_NFC' else label
                crob[r['arm']+'-'+r['reference']]=rob
        a3=dict(robustness_a3=robust,design_sensitivities=design[task],attribution_a3=attrs,
            combination=dict(state=combo['state'],family=combo),combination_robustness_a3=crob)
        ts=dict(state='COMPUTED' if seed else 'NOT_AVAILABLE',pairs={r['arm']+'-'+r['reference']:dict(state='COMPUTED',**{'class':r['decision']},effect=r.get('effect_percent_reference_mae'),mean_difference=r.get('mean_difference'),interval95=r.get('interval95_one_day'),interval_family=r.get('interval_family_one_day'),holm_p=r.get('holm_p')) for r in seed})
        def slot(layer):
            rr=current.get(task+'/'+layer,{}).get('reports',[])
            if not rr:return {'state':'NOT_FOUND'}
            r=rr[0]
            return dict(state='COMPUTED' if r['decision']!='NOT_EVALUABLE' else 'NOT_FOUND',
                **{'class':r['decision']},effect=r.get('effect_percent_reference_mae'),mean_difference=r.get('mean_difference'),p_two_sided=r.get('p_two_sided'),interval95=r.get('interval95_one_day'),days=current[task+'/'+layer].get('days'))
        pc=robustness_tests.pc_state_a4(task,pcraw,pcx,pcsha)
        slots=dict(mn=slot('mn'),lear=slot('lear'),shift=slot('shift'),tvn={})
        matched_sentence=inputs['a3']['tasks'][task].get('matched_support',{}).get('sentence',sensitivity_tests.SENTENCES['A3C7'] if task=='notice' else robustness_tests.SENTENCES['A4SUB'])
        tasks[task]=robustness_tests.build_task(task,rows,a3,ts,pc,slots,matched_sentence,incomplete_reason='parity' if f['state']!='COMPUTED' else None)
        details[task]=dict(a3=a3,three_seed=ts,pc=pc,secondary=secondary)
    lear=tasks['news'].get('lear',{})
    extras=dict(lear=lear,combination_ok=all(current[t+'/combination']['state']=='COMPUTED' for t in P.PAIRS),batch=batch,
        batch_differences=robustness_tests.batch_differences('news',rows_by_task['news'],batch),batch_texts=robustness_tests.batch_texts(batch))
    return dict(tasks=tasks,extras=extras,rows=rows_by_task,details=details,caps=robustness_tests.caps(tasks,extras))
