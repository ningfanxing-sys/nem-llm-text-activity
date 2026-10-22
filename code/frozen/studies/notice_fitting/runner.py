'Fit the notice representation models by fold and seed in serial processes.'
from __future__ import annotations
import gc, hashlib, importlib.util, json, os, resource, shutil, subprocess, sys, time
from pathlib import Path
sys.dont_write_bytecode=True
OUT=Path(__file__).resolve().parent;PROJ=OUT.parents[2];AUTO=PROJ/'forecasting';forecast_replication=OUT.parent/'forecast_replication';label_availability=OUT.parent/'label_availability';B1B=OUT.parent/'B1b';V3=OUT.parent/'V3';RF=OUT.parent/'RF';FINAL3=OUT.parent/'notice_records/source_relations'
os.environ['MPLCONFIGDIR']=str(OUT/'mpl-cache');os.environ['TMPDIR']='/tmp'
sys.path.insert(0,str(AUTO))
import numpy as np
import pandas as pd
import psutil
import run_window as rw
rn=rw.rn; rn.OUT=OUT
KEYS=rn.KEYS;SEEDS=(20260919,20260920,20260921);FOLDS=[f[0] for f in rn.FOLDS]+['C'];ARMS=tuple('RLP');LIMIT=2*1024**3;START=time.monotonic();ACTIVE_FREEZE=OUT/'FREEZE_PREFIT_CORRECTION.json'
def read(p):return json.loads(Path(p).read_text())
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def write(p,obj):
 p=OUT/p;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x') as f:json.dump(obj,f,indent=2,sort_keys=True,default=str,allow_nan=False);f.write('\n')
def module(p,n):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);sys.modules[n]=m;s.loader.exec_module(m);return m
def rss():
 n=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;return int(n if sys.platform=='darwin' else n*1024)
def log(stage,**kw):
 obj=dict(utc=pd.Timestamp.now(tz='UTC').isoformat(),stage=stage,peak_rss_bytes=rss(),**kw)
 with (OUT/'progress.jsonl').open('a') as f:f.write(json.dumps(obj,default=str)+'\n')
 print(json.dumps(obj,default=str),flush=True)
 assert rss()<LIMIT,'RSS exceeded 2 GiB'
def frozen():
 f=read(ACTIVE_FREEZE);assert f['previous_freeze_sha256']==sha(OUT/'FREEZE.json')
 assert f['execution_sha256']==sha(OUT/'EXECUTION.md')
 assert f['protocol_sha256']==sha(OUT/'PROTOCOL_RF2.md')
 for p,h in f['code_sha256'].items():assert sha(OUT/p)==h,('frozen code drift',p)
 assert sha(OUT/'INPUT_MANIFEST.json')==f['input_manifest_sha256']
 assert sha(OUT/'PREPARATION.json')==f['preparation_sha256']
 for group in ('feature_matrix_sha256','indices_sha256'):
  for p,h in f[group].items():assert sha(OUT/p)==h,('frozen prepared data drift',p)
 for p,h in f['design_sha256'].items():assert sha(OUT/f'{p}/design.json')==h,('frozen design drift',p)
def reference(fold):return forecast_replication/'aligned' if fold=='C' else label_availability/'resolved/main'
def reference_design(fold):return read(reference(fold)/'design.json')
def reference_prediction(fold):
 s=read(reference(fold)/'candidate_seal.json')['files'][fold];assert sha(s['path'])==s['sha256'];return Path(s['path'])
def metadata(period):return pd.read_parquet(B1B/f'{period}_metadata.parquet')
def ids_for(fold):
 if fold=='C':return np.arange(len(metadata('development')),dtype='int64'),np.arange(len(metadata('C')),dtype='int64')
 return np.load(label_availability/f'input_checks/train_indices_{fold}.npy'),np.load(label_availability/f'input_checks/test_indices_{fold}.npy')
def matrix_path(phase,period,arm):return OUT/f'blocks/{phase}/notices_{period}_{arm}.npy'
def prune(a,names,ids):
 kept=[];dropped={}
 for j,c in enumerate(names):
  k,v=rn.prune(a[ids,j].reshape(-1,1),[c]);kept+=k;dropped.update(v)
 return kept,dropped

