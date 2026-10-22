'Recompute daily losses from forecasts after checking their hashes.'
from contextlib import contextmanager
from copy import deepcopy
import ast
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import read_comparisons as P
from parity_gate import deviation,run as parity_run


def ast_functions(path, names, namespace):
    record=P.strict_json(P.HERE/'DEPENDENCY_PINS.json');pins=record['files']
    rel=str(Path(path).relative_to(P.PROJ))
    exact=record.get('exact_ast',{}).get(rel)
    if exact is None:P.require(rel in pins and P.sha256(path)==pins[rel], 'Frozen function source drift: '+rel)
    tree=ast.parse(Path(path).read_text())
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
    P.require({n.name for n in nodes}==set(names),'Missing frozen function')
    if exact is not None:
        for n in nodes:P.require(n.name in exact and hashlib.sha256(ast.dump(n,include_attributes=False).encode()).hexdigest()==exact[n.name], 'Exact frozen AST drift: '+rel+'/'+n.name)
    module=ast.Module(body=nodes,type_ignores=[])
    exec(compile(module,str(path),'exec'),namespace)
    return namespace


def native_functions():
    import pandas as pd
    from dataclasses import replace
    a1=P.load_module('_a8post_a1',P.confirmation/'execution/additional_scoring.py')
    ns=dict(Path=Path,np=np,pd=pd,hashlib=hashlib,json=json,SEED=20260919,
            KEYS=['origin','target_time','region','horizon'],a1=a1,replace=replace,
            sha256=P.sha256,read_json=P.strict_json,require=P.require,
            audit=lambda *a:None,file_identity=P.identity)
    def atomic(path,value,**kw):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
    ns['atomic_json']=atomic
    names=('tag','key_hash','coerce_keys','normalize','complete_grid','_read_task_data','_daily',
           '_json_result','_write_inference','_matched_mask','_secondary_contrasts',
           '_stage_reasons_for','_a1_contrast_row','_a1_task','_a1_reclip')
    ast_functions(P.confirmation/'execution/seal_score.py',names,ns)

    sys.path.insert(0,str(P.confirmation/'execution'))
    try:report=P.load_module('_a8post_report_adapter',P.confirmation/'execution/report_adapter.py')
    finally:sys.path.pop(0)
    ns['_primary_sentence']=lambda r,s:report.primary_sentence(r,s)
    ns['_secondary_reading']=report.secondary_reading
    return ns


def permit(sc,seal):


    return sc.ExecutionPermit('A8POST_RECEIPT_BOUND_REPLAY',seal.get('design_freeze_sha256',P.sha256(P.confirmation/'FREEZE.json')),seal.get('completed_input_manifest_sha256','f'*64) if seal.get('synthetic') else seal['completed_input_manifest_sha256'],True,True)


class Capture:

    def __init__(self,sc,source):
        self.sc,self.source,self.calls=sc,source,[]
    def __getattr__(self,k):return getattr(self.sc,k)
    def save(self,fn,losses,pairs,days,*args,**kw):
        P.resource_gate()
        result=fn(losses,*args,**kw)
        bundle=dict(task=self.source,state='COMPUTED',days=list(days),pairs=[list(x) for x in pairs],
            losses={a:np.array(v,copy=True) for a,v in losses.items()},subset=True,
            native_result=result)
        self.calls.append((result,bundle))
        return result
    def specified_daily_inference(self,losses,days,source,permit_,panel_id):
        pairs=self.sc.NEWS_FAMILY if source=='news' else self.sc.NOTICE_FAMILY
        return self.save(self.sc.specified_daily_inference,losses,pairs,days,days,source,permit_,panel_id)
    def secondary_daily_inference(self,losses,pairs,days,permit_):
        b=self.save(self.sc.secondary_daily_inference,losses,pairs,days,pairs,days,permit_)
        self.calls[-1][1]['unadjusted']=True
        return b


