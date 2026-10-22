"""Sealed-chain adapter by path, with batch-local I/O and registered CPS8 wrappers."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import importlib
import os
import sys
import uuid
from a8_common import *

_loaded = None
_audit = None
_transient_deletions = set()
_ledger_events = {}

def install_audit(state, synthetic=False):
    """Synthetic runs cannot open production state, seals, predictions or scores."""
    global _audit
    state = Path(state).resolve()
    if _audit is not None:
        require(_audit == (state, synthetic), 'Cannot mix audited states in a process')
        return
    state.mkdir(parents=True, exist_ok=True)
    log = state/'OPENED_PATHS.jsonl'
    fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    def hook(event, args):
        if event in ('os.remove', 'os.rmdir') and not (event == 'os.remove' and str(Path(os.fsdecode(args[0])).resolve()) in _transient_deletions):
            raise PermissionError('Permanent deletion prohibited; retain evidence or use /usr/bin/trash')
        if event != 'open' or not isinstance(args[0], (str,bytes,os.PathLike)):
            return
        p = Path(os.fsdecode(args[0])).resolve()
        if p == log or p == Path('/dev/null'):
            return
        mode, flags = args[1:3]
        writing = (isinstance(mode,str) and any(c in mode for c in 'wax+')) or bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT))
        require(p.name not in {'.env','auth.json','.netrc'} and '/Keychains/' not in str(p) and
                '/semantic_validation/private/' not in str(p), 'Protected input')
        if writing and not (OUT == p or OUT in p.parents or state == p or state in p.parents):
            raise PermissionError('A8BATCH write outside own state: '+str(p))
        if not writing and Q in p.parents:
            require(not synthetic or 'host_state' not in p.parts, 'Synthetic test production host_state read')
            require(not synthetic or not any(x in p.parts for x in ('scored','a2_scored','scores','evaluation')), 'Synthetic production score access')
            if synthetic:
                require(not p.name.startswith('SEAL') and 'prediction' not in p.name.lower(), 'Synthetic production seal/prediction read')
        if Q in p.parents or state in p.parents:
            os.write(fd,(json.dumps(dict(path=str(p),mode=str(mode),time_utc=now()))+'\n').encode())
    sys.addaudithook(hook)
    _audit = (state, synthetic)

def load(root=ADAPTER, synthetic=False, expected=None, preverified=False):
    global _loaded
    root = Path(root).resolve()
    if not synthetic and not preverified:
        from a8_freeze import verify_adapter
        verify_adapter(root, expected)
    elif synthetic:
        require(Q not in root.parents and (root.parent/'SYNTHETIC_ONLY.json').is_file(), 'Synthetic adapter root required')
    if preverified:
        require(expected is not None and sha(root/'ADAPTER_FREEZE.json') == expected, 'Worker/parent adapter hash drift')
    if _loaded is not None:
        require(_loaded.root == root, 'Cannot mix adapter roots')
        return _loaded
    sys.path.insert(0,str(root))
    runtime = importlib.import_module('runtime')
    execution = importlib.import_module('execution_adapter')
    features = importlib.import_module('features_adapter')
    storage = importlib.import_module('feature_storage')
    require(all(Path(m.__file__).resolve().parent == root for m in (runtime,execution,features,storage)), 'Cached module path drift')
    _loaded = SimpleNamespace(root=root, runtime=runtime, execution=execution, features=features, storage=storage,
                              scheduler=runtime.conf_module('scheduler'), guard=runtime.conf_module('guard'),
                              worker=execution._worker, original_lear_worker=execution._lear_subjob_worker,
                              params=execution.parameters, select=execution.select_rows)
    return _loaded

def relocate(adapters, state, synthetic=False):
    """Change I/O callbacks only; installed scientific code stays on disk unchanged."""
    state = Path(state).resolve()
    install_audit(state, synthetic)
    def audit_install(*args,**kwargs):
        install_audit(state, synthetic)
    def audit(path,mode='read',purpose='A8 batch'):
        with (state/'EXPLICIT_READS.jsonl').open('a') as f:
            f.write(json.dumps(dict(path=str(Path(path).resolve()),mode=mode,purpose=purpose,time_utc=now()))+'\n')
    def own_output(p):
        return state == p or state in p.parents or any(root == p or root in p.parents for root in (OUT/'dly8',OUT/'cps8'))
    def atomic(path,value,immutable=False):
        p = Path(path).resolve()
        require(own_output(p),'Installed writer escaped batch outputs')
        retain = True
        if p.name == 'FITTING_WALL_LEDGER.json':
            # The wave signature changes only at begin/finish/recovery. Heartbeats
            # atomically replace the live ledger, without retaining a full copy.
            events = tuple((w['id'],w.get('end'),w['state']) for w in value['waves'])
            if str(p) not in _ledger_events:
                prior = read_json(p).get('waves',[]) if p.exists() else []
                _ledger_events[str(p)] = tuple((w['id'],w.get('end'),w['state']) for w in prior)
            previous = dict((w[0],w[1:]) for w in _ledger_events.get(str(p),()))
            changed = [w for w in value['waves'] if previous.get(w['id']) != (w.get('end'),w['state'])]
            if changed:
                event_path = p.with_name('FITTING_WALL_EVENTS.jsonl')
                with event_path.open('a') as stream:
                    for wave in changed:
                        stream.write(json.dumps(dict(wave=wave,recorded_utc=now()),sort_keys=True)+'\n')
                    stream.flush();os.fsync(stream.fileno())
            retain = False  # linear event evidence replaces quadratic full-ledger copies
            _ledger_events[str(p)] = events
        return write_json(p,value,exclusive=immutable,retain_revision=retain)
    class ScratchPath(type(Path())):
        def unlink(self, missing_ok=False):
            p = Path(self).resolve()
            require(state in p.parents and p.name.endswith(('.train.npy','.query.npy')),
                    'Only worker-owned transient train/query scratch may be deleted')
            _transient_deletions.add(str(p))
            try:
                return super().unlink(missing_ok=missing_ok)
            finally:
                _transient_deletions.discard(str(p))
    for m in (adapters.runtime,adapters.execution,adapters.features):
        m.install_audit = audit_install
        m.audit = audit
        m.atomic_json = atomic
    adapters.execution.Path = ScratchPath
    # Helpers may already have bound callbacks; install before importing them.
    for name in ('lear_parallel','lear_adapter','lear_adapter_confx5','embedding_adapter','nrx_adapter','feature_storage'):
        if name in sys.modules:
            m = sys.modules[name]
            for key,value in [('install_audit',audit_install),('audit',audit),('atomic_json',atomic)]:
                if hasattr(m,key):
                    setattr(m,key,value)
    embedding = sys.modules.get('embedding_adapter')
    if embedding is not None:
        def save_array(path,value):
            import numpy as np
            p = Path(path).resolve()
            require(own_output(p),'Encoder cache output escaped batch state')
            p.parent.mkdir(parents=True,exist_ok=True)
            if p.exists():
                require(not p.with_suffix('.json').exists(),'Preserve bound encoder cache array')
                retained = p.parent/'failed_attempts'/uuid.uuid4().hex
                retained.mkdir(parents=True)
                old = identity(p);os.rename(p,retained/p.name)
                write_json(retained/'IDENTITY.json',dict(original=old,retained=identity(retained/p.name)),exclusive=True)
            temporary = p.with_name(p.name+'.atomic.'+uuid.uuid4().hex)
            with temporary.open('xb') as stream:
                np.save(stream,np.asarray(value,dtype='float32'),allow_pickle=False)
                stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,p)
        embedding._save_array = save_array

def configure_cps(adapters):
    def params(task):
        result = adapters.params(task)
        if task.variant.startswith('cps8_'):
            from cps8_runner import grid_parameters, decode_arm
            _,g = decode_arm(task.arm)
            result = grid_parameters(result,g)
        return result
    def select(panel,task,bundle):
        if task.variant.startswith('cps8_'):
            from cps8_runner import select_rows
            return select_rows(panel,task,bundle)
        return adapters.select(panel,task,bundle)
    adapters.execution.parameters = params
    adapters.execution.select_rows = select

def runtime_hashes(code):
    return [identity(OUT/'CODE_FREEZE.json'),code['bindings'],*code['adapter_files'],
            *[identity(OUT/rel) for rel in code['code_sha256']]]

def worker_adapters(state):
    """Hash-only launch check. No chain/TSA/receipt parsing in fitting workers."""
    launch = read_json(Path(state)/'WORKER_BINDING.json')
    for item in launch['hashes']:
        checked(item)
    A = load(launch['adapter_root'],synthetic=launch.get('synthetic_only',False),
             expected=launch.get('adapter_freeze_sha256'),preverified=not launch.get('synthetic_only',False))
    relocate(A,state,synthetic=launch.get('synthetic_only',False))
    configure_cps(A)
    return A

def worker(payload):
    A = worker_adapters(Path(payload[-1]).parents[1])
    return A.worker(payload)

def lear_worker(payload):
    A = worker_adapters(Path(payload[4]).parents[1])
    return A.original_lear_worker(payload)

@contextmanager
def installed_wave(adapters, workers=4):
    e = adapters.execution
    require(1 <= workers <= 7, 'Worker cap outside installed limits')
    original = e._worker, e._lear_subjob_worker, e.NEWS_MAX_WORKERS,e.fit_disk_plan
    e._a8_original_lear_worker = e._lear_subjob_worker
    e._worker, e._lear_subjob_worker, e.NEWS_MAX_WORKERS = worker, lear_worker, workers
    def disk_plan(tasks,manifest):
        tasks = list(tasks)
        plan = original[3](tasks,manifest)
        rates = getattr(adapters,'model_serialization_rates',{})
        saving = 0
        for task in tasks:
            if task.task not in rates or task.variant.startswith('cps8_'): continue  # unseen capacity grids keep the uncalibrated upper reserve
            params = e.parameters(task);leaves = params['n_estimators']*params['num_leaves']
            saving += max(0,int(leaves*1024-__import__('math').ceil(leaves*rates[task.task]*1.25)))
        plan = dict(plan)
        plan['persistent_output_bytes'] -= saving;plan['planned_bytes'] -= saving
        plan['sealed_model_calibration'] = rates
        return plan
    e.fit_disk_plan = disk_plan
    try:
        yield
    finally:
        e._worker, e._lear_subjob_worker, e.NEWS_MAX_WORKERS,e.fit_disk_plan = original
