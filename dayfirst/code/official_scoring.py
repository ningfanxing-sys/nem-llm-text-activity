'Score the affected official comparisons under both timestamp readings.'
from __future__ import annotations
from functools import lru_cache
from score_dayfirst import *

REPS=('L14','L_Laz','L_chen_notice')

class OfficialForecasts:
    def __init__(self,forecasts,predictions,native):
        self.panel=forecasts.panels['notice'];self.native=native
        self.new={(e['group'],e['arm'],e['seed'],e.get('variant','main'),e['delta_minutes']):e for e in predictions['predictions']}
        self.delays={}
        for mode in (1,2):
            for e in read(BATCH/f'dly8/mode{mode}/DELAY_RECEIPT.json')['predictions']:
                self.delays[(mode,e['arm'],e['delta_minutes'])]=e
        _,self.primary_tests,_=statistical_modules()
        sys.path.insert(0,str(confirmation/'execution'))
        import additional_scoring
        self.a1=additional_scoring

    @lru_cache(maxsize=6)
    def prediction(self,arm,seed=20260919,version='day-first',delta=0,variant='main',raw=False,mean_round=True):
        import numpy as np
        import pandas as pd
        if seed=='mean':
            p=np.mean([self.prediction(arm,s,version,delta,variant,raw) for s in (20260919,20260920,20260921)],axis=0)
            return p.astype('float32') if mean_round else p
        group='windowed_activity' if arm.endswith('+') or arm in ('M+_n','M0_n','M+0_n') else 'official'
        changed=self.new.get((group,arm,seed,variant,delta)) if version=='day-first' else None
        if changed:
            path=changed['prediction_path'];digest=changed['prediction_sha256']
        elif delta:
            e=self.delays[(2 if group=='windowed_activity' else 1,arm,delta)]
            path=e['path'];digest=e['sha256']
        else:
            bank=BATCH/'state' if group=='windowed_activity' else STATE
            r=read(bank/f'fits/receipts/notice__prewindow_frozen_C_bank__{arm}__s{seed}__{variant}.json')
            path=r['prediction_path'];digest=r['prediction_sha256']
        assert sha(path)==digest
        column='raw_prediction' if raw else 'prediction'
        frame=self.native.normalize(pd.read_parquet(path,columns=KEYS+['target_day',column]))
        assert frame[KEYS+['target_day']].equals(self.panel[KEYS+['target_day']])
        return frame[column].to_numpy(dtype='float64')

    def daily(self,arm,seed=20260919,version='day-first',delta=0,variant='main',days=None,power=1,reclip=False,combination=False):
        import numpy as np
        import pandas as pd
        p=self.prediction(arm,seed,version,delta,variant,raw=reclip,mean_round=not combination)
        if reclip:p=self.a1.official_reclip(p,self.panel.target_time).astype('float64')
        if combination:p=.5*(self.prediction('NP',20260919,version)+p)
        if power==1:
            actual,loss=self.primary_tests.daily_abs_loss(self.panel,p)
        else:
            squared=np.square(np.abs(p-self.panel.y.to_numpy(dtype='float64')))
            grouped=pd.DataFrame({'day':self.panel.target_day.to_numpy(),'loss':squared}).groupby('day',sort=True).loss.mean()
            actual,loss=grouped.index.tolist(),grouped.to_numpy(dtype='float64')
        if days is not None:
            ids=[actual.index(d) for d in days];loss=loss[ids];actual=days
        return actual,loss

