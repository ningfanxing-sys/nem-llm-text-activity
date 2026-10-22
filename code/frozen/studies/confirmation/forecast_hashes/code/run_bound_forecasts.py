'Run forecasts after checking their input metadata.'
import os
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[name]='1'
import argparse
import ast
from contextlib import nullcontext
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from common import *
from activity_guard import read_lsof_snapshot,refuse_metadata,process_entry
from check_prescoring_state import prove_before_t5

class ReviewedModuleUncertainty(RuntimeError):
    'Input metadata.'

class _WrapperParser(argparse.ArgumentParser):
    def error(self, message):
        raise RuntimeError('Cannot certify reviewed wrapper argv: '+message)

    def exit(self, status=0, message=None):
        raise RuntimeError('Cannot certify reviewed wrapper argv exit')

    def _print_message(self, message, file=None):
        pass


def wrapper_parser():

    from forecast_inputs import D
    tree=ast.parse((D/'forecast_wrapper.py').read_text())
    main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    constructors=[n for n in main.body if isinstance(n,ast.Assign) and
                  len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='parser']
    require(len(constructors)==1 and ast.dump(constructors[0].value)==
            ast.dump(ast.parse('argparse.ArgumentParser()',mode='eval').body),
            'Cannot certify frozen wrapper parser construction')
    declarations=[]
    for node in main.body:
        if not (isinstance(node,ast.Expr) and isinstance(node.value,ast.Call) and
                isinstance(node.value.func,ast.Attribute) and
                isinstance(node.value.func.value,ast.Name) and node.value.func.value.id=='parser' and
                node.value.func.attr=='add_argument'):
            continue
        call=node.value
        args=tuple(ast.literal_eval(a) for a in call.args)
        kwargs={k.arg:(int if isinstance(k.value,ast.Name) and k.value.id=='int'
                       else ast.literal_eval(k.value)) for k in call.keywords}
        declarations.append((args,kwargs))
    expected=[(('--execute',),dict(action='store_true')),
              (('--plan-only',),dict(action='store_true')),
              (('--finish-sealed',),dict(action='store_true')),
              (('--workers',),dict(type=int,default=4)),
              (('--dly-child',),dict(action='store_true')),
              (('--child',),dict(action='store_true')),
              (('--mode',),dict(type=int,choices=(1,2)))]
    require(declarations==expected,'Cannot certify frozen wrapper parser declaration drift')
    parser=_WrapperParser()
    for args,kwargs in declarations:
        parser.add_argument(*args,**kwargs)
    return parser


def _python_script_tail(tail, entries):

    tail=list(tail); no_value=set('bBdEiIOPqRsStuvx')
    while tail:
        token=tail.pop(0)
        if token=='--':
            return tail
        if token=='-':
            return []
        if not token.startswith('-'):
            return [token,*tail]
        if token in ('--help','--help-env','--help-xoptions','--help-all','--version'):
            return []
        if token=='--check-hash-based-pycs':
            require(tail and tail.pop(0) in ('default','always','never'),
                    'Cannot certify Python hash-pyc option')
            continue
        require(not token.startswith('--'),'Cannot certify unknown Python option')
        cluster=token[1:]
        for j,flag in enumerate(cluster):
            if flag in no_value:
                continue
            if flag in ('h','?','V'):
                return []
            if flag in ('c','m'):
                operand=cluster[j+1:] or (tail.pop(0) if tail else None)
                require(operand is not None,'Cannot certify missing Python interface operand')
                if flag=='m':
                    if operand.rsplit('.',1)[-1] in {Path(p).stem for p in entries}:
                        raise ReviewedModuleUncertainty('Cannot certify reviewed wrapper module provenance')
                return []
            if flag in ('W','X'):
                if not cluster[j+1:]:
                    require(tail,'Cannot certify missing Python option operand')
                    tail.pop(0)
                break
            raise RuntimeError('Cannot certify unknown Python option')
    return []


