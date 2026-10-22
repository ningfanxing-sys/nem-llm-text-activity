'Read the saved forecast sources through checked numerical functions.'
import contextlib
import json
from pathlib import Path
import sys
from forecast_time_alignment import Dec16C, SCHEMA as TIME_ALIGNMENT_C_SCHEMA
from forecast_check_helpers import checked, document, exclusive, metadata_path, now, require, row, utc

AF_REL = 'studies/confirmation/forecast_hashes/statistics'
C_REL = 'studies/batch_estimation/batch_checks/statistics'
AM_REL = 'studies/confirmation/notice_constraints/statistics/PREPARE_5'


class Native:
    def __init__(self, project, catalog, sources):
        self.project = Path(project)
        self.catalog = catalog
        self.sources = sources
        self.af_root = self.project / AF_REL
        self.c_root = self.project / C_REL
        self.allowed = {}

    def register(self, rows):
        for item in rows:
            checked(item, self.sources)
            require(item['path'] not in self.allowed or self.allowed[item['path']] == item,
                    'Conflicting declared metadata')
            self.allowed[item['path']] = item

    @contextlib.contextmanager
    def installed(self):

        reference_snapshot = dict(sys.modules)
        saved = []
        with self.sources.imports():
            sys.path.insert(0, str(self.af_root))
            science = self.sources.module('science_contract', self.af_root / 'science_contract.py')
            io = self.sources.module('metadata_io', self.af_root / 'metadata_io.py')
            original = io.snapshot
            def snapshot(path, expected=None):
                key = str(Path(path).absolute())
                if key in self.sources.rows:
                    data = self.sources.bytes(key)
                    item = row(key, data)
                    require(expected is None or item == expected, 'Archived C/AF source identity drift')
                    return item, data
                return original(path, expected)
            saved.append((io, 'snapshot', original)); io.snapshot = snapshot
            self.io = io
            self.c = self.sources.module('c_interface_adapter', self.af_root / 'c_interface_adapter.py')
            self.time_alignment = Dec16C(self)
            original_read, original_normalize = self.c.read_scientific_authority, self.c.normalize_documents
            def read_c(root=self.c_root, *, synthetic=False):
                freeze_path = Path(root) / 'SCIENCE_FREEZE.json'
                if freeze_path.is_file() and not synthetic and Path(root) == self.c_root:
                    freeze = io.read_json(freeze_path)
                    acceptance = document(freeze['acceptance'], self.sources)
                    if acceptance.get('schema') == TIME_ALIGNMENT_C_SCHEMA:
                        return self.time_alignment.read()
                return original_read(root, synthetic=synthetic)
            def normalize_c(freeze, acceptance, review, contract):
                if acceptance.get('schema') == TIME_ALIGNMENT_C_SCHEMA:
                    return self.time_alignment.normalize(freeze, acceptance, review, contract)
                return original_normalize(freeze, acceptance, review, contract)
            saved += [(self.c, 'read_scientific_authority', original_read), (self.c, 'normalize_documents', original_normalize)]
            self.c.read_scientific_authority, self.c.normalize_documents = read_c, normalize_c
            try:


                self.af('root_mapping')
                self.af('runtime_bridge')
                yield self
            finally:
                for module, name, old in reversed(saved):
                    setattr(module, name, old)
                for name in list(sys.modules):
                    if name not in reference_snapshot and getattr(sys.modules[name], '__file__', '') in self.sources.rows:
                        sys.modules.pop(name, None)

    def af(self, name):
        module = self.sources.module(name, self.af_root / (name + '.py'))
        if name == 'runtime_bridge' and not getattr(module, '_time_alignment_a2_acceptance_adapter', False):
            original_loader=module.resolved_base_freezer
            def loader(*args,**kwargs):
                base=original_loader(*args,**kwargs)

                if hasattr(base,'acceptance'):
                    from forecast_source_contracts import base_acceptance
                    base.acceptance=base_acceptance(self,base.acceptance)
                return base
            module.resolved_base_freezer=loader
            module._time_alignment_a2_acceptance_adapter=True
        if name == 'root_mapping' and not getattr(module, '_time_alignment_contract_adapter', False):
            original = module.final_mapping_contract
            def contract(*args, **kwargs):
                value = original(*args, **kwargs)
                path = self.c_root / 'SCIENCE_FREEZE.json'
                if path.is_file():
                    freeze = self.io.read_json(path)
                    acceptance = document(freeze['acceptance'], self.sources)
                    if acceptance.get('schema') == TIME_ALIGNMENT_C_SCHEMA:
                        value.update(acceptance_path=freeze['acceptance']['path'], acceptance_schema=TIME_ALIGNMENT_C_SCHEMA,
                                     review_path=freeze['independent_review']['path'], review_schema=TIME_ALIGNMENT_C_SCHEMA)
                return value
            module.final_mapping_contract = contract
            module._time_alignment_contract_adapter = True
        return module

    @contextlib.contextmanager
    def am3(self):
        names = ('science_identity', 'af_final_v2', 'citation_identity', 'native_c_provenance',
                 'native_closure_v2', 'prepare_scientific', 'inherited_authority')
        saved = {n: sys.modules.pop(n, None) for n in names}
        try:
            for name in names:
                self.sources.module(name, self.project / AM_REL / (name + '.py'))
            identity = sys.modules['science_identity']
            original = identity.native_c
            def native_c(*args):
                return self.time_alignment.am3_native_c(original, *args)
            identity.native_c = native_c
            sys.modules['af_final_v2'].native_c = native_c
            yield sys.modules['prepare_scientific']
        finally:
            for n, old in saved.items():
                sys.modules.pop(n, None)
                if old is not None:
                    sys.modules[n] = old

    def c61(self):
        selected = self.catalog['c_v1']
        require(len(selected) == 61, 'TIME_ALIGNMENT requires exact C V1 61-source association')
        pins = self.io.read_json(self.af_root / 'C_INTERFACE_SOURCE_PINS.json')['files']
        expected = {str(self.c_root / name): item for name, item in pins.items()}
        actual = {str(self.project / x['logical_path']): dict(path=str(self.project / x['logical_path']),
                    bytes=x['bytes'], sha256=x['sha256']) for x in selected}
        require(actual == expected, 'C61 must equal AF native V1 pins, no successor/fallback')
        for path, item in actual.items():
            self.io.snapshot(path, item)
        return dict(schema='MINRUN_AF_C_V1_ASSOCIATION_V1', sources=actual,
                    source_association_only=True, production_authority=False)

    def c_authority(self):
        self.c61()
        return self.c.read_scientific_authority()

    def freeze_c(self, inputs, out):

        self.c61()
        if 'time_alignment_closure' in inputs:
            return self.time_alignment.freeze(inputs, out)
        require(Path(out) == self.c_root / 'SCIENCE_FREEZE.json', 'Exact installed C science-freeze path required')
        spec = self.io.read_json(self.c_root / 'SCIENTIFIC_ACCEPTANCE_SPEC.json')
        census = self.io.read_json(self.c_root / 'FREEZE_CENSUS.json')
        rows = inputs['files']
        require(set(rows) == set(census['files']), 'Exact archived native C freeze census required')
        files = {}
        for name, item in rows.items():
            require(item['path'] == str(self.c_root / name), 'Native C member path mismatch')
            checked(item, self.sources)
            files[name] = {k: item[k] for k in ('bytes', 'sha256')}
        tested = {name: {k: pin[k] for k in ('bytes', 'sha256')} for name, pin in
                  self.io.read_json(self.af_root / 'C_INTERFACE_SOURCE_PINS.json')['files'].items()}
        require(set(tested) == set(spec['tested_source_files']), 'C tested V1 census mismatch')

        receipt = document(inputs['acceptance'], self.sources)
        review = document(inputs['independent_review'], self.sources)
        require(receipt['delivered_sources'] == tested, 'Native C full receipt source set mismatch')
        rules = self.io.read_json(self.c_root / 'SCIENCE_RULES.json')['authority_identities']
        for item in [inputs['acceptance'], inputs['independent_review'], inputs['release_binding'],
                     inputs['callable_ast_inventory'], inputs['numeric_ancestor_contract'], *rules]:
            checked(item, self.sources)
        value = dict(schema=self.c.NATIVE_FREEZE_SCHEMA, state='SCIENTIFIC_CONSUMER_FROZEN_BEFORE_T5',
                     task_revision=self.c.NATIVE_REVISION, frozen_utc=now(), files=files, tested_sources=tested,
                     callable_ast_inventory=inputs['callable_ast_inventory'], scientific_decisions=rules,
                     numeric_ancestor_contract=inputs['numeric_ancestor_contract'], acceptance=inputs['acceptance'],
                     independent_review=inputs['independent_review'], release_binding=inputs['release_binding'],
                     synthetic_only=False)
        from science_contract import digest
        contract = dict(stable=True, owner_agreed=True, revision=self.c.NATIVE_REVISION,
                        native_api_source_identities=self.io.read_json(self.af_root / 'C_INTERFACE_SOURCE_PINS.json')['files'],
                        native_case_ids=spec['case_ids'], native_freeze_files=files, sources=tested,
                        scientific_decisions=rules, numeric_ancestor_contract=inputs['numeric_ancestor_contract'],
                        review_identity=inputs['independent_review'],
                        native_document_hashes={'timestamp_checks': digest(value), 'acceptance': digest(receipt), 'review': digest(review)})
        self.c.normalize_documents(value, receipt, review, contract)
        binding = document(inputs['release_binding'], self.sources)
        require(Path(inputs['release_binding']['path']).parent == self.c_root and
                binding.get('schema') == 'C_SCORING_SCIENTIFIC_RELEASE_V1' and
                binding.get('source_reviewed') is True and binding.get('integration_complete') is True and
                binding.get('scientific_eligibility_changed') is False and
                binding.get('numeric_ancestor_contract') == inputs['numeric_ancestor_contract'],
                'Actual native C release binding required')
        for name in ('runtime_family_policy', 'scorer_contract', 'entry_contracts'):
            require(Path(binding[name]['path']).parent == self.c_root, 'C binding member escaped owner root')
            checked(binding[name], self.sources)
        pins = contract['native_api_source_identities']
        with self.c.native_review_helpers(pins):
            gate = self.io.load_source('_af_chain_c_review_gate', self.c_root / 'review_gate.py', pins['review_gate.py'], register=False)
            require(gate.eligibility(self.c_root)['state'] == 'FREEZE-READY-PENDING-SOURCE-RELEASE',
                    'Original C full native scientific eligibility required')
        self.c.verify_numeric_ancestor(self.c_root, inputs['numeric_ancestor_contract'], pins)
        exclusive(out, value)
        self.c_authority()
        return value

    @contextlib.contextmanager
    def crypto(self, required):

        self.register(required)
        m = self.af('runtime_bridge').frozen_modules()
        parent = m['delay_authority'].parent_authority()
        old = parent.read_metadata
        def read_metadata(path):
            key = str(Path(path).absolute())
            if key in self.sources.rows:
                return self.sources.bytes(key)
            if key in self.allowed:
                return checked(self.allowed[key], self.sources)
            return old(path)
        parent.read_metadata = read_metadata
        try:
            yield parent
        finally:
            parent.read_metadata = old
