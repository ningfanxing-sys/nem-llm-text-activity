'Check batch source hashes and forecast computation records.'
from pathlib import Path
from batch_inputs import *
from batch_identities import chain_pin, newest_chain, declared_identity, receipt_identity_checks, NO_SEAL_ADAPTER, ADAPTER_FIELDS, PATH_FIELDS

def verify_adapter(root=ADAPTER, expected=None):

    root = Path(root).resolve()
    freeze = root / 'ADAPTER_FREEZE.json'
    require(expected is not None and sha(freeze) == expected, 'Installed adapter freeze drift or missing pin')
    frozen = read_json(freeze)
    require(frozen['state'] == 'SPEC_2_FROZEN_SYNTHETICALLY_VERIFIED', 'Invalid adapter freeze')
    files = [identity(freeze)]
    for rel, item in frozen['files'].items():
        p = (root / rel).resolve()
        require(root.parent in p.parents and 'host_state' not in p.parts and
                not p.name.startswith('SEAL') and 'scored' not in p.parts and 'predictions' not in p.name.lower(),
                'Invalid adapter freeze path')
        require(sha(p) == item['sha256'] and p.stat().st_size == item['bytes'], 'Adapter code drift: ' + rel)
        files.append(identity(p))

    runtime = module(root / 'runtime.py', '_a8_pin_runtime')
    chain_path, chain = newest_chain(root)
    require(chain['steps'][-1]['task'] == frozen['execution_specification']['task'] and
            chain['steps'][-1]['adapter_freeze']['sha256'] == expected, 'Chain/adapter pin drift')
    runtime.verify_adapter_ancestor(root, chain['input_bound_root']['sha256'])
    files.append(identity(chain_path))
    return files

def seal_adapter_pin(seal):

    require(seal.get('state') == 'ALL_SPECIFIED_PREDICTIONS_SEALED' and
            seal.get('sealed_before_outcome_scoring') is True, 'Completed main confirmation seal required')
    pin = seal.get('adapter_freeze_sha256')
    if pin is None:
        value = seal.get('adapter_freeze')
        pin = value.get('sha256') if isinstance(value, dict) else value
    require(pin is None or (isinstance(pin, str) and len(pin) == 64 and all(c in '0123456789abcdef' for c in pin)),
            'Invalid main seal adapter identity')
    return pin

def verify_main_binding(code, seal_path=None, preverified=False):
    path = Path(seal_path) if seal_path is not None else Path(code['adapter_root']) / 'host_state/SEAL.json'
    binding = code['adapter_chain_pin'] if preverified else chain_pin(code['adapter_root'])
    pin = binding['adapter_freeze']['sha256']
    require(pin == code['adapter_freeze_sha256'], 'Main chain/code adapter pin drift; re-pin and timestamp required')
    if not preverified:
        verify_adapter(code['adapter_root'],pin)
    require(path.is_file(), 'Main seal does not exist; verifier refuses before sealing')
    if code.get('conf_seal'):
        require(identity(path) == code['conf_seal'], 'Main seal drift')
    seal = read_json(path)
    seal_adapter_pin(seal)
    if code.get('adapter_chain_pin'):
        require(binding == code['adapter_chain_pin'], 'Frozen specification-chain/T4 binding drift')
    frozen = read_json(Path(code['adapter_root'])/'ADAPTER_FREEZE.json')
    from batch_identities import main_group_chronology
    chronology = main_group_chronology(seal,path,code['adapter_root'])
    fields = declared_identity(seal, code['adapter_root'], pin, frozen, str(path))
    receipts = receipt_identity_checks(seal, path, code['adapter_root'], pin, frozen)
    code['main_adapter_binding'] = dict(pin=binding, seal=identity(path), declared_identity_fields=fields,
        fit_receipts=receipts, chronology=chronology, note=(NO_SEAL_ADAPTER if not any(k in seal for k in (*ADAPTER_FIELDS, *PATH_FIELDS))
                                   else 'seal adapter identity agrees with SPECIFIED_ADAPTER_CHAIN + live freeze + T4'))
    return identity(path)