def core_task(ns,sc,source,seal,root):

    P.resource_gate()
    tree=ast.parse((P.confirmation/'execution/seal_score.py').read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='score')
    loop=next(n for n in fn.body if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='source')
    stop=next(i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='price_path' for t in n.targets))
    body=loop.body[:stop]
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    capture=Capture(sc,source)
    bundles={}
    frozen_writer=ns['_write_inference']
    def write(path,result):
        found=next((b for r,b in capture.calls if r is result),None)
        P.require(found is not None,'Frozen inference without captured loss arguments')
        name=Path(path).name
        found.update(id=source+'/'+name,native_name=name)
        bundles[name]=found
        return frozen_writer(path,result)
    ns.update(source=source,scoring=capture,seal_receipt=seal,scoring_root=root,
        scoring_permit=permit(sc,seal),manifest=P.strict_json(seal['feature_manifest_path']),
        summaries={},lines=[],a1_primary={},a1_tasks={},_write_inference=write,
        root=Path(seal['_state_root']))

    ns['_primary_sentence']=lambda *a:''
    exec(compile(ast.Module(body=body,type_ignores=[]),str(P.confirmation/'execution/seal_score.py'),'exec'),ns)
    ns['_write_inference']=frozen_writer
    return bundles,ns['daily'],ns['clips'],ns['summaries'][source]


def canonical_daily(days,losses):
    import pandas as pd
    return pd.DataFrame({'target_day':days,**losses}).to_csv(index=False).encode()


def native_parity(sc,bundle,saved):
    'Compare each bootstrap interval, estimate and tail count with the saved values.'
    pairs=[tuple(x) for x in bundle['pairs']]
    P.require([(r['arm'],r['reference']) for r in saved['reports']]==pairs,'Native pair inventory drift')
    proof=[]
    for r in saved['reports']:
        a,b=r['arm'],r['reference']
        if a not in bundle['losses'] or b not in bundle['losses']:
            P.require(r.get('primary_decision','NOT_EVALUABLE')=='NOT_EVALUABLE','Missing native arm rendered')
            continue
        for block,old in r['bootstrap'].items():
            block=int(block)
            try:picks=sc.block_picks(len(bundle['days']),block,bundle['days'] if bundle.get('subset') else None)
            except ValueError:
                P.require(old.get('interval95_percent') is None,'Unsupported block has numbers');continue
            result=sc.paired_percent_interval(bundle['losses'][a],bundle['losses'][b],picks)
            for key in ('effect_percent_reference_mae','reference_mae','interval95_percent','finite_draws',
                        'undefined_draws','bootstrap_nonpositive_effect_count','monte_carlo_resolution'):
                if key in old:P.require(result[key]==old[key],f'Native B2000 parity mismatch: {bundle["id"]}/{a}/{block}/{key}')
            dm=r.get('dm_p1',{})
            if 'mean_difference' in dm:P.require(float((bundle['losses'][a]-bundle['losses'][b]).mean())==dm['mean_difference'],'Native mean parity mismatch')
            proof.append(dict(arm=a,reference=b,block=block,state='PASS',draws=2000,
                interval=result['interval95_percent'],tail_count=result['bootstrap_nonpositive_effect_count']))
    return proof


def clean(primary_tests,x):
    return primary_tests.json_safe(x)


def capture_a2(primary_tests,sc,source,inputs,rows):

    calls=[]
    old=primary_tests.family_inference
    def wrapped(sc_,losses,pairs,days,m=None,subset=False):
        r=old(sc_,losses,pairs,days,m,subset)
        calls.append(dict(task=source,state='COMPUTED',days=list(days),pairs=pairs,
            losses={k:np.array(v,copy=True) for k,v in losses.items()},family_m=m or len(pairs),subset=subset,
            native_result=r))
        return r
    try:
        primary_tests.family_inference=wrapped
        result=primary_tests.combination_section(sc,inputs,source,rows)
    finally:primary_tests.family_inference=old
    return result,calls


