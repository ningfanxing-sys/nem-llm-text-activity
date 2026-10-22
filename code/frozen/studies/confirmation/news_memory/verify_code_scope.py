"""Parse-only CONFX8 code scope, exact allowed definitions, feature path and inherited CONFX6 proof.
python verify_code_scope.py --pre PRE_CONFX2 --post POST_CONFX2 --out UNCHANGED_CODE.json
"""
import argparse, ast, hashlib, importlib.util, json
from pathlib import Path
HERE = Path(__file__).resolve().parent
CONF = HERE.parent
EXPECTED = {
    'runtime.py': ({'AMENDMENT_CHAIN', '_amendment_declared'}, {'CONFX8_RESOURCE_RULE'}),
    'execution_adapter.py': ({'MEMORY_RULE', 'job_limit', '_projected_anonymous', 'counted_pilots'},
                             {'NEWS_JOB_LIMIT', 'NEWS_REFERENCE_ROWS', 'NEWS_REFERENCE_PEAKS', 'NEWS_REFERENCE_COLUMNS'}),
}
CHAIN_DEFS = {'AMENDMENT_CHAIN', '_amendment_declared', 'CONFX8_RESOURCE_RULE'}
FEATURES = ('features_adapter.py', 'feature_storage.py', 'embedding_adapter.py', 'nrx_adapter.py',
            'panels_adapter.py', 'a1_scoring.py', 'cli.py')

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def definitions(p):
    spec = importlib.util.spec_from_file_location('confx7_scope', CONF / 'CONFX7/verify_code_scope.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m.definitions(p)

def verify(pre, post):
    pre, post = Path(pre), Path(post)
    parent_path = HERE / 'archive/pre_CONFX8/CONFX2/ADAPTER_FREEZE.json'
    if not parent_path.exists(): parent_path = CONF / 'CONFX2/ADAPTER_FREEZE.json'
    frozen_parent = json.loads(parent_path.read_text())
    # An install archive contains only replaced files. Unchanged files may be read in place, but their
    # hashes must still match the registered parent freeze below; this cannot conceal an unarchived change.
    pre_file = lambda rel: pre / rel if (pre / rel).exists() else post / rel
    paths = lambda root: {str(p.relative_to(root)) for p in [*root.glob('*.py'), *(root / 'tests').glob('*.py')]}
    a = {rel for rel in frozen_parent['files'] if rel.endswith('.py') and not rel.startswith('../')}
    b = paths(post)
    changed = sorted(p for p in a & b if sha(pre_file(p)) != sha(post / p))
    added, removed = sorted(b - a), sorted(a - b)
    expected_changed = set(EXPECTED) | {'tests/test_execution_amendment.py', 'tests/test_confx7_memory.py'}
    ok = set(changed) == expected_changed and added == ['tests/test_confx8_resources.py'] and not removed
    scope = {}
    for rel, (want_changed, want_added) in EXPECTED.items():
        d1, d2 = definitions(pre_file(rel)), definitions(post / rel)
        c = {k for k in d1.keys() & d2.keys() if d1[k] != d2[k]}
        n, r = set(d2) - set(d1), set(d1) - set(d2)
        exact = c == want_changed and n == want_added and not r
        ok &= exact
        scope[rel] = {'changed': sorted(c), 'added': sorted(n), 'removed': sorted(r), 'matches_spec': exact}
    f = {rel: sha(pre_file(rel)) == sha(post / rel) for rel in FEATURES}
    r1, r2 = definitions(pre_file('runtime.py')), definitions(post / 'runtime.py')
    outside = all(r1.get(k) == r2.get(k) for k in (set(r1) | set(r2)) - CHAIN_DEFS)
    pre_code = pre.parent / 'code'
    if not pre_code.is_dir(): pre_code = CONF / 'code'
    code = {p.name: sha(p) == sha(post.parent / 'code' / p.name) for p in pre_code.glob('*.py')}
    prior = json.loads((CONF / 'CONFX7/UNCHANGED_CODE.json').read_text())
    prior_sha = sha(CONF / 'CONFX7/UNCHANGED_CODE.json')
    spec = json.loads((HERE / 'SPEC_FREEZE.json').read_text())
    # Check all input pre-replica files against the genuine parent freeze, not just pre/post agreement.
    parent_checks = {rel: sha(pre_file(rel)) == frozen_parent['files'][rel]['sha256'] for rel in a}
    feature_identical = all(f.values()) and outside and all(code.values())
    ok &= feature_identical and all(parent_checks.values()) and prior['state'] == 'PASS' and prior_sha == spec['parent_scope_proof']['sha256']
    return {'task': 'CONFX8', 'state': 'PASS' if ok else 'FAIL', 'pre_root': str(pre), 'post_root': str(post),
            'feature_path_identical_to_confx7': feature_identical, 'confx7_feature_path_proof': prior,
            'confx7_feature_path_proof_sha256': prior_sha, 'feature_path_files_byte_identical': f,
            'runtime_definitions_outside_the_chain_ast_identical': outside, 'conf_code_files_byte_identical': code,
            'pre_sources_match_registered_confx7_freeze': parent_checks, 'definition_scope': scope,
            'changed_files': changed, 'new_files': added, 'removed_files': removed,
            'worker_and_admission_ast_identical': all(definitions(pre_file('execution_adapter.py'))[k] == definitions(post / 'execution_adapter.py')[k]
                for k in ('_worker', '_fit_wave', '_admits', 'parameters', 'registered_plan', '_resource_records', '_conservative', '_run_stage')),
            'host_state_opened': False, 'production_commands_run': []}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('pre', 'post', 'out'): p.add_argument('--' + key, required=True)
    args = p.parse_args(); result = verify(args.pre, args.post)
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'state': result['state'], 'changed': result['changed_files'], 'new': result['new_files']}))
    raise SystemExit(0 if result['state'] == 'PASS' else 1)

if __name__ == '__main__':
    main()
