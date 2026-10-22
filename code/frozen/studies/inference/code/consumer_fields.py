'Fill table input fields from the saved comparison records.'
from pathlib import Path
import re
import read_comparisons as P


def identify_sentence(F,text,sheets=None):

    tables=[]
    if sheets is None:
        tables.append(F.templates()['forms'])
        for rel in ('primary_tests/DECISIONS_A2.json','sensitivity_tests/RULES_FOR_FILL3A.json','robustness_tests/RULES_FOR_MAIN_COMPARISONS.json','A6/RULES_FOR_SENSITIVITY_COMPARISONS.json'):
            path=P.confirmation/rel
            if path.exists():
                raw=P.strict_json(path)
                tables.extend(v for v in raw.values() if isinstance(v,dict))


        from reading_propagation import P as unused
        primary_tests,sensitivity_tests,robustness_tests,_,_=P.dependencies();tables += [primary_tests.SENTENCES,sensitivity_tests.SENTENCES,robustness_tests.SENTENCES]
    else:tables=sheets


    candidates=[(key,pattern) for table in tables for key,pattern in table.items() if isinstance(pattern,str)]
    candidates.sort(key=lambda item:len(re.sub(r'\{\w+\}','',item[1])),reverse=True)
    for key,pattern in candidates:
        parts=re.split(r'(\{\w+\})',pattern)
        literals=[v for v in parts if v and not re.fullmatch(r'\{\w+\}',v)]
        if any(v not in text for v in literals):continue
        if parts[0] and not text.startswith(parts[0]):continue
        seen=set();chunks=[]
        for x in parts:
            if x.startswith('{') and x.endswith('}'):
                k=x[1:-1];chunks.append('(?P='+k+')' if k in seen else '(?P<'+k+'>.*?)');seen.add(k)
            else:chunks.append(re.escape(x))
        match=re.fullmatch(''.join(chunks),text,re.S)
        if match and pattern.format(**match.groupdict())==text:
            return dict(id=key,slots=match.groupdict())
    raise P.Refusal('Sentence not represented by an exact frozen form')