def a2_parity(actual,saved,where,point_only=False):


    fields={'mean_difference','effect_percent_reference_mae','reference_mae','arm_mae','interval95_percent',
        'interval_family_adjusted_percent','bootstrap_nonpositive_effect_count','finite_draws',
        'undefined_draws','monte_carlo_resolution','p_two_sided','hln_p_two_sided','hac7_p_two_sided','holm_p','hln_holm_p','hac7_holm_p','benchmark_mae','combined_mae','single_mae'}
    if point_only:fields={'mean_difference','effect_percent_reference_mae','reference_mae','arm_mae','benchmark_mae','combined_mae','single_mae'}
    compared=[]
    def walk(a,b,path):
        if isinstance(a,dict):
            for k,v in a.items():
                if k in fields:
                    anchor=k
                    # Compare raw p-values before applying the specified Holm family adjustment.

                    if k not in b and k in {'holm_p','hln_holm_p','hac7_holm_p'}:
                        single=all(x.get('bootstrap',{}).get('1',{}).get('family_m')==1 for x in (a,b))
                        if single:anchor={'holm_p':'p_two_sided','hln_holm_p':'hln_p_two_sided','hac7_holm_p':'hac7_p_two_sided'}[k]
                    P.require(anchor in b,'Missing frozen parity field: '+where+'/'+path+k)
                    P.require( clean_value(v)==clean_value(b[anchor]),'Frozen reader exact parity mismatch: '+where+'/'+path+k)
                    compared.append(path+k)
                elif isinstance(v,(dict,list)) and k in b:walk(v,b[k],path+k+'/')
        elif isinstance(a,list):
            P.require(isinstance(b,list) and len(a)==len(b),'Frozen reader row census mismatch: '+where)
            for i,(x,y) in enumerate(zip(a,b)):walk(x,y,path+str(i)+'/')
    def clean_value(x):
        if isinstance(x,np.ndarray):return x.tolist()
        if isinstance(x,np.generic):return x.item()
        if isinstance(x,float) and not np.isfinite(x):return None
        return x
    walk(actual,saved,'')
    P.require(compared,'No frozen point/interval parity anchors: '+where)
    return compared


