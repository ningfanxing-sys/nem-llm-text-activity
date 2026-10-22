'Read notice creation dates day first within the specified input format.'
from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import re
import textwrap
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

STRICT_ANCHOR_PATTERN = r"^\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}$"
STRICT_ANCHOR = re.compile(STRICT_ANCHOR_PATTERN)
ANCHOR_FORMAT = "%d/%m/%Y %H:%M:%S"
HELPER_NAME = '_forecast_binding_parse_anchor_strict_v1'
LOADER_HELPER_NAME = '_forecast_binding_loader_anchor_strict_v1'
FROZEN_FUNCTION_AST_SHA256 = {
    "normalize_notice": "8b7c3189632910be7c693676c81f032c714c50ca02433276e08e23b9d8e3a066",
    "load_host_notices": "013288d3c7654d2305bd0c789f82180740cf69080c84cafa10dca6cbd2597a09",
    "notice_feature_rows": "5f8cca5a34e0124214d26866fb49d596a1f79d2f50ae707c838588c9dfb197e9",
}
_TARGET_EXPRESSIONS = {
    "normalize_notice": "pd.Timestamp(anchor)",
    "load_host_notices": "clock.get('raw_time_local')",
    "notice_feature_rows": "pd.Timestamp(n.get('anchor_local') or pd.Timestamp(n['available_utc']).tz_convert('Australia/Brisbane').tz_localize(None))",
}


def _is_strict_anchor(value):
    return isinstance(value, str) and STRICT_ANCHOR.fullmatch(value) is not None


def parse_anchor(value):
    'Parse the specified DD/MM/YYYY format day first.'
    if _is_strict_anchor(value):
        return pd.Timestamp(datetime.strptime(value, ANCHOR_FORMAT))
    return pd.Timestamp(value)


def loader_anchor(value):

    return parse_anchor(value) if _is_strict_anchor(value) else value


def _dump(node):
    return ast.dump(node, include_attributes=False)


def _ast_hash(node):
    return hashlib.sha256(_dump(node).encode("utf-8")).hexdigest()


def _function_tree(source, name):
    tree = ast.parse(textwrap.dedent(source))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(nodes) != 1:
        raise ValueError('forecast_hashes expected exactly one function: ' + name)
    return tree, nodes[0]


def transform_function_source(source, name):

    if name not in FROZEN_FUNCTION_AST_SHA256:
        raise ValueError('forecast_hashes unsupported function: ' + name)
    _, original = _function_tree(source, name)
    reference_snapshot = _ast_hash(original)
    if reference_snapshot != FROZEN_FUNCTION_AST_SHA256[name]:
        raise ValueError('forecast_hashes frozen function AST drift: ' + name)
    patched = copy.deepcopy(original)
    target = ast.parse(_TARGET_EXPRESSIONS[name], mode="eval").body
    target_dump = _dump(target)
    helper = LOADER_HELPER_NAME if name == "load_host_notices" else HELPER_NAME
    expected_argument = target if name == "load_host_notices" else target.args[0]

    class ReplaceSite(ast.NodeTransformer):
        count = 0

        def visit_Call(self, node):
            if _dump(node) == target_dump:
                self.count += 1
                return ast.copy_location(ast.Call(
                    func=ast.Name(id=helper, ctx=ast.Load()),
                    args=[copy.deepcopy(expected_argument)], keywords=[]), node)
            return self.generic_visit(node)

    replacer = ReplaceSite()
    patched = replacer.visit(patched)
    if replacer.count != 1:
        raise ValueError('forecast_hashes expected one AST target in ' + name)
    ast.set_missing_locations(patched)


    restored = copy.deepcopy(patched)

    class RestoreSite(ast.NodeTransformer):
        count = 0

        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id == helper:
                if (len(node.args) != 1 or node.keywords or
                        _dump(node.args[0]) != _dump(expected_argument)):
                    raise ValueError('forecast_hashes inserted helper argument drift')
                self.count += 1
                return ast.copy_location(copy.deepcopy(target), node)
            return self.generic_visit(node)

    reverse = RestoreSite()
    restored = reverse.visit(restored)
    if reverse.count != 1 or _dump(restored) != _dump(original):
        raise ValueError('forecast_hashes changed syntax beyond the allowed anchor site')
    module = ast.Module(body=[patched], type_ignores=[])
    ast.set_missing_locations(module)
    receipt = {
        "function": name,
        "original_function_ast_sha256": reference_snapshot,
        "patched_function_ast_sha256": _ast_hash(patched),
        "target_expression_ast_sha256": _ast_hash(target),
        "target_expression": _TARGET_EXPRESSIONS[name],
        "target_count": replacer.count,
        "reverse_target_count": reverse.count,
        "all_other_function_ast_equal": True,
        "helper": helper,
    }
    return module, receipt


