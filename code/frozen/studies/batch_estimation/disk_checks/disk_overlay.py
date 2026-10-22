"""Additive persistence/reservation overlay. Import performs no study reads."""
from __future__ import annotations
import contextlib
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
PARENT = HERE.parent / 'A8BATCHFIX4'
PROJ = HERE.parents[3]
HEADROOM = 3 * 1024**3
SCRATCH_LIMIT = 1_000_000_000


def ident(path):
    p = Path(path)
    h = hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return dict(bytes=p.stat().st_size, sha256=h.hexdigest())


def resource_guard():
    if os.getpriority(os.PRIO_PROCESS, 0) < 20:
        os.setpriority(os.PRIO_PROCESS, 0, 20)
    result = subprocess.run(['/usr/bin/memory_pressure'], capture_output=True, text=True, check=True)
    match = re.search(r'System-wide memory free percentage:\s*(\d+)%', result.stdout)
    if not match or int(match[1]) < 25:
        raise MemoryError('DISKFIX requires >=25% free memory')
    return dict(nice=os.getpriority(os.PRIO_PROCESS, 0), memory_free_percent=int(match[1]))


def verify_parent():
    pins = json.loads((HERE/'SOURCE_IDENTITIES.json').read_text())
    for rel, expected in pins['parents'].items():
        if ident(PROJ/rel) != expected:
            raise PermissionError('Frozen source drift: '+rel)
    freeze=json.loads((PARENT/'CODE_FREEZE.json').read_text())
    for rel,expected in freeze['code_sha256'].items():
        if ident(PARENT/rel)['sha256']!=expected: raise PermissionError('Declared frozen batch code drift: '+rel)
    adapter=PROJ/'autopilot/q1_audits/CONF/CONFX2'
    receipt=json.loads((adapter/'ADAPTER_FREEZE.json').read_text())
    if ident(adapter/'ADAPTER_FREEZE.json')['sha256']!=freeze['adapter_freeze_sha256']:
        raise PermissionError('Declared adapter parent drift')
    for name in ('feature_storage.py','execution_adapter.py','features_adapter.py'):
        if ident(adapter/name)!=receipt['files'][name]: raise PermissionError('Declared frozen adapter drift: '+name)
    return pins


def import_frozen():
    verify_parent()  # before importing any batch source
    sys.path.insert(0, str(PARENT/'code'))
    import runner, r8_activity, dly8_rebuild
    return runner, r8_activity, dly8_rebuild


def npy_header(shape):
    import numpy as np
    stream = io.BytesIO()
    np.lib.format.write_array_header_1_0(stream, dict(descr='<f4', fortran_order=False, shape=tuple(shape)))
    return stream.getvalue()


class HashMatrix:
    """Frozen R8 writer's sequential two-assignment blocks; bounded RAM only."""
    def __init__(self, path, shape):
        import numpy as np
        self.path, self.shape = Path(path).resolve(), tuple(shape)
        self.dtype = np.dtype('float32')
        self.header = npy_header(shape)
        self.digest = hashlib.sha256(self.header)
        self.pending = None
        self.next_row = 0
        self.closed = False
        self._mmap = self
    def __setitem__(self, key, value):
        import numpy as np
        rows, columns = key
        if not isinstance(rows, slice) or rows.step not in (None, 1):
            raise RuntimeError('Unexpected frozen R8 write selector')
        start, stop = rows.start or 0, min(rows.stop, self.shape[0])
        if self.pending is None:
            if start != self.next_row or (stop-start)*self.shape[1]*4 >= SCRATCH_LIMIT:
                raise RuntimeError('Nonsequential or oversized R8 block')
            self.pending = (start, stop, np.empty((stop-start, self.shape[1]), dtype='float32'), np.zeros(self.shape[1], bool))
        first, last, block, filled = self.pending
        if (start, stop) != (first, last) or filled[columns].any():
            raise RuntimeError('Frozen R8 overlapping/unflushed writes')
        block[:, columns] = value
        filled[columns] = True
    def flush(self):
        if self.pending is None: return
        start, stop, block, filled = self.pending
        if not filled.all(): raise RuntimeError('Incomplete R8 output block')
        self.digest.update(block.tobytes(order='C'))
        self.next_row = stop
        self.pending = None
    def close(self):
        self.flush()
        if self.next_row != self.shape[0]: raise RuntimeError('Incomplete R8 output matrix')
        self.closed = True
    def identity(self, **extra):
        if not self.closed: raise RuntimeError('R8 matrix identity before close')
        return dict(path=str(self.path), bytes=len(self.header)+self.shape[0]*self.shape[1]*4,
                    sha256=self.digest.hexdigest(), **extra)


