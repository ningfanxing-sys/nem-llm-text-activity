
'Reconstruct the printed tables from saved forecasts and truth.'
from __future__ import annotations
import hashlib
import json
import math
import re
import sys
import time
import zipfile
sys.dont_write_bytecode=True
from recover_files import Recovery
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import t

ROOT=Path(__file__).resolve().parents[1]
SEED=20260919
KEYS=['origin','target_time','region','horizon']
PRIMARY={'news':['L_count','L_chen'],'notice':['L14','L_Laz','L_chen_notice']}
REF={'news':'M','notice':'M_notice'}
COUNTS={'news':72,'notice':8640}
checks=[];maximum={};bootstrap_max=0.0
recovery=None

def evidence(rel):
    return recovery.path(rel)


def read(rel):
    p=evidence(rel).resolve()
    if not p.is_relative_to(ROOT):raise ValueError('Path leaves package')
    return json.loads(p.read_text())

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1<<20),b''):h.update(block)
    return h.hexdigest()

def check(label,actual,expected,*,prob=False,atol=None):
    if isinstance(actual,(float,int,np.number)) and isinstance(expected,(float,int,np.number)):
        diff=abs(float(actual)-float(expected))
        tolerance=(1e-18+1e-7*abs(float(expected))) if prob else (1e-9+1e-12*abs(float(expected)))
        if atol is not None:tolerance=atol
        passed=bool(np.isfinite(actual) and diff<=tolerance)
        category='probability' if prob else 'scalar'
        maximum[category]=max(maximum.get(category,0),diff)
    else:diff=None;passed=actual==expected
    checks.append({'label':label,'pass':bool(passed),'actual':actual,'expected':expected,'absolute_difference':diff})
    print(('PASS ' if passed else 'FAIL ')+label+(f' (difference={diff:.3g})' if diff is not None else ''),flush=True)
    return passed

def printed(label,actual,cell):

    s=cell.replace('−','-').replace('$','').replace('**','').strip()
    if s in ['–','—','-','']:return
    if isinstance(actual,(list,tuple,np.ndarray)):
        vals=re.findall(r'[+-]?\d+(?:\.\d+)?',s)
        if len(vals)!=len(actual):raise ValueError('Unexpected interval cell '+s)
        for i,(x,c) in enumerate(zip(actual,vals)):printed(label+f'[{i}]',float(x),c)
        return
    if '<' in s:
        m=re.search(r'10\^\{(-?\d+)\}',s)
        limit=10.**int(m.group(1)) if m else float(s.replace('<','').strip())
        ok=bool(np.isfinite(actual) and actual<limit)
        checks.append({'label':label,'pass':ok,'actual':float(actual),'expected_printed':cell})
        print(('PASS ' if ok else 'FAIL ')+label+' '+cell,flush=True);return
    value=float(s);decimals=len(s.split('.')[1]) if '.' in s else 0
    tolerance=.5*10**(-decimals)+2e-12
    diff=abs(float(actual)-value);ok=bool(np.isfinite(actual) and diff<=tolerance)
    maximum['paper_rounding_difference']=max(maximum.get('paper_rounding_difference',0),diff)
    checks.append({'label':label,'pass':ok,'actual':float(actual),'expected_printed':cell,'absolute_difference':diff,'rounding_tolerance':tolerance})
    print(('PASS ' if ok else 'FAIL ')+label+f' printed={cell}, recomputed={actual:.12g}',flush=True)

def norm(frame):
    for k in ['origin','target_time']:frame[k]=pd.to_datetime(frame[k],utc=True).astype('datetime64[ns, UTC]')
    frame['target_day']=frame.target_day.astype(str)
    return frame.sort_values(KEYS,kind='mergesort').reset_index(drop=True)

def holm(ps):
    ps=np.asarray(ps,float);order=np.argsort(ps,kind='stable');out=np.empty(len(ps));running=0.
    for rank,i in enumerate(order):running=max(running,(len(ps)-rank)*ps[i]);out[i]=min(1.,running)
    return out

