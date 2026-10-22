'Read optional forecast losses through the checked scoring functions.'
from pathlib import Path
from types import SimpleNamespace
import ast
import numpy as np
import pandas as pd
import read_comparisons as P
from frozen_losses import ast_functions,a2_parity,canonical_daily
from parity_gate import run as parity_run


def batch(primary_tests,sensitivity_tests,sc,inputs,bundles):
    raw=inputs.get('a2batch')
    if raw is None:return
    for name,layer in [('L1','l1_family'),('PD','pd_family')]:
        family=raw['families'].get(name)
        if not family or family['state']!='COMPUTED':
            bundles['news/'+layer]=dict(id='news/'+layer,task='news',state='PENDING' if family is None else family['state'],losses={},reason=(family or {}).get('reason'));continue
        seal=P.strict_json(P.checked(raw['seal']));main=inputs['seal']
        P.require('a2batch_receipt' in inputs,'Native A2B score receipt required')
        receipt=inputs['a2batch_receipt']
        P.require(receipt['state']=='A2BATCH_SECONDARY_SCORE_COMPLETE' and receipt['seal_sha256']==raw['seal']['sha256']
            and receipt['conf_seal_sha256']==P.sha256(inputs['_seal_path']),'A2B score receipt/seal drift')
        for item in receipt['files']:P.checked(item)
        P.require(raw['conf_seal_sha256']==P.sha256(inputs['_seal_path']),'A2B main seal drift')
        P.require(seal['truth_panels']['news']['sha256']==main['truth_panels']['news']['sha256'],'A2B truth drift')
        from replay_composite_losses import effective_inputs
        loader=effective_inputs(primary_tests,sc,Path(inputs['_seal_path']).parent,inputs)
        truth=loader.truth('news');days=sorted(truth.target_day.unique().tolist())
        ns=dict(pd=pd,np=np,KEYS=['origin','target_time','region','horizon'],SEED=20260919,checked=P.checked,require=P.require)
        ast_functions(P.PROJ/'studies/batch_scoring/code/sealing.py',('normalize',),ns)
        ns['sealing']=SimpleNamespace(normalize=ns['normalize'])
        ast_functions(P.PROJ/'studies/batch_scoring/code/batch_score.py',('prediction_losses',),ns)
        losses=ns['prediction_losses'](seal,truth,days,primary_tests)
        references=dict(main,predictions=[i for i in main['predictions'] if i.get('arm') in ('N','M','L_count','L_chen','LEAR')])
        losses.update(ns['prediction_losses'](references,truth,days,primary_tests))
        b=dict(id='news/'+layer,task='news',state='COMPUTED',losses=losses,days=days,
            pairs=[(r['arm'],r['reference']) for r in family['reports']],subset=False)
        def check():
            daily=[i for i in receipt['files'] if Path(i['path']).name=='DAILY_LOSSES.csv']
            P.require(len(daily)==1 and canonical_daily(days,losses)==P.checked(daily[0]).read_bytes(),'A2B canonical DAILY_LOSSES mismatch')
            actual=P.compute_bundle(primary_tests,P.ChunkedScoring(sc,2000),b)
            a2_parity(actual,family,'news/'+layer)
        parity_run(b,check);bundles[b['id']]=b


def label(primary_tests,sc,inputs,bundles):
    raw=inputs.get('label')
    if raw is None:return
    if raw['state']!='A2LABEL_SCORED':
        for task in P.PAIRS:bundles[task+'/label_replacement']=dict(id=task+'/label_replacement',task=task,state=raw['state'],losses={},reason=raw.get('reason'))
        return


    P.require('label_receipt' in inputs,'Native replacement receipt identity required')
    receipt=inputs['label_receipt']
    P.require(receipt['state']=='A2LABEL_COMPLETE' and receipt['production_seal_sha256']==P.sha256(inputs['_seal_path']),'Label seal binding drift')
    pred_receipt=P.strict_json(P.checked(receipt['replacement_predictions']))
    P.require(pred_receipt['state']=='ALL_REPLACEMENT_PREDICTIONS_COMPLETE','Label prediction seal invalid')
    parity=P.strict_json(P.checked(pred_receipt['parity']))
    P.require(parity['state']=='BOTH_PARITY_GATES_PASS','Label parity gate failed')
    from replay_composite_losses import effective_inputs
    loader=effective_inputs(primary_tests,sc,Path(inputs['_seal_path']).parent,inputs)
    path=P.PROJ/'studies/label_scoring/code/score_labels.py'
    pins=P.strict_json(P.HERE/'DEPENDENCY_PINS.json')['files'];P.require(P.sha256(path)==pins[str(path.relative_to(P.PROJ))],'Label frozen loader drift')
    run=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='run')
    loop=next(n for n in run.body if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='source')
    end=next(i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='family' for t in n.targets))
    ns=dict(a2=primary_tests,inputs=loader,receipt=pred_receipt,pd=pd,np=np,checked=P.checked,
        KEYS=['origin','target_time','region','horizon'],ARMS={t:list(dict.fromkeys(a for pair in ps for a in pair)) for t,ps in P.PAIRS.items()})
    for task in P.PAIRS:
        ns['source']=task
        exec(compile(ast.Module(body=loop.body[:end],type_ignores=[]),str(path),'exec'),ns)
        b=dict(id=task+'/label_replacement',task=task,state='COMPUTED',losses=ns['losses'],days=ns['days'],pairs=P.PAIRS[task],subset=False)
        parity_run(b,lambda:a2_parity(P.compute_bundle(primary_tests,P.ChunkedScoring(sc,2000),b),raw['families'][task],b['id']))
        bundles[b['id']]=b