def fill(F,primary_tests,sensitivity_tests,robustness_tests,record,inputs,manifest,current,prop):
    for name in ('hrc_review','hrc_agreement','author_a3_a6'):
        P.require(name in manifest['inputs'],'Native consumer input missing: '+name)
    record['hrc_results']=dict(review=manifest['inputs']['hrc_review'],agreement=manifest['inputs']['hrc_agreement'],
        review_data=inputs['hrc_review'],agreement_data=inputs['hrc_agreement'])
    record['author_a3_a6']=dict(manifest['inputs']['author_a3_a6'],data=inputs['author_a3_a6'])
    record['declarations']=inputs['context']['declarations']
    record['specification2_sha256']=manifest['inputs']['specification2']['sha256']
    record['batch_parity_failed']=any(x['state']!='PASS' for x in inputs['batch']['scoring_parity'].values())
    sheet=[F.templates()['forms'],primary_tests.SENTENCES,sensitivity_tests.SENTENCES,robustness_tests.SENTENCES]
    def entry(text):return identify_sentence(F,text,sheet)
    sections={'e3':[],'a1':[],'pc':[],'combinations':[]}
    e3=inputs['score_report'].get('notice',{}).get('e3_joint_state','E3_SECONDARY_JOINT_NOT_EVALUABLE')
    from types import SimpleNamespace
    from native_tables import frozen_method
    E=F.load_summary_comparisons();B=E.F3B;F3A=B.deps()[0]
    secondary={}
    for key,fam in current.items():
        if not key.startswith('notice/native:') or '__SECONDARY__' not in key:continue
        for r in fam.get('reports',[]):
            secondary[(r['arm'],r['reference'])]=SimpleNamespace(branch='FAVORABLE' if primary_tests.decision_class(r.get('mean_difference'),r.get('p_two_sided'))==robustness_tests.IMP else 'UNFAVORABLE') if fam['state']=='COMPUTED' else {}
    captured=[]
    facade=SimpleNamespace(report={'notice':{'e3_joint_state':e3}},sensitivity_tests=sensitivity_tests,secondary={'notice':secondary},a3fixed=lambda phrase,*args:captured.append(phrase) or phrase)
    frozen_method(P.MS/'main_comparisons_conf_results.py','e3_line3b',dict(require=P.require,F3A_=F3A))(facade)
    sections['e3'].append(identify_sentence(F,captured[0],[sensitivity_tests.CODE_PHRASES]))
    for task,t in record['tasks'].items():
        pt=prop['tasks'][task]

        if record['pc_state']=='RESULT':
            for sent in robustness_tests.pc_sentences(task,pt['scenario'],pt['pc']):sections['pc'].append(entry(sent))
        else:sections['pc'].append(dict(id='A8PEND_PC',slots=dict(reason='it had no result at the cut-off')))
        for c in t['contrasts']:
            pkey=c['arm']+'-'+c['reference']
            if c['class'] in ('IMP','DET') and not all(x=='PASS' for x in c['checks'].values()):
                sections['a1'].append(dict(id='A8SEED',slots=dict(e3=c['three_seed_effect'],c3=F.templates()['words']['PLAIN_C3'][c['three_seed_class']]))) if c['three_seed_effect'] is not None else sections['a1'].append(dict(id='A8SEED_NOEST',slots=dict(c3=F.templates()['words']['PLAIN_C3'][c['three_seed_class']])))
            attr=next(a for a in prop['details'][task]['a3']['attribution_a3'] if a['arm']==c['arm'])
            cheap=attr.get('cheap_text',{})
            c['cheap_comparators']={kind:[primary_tests.COMPARATOR_NAME[k] for k,v in cheap.get('computed',{}).items() if v==val] for kind,val in (('beaten','beaten'),('not_beaten','not_beaten'),('worse','worse'))}
            c['cheap_comparators']['unavailable']=[primary_tests.COMPARATOR_NAME[k] for k in cheap.get('unavailable',[])]
            key=robustness_tests.cheap_reading_key(cheap)
            c['cheap_text']='NOT_EVALUABLE' if t['alert'] or not cheap.get('computed') else 'BETTER' if key=='A4CHR_BETTER' else 'WORSE' if 'worse' in cheap.get('computed',{}).values() else 'NOTSHOWN'
            combo=current[task+'/combination']
            cr=next((r for r in combo['reports'] if r['arm']==c['arm'] and r['reference']==c['reference']),None)
            if cr is not None and cr['decision']!='NOT_EVALUABLE':


                from copy import deepcopy
                rr=deepcopy(cr);ss=(combo.get('three_seed') or {}).get('reports',[])
                sr=next((s for s in ss if s['arm']==c['arm']),None)
                _,lab,rob=P.six_checks(primary_tests,sensitivity_tests,rr,sr)
                rr['robustness']=dict(label='FRAGILE' if lab=='FRAGILE_NFC' else lab)
                key,sent=primary_tests.combination_clause(task,rr,P.CLASS_INV[c['class']])
                if sent is not None:
                    if key=='S2':
                        d=robustness_tests.decimals(rr['interval_family_one_day']);lo,hi=primary_tests.fmt_interval(rr['interval_family_one_day'],d)
                        form=dict(id='A3S2',slots=dict(benchmark=primary_tests.BENCHMARK_NAME[task],effect=primary_tests.fmt_effect(rr['effect_percent_reference_mae'],d),level=sensitivity_tests.LEVEL_TEXT[task],lo=lo,hi=hi,p=primary_tests.display_p(rr['holm_p'])))
                    else:
                        from reading_rules import states
                        D,native_tasks,_=states(record,F,prop)
                        native_c=next(c0 for c0 in native_tasks[task]['contrasts'] if c0['arm']==c['arm'])
                        if t['alert']:native_c['robust']='NOT_FULLY_CHECKED'
                        text,key=D.combination6(D.a4mod(),task,native_c)
                        form=identify_sentence(F,text,[{key:D.F6[key]}])
                    c['benchmark_forms']=[form];sections['combinations'].append(form)
                else:c['benchmark_forms']=[]
            else:
                reason='the benchmark forecasts were not available'
                c['benchmark_forms']=[dict(id='A6S7',slots=dict(benchmark=primary_tests.BENCHMARK_NAME[task],reason=reason))]
                sections['combinations'].extend(c['benchmark_forms'])
        shift=pt['shift'];arm=primary_tests.CONTENT_ARM[task]
        if shift.get('state')=='COMPUTED':
            d=robustness_tests.decimals(shift['interval95']);lo,hi=primary_tests.fmt_interval(shift['interval95'],d)
            t['shift_forms']=[dict(id='A6CS',slots=dict(arm=F.templates()['names'][arm],se=robustness_tests.sfmt(shift['effect'],d),lo=lo,hi=hi,p=primary_tests.display_p(shift['p_two_sided']),days=robustness_tests.SENTENCES['A4CS_DAYS'].format(n=shift['days']) if task=='notice' else '',seed='',**{'class':F.load_summary_comparisons().F3D.WD['CS6'][P.CLASS[shift['class']]]}))]
        else:t['shift_forms']=[dict(id='A4CSX',slots=dict(arm=F.templates()['names'][arm],reason=robustness_tests.reason_phrase(shift.get('state'))))]
    if not sections['a1']:sections['a1']=[dict(id='A8LEVELS',slots={})]
    record['section_readings']=sections
    from comparison_fields import fill as components
    item=components(F,primary_tests,sensitivity_tests,robustness_tests,record,current)
    for task,t in record['tasks'].items():
        for i,c in enumerate(t['contrasts']):
            combo=current[task+'/combination'];rows=combo.get('reports',[])
            form=item('('+F.templates()['names'][c['arm']]+' + '+primary_tests.BENCHMARK_NAME[task]+')/2 - ('+F.templates()['names'].get(c['reference'],primary_tests.ACTIVITY[task])+' + '+primary_tests.BENCHMARK_NAME[task]+')/2',rows[i] if len(rows)>i else None)
            sections['combinations'].append(form)
            if not c['benchmark_forms']:c['benchmark_forms']=[form]
            direct=current[task+'/combination_benchmark'];dr=direct.get('reports',[])
            sections['combinations'].append(item(F.templates()['names'][c['arm']]+' - '+primary_tests.BENCHMARK_NAME[task],dr[i] if len(dr)>i else None))
