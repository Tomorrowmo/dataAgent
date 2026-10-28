"""Parse and normalize a skill pack's manifest.

Two authoring styles are accepted, because both are natural and neither should
be a gotcha:

  A) everything in SKILL.md frontmatter (small packs — one file to write)
  B) identity in SKILL.md frontmatter + `tools:` in a sibling skill.yaml
     (bigger packs — keeps the prose file readable)

`load_manifest(dir)` returns a fully normalized SkillManifest plus a list of
warnings. Anything structurally wrong raises ManifestError with a message the
UI can show verbatim — the author must never have to read a traceback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-_]{1,62}$")
TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")  # 单字母工具名也放行,没理由拒
ENTRY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$")

VALID_PARAM_TYPES = {"string", "number", "integer", "boolean", "array", "object"}
VALID_RETURNS = {"dataframe", "series", "dict", "scalar", "artifact", "markdown"}
VALID_RUNTIMES = {"python", "command", "script"}

DOC_NAME_CANDIDATES = ("SKILL.md", "skill.md", "README.md", "readme.md")
MANIFEST_NAME_CANDIDATES = ("skill.yaml", "skill.yml", "SKILL.yaml", "SKILL.yml")


class ManifestError(ValueError):
    """A manifest problem the author must fix. Message is user-facing (中文)."""


@dataclass
class ToolSpec:
    name: str                       # tool id inside the pack, e.g. "capacity_fade"
    title: str = ""                 # human label
    description: str = ""
    runtime: str = "python"         # python | command
    entry: str = ""                 # python: "tools.capacity_fade:run"
    command: List[str] = field(default_factory=list)  # command runtime argv template
    output_file: str = ""           # command runtime: file the program must write
    needs_data: bool = True         # call fn(df, **params) vs fn(**params)
    params_schema: Dict[str, Any] = field(default_factory=dict)
    returns: str = "dataframe"
    aliases: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    tests: List[Dict[str, Any]] = field(default_factory=list)
    timeout_seconds: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name, "title": self.title, "description": self.description,
            "runtime": self.runtime, "entry": self.entry, "command": list(self.command),
            "output_file": self.output_file,
            "needs_data": self.needs_data, "params_schema": self.params_schema,
            "returns": self.returns, "aliases": list(self.aliases),
            "examples": list(self.examples), "tests": list(self.tests),
            "timeout_seconds": self.timeout_seconds,
        }

    @property
    def module(self) -> str:
        return self.entry.split(":", 1)[0] if self.entry else ""

    @property
    def func(self) -> str:
        return self.entry.split(":", 1)[1] if ":" in self.entry else ""


@dataclass
class SkillManifest:
    slug: str
    name: str
    version: str = "0.1.0"
    description: str = ""
    when_to_use: str = ""
    triggers: List[str] = field(default_factory=list)
    category: str = "skill"
    author: str = ""
    doc_file: str = "SKILL.md"
    doc_body: str = ""
    references: List[str] = field(default_factory=list)
    tools: List[ToolSpec] = field(default_factory=list)
    requires: List[str] = field(default_factory=list)  # extra python imports the tools use
    # 通用(标准 Agent Skills)包的痕迹:没写 tools、但带 scripts/,并且 frontmatter 里
    # 常见 allowed-tools / metadata。记下来是为了如实告诉用户"这个包在本系统能用到哪些部分"。
    kind: str = "native"              # native(为本系统写的) | generic(通用 skill 包)
    scripts: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slug": self.slug, "name": self.name, "version": self.version,
            "description": self.description, "when_to_use": self.when_to_use,
            "triggers": list(self.triggers), "category": self.category,
            "author": self.author, "doc_file": self.doc_file,
            "references": list(self.references), "requires": list(self.requires),
            "kind": self.kind, "scripts": list(self.scripts),
            "allowed_tools": list(self.allowed_tools),
            "tools": [t.to_dict() for t in self.tools],
        }

    @property
    def trust(self) -> str:
        """sandbox(检查过的 python)| script(通用包自带脚本)| command(自带可执行程序)。

        script 单独一档:通用 skill 包几乎都带脚本,如果把它们一律当成 command
        (仅管理员可装),那"网上下的包直接能用"就成了空话。所以脚本包**任何人都能装**,
        知识部分立刻可用;真要执行脚本时才受服务端开关约束。"""
        if any(t.runtime == "command" for t in self.tools):
            return "command"
        if any(t.runtime == "script" for t in self.tools):
            return "script"
        return "sandbox"


# ── frontmatter ──────────────────────────────────────────────────────────────

def split_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Split a `---` YAML frontmatter block off the top of a markdown file.

    Returns ({}, whole_text) when there is no frontmatter — a pack whose
    identity lives entirely in skill.yaml is legal."""
    t = text.lstrip("﻿")
    if not t.startswith("---"):
        return {}, text
    m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", t, re.DOTALL)
    if not m:
        return {}, text
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise ManifestError(f"SKILL.md 的 frontmatter 不是合法 YAML:{e}") from e
    if not isinstance(data, dict):
        raise ManifestError("SKILL.md 的 frontmatter 必须是键值对(YAML 映射)。")
    return data, t[m.end():]


