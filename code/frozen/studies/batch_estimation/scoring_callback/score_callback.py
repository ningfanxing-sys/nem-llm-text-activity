'Record forecast completion and validate the scoring callback metadata.'
from __future__ import annotations

import argparse
import ast
import errno
import datetime as dt
from decimal import Decimal
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile

sys.dont_write_bytecode = True
PACKAGE = Path(__file__).resolve().parent
PROJECT = PACKAGE.parents[3]
PYTHON = '.venv/bin/python'
FIXED = dt.datetime(2026, 10, 6, 1, tzinfo=dt.timezone.utc)
PRODUCERS = {'primary_tests', 'sensitivity_tests', 'robustness_tests', 'batch_estimation', 'label_scoring', 'KCX', 'PC', 'PCX_extension', 'inference', 'FILL3f',
             'AP6', 'notice_evaluation', 'DEVIATIONS', 'D28'}
BLOCKED_SCRIPTS = {'primary_comparisons.py', 'sensitivity_comparisons.py', 'robustness_comparisons.py', 'score_batch.py',
                   'check_scoring_context.py', 'check_scoring_bindings.py', 'dispatch_scoring.py',
                   'check_matched_controls.py', 'pcx_runner.py', 'a2label_turn.py', 'read_comparisons.py',
                   'table_results_conf_results.py', 'host_postscore_a8batch.sh', 'host_PCX.sh',
                   'kcx_runner.py', 'iso_runner.py', 'iso_blocks.py',
                   'producer.py', 'validation_group_8_producer.py', 'anchor_reader.py', 'joint_passthrough.py',
                   'descriptive_diagnostics.py', 'benchmark_positions.py', 'complete_fill.py',
                   'final_deviations.py', 'd28_feature_usage.py', 'run_positive_control.py',
                   'anchor_delays.py', 'robustness_fields.py', 'combination_mae.py',
                   'a2label_extract.py', 'a2label_scope.py', 'a2label_compose.py', 'a2label_features.py',
                   'a2label_predict.py', 'score_labels.py', 'a2label_score_a2x.py', 'a2label_export.py',
                   'host_run_a2batch.sh', 'batch_score.py', 'batch_export.py', 'specified_positive_control.py',
                   'batch_layers.py', 'frozen_losses.py', 'optional_losses.py', 'replay_composite_losses.py',
                   'input_specification.py', 'postscore_guards.py', 'squared_replay.py', 'batch_features.py'}
BLOCKED_CONSUMERS = {Path(name).stem for name in BLOCKED_SCRIPTS} | {'repin_outer'}
SCRIPT_SCOPES = ('/label_scoring/', '/batch_scoring/', '/KCX/', '/robustness_tests/matched_controls/', '/positive_control/',
                 '/inference/', '/notice_evaluation/', '/table_renderer/notice_constraints/',
                 '/deviations_20261005/v4/', '/llm_feature_use_20261007/')

SCOPED_STEMS = {'runner': ('/batch_scoring/', 'batch_scoring.', '/batch_estimation/', 'batch_estimation.'),
                'sealing': ('/batch_scoring/', 'batch_scoring.'),
                'adapter': ('/batch_scoring/', 'batch_scoring.')}


FORBIDDEN = {'host_state', 'private', 'scored', 'scores', 'scoring', 'predictions', 'prediction',
             'sealed', 'run', 'run_null_ext', 'evaluation', 'models', '.git', '.llm_client', '.aws'}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def utc(value):
    require(isinstance(value, str), 'UTC string required')
    stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(stamp.utcoffset() == dt.timedelta(0), 'UTC offset required')
    return stamp


def now():
    return dt.datetime.now(dt.timezone.utc)


def exact_path(value):
    p = Path(value)
    require(p.is_absolute() and str(p) == str(p.resolve()), 'Absolute canonical path required')
    require(not any(a.is_symlink() for a in [p, *p.parents]), 'Symlink path refused')
    return p


def metadata_path(value):
    p = exact_path(value)
    require(p.is_relative_to(PROJECT) and not (set(p.relative_to(PROJECT).parts) & FORBIDDEN), 'Metadata path input_checks')
    require(p.suffix in {'.py', '.md', '.json', '.txt', '.sha256', '.tsr', '.sh'}, 'Metadata/source file required')
    require(not p.name.startswith(('.env', 'OPENED_PATHS')) and p.name != 'auth.json', 'Restricted file')
    return p


def read(path):
    p = metadata_path(path)
    require(p.is_file() and p.stat().st_size < 16_000_000, 'Missing/oversized metadata')
    def pairs(items):
        out = {}
        for k, v in items:
            require(k not in out, 'Duplicate JSON key')
            out[k] = v
        return out
    return json.loads(p.read_text(), object_pairs_hook=pairs,
                      parse_constant=lambda _: require(False, 'Nonfinite JSON'))


