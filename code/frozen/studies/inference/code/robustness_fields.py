'Format the robustness fields from checked comparison records.'
from copy import deepcopy
from pathlib import Path
import json,uuid
import read_comparisons as P


def artifact(root,name,data):
    root=Path(root);P.require(root.resolve().is_relative_to(Path('/private/tmp')) or root.resolve().is_relative_to(P.HERE),'Unsafe formatted metadata destination')
    root.mkdir(parents=True,exist_ok=True);path=root/name
    with path.open('x') as f:json.dump(data,f,indent=2,allow_nan=False);f.write('\n')
    return P.identity(path)


def timestamp_checks(inputs,manifest,name):
    if name in manifest['inputs']:
        item=manifest['inputs'][name];P.checked(item)
        P.require(any(Path(k).resolve()==Path(item['path']).resolve() and v==item['sha256'] for k,v in inputs['timestamps']['T5']['files'].items()),name+' exact path absent from T5')
        return dict(item,data=inputs[name])
    filename={'check_window_inputs':'R8_ADMISSION.json','cps8_selection':'CPS8_SELECTION.json'}[name]
    candidates=[i for i in inputs['batch_seal'].get('auxiliary',[]) if Path(i['path']).name==filename]
    P.require(len(candidates)==1,'Missing native '+filename)
    i=candidates[0];data=P.strict_json(P.checked(i))
    P.require(any(Path(k).resolve()==Path(i['path']).resolve() and v==i['sha256'] for k,v in inputs['timestamps']['T5']['files'].items()),filename+' exact path absent from T5')
    return dict(i,data=data)


def square(row):
    if row and row.get('state')=='COMPUTED' and row.get('dm',{}).get('p_two_sided') is not None and row.get('effect') is not None:
        return dict(state='COMPUTED',effect=P.decimal(float(row['effect'])),p=P.decimal(row['dm']['p_two_sided'],12))
    return dict(state='NOT_RUN',effect=None,p=None,reason=(row or {}).get('reason','fail'))


def r8_fields(F,record,inputs,manifest,current):
    batch=inputs['batch'];rows={r['stage']:r for r in record['stages']}
    record['r8_seed_disposition']=dict(state='NOT_RUN',reason='A8NR_AUTHOR',seeds='single')
    record['optional']['R8']=any(batch.get('families',{}).get('R8_'+t,{}).get('state')=='COMPUTED' for t in P.PAIRS)
    b4=rows['A8B-R8'];record.pop('check_window_inputs',None)
    if not record['batch_parity_failed'] and (b4['reason']=='A8NR_RESOURCE_A8AM2' or b4['counted_category'] in P.CATEGORIES[:2]):record['check_window_inputs']=timestamp_checks(inputs,manifest,'check_window_inputs')
    for task,t in record['tasks'].items():
        family=current.get(task+'/R8',batch.get('families',{}).get('R8_'+task,dict(state='PENDING',reports=[])))
        stage=rows['A8B-R8' if task=='news' else 'A8B-R8N']
        for i,c in enumerate(t['contrasts']):
            rel=P.relation(c['class'],family,i,fully_checked=False,seeds_run='single')
            if rel['state'] not in ('SAME','DIFFERENT'):rel['class']=None
            if stage['counted_category'] in P.CATEGORIES[2:]:
                rel.update(state={P.CATEGORIES[2]:'NOT_RUN',P.CATEGORIES[3]:'NOT_EVALUABLE',P.CATEGORIES[4]:'PENDING'}[stage['counted_category']],reason=stage['reason'])
            c['relations']['R8']=rel;c.pop('r8_result',None)
            if rel['state'] in ('SAME','DIFFERENT'):
                r=family['reports'][i];saved=batch.get('squared_loss',{}).get('R8',{}).get(task,[])
                c['r8_result']=dict(effect_percent=P.decimal(r.get('effect_percent_reference_mae')),family_one_day=P.interval_strings(r.get('interval_family_one_day')),holm_p=P.decimal(r.get('holm_p'),12),label='NOT_FULLY_CHECKED',squared_loss=square(saved[i] if len(saved)>i else None))
        t.pop('r8_descriptive',None)
        if stage['counted_category'] in P.CATEGORIES[:2]:
            schedule={'news':[('M0','N'),('M','M0'),('M+0','N'),('M+','M+0'),('M+','M')],'notice':[('M0_n','N'),('M_notice','M0_n'),('M+0_n','N'),('M+_n','M+0_n'),('M+_n','M_notice')]}[task]
            values={}
            for key,(arm,ref) in zip(('m0_n','m_m0','mp0_n','mp_mp0','mp_m'),schedule):
                fam=current.get(task+'/R8_desc/'+arm+'-'+ref,{})
                if fam.get('state')=='COMPUTED' and fam.get('reports'):values[key]=P.decimal(fam['reports'][0].get('effect_percent_reference_mae'))
            if len(values)==5 and all(v is not None for v in values.values()):t['r8_descriptive']=values
            else:P.require(stage['counted_category']!=P.CATEGORIES[0],'Completed R8 missing parity-verified descriptive census')
    delayed=batch.get('DLY8',{}).get('R8',{})
    fams=[current.get('notice/DLY8_R8_'+str(d),delayed.get(str(d),delayed)) for d in (5,15,60)]
    if rows['A8B-R8N']['counted_category']==P.CATEGORIES[2] and record['batch_parity_failed']:
        record['dly8_r8']=dict(state='NOT_RUN',reason='A8NR_PARITY',contrasts={})
    elif all(f.get('state')=='COMPUTED' for f in fams):
        record['dly8_r8']=dict(state='COMPUTED',reason=None,contrasts={c['arm']:{str(d):P.CLASS[f['reports'][i]['decision']] for d,f in zip((5,15,60),fams)} for i,c in enumerate(record['tasks']['notice']['contrasts'])})
    else:
        f=next(f for f in fams if f.get('state')!='COMPUTED')
        state=f.get('state','PENDING');state='DEVIATION' if state.startswith('DEVIATION') else 'NOT_RUN' if state.startswith('NOT_RUN') else 'PENDING'
        record['dly8_r8']=dict(state=state,reason=f.get('reason'),contrasts={})
    primary=batch.get('DLY8',{}).get('primary',{})
    if all(primary.get(str(d),{}).get('state')=='COMPUTED' for d in (5,15,60)):
        cat=P.CATEGORIES[0] if record['dly8_r8']['state']=='COMPUTED' else P.CATEGORIES[1]
        rows['DLY8'].update(counted_category=cat,postseal=cat)


