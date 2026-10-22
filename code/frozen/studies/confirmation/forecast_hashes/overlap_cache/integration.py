'Apply the checked structural feature cache during forecasting.'
from contextlib import contextmanager
import hashlib
from pathlib import Path
import sys
import types

HERE = Path(__file__).absolute().parent
AF = HERE.parent
Q = AF.parents[1]
F5 = Q / 'batch_estimation/matrix_storage'
BASE_ADAPTER_SHA256 = '03c8157ec121e7318f611eb56c2c61cc7a6e16d212a2115da8dcb2783bac7c2c'
F5_EVICTION_SHA256 = 'bd80165800befc0ecdaa2d2d54eb31bef690ad63d8c8b137cfb708d55e3928ec'


def require(ok, message):
    if not ok:
        raise RuntimeError('AFSPEED integration refused: ' + message)


def _source(path, expected_sha256=None):
    path = Path(path).absolute()
    require(path.resolve() == path, 'source path must be a real canonical path')
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    require(expected_sha256 is None or digest == expected_sha256, 'source identity drift: ' + str(path))
    return data, dict(path=str(path), bytes=len(data), sha256=digest)


def _load_source(name, path, expected_sha256=None):
    data, identity = _source(path, expected_sha256)
    module = types.ModuleType(name)
    module.__file__ = str(Path(path).absolute())


    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        exec(compile(data, module.__file__, 'exec'), vars(module))
    except BaseException:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
        raise
    return module, identity


def _verify_function(module, name, path, expected_sha256=None):
    data, identity = _source(path, expected_sha256)
    require(Path(module.__file__).absolute() == Path(path).absolute(), 'unexpected module source')
    functions = [code for code in compile(data, str(path), 'exec').co_consts
                 if isinstance(code, types.CodeType) and code.co_name == name]
    function = getattr(module, name, None)
    require(len(functions) == 1 and isinstance(function, types.FunctionType)
            and function.__globals__ is vars(module) and function.__closure__ is None
            and function.__code__ == functions[0], 'loaded function differs from exact source: ' + name)
    return identity


@contextmanager
def _install_factory(structural_module, factory, evict):

    original_factory = structural_module.structural_adapter
    originals = {}

    def replacement(A, arms, scratch, checkpoints):
        features = A.features
        key = id(features)
        if key not in originals:
            originals[key] = (features, features._evict)
            features._evict = evict
        else:
            require(originals[key][0] is features and features._evict is evict,
                    'installed eviction was replaced during the run')
        try:

            return factory(A, arms, scratch, checkpoints)
        except BaseException:
            previous_features, previous_evict = originals.pop(key)
            previous_features._evict = previous_evict
            raise

    structural_module.structural_adapter = replacement
    try:
        yield
    finally:
        structural_module.structural_adapter = original_factory
        for features, original_evict in originals.values():
            features._evict = original_evict


@contextmanager
def install(structural_module=None):

    if structural_module is None:
        import structural_projection as structural_module
    base = _verify_function(structural_module, 'structural_adapter',
                            AF / 'code/structural_projection.py', BASE_ADAPTER_SHA256)
    core, core_identity = _load_source('_forecast_binding_speed3_core', HERE / 'speed_core.py')
    _verify_function(core, 'structural_adapter', HERE / 'speed_core.py')
    eviction, eviction_identity = _load_source('_forecast_binding_speed3_eviction',
                                              F5 / 'eviction_patch.py', F5_EVICTION_SHA256)
    _verify_function(eviction, 'evict', F5 / 'eviction_patch.py', F5_EVICTION_SHA256)
    proof = dict(schema='FORECAST_BINDING_SPEED3_IN_PROCESS_INTEGRATION_V1',
                 base_adapter=base, speed_core=core_identity, reviewed_eviction=eviction_identity,
                 eviction_installed_before_adapter_copy=True, restores_on_every_exit=True,
                 host_launch_bytes_changed=False, frozen_rebuild_or_predict_changed=False,
                 gate_or_parity_functions_replaced=False, host_eligibility_granted=False)
    with _install_factory(structural_module, core.structural_adapter, eviction.evict):
        yield proof
