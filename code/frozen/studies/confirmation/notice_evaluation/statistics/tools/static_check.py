'Inspect the source ASTs used by forecast validation.'
import ast
import builtins
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import symtable
import sys

OUT = Path(__file__).resolve().parents[1]
PROJ = OUT.parents[4]
notice_delays = OUT.parent
AF = PROJ / 'studies/confirmation/forecast_hashes'
C = PROJ / 'studies/batch_estimation/batch_checks'
R2 = PROJ / 'comparison_inputs'


def read(path):
    path = Path(path)
    if path.resolve() != path or path.is_symlink():
        raise RuntimeError('Source alias: ' + str(path))
    if any(p.lower() in {'host_state', 'sealed', 'scores', 'predictions', 'run', 'evaluation'} for p in path.parts):
        raise RuntimeError('Protected path: ' + str(path))
    if path.suffix != '.py' and path.name.upper().startswith(('SEAL_', 'SCORE_')):
        raise RuntimeError('Protected payload-like path: ' + str(path))
    reference_snapshot = path.stat()
    if reference_snapshot.st_size > 16 * 1024 * 1024:
        raise RuntimeError('Unbounded public source')
    data = path.read_bytes()
    after = path.stat()
    if (reference_snapshot.st_ino, reference_snapshot.st_mtime_ns, reference_snapshot.st_size) != (after.st_ino, after.st_mtime_ns, after.st_size):
        raise RuntimeError('Source changed while reading')
    return data


