'Recover synthetic test inputs and check their saved hashes.'
import ast,hashlib,itertools,json,os,pickle,sys
from pathlib import Path
from copy import deepcopy
from table_input_hash import AP,ROOT
sys.path.insert(0,str(AP/'code'))
sys.path.insert(0,str(AP/'tests'))
import read_comparisons as P

def digest(data):return hashlib.sha256(data).hexdigest()

def recover(item,value,rows):
    path=Path(item['path'])
    if path.exists():
        assert P.sha256(path)==item['sha256'], 'Existing synthetic bytes drift: '+str(path)
        rows.append(dict(**item,bytes=path.stat().st_size,method='Existing metadata; original SHA verified'))
        return True
    assert path.is_relative_to(Path('runtime/synthetic_forecasts'))
    for indent,sort,ascii_,separators,newline in itertools.product((None,2,4),(False,True),(True,False),(None,(',',':')),('\n','')):
        try:data=(json.dumps(value,indent=indent,sort_keys=sort,ensure_ascii=ascii_,separators=separators,allow_nan=False)+newline).encode()
        except (ValueError,TypeError):continue
        if digest(data)!=item['sha256']:continue
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        rows.append(dict(**item,bytes=len(data),method='Immutable cached JSON; exact original SHA'))
        return True
    return False

