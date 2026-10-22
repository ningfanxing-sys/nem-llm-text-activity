'Check the forecast source chain from the command line.'
import argparse
import json
from pathlib import Path
import sys
from forecast_check_helpers import (accepted, checked, document, exact_union, exclusive, flags,
                           load_control, now, require, row, utc)
from forecast_time_alignment import create_closure, evidence_manifest
from forecast_readers import Native, AF_REL, C_REL
from forecast_runtime_metadata import AM3
from forecast_timestamps import create_verify_bind
from source_bytes import Sources

HERE = Path(__file__).absolute().parent
ACTIONS = ('c-v1-time_alignment-closure', 'freeze-science', 'freeze-science-addendum', 'c-v1-association', 'af-mapping-refresh', 'af-final-source-publish',
           'am3-source-freeze', 'af-source-freeze', 't4g-create-verify-bind', 'af-execute', 'verify-seal')
FLAGS = ('FORECAST_BINDING_SOURCE_MAPPING_REFRESH', 'FORECAST_BINDING_SOURCE_SOURCE_COMMITMENT',
         'FORECAST_BINDING_SOURCE_FREEZE', 'FORECAST_BINDING_SOURCE_TIMESTAMP_BIND', 'FORECAST_BINDING_SOURCE_RUN')


def source_catalog(project):
    catalog = json.loads((HERE / 'AF_CHAIN_SOURCES.json').read_bytes())
    rows = [dict(r, logical_path=str(Path(project) / r['logical_path']),
                 path=str(Path(project) / r['path'])) for r in catalog['files']]
    build = json.loads((HERE / 'AF_CHAIN_BUILD.json').read_bytes())
    build_sources = [dict(path=str(HERE / name), **pin) for name, pin in build['files'].items()]
    build_sources.append(row(HERE / 'AF_CHAIN_BUILD.json'))
    for item in build_sources:
        rows.append(dict(item, logical_path=item['path']))
    return catalog, Sources(rows), build_sources


def science_inventory(native, build_sources):
    paths = set(str(native.project / x['logical_path']) for x in native.catalog['c_v1'])
    paths.update(str(native.project / x['logical_path']) for x in native.catalog['af_v3'])
    paths.update(str(native.project / x['logical_path']) for x in native.catalog['am3_part_a'])
    score_sources=[]
    if 'files' in native.catalog:
        score_build = json.loads((HERE/'BUILD_IDENTITY.json').read_bytes())
        score_sources = [row(HERE/name) for name in score_build['files']] + [row(HERE/'BUILD_IDENTITY.json')]

    return exact_union([row(p, native.sources.bytes(p)) for p in sorted(paths)], [*build_sources,*score_sources])


def freeze_science(native, inputs, outputs, build, build_sources):
    inventory = science_inventory(native, build_sources)
    require(inputs['inventory'] == inventory, 'Limited exact scientific inventory missing/extra/drift')
    subject = dict(build=build, inventory=inventory, c_v1=native.c61()['sources'])
    review = accepted(inputs['source_review'], subject, sources=native.sources, role='DRIVER_AF_CHAIN_FINAL_SOURCE_REVIEW')
    for p in outputs.values():
        require(not Path(p).exists(), 'Exclusive science-freeze output already exists')

    c_value = native.freeze_c(inputs['c'], outputs['c_freeze'])
    value = dict(schema='MINRUN_LIMITED_SCIENCE_SOURCE_FREEZE_V1', utc=now(), inventory=inventory,
                 review=inputs['source_review'], build=build, c_authority=row(outputs['c_freeze']),
                 source_association_only=True, production_authority=False)
    require(utc(value['utc']) >= utc(review['utc']), 'Science freeze follows genuine source review')
    exclusive(outputs['science_freeze'], value)
    return value


def verify_science(native, item, build, build_sources, addendum=None, *, static=False):
    value = document(item, native.sources)
    require(value.get('schema') == 'MINRUN_LIMITED_SCIENCE_SOURCE_FREEZE_V1' and
            value.get('production_authority') is False, 'Exact limited upstream source freeze required')
    accepted(value['review'], dict(build=value['build'], inventory=value['inventory'], c_v1=native.c61()['sources']),
             sources=native.sources, role='DRIVER_AF_CHAIN_FINAL_SOURCE_REVIEW')
    require(value['c_authority'] == row(native.c_root / 'SCIENCE_FREEZE.json'), 'Exact installed C freeze required')
    if static:
        native.time_alignment.validate_freeze(document(value['c_authority'],native.sources))
    else:native.c_authority()
    if addendum is None:
        require(value['inventory'] == science_inventory(native, build_sources) and value['build'] == build,
                'sensitivity_tests current driver bytes require actual science_addendum and fresh scoped GO')
    else:
        from forecast_context import verify_addendum
        verify_addendum(native, addendum, item, build, build_sources)
    return value


