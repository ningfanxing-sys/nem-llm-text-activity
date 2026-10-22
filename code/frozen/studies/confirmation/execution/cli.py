"""Ordered, resumable CONF host commands. Production commands always verify global freeze."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import traceback
from runtime import (STATE, ROOT, CONF, atomic_json, exclusive_lock, install_audit,
                     validate_permit, read_json, utc_now, file_identity, sha256)

COMMANDS = ['freeze', 'panels', 'features', 'counted-pilots', 'fit-bank', 'lear', 'seal', 'score']

def dispatch(command, state):
    state = Path(state)
    if command == 'freeze':
        from global_input_freeze import global_input_freeze
        return global_input_freeze(state_root=state)
    permit = validate_permit(receipt_path=state / 'EXECUTION_AUTHORIZATION.json')
    inputs = read_json(state / 'COMPLETE_INPUT_FREEZE.json')
    if command == 'panels':
        from panels_adapter import build_panels
        return build_panels(permit, state / 'panels', catalog=read_json(inputs['source_catalog_path']))
    if command == 'features':
        from features_adapter import build_all_features
        return build_all_features(permit, state / 'panels', state / 'features', input_freeze=inputs)
    if command == 'counted-pilots':
        from execution_adapter import counted_pilots
        return counted_pilots(permit, state / 'features', state)
    if command == 'fit-bank':
        from execution_adapter import run_fits
        return run_fits(permit, state / 'features', state, until='secondary_news')
    if command == 'lear':
        from execution_adapter import run_lear_and_remaining
        return run_lear_and_remaining(permit, state / 'features', state)
    if command == 'seal':
        from seal_score import seal
        return seal(permit, state / 'features', state)
    if command == 'score':
        from seal_score import score
        return score(permit, state / 'features', state)
    raise ValueError(command)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=COMMANDS)
    p.add_argument('--state', type=Path, default=STATE)
    args = p.parse_args(argv)
    if args.state.resolve() != STATE.resolve():
        p.error('CONF host execution uses the canonical host_state; changing it cannot reset the fitting budget')
    install_audit('host_' + args.command.replace('-', '_'))
    with exclusive_lock(args.state / '.host.lock'):
        failure_path=args.state / ('FAILED_' + args.command + '.json')
        prior_failure=file_identity(failure_path) if failure_path.exists() else None
        try:
            result = dispatch(args.command, args.state)
            if args.command == 'features':
                completion_path=args.state/'COMPLETE_features.json'
                manifest_identity=file_identity(args.state/'features/manifest.json')
                if completion_path.exists():
                    previous=read_json(completion_path)
                    if previous['feature_manifest']!=manifest_identity:
                        raise RuntimeError('Completed feature receipt identity drift')
                else:
                    atomic_json(completion_path,{'state':'COMPLETE','command':'features','time_utc':utc_now(),
                        'feature_manifest':manifest_identity,'adapter_freeze_sha256':sha256(ROOT/'ADAPTER_FREEZE.json'),
                        'supersedes_failed_receipt':prior_failure,
                        'failed_receipt_retained':bool(prior_failure),'partial_outputs_must_not_be_scored':False},immutable=True)
        except Exception as exc:
            # Retain the original disk failure. Retries create a distinct receipt
            # until successful features completion explicitly supersedes it.
            new_failure_path=failure_path
            if args.command=='features' and prior_failure:
                new_failure_path=args.state/('FAILED_features_attempt_'+utc_now().replace(':','-')+'.json')
            atomic_json(new_failure_path,
                        {'state':'STOPPED', 'command':args.command, 'time_utc':utc_now(),
                         'exception':type(exc).__name__, 'reason':str(exc),
                         'traceback':traceback.format_exc(),
                         'partial_outputs_must_not_be_scored':True,
                         'previous_failed_receipt':prior_failure})
            raise
    print(json.dumps({'command':args.command, 'state':result.get('state','COMPLETE'),
                      'receipt_directory':str(args.state.resolve())}))

if __name__ == '__main__': main()
