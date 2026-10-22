"""D prediction-time notice-clock delays through sealed models, never fitting."""
from pathlib import Path
import argparse
import copy
import numpy as np
import pandas as pd
from a8_common import *

DELAYS = (5,15,60)

def peak_check():
    import resource
    import sys
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    value = int(value if sys.platform == 'darwin' else value*1024)
    if value >= 2*1024**3:
        raise ResourceStop('DLY8 process reached the 2 GiB peak RSS limit')
    return value

def shifted_notices(notices,delta):
    require(delta in (0,*DELAYS), 'Unregistered DLY8 delay')
    out = []
    for source in notices:
        row = dict(source)
        stamp = pd.Timestamp(row['available_utc'])
        row['available_utc'] = stamp+pd.Timedelta(minutes=delta) if stamp >= pd.Timestamp('2026-07-27T00:00',tz='Australia/Brisbane') else stamp
        # Event dates, creation/anchor clocks and label contents remain fixed.
        out.append(row)
    return sorted(out,key=lambda r:(pd.Timestamp(r['available_utc']),str(r['notice_id'])))

def predict_notice(model,x,panel,params,cap):
    require(x.dtype == np.float32, 'DLY8 float32 input required')
    residual = np.asarray(model.predict(x,num_threads=params['n_jobs']),dtype='float64')
    raw = residual + panel.anchor.to_numpy(dtype='float64')
    lower,upper = np.full(len(panel),-1000.),cap(panel.target_time)
    result = panel[KEYS+['target_day']].copy()
    result['raw_prediction'],result['lower_bound'],result['upper_bound'] = raw,lower,upper
    result['prediction'] = np.clip(raw,lower,upper).astype('float32')
    require(np.isfinite(result.prediction.to_numpy()).all(), 'Nonfinite DLY8 prediction')
    return normalize(result)

def parity_frame(rebuilt,sealed):
    a,b = normalize(rebuilt),normalize(sealed)
    require(a[KEYS+['target_day']].equals(b[KEYS+['target_day']]), 'DLY8 delta=0 key parity failed')
    require(list(a.columns) == list(b.columns), 'DLY8 delta=0 prediction schema parity failed')
    for col in ('prediction','raw_prediction','lower_bound','upper_bound'):
        require(col in a and bytes_equal(a[col].to_numpy(),b[col].to_numpy()), 'DLY8 delta=0 prediction byte parity failed: '+col)
    return True

def run_delays(root,arms,rebuild,predict,reference,expected_features,binding,rebuild_all=None):
    """Rebuild each Δ once for all arms, with all zero checks before delays."""
    import time
    started = time.monotonic()
    root = Path(root)
    root.mkdir(parents=True,exist_ok=True)
    receipt_path = root/'DLY8_RECEIPT.json'
    if receipt_path.exists():
        old = read_json(receipt_path)
        require(old['binding'] == binding,'DLY8 resume seal/model binding drift')
        if old['state'] != 'ALL_DLY8_PREDICTIONS_SEALED':
            return old
        require(old['arms'] == list(arms),'DLY8 resume arm drift')
        for item in [old['parity'],*old['predictions']]:
            checked(item)
        return old
    attempt = root/'attempts'/__import__('uuid').uuid4().hex
    attempt.mkdir(parents=True)
    def matrices(delta):
        if rebuild_all is not None:
            return rebuild_all(delta,attempt/('delta'+str(delta)))
        return {a:rebuild(delta,a,attempt/('delta'+str(delta)+'__'+a)) for a in arms}
    def close(actual):
        if isinstance(actual,np.memmap) and not actual._mmap.closed:
            actual.flush(); actual._mmap.close()
    reports = []
    zero = matrices(0)
    try:
        for arm in arms:
            actual = zero[arm]
            digest = __import__('hashlib').sha256()
            for start in range(0,len(actual),2048):
                ids = slice(start,start+2048)
                if not bytes_equal(actual[ids],expected_features(arm,ids)):
                    raise ParityFailure('DLY8 delta=0 feature byte parity failed: '+arm)
                digest.update(actual[ids].tobytes())
            try:
                parity_frame(predict(arm,actual),reference(arm))
            except RuntimeError as exc:
                raise ParityFailure(str(exc)) from exc
            reports.append(dict(arm=arm,state='PASS',features_byte_equal=True,predictions_byte_equal=True,
                                feature_bytes_sha256=digest.hexdigest()))
            close(actual)
            peak_check()
    finally:
        for actual in zero.values():
            close(actual)
    parity = attempt/'PARITY_DELTA0.json'
    write_json(parity,dict(state='PASS',binding=binding,checks=reports,delta_minutes=0),exclusive=True)
    outputs = []
    for delta in DELAYS:
        values = matrices(delta)
        try:
            for arm in arms:
                actual = values[arm]
                if arm == 'N':
                    for start in range(0,len(actual),2048):
                        ids = slice(start,start+2048)
                        if not bytes_equal(actual[ids],expected_features(arm,ids)):
                            raise ParityFailure('DLY8 delayed N feature byte parity failed')
                    frame = normalize(reference(arm))  # sealed N is reused at every Δ
                    parity_frame(frame,reference(arm))
                else:
                    frame = normalize(predict(arm,actual))
                path = attempt/('notice__'+arm+'__delay'+str(delta)+'.parquet')
                frame.to_parquet(path,index=False)
                outputs.append(identity(path,source='notice',arm=arm,seed=SEED,variant='delay'+str(delta),
                                        rows=len(frame),delta_minutes=delta))
                close(actual)
                peak_check()
        finally:
            for actual in values.values():
                close(actual)
    result = dict(state='ALL_DLY8_PREDICTIONS_SEALED',binding=binding,arms=list(arms),parity=identity(parity),
                  predictions=outputs,models_refitted=0,training_rows_changed=False,delays_minutes=list(DELAYS),
                  delta0_first=True,outcomes_read=False,wall_seconds=time.monotonic()-started,
                  peak_rss_bytes=peak_check(),N_delayed_features_checked='N' in arms,N_sealed_predictions_reused='N' in arms)
    write_json(receipt_path,result,exclusive=True)
    return result

