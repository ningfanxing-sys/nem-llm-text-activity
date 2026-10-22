'Check the scientific invariants of the result tables.'
from pathlib import Path
import importlib.util
import re
from decimal import Decimal
import table_results_conf_results as F

CLOCK_SHA='58233f4699ed0c92b942958834fe75cdabc6e6dedc9594ce82d936f0da036635'
CLOCK_KEYS=('state','reason_codes','coverage','listed_by_admission_n','X','Y','Z','reading')
HRC_SHA='cc5683835ae5d8e66f3b2599578615eafdd4122525c9a6dfd0304d90120132cf'

STAGES={'R8':{'news':'A8B-R8','notice':'A8B-R8N'},'DLY8':dict.fromkeys(F.ARMS,'DLY8'),'CPS8':dict.fromkeys(F.ARMS,'A8B-CPS8'),'KCX':dict.fromkeys(F.ARMS,'KCX')}
REASONS={'R8':{'A8NR_RESOURCE_A8AM2','A8NR_BATCH_BUDGET','A8NR_PARITY'},'DLY8':{'A8NR_PARITY','A8NR_FAIL','A8NR_BATCH_BUDGET'},'CPS8':{'A8NR_BATCH_BUDGET','A8NR_PARITY'},'KCX':{'A8NR_AUTHOR','A8NR_KEY','A8NR_PRICE','A8NR_FAIL','A8NR_PARITY'}}


def assertion(ok,msg):F.require(ok,'validation_group_4: '+msg)


def relations(record):
    stages={r['stage']:r for r in F.stage_rows(record)}
    for task,t in record['tasks'].items():
        for c in t['contrasts']:
            for layer,rel in c['relations'].items():
                if layer=='DLY8' and task=='news':
                    assertion(rel['state']=='NOT_APPLICABLE' and rel['class'] is None,'news DLY8 must be not applicable');continue
                row=stages[STAGES[layer][task]];cat=row['counted_category'];state=rel['state']
                if cat==F.CATEGORIES[4]:assertion(state=='PENDING','relation pending category: '+layer)
                elif cat==F.CATEGORIES[2]:assertion(state=='NOT_RUN' and rel.get('reason')==row['reason'],'relation not-run reason/category: '+layer)
                elif cat==F.CATEGORIES[3]:assertion(state=='NOT_EVALUABLE' and rel.get('reason')==row['reason'],'relation deviation reason/category: '+layer)
                else:assertion(state in ('SAME','DIFFERENT','NOT_EVALUABLE','NOT_APPLICABLE'),'completed relation state: '+layer)
                if state in ('SAME','DIFFERENT'):
                    assertion(rel['class'] in F.CLASSES and rel['class']!='NE','relation result class: '+layer)
                    primary=c['class'];reference=rel.get('g0_class',primary) if layer=='CPS8' else primary
                    assertion((state=='SAME')==(rel['class']==reference),'relation SAME/DIFFERENT class: '+layer)
                    if layer=='DLY8':assertion(rel['class']==c['delay_classes']['15'],'DLY8 +15 class')
                    if layer=='CPS8':assertion(rel.get('selected_grid') in (0,1,2) and rel.get('g0_class') in F.CLASSES,'CPS8 selected/g0 native fields')
                else:assertion(rel['class'] is None,'unavailable relation has a class: '+layer)
                if state=='NOT_RUN':assertion(rel.get('reason') in REASONS[layer],'layer reason domain: '+layer)
                if layer=='DLY8':
                    if state not in ('SAME','DIFFERENT'):assertion(all(v is None for v in c['delay_classes'].values()),'unavailable DLY8 numeric classes')
                    else:assertion(all(v in F.CLASSES for v in c['delay_classes'].values()),'completed DLY8 grid census')