def replay(state,scratch,primary_tests,sensitivity_tests,robustness_tests,frozen,records,synthetic=False):

    state=Path(state);scratch=Path(scratch)
    P.require(not scratch.exists(),'Replay scratch already exists')
    from replay_composite_losses import effective_inputs
    inputs=effective_inputs(primary_tests,frozen,state,records,synthetic)
    inputs.seal['_state_root']=str(state)

    for item in [*inputs.seal['predictions'],*inputs.seal['truth_panels'].values()]:P.checked(item)
    ns=native_functions();bundles={};proof={};clipping={};native={};reader={};daily_proof={};mean_proof={}
    sc2=P.ChunkedScoring(frozen,2000,512,P.resource_gate)
    for source in P.PAIRS:
        captured,daily,clips,summary=core_task(ns,frozen,source,inputs.seal,scratch/source)
        clipping[source]=[r for r in clips if not any(k in r for k in ('region','horizon','target_day'))]
        primary_name=source+'__PRIMARY.json'
        days=captured[primary_name]['days']
        saved_csv=inputs.score_file(source+'__DAILY_LOSSES.csv')
        daily_ok=canonical_daily(days,daily)==saved_csv.read_bytes()
        daily_proof[source]=dict(state='PASS' if daily_ok else 'DEVIATION',file=P.identity(saved_csv),
            columns=list(daily),seed=20260919,variant='main',format='unchanged pandas to_csv(index=False)')

        summary_saved=inputs.score_json('SCORE_REPORT.json')[source]
        means_ok=summary['pooled_mae']==summary_saved['pooled_mae']
        mean_proof[source]=dict(state='PASS' if means_ok else 'DEVIATION',point_fields='SCORE_REPORT/'+source+'/pooled_mae')
        for name,bundle in captured.items():
            saved=inputs.score_json(name,required=False)
            if not daily_ok or not means_ok:
                deviation(bundle,'canonical DAILY_LOSSES byte/pooled mean mismatch')
                proof[name]=dict(state='DEVIATION',reason='canonical DAILY_LOSSES byte/pooled mean mismatch')
            elif saved is None:

                deviation(bundle,'missing or mismatched frozen B2000 reference')
                proof[name]=dict(state='DEVIATION',reason='missing frozen B2000 reference')
            else:
                try:proof[name]=dict(state='PASS',checks=native_parity(sc2,bundle,saved))
                except (P.Refusal,ValueError) as exc:
                    deviation(bundle,'missing or mismatched frozen B2000 reference')
                    proof[name]=dict(state='DEVIATION',reason=str(exc))
            bundle['frozen_parity']=proof[name]['state']
            native[name]=bundle
        primary=captured[primary_name];primary['id']=source+'/primary';primary['subset']=False
        primary['frozen_parity']=proof[primary_name]['state']
        bundles[primary['id']]=primary
        for seed in (20260920,20260921):
            b=captured.get(f'{source}__SEED_{seed}.json')
            if b:
                b['id']=f'{source}/seed_{seed}';bundles[b['id']]=b
        mean=captured.get(source+'__THREE_SEED_MEAN.json')
        if mean and mean['state']=='COMPUTED':
            primary['mean_prediction_losses']=mean['losses']
            primary['mean_prediction_loss_definition']='daily loss of the mean prediction; not mean arm loss'


        persisted_reader=deepcopy(records['a2']['tasks'][source])
        frozen_reader=primary_tests.run_task(frozen,inputs,source) if primary['state']=='COMPUTED' else persisted_reader
        if primary['state']=='COMPUTED':
            parity_run(primary,lambda:a2_parity(frozen_reader['primary'],persisted_reader['primary'],source+'/persisted_primary'))
        records['a2']['tasks'][source]=frozen_reader
        if primary['state']=='COMPUTED':


            from reading_propagation import batch_reading
            from synthetic_support import readmission
            native_batch=batch_reading(sensitivity_tests,{},records)
            with readmission(sensitivity_tests,records['seal']):
                records['a3']['tasks'][source]=sensitivity_tests.run_task_a3(frozen,inputs,source,frozen_reader,pc_result=records.get('pc'),batch=native_batch,label=records.get('label'))
        records['score_report'][source]=summary
        rows=frozen_reader['primary']
        combo,calls=capture_a2(primary_tests,sc2,source,inputs,rows) if primary['state']=='COMPUTED' else (dict(state='DEVIATION',reports=[],reason='A8NR_PARITY'),[])
        if calls:
            b=calls[0];b['id']=source+'/combination'
            parity_run(b,lambda:a2_parity(combo,records['a2']['tasks'][source]['combination'],source+'/combination'))
            benchmark_source,benchmark_arm=primary_tests.BENCHMARK[source]
            def benchmark_ids(seal):
                return {(i['seed'],i['variant']):i['sha256'] for i in seal['predictions'] if i['source']==benchmark_source and i['arm']==benchmark_arm}
            if benchmark_ids(inputs.seal)==benchmark_ids(records['seal']):
                parity_run(b,lambda:a2_parity(combo,persisted_reader['combination'],source+'/persisted_combination'))
            if len(calls)>1 and b['state']=='COMPUTED':
                b['mean_prediction_losses']=calls[1]['losses'];b['mean_prediction_loss_definition']='daily loss of the mean prediction; not mean arm loss'
            bundles[b['id']]=b
        else:bundles[source+'/combination']=dict(id=source+'/combination',task=source,state='DEVIATION' if primary['state']!='COMPUTED' else 'NOT_EVALUABLE',losses={},reason='A8NR_PARITY' if primary['state']!='COMPUTED' else 'benchmark unavailable')
        for name,b in captured.items():
            if name==primary_name or '__SEED_' in name or '__THREE_SEED_MEAN' in name:continue


            if name.endswith('__first_L.json'):layer='first_chunk'
            elif name.endswith('__24h.json'):layer='window_24h'
            elif name.endswith('__DROP_FIRST_SEVEN_DAYS.json'):layer='drop_first_seven'
            elif name.endswith('__A1_OFFICIAL_CAP_RECLIP_PRIMARY.json'):layer='official_cap'
            else:layer='native:'+name.removesuffix('.json')
            b['id']=source+'/'+layer;b['frozen_parity']=proof[name]['state'];bundles[b['id']]=b

        reader[source]=dict(combination=combo,primary=rows,reference_kind='unchanged frozen primary_tests.run_task with actual CS8 receipt/composite')
    from squared_replay import replay as squared_replay
    squared_proof=squared_replay(frozen,records)
    return bundles,dict(squared_parity=squared_proof,scratch=str(scratch.parent),native_parity=proof,daily_csv_proof=daily_proof,pooled_mean_proof=mean_proof,
        csv_scope='persisted main-seed/main-variant CSV columns only; other arrays have point and independent frozen-function prefix proofs, not persisted CSV proof',
        canonical_daily_bytes='PASS' if all(x['state']=='PASS' for x in daily_proof.values()) else 'DEVIATION',exact_pooled_means='PASS' if all(x['state']=='PASS' for x in mean_proof.values()) else 'DEVIATION',
        clipping=clipping,native=native,reader=reader,read_log=inputs.read_log)


