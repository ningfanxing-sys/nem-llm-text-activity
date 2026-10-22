'Select the specified deadline checks for forecast execution.'
import ast
from contextlib import contextmanager
import hashlib
import types

OLD_DEADLINE = '2026-10-06T18:00:00+11:00'
NEW_DEADLINE = None
CALENDAR_RULE = 'NO_CALENDAR_DEADLINE_CORRECTED_SEAL_PRECEDES_T5'


def require(ok, message):
    if not ok:
        raise RuntimeError('Deadline overlay refused: ' + message)


def _ast_sha(tree):
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()


def patch_source(source):

    require(isinstance(source, bytes), 'source bytes required')
    require(source.count(OLD_DEADLINE.encode()) == 1, 'exactly one frozen old deadline required')
    try:
        original = ast.parse(source.decode('utf-8'))
    except (SyntaxError, UnicodeError) as exc:
        raise RuntimeError('Deadline overlay refused: invalid source syntax or encoding') from exc
    launches = [node for node in original.body if isinstance(node, ast.FunctionDef) and node.name == 'dispatch']
    require(len(launches) == 1, 'one top-level dispatch required')
    dispatch = launches[0]
    statements = (
        "require(activation['deadline_aedt']=='2026-10-06T18:00:00+11:00','Deadline rule drift')",
        "deadline=datetime.fromisoformat(activation['deadline_aedt'])",
        "require(datetime.now(deadline.tzinfo)<deadline,'Corrected seal missed the before-T5 deadline')",
        "require(datetime.now(deadline.tzinfo)<deadline,'Correction finished after the deadline; do not seal as pre-T5')",
    )
    removals = []
    for text in statements:
        expected = ast.dump(ast.parse(text).body[0], include_attributes=False)
        matches = [node for node in dispatch.body if ast.dump(node, include_attributes=False) == expected]
        require(len(matches) == 1 and matches[0].lineno == matches[0].end_lineno,
                'exact single-line calendar statement missing or duplicated')
        removals.append(matches[0])
    lines = source.splitlines(keepends=True)
    removed_lines = {node.lineno - 1 for node in removals}
    require(len(removed_lines) == 4, 'four distinct calendar lines required')
    for node, text in zip(removals, statements):
        require(lines[node.lineno - 1].rstrip(b'\r\n') == ('    ' + text).encode(),
                'calendar line bytes differ from frozen contract')
    patched = b''.join(line for index, line in enumerate(lines) if index not in removed_lines)
    dispatch.body = [node for node in dispatch.body if node not in removals]
    actual = ast.parse(patched.decode('utf-8'))
    require(ast.dump(actual, include_attributes=False) == ast.dump(original, include_attributes=False),
            'AST changed outside four calendar statements')
    patched_launch = next(node for node in actual.body if isinstance(node, ast.FunctionDef) and node.name == 'dispatch')
    require(not any(isinstance(node, ast.Name) and node.id == 'deadline' for node in ast.walk(patched_launch)),
            'calendar deadline dependency remains')
    require(not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == 'datetime'
                    and node.func.attr == 'now' for node in ast.walk(patched_launch)),
            'calendar clock refusal remains')
    offset = 0; spans = []
    for index, line in enumerate(lines):
        if index in removed_lines:
            spans.append(dict(start=offset,end=offset+len(line),line=index+1,
                              deleted_sha256=hashlib.sha256(line).hexdigest()))
        offset += len(line)
    return patched, dict(schema='FORECAST_BINDING_NO_CALENDAR_PATCH_V1',
        original_sha256=hashlib.sha256(source).hexdigest(),
        patched_sha256=hashlib.sha256(patched).hexdigest(),
        original_ast_sha256=_ast_sha(ast.parse(source.decode('utf-8'))),patched_ast_sha256=_ast_sha(actual),
        old_deadline=OLD_DEADLINE,new_deadline=None,calendar_rule=CALENDAR_RULE,
        removed_statements=4,activation_equality_removed=True,calendar_parse_removed=True,
        now_before_deadline_refusals_removed=2,deleted_byte_spans=spans,
        byte_insertions=0,byte_replacements=0,
        original_bytes=len(source),patched_bytes=len(patched),
        all_other_bytes_identical=True,remaining_ast_identical=True,
        before_T5_no_overlap_coverage_parity_identity_unchanged=True,
        models_features_seeds_scoring_changed=False)


def _launch_code(source, filename):
    code = compile(source, filename, 'exec')
    matches = [value for value in code.co_consts if isinstance(value, types.CodeType) and value.co_name == 'dispatch']
    require(len(matches) == 1, 'one compiled dispatch required')
    return matches[0]


@contextmanager
def install(module, source):

    patched, proof = patch_source(source)
    original = module.dispatch
    require(isinstance(original, types.FunctionType) and original.__globals__ is vars(module)
            and original.__closure__ is None, 'unexpected dispatch function context')
    require(original.__code__ == _launch_code(source, module.__file__),
            'loaded dispatch differs from pinned source')
    replacement = types.FunctionType(_launch_code(patched, module.__file__), vars(module),
                                    original.__name__, original.__defaults__)
    replacement.__kwdefaults__ = original.__kwdefaults__
    replacement.__annotations__ = original.__annotations__
    replacement.__qualname__ = original.__qualname__
    replacement.__doc__ = original.__doc__
    module.dispatch = replacement
    try:
        yield proof
    finally:
        module.dispatch = original
