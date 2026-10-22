'Reconstruct seed and window comparisons from forecasts and daily losses.'
from pathlib import Path
import copy
import csv
import hashlib
import importlib.util
import json
import re
import shutil
import sys
import numpy as np
import pandas as pd

SEEDS=(20260919,20260920,20260921)
REPS={'notice':['L14','L_Laz','L_chen_notice'],'news':['L_count','L_chen']}
NAMES={'L14':'Event states','L_Laz':'Overlap components','L_chen_notice':'Archive embeddings','L_count':'Fields','L_chen':'Embeddings'}
ANALYSES=[('a1','notice','original'),('a2_w7','notice','w7'),('a2_w24','notice','w24'),('a1','news','original')]


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def verify_posthoc(v,F,expectations):
    root=v.ROOT;post=root/'seeds_windows';check=v.check;printed=v.printed
    def gate():
        if shutil.disk_usage(root).free<2_000_000_000:raise RuntimeError('STOP: free disk below 2 GB')
    gate()
    def read(name):
        with (post/'results'/f'{name}.csv').open(newline='') as f:return list(csv.DictReader(f))


    rewrites=json.loads((post/'INPUT_RECORDS.json').read_text())
    for record in rewrites:
        if 'original_sha256' in record:
            check('seeds_windows/source_record_hash/'+record['file'],bool(re.fullmatch('[a-f0-9]{64}',record['original_sha256'])),True)
        if 'package_sha256' in record:
            check('seeds_windows/portable_record_hash/'+record['file'],v.sha(root/record['file']),record['package_sha256'])
    feature=json.loads((post/'FEATURE_CHECKS.json').read_text())
    normalized=copy.deepcopy(feature)
    for item in normalized['outputs']:item['path']=Path(item['path']).name
    payload=json.dumps(normalized,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    expected_payloads={r['content_sha256'] for r in rewrites if r['file']=='seeds_windows/FEATURE_CHECKS.json'}
    check('seeds_windows/feature/content_identity',{hashlib.sha256(payload).hexdigest()},expected_payloads)
    for item in feature['outputs']:
        check('seeds_windows/feature/input_location/'+Path(item['path']).name,item['path'],'seeds_windows/features/'+Path(item['path']).name)
    for item in feature['outputs']:
        p=root/item['path'];check('seeds_windows/features/hash/'+p.name,v.sha(p),item['sha256'])
        a=np.load(p,mmap_mode='r',allow_pickle=False)
        check('seeds_windows/features/shape/'+p.name,list(a.shape),item['shape'])
        check('seeds_windows/features/finite_nonnegative/'+p.name,bool(np.isfinite(a).all() and (a>=0).all()),True)
    eq=json.loads((post/'EQUIVALENCE_GATE.json').read_text())
    check('seeds_windows/equivalence/state',eq['state'],'PASSED')
    check('seeds_windows/equivalence/fits',len(eq['fits']),4)
    for x in eq['fits']:
        for k in ['max_abs_difference','max_abs_difference_raw','max_abs_difference_sealed']:check('seeds_windows/equivalence/'+x['task_id']+'/'+k,x[k],0.,atol=1e-9)
        for k in ['train_indices_match','params_match']:check('seeds_windows/equivalence/'+x['task_id']+'/'+k,x[k],True)
    entries=json.loads((post/'forecasts/INDEX.json').read_text())['predictions']
    check('seeds_windows/forecast_count',len(entries),298)
    check('seeds_windows/group_counts',pd.Series([e['group'] for e in entries]).value_counts().to_dict(),{'no_text_notice':2,'no_text_news':270,'w7':12,'w24':12,'w7_shift':2})
    actual_files={str(p.relative_to(root)) for p in (post/'forecasts').glob('*/artifacts/*.predictions.parquet')}
    check('seeds_windows/forecast_files_exactly_indexed',actual_files=={e['path'] for e in entries},True)
    manifest={p:h for h,p in (line.split('  ',1) for line in (post/'forecasts/SHA256SUMS').read_text().splitlines())}
    check('seeds_windows/forecast_manifest_count',len(manifest),298)
    for e in entries:
        p=(root/e['path']).resolve()
        if not p.is_relative_to(post.resolve()):raise ValueError('Unsafe forecast path')
        check('seeds_windows/forecast_hash/'+str(p.relative_to(post)),v.sha(p),e['sha256'])
        check('seeds_windows/forecast_manifest/'+p.name,manifest[str(p.relative_to(post/'forecasts'))],e['sha256'])

    wanted=[]
    for group,arms,seeds,task in [('no_text_notice',['N'],SEEDS[1:],'notice'),('no_text_news',['N'],SEEDS[1:],'news'),('w7',['M_notice',*REPS['notice']],SEEDS,'notice'),('w24',['M_notice',*REPS['notice']],SEEDS,'notice'),('w7_shift',['M_shift_notice','P_shift'],SEEDS[:1],'notice')]:
        origins=pd.date_range('2026-05-19','2026-09-30').strftime('%Y-%m-%d').tolist() if task=='news' else ['prewindow_frozen_C_bank']
        wanted.extend((group,task,a,s,o) for a in arms for s in seeds for o in origins)
    check('seeds_windows/fixed_fit_population',sorted((e['group'],e['task'],e['arm'],e['seed'],e['origin']) for e in entries),sorted(wanted))
    values=verify_posthoc_values(v,F,expectations,post,entries,gate)
    check('seeds_windows/resource_rows',len(read('fit_resources')),298)
    final=json.loads((post/'FINAL_CHECKS.json').read_text())
    for name,count in [('analysis1_comparisons',60),('analysis2_comparisons',72),('placebo_comparisons',2),('daily_losses',5446),('reversals',44),('robust_reversals',5),('robust_notice_gains',3),('fit_resources',298)]:check('seeds_windows/final/row_count/'+name,len(read(name)),final['table_rows'][name])
    check('seeds_windows/final/state',final['state'],'PASS')
    gate()
    return values


def verify_posthoc_values(v,F,expectations,post,entries,gate):
    'Reconstruct both timestamp readings with the shared scoring calculations.'
    root=v.ROOT;check=v.check;printed=v.printed
    def read(name):
        with (post/'results'/f'{name}.csv').open(newline='') as f:return list(csv.DictReader(f))
    panels={task:p.loc[p.target_day.ge('2026-05-19')].reset_index(drop=True) if task=='news' else p for task,p in F.panels.items()}
    for task,p in panels.items():
        keys=v.norm(pd.read_parquet(root/f'forecasts/keys/{task}__COMMON_KEYS.parquet'))
        keys=keys.loc[keys.target_day.between(p.target_day.min(),p.target_day.max())].reset_index(drop=True)
        check('seeds_windows/common_keys/'+task,p[v.KEYS+['target_day']].equals(keys[v.KEYS+['target_day']]),True)
    def load(task,arm,seed,group):
        p=panels[task]
        if group=='original' and (arm!='N' or seed==20260919):
            pred=F.prediction(task,arm,seed)
            if task=='news':pred=pred[F.panels[task].target_day.ge('2026-05-19').to_numpy()]
            return pred
        group='no_text_'+task if group=='original' else group
        chosen=[e for e in entries if (e['task'],e['arm'],e['seed'],e['group'])==(task,arm,seed,group)]
        check(f'seeds_windows/keys/{task}/{group}/{arm}/{seed}/file_count',len(chosen),135 if task=='news' else 1)
        frames=[]
        for e in chosen:
            f=pd.read_parquet(root/e['path'],columns=v.KEYS+['target_day','prediction'])
            check('seeds_windows/file_rows/'+Path(e['path']).name,len(f),e['rows']);frames.append(f)
        f=v.norm(pd.concat(frames,ignore_index=True))
        check(f'seeds_windows/keys/{task}/{group}/{arm}/{seed}/exact',f[v.KEYS+['target_day']].equals(p[v.KEYS+['target_day']]),True)
        a=f.prediction.to_numpy(dtype='float64')
        if len(a)!=len(p) or not np.isfinite(a).all():raise ValueError('Incomplete or nonfinite seed and window forecast')
        return a
    daily_rows=read('daily_losses');cache={}

    frame=pd.DataFrame(daily_rows)
    keys=['task','arm','seed','group','placebo','target_day']
    check('seeds_windows/daily/no_duplicates',not frame.duplicated(keys).any(),True)
    check('seeds_windows/daily/row_count',len(frame),5446)
    for ident,ds in frame.groupby(keys[:-1],sort=True):
        task,arm,s,group,pl=ident;seed='mean' if s=='mean' else int(s)
        if seed=='mean':
            pred=np.mean([load(task,arm,x,group) for x in SEEDS],axis=0)
            if task=='notice':pred=pred.astype('float32')
        else:pred=load(task,arm,seed,group)
        panel=panels[task]
        loss=pd.DataFrame({'day':panel.target_day,'loss':np.abs(pred-panel.y.to_numpy(dtype='float64'))}).groupby('day',sort=True).loss.mean()
        if pl=='True':loss=loss.loc['2026-08-24':]
        label='seeds_windows/daily/'+'/'.join(ident)
        ds=ds.sort_values('target_day')
        check(label+'/day_keys',loss.index.tolist(),ds.target_day.tolist())
        for day,value,stored in zip(loss.index,loss.to_numpy(),ds.daily_mae):check(label+'/'+day,float(value),float(stored),atol=2e-12)
        cache[ident]=(loss.index.tolist(),loss.to_numpy(dtype='float64'))
        gate()
    # Apply the frozen bootstrap function to the seed and window losses.
    conf=root/'code/frozen/studies/confirmation/code'
    sys.path.insert(0,str(conf))
    frozen=module('_posthoc_scoring',conf/'scoring.py')
    official=module('_posthoc_bootstrap',root/'code/frozen/studies/inference/code/read_comparisons.py')
    sc=official.ChunkedScoring(frozen,draws=100000,chunk=512,gate=gate)
    comparisons={};seen=set();stats_cache={}
    identity=lambda r:(r['analysis'],r['task'],r['seed'],r['representation'],r['step'])
    for name,count in [('analysis1_comparisons',60),('analysis2_comparisons',72),('placebo_comparisons',2)]:
        rows=read(name);check('seeds_windows/'+name+'/row_count',len(rows),count)
        for i,r in enumerate(rows):
            key=identity(r)
            if key in seen:raise ValueError('Duplicate seed and window comparison')
            seen.add(key);pl=str(r['analysis']=='a2_w7_placebo')
            ka=(r['task'],r['arm'],r['seed'],r['arm_group'],pl);kb=(r['task'],r['reference'],r['seed'],r['reference_group'],pl)
            days,a=cache[ka];bdays,b=cache[kb];label=f'seeds_windows/{name}/{i}'
            check(label+'/paired_days',days,bdays)
            if (ka,kb) not in stats_cache:
                dm=frozen.dm_daily(a-b)
                independent=v.statistics(a,b)
                check(label+'/independent_n_minus_1_DM',dm['p_two_sided'],independent['p_two_sided'],prob=True)
                boot=sc.paired_percent_interval(a,b,sc.block_picks(len(days),7,days))
                check(label+'/undefined_bootstrap_draws',boot['undefined_draws'],0)
                stats_cache[ka,kb]={'n_days':len(days),'mae':float(a.mean()),'reference_mae':float(b.mean()),'delta_mae':dm['mean_difference'],'delta_percent':boot['effect_percent_reference_mae'],'p_nominal':dm['p_two_sided'],'interval95_low_percent':boot['interval95_percent'][0],'interval95_high_percent':boot['interval95_percent'][1],'bootstrap_draws':100000,'bootstrap_seed':20260925,'bootstrap_block_days':7}
            computed=stats_cache[ka,kb]
            for k,x in computed.items():check(label+'/'+k,x,float(r[k]),prob=k=='p_nominal',atol=2e-9 if k.startswith('interval') else None)
            comparisons[key]=dict(r,**computed)
    expected_pop=set()
    for an,task,group in ANALYSES:
        for seed in (*SEEDS,'mean'):
            for rep in REPS[task]:
                for step in ['activity','representation','net']:
                    key=(an,task,str(seed),rep,step);expected_pop.add(key);r=comparisons[key]
                    ref='M_notice' if task=='notice' else 'M'
                    check('seeds_windows/comparison_design/'+'/'.join(key),(r['arm'],r['reference'],r['arm_group'],r['reference_group']),(ref if step=='activity' else rep,ref if step=='representation' else 'N',group,group if step=='representation' else 'original'))
    check('seeds_windows/exact_comparison_population',set(k for k in comparisons if k[0]!='a2_w7_placebo')==expected_pop,True)
    def get(an,task,rep,step,seed='mean'):return comparisons[an,task,str(seed),rep,step]
    reversals={}
    for i,r in enumerate(read('reversals')):
        key=(r['analysis'],r['task'],r['seed'],r['representation'])
        if key in reversals:raise ValueError('Duplicate reversal')
        net=get(*key[:2],key[3],'net',key[2])['delta_percent'];step=get(*key[:2],key[3],'representation',key[2])['delta_percent']
        rev=bool(np.sign(net)!=np.sign(step));reversals[key]=rev
        check(f'seeds_windows/reversals/{i}/net',net,float(r['net_delta_percent']))
        check(f'seeds_windows/reversals/{i}/representation',step,float(r['representation_delta_percent']))
        check(f'seeds_windows/reversals/{i}/decision',rev,r['reversal']=='True')
    check('seeds_windows/reversal_population',set(reversals),{k[:4] for k in expected_pop})
    robust=[];robust_rows=read('robust_reversals')
    check('seeds_windows/robust_reversal_population',[(r['task'],r['representation']) for r in robust_rows],[(t,a) for t in ['news','notice'] for a in REPS[t]])
    for i,r in enumerate(robust_rows):
        task=r['task'];rep=r['representation'];orig=reversals['a1',task,'mean',rep];window=reversals['a2_w7',task,'mean',rep] if task=='notice' else orig
        robust.append(orig and window)
        for k,val in [('original_mean_reversal',orig),('w7_mean_reversal',window),('robust_reversal',orig and window),('news_reference_unchanged_by_analysis2',task=='news')]:check(f'seeds_windows/robust_reversals/{i}/{k}',val,r[k]=='True')
    adj=v.holm([get('a2_w7','notice',a,'representation')['p_nominal'] for a in REPS['notice']]);gains={};holm_by_rep={}
    gain_rows=read('robust_notice_gains');check('seeds_windows/robust_gain_population',[r['representation'] for r in gain_rows],REPS['notice'])
    for r,h in zip(gain_rows,adj):
        a=r['representation'];base=get('a2_w7','notice',a,'representation');label='seeds_windows/robust_notice_gains/'+a
        for k in r:
            if k in ['p_holm_notice_family','robust_gain']:continue
            if k in ['n_days','mae','reference_mae','delta_mae','delta_percent','p_nominal','interval95_low_percent','interval95_high_percent','bootstrap_draws','bootstrap_seed','bootstrap_block_days']:check(label+'/'+k,base[k],float(r[k]),prob=k=='p_nominal')
            else:check(label+'/'+k,base[k],r[k])
        check(label+'/Holm',h,float(r['p_holm_notice_family']),prob=True)
        gains[a]=bool(base['delta_percent']<0 and h<.05);holm_by_rep[a]=h
        check(label+'/decision',gains[a],r['robust_gain']=='True')
    decisions=json.loads((post/'DECISIONS.json').read_text())
    for k,val in [('state','COMPLETE'),('robust_reversals_count',sum(robust)),('robust_notice_gains_count',sum(gains.values())),('robust_notice_gains_all_three',all(gains.values())),('notice_reversals_disappear_under_w7',not any(reversals['a2_w7','notice','mean',a] for a in REPS['notice'])),('rule1_all_seeds_means_windows_reported',True),('rule5_no_additional_variants',True)]:check('seeds_windows/decisions/'+k,val,decisions[k])
    if expectations is not None:
        def effect_cell(label,r,cell):
            parts=cell.replace('−','-').split(' (');printed(label+'/delta_percent',r['delta_percent'],parts[0]);printed(label+'/p_nominal',r['p_nominal'],parts[1].rstrip(')'))

        order=[(an,'notice',a) for a in REPS['notice'] for an in ['a1','a2_w7','a2_w24']]+[('a1','news',a) for a in REPS['news']]
        for tab,table in [('4',expectations['tables']['4']),('S1',expectations['supplement_tables']['S1'])]:
            check('seeds_windows/paper/Table'+tab+'/row_count',len(table['rows']),11)
            for i,(row,(an,task,a)) in enumerate(zip(table['rows'],order)):
                for col,step in enumerate(['activity','representation','net'],2):
                    r=get(an,task,a,step);label=f'paper/Table{tab}/{i}/{step}';cell=row['cells'][col]
                    if tab=='4':effect_cell(label,r,cell)
                    else:
                        vals=re.findall(r'[+−-]?\d+\.\d+',cell)
                        for k,c in zip(['delta_percent','interval95_low_percent','interval95_high_percent'],vals):printed(label+'/'+k,r[k],c)
                if tab=='4':check(f'paper/Table4/{i}/reversal','Yes' if reversals[an,task,'mean',a] else 'No',row['cells'][5])
        d2=expectations['tables']['D2']['rows'];check('paper/TableD2/row_count',len(d2),8)
        for i,(an,task,group) in enumerate(ANALYSES):
            for j,seed in enumerate((*SEEDS,'mean'),1):
                effect_cell(f'paper/TableD2/{i}/{seed}',get(an,task,REPS[task][0],'activity',seed),d2[2*i]['cells'][j])
                names=', '.join(NAMES[a] for a in REPS[task] if reversals[an,task,str(seed),a]) or 'None'
                check(f'paper/TableD2/{i}/{seed}/reversals',names,d2[2*i+1]['cells'][j])
        s2=expectations['supplement_tables']['S2']['rows'];check('paper/TableS2/row_count',len(s2),22)
        for i,(an,task,a) in enumerate(order):
            for j,step in enumerate(['representation','net']):
                for c,seed in enumerate(SEEDS,3):effect_cell(f'paper/TableS2/{2*i+j}/{seed}',get(an,task,a,step,seed),s2[2*i+j]['cells'][c])


        for record in expectations['posthoc_text_numbers']:
            tokens=re.findall(r'(?<!\d)[−+-]?\d+\.\d+',record['text'])
            check('seeds_windows/prose/'+record['label']+'/complete_decimal_coverage',len(tokens),len(record['bindings']))
            for i,(token,binding) in enumerate(zip(tokens,record['bindings'])):
                if binding is None:continue
                if binding[0]=='representation_range':
                    _,rep,endpoint=binding
                    candidates=[abs(get(an,'notice',rep,'representation')['delta_percent']) for an in ['a1','a2_w7','a2_w24']]
                    value=(min if endpoint=='min' else max)(candidates);absolute=False
                elif binding[0]=='comparison':
                    _,an,task,rep,step,seed,metric,absolute=binding
                    value=get(an,task,rep,step,seed)[metric]
                elif binding[0]=='holm':_,rep=binding;value=holm_by_rep[rep];absolute=False
                elif binding[0]=='placebo':_,step,metric,absolute=binding;value=get('a2_w7_placebo','notice','L_chen_notice',step,20260919)[metric]
                elif binding[0]=='rule_threshold':_,value=binding;absolute=False
                elif binding[0]=='legacy':
                    _,arm,ref,metric,absolute=binding;value=F.stats('notice',arm,ref,days=pd.date_range('2026-08-24','2026-09-30').strftime('%Y-%m-%d').tolist())[metric]
                else:raise ValueError('Unknown prose binding')
                if absolute:value=abs(value)
                cell=('<' if re.search(r'<\s*$',record['text'][:record['text'].find(token)]) else '')+token
                printed('seeds_windows/prose/'+record['label']+f'/{i}',value,cell)

    for seed,count in zip(SEEDS,[3,2,1]):check(f'seeds_windows/prose/original_reversal_count/{seed}',sum(reversals['a1',t,str(seed),a] for t in REPS for a in REPS[t]),count)
    for an in ['a2_w7','a2_w24']:
        check('seeds_windows/prose/window_reversal_seeds/'+an,sum(any(reversals[an,'notice',str(s),a] for a in REPS['notice']) for s in SEEDS),1)
        check('seeds_windows/prose/window_mean_reversals/'+an,sum(reversals[an,'notice','mean',a] for a in REPS['notice']),0)
    check('seeds_windows/prose/robust_reversal_count',sum(robust),0);check('seeds_windows/prose/robust_notice_gains',sum(gains.values()),2)
    check('seeds_windows/prose/three_seeds',len(SEEDS),3)
    if expectations is not None:check('seeds_windows/supplement_hash',v.sha(root/expectations['supplement_source']),expectations['supplement_sha256'])
    return dict(daily=cache,comparisons=comparisons,reversals=reversals,gains=gains,holm=holm_by_rep,scoring=sc)