def recipe_load(storage, bundle, rows, columns=None):
    import numpy as np
    recipe = bundle['disk_recipe']
    selected = list(bundle['columns'] if columns is None else columns)
    if any(c not in bundle['columns'] for c in selected): raise ValueError('Recipe unknown column')
    selector, count = storage._normalise_rows(rows, bundle['rows'])
    output = np.empty((count, len(selected)), dtype='float32')
    base_columns = set(recipe['base_columns'])
    old = [(i, c) for i, c in enumerate(selected) if c in base_columns]
    new = [(i, c) for i, c in enumerate(selected) if c not in base_columns]
    if old:
        output[:, [i for i,c in old]] = storage.load_feature_rows(recipe['base'], selector, [c for i,c in old])
    if new:
        values = np.load(recipe['metadata']['path'], mmap_mode='r', allow_pickle=False)
        try:
            indices = [recipe['metadata_columns'].index(c) for i,c in new]
            for start in range(0, count, 10000):
                stop = min(count, start+10000)
                if isinstance(selector, slice):
                    first, _, step = selector.indices(bundle['rows'])
                    ids = first+step*np.arange(start,stop)
                else: ids = selector[start:stop]
                output[start:stop, [i for i,c in new]] = values[np.ix_(ids,indices)]
        finally: values._mmap.close()
    return output


def install_storage(A):
    """Only the physical storage functions; worker science imports stay intact."""
    storage = A.storage
    if getattr(storage, '_disk_overlay', False): return
    old_load, old_verify = storage.load_feature_rows, storage.verify_bundle
    old_ids, old_paths = storage.bundle_storage_identities, storage.bundle_storage_paths
    def load(b, rows, columns=None):
        return recipe_load(storage,b,rows,columns) if 'disk_recipe' in b else old_load(b,rows,columns)
    def ids(b):
        if 'disk_recipe' not in b: return old_ids(b)
        r = b['disk_recipe']
        return [*old_ids(r['base']),r['metadata'],r['receipt']]
    def paths(b): return [Path(i['path']) for i in ids(b)]
    def verify(b, seen=None):
        if 'disk_recipe' not in b: return old_verify(b,seen=seen)
        r = b['disk_recipe']
        old_verify(r['base'],seen=seen)
        for i in (r['metadata'],r['receipt']): storage._verify_identity(i, {} if seen is None else seen)
        receipt = json.loads(Path(r['receipt']['path']).read_text())
        if receipt['matrix'] != b['matrix'] or receipt['columns'] != b['columns'] or receipt['recipe'] != {k:v for k,v in r.items() if k!='receipt'}:
            raise PermissionError('R8 recipe identity drift')
        if b['matrix']['shape'] != [b['rows'],len(b['columns'])]: raise ValueError('Recipe shape drift')
        return True
    storage.load_feature_rows,storage.verify_bundle = load,verify
    storage.bundle_storage_identities,storage.bundle_storage_paths = ids,paths
    storage._disk_overlay = True
    # Frozen worker imports bound these callbacks by name before installation.
    for mod in (A.execution,A.features):
        for key, value in [('load_feature_rows',load),('verify_bundle',verify),('bundle_storage_paths',paths)]:
            if hasattr(mod,key): setattr(mod,key,value)