def design(phase='final'):

 assert phase=='final'
 d=metadata('development');num=np.load(forecast_replication/'corrected_numeric.npy',mmap_mode='r');specs={}
 for fold in FOLDS:
  ref=reference_design(fold);r=ref['folds'][fold];ids,tids=ids_for(fold)
  nk,nd=prune(num,ref['numeric_names'],ids)
  assert nk==r['numeric_kept'] and nd==r['numeric_dropped']
  assert len(ids)==r['train_rows'] and len(tids)==r['test_rows']
  ev=metadata('C') if fold=='C' else d.iloc[tids]
  original=pd.read_parquet(reference_prediction(fold),columns=KEYS)
  assert ev[KEYS].reset_index(drop=True).equals(original)
  p=OUT/f'{phase}/indices/{fold}_train.npy';p.parent.mkdir(parents=True,exist_ok=True);assert not p.exists();np.save(p,ids)
  q=OUT/f'{phase}/indices/{fold}_test.npy';assert not q.exists();np.save(q,tids)
  spec=dict(train_rows=len(ids),test_rows=len(tids),q90=r['q90'],cutoff=r['cutoff'],numeric_kept=nk,numeric_dropped=nd,train_indices_path=str(p),train_indices_sha256=sha(p),test_indices_path=str(q),test_indices_sha256=sha(q),arms={})
  for arm in ['N',*ARMS]:
   bk=[];bd={}
   if arm!='N':
    a=np.load(matrix_path(phase,'development',arm),mmap_mode='r');bk,bd=prune(a,[arm+'_'+n for n in ref['notice_columns']],ids);del a
   names=nk+bk;match=names==r['arms'][arm]['features']
   if arm=='N':assert match,(phase,fold,arm,'feature order')
   spec['arms'][arm]=dict(features=names,notice_kept=bk,notice_dropped=bd,matches_reference_features=match)
  specs[fold]=spec;del ev,original
 params={str(s):rn.params(s) for s in SEEDS}
 for fold in FOLDS:assert params==reference_design(fold)['params_by_seed']
 write(f'{phase}/design.json',dict(phase=phase,folds=specs,numeric_names=ref['numeric_names'],notice_columns=ref['notice_columns'],numeric_path=str(forecast_replication/'corrected_numeric.npy'),numeric_C_path=str(forecast_replication/'numeric_C.npy'),params_by_seed=params,protocol_sha256=sha(OUT/'PROTOCOL_RF2.md')))
 log('design_complete',phase=phase)

def matrices(phase,fold,arm):
 des=read(OUT/f'{phase}/design.json');spec=des['folds'][fold];an=spec['arms'][arm];names=an['features']
 for k in ['train','test']:assert sha(spec[f'{k}_indices_path'])==spec[f'{k}_indices_sha256']
 ids=np.load(spec['train_indices_path']);tids=np.load(spec['test_indices_path']);d=metadata('development')
 target=d.y_true.to_numpy('float64')[ids]-d.legal_anchor.to_numpy('float64')[ids];weight=d.weight.to_numpy('float32')[ids]
 ev=metadata('C') if fold=='C' else d.iloc[tids].reset_index(drop=True)
 anchor=ev.legal_anchor.to_numpy('float64');caps=rn.price_cap(ev.target_time);predframe=ev[KEYS].copy();del d,ev;gc.collect()
 x=np.empty((len(ids),len(names)),dtype='float32');z=np.empty((len(tids),len(names)),dtype='float32')
 sources=[(Path(des['numeric_path']),Path(des['numeric_C_path']) if fold=='C' else Path(des['numeric_path']),des['numeric_names'],spec['numeric_kept'])]
 if arm!='N':sources.append((matrix_path(phase,'development',arm),matrix_path(phase,'C' if fold=='C' else 'development',arm),[arm+'_'+n for n in des['notice_columns']],an['notice_kept']))
 offset=0
 for trainp,testp,allnames,kept in sources:
  inds=[allnames.index(n) for n in kept];end=offset+len(inds);mat=np.load(trainp,mmap_mode='r')
  for st in range(0,len(ids),20000):x[st:st+20000,offset:end]=mat[np.ix_(ids[st:st+20000],inds)]
  del mat;mat=np.load(testp,mmap_mode='r')
  for st in range(0,len(tids),20000):z[st:st+20000,offset:end]=mat[np.ix_(tids[st:st+20000],inds)]
  del mat;offset=end
 assert offset==len(names);gc.collect()
 return x,z,target,weight,anchor,caps,predframe,names,spec

