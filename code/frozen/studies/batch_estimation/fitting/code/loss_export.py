"""Post-T5 sufficient statistics for frozen B=100000 A8 reading functions.

In particular losses of averaged predictions cannot be recovered by averaging
daily absolute losses. This exporter computes them from the paired sealed rows.
"""
import numpy as np
from a8_common import *

PAIRS = {'news':[('L_count','M'),('L_chen','M')],
         'notice':[('L14','M_notice'),('L_Laz','M_notice'),('L_chen_notice','M_notice')]}
MEAN_DEFINITION = 'daily loss of the mean prediction; not mean arm loss'
LAYERS = ('primary','combination','combination_benchmark','cheap','shift','mn','report_2025',
          'label_replacement','first_chunk','window_24h','official_cap','drop_first_seven',
          'l1_family','pd_family','subsets')

def bundle(native,task,layer,panel,days,pairs,predictions,mask=None,mean=None,subset=False):
    losses = {}; selected_days = list(days)
    for arm,values in predictions.items():
        actual_days,values = native._daily(panel,values,mask)
        if losses:
            require(actual_days == selected_days,'Export paired daily order drift')
        selected_days = actual_days
        require(np.isfinite(values).all() and (values >= 0).all(),'Invalid exported daily loss')
        losses[arm] = values.tolist()
    row = dict(id=task+'/'+layer,task=task,state='COMPUTED' if losses else 'NOT_EVALUABLE',
               days=selected_days,pairs=[list(p) for p in pairs],family_m=len(pairs),subset=subset,losses=losses)
    if mean:
        row['mean_prediction_losses'] = {a:native._daily(panel,p,mask)[1].tolist() for a,p in mean.items()}
        row['mean_prediction_loss_definition'] = MEAN_DEFINITION
    return row

def mean_predictions(pred,task,arms):
    if not all((a,s,'main') in pred for a in arms for s in (SEED,20260920,20260921)):
        return None
    result = {a:np.mean([pred[(a,s,'main')] for s in (SEED,20260920,20260921)],axis=0) for a in arms}
    if task == 'notice': result = {a:v.astype('float32') for a,v in result.items()}
    return result

