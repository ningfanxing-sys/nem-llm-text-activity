'Fill the result tables using saved numerical and layout functions.'
from copy import deepcopy
import importlib.util
import re
from pathlib import Path
import table_results_conf_results as F

MACRO=lambda task,pair,field:r'\Dres{'+task+'}{'+pair+'}{'+field+'}'


def six_label(c,t):
    if c['class']=='NE':return 'not evaluable'
    if t['alert'] and c['class']=='IMP':return 'increment detected under a negative-control alert'
    fails=F.join(F.templates()['words']['PLAIN_CHECKS'][k] for k in F.CHECKS if c['checks'][k]=='FAIL')
    missing=F.join(F.templates()['words']['PLAIN_CHECKS'][k] for k in F.CHECKS if c['checks'][k]=='UNAVAILABLE')
    if not fails and not missing:return F.form('A8R1')
    return ('fragile: '+fails+' disagreed' if fails else '')+('; ' if fails and missing else '')+('not fully checked: '+missing+' unavailable' if missing else '')


def cheap_sentence(c,t,task):
    if c['class']!='IMP' or t['alert']:return ''
    groups=c.get('cheap_comparators',{})
    pieces=[F.inherited_form(identity,list=F.join(groups[key])) for key,identity in (('beaten','A6CH_BEATEN'),('not_beaten','A6CH_NOT'),('worse','A6CH_WORSE')) if groups.get(key)]
    text=F.join(pieces) if pieces else F.inherited_form('A6CH_NONE')
    if groups.get('unavailable'):
        text+=('; ' if pieces else ', because ')+F.join(groups['unavailable'])+(' was' if len(groups['unavailable'])==1 else ' were')+' not available'
    mapping={'BETTER':'BETTER','WORSE':'WORSE','NOTSHOWN':'NOTSHOWN','NOT_EVALUABLE':'UND','NOT_RUN':'UND'}
    return F.form('A8CHS',documents='articles' if task=='news' else 'notices',seed='; primary seed only' if not F.robust(c) else '',arm=F.templates()['names'][c['arm']],cheap_list=text,cheap_reading=F.inherited_form('A6CHR_'+mapping[c['cheap_text']]))


def detailed_reading(record,task):
    t=record['tasks'][task];T=F.templates();out=list(record['kept_alert_sentences'].get(task,[]))
    for c in t['contrasts']:
        name=T['names'][c['arm']];ref=T['words']['PLAIN_ACTIVITY_REF'][task].removesuffix(' reference')
        q=F.form('A8SEVEN') if c['class']!='NE' and F.seven_undefined(c) else ''
        zero=F.form('A8Z',level='97.5' if task=='news' else '98.3') if c['class'] in ('IMP','DET') and c['family_one_day'][0] is not None and F.decimal(c['family_one_day'][0])<=0<=F.decimal(c['family_one_day'][1]) else ''
        if c['class']=='NE':out.append(F.form('A8H4',arm=name,activity=ref,reason=T['words']['PLAIN_INC_REASON'][c['reason']]))
        elif c['class']=='IMP' and t['alert']:
            nc=t.get('negative_control');F.require(isinstance(nc,dict), 'alert requires the actual planted-null count and interval')
            out.append(F.form('A8H2_NC',arm=name,activity=ref,se=c['effect_percent'],aud=str(abs(F.decimal(c['effect_aud']))),level='97.5' if task=='news' else '98.3',lo=c['family_one_day'][0],hi=c['family_one_day'][1],p=c.get('holm_p','not available'),k0=str(nc['k0']),R0=str(nc['R0']),lo0=nc['lo0'],hi0=nc['hi0'],zero=zero,robustness=six_label(c,t),qualifiers=q))
        elif c['class']=='IMP':
            out.append(increment_detail(c,t,task,zero,q))
        else:
            out.append(F.contrast_sentence(c,T,False,t['alert'])+zero)
        if c['relations']['R8']['state'] in ('SAME','DIFFERENT','NOT_EVALUABLE'):
            data=c.get('r8_result')
            if data:
                out.append(F.form('A8R8_H',arm_words=name,se=data['effect_percent'],level='97.5' if task=='news' else '98.3',lo=data['family_one_day'][0],hi=data['family_one_day'][1],p=data['holm_p'],**{'class':T['words']['PLAIN_C3'][c['relations']['R8']['class']], 'robustness':{'ROBUST':F.form('A8R1'),'FRAGILE':'fragile','NOT_FULLY_CHECKED':'not fully checked','FRAGILE_NFC':'fragile; not fully checked'}[data['label']]}))
            if c['class']=='NULL' and c['relations']['R8']['class']=='IMP':out.append(F.form('A8R8_PRIMARY_NULL'))
        erd=c.get('erd_class')
        if erd is not None:out.append(F.form('A8REL_ERD',names=name,c3=T['words']['PLAIN_C3'][erd]))
        cheap=cheap_sentence(c,t,task)
        if cheap:out.append(cheap)
    from .constraint_contract import render_sequence
    if t.get('shift_forms'):out.append(render_sequence(t['shift_forms']))

    evaluable=[c for c in t['contrasts'] if c['class']!='NE'];ne=[c for c in t['contrasts'] if c['class']=='NE']
    if evaluable and all(F.robust(c,t['alert']) for c in evaluable) and not ne:out.append(F.form('A8R4',task_label=T['words']['PLAIN_TASK_LABEL'][task]))
    if not any(c['class']=='IMP' for c in t['contrasts']) and t['bound'] is not None:
        reference='3.8' if task=='news' else '0.5';mc=any(c.get('mc_unresolved',False) for c in evaluable)
        out.append(F.form('A8H5_NC' if t['alert'] else 'A8H5',names=F.join(T['names'][c['arm']] for c in evaluable),X=t['bound'],tail='98.75' if task=='news' else '99.17',below_or_above='below' if F.decimal(t['bound'])<F.decimal(reference) else 'above',S_phrase=reference+'% of the reference error',env=F.form('A8SEVEN') if any(F.seven_undefined(c) for c in evaluable) else '',mc=F.form('A8MC',S_phrase=reference+'% of the reference error') if mc else '',sens=F.form('A8SENS_A') if t['signal_failed'] else '',ne=F.form('A8H5_NE',ne_names=F.join(T['names'][c['arm']] for c in ne)) if ne else ''))
    windowed_activity=t.get('r8_descriptive')
    if windowed_activity:out.append(F.form('A8R8_DESC',**windowed_activity))
    return '\n\n'.join(out)


