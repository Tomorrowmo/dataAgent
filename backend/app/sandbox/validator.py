"""Static AST validation for user/AI-generated algorithm code.

We can't make Python truly safe by static checks alone, but we can catch the
obvious bad patterns before paying for a subprocess spin-up. The subprocess
itself provides the real isolation.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import List, Set

# Modules the user code is allowed to import. Anything outside this list is
# rejected up-front. We deliberately keep this tight — adding to it is cheap,
# removing is hard.
ALLOWED_IMPORTS: Set[str] = {
    "math", "statistics", "numbers", "fractions", "decimal", "cmath",
    "itertools", "functools", "operator", "collections", "heapq", "bisect",
    "typing", "dataclasses", "enum", "copy", "re", "json", "string",
    "datetime", "time",  # `time.sleep` is OK — sandbox will time out anyway
    "numpy", "pandas", "scipy", "sklearn", "sklearn.preprocessing",
    "sklearn.decomposition", "sklearn.linear_model", "sklearn.cluster",
    "sklearn.metrics", "sklearn.ensemble", "sklearn.model_selection",
    "sklearn.tree", "sklearn.neighbors", "sklearn.svm", "sklearn.pipeline",
    "scipy.stats", "scipy.signal", "scipy.optimize", "scipy.interpolate",
    "scipy.linalg", "scipy.fft", "scipy.spatial",
}

FORBIDDEN_NAMES: Set[str] = {
    "eval", "exec", "compile", "__import__", "open",
    "globals", "locals", "vars",
    "input",
}

# Parser-mode validation drops `open` from the forbidden set so adapters can
# read binary input files. Everything else stays restricted.
PARSER_FORBIDDEN_NAMES: Set[str] = FORBIDDEN_NAMES - {"open"}

# Extra modules useful for binary / text format parsing — added on top of
# ALLOWED_IMPORTS when validating parser-mode code.
PARSER_EXTRA_IMPORTS: Set[str] = {
    "struct", "io", "gzip", "zipfile", "bz2", "binascii", "base64",
    "csv", "xml", "xml.etree", "xml.etree.ElementTree", "configparser",
    "yaml",        # PyYAML — text configs / metadata files
    "tomllib",     # stdlib in 3.11+
    "html",  "html.parser",
    "string",
    "warnings",    # parsers often want warnings.filterwarnings
    "pathlib",     # safe — just path manipulation
    "urllib.parse",  # parsing URLs in CSV-like data; no network access
}

FORBIDDEN_ATTRS: Set[str] = {
    "__class__", "__bases__", "__subclasses__", "__mro__",
    "__globals__", "__getattribute__", "__reduce__", "__reduce_ex__",
    "__code__", "__closure__", "__dict__",
}


@dataclass
class ValidationResult:
    ok: bool
    errors: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    has_run_function: bool = False
    has_meta: bool = False


def validate_algorithm_code(source: str, *, mode: str = "algorithm") -> ValidationResult:
    """Validate user-supplied code.

    mode='algorithm' — expects a top-level `run(df, **params)` function AND a
                      top-level `META` dict. `open` is forbidden.
    mode='viz'       — AI-written chart code: expects `run(df, **params)` that
                      returns a chart-spec dict. NO `META` required (it's not a
                      library algorithm, just a one-off chart builder).
    mode='parser'    — expects a top-level `parse(path, **kwargs)` function.
                      `open` is allowed (parsers read binary files).
    """
    res = ValidationResult(ok=True)
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        res.ok = False
        res.errors.append(f"SyntaxError: {e}")
        return res

    expected_fn = "parse" if mode == "parser" else "run"
    forbidden_names = PARSER_FORBIDDEN_NAMES if mode == "parser" else FORBIDDEN_NAMES
    allowed_imports = ALLOWED_IMPORTS | PARSER_EXTRA_IMPORTS if mode == "parser" else ALLOWED_IMPORTS

    found_entry = False
    found_meta = False

    # A top-level `META = {...}` assignment, checked statically (no exec). Only
    # required for algorithm mode — parsers describe themselves differently.
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "META" for t in node.targets
        ) and isinstance(node.value, ast.Dict):
            found_meta = True
            break

    for node in ast.walk(tree):
        # Imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if alias.name not in allowed_imports and root not in allowed_imports:
                    res.errors.append(f"import not allowed: {alias.name}")
                res.imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                res.errors.append("relative imports are not allowed")
                continue
            root = node.module.split(".")[0]
            if node.module not in allowed_imports and root not in allowed_imports:
                res.errors.append(f"import not allowed: {node.module}")
            res.imports.append(node.module)

        # Forbidden builtin names
        elif isinstance(node, ast.Name) and node.id in forbidden_names:
            if isinstance(getattr(node, "ctx", None), ast.Store):
                continue
            res.errors.append(f"use of '{node.id}' is not allowed")

        # Dunder access
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
            res.errors.append(f"access to '{node.attr}' is not allowed")

        # Expected entry-point function
        elif isinstance(node, ast.FunctionDef) and node.name == expected_fn:
            found_entry = True

    res.has_run_function = found_entry
    if not found_entry:
        res.errors.append(f"missing top-level function `{expected_fn}(...)`")

    # META is part of the接入规范 for algorithms (not parsers). Flag it here so
    # the upload UI can show a precise conformance checklist instead of letting
    # the user discover it only when save → parse_meta fails.
    res.has_meta = found_meta
    if mode == "algorithm" and not found_meta:
        res.errors.append("missing top-level META dict (须定义顶级 META 字典)")

    res.ok = len(res.errors) == 0
    return res