def specs():
    final = confirmation / 'inference_design/ADDENDUM_A8.md'
    frozen_path = final.parent/'A8_FREEZE.json'
    if not frozen_path.is_file():
        return dict(status='TODO_FINAL_A8_BINDING', files=[])
    frozen = read_json(frozen_path)
    paths = [frozen_path]
    specification = final.parent/'ADDENDUM_A8_SPECIFICATION_1_FREEZE.json'
    helper = module(final.parent/'freeze_inference_design.py','_a8_specification1')
    helper.verify(specification)
    paths += [specification,final.parent/'freeze_inference_design.py',final.parent/'ADDENDUM_A8_SPECIFICATION_1_PAPER.md']
    for rel, item in frozen['files'].items():
        path = final.parent/rel
        require(path.stat().st_size == item['bytes'] and sha(path) == item['sha256'], 'Frozen inference_design input drift: '+rel)
        paths.append(path)


    paths += [OUT/'specification2/ADDENDUM_A8_SPECIFICATION_2_PAPER.md']
    return dict(status='FINAL_PRESENT', files=[identity(p) for p in dict.fromkeys(paths)])

def external_files():
    paths = [PROJ / 'paper_plan/task_specs/COMMON_RULES.md',
             confirmation / 'COMPUTE_PLAN.md',
             confirmation / 'input_definitions/PLAN_ACCOUNTING.json', confirmation / 'DESIGN_CONFIG.json', confirmation / 'FREEZE.json',
              Q / 'batch_scoring/CODE_FREEZE.json']
    paths += sorted((confirmation / 'code').glob('*.py'))
    paths += [confirmation/'primary_tests/A2_CODE_AND_RULES_FREEZE.json',confirmation/'primary_tests/code/primary_comparisons.py']

    paths += sorted((Q / 'batch_scoring/code').glob('*.py'))
    paths += [OUT/'HOST_RUN_A8.md',OUT/'DLY8_EXECUTION_NOTE.md',OUT/'validation_group_4_CONSUMER_CONTRACT.md']
    return [identity(p) for p in paths]

def provenance_files():
    return [identity(p) for p in (PROJ/'tables/table_renderer/SOURCE_RULINGS_20261004.md',PROJ/'paper_plan/MASTER_PLAN_20261004.md',
            PROJ/'tables/SPEC_TABLE_RESULTS.md', PROJ/'paper_plan/task_specs/COMMON_RULES_ADDENDUM_20261004.md',
            PROJ/'paper_plan/task_specs/TASK_A8BATCH_code.md',Q/'label_scoring/RUNBOOK.md')]

def prepare():
    pin = chain_pin(ADAPTER)
    from batch_definitions import r8_policy
    return dict(state='PRE_FREEZE_REVIEW_ONLY', adapter_chain_pin=pin, r8_policy=r8_policy(),
                adapter_files=verify_adapter(expected=pin['adapter_freeze']['sha256']), specs=specs(),
                external_files=external_files(), provenance=provenance_files(), code_sha256=code_hashes(), production_state_reads=0,
                production_fits=0, frozen=False)