def verify_n(output_name='N_REUSE.json'):
 import lightgbm as lgb
 checks=[];des=read(OUT/'final/design.json');v3_inputs=read(V3/'INPUT_MANIFEST.json')['files'];input_files=read(OUT/'INPUT_MANIFEST.json')['files'];mismatches=[]
 identical_sources=[]
 for p in [forecast_replication/'corrected_numeric.npy',forecast_replication/'numeric_C.npy',B1B/'development_metadata.parquet',B1B/'C_metadata.parquet',*[label_availability/f'input_checks/{part}_indices_{fold}.npy' for fold in FOLDS if fold!='C' for part in ('train','test')]]:
  key=str(p);actual=sha(p);assert actual==input_files[key]['sha256'],('notice_fitting input drift',key)
  identical_sources.append(dict(path=key,sha256=actual,v3_identical=actual==v3_inputs[key]['sha256']))
 mismatches += [dict(type='source',path=x['path']) for x in identical_sources if not x['v3_identical']]
 for fold in FOLDS:
  x,z,y,w,anchor,caps,out,names,spec=matrices('final',fold,'N')
  assert np.array_equal(w,np.asarray(metadata('development').weight.to_numpy('float32')[np.load(spec['train_indices_path'])]))
  assert len(x)==spec['train_rows'] and len(z)==spec['test_rows']
  matrix_hashes=dict(train=hashlib.sha256(x.tobytes()).hexdigest(),test=hashlib.sha256(z.tobytes()).hexdigest(),target=hashlib.sha256(y.tobytes()).hexdigest(),weight=hashlib.sha256(w.tobytes()).hexdigest())
  del x,y,w;gc.collect()
  ref=reference_design(fold);assert names==ref['folds'][fold]['arms']['N']['features']
  assert spec['q90']==ref['folds'][fold]['q90'] and spec['cutoff']==ref['folds'][fold]['cutoff']
  seed_total=np.zeros(len(z),dtype='float64')
  ref_prediction_sha=sha(reference_prediction(fold))
  prediction_file_v3_equal=ref_prediction_sha==v3_inputs[str(reference_prediction(fold))]['sha256']
  if not prediction_file_v3_equal:mismatches.append(dict(type='prediction_file_hash_vs_v3',fold=fold,sha256=ref_prediction_sha))
  for seed in SEEDS:
   mp=reference(fold)/f'models/{fold}_N_s{seed}.txt';expected=read(OUT/'INPUT_MANIFEST.json')['files'][str(mp)]['sha256'];assert sha(mp)==expected
   model_v3_equal=expected==v3_inputs[str(mp)]['sha256']
   if not model_v3_equal:
    mismatches.append(dict(type='model_hash_vs_v3',fold=fold,seed=seed,sha256=expected))
   m=lgb.Booster(model_file=str(mp));model_features_equal=m.feature_name()==names
   if not model_features_equal:
    mismatches.append(dict(type='model_feature_order',fold=fold,seed=seed))
    checks.append(dict(fold=fold,seed=seed,exact_equal=False,model_sha256=sha(mp),model_v3_hash_equal=model_v3_equal,prediction_file_sha256=ref_prediction_sha,prediction_file_v3_hash_equal=prediction_file_v3_equal,features=names,model_features=m.feature_name(),train_indices_sha256=spec['train_indices_sha256'],test_indices_sha256=spec['test_indices_sha256'],matrix_sha256=matrix_hashes))
    continue
   pred=np.clip(anchor+m.predict(z,num_threads=rn.N_JOBS),-1000.,caps).astype('float32')
   col=f'N_s{seed}';refp=pd.read_parquet(reference_prediction(fold),columns=KEYS+[col]);keys_equal=out[KEYS].equals(refp[KEYS]);pred_equal=np.array_equal(pred,refp[col].to_numpy());seed_total+=pred
   if not keys_equal or not pred_equal:mismatches.append(dict(type='seed_prediction',fold=fold,seed=seed,keys_equal=keys_equal,prediction_equal=pred_equal))
   checks.append(dict(fold=fold,seed=seed,exact_equal=bool(keys_equal and pred_equal),model_sha256=sha(mp),model_v3_hash_equal=model_v3_equal,prediction_file_sha256=ref_prediction_sha,prediction_file_v3_hash_equal=prediction_file_v3_equal,features=names,train_indices_sha256=spec['train_indices_sha256'],test_indices_sha256=spec['test_indices_sha256'],matrix_sha256=matrix_hashes))
  ensemble=(seed_total/len(SEEDS)).astype('float32');baseline=pd.read_parquet(reference_prediction(fold),columns=['N']);ensemble_equal=np.array_equal(ensemble,baseline.N.to_numpy())
  if not ensemble_equal:mismatches.append(dict(type='ensemble_prediction',fold=fold))
  del z,out;gc.collect();log('N_replay_fold_complete',fold=fold)
 write(output_name,dict(passed=not mismatches,reuse=not mismatches,numeric_inputs_identical=all(x['v3_identical'] for x in identical_sources if x['path'].endswith(('.npy',)) and '/forecast_replication/' in x['path']),labels_and_weights_from_same_metadata=all(x['v3_identical'] for x in identical_sources if x['path'].endswith('_metadata.parquet')),train_masks_identical=all(x['v3_identical'] for x in identical_sources if '/input_checks/' in x['path']),params_identical=True,v3_source_identity=identical_sources,checks=checks,ensemble_exact_equal=not any(x['type']=='ensemble_prediction' for x in mismatches),mismatches=mismatches,seconds=time.monotonic()-START,peak_rss_bytes=rss()))