@contextlib.contextmanager
def r8_persistence(r8,A,root):
    """Frozen build_bundles computes every value; replace only matrix persistence."""
    import numpy as np
    import a8_common as common
    root = Path(root).resolve()
    install_storage(A)
    original_open, original_meta, original_gate = np.lib.format.open_memmap,r8.metadata_matrix,r8.base_gate
    matrices, metadata = {}, {}
    def open_matrix(path,*args,**kw):
        p = Path(path).resolve()
        if p.parent == root and p.name.endswith('.npy') and not p.name.endswith('__R8_unpruned.npy'):
            if args or kw.get('mode') != 'w+' or np.dtype(kw['dtype']) != np.dtype('float32') or p.exists():
                raise RuntimeError('Unexpected R8 persistence call')
            m = HashMatrix(p,kw['shape']); matrices[str(p)] = m
            return m
        return original_open(path,*args,**kw)
    def meta(*args,**kw):
        result = original_meta(*args,**kw)
        if kw.get('out_path') is not None:
            p = Path(kw['out_path']).resolve()
            metadata[str(p)] = list(result[1])
        return result
    def identity(path,**extra):
        m = matrices.get(str(Path(path).resolve()))
        return m.identity(**extra) if m else common.identity(path,**extra)
    def gate(storage,base,new,expected_columns,chunk=2048):
        path = Path(new['matrix']['path'])
        meta_path = path.parent/(new['source']+'__R8_unpruned.npy')
        meta_array = np.load(meta_path,mmap_mode='r',allow_pickle=False)
        shape = list(meta_array.shape); meta_array._mmap.close()
        recipe = dict(base=base,base_columns=list(expected_columns),metadata=common.identity(meta_path,shape=shape,dtype='float32'),metadata_columns=metadata[str(meta_path.resolve())])
        new['disk_recipe'] = recipe
        h = hashlib.sha256(npy_header(new['matrix']['shape']))
        for start in range(0,new['rows'],2048): h.update(load_direct(new,slice(start,start+2048)).tobytes())
        if h.hexdigest() != new['matrix']['sha256']: raise RuntimeError('R8 virtual NPY byte identity failed')
        recipe['virtual_npy'] = dict(new['matrix'])
        new['matrix'] = {k:v for k,v in new['matrix'].items() if k!='path'}
        receipt = path.with_suffix('.recipe.json')
        common.write_json(receipt,dict(matrix=new['matrix'],columns=new['columns'],recipe=recipe,state='EXACT_NPY_SHA256_RECONSTRUCTION_PASS'),exclusive=True)
        recipe['receipt'] = common.identity(receipt)
        return original_gate(storage,base,new,expected_columns,chunk)
    def load_direct(b,rows): return recipe_load(A.storage,b,rows)
    np.lib.format.open_memmap,r8.metadata_matrix,r8.base_gate = open_matrix,meta,gate
    try: yield identity
    finally: np.lib.format.open_memmap,r8.metadata_matrix,r8.base_gate = original_open,original_meta,original_gate


def release_delta(root, values, binding=None):
    """Durable regeneration receipt first; delete exact owned matrix files only."""
    import numpy as np
    import a8_common as c
    import a8_adapter
    root = Path(root).resolve()
    records = []
    for arm,x in values.items():
        if not isinstance(x,np.memmap): continue
        p = Path(x.filename).resolve()
        if root not in p.parents or p.suffix != '.npy' or p.is_symlink(): raise PermissionError('DLY8 release escaped owned delta')
        if not x._mmap.closed: x.flush();x._mmap.close()
        records.append(c.identity(p,arm=arm,shape=list(x.shape),dtype=str(x.dtype)))
    receipt = root/'MATRIX_RELEASE.json'
    if records: c.write_json(receipt,dict(state='COMPLETED_DELTA_RELEASE',binding=binding,matrices=records,regeneration='frozen rebuild_features with same bound inputs'),exclusive=True)
    for item in records:
        p = Path(item['path'])
        a8_adapter._transient_deletions.add(str(p))
        try: p.unlink()
        finally: a8_adapter._transient_deletions.discard(str(p))


def finish_matrix_evidence(root,binding):
    """Recover only the successful attempt, including an unrecorded final delta."""
    from dly_evidence import complete
    return complete(root,binding)


@contextlib.contextmanager
def dly_persistence(dly):
    original, original_host = dly.run_delays, dly.host_mode
    def run(root,arms,rebuild,predict,reference,expected_features,binding,rebuild_all=None):
        previous = []
        def all_matrices(delta,out):
            if previous:
                release_delta(*previous.pop(),binding=binding)
            values = rebuild_all(delta,out) if rebuild_all is not None else {a:rebuild(delta,a,out/str(a)) for a in arms}
            previous.append((out,values))
            return values
        result = original(root,arms,rebuild,predict,reference,expected_features,binding,rebuild_all=all_matrices)
        if result['state'] == 'ALL_DLY8_PREDICTIONS_SEALED':
            if previous: release_delta(*previous.pop(),binding=binding)
            finish_matrix_evidence(root,binding)
        return result
    dly.run_delays = run
    from dly_evidence import host_entry
    def host(mode,context=None):
        return host_entry(original_host,dly,mode,context)
    dly.host_mode = host
    try: yield
    finally: dly.run_delays, dly.host_mode = original, original_host