def validate_author(binding):

    item = identity(confirmation/'AUTHOR_CONFIRMATION_A8.json')
    declared = binding.get('author_confirmation',{'path':item['path']})
    require(set(declared) == {'path'} or declared == item,'Author record identity drift')
    require(Path(item['path']).resolve() == (confirmation/'AUTHOR_CONFIRMATION_A8.json').resolve(), 'Wrong inference_design author record path')
    author = read_json(checked(item))
    schema = read_json(confirmation/'inference_design/AUTHOR_CONFIRMATION_A8_SCHEMA.json')['record_1']
    require(set(schema['required_keys']) <= set(author), 'Incomplete inference_design author confirmation')
    require(author['a8_freeze_sha256'] == sha(confirmation/'inference_design/A8_FREEZE.json'), 'Author/inference_design freeze drift')
    for name,definition in schema['fields']['choices'].items():
        require(name in author['choices'], 'Missing author choice: '+name)
        if 'allowed' in definition:
            require(author['choices'][name] in definition['allowed'], 'Invalid author choice: '+name)
    choices = author['choices']
    require(choices.get('kcx') == 'not_run' and choices.get('public_registration') == 'b_private_timestamps_only' and choices.get('r8_seeds') == 'single',
            'Source R6/R12b: KCX not_run, private timestamps and single seed are binding')
    require(bool(author['recorded_by']) and dt.datetime.fromisoformat(author['recorded_utc'].replace('Z','+00:00')).utcoffset() == dt.timedelta(0),
            'Dated UTC author record required')
    instruction = author['instructions'].get('resource_only_continuation',{})
    expected = schema['fields']['instructions']['resource_only_continuation']
    require(isinstance(instruction,dict) and instruction.get('value') is True and instruction.get('meaning_text') == expected['meaning_text'] and bool(instruction.get('author_words')),
            'Explicit author resource-only continuation instruction required')
    for name,definition in schema['fields']['statements'].items():
        require(author['statements'].get(name) in definition['allowed'], 'Invalid author statement: '+name)
    entries = [e for e in author['confirmations'] if e.get('addendum') == 'inference_design']
    require(len(entries) == 1 and entries[0].get('date') == author['author_local_date'] and entries[0].get('choices'),
            'Dated inference_design confirmation required')
    return item

def r8_projection_inputs(binding):
    from check_window_inputs import decision
    projection=binding.get('r8_time_projection')
    require(isinstance(projection,dict) and set(projection)=={'dly8_r8_seconds','seal_seconds','evidence'}
            and projection['evidence'], 'Reviewed DLY8-R8/seal projections required')
    decision(now(),1.,projection['dly8_r8_seconds'],projection['seal_seconds'])
    for item in projection['evidence']:checked(item)
    require(all(item in binding.get('input_files',[]) for item in projection['evidence']),
            'Projection evidence must be immutable batch inputs before T4B')
    return projection['evidence']

def r8_build_inputs(binding):
    from window_manifest import validate_receipt
    require(binding.get('r8_build_receipt'), 'R8 build receipt required')
    manifest_path = checked(binding['r8_metadata_manifest'])
    receipt_path = checked(binding['r8_build_receipt'])
    items = validate_receipt(manifest_path,receipt_path)
    manifest = read_json(manifest_path)
    require(manifest['builder'] == identity(OUT/'code/window_manifest.py'), 'Current R8 builder required')
    require(manifest['metadata'] == binding['metadata'], 'R8 metadata/bindings drift')
    bound = binding.get('input_files',[])
    require(all(item in bound for item in items), 'All R8 build/config/source/type/coverage identities must be batch inputs')
    return items

def validate_t4b(binding):

    gate_path = OUT/'T4B_BINDING.json'
    gate = read_json(gate_path)
    require(gate.get('state') == 'T4B_VERIFIED' and gate.get('source_verified') is True, 'Verified T4B required before computation')
    required = [identity(OUT/'CODE_FREEZE.json'),identity(OUT/'HOST_RUN_A8.md'),
                validate_author(binding),identity(checked(binding['r8_metadata_manifest'])),identity(confirmation/'inference_design/A8_FREEZE.json')]
    from batch_definitions import r8_policy
    policy = r8_policy()
    require(policy.get('admission_rule') == 'R12b' and policy.get('specification'),
            'Effective verified R12b specification 2 required before T4B/execution')
    from batch_definitions import verify as verify_specification
    specification = verify_specification(policy['specification']['path'])
    required += [policy['specification'],*specification['files'],*r8_build_inputs(binding),*r8_projection_inputs(binding)]
    from source_binding_plan import validate_plan, mutable_repin_path
    required += validate_plan(binding)
    types = read_json(checked(binding['r8_metadata_manifest'])).get('training_types_receipt')
    require(types is not None,'T4B requires separate training-only type receipt')
    required.append(types)
    author = read_json(checked(validate_author(binding)))
    gate_time = gate.get('utc',gate.get('time_utc',gate.get('verified_utc')))
    require(gate_time is not None,'Dated T4B gate required')
    require(dt.date.fromisoformat(author['author_local_date']) <= dt.datetime.fromisoformat(gate_time.replace('Z','+00:00')).astimezone(__import__('zoneinfo').ZoneInfo('Australia/Sydney')).date(),'Author local date is later than T4B')
    for item in gate['files']:
        if not mutable_repin_path(item['path']):checked(item)
    require(all(item in gate['files'] for item in required), 'T4B is missing a required current batch_estimation identity')
    require(len(gate.get('tsa_receipts',[])) >= 2, 'Two verified TSA receipts required')
    for item in gate['tsa_receipts']:
        checked(item)
    return identity(gate_path)

