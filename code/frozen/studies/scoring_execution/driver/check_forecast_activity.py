'Check whether a forecast calculation is active.'
import argparse
import json
from pathlib import Path
from forecast_activity_checks import installed
from forecast_check_helpers import exclusive, now, row
from forecast_processes import exception_detail

HERE = Path(__file__).absolute().parent
PROJECT = HERE.parents[3]


def certify(native, receipt_root):

    with native.installed(), installed(native, 'guard-dry-run', dict(
            phase='PREPARE_WHOLE_ACTIVITY_GUARD_ONLY', no_AF_action=True), receipt_root=receipt_root):
        native.c61()
        bridge = native.af('runtime_bridge')
        modules = bridge.frozen_modules()
        host = modules['run_bound_forecasts']
        wrapper = native.af('forecast_wrapper')
        with bridge.actual_entry_metadata(host), wrapper.extend_activity_guard(host), wrapper.include_science_entry(host):
            host.no_overlap(modules['forecast_inputs'].root_mapping_contract())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='New exclusive receipt directory')
    args = parser.parse_args(argv)
    args.out = args.out.absolute()
    from forecast_check_helpers import metadata_path, require
    metadata_path(args.out)
    require(any(args.out.is_relative_to(HERE/version) for version in ('a6','a7')), 'Dry receipts must remain in driver/a6 or driver/a7')
    args.out.mkdir(parents=True, exist_ok=False)
    outcome = 'REFUSE'; detail = None; identities = []; sources = None
    try:
        from forecast_checks_cli import source_catalog
        from forecast_readers import Native
        catalog, sources, own = source_catalog(PROJECT)
        certify(Native(PROJECT, catalog, sources), args.out/'receipts')
        sources.recheck()
        identities = own
        outcome = 'PASS'
    except Exception as exc:
        detail = exception_detail(exc)
    receipts = [row(p) for p in sorted((args.out/'receipts').glob('*.json'))]
    exits = [json.loads(Path(r['path']).read_bytes()) for r in receipts]
    exits = [r for r in exits if r['phase']=='adapter_exit']
    if exits and exits[-1].get('exception'): detail = exits[-1]['exception']
    result = exclusive(args.out/'RESULT.json', dict(schema='MINRUN_TIME_ALIGNMENT_A6_GUARD_DRY_RUN_V1',
        utc=now(), outcome=outcome, exception=detail, activity_certified=outcome=='PASS',
        receipt_identities=receipts, build=row(HERE/'AF_CHAIN_BUILD.json'), verified_driver_sources=identities,
        same_uid_scope=exits[-1].get('same_uid_scope', {}) if exits else {},
        certification_attempts=exits[-1].get('certification_attempts', []) if exits else [],
        no_AF_action=True, no_freeze=True, no_TSA=True, no_protected_payload_reads=True,
        limitation='Root and other-UID/system processes are not inspected.'))
    print(json.dumps(dict(outcome=outcome, exception=detail, receipt=result), ensure_ascii=False, indent=2))
    return 0 if outcome=='PASS' else 2


if __name__=='__main__': raise SystemExit(main())
