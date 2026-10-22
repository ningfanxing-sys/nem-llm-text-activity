'Dispatch the checked forecast input calculation.'
import argparse
import json
from pathlib import Path
from forecast_checks_cli import source_catalog, FLAGS
from forecast_check_helpers import document, exclusive, flags, load_control, now, require, row
from forecast_readers import Native
from forecast_static_checks import check
from forecast_receipts import receipt_directory


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('af-execute','verify-seal','check-control'))
    parser.add_argument('--for-action',choices=('af-execute','verify-seal'))
    parser.add_argument('--control',required=True,type=Path)
    args=parser.parse_args(argv)
    here=Path(__file__).absolute().parent;project=here.parents[3]
    action=args.for_action if args.action=='check-control' else args.action
    require(action in ('af-execute','verify-seal'),'Explicit runtime action required')
    paper=json.loads(args.control.read_bytes())
    result=check(paper,action,build=row(here/'AF_CHAIN_BUILD.json'),catalog=row(here/'AF_CHAIN_SOURCES.json'))
    if result['blockers']:
        print(json.dumps(result,ensure_ascii=False,indent=2));__import__('sys').stderr.write('STOP: PENDING CONTROL or static gate blockers\n');return 2
    control=load_control(args.control,action,row(here/'AF_CHAIN_BUILD.json'))
    if args.action=='check-control':print(json.dumps(result));return 0

    from forecast_score_inputs import installed
    directory=receipt_directory(project,action,control['outputs']['receipt'])
    directory.mkdir(parents=True,exist_ok=False)
    catalog,sources,own=source_catalog(project)
    native=Native(project,catalog,sources)
    import types
    placeholder=types.SimpleNamespace(scientific_provider=None)

    from forecast_activity_checks import installed as activity_adapter
    from forecast_resource_limits import installed as resource_adapter
    with resource_adapter(native,action), installed(control['inputs']['am3_t4g'],placeholder),flags(FLAGS),native.installed(), activity_adapter(native,action,row(args.control),receipt_root=directory/'activity'):
        binding=document(control['inputs']['am3_t4g'],sources)
        completion=document(binding['t4g_completion'],sources)

        with native.crypto(completion['union']):
            start=now()
            if action=='af-execute':
                document(control['inputs']['activation'],sources)
                native.af('forecast_wrapper').run(Path(control['inputs']['activation']['path']))
            else:native.af('forecast_wrapper').run(verify_seal=True)
            value=dict(schema='MINRUN_AF_RUNTIME_COMMAND_RECEIPT_V1',action=action,argv=[__import__('sys').executable,*__import__('sys').argv],
                       control=row(args.control),build=control['build'],receipt_directory=str(directory),started_utc=start,completed_utc=now(),exit_code=0,
                       source=row(native.af_root/'forecast_wrapper.py',sources.bytes(native.af_root/'forecast_wrapper.py')),
                       verification_scope='UNCHANGED_COMPLETE_COMBINED_SEAL_VERIFIER' if action=='verify-seal' else 'NATIVE_AF_EXECUTION')
            exclusive(control['outputs']['receipt'],value)
    return 0

if __name__=='__main__':raise SystemExit(main())
