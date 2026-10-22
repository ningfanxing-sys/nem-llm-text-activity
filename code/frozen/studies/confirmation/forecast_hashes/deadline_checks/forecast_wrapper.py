'Run notice forecasts with the specified deadline checks.'
import argparse
import os
from pathlib import Path
import sys
import types

sys.dont_write_bytecode = True
HERE = Path(__file__).absolute().parent
AF = HERE.parent


def load_source(name, path):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(Path(path).read_bytes(), str(path), 'exec'), vars(module))
    return module


def require(ok, message):
    if not ok:
        raise PermissionError(message)


def validate_activation(activation, release, commitment):

    require(isinstance(activation, dict) and activation.get('overlay_release') == release,
            'Activation must bind the complete verified AM1/AM2 overlay release')
    require(activation.get('final_source_commitment') == commitment,
            'Activation must bind the verified final AF source commitment')
    require(activation.get('calendar_rule') == 'NO_CALENDAR_DEADLINE_CORRECTED_SEAL_PRECEDES_T5',
            'Specification-2 no-calendar chronology must be acknowledged')
    require(activation.get('deadline_rule_acknowledged') is True,
            'Frozen chronology attestation remains required')


    return True


def run(activation_path=None, *, verify_seal=False):
    require(os.environ.get('FORECAST_BINDING_SOURCE_RUN') == '1', 'Source-only host action')
    require(verify_seal or activation_path is not None, 'Explicit activation path required')
    sys.path[:0] = [str(HERE), str(AF/'code')]
    common = load_source('common', AF/'code/common.py')
    common.install_audit()
    common.resources()


    for name in ('timestamp_checks','root_mapping','deadline_patch','source_inventory','freeze_overlay'):
        load_source(name, HERE/(name+'.py'))
    import freeze_overlay
    import source_inventory
    from deadline_patch import install
    release = freeze_overlay.verify_overlay_release()
    final = source_inventory.verify_final_source()
    commitment = source_inventory.identity(HERE/'FINAL_SOURCE_COMMITMENT.json')
    require(release['final_source_commitment'] == commitment
            and final['final_root_mapping'] == release['final_root_mapping'],
            'Final source commitment and overlay release differ')
    host = load_source('run_bound_forecasts', AF/'code/run_bound_forecasts.py')
    source = (AF/'code/run_bound_forecasts.py').read_bytes()
    with install(host, source):
        if verify_seal:


            path = AF/'code/verify_forecast_binding.py'
            namespace = dict(__name__='__main__', __file__=str(path))
            exec(compile(path.read_bytes(), str(path), 'exec'), namespace)
            return None
        activation = common.read_json(activation_path)
        validate_activation(activation, release, commitment)
        return host.dispatch(activation_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--execute', action='store_true')
    modes.add_argument('--verify-seal', action='store_true')
    parser.add_argument('--activation', type=Path)
    args = parser.parse_args()
    if args.execute:
        require(args.activation is not None, '--execute requires --activation')
    else:
        require(args.activation is None, '--verify-seal does not consume an activation file')
    run(args.activation, verify_seal=args.verify_seal)


if __name__ == '__main__':
    main()
