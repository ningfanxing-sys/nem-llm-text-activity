'Run notice forecasts with the specified availability delays.'
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import types

sys.dont_write_bytecode=True
HERE=Path(__file__).absolute().parent
AF=HERE.parent
PARENT=AF/'deadline_checks'


def load_source(name,path):
    module=types.ModuleType(name); module.__file__=str(path); sys.modules[name]=module
    exec(compile(Path(path).read_bytes(),str(path),'exec'),vars(module))
    return module


def require(ok,message):
    if not ok: raise PermissionError(message)


def validate_activation(activation,release,commitment):
    from delay_patch import SCOPE

    parent=load_source('_forecast_binding8_parent_wrapper',PARENT/'forecast_wrapper.py')
    parent.validate_activation(activation,release,commitment)
    require(activation.get('delay_release')==release,'Complete corrected-delay release required')
    require(activation.get('review8_decision_authority')==release['review8_decision_authority'],
            'Activation REVIEW8/D1 decision binding drift')
    require(activation.get('corrected_delay_scope')==SCOPE,'Activation corrected-delay scope drift')
    require(activation.get('dly8_r8_finished') is True and
            activation.get('delayed_month_first_parity_required') is True,
            'DLY8-R8 completion and specified-delay parity acknowledgement required')
    return True


@contextmanager
def extend_activity_guard(host):

    from activity_guard import process_entry,refuse_metadata,read_lsof_snapshot
    original=host.no_overlap
    def extended(roots=None,*,process_api=None,legacy_recognizer=None,snapshot_provider=None):
        from forecast_inputs import root_mapping_contract
        if legacy_recognizer is None:
            from runner import fitting_argv as legacy_recognizer
        mapping=roots or root_mapping_contract()
        contract=dict(mapping['activity_guard'])
        contract['entry_files']=[*contract['entry_files'],str(HERE/'forecast_wrapper.py'),str(PARENT/'forecast_wrapper.py')]
        def snapshot():
            records=(snapshot_provider or read_lsof_snapshot)()
            refuse_metadata(contract,records)
            return records
        def recognizer(argv,cwd):
            return process_entry(argv,cwd,contract,host._launch_tail) or legacy_recognizer(argv,cwd)
        return original(mapping,process_api=process_api,legacy_recognizer=recognizer,snapshot_provider=snapshot)
    host.no_overlap=extended
    try:
        yield
    finally:
        host.no_overlap=original


def run(activation_path=None,*,verify_seal=False):
    require(os.environ.get('FORECAST_BINDING_SOURCE_RUN')=='1','Source-only host action')
    require(verify_seal or activation_path is not None,'Explicit activation required')
    sys.path[:0]=[str(HERE),str(PARENT),str(AF/'code')]
    common=load_source('common',AF/'code/common.py')
    common.install_audit(); common.resources()
    sys.path.insert(0,str(common.B/'code'))

    for name in ('timestamp_checks','deadline_patch'):
        load_source(name,PARENT/(name+'.py'))
    for filename,name in (('timestamp_checks','delay_authority'),('root_mapping','delay_root_mapping'),
                          ('speed_binding','delay_speed_binding'),
                          ('source_inventory','delay_final_source'),('delay_patch','delay_patch'),
                          ('delay_core','delay_core'),('freeze_delay','delay_freeze')):
        load_source(name,HERE/(filename+'.py'))
    import delay_authority,delay_final_source,delay_freeze,delay_patch,delay_core,delay_speed_binding
    release=delay_freeze.verify_delay_release()
    final=delay_final_source.verify_final_source()
    commitment=delay_authority.identity(HERE/'FINAL_SOURCE_COMMITMENT.json')
    require(release['final_source_commitment']==commitment and
            final['final_root_mapping']==release['final_root_mapping'],
            'Final delay source commitment/runtime release drift')
    speed=delay_speed_binding.verify_speed_delivery()
    require(release.get('speed_overlay_binding')==speed and final.get('speed_overlay_binding')==speed,
            'Final commitment/release must bind the exact clean SPEED3 delivery')
    load_source('structural_projection',AF/'code/structural_projection.py')
    host=load_source('run_bound_forecasts',AF/'code/run_bound_forecasts.py')
    with delay_patch.install(host,(AF/'code/run_bound_forecasts.py').read_bytes()),extend_activity_guard(host), \
            delay_speed_binding.install_speed_overlay(speed):
        if verify_seal:
            frozen=host.verify_code()
            host.no_overlap(frozen['root_mapping'])
            host.require_before_t5(frozen['root_mapping'],frozen['timestamp_root_identity'])
            value=delay_core.verify_combined_seal(AF/'SEAL_FORECAST_BINDING.json')
            require(value['binding']['delay_authority']==release,'Corrected seal/runtime release mismatch')
            host.require_before_t5(frozen['root_mapping'],frozen['timestamp_root_identity'])
            print('Verified one corrected +5/+15/+60 seal before T5; no values printed')
            return value
        activation=common.read_json(activation_path)
        validate_activation(activation,release,commitment)
        return host.dispatch(activation_path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--execute',action='store_true'); modes.add_argument('--verify-seal',action='store_true')
    parser.add_argument('--activation',type=Path); args=parser.parse_args()
    require((args.execute and args.activation is not None) or (args.verify_seal and args.activation is None),
            'Execute requires activation; verification does not consume activation')
    run(args.activation,verify_seal=args.verify_seal)


if __name__=='__main__':main()
