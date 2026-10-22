"""Bind BOTH sources atomically after NRX1.3 finalization; never read numerical values."""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import importlib.metadata as im
import json
from pathlib import Path
import sys
from runtime import (CONF, ROOT, STATE, atomic_json, file_identity, read_json,
                     sha256, verify_adapters, verify_design, verify_identities,
                     exclusive_lock, install_audit, utc_now)

TERMINAL = {'SUCCESS', 'TERMINAL_FAILURE'}


def project_json_object(text, wanted):
    """Decode selected top-level fields; skip body/label values lexically."""
    decoder = json.JSONDecoder()
    def white(i):
        while i < len(text) and text[i].isspace(): i += 1
        return i
    def skip(i):
        in_string = False; escape = False; level = 0
        while i < len(text):
            c = text[i]
            if in_string:
                if escape: escape = False
                elif c == '\\': escape = True
                elif c == '"': in_string = False
            elif c == '"': in_string = True
            elif c in '[{': level += 1
            elif c in ']}':
                if level == 0: return i
                level -= 1
            elif c == ',' and level == 0: return i
            i += 1
        raise ValueError('Unterminated JSON object')
    i = white(0)
    if text[i] != '{': raise ValueError('Expected JSON object')
    i += 1; out = {}
    while True:
        i = white(i)
        if text[i] == '}': return out
        key, i = decoder.raw_decode(text, i); i = white(i)
        if text[i] != ':': raise ValueError('Missing JSON colon')
        i = white(i + 1)
        if key in wanted:
            out[key], i = decoder.raw_decode(text, i)
        else: i = skip(i)
        i = white(i)
        if text[i] == '}': return out
        if text[i] != ',': raise ValueError('Missing JSON comma')
        i += 1


def classify_nrx_receipt(receipt, census, expected):
    """Producer COMPLETE_WITH_FAILURES is PARTIAL-final iff ALL IDs are terminal."""
    rows = list(census)
    key = lambda r: str(r['notice_key'])
    expected_keys = {key(r) for r in expected}
    if len(expected_keys) != len(expected): raise PermissionError('Duplicate NRX source keys')
    if len({str(r['notice_id']) for r in expected}) != len(expected):
        raise PermissionError('Duplicate NRX source notice IDs')
    keys = [key(r) for r in rows]
    if len(set(keys)) != len(keys) or set(keys) != expected_keys:
        raise PermissionError('NRX has not finalized exactly the full source census')
    counts = Counter(str(r['terminal_state']) for r in rows)
    if set(counts) - TERMINAL:
        raise PermissionError('Pending/nonterminal or unknown NRX states remain')
    if dict(counts) != receipt.get('terminal_counts'):
        raise PermissionError('NRX receipt and terminal census disagree')
    for field in ['expected_unique_notices', 'labels_rows_including_failed_placeholders']:
        if receipt.get(field) != len(expected):
            raise PermissionError('NRX final count mismatch: ' + field)
    state = receipt.get('state')
    if state == 'COMPLETE':
        if counts.get('SUCCESS', 0) != len(expected):
            raise PermissionError('NRX COMPLETE claims failure-free census incorrectly')
        normalized = 'COMPLETE'
    elif state in {'PARTIAL-final', 'PARTIAL_FINAL', 'COMPLETE_WITH_FAILURES'}:
        normalized = 'PARTIAL-final'
    else:
        raise PermissionError('NRX receipt must be COMPLETE or PARTIAL-final, with full terminal census')
    source = {key(r): r for r in expected}
    for row in rows:
        original = source[key(row)]
        for field in ['notice_id', 'input_sha256']:
            if str(row[field]) != str(original[field]):
                raise PermissionError('NRX source/census identity mismatch: ' + field)
        if str(row.get('contract_version')) != '1.3':
            raise PermissionError('Earlier pilot labels cannot populate NRX1.3 final bank')
    return {'state': normalized, 'producer_state': state, 'full_terminal_census': True,
            'expected_unique_notices': len(expected), 'terminal_counts': dict(counts),
            'successful_notice_keys': sorted(key(r) for r in rows if r['terminal_state'] == 'SUCCESS'),
            'terminal_failure_notice_keys': sorted(key(r) for r in rows if r['terminal_state'] != 'SUCCESS'),
            'successful_notice_ids': sorted(str(r['notice_id']) for r in rows if r['terminal_state'] == 'SUCCESS'),
            'terminal_failure_notice_ids': sorted(str(r['notice_id']) for r in rows if r['terminal_state'] != 'SUCCESS')}