def validate_measurement(path=LEGACY_OUT/'test_logs/DLY8_BENCHMARK_RESULTS.json'):

    value = read_json(path)
    require(value.get('state') == 'MEASURED_SYNTHETIC_ONLY' and value.get('serial_children') is True and
            value.get('production_state_reads') == 0 and value.get('production_fits') == 0,
            'Full-panel serial synthetic DLY8 measurement required before freeze')
    if value['code_sha256']['code/rebuild_delayed_features.py'] != sha(OUT/'code/rebuild_delayed_features.py'):
        from measurement_bridge import verify_bridge
        verify_bridge(path,value)
    modes = {r['mode']:r for r in value['results']}
    require(set(modes) == {1,2} and len(value['results']) == 2,'Measure each DLY8 mode in a separate child')
    require(modes[1]['keys'] == 527040 and modes[1]['projection_calls'] == 4 and
            modes[1]['deltas'] == [0,5,15,60] and modes[1]['state'] == 'ALL_DLY8_PREDICTIONS_SEALED',
            'DLY8 complete full-panel zero/delay measurement required')
    require(modes[1]['scratch'] != modes[2]['scratch'],'DLY8 memory must be measured in separate roots/children')
    for row in modes.values():
        require(row['synthetic_only'] is True and row['nice'] >= 5 and row['wall_seconds'] >= 0 and
                0 < row['peak_rss_bytes'] < 2*1024**3 and row['minimum_memory_free_percent'] >= 25 and
                row['parent_observed_minimum_free_percent'] >= 25,'DLY8 measurement resource gate failed')

        copied = Path(row['scratch'])/'confirmation/execution'
        if not copied.exists():
            copied = LEGACY_OUT/'measurement_evidence'/('mode'+str(row['mode']))/'execution'
        require(all((copied/p.name).is_file() and sha(copied/p.name) == sha(p) for p in ADAPTER.glob('*.py')),
                'Installed projection differs from measured implementation copy')
    return identity(path)

