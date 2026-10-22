'Map saved execution metadata to the forecast input schema.'
import sys
from pathlib import Path
from forecast_check_helpers import (accepted, acknowledged, checked, digest, document, exact_union, exclusive,
                           now, require, row, utc)
from forecast_readers import AM_REL
from forecast_context import commitment_view, q_members

SCHEMA = 'MINRUN_AM3_SCIENTIFIC_SOURCE_FREEZE_V1'


class AM3:
    def __init__(self, native, build_sources):
        self.native = native
        self.sources = native.sources
        self.build_sources = build_sources

    def prepare(self, inputs):
        contract = document(inputs['contract'], self.sources)
        require(contract['c_contract']['artificial'] is False, 'Real AM3 contract cannot select an artificial C premise')
        payloads = {r['path']: checked(r, self.sources) for r in inputs['payloads']}
        self.native.register(inputs['payloads'])
        mapping = __import__('json').loads(payloads[contract['mapping_identity']['path']])
        commitment = __import__('json').loads(payloads[contract['commitment_identity']['path']])
        commitment, row_groups = commitment_view(commitment, payloads)

        c = self.native.c_authority()
        require(contract['c_contract']['document_ids']['c_authority'] == c['authority_identity'],
                'AM3/C actual timestamp_checks mismatch')
        with self.native.am3() as part_a:
            verification = part_a.validate_native_final_supplied(mapping, commitment,
                                           contract=contract, source_bytes=payloads)
            identity = sys.modules['science_identity']
            policy = self.native.io.read_json(self.native.project / AM_REL / 'CURRENT_AM3_VERSION.json')
            require(contract['canonical'] == policy['canonical'], 'Accepted scientific AM3 canonical required')
            require(contract['am_policy_identity'] == row(self.native.project / AM_REL / 'CURRENT_AM3_VERSION.json',
                    self.sources.bytes(self.native.project / AM_REL / 'CURRENT_AM3_VERSION.json')),
                    'Exact accepted PREPARE_5 policy required')
            scope, calendar = identity.SCOPE, identity.CALENDAR
        verification['time_alignment_a3_row_groups'] = row_groups

        with self.native.crypto(inputs['payloads']) as timestamp_checks:
            inherited = timestamp_checks.verify_specification()
        require(inherited['calendar_rule'] == calendar, 'AM1/AM2 no-calendar timestamp_checks drift')
        subject = dict(contract=inputs['contract'], mapping=contract['mapping_identity'],
                       commitment=contract['commitment_identity'], canonical=contract['canonical'],
                       build_sources=self.build_sources)
        source_acceptance = acknowledged(inputs['source_acceptance'], subject, sources=self.sources,
                                     role='AM3_SOURCE_ACCEPTANCE')
        part_b = accepted(inputs['part_b'], subject, sources=self.sources, role='AM3_INDEPENDENT_PART_B')
        require(part_b.get('scientific_checks') == {'D1_joint_correction_delay': True,
                    'D2_weakest_reading': True, 'D3_retained_joint_reporting': True},
                'Actual AM3 Part B D1-D3 review required')
        attestation = document(inputs['attestation'], self.sources)
        require(attestation.get('schema') == 'MINRUN_AM3_SOURCE_ATTESTATION_V1' and
                attestation.get('source') and attestation.get('subject') == subject and
                attestation.get('source_acceptance') == inputs['source_acceptance'] and
                attestation.get('part_b') == inputs['part_b'] and
                attestation.get('before_T5') is True and attestation.get('no_calendar_deadline') is True and
                attestation.get('no_production_or_scoring') is True,
                'Real same-source AM3 source attestation required')
        require(utc(attestation['utc']) >= utc(part_b['utc']) >= utc(source_acceptance['utc']),
                'AM3 source acceptance/Part B/attestation chronology')

        c_members = []
        if 'native_authority' in c:
            cf = c['native_authority']
            c_members += [dict(path=str(self.native.c_root / name), **pin) for name, pin in cf['files'].items()]
            c_members += [cf[k] for k in ('acceptance', 'independent_review', 'release_binding',
                          'callable_ast_inventory', 'numeric_ancestor_contract')] + cf['scientific_decisions']
            c_members += list(c['numeric_ancestor_verification']['files'].values())
            if 'native_release_binding' in c:
                binding=c['native_release_binding']
                if 'scorer_contract' in binding:


                    c_members.append(document(binding['scorer_contract'],self.sources)['r2']['source'])
            if c['native_acceptance'].get('schema') == 'MINRUN_TIME_ALIGNMENT_C_V1_CLOSURE_V1':
                e = c['native_acceptance']['evidence']
                c_members += [e['decision'], e['targeted_acceptance'], *e['source_reviews'], e['final_check']]
        inherited_members = []
        for entry in inherited.get('ordered_specifications', []):
            proof = entry['timestamp']
            inherited_members += [proof['manifest'], proof['result'], *[r['receipt'] for r in proof['tsa'].values()]]
        science_freeze = document(inputs['science_freeze'], self.sources)
        science_review = [science_freeze['review']] if 'review' in science_freeze else []
        science_members = science_freeze.get('inventory', [])
        additive_members = []
        if 'inventory' in science_freeze:
            from forecast_checks_cli import verify_science
            build = next((item for item in self.build_sources if Path(item['path']).name == 'AF_CHAIN_BUILD.json'),science_freeze['build'])
            verify_science(self.native,inputs['science_freeze'],build,self.build_sources,inputs.get('science_addendum'))
        if 'science_addendum' in inputs:
            additive = document(inputs['science_addendum'],self.sources)
            science_members = additive['subject']['inventory']
            additive_members = [inputs['science_addendum'], additive['source_review']]
        required = exact_union(inputs['payloads'], [*c_members, *inherited_members, *science_review, *science_members, inputs['contract'], inputs['source_acceptance'],
                    inputs['part_b'], inputs['attestation'], inputs['science_freeze'],
                    *additive_members, *self.build_sources, *list(self.native.c61()['sources'].values())])
        for item in required:
            checked(item, self.sources)
        return dict(subject=subject, required=required, verification=verification, scope=scope, calendar=calendar)

    def create(self, inputs, path):
        require(not Path(path).exists(), 'AM3 source freeze already exists')
        require(Path(path).parent == self.native.project / 'studies/confirmation/notice_constraints/statistics',
                'Exact scientific AM3 output root required')

        require(not (self.native.af_root / 'OVERLAY_FREEZE.json').exists() and
                not (self.native.af_root / 'BASE_CODE_FREEZE.json').exists(), 'AM3 source freeze must precede AF freeze')
        result = self.prepare(inputs)
        value = dict(schema=SCHEMA, version='AM3_statistics', utc=now(), inputs=inputs,
                     subject=result['subject'], verification=result['verification'],
                     corrected_scope=result['scope'], calendar_rule=result['calendar'],
                     required_identities=result['required'], production_authority=False,
                     runtime_authority=False, timestamp_created=False)
        require(utc(value['utc']) >= utc(document(inputs['attestation'], self.sources)['utc']),
                'AM3 freeze follows genuine attestation')
        exclusive(path, value)
        return value

    def verify(self, item, *, require_timestamp=False, require_af_freeze=False, t4g=None, binding=None):
        value = document(item, self.sources)
        require(value.get('schema') == SCHEMA and value.get('version') == 'AM3_statistics' and
                value.get('production_authority') is False and value.get('runtime_authority') is False,
                'Actual minimal AM3 scientific source freeze required')
        expected = self.prepare(value['inputs'])
        require(all(value[key] == expected[target] for key, target in
                    [('subject', 'subject'), ('verification', 'verification'), ('required_identities', 'required'),
                     ('corrected_scope', 'scope'), ('calendar_rule', 'calendar')]), 'AM3 frozen source association drift')
        require(utc(value['utc']) >= utc(document(value['inputs']['attestation'], self.sources)['utc']),
                'AM3 freeze chronology drift')
        if require_af_freeze:
            af = self.native.af('freeze_science').verify_delay_freeze()
            require(utc(af['utc']) >= utc(value['utc']), 'AF runtime freeze must follow AM3 source freeze')
        if require_timestamp:
            require(t4g is not None and binding is not None, 'Actual AM3 shared T4G binding required')
            self.verify_binding(item, binding, t4g)
        return value

    def required_identities(self, item):
        value = self.verify(item)


        return q_members(self.native.project, exact_union(value['required_identities'], [item]))

    def bind(self, freeze, path, t4g):
        verified = t4g.verify()
        value = dict(schema='MINRUN_AM3_T4G_BINDING_V1', label='T4G', source_freeze=freeze,
                     verification=verified, timestamp_generated=False, utc=now())
        exclusive(path, value)
        return value

    def verify_binding(self, freeze, binding, t4g):
        value = document(binding, self.sources)
        verified = t4g.verify()
        require(value.get('schema') == 'MINRUN_AM3_T4G_BINDING_V1' and value.get('label') == 'T4G' and
                value.get('source_freeze') == freeze and value.get('verification') == verified,
                'AM3 binding must independently match the exact shared union/T4G')
        return verified