def bind_nrx(nrx):
    nrx = Path(nrx)
    bank = nrx / 'results_1_3'
    receipt_path = bank / 'EXTRACTION_RECEIPT_1_3.json'
    if not receipt_path.is_file():
        raise PermissionError('NRX1.3 finalize receipt is absent; global freeze is forbidden')
    receipt = read_json(receipt_path)
    if str(receipt.get('contract_version')) != '1.3' or receipt.get('phase') != 'finalize':
        raise PermissionError('NRX1.3 full finalize receipt required')
    if (receipt.get('model_requested'), receipt.get('model_reasoning_effort')) != ('gpt-6-luna', 'medium'):
        raise PermissionError('NRX model/effort differs')
    freeze_path = nrx / 'CONTRACT_FREEZE_1_3.json'; freeze = read_json(freeze_path)
    if freeze.get('contract_version') != '1.3' or receipt.get('contract_freeze_sha256') != sha256(freeze_path):
        raise PermissionError('NRX final producer freeze differs')
    identities = []
    def bind(path, role, expected_hash=None):
        item = file_identity(path, role=role)
        if expected_hash and item['sha256'] != expected_hash:
            raise PermissionError('NRX final artifact drift: ' + str(path))
        identities.append(item)
    bind(freeze_path, 'NRX final producer freeze')
    for rel, expected_hash in freeze['files_sha256'].items():
        bind(nrx / rel, 'NRX frozen producer dependency', expected_hash)
    for filename, receipt_field in [('scope.jsonl', 'scope_sha256')]:
        bind(nrx / filename, 'NRX source scope', receipt[receipt_field])
    for filename, field in [('labels.parquet', 'labels_sha256'),
                            ('extraction_ledger.jsonl', 'ledger_sha256'),
                            ('PILOT_RECEIPT_1_3.json', 'pilot_receipt_sha256'),
                            ('PILOT_GATE_1_3.json', 'pilot_gate_sha256')]:
        if not receipt.get(field): raise PermissionError('NRX final receipt missing identity: ' + field)
        bind(bank / filename, 'NRX final ' + filename, receipt[field])
    bind(receipt_path, 'NRX final receipt')
    if receipt.get('contract_sha256') != freeze.get('contract_sha256'):
        raise PermissionError('NRX contract receipt mismatch')
    if not freeze.get('scope_freeze_sha256') or receipt.get('scope_freeze_sha256') != freeze['scope_freeze_sha256']:
        raise PermissionError('NRX source-scope freeze receipt mismatch')
    gate = read_json(bank / 'PILOT_GATE_1_3.json')
    if gate.get('state') != 'PASS' or gate.get('contract_freeze_sha256') != sha256(freeze_path):
        raise PermissionError('NRX same-contract PASS gate required')
    with (nrx / 'scope.jsonl').open() as f:
        expected = [project_json_object(line, {'notice_key', 'notice_id', 'input_sha256'})
                    for line in f if line.strip()]
    # Explicit projection: labels, windows, quantities and notice text are not decoded.
    import pyarrow.parquet as pq
    cols = ['notice_key', 'notice_id', 'input_sha256', 'terminal_state', 'contract_version',
            'contract_sha256', 'contract_freeze_sha256']
    census = pq.read_table(bank / 'labels.parquet', columns=cols).to_pylist()
    result = classify_nrx_receipt(receipt, census, expected)
    for row in census:
        if row['contract_sha256'] != freeze['contract_sha256'] or row['contract_freeze_sha256'] != sha256(freeze_path):
            raise PermissionError('Mixed-contract NRX final row')
    # A signed count alone does not certify raw evidence. Bind every retained attempt.
    for p in sorted((bank / 'raw').rglob('*')):
        if p.is_file(): bind(p, 'NRX raw attempt opaque identity')
    return result, identities