def conservative_plan(facts):
    """Metadata-free bound using only coordinator-supplied components."""
    n,arms = 527040,11
    predictions = 3*n*192*arms
    delta = math.ceil((facts['dly8_bytes']-predictions)/4)
    # Every R8 arm in a source contributes >= one complete metadata width in the
    # old upper bound, except M0. There are 5 news / 6 notice reserved arms;
    # old bound includes metadata width even for M0. Two metadata banks together
    # therefore cost at most total dense reserve / 5 (plus NPY headers).
    metadata = math.ceil(facts['r8_bundle_bytes']/5)+2*1024**2+512
    fit = facts['fit_persistent_bytes']; scratch=facts['peak_transient_scratch_bytes']
    cache=facts['cache_and_receipt_reserve_bytes']; ledger=2*facts['ledger_revision_reserve_bytes']  # live events/final ledger plus pre-T5 sealed snapshots
    copies=facts['sealed_copy_reserve_bytes']
    shared = fit+metadata+cache+ledger
    rows = [dict(stage='DLY8_primary',planned_bytes=delta+3*n*192*5+cache+ledger),
            dict(stage='R8_build',planned_bytes=metadata+3*n*192*5+cache+ledger),
            dict(stage='B0_B1_B2_B3_B4_B5_upper_each',planned_bytes=shared+scratch+3*n*192*5+copies),
            dict(stage='batch_seal',planned_bytes=shared+2*copies+3*n*192*5+64*1024**2),
            dict(stage='DLY8_R8',planned_bytes=shared+copies+predictions+delta)]
    for row in rows:
        row.update(required_bytes=row['planned_bytes']+HEADROOM,
                   admitted=facts['free_bytes']>=row['planned_bytes']+HEADROOM,
                   additional_free_bytes=max(0,row['planned_bytes']+HEADROOM-facts['free_bytes']))
    return dict(state='CONSERVATIVE_BOUND_NOT_PRODUCTION_SHAPE_MEASUREMENT',stages=rows,
                maximum_required_bytes=max(r['required_bytes'] for r in rows),
                additional_free_bytes=max(r['additional_free_bytes'] for r in rows),
                one_delta_combined_upper_bytes=delta,r8_metadata_upper_bytes=metadata,
                exact_production_shapes_read=False,headroom_bytes=HEADROOM,
                runtime_metadata_admissions={
                    'reuse_from_main':'all copy sizes + largest atomic copy + rebound receipts + partial-copy identity receipts',
                    'create_seal':'all missing complete-stage aggregates + actual live ledger/events + seal receipts + atomic duplicates',
                    'static_seal_row':'64 MiB supplementary receipt allowance; actual metadata planner takes precedence',
                    'reuse_static_bound_available':False})


def install_runtime(A,runner,r8,dly):
    """Patch I/O callbacks only; frozen scheduling and numerical kernels remain."""
    if getattr(A,'_disk_runtime',False): return
    import batch_export
    from disk_entries import install
    install(runner,batch_export)
    install_storage(A)
    old_require = A.storage.require_disk_space
    def require_space(path,planned,headroom,stage):
        if stage.startswith('R8 ') and hasattr(A,'_disk_r8_reserve'):
            planned = A._disk_r8_reserve
        elif stage.startswith('DLY8 remedied'):
            # The family rebuild guard below still checks a full delta before writes.
            planned = math.ceil(planned/4) + 3*527040*192*len(runner.R8_NOTICE)
        return old_require(path,planned,headroom,stage)
    A.storage.require_disk_space = require_space
    build_original = r8.build_bundles
    def build(production,out,adapters,records,contract,write,ident_callback):
        # Metadata shape is fully known before source-value construction.
        planned = sum(max(b['rows'] for b in production['bundles'] if b['source']==source)*4*width+256
                      for source,width in [('news',len(r8.NEWS_COLUMNS)),
                          ('notice',len(r8.NOTICE_COLUMNS)+len(r8.training_types(records['notice']))+3)])
        planned += 2*1024**2  # durable recipe receipts and immutable-write duplicates
        A._disk_r8_reserve = planned
        old_require(out,planned,HEADROOM,'R8 complete metadata/recipe stage')
        try:
            with r8_persistence(r8,A,out) as virtual_ident:
                return build_original(production,out,adapters,records,contract,write,virtual_ident)
        finally: del A._disk_r8_reserve
    r8.build_bundles = build
    guard_original = A.execution.guard_fit_bank
    def guard(jobs,manifest,state,name):
        jobs=list(jobs)
        reserve=fit_stage_reserve(A,jobs,manifest)
        old_require(state,reserve['planned_bytes'],HEADROOM,'whole stage plus sealing: '+name)
        return guard_original(jobs,manifest,state,name)
    A.execution.guard_fit_bank = guard
    A._disk_runtime=True