def _as_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        parts = re.split(r"[,,;;\n]", v)
        return [p.strip() for p in parts if p.strip()]
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    return [str(v)]


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9\-_]+", "-", (text or "").strip().lower()).strip("-_")
    return s[:60] or "skill"


# ── tool normalization ───────────────────────────────────────────────────────

def _normalize_params_schema(raw: Any, where: str, warnings: List[str]) -> Dict[str, Any]:
    """Accept both the verbose dict-of-dicts form and the shorthand
    `column: string` / `window: {type: integer, default: 5}`."""
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ManifestError(f"{where}: params 必须是映射(参数名 → 说明)。")
    out: Dict[str, Any] = {}
    for pname, pdef in raw.items():
        key = str(pname)
        if isinstance(pdef, str):
            pdef = {"type": pdef}
        if not isinstance(pdef, dict):
            raise ManifestError(f"{where}: 参数 `{key}` 的定义必须是字符串类型名或映射。")
        t = str(pdef.get("type", "string")).lower()
        t = {"int": "integer", "float": "number", "double": "number", "bool": "boolean",
             "list": "array", "columns": "array", "dict": "object", "map": "object"}.get(t, t)
        if t not in VALID_PARAM_TYPES:
            warnings.append(f"{where}: 参数 `{key}` 的类型 `{t}` 不认识,按 string 处理。")
            t = "string"
        entry: Dict[str, Any] = {
            "type": t,
            "description": str(pdef.get("description") or pdef.get("desc") or ""),
            "required": bool(pdef.get("required", False)),
        }
        # `role` 把参数从"我要一个叫 cycle 的列"升级成"我要循环号这个**物理量**"。
        # 有了它,用户教过一次「Cyc_No 是循环号」之后,任何包的任何工具都能认 —— 这是
        # 跨包、跨数据集复用的唯一钩子。不写也行,那就退回按名字字面匹配。
        if pdef.get("role"):
            entry["role"] = str(pdef["role"]).strip()
        if "default" in pdef:
            entry["default"] = pdef["default"]
        if pdef.get("enum"):
            entry["enum"] = list(pdef["enum"])
        if pdef.get("values"):  # object-of-arrays hint, mirrors the builtin registry
            entry["values"] = pdef["values"]
        out[key] = entry
    return out