def _launch_tail(argv):

    tail=list(argv or [])
    while tail and Path(tail[0]).name in ('nice','caffeinate'):
        tool=Path(tail.pop(0)).name
        while tail and tail[0].startswith('-'):
            flag=tail.pop(0)
            if flag=='--':
                break
            if tool=='nice':
                if flag=='-n':
                    require(tail,'Cannot certify missing nice increment'); tail.pop(0)
                elif flag[1:].lstrip('+-').isdigit():
                    continue
                else:
                    raise RuntimeError('Cannot certify nice prefix')
            else:
                cluster=flag[1:]
                require(cluster and not cluster.startswith('-'),'Cannot certify caffeinate prefix')
                for j,char in enumerate(cluster):
                    if char in 'dimsu':
                        continue
                    require(char in 'tw','Cannot certify caffeinate prefix')
                    if not cluster[j+1:]:
                        require(tail,'Cannot certify missing caffeinate operand'); tail.pop(0)
                    break
    return tail


def wrapper_execution_argv(argv, entries, cwd=None):

    entries={str(Path(p).resolve()) for p in entries}
    def is_entry(token):
        if not token.endswith('.py') or token.startswith('-'):
            return False
        p=Path(token)
        if not p.is_absolute():
            require(cwd is not None,'Cannot certify relative wrapper entry without process cwd')
            p=Path(cwd)/p
        return str(p.resolve()) in entries

    try:
        command=_launch_tail(argv)
        if not command:
            return False
        executable=Path(command[0]).name.lower()
        if executable.startswith('python'):
            tail=_python_script_tail(command[1:],entries)
        elif executable in ('bash','zsh','sh'):
            if any('c' in t[1:] for t in command[1:] if t.startswith('-')):
                return False
            require(len(command)>1 and not command[1].startswith('-'),
                    'Cannot certify shell script options')
            tail=command[1:]
        else:
            return False
    except ReviewedModuleUncertainty:
        raise
    except RuntimeError:
        if any(is_entry(t) for t in argv or []):
            raise
        raise_if_module=any(t.rsplit('.',1)[-1] in {Path(p).stem for p in entries} for t in argv or [])
        if raise_if_module:
            raise
        return False
    if not tail or not is_entry(tail[0]):
        return False
    args=wrapper_parser().parse_args(tail[1:])

    if args.dly_child:
        require(args.child and args.execute and args.mode is not None,
                'Cannot certify incomplete DLY child dispatch')
        return True
    if args.plan_only:
        return False
    return args.execute or args.finish_sealed

def no_overlap(root_mapping=None, *, process_api=None, legacy_recognizer=None,
               snapshot_provider=None):

    if process_api is None:
        import psutil as process_api
    if legacy_recognizer is None:
        from runner import fitting_argv as legacy_recognizer
    from forecast_inputs import root_mapping_contract,verify_root_mapping
    roots=verify_root_mapping(root_mapping or root_mapping_contract())
    found=[]; contract=roots['activity_guard']
    try:
        ancestor_wrappers=set()
        for ancestor in process_api.Process().parents():
            if ancestor.name() not in ('caffeinate','nice'):
                continue
            argv=ancestor.cmdline() or []
            if str(Path(__file__).resolve()) in argv and not wrapper_execution_argv(argv,roots['wrapper_entries']):
                ancestor_wrappers.add(ancestor.pid)
        processes=list(process_api.process_iter())
        observed={}
        for process in processes:
            try:
                observed[process.pid]=(process.create_time(),process.cmdline() or [],process.cwd())
            except process_api.NoSuchProcess:
                continue
        records=(snapshot_provider or read_lsof_snapshot)()


        after={p.pid:p.create_time() for p in process_api.process_iter()}
        require(after=={pid:v[0] for pid,v in observed.items()},
                'Cannot certify host fit/rebuild non-overlap: process census changed')
        require(set(after)<={p['pid'] for p in records},
                'Cannot certify host fit/rebuild non-overlap: incomplete all-UID lsof coverage')
        refuse_metadata(contract,records)
    except (process_api.AccessDenied,PermissionError,OSError) as exc:
        raise RuntimeError('Cannot certify host fit/rebuild non-overlap') from exc
    for process in processes:
        if process.pid==os.getpid() or process.pid in ancestor_wrappers:
            continue
        try:
            if process.pid not in observed:
                continue
            _,argv,cwd=observed[process.pid]

            refuse_metadata(contract,[dict(pid=process.pid,uid=-1,
                files=[dict(fd='cwd',name=cwd,type='DIR')])])
            if process_entry(argv,cwd,contract,_launch_tail):
                found.append(process.pid); continue
            if wrapper_execution_argv(argv,roots['wrapper_entries'],cwd) or legacy_recognizer(argv,cwd):
                found.append(process.pid); continue

            for i,token in enumerate(argv):
                if not token.endswith(('.py','.sh')):
                    continue
                name=Path(token).name
                if name in ('rebuild_delayed_features.py','project_d.py','project_laz.py','diagnose.py','run_bound_forecasts.py',
                            'seal_score.py','read_comparisons.py','score_batch.py','primary_comparisons.py'):
                    found.append(process.pid); break
                if name.startswith('host_') and any(x in name.lower() for x in ('batch','spec_','rebuild','forecast_binding')):
                    found.append(process.pid); break
        except process_api.NoSuchProcess:
            continue
        except (process_api.AccessDenied,PermissionError,OSError) as exc:
            raise RuntimeError('Cannot certify host fit/rebuild non-overlap') from exc
    require(not found,'inference_design host-order refusal: another fit/rebuild is active')