def prepare_stages(inputs):

    batch=inputs['batch'];own=inputs['context']['own_stages']
    for row in batch.get('canonical_stage_rows',[]):
        if row['stage'] in ('A8B-R8N','A8B-R8','A8B-CPS8','DLY8'):
            own[row['stage']]=dict(state='PENDING',category=row['counted_category'],reason=row.get('reason'))
    if batch.get('batch_parity_failed') or any(r['state']!='PASS' for r in batch['scoring_parity'].values()):
        for name in own:
            if name.startswith('A8B-'):own[name]=dict(state='NOT_RUN',reason='A8NR_PARITY')
        for row in batch['CS8']['stage_dispositions'].values():row.update(state='NOT_RUN_PARITY_FAILED',reason='A8NR_PARITY',score_eligible=False)

def align(F,primary_tests,sensitivity_tests,robustness_tests,record,inputs,manifest,current,prop):
    r8_fields(F,record,inputs,manifest,current)
    record['clk8_details']={k:deepcopy(inputs['clk8'].get(k,{})) for k in ('overall','by_month')}
    record['cps8_selection']=None
    rows={r['stage']:r for r in record['stages']}
    if rows['A8B-CPS8']['counted_category'] in P.CATEGORIES[:2]:
        record['cps8_selection']=timestamp_checks(inputs,manifest,'cps8_selection')

        data=record['cps8_selection']['data'];P.require(set(data)==set(P.PAIRS),'CPS8 requires normalized native per-task selection artifact')
        for task,t in record['tasks'].items():
            for c in t['contrasts']:
                rel=c['relations']['CPS8'];g=data[task][c['arm']]
                if rel['state'] in ('SAME','DIFFERENT'):
                    if g is None or data[task][c['reference']] is None:rel.update(state='NOT_EVALUABLE',reason='fail',**{'class':None})
                    else:rel['selected_grid']=g


    root=Path(manifest['inputs']['context']['path']).parent/('a8post_native_'+uuid.uuid4().hex)
    from native_tables import Cells
    cells=Cells(primary_tests,sensitivity_tests,robustness_tests,F.load_summary_comparisons(),current,prop)
    data={}
    for task,t in record['tasks'].items():
        fam=current[task+'/primary'];d=cells.task_decimals(task)
        for i,c in enumerate(t['contrasts']):
            row=fam['reports'][i];seed=(fam.get('three_seed') or {}).get('reports',[]);sr=seed[i] if len(seed)>i else {};valid=c['class']!='NE'
            native=dict(days=str(fam['days']),reference_mae=f"{row['bootstrap']['1']['reference_mae']:.3f}" if valid else None,one_day=list(primary_tests.fmt_interval(row['interval95_one_day'],d)) if valid and row.get('interval95_one_day') else None,dm_p=P.decimal(row.get('p_two_sided'),12) if valid else None,hln_p=P.decimal(row.get('hln_holm_p'),12) if valid else None,hac7_p=P.decimal(row.get('hac7_holm_p'),12) if valid else None,seed_effects=[cells.seed_effect(task,i,s) if current.get(task+'/primary' if s==20260919 else task+'/seed_'+str(s),{}).get('state')=='COMPUTED' else None for s in (20260919,20260920,20260921)],seed_sd=cells.seed_sd(task,i),three_seed_family=P.interval_strings(sr.get('interval_family_one_day')) if c['three_seed_effect'] is not None else None)
            native['seed_effects']=[None if v in ('not available','undefined','--') else v for v in native['seed_effects']];native['seed_sd']=None if native['seed_sd']=='not available' else native['seed_sd']
            data.setdefault(task,{})[c['arm']]=native;c['native_primary']=deepcopy(native)
    ident=artifact(root,'NATIVE_PRIMARY.json',data)
    for task,t in record['tasks'].items():
        for c in t['contrasts']:c['native_primary']['timestamp_checks']=dict(ident,pointer='/'+task+'/'+c['arm'],source_receipt_sha256=record['identities']['source_receipt_sha256'])
    from table_renderer.table_contract import primary_rows
    tables={t['id']:t for t in record['source_tables']}
    for key,values in primary_rows(record).items():tables[key]['rows']=values
    from table_renderer.table_headings import headings
    for table in record['source_tables']:table['caption'],table['header']=headings(table,record)