def prepare_official(F):
    import numpy as np
    import pandas as pd
    official=read(OFFICIAL)
    slots={e['slot_id']:e for e in official['rows']}
    changed={'L14','L_Laz','R','NPL','NPP','L14+','L_Laz+'}
    grouped={};unavailable=[];missing_groups={}
    for e in official['rows']:
        if not e['slot_id'].startswith('forest/') or e['identity'].get('task')!='notice':continue
        ident=e['identity'];value=e['value'];old=value.get('native')
        key=ident['family_key']
        if old is None:
            missing_groups.setdefault(key,[]).append(e)
            if ident['arm'] in changed or ident['reference'] in changed:unavailable.append(e)
            continue
        grouped.setdefault(key,[]).append(e)
    bundles=[];metadata={};baseline_checks=[]
    def add_family(ident,pairs,old_rows,m=3,subset=False,unadjusted=False,**condition):
        for version in ('month-first','day-first'):
            losses={};days=None
            for arm in dict.fromkeys(x for p in pairs for x in p):
                d,values=F.daily(arm,version=version,**condition)
                if days is None:days=d
                assert days==d
                losses[arm]=values.tolist()
            spec=dict(id=ident+'/'+version,kind='official',days=days,losses=losses,pairs=pairs,m=m,
                      subset=subset,unadjusted=unadjusted)
            # Check month-first point estimates before drawing bootstrap samples.
            if version=='month-first':
                frozen,_,_=statistical_modules()
                for (arm,ref),old in zip(pairs,old_rows):
                    a,b=np.asarray(losses[arm]),np.asarray(losses[ref]);dm=frozen.dm_daily(a-b)
                    effect=100*dm['mean_difference']/float(b.mean())
                    target=old.get('effect_percent_reference_mae',old.get('effect'))
                    p=old.get('p_two_sided',old.get('dm',{}).get('p_two_sided'))
                    if target is not None:target=float(target)
                    if p is not None:p=float(p)
                    if target is not None:assert abs(effect-target)<=1e-9,(ident,arm,effect,target)
                    if p is not None:assert abs(dm['p_two_sided']-p)<=max(1e-15,abs(p)*1e-7),(ident,arm,dm['p_two_sided'],p)
                    baseline_checks.append(dict(family=ident,arm=arm,reference=ref,effect_absolute_difference=abs(effect-target) if target is not None else None,
                        p_absolute_difference=abs(dm['p_two_sided']-p) if p is not None else None))
            bundles.append(spec)
        metadata[ident]=dict(pairs=pairs,old_rows=old_rows,condition=condition,m=m,subset=subset,unadjusted=unadjusted)
    for key,entries in grouped.items():
        if not any(e['identity']['arm'] in changed or e['identity']['reference'] in changed for e in entries):continue
        layer=entries[0]['identity']['layer']
        pairs=[(e['identity']['arm'],e['identity']['reference']) for e in entries]
        old=[e['value']['native'] for e in entries]
        m=entries[0]['value']['family_m']
        condition={};subset=False
        if layer.startswith('seed_'):condition['seed']=int(layer.split('_')[-1])
        if layer=='combination':condition['combination']=True
        if layer=='drop_first_seven':condition['days']=pd.date_range('2026-08-08','2026-09-30').strftime('%Y-%m-%d').tolist();subset=True
        if 'EXPOSURE_EXCLUDED' in layer:
            condition['days']=F.a1.exposure_excluded_days('notice');subset=True
        if layer=='official_cap' or 'OFFICIAL_CAP_RECLIP' in layer:condition['reclip']=True
        if any(F.a1.shift_dependent('notice',a,b) for a,b in pairs):
            condition['days']=pd.date_range('2026-08-24','2026-09-30').strftime('%Y-%m-%d').tolist();subset=True
        add_family(key,pairs,old,m=m,subset=subset,unadjusted=(m==1 and len(pairs)>1),**condition)
        metadata[key]['slots']=[e['slot_id'] for e in entries]


    for key,entries in missing_groups.items():
        if not any(e['identity']['arm'] in changed or e['identity']['reference'] in changed for e in entries):continue
        assert key in ('notice/cheap','notice/subsets'),('Unspecified unavailable specified family',key)
        pairs=[(e['identity']['arm'],e['identity']['reference']) for e in entries]
        if key=='notice/cheap':
            sensitivity_tests=module('_dayfirst_frozen_A3_inventory',confirmation/'sensitivity_tests/code/sensitivity_comparisons.py')
            declared=list(dict.fromkeys([*F.primary_tests.CHEAP_COMPARATORS['notice'],*sensitivity_tests.A3_NEW_CONTRASTS['notice']]))
            assert pairs==declared
            condition={};subset=False
        else:
            assert pairs==list(F.primary_tests.FAMILIES['notice'])
            condition={'days':F.primary_tests.day_list(F.primary_tests.STRICT_UNEXPOSED['notice'])};subset=True
        add_family(key,pairs,[{} for _ in pairs],m=1,subset=subset,unadjusted=True,**condition)
        metadata[key].update(slots=[e['slot_id'] for e in entries],
            historical_export_state='DEVIATION',historical_export_reason='A8NR_PARITY',
            rescore_authority='Fixed day-first PLAN: every comparison involving a changed model; original primary_tests/sensitivity_tests pair inventory')

    primary=slots['native-family/notice/primary']['value']['three_seed']['reports']
    add_family('notice/primary_mean',[(a,'M_notice') for a in REPS],primary,seed='mean')

    combo=slots.get('native-family/notice/combination',{}).get('value',{}).get('three_seed')
    if combo is not None:
        add_family('notice/combination_mean',[(a,'M_notice') for a in REPS],combo['reports'],seed='mean',combination=True)
    batch=slots['metadata/batch_native']['value']
    add_family('notice/R8',[(a+'+','M+_n') for a in REPS],batch['families']['R8_notice']['reports'])
    for delta in (5,15,60):
        add_family(f'notice/delay{delta}',[(a,'M_notice') for a in REPS],batch['DLY8']['primary'][str(delta)]['reports'],delta=delta)
        add_family(f'notice/R8_delay{delta}',[(a+'+','M+_n') for a in REPS],batch['DLY8']['R8'][str(delta)]['reports'],delta=delta)
    add_family('notice/squared',[(a,'M_notice') for a in REPS],batch['squared_loss']['primary']['notice'],power=2)
    r8square=batch['squared_loss'].get('R8',{}).get('notice')
    if r8square:add_family('notice/R8_squared',[(a+'+','M+_n') for a in REPS],r8square,power=2)
    write(OUT/'OFFICIAL_BASELINE_EQUIVALENCE.json',dict(state='PASS',checks=baseline_checks))
    write(OUT/'OFFICIAL_UNAVAILABLE_UNCHANGED.json',unavailable)
    write(OUT/'OFFICIAL_SPECS.json',dict(metadata=metadata,bundles=bundles))
    return bundles,metadata