@__import__('functools').lru_cache(maxsize=1)
def inherited_generators():
    E=F.load_summary_comparisons();B=E.F3B
    A,F3,F2,robustness_tests=B.deps()
    return B.renderer_class(A,F3,F2,robustness_tests)


def inherited_tables(record,registry):

    R=inherited_generators()
    class Layout:
        layout=staticmethod(lambda text:text)
        fx3b=staticmethod(lambda text,key:text)
    out={}
    for table in record.get('source_tables',[]):
        F.require(table['location'] in ('S7','S9'), 'invalid inherited table location')
        F.require(table['bootstrap_draws']==100000, 'inherited current table must use B=100000')
        rows=[]
        for i,row in enumerate(table['rows']):
            values=[]
            for j,cell in enumerate(row):
                key=f"global/{table['id']}_{i}_{j}/reading";registry[key]=display_cell(cell)
                values.append(MACRO('global',f"{table['id']}_{i}_{j}",'reading'))
            rows.append(' & '.join(values)+r' \\')
        registry['global/'+table['id']+'_caption/reading']=table['caption']
        registry['global/'+table['id']+'_header/reading']=table['header']
        out[table['id']]=R.table3b(Layout(),table['label'],MACRO('global',table['id']+'_caption','reading'),MACRO('global',table['id']+'_header','reading'),rows,table['spec'])
    return out


def inherited_figure(record):

    R=inherited_generators();rows=deepcopy(record['forest_rows'])
    F.require(all(r['bootstrap_draws']==100000 for r in rows), 'figure intervals must use B=100000')
    class Forest:
        primary_tests=type('primary_tests',(),{'SESOI':{'news':3.8,'notice':.5}})
        forest_rows3b=lambda self:rows
    return R.forest(Forest())


def increment_detail(c,t,task,zero,q):
    from .constraint_contract import render_sequence
    T=F.templates();common=dict(arm=T['names'][c['arm']],activity=T['words']['PLAIN_ACTIVITY_REF'][task].removesuffix(' reference'),
        se=c['effect_percent'],aud=str(abs(F.decimal(c['effect_aud']))),level='97.5' if task=='news' else '98.3',lo=c['family_one_day'][0],hi=c['family_one_day'][1],p=c.get('holm_p','not available'),
        zero=zero,robustness=six_label(c,t),qualifiers=q,benchmark=render_sequence(c.get('benchmark_forms',[])))
    if F.robust(c):
        lo=-max(F.interval(c['family_one_day'])[1],F.interval(c['family_seven_day'])[1]);hi=-min(F.interval(c['family_one_day'])[0],F.interval(c['family_seven_day'])[0]);point=-F.decimal(c['effect_percent']);bound=F.Decimal('3.8' if task=='news' else '0.5')
        key='BEYOND' if lo>bound else 'BELOW' if hi<bound else 'ABOVE' if point>bound else 'BELOWPT'
        slots=dict(S_phrase=str(bound)+'% of the reference error',S=str(bound))
        if key in ('BEYOND','BELOW'):slots['tail']='98.75' if task=='news' else '99.17'
        return F.inherited_form('A6H2',**common,attribution=F.inherited_form('A6C1',activity=common['activity']),position=F.form('A8S_'+key,**slots))
    seed=F.form('A8SEED',e3=c['three_seed_effect'],c3=T['words']['PLAIN_C3'][c['three_seed_class']]) if c['three_seed_effect'] is not None else F.form('A8SEED_NOEST',c3=T['words']['PLAIN_C3'][c['three_seed_class']])
    return F.inherited_form('A6H2F',**common,three_seed=seed,test_note=F.inherited_form('A6FT_F' if 'FAIL' in c['checks'].values() else 'A6FT_N'))