def r12b(record):
    from .constraint_contract import specification2
    rows={r['stage']:r for r in F.stage_rows(record)}
    binding=specification2()

    relevant=[rows['A8B-R8N'],rows['A8B-R8']]
    resource=rows['A8B-R8']['reason']=='A8NR_RESOURCE_A8AM2'
    if binding or resource or record.get('specification2_sha256'):
        assertion(binding and record.get('specification2_sha256')==binding['sha256'],'specification-2 identity')
        needed=[(Path(x['path']).name,x['sha256']) for x in binding['record']['files']]+[('ADDENDUM_A8_SPECIFICATION_2_FREEZE.json',binding['sha256'])]
        for label in ('T4B','T5'):
            for name,sha in needed:assertion(any(Path(k).name==name and v==sha for k,v in record['timestamps'][label]['files'].items()),'specification-2 '+label+' coverage: '+name)
    assertion(rows['A8B-R8N']['reason']!='A8NR_RESOURCE_A8AM2','mandatory B2 cannot be resource-not-admitted')
    if record.get('batch_parity_failed'):
        assertion(all(r['counted_category']==F.CATEGORIES[2] and r['reason']=='A8NR_PARITY' for r in rows.values() if r['stage'].startswith('A8B-') or r['rerun_trigger']),'B0 parity all batch dispositions')
    elif resource or rows['A8B-R8']['counted_category'] in F.CATEGORIES[:2]:
        b=record.get('check_window_inputs');assertion(isinstance(b,dict),'forecast_replication metadata admission identity required')
        path=Path(b['path']);assertion(path.name=='R8_ADMISSION.json' and F.sha256(path)==b['sha256'],'forecast_replication admission bytes')
        assertion(any(Path(k).resolve()==path.resolve() and v==b['sha256'] for k,v in record['timestamps']['T5']['files'].items()),'forecast_replication admission T5 coverage')
        raw=F.strict_json(path);assertion(raw==b['data'],'forecast_replication admission native fields')
        spec=importlib.util.spec_from_file_location('validation_group_4_admission',F.PROJ/'studies/batch_estimation/code/check_window_inputs.py')
        import sys
        sys.path.insert(1,str(F.PROJ/'studies/batch_estimation/code'))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        expected=module.decision(raw['start_utc'],raw['rho'],raw['dly8_r8_seconds'],raw['seal_seconds'])
        assertion(all(raw.get(k)==v for k,v in expected.items()),'forecast_replication projection/decision drift')
        assertion(raw.get('outcome_access') is False,'forecast_replication admission outcome access')
        assertion(raw['admitted'] is (not resource),'forecast_replication contribution/admission disagreement')
    for task,t in record['tasks'].items():
        row=rows[STAGES['R8'][task]];done=row['counted_category'] in F.CATEGORIES[:2]
        assertion(not t.get('r8_descriptive') or done,'R8 descriptive unavailable task')
        if row['counted_category']==F.CATEGORIES[0]:assertion(t.get('r8_descriptive') is not None,'completed R8 descriptive census')
        if t.get('r8_descriptive'):
            assertion(set(t['r8_descriptive'])=={'m0_n','m_m0','mp0_n','mp_mp0','mp_m'} and all(F.decimal(v) is not None for v in t['r8_descriptive'].values()),'R8 descriptive numeric census')
        for c in t['contrasts']:
            data=c.get('r8_result');rel=c['relations']['R8']
            if rel['state'] in ('SAME','DIFFERENT'):assertion(done and isinstance(data,dict),'completed R8 contrast missing result')
            if data:
                assertion(done and rel['state'] in ('SAME','DIFFERENT'),'R8 result outside completed family')
                sq=data.get('squared_loss');assertion(isinstance(sq,dict),'R8 squared-loss reading required');squared(sq)
            else:assertion(rel['state'] not in ('SAME','DIFFERENT'),'R8 result census')
    if 'A8B-R8S' in rows and record['author_confirmation']['choices']['r8_seeds']=='single':
        assertion(rows['A8B-R8S']['reason']=='A8NR_AUTHOR','R8S default reason')


    rs=record.get('r8_seed_disposition');assertion(rs=={'state':'NOT_RUN','reason':'A8NR_AUTHOR','seeds':'single'} if record['author_confirmation']['choices']['r8_seeds']=='single' else rs is not None,'R8S disposition')
    d=record.get('dly8_r8');assertion(isinstance(d,dict),'DLY8-R8 family disposition required')
    assertion(d['state'] in ('COMPUTED','NOT_RUN','DEVIATION','PENDING'),'DLY8-R8 state')
    if d['state']=='COMPUTED':
        assertion(rows['A8B-R8N']['counted_category'] in F.CATEGORIES[:2],'DLY8-R8 without completed B2')
        assertion(set(d['contrasts'])=={c['arm'] for c in record['tasks']['notice']['contrasts']},'DLY8-R8 contrast census')
        for arm,v in d['contrasts'].items():
            assertion(set(v)=={'5','15','60'} and all(x in F.CLASSES for x in v.values()),'DLY8-R8 grid/class census')
    else:
        assertion(not d.get('contrasts'),'unavailable DLY8-R8 results forbidden')
        if d['state']=='NOT_RUN':assertion(d.get('reason') in REASONS['DLY8'],'DLY8-R8 not-run reason')
    primary_done=rows['DLY8']['counted_category'] in F.CATEGORIES[:2]
    if primary_done:assertion(rows['DLY8']['counted_category']==(F.CATEGORIES[0] if d['state']=='COMPUTED' else F.CATEGORIES[1]),'DLY8 combined category')


