'Reproduce forecasts in serial processes with bounded memory use.'
from __future__ import annotations
import gc, hashlib, importlib.util, json, os, resource, subprocess, sys, time
from pathlib import Path
sys.dont_write_bytecode = True
OUT = Path(__file__).resolve().parent
PREP = OUT.parents[2]
B1B, B1C, B3 = (OUT.parent / n for n in ('B1b','B1c','B3'))
C, DEV = PREP/'forecasting/windows/C', PREP/'forecasting/run_forecasts'
os.environ['MPLCONFIGDIR'] = str(OUT/'mpl-cache')
os.environ['TMPDIR'] = '/tmp'
sys.path.insert(0,str(PREP/'forecasting'))
import numpy as np
import pandas as pd
import run_window as rw
rn = rw.rn
rn.OUT = OUT
KEYS, SEEDS, ARMS = rn.KEYS, rw.SEEDS, rw.ARMS
FOLDS = [x[0] for x in rn.FOLDS]+['C']
START = time.monotonic()

def read(p): return json.loads(Path(p).read_text())
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()
def write(p,obj):
    p=OUT/p; p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as f: json.dump(obj,f,indent=2,sort_keys=True,allow_nan=False,default=str);f.write('\n')
def frozen():
    f=read(OUT/'FREEZE.json')
    assert f['state']=='B4_SPEC_FROZEN_BEFORE_COMPUTATION' and f['spec_sha256']==sha(OUT/'SPEC.md')
def module(p,n):
    s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);sys.modules[n]=m;s.loader.exec_module(m);return m
def log(stage,**kw):
    d=dict(utc=pd.Timestamp.now(tz='UTC').isoformat(),stage=stage,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)|kw
    with (OUT/'progress.jsonl').open('a') as f:f.write(json.dumps(d,default=str)+'\n')
    print(json.dumps(d,default=str),flush=True)
    if d['peak_rss_bytes']>2*1024**3: raise MemoryError('forecast_replication exceeded 2 GiB')
def finish(stage,**kw):
    d=dict(seconds=time.monotonic()-START,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,**kw)
    log(stage+'_complete',**d);write('receipts/'+stage+'.json',d)
def original_num(): return np.load(B1B/'X_train.npy',mmap_mode='r')
def metadata():
    return pd.read_parquet(B1B/'development_metadata.parquet'),pd.read_parquet(B1B/'C_metadata.parquet')
def selection(d,w,fold):
    if fold=='C': cutoff=w.target_time.min();test=np.ones(len(w),bool)
    else:
        _,first,last=next(x for x in rn.FOLDS if x[0]==fold)
        cutoff=pd.Timestamp(first+'-01',tz='Australia/Brisbane').tz_convert('UTC')
        test=np.isin(d.bank_month.to_numpy(),[str(p) for p in pd.period_range(first,last,freq='M')])
    train=((d.target_time<cutoff)&(d.label_available_time<cutoff)).to_numpy()
    assert train.all() if fold=='C' else not train[test].any()
    return train,test,cutoff
def prune(a,names,rows=None):
    kept=[];dropped={}
    for j,c in enumerate(names):
        x=a[:,j] if rows is None else a[rows,j]
        k,d=rn.prune(x.reshape(-1,1),[c]);kept+=k;dropped.update(d)
    return kept,dropped