def merge_identities(*groups):
    merged = {}
    for group in groups:
        for item in group:
            p = str(Path(item['path']).resolve())
            if p in merged and (merged[p]['sha256'], merged[p]['bytes']) != (item['sha256'], item['bytes']):
                raise PermissionError('Contradictory input identities: ' + p)
            merged.setdefault(p, {**item, 'path': p})
    return [merged[p] for p in sorted(merged)]


def bind_news(conf):
    preflight_path = conf / 'CONFX1/NEWS_INPUT_PREFLIGHT_IDENTITIES.json'
    preflight = read_json(preflight_path)
    verify_identities(preflight['inputs'])
    partitions = preflight['news_partitions']
    for group in partitions.values():
        if not all(group['checks'].values()): raise PermissionError('NEWSX preflight gate failed')
        source = set(group['source_ids']); valid = set(group['valid_ids']); failed = set(group['terminal_failure_ids'])
        if valid & failed or valid | failed != source: raise PermissionError('NEWSX terminal partition incomplete')
    bridge_path = conf / 'CONFX1/NEWS_BRIDGE_CHECK.json'; bridge = read_json(bridge_path)
    if bridge.get('same_id_conflict_count') != 0 or bridge['jan_feb_2026'].get('conflict_count') != 0:
        raise PermissionError('NEWSX cross-version or Jan-Feb bridge conflict')
    items = list(preflight['inputs']) + [file_identity(preflight_path), file_identity(bridge_path)]
    banks = [conf.parent / 'NEWSX', conf / 'newsx_extension']
    for bank in banks:
        freeze = read_json(bank / 'LABEL_FREEZE.json')
        for rel, expected in freeze['files_sha256'].items():
            p = bank / rel
            item = file_identity(p, role='NEWSX frozen dependency ' + rel)
            if item['sha256'] != expected: raise PermissionError('NEWSX contract/source drift: ' + rel)
            items.append(item)
        # Source-post files are frozen bytes, never text-decoded by this command.
        source_path = bank / 'source_posts.json'
        if source_path.is_file(): items.append(file_identity(source_path, role='NEWSX complete normalized source'))
    # Raw article reconstruction is a feature input, bound without text decoding.
    bank = banks[0]
    scope_path = bank / 'SCOPE_FREEZE_v2.json'; scope = read_json(scope_path)
    items.append(file_identity(scope_path, role='NEWSX raw-source scope freeze'))
    proj = conf.parents[2]
    source_manifest = proj / 'autopilot/q1_audits/NEWS2/A/source_manifest.csv'
    if sha256(source_manifest) != scope['source_manifest_sha256']:
        raise PermissionError('NEWSX raw source manifest changed')
    items.append(file_identity(source_manifest, role='NEWSX raw source manifest'))
    with source_manifest.open(newline='') as f:
        rows = list(csv.DictReader(f))
    suffixes = {'M917': 'm917_wattclarity_source_2016_2024/raw_posts.json',
                'M162': 'm162_wattclarity_llm_source_expansion/wattclarity_wp_posts_raw.json'}
    raw_paths = {}
    for name, suffix in suffixes.items():
        found = [Path(r['source_path']) for r in rows if r['source_path'].endswith(suffix)]
        if len(found) != 1: raise PermissionError('Ambiguous NEWSX raw source: ' + name)
        raw_paths[name] = found[0]
    raw_paths['M846'] = proj.parent.parent / 'artifacts/pivot_bq/m846_wattclarity_source_2024_2026/raw_posts.json'
    for name, path in raw_paths.items():
        item = file_identity(path, role='NEWSX frozen raw source ' + name)
        if item['sha256'] != scope['source_sha256'][name]:
            raise PermissionError('NEWSX raw source drift: ' + name)
        items.append(item)
    acquisition = raw_paths['M846'].parent / 'ACQUISITION_COMPLETE.json'
    if sha256(acquisition) != scope['m846_acquisition_receipt_sha256']:
        raise PermissionError('M846 acquisition receipt changed')
    items.append(file_identity(acquisition, role='NEWSX raw source acquisition receipt'))
    for rel in ['autopilot/q1_audits/TFN2/corrected/selection/C.json',
                'autopilot/q1_audits/TFN2/corrected/english_stopwords.txt',
                'autopilot/q1_audits/TFN2/english_stopwords.txt']:
        items.append(file_identity(proj / rel, role='Frozen T/word preprocessing input'))
    return partitions, items