def model_bank(seal,arms):
    result = {}
    models = {str(Path(i['path']).resolve()):i for i in seal['fit_receipts_and_models'] if i.get('kind') == 'LightGBM_model'}
    for item in seal['fit_receipts_and_models']:
        if item.get('kind') != 'fit_receipt':
            continue
        rec = read_json(checked(item))
        task = rec['task']
        if (task['task'],task['seed'],task['variant']) != ('notice',SEED,'main') or task['arm'] not in arms:
            continue
        require(task['arm'] not in result and rec['state'] == 'COMPLETE', 'DLY8 missing/duplicate/unfinished model')
        model = models.get(str(Path(rec['model_path']).resolve()))
        require(model and model['sha256'] == rec['model_sha256'], 'DLY8 model not named by seal')
        checked(model)
        result[task['arm']] = dict(rec,model_identity=model,receipt_identity=item)
    require(set(result) == set(arms), 'DLY8 sealed seed-20260919 model census incomplete')
    return result

def d_panel(bundle,A):
    """Column-batched D keys/numerical inputs/anchor only; no y."""
    import pyarrow.parquet as pq
    shared = bundle.get('shared_columns',[])
    cols = KEYS+['target_day','anchor']  # numeric rows are loaded in bounded chunks from the frozen bundle
    require('y' not in cols, 'D outcome in DLY8 input schema')
    pieces,indices,offset = [],[],0
    for block in pq.ParquetFile(bundle['panel_path']).iter_batches(columns=cols,batch_size=10000):
        f = block.to_pandas()
        mask = f.target_day.astype(str).between('2026-08-01','2026-09-30').to_numpy()
        if mask.any():
            pieces.append(f.loc[mask])
            indices.extend(offset+np.flatnonzero(mask))
        offset += len(f)
    require(pieces, 'Missing notice D input grid')
    panel = pd.concat(pieces,ignore_index=True)
    require(not panel.duplicated(KEYS).any() and len(panel) == 61*8640, 'DLY8 full notice D grid required')
    return panel,np.asarray(indices,dtype='int64')