def source_ast_receipt(nrx_path, features_path):

    sources = {
        'notice_label_adapter': (Path(nrx_path), Path(nrx_path).read_text()),
        "features_adapter": (Path(features_path), Path(features_path).read_text()),
    }
    sites = []
    for module, names in (('notice_label_adapter', ("normalize_notice", "load_host_notices")),
                          ("features_adapter", ("notice_feature_rows",))):
        path, source = sources[module]
        for name in names:
            _, receipt = transform_function_source(source, name)
            receipt["module"] = module
            receipt["source_path"] = str(path.resolve())
            sites.append(receipt)
    return {
        "state": "PASS_AST_ONLY_THREE_CREATION_CLOCK_SITES",
        "strict_pattern": STRICT_ANCHOR_PATTERN,
        "strict_format": ANCHOR_FORMAT,
        "sites": sites,
        "source_file_sha256": {
            module: hashlib.sha256(source.encode("utf-8")).hexdigest()
            for module, (_, source) in sources.items()
        },
        "source_files_modified": False,
        "frozen_other_timestamp_calls_unchanged": True,
    }


@contextmanager
def install_patch(nrx, features):

    originals = []
    helpers = []
    sources = []
    site_receipts = []
    targets = ((nrx, "normalize_notice"), (nrx, "load_host_notices"),
               (features, "notice_feature_rows"))


    for module, name in targets:
        fn = getattr(module, name)
        if fn.__globals__ is not vars(module):
            raise ValueError('forecast_hashes function globals do not match its module')
        source = inspect.getsource(fn)
        tree, receipt = transform_function_source(source, name)
        sources.append((module, name, fn, compile(tree, fn.__code__.co_filename, "exec")))
        site_receipts.append(receipt)
    alias_missing = object()
    loader_alias = getattr(features, "load_host_notices", alias_missing)
    if loader_alias is not alias_missing and loader_alias is not nrx.load_host_notices:
        raise ValueError('forecast_hashes features loader alias identity drift')
    for module in (nrx, features):
        for name in (HELPER_NAME, LOADER_HELPER_NAME):
            if name in vars(module):
                raise ValueError('forecast_hashes helper already installed: ' + name)
    receipt = {
        "state": "IN_PROCESS_AST_PATCH_ACTIVE",
        "strict_pattern": STRICT_ANCHOR_PATTERN,
        "strict_format": ANCHOR_FORMAT,
        "sites": site_receipts,
        "feature_loader_alias_rebound": loader_alias is not alias_missing,
        "source_files_modified": False,
        "nonmatching_loader_literals_preserved_by_identity": True,
        "normalization_and_projection_functions_other_ast_equal": True,
        "restored_after_context": False,
    }
    try:
        for module in (nrx, features):
            for name, fn in ((HELPER_NAME, parse_anchor), (LOADER_HELPER_NAME, loader_anchor)):
                vars(module)[name] = fn
                helpers.append((module, name))
        for module, name, original, code in sources:
            originals.append((module, name, original))
            exec(code, vars(module))
        if loader_alias is not alias_missing:
            features.load_host_notices = nrx.load_host_notices
        yield receipt
    finally:
        for module, name, original in reversed(originals):
            setattr(module, name, original)
        if loader_alias is not alias_missing:
            features.load_host_notices = loader_alias
        for module, name in reversed(helpers):
            vars(module).pop(name, None)
        receipt["restored_after_context"] = True
