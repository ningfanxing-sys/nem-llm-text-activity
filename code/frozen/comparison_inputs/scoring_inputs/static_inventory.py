'List source files and their saved hashes.'
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import subprocess

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
R2 = 'comparison_inputs/'
SOURCE = 'studies/confirmation/comparison_specifications/'
T4X = 'studies/confirmation/TIMESTAMPS/T4X/'


def read(relative):
    p = ROOT / relative
    if p.is_symlink() or not p.resolve().is_relative_to(ROOT.resolve()):
        raise PermissionError('Unsafe source path: ' + relative)
    parts = Path(relative).parts
    if any(x.lower() in {'host_state', 'seals', 'scores', 'predictions', 'outcomes'} for x in parts):
        raise PermissionError('Payload directory refused')
    if relative.startswith('tables/table_renderer/notice_constraints/'):
        raise PermissionError('Live F12 refused')
    return p.read_bytes()


def sha(b):
    return hashlib.sha256(b).hexdigest()


def identity(relative, expected=None):
    b = read(relative)
    result = dict(path=relative, absolute_path=str(ROOT / relative), bytes=len(b), sha256=sha(b))
    if expected is not None:
        result.update(expected_sha256=expected, matches_expected=sha(b) == expected)
        if not result['matches_expected']:
            raise PermissionError('SET FIRST source drift: ' + relative)
    return result


def census(relative):
    tree = ast.parse(read(relative))
    definitions = []
    def visit(node, prefix=''):
        for child in ast.iter_child_nodes(node):
            qualified = prefix
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualified = prefix + child.name
                item = dict(name=qualified, kind=type(child).__name__, line_start=child.lineno,
                            line_end=child.end_lineno,
                            ast_sha256=sha(ast.dump(child, include_attributes=False).encode()),
                            loaded_names=sorted({x.id for x in ast.walk(child)
                                                 if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load)}),
                            call_targets=sorted({ast.unparse(x.func) for x in ast.walk(child)
                                                 if isinstance(x, ast.Call)}))
                if hasattr(child, 'args'):
                    item['signature'] = '(' + ast.unparse(child.args) + ')'
                definitions.append(item)
                qualified += '.'
            visit(child, qualified)
    visit(tree)
    imports = [dict(line=x.lineno, statement=ast.unparse(x)) for x in ast.walk(tree)
               if isinstance(x, (ast.Import, ast.ImportFrom))]
    inherited = [dict(line=x.lineno, expression=ast.unparse(x)) for x in ast.walk(tree)
                 if isinstance(x, ast.Call) and isinstance(x.func, ast.Name)
                 and x.func.id in {'inherit', 'ast_functions'}]
    return dict(definitions=definitions, imports=imports, finite_inheritance_calls=inherited)


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n')


