'Compare forecast metadata with the saved source hashes.'
from contextlib import contextmanager
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import sys
from evaluator.validation import require, exact_identity
from native import reader as R

AF_SCIENCE = R.AF/'statistics'


@contextmanager
def isolated_aliases(aliases):
    prior = {name:sys.modules.pop(name) for name in aliases if name in sys.modules}
    try:
        yield
    finally:
        for name in aliases:
            sys.modules.pop(name, None)
        sys.modules.update(prior)


@contextmanager
def checked_scientific_imports(rows):
    sources = {Path(n).stem:item for n,item in rows.items()
               if Path(n).suffix == '.py' and '/' not in n}
    class Finder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, fullname, path=None, target=None):
            if fullname not in sources:return None
            return importlib.util.spec_from_loader(fullname,self,origin=sources[fullname]['path'])
        def create_module(self, spec):return None
        def exec_module(self, module):
            item=sources[module.__name__];path=R.checked(item);data=path.read_bytes()
            require(len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256'],
                    'AF compile source drift')
            module.__file__=item['path']
            exec(compile(data,item['path'],'exec',dont_inherit=True),vars(module))
    finder=Finder();sys.meta_path.insert(0,finder)
    try:yield
    finally:sys.meta_path.remove(finder)


def reviewed_sources():
    doc = R.read_json(R.OUT/'AF9_REVIEWED_SOURCE_PINS.json')
    require(doc['revision'] == 'AF9_statistics_V3' and doc['source_review'] in ('Part A READY', 'PART A ACCEPTED'),
            'AF source review/revision identity')
    rows = doc['reviewed_source_census']
    require(isinstance(rows, dict) and rows, 'Reviewed AF finite census')
    for name, item in rows.items():
        exact_identity(item)
        path = Path(item['path'])
        require(path == AF_SCIENCE/name and path.resolve() == path and
            all(not p.is_symlink() for p in (path, *path.parents)), 'Reviewed AF path alias')
        require(path.suffix in ('.py', '.md', '.json'), 'Reviewed AF public source only')
        require(not path.name.upper().startswith(('SEAL_', 'SCORE_')), 'AF payload in source census')
        data = path.read_bytes()
        require(len(data) == item['bytes'] and hashlib.sha256(data).hexdigest() == item['sha256'],
                'Reviewed AF source drift: '+name)
    for key in ('delivery_manifest', 'independent_source_review', 'reviewed_identity_inventory'):
        item = doc[key]; exact_identity(item)
        path = R.checked(item)
        require(path.stat().st_size == item['bytes'], 'AF review evidence size drift')
    return rows


@contextmanager
def scientific_provider():
    require(os.environ.get('SCORING_PHASE', 'prepare') == 'source_runtime' and
        os.environ.get('FORECAST_BINDING_SOURCE_RUN') == '1', 'AF read-only runtime requires separate release')
    rows = reviewed_sources()
    aliases = {'metadata_io', 'science_contract', 'freeze_science', 'root_mapping', 'source_inventory',
        'runtime_bridge', 'c_interface_adapter', 'speed_selection', 'common', 'activity_guard',
        'check_prescoring_state', 'forecast_inputs', 'run_bound_forecasts', 'runner', 'anchor_patch', 'timestamp_checks',
        'deadline_patch', 'delay_authority', 'delay_speed_binding', 'delay_patch', 'delay_core',
        'delay_root_mapping', 'delay_final_source', 'delay_freeze', '_original_delay_freeze',
        '_original_delay_host', 'structural_projection', 'prediction_set', 'source_anchor_check'}
    try:
        with isolated_aliases(aliases), checked_scientific_imports(rows), R.import_path(AF_SCIENCE):
            import runtime_bridge
            import freeze_science
            import source_inventory
            modules = runtime_bridge.frozen_modules()
            provider = runtime_bridge.delay_freezer_provider()
            with runtime_bridge.metadata_aliases([provider, modules['common'],
                    modules['run_bound_forecasts'], modules['delay_authority']]):
                yield modules, freeze_science, source_inventory
    finally:
        require(reviewed_sources() == rows, 'AF source changed during read-only verification')


def verify_combined(seal_item, main_identity, batch_identity, acceptance, t5):
    require(Path(seal_item['path']) == R.AF/'SEAL_FORECAST_BINDING.json', 'Exact corrected seal location')


    with scientific_provider() as (modules, freezer, source_inventory):
        release = freezer.verify_delay_release()
        source_inventory.verify_final_source()
        R.checked(seal_item)
        correction = modules['delay_core'].verify_combined_seal(seal_item['path'])
        require(correction['binding']['delay_authority'] == release, 'AF seal/release association drift')
        for field, expected in (('main_conf_seal', main_identity), ('batch_seal', batch_identity)):
            bound=correction['binding'][field]
            require(bound['path']==expected['path'] and bound['sha256']==expected['sha256'],
                    'AF original seal association drift')
        roots = acceptance['metadata_roots']
        for field in ('overlay_freeze', 'overlay_timestamp_binding', 'final_root_mapping', 'final_source_commitment'):
            item = release[field]
            R.checked(item)
            require(R.t5_contains(t5, item) and any(r['path']==item['path'] and r['sha256']==item['sha256'] for r in roots),
                    'AF release acceptance/T5 root missing: '+field)
        for field in ('code_freeze', 'patch', 'activation'):
            item = correction['binding'][field]
            R.checked(item)
            require(R.t5_contains(t5, item) and any(r['path']==item['path'] and r['sha256']==item['sha256'] for r in roots),
                    'AF metadata acceptance/T5 root missing: '+field)
        return correction
