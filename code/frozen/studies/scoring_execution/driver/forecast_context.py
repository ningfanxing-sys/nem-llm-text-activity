'Construct the forecast context and record its source identities.'
import copy
import json
from pathlib import Path
from forecast_check_helpers import accepted, checked, document, exclusive, now, require, row, utc

ADDENDUM = 'MINRUN_SCIENCE_SOURCE_ADDENDUM_V1'
ROLE = 'DRIVER_AF_CHAIN_FINAL_SOURCE_REVIEW'
GROUPS = ('final_base_source_rows', 'parent_overlay_source_rows',
          'overlay_sources', 'consumer_scientific_source_rows')


class KeyedRows(list):

    def __init__(self, rows):
        super().__init__(rows)
        self.keyed = {item['path']: item for item in rows}
        require(len(self.keyed) == len(rows), 'sensitivity_tests row-group duplicate path')

    def values(self):
        require(list(self.keyed.values()) == list(self), 'sensitivity_tests keyed row order/identity drift')
        return self.keyed.values()


def commitment_view(commitment, payloads):
    value = copy.deepcopy(commitment)
    proof = {}
    for name in GROUPS:
        rows = value[name]
        require(isinstance(rows, (list, dict)) and rows, 'sensitivity_tests complete native row group required')
        ordered = list(rows.values()) if isinstance(rows, dict) else list(rows)
        for item in ordered:
            require(set(item) == {'path', 'bytes', 'sha256'}, 'sensitivity_tests exact per-row identity required')
            require(row(item['path'], payloads[item['path']]) == item, 'sensitivity_tests supplied row identity drift')
        proof[name] = dict(input_container='list' if isinstance(rows, list) else 'dict',
                           ordered_identities=ordered, keyed_paths=[r['path'] for r in ordered])
        if isinstance(rows, list):
            value[name] = KeyedRows(rows)
    require(value == commitment and json.dumps(value) == json.dumps(commitment),
            'sensitivity_tests container view changed the native document')
    return value, proof


def q_members(project, identities):

    q = Path(project) / 'studies'
    return [item for item in identities if Path(item['path']).is_relative_to(q)]


def baseline(receipt, science_freeze, sources=None):
    original = document(receipt, sources)
    science = document(science_freeze, sources)
    require(original.get('schema') == 'MINRUN_AF_CHAIN_STAGE_RECEIPT_V1' and
            original.get('action') == 'freeze-science' and original.get('production_authority') is False and
            original.get('result') == science and original.get('build') == science.get('build') and
            science.get('schema') == 'MINRUN_LIMITED_SCIENCE_SOURCE_FREEZE_V1' and
            science.get('production_authority') is False, 'sensitivity_tests exact original successful freeze receipt required')
    return science


def delta(original_inventory, inventory, driver_root, history):

    old = {r['path']: r for r in original_inventory}
    new = {r['path']: r for r in inventory}
    require(len(old) == len(original_inventory) and len(new) == len(inventory) and
            set(old) <= set(new), 'sensitivity_tests original inventory member removed/duplicated')
    history_rows = {r['original']['path']: r for r in history['files']}
    changes = []
    for path in sorted(new):
        item = new[path]
        if old.get(path) == item:
            continue
        require(Path(path).is_relative_to(driver_root), 'sensitivity_tests may change only driver sources')
        change = dict(path=path, after=item)
        if path in old:
            archived = history_rows.get(path)
            require(archived and archived['original'] == old[path], 'sensitivity_tests missing exact old driver bytes')
            checked(archived['archive'])
            require(all(archived['archive'][k] == old[path][k] for k in ('bytes','sha256')),
                    'sensitivity_tests old-byte history mismatch')
            change.update(reference_snapshot=old[path], old_sha256=old[path]['sha256'], old_bytes=archived['archive'])
        else:
            archived=history_rows.get(path)
            if archived:
                checked(archived['archive'])
                require(all(archived['archive'][k]==archived['original'][k] for k in ('bytes','sha256')),
                        'sensitivity_tests observed pre-change history mismatch')
                change.update(reference_snapshot=archived['original'],old_sha256=archived['original']['sha256'],
                              old_bytes=archived['archive'],old_identity_basis=history.get('new_member_history_basis','OBSERVED_PRE_A3_NOT_ORIGINAL_FREEZE_PIN'))
            else:
                change.update(reference_snapshot='NOT_IN_ORIGINAL_FREEZE_INVENTORY_OR_PRE_A3_HISTORY',
                              old_sha256='NOT_IN_ORIGINAL_FREEZE_INVENTORY_OR_PRE_A3_HISTORY')
        change['new_sha256'] = item['sha256']
        changes.append(change)
    require(changes, 'sensitivity_tests addendum requires actual driver byte changes')
    return changes


