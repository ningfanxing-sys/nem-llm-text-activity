"""CONFX5 code scope: which top-level definitions changed, and which files are byte-identical.

    python verify_code_scope.py --pre PRE_CONFX2 --post POST_CONFX2 --out UNCHANGED_CODE.json

PRE_CONFX2 holds the pre-CONFX5 adapter files; POST_CONFX2 the amended ones. Code is parsed, never
executed. The expected change set is the one fixed in CONFX5/SPEC.md and its two addenda.
"""
from __future__ import annotations
import argparse, ast, hashlib, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONF = HERE.parent
EXPECTED_CHANGED_FILES = {'runtime.py', 'features_adapter.py', 'execution_adapter.py', 'seal_score.py', 'report_adapter.py',
                          'tests/test_execution_amendment.py', 'tests/test_features_adapter.py',
                          'tests/test_execution_adapters.py', 'tests/test_nrx_mw_literal.py'}
EXPECTED_NEW_FILES = {'a1_scoring.py', 'lear_adapter_confx5.py', 'tests/test_confx5_a1.py', 'tests/test_confx5_restart.py',
                      'tests/test_confx5_lear.py'}
EXPECTED_DEFINITIONS = {
    'runtime.py': {'changed': {'AMENDMENT_CHAIN', '_amendment_declared'},
                   'added': {'CONFX5_FEATURE_CONTENT_CHANGE', 'CONFX5_ADDED_SECONDARY_ARMS', 'CONFX5_UNCHANGED'}},
    'features_adapter.py': {'changed': {'NOTICE_ARMS', 'news_feature_rows', 'notice_feature_rows', 'registered_extra_widths',
                                        'build_all_features'},
                            'added': {'import:a1_scoring', 'NEWS_A1_ARMS', 'W2D_CANDIDATE_SIZES', 'W2D_GRANGER_LAG',
                                      'W2D_CORPUS_ISSUE_DAYS', 'W2D_PRICE_DAYS', 'W2D_LABEL_CUTOFF', 'W2D_RULE',
                                      'NOTICE_DERIVED_FILES', 'notice_derived_feature_files', '_finite_or_none',
                                      '_w2d_unavailable', 'select_w2d_vocabulary'}},
    'execution_adapter.py': {'changed': {'import:try', 'feature_manifest', '_fit_wave', 'counted_pilots', 'run_fits',
                                         'run_lear_and_remaining'},
                             'added': {'A1_NEWS_SECONDARY', 'A1_NOTICE_SECONDARY', 'registered_plan'}},
    'seal_score.py': {'changed': {'import:try', '_stage_dispositions', 'seal', '_read_task_data', '_secondary_contrasts', 'score'},
                      'added': {'_stage_reasons_for', '_a1_contrast_row', '_a1_task', '_a1_reclip', '_lear_convergence',
                                '_a1_summary'}},
    'report_adapter.py': {'changed': {'_secondary_prefix', 'write_host_report'}, 'added': {'_a1_lines'}},
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def definitions(path):
    tree = ast.parse(Path(path).read_text())
    result, imports = {}, 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            name = ','.join(ast.unparse(t) for t in targets)
        elif isinstance(node, ast.Try):
            name = 'import:try'
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            module = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
            name = 'import:' + str(module)
        elif isinstance(node, ast.Expr) and isinstance(getattr(node, 'value', None), ast.Constant):
            name = 'docstring'
        else:
            name = 'statement:' + ast.unparse(node)[:60]
        key = name
        while key in result:
            key += "'"
        result[key] = hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
    return result


def expand(names):
    """Tuple assignments such as `a,b=...` keep their joined key; compare by membership."""
    return set(names)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pre', required=True); parser.add_argument('--post', required=True); parser.add_argument('--out', required=True)
    args = parser.parse_args()
    pre, post = Path(args.pre), Path(args.post)
    pre_files = {str(p.relative_to(pre)) for p in [*pre.glob('*.py'), *(pre / 'tests').glob('*.py')]}
    post_files = {str(p.relative_to(post)) for p in [*post.glob('*.py'), *(post / 'tests').glob('*.py')]}
    identical = sorted(f for f in pre_files & post_files if sha(pre / f) == sha(post / f))
    changed = sorted(f for f in pre_files & post_files if sha(pre / f) != sha(post / f))
    added, removed = sorted(post_files - pre_files), sorted(pre_files - post_files)
    scope = {}
    ok = set(changed) == EXPECTED_CHANGED_FILES and set(added) == EXPECTED_NEW_FILES and not removed
    for name in sorted(EXPECTED_DEFINITIONS):
        a, b = definitions(pre / name), definitions(post / name)
        changed_defs = {k for k in a.keys() & b.keys() if a[k] != b[k]}
        added_defs, removed_defs = set(b) - set(a), set(a) - set(b)
        expected = EXPECTED_DEFINITIONS[name]
        exact = changed_defs == expected['changed'] and added_defs == expected['added'] and not removed_defs
        ok &= exact
        scope[name] = {'pre_sha256': sha(pre / name), 'post_sha256': sha(post / name), 'changed': sorted(changed_defs),
                       'added': sorted(added_defs), 'removed': sorted(removed_defs),
                       'unchanged': sorted(k for k in a.keys() & b.keys() if a[k] == b[k]),
                       'matches_spec': exact}
    frozen = json.loads((CONF / 'FREEZE.json').read_text())['frozen_files']
    design = {rel: sha(CONF / rel) == item['sha256'] for rel, item in frozen.items()}
    ok &= all(design.values())
    result = {'state': 'PASS' if ok else 'FAIL', 'pre_root': str(pre), 'post_root': str(post),
              'byte_identical_files': identical, 'changed_files': changed, 'new_files': added, 'removed_files': removed,
              'definition_scope': scope, 'design_freeze_files_verified': len(design),
              'design_freeze_files_drifted': sorted(k for k, v in design.items() if not v),
              'note': 'lear_adapter.py, nrx_adapter.py, panels_adapter.py, feature_storage.py, embedding_adapter.py, cli.py and every other '
                      'non-listed adapter file must be byte-identical; within changed modules every frozen function not listed is AST-identical.'}
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'state': result['state'], 'changed': changed, 'new': added, 'identical': len(identical)}))
    raise SystemExit(0 if ok else 1)


if __name__ == '__main__':
    main()
