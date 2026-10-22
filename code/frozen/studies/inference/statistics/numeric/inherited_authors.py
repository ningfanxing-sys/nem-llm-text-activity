'Check numerical result fields with the saved validation functions.'
def validate_authors(first, second, timestamps):
    from datetime import datetime, date
    schema = author_schema()
    for obj, key in ((first, 'record_1'), (second, 'record_2')):
        require(isinstance(obj, dict) and set(schema[key]['required_keys']) <= set(obj), 'missing inference_design author record keys: ' + key)
        require(bool(obj['recorded_by']), 'empty author record provenance')
        try:
            d = date.fromisoformat(obj['author_local_date'])
            dt = datetime.fromisoformat(obj['recorded_utc'].replace('Z', '+00:00'))
            require(dt.utcoffset().total_seconds() == 0, 'author record must use UTC')
        except (ValueError, TypeError, AttributeError):
            raise FillError('invalid author record date')
        label = 'T4B' if key == 'record_1' else 'T5'
        require(label in timestamps and d <= date.fromisoformat(timestamps[label]['local_date']), 'author record after ' + label)
    require(first['choices'].get('r8_seeds') == 'single', 'RUNBOOK I19: current arXiv R12b accepts single-seed R8 only')
    require(first['choices'].get('kcx') == 'not_run' and first['choices'].get('public_registration') == 'b_private_timestamps_only', 'source R6: KCX and public registration branch refused')
    require(first['a8_freeze_sha256'] == A8_BINDINGS['A8_FREEZE.json'], 'author inference_design freeze identity drift')
    fields = schema['record_1']['fields']
    for k, spec in fields['choices'].items():
        require(first['choices'].get(k) in spec['allowed'], 'invalid author choice: ' + k)
    instruction = first['instructions'].get('resource_only_continuation', {})
    spec = fields['instructions']['resource_only_continuation']
    require(instruction.get('value') is True and instruction.get('meaning_text') == spec['meaning_text'] and bool(instruction.get('author_words')), 'missing author continuation instruction')
    correction = first['statements'].get('extraction_model_correction')
    if isinstance(correction, dict):
        correction = correction.get('value')
    require(correction == 'confirmed', 'missing extraction-model statement')
    entries = [e for e in first['confirmations'] if e.get('addendum') == 'inference_design']
    require(len(entries) == 1 and entries[0]['date'] == first['author_local_date'] and bool(entries[0]['choices']), 'invalid inference_design confirmation entry')
    for obj, label, filename in ((first, 'T4B', 'AUTHOR_CONFIRMATION_A8.json'), (second, 'T5', 'AUTHOR_CONFIRMATION_A8_PRESCORE.json')):
        digest = timestamps[label]['files'].get(filename)
        require(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest), 'author record not listed in ' + label)
    require(second['record_1_sha256'] == timestamps['T4B']['files']['AUTHOR_CONFIRMATION_A8.json'], 'record 2 first-record identity drift')
    kcx = second['kcx']
    has = kcx.get('kcx_api_key_supplied_before_T5')
    require(type(has) is bool, 'invalid KCX key attestation')
    cap = kcx.get('kcx_spend_cap_usd')
    require(has and type(cap) in (int, float) and (cap > 0) or (not has and cap is None), 'invalid KCX spend cap')
    reg = second['registration']
    vals = [reg.get(k) for k in ('registration_repository', 'registration_identifier', 'registration_embargo')]
    require(all((v is None for v in vals)) or (vals[0] in ('OSF', 'Zenodo') and isinstance(vals[1], str) and bool(vals[1]) and (type(vals[2]) is bool)), 'inconsistent deposit record')
    if first['choices']['public_registration'] == 'b_private_timestamps_only':
        require(all((v is None for v in vals)), 'private variant with public deposit')
    require(all((second['statements'].get(k) is True for k in schema['record_2']['fields']['statements'])), 'missing inference_design prescore review statements')
    return True