def verify_code():
    freeze=read_json(OUT/'CODE_FREEZE.json')
    require(freeze['state']=='FORECAST_BINDING_CODE_FROZEN_FOR_SOURCE', 'Reviewed forecast_hashes code freeze required')
    for item in freeze['files']+freeze['dependencies']+freeze['ad_inputs']:
        checked(item)
    return freeze

def require_before_t5(root_mapping=None,timestamp_root_identity=None):
    from forecast_inputs import root_mapping_contract,verify_root_mapping
    roots=verify_root_mapping(root_mapping or root_mapping_contract())
    contract=roots['before_t5_guard']
    require(contract['sentinel_paths']==roots['t5_gate_paths'],
            'Cannot certify before-T5: gate/source mapping drift')
    return prove_before_t5(contract,timestamp_root_identity)

def affected_arms(result):
    require(result['state']=='COMPLETE_SOURCE_ONLY_BLINDED_DIAGNOSTIC','ANCHORDIAG is not complete')
    families=result['D_feature_diff']['families']
    arms=[]
    if families['L14']['D_rows_any_difference']:
        arms.append('L14')
    if result['Laz_feature_diff']['D_rows_any_difference']:
        arms.append('L_Laz')
    require(arms==['L14','L_Laz'] and families['L14']['D_rows_any_difference']==29310
            and result['Laz_feature_diff']['D_rows_any_difference']==3456,
            'Completed AD differs from the reviewed two-arm/count contract')
    return arms