def verify_n_resume():
 path=OUT/'N_REUSE_RESUME.json'
 if not path.exists():verify_n(path.name)
 old=read(OUT/'N_REUSE.json');fresh=read(path)
 stable=lambda x:{k:v for k,v in x.items() if k not in ('seconds','peak_rss_bytes')}
 assert old['passed'] and fresh['passed'] and stable(old)==stable(fresh),'N replay changed on resume'
 if not (OUT/'N_REUSE_RESUME_VALIDATION.json').exists():
  write('N_REUSE_RESUME_VALIDATION.json',dict(passed=True,original_sha256=sha(OUT/'N_REUSE.json'),repeat_sha256=sha(path),exact_stable_result_equal=True,checks=len(fresh['checks'])))
 log('N_resume_replay_complete',checks=len(fresh['checks']))

def compare_rf_complete_matrix(current,indices,numeric_path,notice_path,all_numeric,kept_numeric,all_notice,kept_notice):

 numeric=np.load(numeric_path,mmap_mode='r');notice=np.load(notice_path,mmap_mode='r')
 ni=[all_numeric.index(name) for name in kept_numeric];ri=[all_notice.index(name) for name in kept_notice]
 digest=hashlib.sha256();current_digest=hashlib.sha256();differences=0
 assert current.shape==(len(indices),len(ni)+len(ri))
 for start in range(0,len(indices),8192):
  selected=indices[start:start+8192]
  block=np.empty((len(selected),current.shape[1]),dtype='float32')
  block[:,:len(ni)]=numeric[np.ix_(selected,ni)]
  block[:,len(ni):]=notice[np.ix_(selected,ri)]
  current_block=current[start:start+len(selected)]
  digest.update(memoryview(block).cast('B'))
  current_digest.update(memoryview(current_block).cast('B'))
  differences+=int(np.count_nonzero(block.view('uint32')!=current_block.view('uint32')))
 del numeric,notice;gc.collect()
 return dict(RF_sha256=digest.hexdigest(),RF2_sha256=current_digest.hexdigest(),different_cells=differences,bitwise_equal=differences==0)