def _normalize_tool(raw: Dict[str, Any], idx: int, warnings: List[str]) -> ToolSpec:
    where = f"tools[{idx}]"
    if not isinstance(raw, dict):
        raise ManifestError(f"{where}: 每个工具必须是映射。")
    name = str(raw.get("name") or raw.get("id") or "").strip()
    if not name:
        raise ManifestError(f"{where}: 缺少 `name`(工具在包内的唯一标识,小写下划线)。")
    if not TOOL_NAME_RE.match(name):
        raise ManifestError(f"{where}: `name` 只能用小写字母/数字/下划线,且以字母开头(当前:{name})。")

    runtime = str(raw.get("runtime") or "python").strip().lower()
    if runtime not in VALID_RUNTIMES:
        raise ManifestError(f"{where}: runtime 只支持 {sorted(VALID_RUNTIMES)}(当前:{runtime})。")

    entry = str(raw.get("entry") or "").strip()
    command = raw.get("command") or []
    if isinstance(command, str):
        raise ManifestError(
            f"{where}: `command` 必须写成列表(argv),不要写成一整行命令 —— "
            "避免 shell 注入,例:['python', 'bin/run.py', '--in', '{input}']。"
        )
    command = [str(c) for c in command]

    if runtime == "python":
        if not entry:
            raise ManifestError(f"{where}: python 工具必须声明 `entry`,格式 `模块路径:函数名`,"
                                "例 `tools.capacity_fade:run`。")
        if not ENTRY_RE.match(entry):
            raise ManifestError(f"{where}: `entry` 格式不对(应为 `模块.子模块:函数`,当前:{entry})。")
    else:
        if not command:
            raise ManifestError(f"{where}: command 工具必须声明 `command` argv 列表。")
        out_file = str(raw.get("output_file") or "output.parquet")
        if Path(out_file).suffix.lower() not in (".parquet", ".csv", ".json", ".md"):
            raise ManifestError(
                f"{where}: output_file 的扩展名必须是 .parquet/.csv/.json/.md(当前:{out_file})。"
                "它决定系统怎么读回你的程序写出来的结果。"
            )

    returns = str(raw.get("returns") or "dataframe").strip().lower()
    if returns not in VALID_RETURNS:
        warnings.append(f"{where}: returns=`{returns}` 不认识,按 dataframe 处理。")
        returns = "dataframe"

    needs_data = raw.get("needs_data", raw.get("needs_dataset", True))
    tests = raw.get("tests") or []
    if not isinstance(tests, list):
        raise ManifestError(f"{where}: `tests` 必须是列表。")

    return ToolSpec(
        name=name,
        title=str(raw.get("title") or raw.get("label") or name),
        description=str(raw.get("description") or raw.get("desc") or ""),
        runtime=runtime,
        entry=entry,
        command=command,
        output_file=(str(raw.get("output_file") or "output.parquet") if runtime == "command" else ""),
        needs_data=bool(needs_data),
        params_schema=_normalize_params_schema(raw.get("params") or raw.get("params_schema"),
                                               where, warnings),
        returns=returns,
        aliases=_as_list(raw.get("aliases")),
        examples=_as_list(raw.get("examples")),
        tests=[t for t in tests if isinstance(t, dict)],
        timeout_seconds=int(raw["timeout_seconds"]) if raw.get("timeout_seconds") else None,
    )



# ── 通用(标准 Agent Skills)包的兼容层 ────────────────────────────────────
# 网上下的 skill 包绝大多数长这样:SKILL.md + references/ + scripts/,没有为本系统
# 写的 tools 声明 —— 因为它们本来是给"有 shell 的编码 agent"用的:SKILL.md 里写着
# "运行 scripts/xxx.py --foo",agent 自己去执行。
#
# 本系统的 AI 没有 shell,所以给这类包自动配一把钥匙:一个 `run_script` 工具,
# 参数是「跑包里哪个脚本、带什么参数」。这样 SKILL.md 里那些指令就能照原样执行,
# 用户一个字都不用改。
SCRIPT_SUFFIXES = (".py",)
SCRIPT_DIR_HINTS = ("scripts", "bin", "tools", "cli")


