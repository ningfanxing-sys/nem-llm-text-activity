'Compare source ASTs and hashes for the quantity parsing calculation.'
from __future__ import annotations
import sys
sys.dont_write_bytecode = True

import argparse
import ast
import contextlib
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
confirmation = HERE.parent
execution = confirmation / 'execution'
STUDY = confirmation.parent
notice_extraction = STUDY / 'notice_extraction'
ARCHIVE = HERE / 'archive/pre_SPEC_4'
HOST_STATE = str((execution / 'host_state').resolve())
AUDIT_LOG = HERE / 'OPENED_PATHS_code_scope.jsonl'
CHANGED = {'execution/notice_label_adapter.py', 'execution/runtime.py', 'execution/tests/test_execution_specification.py', 'HOST_RUN.md',
           'execution/ADAPTER_FREEZE.json'}
ADDED_CODE = {'execution/tests/test_nrx_mw_literal.py'}
EXPECTED_AST = {
    'notice_label_adapter.py': {'changed': ['_bound_quantities', 'scalar'], 'added': ['NUMBER_UNIT', 'UNIT_TOKENS'], 'removed': []},
    'runtime.py': {'changed': ['validate_permit', 'verify_adapter_ancestor'],
                   'added': ['SPECIFICATION_CHAIN', 'SPEC_4_FEATURE_CONTENT_CHANGE', '_specification_declared',
                             'adapter_specification_chain'], 'removed': []}}
NEWS_ROOTS = ('features_adapter.news_feature_rows', 'features_adapter._write_bundles', 'features_adapter.fixed_pruning',
              'features_adapter.load_news_articles', 'features_adapter.select_news_vocabulary',
              'features_adapter.news_derived_date_sidecar', 'features_adapter.specified_extra_widths',
              'features_adapter.planned_array_bytes', 'embedding_adapter.encode_cached', 'embedding_adapter.build_encoder')


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def identity(path):
    p = Path(path).resolve()
    return {'path': str(p), 'sha256': sha256(p), 'bytes': p.stat().st_size}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def install_audit():
    fd = os.open(AUDIT_LOG, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)

    def hook(event, args):
        if event != 'open' or not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        path = os.path.abspath(os.fsdecode(args[0]))
        if path == str(AUDIT_LOG):
            return
        if (path == HOST_STATE or path.startswith(HOST_STATE + os.sep) or '/semantic_validation/private/' in path
                or Path(path).name in {'.env', '.netrc'} or '/.llm_client/auth.json' in path or '/Keychains/' in path):
            raise PermissionError('quantity_parsing code-scope proof refuses protected path: ' + path)
        os.write(fd, (json.dumps({'time_utc': utc_now(), 'path': path, 'mode': str(args[1]),
                                  'reader': 'spec_4_code_scope'}) + '\n').encode())
    sys.addaudithook(hook)


def top_level(source):
    nodes = {}
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            key = node.name
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            key = ','.join(sorted(t.id for t in targets if isinstance(t, ast.Name))) or ast.dump(node)
        elif isinstance(node, ast.Expr) and isinstance(getattr(node, 'value', None), ast.Constant):
            key = '__docstring__'
        else:
            key = ast.dump(node, include_attributes=False)
        require(key not in nodes, 'duplicate top-level key ' + key)
        nodes[key] = hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
    return nodes


def ast_scope(name):
    old = top_level((ARCHIVE / 'execution' / name).read_text())
    new = top_level((execution / name).read_text())
    result = {'changed': sorted(k for k in old if k in new and old[k] != new[k]),
              'added': sorted(k for k in new if k not in old), 'removed': sorted(k for k in old if k not in new),
              'unchanged': sorted(k for k in old if k in new and old[k] == new[k])}
    result['matches_spec'] = {k: result[k] for k in ('changed', 'added', 'removed')} == EXPECTED_AST[name]
    result['unchanged_ast_sha256'] = {k: new[k] for k in result['unchanged']}
    return result


