"""Post-CONF-seal A8 fitting batch. No data reads/fits on import.

Order: B0 reproduction; B1 CS8; B2 R8 notice; B3 CPS8; B4 R8 news; B5 extra news seeds.
"""
from dataclasses import asdict
from pathlib import Path
import argparse
import math
import os
import shutil
from a8_common import *
import a8_adapter
import a8_freeze

CS8_ORDER = ('report_only_2025_validation','secondary_notice','secondary_news','secondary_LEAR',
             'primary_seed_robustness_notice','primary_seed_robustness_news')
BUDGET_OMISSIONS = {'UNAVAILABLE_RESOURCE_BUDGET'}

def fitting_argv(argv,cwd=None):
    """Recognise exact REPIN8 bootstrap payloads and direct scripts, never shell text."""
    bootstrap = "import sys; sys.path.insert(0, sys.argv[2]); from launcher import exec_original; exec_original(sys.argv[3], sys.argv[4], sys.argv[5:])"
    flags = ('-B','-P','-u','-I','-s','-S','-E','-O','-OO')
    for i,token in enumerate(argv or []):
        exe = Path(token).name.lower()
        if not (exe.startswith('python') or exe in ('bash','zsh','sh')):
            continue
        tail = list(argv[i+1:])
        while tail and tail[0] in flags:
            tail.pop(0)
        if tail[:2] == ['-c',bootstrap]:
            payload = tail[2:]
            if not (len(payload)>=4 and Path(payload[1]).name=='REPIN8' and
                    Path(payload[2]).name=='REPIN_CONFX8' and payload[3]==Path(payload[0]).name):
                continue
            script,args = payload[0],payload[4:]
            # Cross-check source/stage identity patterns rather than arbitrary -c text.
            stage=Path(payload[2])
            source=Path(script)
            if source.parent.name!='code' or stage.parent.name!=source.parent.parent.name:
                continue
        else:
            if not tail or tail[0].startswith('-'):
                continue
            script,args=tail[0],tail[1:]
        if not script.endswith(('.py','.sh')):
            continue
        script = str((Path(cwd or '.')/script).resolve())
        if script.endswith('/CONFX2/cli.py'):
            if args and args[0] in ('panels','features','counted-pilots','fit-bank','lear','fit','run','pilot'):
                return True
            continue
        if '/REPIN8/' in script and Path(script).name == 'postscore_launch.py':
            return '--execute' in args
        if '/A8BATCH/' in script and Path(script).name in ('runner.py','repin_postscore_launch.py','postscore_host.py','pcx_turn.py'):
            return '--execute' in args or any(a in ('fit','run','host') for a in args)
        if any(marker in script for marker in ('/host_chain_CONFX','/A4/PCX/','/A2BATCH/code/runner.py','/A2LABEL/','/KCX/','/positive_control/')) or Path(script).name in ('pcx_runner.py','iso_runner.py','iso_blocks.py'):
            return True
    return False