def statistics(a,b):
    a=np.asarray(a,float);b=np.asarray(b,float);d=a-b;n=len(d);mean=float(d.mean())
    statistic=math.sqrt(n)*mean/math.sqrt(float(d.var(ddof=1)))
    p=math.erfc(abs(statistic)/math.sqrt(2))
    z=d-mean;variance=float(z@z/n)
    for lag in range(1,min(7,n-1)+1):variance+=2*(1-lag/8)*float(z[lag:]@z[:-lag]/n)
    hac=math.erfc(abs(math.sqrt(n)*mean/math.sqrt(variance))/math.sqrt(2)) if variance>0 else None
    return {'n_days':n,'arm_mae':float(a.mean()),'reference_mae':float(b.mean()),'mean_difference':mean,
            'effect_percent_reference_mae':100.*mean/float(b.mean()),'p_two_sided':p,
            'hac7_p_two_sided':hac,'hln_p_two_sided':float(2*t.sf(abs(statistic),df=n-1))}

def bootstrap(a,b,task,index):
    'Draw non-circular moving blocks with one RNG stream per block length.'
    global bootstrap_max
    out={};n=len(a);z=np.load(ROOT/f'results/score/R2_STATE/scored/{task}__PRIMARY.npz',allow_pickle=False)
    for block in [1,7]:
        rng=np.random.default_rng(20260925);chunks=[];first_picks=None
        for start in range(0,100000,2000):
            starts=rng.choice(np.arange(n-block+1),size=(2000,math.ceil(n/block)))
            picks=(starts[...,None]+np.arange(block)).reshape(2000,-1)[:,:n]
            draws=100.*(a[picks]-b[picks]).mean(axis=1)/b[picks].mean(axis=1)
            if start==0:
                check(f'bootstrap/{task}/{index}/saved_picks_{block}',bool(np.array_equal(picks,z[f'picks_{block}'])),True)
                check(f'bootstrap/{task}/{index}/saved_draws_{block}',float(np.max(np.abs(draws-z[f'contrast_{index}_draws_{block}']))),0.,atol=2e-10)
            if start==0:draws=np.asarray(z[f'contrast_{index}_draws_{block}'],dtype='float64')
            chunks.append(draws)
        draws=np.concatenate(chunks)
        out[f'interval95_{block}']=np.quantile(draws,[.025,.975],method='linear').tolist()
    z.close();return out

class Forecasts:
    def __init__(self):
        self.panels={};self.entries={};self.daily_cache={};self.square_cache={}
        for tag,name in [('conf','SEAL.json'),('batch','SEAL_BATCH.json')]:
            seal=read('results/seals/'+name)
            for e in seal['predictions']:
                task='news' if e['source']=='lear' else e['source']
                self.entries[(task,e['arm'],e['seed'],e['variant'])]=f'forecasts/{tag}/'+Path(e['path']).name
        for task,name in [('news','news_keys_labels.parquet'),('notice','notice_joint.parquet')]:
            f=pd.read_parquet(evidence('forecasts/truth/'+name),columns=KEYS+['target_day','y','weight'])
            lo='2026-03-01' if task=='news' else '2026-08-01'
            f=norm(f.loc[f.target_day.astype(str).between(lo,'2026-09-30')].copy())
            expected_days=214 if task=='news' else 61
            counts=f.groupby('target_day').size()
            check(f'forecast/{task}/days',len(counts),expected_days)
            check(f'forecast/{task}/rows',len(f),expected_days*COUNTS[task])
            check(f'forecast/{task}/daily_complete',bool((counts==COUNTS[task]).all()),True)
            check(f'forecast/{task}/finite_truth_unit_weights',bool(np.isfinite(f.y).all() and f.weight.eq(1).all()),True)
            check(f'forecast/{task}/unique_keys',not f.duplicated(KEYS).any(),True)
            self.panels[task]=f
    def prediction(self,task,arm,seed=SEED,variant='main',rel=None):
        rel=rel or self.entries[(task,arm,seed,variant)]
        f=pd.read_parquet(evidence(rel),columns=KEYS+['target_day','prediction']);f=norm(f)
        panel=self.panels[task]
        if not f[KEYS].equals(panel[KEYS]):raise ValueError('Forecast and truth keys differ: '+rel)
        a=f.prediction.to_numpy(dtype='float64')
        if not np.isfinite(a).all():raise ValueError('Nonfinite prediction '+rel)
        return a
    def aggregate(self,task,pred,power=1,days=None):
        panel=self.panels[task];d=np.abs(pred-panel.y.to_numpy(dtype='float64'))
        if power==2:d=d*d
        frame=pd.DataFrame({'day':panel.target_day.to_numpy(),'loss':d})
        v=frame.groupby('day',sort=True).loss.mean()
        if days is None:days=v.index[v.index>='2026-05-19'].tolist() if task=='news' else v.index.tolist()
        return v.loc[days].to_numpy(dtype='float64')
    def losses(self,task,arm,seed=SEED,variant='main',power=1,days=None):
        key=(task,arm,seed,variant,power,tuple(days) if days is not None else None)
        if key not in self.daily_cache:
            if seed=='mean':
                p=np.mean([self.prediction(task,arm,s,variant) for s in [20260919,20260920,20260921]],axis=0)
                if task=='notice':p=p.astype('float32')
            else:p=self.prediction(task,arm,seed,variant)
            self.daily_cache[key]=self.aggregate(task,p,power=power,days=days)
        return self.daily_cache[key]
    def stats(self,task,arm,ref,seed=SEED,power=1,days=None):
        return statistics(self.losses(task,arm,seed,power=power,days=days),self.losses(task,ref,seed,power=power,days=days))

