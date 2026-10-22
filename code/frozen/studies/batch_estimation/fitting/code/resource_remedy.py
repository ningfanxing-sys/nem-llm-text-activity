"""One documented resource-only remedy per stage; no unbounded retry loop."""
from a8_common import *

MAX_REMEDIES = 1
CLAUSE = ('An execution failure after the documented resource-only remedy (a restart of the same batch command after\n'
          'freeing memory or disk, reusing completed fits, logged in `A8BATCH/REMEDY_LOG.md`) is a deviation, never a null or a\n'
          'partial score')

def retry_count(state, name, failure_path):
    """Bind a single remedy to this stage and this exact failed-attempt receipt."""
    state, failure_path = Path(state), Path(failure_path)
    if not failure_path.exists():
        return 0
    failed = read_json(failure_path)
    if failed.get('state') in ('DEVIATION', 'A8DLY_DEV'):
        return MAX_REMEDIES
    require(failed.get('remedy_count', 0) == 0, 'Remedy limit exceeded: '+name)
    started = state/'remedied_attempts'/(name+'.json')
    if started.exists():
        raise RemedyInterrupted('Killed or interrupted remedied attempt: '+name)
    remedy = state/'remedies'/(name+'.json')
    if not remedy.exists():
        remedy = state/'RESOURCE_REMEDY.json'
    log = OUT/'REMEDY_LOG.md'
    if not remedy.is_file() or not log.is_file():
        raise ResourceStop('Document resource-only remedy for '+name+' before retry')
    row = read_json(remedy)
    require(row.get('stage') == name and row.get('failure') == identity(failure_path)
            and row.get('resource_only') is True and row.get('remedy_count') == 1
            and bool(row.get('description')) and row.get('remedy_log') == identity(log),
            'Remedy must bind stage, failure identity, count, description and REMEDY_LOG: '+name)
    try:
        stamp = dt.datetime.fromisoformat(row['utc'].replace('Z','+00:00'))
        failure_stamp = dt.datetime.fromisoformat(failed['failure_utc'])
    except (KeyError, ValueError, TypeError) as exc:
        raise RuntimeError('Dated UTC remedy required: '+name) from exc
    require(stamp.utcoffset() == dt.timedelta(0) and stamp >= failure_stamp,
            'Remedy must follow its failure in UTC: '+name)
    # Preserve the consumed identity even if the coordinator later adds log entries.
    used = state/'remedies_used'/(name+'.json')
    write_json(used, dict(stage=name,remedy=identity(remedy),failure=identity(failure_path),
                        remedy_log=identity(log),remedy_count=1,clause=CLAUSE),exclusive=True)
    write_json(started,dict(stage=name,utc=now(),remedy=identity(remedy),failure=identity(failure_path)),exclusive=True)
    return 1

def failure(state,name,path,exc,count,reason='A8DEV_RERUN',**extra):
    """A pre-remedy disk/memory stop has no permanent scientific disposition."""
    row = dict(extra,stage=name,state='DEVIATION' if count else 'STOPPED_FOR_REMEDY',
               reason=reason if count else 'RESOURCE_STOP',detail=repr(exc),failure_utc=now(),
               remedy_count=count,maximum_remedies=MAX_REMEDIES,clause=CLAUSE,
               eligible_tasks=[],partial_predictions_eligible_for_scoring=False)
    write_json(path,row)
    if not count:
        raise ResourceStop(name+' stopped before export; document its resource-only remedy') from exc
    return row

def preserve_failed_artifacts(state,jobs,A,feature_sha,permit):
    """Move failed-task binaries and receipts before the native writer retries."""
    state = Path(state)
    retained = []
    for task in jobs:
        if A.execution.reusable(state,task,feature_sha,permit) is not None:
            continue
        ident = A.execution.task_id(task)
        paths = set((state/'fits').rglob(ident+'*'))
        if task.task == 'lear':
            # Native window workers can leave NPZ before assemble_daily_job
            # writes a receipt. Their names do not use the daily task_id.
            paths.update((state/'fits/artifacts').glob('LEAR__'+task.origin+'__*'))
        receipt = A.execution._receipt_path(state,task)
        if receipt.exists():
            rec = read_json(receipt)
            for record in [rec,*rec.get('windows',[])]:
                for key in ('model_path','prediction_path','input_scaling_path'):
                    if record.get(key):
                        paths.add(Path(record[key]))
        dest = state/'failed_attempts'/uuid.uuid4().hex
        for p in sorted(paths):
            if not p.is_file():
                continue
            require(state in p.resolve().parents, 'Failed artifact outside batch state')
            item = identity(p)
            target = dest/p.relative_to(state)
            target.parent.mkdir(parents=True,exist_ok=True)
            os.rename(p,target)
            retained.append(dict(original=item,retained=identity(target)))
    if retained:
        write_json(state/'failed_attempts'/('inventory_'+uuid.uuid4().hex+'.json'),
                   dict(files=retained,reason='preserve failed evidence before retry'),exclusive=True)
    return retained