def verify_r():
 import lightgbm as lgb
 manifest=read(OUT/'INPUT_MANIFEST.json')['files'];previous=read(RF/'final/design.json');current=read(OUT/'final/design.json')
 old_seal=read(RF/'final/candidate_seal.json');checks=[];mismatches=[];blocks={}
 old_freeze=read(RF/'FREEZE.json');old_inputs=read(RF/'INPUT_MANIFEST.json')['files'];old_outputs=read(RF/'OUTPUT_MANIFEST.json')['files']
 numeric_sources=[forecast_replication/'corrected_numeric.npy',forecast_replication/'numeric_C.npy']
 numeric_source_equal=all(sha(path)==old_inputs[str(path)]['sha256']==manifest[str(path)]['sha256'] for path in numeric_sources)
 if not numeric_source_equal:mismatches.append(dict(type='numeric_source_vs_RF'))
 for period in ('development','C'):
  new=matrix_path('final',period,'R');old=RF/f'blocks/final/notices_{period}_R.npy'
  a=np.load(new,mmap_mode='r');b=np.load(old,mmap_mode='r')
  equal=a.shape==b.shape and np.array_equal(a.view('uint32'),b.view('uint32'))
  cell_differences=int(np.count_nonzero(a.view('uint32')!=b.view('uint32'))) if a.shape==b.shape else None
  committed=old_freeze['feature_matrix_sha256'][f'blocks/final/notices_{period}_R.npy']
  blocks[period]=dict(rows=len(a),columns=a.shape[1],new_sha256=sha(new),RF_sha256=sha(old),RF_committed_sha256=committed,RF_commit_equal=sha(old)==committed==manifest[str(old)]['sha256']==old_outputs[f'blocks/final/notices_{period}_R.npy']['sha256'],sha256_equal=sha(new)==sha(old),bitwise_equal=bool(equal),different_cells=cell_differences)
  if not (equal and blocks[period]['sha256_equal'] and blocks[period]['RF_commit_equal']):mismatches.append(dict(type='full_R_feature_block',period=period))
  del a,b;gc.collect()
 if mismatches:
  write('R_REUSE.json',dict(passed=False,reuse=False,numeric_source_equal=numeric_source_equal,blocks=blocks,checks=checks,mismatches=mismatches,seconds=time.monotonic()-START,peak_rss_bytes=rss()))
  return
 assert read(RF/'N_REUSE.json')['passed'] and read(RF/'scoring/final/SCORE_VALIDATION.json')['passed']
 for fold in FOLDS:
  cur=current['folds'][fold];old=previous['folds'][fold]
  mask_equal=all(cur[f'{part}_indices_sha256']==old[f'{part}_indices_sha256'] for part in ('train','test'))
  feature_equal=cur['arms']['R']['features']==old['arms']['R']['features']
  pruning_equal=cur['arms']['R']['notice_kept']==old['arms']['R']['notice_kept'] and cur['arms']['R']['notice_dropped']==old['arms']['R']['notice_dropped']
  numeric_equal=cur['numeric_kept']==old['numeric_kept'] and cur['numeric_dropped']==old['numeric_dropped']
  design_equal=mask_equal and feature_equal and pruning_equal and numeric_equal and cur['q90']==old['q90'] and cur['cutoff']==old['cutoff'] and current['params_by_seed']==previous['params_by_seed']
  if not design_equal:
   mismatches.append(dict(type='R_design',fold=fold,mask_equal=mask_equal,feature_equal=feature_equal,pruning_equal=pruning_equal,numeric_equal=numeric_equal))
   continue
  x,z,y,w,anchor,caps,keys,names,spec=matrices('final',fold,'R')
  matrix_hashes=dict(target=hashlib.sha256(y.tobytes()).hexdigest(),weight=hashlib.sha256(w.tobytes()).hexdigest())
  old_notice_names=['R_'+name for name in previous['notice_columns']]
  for part in ('train','test'):
   assert sha(old[f'{part}_indices_path'])==old[f'{part}_indices_sha256']
  old_train=np.load(old['train_indices_path']);old_test=np.load(old['test_indices_path'])
  complete_matrix={}
  for part,values,ids in (('train',x,old_train),('test',z,old_test)):
   assert np.array_equal(ids,np.load(cur[f'{part}_indices_path']))
   numeric_path=forecast_replication/('numeric_C.npy' if fold=='C' and part=='test' else 'corrected_numeric.npy')
   notice_path=RF/f"blocks/final/notices_{'C' if fold=='C' and part=='test' else 'development'}_R.npy"
   check=compare_rf_complete_matrix(values,ids,numeric_path,notice_path,previous['numeric_names'],old['numeric_kept'],old_notice_names,old['arms']['R']['notice_kept'])
   matrix_hashes[part]=check['RF2_sha256']
   check['sha256_equal']=check['RF_sha256']==check['RF2_sha256']
   complete_matrix[part]=check
   if not (check['bitwise_equal'] and check['sha256_equal']):mismatches.append(dict(type='R_complete_matrix',fold=fold,part=part,check=check))
  old_n=next(q for q in read(RF/'N_REUSE.json')['checks'] if q['fold']==fold)
  labels_weights_equal=matrix_hashes['target']==old_n['matrix_sha256']['target'] and matrix_hashes['weight']==old_n['matrix_sha256']['weight']
  if not labels_weights_equal:mismatches.append(dict(type='labels_or_weights',fold=fold))
  del x,y,w;gc.collect()
  source=RF/f'final/predictions/{fold}.parquet'
  source_hash=sha(source);seal_hash=old_seal['files'][fold]['sha256']
  if source_hash!=seal_hash or source_hash!=old_outputs[f'final/predictions/{fold}.parquet']['sha256']:
   mismatches.append(dict(type='RF_ensemble_file_hash',fold=fold))
  oldframe=pd.read_parquet(source,columns=KEYS+[f'R_s{s}' for s in SEEDS]+['R'])
  key_equal=keys[KEYS].equals(oldframe[KEYS])
  if not key_equal:mismatches.append(dict(type='R_prediction_keys',fold=fold))
  total=np.zeros(len(z),dtype='float64')
  for seed in SEEDS:
   mpath=RF/f'final/models/{fold}_R_s{seed}.txt';ppath=RF/f'final/predictions/{fold}_R_s{seed}.parquet';receipt=read(RF/f'receipts/final_{fold}_R_{seed}.json')
   model_hash_equal=sha(mpath)==receipt['model_sha256']==manifest[str(mpath)]['sha256']==old_outputs[f'final/models/{fold}_R_s{seed}.txt']['sha256']
   prediction_hash_equal=sha(ppath)==receipt['prediction_sha256']==manifest[str(ppath)]['sha256']==old_outputs[f'final/predictions/{fold}_R_s{seed}.parquet']['sha256']
   model=lgb.Booster(model_file=str(mpath));order_equal=model.feature_name()==names
   if order_equal:
    prediction=np.clip(anchor+model.predict(z,num_threads=rn.N_JOBS),-1000.,caps).astype('float32')
    part=pd.read_parquet(ppath,columns=KEYS+[f'R_s{seed}'])
    exact=part[KEYS].equals(keys[KEYS]) and np.array_equal(prediction,part[f'R_s{seed}'].to_numpy()) and np.array_equal(prediction,oldframe[f'R_s{seed}'].to_numpy())
    total+=prediction
   else:exact=False
   if not (model_hash_equal and prediction_hash_equal and order_equal and exact):
    mismatches.append(dict(type='R_seed_replay',fold=fold,seed=seed,model_hash_equal=model_hash_equal,prediction_hash_equal=prediction_hash_equal,feature_order_equal=order_equal,exact_prediction_equal=exact))
   checks.append(dict(fold=fold,seed=seed,model_sha256=sha(mpath),prediction_sha256=sha(ppath),model_hash_equal=model_hash_equal,prediction_hash_equal=prediction_hash_equal,feature_order_equal=order_equal,exact_prediction_equal=exact,train_indices_sha256=cur['train_indices_sha256'],test_indices_sha256=cur['test_indices_sha256'],labels_weights_equal=labels_weights_equal,full_train_test_matrix_sha256=matrix_hashes,complete_RF_matrix_check=complete_matrix))
   del model;gc.collect()
  ensemble=(total/len(SEEDS)).astype('float32')
  if not np.array_equal(ensemble,oldframe['R'].to_numpy()):mismatches.append(dict(type='R_ensemble_replay',fold=fold))
  del z,oldframe,keys;gc.collect();log('R_replay_fold_complete',fold=fold)
 write('R_REUSE.json',dict(passed=not mismatches,reuse=not mismatches,numeric_source_equal=numeric_source_equal,blocks=blocks,checks=checks,mismatches=mismatches,RF_freeze_sha256=sha(RF/'FREEZE.json'),RF_candidate_seal_sha256=sha(RF/'final/candidate_seal.json'),seconds=time.monotonic()-START,peak_rss_bytes=rss()))

