'Validate scoring callback sources and save their hashes.'
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import score_callback as C


def package_files(root):
    files = []
    for p in sorted(root.iterdir()):
        if p.name in {'CODE_FREEZE.json', 'production_callback'}:
            continue
        C.require(not p.is_symlink(), 'Symlink in callback package')
        if p.is_dir():
            C.require(p.name in {'tests', 'validation'}, 'Unexpected package directory')
            if p.name == 'tests':
                for child in sorted(p.iterdir()):
                    C.require(child.is_file() and not child.is_symlink() and child.suffix == '.py', 'Unexpected test entry')
                    files.append(child)
            else:
                for run in sorted(p.iterdir()):
                    C.require(run.is_dir() and not run.is_symlink(), 'Exact validation directory required')
                    for child in sorted(run.iterdir()):
                        C.require(child.is_file() and not child.is_symlink() and child.suffix in {'.json', '.txt', '.md'},
                                  'Validation contains non-metadata entry')
                        files.append(child)
        else:
            C.require(p.is_file() and p.suffix in {'.py', '.json', '.md', '.txt'}, 'Non-metadata package file')
            files.append(p)
    return files


def tested_files(root):

    inputs = ['score_callback.py', 'freeze_scoring_callback.py', 'run_tests.py', 'tests/test_callback.py',
              'DEPENDENCY_PINS.json', 'SOURCE_PLAN.template.json', 'REVIEW_ACCEPTANCE.template.json',
              'RUNBOOK_FRAGMENT.sh.txt', 'SYNTHETIC_SPEC.md', 'SCORECB2_VALIDATION_SPEC.md',
              'SCORECB3_VALIDATION_SPEC.md', 'SCORECB4_VALIDATION_SPEC.md', 'SCORECB5_VALIDATION_SPEC.md',
              'SCORECB5_PRODUCER_INVENTORY.json', 'SCORECB5B_RECHECK.json',
              'SCORECB5A_VALIDATION_SPEC.md', 'SCORECB5A_DIRECTORY_AUDIT.json', 'SCORECB5A_G39_CONTRACT.json',
              'SCORECB5A2_VALIDATION_SPEC.md', 'SCORECB5A3_VALIDATION_SPEC.md', 'SCORECB5A4_VALIDATION_SPEC.md',
              'SCORECB5A4_REVIEWER_EVASIONS.json', 'SCORECB5A5_VALIDATION_SPEC.md',
              'SCORECB5A5_SOURCE_ADDENDUM1.md']
    files = [root / rel for rel in inputs]
    C.require(all(p.is_file() and not p.is_symlink() for p in files), 'Tested executable/input inventory incomplete')
    C.require({p for p in package_files(root) if p.suffix == '.py'} == {p for p in files if p.suffix == '.py'},
              'Untested Python source in package')
    return sorted(files)


def tested_hashes(root):
    return {str(p.relative_to(root)): C.identity(p)['sha256'] for p in tested_files(root)}


