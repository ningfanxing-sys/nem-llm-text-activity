'Read forecast source metadata for notice-delay scoring.'
from contextlib import contextmanager
import json
from pathlib import Path
import sys
from forecast_check_helpers import checked, document, flags, require, row


def scoring_catalog(project):

    from source_bytes import Sources, checked as current_checked, document as current_document
    here = Path(__file__).absolute().parent
    catalog = json.loads((here/'AF_CHAIN_SOURCES.json').read_bytes())
    build = json.loads((here/'AF_CHAIN_BUILD.json').read_bytes())
    current = current_document(row(here/'BUILD_IDENTITY.json'))
    history = document(dict(path=str(Path(project)/'paper_plan/minrun_execution_20261010/t5_final/a18b_resources_route_20261011_01/AF_SOURCE_HISTORY.json'),
        bytes=2155, sha256='995e8082f635cf248994159f45fd2d19d50012f44ba56c0d7b644bf253642d92'))['files']
    rows = [dict(r, logical_path=str(Path(project)/r['logical_path']),
                 path=str(Path(project)/r['path'])) for r in catalog['files']]
    own = [dict(path=str(here/name), **pin) for name,pin in build['files'].items()]
    own.append(row(here/'AF_CHAIN_BUILD.json'))
    for item in own:
        name = Path(item['path']).name
        live = dict(path=item['path'], **current['files'][name]) if name in (
            'source_bytes.py', 'forecast_score_inputs.py', 'forecast_resource_limits.py') else item
        if live != item:
            matches = [r for r in history if r['original'] == item]
            require(len(matches) == 1 and all(matches[0]['archive'][k] == item[k]
                    for k in ('bytes','sha256')), 'A16 exact old AF importer archive missing/mismatched')
            current_checked(matches[0]['archive'])
        current_checked(live)
        rows.append(dict(live, logical_path=live['path']))


    helper=dict(path=str(here/'forecast_reading_functions.py'), **current['files']['forecast_reading_functions.py'])
    current_checked(helper)
    rows.append(dict(helper, logical_path=helper['path']))
    return catalog, Sources(rows), own


@contextmanager
def installed(contract_identity, forecast_metadata):
    from forecast_checks_cli import FLAGS
    from forecast_readers import Native
    from forecast_runtime_metadata import AM3
    from forecast_timestamps import T4G
    project = Path(__file__).absolute().parent.parents[3]
    catalog, sources, own = scoring_catalog(project)
    binding = document(contract_identity, sources)
    require(binding['schema'] == 'MINRUN_RD_AM3_T4G_ASSOCIATION_V1',
            'Actual AM3/T4G read-only association required')
    native = Native(project, catalog, sources)
    from forecast_timestamp_history import HistoricalT4G
    historical = HistoricalT4G(native)
    historical.historical(binding['af_chain_build'])
    old_build = historical.document(binding['af_chain_build'])

    own = [dict(path=str(Path(__file__).parent/name), **pin) for name,pin in old_build['files'].items()]
    own.append(binding['af_chain_build'])
    reference_snapshot = {k:sys.modules.pop(k) for k in ('science_contract','metadata_io','runtime_bridge','root_mapping',
        'c_interface_adapter','freeze_science','source_inventory','speed_selection') if k in sys.modules}
    old_provider = forecast_metadata.scientific_provider
    try:
        with flags(FLAGS), native.installed(), historical.installed():
            am3 = AM3(native, own)
            completion = document(binding['t4g_completion'], sources)
            af_value = native.af('freeze_science').verify_delay_freeze()
            am_value = am3.verify(binding['am3_freeze'])
            require(completion['schema'] == 'MINRUN_AF_CHAIN_T4G_COMPLETION_V1', 'Genuine T4G completion required')
            from forecast_check_helpers import exact_union
            union = exact_union(am3.required_identities(binding['am3_freeze']),
                native.af('freeze_science').timestamp_required_identities(af_value))
            require(completion['union'] == union, 'Exact live AM3/AF union differs from T4G completion')
            t4g = T4G(native, union, am_value['utc'], af_value['utc'])
            require(completion['verification'] == t4g.verify(), 'Both actual T4G TSAs reverify')
            require(binding['am3_binding'] == completion['am3_binding'] and
                    binding['af_union_binding'] == completion['af_union_binding'], 'Both real bindings required')
            am3.verify(binding['am3_freeze'], require_timestamp=True, require_af_freeze=True,
                       t4g=t4g, binding=binding['am3_binding'])
            t4g.af_verify(binding['af_union_binding'])
            @contextmanager
            def provider():
                rows = forecast_metadata.reviewed_sources()
                modules = native.af('runtime_bridge').frozen_modules()
                try:
                    from forecast_reading_functions import installed as exact_metadata_leaves
                    with native.crypto(union), exact_metadata_leaves(modules['delay_authority'], project, af_value):
                        yield modules, native.af('freeze_science'), native.af('source_inventory')
                finally:
                    require(forecast_metadata.reviewed_sources() == rows, 'Same accepted AF42 source bytes')
            forecast_metadata.scientific_provider = provider
            yield
    finally:
        forecast_metadata.scientific_provider = old_provider
        for k in reference_snapshot: sys.modules[k] = reference_snapshot[k]