def complete_bundles(primary_tests,sensitivity_tests,robustness_tests,sc,bundles,records,evidence):

    import pandas as pd
    for task in P.PAIRS:
        primary=bundles[task+'/primary']
        def absent(layer,reason='not applicable under frozen design'):
            return dict(id=task+'/'+layer,task=task,state='NOT_EVALUABLE',losses={},pairs=P.PAIRS[task],days=primary['days'],reason=reason)
        for layer in ('first_chunk','window_24h','official_cap','drop_first_seven','label_replacement','l1_family','pd_family','report_2025'):
            bundles.setdefault(task+'/'+layer,absent(layer))
        if primary['state']!='COMPUTED':
            for layer in ('cheap','mn','lear','combination_benchmark','shift','subsets'):
                bundles[task+'/'+layer]=dict(absent(layer,'A8NR_PARITY'),state='DEVIATION',mean_prediction_losses=None)
            continue
        daily=pd.DataFrame({'target_day':primary['days'],**primary['losses']})


        pairs=list(dict.fromkeys([*primary_tests.CHEAP_COMPARATORS[task],*sensitivity_tests.A3_NEW_CONTRASTS[task]]))
        bundles[task+'/cheap']=dict(primary,id=task+'/cheap',pairs=pairs,unadjusted=True,mean_prediction_losses=None)
        ref=P.PAIRS[task][0][1]
        bundles[task+'/mn']=dict(primary,id=task+'/mn',pairs=[(ref,'N')],unadjusted=True,mean_prediction_losses=None)
        if task=='news':bundles[task+'/lear']=dict(primary,id=task+'/lear',pairs=[('LEAR','N')],unadjusted=True,mean_prediction_losses=None)
        benchmark='LEAR' if task=='news' else 'NP'
        bundles[task+'/combination_benchmark']=dict(primary,id=task+'/combination_benchmark',pairs=[(a,benchmark) for a,b in P.PAIRS[task]],unadjusted=True,mean_prediction_losses=None)
        content=primary_tests.CONTENT_ARM[task]
        name=task+'__SECONDARY__'+content+'__P_shift.json'
        native=evidence['native'].get(name)
        bundles[task+'/shift']=dict(native,id=task+'/shift',unadjusted=True) if native else absent('shift','shift stage unavailable')


        calls=[];old=primary_tests.family_inference
        def collect(sc_,losses,pairs,days,m=None,subset=False):
            result=old(sc_,losses,pairs,days,m,subset)
            calls.append(dict(task=task,state='COMPUTED',losses={k:np.array(v,copy=True) for k,v in losses.items()},pairs=pairs,days=days,family_m=m or len(pairs),subset=subset,descriptive=True))
            return result
        try:
            primary_tests.family_inference=collect
            actual=primary_tests.strict_unexposed_section(P.ChunkedScoring(sc,2000),task,daily)
            b=dict(calls[-1],id=task+'/subsets');parity_run(b,lambda:a2_parity(actual,records['a2']['tasks'][task]['strictly_unexposed'],task+'/strictly_unexposed'));bundles[b['id']]=b
            if task=='news':
                from synthetic_support import readmission
                with readmission(sensitivity_tests,records['seal']):keep=sensitivity_tests.readmission_free_days()
                actual=sensitivity_tests.subset_reports(P.ChunkedScoring(sc,2000),task,daily,keep,'A3V1')
                if actual.get('state')=='COMPUTED':
                    b=dict(calls[-1],id=task+'/readmission_free_subset');parity_run(b,lambda:a2_parity(actual,records['a3']['tasks'][task]['readmission_free_subset'],task+'/readmission_free_subset'));bundles[b['id']]=b

            from replay_composite_losses import effective_inputs
            inputs=effective_inputs(primary_tests,sc,Path(records['_seal_path']).parent,records,records.get('seal',{}).get('synthetic',False))
            actual=sensitivity_tests.matched_support_section(P.ChunkedScoring(sc,2000),inputs,task,records['a2']['tasks'][task].get('p_content_unmatched'))
            if actual.get('state')=='COMPUTED':
                b=dict(calls[-1],id=task+'/matched_support_subset');parity_run(b,lambda:a2_parity(actual,records['a3']['tasks'][task]['matched_support'],task+'/matched_support'));bundles[b['id']]=b
        finally:primary_tests.family_inference=old

        for layer in ('cheap','mn','lear','combination_benchmark'):
            b=bundles.get(task+'/'+layer)
            if not b or b['state']!='COMPUTED':continue
            def verify_alias():
                computed=P.compute_bundle(primary_tests,P.ChunkedScoring(sc,2000),b)
                for r in computed['reports']:
                    key=r['arm']+'-'+r['reference']
                    saved=records['a3']['tasks'][task].get('a3_new_cheap_contrasts',{}).get(key) or records['a2']['tasks'][task].get('cheap_text_comparators',{}).get(key)
                    if saved and ('bootstrap' in saved or 'mean_difference' in saved):a2_parity(r,saved,task+'/'+layer+'/'+key)
                    else:
                        name=task+'__SECONDARY__'+r['arm']+'__'+r['reference']+'.json'
                        if name in evidence['native_parity']:
                            P.require(evidence['native_parity'][name]['state']=='PASS','Single-contrast native parity failed: '+name)
                        elif layer=='combination_benchmark':


                            anchor=primary_tests.contrast_stats(sc,b['losses'][r['arm']],b['losses'][r['reference']],primary_tests.complete_picks(sc,len(b['days'])),1)
                            a2_parity(r,anchor,task+'/'+layer+'/'+key)
                        else:raise P.Refusal('Missing single-contrast frozen parity: '+name)
            parity_run(b,verify_alias)
    for b in bundles.values():
        if b.get('native_name') in evidence['native_parity']:b['frozen_parity']=evidence['native_parity'][b['native_name']]['state']
    from optional_losses import batch,label
    batch(primary_tests,sensitivity_tests,sc,records,bundles);label(primary_tests,sc,records,bundles)
    from batch_layers import replay as batch_layers
    batch_layers(primary_tests,sc,records,bundles)
    # Resample the daily losses without retaining the smaller draw arrays.
    for b in [*bundles.values(),*evidence['native'].values()]:b.pop('native_result',None)
    return bundles
