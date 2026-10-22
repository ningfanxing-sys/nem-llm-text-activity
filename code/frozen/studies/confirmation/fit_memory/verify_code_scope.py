"""CONFX7 code scope: changed definitions, byte-identical files and the feature-path identity proof.

    python verify_code_scope.py --pre PRE_CONFX2 --post POST_CONFX2 --out UNCHANGED_CODE.json

PRE_CONFX2 holds the pre-CONFX7 (CONFX6) adapter files; POST_CONFX2 the amended ones. Code is parsed,
never executed. The expected change set is the one fixed in CONFX7/SPEC.md, SPEC_ADDENDUM_2_RESUME_IDENTITY.md and
SPEC_ADDENDUM_3_THROUGHPUT.md.
The feature-path proof implements addendum 2 section 3 (superseding SPEC.md section 4's byte identity): every
feature-path file is byte-identical to CONFX6 except `features_adapter.py`, whose only difference is the resume
comparison, proven by reconstruction (remove the added `panel_copy_sha256` block, restore the CONFX6 compare line,
and the CONFX6 file results byte for byte).
"""
from __future__ import annotations
import argparse, ast, hashlib, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONF = HERE.parent
EXPECTED_CHANGED_FILES = {'runtime.py', 'execution_adapter.py', 'tests/test_execution_amendment.py', 'features_adapter.py',
                          'tests/test_confx5_lear.py', 'tests/test_execution_adapters.py'}
EXPECTED_NEW_FILES = {'anonymous_memory.py', 'lear_parallel.py', 'tests/test_confx7_memory.py',
                      'tests/test_confx7_panel_resume.py', 'tests/test_confx7_throughput.py'}
EXPECTED_DEFINITIONS = {
    'runtime.py': {'changed': {'AMENDMENT_CHAIN', '_amendment_declared'},
                   'added': {'CONFX7_RESOURCE_RULE', 'CONFX7_RESUME_IDENTITY_RULE', 'CONFX7_THROUGHPUT_RULE'}},
    'features_adapter.py': {'changed': {'_write_bundles'}, 'added': {'panel_copy_sha256'}},
    'execution_adapter.py': {'changed': {'import:try', '_worker', '_fit_wave', '_resource_records', '_run_stage', 'fit_disk_plan'},
                             'added': {'NOTICE_JOB_LIMIT', 'WIDE_EXTRA_COLUMNS', 'MEMORY_RULE', 'NEWS_MAX_WORKERS',
                                       'THROUGHPUT_RULE', 'job_limit', '_apply_job_memory_rule', '_lear_subjob_worker',
                                       '_admits', '_projection_for', '_memory_class', '_record_class',
                                       '_projected_anonymous'}},
    'tests/test_confx5_lear.py': {'changed': {'test_fit_wave_dispatches_lear_jobs_to_the_confx5_path'}, 'added': set()},
    'tests/test_execution_adapters.py': {'changed': {'AdapterTests'}, 'added': set()},
}
# The feature path (CONFX7/SPEC.md section 4): byte-identical files, and runtime.py definitions other than the chain.
FEATURE_PATH_FILES = ('features_adapter.py', 'feature_storage.py', 'embedding_adapter.py', 'nrx_adapter.py',
                      'panels_adapter.py', 'a1_scoring.py', 'cli.py')
RUNTIME_CHAIN_DEFINITIONS = {'AMENDMENT_CHAIN', '_amendment_declared', 'CONFX7_RESOURCE_RULE', 'CONFX7_RESUME_IDENTITY_RULE',
                             'CONFX7_THROUGHPUT_RULE'}
# Addendum 2: the only permitted feature-path difference (features_adapter.py).
RESUME_SCOPE = 'RESUME_PANEL_COMPARISON_ONLY'
OLD_COMPARE_LINE = "    elif not pd.read_parquet(panel_path).equals(panel):raise ValueError('Resume panel identity drift')\n"
NEW_COMPARE_LINE = "    elif sha256(panel_path)!=panel_copy_sha256(panel):raise ValueError('Resume panel identity drift')\n"
HELPER_START = 'def panel_copy_sha256(panel):\n'
NEXT_DEFINITION = 'def _write_bundles(panel,numeric_columns,rows,out,source,train_mask,*,permit,train_rows=None,storage_plan=None):\n'


