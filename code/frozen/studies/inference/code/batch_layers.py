'Recompute batch losses and compare the 2,000-draw bootstrap summaries.'
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import read_comparisons as P
from frozen_losses import ast_functions,native_functions,a2_parity
from parity_gate import run as parity_run


def family(primary_tests,sc,task,pairs,main,preds,key):
    P.resource_gate()
    ns=dict(DRAWS=P.DRAWS,np=np,SEED=20260919,contextmanager=contextmanager,CLASS=P.CLASS,load_a2=lambda:primary_tests)
    path=P.BATCH_CODE/'score_batch.py'
    ast_functions(path,('settings','fill_fields','family_score'),ns)
    native=SimpleNamespace(**native_functions())


    import json
    cache={};loader=native._read_task_data
    def identical_native_input(source,combined):
        key=json.dumps([source,combined],sort_keys=True)
        if key in cache:
            for item in [*combined['truth_panels'].values(),*combined['predictions']]:P.checked(item)
        else:cache[key]=loader(source,combined)
        return cache[key]
    native._read_task_data=identical_native_input
    # Use identical daily losses for both bootstrap calculations.


    import hashlib
    daily_cache={};daily=native._daily
    def identical_native_daily(panel,prediction):
        vector=np.asarray(prediction)
        key=(id(panel),vector.dtype.str,vector.shape,hashlib.sha256(vector.tobytes()).hexdigest())
        if key not in daily_cache:daily_cache[key]=daily(panel,prediction)
        return daily_cache[key]
    native._daily=identical_native_daily
    dense=ns['family_score'](native,sc,None,task,pairs,main,preds,2000,primary_tests)
    calls=[];old=primary_tests.family_inference
    def capture(sc_,losses,pairs_,days,m=None,subset=False):
        r=old(sc_,losses,pairs_,days,m,subset)
        calls.append(dict(id=key,task=task,state='COMPUTED',losses={a:np.array(v,copy=True) for a,v in losses.items()},
            pairs=pairs_,days=list(days),subset=subset,native_result=r))
        return r
    try:
        primary_tests.family_inference=capture
        actual=ns['family_score'](native,P.ChunkedScoring(sc,2000),None,task,pairs,main,preds,2000,primary_tests)
    finally:primary_tests.family_inference=old
    P.require(calls,'Missing frozen layer loss arguments')
    b=calls[0]
    parity_run(b,lambda:a2_parity(actual,dense,key+'/dense-prefix'))
    if len(calls)>1 and b['state']=='COMPUTED':
        b['mean_prediction_losses']=calls[1]['losses'];b['mean_prediction_loss_definition']='daily loss of the mean prediction; not mean arm loss'
    for x in calls:x.pop('native_result',None)
    return b


def specified_families():
    import ast
    path=P.BATCH_CODE/'batch_export.py'
    rel=str(path.relative_to(P.PROJ));pins=P.strict_json(P.HERE/'DEPENDENCY_PINS.json')['files']
    P.require(pins.get(rel)==P.sha256(path),'Frozen R8 family inventory drift')
    tree=ast.parse(path.read_text())
    node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='FAMILIES' for t in n.targets))
    return ast.literal_eval(node.value)


def r8_replay(primary_tests,sc,records,bundles):

    raw=records['batch'];families=specified_families();main=records['seal']
    for name,pairs in families.items():
        saved=raw.get('families',{}).get(name,{})
        if saved.get('state')!='COMPUTED':continue
        task=name.removeprefix('R8_');key=task+'/R8'
        P.require([(r['arm'],r['reference']) for r in saved['reports']]==pairs,'R8 frozen pair census drift')
        predictions=[*main['predictions'],*records['batch_seal']['predictions']]
        b=family(primary_tests,sc,task,pairs,main,predictions,key)
        parity_run(b,lambda:a2_parity(P.compute_bundle(primary_tests,P.ChunkedScoring(sc,2000),b),saved,key+'/point',point_only=True))
        bundles[key]=b


