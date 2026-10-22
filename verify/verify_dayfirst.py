'Reconstruct day-first results from forecasts, truth and common keys.'
from pathlib import Path
from functools import lru_cache
from types import SimpleNamespace
import ast,copy,csv,json,re,shutil
import numpy as np
import pandas as pd
from verify_posthoc import module,verify_posthoc_values,SEEDS,REPS

NUM=re.compile(r'(?<!\d)(?:<\s*)?[+−-]?\d+\.\d+')

def verify_dayfirst(v,F,monthfirst):
    root=v.ROOT;post=root/'dayfirst'
    def check(label,*a,**kw):return v.check('dayfirst/'+label,*a,**kw)
    def printed(label,*a):return v.printed('dayfirst/'+label,*a)
    def read(name):return json.loads((post/name).read_text())
    def csvrows(name):
        with (post/'results'/f'{name}.csv').open(newline='') as f:return list(csv.DictReader(f))
    def gate():
        if shutil.disk_usage(root).free<2_000_000_000:raise RuntimeError('STOP: free disk below 2 GB')
    gate()
    expected=json.loads((root/'verify/expected_paper_values.json').read_text())
    check('paper/source_description',expected['paper_source'],'Paper accompanying this replication package (Markdown source)')
    check('paper/source_digest',bool(re.fullmatch('[a-f0-9]{64}',expected['paper_sha256'])),True)
    supplement=(root/expected['supplement_source']).read_text().splitlines()
    check('paper/supplement/hash',v.sha(root/expected['supplement_source']),expected['supplement_sha256'])
    for key,tbl in expected['supplement_tables'].items():
        check(f'paper/supplement/{key}/caption',supplement[tbl['caption_line']-1],tbl['caption'])
        for i,row in enumerate(tbl['rows']):check(f'paper/supplement/{key}/row{i}',[x.strip() for x in supplement[row['source_line']-1].strip('|').split('|')],row['cells'])
    for rec in expected['posthoc_text_numbers']:
        if rec['source']=='supplement':check('paper/prose/'+rec['label'],supplement[rec['source_line']-1],rec['text'])
    timing=expected['notice_listing_timing']
    clock=v.read(timing['result_source'])
    for part in timing['result_pointer'].strip('/').split('/'):
        clock=clock[int(part)] if isinstance(clock,list) else clock[part]
    for rec in timing['prose']:
        label='paper/notice_listing/'+rec['label']
        if rec['source']=='supplement':
            check(label+'/source',supplement[rec['source_line']-1],rec['text'])
        matches=re.findall(rec['pattern'],rec['text'])
        check(label+'/coverage',len(matches),1)
        if len(matches)==1:
            check(label+'/printed_minutes',int(matches[0]),int(rec['printed_minutes']))
            check(label+'/a0_minutes',int(matches[0]),clock)


    for item in read('PROVENANCE.json')['files']:
        check('provenance/'+item['destination'],v.sha(root/item['destination']),item['sha256'])
    for item in read('INPUT_RECORDS.json'):
        check('portable/'+item['file'],v.sha(root/item['file']),item['package_sha256'])
        check('original_hash_recorded/'+item['file'],bool(re.fullmatch('[a-f0-9]{64}',item['original_sha256'])),True)
    eq=read('EQUIVALENCE.json');check('equivalence/state',eq['state'],'PASSED')
    gates=[*eq['month_first_checks'],*eq['day_first_checks'],*eq['delayed_month_first_checks']]
    check('equivalence/count',len(gates),37)
    for i,e in enumerate(gates):
        check(f'equivalence/{i}/state',e['state'],'PASS')
        for key,d in e.get('differences',{}).items():check(f'equivalence/{i}/{key}',d,0.,atol=1e-9)
    predictions=read('PREDICTIONS.json');entries=predictions['predictions'];check('predictions/count',len(entries),35)
    check('predictions/no_refit',predictions['models_refitted'],0)
    new={(e['group'],e['arm'],e['seed'],e['delta_minutes']):e for e in entries}
    check('predictions/unique',len(new),35)
    manifest={p:h for h,p in (line.split('  ',1) for line in (post/'predictions/SHA256SUMS').read_text().splitlines())}
    check('predictions/manifest_population',set(manifest),{str(p.relative_to(post/'predictions')) for p in (post/'predictions').rglob('*.parquet')})
    for e in entries:
        path=root/e['prediction_path'];check('predictions/hash/'+e['id'],v.sha(path),e['prediction_sha256'])
        check('predictions/manifest/'+e['id'],manifest[str(path.relative_to(post/'predictions'))],e['prediction_sha256'])
    inventory=pd.read_csv(post/'MODEL_INVENTORY.csv');check('inventory/rows',len(inventory),91)
    check('inventory/instances',inventory.model_path.nunique(),58)
    support=read('supporting_forecasts/INDEX.json')
    support_by={(e['arm'],e['delta_minutes']):e for e in support}
    check('support/population',set(support_by),{(a,d) for a in ['M+_n','L14+','L_Laz+','L_chen_notice+'] for d in [5,15,60]})
    support_manifest={p:h for h,p in (line.split('  ',1) for line in (post/'supporting_forecasts/SHA256SUMS').read_text().splitlines())}
    for e in support:
        check('support/hash/'+Path(e['path']).name,v.sha(root/e['path']),e['sha256'])
        check('support/manifest/'+Path(e['path']).name,support_manifest[Path(e['path']).name],e['sha256'])
    @lru_cache(maxsize=8)
    def prediction(arm,seed=20260919,version='day-first',delta=0,raw=False):
        if seed=='mean':return np.mean([prediction(arm,s,version,delta,raw) for s in SEEDS],axis=0)
        group='windowed_activity' if arm.endswith('+') or arm=='M+_n' else 'official'
        changed=new.get((group,arm,seed,delta)) if version=='day-first' else None
        if changed:rel=changed['prediction_path']
        elif delta:rel=support_by[arm,delta]['path'] if group=='windowed_activity' else f'forecasts/delayed/notice__{arm}__delay{delta}.parquet'
        else:rel=F.entries['notice',arm,seed,'main']
        f=v.norm(pd.read_parquet(v.evidence(rel),columns=v.KEYS+['target_day','raw_prediction' if raw else 'prediction']))
        panel=F.panels['notice']
        check(f'keys/{version}/{arm}/{seed}/{delta}/{raw}',f[v.KEYS+['target_day']].equals(panel[v.KEYS+['target_day']]),True)
        a=f['raw_prediction' if raw else 'prediction'].to_numpy(dtype='float64')
        check(f'finite/{version}/{arm}/{seed}/{delta}/{raw}',bool(np.isfinite(a).all()),True)
        return a


    keys=v.norm(pd.read_parquet(root/'forecasts/keys/notice__COMMON_KEYS.parquet'))
    check('common_keys',keys[v.KEYS+['target_day']].equals(F.panels['notice'][v.KEYS+['target_day']]),True)
    prediction_daily={}
    for e in entries:
        f=v.norm(pd.read_parquet(root/e['prediction_path'],columns=v.KEYS+['target_day','prediction']))
        check('prediction_keys/'+e['id'],f[v.KEYS+['target_day']].equals(keys[v.KEYS+['target_day']]),True)
        check('prediction_rows/'+e['id'],len(f),527040)
        check('prediction_finite/'+e['id'],bool(np.isfinite(f.prediction).all()),True)
        loss=F.aggregate('notice',f.prediction.to_numpy(dtype='float64'))
        prediction_daily[e['id']]=loss
        check('prediction_daily_count/'+e['id'],len(loss),61)


    class MainForecasts(type(F)):
        def __init__(self):
            self.panels=F.panels;self.entries=F.entries;self.daily_cache={};self.square_cache={}
        def prediction(self,task,arm,seed=20260919,variant='main',rel=None):
            if task=='notice' and rel is None:return prediction(arm,seed)
            return F.prediction(task,arm,seed,variant,rel)
    mainF=MainForecasts()
    combined=copy.deepcopy(json.loads((root/'seeds_windows/forecasts/INDEX.json').read_text())['predictions'])
    for e in combined:
        change=new.get((e['group'],e['arm'],e['seed'],0))
        if change:e['path']=change['prediction_path'];e['sha256']=change['prediction_sha256']
    proxy=SimpleNamespace(**{k:getattr(v,k) for k in ['ROOT','KEYS','norm','statistics','sha','holm']},check=check,printed=printed)
    values=verify_posthoc_values(proxy,mainF,expected,post,combined,gate)
    sc=values['scoring'];conf=root/'code/frozen/studies/confirmation'
    primary_tests=module('_dayfirst_A2',conf/'primary_tests/code/primary_comparisons.py')
    a1=module('_dayfirst_a1',conf/'execution/additional_scoring.py')
    official=module('_dayfirst_official',root/'code/frozen/studies/inference/code/read_comparisons.py')
    @lru_cache(maxsize=128)
    def daily(arm,seed=20260919,version='day-first',delta=0,power=1,reclip=False,combination=False):
        p=prediction(arm,seed,version,delta,reclip)
        if seed=='mean' and not combination:p=p.astype('float32')
        if reclip:p=a1.official_reclip(p,F.panels['notice'].target_time).astype('float64')
        if combination:p=.5*(prediction('NP',20260919,version)+p)
        return F.aggregate('notice',p,power=power)
    specs=read('OFFICIAL_SPECS.json');tree=read('OFFICIAL_DAYFIRST.json');computed={};slots={};official_daily={}
    check('official/family_population',set(tree),set(specs['metadata']))
    bundles={(b['id']):b for b in specs['bundles']}
    check('official/bundle_population',set(bundles),{fam+'/'+version for fam in tree for version in ['month-first','day-first']})
    all_days=F.panels['notice'].target_day.drop_duplicates().tolist()
    def compare(label,x,y):
        if isinstance(y,dict):
            check(label+'/fields',set(x),set(y))
            for k in y:compare(label+'/'+k,x[k],y[k])
        elif isinstance(y,list):
            check(label+'/length',len(x),len(y))
            for i,(a,b) in enumerate(zip(x,y)):compare(label+'/'+str(i),a,b)
        else:check(label,x,y,prob=('p_two_sided' in label or label.endswith('_p')),atol=2e-9 if ('interval' in label or label.endswith('/tail_draws_expected')) else None)
    for fam,meta in specs['metadata'].items():
        condition=meta['condition'];days=condition.get('days',all_days);ix=[all_days.index(d) for d in days]
        check('official/'+fam+'/pairs',meta['pairs'],bundles[fam+'/day-first']['pairs'])


        original_rows={r['slot_id']:r for r in v.read('results/score/export/OFFICIAL_RESULTS.json')['rows']}
        for i,slot in enumerate(meta.get('slots',[])):
            ident=original_rows[slot]['identity'];check(f'official/{fam}/slot{i}',meta['pairs'][i],[ident['arm'],ident['reference']])
        for version in ['month-first','day-first']:
            bundle=bundles[fam+'/'+version];losses={}
            for arm in dict.fromkeys(a for pair in meta['pairs'] for a in pair):
                loss=daily(arm,version=version,**{k:x for k,x in condition.items() if k!='days'})[ix];losses[arm]=loss
                check(f'official/{fam}/{version}/{arm}/daily',float(np.max(np.abs(loss-np.asarray(bundle['losses'][arm])))),0.,atol=2e-12)
            official_daily[fam,version]=losses
            current=dict(bundle,state='COMPUTED',losses=losses)
            result=official.compute_bundle(primary_tests,sc,current)
            if fam=='notice/subsets':
                for r in result['reports']:
                    for key in ['decision','hac7_decision','hln_decision','holm_p','hac7_holm_p','hln_holm_p']:r[key]=None

            def safe(x):
                if isinstance(x,dict):return {k:safe(a) for k,a in x.items() if k!='draws'}
                if isinstance(x,(list,tuple)):return [safe(a) for a in x]
                if isinstance(x,np.ndarray):return x.tolist()
                if isinstance(x,np.generic):return x.item()
                return x
            result=safe(result);compare(f'official/{fam}/{version}',result,tree[fam][version]);computed[fam,version]=result
            for i,slot in enumerate(meta.get('slots',[])):slots[slot,version]=result['reports'][i]
            gate()


    for e in entries:
        if e['group'] in ['w7','w24']:
            key=('notice',e['arm'],str(e['seed']),e['group'],'False')
            target=values['daily'][key][1]
        else:
            fam=('notice/R8' if e['group']=='windowed_activity' else 'notice/primary')
            if e['delta_minutes']:fam=('notice/R8_delay' if e['group']=='windowed_activity' else 'notice/delay')+str(e['delta_minutes'])
            elif e['group']=='official' and e['seed']!=20260919:fam='notice/seed_'+str(e['seed'])
            elif e['arm'] not in REPS['notice'] and e['group']=='official':


                fam={'R':'notice/native:notice__SECONDARY__R__N','NPL':'notice/native:notice__SECONDARY__NPL__N','NPP':'notice/native:notice__SECONDARY__NPP__N'}[e['arm']]
            loss=prediction_daily[e['id']];days=specs['metadata'][fam]['condition'].get('days',all_days)
            loss=loss[[all_days.index(d) for d in days]];target=official_daily[fam,'day-first'][e['arm']]
            check('prediction_daily/'+e['id'],float(np.max(np.abs(loss-target))),0.,atol=2e-12);continue
        check('prediction_daily/'+e['id'],float(np.max(np.abs(prediction_daily[e['id']]-target))),0.,atol=2e-12)

    intervals=csvrows('posthoc_intervals_both_blocks');check('intervals/row_count',len(intervals),268)
    boots={}
    for i,r in enumerate(intervals):
        source=monthfirst if r['version']=='month-first' else values
        key=(r['analysis'],r['task'],r['seed'],r['representation'],r['step']);c=source['comparisons'][key];pl=str(r['analysis']=='a2_w7_placebo')
        ka=(r['task'],c['arm'],r['seed'],c['arm_group'],pl);kb=(r['task'],c['reference'],r['seed'],c['reference_group'],pl)
        days,a=source['daily'][ka];_,b=source['daily'][kb]
        printed_label=f'intervals/{i}'
        check(printed_label+'/effect',c['delta_percent'],float(r['delta_percent']))
        for block,name in [(1,'one'),(7,'seven')]:
            cachekey=(r['version'],ka,kb,block)
            if cachekey not in boots:boots[cachekey]=sc.paired_percent_interval(a,b,sc.block_picks(len(days),block,days))['interval95_percent']
            for j,end in enumerate(['low','high']):check(printed_label+f'/{block}/{end}',boots[cachekey][j],float(r[f'interval95_{name}_day_{end}']),atol=2e-9)


    def rowvals(tab,row,report,cols):
        for col,metric in cols:
            cell=row['cells'][col]
            if cell in ['–','—','-','']:continue
            printed(f'paper/Table{tab}/line{row["source_line"]}/{metric}',report[metric],cell)
    table5=[None,50,2,3,4,61,62,51,52,53,64,63,58]
    for row,slot in zip(expected['tables']['5']['rows'],table5):
        if slot is None:printed('paper/Table5/no_text',float(mainF.losses('notice','N').mean()),row['cells'][2]);continue
        report=slots.get((f'forest/{slot:03}','day-first'))
        if report is None:

            report=next(r['value']['native'] for r in v.read('results/score/export/OFFICIAL_RESULTS.json')['rows'] if r['slot_id']==f'forest/{slot:03}')
        rowvals('5',row,report,[(2,'arm_mae'),(3,'effect_percent_reference_mae'),(4,'mean_difference'),(5,'p_two_sided'),(6,'holm_p')])
    primary=computed['notice/primary','day-first']['reports']
    for i,row in enumerate(expected['tables']['A1']['rows']):
        for j,r in enumerate(primary,1):
            x=r[['hac7_p_two_sided','hln_p_two_sided'][i]] if i<2 else r['bootstrap'][str(1 if i==2 else 7)]['interval95_percent']
            printed(f'paper/TableA1/{i}/{j}',x,row['cells'][j])
    families=['notice/primary','notice/seed_20260920','notice/seed_20260921','notice/primary_mean','notice/squared','notice/drop_first_seven','notice/R8']
    for i,(row,fam) in enumerate(zip(expected['tables']['D1']['rows'],families)):
        for j,r in enumerate(computed[fam,'day-first']['reports']):
            for k,metric in enumerate(['effect_percent_reference_mae','holm_p' if i==6 else 'p_two_sided']):printed(f'paper/TableD1/{i}/{j}/{metric}',r[metric],row['cells'][1+2*j+k])
    delay_rows=expected['tables']['D1']['rows']
    dayfirst_row=next(r for r in delay_rows if r['cells'][0].startswith('Day-first date parsing'))
    monthfirst_row=next(r for r in delay_rows if r['cells'][0].startswith('Month-first date parsing'))
    check('paper/TableD1/dayfirst_is_main','main estimates' in dayfirst_row['cells'][0],True)
    check('paper/TableD1/monthfirst_is_sensitivity','main estimates' in monthfirst_row['cells'][0],False)
    for j in range(3):
        rs=[computed[f,'day-first']['reports'][j] for f in ['notice/primary','notice/delay5','notice/delay15','notice/delay60']]
        printed(f'paper/TableD1/dayfirst_delays/{j}/range',[min(r['effect_percent_reference_mae'] for r in rs),max(r['effect_percent_reference_mae'] for r in rs)],dayfirst_row['cells'][1+2*j])
        printed(f'paper/TableD1/dayfirst_delays/{j}/Holm',max(r['holm_p'] for r in rs),dayfirst_row['cells'][2+2*j])
    for i,(row,slot) in enumerate(zip(expected['tables']['D3']['rows'],[58,68,59,65,69,66,None,None])):
        if slot is not None and (f'forest/{slot:03}','day-first') in slots:
            rowvals('D3',row,slots[f'forest/{slot:03}','day-first'],[(1,'effect_percent_reference_mae'),(2,'mean_difference'),(3,'p_two_sided')])

    def flatten(r):
        out={k:r.get(k) for k in ['n_days','arm_mae','reference_mae','mean_difference','effect_percent_reference_mae','p_two_sided','holm_p','hac7_p_two_sided','hac7_holm_p','hln_p_two_sided','hln_holm_p','decision','hac7_decision','hln_decision','hac7_state']}
        for block in ['1','7']:
            for key,prefix in [('interval95_percent','interval95'),('interval_family_adjusted_percent','interval_family')]:
                val=r.get('bootstrap',{}).get(block,{}).get(key)
                for j,end in enumerate(['low','high']):out[f'{prefix}_{block}_{end}']=None if val is None else val[j]
        return out
    for i,r in enumerate(csvrows('official_comparisons')):
        a=flatten(computed[r['family'],r['version']]['reports'][int(r['index'])])
        for key,x in a.items():
            y=r[key];target=None if y=='' else (float(y) if isinstance(x,(float,int,np.number)) else y)
            check(f'official_csv/{i}/{key}',x,target,prob=('p_two_sided' in key or key.endswith('_p')),atol=2e-9 if key.startswith('interval') else None)
    changes=csvrows('official_comparison_changes');check('official_changes/count',len(changes),80)
    for i,r in enumerate(changes):
        a,b=[computed[r['family'],ver]['reports'][int(r['index'])] for ver in ['month-first','day-first']]
        for key,x in [('sign_change',np.sign(a['mean_difference'])!=np.sign(b['mean_difference'])),('nominal_significance_change',(a['p_two_sided']<.05)!=(b['p_two_sided']<.05)),('decision_change',a['decision']!=b['decision']),('hac7_decision_change',a['hac7_decision']!=b['hac7_decision']),('student_t_decision_change',a['hln_decision']!=b['hln_decision'])]:check(f'official_changes/{i}/{key}',bool(x),r[key]=='True')
        fa,fb=flatten(a),flatten(b)
        check(f'official_changes/{i}/numerical_change',any(fa[k]!=fb[k] for k in fa),r['numerical_change']=='True')
        for version,data in [('month_first',fa),('day_first',fb)]:
            for key,x in data.items():
                target=r[version+'_'+key]
                target=None if target=='' else (float(target) if isinstance(x,(float,int,np.number)) else target)
                check(f'official_changes/{i}/{version}/{key}',x,target,prob=('p_two_sided' in key or key.endswith('_p')),atol=2e-9 if key.startswith('interval') else None)
        check(f'official_changes/{i}/sign_retained',np.sign(a['mean_difference'])==np.sign(b['mean_difference']),True)
        check(f'official_changes/{i}/decision_retained',a['decision']==b['decision'],True)
    postchanges=csvrows('posthoc_comparison_changes');check('posthoc_changes/count',len(postchanges),134);nominal=0
    for i,r in enumerate(postchanges):
        key=(r['analysis'],r['task'],r['seed'],r['representation'],r['step']);a=monthfirst['comparisons'][key];b=values['comparisons'][key]
        check(f'posthoc_changes/{i}/sign_retained',np.sign(a['delta_percent'])==np.sign(b['delta_percent']),True)
        changed=(a['p_nominal']<.05)!=(b['p_nominal']<.05);nominal+=changed
        check(f'posthoc_changes/{i}/nominal',bool(changed),r['nominal_significance_change']=='True')
        for version,stats in [('month_first',a),('day_first',b)]:
            for key,x in stats.items():
                if key+'_'+version not in r:continue
                target=r[key+'_'+version]
                if isinstance(x,(int,float,np.number)):target=float(target)
                check(f'posthoc_changes/{i}/{version}/{key}',x,target,prob=key=='p_nominal',atol=2e-9 if key.startswith('interval') else None)
    check('posthoc_changes/nominal_count',int(nominal),1)
    for key in ['gains','reversals']:check('decisions/'+key,values[key],monthfirst[key])
    verify_sensitivity(v,check,printed,expected,computed,csvrows('official_comparison_changes'),post)
    gate()