# Addendum 4 (incremental notice-prefix encoding): the exact hunks that turn the addendum-4 features_adapter.py back
# into the addendum-2 one (resume comparison only). Each is (addendum-4 text, addendum-2 text).
A4_SCOPE = 'RESUME_COMPARISON_AND_INCREMENTAL_NOTICE_PREFIX_ENCODING'
A4_HUNKS = [
    ("from embedding_adapter import build_encoder,encode_cached\n"
     "# CONFX7 addendum 4: incremental notice-prefix corpora, bit-identical to encode_cached on the full prefix text.\n"
     "from notice_prefix_encoding import NoticePrefixStore,PrefixState,supports_incremental\n",
     "from embedding_adapter import build_encoder,encode_cached\n"),
    ("    # The pinned MiniLM (a FrozenMiniLM) takes the incremental path; other encoders keep the CONFX6 calls below.\n"
     "    incremental=supports_incremental(encoder)\n"
     "    store=NoticePrefixStore(notices,encoder,permit=permit)\n"
     "    main_state=PrefixState(store,cache_directory,'main');shift_state=PrefixState(store,cache_directory,'shift')\n"
     "    origin_groups=panel.groupby('origin',sort=True);last_position=origin_groups.ngroups-1\n"
     "    for position,(origin,frame) in enumerate(origin_groups):\n",
     "    for origin,frame in panel.groupby('origin',sort=True):\n"),
    ("            if incremental:\n"
     "                main_state.advance(end)\n"
     "                main_vec,main_report=main_state.encode_cached(permit=permit)\n"
     "                first_vec,first_report=main_state.encode_cached(permit=permit,first_chunk_only=True)\n"
     "            else:\n"
     "                prefix=notices[:end];serialized=f.chen_notice_text(prefix,permit=permit)\n"
     "                main_vec,main_report=encode_cached(encoder,serialized,cache_directory,permit=permit)\n"
     "                first_vec,first_report=encode_cached(encoder,serialized,cache_directory,permit=permit,first_chunk_only=True)\n",
     "            prefix=notices[:end];serialized=f.chen_notice_text(prefix,permit=permit)\n"
     "            main_vec,main_report=encode_cached(encoder,serialized,cache_directory,permit=permit)\n"
     "            first_vec,first_report=encode_cached(encoder,serialized,cache_directory,permit=permit,first_chunk_only=True)\n"),
    ("            if incremental:\n"
     "                shift_state.advance(shift_end)\n"
     "                shift_vec,_=shift_state.encode_cached(permit=permit)\n"
     "            else:\n"
     "                shifted=notices[:shift_end]\n"
     "                shift_vec,_=encode_cached(encoder,f.chen_notice_text(shifted,permit=permit),cache_directory,permit=permit)\n",
     "            shifted=notices[:shift_end]\n"
     "            shift_vec,_=encode_cached(encoder,f.chen_notice_text(shifted,permit=permit),cache_directory,permit=permit)\n"),
    ("        if incremental and position==last_position:\n"
     "            main_state.check();shift_state.check()\n", ""),
]


def a4_reconstruction(post_text):
    """Undo the addendum-4 hunks (each must occur exactly once) and return the addendum-2 text, or None."""
    text = post_text
    for new, old in A4_HUNKS:
        if text.count(new) != 1:
            return None
        text = text.replace(new, old, 1)
    return text


