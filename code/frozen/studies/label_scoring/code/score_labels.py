"""Registered replacement families and descriptive agreement; postscore helpers only."""
from collections import Counter
import time
import numpy as np
import pandas as pd
from a2label_common import *

def replacement_state(a2, primary_class, primary_mean, replacement_class, replacement_mean):
    rule=a2.seed_rule(primary_class,primary_mean,replacement_class,replacement_mean)
    state={'SEED_CONSISTENT':'REPRODUCED','SEED_FRAGILE':'NOT_REPRODUCED','SEED_ROBUSTNESS_NOT_EVALUABLE':'LABEL_REPLACEMENT_NOT_EVALUABLE'}[rule]
    return {'state':state,'primary_decision':primary_class,'primary_mean_difference':primary_mean,'replacement_decision':replacement_class,'replacement_mean_difference':replacement_mean}

def label_record_news(row):
    return {'article_id':str(row['article_id']),'impact_level':row['impact_level'],'impact_evidence_quote':row['impact_evidence_quote'],'attributes':json.loads(row['attributes_json']),'statements':json.loads(row['statements_json'])}

def original_labels(news_rows, notice_rows):
    output={}
    for owner,root in (('bank',Q1/'NEWSX'),('extension',CONF/'newsx_extension')):
        receipt=read(root/'EXTRACTION_RECEIPT.json'); failed=set(map(str,receipt['failed_article_ids']))
        table=pd.read_parquet(checked({'path':str(root/'labels.parquet'),'sha256':receipt['labels_sha256']}))
        labels={str(r['article_id']):label_record_news(r) for r in table.to_dict('records')}
        for row in news_rows:
            if row['owner']==owner:
                aid=row['article_id']; output[('news',aid)]=('TERMINAL_FAILURE',None) if aid in failed else ('SUCCESS',labels[aid])
    receipt=read(Q1/'NRX/results_1_3/EXTRACTION_RECEIPT_1_3.json')
    table=pd.read_parquet(checked({'path':str(Q1/'NRX/results_1_3/labels.parquet'),'sha256':receipt['labels_sha256']}),columns=['notice_key','terminal_state','label_json'])
    selected={r['notice_key'] for r in notice_rows}
    for row in table.to_dict('records'):
        if row['notice_key'] in selected: output[('notice',row['notice_key'])]=(row['terminal_state'],json.loads(row['label_json']) if pd.notna(row['label_json']) else None)
    return output

def agreement(m8, original, new, ledgers=None):
    if set(original)!=set(new): raise ValueError('Label agreement requires exact scoped terminal census')
    sample=[]; stored={}; synthetic={'news':[],'notice':[]}; transition={}
    for kind in ('news','notice'):
        native=m8.latest_native(ledgers[kind],kind) if ledgers is not None else {}
        counts=Counter(); pairs=0
        for (corpus,key),(old_state,old_label) in sorted(original.items()):
            if corpus!=kind: continue
            new_state,new_label=new[(corpus,key)]
            if old_state not in ('SUCCESS','TERMINAL_FAILURE') or new_state not in ('SUCCESS','TERMINAL_FAILURE'): raise ValueError('Incomplete label comparison')
            counts[old_state+'->'+new_state]+=1
            if old_state=='SUCCESS' and new_state=='SUCCESS':
                if not isinstance(old_label,dict) or not isinstance(new_label,dict): raise ValueError('Successful status without label')
                pairs+=1; sample.append({'corpus':kind,'item_id':key}); stored[(kind,key)]=old_label
                row={'article_id':key,'status':'SUCCESS','label':new_label} if kind=='news' else {'notice_key':key,'event':'ATTEMPT_RESULT','status':'SUCCESS','parsed_label':new_label}
                if native:
                    row={**native[key],**row}
                synthetic[kind].append(row)
        transition[kind]={'scope_documents':sum(counts.values()),'terminal_status_changes':sum(v for k,v in counts.items() if k in ('SUCCESS->TERMINAL_FAILURE','TERMINAL_FAILURE->SUCCESS')),'transitions':dict(counts),'both_successful_full_label_denominator':pairs,'field_agreement_denominator':'both terminal SUCCESS; no fabricated label for failures'}
    metrics,field_trace,item_trace=m8.agreement(sample,stored,synthetic)
    for kind in metrics:
        metrics[kind]['terminal_status']=transition[kind]
        if ledgers is not None: metrics[kind]['validation']=m8.validation_census(ledgers[kind],kind)
    return metrics,field_trace,item_trace