def addendum_subject(native, inputs, build, build_sources):
    from forecast_checks_cli import science_inventory
    original = baseline(inputs['original_receipt'], inputs['science_freeze'], native.sources)
    inventory = science_inventory(native, build_sources)
    changes = delta(original['inventory'], inventory, getattr(native,'driver_root',Path(__file__).absolute().parent),
                    document(inputs['history'], native.sources))
    require(inputs['inventory'] == inventory and inputs['changes'] == changes,
            'sensitivity_tests complete additive inventory/delta mismatch')
    decision = checked(inputs['decision'], native.sources).decode()
    a4 = any(name in decision for name in ('TIME_ALIGNMENT-robustness_tests', 'TIME_ALIGNMENT-A5', 'TIME_ALIGNMENT-A6', 'TIME_ALIGNMENT-A7'))
    require(('TIME_ALIGNMENT-sensitivity_tests' in decision or a4) and 'ADOPTED' in decision, 'Adopted TIME_ALIGNMENT-sensitivity_tests/robustness_tests/A5/A6/A7 required')
    subject = dict(build=build, inventory=inventory, c_v1=native.c61()['sources'],
                original_receipt=inputs['original_receipt'], science_freeze=inputs['science_freeze'],
                history=inputs['history'], decision=inputs['decision'], changes=changes)
    if a4:
        previous = document(inputs['previous_addendum'], native.sources)
        receipt = document(inputs['previous_receipt'], native.sources)
        require(previous.get('schema') == ADDENDUM and previous.get('additive_only') is True and
                previous.get('original_freeze_unchanged') is True and previous.get('production_authority') is False and
                previous['subject']['science_freeze'] == inputs['science_freeze'] and
                previous['subject']['original_receipt'] == inputs['original_receipt'] and
                receipt.get('schema') == 'MINRUN_AF_CHAIN_STAGE_RECEIPT_V1' and
                receipt.get('action') == 'freeze-science-addendum' and receipt.get('result') == previous and
                receipt.get('build') == previous['subject']['build'] and receipt.get('production_authority') is False,
                'robustness_tests exact successful preceding addendum/receipt required')
        accepted(previous['source_review'], previous['subject'], sources=native.sources, role=ROLE)
        incremental = delta(previous['subject']['inventory'], inventory,
                            getattr(native,'driver_root',Path(__file__).absolute().parent),
                            document(inputs['previous_history'], native.sources))
        subject.update(previous_addendum=inputs['previous_addendum'],previous_receipt=inputs['previous_receipt'],
                       previous_history=inputs['previous_history'],incremental_changes=incremental)
    return subject


def create_addendum(native, inputs, outputs, build, build_sources):
    for path in outputs.values():
        require(not Path(path).exists(), 'Exclusive sensitivity_tests addendum output already exists')
        require(Path(path).is_relative_to(getattr(native,'driver_root',Path(__file__).absolute().parent)), 'sensitivity_tests output must remain in driver')
    subject = addendum_subject(native, inputs, build, build_sources)
    review = accepted(inputs['source_review'], subject, sources=native.sources, role=ROLE)
    value = dict(schema=ADDENDUM, utc=now(), subject=subject, source_review=inputs['source_review'],
                 additive_only=True, original_freeze_unchanged=True, production_authority=False)
    require(utc(value['utc']) >= utc(review['utc']), 'sensitivity_tests addendum must follow actual scoped GO')
    exclusive(outputs['addendum'], value)
    return value


def verify_addendum(native, item, science_freeze, build, build_sources):
    value = document(item, native.sources)
    require(value.get('schema') == ADDENDUM and value.get('additive_only') is True and
            value.get('original_freeze_unchanged') is True and value.get('production_authority') is False,
            'Actual additive sensitivity_tests scientific source record required')
    subject = value['subject']
    require(subject['science_freeze'] == science_freeze, 'sensitivity_tests addendum original-freeze mismatch')
    expected = addendum_subject(native, subject, build, build_sources)
    require(subject == expected, 'sensitivity_tests additive source binding drift')
    review = accepted(value['source_review'], expected, sources=native.sources, role=ROLE)
    require(utc(value['utc']) >= utc(review['utc']), 'sensitivity_tests addendum chronology drift')
    return value
