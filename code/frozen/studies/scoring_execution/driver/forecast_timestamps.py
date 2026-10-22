'Create and verify the two forecast timestamp bindings.'
import contextlib
import json
from pathlib import Path
import sys
import types
from forecast_check_helpers import checked, document, exact_union, exclusive, require, row, utc


class T4G:
    def __init__(self, native, union, am3_utc, af_utc):
        self.native = native
        self.union = exact_union(union, union)
        q = native.project / 'studies'
        for item in self.union:
            p = Path(item['path'])
            require(p.is_relative_to(q) and p.is_file() and p.resolve() == p and not p.is_symlink(),
                    'Exact-union member must be a readable canonical file, no directory/alias')
        self.am3_utc, self.af_utc = utc(am3_utc), utc(af_utc)
        self.root = native.project / 'studies/confirmation/TIMESTAMPS'
        native.register(self.union)

    def create(self, description):
        require(not (self.root / 'T4G').exists(), 'Existing T4G: STOP, no overwrite/resume/new label')
        for item in self.union:
            checked(item, self.native.sources)
        path = self.root / 'make_timestamp.py'
        maker = self.native.sources.module('_minrun_af_timestamp_maker', path)


        namespace = dict(vars(maker))
        paths = {r['path'] for r in self.union}
        q = self.native.project / 'studies'
        def excluded(rel):
            require(str(q / rel) in paths, 'Maker attempted an unlisted union member')
            return False
        namespace['excluded'] = excluded
        main = types.FunctionType(maker.main.__code__, namespace, maker.main.__name__, maker.main.__defaults__)
        require(main.__code__ is maker.main.__code__, 'Original timestamp maker code object required')
        reference_snapshot = sys.argv[:]
        try:
            sys.argv = [str(path), 'T4G', description, *[str(Path(r['path']).relative_to(q)) for r in self.union]]
            main()
        finally:
            sys.argv = reference_snapshot

        return self.verify()

    def verify(self):
        for item in self.union:
            checked(item, self.native.sources)
        with self.native.crypto(self.union) as timestamp_checks:
            verified = timestamp_checks.verify_timestamp_bundle('T4G', self.union)
        require(verified['manifest_rows'] == self.union, 'T4G manifest must equal complete canonical union')
        created = utc(verified['headers']['created_utc'])
        require(set(verified['tsa']) == {'freetsa', 'digicert'}, 'Both TSAs required')
        for value in verified['tsa'].values():
            require(value.get('verified') is True and utc(value['utc']) > self.af_utc and
                    utc(value['utc']) >= self.am3_utc and utc(value['utc']) >= created,
                    'Both actual token UTCs must follow AF and not precede AM3/manifest')
        return verified

    def af_bind(self, union_receipt_path):

        union_verification = self.verify()
        with self.native.crypto(self.union):
            native_binding = self.native.af('bind_science_timestamp').bind('T4G')
        value = dict(schema='MINRUN_AF_EXACT_UNION_BINDING_V1', label='T4G',
                     native_binding=row(self.native.af_root / 'OVERLAY_TIMESTAMP_BINDING.json'),
                     verification=union_verification, timestamp_generated=False)
        exclusive(union_receipt_path, value)
        return value

    def af_verify(self, union_receipt):
        value = document(union_receipt, self.native.sources)
        require(value['schema'] == 'MINRUN_AF_EXACT_UNION_BINDING_V1' and
                value['native_binding'] == row(self.native.af_root / 'OVERLAY_TIMESTAMP_BINDING.json') and
                value['verification'] == self.verify(), 'AF binder exact-union receipt drift')


        with self.native.crypto(self.union):
            return self.native.af('freeze_science').verify_delay_release()


def create_verify_bind(native, am3, inputs, outputs, build_sources):
    am_item = inputs['am3_freeze']
    am_value = am3.verify(am_item)
    af_module = native.af('freeze_science')
    af_value = af_module.verify_delay_freeze()
    require(row(native.af_root / 'OVERLAY_FREEZE.json') == inputs['af_freeze'], 'Actual AF freeze identity required')
    require(utc(af_value['utc']) >= utc(am_value['utc']), 'AM3 source freeze precedes AF runtime freeze')
    left = am3.required_identities(am_item)
    right = af_module.timestamp_required_identities(af_value)

    with native.am3():
        selected = sys.modules['science_identity'].timestamp_union(left, right)
    require(selected == exact_union(left, right), 'Native exact-union disagreement')
    for p in [outputs['am3_binding'], outputs['af_union_binding'], outputs['receipt']]:
        require(not Path(p).exists(), 'Exclusive T4G stage output already exists')
    require(not (native.af_root / 'OVERLAY_TIMESTAMP_BINDING.json').exists(), 'Native AF binding already exists')
    t4g = T4G(native, selected, am_value['utc'], af_value['utc'])
    first = t4g.create(inputs['description'])
    native.sources.recheck()
    am3.bind(am_item, outputs['am3_binding'], t4g)
    t4g.af_bind(outputs['af_union_binding'])
    am_binding = row(outputs['am3_binding']); af_binding = row(outputs['af_union_binding'])
    am3.verify(am_item, require_timestamp=True, require_af_freeze=True, t4g=t4g, binding=am_binding)
    af_verified = t4g.af_verify(af_binding)
    final = dict(schema='MINRUN_AF_CHAIN_T4G_COMPLETION_V1', union=selected,
                 verification=first, am3_binding=am_binding, af_union_binding=af_binding,
                 af_release_verification=af_verified, production_authority=False)
    native.sources.recheck()
    exclusive(outputs['receipt'], final)
    return final