def relation_display(record,task,c,layer):
    T=F.templates();r=c['relations'][layer];state=r['state']
    if state=='PENDING':return 'pending (no result file when filled)'
    if state=='NOT_APPLICABLE' or layer=='DLY8' and task=='news':return 'not applicable'
    if state in ('NOT_RUN','NOT_EVALUABLE'):
        reason=F.relation_reason(r,layer,F.task_context(record,task))
        return ('not run' if state=='NOT_RUN' else 'not evaluable')+' ('+reason+')'
    words=T['words']['PLAIN_C3']
    prefix='; '.join(k+' minutes: '+words.get(c['delay_classes'][k],'not evaluable') for k in ('5','15','60'))+'; ' if layer=='DLY8' else ''
    result=prefix+('same reading' if state=='SAME' else 'different reading')+'; '+words.get(r['class'],'not evaluable')
    if layer=='CPS8' and r.get('g0_class'):result+='; schedule-matched control: '+words[r['g0_class']]
    return result


def finish_slots(record,out,registry,manifest):
    from .constraint_contract import render_sequence,hrc_render
    T=F.templates()
    registry['global/overview/reading']='See the evaluation readings in the main article.'
    hrc=F.human_review_sentences(record)
    registry['global/hrc_historical/reading']=' '.join(s for s in hrc if s in (F.form('A8HRC_PENDING'),F.form('A8HRC_POST',what='100 news articles, 60 notices and 20 historical pairs')))

    out['TABLE_RESULTS_fixed.tex']=MACRO('global','author','reading')+'\n'+(MACRO('global','pv','reading')+'\n' if F.prospective_sentence(record) else '')
    if record.get('hrc_results'):
        sentence,table=hrc_render(record,registry)
        registry['global/human_results/reading']=sentence+' '+registry['global/hrc/reading']
        out['TABLE_RESULTS_human.tex']=MACRO('global','human_results','reading')+'\n'
        out['TABLE_RESULTS_human_tables.tex']=table+'\n'
    else:
        out['TABLE_RESULTS_human.tex']=MACRO('global','hrc','reading')+'\n';out['TABLE_RESULTS_human_tables.tex']=''
    for k,v in record.get('declarations',{}).items():registry['global/declaration_'+k+'/reading']=v
    auth=record.get('author_a3_a6')
    if auth:
        E=F.load_summary_comparisons();addenda,dates=E.validate_author_confirmation(auth['data'])
        text=E.F7['A7AUTH'].format(dates=E.format_dates(dates),label='T5',seventh=F.form('A8AUTH_NO7') if record['seventh_separate_approval'] is False else E.F7['A7AUTH_SEVENTH'])
        registry['global/author_a3_a6/reading']=iso_dates(F.rename_rendered(text))
        out['TABLE_RESULTS_author_a3_a6.tex']=MACRO('global','author_a3_a6','reading')+'\n'
    else:out['TABLE_RESULTS_author_a3_a6.tex']=''
    readings=record.get('section_readings',{})
    registry['global/section_readings/reading']='\n\n'.join(render_sequence(readings.get(k,[]),alert=any(t['alert'] for t in record['tasks'].values())) for k in ('e3','a1','pc'))
    registry['global/section_readings/reading']+='\n\n'+'\n\n'.join(render_sequence(items) for items in readings.get('a1_components',{}).values())
    out['TABLE_RESULTS_section_readings.tex']=MACRO('global','section_readings','reading')+'\n'
    registry['global/combinations/reading']=render_sequence(readings.get('combinations',[]))+(' An averaged forecast that improves on the averaged reference need not beat the strong benchmark alone.' if readings.get('combinations') else '')
    out['TABLE_RESULTS_combinations.tex']=MACRO('global','combinations','reading')+'\n'
    rows=[]
    for label in ('T0','T1','T2','T3','T4','T4A','T4B','T5'):
        t=record['timestamps'].get(label)
        if t:
            content=T['frozen_templates']['timestamp_content_'+label] if 'timestamp_content_'+label in T['frozen_templates'] else historical_timestamp_content(label)
            content=F.rename_rendered(content)
            rows.append(' & '.join(F.tex(str(x)) for x in (label,content,len(t['files']),t['utc'],t.get('freetsa_utc','unavailable'),t.get('digicert_utc','unavailable')))+r' \\')
    out['TABLE_RESULTS_timestamp_table.tex']=r'\begin{longtable}{lp{.4\linewidth}rlll}'+'\n'+r'\caption{Trusted timestamp records of the evaluation design (UTC).}\label{supp:tab:timestamps}\\'+'\n'+r'Label & Content & Files & Record UTC & FreeTSA & DigiCert \\'+'\n'+'\n'.join(rows)+'\n'+r'\end{longtable}'+'\n'

    branches=F.branch_sentences(record)
    ps=[s for s in branches if s.startswith('The planted-signal check was not run') or s.startswith('For ') and 'planted-signal' in s]
    registry['global/branches/reading']=' '.join(s for s in branches if s not in ps)
    registry['global/planted_cap/reading']=' '.join(ps)
    out['TABLE_RESULTS_tables.tex']+=MACRO('global','planted_cap','reading')+'\n'
    from .prepare_table_fields import cited
    out['TABLE_RESULTS_RS8_N0.tex']=cited(record['specified_reading_n0'])+'\n'
    registry['global/stages/reading']=F.stage_text(record)

    if record.get('specification2_sha256'):
        from .constraint_contract import specification2
        b=specification2();F.require(b and b['sha256']==record['specification2_sha256'],'invalid specification 2 producer binding')
        for i,row in enumerate(F.stage_rows(record)):
            if row['stage']=='A8B-R8' and row['reason']=='A8NR_RESOURCE_A8AM2':
                registry['global/stage'+str(i)+'/postseal']=b['record']['changes']['FILL3f']+' ('+F.reason_text(row['reason'])+')'
    out['TABLE_RESULTS_RS8_2000.tex']=F.tex('Frozen 2,000-draw reading')+r'\par'+'\n'+F.tex(F.rename_rendered(record['specified_reading_2000']))+'\n'