def dispatch(activation_path):
    require(os.environ.get('FORECAST_BINDING_SOURCE_RUN')=='1','Separate source host execution required')

    reads=install_audit(); checkpoints=[resources()]; freeze=verify_code()
    sys.path.insert(0,str(B/'code'))
    roots=freeze['root_mapping']
    from forecast_inputs import verify_root_mapping,verify_runtime_roots,load_dly8_binding
    verify_root_mapping(roots)
    no_overlap(roots)
    activation=read_json(activation_path)
    required=('authorized','batch_finished','before_T5','no_scores_seen','no_fit_or_rebuild_overlap','deadline_rule_acknowledged')
    require(activation.get('state')=='FORECAST_BINDING_SOURCE_AUTHORIZED' and all(activation.get(k) is True for k in required), 'Explicit source pre-score/host-order attestation required')
    require(activation['code_freeze']==identity(OUT/'CODE_FREEZE.json'),'Activation/code-freeze drift')
    require(activation['decision_rule']==identity(AD/'SOURCE_DECISION_RULE_20261005.md'),'Source revision binding drift')
    require(activation['root_mapping']==roots,'Activation/code freeze root mapping drift')
    require(activation.get('timestamp_root_identity')==freeze['timestamp_root_identity'],
            'Activation/freeze timestamp directory identity drift')
    for field in ('independent_review','consumer_acceptance'):
        require(activation[field]==freeze[field],'Activation/freeze owner acceptance drift: '+field)
        checked(activation[field])
    require(activation['deadline_aedt']=='2026-10-06T18:00:00+11:00','Deadline rule drift')
    result_ad=read_json(AD/'RESULT.json'); affected=affected_arms(result_ad)
    from datetime import datetime
    deadline=datetime.fromisoformat(activation['deadline_aedt'])
    recorded=datetime.fromisoformat(activation['recorded_utc'].replace('Z','+00:00'))
    require(recorded.utcoffset() is not None and bool(activation['recorded_by']), 'Dated source identity required')
    require(datetime.now(deadline.tzinfo)<deadline,'Corrected seal missed the before-T5 deadline')
    before_t5_checks=[require_before_t5(roots,freeze['timestamp_root_identity'])]
    runtime_roots=verify_runtime_roots(roots)
    import freeze_batch_sources
    code=freeze_batch_sources.verify()

    import batch_adapter
    A=batch_adapter.load(code['adapter_root'],expected=code['adapter_freeze_sha256'],preverified=True)
    require(Path(code['adapter_root']).resolve()==X2.resolve(),'Unexpected main adapter root')
    def own_atomic(path,value,immutable=False):
        p=Path(path).resolve(); require(p.is_relative_to(OUT),'Installed callback write escaped OUT')
        write_json(p,value)
    for module_name in ('runtime','features_adapter','notice_label_adapter','embedding_adapter','feature_storage','execution_adapter'):
        module=sys.modules.get(module_name)
        if module and hasattr(module,'atomic_json'):
            module.atomic_json=own_atomic
    main_path=checked(activation['main_conf_seal']); main=read_json(main_path)
    batch_path=checked(activation['batch_seal']); batch=read_json(batch_path)
    require(main_path==X2/'host_state/SEAL.json','Wrong main seal path')
    require(batch_path==Path(roots['state_root'])/'SEAL_BATCH.json','Wrong current D batch seal path')
    require(main['state']=='ALL_SPECIFIED_PREDICTIONS_SEALED' and main['sealed_before_outcome_scoring'],'Main chain is not sealed pre-score')
    require(batch['state']=='ALL_A8BATCH_SPECIFIED_PREDICTIONS_SEALED' and batch['sealed_before_outcome_scoring'],'Batch has not finished/sealed')
    require(batch['conf_seal']==identity(main_path),'Batch/main seal mismatch')
    checked(batch['code_freeze'])

    dly_binding=load_dly8_binding(roots,identity(main_path),identity(batch_path),code['adapter_freeze_sha256'])
    before_t5_checks.append(require_before_t5(roots,freeze['timestamp_root_identity']))
    require(not (OUT/'SEAL_FORECAST_BINDING.json').exists(),'Existing seal is immutable; verify it separately')
    permit=A.runtime.validate_permit()
    manifest_path=X2/'host_state/features/manifest.json'
    require(sha(manifest_path)==main['feature_manifest_sha256'],'Main features are not seal-bound')
    manifest=read_json(manifest_path)
    bundles={arm:next(b for b in manifest['bundles'] if (b['source'],b['arm'],b.get('variant','main'))==('notice',arm,'main')) for arm in (*affected,'N')}
    seen={}
    for bundle in bundles.values():
        A.storage.verify_bundle(bundle,seen=seen)
        require(sha(bundle['panel_path'])==bundle['panel_sha256'],'Panel identity drift')
    import numpy as np
    import pandas as pd
    import lightgbm as lgb
    import notice_label_adapter as nrx
    from anchor_patch import install_patch
    from prediction_set import run_set,write_seal,build_production_support_binding
    from structural_projection import structural_adapter,NoEncoder
    dly=dly_module(); panel,production_rows=dly.d_panel(bundles['N'],A)
    panel['_production_row']=production_rows
    panel=dly.normalize(panel)
    production_rows=panel.pop('_production_row').to_numpy(dtype='int64')
    models=dly.model_bank(main,affected)
    for arm,rec in models.items():
        require(rec['task']['origin']=='prewindow_frozen_C_bank' and rec['feature_order']==bundles[arm]['columns'],'Pre-window/main column identity drift')
    refs={}
    for arm in PRIMARY:
        matches=[i for i in main['predictions'] if (i['source'],i['arm'],i['seed'],i['variant'])==('notice',arm,SEED,'main')]
        require(len(matches)==1,'Main PRIMARY prediction census drift')
        refs[arm]=matches[0]; checked(refs[arm])
    notices=A.features.load_host_notices(Q/'notice_extraction/results_1_3',permit=permit)
    with install_patch(nrx,A.features) as patch_receipt:
        pass
    patch_path=OUT/'PATCH_IDENTITY.json'; write_json(patch_path,patch_receipt)
    binding=dict(main_conf_seal=identity(main_path),batch_seal=identity(batch_path),
                 code_freeze=identity(OUT/'CODE_FREEZE.json'),models=[rec['model_identity'] for rec in models.values()],
                 model_receipts=[rec['receipt_identity'] for rec in models.values()],patch=identity(patch_path),
                 ad_inputs=freeze['ad_inputs'],activation=identity(activation_path),main_feature_manifest=identity(manifest_path))
    binding['runtime_roots']=runtime_roots
    binding['dly8']=dly_binding
    binding['support']=build_production_support_binding(binding['ad_inputs'])
    started=time.monotonic()
    with tempfile.TemporaryDirectory(prefix='FORECAST_BINDING_',dir='/private/tmp') as directory:
        scratch=Path(directory)
        def checkpoint():
            checkpoints.append(resources(scratch)); no_overlap(roots)
            before_t5_checks.append(require_before_t5(roots,freeze['timestamp_root_identity']))
        def rebuild(arm,aligned,root):
            checkpoint()

            for p in scratch.glob('**/*.npy'):
                p.unlink()
            planned=len(panel)*len(bundles[arm]['columns'])*4+len(panel)*80
            require(planned<SCRATCH_LIMIT,'Rebuild scratch plan is at least 1 GB')
            proxy=structural_adapter(A,[arm],scratch,checkpoints)
            ctx=install_patch(nrx,A.features) if aligned else nullcontext()
            with ctx:
                return dly.rebuild_features(panel,notices,0,[arm],bundles,proxy,permit,scratch/root.name,
                         {'numeric_columns':bundles['N'].get('shared_columns',bundles['N']['columns'])},
                         encoder=NoEncoder(),cache_directory=scratch/'no_encoding',production_rows=production_rows)[arm]
        def predict(arm,x):
            checkpoint(); rec=models[arm]
            model=lgb.Booster(model_file=str(checked(rec['model_identity'])))
            require(model.feature_name()==rec['feature_order']==bundles[arm]['columns'],'Model column order drift')

            return dly.predict_notice(model,x,panel,rec['params'],A.execution.price_cap)
        def reference(arm):
            f=pd.read_parquet(checked(refs[arm]),columns=KEYS+['target_day','raw_prediction','lower_bound','upper_bound','prediction'])
            return f.loc[f.target_day.astype(str).str[:10].between('2026-08-01','2026-09-30')]
        def changed(arm):
            return pd.read_parquet(AD/(arm+'_changed_keys.parquet'))
        result=run_set(OUT/'prediction_set',panel,affected,refs,reference,
                      lambda arm,ids:A.storage.load_feature_rows(bundles[arm],production_rows[ids]),
                      rebuild,predict,changed,binding,checkpoint)
        checkpoint()
    require(datetime.now(deadline.tzinfo)<deadline,'Correction finished after the deadline; do not seal as pre-T5')
    no_overlap(roots)
    before_t5_checks.append(require_before_t5(roots,freeze['timestamp_root_identity']))
    require(identity(main_path)==binding['main_conf_seal'] and identity(batch_path)==binding['batch_seal'],'Parent seal drift during run')
    write_json(OUT/'HOST_RUN_RECEIPT.json',dict(state='REBUILT_AND_PARITY_PASSED',resources=checkpoints,
               wall_seconds=time.monotonic()-started,models_refitted=0,outcomes_read=False,
               exact_python_project_reads=sorted(reads),before_t5_checks=before_t5_checks))
    return write_seal(OUT/'SEAL_FORECAST_BINDING.json',result,binding)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--activation',type=Path)
    args=parser.parse_args()
    require(args.execute and args.activation,'Explicit source --execute --activation is required')
    result=dispatch(args.activation)
    print(json.dumps({'state':result['state'],'models_refitted':0,'values_printed':False}))