def run(state):
    started=time.monotonic()
    a2,inputs=host_inputs(state); installed(); audit_writes()
    if (OUT/'parity/NOT_RUN_PARITY_FAILED.json').exists(): raise PermissionError('NOT_RUN_PARITY_FAILED: scoring prohibited')
    receipt=read(OUT/'predictions/PREDICTION_RECEIPT.json')
    if receipt['state']!='ALL_REPLACEMENT_PREDICTIONS_COMPLETE' or receipt['seal_sha256']!=inputs.seal_sha256: raise PermissionError('Replacement prediction seal missing')
    parity=read(checked(receipt['parity']))
    if parity['state']!='BOTH_PARITY_GATES_PASS' or parity['seal_sha256']!=inputs.seal_sha256: raise PermissionError('Both parity gates required')
    for ident in receipt['files']: checked(ident)
    sc=a2.load_frozen_scoring(CONF)
    results={}
    for source in ARMS:
        truth=inputs.truth(source); losses={}; original_loss={}; days=None
        for arm in ARMS[source]:
            ident=next(i for i in receipt['files'] if (i['source'],i['arm'])==(source,arm))
            prediction=a2.coerce_keys(pd.read_parquet(checked(ident)))
            if not prediction[KEYS+['target_day']].equals(truth[KEYS+['target_day']]): raise ValueError('Replacement scoring common keys differ')
            values=prediction.prediction.to_numpy(dtype='float64')
            if not np.isfinite(values).all(): raise ValueError('Nonfinite replacement prediction')
            days,losses[arm]=a2.daily_abs_loss(truth,values)
            _,original_loss[arm]=a2.daily_abs_loss(truth,inputs.prediction(source,arm,truth))
        family=a2.family_inference(sc,losses,a2.FAMILIES[source],days)
        primary=inputs.score_json(source+'__PRIMARY.json')['reports']
        for row in family['reports']:
            saved=next(p for p in primary if (p['arm'],p['reference'])==(row['arm'],row['reference']))
            row['label_replacement']=replacement_state(a2,saved['primary_decision'],saved['dm_p1']['mean_difference'],row['decision'],row['mean_difference'])
            interval=row['bootstrap']['1'].get('interval95_percent')
            if row['label_replacement']['state']=='REPRODUCED':
                row['sentence']=a2.SENTENCES['L1'].format(effect=row['effect_percent_reference_mae'],lo=interval[0] if interval else 'undefined',hi=interval[1] if interval else 'undefined')
            elif row['label_replacement']['state']=='NOT_REPRODUCED':
                row['sentence']=a2.SENTENCES['L2'].format(reading_original=saved['primary_decision'],reading_replacement=row['decision'],effect=row['effect_percent_reference_mae'],lo=interval[0] if interval else 'undefined',hi=interval[1] if interval else 'undefined')
            else: row['sentence']=a2.SENTENCES['L3'].format(reason='registered comparison not evaluable')
        picks=a2.complete_picks(sc,len(days))
        effects={arm:a2.contrast_stats(sc,losses[arm],original_loss[arm],picks,1) for arm in ARMS[source]}
        results[source]={'replacement_family':family,'label_change_effect_Aprime_minus_A':effects}
        peak_check()
    scope=read(OUT/'scope/SCOPE_RECEIPT.json'); news=read(checked(scope['news'])); notices=read(checked(scope['notice']))
    original=original_labels(news,notices)
    ledgers={'news':jsonl(OUT/'extraction/news/extraction_ledger.jsonl'),'notice':jsonl(OUT/'extraction/notice/extraction_ledger.jsonl')}
    m8=load_module(Q1/'M8/analyze.py','_a2label_m8_metrics')
    new={}
    for kind in ledgers:
        finals=m8.latest_native(ledgers[kind],kind)
        for key,row in finals.items(): new[(kind,key)]=(row['status'],row.get('label') if kind=='news' else row.get('parsed_label'))
    metrics,fields,items=agreement(m8,original,new,ledgers)
    out=OUT/'scored'
    pd.DataFrame(fields).to_csv(target(out/'label_field_trace.csv'),index=False)
    pd.DataFrame(items).to_csv(target(out/'paired_success_item_trace.csv'),index=False)
    terminal_trace=[{'corpus':kind,'item_id':key,'original_terminal_state':old[0],'replacement_terminal_state':new[(kind,key)][0],'status_changed':old[0]!=new[(kind,key)][0]} for (kind,key),old in sorted(original.items())]
    pd.DataFrame(terminal_trace).to_csv(target(out/'label_terminal_trace.csv'),index=False)
    write(out/'A2LABEL_SCORE.json',a2.json_safe({'state':'A2LABEL_COMPLETE_SECONDARY_ONLY','families':results,'label_agreement':metrics,'clipping':receipt['clipping'],'does_not_change_primary':True,'peak_rss_bytes':peak_check()}))
    write(out/'SCORE_RECEIPT.json',{'state':'A2LABEL_COMPLETE','files':[identity(out/'A2LABEL_SCORE.json'),identity(out/'label_field_trace.csv'),identity(out/'paired_success_item_trace.csv'),identity(out/'label_terminal_trace.csv')],'production_seal_sha256':inputs.seal_sha256,'replacement_predictions':identity(OUT/'predictions/PREDICTION_RECEIPT.json'),'read_log':inputs.read_log,'wall_seconds':time.monotonic()-started,'helpers':[identity(CONF/'A2/code/a2_postscore.py'),identity(Q1/'M8/analyze.py')]})

if __name__=='__main__':
    args=host_args(__doc__).parse_args()
    with lock('score'): run(args.state)