def bind_environment(conf, out):
    previous_path = conf / 'CONFX1/ENCODER_ENVIRONMENT_IDENTITY.json'
    previous = read_json(previous_path)
    identities = previous['package_file_identities'] + previous['model_files'] + [previous['executable']]
    compatibility_path = conf / 'CONFX2/ENCODER_TOKENIZER_COMPATIBILITY_IDENTITIES.json'
    compatibility = read_json(compatibility_path)
    identities += compatibility['installed_primary_implementation'] + [file_identity(compatibility_path)]
    verify_identities(identities)
    if Path(sys.executable).resolve() != Path(previous['executable']['path']).resolve():
        raise PermissionError('Python executable differs from accepted preflight')
    versions = {name: im.version(name) for name in previous['packages']}
    if versions != previous['packages']:
        raise PermissionError('Encoder environment changed after accepted preflight')
    roots = {name: Path(im.distribution(name).locate_file('')).resolve()
             for name in previous['packages']}
    for item in previous['package_file_identities']:
        if not Path(item['path']).resolve().is_relative_to(roots[item['package']]):
            raise PermissionError('Installed package location differs from accepted preflight')
    if not all(x.get('match') for x in previous['model_files']):
        raise PermissionError('Encoder model bytes do not match pinned revision')
    env = {**previous, 'state': 'ENCODER_ENVIRONMENT_REVERIFIED',
           'preflight_identity': file_identity(previous_path), 'window_values_read': False}
    p = Path(out) / 'ENCODER_ENVIRONMENT_IDENTITY.json'; atomic_json(p, env, immutable=True)
    return identities + [file_identity(previous_path), file_identity(p)]


