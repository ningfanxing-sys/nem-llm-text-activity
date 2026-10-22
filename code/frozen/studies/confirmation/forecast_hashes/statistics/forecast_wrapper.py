'Run forecasts with checked numerical inputs and resource limits.'
from pathlib import Path
from contextlib import contextmanager,ExitStack
import sys
import metadata_io as io
from science_contract import require,SCOPE,CALENDAR_RULE
from runtime_bridge import frozen_modules,metadata_aliases,actual_entry_metadata
HERE=io.AF/'availability_delays'
AF=io.AF
PARENT=AF/'deadline_checks'
ADAPTER_SEAMS={'delay_root_mapping':'statistics/root_mapping.py',
 'delay_final_source':'statistics/source_inventory.py','delay_freeze':'statistics/freeze_science.py'}
RETAINED=('clock','coverage','identity','before_T5','no_overlap','full_D_specified_bank_byte_parity',
 'prediction_byte_parity','specified_delayed_prediction_byte_parity','resource_checkpoints',
 'actual_combined_corrected_seal_precedes_T5','zero_refit')


def load_source(name,path):
    from runtime_bridge import pinned_source
    path,pin=pinned_source(Path(path).relative_to(io.PROJ).as_posix())
    return io.load_source(name,path,pin)

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

def integration_plan(*, numerical_inventory, selected_speed, stable_c_contract):
    require(numerical_inventory and selected_speed, 'Exact inherited sources required')
    return dict(schema='AF_SCORING_HOST_INTEGRATION_PLAN_V1', scope=SCOPE,
                calendar_rule=CALENDAR_RULE, numerical_inventory=numerical_inventory,
                selected_speed=selected_speed, adapter_seams=ADAPTER_SEAMS,
                retained_gates=list(RETAINED),
                speed_install='OV2.speed_binding.install_speed_overlay before structural_adapter copies A.features',
                eviction='Reviewed SET5 msync(MS_INVALIDATE); restore original _evict on exit/exception',
                pass_order='Unchanged OV2.delay_patch/delay_core 12-pass order',
                c_api_stable=stable_c_contract.get('stable') is True,
                executable=True, runtime_authority=False,
                pending='Actual C acceptance/review/timestamp_checks, mapping/publication, AF acceptances and source release')

@contextmanager
def include_science_entry(host):

    from activity_guard import refuse_metadata,read_lsof_snapshot,process_entry
    old=host.no_overlap
    def guarded(roots=None,**kwargs):
        original_provider=kwargs.get('snapshot_provider') or read_lsof_snapshot
        def snapshots():
            rows=original_provider()
            mapping=roots or frozen_modules()['forecast_inputs'].root_mapping_contract()
            contract=dict(mapping['activity_guard'])
            contract['entry_files']=[*contract['entry_files'],str(io.HERE/'forecast_wrapper.py')]
            refuse_metadata(contract,rows)
            return rows
        kwargs['snapshot_provider']=snapshots
        mapping=roots or frozen_modules()['forecast_inputs'].root_mapping_contract()
        contract=dict(mapping['activity_guard'])
        contract['entry_files']=[*contract['entry_files'],str(io.HERE/'forecast_wrapper.py')]
        original_recognizer=kwargs.get('legacy_recognizer')
        if original_recognizer is None:
            from runner import fitting_argv as original_recognizer
        kwargs['legacy_recognizer']=lambda argv,cwd: process_entry(argv,cwd,contract,host._launch_tail) or original_recognizer(argv,cwd)
        return old(roots,**kwargs)
    host.no_overlap=guarded
    try:yield
    finally:host.no_overlap=old


def run(activation_path=None,*,verify_seal=False):
    io.phase(source_flag='FORECAST_BINDING_SOURCE_RUN')
    require(verify_seal or activation_path is not None,'Explicit activation required')
    m=frozen_modules();common=m['common'];common.resources();common.install_audit()
    import freeze_science,source_inventory
    provider=__import__('runtime_bridge').delay_freezer_provider()
    with metadata_aliases([provider,common,m['run_bound_forecasts'],m['delay_authority']]):
        release=freeze_science.verify_delay_release();final=source_inventory.verify_final_source()
        commitment=io.identity(io.HERE/'FINAL_SOURCE_COMMITMENT.json')
        require(release['final_source_commitment']==commitment and
                final['final_root_mapping']==release['final_root_mapping'],'Scientific final-source/release drift')
        speed=m['delay_speed_binding'].verify_speed_delivery()
        require(release['speed_overlay_binding']==final['speed_overlay_binding']==speed,
                'Final commitment/release must bind exact selected SPEED3')
        host=m['run_bound_forecasts']
        with actual_entry_metadata(host),m['delay_patch'].install(host,(AF/'code/run_bound_forecasts.py').read_bytes()), \
                extend_activity_guard(host),include_science_entry(host),m['delay_speed_binding'].install_speed_overlay(speed):
            if verify_seal:
                frozen=host.verify_code();host.no_overlap(frozen['root_mapping'])
                host.require_before_t5(frozen['root_mapping'],frozen['timestamp_root_identity'])
                value=m['delay_core'].verify_combined_seal(AF/'SEAL_FORECAST_BINDING.json')
                require(value['binding']['delay_authority']==release,'Corrected combined seal/release mismatch')
                host.require_before_t5(frozen['root_mapping'],frozen['timestamp_root_identity'])
                return value
            activation=common.read_json(activation_path)
            validate_activation(activation,release,commitment)
            return host.dispatch(activation_path)


def main():
    io.phase(source_flag='FORECAST_BINDING_SOURCE_RUN')
    import argparse
    p=argparse.ArgumentParser();m=p.add_mutually_exclusive_group(required=True)
    m.add_argument('--execute',action='store_true');m.add_argument('--verify-seal',action='store_true')
    p.add_argument('--activation',type=Path);a=p.parse_args()
    require((a.execute and a.activation is not None) or (a.verify_seal and a.activation is None),'Activation/verification argv contract')
    run(a.activation,verify_seal=a.verify_seal)

if __name__=='__main__':main()