def active_fit_jobs():
    """Recognize launched fit scripts; read-only tools cannot match path text."""
    import psutil
    found = []
    skipped = []
    try:
        processes = list(psutil.process_iter())
    except (PermissionError,psutil.AccessDenied) as exc:
        raise OverlapRefusal('Process-table access refused; host read-only verification required') from exc
    for process in processes:
        if process.pid == os.getpid():
            continue
        try:
            if process.uids().real != os.getuid():
                skipped.append(dict(pid=process.pid,reason='foreign_uid_skipped'))
                continue
            argv = process.cmdline() or []
            relative = any(token.endswith(('.py','.sh')) and not Path(token).is_absolute() for token in argv)
            if fitting_argv(argv,process.cwd() if relative else None):
                found.append(dict(pid=process.pid,argv=argv))
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as exc:
            raise OverlapRefusal('Cannot certify non-overlap of fitting jobs') from exc
    active_fit_jobs.last_skipped = skipped
    if os.environ.get('A8BATCH_HOST_RUN') == '1':
        with (OUT/'state/PROCESS_OVERLAP_AUDIT.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(utc=now(),checked_uid=os.getuid(),foreign_skipped=skipped,matched=found))+'\n')
    return found

def cs8_tasks(A,seal):
    definitions = {name:list(jobs) for name,jobs,_ in A.execution.registered_plan()}
    dispositions = {row['stage']:row for row in seal['stage_dispositions']}
    require(len(dispositions) == len(seal['stage_dispositions']), 'Duplicate CONF stage disposition')
    selected = {}
    for name, jobs, _ in A.execution.registered_plan():
        if name not in CS8_ORDER:
            continue
        require(name in dispositions, 'Missing registered CS8 stage definition')
        old = dispositions[name]
        if not rerun_eligible(old):
            continue
        declared = old.get('registered_tasks')
        require(declared is not None and declared == [A.execution.task_id(t) for t in jobs], 'CONF registered stage identity drift')
        selected['CS8_'+name] = list(jobs)
    return selected

DEADLINE_ERRORS = (
    "TimeoutError('No new fitting launches at the 24-hour deadline')",
    "TimeoutError('24-hour deadline: unlaunched tasks remain')")

def rerun_eligible(row):
    if row['state'] in BUDGET_OMISSIONS:
        return True
    return row['state'] == 'UNAVAILABLE_RESOURCE_FAILURE' and row.get('error',row.get('reason')) in DEADLINE_ERRORS

def rerun_trigger(row):
    if row['state'] in BUDGET_OMISSIONS:
        return 'UNAVAILABLE_RESOURCE_BUDGET'
    error = row.get('error',row.get('reason'))
    require(error in DEADLINE_ERRORS,'Unregistered CS8 trigger')
    return 'No new fitting launches at the 24-hour deadline' if error == DEADLINE_ERRORS[0] else '24-hour deadline: unlaunched tasks remain'

def r8_tasks(A, days, seeds='single'):
    require(seeds in ('single','three'), 'Invalid R8 seed choice')
    F = A.scheduler.FitTask
    jobs = {'R8_notice':[F('notice','prewindow_frozen_C_bank',a,SEED) for a in R8_NOTICE],
            'R8_news':[F('news',d,a,SEED) for d in days for a in R8_NEWS] +
                      [F('news','2025-01-01',a,SEED,'2025_fixed_validation') for a in R8_NEWS]}
    if seeds == 'three':
        jobs['R8_notice'] += [F('notice','prewindow_frozen_C_bank',a,seed)
            for seed in (20260920,20260921) for a in ('M+_n','L14+','L_Laz+','L_chen_notice+')]
        jobs['R8_news_seeds'] = [F('news',d,a,seed) for d in days for seed in (20260920,20260921)
                                  for a in ('M+','L_count+','L_chen+')]
    return jobs

def estimate_stage(A,jobs,records,manifest,parent_bytes=0,workers=4):
    """A8 estimate from THIS stage's counted pilot/fit receipts, never a proxy fit."""
    if not jobs:
        return 0.
    ids = {A.execution.task_id(t) for t in jobs}
    durations = [float(r['runtime_seconds']) for r in records
                 if r.get('state') == 'COMPLETE' and 'task' in r and
                 A.execution.task_id(A.scheduler.FitTask(**r['task'])) in ids]
    if not durations:
        return None
    rounds = estimate_rounds(A,jobs,records,manifest,parent_bytes,workers)

    return 1.25 * max(durations) * rounds

def estimate_rounds(A,jobs,records,manifest,parent_bytes=0,workers=4):
    groups = {}
    for task in jobs:
        groups.setdefault((task.task,task.origin),[]).append(task)
    rounds = 0
    for (source,_),group in groups.items():
        cap = workers if source == 'news' else 1
        if source == 'news' and manifest.get('bundles'):
            projections = [A.execution._projected_anonymous(t,records,manifest) for t in group]
            cap = min(cap,max(1,int((A.execution.TREE_LIMIT-parent_bytes)//max(projections))))
        rounds += math.ceil(len(group)/cap)
    return rounds

def rho_from_ledger(data):
    waves = [w for w in data['waves'] if w['stage'] == 'primary_news' and w['state'] != 'ABANDONED_ATTEMPT_CHARGED']
    require(waves and all(w.get('end') is not None for w in waves), 'Completed primary-news wall waves required')
    origins = set()
    for w in waves:
        for t in w['tasks']:
            origins.add(t['origin'] if isinstance(t,dict) else t.split('__')[1])
    require(origins, 'Primary-news origins missing')
    return sum(max(0.,w['end']-w['start']) for w in waves)/len(origins)/43.488448833

def pcx_estimate(rho):
    return 0. if rho >= 1.5 else 2.4889 * 3600 * rho * 1.25

def optional_admission(remaining,estimates,mandatory=0.,rho=1.):
    require(set(estimates) <= set(DROP_ORDER), 'Optional estimate inventory drift')
    estimates = dict(estimates)
    if rho >= 1.5:
        estimates.pop('PCX_extension',None)
    keep = [n for n in DROP_ORDER if n in estimates]
    drops = []
    for name in list(keep):
        if mandatory is not None and all(estimates[k] is not None for k in keep) and mandatory + sum(estimates[k] for k in keep) <= remaining:
            break
        keep.remove(name)
        drops.append(name)
    return dict(keep=keep,drop=drops,drop_order=list(DROP_ORDER),remaining_seconds=remaining,
                mandatory_reserve_seconds=mandatory,metadata_only_estimates_seconds=estimates,rho=rho,
                PC_host_state='PENDING_A8NR_SPEED' if rho >= 1.5 else 'POSTSCORE_BASE',
                PCX_extension_state='PENDING_A8NR_SPEED' if rho >= 1.5 else
                    ('ADMITTED' if 'PCX_extension' in keep else 'NOT_RUN_A8NR_BATCH_BUDGET'))

def reservation_decision(name,remaining,estimates,finished=(),mandatory=0.,rho=1.):
    require(name in DROP_ORDER, 'Unknown A8 droppable item')
    later = DROP_ORDER[DROP_ORDER.index(name):]
    reserved = [n for n in later if n in estimates and n not in finished and not (n == 'PCX_extension' and rho >= 1.5)]
    amount = None if mandatory is None or any(estimates[n] is None for n in reserved) else mandatory+sum(estimates[n] for n in reserved)
    ok = name in reserved and amount is not None and amount <= remaining
    return dict(stage=name,admitted=ok,remaining_seconds=remaining,reserved_items=reserved,
                estimate_seconds=amount,reason=None if ok else 'A8NR_BATCH_BUDGET')

class ContinuationLedger:
    """Keep the real 86400-second ledger; remove only launch deadlines for B0-B2."""
    def __init__(self, ledger):
        self.ledger = ledger
    def __getattr__(self, name):
        return getattr(self.ledger, name)
    def remaining(self):
        return float('inf')
    def begin(self,tasks,stage):
        require(not any(w.get('end') is None for w in self.data['waves']), 'Overlapping fitting wall accounting')
        ident = __import__('uuid').uuid4().hex
        stamp = self.clock()
        self.data['waves'].append(dict(id=ident,stage=stage,tasks=[
            t.task+'__'+t.origin+'__'+t.arm+'__s'+str(t.seed)+'__'+t.variant for t in tasks],
            start=stamp,heartbeat=stamp,end=None,workers=[],state='RUNNING',a8_authorised_continuation=True))
        self.save()
        return ident

def counted_pilot(name,jobs,manifest,feature_sha,stats,permit,state,ledger,A,resources,workers):
    if ledger.remaining() <= 0:
        not_run_stage(state,name,jobs,feature_sha,A)
        return None
    candidates = []
    for t in jobs:
        b = A.execution.find_bundle(manifest,t)
        if b.get('state','COMPLETE') == 'COMPLETE':
            candidates.append(t)
    if name == 'CPS8':
        candidates = [t for t in candidates if t.task == 'news' and t.arm == 'L_chen__CPS8_g1' and t.variant == 'cps8_selection']
    require(candidates, 'No eligible counted pilot: '+name)
    def trees(t):
        params = A.params(t)
        if t.variant.startswith('cps8_'):
            from cps8_runner import grid_parameters,decode_arm
            params = grid_parameters(params,decode_arm(t.arm)[1])
        return params['n_estimators']
    largest = max(candidates,key=lambda t:(len(A.execution.find_bundle(manifest,t)['columns']),trees(t)))
    row = run_stage('counted_pilot__'+name,[largest],manifest,feature_sha,stats,permit,state,ledger,A,
                    resources,workers,admitted=True)
    if row['state'] in ('DEVIATION','NOT_RUN_BUDGET'):
        not_run_stage(state,name,jobs,feature_sha,A) if row['state'] == 'NOT_RUN_BUDGET' else None
        return None
    require(row['state'] in COMPLETE, 'Counted pilot failed: '+name)
    return largest

def stats_for(manifest,A):
    stats = {}
    seen = {}
    panels = {}
    for b in manifest['bundles']:
        if b.get('state','COMPLETE') != 'COMPLETE':
            continue
        verify_bundle(b,A,seen=seen)
        if b['panel_path'] not in panels:
            panels[b['panel_path']] = sha(b['panel_path'])
        require(panels[b['panel_path']] == b['panel_sha256'],'Panel identity drift')
        for p in [*A.storage.bundle_storage_paths(b),Path(b['panel_path'])]:
            s = p.stat()
            stats[str(p.resolve())] = [s.st_size,s.st_mtime_ns]
    if manifest.get('hourly_path'):
        require(sha(manifest['hourly_path']) == manifest['hourly_sha256'], 'LEAR hourly input drift')
    return stats

def resource_metadata(seal,A):
    result = []
    for item in seal['fit_receipts_and_models']:
        if item.get('kind') != 'fit_receipt':
            continue
        rec = read_json(checked(item))
        # Performance/prediction values never enter this inventory.
        result.append({k:rec[k] for k in ('task','state','runtime_seconds','peak_rss_bytes','peak_anonymous_bytes',
                       'train_rows','prediction_rows','features','component_pairs') if k in rec})
    return result

def main_reuse_inventory(main_state,jobs,seal,A,main_permit):
    """Include counted completed pilots absent from the main complete-stage seal.

    Only exact registered receipt paths are candidates. Independently bind these
    receipts/artifacts into BATCH_INPUT_FREEZE before any batch fit; do not call
    them predictions already included in the main seal.
    """
    registered = {A.execution.task_id(t) for _,tasks,_ in A.execution.registered_plan() for t in tasks}
    items = {i['path']:i for i in seal['fit_receipts_and_models']}
    for task in jobs:
        require(A.execution.task_id(task) in registered, 'Unregistered main reuse task')
        rec = A.execution.reusable(main_state,task,seal['feature_manifest_sha256'],main_permit)
        if rec is None:
            continue
        rp = A.execution._receipt_path(main_state,task)
        items.setdefault(str(rp.resolve()),identity(rp,kind='fit_receipt',binding='COUNTED_COMPLETED_FIT_INDEPENDENTLY_BOUND'))
        paths = [(rec['prediction_path'],rec['prediction_sha256'],'per_fit_prediction')]
        if task.task == 'lear':
            require(rec.get('component_pairs') == 288 and len(rec.get('windows',[])) == 12, 'Incomplete counted LEAR pilot')
            for window in rec['windows']:
                require(len(window['hours']) == 24, 'Incomplete LEAR hour bank')
                paths += [(window['model_path'],window['model_sha256'],'LEAR_window_models'),
                          (window['input_scaling_path'],window['input_imputation_scaling_sha256'],'LEAR_input_scaling')]
        else:
            paths.append((rec['model_path'],rec['model_sha256'],'LightGBM_model'))
        for path,expected,kind in paths:
            require(sha(path) == expected, 'Counted main fit artifact drift')
            items.setdefault(str(Path(path).resolve()),identity(path,kind=kind,binding='COUNTED_COMPLETED_FIT_INDEPENDENTLY_BOUND'))
    records = A.execution._resource_records(main_state,seal['feature_manifest_sha256'],main_permit)
    resource_fields = ('task','state','runtime_seconds','peak_rss_bytes','peak_anonymous_bytes','train_rows','prediction_rows','features','component_pairs')
    return dict(fit_receipts_and_models=list(items.values()),
                resource_metadata=[{k:r[k] for k in resource_fields if k in r} for r in records])

def reuse_from_main(state,jobs,seal,A,manifest,feature_sha,permit,inventory=None):
    """Rebind exact unchanged completed fits, preserving original provenance."""
    wanted = {A.execution.task_id(t):t for t in jobs}
    entries = inventory['fit_receipts_and_models'] if inventory is not None else seal['fit_receipts_and_models']
    by_path = {str(Path(i['path']).resolve()):i for i in entries}
    for item in entries:
        if item.get('kind') != 'fit_receipt':
            continue
        old = read_json(checked(item))
        if old.get('task_id') not in wanted:
            continue
        t = wanted[old['task_id']]
        require(old['state'] in COMPLETE and old['task'] == asdict(t) and
                old['feature_manifest_sha256'] == seal['feature_manifest_sha256'], 'Main reusable receipt drift')
        if A.execution.reusable(state,t,feature_sha,permit) is not None:
            continue
        b = A.execution.find_bundle(manifest,t if t.variant != '2025_fixed_validation' else A.scheduler.FitTask(t.task,t.origin,t.arm,t.seed)) if t.task != 'lear' else None
        if b:
            require(old['feature_order'] == b['columns'] and old['pruned_names'] == b.get('pruned_names',[]) and old['params'] == A.params(t), 'Main fit recipe/order drift')
        local_receipt = A.execution._receipt_path(state,t)
        bound_copy = local_receipt.exists() and read_json(local_receipt).get('state') in COMPLETE
        record = dict(old,feature_manifest_sha256=feature_sha,design_freeze_sha256=permit.design_freeze_sha256,
                      completed_input_manifest_sha256=permit.completed_input_manifest_sha256,
                      reused_from_main_receipt=item,reuse_no_new_fit=True)
        for what in ('model','prediction'):
            if what == 'model' and t.task == 'lear':
                continue
            path = Path(old[what+'_path']).resolve()
            require(sha(path) == old[what+'_sha256'], 'Main reusable artifact drift')
            if what == 'model':
                require(str(path) in by_path and by_path[str(path)]['sha256'] == old['model_sha256'], 'Reusable model not in sealed/input-bound inventory')
                checked(by_path[str(path)])
            dest = Path(state)/'fits/reused'/path.name
            dest.parent.mkdir(parents=True,exist_ok=True)
            atomic_copy(path,dest,bound=bound_copy)
            record[what+'_path'] = str(dest)
        if t.task == 'lear':
            record['windows'] = [dict(w) for w in old['windows']]
            for window in record['windows']:
                for key,hash_key in (('model_path','model_sha256'),('input_scaling_path','input_imputation_scaling_sha256')):
                    source = Path(window[key]).resolve()
                    require(str(source) in by_path and sha(checked(by_path[str(source)])) == window[hash_key], 'LEAR reuse artifact drift')
                    dest = Path(state)/'fits/reused'/source.name
                    atomic_copy(source,dest,bound=bound_copy)
                    window[key] = str(dest)
        write_json(A.execution._receipt_path(state,t),record,exclusive=True)

def prediction_parity(candidate,sealed):
    candidate,sealed = normalize(candidate),normalize(sealed)
    if not (candidate.columns.tolist() == sealed.columns.tolist() and candidate[KEYS+['target_day']].equals(sealed[KEYS+['target_day']])):
        raise ParityFailure('B0 prediction keys/schema parity failed')
    for name in candidate.columns:
        if name not in KEYS+['target_day']:
            if not bytes_equal(candidate[name].to_numpy(),sealed[name].to_numpy()):
                raise ParityFailure('B0 prediction bytes parity failed: '+name)
    return True

def b0_gate(state,A,manifest,feature_sha,stats,permit,ledger,seal,resources,workers):
    """Two genuine batch-path refits, reused only from this batch on resume."""
    import pandas as pd
    path = Path(state)/'B0_REPRODUCTION.json'
    if path.exists():
        old = read_json(path)
        if old['state'] == 'NOT_RUN_PARITY_FAILED':
            raise ParityFailure('B0 prior missing reference or inequality; frozen terminal refusal')
        if old['state'] == 'DEVIATION':
            raise BatchDeviation('B0 prior terminal execution deviation')
        require(old['state'] == 'PASS' and old['feature_manifest_sha256'] == feature_sha,'B0 feature drift')
        for item in old['artifacts']:
            checked(item)
        return old
    tasks = [A.scheduler.FitTask('news','2026-03-01','M',SEED),
             A.scheduler.FitTask('notice','prewindow_frozen_C_bank','M_notice',SEED)]
    artifacts = []
    try:
        for task in tasks:
            row = run_stage('B0_'+task.task,[task],manifest,feature_sha,stats,permit,state,ledger,A,resources,workers,True)
            if row['state'] == 'DEVIATION':
                write_json(path,dict(state='DEVIATION',reason='A8DEV_RERUN',stage='B0',artifacts=artifacts,
                                    feature_manifest_sha256=feature_sha,failed_stage=identity(Path(state)/'stages'/('B0_'+task.task+'.json'))),exclusive=True)
                raise BatchDeviation('B0 failed after documented resource-only remedy')
            if row['state'] not in COMPLETE:
                raise ResourceStop('B0 required refit incomplete: '+str(row.get('reason')))
            rec = A.execution.reusable(state,task,feature_sha,permit)
            ref = next((i for i in seal['predictions'] if i.get('source') == task.task and i.get('arm') == task.arm and i.get('seed') == SEED and i.get('variant') == 'main'),None)
            if ref is None:
                raise ParityFailure('B0 missing reference: '+task.task+'/'+task.arm)
            sealed = pd.read_parquet(checked(ref))
            if task.task == 'news':
                sealed = sealed[sealed.target_day.astype(str).str[:10] == task.origin]
            prediction_parity(pd.read_parquet(rec['prediction_path']),sealed)
            artifacts += [identity(A.execution._receipt_path(state,task)),identity(rec['model_path']),identity(rec['prediction_path'])]
        # B0 checks immutable base rows only; R8 copies are outside this gate.
        import r8_activity
        unchanged = {}
        for source,arms in {'news':('N','M','L_count','L_chen'),
                            'notice':('N','M_notice','L14','L_Laz','L_chen_notice')}.items():
            for arm in arms:
                task = A.scheduler.FitTask(source,'2026-03-01' if source == 'news' else 'prewindow_frozen_C_bank',arm,SEED)
                bundle = A.execution.find_bundle(manifest,task)
                A.storage.verify_bundle(bundle)
                # Original bundles are immutable pass-through inputs. R8 copies
                # are independently compared by r8_base_gates over all rows.
                unchanged[source+'/'+arm] = r8_activity.base_gate(A.storage,bundle,bundle,bundle['columns'])
        result = dict(state='PASS',feature_manifest_sha256=feature_sha,artifacts=artifacts,
                      batch_refits=2,base_gates=unchanged,unchanged_base_checks=unchanged,
                      base_gate_kind='hash-verified immutable pass-through; not an independent feature comparison',
                      prediction_values_byte_equal=True)
    except ParityFailure as exc:
        write_json(path,dict(state='NOT_RUN_PARITY_FAILED',reason=repr(exc),artifacts=artifacts,
                            feature_manifest_sha256=feature_sha,partial_predictions_eligible_for_scoring=False),exclusive=True)
        raise
    write_json(path,result,exclusive=True)
    return result

def run_stage(name,jobs,manifest,feature_sha,stats,permit,state,ledger,A,resources=(),workers=4,mandatory=False,admitted=False):
    from resource_remedy import retry_count, failure, preserve_failed_artifacts
    e = A.execution
    path = Path(state)/'stages'/(name+'.json')
    ids = [e.task_id(t) for t in jobs]
    count = 0
    if path.exists():
        old = read_json(path)
        require(old['registered_tasks'] == ids and old['feature_manifest_sha256'] == feature_sha, 'Resume stage identity drift')
        if old['state'] in COMPLETE:
            require(all(e.reusable(state,t,feature_sha,permit) is not None for t in jobs if e.task_id(t) in old['eligible_tasks']), 'Completed stage artifact drift')
            return old
        if old['state'] in ('NOT_RUN_BUDGET','NOT_RUN_INPUT_UNAVAILABLE','DEVIATION'):
            return old
        if old['state'] in ('STOPPED_FOR_REMEDY','INCOMPLETE_FAILURE','INCOMPLETE_BUDGET'):
            try:
                count = retry_count(state,name,path)
            except RemedyInterrupted as exc:
                return failure(state,name,path,exc,1,reason='A8DEV_RERUN' if name.startswith(('CS8_','B0_')) else None,registered_tasks=ids,feature_manifest_sha256=feature_sha)
            preserve_failed_artifacts(state,jobs,A,feature_sha,permit)
    rec = dict(stage=name,registered_tasks=ids,feature_manifest_sha256=feature_sha,mandatory=mandatory,
               partial_predictions_eligible_for_scoring=False,budget_before_seconds=ledger.remaining())
    runnable = []
    unavailable = []
    for task in jobs:
        if task.task != 'lear':
            lookup = task if task.variant != '2025_fixed_validation' else A.scheduler.FitTask(task.task,task.origin,task.arm,task.seed)
            b = e.find_bundle(manifest,lookup)
            if b.get('state','COMPLETE') != 'COMPLETE':
                unavailable.append(dict(task_id=e.task_id(task),state=b['state'],reason=b.get('reason')))
                continue
        runnable.append(task)
    rec['unavailable_configurations'] = unavailable
    rec['eligible_tasks'] = [e.task_id(t) for t in runnable]
    missing = [t for t in runnable if e.reusable(state,t,feature_sha,permit) is None]
    records = list(resources)+e._resource_records(state,feature_sha,permit)
    parent = e.anonymous_bytes(os.getpid()) or 0
    needed = estimate_stage(A,missing,records,manifest,parent,workers)
    rec.update(conservative_completion_seconds=needed,reused_jobs=len(runnable)-len(missing),workers_cap=workers)
    if missing and not mandatory and (ledger.remaining() <= 0 or not admitted and (needed is None or needed > ledger.remaining())):
        rec.update(state='INCOMPLETE_CS8_BUDGET' if mandatory else 'NOT_RUN_BUDGET',reason='A8NR_BATCH_BUDGET')
    elif not runnable and unavailable:
        rec.update(state='COMPLETE_WITH_UNAVAILABLE_CONFIGURATIONS',completed_jobs=0,reason='Every registered configuration unavailable under its frozen rule')
    else:
        try:
            with a8_adapter.installed_wave(A,workers):
                e.guard_fit_bank(missing,manifest,state,name)
            groups = {}
            for t in missing:
                groups.setdefault(t.origin,[]).append(t)
            for origin,group in sorted(groups.items()):
                if Path(state).resolve() == (OUT/'state').resolve():
                    if active_fit_jobs():
                        raise OverlapRefusal('Independent fitting job started; stop before launch')
                records = list(resources)+e._resource_records(state,feature_sha,permit)
                projections = {e.task_id(t):e._projected_anonymous(t,records,manifest) for t in group}
                with a8_adapter.installed_wave(A,workers):
                    e._fit_wave(group,name,manifest,feature_sha,stats,permit,state,ContinuationLedger(ledger) if mandatory else ledger,projections)
            require(all(e.reusable(state,t,feature_sha,permit) is not None for t in runnable), 'Stage has missing completed fit')
            rec.update(state='COMPLETE_WITH_UNAVAILABLE_CONFIGURATIONS' if unavailable else 'COMPLETE',completed_jobs=len(runnable))
        except OverlapRefusal:
            raise
        except (A.storage.DiskSpaceError,ResourceStop,OSError,MemoryError,TimeoutError,RuntimeError) as exc:
            # No launch on a pre-fit disk guard is a recoverable resource stop.
            import errno
            if isinstance(exc,TimeoutError) and str(exc) in ('No new fitting launches at the 24-hour deadline','24-hour deadline: unlaunched tasks remain'):
                rec.update(state='NOT_RUN_BUDGET',reason='A8NR_BATCH_BUDGET',eligible_tasks=[],partial_predictions_eligible_for_scoring=False)
                write_json(path,rec)
                return rec
            # Only actual pre-launch disk exhaustion leaves the fit receipt untouched.
            if not count and (isinstance(exc,A.storage.DiskSpaceError) or isinstance(exc,OSError) and exc.errno in (errno.ENOSPC,errno.EDQUOT)):
                raise
            rec = failure(state,name,path,exc,count,reason='A8DEV_RERUN' if name.startswith(('CS8_','B0_')) else None,**rec)
    rec['budget_after_seconds'] = ledger.remaining()
    write_json(path,rec)
    return rec

def host_context(check_overlap=True):
    """Only later explicit --execute entrypoints may call this production reader."""
    require(os.environ.get('A8BATCH_HOST_RUN') == '1', 'Separate coordinator host execution required')
    a8_adapter.install_audit(OUT/'state')  # log verifier opens as well as later adapter reads
    code = a8_freeze.verify()  # MUST precede host_state existence checks/imports.
    require(os.getpriority(os.PRIO_PROCESS,0) >= 10, 'Host execution requires actual nice 10 priority')
    if check_overlap and active_fit_jobs():
        raise OverlapRefusal('Wait until independent fitting jobs have exited')
    bindings = read_json(checked(code['bindings']))
    # T4B was already verified before the seal by a8_freeze.verify().
    A = a8_adapter.load(code['adapter_root'], expected=code['adapter_freeze_sha256'],preverified=True)
    state = OUT/'state'
    a8_adapter.relocate(A,state)
    seal_path = Path(code['adapter_root'])/'host_state/SEAL.json'
    seal = read_json(seal_path)
    require(seal['state'] == 'ALL_REGISTERED_PREDICTIONS_SEALED' and seal['sealed_before_outcome_scoring'], 'Completed main CONF seal required')
    manifest_path = Path(code['adapter_root'])/'host_state/features/manifest.json'
    require(sha(manifest_path) == seal['feature_manifest_sha256'], 'Main seal/feature drift')
    main_permit = A.runtime.validate_permit()
    return A,state,code,bindings,seal_path,seal,manifest_path,main_permit

def host_run(workers=4):
    A,state,code,binding,seal_path,seal,main_manifest_path,main_permit = host_context()
    require(1 <= workers <= 4 or (workers <= 7 and binding.get('memory_guard_allows_more') is True), 'Workers above four require frozen memory-guard authorization')
    with A.execution.exclusive_state(state):
        # A seal is the terminal batch transition. Never reserve, refit or rewrite
        # any bound byte on re-entry (including after an interrupted DLY8 mode 2).
        from batch_export import verify_seal,export_score_inputs
        if (state/'SEAL_A8BATCH.json').exists():
            verify_seal(state)
            return dict(state='SEALED_VERIFIED_STOP',sealed_files_rewritten=False)
        from dly8_rebuild import launch_mode
        production = read_json(main_manifest_path)
        cs8 = cs8_tasks(A,seal)
        author = read_json(checked(binding['author_confirmation'])) if binding['author_confirmation'].get('sha256') else read_json(CONF/'AUTHOR_CONFIRMATION_A8.json')
        require(not code['r8_policy'].get('admission_rule') or author['choices']['r8_seeds'] == 'single','R12b author default requires single seed')
        policy = code['r8_policy']
        a8_adapter.configure_cps(A)
        disk = reserve_batch_disk(state,A,production,cs8,binding,policy,author['choices']['r8_seeds'],workers,main_seal=seal)
        write_json(state/'DISK_RESERVATION.json',disk)
        # Mode 1 is the first prediction operation, in its own measured child.
        launch_mode(1,context=(A,state,code,binding,seal_path,seal,main_manifest_path,main_permit))
        inventory = main_reuse_inventory(main_manifest_path.parents[1],[t for jobs in cs8.values() for t in jobs],seal,A,main_permit)
        input_path = state/'BATCH_INPUT_FREEZE.json'
        inputs = dict(state='A8BATCH_INPUTS_BOUND',conf_seal=identity(seal_path),
                      main_manifest=identity(main_manifest_path),code_freeze=identity(OUT/'CODE_FREEZE.json'),
                      adapter_freeze_sha256=code['adapter_freeze_sha256'],main_adapter_binding=code['main_adapter_binding'],bindings=code['bindings'],
                      t4b=identity(OUT/'T4B_BINDING.json'),r8_policy=policy,r8_seeds=author['choices']['r8_seeds'],main_completed_fit_inventory=inventory)
        if input_path.exists():
            old = read_json(input_path)
            require(all(old[k] == v for k,v in inputs.items()), 'Main seal/batch input identity drift')
        else:
            write_json(input_path,inputs,exclusive=True)
        production = read_json(main_manifest_path)
        feature_path = state/'features/manifest.json'
        if feature_path.exists():
            manifest = read_json(feature_path)
        else:
            import r8_activity as r8
            import cps8_runner as cps
            manifest = dict(production,bundles=list(production['bundles']))
            if policy['run']:
                sources = binding['metadata']
                bound = {i['sha256'] for i in code['external_files']}
                require(all(i['sha256'] in bound for i in [*sources['news_manifests'],sources['notice_scope']]),'Metadata source not pre-bound')
                from resource_remedy import retry_count,failure
                build_failure = state/'stages/R8_build.json'
                try:
                    build_count = retry_count(state,'R8_build',build_failure)
                except RemedyInterrupted as exc:
                    failure(state,'R8_build',build_failure,exc,1,reason=None)
                    build_count = 1
                try:
                    if build_failure.exists() and read_json(build_failure)['state'] == 'DEVIATION':
                        raise RemedyInterrupted('R8 build terminal deviation')
                    records = {'news':r8.read_news(sources['news_manifests']),
                               'notice':r8.read_notices(sources['notice_scope'],sources['notice_type_map'])}
                    attempt = state/'features/r8/attempts'/__import__('uuid').uuid4().hex
                    manifest = r8.build_bundles(production,attempt,A,records,sources,write_json,identity)
                except OverlapRefusal:
                    raise
                except Exception as exc:
                    failure(state,'R8_build',build_failure,exc,build_count,reason=None)
                    # R8 source/schema/census/disk failure cannot disable base B0/B1.
                    manifest['r8_build_failure'] = repr(exc)
                    for source,arms in (('news',R8_NEWS),('notice',R8_NOTICE)):
                        manifest['bundles'] += [dict(source=source,arm=a,variant='main',state='NOT_RUN_INPUT_UNAVAILABLE',
                                                     reason='R8 build failure: '+repr(exc)) for a in arms]
            manifest = cps.add_bundles(manifest,binding['cps8'])
            write_json(feature_path,manifest,exclusive=True)
        feature_freeze = state/'FEATURE_FREEZE.json'
        if not feature_freeze.exists():
            write_json(feature_freeze,dict(manifest=identity(feature_path),inputs=identity(input_path)),exclusive=True)
        frozen = read_json(feature_freeze)
        checked(frozen['manifest'])
        checked(frozen['inputs'])
        # Worker binding is a separate immutable launch receipt (input receipt
        # stays unchanged, so FEATURE_FREEZE has no self-referential hash).
        launch_path = state/'WORKER_BINDING.json'
        write_json(launch_path,dict(inputs=identity(input_path),feature_freeze=identity(feature_freeze),
                   adapter_root=code['adapter_root'],adapter_freeze_sha256=code['adapter_freeze_sha256'],
                   hashes=[identity(input_path),identity(feature_freeze),*a8_adapter.runtime_hashes(code)]),exclusive=True)
        permit = A.guard.ExecutionPermit('A8BATCH',main_permit.design_freeze_sha256,sha(feature_freeze),True)
        feature_sha = sha(feature_path)
        stats = stats_for(manifest,A)
        a8_adapter.configure_cps(A)
        ledger = A.execution.WallLedger(state)
        resources = inventory['resource_metadata']
        try:
            b0_gate(state,A,manifest,feature_sha,stats,permit,ledger,seal,resources,workers)
        except (ParityFailure,BatchDeviation) as exc:
            terminal_parity_seals(state,exc)
            return dict(state='DEVIATION' if isinstance(exc,BatchDeviation) else 'NOT_RUN_PARITY_FAILED')
        all_tasks = dict(cs8)
        all_tasks.update(r8_tasks(A,list(A.scheduler.days()),author['choices']['r8_seeds']))
        reuse_from_main(state,[t for name,jobs in all_tasks.items() if name.startswith('CS8_') for t in jobs],seal,A,manifest,feature_sha,permit,inventory)
        dispositions = {}
        for name in [*cs8,*(['R8_notice'] if policy['run'] and not manifest.get('r8_build_failure') else [])]:
            dispositions[name] = run_stage(name,all_tasks[name],manifest,feature_sha,stats,permit,state,ledger,A,resources,workers,True)
            if dispositions[name]['state'] not in (*COMPLETE,'DEVIATION'):
                raise ResourceStop('Mandatory stage '+name+' stopped before export; record a resource-only remedy and resume')
            if name.startswith('CS8_'):
                original = next(r for r in seal['stage_dispositions'] if r['stage'] == name[4:])
                dispositions[name]['rerun_trigger'] = rerun_trigger(original)
                dispositions[name]['main_chain_reason'] = original.get('error',original.get('reason',original['state']))
                write_json(state/'stages'/(name+'.json'),dispositions[name])
        if not policy['run'] or manifest.get('r8_build_failure'):
            for name in ('R8_notice','R8_news','R8_news_seeds'):
                if name in all_tasks:
                    dispositions[name] = unavailable_r8(state,name,all_tasks[name],feature_sha,A,policy,manifest.get('r8_build_failure'))
        import cps8_runner as cps
        main_wall = next(i for i in seal['auxiliary_sources_and_resources'] if i.get('kind') == 'wall_fitting_ledger')
        rho_path = state/'RHO.json'
        if not rho_path.exists():
            write_json(rho_path,dict(rho=rho_from_ledger(read_json(checked(main_wall))),wall_ledger=main_wall,
                                   conf_seal=identity(seal_path)),exclusive=True)
        rho_record = read_json(rho_path)
        require(rho_record['conf_seal'] == identity(seal_path) and rho_record['wall_ledger'] == main_wall, 'Rho input drift')
        rho = rho_record['rho']
        candidates = {'CPS8':cps.selection_tasks(A)}
        if policy['run'] and not policy.get('admission_rule') and not manifest.get('r8_build_failure'):
            candidates['R8_news'] = all_tasks['R8_news']
        if 'R8_news' in candidates and 'R8_news_seeds' in all_tasks:
            candidates['R8_news_seeds'] = all_tasks['R8_news_seeds']
        # Each stage's largest-arm first fit is charged even if admission later drops the stage.
        admission_path = state/'OPTIONAL_ADMISSION.json'
        if not admission_path.exists():
            estimates = {'PCX_extension':pcx_estimate(rho)}
            for name,jobs in candidates.items():
                try:
                    pilot = counted_pilot(name,jobs,manifest,feature_sha,stats,permit,state,ledger,A,resources,workers)
                    if pilot is None and (state/'stages'/(name+'.json')).exists() and read_json(state/'stages'/(name+'.json'))['state'] == 'NOT_RUN_BUDGET':
                        estimates[name] = 0.
                        all_tasks[name] = jobs
                        dispositions[name] = read_json(state/'stages'/(name+'.json'))
                        continue
                    if pilot is None:
                        estimates[name] = 0.
                        all_tasks[name] = []
                        dispositions[name] = dict(stage=name,state='DEVIATION',reason=None,
                             registered_tasks=[A.execution.task_id(t) for t in jobs],eligible_tasks=[],
                             partial_predictions_eligible_for_scoring=False,
                             pilot_failure=identity(state/'stages'/('counted_pilot__'+name+'.json')))
                        write_json(state/'stages'/(name+'.json'),dispositions[name],exclusive=True)
                        continue
                    rec = A.execution.reusable(state,pilot,feature_sha,permit)
                    planned = {'CPS8':{'news':15,'notice':16},'R8_news':{'news':1075},'R8_news_seeds':{'news':1284}}[name]
                    estimated_jobs = jobs
                    if name == 'CPS8':
                        estimated_jobs = jobs+cps.d_tasks(A,{'selected':{s+'/'+a:'g1' for s,arms in cps.ARMS.items() for a in arms}})
                    estimates[name] = 1.25*rec['runtime_seconds']*estimate_rounds(A,estimated_jobs,[*resources,rec],manifest,A.execution.anonymous_bytes(os.getpid()) or 0,workers)
                except (A.storage.DiskSpaceError,ResourceStop,OSError):
                    raise
                except (TimeoutError,RuntimeError,MemoryError) as exc:
                    raise ResourceStop('Pilot failed; no budget admission may be written: '+name) from exc
            write_json(admission_path,optional_admission(ledger.remaining(),estimates,rho=rho),exclusive=True)
        admission = read_json(admission_path)
        require(admission['drop_order'] == list(DROP_ORDER) and admission['rho'] == rho, 'Optional admission drift')
        estimates = dict(admission['metadata_only_estimates_seconds'])
        if policy.get('admission_rule'):
            estimates.update(R8_news=0.,R8_news_seeds=0.)
        for name in candidates:
            terminal = state/'stages'/(name+'.json')
            if terminal.exists() and read_json(terminal)['state'] == 'DEVIATION':
                all_tasks[name] = []
                dispositions[name] = read_json(terminal)
        decisions = {}
        def admit(name,finished=()):
            path = state/'admissions'/(name+'.json')
            if path.exists():
                row = read_json(path)
            else:
                row = reservation_decision(name,ledger.remaining(),estimates,finished=finished,rho=rho)
                write_json(path,row,exclusive=True)
            decisions[name] = row
            return row['admitted']
        # B3 precedes B4/B5 even though its drop priority is lower.
        if 'CPS8' in dispositions:
            pass  # terminal pilot deviation is never relabelled as a budget drop
        elif (state/'stages/CPS8.json').exists() and read_json(state/'stages/CPS8.json')['state'] in ('DEVIATION','NOT_RUN_BUDGET'):
            all_tasks['CPS8'] = []
            dispositions['CPS8'] = read_json(state/'stages/CPS8.json')
        elif admit('CPS8'):
            def stage(*args):
                return run_stage(*args,workers=workers,admitted=True)
            from resource_remedy import retry_count,failure
            try:
                cps_count = retry_count(state,'CPS8',state/'stages/CPS8.json')
            except RemedyInterrupted as exc:
                dispositions['CPS8'] = failure(state,'CPS8',state/'stages/CPS8.json',exc,1,reason=None,registered_tasks=[])
                cps_count = 1
            try:
                if 'CPS8' in dispositions:
                    raise RemedyInterrupted('Aggregate CPS8 remedied attempt interrupted')
                cps_jobs,cps_dispositions = cps.run(state,A,manifest,feature_sha,stats,permit,ledger,stage,resources,inputs['code_freeze'])
                for name in ('CPS8_selection_news','CPS8_selection_notice'):
                    all_tasks[name] = [t for t in cps.selection_tasks(A) if t.task == ('news' if name.endswith('news') else 'notice')]
                    dispositions[name] = read_json(state/'stages'/(name+'.json'))
                for name,row in cps_dispositions.items():
                    all_tasks[name] = [t for t in cps_jobs if t.task == ('news' if name.endswith('news') else 'notice')]
                    dispositions[name] = row
            except OverlapRefusal:
                raise
            except ResourceStop:
                raise  # run_stage already recorded the stage-specific remedy
            except (A.storage.DiskSpaceError,OSError,MemoryError,TimeoutError,RuntimeError) as exc:
                from resource_remedy import retry_count,failure
                # A stopped budget child makes the whole CPS8 family not run, never a partial score.
                children = [read_json(p) for p in (state/'stages').glob('CPS8_*.json')]
                if isinstance(exc,TimeoutError) or any(r['state'] == 'NOT_RUN_BUDGET' for r in children):
                    all_tasks['CPS8'] = []
                    dispositions['CPS8'] = not_run_stage(state,'CPS8',[],feature_sha,A,ledger=ledger)
                    count = None
                else:
                    count = 1 if any(r['state'] == 'DEVIATION' for r in children) else cps_count
                if count is not None:
                    all_tasks['CPS8'] = []
                    dispositions['CPS8'] = failure(state,'CPS8',state/'stages/CPS8.json',exc,count,reason=None,registered_tasks=[])
        else:
            all_tasks['CPS8'] = []
            dispositions['CPS8'] = not_run_stage(state,'CPS8',[],feature_sha,A,ledger=ledger)
        for name in ('R8_news','R8_news_seeds'):
            if name not in all_tasks or name in dispositions:
                continue
            if name == 'R8_news_seeds' and dispositions['R8_news']['state'] not in COMPLETE:
                dispositions[name] = unavailable_r8(state,name,all_tasks[name],feature_sha,A,policy,
                                                    'Required R8 news stage did not complete',prerequisite_state=dispositions['R8_news']['state'])
                continue
            if policy.get('admission_rule'):
                from r8_admission import record_decision
                if name == 'R8_news_seeds':
                    dispositions[name] = not_run_stage(state,name,all_tasks[name],feature_sha,A,reason='A8NR_AUTHOR')
                else:
                    decision = record_decision(state,ledger,rho,binding['r8_time_projection'])
                    dispositions[name] = (run_stage(name,all_tasks[name],manifest,feature_sha,stats,permit,state,ledger,A,resources,workers,mandatory=True,admitted=True)
                        if decision['admitted'] else not_run_stage(state,name,all_tasks[name],feature_sha,A,reason='A8NR_RESOURCE_A8AM2'))
                continue
            dispositions[name] = (run_stage(name,all_tasks[name],manifest,feature_sha,stats,permit,state,ledger,A,resources,workers,admitted=True)
                                  if admit(name,finished=('CPS8','R8_news') if name == 'R8_news_seeds' else ('CPS8',)) and
                                     (name != 'R8_news_seeds' or dispositions['R8_news']['state'] in COMPLETE) else not_run_stage(state,name,all_tasks[name],feature_sha,A))
        pcx_ok = admit('PCX_extension',finished=('CPS8','R8_news','R8_news_seeds')) if rho < 1.5 else False
        write_json(state/'PCX_ADMISSION.json',dict(state='PENDING_A8NR_SPEED' if rho >= 1.5 else 'ADMITTED' if pcx_ok else 'NOT_RUN_A8NR_BATCH_BUDGET',rho=rho,
                   estimate_seconds=pcx_estimate(rho),ledger=identity(ledger.path),
                   charge_to_ledger=str(ledger.path),postscore_host_order=['A2LABEL','KCX','PC','PCX_extension']),exclusive=True)
        write_json(state/'RESOURCE_RECEIPT.json',dict(budget_seconds=A.execution.BUDGET,fitting_seconds=ledger.elapsed(),
                   remaining_seconds=ledger.remaining(),worker_cap=workers,drop_order=list(DROP_ORDER),production_score_performed=False))
        from batch_export import create_seal,export_score_inputs
        create_seal(state,A,manifest,all_tasks,dispositions,permit,seal_path,feature_freeze)
        launch_mode(2,context=(A,state,code,binding,seal_path,seal,main_manifest_path,main_permit))
        export_score_inputs(state)

def finish_sealed():
    """Repair only absent DLY8 mode-2/export receipts after an interrupted seal."""
    context = host_context()
    A,state = context[:2]
    with A.execution.exclusive_state(state):
        from batch_export import verify_seal,export_score_inputs
        verify_seal(state)
        from dly8_rebuild import launch_mode
        launch_mode(2,context)
        return export_score_inputs(state)

def plan_only(workers=4):
    """After T4B/main seal: read resource identities/shapes, no fits or binding writes."""
    A,state,code,binding,seal_path,seal,manifest_path,permit = host_context(check_overlap=False)
    production = read_json(manifest_path)
    author = read_json(CONF/'AUTHOR_CONFIRMATION_A8.json')
    a8_adapter.configure_cps(A)
    return reserve_batch_disk(state,A,production,cs8_tasks(A,seal),binding,code['r8_policy'],author['choices']['r8_seeds'],workers,check_space=False,main_seal=seal)

def sum_estimates(estimates,factor=1.):
    return None if any(e is None for e in estimates) else factor*sum(estimates)

def not_run_stage(state,name,jobs,feature_sha,A,reason='A8NR_BATCH_BUDGET',ledger=None):
    rec = dict(stage=name,state='NOT_RUN_BUDGET',reason=reason,
               registered_tasks=[A.execution.task_id(t) for t in jobs],feature_manifest_sha256=feature_sha,
               eligible_tasks=[],partial_predictions_eligible_for_scoring=False)
    path = Path(state)/'stages'/(name+'.json')
    if path.exists():
        old=read_json(path)
        if old.get('state')=='NOT_RUN_BUDGET':
            require(all(old.get(k)==v for k,v in rec.items()), 'Bound budget disposition drift')
            return old
        require(name=='CPS8' and old.get('state')=='STOPPED_FOR_REMEDY' and old.get('remedy_count')==0
                and reason=='A8NR_BATCH_BUDGET', 'Only stopped CPS8 aggregate can transition to budget terminal')
        require(not (Path(state)/'SEAL_A8BATCH.json').exists(), 'Sealed stage is immutable')
        used=Path(state)/'remedies_used/CPS8.json';started=Path(state)/'remedied_attempts/CPS8.json'
        require(used.is_file() and started.is_file() and ledger is not None, 'Consumed unique CPS8 remedy and charged ledger required')
        failure_id=identity(path);u=read_json(used);marker=read_json(started)
        require(u['remedy_count']==1 and u['failure']==failure_id and marker['failure']==failure_id
                and u['remedy']==marker['remedy'], 'CPS8 remedy/failure/marker drift')
        checked(u['remedy'])  # the consumed log identity remains preserved in used
        retained=Path(state)/'retained_budget/CPS8_STOPPED_FOR_REMEDY.json'
        atomic_copy(path,retained,bound=True)
        snapshot=Path(state)/'retained_budget/CPS8_FITTING_LEDGER.json'
        atomic_copy(ledger.path,snapshot,bound=True)
        rec.update(budget_transition=dict(previous=failure_id,retained_previous=identity(retained),
             remedy_used=identity(used),consumed_marker=identity(started),ledger_snapshot=identity(snapshot),
             charged_seconds=ledger.elapsed(),remaining_seconds=ledger.remaining(),remedy_count=1))
        write_json(path,rec)  # revision retained; admission, markers and seal are never rewritten
    else:
        write_json(path,rec,exclusive=True)
    return rec

def unavailable_r8(state,name,jobs,feature_sha,A,policy,failure=None,prerequisite_state=None):
    from a8_amendment2 import REASON,RENDERING
    budget = prerequisite_state in ('NOT_RUN_BUDGET','INCOMPLETE_BUDGET')
    row = dict(stage=name,state='NOT_RUN_A8_AMENDMENT_2' if not policy['run'] else 'NOT_RUN_BUDGET' if budget else 'DEVIATION',
               reason=policy.get('reason',REASON) if not policy['run'] else 'A8NR_BATCH_BUDGET' if budget else None,detail=failure,
               prerequisite_state=prerequisite_state,
               rendering=RENDERING if not policy['run'] else 'R8 build unavailable',
               registered_tasks=[A.execution.task_id(t) for t in jobs],feature_manifest_sha256=feature_sha,
               eligible_tasks=[],partial_predictions_eligible_for_scoring=False)
    write_json(Path(state)/'stages'/(name+'.json'),row,exclusive=True)
    return row

def reserve_batch_disk(state,A,production,cs8,binding,policy,seeds,workers,check_space=True,main_seal=None):
    from cps8_runner import add_bundles,selection_tasks,d_tasks,ARMS
    manifest = add_bundles(production,binding['cps8'])
    stages = dict(cs8)
    stages['B0'] = [A.scheduler.FitTask('news','2026-03-01','M',SEED),A.scheduler.FitTask('notice','prewindow_frozen_C_bank','M_notice',SEED)]
    stages['CPS8'] = selection_tasks(A)+d_tasks(A,{'selected':{s+'/'+a:'g2' for s,arms in ARMS.items() for a in arms}})
    r8_bytes = 0
    existing_manifest = Path(state)/'features/manifest.json'
    existing_r8 = read_json(existing_manifest) if existing_manifest.exists() else None
    if policy['run']:
        # Metadata-only conservative upper bound; no R8 source values are read.
        for source,arms in (('news',R8_NEWS),('notice',R8_NOTICE)):
            bases = [b for b in production['bundles'] if b['source'] == source and b.get('variant','main') == 'main' and b.get('state','COMPLETE') == 'COMPLETE']
            base = max(bases,key=lambda b:len(b['columns']))
            width = len(base['columns'])+64+len(binding['metadata'].get('notice_training_types',[]))
            for arm in arms:
                saved = next((b for b in (existing_r8 or {}).get('bundles',[]) if
                              b['source'] == source and b['arm'] == arm and b.get('variant','main') == 'main'),None)
                if saved is not None:
                    if saved.get('state','COMPLETE') == 'COMPLETE': verify_bundle(saved,A)
                    manifest['bundles'].append(saved)
                else:
                    manifest['bundles'].append(dict(base,arm=arm,columns=['reserve_'+str(i) for i in range(width)],matrix=dict(shape=[base['rows'],width])))
                    r8_bytes += base['rows']*width*4
        stages.update(r8_tasks(A,list(A.scheduler.days()),seeds))
    for name in list(stages):
        terminal = Path(state)/'stages'/(name+'.json')
        if terminal.exists() and read_json(terminal).get('state') in ('DEVIATION','NOT_RUN_BUDGET','NOT_RUN_A8_AMENDMENT_2','NOT_RUN_PARITY_FAILED'):
            stages[name] = []  # terminal stages allocate neither refits nor sealed predictions
    # Count each task once and omit only hash-checked completed batch receipts.
    # Existing failed evidence still consumes free space; never subtract it.
    tasks = {A.execution.task_id(t):t for jobs in stages.values() for t in jobs}
    remaining = []
    for ident,t in tasks.items():
        rp = A.execution._receipt_path(state,t)
        completed = False
        if rp.exists():
            rec = read_json(rp)
            completed = rec.get('state') == 'COMPLETE' and rec.get('task') == asdict(t)
            if completed:
                for what in ('model','prediction') if t.task != 'lear' else ('prediction',):
                    completed = completed and sha(rec[what+'_path']) == rec[what+'_sha256']
        if not completed:
            remaining.append(t)
    calibration = {}
    if main_seal is not None:
        artifacts = {i['path']:i for i in main_seal['fit_receipts_and_models']}
        for item in main_seal['fit_receipts_and_models']:
            if item.get('kind') != 'fit_receipt': continue
            rec = read_json(checked(item))
            if rec.get('state') not in COMPLETE or not rec.get('model_path'): continue
            model = artifacts.get(rec['model_path'])
            if model is None: continue
            task = A.scheduler.FitTask(**rec['task'])
            params = A.params(task)
            denom = params['n_estimators']*params['num_leaves']
            calibration[task.task] = max(calibration.get(task.task,0.),model['bytes']/denom)
    A.model_serialization_rates = calibration
    persistent = 0; scratch = 0; grouped = []
    for source in {t.task for t in remaining}:
        eligible = [t for t in remaining if t.task == source and (source == 'lear' or
                    A.execution.find_bundle(manifest,t if t.variant != '2025_fixed_validation' else A.scheduler.FitTask(t.task,t.origin,t.arm,t.seed)).get('state','COMPLETE') == 'COMPLETE')]
        if not eligible:
            continue
        with a8_adapter.installed_wave(A,workers):
            plan = A.execution.fit_disk_plan(eligible,manifest)
        # Installed disk planner treats all news queries as 72 rows. CPS8's
        # actual selection and D schedules have 42*7*72 and 214*72 rows.
        correction = sum((42*7*72-72 if t.variant == 'cps8_selection' else
                          214*72-72 if t.variant == 'cps8_D' else 0)*192
                         for t in eligible if t.task == 'news')
        correction += sum(max(0,int(A.execution.find_bundle(manifest,t)['train_rows'])-
                              (A.execution.find_bundle(manifest,t)['rows']-int(A.execution.find_bundle(manifest,t)['train_rows'])))*192
                          for t in eligible if t.task == 'notice' and t.variant == 'cps8_selection')
        persistent += plan['persistent_output_bytes']+correction
        scratch = max(scratch,plan['peak_scratch_bytes'])
        groups = {}
        for task in eligible:
            groups.setdefault((task.task,task.origin),[]).append(task)
        # Each possible worker-sized wave gets a bounded event, not a final-ledger copy.
        for group in groups.values():
            grouped.extend([group[i:i+workers] for i in range(0,len(group),workers)] if source == 'news' else [[t] for t in group])
    notices = [b for b in manifest['bundles'] if b['source'] == 'notice' and b['arm'] in (*PRIMARY_NOTICE,*(R8_NOTICE if policy['run'] else ())) and b.get('variant','main') == 'main']
    from dly8_rebuild import dly_root
    dly = 0
    for mode,arms in ((1,PRIMARY_NOTICE),(2,R8_NOTICE if policy['run'] else ())):
        receipt = dly_root(state)/('mode'+str(mode))/'DLY8_RECEIPT.json'
        if receipt.exists() or not arms:
            continue  # immutable terminal outputs already occupy disk, no new allocation
        scope = [b for b in notices if b['arm'] in arms]
        dly += 4*sum(527040*len(b['columns'])*4+256 for b in scope)+3*527040*192*len(scope)
    # Upper bound for event payloads: per-wave fixed fields/workers/float text
    # 16384 bytes + exact escaped, serialized task list; begin+finish+recovery.
    # One additional failed/remedy attempt per stage is included (factor 2).
    event_bounds = [16384+len(json.dumps([asdict(t) for t in group],ensure_ascii=False).encode()) for group in grouped]
    events = 2*3*sum(event_bounds)+5*16384  # optional pilot and PCX events
    live = Path(state)/'FITTING_WALL_LEDGER.json'
    existing = live.stat().st_size if live.exists() else 0
    ledger_final = existing+65536+2*sum(event_bounds)+5*16384
    revisions = events+ledger_final  # incremental events + final live ledger, no quadratic copies
    overhead = 1024**3+527040*max(2048,int(getattr(A.features,'AUXILIARY_BYTES_PER_PANEL_ROW',2048)))
    cache = dly_root(state)/'embedding_cache'
    cache_existing = sum(p.stat().st_size for p in cache.rglob('*') if p.is_file()) if cache.exists() else 0
    overhead = max(1024**3,overhead-cache_existing)
    # Sealing copies predictions only, never models or per-fit JSON receipts.
    prediction_copies = 0
    copied_ids = {A.execution.task_id(t) for name,jobs in stages.items() if name != 'B0' for t in jobs
                  if t.variant != 'cps8_selection'}
    for source in {t.task for t in tasks.values()}:
        eligible = [t for t in tasks.values() if t.task == source and (source == 'lear' or
                    A.execution.find_bundle(manifest,t if t.variant != '2025_fixed_validation' else A.scheduler.FitTask(t.task,t.origin,t.arm,t.seed)).get('state','COMPLETE') == 'COMPLETE')]
        if eligible:
            for task in eligible:
                if A.execution.task_id(task) not in copied_ids: continue
                if task.task == 'lear':
                    rows = 72
                elif task.task == 'notice':
                    bundle = A.execution.find_bundle(manifest,task)
                    rows = bundle['rows']-int(bundle['train_rows'])
                    if task.variant == 'cps8_selection': rows = max(rows,int(bundle['train_rows']))
                else:
                    rows = (365*72 if task.variant == '2025_fixed_validation' else
                            42*7*72 if task.variant == 'cps8_selection' else
                            214*72 if task.variant == 'cps8_D' else 72)
                prediction_copies += 65536+rows*192
    from cps8_runner import cps_root
    sealed_existing = sum(p.stat().st_size for root in (Path(state)/'sealed',cps_root(state)/'sealed')
                          for p in root.glob('*.parquet'))
    sealed_copies = max(0,prediction_copies-sealed_existing)
    planned = persistent+sealed_copies+scratch+r8_bytes+dly+overhead+revisions
    if check_space:
        probe = A.storage.require_disk_space(state,planned,3*1024**3,'A8BATCH remaining batch reservation')
    else:
        usage = shutil.disk_usage(state if Path(state).exists() else OUT)
        probe = dict(free_bytes=usage.free,planned_bytes=planned,headroom_bytes=3*1024**3,required_bytes=planned+3*1024**3,admitted=usage.free >= planned+3*1024**3)
    probe['model_bytes_per_leaf_metadata'] = calibration
    return dict(probe,fit_persistent_bytes=persistent,sealed_copy_reserve_bytes=sealed_copies,
                peak_transient_scratch_bytes=scratch,r8_bundle_bytes=r8_bytes,dly8_bytes=dly,
                cache_and_receipt_reserve_bytes=overhead,ledger_revision_reserve_bytes=revisions,
                ledger_event_reserve_bytes=events,planned_wave_bound=len(grouped)+5,
                event_payload_bounds=event_bounds,ledger_final_byte_bound=ledger_final,
                remaining_jobs=len(remaining),registered_unique_jobs=len(tasks),R8_run=policy['run'],
                rule='remaining batch bytes + 3 GiB; linear ledger events; sealed host command verifies and stops')

def terminal_parity_seals(state,exc):
    """B0 parity refusal produces terminal identities for T5, without any fits."""
    from dly8_rebuild import dly_root
    inputs = read_json(Path(state)/'BATCH_INPUT_FREEZE.json')
    deviation = isinstance(exc,BatchDeviation)
    terminal_state = 'DEVIATION' if deviation else 'NOT_RUN_PARITY_FAILED'
    terminal_reason = 'A8DEV_RERUN' if deviation else 'A8NR_PARITY'
    seal_path = Path(state)/'SEAL_A8BATCH.json'
    if seal_path.exists():
        from batch_export import verify_seal
        old = verify_seal(state)
        require(old.get('batch_state') == terminal_state and old['conf_seal'] == inputs['conf_seal'],
                'Prior terminal parity seal binding drift')
        seal_r8 = read_json(dly_root(state)/'DLY8_SEAL_R8.json')
        checked(seal_r8['receipt'])
        require(seal_r8['source_seal'] == identity(seal_path),'Prior terminal DLY8 seal drift')
        return old
    main = read_json(checked(inputs['conf_seal']))
    names = ['R8_notice','R8_news']+(['R8_news_seeds'] if inputs.get('r8_seeds') == 'three' else [])+['CPS8']+[
        'CS8_'+r['stage'] for r in main['stage_dispositions'] if r['stage'] in CS8_ORDER and rerun_eligible(r)]
    A = a8_adapter._loaded
    require(A is not None,'Terminal parity records require the already verified parent adapter')
    from cps8_runner import selection_tasks
    registered = r8_tasks(A,list(A.scheduler.days()),inputs.get('r8_seeds','single'))
    registered['CPS8'] = selection_tasks(A)
    rows = [dict(stage=n,state=terminal_state,reason=terminal_reason if n.startswith('CS8_') or not deviation else None,eligible_tasks=[],registered_tasks=[],
                 partial_predictions_eligible_for_scoring=False) for n in names]
    for row in rows:
        if row['stage'].startswith('CS8_'):
            original = next(r for r in main['stage_dispositions'] if r['stage'] == row['stage'][4:])
            row.update(registered_tasks=original['registered_tasks'],rerun_trigger=rerun_trigger(original),
                       main_chain_reason=original.get('error',original.get('reason',original['state'])))
        else:
            row['registered_tasks'] = [A.execution.task_id(t) for t in registered[row['stage']]]
    if not inputs.get('r8_policy',{'run':True})['run']:
        from a8_amendment2 import REASON,RENDERING
        for row in rows:
            if row['stage'].startswith('R8'):
                row.update(state='NOT_RUN_A8_AMENDMENT_2',reason=inputs['r8_policy'].get('reason',REASON),rendering=RENDERING)
    value = dict(state='ALL_A8BATCH_REGISTERED_PREDICTIONS_SEALED',sealed_utc=now(),sealed_before_outcome_scoring=True,
                 conf_seal=inputs['conf_seal'],conf_seal_sha256=inputs['conf_seal']['sha256'],code_freeze=inputs['code_freeze'],
                 adapter_freeze_sha256=inputs['adapter_freeze_sha256'],feature_manifest_path=str(Path(state)/'features/manifest.json'),
                 feature_manifest_sha256=sha(Path(state)/'features/manifest.json'),fit_receipts_and_models=[],predictions=[],
                 stage_dispositions=rows,auxiliary=[identity(Path(state)/'B0_REPRODUCTION.json')],truth_panels=read_json(checked(inputs['conf_seal']))['truth_panels'],
                 outcome_scoring_performed=False,partial_predictions_scored=False,batch_state=terminal_state,
                 reason=terminal_reason)
    for row in rows:
        p = Path(state)/'stages'/(row['stage']+'.json')
        write_json(p,row,exclusive=True)
        row['receipt_identity'] = identity(p)
    write_json(Path(state)/'SEAL_A8BATCH.json',value,exclusive=True)
    receipt = dly_root(state)/'mode2/DLY8_RECEIPT.json'
    write_json(receipt,dict(state=terminal_state if inputs.get('r8_policy',{'run':True})['run'] else 'NOT_RUN_A8_AMENDMENT_2',reason=terminal_reason if inputs.get('r8_policy',{'run':True})['run'] else inputs['r8_policy'].get('reason','A8NR_RESOURCE_A8AM2'),
              rendering=None if inputs.get('r8_policy',{'run':True})['run'] else 'registered before scoring but not run',predictions=[],parity=None,models_refitted=0,
              binding=dict(main_conf_seal=inputs['conf_seal'],source_seal=identity(Path(state)/'SEAL_A8BATCH.json'))),exclusive=True)
    write_json(dly_root(state)/'DLY8_SEAL_R8.json',dict(state='DLY8_SEALED_BEFORE_SCORING',receipt=identity(receipt),
               conf_seal_sha256=inputs['conf_seal']['sha256'],source_seal=identity(Path(state)/'SEAL_A8BATCH.json'),
               adapter_freeze_sha256=inputs['adapter_freeze_sha256']),exclusive=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--plan-only',action='store_true')
    parser.add_argument('--finish-sealed',action='store_true')
    args = parser.parse_args()
    if args.plan_only:
        print(json.dumps(plan_only(args.workers),sort_keys=True,indent=2))
        raise SystemExit(0)
    if args.finish_sealed:
        finish_sealed()
        raise SystemExit(0)
    require(args.execute, 'Production fits require the separate explicit host --execute action')
    try:
        host_run(args.workers)
    except Exception as exc:
        state = 'NOT_RUN_PARITY_FAILED' if isinstance(exc,ParityFailure) else 'STOPPED_FOR_REMEDY' if isinstance(exc,(ResourceStop,MemoryError,OSError)) or isinstance(exc,RuntimeError) and 'Disk space guard' in str(exc) else 'A8BATCH_DEVIATION_OR_IDENTITY_REFUSAL'
        write_json(OUT/'state/BATCH_STATUS.json',dict(state=state,reason=repr(exc),
                   partial_predictions_eligible_for_scoring=False,outcome_scoring_performed=False))
        if isinstance(exc,(ParityFailure,BatchDeviation)):
            terminal_parity_seals(OUT/'state',exc)
        raise