def squared(sq):
    assertion(sq['state'] in ('COMPUTED','NOT_RUN'),'squared state')
    if sq['state']=='COMPUTED':assertion(F.decimal(sq['effect']) is not None and 0<=F.decimal(sq['p'])<=1,'squared numbers')
    else:assertion(sq.get('effect') is None and sq.get('p') is None and isinstance(sq.get('reason'),str),'squared absence/reason')


def n0(record):

    forms=record['n0_forms'];W=F.templates()['words'];T=F.templates()
    for item in forms:
        if item['id']=='A8EST':assertion(item['slots'].get('cw')=='','R13 CW clause must stay inactive')
    for task,t in record['tasks'].items():
        for c in t['contrasts']:
            name=T['names'][c['arm']];activity=W['PLAIN_ACTIVITY_REF'][task].removesuffix(' reference')
            matching=[x for x in forms if x['slots'].get('arm')==name and x['slots'].get('activity')==activity and x['id'] in ('A8H4','A6H1','A6H2','A6H2F','A6H3','A6H3F','A8H2_NC')]
            assertion(len(matching)==1,'N0 member census');item=matching[0];s=item['slots']
            from .reading_metadata import expected_slots
            expected=expected_slots(record,task,c,item['id'])
            assertion(set(s)==set(expected),'N0 exact primary slot census')
            for key,value in expected.items():
                if key in ('se','aud','level','lo','hi','p','k0','R0','lo0','hi0'):
                    assertion(F.decimal(s[key].removeprefix('p = '))==F.decimal(value.removeprefix('p = ')),'N0 scientific slot '+key)
                else:assertion(s[key]==value,'N0 scientific slot '+key)
            if c['class']=='NE':continue
            fails=[W['PLAIN_CHECKS'][k] for k in F.CHECKS if c['checks'][k]=='FAIL'];missing=[W['PLAIN_CHECKS'][k] for k in F.CHECKS if c['checks'][k]=='UNAVAILABLE']
            robust=not fails and not missing and not F.seven_undefined(c)
            label=(('fragile: '+F.join(fails)+' disagreed') if fails else '')+('; ' if fails and missing else '')+(('not fully checked: '+F.join(missing)+' unavailable') if missing else '')
            label=F.form('A8R1') if robust else label
            if t['alert'] and c['class']=='IMP':label='increment detected under a negative-control alert'
            assertion(s.get('robustness')==label,'N0 inference label disagrees with six checks')
            assertion(s.get('qualifiers')==(F.form('A8SEVEN') if F.seven_undefined(c) else ''),'N0 seven-day qualifier')
            if c['class'] in ('IMP','DET'):
                zero=F.form('A8Z',level='97.5' if task=='news' else '98.3') if F.decimal(c['family_one_day'][0])<=0<=F.decimal(c['family_one_day'][1]) else ''
                assertion(s.get('zero')==zero,'N0 Holm rejection/zero qualifier')
                if not robust and not (t['alert'] and c['class']=='IMP'):
                    expected=F.form('A8SEED',e3=c['three_seed_effect'],c3=W['PLAIN_C3'][c['three_seed_class']]) if c['three_seed_effect'] is not None else F.form('A8SEED_NOEST',c3=W['PLAIN_C3'][c['three_seed_class']])
                    assertion(s.get('three_seed')==expected,'N0 three-seed class/effect')
                if t['alert']:
                    for key in ('k0','R0','lo0','hi0'):assertion(s.get(key)==str(t['negative_control'][key]),'N0 negative-control count/interval')