def ident(path):
    path = Path(path)
    data = read(path)
    return dict(path=str(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def load(path):
    return json.loads(read(path))


def digest(node):
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def named(tree, name):
    nodes = [n for n in tree.body if getattr(n, 'name', None) == name or
        isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]
    if len(nodes) != 1:
        raise RuntimeError('Node census: ' + name)
    return nodes[0]


def resources():
    result = subprocess.run(['/usr/bin/memory_pressure'], text=True, capture_output=True, check=True)
    match = re.search(r'System-wide memory free percentage: (\d+)%', result.stdout)
    if not match:
        raise RuntimeError('Memory floor unobservable')
    free = int(match.group(1))
    nice = os.getpriority(os.PRIO_PROCESS, 0)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    size = sum(p.stat().st_size for p in OUT.rglob('*') if p.is_file())
    if free < 25 or rss >= 1_500_000_000 or size >= 10**9 or nice != 20:
        raise RuntimeError('Resource gate breach: ' + str((free, nice, rss, size)))
    return dict(free_memory_percent=free, inherited_nice=nice, peak_rss_bytes=rss,
        output_bytes=size, scratch_bytes=0, one_inspection_process=True,
        global_floor_percent=10, effective_floor_percent=25)


def record(path, expected=None):
    item = ident(path)
    if expected is not None:
        wanted = expected if isinstance(expected, str) else expected['sha256']
        if item['sha256'] != wanted or isinstance(expected, dict) and 'bytes' in expected and item['bytes'] != expected['bytes']:
            raise RuntimeError('Public source drift: ' + str(path))
    return item


def functions(path, names=None):
    tree = ast.parse(read(path), filename=str(path))
    result = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and (names is None or node.name in names):
            result.append(dict(path=str(path), name=node.name, lines=[node.lineno, node.end_lineno], ast_sha256=digest(node)))
    if names is not None and set(names) != {r['name'] for r in result}:
        raise RuntimeError('Required callable missing: ' + str(path))
    return result


def main():
    if os.environ.get('SCORING_PHASE', 'prepare') not in ('prepare', 'accept'):
        raise RuntimeError('This is only a prepare static inspection')
    receipt_name = sys.argv[1] if len(sys.argv) == 2 else 'STATIC_CHECK.json'
    if len(sys.argv) > 2 or not re.fullmatch(r'STATIC_CHECK(?:_[A-Z0-9]+)?\.json', receipt_name):
        raise RuntimeError('Finite static receipt filename required')
    destination = OUT / receipt_name
    if destination.exists():
        raise RuntimeError('Preserve existing static receipt; choose a new filename')
    start = resources()
    checkpoints = []
    public = []
    copied = []
    original = load(OUT / 'ORIGINAL_SOURCE_AST_INVENTORY.json')
    for item in original['original_whole_sources'].values():
        public.append(record(Path(item['path']), item))
    for row in original['nodes']:
        source = Path(row['original_source']['path'])
        source_data = read(source)
        node = named(ast.parse(source_data), row['name'])
        target = Path(row['extracted_path'])
        target_node = named(ast.parse(read(target)), row['name'])
        text = '\n'.join(source_data.decode().splitlines()[node.lineno-1:node.end_lineno]) + '\n'
        if digest(node) != row['ast_sha256'] or digest(target_node) != row['ast_sha256'] or hashlib.sha256(text.encode()).hexdigest() != row['original_text_sha256']:
            raise RuntimeError('Extraction drift: ' + row['name'])
        copied.append(dict(name=row['name'], original=str(source), extracted=str(target), ast_sha256=row['ast_sha256']))
    native_extractions = load(OUT/'NATIVE_AST_EXTRACTIONS.json')['nodes']
    for row in native_extractions:
        source=Path(row['original_source']['path']);record(source,row['original_source'])
        node=named(ast.parse(read(source)),row['name'])
        target_node=named(ast.parse(read(Path(row['extracted_path']))),row['name'])
        if digest(node)!=row['ast_sha256'] or digest(target_node)!=row['ast_sha256']:
            raise RuntimeError('Native scientific AST drift: '+row['name'])
    reviewed=load(OUT/'AF9_REVIEWED_SOURCE_PINS.json')
    for item in reviewed['reviewed_source_census'].values():record(Path(item['path']),item)
    record(Path(reviewed['delivery_manifest']['path']),reviewed['delivery_manifest'])
    record(Path(reviewed['independent_source_review']['path']),reviewed['independent_source_review'])
    pins = load(notice_delays / 'PINNED_SOURCES.json')
    inherited = []
    removed = []
    for row in pins['files']:
        if 'consumer_path' in row or 'tables' in row.get('path', ''):
            removed.append(row)
        else:
            inherited.append(record(Path(row['path']), row))
    original_numeric = []
    for group in ('source_functions', 'delay_source_functions'):
        for row in pins[group]:
            record(Path(row['path']), row)
            original_numeric.extend(dict(r, group=group) for r in functions(Path(row['path']), row['functions']))
    baseline = load(PROJ / 'paper_plan/nof12_path_20261009/INVENTORY.json')['source_snapshots']
    old_t5_candidates = {r['path']:r for r in load(notice_delays/'T5_ROWS.json')['current_metadata_rows'] if 'path' in r}
    preserved = []
    for path in [notice_delays/'code/anchor_reader.py', notice_delays/'code/anchor_delays.py', notice_delays/'code/joint_record.py',
        notice_delays/'JOINT_RECORD_SCHEMA.json', notice_delays/'INTERFACE_FOR_FILL_AND_A8POST.md']:
        key = str(path.relative_to(PROJ))
        preserved.append(record(path, baseline[key] if key in baseline else old_t5_candidates[str(path)]))
    if read(notice_delays/'JOINT_RECORD_SCHEMA.json') != read(OUT/'evaluator/JOINT_RECORD_SCHEMA.json'):
        raise RuntimeError('Joint schema copy drift')
    checkpoints.append(resources())
    r2_source = record(R2/'APPROVED_NEWS_SOURCE.json', baseline[str((R2/'APPROVED_NEWS_SOURCE.json').relative_to(PROJ))])
    r2 = load(R2/'APPROVED_NEWS_SOURCE.json')
    r2_pins = [record(PROJ/path, sha) for path, sha in r2['source_pins'].items()]
    r2_callables = []
    for row in r2['source_functions']:
        r2_callables.extend(functions(PROJ/row['path'], row['functions']))
    af_delivery = load(AF/'availability_delays/DELIVERY_MANIFEST_FORECAST_BINDING9.json')
    af_source_rows = {**af_delivery['anchorreader_direct_sources'], **af_delivery['anchorreader_transitive_runtime_sources']}
    af9_sources = [record(Path(row['path']), row) for row in af_source_rows.values()]
    af9_receipt = record(Path(af_delivery['new_full_suite_receipt']['path']), af_delivery['new_full_suite_receipt'])

    af9_review = record(AF/'availability_delays/REVIEW2_IMPLEMENTATION_CHECK_20261008_source.md')
    af_paper = load(Path(reviewed['delivery_manifest']['path']))
    if af_paper['phase'] != 'accept' or af_paper['own_source_census'] != reviewed['reviewed_source_census']:
        raise RuntimeError('AF accepted delivery changed')
    af_candidates = [record(Path(row['path']),row) for row in af_paper['own_runtime10'].values()]
    c_paper=load(C/'statistics/C_SOURCE_INTERFACE_STABLE_V1.json')
    if c_paper['stable'] is not True or c_paper['owner_agreed'] is not True or c_paper['source_inventory_finalization_pending'] is not False:
        raise RuntimeError('Stable C source V1 changed')
    for row in [*c_paper['files'].values(),*c_paper['interface_metadata_files'].values()]:record(Path(row['path']),row)
    c_names = ['AP_ROUTE_INTERFACE.md', 'G42_ELIGIBILITY_INTERFACE.md', 'science_contract.py']

    c_observed = []
    c_drift = []
    for name in c_names:
        actual = record(C/'statistics'/name)
        expected = load(AF/'statistics/C_INTERFACE_SOURCE_PINS.json')['files'][name]
        c_observed.append(actual)
        if actual != expected:
            c_drift.append(dict(expected=expected, observed=actual, disposition='SET FIRST/PENDING; no pin or reuse'))
    checkpoints.append(resources())
    own_callables, imports, unresolved = [], [], []
    allowed = {'ast','builtins','copy','datetime','decimal','hashlib','json','math','os','pathlib','re','resource',
        'subprocess','symtable','sys','tempfile','unittest','evaluator','source_validator','numerical_inputs','original_projection',
        'argparse','importlib','inspect','types','io','gc','time','signal','numpy','pandas','jsonschema','native',
        'forecast_metadata','freeze_layout','dispatcher_entry','acceptance_preflight','campaign_control','freeze_notice_evaluation',
        'read_comparisons','score_batch','frozen_losses','parity_gate','runtime_bridge','freeze_science','source_inventory',
        'test_native_reader','test_native_joint','test_native_delays','contextlib','batch_layers','prediction_set','psutil','__future__'}

    files = sorted([*OUT.glob('*.py'), *OUT.joinpath('evaluator').glob('*.py'),
        *OUT.joinpath('tests').glob('*.py'), *OUT.joinpath('tools').glob('*.py'), *OUT.joinpath('native').glob('*.py')])
    for path in files:
        data = read(path).decode()
        tree = ast.parse(data, filename=str(path))
        own_callables.extend(functions(path))
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                modules = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                modules = [('.'*n.level) + (n.module or '')]
            else:
                continue
            if any(not m.startswith('.') and m.split('.')[0] not in allowed for m in modules):
                raise RuntimeError('Unexpected import: ' + str(modules))
            imports.append(dict(path=str(path), line=n.lineno, modules=modules))
        if path.name in {'_scalar.py', '_predicates.py', '_joint_comparisons.py', 'original_projection.py', 'reader.py', 'delays.py'}:
            table = symtable.symtable(data, str(path), 'exec')
            top = set(table.get_identifiers()) | set(dir(builtins))
            def closure(child):
                for symbol in child.get_symbols():
                    if symbol.is_referenced() and symbol.is_global() and symbol.get_name() not in top:
                        unresolved.append(dict(path=str(path), scope=child.get_name(), name=symbol.get_name()))
                for nested in child.get_children():
                    closure(nested)
            for child in table.get_children():
                closure(child)
    if unresolved:
        raise RuntimeError('Missing pure helper closure: ' + str(unresolved))

    oracle_tree = ast.parse(read(OUT/'tests/original_projection.py'))
    original_max = [n for n in ast.walk(oracle_tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == 'max' and n.args and isinstance(n.args[0], ast.Name) and n.args[0].id == 'own_exclusions']
    new_max = [n for n in ast.walk(ast.parse(read(OUT/'evaluator/api.py'))) if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name) and n.func.id == 'max']
    if len(original_max) != 1 or len(new_max) != 1:
        raise RuntimeError('D24 max expression census')
    original_max[0].args[0].id = 'candidates'
    if digest(original_max[0]) != digest(new_max[0]):
        raise RuntimeError('D24 maximum expression drift')
    legacy = []
    for path in sorted((notice_delays/'tests').glob('test_*.py')):
        tree = ast.parse(read(path))
        tests = [dict(name=n.name, lines=[n.lineno,n.end_lineno],ast_sha256=digest(n)) for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name.startswith('test_')]
        legacy.append(dict(source=ident(path), methods=tests, acceptance_executed=False))
    end = resources()
    receipt = dict(schema='RD7_SCORING_PREPARE_STATIC_CHECK_V1', state='STATIC_INSPECTION_COMPLETE_FINAL_DEPENDENCIES_PENDING',
        phase=os.environ.get('SCORING_PHASE','prepare'), extracted_AST_count=len(copied), extracted_nodes=copied,
        native_exact_AST_count=len(native_extractions), native_exact_ASTs=native_extractions,
        pure_helper_unresolved_globals=unresolved, imports=imports, own_python_files=[ident(p) for p in files],
        own_callable_AST_inventory=own_callables, preserved_parent_sources=preserved,
        inherited_nonwriting_source_pins=inherited, removed_whole_FILL_pin_rows=removed,
        original_numerical_function_inventory=original_numeric,
        news_source=dict(approved_source=r2_source, runtime_files=[record(PROJ/p) for p in r2['runtime_files']],
            all_inherited_pins=r2_pins, source_function_ASTs=r2_callables, production_authority=False),
        forecast_binding9=dict(final_original_sources=af9_sources,inherited_clean_receipt_identity=af9_receipt,
            inherited_Part_A_review=af9_review,new_scientific_candidates=af_candidates,
            new_scientific_acceptance=reviewed['scientific_acceptance'], new_scientific_Part_A=record(Path(reviewed['independent_source_review']['path']))),
        c_scientific_interface=dict(status='OBSERVED_PREPARE_PAPER_NOT_FINAL_PIN',sources=c_observed,drift=c_drift),
        legacy_regression_migration_census=legacy,
        resources=dict(start=start,checkpoints=checkpoints,end=end,nice_request='nice -n 20',
            nice_request_result='setpriority refused; inherited nice20 verified via os.getpriority'),
        numerical_tests_run=0,numerical_predicates_executed=False,
        independent_review=None,writing_roots_unavailable_dynamic_check='NOT_RUN_PREPARE',
        production_authority=False, actual_T5_grant=False)
    destination.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(state=receipt['state'], copied_ASTs=len(copied), own_python_files=len(files),
        legacy_methods=sum(len(r['methods']) for r in legacy),free_memory_percent=end['free_memory_percent'],
        numerical_tests_run=0),ensure_ascii=False))


if __name__ == '__main__':
    main()
