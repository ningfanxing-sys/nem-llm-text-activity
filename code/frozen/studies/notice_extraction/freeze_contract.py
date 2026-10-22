'Save the notice extraction source hashes before sample extraction.'
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLI = Path('openai-cli')
FILES = (
    'CONTRACT.md', 'PILOT_PLAN.md', 'FULL_PLAN.md', 'REPORT.md',
    'prompt.txt', 'schema_full.json', 'schema_response_format.json',
    'prepare_notice_scope.py', 'validate_notice_label.py', 'run_notice_extraction.py',
    'freeze_contract.py', 'test_prepare_notice_scope.py',
    'test_validate_notice_label.py', 'test_run_notice_extraction.py',
    'scope.jsonl', 'pilot_ids.json', 'PILOT_SELECTION.json',
    'EXCLUDED_HUMAN60_IDS.json', 'SOURCE_VERSIONS.jsonl',
    'SOURCE_VERSION_CONFLICTS.json', 'PREPARATION_SPEC.json',
    'PREPARATION_FREEZE.json', 'SCOPE_RECEIPT.json', 'BUILD_CHECKS.json',
    'BUILD_TEST.log',
)


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    freeze_path = HERE / 'CONTRACT_FREEZE.json'
    if args.check:
        from run_notice_extraction import verify_freeze
        from prepare_notice_scope import load_scope
        freeze = verify_freeze()
        scope = load_scope(verify_sources=True)
        print(json.dumps({'state': 'PASS_FROZEN_BUILD_INTEGRITY',
                          'notices': len(scope),
                          'contract_sha256': freeze['contract_sha256'],
                          'contract_freeze_sha256': sha_file(freeze_path)}))
        return
    if freeze_path.exists():
        raise SystemExit('Contract already frozen. Use --check; never overwrite a pilot contract.')
    if any((HERE / name).exists() for name in
           ('extraction_ledger.jsonl', 'PILOT_RECEIPT.json', 'PILOT_GATE.json', 'labels.parquet')):
        raise SystemExit('Extraction state exists; cannot freeze this as a fresh pre-pilot build.')
    checks = json.loads((HERE / 'BUILD_CHECKS.json').read_text())
    if checks.get('state') != 'PASS_BUILD_ONLY_NO_EXTRACTION' or checks.get('model_calls') != 0:
        raise SystemExit('A passing build-only check receipt is required before freezing.')
    for name, expected in checks['tested_files_sha256'].items():
        if sha_file(HERE / name) != expected:
            raise SystemExit(f'Tested file changed after verification: {name}')
    from prepare_notice_scope import load_scope
    scope = load_scope(verify_sources=True)
    pilot = json.loads((HERE / 'pilot_ids.json').read_text())
    if len(pilot) != 20 or len(set(pilot)) != 20:
        raise SystemExit('Pilot selection must contain 20 unique IDs.')
    freeze = {
        'state': 'FROZEN_BEFORE_HOST_PILOT', 'contract_version': 1,
        'frozen_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'model_requested': 'gpt-6-luna', 'model_reasoning_effort': 'medium',
        'cli_path': str(CLI), 'cli_version': checks['cli_version'],
        'cli_sha256': sha_file(CLI),
        'contract_sha256': sha_file(HERE / 'CONTRACT.md'),
        'scope_freeze_sha256': sha_file(HERE / 'SCOPE_RECEIPT.json'),
        'files_sha256': {name: sha_file(HERE / name) for name in FILES},
        'expected_unique_notices': len(scope), 'pilot_notices': len(pilot),
        'transport_retries_total_per_notice': 3,
        'validation_retries_total_per_notice': 1,
        'maximum_requests_per_notice': 5,
        'full_worker_policy': 'start16; first200 full requests completed capacity-free permits24; capacity halves global per-request ceiling',
        'model_calls_during_build': 0,
        'pilot_gate_state': 'NOT_RUN_REQUIRES_SEPARATE_GRADING',
    }
    with freeze_path.open('x', encoding='utf-8') as handle:
        json.dump(freeze, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write('\n')
        handle.flush()
        import os
        os.fsync(handle.fileno())
    print(json.dumps({'state': freeze['state'], 'notices': len(scope),
                      'contract_sha256': freeze['contract_sha256'],
                      'contract_freeze_sha256': sha_file(freeze_path)}))


if __name__ == '__main__':
    main()
