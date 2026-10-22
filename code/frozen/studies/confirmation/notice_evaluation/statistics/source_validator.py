'Compare source hashes and ASTs with the required file list.'
import ast
import hashlib
from pathlib import Path
from evaluator.validation import exact_identity, require


def checked_public_source(item, *, permitted_paths):
    exact_identity(item)
    path = Path(item['path'])
    require(item['path'] in permitted_paths, 'Unlisted source path')
    require(not any(part.lower() in {'host_state', 'predictions', 'scores', 'scored', 'sealed', 'run', 'evaluation'}
        for part in path.parts), 'Protected source root')
    require(path.suffix == '.py' or not path.name.upper().startswith(('SEAL_', 'SCORE_')), 'Payload-like identity refused')
    require(path.suffix in {'.py', '.md', '.json', '.sha256', '.txt'}, 'Not public source/metadata')
    if path.suffix == '.json':
        require(path.name in {'APPROVED_NEWS_SOURCE.json', 'PARENT_PINS.json', 'PINNED_SOURCES.json',
            'JOINT_RECORD_SCHEMA.json', 'ORIGINAL_SOURCE_AST_INVENTORY.json', 'PUBLIC_SOURCE_CONTRACT.json',
            'SCIENTIFIC_ACCEPTANCE_SPEC.json', 'NUMERICAL_INTERFACE.json', 'SOURCE_LOCK.json',
            'DEPENDENCY_PINS.json', 'MODEL_CUTOFF_RECORD.json', 'SCIENTIFIC_FREEZE.schema.json',
            'T4I_RESULT.json', 'T4J_RESULT.json', 'T4K_RESULT.json', 'RULES_FOR_TABLE_RESULTS.json',
            'AF9_REVIEWED_SOURCE_PINS.json', 'C_INTERFACE_SOURCE_OBSERVATION.json',
            'RUNTIME_CENSUS.json', 'ACCEPTANCE_CENSUS.json'}, 'Not a declared scientific metadata basename')

    require(path.resolve() == path and all(not parent.is_symlink() for parent in (path, *path.parents)), 'Source alias/symlink')
    require(path.is_file(), 'Source is not a regular file')
    reference_snapshot = path.stat()
    require(reference_snapshot.st_size <= 16 * 1024 * 1024, 'Bounded public source required')
    data = path.read_bytes()
    after = path.stat()
    require((reference_snapshot.st_dev, reference_snapshot.st_ino, reference_snapshot.st_size, reference_snapshot.st_mtime_ns, reference_snapshot.st_ctime_ns) ==
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'Source changed during read')
    require(len(data) == item['bytes'] and hashlib.sha256(data).hexdigest() == item['sha256'], 'Source identity drift')
    return data


def verify_source_contract(contract):
    require(isinstance(contract, dict) and set(contract) == {'schema', 'runtime_sources', 'callable_asts'},
            'Closed public source contract fields')
    require(contract.get('schema') == 'RD_SCORING_PUBLIC_SOURCE_CONTRACT_V1', 'Source contract schema')
    rows = contract['runtime_sources']
    require(isinstance(rows, list) and rows and len(rows) == len({r['path'] for r in rows}), 'Finite source census')
    permitted = {r['path'] for r in rows}
    require(not any('/tables/table_renderer/' in p for p in permitted), 'Whole FILL runtime dependency refused')
    snapshots = {r['path']: checked_public_source(r, permitted_paths=permitted) for r in rows}
    callables = contract['callable_asts']
    require(isinstance(callables, list) and callables and
        len(callables) == len({(item['path'], item['name']) for item in callables}), 'Finite callable census')
    for item in callables:
        require(set(item) == {'path', 'name', 'ast_sha256'}, 'Callable identity fields')
        require(item['path'] in snapshots and Path(item['path']).suffix == '.py', 'AST must belong to checked source')
        tree = ast.parse(snapshots[item['path']], filename=item['path'])
        matches = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == item['name']]
        require(len(matches) == 1, 'Callable census drift')
        digest = hashlib.sha256(ast.dump(matches[0], include_attributes=False).encode()).hexdigest()
        require(digest == item['ast_sha256'], 'Callable AST drift')
    return dict(source_integrity_verified=True, production_authority=False,
        verified_paths=sorted(snapshots), eligibility_granted=False)