def run():
    global bootstrap_max
    begin=time.monotonic()
    for rel,entry in recovery.records.items():
        path=evidence(rel)
        check('integrity/recovered_original/'+rel,sha(path),entry['sha256'])
    expectations=read('verify/expected_paper_values.json')
    expected=expectations['tables']
    precise={(c['table'],c['row'],c['column']):c['cell']
             for c in expectations['numerical_precision_checks']['cells']}
    assert len(precise)==8
    official=read('results/score/export/OFFICIAL_RESULTS.json')
    check('official_results/sha256',sha(evidence('results/score/export/OFFICIAL_RESULTS.json')),'7fce73ed9e11542e2ec7515e6448e37a4c12c9f60103bf5b899f908544b8b591')
    rows={r['slot_id']:r['value'] for r in official['rows']}
    def forest(i):return rows[f'forest/{i:03}']['native']
    source_map=read('results/SOURCE_MAP.json')
    frozen=[e for e in source_map if e.get('byte_identical')]
    bad=[e['destination'] for e in frozen if sha(evidence(e['destination']))!=e['sha256']]
    check('integrity/byte_identical_frozen_files',len(bad),0)
    if bad:raise ValueError('Frozen evidence hash mismatch')
    print(f'Frozen files checked: {len(frozen)}',flush=True)
    labels=pd.read_parquet(evidence('extraction/notices/labels.parquet'),columns=['notice_id','package_partition'])
    check('notices/all_archive_labels',len(labels),21470)
    check('notices/unique_archive_ids',labels.notice_id.nunique(),21470)
    check('notices/partitions',labels.package_partition.value_counts().to_dict(),{'training':11348,'confirmation_leadin':796,'other_saved_prefix':9326})
    ids=set(labels.notice_id.astype(str))
    for name in ['scope.jsonl','extraction_ledger.jsonl']:
        seen=set();count=0
        with evidence('extraction/notices/'+name).open() as f:
            for line in f:seen.add(str(json.loads(line)['notice_id']));count+=1
        check('notices/'+name+'/all_archive_ids',seen==ids,True)
        if name=='scope.jsonl':check('notices/scope_one_record_per_id',count,21470)
    compressed=[e for e in source_map if e.get('transformation')=='lossless float32 array in NPZ']
    for e in compressed:
        h=hashlib.sha256()
        with zipfile.ZipFile(ROOT/e['destination']) as z,z.open('values.npy') as stream:
            for block in iter(lambda:stream.read(1<<20),b''):h.update(block)
        check('integrity/restored_npy/'+Path(e['destination']).name,h.hexdigest(),e['sha256'])
    by_source={e['source']:e for e in frozen}
    binding_count=0;binding_bad=0
    freeze=read('configs/confirmation/FREEZE.json')
    catalogue=read('configs/RUNTIME_SOURCES.json')['files']
    bound=[(e['path'],e['sha256']) for e in catalogue]
    bound += [('studies/confirmation/'+k,e['sha256']) for k,e in freeze['frozen_files'].items()]
    for source,digest in bound:
        if source in by_source:
            binding_count+=1;binding_bad+=by_source[source]['sha256']!=digest
    check('integrity/freeze_and_runtime_registration_bindings',binding_bad,0)
    receipt=read('results/score/R2_STATE/scored/SCORE_RECEIPT.json')
    check('integrity/specified_main_seal',sha(evidence('results/seals/SEAL.json')),receipt['seal_sha256'])
    main_seal=read('results/seals/SEAL.json')
    check('integrity/specified_design_freeze',sha(ROOT/'configs/confirmation/FREEZE.json'),main_seal['design_freeze_sha256'])
    check('integrity/specified_feature_manifest',sha(evidence('results/bindings/manifest.json')),main_seal['feature_manifest_sha256'])
    score_bad=sum(sha(ROOT/'results/score/R2_STATE/scored'/Path(e['path']).name)!=e['sha256'] for e in receipt['files'])
    check('integrity/all_131_score_receipt_files',score_bad,0)
    F=Forecasts();primary={};means={}
    for task in ['news','notice']:
        primary[task]=[F.stats(task,a,REF[task]) for a in PRIMARY[task]]
        means[task]=[F.stats(task,a,REF[task],seed='mean') for a in PRIMARY[task]]
        for rr in [primary[task],means[task]]:
            for r,h in zip(rr,holm([r['p_two_sided'] for r in rr])):r['holm_p']=float(h)
        daily=pd.read_csv(ROOT/f'results/score/R2_STATE/scored/{task}__DAILY_LOSSES.csv',float_precision='round_trip')
        for a in [REF[task],*PRIMARY[task],'N']:
            check(f'daily_losses/{task}/{a}',float(np.max(np.abs(F.losses(task,a)-daily[a].to_numpy()))),0.,atol=2e-12)
        for i,(arm,r) in enumerate(zip(PRIMARY[task],primary[task])):
            o=forest(i if task=='news' else i+2)
            for k in list(r):check(f'official/primary/{task}/{arm}/{k}',r[k],o[k],prob=k.endswith('_p') or '_p_' in k)
            b=bootstrap(F.losses(task,arm),F.losses(task,REF[task]),task,i);r.update(b)
            for block in [1,7]:
                for typ,oldkey in [('interval95','interval95_percent')]:
                    old=o['bootstrap'][str(block)][oldkey];new=b[f'{typ}_{block}']
                    for j,(x,y) in enumerate(zip(new,old)):
                        bootstrap_max=max(bootstrap_max,abs(x-y));check(f'official/bootstrap/{task}/{arm}/{typ}_{block}[{j}]',x,y,atol=2e-9)
            mo=rows[f'native-family/{task}/primary']['three_seed']['reports'][i]
            for k in ['effect_percent_reference_mae','holm_p']:
                check(f'official/mean/{task}/{arm}/{k}',means[task][i][k],mo[k],prob=k=='holm_p')


    placebo=pd.date_range('2026-08-24','2026-09-30').strftime('%Y-%m-%d').tolist()
    table_specs={
      '5':('notice',[(None,None,None),('M_notice','N',50),('L14','M_notice',2),('L_Laz','M_notice',3),('L_chen_notice','M_notice',4),('R','M_notice',61),('T','M_notice',62),('L14','N',51),('L_Laz','N',52),('L_chen_notice','N',53),('L_chen_notice','P_shift',64),('P_shift','M_shift_notice',63),('NP','N',58)]),
      '6':('news',[(None,None,None),('M','N',11),('L_count','M',0),('L_chen','M',1),('E_raw','M',18),('W2_D','M',31),('L_count','N',12),('L_chen','N',13),('M_shift','N',14),('L_chen','P_shift',21),('LEAR','N',17),('LEAR','M',22)])}
    for tab,(task,specs) in table_specs.items():
        assert len(specs)==len(expected[tab]['rows'])
        for no,(entry,(arm,ref,slot)) in enumerate(zip(expected[tab]['rows'],specs)):
            cells=entry['cells'];label=f'paper/Table{tab}/line{entry["source_line"]}'
            if arm is None:
                mae=float(F.losses(task,'N').mean());printed(label+'/MAE',mae,cells[2])
                official_mae=read('results/score/R2_STATE/scored/SCORE_REPORT.json')[task]['pooled_mae']['N']
                check(f'official/Table{tab}/N/MAE',mae,official_mae);continue
            days=placebo if task=='notice' and no in [10,11] else None
            r=F.stats(task,arm,ref,days=days);o=forest(slot)
            if arm in PRIMARY[task] and ref==REF[task] and days is None:r=primary[task][PRIMARY[task].index(arm)]
            for col,k in [(2,'arm_mae'),(3,'effect_percent_reference_mae'),(4,'mean_difference'),(5,'p_two_sided'),(6,'holm_p')]:
                if cells[col] in ['–','—','-','']:continue

                if task=='news':printed(label+'/'+expected[tab]['columns'][col],r[k],cells[col])
                check(f'official/Table{tab}/{no}/{k}',r[k],o[k],prob=k in ['p_two_sided','holm_p'])
    # Compare Table A1 with the HAC7 tests, Student-t tests and interval endpoints.
    ordered=[primary['notice'][i] for i in range(3)]+primary['news']
    order_meta=[('notice',i) for i in range(3)]+[('news',i) for i in range(2)]
    arows=expected['A1']['rows']
    fields=['hac7_p_two_sided','hln_p_two_sided','interval95_1','interval95_7']
    assert len(arows)==len(fields)
    for row,k in zip(arows,fields):
        assert len(row['cells'])==6
        for i,r in enumerate(ordered):
            if i>=3:printed(f'paper/TableA1/line{row["source_line"]}/contrast{i}/{k}',r[k],row['cells'][i+1])

    drows=expected['D1']['rows']
    assert len(drows)==10
    for rowno in range(7):
        erow=drows[rowno]
        for c,(task,j) in enumerate(order_meta):
            if rowno in [5,6] and task=='news':continue
            arm=PRIMARY[task][j];ref=REF[task];days=None;seed=SEED;power=1
            if rowno in [1,2]:seed=20260919+rowno
            if rowno==3:seed='mean'
            if rowno==4:power=2
            if rowno==5:days=pd.date_range('2026-08-08','2026-09-30').strftime('%Y-%m-%d').tolist()
            if rowno==6:arm=arm+'+';ref='M+_n'
            r=F.stats(task,arm,ref,seed,power,days)
            if rowno==6:
                allr=[F.stats(task,a+'+',ref) for a in PRIMARY[task]]
                r['holm_p']=float(holm([x['p_two_sided'] for x in allr])[j]);o=rows['metadata/batch_native']['families']['R8_notice']['reports'][j]
            elif rowno==4:
                o=rows['metadata/batch_native']['squared_loss']['primary'][task][j]
                o={'effect_percent_reference_mae':float(o['effect']),'p_two_sided':o['dm']['p_two_sided']}
            else:
                offset=0 if task=='news' else 2
                if rowno==1:offset=5 if task=='news' else 41
                if rowno==2:offset=7 if task=='news' else 44
                if rowno==3:offset=9 if task=='news' else 47
                if rowno==5:offset=71
                o=rows[f'native-family/{task}/primary']['three_seed']['reports'][j] if rowno==3 else forest(offset+j)
            metric='holm_p' if rowno==6 else 'p_two_sided'
            for v,k in [(0,'effect_percent_reference_mae'),(1,metric)]:

                if task=='news':printed(f'paper/TableD1/line{erow["source_line"]}/{task}/{j}/{k}',r[k],erow['cells'][1+2*c+v])
                check(f'official/TableD1/{rowno}/{task}/{j}/{k}',r[k],o[k],prob=k.endswith('_p') or k=='p_two_sided')
                if ('D1',rowno,1+2*c+v) in precise:
                    printed(f'precision/TableD1/{rowno}/{task}/{j}/{k}',r[k],precise[('D1',rowno,1+2*c+v)])


    delay_results={'specified':{},'aligned':{}}
    for mode in ['specified','aligned']:
        reading='month-first' if mode=='specified' else 'day-first'
        for delta in [0,5,15,60] if mode=='specified' else [0,15,60]:
            losses={}
            for arm in [REF['notice'],*PRIMARY['notice']]:
                if mode=='aligned' and arm in ['L14','L_Laz']:
                    name=f'{arm}__corrected_D'+(f'__delay{delta}' if delta else '')+'.parquet';rel='forecasts/dayfirst_dates/'+name
                elif delta:rel=f'forecasts/delayed/notice__{arm}__delay{delta}.parquet'
                else:rel=None
                p=F.prediction('notice',arm,rel=rel);losses[arm]=F.aggregate('notice',p)
            rs=[statistics(losses[a],losses[REF['notice']]) for a in PRIMARY['notice']]
            for r,h in zip(rs,holm([r['p_two_sided'] for r in rs])):r['holm_p']=float(h)
            delay_results[mode][delta]=rs
            for j,r in enumerate(rs):
                if mode=='specified' and delta==5:o=rows['metadata/batch_native']['DLY8']['primary']['5']['reports'][j]
                else:
                    rd=read('results/score/notice_delays/DELAY_FAMILIES.json');o=rd['families'][mode+'/'+str(delta or 5)]['reports'][j]
                for k in ['effect_percent_reference_mae','p_two_sided','holm_p']:
                    check(f'official/delay/{reading}/{delta}/{j}/{k}',r[k],o[k],prob=k in ['p_two_sided','holm_p'])
        rowno=7 if mode=='specified' else 8
        erow=next(r for r in drows if r['cells'][0].startswith('Month-first date parsing' if mode=='specified' else 'Day-first date parsing'))
        for j in range(3):
            rs=[v[j] for v in delay_results[mode].values()];effects=[r['effect_percent_reference_mae'] for r in rs]
            if mode=='specified':
                printed(f'paper/TableD1/month-first/{j}/range',[min(effects),max(effects)],erow['cells'][1+2*j]);printed(f'paper/TableD1/month-first/{j}/Holm',max(r['holm_p'] for r in rs),erow['cells'][2+2*j])
            printed(f'precision/TableD1/{rowno}/{j}/Holm',max(r['holm_p'] for r in rs),precise[('D1',rowno,2+2*j)])

    days=pd.date_range('2026-03-01','2026-09-30').strftime('%Y-%m-%d').tolist()
    for j,arm in enumerate(PRIMARY['news']):
        r=F.stats('news',arm,'M',days=days);o=rows[f'original-news-214/{j}']
        for z,k in [(0,'effect_percent_reference_mae'),(1,'p_two_sided')]:
            printed(f'paper/TableD1/score_news_full_window/{arm}/{k}',r[k],drows[9]['cells'][7+2*j+z]);check(f'official/score_news_full_window/{arm}/{k}',r[k],o[k],prob=k=='p_two_sided')

    specs=[('notice','NP','N',58),('notice','NPM','N',68),('notice','NPL','N',59),('notice','NPL','NP',65),('notice','NPL','NPM',69),('notice','NPL','NPP',66),('news','L_count','LEAR',25),('news','L_chen','LEAR',26)]
    for no,(erow,(task,arm,ref,slot)) in enumerate(zip(expected['D3']['rows'],specs)):
        r=F.stats(task,arm,ref,days=placebo if no==5 else None);o=forest(slot)
        for col,k in [(1,'effect_percent_reference_mae'),(2,'mean_difference'),(3,'p_two_sided')]:

            if no not in [2,3,4,5]:printed(f'paper/TableD3/line{erow["source_line"]}/{k}',r[k],erow['cells'][col])
            check(f'official/TableD3/{no}/{k}',r[k],o[k],prob=k=='p_two_sided')
            if ('D3',no,col) in precise:
                printed(f'precision/TableD3/{no}/{k}',r[k],precise[('D3',no,col)])

    check('paper/Table5/caption/forecast_count',61*COUNTS['notice'],527040)
    check('paper/Table6/caption/forecast_count',135*COUNTS['news'],9720)
    from verify_posthoc import verify_posthoc
    monthfirst=verify_posthoc(sys.modules[__name__], F, None)
    from verify_dayfirst import verify_dayfirst
    verify_dayfirst(sys.modules[__name__],F,monthfirst)
    failed=[x for x in checks if not x['pass']]
    summary={'overall':'FAIL' if failed else 'PASS','values_checked':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'largest_absolute_differences':maximum,'largest_bootstrap_endpoint_difference_percentage_points':bootstrap_max,'byte_identical_frozen_files_checked':len(frozen),'restored_original_file_hashes_checked':len(recovery.checked),'restored_frozen_file_hashes_checked':sum(e['frozen_evidence'] for e in recovery.records.values()),'restored_numeric_npy_hashes_checked':len(compressed),'registration_code_config_bindings_checked':binding_count,'bootstrap_draws':100000,'bootstrap_seed':20260925,'runtime_seconds':round(time.monotonic()-begin,3)}
    print('SUMMARY_JSON '+json.dumps(summary),flush=True)
    print('OVERALL '+summary['overall'],flush=True)
    return 1 if failed else 0

if __name__=='__main__':
    sys.dont_write_bytecode=True
    try:
        with Recovery(ROOT) as recovery:sys.exit(run())
    except Exception as exc:
        print(f'FAIL verification stopped: {type(exc).__name__}: {exc}',flush=True)
        raise
