'Associate time-alignment evidence with the forecast inputs.'
import json
from pathlib import Path
from forecast_check_helpers import checked, document, exclusive, now, require, row, utc

def digest(value):
    import hashlib
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


SCHEMA = 'MINRUN_TIME_ALIGNMENT_C_V1_CLOSURE_V1'
SCOPE = 'TIME_ALIGNMENT_TARGETED_PLUS_SOURCE_REVIEW'
FULL = 'NOT_RUN_B_CLASS'
REPLACED = {'SCIENTIFIC_ACCEPTANCE_RECEIPT.json', 'INDEPENDENT_REVIEW.json', 'SOURCE_CLOSURE_RECEIPT.json'}
HERE = Path(__file__).absolute().parent


def evidence_manifest():
    return json.loads((HERE / 'C_V1_TIME_ALIGNMENT_EVIDENCE.json').read_bytes())


def validate_evidence(manifest, sources=None, *, check_origin=False):
    decision = checked(manifest['decision'], sources).decode()
    require('TIME_ALIGNMENT-A1 (ADOPTED' in decision and SCOPE in decision and FULL in decision,
            'Adopted TIME_ALIGNMENT-A1 exact decision required')
    receipt = document(manifest['targeted_acceptance'], sources)
    require(receipt.get('schema') == 'C_statistics_ACCEPTANCE_V1' and
            receipt.get('task_revision') == 'SCORING_C8B_SCIENCE_V1' and receipt.get('state') == 'TARGETED_ONLY' and
            len(receipt.get('case_ids', [])) == 62 and len(set(receipt['case_ids'])) == 62 and
            [r['case_id'] for r in receipt.get('cases', [])] == receipt['case_ids'] and
            all(r.get('state') == 'PASS' for r in receipt['cases']) and
            all(receipt.get(k) == [] for k in ('failures', 'errors', 'skipped')) and
            receipt.get('full_numeric_chain') is False and receipt.get('scientific_grant') is False and
            all(receipt.get(k) == 0 for k in ('production_state_reads', 'production_commands_run')),
            'Exact V1 62/62 TARGETED_ONLY evidence required; never a full PASS')
    require(receipt['delivered_sources'] == manifest['tested_sources'], 'Targeted receipt not archived C61 bytes')
    r = receipt['resources']
    require(r.get('nice') == 20 and r.get('test_processes') == 1 and
            r.get('minimum_memory_free_percent', 0) >= 25 and r.get('peak_rss_bytes', 10**12) <= 1610612736 and
            r.get('scratch_peak_bytes', 10**12) < 1000000000 and r.get('breaches') == [] and r.get('periodic_samples'),
            'Original targeted acceptance resource gates')
    require(all(x.get('nice') == 20 and 25 <= x.get('memory_free_percent', 0) <= 100 and
                x.get('rss_bytes', 10**12) <= 1610612736 and x.get('scratch_bytes', 10**12) < 1000000000
                for x in r['periodic_samples']), 'Original periodic resource observations required')
    require(len(manifest['source_reviews']) == 2, 'Both CONSUMERREV3B source-review records required')
    for item in manifest['source_reviews']:
        text = checked(item, sources).decode()
        require('CONSUMERREV3B' in text and 'SOURCE READY' in text[:350], 'Exact SOURCE READY review required')
    final = checked(manifest['final_check'], sources)
    require(' Conclusion ：GO' in final.decode() and final.count(' PASS '.encode()) >= 3, 'Final scientific/blinding GO required')
    origin = manifest['final_check_origin']
    require(all(origin[k] == manifest['final_check'][k] for k in ('bytes', 'sha256')),
            'Retained final-check copy differs from its origin')
    if check_origin:
        require(checked(origin) == final, 'Final-check original/copy mismatch')
    utc(receipt['utc'])
    return receipt


def create_closure(manifest, output, *, sources=None):
    receipt = validate_evidence(manifest, sources, check_origin=True)
    value = dict(schema=SCHEMA, state='TIME_ALIGNMENT_C_V1_ACCEPTANCE_CLOSED', scope=SCOPE, full_suite=FULL,
                 task_revision='SCORING_C8B_SCIENCE_V1', evidence=manifest, targeted_passed=62,
                 targeted_total=62, acceptance_utc=receipt['utc'], utc=now(),
                 source_scope='ADOPTED_TIME_ALIGNMENT_A1', production_authority=False, scientific_grant=False)
    exclusive(output, value)
    return value