def number_cell(value):
    if value is None:return 'not evaluable'
    return str(value)

def interval_cell(value):return '$['+', '.join(value)+']$' if value else 'not evaluable'


def primary_rows(record):
    rows={k:[] for k in ('primary_effects','primary_tests','primary_seeds')}
    for task,t in record['tasks'].items():
        for c in t['contrasts']:
            raw=c['native_primary'];a=raw['timestamp_checks'];path=Path(a['path'])
            assertion(F.sha256(path)==a['sha256'] and a.get('source_receipt_sha256')==record['identities']['source_receipt_sha256'],'native primary timestamp_checks bytes/score association')
            native=F.strict_json(path)
            for k in filter(None,a['pointer'].strip('/').split('/')):
                native=native[int(k)] if isinstance(native,list) else native[k]
            assertion(native=={k:v for k,v in raw.items() if k!='timestamp_checks'},'native primary timestamp_checks pointer')
            p=c['arm']+' - '+c['reference'];n=number_cell;iv=interval_cell
            rows['primary_effects'].append([p,n(raw['days']),n(raw['reference_mae']),n(c['effect_aud']),n(c['effect_percent']),iv(raw['one_day']),iv(c['family_one_day'])])
            rows['primary_tests'].append([p,iv(c['per_contrast_seven_day']),iv(c['family_seven_day']),n(raw['dm_p']),n(c.get('holm_p') if c['class']!='NE' else None),n(raw['hln_p']),n(raw['hac7_p'])])
            rows['primary_seeds'].append([p,n(raw['seed_effects'][0]),n(raw['seed_effects'][1]),n(raw['seed_effects'][2]),n(raw['seed_sd']),seed_mean_cell(c,raw,t['alert']), 'consistent' if c['checks']['three_seed']=='PASS' else 'not available' if c['checks']['three_seed']=='UNAVAILABLE' else 'different class'])
    return rows


