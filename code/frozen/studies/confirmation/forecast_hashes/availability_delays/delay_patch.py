'Select the notice-delay callbacks for forecasting.'
import ast
from contextlib import contextmanager
import hashlib
import types

SCOPE = dict(arms=['L14','L_Laz'],delta_minutes=[15,60],seed=20260919,
             model_variant='main',models_refitted=0,window='D',
             delta_rule='FROZEN_DLY8_DELTA_ADDED_TO_AVAILABLE_UTC_UNCHANGED')

IMPORT = '    from delay_core import run_delay_set, specified_delay_identities, write_combined_seal as write_seal\n'
BINDING = "    binding['delay_authority']=activation['delay_release']\n    binding['delay_scope']=dict(arms=['L14','L_Laz'],delta_minutes=[15,60],seed=20260919,model_variant='main',models_refitted=0,window='D',delta_rule='FROZEN_DLY8_DELTA_ADDED_TO_AVAILABLE_UTC_UNCHANGED')\n"
REBUILD = "        # +5 arrays have been closed by unchanged run_set; delayed pairs\n        # retain both matrices until exact feature support has been counted.\n        for p in scratch.glob('**/*.npy'):\n            p.unlink()\n        specified_delays=specified_delay_identities(dly_binding)\n        def rebuild_delay(arm,corrected,delta,root):\n            checkpoint()\n            require(arm in ('L14','L_Laz') and delta in (15,60),'D1 delay/arm scope drift')\n            retained=sum(p.stat().st_size for p in scratch.rglob('*.npy'))\n            planned=retained+len(panel)*len(bundles[arm]['columns'])*4+len(panel)*80\n            require(planned<SCRATCH_LIMIT,'Delayed pair scratch plan is at least 1 GB')\n            proxy=structural_adapter(A,[arm],scratch,checkpoints)\n            ctx=install_patch(nrx,A.features) if corrected else nullcontext()\n            with ctx:\n                return dly.rebuild_features(panel,notices,delta,[arm],bundles,proxy,permit,scratch/root.name,\n                         {'numeric_columns':bundles['N'].get('shared_columns',bundles['N']['columns'])},\n                         encoder=NoEncoder(),cache_directory=scratch/'no_encoding',production_rows=production_rows)[arm]\n        def reference_delay(arm,delta):\n            return pd.read_parquet(checked(specified_delays[str(delta)][arm]),\n                     columns=KEYS+['target_day','raw_prediction','lower_bound','upper_bound','prediction'])\n        result['delay_extension']=run_delay_set(OUT/'availability_delays/delay_prediction_set',panel,\n                     specified_delays,rebuild_delay,predict,reference_delay,binding,checkpoint)\n"


def require(ok, message):
    if not ok:
        raise RuntimeError('Delayed dispatch overlay refused: '+message)


def patch_source(source):
    import deadline_patch
    parent, calendar_proof = deadline_patch.patch_source(source)
    insertions = (
        (b'    from structural_projection import structural_adapter,NoEncoder\n',IMPORT.encode()),
        (b'    started=time.monotonic()\n',BINDING.encode()),
        (b'        checkpoint()\n    no_overlap(roots)\n',REBUILD.encode()),
    )


    patched = parent
    proof = []
    for anchor, addition in insertions:
        require(parent.count(anchor)==1,'exact frozen insertion site missing/duplicate')
        position=patched.index(anchor)
        patched=patched[:position]+addition+patched[position:]
        proof.append(dict(anchor_sha256=hashlib.sha256(anchor).hexdigest(),
                          inserted_sha256=hashlib.sha256(addition).hexdigest(),bytes=len(addition)))
    restored=patched
    for _anchor,addition in reversed(insertions):
        require(restored.count(addition)==1,'additive insertion census drift')
        restored=restored.replace(addition,b'',1)
    require(restored==parent,'source bytes changed outside explicit D1 additions')
    old=ast.parse(parent); new=ast.parse(patched)

    stripped=ast.parse(restored)
    require(ast.dump(old,include_attributes=False)==ast.dump(stripped,include_attributes=False),
            'remaining dispatch/module AST drift')
    dispatch=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name=='dispatch')
    original_launch=next(n for n in old.body if isinstance(n,ast.FunctionDef) and n.name=='dispatch')
    for name in ('require_before_t5','no_overlap','verify_runtime_roots','load_dly8_binding','run_set'):
        def census(node):
            return sum(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id==name
                       for n in ast.walk(node))
        require(census(dispatch)==census(original_launch),'earlier gate/call census drift: '+name)
    return patched,dict(schema='FORECAST_BINDING8_ADDITIVE_LAUNCH_PATCH_V1',calendar_patch=calendar_proof,
        source_sha256=hashlib.sha256(source).hexdigest(),parent_launch_sha256=hashlib.sha256(parent).hexdigest(),
        patched_sha256=hashlib.sha256(patched).hexdigest(),insertions=proof,
        all_parent_bytes_outside_additions_identical=True,remaining_parent_AST_identical=True,
        original_plus5_callbacks_unchanged=True,earlier_gates_unchanged=True,
        frozen_dly8_function_bodies_changed=False,scope=SCOPE)


def launch_code(source, filename):
    values=[n for n in compile(source,filename,'exec').co_consts
            if isinstance(n,types.CodeType) and n.co_name=='dispatch']
    require(len(values)==1,'one dispatch code required')
    return values[0]


@contextmanager
def install(module, source):
    patched,proof=patch_source(source)
    original=module.dispatch
    require(isinstance(original,types.FunctionType) and original.__globals__ is vars(module)
            and original.__closure__ is None and original.__code__==launch_code(source,module.__file__),
            'loaded dispatch differs from exact frozen source')
    function=types.FunctionType(launch_code(patched,module.__file__),vars(module),original.__name__,original.__defaults__)
    function.__kwdefaults__=original.__kwdefaults__; function.__annotations__=original.__annotations__
    function.__qualname__=original.__qualname__; function.__doc__=original.__doc__
    module.dispatch=function
    try:
        yield proof
    finally:
        module.dispatch=original
