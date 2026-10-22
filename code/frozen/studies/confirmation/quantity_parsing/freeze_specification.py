"""CONFX4 freeze steps, run once in order after the records are final.

  after    AFTER_IDENTITIES.json for every changed/new file and bound CONFX4 record
  freeze   the amended CONFX2/ADAPTER_FREEZE.json (parent: archived CONFX3 freeze)
  chain    AMENDED_ADAPTER_CHAIN.json covering original -> CONFX3 -> CONFX4
  verify   FINAL_VERIFICATION.json: the real chain, adapters, design, suite sources

No host_state file is opened; no production command runs.
"""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True

import argparse
import datetime as dt
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONF = HERE.parent
ADAPTERS = CONF / 'CONFX2'
sys.path.insert(0, str(ADAPTERS))
import runtime  # noqa: E402

INPUT_BOUND_ROOT = 'de80c4e0c3450f3e4383c477c4a3a088cc7d3956835f8ba5e51cf5d78944b394'
CONFX3_FREEZE = '31d95d21be89a9a69fd8653d630f2e670fbdb06bac1ede7319b5a43e3072d985'
PARENT = HERE / 'archive/pre_CONFX4/CONFX2/ADAPTER_FREEZE.json'
CHANGED_OR_NEW = ['CONFX2/nrx_adapter.py', 'CONFX2/runtime.py', 'CONFX2/tests/test_execution_amendment.py',
                  'CONFX2/tests/test_nrx_mw_literal.py', 'HOST_RUN.md']
BOUND_RECORDS = ['SPEC.md', 'SPEC_FREEZE.json', 'BEFORE_IDENTITIES.json', 'AFTER_IDENTITIES.json',
                 'EXECUTION_DIFF.patch', 'EXECUTION_NOTE.md', 'EQUIVALENCE_RESULTS.json', 'UNCHANGED_CODE.json',
                 'FROZEN_DESIGN_VERIFICATION.json', 'NEWS_PATH_PROOF.json', 'PRODUCTION_INTERRUPTION.json',
                 'FINAL_TEST_RESULTS.json', 'FINAL_SYNTHETIC_TEST.log', 'verify_mw_equivalence.py',
                 'verify_code_scope.py', 'freeze_amendment.py', 'loss_acceptance_breakdown.py',
                 'LOSS_ACCEPTANCE_BREAKDOWN.json']
MW_COLUMNS = {'L14': ['nw_res_deficit_mw_local', 'nw_res_min_avail_mw_local'],
              'NPL': ['nw_res_deficit_mw_local', 'nw_res_min_avail_mw_local'],
              'NPP': ['nw_res_deficit_mw_local', 'nw_res_min_avail_mw_local'],
              'L_Laz': ['laz_SizeOfOutage_MW']}


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def after():
    records = [name for name in BOUND_RECORDS if name != 'AFTER_IDENTITIES.json']
    out = {rel: runtime.file_identity(CONF / rel) for rel in CHANGED_OR_NEW}
    out.update({'CONFX4/' + name: runtime.file_identity(HERE / name) for name in records})
    runtime.atomic_json(HERE / 'AFTER_IDENTITIES.json', out, immutable=True)
    return out