def reuse_r():
 assert read(OUT/'R_REUSE.json')['reuse']
 for fold in FOLDS:
  for seed in SEEDS:
   old=read(RF/f'receipts/final_{fold}_R_{seed}.json')
   model_source=RF/f'final/models/{fold}_R_s{seed}.txt';prediction_source=RF/f'final/predictions/{fold}_R_s{seed}.parquet'
   model_dest=OUT/f'final/models/{fold}_R_s{seed}.txt';prediction_dest=OUT/f'final/predictions/{fold}_R_s{seed}.parquet'
   model_dest.parent.mkdir(parents=True,exist_ok=True);prediction_dest.parent.mkdir(parents=True,exist_ok=True)
   if not model_dest.exists():shutil.copyfile(model_source,model_dest)
   if not prediction_dest.exists():shutil.copyfile(prediction_source,prediction_dest)
   assert sha(model_dest)==old['model_sha256'] and sha(prediction_dest)==old['prediction_sha256']
   receipt=f'receipts/final_{fold}_R_{seed}.json'
   if not (OUT/receipt).exists():
    write(receipt,dict(phase='final',fold=fold,arm='R',seed=seed,reused=True,source='RF',model_sha256=old['model_sha256'],prediction_sha256=old['prediction_sha256'],source_receipt_sha256=sha(RF/f'receipts/final_{fold}_R_{seed}.json'),design_sha256=sha(OUT/'final/design.json'),freeze_sha256=sha(ACTIVE_FREEZE),fit_predict_save_seconds=0,seconds=0,peak_rss_bytes=rss()))
   else:
    existing=read(OUT/receipt)
    assert existing['reused'] and existing['model_sha256']==old['model_sha256'] and existing['prediction_sha256']==old['prediction_sha256']
 log('R_copy_complete',models=21,predictions=21)