def rebuild_features(panel,notices,delta,arms,bundles,A,permit,root,binding,metadata_records=None,encoder=None,cache_directory=None,production_rows=None):
    """One installed projection over the entire D panel per Δ; all arms share it."""
    root = Path(root)
    root.mkdir(parents=True,exist_ok=True)
    shifted = shifted_notices(notices,delta)
    f = A.features
    cache_directory = Path(cache_directory) if cache_directory is not None else root/'embedding_cache'
    cache_directory.mkdir(parents=True,exist_ok=True)
    planned = sum(len(panel)*len(bundles[a]['columns'])*4 for a in arms)+len(panel)*80
    A.storage.require_disk_space(root,planned,3*1024**3,'DLY8 all arms/delay retained arrays and predictions')
    encoder = encoder or f.build_encoder(permit=permit,cache_directory=cache_directory)
    final3,corrected = f.load_final3(permit=permit),f.load_corrected_rule(permit=permit)
    outputs = {a:np.lib.format.open_memmap(root/(a+'.npy'),mode='w+',dtype='float32',
                                         shape=(len(panel),len(bundles[a]['columns']))) for a in arms}
    # Five primary arms / six R8 arms need no donor history and no word vocabulary.
    base_map = {'M0_n':'M_notice','M+0_n':'M_notice','M+_n':'M_notice','L14+':'L14',
                'L_Laz+':'L_Laz','L_chen_notice+':'L_chen_notice'}
    new_names = None
    new_values = None
    if metadata_records is not None:
        import r8_activity as r8
        records = [dict(r,available=r['available']+pd.Timedelta(minutes=delta) if r['available'] >= pd.Timestamp('2026-07-27T00:00',tz='Australia/Brisbane') else r['available']) for r in metadata_records]
        contract = copy.deepcopy(binding['metadata'])
        contract['coverage']['notice'] = [[(pd.Timestamp(a)+pd.Timedelta(minutes=delta)).isoformat(),
                                          (pd.Timestamp(b)+pd.Timedelta(minutes=delta)).isoformat()]
                                         for a,b in contract['coverage']['notice']]
        new_values,new_names = r8.metadata_matrix(panel,records,'notice',contract,types=binding['training_type_ids'])
    # Numerical inputs are delay-invariant. Copy once in bounded blocks, avoiding
    # re-opening the shared bank for every origin and every numeric column.
    projected_columns = {}
    for arm in arms:
        columns = bundles[arm]['columns']
        numerical = [c for c in columns if c in bundles[arm].get('shared_columns',binding.get('numeric_columns',[])) and c not in panel.columns]
        fixed = [c for c in columns if c in panel.columns]
        if numerical:
            require(production_rows is not None,'DLY8 numeric frozen row mapping absent')
        projected_columns[arm] = [(j,c) for j,c in enumerate(columns) if c not in numerical and c not in fixed]
        for start in range(0,len(panel),4096):
            stop = min(len(panel),start+4096)
            if numerical:
                block = A.storage.load_feature_rows(bundles[arm],production_rows[start:stop],columns=numerical)
                outputs[arm][start:stop,[columns.index(c) for c in numerical]] = block
            if fixed:
                outputs[arm][start:stop,[columns.index(c) for c in fixed]] = panel.iloc[start:stop][fixed].to_numpy(dtype='float32')
            f._evict(outputs[arm])
    seen = np.zeros(len(panel),dtype=bool)
    rows_since_evict = 0
    for indices,extras,_coverage in f.notice_feature_rows(panel,shifted,permit=permit,encoder=encoder,
                cache_directory=cache_directory,final3=final3,corrected_rule=corrected,
                vocabulary={'title':[],'body':[]},stopwords=set()):
        require(not seen[indices].any(), 'DLY8 duplicate projection rows')
        seen[indices] = True
        for arm in arms:
            extra = extras[(base_map.get(arm,arm),'main')]
            values = []
            positions = []
            for j,col in projected_columns[arm]:
                if col in extra:
                    value = np.broadcast_to(np.asarray(extra[col],dtype='float32'),len(indices))
                elif new_names is not None and col in new_names:
                    value = new_values[indices,new_names.index(col)]
                else:
                    raise RuntimeError('DLY8 frozen column absent: '+col)
                values.append(value); positions.append(j)
            if values:
                outputs[arm][np.ix_(indices,positions)] = np.column_stack(values)
        rows_since_evict += len(indices)
        if rows_since_evict >= 4096:
            for matrix in outputs.values():
                f._evict(matrix)
            rows_since_evict = 0
            peak_check()
    require(seen.all(), 'DLY8 incomplete feature projection')
    for x in outputs.values():
        x.flush()
    return outputs