def verify_closure(item, sources=None, *, expected=None):
    value = document(item, sources)
    expected = evidence_manifest() if expected is None else expected
    require(value.get('schema') == SCHEMA and value.get('state') == 'TIME_ALIGNMENT_C_V1_ACCEPTANCE_CLOSED' and
            value.get('scope') == SCOPE and value.get('full_suite') == FULL and
            value.get('task_revision') == 'SCORING_C8B_SCIENCE_V1' and value.get('evidence') == expected and
            value.get('source_scope') == 'ADOPTED_TIME_ALIGNMENT_A1' and
            value.get('targeted_passed') == value.get('targeted_total') == 62 and
            value.get('production_authority') is False and value.get('scientific_grant') is False,
            'Exact source-scoped TIME_ALIGNMENT C-V1 closure required')
    receipt = validate_evidence(expected, sources)
    require(value['acceptance_utc'] == receipt['utc'] and utc(value['utc']) >= utc(receipt['utc']),
            'C closure targeted evidence chronology drift')
    return value


class Dec16C:
    def __init__(self, native):
        self.native = native
        self.sources = native.sources

    def verify(self, item):
        value = verify_closure(item, self.sources)
        actual = self.native.c61()['sources']
        tested = {str(Path(p).relative_to(self.native.c_root)): {k:r[k] for k in ('bytes', 'sha256')}
                  for p, r in actual.items()}
        require(tested == value['evidence']['tested_sources'], 'TIME_ALIGNMENT closure must match installed archived C61')
        return value

    def census(self, binding=None):
        if binding and binding.get("schema") == "MINRUN_C_V1_SCIENTIFIC_ASSOCIATION_V1":
            return set(self.native.io.read_json(self.native.af_root / "C_INTERFACE_SOURCE_PINS.json")["files"])

        old = self.native.io.read_json(self.native.c_root / 'FREEZE_CENSUS.json')['files']
        require(REPLACED <= set(old), 'Archived V1 census changed')
        return set(old) - REPLACED

    def policy_gate(self, binding):
        n = self.native
        if binding.get("schema") == "MINRUN_C_V1_SCIENTIFIC_ASSOCIATION_V1":
            from forecast_source_contracts import policy
            return policy(binding, n)
        names = dict(runtime_family_policy='RUNTIME_FAMILY_POLICY.json', scorer_contract='SCORER_CONTRACT.json',
                     entry_contracts='ENTRY_CONTRACTS.json')
        for name, filename in names.items():
            require(Path(binding[name]['path']) == n.c_root / filename, 'Original C binding member path changed')
            checked(binding[name], self.sources)
        policy = document(binding['runtime_family_policy'], self.sources)
        scorer = document(binding['scorer_contract'], self.sources)
        require(policy.get('schema') == 'C_SCORING_RUNTIME_FAMILIES_V1' and
                policy.get('status') == 'REVIEWED_EXACT_OWNER_CONTRACTS' and
                set(policy.get('families', {})) == {'AP5','AP6','notice_delays','scoring_callback'},
                'Four actual reviewed successor owner contracts pending')
        fields = {'root','freeze','schema','state','inventory_field','inventory_format','inventory_base','declared_census_field','names'}
        for r in policy['families'].values():
            require(set(r) == fields and all(r[k] is not None for k in fields) and r['names'] and
                    len(r['names']) == len(set(r['names'])), 'Successor exact owner census missing/duplicate')
        require(scorer.get('schema') == 'C_SCORING_SCORER_CONTRACT_V1' and
                scorer.get('status') == 'REVIEWED_EXACT_R2_SOURCE_DELIVERY', 'Actual agreed original/R2 scorer contract pending')

    def normalize(self, freeze, acceptance, review, contract):
        n = self.native
        closure_id = freeze['acceptance']
        closure = self.verify(closure_id)
        require(acceptance == review == closure and freeze['independent_review'] == closure_id,
                'TIME_ALIGNMENT closure replaces acceptance/review without invented native PASS fields')
        require(contract.get('stable') is True and contract.get('owner_agreed') is True and
                contract.get('revision') == n.c.NATIVE_REVISION and contract.get('native_api_source_identities') and
                contract.get('sources') == freeze['tested_sources'] and
                contract.get('native_freeze_files') == freeze['files'] and
                set(freeze) == n.c.FREEZE_FIELDS and freeze.get('schema') == n.c.NATIVE_FREEZE_SCHEMA and
                freeze.get('state') == 'SCIENTIFIC_CONSUMER_FROZEN_BEFORE_T5' and
                freeze.get('task_revision') == n.c.NATIVE_REVISION and
                freeze.get('scientific_decisions') == contract.get('scientific_decisions') and
                freeze.get('numeric_ancestor_contract') == contract.get('numeric_ancestor_contract') and
                contract.get('review_identity') == closure_id and
                contract.get('native_document_hashes') == {'timestamp_checks':digest(freeze),'acceptance':digest(closure),'review':digest(closure)},
                'Original C schema/source/decision/ancestor/document bindings must remain exact')
        require(freeze['synthetic_only'] is False and utc(freeze['frozen_utc']) >= utc(closure['utc']),
                'C source freeze must follow actual source closure')
        return dict(native_authority=freeze,native_acceptance=closure,native_review=closure,
                    native_document_hashes=contract['native_document_hashes'],source_association_only=True,
                    production_authority=False)

    def validate_freeze(self, freeze):
        n = self.native
        closure = self.verify(freeze['acceptance'])
        require(set(freeze['files']) == self.census(document(freeze['release_binding'], self.sources)), 'C census differs beyond the three TIME_ALIGNMENT-A1 substitutions')
        pins = n.io.read_json(n.af_root / 'C_INTERFACE_SOURCE_PINS.json')['files']
        tested = {k:{f:v[f] for f in ('bytes','sha256')} for k,v in pins.items()}
        require(freeze['tested_sources'] == tested and
                set(tested) == set(n.io.read_json(n.c_root/'SCIENTIFIC_ACCEPTANCE_SPEC.json')['tested_source_files']),
                'Complete exact C61 tested source census required')
        rules = n.io.read_json(n.c_root/'SCIENCE_RULES.json')['authority_identities']
        require(freeze['scientific_decisions'] == rules, 'Original scientific decisions changed')
        for name, pin in freeze['files'].items():
            require(not Path(name).is_absolute() and '..' not in Path(name).parts, 'C inventory alias/escape')
            checked(dict(path=str(n.c_root/name),**pin),self.sources)
        for item in [freeze['callable_ast_inventory'],freeze['numeric_ancestor_contract'],freeze['release_binding'],*rules]:
            checked(item,self.sources)
        binding = document(freeze['release_binding'],self.sources)
        a2 = binding.get('schema') == 'MINRUN_C_V1_SCIENTIFIC_ASSOCIATION_V1'
        require(a2 or (Path(freeze['release_binding']['path']).parent == n.c_root and
                binding.get('schema') == 'C_SCORING_SCIENTIFIC_RELEASE_V1' and
                binding.get('source_reviewed') is True and binding.get('integration_complete') is True and
                binding.get('scientific_eligibility_changed') is False and
                binding.get('numeric_ancestor_contract') == freeze['numeric_ancestor_contract']),
                'Actual native scientific binding/ancestor association required')
        self.policy_gate(binding)
        require(binding['numeric_ancestor_contract'] == freeze['numeric_ancestor_contract'], 'Exact adopted ancestor binding')
        if a2:
            from forecast_source_contracts import numeric
            ancestor = numeric(freeze['numeric_ancestor_contract'], n)
            require(binding['c61'] == n.c61()['sources'], 'Exact adopted C61 binding')
        else:
            ancestor = n.c.verify_numeric_ancestor(n.c_root,freeze['numeric_ancestor_contract'],pins)
        contract = dict(stable=True,owner_agreed=True,revision=n.c.NATIVE_REVISION,
                native_api_source_identities=pins,native_freeze_files=freeze['files'],sources=tested,
                scientific_decisions=rules,numeric_ancestor_contract=freeze['numeric_ancestor_contract'],
                review_identity=freeze['acceptance'],native_document_hashes={'timestamp_checks':digest(freeze),'acceptance':digest(closure),'review':digest(closure)})
        result = self.normalize(freeze,closure,closure,contract)
        result.update(contract=contract,numeric_ancestor_verification=ancestor,native_release_binding=binding,
                      independent_source_verdict=dict(state='TIME_ALIGNMENT_TARGETED_PLUS_SOURCE_REVIEW',full_suite=FULL,
                          closure=freeze['acceptance'],freeze_permitted=False,production_authority=False),root=str(n.c_root))
        return result

    def freeze(self, inputs, out):
        n = self.native
        require(Path(out) == n.c_root/'SCIENCE_FREEZE.json', 'Exact installed C science-freeze path required')
        closure = self.verify(inputs['time_alignment_closure'])
        require(set(inputs['files']) == self.census(document(inputs['release_binding'], self.sources)), 'Provide archived census minus only three substituted files')
        files = {}
        for name,item in inputs['files'].items():
            require(item['path'] == str(n.c_root/name), 'Exact native C member path required')
            checked(item,self.sources);files[name] = {k:item[k] for k in ('bytes','sha256')}
        pins = n.io.read_json(n.af_root/'C_INTERFACE_SOURCE_PINS.json')['files']
        value = dict(schema=n.c.NATIVE_FREEZE_SCHEMA,state='SCIENTIFIC_CONSUMER_FROZEN_BEFORE_T5',
            task_revision=n.c.NATIVE_REVISION,frozen_utc=now(),files=files,
            tested_sources={k:{f:v[f] for f in ('bytes','sha256')} for k,v in pins.items()},
            callable_ast_inventory=inputs['callable_ast_inventory'],
            scientific_decisions=n.io.read_json(n.c_root/'SCIENCE_RULES.json')['authority_identities'],
            numeric_ancestor_contract=inputs['numeric_ancestor_contract'],release_binding=inputs['release_binding'],
            acceptance=inputs['time_alignment_closure'],independent_review=inputs['time_alignment_closure'],synthetic_only=False)
        self.validate_freeze(value)
        exclusive(out,value)
        return value

    def read(self):
        n = self.native
        n.io.phase(source_flag=('FORECAST_BINDING_SOURCE_MAPPING_REFRESH','FORECAST_BINDING_SOURCE_SOURCE_COMMITMENT',
            'FORECAST_BINDING_SOURCE_FREEZE','FORECAST_BINDING_SOURCE_RUN','FORECAST_BINDING_SOURCE_TIMESTAMP_BIND'))
        item = row(n.c_root/'SCIENCE_FREEZE.json')
        result = self.validate_freeze(document(item,self.sources))
        result['authority_identity'] = item
        return result

    def am3_native_c(self, original, timestamp_checks, receipt, review, contract, payloads):
        if receipt.get('schema') != SCHEMA:
            return original(timestamp_checks,receipt,review,contract,payloads)
        require(contract['artificial'] is False and contract['c_revision'] == self.native.c.NATIVE_REVISION,
                'Exact real archived C revision required')
        proof = self.read()
        require(timestamp_checks == proof['native_authority'] and receipt == review == proof['native_acceptance'],
                'AM3 C records differ from independently verified TIME_ALIGNMENT C timestamp_checks')
        require(contract['document_ids']['c_authority'] == proof['authority_identity'] and
                contract['document_ids']['c_receipt'] == contract['document_ids']['c_review'] == timestamp_checks['acceptance'],
                'AM3 actual C/closure identities disagree')
        from science_identity import source_identity, literal_revision
        sources = contract['c_sources']
        require(sources == self.native.io.read_json(self.native.af_root/'C_INTERFACE_SOURCE_PINS.json')['files'] and
                contract['c_tested_sources'] == timestamp_checks['tested_sources'] and contract['c_freeze_files'] == timestamp_checks['files'],
                'AM3 declared C61/freeze inventory mismatch')
        for item in sources.values():source_identity(item,payloads[item['path']])
        require(literal_revision(payloads[sources[contract['c_revision_source']]['path']]) == contract['c_revision'],
                'Actual C source revision drift')
        for field in ('callable_ast_inventory','numeric_ancestor_contract','release_binding'):
            require(timestamp_checks[field] == contract['c_authority_metadata'][field], 'C timestamp_checks metadata association drift')
            source_identity(timestamp_checks[field],payloads[timestamp_checks[field]['path']])
        require(timestamp_checks['scientific_decisions'] == contract['scientific_decisions'], 'AM3 scientific authorities changed')
        for item in timestamp_checks['scientific_decisions']:source_identity(item,payloads[item['path']])
        return None