def complete(record):
    from .table_headings import validate as validate_headings
    validate_headings(record)
    relations(record);r12b(record);n0(record)
    if record['tasks']['notice']['clk8']['state']=='INFORMATIVE':
        raw=F.strict_json(record['clk8_result']['path'])
        assertion(record.get('clk8_details')=={k:raw[k] for k in ('overall','by_month')},'CLK8 distribution/months native binding')
    rows={x['stage']:x for x in F.stage_rows(record)}
    selection=record.get('cps8_selection')
    if rows['A8B-CPS8']['counted_category'] in F.CATEGORIES[:2]:
        assertion(isinstance(selection,dict),'CPS8 per-arm selection timestamp_checks')
        assertion(F.sha256(selection['path'])==selection['sha256'] and F.strict_json(selection['path'])==selection['data'],'CPS8 selection native bytes')
        assertion(any(Path(k).resolve()==Path(selection['path']).resolve() and v==selection['sha256'] for k,v in record['timestamps']['T5']['files'].items()),'CPS8 selection T5 coverage')
        assertion(set(selection['data'])==set(F.ARMS),'CPS8 tasks')
        for task,t in record['tasks'].items():
            expected={v for pair in F.ARMS[task] for v in pair}
            assertion(set(selection['data'][task])==expected and all(v is None or type(v) is int and v in (0,1,2) for v in selection['data'][task].values()),'CPS8 per-arm census/grid')
            for c in t['contrasts']:
                rel=c['relations']['CPS8']
                if rel['state'] in ('SAME','DIFFERENT'):assertion(rel['selected_grid']==selection['data'][task][c['arm']] and selection['data'][task][c['reference']] is not None,'CPS8 relation selected arm/reference grid')
    else:assertion(selection is None,'CPS8 unavailable selection values')
    tables={x['id']:x for x in record['source_tables']}
    for key,rows in primary_rows(record).items():assertion(len(tables[key]['rows'])==len(rows) and all(a[0]==b[0] and all(equal_cell(x,y) for x,y in zip(a[1:],b[1:])) and len(a)==len(b) for a,b in zip(tables[key]['rows'],rows)),'native primary numbers differ from RS8: '+key)
    for t in record['tasks'].values():
        for c in t['contrasts']:assertion(c['class']!='NE' or c.get('holm_p') is None,'NE must suppress Holm p')
    from .constraint_contract import exclusion_problems
    for table in record['source_tables']:
        for value in [table['caption'],table['header']]+[v for row in table['rows'] for v in row]:assertion(not exclusion_problems(value,any(t['alert'] for t in record['tasks'].values())),'inactive native text '+table['id']+': '+str(exclusion_problems(value,any(t['alert'] for t in record['tasks'].values()))))
    for deviation in record.get('deviations',[]):
        for key in ('what','label','pre_deviation_reading','post_deviation_reading'):assertion(not exclusion_problems(deviation[key],True),'inactive deviation prose')
    for value in record['declarations'].values():assertion(not exclusion_problems(value,True),'inactive declaration')
    path=F.inference_design/'hrc_code/hrcprep_validate.py'
    assertion(F.sha256(path)=='cc5683835ae5d8e66f3b2599578615eafdd4122525c9a6dfd0304d90120132cf','HRC validator code identity')
    spec=importlib.util.spec_from_file_location('validation_group_4_hrc_native',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    try:module.validate(record['hrc_results']['review_data'],record['hrc_results']['agreement_data'])
    except (ValueError,KeyError,TypeError) as exc:raise F.FillError('validation_group_4 native HRC: '+str(exc)) from exc


def equal_cell(a,b):
    if a==b:return True
    null={'not evaluable','not available','undefined','--'}
    if a in null or b in null:return a in null and b in null
    def tokens(x):return re.findall(r'[+-]?\d+(?:\.\d+)?',x.replace(r'$^{\dagger}$',''))
    va,vb=tokens(a),tokens(b)
    return bool(va) and len(va)==len(vb) and all(Decimal(x)==Decimal(y) for x,y in zip(va,vb)) and re.sub(r'[+\d\s.,%\[\]$-]|\\%', '',a)==re.sub(r'[+\d\s.,%\[\]$-]|\\%', '',b)


def seed_mean_cell(c,raw,alert=False):
    if c['three_seed_effect'] is None:return 'not available'
    F.interval(raw['three_seed_family'])
    words={'IMP':'a reliable increment','NULL':'no reliable increment detected','DET':'a reliable deterioration','NE':'not evaluable'}
    if alert:words['IMP']='increment detected under a negative-control alert'
    return '$'+c['three_seed_effect']+' ['+', '.join(raw['three_seed_family'])+']$, '+words[c['three_seed_class']]
