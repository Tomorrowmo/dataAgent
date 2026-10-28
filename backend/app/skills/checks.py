"""Static checks for skill-pack python files.

A skill pack is MORE trusted than an AI-generated algorithm (the user wrote it
deliberately and installed it themselves) and LESS trusted than the built-ins
(it did not go through review). So the rule set differs from
`sandbox/validator.py` on purpose:

  allowed here but not there : `open`, its own bundled modules, `os.path`/
                               `pathlib`, any third-party lib it declares in
                               `requires` (a pack that needs `openpyxl` is a
                               normal thing to want)
  still forbidden            : starting processes, sockets/HTTP, ctypes,
                               importlib/pickle tricks, and the filesystem
                               calls that DESTROY things (rm/rmtree/chmod)

The boundary is stated plainly in the authoring spec, so the author can predict
what will be rejected instead of discovering it at install time.

`command` runtime is out of scope for these checks by definition — an arbitrary
executable can't be statically reasoned about. That's exactly why it is gated
behind an explicit setting + admin, and flagged in the install report.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set

# Import roots a pack may never touch. Network, process spawning, and the
# dynamic-import / deserialization escapes that make the rest pointless.
FORBIDDEN_IMPORT_ROOTS: Set[str] = {
    "subprocess", "socket", "socketserver", "ssl", "ctypes", "cffi",
    "multiprocessing", "concurrent", "asyncio", "signal", "pty", "tty", "fcntl",
    "importlib", "imp", "runpy", "pickle", "cPickle", "shelve", "marshal", "dill",
    "requests", "httpx", "aiohttp", "urllib3", "http", "ftplib", "smtplib",
    "telnetlib", "paramiko", "webbrowser", "xmlrpc", "pip", "setuptools",
    "distutils", "sysconfig", "pdb", "code", "codeop", "atexit", "gc",
}
# `urllib` is only dangerous via `urllib.request`; `urllib.parse` is pure string
# work and packs legitimately use it.
FORBIDDEN_SUBMODULES: Set[str] = {"urllib.request", "urllib.error", "os.path.exec"}

# Names that hand back an unchecked execution primitive.
FORBIDDEN_NAMES: Set[str] = {"eval", "exec", "compile", "__import__", "breakpoint", "input"}

# Attribute calls that either run something or delete something.
FORBIDDEN_ATTR_CALLS: Set[str] = {
    "system", "popen", "spawn", "spawnl", "spawnv", "spawnve", "execv", "execve", "execl",
    "fork", "forkpty", "kill", "killpg", "abort",
    "rmtree", "remove", "unlink", "rmdir", "removedirs", "chmod", "chown", "truncate",
    "setuid", "setgid", "startfile", "check_output", "check_call", "call", "run",
}
# …but only when called on one of these modules/objects. `df.run(...)` or a
# pack's own `self.call()` are fine; `os.system(...)` / `shutil.rmtree(...)` are not.
DANGEROUS_CALL_ROOTS: Set[str] = {"os", "sys", "shutil", "subprocess", "pathlib", "Path", "sh"}

FORBIDDEN_ATTRS: Set[str] = {
    "__class__", "__bases__", "__subclasses__", "__mro__",
    "__globals__", "__getattribute__", "__reduce__", "__reduce_ex__",
    "__code__", "__closure__",
}


@dataclass
class FileCheck:
    file: str
    ok: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)


@dataclass
class PackCheck:
    ok: bool
    files: List[FileCheck] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "files": [
                {"file": f.file, "ok": f.ok, "errors": f.errors,
                 "warnings": f.warnings, "imports": f.imports}
                for f in self.files
            ],
        }


def local_module_names(root: Path) -> Set[str]:
    """Top-level importable names the pack ships itself (packages and modules).

    These are what makes `from lib.core import x` legal inside a pack — without
    this the import check would reject a pack for importing its own code, which
    is the single most confusing rejection possible."""
    names: Set[str] = set()
    for p in root.iterdir():
        if p.name.startswith(".") or p.name.startswith("__"):
            continue
        if p.is_dir():
            names.add(p.name)
        elif p.suffix == ".py":
            names.add(p.stem)
    return names


def check_source(source: str, rel_path: str, *, local: Set[str], extra_allowed: Set[str]) -> FileCheck:
    fc = FileCheck(file=rel_path, ok=True)
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        fc.ok = False
        fc.errors.append(f"SyntaxError: line {e.lineno}: {e.msg}")
        return fc

    def _reject(node: ast.AST, msg: str) -> None:
        fc.errors.append(f"line {getattr(node, 'lineno', '?')}: {msg}")

    def _check_import(node: ast.AST, dotted: str) -> None:
        fc.imports.append(dotted)
        root = dotted.split(".")[0]
        if dotted in extra_allowed or root in extra_allowed or root in local:
            return
        if dotted in FORBIDDEN_SUBMODULES:
            _reject(node, f"不允许 import {dotted}(技能包不能联网)")
            return
        if root in FORBIDDEN_IMPORT_ROOTS:
            _reject(node, f"不允许 import {dotted} —— 技能包不能起进程/联网/动态加载代码。"
                          "需要外部数据请让用户先导入成数据集。")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _check_import(node, alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # relative import inside the pack — that's its own code
            _check_import(node, node.module or "")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            if isinstance(getattr(node, "ctx", None), ast.Store):
                continue
            _reject(node, f"不允许使用 `{node.id}`")
        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_ATTRS:
                _reject(node, f"不允许访问 `{node.attr}`")
            elif node.attr in FORBIDDEN_ATTR_CALLS:
                base = node.value
                base_name = base.id if isinstance(base, ast.Name) else (
                    base.attr if isinstance(base, ast.Attribute) else "")
                if base_name in DANGEROUS_CALL_ROOTS:
                    _reject(node, f"不允许调用 `{base_name}.{node.attr}` —— "
                                  "技能包不能删除文件或启动外部进程。")

    fc.ok = not fc.errors
    return fc


def _module_to_rel(root: Path, dotted: str) -> str | None:
    """Map an import name to a file inside the pack, if it is the pack's own code."""
    parts = dotted.split(".")
    for cand in (root.joinpath(*parts).with_suffix(".py"),
                 root.joinpath(*parts) / "__init__.py"):
        if cand.is_file():
            return str(cand.relative_to(root)).replace("\\", "/")
    return None