def complete_bundle(record,bindings,out,manifest):
    registry=manifest['registry'];T=F.templates()


    stages={row['stage']:row for row in F.stage_rows(record)}
    for optional,stage in (('KCX','KCX'),('matched_controls','matched_controls'),('R8','A8B-R8')):
        if stages[stage]['counted_category']==F.CATEGORIES[4]:
            registry['global/'+optional+'/status']=F.CATEGORIES[4]
    reasons=record.get('squared_not_run_reasons',{})
    for task,t in record['tasks'].items():
        for c in t['contrasts']:
            pair=c['arm']+'-'+c['reference'];sq=c['squared_loss']
            if sq['state']=='NOT_RUN':
                reason=reasons.get(task,{}).get(pair)
                phrase=T['words']['PLAIN_INC_REASON'].get(reason) if reason in T['words']['PLAIN_INC_REASON'] else F.reason_text(reason) if reason else None
                registry[task+'/'+pair+'/squared']='Squared-loss descriptive: not run'+(' ('+phrase+')' if phrase else '')+'.'

    if record.get('n0_forms') is not None:
        for item in record['n0_forms']:
            if item['id']=='A8EST':
                from .prepare_table_fields import estimand
                expected=''
                F.require(item['slots'].get('cw')==expected, 'R13: CW clause must remain inactive')
        from .constraint_contract import render_sequence

        n0=render_sequence(record['n0_forms'],record=record)

        F.require(n0==record['specified_reading_n0'],'N0 differs from its exact frozen form sequence')
    for task,t in record['tasks'].items():
        for c in t['contrasts']:
            key=f"{task}/{c['arm']}-{c['reference']}/"
            if c.get('mc_unresolved'):registry[key+'envelope']+=F.form('A8MCC')

    for task,t in record['tasks'].items():
        for c in t['contrasts']:
            key=f"{task}/{c['arm']}-{c['reference']}/";q=F.form('A8SEVEN') if c['class']!='NE' and F.seven_undefined(c) else ''
            registry.update({key+'label':six_label(c,t),key+'effect':registry[key+'effectPercent'],key+'aud':registry[key+'effectAUD'],key+'lo':(c['family_one_day'][0] if c['family_one_day'] else 'not evaluable'),key+'hi':(c['family_one_day'][1] if c['family_one_day'] else 'not evaluable'),key+'threeseed':T['words']['PLAIN_C3'][c['three_seed_class']],key+'windowed_activity':relation_display(record,task,c,'R8'),key+'dly15':relation_display(record,task,c,'DLY8'),key+'kcx':relation_display(record,task,c,'KCX'),key+'erd':T['words']['PLAIN_C3'].get(c.get('erd_class'),'not run'),key+'seven':q,key+'bound':registry[key+'envelope'],key+'alert':'negative-control alert' if t['alert'] else 'no negative-control alert'})
        registry[task+'/task/detail']=detailed_reading(record,task)
        registry[task+'/task/secondary']=' '.join(F.secondary_sentences(record))
    for task,t in record['tasks'].items():
        for c in t['contrasts']:
            if t['alert'] and c['class']!='NE' and c['envelope'] is not None:
                registry[task+'/'+c['arm']+'-'+c['reference']+'/bound']+=r'$^{c}$'
    registry['global/shared/reading']=F.form('A8SHARED')
    registry['global/supplement/reading']='\n\n'.join(detailed_reading(record,task) for task in F.ARMS)
    registry['global/plant/reading']=F.form('A8P1')+((' '+F.form('A8P1N',n1=record['pc_daily_refit_comparison'])) if record.get('pc_daily_refit_comparison') else '')
    registry['global/author_no7/reading']=F.form('A8AUTH_NO7') if record.get('seventh_separate_approval') is False else ''
    registry['global/deviations/reading']=' '.join(F.form('A8DEVIATION',what=d['what'],label=d['label']) for d in record.get('deviations',[]) if d['timestamp_verified'] is True)
    for d in record.get('deviations',[]):F.require(d['timestamp_verified'] is True and d.get('pre_deviation_reading') and d.get('post_deviation_reading'), 'deviation needs separate verified timestamp and both readings')
    tables=inherited_tables(record,registry)
    out['TABLE_RESULTS_detail.tex']='\n\n'.join(MACRO(task,'task','detail') for task in F.ARMS)+'\n'
    out['TABLE_RESULTS_S7.tex']= '\n'.join(tables[t['id']] for t in record.get('source_tables',[]) if t['location']=='S7')+'\n'+MACRO('global','supplement','reading')+'\n'+ '\n'.join(MACRO(task,c['arm']+'-'+c['reference'],'squared')+r'\par' for task,t in record['tasks'].items() for c in t['contrasts'])+'\n'
    out['TABLE_RESULTS_sensitivity.tex']=''
    out['TABLE_RESULTS_S9.tex']='\n'.join(tables[t['id']] for t in record.get('source_tables',[]) if t['location']=='S9')+'\n'
    out['TABLE_RESULTS_shared.tex']=MACRO('global','shared','reading')+'\n'
    out['TABLE_RESULTS_plant.tex']=MACRO('global','plant','reading')+'\n'
    out['TABLE_RESULTS_deviations.tex']=MACRO('global','deviations','reading')+'\n'+''.join('Pre-deviation reading: '+F.tex(d['pre_deviation_reading'])+'\n'+'Post-deviation reading: '+F.tex(d['post_deviation_reading'])+'\n' for d in record.get('deviations',[]))
    registration=F.registration_fixed(record)
    registry['global/registration_protocol/reading']=F.form('A8EV_PRIVATE')
    registry['global/registration_limit/reading']=F.form('A8LIM_PRIVATE') if F.form('A8LIM_PRIVATE') in registration else registration[0]
    registry['global/contribution/reading']=F.form('A8CONTRIB2_PRIVATE')
    for name,key in [('registration_protocol','registration_protocol'),('registration_limit','registration_limit'),('contribution','contribution')]:out['TABLE_RESULTS_'+name+'.tex']=MACRO('global',key,'reading')+'\n'

    out['TABLE_RESULTS_captions.tex']='% Frozen captions, verified by ID at generation.\n'+''.join('\\expandafter\\def\\csname TABLE_RESULTScaption@'+key+r'\endcsname{'+F.frozen_template(key,**({'marks':(F.load_summary_comparisons().TP7['table6_mark_nc'] if any(t['alert'] for t in record['tasks'].values()) else '')+(T['frozen_templates']['table6_mark_seven'] if any(c['class']!='NE' and F.seven_undefined(c) for t in record['tasks'].values() for c in t['contrasts']) else '')+(T['frozen_templates']['table6_mark_mc'] if any(c.get('mc_unresolved',False) for t in record['tasks'].values() for c in t['contrasts']) else ''),'table_ref':'\\ref{tab:main_comparisons-sensitivity}'} if key=='table6_caption' else {}))+ '}\n' for key in ('table6_caption','figure_caption','dly8_caption','cps8_caption','r8_caption','kcx_caption','clk8_caption'))
    out['TABLE_RESULTS_primary_intro.tex']=F.frozen_template('primary_intro')+'\n'
    out['TABLE_RESULTS_figure.tex']='\\begin{figure}[htbp]\\centering\\includegraphics[width=\\linewidth]{figures/TABLE_RESULTS_forest.pdf}\\caption{\\csname TABLE_RESULTScaption@figure_caption\\endcsname}\\label{fig:main_comparisons-forest}\\end{figure}'+'\n'
    rows=[]
    for task,t in record['tasks'].items():
        for c in t['contrasts']:
            pair=c['arm']+'-'+c['reference'];key=task+'/'+pair+'/'
            registry[key+'holm']=(c.get('holm_p') or 'not evaluable') if c['class']!='NE' else 'not evaluable'
            registry[key+'family_interval']=('$['+', '.join(c['family_one_day'])+']$%'+registry[key+'seven']) if c['family_one_day'] else 'not evaluable'
            registry[key+'dissent']=F.join(T['words']['PLAIN_LAYER'][k] for k in list(dict.fromkeys(c['design_layers']+(['dly8_15'] if c['relations']['DLY8']['state']=='DIFFERENT' else [])+(['cps8'] if c['relations']['CPS8']['state']=='DIFFERENT' else [])))) or '--'
            cells=[MACRO(task,pair,k) for k in ('aud','effect')]+[MACRO(task,pair,'family_interval')]+[MACRO(task,pair,k) for k in ('bound','holm','class','label','dissent')]
            rows.append(F.tex(display_pair(task,c))+' & '+' & '.join(cells)+r' \\')
    out['TABLE_RESULTS_tables.tex']=r'\begin{longtable}{lp{.06\linewidth}p{.06\linewidth}p{.10\linewidth}p{.06\linewidth}p{.05\linewidth}p{.12\linewidth}p{.12\linewidth}p{.12\linewidth}}'+'\n'+'\\caption{\\csname TABLE_RESULTScaption@table6_caption\\endcsname}\\label{tab:main_comparisons-primary}\\\\'+'\n'+r'Task and contrast & AUD/MWh & Effect & Family interval & Envelope & Holm & Reading & Inference checks & Design dissent \\'+'\n'+'\n'.join(rows)+'\n'+r'\end{longtable}'+'\n'+'\n'
    out['TABLE_RESULTS_tables.tex']=out['TABLE_RESULTS_tables.tex'].replace(r'\begin{longtable}{lllllp{.35\linewidth}}',r'\begin{longtable}{lllllp{.35\linewidth}}'+'\n'+'\\caption{\\csname TABLE_RESULTScaption@table6_caption\\endcsname}\\label{tab:main_comparisons-primary}\\\\')
    supp=[]
    for layer,caption in (('DLY8','dly8_caption'),('CPS8','cps8_caption'),('R8','r8_caption'),('KCX','kcx_caption'),('CLK8','clk8_caption')):
        rows=[]
        for task,t in record['tasks'].items():
            if layer=='CLK8':
                if task=='notice':
                    registry['global/clock/reading']=F.clk_sentence(t)
                    registry['global/clock_codes/reading']='Listing diagnostic: '+(F.clock_reason(t['clk8']) if t['clk8']['reason_codes'] else 'no listing problems')+'.'
                    rows.append(MACRO('global','clock_codes','reading')+r' \\')
                    rows.append(MACRO('global','clock','reading')+r' \\')
                    rows.extend(clock_rows(record,registry))
                continue
            for c in t['contrasts']:
                rel=c['relations'][layer];pair=c['arm']+'-'+c['reference'];field='support_'+layer
                if layer=='DLY8' and task!='notice':continue
                registry[f'{task}/{pair}/{field}']=relation_display(record,task,c,layer)
                if layer=='CPS8' and c['relations'][layer]['state'] in ('SAME','DIFFERENT'):
                    registry[f'{task}/{pair}/{field}']+='; selected grid: '+str(c['relations'][layer]['selected_grid'])
                rows.append(F.tex(display_pair(task,c))+' & '+MACRO(task,pair,field)+r' \\')
        if layer=='CPS8' and record.get('cps8_selection'):
            for task,data in record['cps8_selection']['data'].items():
                for arm,grid in data.items():
                    key='cpsgrid_'+task+'_'+arm
                    registry['global/'+key+'/reading']=T['names'].get(arm,arm)+(': selected grid point g'+str(grid)+'.' if grid is not None else ': selected grid not available.')
                    rows.append(F.tex(task)+' & '+MACRO('global',key,'reading')+r' \\')
        if layer=='CLK8':header='Clock reading';spec='p{.9\\linewidth}'
        else:header=r'Task and contrast & Reading \\';spec='lp{.7\\linewidth}'
        R=inherited_generators()
        class Layout:
            layout=staticmethod(lambda text:text)
            fx3b=staticmethod(lambda text,key:text)
        supp.append(R.table3b(Layout(),'supp:tab:table_results-'+layer.lower(),'\\csname TABLE_RESULTScaption@'+caption+r'\endcsname',header,rows,spec))
    out['TABLE_RESULTS_support.tex']='\n'.join(supp)+'\n'+r8_extra(record,registry)
    out['TABLE_RESULTS_abstract.tex']=T['frozen_templates']['abstract_marker']+'\n'+out['TABLE_RESULTS_abstract.tex']
    times=record['timestamps']
    if all(k in times for k in ('T4','T4A','T4B','T5')):
        out['TABLE_RESULTS_timestamps.tex']=F.frozen_template('design_timestamps',labels='T0, T1, T2, T3, T4, T4A, T4B and T5',t4a='T4A',t4b='T4B',t5='T5',time4a=utc_display(times['T4A']['utc']),time4b=utc_display(times['T4B']['utc']),time5=utc_display(times['T5']['utc']))+'\n'
    else:out['TABLE_RESULTS_timestamps.tex']=''
    finish_slots(record,out,registry,manifest)
    manifest['expected']['main']=[registry[task+'/task/lead'] for task in F.ARMS]+[manifest['expected']['main'][-4],registry['global/registration_protocol/reading'],registry['global/registration_limit/reading'],registry['global/contribution/reading'],registry['global/hrc/reading'],registry['global/author/reading']]
    out['TABLE_RESULTS_claim_values.tex']=F.claim_definitions(registry)

    manifest['generated_sha256']={k:F.text_hash(v) for k,v in out.items()}
    manifest['frozen_form_ids']=sorted(T['forms'])
    manifest['frozen_template_ids']=sorted(T['frozen_templates'])
    return out,manifest