def byte_scope():
    parent = json.loads((ARCHIVE / 'execution/ADAPTER_FREEZE.json').read_text())
    unchanged, changed = {}, {}
    for rel, item in sorted(parent['files'].items()):
        key = str((execution / rel).resolve().relative_to(confirmation))
        current = identity(execution / rel)
        same = current['sha256'] == item['sha256'] and current['bytes'] == item['bytes']
        (unchanged if same else changed)[key] = {'spec_3_sha256': item['sha256'], 'current_sha256': current['sha256']}
    tests_now = {str(p.relative_to(confirmation)) for p in (execution / 'tests').glob('*.py')}
    tests_bound = {k for k in list(unchanged) + list(changed) if k.startswith('execution/tests/')}
    code_now = {str(p.relative_to(confirmation)) for p in execution.glob('*.py')}
    code_bound = {k for k in list(unchanged) + list(changed) if k.startswith('execution/') and k.count('/') == 1
                  and k.endswith('.py')}
    return {'spec_3_bound_files': len(parent['files']), 'unchanged_files': len(unchanged),
            'changed_files': sorted(changed), 'changed_detail': changed,
            'changed_set_equals_spec': set(changed) == CHANGED - {'execution/ADAPTER_FREEZE.json'},
            'new_code_or_test_files': sorted((tests_now - tests_bound) | (code_now - code_bound)),
            'new_files_equal_spec': (tests_now - tests_bound) | (code_now - code_bound) == ADDED_CODE,
            'unchanged': unchanged}


def design_and_nrx():
    sys.path.insert(0, str(execution))
    import runtime
    design = runtime.verify_design()
    contract = json.loads((notice_extraction / 'CONTRACT_FREEZE_1_3.json').read_text())
    drift = [rel for rel, digest in contract['files_sha256'].items() if sha256(notice_extraction / rel) != digest]
    receipt = json.loads((notice_extraction / 'results_1_3/EXTRACTION_RECEIPT.json').read_text())
    labels = sha256(notice_extraction / 'results_1_3/labels.parquet')
    scope = sha256(notice_extraction / 'scope.jsonl')
    return {'design_freeze': identity(confirmation / 'FREEZE.json'), 'design_frozen_files_verified': len(design['frozen_files']),
            'design_state': 'PASS',
            'nrx_contract_freeze': identity(notice_extraction / 'CONTRACT_FREEZE_1_3.json'),
            'nrx_contract_files_verified': len(contract['files_sha256']), 'nrx_contract_drift': drift,
            'nrx_labels_sha256': labels, 'nrx_labels_equal_receipt': labels == receipt.get('labels_sha256'),
            'nrx_scope_sha256': scope, 'nrx_scope_equal_receipt': scope == receipt.get('scope_sha256')}


def definitions():

    modules = sorted(execution.glob('*.py')) + sorted((confirmation / 'code').glob('*.py'))
    defs = {}
    for path in modules:
        tree = ast.parse(path.read_text())
        stem = path.stem

        def visit(node, prefix):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    refs = set()
                    for sub in ast.walk(child):
                        if isinstance(sub, ast.Name):
                            refs.add(sub.id)
                        elif isinstance(sub, ast.Attribute):
                            refs.add(sub.attr)
                    defs[f'{stem}.{prefix}{child.name}'] = {'name': child.name, 'refs': refs,
                                                           'module': str(path.relative_to(confirmation))}
                elif isinstance(child, ast.ClassDef):
                    visit(child, prefix + child.name + '.')
        visit(tree, '')
    return defs


def news_path_static():
    defs = definitions()

    reach, names = {'notice_label_adapter.scalar'}, {'scalar'}
    changed = True
    while changed:
        changed = False
        for qual, item in defs.items():
            if qual not in reach and item['refs'] & names:
                reach.add(qual); names.add(item['name']); changed = True

    forward = set(NEWS_ROOTS)
    require(forward <= set(defs), 'news root missing: ' + repr(sorted(forward - set(defs))))
    changed = True
    while changed:
        changed = False
        for qual in list(forward):
            for other, item in defs.items():
                if other not in forward and item['name'] in defs[qual]['refs']:
                    forward.add(other); changed = True

    tree = ast.parse((execution / 'features_adapter.py').read_text())
    build = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'build_all_features')
    calls = [(n.lineno, n.func.id if isinstance(n.func, ast.Name) else n.func.attr, n) for n in ast.walk(build)
             if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))]
    news_write = min(line for line, name, n in calls if name == '_write_bundles' and n.args
                     and isinstance(n.args[0], ast.Name) and n.args[0].id == 'news')
    first_nrx = min(line for line, name, _ in calls if name in
                    ('load_host_notices', 'normalize_notices', 'laz_asof', 'load_final3', 'notice_feature_rows'))
    return {'reverse_closure_of_scalar': sorted(reach), 'news_forward_closure_size': len(forward),
            'news_forward_closure': sorted(forward), 'intersection': sorted(forward & reach),
            'news_path_cannot_reach_scalar': not (forward & reach),
            'build_all_features_news_write_line': news_write, 'build_all_features_first_nrx_call_line': first_nrx,
            'news_bundles_written_before_any_nrx_call': news_write < first_nrx,
            'method': 'Name/attribute references per function over execution production modules and confirmation/code; '
                      'closures by simple name across modules (over-approximation).'}