def identity(path, *, opaque=False):
    p = exact_path(path) if opaque else metadata_path(path)
    require(p.is_file(), 'Missing identity file: ' + str(p))
    reference_snapshot = p.stat()
    h = hashlib.sha256()
    with p.open('rb') as handle:
        for block in iter(lambda: handle.read(65536), b''):
            h.update(block)
    after = p.stat()
    require((reference_snapshot.st_dev, reference_snapshot.st_ino, reference_snapshot.st_size, reference_snapshot.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'Identity changed while hashing')
    return dict(path=str(p), bytes=after.st_size, sha256=h.hexdigest())


def checked(item, *, opaque=False):
    require(isinstance(item, dict) and set(item) >= {'path', 'bytes', 'sha256'}, 'Identity required')
    require(identity(item['path'], opaque=opaque) == {k: item[k] for k in ('path', 'bytes', 'sha256')}, 'Identity drift')
    return Path(item['path'])


def publish(path, value):

    p = exact_path(path)
    require(not os.path.lexists(p), 'Existing output refused')
    require(p.parent.is_dir(), 'Output parent must already exist')
    fd, tmp = tempfile.mkstemp(prefix='.scorecb-', dir=p.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.link(tmp, p)
    finally:
        os.unlink(tmp)


def expected_score_argv():

    return ['/usr/bin/caffeinate', '-i', PYTHON,
            str(PROJECT / 'studies/confirmation/execution/cli.py'), 'score']


def minimum_history():
    q = PROJECT / 'studies'
    b = q / 'batch_estimation/fitting'
    d = q / 'batch_estimation/disk_checks'
    state = q / 'confirmation/execution/host_state'
    return {b / 'POSTSCORE_HOST_LOG.jsonl', b / 'POSTSCORE_TURN_STATE.json',
            d / 'state/postscore/POSTSCORE_HOST_LOG.jsonl', d / 'state/postscore/POSTSCORE_TURN_STATE.json',
            *(state / s for s in ('a2_scored', 'a3_scored', 'a4_scored')),
            b / 'state/scoring', d / 'state/scoring',
            q / 'inference/production_output', PROJECT / 'tables/table_results_production',
            q / 'inference/a8post6/postscore', q / 'confirmation/notice_evaluation/after_score',
            PROJECT / 'paper_plan/deviations_20261005/v4/FINAL_ACCEPTED'}


def validate_plan(path):
    require(exact_path(path) == PACKAGE / 'SOURCE_PLAN.json', 'Exact frozen source plan path required')
    plan = read(path)
    require(plan.get('schema') == 'SCORECB_SOURCE_PLAN_V1' and plan.get('source_reviewed') is True,
            'Reviewed source plan required')
    reviewed_python_allowlist(plan)
    require(plan.get('fixed_cutoff_utc') == '2026-10-06T01:00:00Z', 'Specified fixed cutoff cannot change')
    require(plan.get('score_argv') == expected_score_argv(), 'Specified score argv drift')
    receipt = exact_path(plan['score_receipt_path'])
    require(receipt == PROJECT / 'studies/confirmation/execution/host_state/scored/SCORE_RECEIPT.json',
            'Canonical score receipt required')
    require(plan.get('launch_embargo') == {'sole_source': True, 'no_postscore_launch_since_t5': True,
                                         'all_alternative_outputs_declared': True}, 'Source dispatch embargo required')
    require(set(plan['producer_outputs']) == PRODUCERS, 'Complete producer inventory required')
    paths = []
    for outputs in plan['producer_outputs'].values():
        require(isinstance(outputs, list) and outputs, 'Exact future producer paths required')
        require(all(Path(p).suffix in {'.json', '.csv', '.jsonl', '.sha256', '.npz'} for p in outputs),
                'Producer outputs must be exact files, not directories')
        paths.extend(exact_path(p) for p in outputs)
    history = {exact_path(p) for p in plan['never_started_paths']}
    require(minimum_history() <= history, 'Historical dispatch sentinel inventory incomplete')
    require(set(paths) <= history, 'Every future producer output must also be a dispatch sentinel')
    require(all(p.is_relative_to(PROJECT) for p in history), 'Launch sentinel escaped project')
    prefixes = plan.get('never_started_prefixes')
    require(isinstance(prefixes, list) and prefixes, 'inference native output prefix policy required')
    for rule in prefixes:
        require(isinstance(rule, dict) and set(rule) == {'producer', 'directory', 'prefix', 'source_reviewed'}
                and rule['producer'] == 'inference' and rule['prefix'] == 'a8post_native_'
                and rule['source_reviewed'] is True, 'Reviewed inference context parent/prefix required')
        parent = exact_path(rule['directory'])
        require(parent.is_relative_to(PROJECT) and not (set(parent.relative_to(PROJECT).parts) & FORBIDDEN),
                'Native output parent must be a project metadata directory')
    b = PROJECT / 'studies/batch_estimation/fitting'
    require(plan['host_log'] == str(b / 'POSTSCORE_HOST_LOG.jsonl') and
            plan['turn_state'] == str(b / 'POSTSCORE_TURN_STATE.json'), 'Frozen journal paths required')
    require(plan['t5_binding_path'] == str(PROJECT / 'studies/batch_estimation/batch_checks/T5_BINDING.json'),
            'Current C T5 timestamp_checks required')
    require(plan.get('initial_inputs_reviewed') is True and isinstance(plan['initial_inputs'], list) and plan['initial_inputs'],
            'Source must complete exact initial identities before capture')
    for item in plan['initial_inputs']:
        metadata_path(item['path'])
    output = exact_path(plan['output_dir'])
    require(output == PACKAGE / 'production_callback', 'Fresh dedicated callback output required')
    return plan


def verify_package():
    freeze = read(PACKAGE / 'CODE_FREEZE.json')
    require(freeze.get('state') == 'SCORECB_FROZEN_FOR_SOURCE', 'Reviewed callback freeze required')
    from freeze_scoring_callback import package_files
    current = package_files(PACKAGE)
    require({str(p) for p in current} == {i['path'] for i in freeze['files']}, 'Callback file inventory drift')
    for item in freeze['files']:
        checked(item)
    for item in freeze['dependencies']:
        checked(item)
    pins = read(PACKAGE / 'DEPENDENCY_PINS.json')
    commitments = set(pins.get('t5_commitment_only_paths', []))
    require(freeze.get('source_commitments') == [dict(source_path=i['path'], source_sha256=i['sha256'], source_bytes=i['bytes'])
                                               for i in pins['files'] if i['path'] in commitments],
            'Exact source commitment drift')
    require(freeze['review_acceptance'] in freeze['files'] and freeze['review'] in freeze['files'],
            'Freeze must bind review and acceptance')
    return freeze


def verify_t5(plan, freeze):
    gate = read(plan['t5_binding_path'])
    require(gate.get('schema') == 'SOURCE_T5_BINDING_V1' and gate.get('label') == 'T5'
            and gate.get('state') == 'T5_VERIFIED' and gate.get('source_verified') is True
            and gate.get('chronology_verified') is True, 'Verified T5 required')
    require(utc(gate['utc']) <= now(), 'T5 has not occurred')
    require(gate.get('authority_path') == plan['t5_binding_path'], 'Wrong T5 timestamp_checks path')
    manifest = checked(gate['manifest'])
    checked(gate['result'])
    require(gate.get('manifest_sha256') == gate['manifest']['sha256'], 'T5 manifest identity mismatch')
    tsas = gate.get('tsa_receipts', [])
    require(len(tsas) >= 2 and len({i['path'] for i in tsas}) == len(tsas)
            and len({i.get('tsa') for i in tsas}) >= 2
            and len({(i['sha256'], i['bytes']) for i in tsas}) == len(tsas), 'Two independent verified TSA receipts required')
    for item in tsas:

        stamp = dt.datetime.strptime(item['time_stamp'], '%b %d %H:%M:%S %Y GMT').replace(tzinfo=dt.timezone.utc)
        require(item.get('verified') is True and stamp <= utc(gate['utc']), 'Unverified T5 TSA')
        checked(item)
    rows = {}
    for line in manifest.read_text().splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        match = re.fullmatch(r'([0-9a-f]{64})  (\d+)  (.+)', line)
        require(match is not None, 'Malformed T5 manifest row')
        digest, size, rel = match.groups()
        require(not Path(rel).is_absolute(), 'T5 root must be relative to Q')
        p = str((PROJECT / 'studies' / rel).resolve())
        require(p not in rows, 'Duplicate T5 manifest row')
        rows[p] = dict(path=p, bytes=int(size), sha256=digest)
    pins = read(PACKAGE / 'DEPENDENCY_PINS.json')
    commitment_only = set(pins.get('t5_commitment_only_paths', []))
    require(commitment_only == {str(PROJECT / 'studies/confirmation/execution/seal_score.py')},
            'Exact commitment-only source exception required')
    required = [identity(PACKAGE / 'CODE_FREEZE.json'), *freeze['files'],
                *(i for i in freeze['dependencies'] if i['path'] not in commitment_only), *plan['initial_inputs']]
    for item in required:
        require(item in gate['files'] and rows.get(item['path']) == item, 'T5 lacks exact callback metadata/source identity')

    return identity(plan['t5_binding_path']), utc(gate['utc'])


def producer_argv(argv, *, launch_dirs=(), resolved_files=(), verified=False):
    if not argv:
        return False
    if any(producer_path(p) for p in resolved_files):
        return True
    if any(Path(p).name.casefold() == 'dispatch.py' and project_identity_path(p) is not None
           for p in resolved_files):
        for vector in launch_vectors(argv):
            consumers = [v.split('=', 1)[1] for v in vector if v.startswith('--consumer=')]
            for index, value in enumerate(vector):
                if value == '--consumer':
                    require(index + 1 < len(vector), 'Uninspectable consumer launcher')
                    consumers.append(vector[index + 1])
            if set(consumers) & BLOCKED_CONSUMERS:
                return True
    if verified:
        return False
    exe = Path(argv[0]).name.lower()
    if not verified and argv[0].endswith(('.py', '.sh')) and any(scope in argv[0] for scope in SCRIPT_SCOPES):
        return True
    direct_stem = Path(argv[0]).stem
    if not verified and argv[0].endswith('.py') and direct_stem in SCOPED_STEMS and any(
            context in token for token in (argv[0], *launch_dirs) for context in SCOPED_STEMS[direct_stem]):
        return True
    if Path(argv[0]).name in BLOCKED_SCRIPTS:
        return True
    if not any(word in exe for word in ('python', 'zsh', 'bash', 'sh', 'nice', 'caffeinate', 'env')):
        return False
    for token in argv:
        name = Path(token).name
        if name == 'dispatch.py':
            consumers = [a.split('=', 1)[1] for a in argv if a.startswith('--consumer=')]
            if '--consumer' in argv:
                index = argv.index('--consumer') + 1
                require(index < len(argv), 'Uninspectable consumer launcher')
                consumers.append(argv[index])
            if set(consumers) & BLOCKED_CONSUMERS:
                return True
        if name in BLOCKED_SCRIPTS:
            return True
        if not verified and token.endswith(('.py', '.sh')) and any(part in token for part in SCRIPT_SCOPES):
            return True
        if name == 'cli.py' and any(a in argv for a in
                ('score', 'panels', 'features', 'counted-pilots', 'fit-bank', 'lear', 'seal')):
            return True
        if not verified and name == 'runner.py' and '/batch_estimation/' in token:
            return True
    if verified:
        return False


    for token in argv:
        for scope in SCRIPT_SCOPES:
            qualified = scope.strip('/').replace('/', '.')
            if re.search(r'(?<![\w])' + re.escape(qualified) + r'\.[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', token):
                return True
            if re.search(re.escape(scope) + r'[^\s\"\']+\.(?:py|sh)\b', token):
                return True
    for stem, contexts in SCOPED_STEMS.items():
        if any(context in token for token in (*argv, *launch_dirs) for context in contexts) and any(
                re.search(r'(?<![\w])' + re.escape(stem) + r'(?:\.py)?(?![\w])', token) for token in argv):
            return True


    for token in argv:
        if any(re.search(r'(?<![\w])' + re.escape(name) + r'(?![\w])', token)
               for name in BLOCKED_SCRIPTS):
            return True
        if any(re.search(r'(?<![\w])' + re.escape(name) + r'(?![\w])', token)
               for name in BLOCKED_CONSUMERS):
            return True
    return False


def launch_vectors(argv):

    vectors = [argv]
    for token in argv:
        if Path(token).name in {'sh', 'bash', 'zsh'}:
            i = argv.index(token) + 1
            if i < len(argv) and re.fullmatch(r'-[a-zA-Z]*c[a-zA-Z]*', argv[i]):
                require(i + 1 < len(argv), 'Unverifiable shell dispatch context')
                try:
                    vectors.append(shlex.split(argv[i + 1]))
                except ValueError as exc:
                    raise RuntimeError('Unverifiable shell dispatch context') from exc
    return vectors


def python_codes(argv):
    codes = []
    for vector in launch_vectors(argv):
        for index, token in enumerate(vector):
            if not re.fullmatch(r'(?:python(?:\d+(?:\.\d+)*)?|pypy\d*)', Path(token).name.lower()):
                continue
            i = index + 1
            while i < len(vector):
                flag = vector[i]
                if flag == '-c':
                    require(i + 1 < len(vector), 'Unverifiable Python dispatch context')
                    codes.append(vector[i + 1])
                    break
                if flag in {'-m', '-', '--'} or not flag.startswith('-'):
                    break
                i += 2 if flag in {'-W', '-X'} else 1


    queue = [(code, 0) for code in codes]
    seen = set()
    out = []
    for code, depth in queue:
        require(depth <= 8 and len(queue) <= 64 and sum(len(c) for c, _ in queue) <= 131072,
                'Unverifiable embedded code complexity')
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            raise RuntimeError('Unverifiable Python dispatch context') from exc
        require(sum(1 for _ in ast.walk(tree)) <= 10000, 'Unverifiable embedded code complexity')
        aliases = {'builtins'}
        operations = {name: name for name in ('exec', 'eval', 'compile')}
        opened = {'open'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                aliases.update(a.asname or a.name for a in node.names if a.name == 'builtins')
            if isinstance(node, ast.ImportFrom) and node.module == 'builtins':
                for alias in node.names:
                    if alias.name in operations:
                        operations[alias.asname or alias.name] = alias.name
                    if alias.name == 'open':
                        opened.add(alias.asname or alias.name)
        def operation(func):
            if isinstance(func, ast.Name):
                return operations.get(func.id)
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in aliases:
                return func.attr if func.attr in {'exec', 'eval', 'compile'} else None
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not operation(node.func):
                continue
            require(node.args, 'Unverifiable embedded code operand')
            source = node.args[0]
            if isinstance(source, ast.Constant) and isinstance(source.value, str):
                queue.append((source.value, depth + 1))
            else:

                file_load = any(isinstance(n, ast.Call) and n.args and
                    isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str) and (
                    (isinstance(n.func, ast.Name) and n.func.id in opened) or
                    (isinstance(n.func, ast.Attribute) and n.func.attr == 'open'))
                    for n in ast.walk(source))
                literal_file = any(isinstance(n, ast.Constant) and isinstance(n.value, str) and
                                   n.value.endswith(('.py', '.sh')) for n in ast.walk(source))
                literal_compile = isinstance(source, ast.Call) and operation(source.func) == 'compile'
                require(file_load or literal_file or literal_compile, 'Unverifiable embedded code operand')
    return out


def python_launch(argv):
    return bool(argv and (argv[0].endswith('.py') or any(
        re.fullmatch(r'(?:python|pypy)(?:\d+(?:\.\d+)*)?[a-z]?', Path(token).name.lower())
        for vector in launch_vectors(argv) for token in vector)))


def literal_sys_paths(argv):
    paths = []
    for code in python_codes(argv):
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:

            raise RuntimeError('Unverifiable Python dispatch context') from exc
        aliases = {'sys'}
        direct = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                aliases.update(a.asname or a.name for a in node.names if a.name == 'sys')
            if isinstance(node, ast.ImportFrom) and node.module == 'sys':
                direct.update(a.asname or a.name for a in node.names if a.name == 'path')
        def path_node(node):
            return (isinstance(node, ast.Attribute) and node.attr == 'path'
                    and isinstance(node.value, ast.Name) and node.value.id in aliases) or (
                    isinstance(node, ast.Name) and node.id in direct)
        def literals(node, many=False):
            try:
                value = ast.literal_eval(node)
            except (ValueError, TypeError, SyntaxError) as exc:
                raise RuntimeError('Unverifiable sys.path dispatch context') from exc
            if many:
                require(isinstance(value, (tuple, list)), 'Unverifiable sys.path dispatch context')
            values = value if many else [value]
            require(all(isinstance(v, str) for v in values), 'Unverifiable sys.path dispatch context')
            paths.extend(values)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and path_node(node.func.value):
                name = node.func.attr
                if name in {'append', 'insert', 'extend'}:
                    expected = 2 if name == 'insert' else 1
                    require(len(node.args) == expected and not node.keywords, 'Unverifiable sys.path dispatch context')
                    if name == 'insert':
                        try:
                            require(type(ast.literal_eval(node.args[0])) is int, 'Unverifiable sys.path dispatch context')
                        except (ValueError, TypeError) as exc:
                            raise RuntimeError('Unverifiable sys.path dispatch context') from exc
                    literals(node.args[-1], many=name == 'extend')
                else:
                    raise RuntimeError('Unverifiable sys.path dispatch context')
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(
                node, (ast.AnnAssign, ast.AugAssign)) else []
            for target in targets:
                is_path = path_node(target) or (isinstance(target, ast.Subscript) and path_node(target.value))
                if is_path:
                    require(getattr(node, 'value', None) is not None, 'Unverifiable sys.path dispatch context')
                    literals(node.value, many=True)
    return paths


def producer_path(path):

    relative = project_identity_path(path)
    if relative is None:
        return False
    text = '/' + '/'.join(p.casefold() for p in relative)
    name = Path(text).name
    return (name in {n.casefold() for n in BLOCKED_SCRIPTS} or
            any(scope.casefold() in text + '/' for scope in SCRIPT_SCOPES) or
            (Path(text).stem in SCOPED_STEMS and any(
                context.casefold() in text for context in SCOPED_STEMS[Path(text).stem])))


def launch_operands(argv):

    scripts, modules, code_tokens = [], [], []
    for vector in launch_vectors(argv):
        if vector and vector[0].endswith(('.py', '.sh')):
            scripts.append(vector[0])
        for index, token in enumerate(vector):
            name = Path(token).name.lower()
            is_python = bool(re.fullmatch(r'(?:python(?:\d+(?:\.\d+)*)?|pypy\d*)', name))
            if not is_python and name not in {'sh', 'bash', 'zsh'}:
                continue
            i = index + 1
            while i < len(vector):
                flag = vector[i]
                if flag == '-c' or (not is_python and re.fullmatch(r'-[a-zA-Z]*c[a-zA-Z]*', flag)):
                    require(i + 1 < len(vector), 'Unverifiable code operand')
                    code_tokens.append(vector[i + 1])
                    break
                if is_python and flag == '-m':
                    require(i + 1 < len(vector), 'Unverifiable module operand')
                    modules.append(vector[i + 1])
                    break
                if flag == '--':
                    i += 1
                    require(i < len(vector), 'Unverifiable script operand')
                    scripts.append(vector[i])
                    break
                if flag == '-':
                    require(not is_python, 'Unverifiable stdin Python operand')
                    break
                if not flag.startswith('-'):
                    scripts.append(flag)
                    break
                i += 2 if (is_python and flag in {'-W', '-X'}) or (not is_python and flag == '-o') else 1
    return scripts, modules, code_tokens


def embedded_operands(argv):
    paths, modules = [], []
    for code in python_codes(argv):
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            raise RuntimeError('Unverifiable Python dispatch context') from exc
        runpy_aliases = {'runpy'}
        run_path_aliases = set()
        run_module_aliases, import_module_aliases = set(), set()
        importlib_aliases, import_aliases = {'importlib'}, {'__import__'}
        builtin_aliases, open_aliases = {'builtins'}, {'open'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                runpy_aliases.update(a.asname or a.name for a in node.names if a.name == 'runpy')
            if isinstance(node, ast.Import):
                builtin_aliases.update(a.asname or a.name for a in node.names if a.name == 'builtins')
                importlib_aliases.update(a.asname or a.name for a in node.names if a.name == 'importlib')
            if isinstance(node, ast.ImportFrom) and node.module == 'builtins':
                open_aliases.update(a.asname or a.name for a in node.names if a.name == 'open')
                import_aliases.update(a.asname or a.name for a in node.names if a.name == '__import__')
            if isinstance(node, ast.ImportFrom) and node.module == 'importlib':
                import_module_aliases.update(a.asname or a.name for a in node.names if a.name == 'import_module')
            if isinstance(node, ast.ImportFrom) and node.module == 'runpy':
                run_path_aliases.update(a.asname or a.name for a in node.names if a.name == 'run_path')
                run_module_aliases.update(a.asname or a.name for a in node.names if a.name == 'run_module')
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                run_path = (isinstance(func, ast.Attribute) and func.attr == 'run_path' and
                            isinstance(func.value, ast.Name) and func.value.id in runpy_aliases) or (
                            isinstance(func, ast.Name) and func.id in run_path_aliases)
                def attr(name, aliases):
                    return isinstance(func, ast.Attribute) and func.attr == name and isinstance(
                        func.value, ast.Name) and func.value.id in aliases
                module_loader = (attr('run_module', runpy_aliases) or attr('import_module', importlib_aliases) or
                    attr('__import__', builtin_aliases) or (isinstance(func, ast.Name) and func.id in
                    (run_module_aliases | import_module_aliases | import_aliases)))
                if module_loader:
                    operand = node.args[0] if node.args else next((k.value for k in node.keywords
                        if k.arg in {'name', 'mod_name'}), None)
                    require(isinstance(operand, ast.Constant) and isinstance(operand.value, str),
                            'Unverifiable embedded module operand')
                    modules.append(operand.value)
                    fromlist = next((k.value for k in node.keywords if k.arg == 'fromlist'), None)
                    if fromlist is None and len(node.args) > 3:
                        fromlist = node.args[3]
                    if fromlist is not None:
                        try:
                            members = ast.literal_eval(fromlist)
                        except (ValueError, TypeError) as exc:
                            raise RuntimeError('Unverifiable module fromlist') from exc
                        require(isinstance(members, (tuple, list)) and all(isinstance(m, str) for m in members),
                                'Unverifiable module fromlist')
                        modules.extend('?' + operand.value + '.' + member for member in members)

                opened = (isinstance(func, ast.Name) and func.id in open_aliases) or (
                    isinstance(func, ast.Attribute) and func.attr == 'open' and
                    isinstance(func.value, ast.Name) and func.value.id in builtin_aliases)
                if run_path or opened:
                    operand = node.args[0] if node.args else next(
                        (k.value for k in node.keywords if k.arg in {'path_name', 'file'}), None)
                    require(isinstance(operand, ast.Constant) and isinstance(operand.value, str),
                            'Unverifiable embedded path operand')
                    paths.append(operand.value)
            imported = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                        [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for module in imported:
                modules.append(module)
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.extend('?' + node.module + '.' + alias.name for alias in node.names if alias.name != '*')
    return paths, modules


def resolved_operand(value, cwd, *, regular=False):
    require(isinstance(value, str) and value and '\x00' not in value and
            not any(c in value for c in ('$', '~', '*', '?', '{', '}')),
            'Unverifiable path operand')
    raw = Path(value) if os.path.isabs(value) else cwd / value
    if regular:
        resolved = raw.resolve(strict=True)
        require(resolved.is_file(), 'Unverifiable regular script operand')
    else:


        ancestor = raw
        while not os.path.lexists(ancestor):
            require(ancestor.parent != ancestor, 'Unverifiable path ancestor')
            ancestor = ancestor.parent
        verified_ancestor = ancestor.resolve(strict=True)
        require(ancestor == raw or verified_ancestor.is_dir(), 'Unverifiable path ancestor')
        resolved = raw.resolve(strict=False)
    return resolved


def resolved_module(module, roots, *, executable, required=True):
    require(isinstance(module, str) and re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', module),
            'Unverifiable module operand')
    relative = Path(*module.split('.'))
    found = []
    for root in roots:
        base = Path(root) / relative
        candidates = [base.with_suffix('.py'), base / ('__main__.py' if executable else '__init__.py')]
        if not executable:
            candidates.append(base / '__main__.py')
        for candidate in candidates:
            if os.path.lexists(candidate):
                found.append(resolved_operand(str(candidate), Path(root), regular=True))
    require(found or not required, 'Unverifiable module operand: ' + module)


    return found


def resolved_launch_files(argv, directories):
    require(directories, 'Verified dispatch cwd required')
    cwd = Path(directories[0])
    scripts, modules, code_tokens = launch_operands(argv)
    embedded, imported = embedded_operands(argv)
    files = [resolved_operand(value, cwd, regular=True) for value in scripts + embedded]
    roots = tuple(dict.fromkeys([*directories, *(str(p.parent) for p in files)]))
    for module in modules:
        files.extend(resolved_module(module, roots, executable=True))
    for item in imported:
        optional = item.startswith('?')
        module = item.lstrip('?')
        standard = module.split('.')[0] in (sys.stdlib_module_names | set(sys.builtin_module_names))
        files.extend(resolved_module(module, roots, executable=False, required=not (standard or optional)))


    codes = python_codes(argv)
    for code in codes:
        for node in ast.walk(ast.parse(code)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value not in codes and (
                    '/' in node.value or node.value.endswith(('.py', '.sh'))):
                files.append(resolved_operand(node.value, cwd, regular=node.value.endswith(('.py', '.sh'))))
    for vector in launch_vectors(argv):
        for token in vector:
            if token in code_tokens or token in scripts or token in modules or token == vector[0]:
                continue
            value = token.split('=', 1)[1] if '=' in token else token
            if value in {'/', '--'} or value.startswith('-'):
                continue
            pathlike = '/' in value or value.startswith('.') or value.endswith(('.py', '.sh'))
            if not pathlike:
                continue

            files.append(resolved_operand(value, cwd, regular=value.endswith(('.py', '.sh'))))
    return tuple(dict.fromkeys(files))


def process_launch_context(proc, argv):

    raw_cwd = proc.cwd()
    require(isinstance(raw_cwd, str) and os.path.isabs(raw_cwd) and '\x00' not in raw_cwd,
            'Unverifiable process cwd')
    cwd = Path(raw_cwd).resolve(strict=True)
    require(cwd.is_dir(), 'Unverifiable process cwd')
    env = proc.environ()
    require(isinstance(env, dict), 'Unverifiable process environment')
    inherited = env.get('PYTHONPATH', '')
    require(isinstance(inherited, str) and '\x00' not in inherited, 'Unverifiable PYTHONPATH')
    inline_paths = [token.split('=', 1)[1] for vector in launch_vectors(argv) for token in vector
                    if token.startswith('PYTHONPATH=')]
    roots = [str(cwd), *inherited.split(os.pathsep),
             *(part for value in inline_paths for part in value.split(os.pathsep)), *literal_sys_paths(argv)]
    directories = []
    for root in roots:
        require(isinstance(root, str) and '\x00' not in root, 'Unverifiable dispatch search directory')
        path = Path(root) if os.path.isabs(root) else cwd / root
        resolved = path.resolve(strict=True)
        require(resolved.is_dir(), 'Unverifiable dispatch search directory')
        directories.append(str(resolved).rstrip(os.sep) + os.sep)
    require(proc.cwd() == raw_cwd, 'Process cwd changed during verification')
    later = proc.environ()
    require(isinstance(later, dict) and later.get('PYTHONPATH', '') == inherited,
            'Process PYTHONPATH changed during verification')
    return tuple(dict.fromkeys(directories))


def environment_digest(environment):

    require(isinstance(environment, dict), 'Unverifiable process environment')
    if 'PYTHONPATH' in environment:
        require(isinstance(environment['PYTHONPATH'], str) and '\x00' not in environment['PYTHONPATH'],
                'Unverifiable PYTHONPATH')
    require(all(isinstance(k, str) and k and '\x00' not in k and '=' not in k and
                isinstance(v, str) and '\x00' not in v for k, v in environment.items()),
            'Unverifiable process environment')
    return hashlib.sha256(json.dumps(environment, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=True).encode('utf-8')).hexdigest()


def reviewed_python_allowlist(plan):
    if plan is None:
        return ()
    require(isinstance(plan, dict) and plan.get('source_reviewed') is True,
            'Reviewed Python process allowlist required')
    entries = plan.get('python_process_allowlist')
    require(isinstance(entries, list), 'Exact Python process allowlist required')
    seen = set()
    for entry in entries:
        require(isinstance(entry, dict) and set(entry) == {'argv', 'cwd', 'environment_sha256'},
                'Exact Python process allowlist identity required')
        argv = entry['argv']
        require(isinstance(argv, list) and argv and all(isinstance(a, str) and '\x00' not in a for a in argv),
                'Unverifiable allowlist argv')
        cwd = exact_path(entry['cwd'])
        require(cwd.is_dir(), 'Unverifiable allowlist cwd')
        require(isinstance(entry['environment_sha256'], str) and
                re.fullmatch(r'[0-9a-f]{64}', entry['environment_sha256']), 'Unverifiable allowlist environment digest')
        key = (tuple(argv), str(cwd), entry['environment_sha256'])
        require(key not in seen, 'Duplicate process allowlist identity')
        seen.add(key)
    return entries


def python_policy_operands(argv, *, executable_python=False):

    if not executable_python:
        return (), ()
    i = 1
    short = set('bBdEhiIOPqRsStuvVx?')
    while i < len(argv):
        flag = argv[i]
        if flag == '--':
            i += 1
            if i == len(argv) or argv[i] == '-':
                return (), ('unverifiable_stdin',)
            return (argv[i],), ()
        if flag == '-':
            return (), ('unverifiable_stdin',)
        if not flag.startswith('-'):
            return (flag,), ()
        if flag.startswith('--'):
            if flag in {'--help', '--version', '--help-all', '--help-env', '--help-xoptions'}:
                return (), ('interpreter_exit_option',)
            require(flag == '--check-hash-based-pycs' and i + 1 < len(argv),
                    'Unverifiable interpreter option')
            require(argv[i + 1] in {'always', 'default', 'never'}, 'Unverifiable interpreter option value')
            i += 2
            continue
        cluster = flag[1:]
        for pos, option in enumerate(cluster):
            if option == '-':
                long = cluster[pos + 1:]
                if not long:
                    i += 1
                    if i == len(argv) or argv[i] == '-':
                        return (), ('unverifiable_stdin',)
                    return (argv[i],), ()
                if long in {'help-all', 'help-env', 'help-xoptions'}:
                    return (), ('interpreter_exit_option',)
                require(long == 'check-hash-based-pycs' and i + 1 < len(argv),
                        'Unverifiable interpreter option')
                i += 1
                require(argv[i] in {'always', 'default', 'never'}, 'Unverifiable interpreter option value')
                break
            if option in 'cmWX':
                value = cluster[pos + 1:]
                if not value:
                    require(i + 1 < len(argv), 'Unverifiable interpreter option operand')
                    i += 1
                    value = argv[i]
                if option in 'cm':
                    return (), ('inline_code' if option == 'c' else 'module_requires_exact_allowlist',)
                break
            require(option in short, 'Unverifiable interpreter option')
            if option in 'hV?':
                return (), ('interpreter_exit_option',)
        i += 1
    return (), ('unverifiable_interactive',)


def filesystem_identity(path):
    stat = Path(path).stat()
    return stat.st_dev, stat.st_ino


def verified_path_ancestor(path):

    path = Path(path)
    ancestor = path
    while True:
        try:
            ancestor.lstat()
            break
        except FileNotFoundError:
            require(ancestor.parent != ancestor, 'Unverifiable path ancestor')
            ancestor = ancestor.parent
    resolved = ancestor.resolve(strict=True)
    require(ancestor == path or resolved.is_dir(), 'Unverifiable path ancestor')
    return resolved, ancestor == path


def project_identity_path(path, root_identity=None):

    root_identity = root_identity or filesystem_identity(PROJECT.resolve(strict=True))
    current, existing = verified_path_ancestor(path)

    suffix = list(Path(path).relative_to(current).parts) if Path(path).is_relative_to(current) else []
    parts = []
    for ancestor in (current, *current.parents):
        if filesystem_identity(ancestor) == root_identity:
            return tuple(reversed(parts)) + tuple(suffix if not existing else ())
        parts.append(ancestor.name)
    return None


def argv_project_paths(argv, cwd, root_identity):
    paths = []
    for token in argv:
        for value in dict.fromkeys([token, token.split('=', 1)[1]] if '=' in token else [token]):
            if not value:
                continue
            raw = Path(value) if os.path.isabs(value) else cwd / value
            try:
                raw.lstat()
            except FileNotFoundError:
                continue
            except OSError as exc:
                if exc.errno in {errno.ENAMETOOLONG, errno.ENOTDIR} and not value.startswith(('/', './', '../')):
                    continue
                raise
            verified, existing = verified_path_ancestor(raw)
            if existing and project_identity_path(verified, root_identity) is not None:
                paths.append(verified)
    return tuple(dict.fromkeys(paths))


def verified_python_context(proc, argv):
    raw_cwd = proc.cwd()
    require(isinstance(raw_cwd, str) and os.path.isabs(raw_cwd) and '\x00' not in raw_cwd,
            'Unverifiable process cwd')
    cwd = Path(raw_cwd).resolve(strict=True)
    require(cwd.is_dir(), 'Unverifiable process cwd')
    environment = proc.environ()
    digest = environment_digest(environment)

    for part in environment.get('PYTHONPATH', '').split(os.pathsep):
        root = Path(part) if os.path.isabs(part) else cwd / part
        require(root.resolve(strict=True).is_dir(), 'Unverifiable dispatch search directory')
    require(proc.cmdline() == argv, 'Process argv changed during verification')
    require(proc.cwd() == raw_cwd, 'Process cwd changed during verification')
    later = proc.environ()
    require(environment_digest(later) == digest,
            'Process environment/PYTHONPATH changed during verification')
    return cwd, environment, digest


def environment_project_paths(environment, cwd, root_identity=None):
    paths = []
    for value in environment.values():
        for part in dict.fromkeys([value, *value.split(os.pathsep)]):
            if not part:
                continue
            raw = Path(part) if os.path.isabs(part) else cwd / part
            verified_path_ancestor(raw)
            if project_identity_path(raw, root_identity) is not None:
                paths.append(str(raw.resolve(strict=False)))
    return tuple(dict.fromkeys(paths))


def active_producers(plan=None, *, observations=None):
    import psutil
    allowlist = reviewed_python_allowlist(plan)
    found = []
    root_identity = filesystem_identity(PROJECT.resolve(strict=True))
    try:
        for proc in psutil.process_iter():
            if proc.pid == os.getpid():
                continue
            command = '<unreadable-command>'
            try:

                uid = proc.uids().real
                require(type(uid) is int and uid >= 0, 'Unverifiable process uid')
                if uid != os.getuid():
                    continue
                try:
                    command = proc.name()
                except (psutil.AccessDenied, AttributeError):
                    pass
                argv = proc.cmdline()
                require(isinstance(argv, list) and argv and all(isinstance(a, str) and '\x00' not in a for a in argv),
                        'Unverifiable process argv')
                exe = proc.exe()
                require(isinstance(exe, str) and os.path.isabs(exe) and '\x00' not in exe,
                        'Unverifiable process executable')
                executable = Path(exe).resolve(strict=True)
                require(executable.is_file(), 'Unverifiable process executable')
                if command == '<unreadable-command>':
                    command = executable.name
                is_python = bool(re.match(r'(?:python|pypy)', executable.name.lower()))

                cwd, environment, digest = verified_python_context(proc, argv)
                if is_python:
                    scripts, modes = python_policy_operands(argv, executable_python=True)
                    resolved = tuple(resolved_operand(p, cwd, regular=True) for p in scripts)
                    argv_paths = argv_project_paths(argv, cwd, root_identity)
                    env_paths = environment_project_paths(environment, cwd, root_identity)
                    require(proc.exe() == exe and Path(proc.exe()).resolve(strict=True) == executable and
                            proc.cmdline() == argv and Path(proc.cwd()).resolve(strict=True) == cwd and
                            environment_digest(proc.environ()) == digest, 'Process context changed during verification')
                    exact = dict(argv=argv, cwd=str(cwd), environment_sha256=digest)
                    allowed = exact in allowlist
                    paths = (cwd, *resolved, *argv_paths, *env_paths)
                    family = producer_argv(argv, launch_dirs=(str(cwd) + os.sep,),
                                           resolved_files=paths, verified=True)
                    families = sorted({str(PROJECT.joinpath(*rel)) for p in paths
                                       if (rel := project_identity_path(p, root_identity)) is not None and producer_path(p)})
                    reasons = list(modes)
                    if project_identity_path(cwd, root_identity) is not None: reasons.append('project_cwd')
                    if any(project_identity_path(p, root_identity) is not None for p in resolved): reasons.append('project_script')
                    if argv_paths: reasons.append('project_argv_path')
                    if env_paths: reasons.append('project_environment')
                    if family: reasons.append('specified_producer_identity')
                    if reasons and not allowed:
                        found.append(proc.pid)
                    if observations is not None:
                        observations.append(dict(pid=proc.pid, command=command, python=True,
                                                 specified_family_identity=family, family_identities=families,
                                                 reasons=reasons, exact_allowlisted=allowed, environment_sha256=digest))
                    continue
                wrapper_script = bool(Path(argv[0]).name in {'env', 'nice', 'caffeinate'} and any(
                    token.endswith(('.py', '.sh')) for vector in launch_vectors(argv) for token in vector))
                dispatch = wrapper_script or argv[0].endswith('.sh') or any(
                    Path(token).name in {'sh', 'bash', 'zsh'} for token in argv)
                contexts = process_launch_context(proc, argv) if dispatch else ()
                resolved = resolved_launch_files(argv, contexts) if dispatch else ()
                existing = argv_project_paths(argv, cwd, root_identity)
                require(proc.exe() == exe and Path(proc.exe()).resolve(strict=True) == executable and
                        proc.cmdline() == argv and Path(proc.cwd()).resolve(strict=True) == cwd and
                        environment_digest(proc.environ()) == digest, 'Process context changed during verification')
                if producer_argv(argv, launch_dirs=contexts,
                                 resolved_files=(executable, *resolved, *existing), verified=True):
                    found.append(proc.pid)
                    if observations is not None:
                        observations.append(dict(pid=proc.pid, command=command, python=False,
                                                 reasons=['specified_producer_identity']))
            except psutil.NoSuchProcess:
                continue
            except (psutil.AccessDenied, OSError, AttributeError, ValueError, RuntimeError) as exc:
                if command == '<unreadable-command>':
                    try:
                        command = proc.name()
                    except (psutil.Error, AttributeError, OSError):
                        pass
                reason = str(exc) if isinstance(exc, RuntimeError) else 'Process dispatch context unreadable'
                raise RuntimeError(f'PID {proc.pid} command {command}: {reason} ({type(exc).__name__})') from exc
    except (psutil.AccessDenied, OSError) as exc:
        raise RuntimeError('Process scan denied; live process table cannot be verified') from exc
    require(filesystem_identity(PROJECT.resolve(strict=True)) == root_identity, 'Project filesystem identity changed during scan')
    return found


def no_launches(plan, confirmed):
    require(confirmed is True, 'Fresh sole-source no-dispatch attestation required')
    for path in plan['never_started_paths']:
        require(not os.path.lexists(path), 'primary_tests/sensitivity_tests/robustness_tests or producer has already started: ' + path)


    for rule in plan['never_started_prefixes']:
        parent = Path(rule['directory'])
        if os.path.lexists(parent):
            require(parent.is_dir(), 'Uninspectable inference context parent')
            with os.scandir(parent) as entries:
                require(not any(entry.name.startswith(rule['prefix']) for entry in entries),
                        'inference native output has already started')
    observations = []
    found = active_producers(plan, observations=observations)
    require(not found, 'primary_tests/sensitivity_tests/robustness_tests or producer process already started (broad Python policy): ' +
            json.dumps([i for i in observations if i['pid'] in found], sort_keys=True))


def load_capture():
    pins = read(PACKAGE / 'DEPENDENCY_PINS.json')
    for item in pins['files']:
        checked(item)
    b = PROJECT / 'studies/batch_estimation/fitting'
    batch = read(b / 'CODE_FREEZE.json')
    require(batch['code_sha256']['code/batch_inputs.py'] == identity(b / 'code/batch_inputs.py')['sha256'],
            'Frozen common function drift')
    host = identity(b / 'HOST_RUN_A8.md')
    require(host in batch['external_files'], 'Host rule not bound by frozen batch')

    for name, path in [('batch_inputs', b / 'code/batch_inputs.py'), ('cutoff_snapshot', b / 'code/cutoff_snapshot.py')]:
        require(name not in sys.modules, 'Unexpected prior frozen module import')
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    mod = sys.modules['cutoff_snapshot']
    require(mod.CUTOFF == FIXED, 'Frozen fixed cutoff mismatch')
    return mod


def arm(plan_path, *, confirmed):
    plan = validate_plan(plan_path)
    freeze = verify_package()
    require(freeze['plan'] == identity(plan_path), 'Plan not bound by callback freeze')
    gate, t5_utc = verify_t5(plan, freeze)
    no_launches(plan, confirmed)
    require(not os.path.lexists(plan['score_receipt_path']), 'Score receipt existed before specified scoring')
    out = exact_path(plan['output_dir'])
    require(not os.path.lexists(out), 'Existing callback output directory refused')
    for item in plan['initial_inputs']:
        checked(item)
    stamp = now()
    require(stamp >= t5_utc, 'Cannot arm before T5')
    value = dict(schema='SCORECB_ARMED_V1', state='ARMED_AFTER_T5_BEFORE_SCORE',
                 armed_utc=stamp.isoformat(), t5_binding=gate, plan=identity(plan_path),
                 callback_freeze=identity(PACKAGE / 'CODE_FREEZE.json'), score_argv=plan['score_argv'],
                 score_receipt_absent=True, no_postscore_launches_confirmed=True)
    out.mkdir()
    publish(out / 'ARMED.json', value)
    return value


def complete(plan_path, *, exit_status, completed_utc, confirmed, cutoff_utc=None):
    plan = validate_plan(plan_path)
    out = exact_path(plan['output_dir'])
    clock_path, fresh_output = out / 'POSTSCORE_CLOCK_ASSOCIATION.json', out / 'CUTOFF_SNAPSHOT.json'
    require(not os.path.lexists(clock_path) and not os.path.lexists(fresh_output), 'Existing output refused')
    require(type(exit_status) is int and exit_status == 0, 'Missing/unverified successful score exit')
    finish = utc(completed_utc)
    require(finish > FIXED, 'This callback is the specified late-score path; use pre-cutoff watcher otherwise')
    require(finish <= now(), 'Score completion is in the future')
    require(cutoff_utc is None or utc(cutoff_utc) == max(finish, FIXED), 'Cutoff earlier/different than specified')
    freeze = verify_package()
    require(freeze['plan'] == identity(plan_path), 'Plan not bound by callback freeze')
    gate, t5_utc = verify_t5(plan, freeze)
    armed = read(out / 'ARMED.json')
    require(armed.get('state') == 'ARMED_AFTER_T5_BEFORE_SCORE' and armed.get('score_receipt_absent') is True
            and armed.get('no_postscore_launches_confirmed') is True, 'Missing verified pre-score arming')
    require(armed['plan'] == identity(plan_path) and armed['t5_binding'] == gate
            and armed['callback_freeze'] == identity(PACKAGE / 'CODE_FREEZE.json')
            and armed['score_argv'] == expected_score_argv(), 'Armed identities drift')
    require(t5_utc <= utc(armed['armed_utc']) <= finish, 'Completion predates T5/score arming')
    no_launches(plan, confirmed)
    receipt = identity(plan['score_receipt_path'], opaque=True)
    require(receipt['bytes'] > 0, 'Missing/empty score receipt')
    published = dt.datetime.fromtimestamp(Path(receipt['path']).stat().st_mtime, dt.timezone.utc)
    require(utc(armed['armed_utc']) <= published <= finish,
            'Score receipt predates arming or postdates completion; metadata corroboration only')
    for item in plan['initial_inputs']:
        checked(item)
    frozen = load_capture()

    no_launches(plan, confirmed)
    require(not os.path.lexists(clock_path) and not os.path.lexists(fresh_output), 'Existing output refused')
    clock = dict(state='POSTSCORE_CLOCK_ASSOCIATION_VERIFIED', source_verified=True,
                 conf_score_receipt=receipt, score_complete_utc=finish.isoformat(),
                 host_log=plan['host_log'], turn_state=plan['turn_state'],
                 producer_outputs=plan['producer_outputs'], initial_inputs=plan['initial_inputs'],
                 schema='SCORECB_POSTSCORE_CLOCK_ASSOCIATION_V1', t5_binding=gate,
                 armed=identity(out / 'ARMED.json'), plan=identity(plan_path),
                 completion_evidence=dict(kind='SOURCE_OBSERVED_SPECIFIED_COMMAND_EXIT',
                     argv=armed['score_argv'], exit_status=exit_status, exit_observed_utc=finish.isoformat(),
                     no_postscore_launches_confirmed=True, receipt_contents_decoded=False),
                 callback_ready_utc=now().isoformat(), retrospective_reconstruction_authorised=False)
    publish(clock_path, clock)
    return frozen.capture(clock_path, fresh_output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('arm', 'complete'))
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--source-confirms-no-launches', action='store_true')
    parser.add_argument('--score-exit-status', type=int)
    parser.add_argument('--score-complete-utc')
    parser.add_argument('--score-complete-epoch')
    parser.add_argument('--cutoff-utc')
    args = parser.parse_args()
    require(args.execute and os.environ.get('A8BATCH_HOST_RUN') == '1', 'Explicit post-T5 source execution required')
    require(os.getpriority(os.PRIO_PROCESS, 0) >= 10, 'Production callback nice >=10 required')
    if args.action == 'arm':
        require(args.score_exit_status is None and args.score_complete_utc is None and args.score_complete_epoch is None and args.cutoff_utc is None,
                'Completion arguments forbidden when arming')
        value = arm(args.plan, confirmed=args.source_confirms_no_launches)
    else:
        require(bool(args.score_complete_utc) != bool(args.score_complete_epoch), 'One actual completion clock required')
        completed = args.score_complete_utc
        if args.score_complete_epoch:
            micros = int(Decimal(args.score_complete_epoch) * 1_000_000)
            completed = (dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(microseconds=micros)).isoformat()
        value = complete(args.plan, exit_status=args.score_exit_status, completed_utc=completed,
                         confirmed=args.source_confirms_no_launches, cutoff_utc=args.cutoff_utc)
    print(json.dumps({'state': value['state'], 'production_fits': 0, 'outcome_values_decoded': False}))


if __name__ == '__main__':
    main()