def fit(phase,fold,arm,seed):
 import lightgbm as lgb
 assert phase=='final' and arm in ('N',*ARMS) and fold in FOLDS and seed in SEEDS
 reuse=read(OUT/'N_REUSE.json')['reuse']
 assert arm!='N' or not reuse
 des=read(OUT/f'{phase}/design.json');x,z,y,weight,anchor,caps,predframe,names,spec=matrices(phase,fold,arm)
 assert rn.params(seed)==des['params_by_seed'][str(seed)]
 log('fit_start',phase=phase,fold=fold,arm=arm,seed=seed,train_shape=x.shape,test_shape=z.shape)
 t=time.monotonic();model=lgb.LGBMRegressor(**rn.params(seed)).fit(x,y,sample_weight=weight,feature_name=names)
 mp=OUT/f'{phase}/models/{fold}_{arm}_s{seed}.txt';mp.parent.mkdir(parents=True,exist_ok=True);assert not mp.exists();model.booster_.save_model(str(mp))
 pred=np.clip(anchor+model.booster_.predict(z,num_threads=rn.N_JOBS),-1000.,caps).astype('float32');assert np.isfinite(pred).all()
 col=f'{arm}_s{seed}';predframe[col]=pred;pp=OUT/f'{phase}/predictions/{fold}_{arm}_s{seed}.parquet';pp.parent.mkdir(parents=True,exist_ok=True);assert not pp.exists();predframe.to_parquet(pp,index=False)
 rec=dict(phase=phase,fold=fold,arm=arm,seed=seed,train_rows=len(x),test_rows=len(z),features=len(names),train_indices_sha256=spec['train_indices_sha256'],design_sha256=sha(OUT/f'{phase}/design.json'),model_sha256=sha(mp),prediction_sha256=sha(pp),peak_rss_bytes=rss(),fit_predict_save_seconds=time.monotonic()-t,seconds=time.monotonic()-START,lightgbm_version=lgb.__version__,numpy_version=np.__version__,pandas_version=pd.__version__,freeze_sha256=sha(ACTIVE_FREEZE),pilot=(fold=='F1' and arm=='L' and seed==SEEDS[0]))
 write(f'receipts/{phase}_{fold}_{arm}_{seed}.json',rec);log('fit_complete',phase=phase,fold=fold,arm=arm,seed=seed,seconds=rec['seconds'])

def seal(phase='final'):
 assert phase=='final'
 des=read(OUT/f'{phase}/design.json');files={};checks=[];seedchecks=[]
 reuse=read(OUT/'N_REUSE.json')['reuse']
 for fold in FOLDS:
  refpath=reference_prediction(fold);out=pd.read_parquet(refpath,columns=KEYS+[f'N_s{s}' for s in SEEDS]+['N'] if reuse else KEYS)
  if not reuse:
   total=np.zeros(len(out),dtype='float64')
   for seed in SEEDS:
    rec=read(OUT/f'receipts/{phase}_{fold}_N_{seed}.json');p=OUT/f'{phase}/predictions/{fold}_N_s{seed}.parquet';assert sha(p)==rec['prediction_sha256'];assert sha(OUT/f'{phase}/models/{fold}_N_s{seed}.txt')==rec['model_sha256']
    part=pd.read_parquet(p);col=f'N_s{seed}';assert out[KEYS].equals(part[KEYS]);out[col]=part[col].to_numpy();total+=part[col].to_numpy()
   out['N']=(total/len(SEEDS)).astype('float32')
  for arm in ARMS:
   total=np.zeros(len(out),dtype='float64')
   for seed in SEEDS:
    rec=read(OUT/f'receipts/{phase}_{fold}_{arm}_{seed}.json');p=OUT/f'{phase}/predictions/{fold}_{arm}_s{seed}.parquet';assert sha(p)==rec['prediction_sha256'];assert sha(OUT/f'{phase}/models/{fold}_{arm}_s{seed}.txt')==rec['model_sha256']
    part=pd.read_parquet(p);col=f'{arm}_s{seed}';assert out[KEYS].equals(part[KEYS]);out[col]=part[col].to_numpy();total+=part[col].to_numpy()
   out[arm]=(total/3).astype('float32')
  p=OUT/f'{phase}/predictions/{fold}.parquet';assert not p.exists();out.to_parquet(p,index=False);files[fold]=dict(path=str(p),sha256=sha(p),rows=len(out),q90=des['folds'][fold]['q90'])
 write(f'{phase}/candidate_seal.json',dict(state='RF2_FINAL3_SEALED',files=files,protocol_sha256=sha(OUT/'PROTOCOL_RF2.md'),design_sha256=sha(OUT/f'{phase}/design.json'),freeze_sha256=sha(ACTIVE_FREEZE),test_scored_before_bank_seal=False,created_utc=pd.Timestamp.now(tz='UTC').isoformat()))
 log('seal_complete',phase=phase)