def validate_complete_inputs(record,refill=False):

    from datetime import datetime,timezone
    from .constraint_contract import validate_complete
    validate_complete(record)
    F.require(record.get('n0_forms'), 'full N0 frozen-form sequence required for standalone fill')
    required={'primary_effects','primary_tests','primary_seeds','combinations','cheap','secondary_news','secondary_notice','sensitivities','diagnostics','clipping_news','clipping_notice','execution'}
    F.require(required <= {t['id'] for t in record.get('source_tables',[])}, 'standalone fill requires all inherited S7/S9 numeric tables')
    for table in record['source_tables']:
        if table['id'] in required:
            expected='S9' if table['id'] in ('clipping_news','clipping_notice','execution') else 'S7'
            F.require(table['location']==expected, 'native table in wrong supplement section: '+table['id'])
    F.require(len({t['id'] for t in record['source_tables']})==len(record['source_tables']),'duplicate native table IDs')
    expected=[a+' - '+b for task,pairs in F.ARMS.items() for a,b in pairs]
    tables={t['id']:t for t in record['source_tables']}
    for key in ('primary_effects','primary_tests','primary_seeds'):
        table=tables[key];F.require(table['header'].count(' & ')==6 and [row[0] for row in table['rows']]==expected and all(len(row)==7 for row in table['rows']),'native primary row/column census drift: '+key)
    F.require(record.get('forest_rows'), 'standalone fill requires frozen-interval forest rows')
    primary=[r for r in record['forest_rows'] if r.get('group')=='Primary']
    F.require([(r['task'],r['arm'],r['ref']) for r in primary]==[(task,a,b) for task,pairs in F.ARMS.items() for a,b in pairs],'forest primary census/order drift')
    for row in primary:
        c=next(c for c in record['tasks'][row['task']]['contrasts'] if (c['arm'],c['reference'])==(row['arm'],row['ref']))
        F.require(F.decimal(row['effect'],nullable=True)==F.decimal(c['effect_percent'],nullable=True) and F.interval(row['thick'],nullable=True)==F.interval(c['family_one_day'],nullable=True) and F.interval(row['thin'],nullable=True)==F.interval(c['family_seven_day'],nullable=True),'forest primary differs from native family record')
    F.require(all(k in record['timestamps'] for k in ('T0','T1','T2','T3','T4','T4A','T4B','T5')), 'actual T0-T5 including T4A/T4B timestamps required')
    for label,t in record['timestamps'].items():
        for key in ('utc','freetsa_utc','digicert_utc'):
            value=datetime.fromisoformat(t[key].replace('Z','+00:00'));F.require(value.utcoffset()==__import__('datetime').timedelta(0),'timestamp must be UTC: '+label+'/'+key)
        F.require(isinstance(t['files'],dict),'timestamp files list required: '+label)
    F.require(isinstance(record.get('seventh_separate_approval'),bool), 'seventh-addendum approval disposition required')
    for task,t in record['tasks'].items():
        for c in t['contrasts']:
            if c['class']!='NE':F.require(c.get('holm_p') is not None, 'actual Holm p required')
    clock=record.get('fill_clock');F.require(isinstance(clock,dict),'arXiv fill clock required')
    dt=lambda s:datetime.fromisoformat(s.replace('Z','+00:00'))
    score=dt(clock['score_utc']);deadline=datetime(2026,10,6,1,tzinfo=timezone.utc)
    runs=clock['authorised_runs'];ends=[dt(r['terminal_utc']) for r in runs.values() if r.get('terminal_utc')]
    terminal=max(ends+[score]) if len(ends)==len(runs) else deadline
    cutoff=max(score,min(terminal,deadline));filled=dt(clock['filled_utc'])
    F.require(filled>=cutoff,'fill precedes the frozen cutoff')
    for name,time in clock.get('input_completed_utc',{}).items():F.require(refill or dt(time)<=cutoff, 'input after arXiv cutoff requires --refill: '+name)
    return cutoff.isoformat()


