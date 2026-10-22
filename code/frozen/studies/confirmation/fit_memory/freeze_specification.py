"""CONFX7 freeze steps, run once in order after the records are final (template: CONFX6/freeze_amendment.py).

  after    AFTER_IDENTITIES.json for every changed/new file and bound CONFX7 record
  freeze   the amended CONFX2/ADAPTER_FREEZE.json (parent: archived CONFX6 freeze)
  chain    AMENDED_ADAPTER_CHAIN.json covering original -> CONFX3 -> CONFX4 -> CONFX5 -> CONFX6 -> CONFX7
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
CONFX5_FREEZE = '32110797f192cf0cf9759fe47de65d783b69a2a582f5e1cc47058344da989dbb'
CONFX6_FREEZE = '51c4f1b8278be8a1fcb152f632ccab5f4c6e0722ee24ba4130822c040498c77c'
PARENT = HERE / 'archive/pre_CONFX7/CONFX2/ADAPTER_FREEZE.json'
CHANGED = ['CONFX2/execution_adapter.py', 'CONFX2/runtime.py', 'CONFX2/tests/test_execution_amendment.py',
           'CONFX2/features_adapter.py', 'CONFX2/tests/test_confx5_lear.py', 'CONFX2/tests/test_execution_adapters.py',
           'HOST_RUN.md']
NEW = ['CONFX2/anonymous_memory.py', 'CONFX2/lear_parallel.py', 'CONFX2/tests/test_confx7_memory.py',
       'CONFX2/tests/test_confx7_panel_resume.py', 'CONFX2/tests/test_confx7_throughput.py']
# Addendum 4 (incremental notice-prefix encoding) is installed only on a switch; its files then join the freeze.
A4 = (ADAPTERS / 'notice_prefix_encoding.py').exists()
if A4:
    NEW += ['CONFX2/notice_prefix_encoding.py', 'CONFX2/tests/test_confx7_notice_prefix.py']
BOUND_RECORDS = ['SPEC.md', 'SPEC_FREEZE.json', 'SPEC_ADDENDUM_1_FULL_ROWS.md', 'SPEC_ADDENDUM_1_FREEZE.json',
                 'SPEC_ADDENDUM_2_RESUME_IDENTITY.md', 'SPEC_ADDENDUM_2_FREEZE.json', 'RESUME_DRIFT_DIAGNOSIS.json',
                 'diagnose_resume_drift.py', 'SPEC_ADDENDUM_3_THROUGHPUT.md', 'SPEC_ADDENDUM_3_FREEZE.json',
                 'measure_speed_a3.py', 'feasibility_24h_a3.py', 'SPEC_ADDENDUM_4_INCREMENTAL_NOTICE_ENCODING.md',
                 'SPEC_ADDENDUM_4_FREEZE.json', 'a4_prove.py', 'measurement_gate.py', 'SPEED_SMOKE_A3.json',
                 'BEFORE_IDENTITIES.json', 'AFTER_IDENTITIES.json', 'EXECUTION_DIFF.patch',
                 'EXECUTION_NOTE.md', 'UNCHANGED_CODE.json', 'FROZEN_DESIGN_VERIFICATION.json',
                 'T3_CONTINUITY.json', 'FINAL_TEST_RESULTS.json', 'FINAL_SYNTHETIC_TEST.log',
                 'features_completion_rule.py', 'measure_fit_memory.py', 'feasibility_24h.py', 'verify_code_scope.py',
                 'freeze_amendment.py', 'host_chain_CONFX7.sh', 't3_continuity.py', 'verify_frozen_design.py',
                 'install_confx7.py', 'update_host_run.py', 'make_scratch_roots.py', 'staging/STAGING_MANIFEST.json',
                 'A4_PROOF.json', 'A4_DECISION.json', 'a4_projection.py', 'a4_structural_inputs.py',
                 'staging_a4/STAGING_A4_MANIFEST.json']
# Addendum 4 section 5: MEMORY_MEASUREMENTS.json, FEASIBILITY_24H.json, SPEED_MEASUREMENTS_A3.json and FEASIBILITY_24H_A3.json
# are written after the features step and are not bound here; host_chain_CONFX7.sh requires them (measurement_gate.py).


def completion_rule():
    import importlib.util
    spec = importlib.util.spec_from_file_location('features_completion_rule', HERE / 'features_completion_rule.py')
    rule = importlib.util.module_from_spec(spec); spec.loader.exec_module(rule)
    return rule


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def after():
    records = [name for name in BOUND_RECORDS if name != 'AFTER_IDENTITIES.json']
    out = {rel: runtime.file_identity(CONF / rel) for rel in CHANGED + NEW}
    out.update({'CONFX7/' + name: runtime.file_identity(HERE / name) for name in records})
    runtime.atomic_json(HERE / 'AFTER_IDENTITIES.json', out, immutable=True)
    return out


def freeze():
    require(runtime.sha256(PARENT) == CONFX6_FREEZE, 'archived CONFX6 freeze drift')
    parent = runtime.read_json(PARENT)
    before = runtime.read_json(HERE / 'BEFORE_IDENTITIES.json')
    for key, item in before.items():
        require(runtime.sha256(item['archive_path']) == item['sha256'], 'archive drift ' + key)
    for key, item in runtime.read_json(HERE / 'AFTER_IDENTITIES.json').items():
        require(runtime.file_identity(item['path']) == item, 'after-identity drift ' + key)
    tests = runtime.read_json(HERE / 'FINAL_TEST_RESULTS.json')
    require(tests['state'] == 'PASS' and not tests['source_drift_during_tests'], 'final suite did not pass cleanly')
    for name in ('UNCHANGED_CODE.json', 'FROZEN_DESIGN_VERIFICATION.json'):
        require(runtime.read_json(HERE / name)['state'] == 'PASS', name + ' did not pass')
    unchanged = runtime.read_json(HERE / 'UNCHANGED_CODE.json')
    if A4:
        change = unchanged.get('feature_path_change') or {}
        require(unchanged['state'] == 'PASS' and unchanged.get('feature_path_identical_to_confx6_except_resume_comparison_and_addendum_4') is True
                and change.get('scope') == 'RESUME_COMPARISON_AND_INCREMENTAL_NOTICE_PREFIX_ENCODING'
                and change.get('reconstruction_equals_confx6') is True and change.get('addendum_4_hunks_undone') is True,
                'feature path: addendum-4 scope not proven')
        proof = runtime.read_json(HERE / 'A4_PROOF.json')
        require(proof.get('all_identical') is True, 'addendum-4 bit-identity proof did not pass')
    else:
        proven, why = completion_rule().feature_path_proven(unchanged)
        require(proven, 'feature path: ' + why)
    diagnosis = runtime.read_json(HERE / 'RESUME_DRIFT_DIAGNOSIS.json')['findings']
    require(diagnosis == {'notice_panel_build_deterministic': True, 'confx6_resume_check_false_mismatch': True,
                          'confx7_resume_check_reuses_identical_copy': True}, 'resume drift diagnosis')
    files = {}
    for rel in parent['files']:
        p = ADAPTERS / rel
        files[rel] = {'sha256': runtime.sha256(p), 'bytes': p.stat().st_size}
    for rel in NEW:
        p = CONF / rel
        files[str(p.relative_to(ADAPTERS))] = {'sha256': runtime.sha256(p), 'bytes': p.stat().st_size}
    for name in BOUND_RECORDS:
        files['../CONFX7/' + name] = {'sha256': runtime.sha256(HERE / name), 'bytes': (HERE / name).stat().st_size}
    identity = runtime.file_identity
    manifest = {
        'design_freeze': parent['design_freeze'], 'execution_rule': parent['execution_rule'],
        'execution_amendment': {
            'task': 'CONFX7',
            'reason': 'CONFX6 audit: the frozen per-job 2 GiB RSS stop is reached by the 384-dimensional arms (both primary '
                      'L_chen arms). Coordinator decision of 2026-10-02 (CONFX6 options 1 + 2 + 3, resource-only): anonymous '
                      'memory is measured, news/LEAR keep 2 GiB per fit, serial notice fits may use 6.6 GiB, wide news arms '
                      'lower the admitted concurrency, and the query matrix is built after the fit. Addendum 2 (coordinator '
                      'message of 2026-10-02 on the recurring notice resume drift): the resume check compared a read-back copy '
                      'with DataFrame.equals, which rejects identical notice content (label_available is an object column after '
                      'concatenating us and ns clocks); a stored panel copy is now reused iff its bytes equal the canonical '
                      'serialization of the current panel. Addendum 3 (author instruction for maximum throughput, relayed by the '
                      'coordinator): up to 7 single-thread news fits under an admission that reserves every running fit at its '
                      'projected anonymous peak, and LEAR daily jobs with their 12 window subjobs on 3 workers (BASE25 approach; '
                      'COMPUTE_PLAN allowance). Models, features, feature values, statistics, budget rules and drop order '
                      'unchanged; made before any CONF fit, prediction, seal or score.',
            'parent_adapter_freeze': identity(PARENT),
            'before_identities': identity(HERE / 'BEFORE_IDENTITIES.json'),
            'after_identities': identity(HERE / 'AFTER_IDENTITIES.json'),
            'execution_note': identity(HERE / 'EXECUTION_NOTE.md'),
            'spec': identity(HERE / 'SPEC.md'), 'spec_freeze': identity(HERE / 'SPEC_FREEZE.json'),
            'spec_addenda': [identity(HERE / name) for name in ('SPEC_ADDENDUM_1_FULL_ROWS.md', 'SPEC_ADDENDUM_1_FREEZE.json',
                                                                 'SPEC_ADDENDUM_2_RESUME_IDENTITY.md', 'SPEC_ADDENDUM_2_FREEZE.json',
                                                                 'SPEC_ADDENDUM_3_THROUGHPUT.md', 'SPEC_ADDENDUM_3_FREEZE.json')],
            'addendum_4': ({'installed': True, 'spec': identity(HERE / 'SPEC_ADDENDUM_4_INCREMENTAL_NOTICE_ENCODING.md'),
                            'freeze': identity(HERE / 'SPEC_ADDENDUM_4_FREEZE.json'), 'proof': identity(HERE / 'A4_PROOF.json'),
                            'decision': identity(HERE / 'A4_DECISION.json')} if A4 else
                           {'installed': False, 'spec': identity(HERE / 'SPEC_ADDENDUM_4_INCREMENTAL_NOTICE_ENCODING.md'),
                            'freeze': identity(HERE / 'SPEC_ADDENDUM_4_FREEZE.json')}),
            'resume_drift_diagnosis': identity(HERE / 'RESUME_DRIFT_DIAGNOSIS.json'),
            'unchanged_code': identity(HERE / 'UNCHANGED_CODE.json'),
            'frozen_design_verification': identity(HERE / 'FROZEN_DESIGN_VERIFICATION.json'),
            'measurement_records_after_features': ['MEMORY_MEASUREMENTS.json', 'FEASIBILITY_24H.json', 'SPEED_MEASUREMENTS_A3.json',
                                                   'FEASIBILITY_24H_A3.json'],
            'measurement_gate': identity(HERE / 'measurement_gate.py'),
            't3_continuity': identity(HERE / 'T3_CONTINUITY.json'),
            'execution_diff': identity(HERE / 'EXECUTION_DIFF.patch'),
            'no_statistical_design_or_feature_content_change': True,
            'execution_resource_rule': runtime.CONFX7_RESOURCE_RULE,
            'resume_identity_rule': runtime.CONFX7_RESUME_IDENTITY_RULE,
            'throughput_rule': runtime.CONFX7_THROUGHPUT_RULE,
            'compute_plan_memory_rule_amended_by_decision': 'coordinator CONFX7 decision, 2026-10-02 (resource-only)',
            'feature_path_identical_to_confx6': unchanged['feature_path_identical_to_confx6'],
            'feature_path_identical_to_confx6_except_resume_comparison':
                unchanged.get('feature_path_identical_to_confx6_except_resume_comparison'),
            'feature_path_change_scope': unchanged.get('feature_path_change_scope'),
            'features_completion_freezes_accepted': (['CONFX7 freeze'] if A4 else
                                                     ['CONFX7 freeze', CONFX6_FREEZE + ' (feature path proven identical except '
                                                      'the resume comparison, SPEC_ADDENDUM_2 section 3)']),
            'registered_chain': list(runtime.AMENDMENT_CHAIN)},
        'files': dict(sorted(files.items())),
        'input_only_feature_slices_read': False,
        'labels_and_keys_read': 'none; synthetic tests and file names only',
        'mutable_access_logs': parent['mutable_access_logs'],
        'parent_task_id': 'CONFX6', 'production_commands_run': [],
        'production_global_input_freeze_written': False,
        'state': 'ADAPTERS_FROZEN_SYNTHETICALLY_VERIFIED', 'task_id': 'CONFX7',
        'test_results': identity(HERE / 'FINAL_TEST_RESULTS.json'), 'time_utc': utc_now(),
        'window_outcomes_read': False, 'window_values_read': False}
    runtime.atomic_json(ADAPTERS / 'ADAPTER_FREEZE.json', manifest)
    return manifest


def chain():
    current, steps = runtime.adapter_amendment_chain(ADAPTERS, INPUT_BOUND_ROOT)
    require([s['task'] for s in steps] == ['CONFX3', 'CONFX4', 'CONFX5', 'CONFX6', 'CONFX7'], 'chain order')
    confx6_chain = runtime.read_json(CONF / 'CONFX6/AMENDED_ADAPTER_CHAIN.json')
    record = {
        'state': 'EXECUTION_AMENDMENT_CHAIN_FROZEN', 'time_utc': utc_now(),
        'registered_chain': ['input-bound original', 'CONFX3', 'CONFX4', 'CONFX5', 'CONFX6', 'CONFX7'],
        'input_bound_root': confx6_chain['input_bound_root'],
        'steps': confx6_chain['steps'][:3] + [
            {**confx6_chain['steps'][3], 'adapter_freeze': runtime.file_identity(PARENT),
             'chain_record': runtime.file_identity(CONF / 'CONFX6/AMENDED_ADAPTER_CHAIN.json')},
            {'task': 'CONFX7', 'adapter_freeze': runtime.file_identity(ADAPTERS / 'ADAPTER_FREEZE.json'),
             'parent_adapter_freeze': current['execution_amendment']['parent_adapter_freeze'],
             'execution_note': current['execution_amendment']['execution_note'],
             'before_identities': current['execution_amendment']['before_identities'],
             'measurement_gate': current['execution_amendment']['measurement_gate'],
             'unchanged_code': current['execution_amendment']['unchanged_code'],
             'test_results': current['test_results'],
             'declaration': {'no_statistical_design_or_feature_content_change': True,
                             'execution_resource_rule': runtime.CONFX7_RESOURCE_RULE,
                             'resume_identity_rule': runtime.CONFX7_RESUME_IDENTITY_RULE,
                             'throughput_rule': runtime.CONFX7_THROUGHPUT_RULE}}],
        'confx6_chain_record': runtime.file_identity(CONF / 'CONFX6/AMENDED_ADAPTER_CHAIN.json'),
        'amended_adapter_freeze': runtime.file_identity(ADAPTERS / 'ADAPTER_FREEZE.json'),
        'features_completion_rule': ('CONFX7/features_completion_rule.py: the CONFX7 freeze only (addendum 4 installed; the feature '
                                     'path differs from CONFX6 beyond the resume comparison)' if A4 else
                                     'CONFX7/features_completion_rule.py: the CONFX7 freeze, or the CONFX6 freeze ' + CONFX6_FREEZE +
                                     ' with UNCHANGED_CODE.json proving the feature path identical to CONFX6 or identical except '
                                     'the resume comparison (reconstruction; SPEC_ADDENDUM_2 section 3)'),
        'runtime_verifier': 'CONFX2/runtime.py adapter_amendment_chain (used by verify_adapter_ancestor and validate_permit)',
        'original_input_freeze_and_authorization_retained': True,
        'primary_decision_rule_change': False, 'frozen_compute_plan_memory_rule_amended_by_decision': True}
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
    for label, rejected in (('unknown', 'f' * 64), ('intermediate CONFX3', CONFX3_FREEZE), ('intermediate CONFX4', CONFX4_FREEZE),
                            ('intermediate CONFX5', CONFX5_FREEZE), ('intermediate CONFX6', CONFX6_FREEZE)):
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
    rule = completion_rule()
    unchanged = runtime.read_json(HERE / 'UNCHANGED_CODE.json')
    checks = {label: rule.verdict({'adapter_freeze_sha256': value}, chain_record, unchanged)[0]
              for label, value in (('confx7_bound', chain_record['amended_adapter_freeze']['sha256']),
                                   ('confx6_bound', CONFX6_FREEZE), ('confx5_bound', CONFX5_FREEZE), ('unknown', 'f' * 64))}
    result['features_completion_rule_checks'] = checks
    require(checks == {'confx7_bound': True, 'confx6_bound': not A4, 'confx5_bound': False, 'unknown': False}, 'completion rule')
    require(result['real_chain_tasks'] == ['CONFX3', 'CONFX4', 'CONFX5', 'CONFX6', 'CONFX7'] and result['input_bound_root']['sha256'] == INPUT_BOUND_ROOT
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