def init():
    expected={p:v['sha256'] for p,v in read(B1B/'INPUT_MANIFEST.json')['files'].items()}
    for base,names in [(B1B,['X_train.npy','X_C.npy','development_metadata.parquet','C_metadata.parquet','source_design.json','phys.parquet']),
                       (B1C,['step0/X_train.npy','step0/X_C.npy','step0/IDENTITY_RESULT.json','placebo_summary.csv','RESULT.json']),
                       (B3,['numeric_audit.py','numeric_violating_key_features.csv.gz','numeric_mask_selection_keys.parquet','numeric_mask_selection_DIAGNOSTIC.json','numeric_RESULT.json']+[f'notice_records_original_{a}.parquet' for a in 'RLP'])]:
        manifest=read(base/'OUTPUT_MANIFEST.json')['files']
        for n in names:
            v=manifest[n];expected[str(base/n)]=v['sha256'] if isinstance(v,dict) else v
        expected[str(base/'OUTPUT_MANIFEST.json')]=sha(base/'OUTPUT_MANIFEST.json')
    seal=read(C/'run/candidate_seal.json')
    for fold in FOLDS:
        if fold=='C':
            rec=seal['receipt'];pred=C/'run/predictions.parquet';expected[str(pred)]=seal['predictions_sha256']
        else:
            rec=read(DEV/f'receipts/{fold}.json');expected[str(DEV/f'predictions/{fold}.parquet')]=rec['sha256']
        for a in ARMS:
            for f in rec['arms'][a]['fits']:
                p=C/f'run/models/{a}_s{f["seed"]}.txt' if fold=='C' else DEV/f'models/{fold}_{a}_s{f["seed"]}.txt'
                expected[str(p)]=f['model_sha256']
    for base in [DEV,C/'run',C/'evaluation',PREP/'forecasting/evaluation_v2g']:
        for p in base.rglob('*'):
            if p.is_file():expected.setdefault(str(p),sha(p))
    for p,h in expected.items(): assert sha(p)==h,('frozen input mismatch',p)
    files={p:dict(sha256=h,bytes=Path(p).stat().st_size) for p,h in sorted(expected.items())}
    if (OUT/'INPUT_MANIFEST.json').exists():assert read(OUT/'INPUT_MANIFEST.json')['files']==files
    else:write('INPUT_MANIFEST.json',dict(created_utc=pd.Timestamp.now(tz='UTC').isoformat(),files=files))
    finish('init',verified_files=len(expected))

def prepare():
    d,w=metadata();source=read(B1B/'source_design.json');names=source['window_design']['kept_numeric'];k=len(names)
    allnames=read(DEV/'design_binding.json')['numeric_features']
    assert source['L_features'][:k]==names and rn.numeric_columns()==allnames
    x=original_num();step=np.load(B1C/'step0/X_train.npy',mmap_mode='r')
    assert x.dtype==step.dtype==np.float32 and x.shape[0]==len(d)
    for st in range(0,len(d),20000):assert np.array_equal(x[st:st+20000,:k],step[st:st+20000,:k],equal_nan=True)
    del step,x;gc.collect()


    omitted=[n for n in allnames if n not in names];discard_checks={n:{'finite':0,'nonzero':0,'rows':0} for n in omitted}
    for month in rn.MONTHS:
        z=pd.read_parquet(rn.BANK/f'{month}.parquet',columns=omitted)
        for n in omitted:
            v=z[n].to_numpy('float32');q=discard_checks[n];q['rows']+=len(v);q['finite']+=int(np.isfinite(v).sum());q['nonzero']+=int((np.isfinite(v)&(v!=0)).sum())
        del z
    assert all(v['nonzero']==0 and v['finite'] in (0,v['rows']) for v in discard_checks.values())
    outnum=np.lib.format.open_memmap(OUT/'numeric_C.npy',mode='w+',dtype='float32',shape=(len(w),k))
    win=pd.read_parquet(C/'features.parquet',columns=list(dict.fromkeys(KEYS+names)))
    assert win[KEYS].equals(w[KEYS])
    for j,n in enumerate(names):outnum[:,j]=win[n].to_numpy('float32')
    outnum.flush();del win
    step=np.load(B1C/'step0/X_C.npy',mmap_mode='r')
    for st in range(0,len(w),20000):assert np.array_equal(outnum[st:st+20000],step[st:st+20000,:k],equal_nan=True)
    del step,outnum;gc.collect()
    v2=module(PREP/'notice_assembly/notice_event_records.py','b4_frozen_v2')
    checks={};inputs={str(OUT/'numeric_C.npy'):sha(OUT/'numeric_C.npy')}
    for arm in 'RLP':
        rec=pd.read_parquet(B3/f'notice_records_original_{arm}.parquet')
        for period,keys in [('development',d[KEYS]),('C',w[KEYS])]:
            block=v2.features(keys,rec);a=block.to_numpy('float32');p=OUT/f'notices_{period}_{arm}.npy';np.save(p,a);inputs[str(p)]=sha(p)
            if arm=='L':
                step=np.load(B1C/f'step0/{"X_train" if period=="development" else "X_C"}.npy',mmap_mode='r')
                assert np.array_equal(a,step[:,k:],equal_nan=True);del step
            checks[f'{period}_{arm}']=dict(rows=len(a),columns=list(block.columns),dtype=str(a.dtype),original_L_step0_parity=arm=='L')
            del block,a;gc.collect()
        del rec
    write('PREPARATION.json',dict(numeric_names=names,all_numeric_names=allnames,omitted_columns=discard_checks,notice_columns=list(v2.COLUMNS),notice_checks=checks,inputs=inputs,original_numeric_cache_parity=True,C_keys_parity=True))
    finish('prepare',development_rows=len(d),C_rows=len(w),numeric_columns=k)