def create():

    require(not (OUT / 'CODE_FREEZE.json').exists(), 'Never overwrite a code freeze')
    candidate = prepare()
    require(candidate['specs']['status'] == 'FINAL_PRESENT', 'Required: final inference_design text/spec binding required')
    require((confirmation/'inference_design/A8_FREEZE.json').is_file(), 'Required: final inference_design freeze required before batch code freeze')
    contract = OUT / 'BINDINGS.json'
    require(contract.is_file(), 'Required: reviewed BINDINGS.json required')
    binding = read_json(contract)
    require(binding.get('source_reviewed') is True, 'Source bindings not reviewed')
    t4a = read_json(checked(binding['t4a_binding']))
    require(t4a.get('state') == 'T4A_VERIFIED' and t4a.get('source_verified') is True, 'Verified T4A required before batch_estimation freeze')
    require(identity(confirmation/'inference_design/A8_FREEZE.json') in t4a['files'], 'T4A does not bind the current inference_design freeze')
    for item in [*t4a['files'],*t4a.get('tsa_receipts',[])]:
        checked(item)
    require(len(t4a.get('tsa_receipts',[])) >= 2, 'Two verified T4A TSA receipts required')
    from window_activity import validate_contract
    validate_contract(binding['metadata'])
    require(binding['metadata']['news_lag_scope'] == 'M_72H_IDS', 'inference_design requires exactly M-admitted source IDs')
    metadata_inputs = [*binding['metadata']['news_manifests'],binding['metadata']['notice_scope']]
    require(len(binding['metadata']['news_manifests']) == 2, 'Bind both original and extension news manifests')
    bound = {i['sha256'] for i in binding.get('input_files',[])}
    require(all(item.get('sha256') in bound for item in metadata_inputs), 'All metadata inputs must be frozen before source reads')
    metadata_manifest = read_json(checked(binding['r8_metadata_manifest']))
    require(metadata_manifest.get('state') == 'R8_SOURCE_METADATA_FROZEN' and metadata_manifest.get('metadata') == binding['metadata'],
            'Frozen R8 metadata manifest/type list must equal bindings')
    r8_build_inputs(binding)
    from source_binding_plan import validate_plan
    validate_plan(binding)
    require(isinstance(binding['metadata'].get('notice_training_types'),list), 'Frozen training-only Notice Type list required')
    require(all(i['sha256'] in bound for i in (binding['r8_metadata_manifest'],binding['t4a_binding'])),
            'R8 metadata manifest and T4A binding must be frozen inputs')
    require(Path(binding.get('author_confirmation',{}).get('path','')).resolve() == (confirmation/'AUTHOR_CONFIRMATION_A8.json').resolve(),
            'Declare author record 1 path; its later exact identity must be listed in T4B')
    from run_comparison_sets import validate_selection_spec
    validate_selection_spec(binding['cps8'])
    from check_window_inputs import decision
    r8_projection_inputs(binding)
    projection = binding.get('r8_time_projection')
    require(isinstance(projection,dict) and projection.get('evidence'),'Reviewed DLY8-R8 and seal-step projections required')
    for item in projection['evidence']: checked(item)
    decision(now(),1.,projection['dly8_r8_seconds'],projection['seal_seconds'])
    tests = read_json(OUT / 'TEST_RESULTS.json')
    require(tests['passed'] and tests['code_sha256'] == code_hashes(), 'Exact current passing synthetic suite required')
    smoke = read_json(OUT/'test_logs/PROCESS_TABLE_SMOKE.json')
    require(smoke.get('passed') is True and smoke.get('read_only') is True and smoke.get('code_sha256') == code_hashes(),'Actual current Mac process-table smoke required before freeze')
    dry = read_json(OUT/'DRY_RUN_RESULT.json')
    require(dry['passed'] and dry.get('code_sha256') == code_hashes(), 'Exact current passing synthetic dry run required')
    measured = validate_measurement()
    encoder_path = LEGACY_OUT/'test_logs/REAL_ENCODER_MEASUREMENT.json'
    encoder = read_json(encoder_path)
    require(encoder['state'] == 'PASS' and encoder['synthetic_only'] is True and
            encoder['production_state_reads'] == encoder['production_fits'] == 0 and
            encoder['bytes_equal'] is True and 0 < encoder['peak_rss_bytes'] < 2*1024**3 and
            encoder['nice'] == 5 and encoder['minimum_memory_free_percent'] >= 25 and
            encoder['measurement_code'] == identity(LEGACY_OUT/'tests/measure_encoder.py') and
            sha(OUT/'tests/measure_encoder.py') == encoder['measurement_code']['sha256'],
            'Exact current real-encoder synthetic RSS and cache-copy parity measurement required')
    checked(encoder['spec']);checked(encoder['log'])
    candidate.update(state='A8BATCH_CODE_FROZEN_BEFORE_FITTING', frozen=True, frozen_utc=now(),
                     adapter_root=str(ADAPTER), adapter_freeze_sha256=candidate['adapter_chain_pin']['adapter_freeze']['sha256'],
                     bindings=identity(contract), test_receipts_provenance=dict(tests=identity(OUT/'TEST_RESULTS.json'),dry_run=identity(OUT/'DRY_RUN_RESULT.json'),dly8_measurement=measured,real_encoder=identity(encoder_path)))
    mutable = {i['path'] for i in candidate['provenance']} | {str(OUT/n) for n in ('TEST_RESULTS.json','DRY_RUN_RESULT.json')}
    from source_binding_plan import mutable_repin_path
    candidate['external_files'] += [i for i in binding.get('input_files',[]) if str(Path(i['path']).resolve()) not in mutable and not mutable_repin_path(i['path'])]
    candidate['provenance'] += [i for i in binding.get('input_files',[]) if str(Path(i['path']).resolve()) in mutable]
    for item in candidate['external_files']:
        checked(item)
    write_json(OUT / 'CODE_FREEZE.json', candidate, exclusive=True)
    return candidate