def _host_mode(mode,context=None):
    from runner import host_context
    A,state,code,binding,main_seal_path,main_seal,main_manifest_path,permit = context or host_context()
    require(mode in (1,2), 'DLY8 mode must be 1 (primary) or 2 (R8)')
    if mode == 1:
        seal_path,seal,manifest_path = main_seal_path,main_seal,main_manifest_path
        arms = PRIMARY_NOTICE
    else:
        from batch_export import verify_seal
        seal_path = state/'SEAL_A8BATCH.json'
        seal = verify_seal(state)
        manifest_path = state/'features/manifest.json'
        arms = R8_NOTICE
        row = next(r for r in seal['stage_dispositions'] if r['stage'] == 'R8_notice')
        if row['state'] not in COMPLETE:
            result = dict(state='NOT_RUN_R8_UNAVAILABLE',binding=dict(main_conf_seal=identity(main_seal_path),source_seal=identity(seal_path)),predictions=[],parity=None,reason=row.get('reason'),models_refitted=0)
            write_json(dly_root(state)/'mode2/DLY8_RECEIPT.json',result,exclusive=True)
            write_json(dly_root(state)/'DLY8_SEAL_R8.json',dict(state=result['state'],receipt=identity(dly_root(state)/'mode2/DLY8_RECEIPT.json'),conf_seal_sha256=sha(main_seal_path),source_seal=identity(seal_path),adapter_freeze_sha256=code['adapter_freeze_sha256']),exclusive=True)
            return result
    manifest = read_json(manifest_path)
    bundles = {a:next(b for b in manifest['bundles'] if (b['source'],b['arm'],b.get('variant','main')) == ('notice',a,'main')) for a in arms}
    for b in bundles.values():
        A.storage.verify_bundle(b)
        require(sha(b['panel_path']) == b['panel_sha256'], 'DLY8 panel drift')
    # Primary N supplies the unpruned numeric column schema for R8 mode as well.
    numeric = next(b for b in read_json(main_manifest_path)['bundles'] if (b['source'],b['arm'],b.get('variant','main')) == ('notice','N','main'))
    panel,production_rows = d_panel(numeric,A)
    models = model_bank(seal,arms)
    refs = {}
    for arm in arms:
        require(models[arm]['task']['origin'] == 'prewindow_frozen_C_bank', 'DLY8 notice training schedule drift')
        matches = [i for i in seal['predictions'] if (i['source'],i['arm'],i['seed'],i['variant']) == ('notice',arm,SEED,'main')]
        require(len(matches) == 1, 'DLY8 sealed prediction census incomplete')
        refs[arm] = matches[0]
    bound = dict(mode=mode,main_conf_seal=identity(main_seal_path),source_seal=identity(seal_path),
                 code_freeze=identity(OUT/'CODE_FREEZE.json'),models=[r['model_identity'] for r in models.values()])
    notices = A.features.load_host_notices(Q/'NRX/results_1_3',permit=permit)
    from dly8_cache import notice_census,copy_production_cache,CacheOnlyEncoder
    census = notice_census(notices)
    metadata_records = None
    local_binding = dict(binding)
    if mode == 2:
        import r8_activity as r8
        metadata_records = r8.read_notices(binding['metadata']['notice_scope'],binding['metadata']['notice_type_map'])
        local_binding['training_type_ids'] = manifest['notice_type_coverage']['training_type_ids']
    cache = OUT/'dly8/embedding_cache'
    cache_receipt = copy_production_cache(main_manifest_path.parent/'embedding_cache',cache)
    bound.update(cache_input=identity(cache_receipt),notice_census=census)
    from dly8_cache import LockedMissingEncoder
    encoder = LockedMissingEncoder(A,permit,cache)  # only missing prefixes; unchanged locked encoder
    local_binding['numeric_columns'] = numeric.get('shared_columns',numeric['columns'])
    def rebuild_all(delta,root):
        from runner import active_fit_jobs
        if active_fit_jobs():
            raise OverlapRefusal('DLY8 must not overlap an independent fit')
        return rebuild_features(panel,notices,delta,arms,bundles,A,permit,root,local_binding,metadata_records,encoder,cache,production_rows)
    def predict(arm,x):
        import lightgbm as lgb
        rec = models[arm]
        model = lgb.Booster(model_file=str(checked(rec['model_identity'])))
        require(model.feature_name() == bundles[arm]['columns'] == rec['feature_order'], 'DLY8 sealed feature order drift')
        # Preserve installed prediction batching (one batch for this pooled fit).
        return predict_notice(model,x,panel,rec['params'],A.execution.price_cap)
    result = run_delays(dly_root(state)/('mode'+str(mode)),arms,None,predict,
                      lambda a:pd.read_parquet(checked(refs[a])),
                      lambda a,ids:A.storage.load_feature_rows(bundles[a],production_rows[ids]),bound,rebuild_all=rebuild_all)
    seal_name = 'DLY8_SEAL_PRIMARY.json' if mode == 1 else 'DLY8_SEAL_R8.json'
    destination = dly_root(state)/seal_name
    if destination.exists():
        prior = read_json(destination)
        require(prior['conf_seal_sha256'] == sha(main_seal_path) and prior['source_seal'] == identity(seal_path) and
                prior['adapter_freeze_sha256'] == code['adapter_freeze_sha256'], 'DLY8 seal identity drift on resume')
        checked(prior['receipt'])
        return result
    write_json(destination,dict(state='DLY8_SEALED_BEFORE_SCORING',receipt=identity(dly_root(state)/('mode'+str(mode))/'DLY8_RECEIPT.json'),
               conf_seal_sha256=sha(main_seal_path),source_seal=identity(seal_path),adapter_freeze_sha256=code['adapter_freeze_sha256'],
               peak_rss_bytes=peak_check(),models_refitted=0),exclusive=True)
    return result