def design(condition):
    assert condition in ('original','aligned')
    if condition=='aligned': assert read(OUT/'IDENTITY.json')['passed']
    prep=read(OUT/'PREPARATION.json');names=prep['numeric_names'];d,w=metadata()
    p=OUT/'corrected_numeric.npy' if condition=='aligned' else B1B/'X_train.npy'
    num=np.load(p,mmap_mode='r');inputs=dict(prep['inputs']);inputs[str(p)]=sha(p);designs={}
    for fold in FOLDS:
        train,test,cutoff=selection(d,w,fold);kept,dropped=prune(num,names,train)
        q90=rn.weighted_q90(d.y_true.to_numpy('float64')[train],d.weight.to_numpy('float64')[train])
        ref=read(C/'run/candidate_seal.json') if fold=='C' else read(DEV/f'receipts/{fold}.json')
        refarms=ref['receipt']['arms'] if fold=='C' else ref['arms']
        assert q90==(ref['prior_q90'] if fold=='C' else ref['q90'])
        spec=dict(train_rows=int(train.sum()),test_rows=int(test.sum()),cutoff=str(cutoff),q90=q90,numeric_kept=kept,numeric_dropped=dropped,arms={})
        for a in ARMS:
            bk=[];bd={}
            if a!='N':
                b=np.load(OUT/f'notices_development_{a}.npy',mmap_mode='r');bn=[a+'_'+c for c in prep['notice_columns']];bk,bd=prune(b,bn,train);del b
            feats=kept+bk;matches=feats==refarms[a]['features']
            if condition=='original':assert matches,(fold,a,'feature ordering')
            spec['arms'][a]=dict(features=feats,notice_kept=bk,notice_dropped=bd,matches_sealed_features=matches)
        designs[fold]=spec
    params={str(s):rn.params(s) for s in SEEDS}
    assert params==read(B1B/'source_design.json')['params_by_seed']
    write(f'{condition}/design.json',dict(condition=condition,folds=designs,numeric_names=names,notice_columns=prep['notice_columns'],numeric_path=str(p),inputs=inputs,params_by_seed=params,spec_sha256=sha(OUT/'SPEC.md'),runner_sha256=sha(__file__)))
    finish(condition+'_design',fits=84)