def candidate(test_receipt=None):
    root = C.PACKAGE
    C.require(not os.path.lexists(root / 'CODE_FREEZE.json'), 'Existing freeze refused')
    plan = C.validate_plan(root / 'SOURCE_PLAN.json')
    C.require(not os.path.lexists(plan['output_dir']), 'Callback cannot already be armed at freeze')
    receipt_path = C.exact_path(test_receipt or root / 'TEST_RESULTS.json')
    validation_receipt = (receipt_path.parent.parent == root / 'validation' and receipt_path.name == 'TEST_RESULTS.json')
    C.require((receipt_path.parent == root and receipt_path.name.startswith('TEST_RESULTS') and receipt_path.suffix == '.json')
              or validation_receipt,
              'Exact passing receipt must be inside scoring_callback')
    tests = C.read(receipt_path)
    C.require(tests.get('schema') == 'SCORECB_SYNTHETIC_TEST_RECEIPT_V1' and tests.get('state') == 'PASS'
              and tests.get('suite_runs') == 1 and tests.get('tests_run', 0) > 0
              and all(tests.get(k) == 0 for k in ('failures', 'errors', 'skipped')),
              'One complete passing synthetic suite required')
    C.require(tests.get('source_sha256') == tested_hashes(root), 'Tested source identity drift')
    resource = tests['resources']
    observed_min = resource.get('minimum_observed_nice', resource['nice'])
    observed_max = resource.get('maximum_observed_nice', resource['nice'])
    priority_ok = resource['nice'] == 20 and observed_min == observed_max == 20
    if not priority_ok:
        refusal = resource.get('nice_refusal')
        C.require(tests.get('task') in {'SCORECB5A2', 'SCORECB5A3', 'SCORECB5A4', 'SCORECB5A5'} and isinstance(refusal, dict)
                  and refusal.get('authorization') == tests['task'] + '_USER_AUTHORIZED_INHERITED_IF_NICE_REFUSED'
                  and refusal.get('requested_nice') == 20
                  and type(refusal.get('inherited_nice')) is int
                  and -20 <= refusal['inherited_nice'] < 20
                  and refusal['inherited_nice'] <= observed_min <= resource['nice'] <= observed_max <= 20,
                  'Reviewed priority refusal witness required')
        warning = C.metadata_path(refusal['launcher_warning']['path'])
        C.require(warning.parent == root and warning.match('LAUNCHER_WARNING_' + tests['task'] + '*.txt'),
                  'Exact priority refusal warning required')
        C.checked(refusal['launcher_warning'])
        C.require('nice: setpriority: Operation not permitted' in warning.read_text(),
                  'Priority request refusal must be recorded')
        priority_ok = True
    C.require(priority_ok and resource['test_processes'] == 1
              and resource['minimum_memory_free_percent'] >= 25
              and resource['maximum_scratch_bytes'] < 1_000_000_000
              and resource['production_payload_reads'] == 0, 'Synthetic resource/read gates required')
    acceptance = C.read(root / 'REVIEW_ACCEPTANCE.json')
    selected_review = acceptance.get('review')
    C.require(isinstance(selected_review, dict) and set(selected_review) == {'path', 'bytes', 'sha256'},
              'Actual reviewed source acceptance requires exact review identity')
    review_path = C.metadata_path(selected_review['path'])
    C.require(review_path.parent == root and review_path.match('REVIEW*_source.md'),
              'Exact independent review must be a scoring_callback review file')
    C.checked(selected_review)
    review = C.identity(review_path)
    C.require(acceptance.get('state') == 'SCORECB_REVIEW_ACCEPTED' and acceptance.get('source_verified') is True
              and acceptance.get('recorded_by') and acceptance.get('review') == review
              and acceptance.get('test_receipt') == C.identity(receipt_path)
              and acceptance.get('plan') == C.identity(root / 'SOURCE_PLAN.json')
              and acceptance.get('source_sha256') == tested_hashes(root), 'Actual reviewed source acceptance required')
    C.require(C.utc(acceptance['recorded_utc']) <= C.now(), 'Review acceptance cannot be in the future')
    pins = C.read(root / 'DEPENDENCY_PINS.json')
    for item in pins['files']:
        C.checked(item)
    commitment_paths = set(pins.get('t5_commitment_only_paths', []))
    C.require(commitment_paths == {str(C.PROJECT / 'studies/confirmation/execution/seal_score.py')},
              'Exact source commitment exception required')
    files = [C.identity(p) for p in package_files(root)]
    return dict(schema='SCORECB_CODE_FREEZE_V1', state='SCORECB_FROZEN_FOR_SOURCE',
                frozen_utc=dt.datetime.now(dt.timezone.utc).isoformat(), files=files,
                dependencies=[i for i in pins['files'] if i['path'] not in commitment_paths],
                source_commitments=[dict(source_path=i['path'], source_sha256=i['sha256'], source_bytes=i['bytes'])
                                    for i in pins['files'] if i['path'] in commitment_paths], review=review,
                review_acceptance=C.identity(root / 'REVIEW_ACCEPTANCE.json'),
                plan=C.identity(root / 'SOURCE_PLAN.json'),
                test_receipt=C.identity(receipt_path), production_payload_reads=0,
                production_commands_run=[], scoring_argv_unchanged=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--freeze', action='store_true')
    p.add_argument('--test-receipt', type=Path)
    args = p.parse_args()
    C.require(args.freeze and os.environ.get('SCORECB_SOURCE_FREEZE') == 'YES', 'Future source freeze opt-in required')
    value = candidate(args.test_receipt)
    C.publish(C.PACKAGE / 'CODE_FREEZE.json', value)
    print(json.dumps({'state': value['state'], 'path': str(C.PACKAGE / 'CODE_FREEZE.json')}))


if __name__ == '__main__':
    main()