def freeze():
    require(runtime.sha256(PARENT) == CONFX3_FREEZE, 'archived CONFX3 freeze drift')
    parent = runtime.read_json(PARENT)
    before = runtime.read_json(HERE / 'BEFORE_IDENTITIES.json')
    for key, item in before.items():
        require(runtime.sha256(item['archive_path']) == item['sha256'], 'archive drift ' + key)
    for key, item in runtime.read_json(HERE / 'AFTER_IDENTITIES.json').items():
        require(runtime.file_identity(item['path']) == item, 'after-identity drift ' + key)
    tests = runtime.read_json(HERE / 'FINAL_TEST_RESULTS.json')
    require(tests['state'] == 'PASS' and not tests['source_drift_during_tests'], 'final suite did not pass cleanly')
    equivalence = runtime.read_json(HERE / 'EQUIVALENCE_RESULTS.json')
    require(equivalence['state'] == 'PASS', 'equivalence proof did not pass')
    for name in ('UNCHANGED_CODE.json', 'FROZEN_DESIGN_VERIFICATION.json', 'NEWS_PATH_PROOF.json'):
        require(runtime.read_json(HERE / name)['state'] == 'PASS', name + ' did not pass')
    files = {}
    for rel in parent['files']:
        p = ADAPTERS / rel
        files[rel] = {'sha256': runtime.sha256(p), 'bytes': p.stat().st_size}
    files['tests/test_nrx_mw_literal.py'] = {'sha256': runtime.sha256(ADAPTERS / 'tests/test_nrx_mw_literal.py'),
                                             'bytes': (ADAPTERS / 'tests/test_nrx_mw_literal.py').stat().st_size}
    for name in BOUND_RECORDS:
        files['../CONFX4/' + name] = {'sha256': runtime.sha256(HERE / name), 'bytes': (HERE / name).stat().st_size}
    identity = runtime.file_identity
    manifest = {
        'design_freeze': parent['design_freeze'], 'execution_rule': parent['execution_rule'],
        'execution_amendment': {
            'task': 'CONFX4',
            'reason': 'NRX 1.3 value_text keeps the source literal (e.g. "447 MW") with the unit in its own enum; '
                      'nrx_adapter.scalar() accepted bare numbers only, so bound MW quantities became NaN '
                      '(ISOBATCH pre-fit audit, 2026-10-02, before any CONF fit, prediction, seal or score)',
            'parent_adapter_freeze': identity(PARENT),
            'before_identities': identity(HERE / 'BEFORE_IDENTITIES.json'),
            'after_identities': identity(HERE / 'AFTER_IDENTITIES.json'),
            'execution_note': identity(HERE / 'EXECUTION_NOTE.md'),
            'spec': identity(HERE / 'SPEC.md'), 'spec_freeze': identity(HERE / 'SPEC_FREEZE.json'),
            'equivalence_proof': identity(HERE / 'EQUIVALENCE_RESULTS.json'),
            'unchanged_code': identity(HERE / 'UNCHANGED_CODE.json'),
            'news_path_proof': identity(HERE / 'NEWS_PATH_PROOF.json'),
            'frozen_design_verification': identity(HERE / 'FROZEN_DESIGN_VERIFICATION.json'),
            'production_interruption': identity(HERE / 'PRODUCTION_INTERRUPTION.json'),
            'execution_diff': identity(HERE / 'EXECUTION_DIFF.patch'),
            'no_statistical_design_or_inference_rule_change': True,
            'no_statistical_design_or_feature_content_change': False,
            'feature_content_change': runtime.CONFX4_FEATURE_CONTENT_CHANGE,
            'corrected_function': 'nrx_adapter.scalar, called by nrx_adapter._bound_quantities with the declared unit',
            'mw_dependent_columns': MW_COLUMNS,
            'registered_chain': list(runtime.AMENDMENT_CHAIN)},
        'files': dict(sorted(files.items())),
        'input_only_feature_slices_read': False,
        'labels_and_keys_read': 'NRX historical-period labels/scope lines, key/clock columns (SPEC section 6)',
        'mutable_access_logs': parent['mutable_access_logs'],
        'parent_task_id': 'CONFX3', 'production_commands_run': [],
        'production_global_input_freeze_written': False,
        'state': 'ADAPTERS_FROZEN_SYNTHETICALLY_VERIFIED', 'task_id': 'CONFX4',
        'test_results': identity(HERE / 'FINAL_TEST_RESULTS.json'), 'time_utc': utc_now(),
        'window_outcomes_read': False, 'window_values_read': False}
    runtime.atomic_json(ADAPTERS / 'ADAPTER_FREEZE.json', manifest)
    return manifest