def flatten(row):
    out={k:row.get(k) for k in ('n_days','arm_mae','reference_mae','mean_difference','effect_percent_reference_mae',
        'p_two_sided','holm_p','hac7_p_two_sided','hac7_holm_p','hln_p_two_sided','hln_holm_p',
        'decision','hac7_decision','hln_decision','hac7_state')}
    for block in ('1','7'):
        b=row.get('bootstrap',{}).get(block,{})
        for key,prefix in (('interval95_percent','interval95'),('interval_family_adjusted_percent','interval_family')):
            values=b.get(key)
            for i,end in enumerate(('low','high')):out[f'{prefix}_{block}_{end}']=None if values is None else values[i]
    return out

def write_official(results,metadata):
    import numpy as np
    import pandas as pd
    rows=[];changes=[];tree={}
    for family,meta in metadata.items():
        tree[family]={v:results[family+'/'+v]['result'] for v in ('month-first','day-first')}
        old,new=[tree[family][v]['reports'] for v in ('month-first','day-first')]
        if family=='notice/subsets':
            # Treat this subset descriptively; its seven-day sample contains one block.

            for r in old+new:
                for k in ('decision','hac7_decision','hln_decision','holm_p','hac7_holm_p','hln_holm_p'):r[k]=None
        for computed,saved in zip(old,meta['old_rows']):
            for k in ('n_days','arm_mae','reference_mae','mean_difference','effect_percent_reference_mae',
                      'p_two_sided','holm_p','hac7_p_two_sided','hac7_holm_p','hln_p_two_sided','hln_holm_p'):
                if k not in saved:continue
                if saved[k] is None:assert computed[k] is None,(family,k,computed[k],saved[k])
                else:assert abs(computed[k]-saved[k])<=max(2e-9 if 'p' not in k else 1e-15,abs(saved[k])*1e-7 if 'p' in k else 0),(family,k,computed[k],saved[k])
            for block,saved_boot in saved.get('bootstrap',{}).items():
                for k in ('interval95_percent','interval_family_adjusted_percent'):
                    if saved_boot.get(k) is None:continue
                    actual=computed['bootstrap'][str(block)][k]
                    assert max(abs(a-b) for a,b in zip(actual,saved_boot[k]))<=2e-9,(family,block,k,actual,saved_boot[k])
            for k in ('decision','hac7_decision','hln_decision'):
                if saved.get(k) is not None:assert computed[k]==saved[k],(family,k,computed[k],saved[k])
        for index,(a,b) in enumerate(zip(old,new)):
            ident=dict(family=family,index=index,arm=a['arm'],reference=a['reference'],
                slot=meta.get('slots',['']*len(old))[index],condition=json.dumps(meta['condition'],ensure_ascii=False))
            for version,row in (('month-first',a),('day-first',b)):rows.append(dict(ident,version=version,**flatten(row)))
            af,bf=flatten(a),flatten(b)
            changed=any(af[k]!=bf[k] for k in af)
            delta=dict(ident,numerical_change=changed,sign_change=bool(np.sign(a['mean_difference'])!=np.sign(b['mean_difference'])),
                nominal_significance_change=bool((a['p_two_sided']<.05)!=(b['p_two_sided']<.05)),
                decision_change=a['decision']!=b['decision'],hac7_decision_change=a['hac7_decision']!=b['hac7_decision'],
                student_t_decision_change=a['hln_decision']!=b['hln_decision'])
            for k in af:delta['month_first_'+k]=af[k];delta['day_first_'+k]=bf[k]
            changes.append(delta)
    (OUT/'results').mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT/'results/official_comparisons.csv',index=False)
    pd.DataFrame(changes).to_csv(OUT/'results/official_comparison_changes.csv',index=False)
    unavailable=read(OUT/'OFFICIAL_UNAVAILABLE_UNCHANGED.json')
    pd.DataFrame([dict(slot=e['slot_id'],arm=e['identity']['arm'],reference=e['identity']['reference'],
        original_export_state=e['value'].get('state'),day_first_state='RECOMPUTED_FIXED_SPECIFIED_CONTRAST',
        reason=e['value'].get('reason')) for e in unavailable]).to_csv(OUT/'results/official_unavailable.csv',index=False)
    write(OUT/'OFFICIAL_DAYFIRST.json',tree)
    return tree