class SyntheticEncoder:


    def encode_corpus(self, text, first_chunk_only=False):
        import numpy as np
        if not text:
            return np.zeros(384, dtype=np.float32), {'tokens': 0, 'chunks': 0, 'encoded_chunks': 0}
        tokens = text.split(); chunks = [tokens[i:i + 254] for i in range(0, len(tokens), 254)]
        chosen = chunks[:1] if first_chunk_only else chunks
        vectors = []
        for chunk in chosen:
            digest = hashlib.sha256(' '.join(chunk).encode()).digest()
            v = np.tile(np.frombuffer(digest, dtype=np.uint8), 12).astype(np.float32); v /= np.linalg.norm(v)
            vectors.append(v)
        vec = np.mean(vectors, axis=0, dtype=np.float32); vec /= np.linalg.norm(vec)
        return vec, {'tokens': len(tokens), 'chunks': len(chunks), 'encoded_chunks': len(chosen),
                     'first_chunk_only': first_chunk_only}


def news_path_dynamic(scratch):
    import numpy as np
    import pandas as pd
    sys.path.insert(0, str(execution))
    import runtime
    import notice_label_adapter
    import features_adapter as fa
    f = runtime.conf_module('features')
    guard = runtime.conf_module('guard')
    permit = guard.ExecutionPermit('SPEC_4_CODE_SCOPE_SYNTHETIC', 'a' * 64, 'b' * 64, True)
    parser = fa.import_pure(fa.PROJ / 'studies/news_features/news_feature_definitions.py',
                            '_spec_4_parser').absolute_interval
    rows = []
    for day in ('2026-07-06', '2026-07-13', '2026-07-20'):
        origin = pd.Timestamp(day, tz='Australia/Brisbane').tz_convert('UTC')
        for region in ('NSW1', 'QLD1', 'TAS1'):
            for h in (1, 2):
                rows.append({'origin': origin, 'target_time': origin + pd.Timedelta(hours=h), 'target_day': day,
                             'region': region, 'horizon': h, 'num_a': float(h), 'num_b': float(len(rows))})
    panel = pd.DataFrame(rows)

    def article(aid, available):
        return {'article_id': str(aid), 'saved_version_available_utc': available, 'publication_utc': available,
                'modified_utc': available, 'extraction_status': 'SUCCESS', 'title': 'plant coal unit1',
                'body': 'failure restored', 'impact_level': 'c1',
                'attributes_json': {k: 'UNKNOWN' for k in f.ATTRIBUTES},
                'statements_json': [{'kind': 'FORECAST', 'event_type': 'GENERATOR_OUTAGE', 'regions': ['NSW1'],
                                     'event_time_text': '2026-07-20'}]}
    articles = [article(i, pd.Timestamp(day, tz='Australia/Brisbane').tz_convert('UTC').isoformat())
                for i, day in enumerate(('2026-07-05', '2026-07-12', '2026-07-19'))]

    def run(cache):
        return list(fa.news_feature_rows(panel, articles, permit=permit, encoder=SyntheticEncoder(),
                                         cache_directory=cache, absolute_interval=parser,
                                         vocabulary={'title': ['coal'], 'body': ['failure']}, stopwords=set()))

    def sentinel(*args, **kwargs):
        raise AssertionError('news path reached the notice_extraction adapter')
    calls = {'sentinel_calls': 0}
    reference = run(scratch / 'news_reference')
    entry_points = ('scalar', '_bound_quantities', '_label_evidence', 'normalize_notice', 'normalize_notices',
                    'laz_asof', 'load_host_notices', 'load_final3', 'load_corrected_rule')
    with contextlib.ExitStack() as stack:
        for name in entry_points:
            stack.enter_context(patch.object(notice_label_adapter, name, sentinel))
        for name in ('normalize_notices', 'laz_asof', 'load_host_notices', 'load_final3', 'load_corrected_rule'):
            stack.enter_context(patch.object(fa, name, sentinel))
        poisoned = run(scratch / 'news_poisoned')
    require(len(reference) == len(poisoned), 'news batch count differs')
    columns = 0
    for (ri, re_, rc), (pi, pe, pc) in zip(reference, poisoned):
        require(np.array_equal(ri, pi) and list(re_) == list(pe), 'news index/arm order differs')
        require(json.dumps(rc, sort_keys=True, default=str) == json.dumps(pc, sort_keys=True, default=str),
                'news coverage differs')
        for key in re_:
            require(list(re_[key]) == list(pe[key]), 'news column order differs')
            for name in re_[key]:
                a = np.broadcast_to(np.asarray(re_[key][name], dtype=np.float32), len(ri)).view(np.uint32)
                b = np.broadcast_to(np.asarray(pe[key][name], dtype=np.float32), len(pi)).view(np.uint32)
                require(np.array_equal(a, b), 'news values differ')
                columns += 1
    return {'synthetic_news_batches': len(reference), 'arm_variants': len(reference[0][1]),
            'compared_column_batches': columns, 'poisoned_entry_points': list(entry_points),
            'outputs_bit_identical_with_nrx_adapter_poisoned': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scratch', type=Path, required=True)
    args = parser.parse_args()
    install_audit()
    scratch = args.scratch.resolve() / ('spec_4_code_scope_' + utc_now().replace(':', '-'))
    scratch.mkdir(parents=True)
    sys.path.insert(0, str(execution))
    import runtime
    asts = {name: ast_scope(name) for name in ('notice_label_adapter.py', 'runtime.py')}
    unchanged = {'task': 'quantity_parsing', 'time_utc': utc_now(), 'ast': asts, 'bytes': byte_scope(),
                 'other_feature_learner_stage_budget_inference_code_changed': False}
    unchanged['state'] = 'PASS' if (all(a['matches_spec'] for a in asts.values())
                                    and unchanged['bytes']['changed_set_equals_spec']
                                    and unchanged['bytes']['new_files_equal_spec']) else 'FAIL'
    design = {'task': 'quantity_parsing', 'time_utc': utc_now(), **design_and_nrx(), 'window_outcomes_read': False}
    design['state'] = 'PASS' if (not design['nrx_contract_drift'] and design['nrx_labels_equal_receipt']
                                 and design['nrx_scope_equal_receipt']) else 'FAIL'
    news = {'task': 'quantity_parsing', 'time_utc': utc_now(), 'static': news_path_static(), 'dynamic': news_path_dynamic(scratch)}
    news['state'] = 'PASS' if (news['static']['news_path_cannot_reach_scalar']
                               and news['static']['news_bundles_written_before_any_nrx_call']
                               and news['dynamic']['outputs_bit_identical_with_nrx_adapter_poisoned']) else 'FAIL'
    trash = shutil.which('trash') or ('/usr/bin/trash' if Path('/usr/bin/trash').exists() else None)
    if trash:
        subprocess.run([trash, str(scratch)], check=True)
    for name, value in (('UNCHANGED_CODE.json', unchanged), ('FROZEN_DESIGN_VERIFICATION.json', design),
                        ('NEWS_PATH_PROOF.json', news)):
        value['temporary_files_moved_to_trash'] = bool(trash) and not scratch.exists()
        runtime.atomic_json(HERE / name, value)
    print(json.dumps({'unchanged_code': unchanged['state'], 'ast': {k: {x: v[x] for x in ('changed', 'added', 'removed')}
                                                                     for k, v in asts.items()},
                      'changed_files': unchanged['bytes']['changed_files'],
                      'new_files': unchanged['bytes']['new_code_or_test_files'],
                      'design_and_nrx': design['state'], 'news_path': news['state'],
                      'reverse_closure': news['static']['reverse_closure_of_scalar'],
                      'intersection': news['static']['intersection']}, indent=1))
    if 'FAIL' in (unchanged['state'], design['state'], news['state']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