def dly_root(state):
    state = Path(state)
    return OUT/'dly8' if state.resolve() == (OUT/'state').resolve() else state/'dly8'

def host_mode(mode,context=None):
    """Terminal failure is resumable: reuse its receipt and always publish its seal."""
    from runner import host_context
    context = context or host_context()
    A,state,code,binding,main_seal_path,main_seal,main_manifest_path,permit = context
    require(mode in (1,2),'DLY8 mode must be 1 or 2')
    path = dly_root(state)/('mode'+str(mode))/'DLY8_RECEIPT.json'
    destination = dly_root(state)/('DLY8_SEAL_PRIMARY.json' if mode == 1 else 'DLY8_SEAL_R8.json')
    source = main_seal_path if mode == 1 else Path(state)/'SEAL_A8BATCH.json'
    if path.exists():
        result = read_json(path)
        require(result['binding']['main_conf_seal'] == identity(main_seal_path) and
                result['binding']['source_seal'] == identity(source),'DLY8 terminal receipt binding drift')
        for item in ([result['parity']] if result.get('parity') else [])+result.get('predictions',[]):
            checked(item)
    else:
        from resource_remedy import retry_count,failure
        stopped = path.parent/'STOPPED_FOR_REMEDY.json'
        try:
            count = retry_count(state,'DLY8_mode'+str(mode),stopped)
        except RemedyInterrupted as exc:
            failure(state,'DLY8_mode'+str(mode),stopped,exc,1,reason='A8DLY_DEV')
            count = 1
        try:
            from a8_amendment2 import RENDERING,REASON
            if stopped.exists() and read_json(stopped)['state'] == 'DEVIATION':
                result = dict(state='A8DLY_DEV',reason='A8DLY_DEV',detail=read_json(stopped)['detail'],
                    binding=dict(main_conf_seal=identity(main_seal_path),source_seal=identity(source)),
                    models_refitted=0,partial_predictions_eligible_for_scoring=False,predictions=[],parity=None)
                write_json(path,result,exclusive=True)
            elif mode == 2 and not code.get('r8_policy',{'run':True})['run']:
                result = dict(state='NOT_RUN_A8_AMENDMENT_2',reason=code['r8_policy'].get('reason',REASON),rendering=RENDERING,
                              binding=dict(main_conf_seal=identity(main_seal_path),source_seal=identity(source)),
                              predictions=[],parity=None,models_refitted=0)
                write_json(path,result,exclusive=True)
            else:
                if count:
                    manifest = read_json(main_manifest_path if mode == 1 else Path(state)/'features/manifest.json')
                    arms = PRIMARY_NOTICE if mode == 1 else R8_NOTICE
                    width = sum(len(b['columns']) for b in manifest['bundles'] if b['source'] == 'notice' and b['arm'] in arms and b.get('variant','main') == 'main')
                    A.storage.require_disk_space(dly_root(state),4*527040*width*4+3*527040*192*len(arms),3*1024**3,'DLY8 remedied retained second attempt')
                result = _host_mode(mode,context)
        except OverlapRefusal:
            raise
        except Exception as exc:
            if not isinstance(exc,ParityFailure):
                failure(state,'DLY8_mode'+str(mode),stopped,exc,count,reason='A8DLY_DEV')
            result = dict(state='NOT_RUN_PARITY_FAILED' if isinstance(exc,ParityFailure) else 'A8DLY_DEV',
                          reason='A8NR_PARITY' if isinstance(exc,ParityFailure) else 'A8DLY_DEV',detail=repr(exc),
                          binding=dict(main_conf_seal=identity(main_seal_path),source_seal=identity(source)),
                          models_refitted=0,partial_predictions_eligible_for_scoring=False,predictions=[],parity=None,
                          peak_rss_bytes=peak_bytes())
            write_json(path,result,exclusive=True)
    value = dict(state='DLY8_SEALED_BEFORE_SCORING',receipt=identity(path),
                 conf_seal_sha256=sha(main_seal_path),source_seal=identity(source),
                 adapter_freeze_sha256=code['adapter_freeze_sha256'],models_refitted=0,
                 mode_state=result['state'],peak_rss_bytes=result.get('peak_rss_bytes',peak_bytes()))
    if destination.exists():
        prior = read_json(destination)
        for k in ('receipt','conf_seal_sha256','source_seal','adapter_freeze_sha256'):
            require(prior[k] == value[k],'DLY8 seal identity drift on resume')
    else:
        write_json(destination,value,exclusive=True)
    return result

