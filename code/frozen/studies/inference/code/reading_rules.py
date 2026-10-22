'Apply the frozen reading rules to numerical comparison results.'
from copy import deepcopy
import read_comparisons as P
from frozen_losses import ast_functions

NAMES=('robust_inc','class_text','rob_quals','quals','clause','mn_text','task_alert',
       'task_sentence','alert_tasks','lear_tail','secondary','any_robust_increment','render_abstract',
       'marks5','gkey','entry5','task5','join','contrast_sentence6','robustness6','combination6','three_seed6','cmap')


def states(record,F,prop=None,apply_a8=True):
    E=F.load_summary_comparisons();D=E.F3D
    tasks={}
    for task,t in record['tasks'].items():
        cs=[]
        for c in t['contrasts']:
            checks=c['checks'];check_order=P.CHECKS if apply_a8 else P.CHECKS[:-1];fail=[k for k in check_order if checks[k]=='FAIL'];unavailable=[k for k in check_order if checks[k]=='UNAVAILABLE']
            rob='FRAGILE' if fail else 'NOT_FULLY_CHECKED' if unavailable else 'ROBUST'
            cs.append(dict(arm=c['arm'],reference=c['reference'],cls=c['class'],robust=rob,
                dissent=fail,unavailable=unavailable,ts=c['three_seed_class'] if c['three_seed_class']!='NE' else 'NA',
                zero=checks['family_interval']=='FAIL' and c['class'] in ('IMP','DET'),
                dd=[],erd=c.get('erd_class'),se=c['effect_percent'],lo=(c['family_one_day'] or [None,None])[0],
                hi=(c['family_one_day'] or [None,None])[1],aud=str(abs(F.decimal(c['effect_aud']))) if c['effect_aud'] else None,
                reason=F.templates()['words']['PLAIN_INC_REASON'][c['reason']],ic='BELOWPT',cb=None,cbl='NOT_FULLY_CHECKED',
                cbn=None,cbnl='NOT_FULLY_CHECKED',cheap='UND',_record=c,_alert=t['alert'],_task=task))
        tasks[task]=dict(scenario='INCOMPLETE' if not t['complete'] else 'B' if any(c['class']=='IMP' for c in t['contrasts']) else 'A',
            reason=F.templates()['words']['PLAIN_INC_REASON'][t['reason']],reason5=t['reason'],contrasts=cs,
            pc='SIZE_FAILS' if t['alert'] else 'SENSITIVITY_FAILS' if t['signal_failed'] else 'NOT_RUN',
            bound=(t['bound'],'below' if float(t['bound'])<(3.8 if task=='news' else .5) else 'at or above',any(F.seven_undefined(c) for c in t['contrasts'] if c['class']!='NE'),any(c.get('mc_unresolved') for c in t['contrasts'])) if t['bound'] else None,
            hist=D.a4mod().sensitivity_tests.HIST_CMP[0],mn=dict(state='COMPUTED',se=t['mn_effect'],cls=t['mn_class']) if t['mn_class']!='NE' else dict(state='NOT_RUN',reason='it was not computed'))
    lear=record['lear']
    ex=dict(lear=dict(state='NOT_RUN',reason=F.templates()['words']['PLAIN_INC_REASON'][lear['reason']]) if lear['class']=='NE' else dict(state='COMPUTED',abs=str(abs(F.decimal(lear['effect']))),lower_higher='lower' if float(lear['effect'])<0 else 'higher',cls=lear['class']),diffs=[],batch={'l1':'PENDING','pd':'PENDING'})
    if prop is not None:
        incomplete_slots=tasks
        design={t:prop['details'][t]['a3']['design_sensitivities'] for t in P.PAIRS}
        rs=D.build_rs6(D.a4mod(),prop,design)
        tasks,ex=rs['tasks'],rs['extras']
        for task,t in tasks.items():
            if t['scenario']=='INCOMPLETE':
                t['contrasts']=incomplete_slots[task]['contrasts']
        for task,t in tasks.items():
            for c,entry in zip(t['contrasts'],record['tasks'][task]['contrasts']):
                c.update(_record=entry,_alert=record['tasks'][task]['alert'],_task=task)
                if not apply_a8:continue
                checks=entry['checks'];c['dissent']=[k for k in P.CHECKS if checks[k]=='FAIL'];c['unavailable']=[k for k in P.CHECKS if checks[k]=='UNAVAILABLE']
                c['robust']='FRAGILE' if c['dissent'] else 'NOT_FULLY_CHECKED' if c['unavailable'] else 'ROBUST'
    return D,tasks,ex