def fit(condition,fold,arm,seed):
    import lightgbm as lgb
    if condition=='aligned': assert read(OUT/'IDENTITY.json')['passed']
    design=read(OUT/f'{condition}/design.json');spec=design['folds'][fold];an=spec['arms'][arm];names=an['features']
    d,w=metadata();train,test,cutoff=selection(d,w,fold);ids=np.flatnonzero(train);tids=np.flatnonzero(test)
    target=d.y_true.to_numpy('float64')[train]-d.legal_anchor.to_numpy('float64')[train];weights=d.weight.to_numpy('float32')[train]
    ev=w if fold=='C' else d.loc[test].reset_index(drop=True)
    anchor=ev.legal_anchor.to_numpy('float64');caps=rn.price_cap(ev.target_time);out=ev[KEYS].copy()
    assert len(ids)==spec['train_rows'] and len(tids)==spec['test_rows']
    del d,w,ev;gc.collect()
    x=np.empty((len(ids),len(names)),dtype='float32');z=np.empty((len(tids),len(names)),dtype='float32')
    ni=[design['numeric_names'].index(n) for n in spec['numeric_kept']];k=len(ni)
    num=np.load(design['numeric_path'],mmap_mode='r')
    for st in range(0,len(ids),20000):x[st:st+20000,:k]=num[np.ix_(ids[st:st+20000],ni)]
    if fold!='C':
        for st in range(0,len(tids),20000):z[st:st+20000,:k]=num[np.ix_(tids[st:st+20000],ni)]
    del num;gc.collect()
    if fold=='C':
        num=np.load(OUT/'numeric_C.npy',mmap_mode='r')
        for st in range(0,len(tids),20000):z[st:st+20000,:k]=num[np.ix_(tids[st:st+20000],ni)]
        del num
    if arm!='N':
        bn=[arm+'_'+n for n in design['notice_columns']];bi=[bn.index(n) for n in an['notice_kept']]
        b=np.load(OUT/f'notices_development_{arm}.npy',mmap_mode='r')
        for st in range(0,len(ids),20000):x[st:st+20000,k:]=b[np.ix_(ids[st:st+20000],bi)]
        if fold!='C':
            for st in range(0,len(tids),20000):z[st:st+20000,k:]=b[np.ix_(tids[st:st+20000],bi)]
        del b
        if fold=='C':
            b=np.load(OUT/f'notices_C_{arm}.npy',mmap_mode='r');z[:,k:]=b[:,bi];del b
    gc.collect();assert rn.params(seed)==design['params_by_seed'][str(seed)]
    log('fit_start',condition=condition,fold=fold,arm=arm,seed=seed,train_shape=x.shape,test_shape=z.shape)
    model=lgb.LGBMRegressor(**rn.params(seed)).fit(x,target,sample_weight=weights,feature_name=names)
    p=OUT/f'{condition}/models/{fold}_{arm}_s{seed}.txt';p.parent.mkdir(parents=True,exist_ok=True);assert not p.exists();model.booster_.save_model(str(p))
    pred=np.clip(anchor+model.booster_.predict(z,num_threads=rn.N_JOBS),-1000.,caps).astype('float32');assert np.isfinite(pred).all()
    out[f'{arm}_s{seed}']=pred;q=OUT/f'{condition}/predictions/{fold}_{arm}_s{seed}.parquet';q.parent.mkdir(parents=True,exist_ok=True);assert not q.exists();out.to_parquet(q,index=False)
    comparison=None
    if condition=='original':
        ref=C/'run/predictions.parquet' if fold=='C' else DEV/f'predictions/{fold}.parquet'
        sealed=pd.read_parquet(ref,columns=KEYS+[f'{arm}_s{seed}']);assert out[KEYS].equals(sealed[KEYS]);v=sealed[f'{arm}_s{seed}'].to_numpy('float64');delta=np.abs(pred.astype('float64')-v)
        old=C/f'run/models/{arm}_s{seed}.txt' if fold=='C' else DEV/f'models/{fold}_{arm}_s{seed}.txt'
        comparison=dict(exact_equal=bool(np.array_equal(pred,v)),max_absolute_difference=float(delta.max()),mean_absolute_difference=float(delta.mean()),above_tolerance=int((delta>1e-6).sum()),model_hash_equal=sha(p)==sha(old),keys_equal=True,rows=len(v))
    finish(f'{condition}_fit_{fold}_{arm}_{seed}',condition=condition,fold=fold,arm=arm,seed=seed,model_sha256=sha(p),prediction_sha256=sha(q),identity=comparison,lightgbm_version=lgb.__version__,numpy_version=np.__version__,pandas_version=pd.__version__)
    if comparison and comparison['above_tolerance']:raise RuntimeError('PIPELINE_IDENTITY_FAILED')