def display_pair(task,c):
    names=F.templates()['names'];return task+': '+names[c['arm']]+' versus '+names.get(c['reference'],F.templates()['words']['PLAIN_ACTIVITY_REF'][task])


def display_cell(cell):

    names=F.templates()['names']
    value=cell.replace(r'$^{\ddagger}$','')
    for arm in sorted(names,key=len,reverse=True):
        value=re.sub(r'(?<![A-Za-z0-9_])'+re.escape(arm)+r'(?![A-Za-z0-9_])',lambda _:names[arm],value)
    if r'$^{\ddagger}$' in cell:value+=r'$^{\ddagger}$'
    return value


def historical_timestamp_content(label):


    text=(F.MS/'supplement_sections/S7_protocol_records.tex').read_text()
    for line in text.splitlines():
        if line.startswith(label+' & '):return line.split(' & ')[1]
    F.require(False,'historical timestamp content missing: '+label)


def utc_display(value):return value.replace('T',' ').replace('Z','').removesuffix('+00:00')


def clock_rows(record,registry):
    clk=record['tasks']['notice']['clk8'];details=record.get('clk8_details')
    if clk['state']!='INFORMATIVE':return []
    F.require(isinstance(details,dict),'CLK8 caption needs native monthly coverage and delay distribution')
    rows=[]
    labels={'covered_notices':'covered notices','total_notices':'total notices','coverage_share':'coverage proportion',
            'maximum_d_hi_minutes':'maximum listing delay (upper time bound), minutes','median_d_hi_minutes':'median listing delay (upper time bound), minutes',
            'listed_by_admission_hi_n':'listed by admission using the upper time bound, count','listed_by_admission_lo_n':'listed by admission using the lower time bound, count',
            'listed_by_admission_hi_share':'listed by admission using the upper time bound, proportion','listed_by_admission_lo_share':'listed by admission using the lower time bound, proportion',
            'batched_notices':'batched notices','batched_share':'batched proportion','before_creation_gt5_notices':'notices listed over five minutes before creation',
            'before_creation_gt5_share':'proportion listed over five minutes before creation','bins':'listing-delay bins (minutes)'}
    def walk(data,path):
        for field,value in data.items():
            label=labels.get(field,field.replace('_',' '));prefix=path+[label]
            if isinstance(value,dict):yield from walk(value,prefix)
            else:yield ', '.join(prefix)+': '+('not available' if value is None else str(value))+'.'
    for group,data in details.items():
        for i,value in enumerate(walk(data,['Overall' if group=='overall' else 'Month'])):
            key='clock_'+group+'_'+str(i);registry['global/'+key+'/reading']=value
            rows.append(MACRO('global',key,'reading')+r' \\')
    return rows