def chain():
    current, steps = runtime.adapter_amendment_chain(ADAPTERS, INPUT_BOUND_ROOT)
    require([s['task'] for s in steps] == ['CONFX3', 'CONFX4'], 'chain order')
    confx3 = runtime.read_json(PARENT)['execution_amendment']
    record = {
        'state': 'EXECUTION_AMENDMENT_CHAIN_FROZEN', 'time_utc': utc_now(),
        'registered_chain': ['input-bound original', 'CONFX3', 'CONFX4'],
        'input_bound_root': {**steps[0]['parent_adapter_freeze'],
                             'bound_by': 'CONFX2/host_state/COMPLETE_INPUT_FREEZE.json adapter_freeze_sha256 and '
                                         'its adapter input item (not opened by CONFX4; recorded by CONFX3)'},
        'steps': [
            {'task': 'CONFX3', 'adapter_freeze': runtime.file_identity(PARENT),
             'parent_adapter_freeze': confx3['parent_adapter_freeze'], 'execution_note': confx3['execution_note'],
             'before_identities': confx3['before_identities'],
             'chain_record': runtime.file_identity(CONF / 'CONFX3/AMENDED_ADAPTER_CHAIN.json'),
             'declaration': {'no_statistical_design_or_feature_content_change': True}},
            {'task': 'CONFX4', 'adapter_freeze': runtime.file_identity(ADAPTERS / 'ADAPTER_FREEZE.json'),
             'parent_adapter_freeze': current['execution_amendment']['parent_adapter_freeze'],
             'execution_note': current['execution_amendment']['execution_note'],
             'before_identities': current['execution_amendment']['before_identities'],
             'equivalence_proof': current['execution_amendment']['equivalence_proof'],
             'test_results': current['test_results'],
             'declaration': {'no_statistical_design_or_inference_rule_change': True,
                             'feature_content_change': runtime.CONFX4_FEATURE_CONTENT_CHANGE}}],
        'amended_adapter_freeze': runtime.file_identity(ADAPTERS / 'ADAPTER_FREEZE.json'),
        'runtime_verifier': 'CONFX2/runtime.py adapter_amendment_chain (used by verify_adapter_ancestor and validate_permit)',
        'original_input_freeze_and_authorization_retained': True,
        'no_statistical_design_or_inference_rule_change': True}
    runtime.atomic_json(HERE / 'AMENDED_ADAPTER_CHAIN.json', record, immutable=True)
    return record


def verify():
    current, steps = runtime.adapter_amendment_chain(ADAPTERS, INPUT_BOUND_ROOT)
    design = runtime.verify_design()
    chain_record = runtime.read_json(HERE / 'AMENDED_ADAPTER_CHAIN.json')
    tests = runtime.read_json(HERE / 'FINAL_TEST_RESULTS.json')
    source_items = tests['test_files'] + tests['adapter_source_files']
    suite_sources_match = all(runtime.file_identity(item['path'])['sha256'] == item['sha256'] for item in source_items)
    # A suite source list must cover every current CONFX2 Python file.
    covered = {Path(item['path']).resolve() for item in source_items}
    current_sources = {p.resolve() for p in [*ADAPTERS.glob('*.py'), *(ADAPTERS / 'tests').glob('*.py')]}
    for rejected in ('f' * 64, CONFX3_FREEZE):
        try:
            runtime.verify_adapter_ancestor(ADAPTERS, rejected)
            refused = False
        except PermissionError:
            refused = True
        require(refused, 'a non-root input-bound hash was accepted: ' + rejected)
    result = {
        'state': 'PASS', 'time_utc': utc_now(),
        'real_chain_tasks': [s['task'] for s in steps],
        'input_bound_root': steps[0]['parent_adapter_freeze'],
        'amended_adapter_freeze': runtime.file_identity(ADAPTERS / 'ADAPTER_FREEZE.json'),
        'amended_freeze_equals_chain_record': runtime.file_identity(ADAPTERS / 'ADAPTER_FREEZE.json') ==
                                              chain_record['amended_adapter_freeze'],
        'adapter_files_verified': len(current['files']),
        'archived_parent_files_verified': {s['task']: len(s['ancestor']['files']) for s in steps},
        'chain_refuses_intermediate_or_unknown_input_bound_hash': True,
        'design_frozen_files_verified': len(design['frozen_files']),
        'final_suite': {k: tests[k] for k in ('state', 'tests_run', 'failures', 'errors', 'skipped')},
        'final_suite_source_identities_still_match': suite_sources_match,
        'final_suite_covers_every_current_confx2_python_file': current_sources <= covered,
        'production_commands_run': [], 'host_state_opened': False, 'window_outcomes_read': False}
    require(result['real_chain_tasks'] == ['CONFX3', 'CONFX4'] and result['input_bound_root']['sha256'] == INPUT_BOUND_ROOT
            and result['amended_freeze_equals_chain_record'] and suite_sources_match
            and result['final_suite_covers_every_current_confx2_python_file'], 'final verification failed')
    runtime.atomic_json(HERE / 'FINAL_VERIFICATION.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step', choices=['after', 'freeze', 'chain', 'verify'])
    step = parser.parse_args().step
    value = {'after': after, 'freeze': freeze, 'chain': chain, 'verify': verify}[step]()
    print(json.dumps({'step': step, 'ok': True, 'keys': len(value)}))