def peak_bytes():
    import resource
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == 'darwin' else value*1024)

def launch_mode(mode,context):
    """Each production mode measures RSS in its own fresh serial child."""
    import subprocess
    A,state,code,binding,seal_path,seal,manifest_path,permit = context
    import a8_adapter
    launch = dict(adapter_root=code['adapter_root'],adapter_freeze_sha256=code['adapter_freeze_sha256'],
                  hashes=a8_adapter.runtime_hashes(code),code=code,binding=binding,main_seal=identity(seal_path),
                  main_manifest=identity(manifest_path),permit=__import__('dataclasses').asdict(permit))
    write_json(Path(state)/'DLY8_LAUNCH.json',launch,exclusive=True)
    command = [sys.executable,'-B',str(Path(__file__).resolve()),'--mode',str(mode),'--execute','--child']
    completed = subprocess.run(command,check=False)
    if completed.returncode != 0:
        from resource_remedy import failure
        stopped = dly_root(state)/('mode'+str(mode))/'STOPPED_FOR_REMEDY.json'
        path = stopped.parent/'DLY8_RECEIPT.json'
        if path.exists():
            return host_mode(mode,context)
        consumed = (Path(state)/'remedied_attempts'/('DLY8_mode'+str(mode)+'.json')).exists()
        if not stopped.exists() or consumed:
            failure(state,'DLY8_mode'+str(mode),stopped,RuntimeError('DLY8 child exit '+str(completed.returncode)),int(consumed),reason='A8DLY_DEV')
        if consumed:
            return host_mode(mode,context)
        raise ResourceStop('DLY8 child failed before terminal receipt; batch stopped for remedy')
    return read_json(dly_root(state)/('mode'+str(mode))/'DLY8_RECEIPT.json')

def child_context():
    import a8_adapter
    require(os.environ.get('A8BATCH_HOST_RUN') == '1' and os.getpriority(os.PRIO_PROCESS,0) >= 10,'DLY8 child requires host environment and nice 10')
    a8_adapter.install_audit(OUT/'state')
    launch = read_json(OUT/'state/DLY8_LAUNCH.json')
    for item in launch['hashes']:
        checked(item)
    checked(launch['main_seal']); checked(launch['main_manifest'])
    A = a8_adapter.load(launch['adapter_root'],expected=launch['adapter_freeze_sha256'],preverified=True)
    a8_adapter.relocate(A,OUT/'state')
    return (A,OUT/'state',launch['code'],launch['binding'],Path(launch['main_seal']['path']),
            read_json(launch['main_seal']['path']),Path(launch['main_manifest']['path']),
            A.guard.ExecutionPermit(**launch['permit']))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',type=int,choices=(1,2),required=True)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--child',action='store_true')
    args = parser.parse_args()
    require(args.execute, 'DLY8 host prediction requires explicit coordinator --execute')
    from runner import host_context
    context = child_context() if args.child else host_context()
    if args.child:
        host_mode(args.mode,context=context)
    else:
        with context[0].execution.exclusive_state(context[1]):
            launch_mode(args.mode,context)
