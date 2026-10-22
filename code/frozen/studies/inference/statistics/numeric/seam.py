'Connect synthetic test inputs to the numerical calculations.'
import sys
from types import SimpleNamespace
from ..input_checks import HERE, artificial_accept, require, verify_source
from .assembly import assemble_numeric
from ..exporter.sensitivity_export import task_pair_export, replay_binding
from copy import deepcopy


def run_artificial(P, branch, runtime, manifest_path, expected, *, fixture_root,
                   chunk=512, gate):
    root = artificial_accept(fixture_root)
    require(runtime.final_reviewed_contract is not None, 'Pending C input/author/ancestor contract')
    require(runtime.synthetic_only is True, 'Artificial capability required')
    runtime.P=P
    runtime.check_sources_and_authority()
    runtime.verify_manifest_location(manifest_path, root)
    runtime.reverify_official_views()
    before_path, before_modules = list(sys.path), dict(sys.modules)
    old = {name: getattr(P, name) for name in ('dependencies', 'load_inputs', 'assemble_output', 'build')}
    def deps(*args, **kwargs):
        kwargs['consumer'] = False
        return old['dependencies'](*args, **kwargs)
    def load(path, digest, synthetic):
        require(synthetic is True, 'Artificial input input_checks')
        runtime.reverify_official_views()


        return runtime.load_scientific_inputs(path, digest, synthetic=True)
    def final(*args, **kwargs):
        runtime.reverify_official_views()
        record, evidence = assemble_numeric(P, *args, **kwargs,
                                             checked_source=runtime.checked_source)


        import inspect
        bound = inspect.signature(assemble_numeric).bind(P, *args, **kwargs,
                                                        checked_source=runtime.checked_source)
        replay = bound.arguments['replay_evidence']
        bundles = bound.arguments['bundles']
        metadata = runtime.verified_sens35_metadata(bundles,replay)
        missing = runtime.native_unavailable_series()
        record['sens35_detached_losses'] = task_pair_export(bundles,replay,metadata,missing)


        record['original_news_214'] = runtime.verified_original_attachment()
        record['original_news_214_source'] = deepcopy(runtime.contract['original_attachment'])
        require(record['original_news_214']['days'] == 214 and
                len(record['original_news_214']['contrasts']) == 2,
                'Separate original-window attachment required in every branch')
        require({'RS8', 'N0', 'source_receipt_sha256', 'original_callable', 'original_destination'} <=
                set(record['original_news_214']), 'Original RS8/N0/provenance fields required')
        evidence['execution_authority'] = runtime.public_execution_provenance()
        record['sens35_replay_binding'] = replay_binding(record['sens35_detached_losses'],evidence)
        record['limitations'] = runtime.verified_limitations()
        runtime.reverify_official_views()
        return record, evidence
    P.dependencies, P.load_inputs, P.assemble_output = deps, load, final
    try:


        with branch.scope(SimpleNamespace(P=P), runtime.r2_contract):
            result = P.build(manifest_path, expected, chunk=chunk, gate=gate, synthetic=True)
        runtime.reverify_official_views()
        return result
    finally:
        for name, value in old.items():
            setattr(P, name, value)
        sys.path[:] = before_path


        for name in set(sys.modules) - set(before_modules):
            del sys.modules[name]
        sys.modules.update(before_modules)