def export_losses(native,A,seal,source_sha,destination,code):
    additional = {}
    for item in code.get('additional_loss_bundles',[]):
        record = read_json(checked(item))
        for row in record['bundles']:
            require(row['id'] not in additional,'Duplicate external loss layer')
            additional[row['id']] = row
    rows = []; clipping = {}
    feature_manifest = read_json(seal['feature_manifest_path'])
    for task,pairs in PAIRS.items():
        panel,days,counts,pred,ids,clips,raw = native._read_task_data(task,seal)
        clipping[task] = [[str(r.get(k,'')) for k in ('arm','eligible_predictions','clipping_operations',
                           'raw_below_lower','raw_above_upper','final_lower_hits','final_upper_hits')]
                          for r in clips if not ('target_day' in r or 'region' in r)]
        main = {a:p for (a,s,v),p in pred.items() if s == SEED and v == 'main'}
        required = {a for p in pairs for a in p}
        require(required <= set(main),'Primary exporter family incomplete')
        means = mean_predictions(pred,task,required)
        made = {'primary':bundle(native,task,'primary',panel,days,pairs,main,mean=means)}
        activity = pairs[0][1]
        made['mn'] = bundle(native,task,'mn',panel,days,[(activity,'N')],main)
        benchmark = 'LEAR' if task == 'news' else 'NP'
        if benchmark in main:
            averaged = {a:.5*(main[a]+main[benchmark]) for a in required}
            mean_combined = None if means is None else {a:.5*(p+main[benchmark]) for a,p in means.items()}
            made['combination'] = bundle(native,task,'combination',panel,days,pairs,averaged,mean=mean_combined)
            made['combination_benchmark'] = bundle(native,task,'combination_benchmark',panel,days,
                               [(a,benchmark) for a,_ in pairs],{**main,**averaged})
        cheap_refs = ('E_raw','W_Bai') if task == 'news' else ('R','T')
        cheap_pairs = [(a,r) for a,_ in pairs for r in cheap_refs]
        made['cheap'] = bundle(native,task,'cheap',panel,days,cheap_pairs,
                               {a:p for a,p in main.items() if a in {x for pair in cheap_pairs for x in pair}})
        shift_pairs = [(a,'P_shift') for a,_ in pairs]
        shift_mask = native.a1.shift_support_mask(panel) if task == 'notice' else None
        made['shift'] = bundle(native,task,'shift',panel,days,shift_pairs,
                               {a:p for a,p in main.items() if a in {x for pair in shift_pairs for x in pair}},
                               mask=shift_mask,subset=shift_mask is not None)
        for layer,variant in (('first_chunk','first_L'),('window_24h','24h')):
            changed = {a:p for (a,s,v),p in pred.items() if s == SEED and v == variant}
            if changed:
                ref = 'M' if task == 'news' else 'M_notice'
                allowed = ('M','L_count','L_chen') if variant == '24h' else ('L_chen','E_raw') if task == 'news' else ('L_chen_notice',)
                available = [a for a in allowed if a in changed]
                layer_pairs = [(a,ref) for a in available if a != ref]
                values = {a:changed[a] for a in available}
                values.setdefault(ref,main[ref])
                if variant == '24h':
                    values['N'] = main['N'];layer_pairs.append(('M','N'))
                made[layer] = bundle(native,task,layer,panel,days,layer_pairs,values)
        if task == 'notice':
            cap = native.a1.official_market_price_cap(panel.target_time)
            reclipped = {a:np.clip(v,-1000.,cap).astype('float32') for (a,s,vv),v in raw.items()
                         if s == SEED and vv == 'main'}
            made['official_cap'] = bundle(native,task,'official_cap',panel,days,pairs,reclipped)
            keep = panel.target_day.astype(str).ge('2026-08-08').to_numpy()
            made['drop_first_seven'] = bundle(native,task,'drop_first_seven',panel,days,pairs,main,mask=keep,subset=True)
        excluded = native.a1.exposure_excluded_days(task)
        mask = panel.target_day.astype(str).isin(excluded).to_numpy()
        made['subsets'] = bundle(native,task,'subsets',panel,days,pairs,main,mask=mask,subset=True)
        if task == 'news':
            made['lear'] = bundle(native,task,'lear',panel,days,[('LEAR','N')],main)
            validation = [i for i in seal['predictions'] if i['source'] == 'news' and i['variant'] == '2025_fixed_validation' and i['seed'] == SEED]
            if validation:
                import pandas as pd
                b = next(b for b in feature_manifest['bundles'] if b['source'] == 'news' and b['arm'] == 'N' and b.get('variant','main') == 'main')
                truth = normalize(pd.read_parquet(b['panel_path'],columns=KEYS+['target_day','y'],
                                  filters=[('target_day','>=','2025-01-01'),('target_day','<=','2025-12-31')]))
                vectors = {}
                for item in validation:
                    values = normalize(pd.read_parquet(checked(item)))
                    require(values[KEYS].equals(truth[KEYS]),'Report-2025 paired keys differ')
                    vectors[item['arm']] = values.prediction.to_numpy(dtype='float64')
                vdays = sorted(truth.target_day.unique().tolist())
                made['report_2025'] = bundle(native,task,'report_2025',truth,vdays,pairs,vectors)
        for layer in (*LAYERS,*(('lear',) if task == 'news' else ())):
            name = task+'/'+layer
            if name in additional:
                require(layer in ('label_replacement','l1_family','pd_family'), 'External losses may only fill their own registered producers')
                row = additional[name]
            elif layer in made:
                row = made[layer]
            else:
                row = dict(id=name,task=task,state='PENDING' if layer in ('label_replacement','l1_family','pd_family') else 'NOT_EVALUABLE',
                           days=days,pairs=[list(p) for p in pairs],family_m=len(pairs),subset=False,
                           losses={},reason=None,prerequisite='own separately sealed registered producer' if layer in ('label_replacement','l1_family','pd_family') else 'registered configuration unavailable')
            rows.append(row)
    freeze = code.get('loss_exporter_freeze')
    if freeze is not None: checked(freeze)
    write_json(destination,dict(schema='A8POST_LOSS_EXPORT_V1',source_seal_sha256=source_sha,
               production_export_authorised=freeze is not None,exporter_freeze=freeze,
               bundles=rows,clipping=clipping,additional_inputs=code.get('additional_loss_bundles',[]),
               partial_predictions_scored=False),exclusive=True)
    return Path(destination)