def r8_extra(record,registry):
    rows=[]
    for task,t in record['tasks'].items():
        for c in t['contrasts']:
            data=c.get('r8_result')
            if not data:continue
            sq=data['squared_loss'];pair=c['arm']+'-'+c['reference'];key=task+'/'+pair+'/r8_squared'
            registry[key]=F.form('A8SQ',arm=F.templates()['names'][c['arm']]+' (richer source metadata)',activity='richer source-metadata',e=sq['effect'],p=sq['p']) if sq['state']=='COMPUTED' else 'Squared-loss descriptive for the richer source-metadata contrast: not run ('+F.reason_text(sq['reason'])+').'
            rows.append(MACRO(task,pair,'r8_squared')+r'\par')
    d=record.get('dly8_r8',{})
    if d.get('state')=='COMPUTED':
        for arm,grid in d['contrasts'].items():
            key='r8_delay_'+arm
            registry['global/'+key+'/reading']='Richer source-metadata notices, '+F.templates()['names'][arm]+': '+ '; '.join(k+' minutes: '+F.templates()['words']['PLAIN_C3'][grid[k]] for k in ('5','15','60'))+'.'
            rows.append(MACRO('global',key,'reading')+r'\par')
    elif d:
        registry['global/r8_delay/reading']=F.form('A8DLY_DEV') if d['state']=='DEVIATION' else 'Richer source-metadata notices: '+(F.form('A8DLY_NR',reason=F.reason_text(d['reason'])) if d['state']=='NOT_RUN' else 'pending (no result file when filled)')
        rows.append(MACRO('global','r8_delay','reading')+r'\par')
    return '\n'.join(rows)+'\n'


def iso_dates(text):
    from datetime import datetime
    return re.sub(r'\b\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|November|December) \d{4}\b',lambda m:datetime.strptime(m.group(),'%d %B %Y').date().isoformat(),text)
