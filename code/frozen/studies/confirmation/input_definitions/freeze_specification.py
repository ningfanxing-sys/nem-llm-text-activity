"""CONFX5 freeze steps, run once in order after the records are final (template: CONFX4/freeze_amendment.py).

  after    AFTER_IDENTITIES.json for every changed/new file and bound CONFX5 record
  freeze   the amended CONFX2/ADAPTER_FREEZE.json (parent: archived CONFX4 freeze)
  chain    AMENDED_ADAPTER_CHAIN.json covering original -> CONFX3 -> CONFX4 -> CONFX5
  verify   FINAL_VERIFICATION.json: the real chain, adapters, design, suite sources, refusals

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
CONFX4_FREEZE = 'a42e82b77f1608ccc572eebf52360763d73f705d11fc8fc0f3ee749fea1dbd1c'
PARENT = HERE / 'archive/pre_CONFX5/CONFX2/ADAPTER_FREEZE.json'
CHANGED = ['CONFX2/runtime.py', 'CONFX2/features_adapter.py', 'CONFX2/execution_adapter.py', 'CONFX2/seal_score.py',
           'CONFX2/report_adapter.py', 'CONFX2/tests/test_execution_amendment.py', 'CONFX2/tests/test_features_adapter.py',
           'CONFX2/tests/test_execution_adapters.py', 'CONFX2/tests/test_nrx_mw_literal.py', 'HOST_RUN.md']
NEW = ['CONFX2/a1_scoring.py', 'CONFX2/lear_adapter_confx5.py', 'CONFX2/tests/test_confx5_a1.py',
       'CONFX2/tests/test_confx5_restart.py', 'CONFX2/tests/test_confx5_lear.py']
BOUND_RECORDS = ['SPEC.md', 'SPEC_FREEZE.json', 'SPEC_ADDENDUM_1_LEAR.md', 'SPEC_ADDENDUM_1_FREEZE.json',
                 'SPEC_ADDENDUM_2_LEAR_TEMPLATE.md', 'SPEC_ADDENDUM_2_FREEZE.json', 'BEFORE_IDENTITIES.json',
                 'AFTER_IDENTITIES.json', 'EXECUTION_DIFF.patch', 'EXECUTION_NOTE.md', 'UNCHANGED_CODE.json',
                 'FROZEN_DESIGN_VERIFICATION.json', 'FROZEN_READINGS_EQUIVALENCE.json', 'PRODUCTION_FAILED_ATTEMPT.json',
                 'RESTART_PROCEDURE.json', 'PLAN_ACCOUNTING.json', 'FINAL_TEST_RESULTS.json', 'FINAL_SYNTHETIC_TEST.log',
                 'verify_frozen_readings.py', 'verify_code_scope.py', 'freeze_amendment.py', 'move_out_notice_files.py']


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def after():
    records = [name for name in BOUND_RECORDS if name != 'AFTER_IDENTITIES.json']
    out = {rel: runtime.file_identity(CONF / rel) for rel in CHANGED + NEW}
    out.update({'CONFX5/' + name: runtime.file_identity(HERE / name) for name in records})
    runtime.atomic_json(HERE / 'AFTER_IDENTITIES.json', out, immutable=True)
    return out


def freeze():
    require(runtime.sha256(PARENT) == CONFX4_FREEZE, 'archived CONFX4 freeze drift')
    parent = runtime.read_json(PARENT)
    before = runtime.read_json(HERE / 'BEFORE_IDENTITIES.json')
    for key, item in before.items():
        require(runtime.sha256(item['archive_path']) == item['sha256'], 'archive drift ' + key)
    for key, item in runtime.read_json(HERE / 'AFTER_IDENTITIES.json').items():
        require(runtime.file_identity(item['path']) == item, 'after-identity drift ' + key)
    tests = runtime.read_json(HERE / 'FINAL_TEST_RESULTS.json')
    require(tests['state'] == 'PASS' and not tests['source_drift_during_tests'], 'final suite did not pass cleanly')
    for name in ('UNCHANGED_CODE.json', 'FROZEN_DESIGN_VERIFICATION.json', 'FROZEN_READINGS_EQUIVALENCE.json'):
        require(runtime.read_json(HERE / name)['state'] == 'PASS', name + ' did not pass')
    files = {}
    for rel in parent['files']:
        p = ADAPTERS / rel
        files[rel] = {'sha256': runtime.sha256(p), 'bytes': p.stat().st_size}
    for rel in NEW:
        p = CONF / rel
        files[str(p.relative_to(ADAPTERS))] = {'sha256': runtime.sha256(p), 'bytes': p.stat().st_size}
    for name in BOUND_RECORDS:
        files['../CONFX5/' + name] = {'sha256': runtime.sha256(HERE / name), 'bytes': (HERE / name).stat().st_size}
    identity = runtime.file_identity
    manifest = {
        'design_freeze': parent['design_freeze'], 'execution_rule': parent['execution_rule'],
        'execution_amendment': {
            'task': 'CONFX5',
            'reason': 'Binding pre-score addendum CONF-A1 (CONF/A1/DECISIONS_A1_zh.md): secondary arms W2_D and NPM, '
                      'declared sensitivities and reporting rules, plus the LEAR template convergence rule; made '
                      'before any CONF fit, prediction, seal or score, after the 2026-10-02 failed features attempt',
            'parent_adapter_freeze': identity(PARENT),
            'before_identities': identity(HERE / 'BEFORE_IDENTITIES.json'),
            'after_identities': identity(HERE / 'AFTER_IDENTITIES.json'),
            'execution_note': identity(HERE / 'EXECUTION_NOTE.md'),
            'spec': identity(HERE / 'SPEC.md'), 'spec_freeze': identity(HERE / 'SPEC_FREEZE.json'),
            'spec_addenda': [identity(HERE / name) for name in ('SPEC_ADDENDUM_1_LEAR.md', 'SPEC_ADDENDUM_1_FREEZE.json',
                                                                'SPEC_ADDENDUM_2_LEAR_TEMPLATE.md', 'SPEC_ADDENDUM_2_FREEZE.json')],
            'binding_decisions': identity(CONF / 'A1/DECISIONS_A1_zh.md'),
            'unchanged_code': identity(HERE / 'UNCHANGED_CODE.json'),
            'frozen_design_verification': identity(HERE / 'FROZEN_DESIGN_VERIFICATION.json'),
            'frozen_readings_equivalence': identity(HERE / 'FROZEN_READINGS_EQUIVALENCE.json'),
            'production_failed_attempt': identity(HERE / 'PRODUCTION_FAILED_ATTEMPT.json'),
            'restart_procedure': identity(HERE / 'RESTART_PROCEDURE.json'),
            'plan_accounting': identity(HERE / 'PLAN_ACCOUNTING.json'),
            'execution_diff': identity(HERE / 'EXECUTION_DIFF.patch'),
            'pre_score_addendum': 'CONF-A1',
            runtime.CONFX5_UNCHANGED: True,
            'primary_decision_rule_change': False,
            'no_statistical_design_or_inference_rule_change': False,
            'no_statistical_design_or_feature_content_change': False,
            'feature_content_change': runtime.CONFX5_FEATURE_CONTENT_CHANGE,
            'added_secondary_arms': runtime.CONFX5_ADDED_SECONDARY_ARMS,
            'lear_convergence_rule': 'TEMPLATE_ALL_CONVERGENCE_WARNINGS_RECORDED_NOT_FATAL (LEAR_SPEC nonconvergence sentence amended)',
            'registered_chain': list(runtime.AMENDMENT_CHAIN)},
        'files': dict(sorted(files.items())),
        'input_only_feature_slices_read': False,
        'labels_and_keys_read': 'none; synthetic tests and file names only',
        'mutable_access_logs': parent['mutable_access_logs'],
        'parent_task_id': 'CONFX4', 'production_commands_run': [],
        'production_global_input_freeze_written': False,
        'state': 'ADAPTERS_FROZEN_SYNTHETICALLY_VERIFIED', 'task_id': 'CONFX5',
        'test_results': identity(HERE / 'FINAL_TEST_RESULTS.json'), 'time_utc': utc_now(),
        'window_outcomes_read': False, 'window_values_read': False}
    runtime.atomic_json(ADAPTERS / 'ADAPTER_FREEZE.json', manifest)
    return manifest


def chain():
    current, steps = runtime.adapter_amendment_chain(ADAPTERS, INPUT_BOUND_ROOT)
    require([s['task'] for s in steps] == ['CONFX3', 'CONFX4', 'CONFX5'], 'chain order')
    confx4_chain = runtime.read_json(CONF / 'CONFX4/AMENDED_ADAPTER_CHAIN.json')
    record = {
        'state': 'EXECUTION_AMENDMENT_CHAIN_FROZEN', 'time_utc': utc_now(),
        'registered_chain': ['input-bound original', 'CONFX3', 'CONFX4', 'CONFX5'],
        'input_bound_root': confx4_chain['input_bound_root'],
        'steps': [confx4_chain['steps'][0],
            {**confx4_chain['steps'][1], 'adapter_freeze': runtime.file_identity(PARENT),
             'chain_record': runtime.file_identity(CONF / 'CONFX4/AMENDED_ADAPTER_CHAIN.json')},
            {'task': 'CONFX5', 'adapter_freeze': runtime.file_identity(ADAPTERS / 'ADAPTER_FREEZE.json'),
             'parent_adapter_freeze': current['execution_amendment']['parent_adapter_freeze'],
             'execution_note': current['execution_amendment']['execution_note'],
             'before_identities': current['execution_amendment']['before_identities'],
             'frozen_readings_equivalence': current['execution_amendment']['frozen_readings_equivalence'],
             'test_results': current['test_results'],
             'declaration': {'pre_score_addendum': 'CONF-A1', runtime.CONFX5_UNCHANGED: True,
                             'primary_decision_rule_change': False,
                             'feature_content_change': runtime.CONFX5_FEATURE_CONTENT_CHANGE,
                             'added_secondary_arms': runtime.CONFX5_ADDED_SECONDARY_ARMS}}],
        'confx4_chain_record': runtime.file_identity(CONF / 'CONFX4/AMENDED_ADAPTER_CHAIN.json'),
        'amended_adapter_freeze': runtime.file_identity(ADAPTERS / 'ADAPTER_FREEZE.json'),
        'runtime_verifier': 'CONFX2/runtime.py adapter_amendment_chain (used by verify_adapter_ancestor and validate_permit)',
        'original_input_freeze_and_authorization_retained': True,
        'primary_decision_rule_change': False}
    runtime.atomic_json(HERE / 'AMENDED_ADAPTER_CHAIN.json', record, immutable=True)
    return record


def verify():
    current, steps = runtime.adapter_amendment_chain(ADAPTERS, INPUT_BOUND_ROOT)
    design = runtime.verify_design()
    chain_record = runtime.read_json(HERE / 'AMENDED_ADAPTER_CHAIN.json')
    tests = runtime.read_json(HERE / 'FINAL_TEST_RESULTS.json')
    source_items = tests['test_files'] + tests['adapter_source_files']
    suite_sources_match = all(runtime.file_identity(item['path'])['sha256'] == item['sha256'] for item in source_items)
    covered = {Path(item['path']).resolve() for item in source_items}
    current_sources = {p.resolve() for p in [*ADAPTERS.glob('*.py'), *(ADAPTERS / 'tests').glob('*.py')]}
    refusals = {}
    for label, rejected in (('unknown', 'f' * 64), ('intermediate CONFX3', CONFX3_FREEZE), ('intermediate CONFX4', CONFX4_FREEZE)):
        try:
            runtime.verify_adapter_ancestor(ADAPTERS, rejected)
            refusals[label] = False
        except PermissionError as exc:
            refusals[label] = str(exc)
    result = {
        'state': 'PASS', 'time_utc': utc_now(),
        'real_chain_tasks': [s['task'] for s in steps],
        'input_bound_root': steps[0]['parent_adapter_freeze'],
        'amended_adapter_freeze': runtime.file_identity(ADAPTERS / 'ADAPTER_FREEZE.json'),
        'amended_freeze_equals_chain_record': runtime.file_identity(ADAPTERS / 'ADAPTER_FREEZE.json') ==
                                              chain_record['amended_adapter_freeze'],
        'adapter_files_verified': len(current['files']),
        'archived_parent_files_verified': {s['task']: len(s['ancestor']['files']) for s in steps},
        'chain_refusals': refusals,
        'design_frozen_files_verified': len(design['frozen_files']),
        'final_suite': {k: tests[k] for k in ('state', 'tests_run', 'failures', 'errors', 'skipped')},
        'final_suite_source_identities_still_match': suite_sources_match,
        'final_suite_covers_every_current_confx2_python_file': current_sources <= covered,
        'production_commands_run': [], 'host_state_opened': False, 'window_outcomes_read': False}
    require(result['real_chain_tasks'] == ['CONFX3', 'CONFX4', 'CONFX5'] and result['input_bound_root']['sha256'] == INPUT_BOUND_ROOT
            and result['amended_freeze_equals_chain_record'] and suite_sources_match and all(refusals.values())
            and result['final_suite_covers_every_current_confx2_python_file'], 'final verification failed')
    runtime.atomic_json(HERE / 'FINAL_VERIFICATION.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step', choices=['after', 'freeze', 'chain', 'verify'])
    step = parser.parse_args().step
    value = {'after': after, 'freeze': freeze, 'chain': chain, 'verify': verify}[step]()
    print(json.dumps({'step': step, 'ok': True, 'keys': len(value)}))