def verify(path=OUT / 'CODE_FREEZE.json', seal_path=None):
    result = read_json(path)
    require(result['state'] == 'A8BATCH_CODE_FROZEN_BEFORE_FITTING', 'Invalid inference_design batch freeze')
    require(result['code_sha256'] == code_hashes(), 'batch_estimation frozen code drift')
    require(result['specs'] == specs(), 'inference_design specification inventory/identity drift')
    from source_binding_plan import mutable_repin_path
    for item in [*result['specs']['files'], *result['external_files'], result['bindings']]:
        if not mutable_repin_path(item['path']):checked(item)
    binding = read_json(checked(result['bindings']))
    pinned = chain_pin(result['adapter_root'])
    require(pinned == result['adapter_chain_pin'], 'Frozen specification-chain/T4 binding drift')
    verify_adapter(result['adapter_root'],result['adapter_freeze_sha256'])
    validate_t4b(binding)
    from batch_definitions import r8_policy
    result['r8_policy'] = r8_policy()
    if result['r8_policy'].get('specification') and not result['r8_policy'].get('admission_rule'):
        from batch_definitions import author_reason
        result['r8_policy']['reason'] = author_reason(read_json(checked(validate_author(binding))))
    verify_main_binding(result, seal_path, preverified=True)
    return result


def validate_t5_binding(code, state):
    path = OUT/'T5_BINDING.json'
    gate = read_json(path)
    require(gate.get('state') == 'T5_VERIFIED' and gate.get('source_verified') is True, 'Verified T5 required before score')
    from scorer_freeze import verify as verify_scorer
    verify_scorer()
    required = [identity(OUT/'CODE_FREEZE.json'),identity(OUT/'SCORER_CODE_FREEZE.json'),identity(OUT/'code/score_batch.py'),
                identity(Path(state)/'SEAL_BATCH.json'),identity(OUT/'dly8/DELAY_FORECAST_SEAL.json'),
                identity(OUT/'dly8/DLY8_SEAL_R8.json'),identity(confirmation/'inference_design/A8_FREEZE.json')]
    from run_comparison_sets import cps_root
    selection = cps_root(state)/'CPS8_SELECTION.json'
    if selection.exists(): required.append(identity(selection))
    b0 = Path(state)/'B0_REPRODUCTION.json'
    require(b0.is_file(),'T5 requires the B0 reproduction/deviation evidence')
    required.append(identity(b0))
    policy = code.get('r8_policy',{'run':True})
    require(policy.get('admission_rule') == 'R12b' and policy.get('specification'), 'Effective R12b specification 2 required at T5')
    from batch_definitions import verify as verify_specification
    specification = verify_specification(checked(policy['specification']))
    required += [policy['specification'],*specification['files']]
    from source_binding_plan import validate_effective
    required += validate_effective(read_json(checked(code['bindings'])))
    for item in gate['files']:
        checked(item)
    require(all(i in gate['files'] for i in required), 'T5 missing current inference_design scorer/seal identity')
    require(len(gate.get('tsa_receipts',[])) >= 2, 'Two verified T5 TSA receipts required')
    for item in gate['tsa_receipts']:
        checked(item)
    return identity(path)
