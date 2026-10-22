'Define and validate the table input fields.'
import importlib.util
from pathlib import Path
import re
from functools import lru_cache
import table_results_conf_results as F

DESIGN_STAGE={'label_replacement':'label_scoring','l1_family':'A2B-1','pd_family':'A2B-2','window_24h':'window_24h',
              'first_chunk':'first_L_news','official_cap':'secondary_notice','drop_first_seven':'secondary_notice'}


def specification2_helper():

    import sys
    directory=F.PROJ/'studies/batch_estimation/fitting/code'
    old_common=sys.modules.get('batch_inputs');old_path=list(sys.path)
    try:
        sys.path.insert(0,str(directory))
        common_path=directory/'batch_inputs.py'


        if common_path.is_file():
            spec=importlib.util.spec_from_file_location('batch_inputs',common_path)
            common=importlib.util.module_from_spec(spec);sys.modules['batch_inputs']=common;spec.loader.exec_module(common)
        spec=importlib.util.spec_from_file_location('table_results_verified_specification2',directory/'batch_definitions.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module,directory.parent/'freeze_a8_specification2.py'
    finally:
        sys.path[:]=old_path
        if old_common is None:sys.modules.pop('batch_inputs',None)
        else:sys.modules['batch_inputs']=old_common


def specification2(root=None):
    root=Path(root or F.inference_design);receipt=root/'ADDENDUM_A8_SPECIFICATION_2_FREEZE.json'
    if not receipt.exists():return None
    module,helper=specification2_helper()
    try:record=module.verify(receipt,root,helper)
    except (ValueError,RuntimeError,OSError,KeyError) as exc:raise F.FillError('specification 2 verification failed: '+str(exc)) from exc
    return {'sha256':F.sha256(receipt),'record':record}


def specification2_plan():

    module,helper=specification2_helper()
    try:record=module.record(F.inference_design,helper)
    except (ValueError,RuntimeError,OSError,KeyError) as exc:raise F.FillError('specification 2 dry-run failed: '+str(exc)) from exc
    return {'sha256':None,'record':record}


def specification2_form(identity):
    binding=specification2();F.require(binding is not None,'specification 2 form requires verified receipt')
    key={'A8NR_RESOURCE_A8AM2':'forms.A8NR_RESOURCE_A8AM2','A8CONTRIB1_when_B4_not_admitted':'forms.A8CONTRIB1_when_B4_not_admitted'}[identity]
    return binding['record']['changes'][key]


def specification2_reason(record):
    binding=specification2();F.require(binding is not None,'R8 deferral reason requires verified specification 2')
    module,helper=specification2_helper()
    return module.author_reason(record['author_confirmation'])


def validate_additions(record):
    rows={x['stage']:x for x in map(F.normalise_stage_row,record['stages'])}
    F.require(record['stage_table_ref']=='supp:tab:table_results-stages','stage table label is consumer-owned')
    for task,t in record['tasks'].items():
        if not t['complete']:F.require(all(c['class']=='NE' for c in t['contrasts']), 'incomplete task members must be NE')
        for c in t['contrasts']:
            for layer in c['design_layers']:
                stage=DESIGN_STAGE.get(layer)
                if layer=='first_chunk':stage='first_L_'+task
                F.require(stage is not None and rows[stage]['counted_category'] in F.CATEGORIES[:2], 'design dissent without completed stage: '+layer)
            for layer,rel in c['relations'].items():
                if rel['state']=='PENDING':
                    stage={'R8':'A8B-R8N' if task=='notice' else 'A8B-R8','DLY8':'DLY8','CPS8':'A8B-CPS8','KCX':'KCX'}[layer]
                    F.require(rows[stage]['counted_category']==F.CATEGORIES[4] and rel['class'] is None,'pending relation disagrees with stage table')
            data=c.get('r8_result')
            if data:
                F.decimal(data['effect_percent']);F.interval(data['family_one_day']);F.decimal(data['holm_p'])
                F.require(data['label'] in ('ROBUST','FRAGILE','NOT_FULLY_CHECKED','FRAGILE_NFC'), 'invalid R8 inferential label')
                F.require(data['label']!='ROBUST' or c['relations']['R8']['fully_checked'] and not t['alert'], 'R8 robust label without fully checked non-alert result')
    clk=record['tasks']['notice']['clk8']
    if clk['state']=='INFORMATIVE':F.require(re.fullmatch(r'\d+',clk.get('maximum_delay_minutes','')) is not None,'CLK8 Z display must be integer')

    from check_table_sources import banned_problems,stale_problems
    for d in record.get('deviations',[]):
        for key in ('what','label','pre_deviation_reading','post_deviation_reading'):
            F.require(isinstance(d.get(key),str) and not banned_problems(d[key]) and not stale_problems(d[key],record,allow_stage_pending=False) and not exclusion_problems(d[key],any(t['alert'] for t in record['tasks'].values())), 'unsafe deviation text: '+key)
    aid=record['human_review'].get('further_aid')
    F.require(aid is None or isinstance(aid,str) and not banned_problems(aid) and not stale_problems(aid,record,allow_stage_pending=False) and not exclusion_problems(aid,any(t['alert'] for t in record['tasks'].values())), 'unsafe aid disclosure')
    for table in record.get('source_tables',[]):
        F.require(not banned_problems(table['caption']) and not banned_problems(table['header']) and not stale_problems(table['caption']+' '+table['header'],record,allow_stage_pending=False), 'unsafe native table heading')
        if table['id']=='sensitivities':F.require(table['label']=='tab:main_comparisons-sensitivity','sensitivity table label drift')
        for row in table['rows']:
            for cell in row:F.require(isinstance(cell,str) and not banned_problems(cell) and not stale_problems(cell,record,allow_stage_pending=False) and not re.search(r'\b(?:None|nan|NOT_RUN|NOT_EVALUABLE|SAME|DIFFERENT)\b',cell), 'unsafe native table cell')


def retained_n0_forms():

    row=next(line for line in (F.inference_design/'ADDENDUM_A8.md').read_text().splitlines() if line.startswith('| A6/A7 abstract ladder'))
    return set(re.findall(r'\bA[3-7][A-Z][A-Z0-9_]*\b',row.split('|')[1]))


@lru_cache(maxsize=2)
def exclusion_patterns(alert,allow_retained=False):
    T=F.templates();retained=retained_n0_forms();patterns=[]
    sheets=[F.strict_json(F.PROJ/rel) for rel in ('studies/confirmation/sensitivity_tests/RULES_FOR_FILL3A.json','studies/confirmation/robustness_tests/RULES_FOR_MAIN_COMPARISONS.json','studies/confirmation/A6/RULES_FOR_SENSITIVITY_COMPARISONS.json')]
    for identity in T['replaces_forms']:
        if allow_retained and identity in retained or identity.startswith('words.') or identity=='A6H2' and not alert:continue
        pattern=next((values[identity] for sheet in sheets for values in sheet.values() if isinstance(values,dict) and isinstance(values.get(identity),str)),None)
        if pattern is None:continue


        if identity in retained and len(re.sub(r'\{[A-Za-z0-9_]+\}|[^A-Za-z]','',pattern))<40:continue
        pattern=F.rename_rendered(pattern)


        if pattern in T['forms'].values():continue
        parts=re.split(r'(\{[A-Za-z0-9_]+\})',pattern)
        expr=''.join(r'.{0,300}?' if re.fullmatch(r'\{[A-Za-z0-9_]+\}',v) else re.escape(v) for v in parts)
        patterns.append((identity,re.compile(expr)))
    E=F.load_summary_comparisons()
    for identity in T['replaces_templates']:
        pattern=E.TP7.get(identity)
        if not isinstance(pattern,str) or pattern==T['frozen_templates'].get(identity):continue
        parts=re.split(r'(<<[A-Za-z0-9_]+>>|\{[A-Za-z0-9_]+\})',F.rename_rendered(pattern))
        expr=''.join(r'.{0,300}?' if re.fullmatch(r'<<[A-Za-z0-9_]+>>|\{[A-Za-z0-9_]+\}',v) else re.escape(v) for v in parts)
        patterns.append(('template.'+identity,re.compile(expr)))
    return patterns


def exclusion_problems(text,alert=False):
    patterns=exclusion_patterns(alert)
    problems=['inactive rendered form: '+identity for identity,pattern in patterns if pattern.search(text)]
    problems+=['inactive literal ID: '+identity for identity in F.templates()['replaces_forms'] if re.search(r'(?<![A-Za-z0-9_])'+re.escape(identity)+r'(?![A-Za-z0-9_])',text)]
    if not problems:return []


    for template in F.templates()['forms'].values():
        parts=re.split(r'(\{[A-Za-z0-9_]+\})',template);fields=[];chunks=[]
        for part in parts:
            if re.fullmatch(r'\{[A-Za-z0-9_]+\}',part):
                key=part[1:-1]
                if key in fields:chunks.append('(?P='+key+')')
                else:fields.append(key);chunks.append('(?P<'+key+'>.{0,300}?)')
            else:chunks.append(re.escape(F.rename_rendered(part)))
        if sum(len(part) for part in parts if not part.startswith('{'))<20:continue
        match=re.fullmatch(''.join(chunks),text,re.S)
        if match and not any(pattern.search(value) for value in match.groupdict().values() for _,pattern in patterns):return []
    return problems


def render_sequence(items, *, alert=False,record=None):

    T=F.templates();out=[]
    retained=retained_n0_forms()
    for item in items:
        identity=item['id'];slots=item['slots']
        local_alert=alert
        if record is not None:
            tasks=[task for task in F.ARMS if slots.get('activity')==F.templates()['words']['PLAIN_ACTIVITY_REF'][task].removesuffix(' reference') or slots.get('documents')==('articles' if task=='news' else 'notices')]
            if tasks:local_alert=any(record['tasks'][task]['alert'] for task in tasks)
            if identity=='A8CHS':F.require(tasks and not local_alert,'alert N0 cheap-text verdict forbidden')
        F.require(identity not in T['replaces_forms'] or identity in retained or identity=='A6H2' and not local_alert,'inactive current form: '+identity)
        if identity=='A6H2':F.require(not local_alert,'alert cannot use A6H2')
        if identity.startswith('FILL2:'):
            E=F.load_summary_comparisons();_,_,F2,_=E.F3B.deps()
            template=F2.Templates(F.MS/'fill2_templates.json')[identity.removeprefix('FILL2:')]
            required=set(re.findall(r'<<([A-Za-z0-9_]+)>>',template))
            F.require(set(slots)==required,'frozen FILL2 template slot drift')
            result=template
            for key,value in slots.items():result=result.replace('<<'+key+'>>',value)
        else:result=F.form(identity,**slots) if identity in T['forms'] and identity not in T['replaces_forms'] else F.inherited_form(identity,**slots)
        from check_table_sources import banned_problems,stale_problems
        F.require(not banned_problems(F.rename_rendered(result)), 'unsafe frozen-form slots: '+identity)
        F.require(not any(stale_problems(value,record or {},allow_stage_pending=False) for value in slots.values()), 'unsafe pending state in free form slots')
        for key,value in slots.items():F.require(not exclusion_problems(value,local_alert), 'inactive current slot '+identity+'/'+key+': '+str(exclusion_problems(value,local_alert)))
        result=F.rename_rendered(result)
        if identity.startswith('E3_SECONDARY_JOINT_'):
            result='Under the frozen joint rule, '+result+' (Supplement~S7).'
        elif identity.startswith('A8S_'):
            result='For the recorded comparison, '+result+'.'
        out.append(result)
    result='\n\n'.join(out)
    return result


def verify_artifact(entry, record, label='T5', name=None):
    path=Path(entry['path'])
    F.require(name is None or path.name==name, 'unexpected input artifact name')
    F.require(F.sha256(path)==entry['sha256'],'input artifact identity drift: '+path.name)
    listing=record['timestamps'][label]['files']
    F.require(any(Path(k).name==path.name and v==entry['sha256'] for k,v in listing.items()),'input artifact not listed in '+label+': '+path.name)
    return F.strict_json(path)


def validate_complete(record):
    F.verify_clock_binding(record)
    rows=F.stage_rows(record)
    from .table_contract import complete
    complete(record)
    reasons=record.get('squared_not_run_reasons')
    F.require(isinstance(reasons,dict) and set(reasons)==set(F.ARMS),'squared-loss not-run dispositions required')
    allowed=set(F.templates()['words']['PLAIN_INC_REASON'])|{k for k in F.templates()['forms'] if k.startswith('A8NR_')}|{'A4NR_BUDGET'}
    for task,t in record['tasks'].items():
        expected={c['arm']+'-'+c['reference'] for c in t['contrasts'] if c['squared_loss']['state']=='NOT_RUN'}
        F.require(set(reasons[task])==expected and all(reason in allowed for reason in reasons[task].values()),'squared-loss exact not-run reason census: '+task)
        for c in t['contrasts']:
            sq=c['squared_loss'];p=F.decimal(sq['p'],nullable=sq['state']=='NOT_RUN')
            F.require((sq['effect'] is None and p is None) if sq['state']=='NOT_RUN' else p is not None and 0<=p<=1,'squared-loss state/numbers drift')
    forms=record.get('n0_forms',[])
    F.require(any(x['id'] in retained_n0_forms() for x in forms),'full N0 needs its retained predecessor design frame')
    for task,t in record['tasks'].items():
        for c in t['contrasts']:
            allowed={'NE':{'A8H4'},'NULL':{'A6H1'},'DET':{'A6H3','A6H3F'},'IMP':{'A8H2_NC'} if t['alert'] else {'A6H2','A6H2F'}}[c['class']]
            matching=[x for x in forms if x['id'] in allowed and x['slots'].get('arm')==F.templates()['names'][c['arm']] and x['slots'].get('activity')==F.templates()['words']['PLAIN_ACTIVITY_REF'][task].removesuffix(' reference')]
            F.require(len(matching)==1,'full N0 current primary reading census: '+task+'/'+c['arm'])
            slots=matching[0]['slots']
            if c['class']!='NE':
                F.require(all(F.decimal(slots[k])==F.decimal(v) for k,v in (('se',c['effect_percent']),('lo',c['family_one_day'][0]),('hi',c['family_one_day'][1]))),'N0 primary numbers differ from result record')
                F.require(F.decimal(slots['p'].removeprefix('p = '))==F.decimal(c['holm_p']),'N0 Holm number differs')
    render_sequence(forms,record=record)
    h=record['human_review']
    F.require(all(h[k]['completed_utc'] and h[k]['listed_in_T5'] is True for k in ('review','second','agreement')),'R6: HRC steps 4-5 must precede T5')
    values=record.get('hrc_results');F.require(isinstance(values,dict),'HRC native results required')
    score=verify_artifact(values['review'],record,name='SCORES.json')
    agreement=verify_artifact(values['agreement'],record,name='SECOND_ANNOTATOR_AGREEMENT_CONFIRMATION10.json' if h['path']=='HRC-inference_design' else 'SECOND_ANNOTATOR_AGREEMENT.json')
    F.require(score==values['review_data'] and agreement==values['agreement_data'],'HRC producer fields differ from native output')
    F.require(score['news']['strata']['ALL']['article_count']==20 and score['notices']['strata']['ALL']['notice_count']==20, 'HRC fixed subset census drift')
    human=F.strict_json(F.MS/'main_comparisons_templates.json')['human']
    F.require(set(score['news']['strata']['ALL']['statement_field_error'])==set(human['field_names_news']),'HRC news field census drift')
    F.require(set(score['notices']['strata']['ALL']['fields'])==set(human['field_names_nrx']),'HRC notice field census drift')
    for corpus,metrics in agreement['groups']['ALL']['metrics'].items():
        expected=set(human['field_names_nrx']) if corpus=='notice' else set(human['field_names_news'])|{'hallucination','omission','impact_code'}
        F.require(set(metrics['fields'])==expected,'HRC agreement field census drift')
        F.require(metrics['items']==(5 if h['path']=='HRC-inference_design' else 15),'HRC agreement pair census drift')
        for field,e in metrics['fields'].items():
            F.require(all(k in e for k in ('paired_n','equal_n','wilson_95','cohens_kappa','observed_agreement','expected_agreement','prevalence')), 'HRC agreement fields missing')
    auth=record.get('author_a3_a6');F.require(isinstance(auth,dict), 'sensitivity_tests-A6 author approval record required')
    native=verify_artifact(auth,record,name='AUTHOR_CONFIRMATION_A3_A6.json')
    F.require(native==auth['data'], 'sensitivity_tests-A6 author approval fields differ from native record')
    slots=record.get('declarations');F.require(isinstance(slots,dict) and set(slots)=={'credit','competing_interest','data_availability','accountability','funding','front_authors','front_affiliations','front_correspondence'},'all declarations slots required')
    from check_table_sources import banned_problems, stale_problems
    for value in slots.values():F.require(isinstance(value,str) and value.strip() and not banned_problems(value) and not stale_problems(value,record,allow_stage_pending=False), 'unfilled or unsafe declaration')
    for section in ('e3','a1','pc','combinations'):
        F.require(record.get('section_readings',{}).get(section),'missing section reading: '+section)
        render_sequence(record['section_readings'][section],alert=any(t['alert'] for t in record['tasks'].values()))
    components=record['section_readings'].get('a1_components')
    F.require(isinstance(components,dict) and set(components)=={'sesoi','seed','hln','exposure','w2d_npm'},'A1 SESOI/seed/HLN/exposure/W2_D-NPM components required')
    for key,items in components.items():
        F.require(items,'missing A1 component: '+key);render_sequence(items)
    if record['pc_state']=='RESULT':
        F.require(any(x['id']=='A4P1T' for x in record['section_readings']['pc']), 'computed PC requires frozen detection-rate form')
    else:F.require(all(x['id']=='A8PEND_PC' for x in record['section_readings']['pc']),'pending PC requires exact inference_design pending form')
    F.require(any(x['id'].startswith('E3_SECONDARY_JOINT_') for x in record['section_readings']['e3']), 'E3 joint reading required')
    for task,t in record['tasks'].items():
        for c in t['contrasts']:
            if c['class']=='IMP' and not t['alert']:
                F.require(c.get('cheap_comparators') and c.get('benchmark_forms'), 'increment needs comparator and strong-benchmark readings')
                groups=c['cheap_comparators'];F.require(set(groups)=={'beaten','not_beaten','worse','unavailable'},'cheap comparator group schema drift')
                names=[n for values in groups.values() for n in values]
                F.require(len(names)==len(set(names)) and all(isinstance(n,str) and n.strip() and not banned_problems(n) and not stale_problems(n,record) for n in names),'cheap comparator names invalid')
                verdict=c['cheap_text'];F.require((bool(groups['beaten']) and not any(groups[k] for k in ('not_beaten','worse','unavailable'))) if verdict=='BETTER' else bool(groups['worse']) if verdict=='WORSE' else bool(groups['not_beaten']) and not groups['worse'] and not groups['unavailable'] if verdict=='NOTSHOWN' else bool(groups['unavailable']),'cheap verdict contradicts comparator outcomes')
        F.require(t.get('shift_forms'), '28-day shift reading required: '+task)


def hrc_render(record,registry=None):

    from types import SimpleNamespace
    from collections import Counter
    from .complete_fill import inherited_generators
    R=inherited_generators();B=F.load_summary_comparisons().F3B
    class Dotted(dict):
        def __getitem__(self,key):
            value=self
            for part in key.split('.'):
                value=dict.__getitem__(value,part) if isinstance(value,Dotted) else value[part]
            return value
    class Human(R):
        layout=staticmethod(lambda text:text)
        fx3b=staticmethod(lambda text,key:text)
        R=staticmethod(lambda value,*args:value)
        a4fixed=staticmethod(lambda identity:F.inherited_form(identity))
        def t3b(self,key,**slots):
            text=self.T3[key]
            for k,v in slots.items():text=text.replace('<<'+k+'>>',str(v))
            return text
    h=object.__new__(Human);h.T3=Dotted(F.strict_json(F.MS/'main_comparisons_templates.json'))
    h.conf_review=SimpleNamespace(data=record['hrc_results']['review_data'],src='T5 SCORES.json')
    h.agreement=SimpleNamespace(data=record['hrc_results']['agreement_data'],src='T5 agreement')
    h.pair_tables={};h.a6_checks=Counter()

    for corpus in ('news','notice'):
        for field in h.agreement.data['groups']['ALL']['metrics'][corpus]['fields']:
            pairs=Counter()
            for item in h.agreement.data['groups']['ALL'].get('pair_trace',[]):
                if item.get('corpus')==corpus and item.get('field')==field:pairs[(item['author_code'],item['second_code'])]+=1
            h.pair_tables[(corpus,field)]=pairs
    summary=h.conf_sentence()+'\n'+h.agreement_sentence()
    summary=re.sub(r'(?<!\\)%[^\n]*','',summary).replace(r'\%','%')
    if registry is not None:
        counter=[0]
        def traced(value,*args):
            key='global/hrc_cell'+str(counter[0])+'/reading';counter[0]+=1
            registry[key]=str(value).replace(r'\%','%')
            return r'\Dres{global}{hrc_cell'+str(counter[0]-1)+'}{reading}'
        h.R=traced
    table=h.conf_table()+'\n'+h.agreement_table()
    if record['human_review']['path']=='HRC-inference_design':
        summary=summary.replace('30-item','10-pair window-D')
        table=table.replace('30-item subsample (all items)','10-pair window-D subsample')
    if registry is not None:
        registry['global/hrc_wilson_level/reading']='95%'
        table=table.replace(r'95\%',r'\Dres{global}{hrc_wilson_level}{reading}')
    return F.rename_rendered(summary), F.rename_rendered(table)