def reachable_files(root: Path, entry_modules: Set[str]) -> Set[str]:
    """Which .py files can actually RUN — i.e. are reachable from a declared tool
    entry by static imports.

    This matters because packs downloaded from elsewhere routinely ship helper
    scripts that were written for a different runtime (a CLI, another agent) and
    are not wired to any tool here. Nothing can invoke them: only declared
    entries get imported, and dynamic import is forbidden — so a violation in
    one of those files is a WARNING, not a reason to refuse the whole pack.
    """
    root = Path(root)
    seen: Set[str] = set()
    queue = [m for m in entry_modules if m]
    while queue:
        rel = _module_to_rel(root, queue.pop())
        if rel is None or rel in seen:
            continue
        seen.add(rel)
        try:
            tree = ast.parse((root / rel).read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        pkg = rel.rsplit("/", 1)[0].replace("/", ".") if "/" in rel else ""
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                queue.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level and pkg:  # `from . import x` inside a sub-package
                    base = f"{pkg}.{base}" if base else pkg
                if base:
                    queue.append(base)
                    queue.extend(f"{base}.{a.name}" for a in node.names)
    return seen


def check_pack(root: Path, *, requires: Set[str] | None = None,
               skip: Set[str] | None = None,
               entry_modules: Set[str] | None = None) -> PackCheck:
    """Static-check every .py file in the pack.

    `entry_modules` = the modules declared as tool entry points. Violations in
    files reachable from them BLOCK the install; violations elsewhere are
    reported as warnings (that code can never be executed by this app)."""
    root = Path(root)
    local = local_module_names(root)
    extra = set(requires or ())
    skip = skip or set()
    res = PackCheck(ok=True)

    py_files = sorted(p for p in root.rglob("*.py")
                      if "__pycache__" not in p.parts and p.name not in skip)
    live = reachable_files(root, set(entry_modules or ()))

    for p in py_files:
        rel = str(p.relative_to(root)).replace("\\", "/")
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            res.files.append(FileCheck(file=rel, ok=False, errors=[f"读不出来:{e}"]))
            continue
        fc = check_source(src, rel, local=local, extra_allowed=extra)
        if fc.errors and rel not in live:
            # Ships with the pack but nothing here can run it — demote to a warning
            # so a stray helper script doesn't block an otherwise fine pack.
            fc.warnings.extend(
                f"{e}(该文件不是任何工具的入口、也没被入口引用,不会被执行)" for e in fc.errors
            )
            fc.errors = []
            fc.ok = True
        res.files.append(fc)

    res.errors = [f"{f.file}: {e}" for f in res.files for e in f.errors]
    res.warnings.extend(f"{f.file}: {w}" for f in res.files for w in f.warnings)
    res.ok = not res.errors
    if not py_files:
        res.warnings.append("包里没有 .py 文件(纯知识包)。")
    return res