def seal(condition):
    des=read(OUT/f'{condition}/design.json')
    for p,h in des['inputs'].items():assert sha(p)==h
    files={};checks=[]
    for fold in FOLDS:
        pred=None
        for a in ARMS:
            total=None
            for s in SEEDS:
                p=OUT/f'{condition}/predictions/{fold}_{a}_s{s}.parquet';receipt=read(OUT/f'receipts/{condition}_fit_{fold}_{a}_{s}.json');assert sha(p)==receipt['prediction_sha256']
                if condition=='original':assert receipt['identity']['above_tolerance']==0
                part=pd.read_parquet(p)
                if pred is None:pred=part[KEYS].copy()
                assert pred[KEYS].equals(part[KEYS]);v=part[f'{a}_s{s}'].to_numpy();pred[f'{a}_s{s}']=v
                if total is None:total=np.zeros(len(v),dtype='float64')
                total+=v
            pred[a]=(total/3).astype('float32')
        if condition=='original':
            p=C/'run/predictions.parquet' if fold=='C' else DEV/f'predictions/{fold}.parquet';ref=pd.read_parquet(p,columns=KEYS+list(ARMS));assert pred[KEYS].equals(ref[KEYS])
            for a in ARMS:
                delta=np.abs(pred[a].to_numpy('float64')-ref[a].to_numpy('float64'))
                checks.append(dict(fold=fold,arm=a,rows=len(pred),max_absolute_difference=float(delta.max()),mean_absolute_difference=float(delta.mean()),above_tolerance=int((delta>1e-6).sum()),exact_equal=bool(np.array_equal(pred[a],ref[a]))))
                assert delta.max()<=1e-6
        assert 'y_true' not in pred
        p=OUT/f'{condition}/predictions/{fold}.parquet';assert not p.exists();pred.to_parquet(p,index=False);files[fold]=dict(path=str(p),sha256=sha(p),rows=len(pred),q90=des['folds'][fold]['q90'])
    write(f'{condition}/candidate_seal.json',dict(state='B4_'+condition.upper()+'_CANDIDATES_SEALED',files=files,spec_sha256=sha(OUT/'SPEC.md'),design_sha256=sha(OUT/f'{condition}/design.json'),test_scored_before_bank_seal=False))
    if condition=='original':
        receipts=[read(OUT/f'receipts/original_fit_{f}_{a}_{s}.json')['identity']|dict(fold=f,arm=a,seed=s) for f in FOLDS for a in ARMS for s in SEEDS]
        write('IDENTITY.json',dict(passed=True,seed_fits=len(receipts),ensemble_checks=checks,seed_checks=receipts,all_models_hash_equal=all(v['model_hash_equal'] for v in receipts),all_predictions_exact_equal=all(v['exact_equal'] for v in receipts+checks),max_absolute_difference=max(v['max_absolute_difference'] for v in receipts+checks),tolerance=1e-6))
    finish(condition+'_seal',folds=len(files))

def serial(condition):
    lock=OUT/'.fit.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    try:
        for f in FOLDS:
            for a in ARMS:
                for s in SEEDS:
                    receipt=OUT/f'receipts/{condition}_fit_{f}_{a}_{s}.json'
                    if receipt.exists():
                        r=read(receipt)
                        if condition=='original':assert r['identity']['above_tolerance']==0
                        assert sha(OUT/f'{condition}/models/{f}_{a}_s{s}.txt')==r['model_sha256']
                        assert sha(OUT/f'{condition}/predictions/{f}_{a}_s{s}.parquet')==r['prediction_sha256']
                        continue
                    lp=OUT/f'logs/{condition}_{f}_{a}_{s}.log';lp.parent.mkdir(exist_ok=True)
                    with lp.open('x') as logf:
                        code=subprocess.run([sys.executable,'-B',str(Path(__file__)),'fit',condition,f,a,str(s)],stdout=logf,stderr=subprocess.STDOUT).returncode
                    if code:raise RuntimeError(f'Fit failed {condition} {f} {a} {s}; see {lp}')
                    count=len(list((OUT/'receipts').glob(f'{condition}_fit_*.json')))
                    (OUT/'PROGRESS.md').write_text(f'# forecast_replication progress\n\n{pd.Timestamp.now(tz="UTC").isoformat()}\n\nPhase: {condition}. Completed fits: {count}/84. One serial fit; frozen SPEC unchanged.\n')
                    log('serial_progress',condition=condition,completed_fits=count,total=84)
        seal(condition)
    finally: lock.unlink()

if __name__=='__main__':
    frozen();stage=sys.argv[1]
    try:
        if stage=='fit':fit(sys.argv[2],sys.argv[3],sys.argv[4],int(sys.argv[5]))
        elif stage in ('design','serial','seal'):globals()[stage](sys.argv[2])
        else:globals()[stage]()
    except Exception as exc:
        write(f'failures/{time.time_ns()}_{stage}.json',dict(error=repr(exc),argv=sys.argv));raise