def fit_stage_reserve(A,jobs,manifest):
    """Entire source-stage output/scratch/copies/linear receipts before any fit."""
    from dataclasses import asdict
    persistent=0;scratch=0;copies=0;ledger=0
    for source in sorted({t.task for t in jobs}):
        group=[t for t in jobs if t.task==source]
        plan=A.execution.fit_disk_plan(group,manifest)
        persistent+=plan['persistent_output_bytes'];scratch=max(scratch,plan['peak_scratch_bytes'])
        for t in group:
            if source=='lear': rows=72
            elif source=='news':
                rows=42*7*72 if t.variant=='cps8_selection' else 214*72 if t.variant=='cps8_D' else 365*72 if t.variant=='2025_fixed_validation' else 72
                persistent+=max(0,rows-(365*72 if t.variant=='2025_fixed_validation' else 72))*192
            else:
                bundle=A.execution.find_bundle(manifest,t)
                rows=int(bundle['train_rows']) if t.variant=='cps8_selection' else bundle['rows']-int(bundle['train_rows'])
                persistent+=max(0,rows-(bundle['rows']-int(bundle['train_rows'])))*192
            if t.variant!='cps8_selection': copies+=65536+rows*192
        groups={}
        for t in group: groups.setdefault(t.origin,[]).append(t)
        cap=A.execution.NEWS_MAX_WORKERS if source=='news' else 1
        for tasks in groups.values():
            for start in range(0,len(tasks),cap):
                bound=16384+len(json.dumps([asdict(t) for t in tasks[start:start+cap]],ensure_ascii=False).encode())
                ledger+=16*bound  # original events/live ledger and their sealed snapshots
    if jobs: ledger+=2*65536+10*16384
    return dict(planned_bytes=persistent+scratch+copies+ledger,persistent_output_bytes=persistent,
                peak_scratch_bytes=scratch,sealing_copy_bytes=copies,ledger_bytes=ledger)


def stage_plan(runner,A,production,cs8,binding,policy,seeds,workers,state,main_seal,check_space):
    """Keep frozen fit estimates; admit only primary DLY8 at the batch boundary."""
    facts = runner._disk_original_reserve(state,A,production,cs8,binding,policy,seeds,workers,check_space=False,main_seal=main_seal)
    n=527040
    scope=[b for b in production['bundles'] if b['source']=='notice' and b['arm'] in runner.PRIMARY_NOTICE and b.get('variant','main')=='main']
    delta=sum(n*len(b['columns'])*4+256 for b in scope)
    planned=delta+3*n*192*len(scope)+facts['cache_and_receipt_reserve_bytes']+2*facts['ledger_revision_reserve_bytes']
    if (HERE/'dly8/mode1/DLY8_RECEIPT.json').exists(): planned=0  # completed family revalidates before any prediction; next stages admit separately
    probe=A.storage.require_disk_space(state,planned,HEADROOM,'DLY8 primary whole family') if check_space else dict(planned_bytes=planned,required_bytes=planned+HEADROOM,headroom_bytes=HEADROOM,free_bytes=facts['free_bytes'],admitted=facts['free_bytes']>=planned+HEADROOM)
    return dict(probe,rule='whole stage admission; downstream stages guarded at start',frozen_estimates=facts,primary_delta_bytes=delta)