def main():
    if os.environ.get('SCORING_PHASE', 'prepare') != 'prepare':
        raise PermissionError('This static source_delivery inventory tool is prepare-only')
    contract = json.loads(read(R2 + 'APPROVED_NEWS_SOURCE.json'))
    parent = json.loads(read(R2 + 'code/PARENT_PINS.json'))
    audit = json.loads(read('paper_plan/nof12_path_20261009/INVENTORY.json'))
    old = json.loads(read(R2 + 'INVENTORY.json'))
    expected = dict(contract['source_pins'])
    expected.update(contract['original_ap27'])
    expected.update(contract['acceptance_sources'])
    expected.update({R2 + 'APPROVED_NEWS_SOURCE.json': audit['r2']['approved_contract_identity']['sha256']})

    caller_sources = [
        'studies/confirmation/execution/cli.py',
        'studies/confirmation/execution/runtime.py',
        'studies/confirmation/execution/execution_adapter.py',
        'studies/confirmation/execution/report_adapter.py',
        'studies/confirmation/code/guard.py',
        'studies/confirmation/robustness_tests/code/robustness_comparisons.py',
        'studies/batch_estimation/batch_checks/consumer_roots.py',
        'studies/batch_estimation/scoring_callback/score_callback.py',
        'studies/inference/DEPENDENCY_PINS.json',
    ]
    for path in caller_sources:
        snap = audit['source_snapshots'].get(path)
        pin = contract['acceptance_public_sources'].get(path)
        if snap is None and pin is None and path.endswith('/runtime.py'):

            continue
        expected[path] = pin or snap['sha256']
    docs = [
        'paper_plan/task_specs/COMMON_RULES.md',
        'paper_plan/task_specs/TASK_SCORING_PCIMPL2.md',
        SOURCE + 'SOURCE_DECISION_SCORING_20261009.md',
        SOURCE + 'SOURCE_DECISION_DEC13_20261008.md',
        SOURCE + 'AUTHOR_DECISION_RULES_20261009.md',
        SOURCE + 'AUTHOR_DECISION_PCPRIMARY_20261008.md',
        SOURCE + 'SCORING_CONTENT/SCORING_FINAL.md',
        'paper_plan/nof12_path_20261009/PLAN_source.md',
        'paper_plan/nof12_path_20261009/INVENTORY.json',
        'paper_plan/nof12_path_20261009/REVIEW_SCORING_source.md',
        R2 + 'ADOPTION_source.md', R2 + 'REVIEW_PCREVC2_source.md',
        R2 + 'REVIEW_PCREVC3_source.md', R2 + 'REVIEW_PCREVC4_source.md',
        R2 + 'INVENTORY.json', R2 + 'F12_PATCH.diff',
        T4X + 'MANIFEST_T4X.sha256', T4X + 'T4X_RESULT.json',
        T4X + 'T4X_freetsa.tsr', T4X + 'T4X_digicert.tsr',
        T4X + 'T4X_freetsa_reply.txt', T4X + 'T4X_digicert_reply.txt',
        'studies/confirmation/TIMESTAMPS/certs/freetsa_cacert.pem',
        'studies/confirmation/TIMESTAMPS/certs/freetsa_tsa.crt',
        'studies/confirmation/TIMESTAMPS/certs/macos_system_roots.pem',
    ]
    manifest = read(T4X + 'MANIFEST_T4X.sha256')
    rows = {}
    for line in manifest.decode().splitlines():
        if not line.startswith('#'):
            digest, count, path = line.split(maxsplit=2)
            rows['studies/' + path] = (digest, int(count))
    adopted_paths = [SOURCE + 'SOURCE_DECISION_SCORING_20261009.md',
                     SOURCE + 'AUTHOR_DECISION_RULES_20261009.md',
                     SOURCE + 'AUTHOR_DECISION_PCPRIMARY_20261008.md',
                     SOURCE + 'SOURCE_DECISION_DEC13_20261008.md',
                     SOURCE + 'SCORING_CONTENT/SCORING_FINAL.md']
    adoption_rows = []
    for path in adopted_paths:
        digest, count = rows[path]
        item = identity(path, digest)
        assert item['bytes'] == count
        expected[path] = digest
        adoption_rows.append(item)
    result = json.loads(read(T4X + 'T4X_RESULT.json'))
    assert result['manifest_sha256'] == sha(manifest)
    assert all(v['verified'] is True for v in result['tsa'].values())
    for name in ('T4X_FREETSA_OFFLINE_VERIFY.log', 'T4X_DIGICERT_OFFLINE_VERIFY.log'):
        assert 'Verification: OK' in (OUT / name).read_text()
    with (ROOT / 'paper_plan/task_specs/logs/PCIMPL2_r2.log').open() as f:
        header = ''.join(next(f) for _ in range(12))
    assert 'session id: 01a11ad9-18b2-7541-baff-232eaae63b81' in header
    save('ADOPTION_EVIDENCE.json', dict(
        schema='PCIMPL2_SCORING_PREPARE_ADOPTION_EVIDENCE_V1',
        adoption_utc='2026-10-08T17:34:22Z',
        source_session='68d8521f-36bc-4a03-bee1-ff11b0c5e343',
        adopted_rows=adoption_rows, manifest=identity(T4X + 'MANIFEST_T4X.sha256'),
        tsa_existing_records=result['tsa'], offline_verification='BOTH_EXISTING_TOKENS_VERIFIED',
        new_timestamp_created=False, release='PREPARE_ONLY',
        session_header=dict(path='paper_plan/task_specs/logs/PCIMPL2_r2.log', lines='1-12',
                            bytes=len(header.encode()), sha256=sha(header.encode()), text=header)))
    identities = []
    for path in sorted(set(expected) | set(docs) | set(caller_sources)):
        item = identity(path, expected.get(path))
        if path in contract['runtime_files']:
            item['role'] = 'UNCHANGED_R2_RUNTIME'
        elif path in parent:
            item['role'] = 'PINNED_PARENT'
        elif path in contract['original_ap27']:
            item['role'] = 'UNCHANGED_ORIGINAL_AP27'
        elif path in contract['acceptance_sources']:
            item['role'] = 'INHERITED_TEST_HELPER_NOT_RUNTIME_AUTHORITY'
        else:
            item['role'] = 'PUBLIC_REFERENCE_OR_CALLER_EDGE_NOT_A_GRANT'
        if path.endswith('.py'):
            item['ast_inventory'] = census(path)
        identities.append(item)
    assert len(parent) == 19 and len(contract['source_pins']) == 22
    assert contract['production_authority'] is False
    assert old['approved_scientific_contract']['sha256'] == identity(R2 + 'APPROVED_NEWS_SOURCE.json')['sha256']

    directory = sorted(x.name for x in (ROOT / R2 / 'code').iterdir() if x.is_file())
    assert directory == ['PARENT_PINS.json', 'build_source_diff.py', 'consumer_branch.py', 'news_source.py']
    save('SOURCE_AST_INVENTORY.json', dict(
        schema='PCIMPL2_SCORING_PUBLIC_SOURCE_AST_INVENTORY_V1', phase='prepare',
        production_authority=False, runtime_files=contract['runtime_files'],
        parent_count=19, scientific_pin_count=22, original_ap_count=27,
        code_directory_file_census=directory, excluded_runtime_tool='code/build_source_diff.py',
        ast_method='sha256(ast.dump(node, include_attributes=False).encode()); original unmodified nodes',
        helper_method='All nested/top-level definitions, call targets, loaded names and imports; dynamic caller edges require owner review, not an inferred import grant',
        identities=identities))
    pressure = subprocess.run(['/usr/bin/memory_pressure'], capture_output=True, text=True, check=True).stdout
    free = int(re.search(r'System-wide memory free percentage:\s*(\d+)%', pressure)[1])
    if free < 10:
        raise RuntimeError('Resource breach; checkpoint and stop')
    save('STATIC_CHECKS.json', dict(
        schema='PCIMPL2_SCORING_PREPARE_STATIC_CHECKS_V1', phase='prepare',
        checks=dict(exact_public_identities='MATCH', unmodified_AST_parsed='YES',
                    adopted_SCORING_manifest_rows='MATCH', existing_T4X_offline_verify='BOTH_OK',
                    session_header='MATCH', runtime_contract='MATCH'),
        numerical_acceptance='NOT_RUN_PREPARE', inherited_evidence='PCREVC4 reports 22/22 targeted and 59/59 parity; not rerun',
        project_imports=False, runtime_wrapper_added=False, F12_patch_applied=False,
        resources=dict(actual_inherited_nice=os.getpriority(os.PRIO_PROCESS, 0),
                       own_free_memory_floor_percent=10, observed_free_memory_percent=free,
                       inherited_AP_free_memory_floor_percent=25, scratch_limit_bytes=1000000000,
                       inherited_peak_RSS_limit_bytes=1610612736,
                       static_process_peak_RSS_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                       numerical_processes_started=0)))
    print(json.dumps(dict(status='STATIC_IDENTITIES_MATCH', sources=len(identities),
                          runtime_files=3, numerical_acceptance='NOT_RUN_PREPARE', free_memory_percent=free)))


if __name__ == '__main__':
    main()