def discover_scripts(root: Path, limit: int = 40) -> List[str]:
    """包里那些"可以被当命令跑"的脚本(相对路径)。

    只认 .py:其它语言的脚本在 Windows 上多半没解释器,与其装上之后运行时才炸,
    不如安装阶段就不声称支持。"""
    found: List[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in SCRIPT_SUFFIXES:
            continue
        rel_parts = p.relative_to(root).parts
        if "__pycache__" in rel_parts or p.name == "__init__.py":
            continue
        rel = "/".join(rel_parts)
        # scripts/ bin/ 之类目录下的,或者带 __main__ 守卫的,才算"命令"
        in_hint_dir = any(part.lower() in SCRIPT_DIR_HINTS for part in rel_parts[:-1])
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            continue
        looks_cli = "__main__" in head or "argparse" in head or head.startswith("#!")
        if in_hint_dir or looks_cli:
            found.append(rel)
        if len(found) >= limit:
            break
    return found


def synthesize_script_tool(scripts: List[str]) -> ToolSpec:
    """把"能跑包里的脚本"包装成一个普通工具,AI 用同一个 run_tool 就能调。"""
    listing = "、".join(scripts[:8]) + ("…" if len(scripts) > 8 else "")
    return ToolSpec(
        name="run_script",
        title="运行包内脚本",
        description=(
            f"运行这个技能包自带的脚本(可选:{listing})。"
            "SKILL.md 里让你执行某个命令时用它:script 填脚本相对路径,args 填命令行参数。"
            "结果是脚本的标准输出;脚本若写出 csv/parquet,会一并读回成表格。"
        ),
        runtime="script",
        needs_data=False,
        returns="dict",
        params_schema={
            "script": {
                "type": "string", "required": True,
                "description": "包内脚本的相对路径,例如 scripts/search.py",
                "enum": scripts[:40],
                **({"default": scripts[0]} if scripts else {}),
            },
            "args": {
                "type": "array", "required": False, "default": [],
                "description": "命令行参数,按 SKILL.md 里写的那样填,例如 [\"--query\", \"button\"]",
            },
            "stdin": {
                "type": "string", "required": False,
                "description": "要喂给脚本标准输入的文本(大多数脚本用不到)",
            },
        },
        aliases=["run_command", "exec_script", "跑脚本"],
    )



def _mine_triggers(name: str, description: str) -> List[str]:
    """从名字和描述里挖几个触发词。

    通用 skill 包几乎都把触发说法写在 description 里(往往就是用 / 或 、隔开的一串
    别名)。与其让用户去补 frontmatter,不如自动认出来 —— 命中率立刻可用,用户想改
    再改。"""
    text = f"{name} {description}"
    cands: List[str] = []
    # "触发:a、b、c" / "Triggers: a, b"
    m = re.search(r"(?:触发|触发词|trigger[s]?)[::]\s*(.{0,200})", text, re.I)
    if m:
        cands += [x for x in re.split(r"[,,、/|;;]", m.group(1)) if x.strip()]
    # description 开头常见的 "甲 / 乙 / 丙。" 别名串
    head = description.split("。")[0][:160]
    if head.count("/") >= 1:
        cands += [x for x in head.split("/") if x.strip()]
    out: List[str] = []
    for c in cands:
        c = re.sub(r"[\s。.]+$", "", c.strip())
        if 2 <= len(c) <= 24 and c not in out:
            out.append(c)
    if name and name not in out:
        out.insert(0, name)
    return out[:8]


# ── entry point ──────────────────────────────────────────────────────────────

def find_doc(root: Path) -> Optional[Path]:
    for cand in DOC_NAME_CANDIDATES:
        p = root / cand
        if p.is_file():
            return p
    return None


def load_manifest(root: Path) -> Tuple[SkillManifest, List[str]]:
    """Read <root>/SKILL.md (+ optional skill.yaml) into a normalized manifest.

    Raises ManifestError with an actionable Chinese message on anything the
    author must fix."""
    warnings: List[str] = []
    root = Path(root)
    doc_path = find_doc(root)
    if doc_path is None:
        raise ManifestError(
            "技能包里没有 SKILL.md。技能包的根目录必须有一个 SKILL.md —— "
            "它既是身份声明(frontmatter),也是给 AI 看的使用说明。"
        )
    raw_text = doc_path.read_text(encoding="utf-8", errors="replace")
    fm, body = split_frontmatter(raw_text)

    yaml_data: Dict[str, Any] = {}
    for cand in MANIFEST_NAME_CANDIDATES:
        p = root / cand
        if p.is_file():
            try:
                loaded = yaml.safe_load(p.read_text(encoding="utf-8", errors="replace")) or {}
            except yaml.YAMLError as e:
                raise ManifestError(f"{cand} 不是合法 YAML:{e}") from e
            if not isinstance(loaded, dict):
                raise ManifestError(f"{cand} 的顶层必须是键值对。")
            yaml_data = loaded
            break

    merged: Dict[str, Any] = {**yaml_data, **{k: v for k, v in fm.items() if v is not None}}
    # Both places declaring `tools` isn't an error — frontmatter is the more
    # specific place so it wins — but say so out loud rather than silently
    # dropping half the author's work.
    if fm.get("tools") and yaml_data.get("tools"):
        warnings.append("SKILL.md frontmatter 和 skill.yaml 都声明了 tools —— 以 frontmatter 为准。")

    name = str(merged.get("name") or "").strip()
    slug = str(merged.get("slug") or "").strip().lower()
    if not name and not slug:
        raise ManifestError("必须至少声明 `name`(技能包名字)。建议同时给一个英文 `slug`。")
    if not slug:
        slug = _slugify(name)
        warnings.append(f"没写 slug,已按名字生成:{slug}")
    if not SLUG_RE.match(slug):
        raise ManifestError(f"slug 只能是小写字母/数字/中划线/下划线,2-63 位(当前:{slug})。")
    if not name:
        name = slug

    description = str(merged.get("description") or "").strip()
    if not description:
        raise ManifestError(
            "必须写 `description`(一句话说明这个技能包是干什么的)。"
            "它会进入 AI 的系统提示,是 AI 判断要不要打开这个包的唯一依据之一。"
        )
    when_to_use = str(merged.get("when_to_use") or merged.get("whenToUse") or "").strip()
    if not when_to_use:
        # 通用 skill 包的惯例是把"什么时候用"直接写进 description
        # ("Use when the user …" / "…时用")。与其提醒用户去改别人的包,不如就地取材。
        m = re.search(r"((Use (this )?when|使用场景|适用于|什么时候用|触发)[::]?.{0,400})",
                      description, re.I | re.S)
        if m:
            when_to_use = m.group(1).strip()
            warnings.append("没有单独的 when_to_use,已从 description 里取「什么时候用」那段。")
        else:
            when_to_use = description
            warnings.append("没写 when_to_use,暂时拿 description 顶上;补一句会让 AI 选包更准。")

    raw_tools = merged.get("tools") or []
    if isinstance(raw_tools, dict):  # allow `tools: {name: {...}}`
        raw_tools = [{**v, "name": k} for k, v in raw_tools.items() if isinstance(v, dict)]
    if not isinstance(raw_tools, list):
        raise ManifestError("`tools` 必须是列表。")
    tools = [_normalize_tool(t, i, warnings) for i, t in enumerate(raw_tools)]
    seen = set()
    for t in tools:
        if t.name in seen:
            raise ManifestError(f"工具名重复:{t.name}")
        seen.add(t.name)

    # ── 通用 skill 包:没写 tools,但带脚本 → 自动配一个 run_script 工具 ──
    scripts = discover_scripts(root)
    kind = "native"
    if not raw_tools:
        kind = "generic"
        if scripts:
            tools.append(synthesize_script_tool(scripts))
            warnings.append(
                f"这是一个通用 skill 包(没有为本系统写工具声明)。已自动识别 {len(scripts)} 个"
                "可运行脚本,并配好 `run_script` 工具 —— SKILL.md 里让 AI 执行的命令可以照原样跑。"
                "注意:运行自带脚本需要管理员开启 SKILLS_ALLOW_COMMAND_RUNTIME。"
            )
        else:
            warnings.append("这个技能包没有声明任何工具 —— 它只会作为知识(SKILL.md)被 AI 读取。")

    refs = _as_list(merged.get("references"))
    if not refs:
        ref_dir = root / "references"
        if ref_dir.is_dir():
            refs = sorted(
                str(p.relative_to(root)).replace("\\", "/")
                for p in ref_dir.rglob("*.md")
            )

    triggers = _as_list(merged.get("triggers") or merged.get("keywords"))
    if not triggers:
        triggers = _mine_triggers(name, description)
        if triggers:
            warnings.append("没写 triggers,已从名字和描述里提取了几个触发词:" + "、".join(triggers))

    return SkillManifest(
        slug=slug,
        name=name,
        version=str(merged.get("version") or "0.1.0"),
        description=description,
        when_to_use=when_to_use,
        triggers=triggers,
        category=str(merged.get("category") or "skill"),
        author=str(merged.get("author") or ""),
        doc_file=doc_path.name,
        doc_body=body.strip(),
        references=refs,
        tools=tools,
        requires=_as_list(merged.get("requires") or merged.get("python_imports")),
        kind=kind,
        scripts=scripts,
        allowed_tools=_as_list(merged.get("allowed-tools") or merged.get("allowed_tools")),
    ), warnings