def run(action, control, native, build_sources):
    inputs, outputs = control['inputs'], control['outputs']
    build = control['build']
    require(not Path(outputs['receipt']).exists(), 'Stage receipt already exists; no overwrite')
    am3 = AM3(native, build_sources)
    from forecast_activity_checks import installed as activity_adapter
    with flags(FLAGS), native.installed(), activity_adapter(native, action, control):
        if action == 'c-v1-time_alignment-closure':
            require(inputs['evidence'] == evidence_manifest(), 'Exact existing TIME_ALIGNMENT-A1 evidence manifest required')
            result = create_closure(inputs['evidence'], outputs['closure'], sources=native.sources)
        elif action == 'freeze-science':
            result = freeze_science(native, inputs, outputs, build, build_sources)
        elif action == 'freeze-science-addendum':
            from forecast_context import create_addendum


            original=document(inputs['science_freeze'],native.sources)
            accepted(original['review'],dict(build=original['build'],inventory=original['inventory'],c_v1=native.c61()['sources']),
                     sources=native.sources,role='DRIVER_AF_CHAIN_FINAL_SOURCE_REVIEW')
            require(original['c_authority']==row(native.c_root/'SCIENCE_FREEZE.json'),'Original C freeze drift')
            native.c_authority()
            result = create_addendum(native, inputs, outputs, build, build_sources)
        elif action == 'c-v1-association':
            verify_science(native, inputs['science_freeze'], build, build_sources, inputs.get('science_addendum'))
            result = native.c_authority()
        elif action in ('af-mapping-refresh', 'af-final-source-publish'):
            verify_science(native, inputs['science_freeze'], build, build_sources, inputs.get('science_addendum'))
            if action == 'af-mapping-refresh':
                require(outputs['mapping'] == str(native.af_root / 'FINAL_ROOT_MAPPING.json'), 'Native AF mapping output required')
                result = native.af('root_mapping').refresh()
            else:
                require(outputs['commitment'] == str(native.af_root / 'FINAL_SOURCE_COMMITMENT.json'), 'Native AF commitment output required')
                result = native.af('source_inventory').publish_final_source()
        elif action == 'am3-source-freeze':
            verify_science(native, inputs['science_freeze'], build, build_sources, inputs.get('science_addendum'))
            result = am3.create(inputs, outputs['am3_freeze'])
        elif action == 'af-source-freeze':
            verify_science(native, inputs['science_freeze'], build, build_sources, inputs.get('science_addendum'))
            am3.verify(inputs['am3_freeze'])
            require(not (native.af_root / 'BASE_CODE_FREEZE.json').exists() and
                    not (native.af_root / 'OVERLAY_FREEZE.json').exists(), 'Exclusive AF freeze outputs already exist')
            for name in ('review_acceptance', 'consumer_acceptance', 'attestation'):
                checked(inputs[name], native.sources)
            result = native.af('freeze_science').create(Path(inputs['review_acceptance']['path']),
                        Path(inputs['consumer_acceptance']['path']), Path(inputs['attestation']['path']))
        else:
            require(action == 't4g-create-verify-bind', 'Unknown source-only chain action')
            verify_science(native, inputs['science_freeze'], build, build_sources, inputs.get('science_addendum'))
            return create_verify_bind(native, am3, inputs, outputs, build_sources)
        receipt = dict(schema='MINRUN_AF_CHAIN_STAGE_RECEIPT_V1', action=action, utc=now(),
                       build=build, permit=control['permit'], source_catalog=control['source_catalog'],
                       inputs=inputs, result=result, production_authority=False)
        exclusive(outputs['receipt'], receipt)
        native.sources.recheck()
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=[*ACTIONS, 'check-control', 'verify-sources', 'guard-dry-run'])
    parser.add_argument('--control', type=Path)
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--for-action', choices=ACTIONS)
    args = parser.parse_args()
    project = HERE.parents[3]
    if args.action == 'guard-dry-run':
        require(args.out is not None and args.control is None, 'guard-dry-run requires --out only; no CONTROL action')
        from check_forecast_activity import main as dry_main
        return dry_main(['--out', str(args.out)])
    if args.action in ('af-execute','verify-seal') or (args.action=='check-control' and args.for_action in ('af-execute','verify-seal')):
        from forecast_entry import main as runtime_main
        return runtime_main(sys.argv[1:])
    if args.action == 'c-v1-time_alignment-closure' and args.control is None:
        require(args.evidence is not None and args.out is not None, '--evidence and --out required')
        actual = json.loads(args.evidence.read_bytes())
        require(actual == evidence_manifest(), 'Exact existing source TIME_ALIGNMENT-A1 evidence required')
        require(args.out.absolute().parent == HERE, 'Source-only closure output must remain in driver')
        create_closure(actual, args.out)
        print('TIME_ALIGNMENT C-V1 closure written: targeted + SOURCE READY + GO; full suite NOT_RUN_B_CLASS')
        return 0
    if args.action == 'verify-sources':
        catalog, sources, own = source_catalog(project)
        print(json.dumps(dict(source_files=len(catalog['files']), c_v1=len(catalog['c_v1']),
                              archived_c=sum(r['path'] != r['logical_path'] for r in catalog['c_v1']), drift=0)))
        return 0
    require(args.control is not None, '--control is required')
    build = row(HERE / 'AF_CHAIN_BUILD.json')
    action = args.for_action if args.action == 'check-control' else args.action
    require(action in ACTIONS, '--for-action required for check-control')
    if args.action == 'check-control':
        from forecast_static_checks import check
        paper=json.loads(args.control.read_bytes())
        result=check(paper,action,build=build,catalog=row(HERE/'AF_CHAIN_SOURCES.json'))
        if result['blockers']:
            print(json.dumps(result,ensure_ascii=False,indent=2))
            print('STOP: PENDING CONTROL or static gate blockers',file=sys.stderr)
            return 2
    control = load_control(args.control, action, build)
    require(control['project'] == str(project), 'Exact project root required')
    require(control['source_catalog'] == row(HERE / 'AF_CHAIN_SOURCES.json'), 'Accepted AF-chain catalog required')
    catalog, sources, own = source_catalog(project)
    if args.action == 'check-control':
        from forecast_static_checks import check
        kwargs=dict(sources=sources,build=build,catalog=row(HERE/'AF_CHAIN_SOURCES.json'))
        if action=='freeze-science':
            native=Native(project,catalog,sources)
            with native.installed():
                c61=native.c61()['sources']
                kwargs.update(inventory=science_inventory(native,own),c61={str(Path(p).relative_to(native.c_root)):r for p,r in c61.items()})
                native.time_alignment.verify(control['inputs']['c']['time_alignment_closure'])
                from forecast_source_contracts import numeric,policy
                numeric(control['inputs']['c']['numeric_ancestor_contract'],native)
                policy(document(control['inputs']['c']['release_binding'],sources),native)
                accepted(control['inputs']['source_review'],dict(build=build,inventory=kwargs['inventory'],c_v1=c61),
                         sources=sources,role='DRIVER_AF_CHAIN_FINAL_SOURCE_REVIEW')
        elif action=='freeze-science-addendum':
            from forecast_context import addendum_subject
            native=Native(project,catalog,sources)
            with native.installed():
                subject=addendum_subject(native,control['inputs'],build,own)
                accepted(control['inputs']['source_review'],subject,sources=sources,role='DRIVER_AF_CHAIN_FINAL_SOURCE_REVIEW')
        elif action in ('c-v1-association','af-mapping-refresh','af-final-source-publish',
                        'am3-source-freeze','af-source-freeze','t4g-create-verify-bind'):
            native=Native(project,catalog,sources)
            with native.installed():
                verify_science(native,control['inputs']['science_freeze'],build,own,control['inputs'].get('science_addendum'),static=True)
        result=check(control,action,**kwargs)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 2 if result['blockers'] else 0
    native = Native(project, catalog, sources)
    run(action, control, native, own)
    print('Completed source-only AF-chain stage: ' + action)
    return 0