def verify_sensitivity(v,check,printed,expected,computed,rows,post):

    spec=expected['date_parsing_sensitivity']
    lines=(v.ROOT/expected['supplement_source']).read_text().splitlines()
    for line,text in zip(spec['source_lines'],spec['texts']):check(f'sensitivity/source/{line}',lines[line-1],text)
    changes=json.loads((post/'FEATURE_CHANGES.json').read_text())
    def records(x):
        if isinstance(x,dict):
            yield x
            for y in x.values():yield from records(y)
        elif isinstance(x,list):
            for y in x:yield from records(y)
    for arm,count in spec['feature_rows'].items():
        candidates=[r for r in records(changes) if r.get('arm')==arm]
        check('sensitivity/feature_record/'+arm,len(candidates),1)
        check('sensitivity/feature_rows/'+arm,candidates[0]['changed_input_rows'],count)
        check('sensitivity/evaluation_rows/'+arm,candidates[0]['rows'],spec['evaluation_rows'])
    primary=[]
    for family in ['notice/primary','notice/delay5','notice/delay15','notice/delay60']:
        for a,b in zip(computed[family,'month-first']['reports'],computed[family,'day-first']['reports']):
            primary.append(abs(a['effect_percent_reference_mae']-b['effect_percent_reference_mae']))
            for reading,r in [('month-first',a),('day-first',b)]:check('sensitivity/Holm/'+family+'/'+reading,r['holm_p']<spec['holm_upper_bound'],True)
    check('sensitivity/primary_effect_difference',max(primary)<spec['primary_effect_difference_upper_bound'],True)
    diffs=[abs(float(r['month_first_effect_percent_reference_mae'])-float(r['day_first_effect_percent_reference_mae'])) for r in rows]
    with (post/'results/posthoc_comparison_changes.csv').open(newline='') as stream:postrows=list(csv.DictReader(stream))
    diffs += [abs(float(r['delta_percent_month_first'])-float(r['delta_percent_day_first'])) for r in postrows]
    printed('sensitivity/all_comparison_maximum',max(diffs),spec['all_comparison_maximum_rounded'])
    check('sensitivity/sign_changes',sum(r['sign_change']=='True' for r in [*rows,*postrows]),spec['sign_changes'])
    check('sensitivity/Holm_decision_changes',sum(r['decision_change']=='True' for r in rows),spec['holm_decision_changes'])