def resume_comparison_reconstruction(pre_text, post_text):
    """Remove the one added `panel_copy_sha256` block (up to `_write_bundles`), restore the CONFX6 compare line and
    compare with the CONFX6 file byte for byte."""
    out = {'scope': RESUME_SCOPE, 'file': 'features_adapter.py', 'old_line': OLD_COMPARE_LINE, 'new_line': NEW_COMPARE_LINE,
           'confx6_sha256': hashlib.sha256(pre_text.encode()).hexdigest(),
           'post_sha256': hashlib.sha256(post_text.encode()).hexdigest()}
    single = (post_text.count(HELPER_START) == 1 and post_text.count(NEXT_DEFINITION) == 1 and
              post_text.count(NEW_COMPARE_LINE) == 1 and pre_text.count(OLD_COMPARE_LINE) == 1 and
              post_text.count(OLD_COMPARE_LINE) == 0 and pre_text.count(HELPER_START) == 0)
    if not single:
        return {**out, 'helper_sha256': None, 'reconstruction_sha256': None, 'reconstruction_equals_confx6': False}
    start = post_text.index(HELPER_START); end = post_text.index(NEXT_DEFINITION)
    helper = post_text[start:end]
    rebuilt = (post_text[:start] + post_text[end:]).replace(NEW_COMPARE_LINE, OLD_COMPARE_LINE, 1)
    return {**out, 'helper_sha256': hashlib.sha256(helper.encode()).hexdigest(), 'helper_lines': helper.count('\n'),
            'reconstruction_sha256': hashlib.sha256(rebuilt.encode()).hexdigest(),
            'reconstruction_equals_confx6': end > start and rebuilt == pre_text}


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
    a4_installed = (post / 'notice_prefix_encoding.py').exists()
    expected_new = EXPECTED_NEW_FILES | ({'notice_prefix_encoding.py', 'tests/test_confx7_notice_prefix.py'} if a4_installed else set())
    expected_definitions = dict(EXPECTED_DEFINITIONS)
    if a4_installed:
        expected_definitions['features_adapter.py'] = {'changed': {'_write_bundles', 'notice_feature_rows'},
                                                       'added': {'panel_copy_sha256', 'import:notice_prefix_encoding'}}
    ok = set(changed) == EXPECTED_CHANGED_FILES and set(added) == expected_new and not removed
    for name in sorted(expected_definitions):
        a, b = definitions(pre / name), definitions(post / name)
        changed_defs = {k for k in a.keys() & b.keys() if a[k] != b[k]}
        added_defs, removed_defs = set(b) - set(a), set(a) - set(b)
        expected = expected_definitions[name]
        exact = changed_defs == expected['changed'] and added_defs == expected['added'] and not removed_defs
        ok &= exact
        scope[name] = {'pre_sha256': sha(pre / name), 'post_sha256': sha(post / name), 'changed': sorted(changed_defs),
                       'added': sorted(added_defs), 'removed': sorted(removed_defs),
                       'unchanged': sorted(k for k in a.keys() & b.keys() if a[k] == b[k]),
                       'matches_spec': exact}
    frozen = json.loads((CONF / 'FREEZE.json').read_text())['frozen_files']
    design = {rel: sha(CONF / rel) == item['sha256'] for rel, item in frozen.items()}
    ok &= all(design.values())
    feature_files = {name: name in identical for name in FEATURE_PATH_FILES}
    rt_pre, rt_post = definitions(pre / 'runtime.py'), definitions(post / 'runtime.py')
    runtime_other = {k for k in set(rt_pre) | set(rt_post) if k not in RUNTIME_CHAIN_DEFINITIONS}
    runtime_other_identical = all(rt_pre.get(k) == rt_post.get(k) and k in rt_pre and k in rt_post for k in runtime_other)
    feature_path = all(feature_files.values()) and runtime_other_identical and all(design.values())
    post_features = (post / 'features_adapter.py').read_text()
    a4 = (post / 'notice_prefix_encoding.py').exists()
    a4_base = a4_reconstruction(post_features) if a4 else None
    change = resume_comparison_reconstruction((pre / 'features_adapter.py').read_text(), a4_base if a4 else post_features)
    others = all(v for k, v in feature_files.items() if k != 'features_adapter.py')
    except_resume = (not a4 and others and not feature_files['features_adapter.py'] and change['reconstruction_equals_confx6']
                     and runtime_other_identical and all(design.values()))
    a4_proven = (a4 and a4_base is not None and others and change['reconstruction_equals_confx6'] and runtime_other_identical
                 and all(design.values()))
    if a4:
        change = {**change, 'scope': A4_SCOPE, 'addendum_4_hunks_undone': a4_base is not None,
                  'addendum_2_text_sha256': hashlib.sha256(a4_base.encode()).hexdigest() if a4_base is not None else None}
    ok &= feature_path or except_resume or a4_proven
    result = {'state': 'PASS' if ok else 'FAIL', 'pre_root': str(pre), 'post_root': str(post),
              'feature_path_identical_to_confx6': feature_path,
              'feature_path_identical_to_confx6_except_resume_comparison': except_resume,
              'feature_path_identical_to_confx6_except_resume_comparison_and_addendum_4': a4_proven,
              'feature_path_change_scope': (None if feature_path else A4_SCOPE if a4 else 'RESUME_PANEL_COMPARISON_ONLY'),
              'feature_path_change': change if not feature_path else None,
              'feature_path_files_byte_identical': feature_files,
              'runtime_definitions_outside_the_chain_ast_identical': runtime_other_identical,
              'byte_identical_files': identical, 'changed_files': changed, 'new_files': added, 'removed_files': removed,
              'definition_scope': scope, 'design_freeze_files_verified': len(design),
              'design_freeze_files_drifted': sorted(k for k, v in design.items() if not v),
              'note': 'Every non-listed adapter file (feature_storage.py, embedding_adapter.py, nrx_adapter.py, panels_adapter.py, '
                      'a1_scoring.py, cli.py, seal_score.py, report_adapter.py, lear_adapter*.py, ...) must be byte-identical; within '
                      'changed modules every definition not listed is AST-identical; features_adapter.py differs from CONFX6 only by '
                      'the resume comparison (addendum 2), proven by reconstruction.'}
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'state': result['state'], 'changed': changed, 'new': added, 'identical': len(identical)}))
    raise SystemExit(0 if ok else 1)


if __name__ == '__main__':
    main()