def worker(payload):
    """Picklable worker entry: verify hashes before frozen worker import."""
    from host_wrapper import verify_release
    verify_release()
    runner,r8,dly=import_frozen()
    import a8_adapter
    a8_adapter.OUT=HERE
    A=a8_adapter.worker_adapters(Path(payload[-1]).parents[1])
    install_storage(A)
    return A.worker(payload)


def install_host():
    runner,r8,dly=import_frozen()
    import a8_adapter,a8_common,batch_export,cps8_runner,dly8_cache,resource_remedy
    from disk_entries import install
    install(runner,batch_export)
    from dly_evidence import install_handoff
    install_handoff(batch_export,dly)
    # Keep the parent verifier/spec/amendment identities anchored at FIX4.
    for module in (runner,r8,dly,a8_adapter,a8_common,batch_export,cps8_runner,dly8_cache,resource_remedy):
        if hasattr(module,'OUT'): module.OUT=HERE
    old_relocate=a8_adapter.relocate
    def relocate(A,state,synthetic=False):
        old_relocate(A,state,synthetic=synthetic)
        install_runtime(A,runner,r8,dly)
    a8_adapter.relocate=relocate
    runner._disk_original_reserve=runner.reserve_batch_disk
    def reserve(state,A,production,cs8,binding,policy,seeds,workers,check_space=True,main_seal=None):
        return stage_plan(runner,A,production,cs8,binding,policy,seeds,workers,state,main_seal,check_space)
    runner.reserve_batch_disk=reserve
    a8_adapter.worker=worker
    def runtime_hashes(code):
        return [a8_common.identity(PARENT/'CODE_FREEZE.json'),code['bindings'],*code['adapter_files'],
                *[a8_common.identity(PARENT/rel) for rel in code['code_sha256']],
                a8_common.identity(HERE/'DISK_FREEZE.json')]
    a8_adapter.runtime_hashes=runtime_hashes
    pilot_original=runner.counted_pilot
    def pilot(name,jobs,manifest,feature_sha,stats,permit,state,ledger,A,resources,workers):
        if name=='CPS8':
            import cps8_runner as cps
            future=cps.d_tasks(A,{'selected':{source+'/'+arm:'g2' for source,arms in cps.ARMS.items() for arm in arms}})
            with a8_adapter.installed_wave(A,workers): reserve=fit_stage_reserve(A,list(jobs)+future,manifest)
            A.storage.require_disk_space(state,reserve['planned_bytes'],HEADROOM,'entire CPS8 before counted pilot')
        return pilot_original(name,jobs,manifest,feature_sha,stats,permit,state,ledger,A,resources,workers)
    runner.counted_pilot=pilot
    # Child dispatch only changes the interpreter entry to this hashed overlay.
    original_launch=dly.launch_mode
    def launch(mode,context):
        A,state,code,binding,seal_path,seal,manifest_path,permit=context
        arms=runner.PRIMARY_NOTICE if mode==1 else runner.R8_NOTICE
        path=Path(manifest_path) if mode==1 else Path(state)/'features/manifest.json'
        bank=json.loads(path.read_text())
        scope=[b for b in bank['bundles'] if b['source']=='notice' and b['arm'] in arms and b.get('variant','main')=='main' and b.get('state','COMPLETE')=='COMPLETE']
        if not (dly.dly_root(state)/('mode'+str(mode))/'DLY8_RECEIPT.json').exists():
            reserve=sum(527040*len(b['columns'])*4+256 for b in scope)+3*527040*192*len(scope)+2*1024**2
            A.storage.require_disk_space(dly.dly_root(state),reserve,HEADROOM,'whole DLY8 family before child')
        import unittest.mock as mock
        original_run=subprocess.run
        def dispatch(command,*args,**kw):
            if isinstance(command,list) and str(PARENT/'code/dly8_rebuild.py') in command:
                command=[str(HERE/'host_wrapper.py') if token==str(PARENT/'code/dly8_rebuild.py') else token for token in command]
                command.insert(3,'--dly-child')
            return original_run(command,*args,**kw)
        with mock.patch.object(subprocess,'run',side_effect=dispatch): return original_launch(mode,context)
    dly.launch_mode=launch
    # Context retained for the complete frozen run, including subprocess branch.
    return runner,r8,dly