def global_input_freeze(conf_root=None, state_root=None, nrx_root=None, catalog_path=None):
    conf = Path(conf_root or CONF); state = Path(state_root or STATE)
    with exclusive_lock(state / '.freeze.lock'):
        design = verify_design(conf); verify_adapters(conf / 'CONFX2')
        complete_path = state / 'COMPLETE_INPUT_FREEZE.json'
        if complete_path.exists():
            complete = read_json(complete_path)
            if (complete.get('state') != 'COMPLETE_GLOBAL_INPUT_FREEZE' or
                    complete.get('pending_dependencies') or
                    complete.get('design_freeze', {}).get('sha256') != sha256(conf / 'FREEZE.json') or
                    complete.get('adapter_freeze_sha256') != sha256(conf / 'CONFX2/ADAPTER_FREEZE.json') or
                    complete.get('nrx_terminal_census', {}).get('state') not in {'COMPLETE','PARTIAL-final'}):
                raise PermissionError('Existing global freeze does not match the full input gate')
            verify_identities(complete['inputs'])
            auth_path = state / 'EXECUTION_AUTHORIZATION.json'
            auth = {'task_id':'CONFX2_HOST', 'state':'SEPARATE_EXECUTION_TASK_AUTHORIZED',
                    'design_freeze_sha256':sha256(conf / 'FREEZE.json'),
                    'completed_input_manifest_path':str(complete_path.resolve()),
                    'completed_input_manifest_sha256':sha256(complete_path),
                    'predictions_sealed':False,
                    'authorization_source':'User Task CONFX2 ordered HOST_RUN after NRX finalization'}
            atomic_json(auth_path, auth, immutable=True)
            return complete
        # NRX gate is checked before any new production identity publication.
        census, nrx_inputs = bind_nrx(nrx_root or conf.parent / 'NRX')
        news_partitions, news_inputs = bind_news(conf)
        from source_catalog import prepare_source_identities
        catalog_file = Path(catalog_path or conf / 'CONFX2/prepared_sources/source_catalog.json')
        if catalog_file.exists():
            catalog = read_json(catalog_file)
        else:
            catalog = prepare_source_identities(state / 'prepared_inputs')
            catalog_file = Path(catalog['path'])
        if catalog.get('pending_dependencies'):
            raise PermissionError('Source catalogue still pending: ' + repr(catalog['pending_dependencies']))
        for field in ['numeric_sources','archive_members','notice_prefix','p5min_mapping']:
            if not catalog.get(field):
                raise PermissionError('Global source identity dependency missing: ' + field)
        if not catalog['p5min_mapping'].get('training_identity'):
            raise PermissionError('Historical E3 training-row key mapping missing')
        catalog_inputs = catalog['inputs'] + [file_identity(catalog_file, role='Complete key/clock source catalogue')]
        verify_identities(catalog_inputs)
        env_inputs = bind_environment(conf, state)
        existing = read_json(conf / 'INPUT_MANIFEST.json')['inputs']
        verify_identities(existing)
        adapter_inputs = [file_identity(conf / 'CONFX2/ADAPTER_FREEZE.json')]
        inputs = merge_identities(existing, news_inputs, nrx_inputs, catalog_inputs, env_inputs, adapter_inputs)
        complete = {'task_id': 'CONFX2_HOST', 'state': 'COMPLETE_GLOBAL_INPUT_FREEZE',
                    'design_freeze': file_identity(conf / 'FREEZE.json'),
                    'adapter_freeze_sha256': sha256(conf / 'CONFX2/ADAPTER_FREEZE.json'),
                    'pending_dependencies': [], 'inputs': inputs, 'inputs_frozen_before_values': True,
                    'nrx_terminal_census': census, 'news_partitions': news_partitions,
                    'source_catalog_path': str(catalog_file.resolve()),
                    'nrx_labels_path': str(Path(nrx_root or conf.parent / 'NRX') / 'results_1_3/labels.parquet'),
                    'window_values_read': False, 'study_fits': 0, 'study_scores': 0,
                    'execution_rule': design['execution_rule']}
        path = state / 'COMPLETE_INPUT_FREEZE.json'; atomic_json(path, complete, immutable=True)
        auth = {'task_id': 'CONFX2_HOST', 'state': 'SEPARATE_EXECUTION_TASK_AUTHORIZED',
                'design_freeze_sha256': sha256(conf / 'FREEZE.json'),
                'completed_input_manifest_path': str(path.resolve()),
                'completed_input_manifest_sha256': sha256(path),
                'predictions_sealed': False,
                'authorization_source': 'User Task CONFX2 ordered HOST_RUN after NRX finalization'}
        atomic_json(state / 'EXECUTION_AUTHORIZATION.json', auth, immutable=True)
        return complete


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state', type=Path, default=STATE)
    p.add_argument('--check-gate', action='store_true')
    args = p.parse_args(); install_audit('global_freeze')
    if args.check_gate:
        census, _ = bind_nrx(CONF.parent / 'NRX')
        print(json.dumps({'state': census['state'], 'full_terminal_census': True}))
    else:
        result = global_input_freeze(state_root=args.state)
        print(json.dumps({'state': result['state'], 'input_files': len(result['inputs']),
                          'window_values_read': False}))

if __name__ == '__main__': main()