def render(F,record,apply_a8=True,prop=None):
    D,tasks,ex=states(record,F,prop,apply_a8)
    forms=deepcopy(D.F6);words=deepcopy(D.WD);calls=[]
    words['CHECK_SHORT']['family_interval']=F.templates()['words']['CHECKS6']['family_interval']
    ns=dict(F6=forms,WD=words,RANK=D.RANK,CONTENT_ARMS=D.CONTENT_ARMS,SOURCES=D.SOURCES,require=P.require,
        a4mod=D.a4mod,FillError=P.Refusal)
    ast_functions(P.MS/'sensitivity_comparisons_conf_results.py',NAMES,ns)
    def emit(key,**slots):
        calls.append(dict(id=key,slots={k:str(v) for k,v in slots.items()}))
        return (F.form(key,**slots) if key in F.templates()['forms'] else F.inherited_form(key,**slots))
    if not apply_a8:
        ns['form']=lambda key,**slots:forms[key].format(**slots)

        actual=ns['render_abstract'](tasks,ex,'N0')
        P.require(actual==D.render_abstract(tasks,ex,'N0'),'Exact A6/A7 N0 call graph differs')
        return actual,[]

    words['POSITION']={k:'' for k in words['POSITION']}
    words['CHEAP_N']={k:'' for k in words['CHEAP_N']}
    words['ALERT_TASKS']=deepcopy(F.templates()['words']['PFMIN_ALERT_TASKS'])
    forms['A6CB_NA']='';forms['A6CB_N']='';forms['A6HN']='';forms['A6CTX']=''
    forms['A6ENV']=F.form('A8SEVEN')
    forms['A6IVN']=''
    forms['A6ATTR']=F.form('A8ATTR')
    def frm(key,**slots):
        if key in ('A6Y0','A6Y1','A6Y3','A6Y3NE','A6LT0','A6LT1','A6LT3','A6LT_NE'):


            lear=record['lear']
            if lear['class']=='NE':return emit('A8LEAR_NE',reason=F.templates()['words']['PLAIN_INC_REASON'][lear['reason']])
            return emit('A8LEAR',abs=str(abs(F.decimal(lear['effect']))),lower_higher='lower' if F.decimal(lear['effect'])<0 else 'higher',cls=F.templates()['words']['PLAIN_LEAR_CLASS'][lear['class']])
        if key in ('A6CB_N','A6CB_NA','A6HN','A6CTX'):return ''
        if key=='A6BOUND' or key=='A6BOUND_NC':
            return emit('A8BOUND_NC' if key.endswith('_NC') else 'A8BOUND',X=slots['X'],seven='',sens='')
        if key=='A6MC':return emit('A8MC',**slots)
        if key=='A6ALERT':return emit('A8ALERT',**slots)
        if key=='A6SENS_A':return emit('A8SENS_A')
        if key=='A6SENS_B':return emit('A8SENS_B')
        return emit(key,**slots)
    ns['form']=frm
    for old in ('A6R1','A6R2','A6R3','A6R4','A6SEED','A6TS','A6NA','A6FT_F','A6FT_N'):
        replacement={'A6R1':'A8R1','A6NA':'A8NA'}.get(old)
        if replacement and replacement in F.templates()['forms']:forms[old]=F.form(replacement)
    original_quals=ns['quals'];original_class=ns['class_text'];original_rob=ns['rob_quals']
    ns['robust_inc']=lambda c:c['cls']=='IMP' and c['robust']=='ROBUST' and not c.get('_alert')
    def class_text(c,r):
        value=F.templates()['words']['PLAIN_CLASS']['IMP_NC'] if c['cls']=='IMP' and c.get('_alert') else original_class(c,r)
        if c['cls'] in ('IMP','DET') and c.get('zero'):
            value=value.removesuffix('; family-adjusted interval includes zero').removesuffix(', although its family-adjusted interval includes zero')
            value+=F.form('A8Z',level=D.a4mod().sensitivity_tests.LEVEL_TEXT[c['_task']])
        if c['cls']!='NE' and F.seven_undefined(c['_record']):value+=F.form('A8SEVEN')
        return value
    ns['class_text']=class_text
    ns['rob_quals']=lambda c,r:[] if c.get('_alert') and c['cls']=='IMP' and c['robust']=='ROBUST' else original_rob(c,r)
    def quals(source,c,r,conclusion=False):
        q=[v for v in original_quals(source,c,r,conclusion) if v]
        if c.get('_alert') and c['cls']=='IMP':q=[v for v in q if v!=forms['A6NA']]+[F.form('A8NA_NC')]
        return q
    ns['quals']=quals
    text=ns['render_abstract'](tasks,ex,'N0')


    detail=[]
    for task,t in tasks.items():
        for c in t['contrasts']:
            entry=c['_record']
            if entry['class']=='NE':
                detail.append(dict(id='A8H4',slots=dict(arm=F.templates()['names'][entry['arm']],activity=F.templates()['words']['PLAIN_ACTIVITY_REF'][task].removesuffix(' reference'),reason=F.templates()['words']['PLAIN_INC_REASON'][entry['reason']])))
                continue
            def detail_form(key,**slots):
                primary=key in ('A6H1','A6H2','A6H2F','A6H3','A6H3F')
                if key.startswith('A6S_'):key='A8S_'+key.removeprefix('A6S_').removesuffix('_NC')
                if key=='A6TS':
                    key='A8SEED';slots=dict(e3=entry['three_seed_effect'],c3=F.templates()['words']['PLAIN_C3'][entry['three_seed_class']])
                if key=='A6PB_NEG':return ''
                if key=='A6C1':key='A8ATTR'
                if key in ('A6H1','A6H2','A6H2F','A6H3','A6H3F'):
                    slots.update(arm=F.templates()['names'][entry['arm']],activity=F.templates()['words']['PLAIN_ACTIVITY_REF'][task].removesuffix(' reference'),se=entry['effect_percent'],lo=entry['family_one_day'][0],hi=entry['family_one_day'][1],p='p = '+entry['holm_p'])
                    if t.get('pc') in ('SIZE_FAILS','BOTH_FAIL') and entry['class']=='IMP':
                        key='A8H2_NC';slots.update(record['tasks'][task]['negative_control'])
                    fail=[F.templates()['words']['CHECKS6'][k] for k,v in entry['checks'].items() if v=='FAIL']
                    unavailable=[F.templates()['words']['CHECKS6'][k] for k,v in entry['checks'].items() if v=='UNAVAILABLE']
                    if fail:slots['robustness']=F.inherited_form('A6R2',dissent_list=F.join(fail))
                    elif not unavailable:slots['robustness']=F.form('A8R1')
                    if unavailable:


                        phrase=D.a4mod().primary_tests.SENTENCES['R3'].format(unavailable_list=F.join(unavailable),was_were='was' if len(unavailable)==1 else 'were',reason='; '.join(D.a4mod().primary_tests.UNAVAILABLE_PHRASE.get(k,D.a4mod().primary_tests.STATE_PHRASE['UNDEFINED']) for k in unavailable))
                        slots['robustness']=(slots['robustness']+'; ' if fail else '')+phrase
                    if record['tasks'][task]['alert'] and entry['class']=='IMP' and not fail and not unavailable:slots['robustness']='all six uncertainty checks agreed with the decision class'
                pattern=F.templates()['forms'].get(key)
                if pattern is None:
                    try:pattern=D.F6[key]
                    except KeyError:pattern=F.inherited_form(key,**slots)
                import re
                keys=set(re.findall(r'\{(\w+)\}',pattern))
                slots={k:str(v) for k,v in slots.items() if k in keys}
                if primary and slots.get('zero'):slots['zero']=F.form('A8Z',level=D.a4mod().sensitivity_tests.LEVEL_TEXT[task])
                if primary:detail.append(dict(id=key,slots=slots))
                return F.form(key,**slots) if key in F.templates()['forms'] else F.inherited_form(key,**slots)
            ns['form']=detail_form


            sent,key=ns['contrast_sentence6'](D.a4mod(),task,c,prop['tasks'][task])
            P.require(detail[-1]['id'] in ('A6H1','A6H2','A6H2F','A6H3','A6H3F','A8H2_NC'),'Native primary branch not traced')
    ns['form']=frm


    for key in ('A4AB_PDS','A6IVN','A6ATTR','A6ENV','A6SENS_A','A6SENS_B'):
        if key in forms and forms[key]:calls.append(dict(id='A8ATTR' if key=='A6ATTR' else key,slots={}))
    calls.append(dict(id='A4AB_PDS',slots={}))
    suffix=[]
    for task,t in record['tasks'].items():
        if task=='notice':
            clk=t['clk8']
            if clk['state']=='INFORMATIVE':
                suffix.append(dict(id='A8CLK_OK',slots=dict(X=clk['public_by_admission'],n=str(clk['covered_n']))) if F.clock_ok(clk) else dict(id='A8CLK_LATE',slots=dict(Y=str(100-F.decimal(clk['public_by_admission'])),Z=clk['maximum_delay_minutes'],n=str(clk['covered_n']))))
            else:suffix.append(dict(id='A8CLK_NR' if clk['state']=='NOT_RUN' else 'A8CLK_NI',slots=dict(reason=F.clock_reason(clk))))
        for c in t['contrasts']:
            if c['class']=='IMP':suffix.append(dict(id='A8CONC_QUAL',slots=dict(increments=F.templates()['names'][c['arm']],exposure=F.form('A8EXPOSURE'),cutoff=F.form('A8CUTOFF'))))
        from consumer_fields import identify_sentence
        for value in F.relation_sentences(task,t,F.templates(),'P0'):
            suffix.append(identify_sentence(F,value,[F.templates()['forms']]))
    def expansion(entry):
        return F.form(entry['id'],**entry['slots']) if entry['id'] in F.templates()['forms'] else F.inherited_form(entry['id'],**entry['slots'])


    candidates=[(expansion(e),e) for e in calls if e['id'] not in ('A6ENV','A6SENS_A','A6SENS_B')]
    entries=[];cursor=0
    while cursor<len(text):
        if text[cursor]==' ':cursor+=1;continue
        matches=[(v,e) for v,e in candidates if v and text.startswith(v,cursor)]
        P.require(matches,'Unbound N0 frozen text at '+str(cursor))
        v,e=max(matches,key=lambda x:len(x[0]));entries.append(e);cursor+=len(v)
    from table_renderer.reading_metadata import expected_slots
    for item in detail:
        match=[(task,c) for task,t in record['tasks'].items() for c in t['contrasts'] if item['slots'].get('arm')==F.templates()['names'][c['arm']] and item['slots'].get('activity')==F.templates()['words']['PLAIN_ACTIVITY_REF'][task].removesuffix(' reference')]
        P.require(len(match)==1,'N0 primary identity census')
        task,c=match[0]
        item['slots']=expected_slots(record,task,c,item['id'])
    entries.extend(detail)
    entries.extend(suffix)
    from table_renderer.constraint_contract import render_sequence
    rendered=render_sequence(entries,record=record)

    rendered=F.rename_rendered(rendered)
    return rendered,entries


def form_sequence(F,record,families,prop=None):
    text,entries=render(F,record,prop=prop)

    record['specified_reading_n0']=text
    record['n0_forms']=entries
    return entries