def main():
    assert os.getpriority(os.PRIO_PROCESS,0)==20;P.resource_gate()
    reuse=P.strict_json(AP/'a8post3/final_suite3/VERIFIED_READER_REUSE.json')
    for rel,sha in reuse['files'].items():assert P.sha256(AP/rel)==sha
    prior=P.strict_json(AP/'a8post3/final_suite2/SOURCE_HASHES_BEFORE.json')
    for rel,sha in prior.items():
        if rel.startswith(('code/','tests/')):assert P.sha256(AP/rel)==sha,'Synthetic source changed: '+rel
    args,_=pickle.load((AP/'a8post3/final_suite2/UNVALIDATED_ASSEMBLY.pkl').open('rb'))
    m,inputs,*_=args;assert m['synthetic'] is True and inputs['seal']['synthetic'] is True
    evidence=P.strict_json(reuse['evidence']['path']);record=P.strict_json(reuse['record']['path']);rows=[];unavailable=[]
    root=Path('runtime/synthetic_forecasts/native')


    if not Path(inputs['seal']['predictions'][0]['path']).exists():
        import sealed_synthetic as S
        tree=ast.parse((AP/'tests/sealed_synthetic.py').read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='layout')
        stop=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='full_native_score')
        fn=deepcopy(fn);fn.name='restore_grid_only';fn.body=fn.body[:stop]
        ns=dict(S.__dict__);exec(compile(ast.Module(body=[fn],type_ignores=[]),'SYNTHETIC_GRID_PREFIX','exec'),ns)
        ns['restore_grid_only'](root,P.dependencies())
        for item in [*inputs['seal']['predictions'],*inputs['seal']['truth_panels'].values()]:
            assert P.sha256(item['path'])==item['sha256'],'Synthetic deterministic grid identity mismatch'
            rows.append(dict(**P.identity(item['path']),bytes=Path(item['path']).stat().st_size,method='Unchanged synthetic generator prefix; original SHA verified'))

        generated=root/'confirmation/execution/synthetic_state/SEAL.json'
        if P.sha256(generated)!=m['inputs']['seal']['sha256']:
            generated.rename(generated.with_name('SYNTHETIC_GENERATOR_PREFIX_SEAL.json'))
    for item in [*inputs['seal']['predictions'],*inputs['seal']['truth_panels'].values()]:
        assert P.sha256(item['path'])==item['sha256'],'Synthetic grid identity mismatch'
        if not any(row['path']==item['path'] for row in rows):
            rows.append(dict(**P.identity(item['path']),bytes=Path(item['path']).stat().st_size,method='Recovered synthetic generator bytes; original SHA verified'))
    for role,item in m['inputs'].items():
        if role in inputs and not recover(item,inputs[role],rows):unavailable.append(role)
    if 'batch' in unavailable:


        import frozen_losses as L
        primary_tests=P.dependencies()[0]
        ns=dict(CLASS=P.CLASS)
        L.ast_functions(P.BATCH_CODE/'score_batch.py',('fill_fields',),ns)
        batch=deepcopy(inputs['batch']);family=batch['families']['R8_notice']
        reports=deepcopy(family['reports'])
        for report in reports:
            for key in ('interval95_one_day','interval95_seven_day','interval_family_one_day','interval_family_seven_day'):report.pop(key,None)
        native=dict(family_m=family['family_m'],days=family['days'],date_gaps=family['date_gaps'],reports=reports,
            table_results_fields=[ns['fill_fields'](primary_tests,report) for report in reports],three_seed=None,bootstrap_draws=100000,state='COMPUTED')
        batch['families']['R8_notice']=deepcopy(native)
        for delay in ('5','15','60'):batch['DLY8']['R8'][delay]=deepcopy(native)
        assert recover(m['inputs']['batch'],primary_tests.json_safe(batch),rows),'Original synthetic batch metadata identity mismatch'
        unavailable.remove('batch')
    state_manifest=dict(schema='A8POST_INPUTS_V2',synthetic=True,inputs=evidence['inputs'])
    assert recover(reuse['manifest'],state_manifest,rows),'Manifest cannot be reproduced exactly'
    data={task:{c['arm']:{k:v for k,v in c['native_primary'].items() if k!='timestamp_checks'} for c in task_data['contrasts']} for task,task_data in record['tasks'].items()}
    assert recover(record['tasks']['news']['contrasts'][0]['native_primary']['timestamp_checks'],data,rows),'Native primary metadata cannot be reproduced exactly'


    import pandas as pd
    import frozen_losses as L
    ns=L.native_functions();state=Path(m['inputs']['seal']['path']).parent
    for task in P.PAIRS:
        dest=state/'scored'/(task+'__DAILY_LOSSES.csv')
        item=next(i for i in inputs['score_receipt']['files'] if i['path']==str(dest))
        if not dest.exists():
            panel,days,_,predictions,*_=ns['_read_task_data'](task,inputs['seal'])
            arms=['N','M','L_count','L_chen'] if task=='news' else ['N','M_notice','L14','L_Laz','L_chen_notice']
            daily={a:ns['_daily'](panel,predictions[(a,20260919,'main')])[1] for a in arms}
            for (arm,seed,variant),prediction in predictions.items():
                if seed==20260919 and variant=='main':daily[arm]=ns['_daily'](panel,prediction)[1]
            data=pd.DataFrame({'target_day':days,**daily}).to_csv(index=False).encode()
            assert digest(data)==item['sha256'],'Synthetic native daily CSV differs'
            dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
            rows.append(dict(**item,bytes=len(data),method='Frozen daily aggregation only; original CSV SHA verified'))
        else:
            assert P.sha256(dest)==item['sha256'],'Recovered synthetic CSV identity drift'
            rows.append(dict(**item,bytes=dest.stat().st_size,method='Existing recovered daily CSV; original SHA verified'))
    receipt=dict(schema='A8POST5_SYNTHETIC_RECOVERY_V1',synthetic_only=True,no_full_score_inference_or_reader_replay=True,
        source_cache=reuse['files'],recovered=rows,unavailable_json_roles=unavailable,
        input_checks='Only absent synthetic scratch; every published artifact checked against original retained SHA. Missing original JSON roles remain missing until exact bytes can be recovered.')
    (ROOT/'SYNTHETIC_RECOVERY.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(dict(state='HASH_IDENTICAL_SYNTHETIC_RECOVERY',files=len(rows),unavailable=unavailable)))

if __name__=='__main__':main()