def replay(primary_tests,sc,records,bundles):
    r8_replay(primary_tests,sc,records,bundles)
    for name,saved in records['batch'].get('descriptive',{}).items():
        if saved.get('state')!='COMPUTED':continue
        task=saved['source'];arm,ref=saved['arm'],saved['reference'];key=task+'/R8_desc/'+arm+'-'+ref
        b=family(primary_tests,sc,task,[(arm,ref)],records['seal'],[*records['seal']['predictions'],*records['batch_seal']['predictions']],key)
        b['unadjusted']=True
        parity_run(b,lambda:a2_parity(P.compute_bundle(primary_tests,P.ChunkedScoring(sc,2000),b),saved,key+'/point',point_only=True))
        bundles[key]=b
    raw=records['batch'];sealed=raw.get('sealed_inputs')
    computed=any(v.get('state')=='COMPUTED' for v in raw['CPS8'].values()) or any(isinstance(v,dict) and v.get('state')=='COMPUTED' for name in ('primary','R8') for v in raw['DLY8'].get(name,{}).values())
    P.require(sealed is not None or not computed,'Computed batch layer lacks bound sealed inputs')
    if sealed is None:return
    main=records['seal']
    for item in sealed['DLY8']:
        rec=P.strict_json(P.checked(item));family_name='primary' if item['mode']==1 else 'R8'
        if rec['state']!='ALL_DLY8_PREDICTIONS_SEALED':continue
        pairs=P.PAIRS['notice'] if family_name=='primary' else specified_families()['R8_notice']
        for delta in (5,15,60):
            preds=[dict(i,variant='main') for i in rec['predictions'] if i['delta_minutes']==delta]
            for i in preds:P.checked(i)
            key='notice/DLY8_'+('R8_' if family_name=='R8' else '')+str(delta)
            b=family(primary_tests,sc,'notice',pairs,main,preds,key)
            parity_run(b,lambda:a2_parity(P.compute_bundle(primary_tests,P.ChunkedScoring(sc,2000),b),raw['DLY8'][family_name][str(delta)],key+'/point',point_only=True))
            bundles[key]=b
    capacity=sealed['CPS8']
    if capacity['state']!='READY_FOR_FROZEN_SCORING':return
    for task in P.PAIRS:
        if capacity.get(task+'_all_g0_no_D_fit',False):continue
        for setting in ('selected','g0'):
            preds=[]
            for arm in dict.fromkeys(a for pair in P.PAIRS[task] for a in pair):
                g=capacity['selected'][task+'/'+arm] if setting=='selected' else 'g0'

                ns=dict(GRID=('g0','g1','g2'),require=P.require);ast_functions(P.BATCH_CODE/'run_comparison_sets.py',('encode_arm',),ns)
                encoded=ns['encode_arm'](arm,g)
                found=[i for i in capacity['predictions'] if i['source']==task and i['arm']==encoded]
                if task=='notice' and g=='g0':found=[i for i in capacity['notice_g0_predictions'] if i['arm']==arm]
                P.require(len(found)==1,'CPS8 schedule-matched sealed arm missing')
                P.checked(found[0]);preds.append(dict(found[0],arm=arm,variant='main'))
            key=task+'/CPS8_'+setting;b=family(primary_tests,sc,task,P.PAIRS[task],main,preds,key)
            parity_run(b,lambda:a2_parity(P.compute_bundle(primary_tests,P.ChunkedScoring(sc,2000),b),raw['CPS8'][task][setting],key+'/point',point_only=True))
            bundles[key]=b


def propagate(primary_tests,current,records):

    raw=records['batch']
    for task in P.PAIRS:
        key=task+'/R8';name='R8_'+task
        if key not in current:continue
        new=current[key]
        if new['state']=='COMPUTED':
            try:a2_parity(new,raw['families'][name],key+'/B100000')
            except P.Refusal:new=dict(state='DEVIATION',reason='A8NR_PARITY',reports=[])
        current[key]=new;raw['families'][name]=deepcopy(new)
        if new['state']=='DEVIATION':records['context']['own_stages']['A8B-R8' if task=='news' else 'A8B-R8N']=dict(state='DEVIATION',reason='A8NR_PARITY')
    for task in P.PAIRS:
        for setting in ('selected','g0'):
            key=task+'/CPS8_'+setting
            if key not in current:continue
            new=current[key];saved=raw['CPS8'][task][setting]
            if new['state']=='COMPUTED':
                try:a2_parity(new,saved,key+'/B100000')
                except P.Refusal:
                    raw['CPS8'][task]=dict(state='DEVIATION',reason='A8NR_PARITY',reports=[])
                    for s in ('selected','g0'):current[task+'/CPS8_'+s]=dict(state='DEVIATION',reason='A8NR_PARITY',reports=[])
                    records['context']['own_stages']['A8B-CPS8']=dict(state='DEVIATION',reason='A8NR_PARITY')
                    break
                raw['CPS8'][task][setting]=deepcopy(new)
            else:
                raw['CPS8'][task]=dict(state='DEVIATION',reason='A8NR_PARITY',reports=[])
                for s in ('selected','g0'):current[task+'/CPS8_'+s]=dict(state='DEVIATION',reason='A8NR_PARITY',reports=[])
                records['context']['own_stages']['A8B-CPS8']=dict(state='DEVIATION',reason='A8NR_PARITY')
                break
    for family_name in ('primary','R8'):
        for delta in (5,15,60):
            key='notice/DLY8_'+('R8_' if family_name=='R8' else '')+str(delta)
            if key not in current:continue
            new=current[key];saved=raw['DLY8'][family_name][str(delta)]
            if new['state']=='COMPUTED':
                try:a2_parity(new,saved,key+'/B100000')
                except P.Refusal:new=dict(state='DEVIATION',reason='A8NR_PARITY',reports=[])
            raw['DLY8'][family_name][str(delta)]=deepcopy(new)
            current[key]=new
            if new['state']=='DEVIATION':records['context']['own_stages']['DLY8']=dict(state='DEVIATION',reason='A8NR_PARITY')
