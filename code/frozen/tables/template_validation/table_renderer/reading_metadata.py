'Read the primary interpretation fields from checked result records.'
import re
import table_results_conf_results as F

IDS={'A8H4','A6H1','A6H2','A6H2F','A6H3','A6H3F','A8H2_NC'}
def expected_slots(record,task,c,identity):
    T=F.templates();W=T['words'];t=record['tasks'][task]
    s={'arm':T['names'][c['arm']],'activity':W['PLAIN_ACTIVITY_REF'][task].removesuffix(' reference')}
    if c['class']=='NE':
        F.require(identity=='A8H4','N0 NE form identity')
        s['reason']=W['PLAIN_INC_REASON'][c['reason']];return s
    fails=[W['PLAIN_CHECKS'][k] for k in F.CHECKS if c['checks'][k]=='FAIL']
    missing=[W['PLAIN_CHECKS'][k] for k in F.CHECKS if c['checks'][k]=='UNAVAILABLE']
    robustness=('fragile: '+F.join(fails)+' disagreed' if fails else '')+('; ' if fails and missing else '')+('not fully checked: '+F.join(missing)+' unavailable' if missing else '')
    if not fails and not missing:robustness=F.form('A8R1')
    if t['alert'] and c['class']=='IMP':robustness='increment detected under a negative-control alert'
    s.update(se=c['effect_percent'],level='97.5' if task=='news' else '98.3',lo=c['family_one_day'][0],hi=c['family_one_day'][1],p=c['holm_p'],robustness=robustness,qualifiers=F.form('A8SEVEN') if F.seven_undefined(c) else '')
    robust=F.robust(c)
    expected_id='A6H1' if c['class']=='NULL' else 'A8H2_NC' if c['class']=='IMP' and t['alert'] else ('A6H2' if robust else 'A6H2F') if c['class']=='IMP' else ('A6H3' if robust else 'A6H3F')
    F.require(identity==expected_id,'N0 primary form disagrees with class/checks')
    if c['class'] in ('IMP','DET'):
        s.update(aud=str(abs(F.decimal(c['effect_aud']))),zero=F.form('A8Z',level=s['level']) if F.decimal(c['family_one_day'][0])<=0<=F.decimal(c['family_one_day'][1]) else '')
        if identity=='A8H2_NC':
            s.update({k:str(t['negative_control'][k]) for k in ('k0','R0','lo0','hi0')})
        elif not robust:
            s['three_seed']=F.form('A8SEED',e3=c['three_seed_effect'],c3=W['PLAIN_C3'][c['three_seed_class']]) if c['three_seed_effect'] is not None else F.form('A8SEED_NOEST',c3=W['PLAIN_C3'][c['three_seed_class']])
        if identity in ('A6H2','A6H2F'):
            from .constraint_contract import render_sequence
            s['benchmark']=render_sequence(c.get('benchmark_forms',[]),record=record)
        if identity=='A6H2F':s['test_note']=F.inherited_form('A6FT_F' if fails else 'A6FT_N')
        if identity=='A6H2':
            s['attribution']=F.inherited_form('A6C1',activity=s['activity'])
            lo=-max(F.interval(c['family_one_day'])[1],F.interval(c['family_seven_day'])[1]);hi=-min(F.interval(c['family_one_day'])[0],F.interval(c['family_seven_day'])[0]);bound=F.Decimal('3.8' if task=='news' else '0.5')
            key='BEYOND' if lo>bound else 'BELOW' if hi<bound else 'ABOVE' if -F.decimal(c['effect_percent'])>bound else 'BELOWPT'
            values=dict(S_phrase=str(bound)+'% of the reference error',S=str(bound))
            if key in ('BEYOND','BELOW'):values['tail']='98.75' if task=='news' else '99.17'
            s['position']=F.form('A8S_'+key,**values)
    return s

def actual_source_problems(text,record):

    from .prepare_table_fields import cited
    out=[];paragraphs=text.strip().split('\n\n')
    for task,t in record['tasks'].items():
        for c in t['contrasts']:
            items=[x for x in record['n0_forms'] if x['id'] in IDS and x['slots'].get('arm')==F.templates()['names'][c['arm']] and x['slots'].get('activity')==F.templates()['words']['PLAIN_ACTIVITY_REF'][task].removesuffix(' reference')]
            if len(items)!=1:out.append('K8 N0 primary census');continue
            identity=items[0]['id']
            try:expected=expected_slots(record,task,c,identity)
            except (F.FillError,KeyError) as exc:out.append('K8 N0 RS8: '+str(exc));continue
            frame=F.templates()['forms'][identity] if identity in F.templates()['forms'] else F.inherited_form(identity,**{k:'{'+k+'}' for k in expected})


            displayed={k:v.removesuffix('.') if '{'+k+'};' in frame else v for k,v in expected.items()}
            frame=F.rename_rendered(frame)
            chunks=[];seen=set()
            for part in re.split(r'(\{[A-Za-z0-9_]+\})',frame):
                if re.fullmatch(r'\{[A-Za-z0-9_]+\}',part):
                    key=part[1:-1]
                    if key in ('arm','activity'):chunks.append(re.escape(cited(expected[key])))
                    elif key not in ('se','aud','level','lo','hi','p','k0','R0','lo0','hi0','reason'):chunks.append(re.escape(cited(F.rename_rendered(displayed[key]))))
                    elif key in seen:chunks.append('(?P='+key+')')
                    else:seen.add(key);chunks.append('(?P<'+key+'>.*?)')
                else:chunks.append(re.escape(cited(part)))
            matches=[m for p in paragraphs if (m:=re.fullmatch(''.join(chunks),p,re.S))]
            if len(matches)!=1:out.append('K8 actual N0 scientific frame: '+task+'/'+c['arm']);continue
            for key,actual in matches[0].groupdict().items():
                want=cited(F.rename_rendered(displayed[key]))
                if key in ('se','aud','level','lo','hi','p','k0','R0','lo0','hi0'):
                    try:ok=F.decimal(actual.removeprefix('p = '))==F.decimal(want.removeprefix('p = '))
                    except F.FillError:ok=False
                else:ok=actual==want
                if not ok:out.append('K8 actual N0 RS8 slot '+key+': '+task+'/'+c['arm'])
    return out
