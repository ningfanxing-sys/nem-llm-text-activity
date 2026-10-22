'Select each component estimate from its comparison bundle.'
import read_comparisons as P


def fill(F,primary_tests,sensitivity_tests,robustness_tests,record,current):
    components={k:[] for k in ('sesoi','seed','hln','exposure','w2d_npm')}
    def item(label,row,word=None):
        if row is None:return dict(id='FILL2:a1_primary.exposure_item',slots=dict(pair=label,estimate='not available',p='not available',word=F.templates()['words']['PLAIN_C3']['NE']))
        d=robustness_tests.decimals(row.get('interval95_one_day'));lo,hi=primary_tests.fmt_interval(row.get('interval95_one_day'),d)
        estimate=primary_tests.fmt_effect(row.get('effect_percent_reference_mae'),d)+'% ['+lo+', '+hi+']%'
        cls=P.CLASS.get(row.get('decision'),'NE')
        return dict(id='FILL2:a1_primary.exposure_item',slots=dict(pair=label,estimate=estimate,
            p=primary_tests.display_p(row.get('p_two_sided')),word=word or F.templates()['words']['PLAIN_C3'][cls]))
    for task,t in record['tasks'].items():
        for i,c in enumerate(t['contrasts']):
            arm=F.templates()['names'][c['arm']];primary=current[task+'/primary']['reports'][i]
            if c['class']=='IMP':
                key=sensitivity_tests.sesoi_increment_class(primary['effect_percent_reference_mae'],primary['interval_family_one_day'],sensitivity_tests.SESOI[task])
                components['sesoi'].append(dict(id='A8S_'+key,slots=dict(S_phrase=robustness_tests.S_PHRASE[task],S=str(sensitivity_tests.SESOI[task]),tail=sensitivity_tests.TAIL_TEXT[task]))) if key else components['sesoi'].append(dict(id='A8LEVELS',slots={}))
            elif c['class'] in ('NULL','DET') and c['envelope'] is not None:
                components['sesoi'].append(dict(id='A8BOUND_NC' if t['alert'] else 'A8BOUND',slots=dict(X=c['envelope'],seven=F.form('A8SEVEN') if F.seven_undefined(c) else '',sens=F.form('A8SENS_A') if t['signal_failed'] else '')))
            else:components['sesoi'].append(dict(id='A8LEVELS',slots={}))
            for seed in (20260919,20260920,20260921):
                fam=current.get(task+'/primary' if seed==20260919 else task+'/seed_'+str(seed),{})
                r=fam.get('reports',[])
                components['seed'].append(item(arm+' (seed '+str(seed)+')',r[i] if len(r)>i else None))
            components['seed'].append(dict(id='A8SEED',slots=dict(e3=c['three_seed_effect'],c3=F.templates()['words']['PLAIN_C3'][c['three_seed_class']])) if c['three_seed_effect'] is not None else dict(id='A8SEED_NOEST',slots=dict(c3=F.templates()['words']['PLAIN_C3'][c['three_seed_class']])))
            h=dict(primary,p_two_sided=primary.get('hln_holm_p'))
            components['hln'].append(item(arm+' (small-sample t calibration with n-1 degrees of freedom, Holm within the pre-specified family)',h,F.templates()['words']['PLAIN_C3'][P.CLASS[primary['hln_decision']]]))
        exp=current.get(task+'/native:'+task+'__A1_EXPOSURE_EXCLUDED',{})
        for i,c in enumerate(t['contrasts']):
            rows=exp.get('reports',[]);r=rows[i] if len(rows)>i else None
            word='descriptive only' if r else None
            components['exposure'].append(item(F.templates()['names'][c['arm']]+' (exposure-excluded days; descriptive only)',r,word))
    for task,a,b in [('news','W2_D','M'),('notice','NPL','NPM')]:
        fam=current.get(task+'/native:'+task+'__SECONDARY__'+a+'__'+b,{})
        rows=fam.get('reports',[])
        r=rows[0] if rows else None
        components['w2d_npm'].append(item(F.templates()['names'].get(a,a)+' - '+F.templates()['names'].get(b,b),r,
            robustness_tests.CS_WORDS.get(primary_tests.decision_class(r.get('mean_difference'),r.get('p_two_sided')),'not evaluable') if r else None))
    record['section_readings']['a1_components']=components
    return item