def subprocess_stage(args,logname):
 p=OUT/'logs'/logname;p.parent.mkdir(exist_ok=True);peak=0;t=time.monotonic()
 if p.exists() or (OUT/f'resource/{p.name}.json').exists():
  p=p.with_name(f'{p.stem}_retry_{time.time_ns()}{p.suffix}')
 with p.open('x') as f:
  child=subprocess.Popen([sys.executable,'-B',str(Path(__file__)),*args],stdout=f,stderr=subprocess.STDOUT);proc=psutil.Process(child.pid)
  while child.poll() is None:
   try:
    combined=proc.memory_info().rss+psutil.Process().memory_info().rss;peak=max(peak,combined)
    if combined>LIMIT:child.terminate();child.wait();raise MemoryError('Parent + fit RSS exceeded 2 GiB')
   except psutil.NoSuchProcess:pass
   time.sleep(.5)
  rc=child.returncode
 write(f'resource/{p.name}.json',dict(args=args,returncode=rc,peak_parent_plus_child_rss_bytes=peak,seconds=time.monotonic()-t))
 if rc:raise RuntimeError(f'Stage failed {args}; see {p}')

def pipeline():
 lock=OUT/'.fit.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
 try:
  if not (OUT/'N_REUSE.json').exists():subprocess_stage(['verify_n'],'N_replay.log')
  if not (OUT/'N_REUSE_RESUME_VALIDATION.json').exists():subprocess_stage(['verify_n_resume'],'N_replay_resume.log')
  assert read(OUT/'N_REUSE_RESUME_VALIDATION.json')['passed']
  if not (OUT/'R_REUSE.json').exists():subprocess_stage(['verify_r'],'R_replay.log')
  r_reuse=read(OUT/'R_REUSE.json')['reuse']
  if r_reuse and any(not (OUT/f'receipts/final_{fold}_R_{seed}.json').exists() or not (OUT/f'final/models/{fold}_R_s{seed}.txt').exists() or not (OUT/f'final/predictions/{fold}_R_s{seed}.parquet').exists() for fold in FOLDS for seed in SEEDS):
   copy_log='R_copy.log' if not (OUT/'logs/R_copy.log').exists() else f'R_copy_retry_{time.time_ns()}.log'
   subprocess_stage(['reuse_r'],copy_log)
  phase='final'
  first=OUT/f'receipts/{phase}_F1_L_{SEEDS[0]}.json'
  if not first.exists():subprocess_stage(['fit',phase,'F1','L',str(SEEDS[0])],f'{phase}_F1_L_{SEEDS[0]}.log')
  assert read(first)['pilot']
  if not read(OUT/'N_REUSE.json')['reuse']:
   for nfold in FOLDS:
    for nseed in SEEDS:
     nrp=OUT/f'receipts/{phase}_{nfold}_N_{nseed}.json'
     if not nrp.exists():subprocess_stage(['fit',phase,nfold,'N',str(nseed)],f'{phase}_{nfold}_N_{nseed}.log')
  fitted=1
  for fold in FOLDS:
   for arm in (('L','P') if r_reuse else ('L','P','R')):
    for seed in SEEDS:
     rp=OUT/f'receipts/{phase}_{fold}_{arm}_{seed}.json'
     if rp.exists():
      rec=read(rp);assert sha(OUT/f'{phase}/models/{fold}_{arm}_s{seed}.txt')==rec['model_sha256'];assert sha(OUT/f'{phase}/predictions/{fold}_{arm}_s{seed}.parquet')==rec['prediction_sha256']
     else:subprocess_stage(['fit',phase,fold,arm,str(seed)],f'{phase}_{fold}_{arm}_{seed}.log')
     if not (fold=='F1' and arm=='L' and seed==SEEDS[0]):fitted+=1
     total=42 if r_reuse else 63
     (OUT/'PROGRESS.md').write_text(f'# notice_fitting progress\n\n{pd.Timestamp.now(tz="UTC").isoformat()}\n\n{phase} {fold} {arm}: completed fits {fitted}/{total}. One fit at a time; frozen protocol unchanged.\n')
     log('pipeline_progress',phase=phase,completed_fits=fitted,total_fits=total)
  if not (OUT/f'{phase}/candidate_seal.json').exists():subprocess_stage(['seal',phase],f'{phase}_seal.log')
  log('pipeline_complete',completed_fits=fitted,reused_R_models=21 if r_reuse else 0)
 finally:lock.unlink()

if __name__=='__main__':
 stage=sys.argv[1]
 if stage!='design':frozen()
 try:
  if stage=='fit':fit(sys.argv[2],sys.argv[3],sys.argv[4],int(sys.argv[5]))
  elif stage in ('design','seal'):globals()[stage](*sys.argv[2:])
  else:globals()[stage]()
 except Exception as exc:
  write(f'failures/{time.time_ns()}_{stage}.json',dict(error=repr(exc),argv=sys.argv));raise
