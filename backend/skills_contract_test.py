"""技能包接入的契约测试 —— 不依赖 LLM,不依赖跑起来的后端。

覆盖:manifest 解析 → 静态检查(含"该拦的必须拦住")→ 沙箱执行 → 命令行 runtime
      → 安装/升级/卸载 → agent 索引与 slug 解析 → 目录穿越防护。

跑法:
    backend/.venv/Scripts/python.exe backend/skills_contract_test.py
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# 用一个临时目录当技能库 + 一个临时 sqlite,避免污染真实数据。
_TMP = Path(tempfile.mkdtemp(prefix="skills_contract_"))
os.environ["SKILLS_DIR"] = str(_TMP / "skills")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["SKILLS_ALLOW_COMMAND_RUNTIME"] = "true"
os.environ["SKILL_TIMEOUT_SECONDS"] = "180"

import pandas as pd  # noqa: E402

from app.db.base import SessionLocal, init_db  # noqa: E402
from app.db.models import User  # noqa: E402
from app.skills import store as skill_store  # noqa: E402
from app.skills.checks import check_source, local_module_names  # noqa: E402
from app.skills.installer import InstallError, install_pack, remove_pack  # noqa: E402
from app.skills.manifest import ManifestError, load_manifest  # noqa: E402
from app.skills.runtime import run_tool  # noqa: E402

EXAMPLES = ROOT.parent / "examples" / "skills"

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail and not ok else ""))


async def main() -> int:
    await init_db()
    async with SessionLocal() as session:
        user = User(email="contract@test.local", name="contract", password_hash="x")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        uid = user.id

        # ── 1. manifest ──────────────────────────────────────────────────────
        manifest, warnings = load_manifest(EXAMPLES / "battery-health")
        check("manifest: slug/名称解析", manifest.slug == "battery-health" and manifest.name.startswith("电池"))
        check("manifest: 三个工具都读到了", len(manifest.tools) == 3,
              f"got {[t.name for t in manifest.tools]}")
        check("manifest: 参数默认值归一化",
              manifest.tools[0].params_schema["baseline_cycles"]["type"] == "integer")
        check("manifest: SKILL.md 正文与 frontmatter 分离", "判级口径" in manifest.doc_body
              and "when_to_use" not in manifest.doc_body)
        check("manifest: references 自动发现", any("判据来源" in r for r in manifest.references))

        # 缺 description 必须报错(不是静默通过)
        bad = _TMP / "bad-pack"
        bad.mkdir(parents=True, exist_ok=True)
        (bad / "SKILL.md").write_text("---\nname: 没写描述\n---\n正文", encoding="utf-8")
        try:
            load_manifest(bad)
            check("manifest: 缺 description 应报错", False, "没有报错")
        except ManifestError as e:
            check("manifest: 缺 description 应报错", "description" in str(e))

        # ── 2. 静态检查的边界 ────────────────────────────────────────────────
        local = local_module_names(EXAMPLES / "battery-health")
        ok_src = "import pandas as pd\nfrom lib import criteria\n\ndef run(df):\n    return df\n"
        r = check_source(ok_src, "tools/x.py", local=local, extra_allowed=set())
        check("checks: 包内 import(lib.criteria)不该被拦", r.ok, str(r.errors))

        for label, src in [
            ("联网", "import requests\ndef run(df):\n    return df\n"),
            ("起子进程", "import subprocess\ndef run(df):\n    return df\n"),
            ("删文件", "import shutil\ndef run(df):\n    shutil.rmtree('/')\n    return df\n"),
            ("动态执行", "def run(df):\n    return eval('1+1')\n"),
        ]:
            r = check_source(src, "tools/bad.py", local=local, extra_allowed=set())
            check(f"checks: {label} 必须被拦下", not r.ok, "没拦住")

        r = check_source("import openpyxl\ndef run(df):\n    return df\n", "tools/x.py",
                         local=local, extra_allowed={"openpyxl"})
        check("checks: requires 声明过的第三方库放行", r.ok, str(r.errors))

        # ── 3. 安装(目录形式)+ 自检 ──────────────────────────────────────────
        row, report = await install_pack(session, uid, src_dir=str(EXAMPLES / "battery-health"))
        check("install: 安装成功且通过自检", row is not None and row.is_verified,
              str([s for s in report["stages"] if not s["ok"]]))
        check("install: 每一步都有记录",
              {s["stage"] for s in report["stages"]} >= {"extract", "manifest", "static_check", "smoke_test", "install", "register"})
        smoke = next(s for s in report["stages"] if s["stage"] == "smoke_test")
        check("install: 声明的测试真的跑了",
              sum(len(t["checks"]) for t in smoke["data"]["tools"]) >= 6,
              str(smoke["data"]))
        check("install: 文件落到隔离目录", str(_TMP) in (row.root or ""), row.root or "")

        # ── 4. 沙箱里跑包内工具 ──────────────────────────────────────────────
        df = pd.DataFrame({
            "cycle": list(range(1, 61)),
            "discharge_capacity_ah": [2.0 - 0.0003 * i for i in range(60)],  # ≈1.5%/100圈 → A
            "internal_resistance_mohm": [20 + 0.02 * i for i in range(60)],
        })
        tools = {t["name"]: t for t in row.tools}

        res = run_tool(root=row.root, tool=tools["capacity_fade"], df=df, params={})
        check("run: capacity_fade 成功", res["status"] == "ok", res.get("error", ""))
        check("run: 输出列符合契约",
              set(res["summary"].get("columns", [])) >= {"cycle", "retention_pct", "fade_pct_per_100cyc"},
              str(res["summary"].get("columns")))

        res = run_tool(root=row.root, tool=tools["soh_report"], df=df, params={})
        check("run: soh_report 返回 dict", res["status"] == "ok" and res["summary"]["type"] == "dict",
              res.get("error", ""))
        val = res["summary"]["value"]
        check("run: 健康数据判 A", val.get("grade") == "A", str(val))
        check("run: 外推被如实标注", val.get("extrapolated") is True and "eol_cycle_est" in val, str(val))

        cliff_df = pd.DataFrame({
            "cycle": list(range(1, 41)),
            "discharge_capacity_ah": [2.0] * 20 + [2.0 - 0.02 * i for i in range(20)],
        })
        res = run_tool(root=row.root, tool=tools["soh_report"], df=cliff_df, params={})
        check("run: 跳水判 C", res["summary"]["value"].get("grade") == "C",
              str(res["summary"].get("value")))

        # 列不存在 → 必须是人话错误,而不是 KeyError 堆栈
        res = run_tool(root=row.root, tool=tools["capacity_fade"], df=pd.DataFrame({"a": [1, 2, 3]}),
                       params={})
        check("run: 缺列时给人话错误",
              res["status"] == "error" and "没有这些列" in res["error"], res.get("error", "")[:200])

        # 参数容器纠偏(LLM 常犯):字符串数字 → int
        res = run_tool(root=row.root, tool=tools["capacity_fade"], df=df,
                       params={"baseline_cycles": "5"})
        check("run: 参数类型自动纠偏", res["status"] == "ok", res.get("error", ""))

        # ── 5. agent 侧索引 / slug 解析 ──────────────────────────────────────
        packs = await skill_store.list_packs(session, uid, enabled_only=True)
        idx = skill_store.tool_index(packs)
        check("agent: 工具进了索引", {t["slug"] for t in idx} >=
              {"battery-health.capacity_fade", "battery-health.soh_report"}, str([t["slug"] for t in idx]))
        block = skill_store.prompt_block(packs)
        check("agent: 提示块含 when_to_use 且不含正文",
              "什么时候用" in block and "判级口径" not in block)
        for probe in ["battery-health.soh_report", "battery-health__soh_report", "soh_report",
                      "Battery-Health.SOH_Report"]:
            hit = skill_store.resolve_tool(packs, probe)
            check(f"agent: slug 容错解析 `{probe}`", hit is not None and hit[1]["name"] == "soh_report")
        check("agent: 不存在的工具解析为 None", skill_store.resolve_tool(packs, "nope.nope") is None)

        doc = skill_store.read_doc(packs[0])
        check("agent: read_skill 拿到正文+工具", "判级口径" in doc["content"] and len(doc["tools"]) == 3)
        ref = skill_store.read_doc(packs[0], "references/判据来源.md")
        check("agent: read_skill 能读参考文件", "每百圈" in ref.get("content", ""), str(ref)[:200])
        esc = skill_store.read_doc(packs[0], "../../../../etc/passwd")
        check("agent: 目录穿越被挡", "error" in esc, str(esc)[:120])

        # ── 5.5 agent 真正的分发路径(不需要 LLM)────────────────────────────
        from app.services import chat_agent
        from app.services.datasets import _persist_dataset

        ds = await _persist_dataset(
            session, owner_id=uid, df=df, name="循环数据", filename="cyc.parquet",
            file_format="parquet", description="contract test",
        )
        await session.commit()
        await session.refresh(ds)

        common = dict(session=session, llm=None, owner_id=uid, datasets=[ds],
                      working={}, frames={}, lineage_state={}, pipeline_state={},
                      skill_packs=packs)

        out = await chat_agent._execute_action(
            parsed={"action": "read_skill", "args": {"slug": "battery-health"}}, **common)
        check("agent: read_skill 动作可用", "判级口径" in out.get("content", ""), str(out)[:200])
        out = await chat_agent._execute_action(
            parsed={"action": "read_skill", "args": {"slug": "不存在"}}, **common)
        check("agent: read_skill 未知包给出可选项", "error" in out and out.get("available"))

        out = await chat_agent._execute_action(
            parsed={"action": "run_tool",
                    "args": {"slug": "battery-health.capacity_fade", "params": {}}}, **common)
        check("agent: run_tool 跑通技能包工具", out.get("status") == "ok", str(out.get("error"))[:300])
        check("agent: 结果自动物化成派生数据集",
              bool(out.get("derived_dataset")), str(out)[:300])

        out = await chat_agent._execute_action(
            parsed={"action": "run_tool",
                    "args": {"slug": "battery-health.ir_growth", "params": {"ir_col": "不存在的列"}}},
            **common)
        check("agent: 工具失败时给出去读文档的提示",
              out.get("status") == "error" and "read_skill" in (out.get("hint") or ""), str(out)[:300])

        out = await chat_agent._execute_action(
            parsed={"action": "describe_tool", "args": {"slug": "battery-health.soh_report"}}, **common)
        check("agent: describe_tool 能描述技能包工具",
              out.get("source") == "skill" and "eol_retention" in (out.get("params_schema") or {}),
              str(out)[:250])

        out = await chat_agent._execute_action(parsed={"action": "list_tools", "args": {}}, **common)
        check("agent: list_tools 含技能包工具",
              any(t.get("source") == "skill" for t in out.get("tools", [])))

        # ── 5.8 网上下的包:用不上的脚本只提醒,不拦整包 ─────────────────────
        # (但工具真正会走到的代码里出现同样的违规,必须照拦不误)
        net = _TMP / "net-pack"
        (net / "scripts").mkdir(parents=True, exist_ok=True)
        (net / "tools").mkdir(parents=True, exist_ok=True)
        (net / "SKILL.md").write_text(
            "---\nname: 下载来的包\nslug: net-pack\ndescription: 从网上下的\n"
            "when_to_use: 测试用\n---\n正文", encoding="utf-8")
        (net / "skill.yaml").write_text(
            "tools:\n  - name: t\n    description: d\n    entry: tools.t:run\n", encoding="utf-8")
        (net / "tools" / "t.py").write_text(
            "def run(df):\n    return df\n", encoding="utf-8")
        # 这个脚本是给别的 runtime 写的,本系统里没有任何入口引用它
        (net / "scripts" / "fetch.py").write_text(
            "import requests\n\ndef go():\n    return requests.get('http://x')\n", encoding="utf-8")

        row4, rep4 = await install_pack(session, uid, src_dir=str(net))
        check("网包: 用不上的违规脚本不拦整包", row4 is not None,
              str([s for s in rep4["stages"] if not s["ok"]])[:300])
        check("网包: 但要在提醒里说清楚",
              any("不会被执行" in w for w in rep4.get("warnings", []) + [
                  str(s.get("data")) for s in rep4["stages"]]),
              str(rep4.get("warnings"))[:300])

        v = rep4.get("verdict") or {}
        check("verdict: 给出可用结论", v.get("installable") and v.get("self_check_passed"), str(v)[:300])
        check("verdict: 说清 AI 能拿到什么", "工具" in (v.get("gives") or ""), str(v.get("gives")))

        # 工具真的会 import 到的模块里有违规 → 必须拦
        (net / "lib_bad.py").write_text("import subprocess\n", encoding="utf-8")
        (net / "tools" / "t.py").write_text(
            "import lib_bad\n\ndef run(df):\n    return df\n", encoding="utf-8")
        try:
            await install_pack(session, uid, src_dir=str(net))
            check("网包: 工具会走到的违规必须拦住", False, "居然装上了")
        except InstallError as e:
            check("网包: 工具会走到的违规必须拦住", "lib_bad" in str(e), str(e)[:200])

        # 纯知识包(Claude Code 风格,只有 SKILL.md)
        kn = _TMP / "knowledge-only"
        kn.mkdir(parents=True, exist_ok=True)
        (kn / "SKILL.md").write_text(
            "---\nname: 纯知识包\nslug: knowledge-only\ndescription: 只有方法没有工具\n---\n正文",
            encoding="utf-8")
        row5, rep5 = await install_pack(session, uid, src_dir=str(kn))
        check("纯知识包可装", row5 is not None and row5.tool_count if hasattr(row5, "tool_count") else row5 is not None)
        check("纯知识包: verdict 点明只有知识",
              (rep5.get("verdict") or {}).get("knowledge_only") is True, str(rep5.get("verdict"))[:200])

        # ── 5.9 通用 skill 包(标准 SKILL.md 格式,一个字不改就能装)────────────
        gen = _TMP / "generic-pack"
        (gen / "scripts").mkdir(parents=True, exist_ok=True)
        (gen / "references").mkdir(parents=True, exist_ok=True)
        (gen / "SKILL.md").write_text(
            "---\nname: generic-demo\n"
            "description: Design helper. Use when the user asks about 配色 / 排版。触发:配色、排版\n"
            "allowed-tools: Read, Bash\n---\n# 用法\n\n运行 `python scripts/pick.py --n 3` 拿到配色。",
            encoding="utf-8")
        (gen / "scripts" / "pick.py").write_text(
            "import argparse\n"
            "ap = argparse.ArgumentParser()\n"
            "ap.add_argument('--n', type=int, default=1)\n"
            "a = ap.parse_args()\n"
            "print('palette:' + ','.join(str(i) for i in range(a.n)))\n",
            encoding="utf-8")
        (gen / "references" / "notes.md").write_text("# 参考\n细则在这里。", encoding="utf-8")

        rowg, repg = await install_pack(session, uid, src_dir=str(gen))
        vg = repg.get("verdict") or {}
        check("通用包: 不用改一个字就能装", rowg is not None and rowg.is_verified,
              str([x for x in repg["stages"] if not x["ok"]])[:300])
        check("通用包: 被认出来是 generic", vg.get("kind") == "generic", str(vg)[:200])
        check("通用包: 自动配了 run_script 工具",
              any(t["name"] == "run_script" and t["runtime"] == "script" for t in rowg.tools),
              str([t["name"] for t in rowg.tools]))
        check("通用包: 脚本被自动发现", "scripts/pick.py" in (vg.get("scripts") or []), str(vg.get("scripts")))
        check("通用包: 没写 when_to_use 也能从 description 取到",
              "Use when" in (rowg.when_to_use or "") or bool(rowg.when_to_use), rowg.when_to_use[:80])
        check("通用包: 触发词自动挖出来", bool(rowg.triggers), str(rowg.triggers))
        check("通用包: trust 是 script(不是 command,普通用户也能装)",
              rowg.trust == "script", rowg.trust)

        script_tool = next(t for t in rowg.tools if t["name"] == "run_script")
        from app.skills.runtime import run_tool as _rt
        res = _rt(root=rowg.root, tool=script_tool, df=None,
                  params={"script": "scripts/pick.py", "args": ["--n", "3"]}, allow_command=True)
        check("通用包: 自带脚本真的能跑",
              res["status"] == "ok" and "palette:0,1,2" in str(res["summary"].get("stdout")),
              str(res.get("error") or res["summary"])[:200])

        res = _rt(root=rowg.root, tool=script_tool, df=None,
                  params={"script": "../../../../etc/passwd"}, allow_command=True)
        check("通用包: 脚本路径越界被挡", res["status"] == "error" and "越界" in res["error"])

        res = _rt(root=rowg.root, tool=script_tool, df=None,
                  params={"script": "scripts/pick.py"}, allow_command=False)
        check("通用包: 未授权时拒跑但说清知识仍可用",
              res["status"] == "error" and "知识部分不受影响" in res["error"], res.get("error", "")[:120])

        packs_g = await skill_store.list_packs(session, uid, enabled_only=True)
        blk = skill_store.prompt_block([p for p in packs_g if p.slug == "generic-demo"])
        check("通用包: 提示词告诉 AI 用 run_script 而不是假装有终端",
              "run_script" in blk and "终端" in blk, blk[:200])

        # ── 5.95 推荐参数:按真实列名填,填不出就明说不合适 ────────────────────
        from app.skills.suggest import suggest_params
        bat_tool = next(t for t in row.tools if t["name"] == "capacity_fade")
        good_cols = [{"name": "Cycle Index", "dtype": "int64"},
                     {"name": "Discharge Capacity (Ah)", "dtype": "float64"}]
        sg = suggest_params(bat_tool, good_cols, dataset_name="电池数据")
        check("推荐: 列名变形也能对上",
              sg["params"].get("cycle_col") == "Cycle Index"
              and sg["params"].get("capacity_col") == "Discharge Capacity (Ah)", str(sg["params"]))
        check("推荐: 说清为什么这么填", "最接近" in "".join(sg["explanations"].values())
              or "正好有列" in "".join(sg["explanations"].values()), str(sg["explanations"])[:200])
        check("推荐: 给出可选列供下拉", bool(sg["options"].get("cycle_col")), str(sg["options"])[:120])

        bad_cols = [{"name": "Mach Number", "dtype": "float64"},
                    {"name": "Shock Angle (deg)", "dtype": "float64"}]
        sg2 = suggest_params(bat_tool, bad_cols, dataset_name="激波角数据")
        check("推荐: 数据不对口时如实说不合适", sg2["fit"] == "mismatch", str(sg2)[:200])
        check("推荐: 绝不硬塞一个能跑的列",
              "cycle_col" not in sg2["params"] and "capacity_col" not in sg2["params"], str(sg2["params"]))
        check("推荐: 非列参数保留默认值", sg2["params"].get("baseline_cycles") == 5, str(sg2["params"]))

        # ── 5.96 报错要人话,traceback 收进 logs ──────────────────────────────
        res = _rt(root=row.root, tool=bat_tool, df=pd.DataFrame({"Mach": [1, 2, 3]}), params={})
        check("报错: 第一屏是人话不是 traceback",
              res["status"] == "error" and "Traceback" not in res["error"]
              and "没有这些列" in res["error"], res.get("error", "")[:160])
        check("报错: traceback 仍留在 logs 里可查", "Traceback" in (res.get("logs") or ""))
        check("报错: 附带这份数据真实的列", "Mach" in (res.get("hint") or ""), str(res.get("hint"))[:120])

        # ── 5.97 启用 / 停用:这是"AI 能不能看到它"的开关 ─────────────────────
        pk = await skill_store.get_pack(session, uid, "battery-health")
        pk.enabled = False
        await session.commit()
        vis = await skill_store.list_packs(session, uid, enabled_only=True)
        allp = await skill_store.list_packs(session, uid)
        check("停用: AI 视野里消失",
              all(p.slug != "battery-health" for p in vis), str([p.slug for p in vis]))
        check("停用: 页面里还在(随时能勾回来)",
              any(p.slug == "battery-health" for p in allp))
        check("停用: 提示词里也没有它",
              "battery-health" not in skill_store.prompt_block(vis))
        check("停用: 工具表里也没有它",
              all(not t["slug"].startswith("battery-health.") for t in skill_store.tool_index(vis)))
        # 停用不影响手动执行(排查/验证需要),这一条要故意保持
        res = _rt(root=pk.root, tool=bat_tool, df=df, params={})
        check("停用: 手动试跑照常能跑", res["status"] == "ok", res.get("error", "")[:120])

        # 重装升级不能把用户的"停用"悄悄冲回启用
        row_up, _rep_up = await install_pack(session, uid, src_dir=str(EXAMPLES / "battery-health"))
        check("停用: 重装升级后仍是停用(不被静默打开)", row_up.enabled is False, str(row_up.enabled))
        row_up2, _r2 = await install_pack(session, uid, src_dir=str(EXAMPLES / "battery-health"),
                                          enable=True)
        check("启用: 明确要求启用时才打开", row_up2.enabled is True)

        # ── 5.98 列映射:教过的规则优先于字面猜测,且教不出来的绝不硬指 ──────────
        from app.skills.suggest import effective_role, suggest_params as _sp
        bat_tool2 = next(t for t in row.tools if t["name"] == "capacity_fade")
        check("映射: 参数能声明物理量 role",
              (bat_tool2["params_schema"]["cycle_col"].get("role") or "") == "cycle_index",
              str(bat_tool2["params_schema"]["cycle_col"]))
        check("映射: 没声明 role 时用默认列名当伪 role",
              effective_role("ir_col", {"default": "internal_resistance_mohm"}) == "internalresistancemohm")

        odd_cols = [{"name": "Cyc_No", "dtype": "int64"}, {"name": "Cap", "dtype": "float64"}]
        # 没教过之前:字面猜不出来 Cyc_No 是循环号
        sg_before = _sp(bat_tool2, odd_cols)
        # Cap 被认成容量是对的(词根命中);Cyc_No 认不出来才是这里要验的
        check("映射: 教之前认不出怪名字列(Cyc_No)",
              sg_before["fit"] == "partial" and "cycle_col" not in sg_before["params"],
              str(sg_before["params"]))
        check("映射: 认不出时给出'教一次'的入口(role 用人看得懂的写法)",
              any(t["role"] == "cycle_index" for t in sg_before["teachable"]),
              str(sg_before["teachable"])[:200])

        # 教一次(等价于用户在界面上指了一下 → 一条 MappingRule)
        sg_after = _sp(bat_tool2, odd_cols,
                       role_columns={"cycle_index": ["Cyc_No"], "discharge_capacity": ["Cap"]})
        check("映射: 教过之后直接认出来",
              sg_after["params"].get("cycle_col") == "Cyc_No"
              and sg_after["params"].get("capacity_col") == "Cap", str(sg_after["params"]))
        check("映射: 说清是'按你教过的'而不是猜的",
              "教过" in "".join(sg_after["explanations"].values()), str(sg_after["explanations"])[:200])
        check("映射: 用到教过的规则会记下来", sg_after["used_rules"], str(sg_after["used_rules"]))

        # 关键:数据里真没有那个量时,教过的规则也不能凭空造一列
        no_cycle = [{"name": "batch", "dtype": "object"}, {"name": "value1", "dtype": "float64"}]
        sg_none = _sp(bat_tool2, no_cycle, role_columns={"cycle_index": ["Cyc_No"]})
        check("映射: 数据里没有那列时,规则也不硬塞",
              "cycle_col" not in sg_none["params"] and sg_none["fit"] == "mismatch", str(sg_none["params"]))

        # ── 6. command runtime ──────────────────────────────────────────────
        row2, report2 = await install_pack(session, uid, src_dir=str(EXAMPLES / "demo-command"),
                                           allow_command=True)
        check("command: 安装并标记 trust=command", row2 is not None and row2.trust == "command")
        res = run_tool(root=row2.root, tool=row2.tools[0], df=df, params={"top_n": 5},
                       allow_command=True)
        check("command: 自带脚本跑通并读回结果",
              res["status"] == "ok" and res["summary"].get("rows", 0) > 0, res.get("error", "")[:300])
        res = run_tool(root=row2.root, tool=row2.tools[0], df=df, params={}, allow_command=False)
        check("command: 未授权时拒绝执行并说明原因",
              res["status"] == "error" and "SKILLS_ALLOW_COMMAND_RUNTIME" in res["error"])

        # ── 7. 升级 / 卸载 ───────────────────────────────────────────────────
        before = row.id
        row3, _r3 = await install_pack(session, uid, src_dir=str(EXAMPLES / "battery-health"))
        check("upgrade: 同 slug 复装是升级而不是新增", row3.id == before)

        # zip 形式 + 目录穿越的压缩包必须被拒
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../evil.py", "print(1)")
            zf.writestr("SKILL.md", "---\nname: evil\ndescription: x\n---\n")
        try:
            await install_pack(session, uid, zip_bytes=buf.getvalue())
            check("zip: 目录穿越必须被拒", False, "居然装上了")
        except InstallError as e:
            check("zip: 目录穿越必须被拒", "非法路径" in str(e) or "越界" in str(e), str(e))

        root_path = Path(row3.root)
        await remove_pack(session, row3)
        check("uninstall: 行与文件一起清掉",
              (await skill_store.get_pack(session, uid, "battery-health")) is None
              and not root_path.exists())

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("失败项:")
        for f in FAIL:
            print("  ·", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    raise SystemExit(code)
