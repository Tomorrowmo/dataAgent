"""Domain knowledge served to the LLM.

Everything the model needs in order to (a) draft a rule, (b) write a custom
feature extractor, or (c) narrate an aerodynamic curve, is assembled here from
the *live* system state — the feature catalogue is generated from
``FEATURE_SPECS``, not copy-pasted, so it can never drift out of date.

The design rule behind this file: **the model is never asked to produce a
number.** It maps intent onto existing features, proposes thresholds the user
then confirms, or writes code whose output is checked in a sandbox. Every
number that reaches a report is computed by :mod:`app.windtunnel.features` or
by sandboxed code that passed a test.
"""

from __future__ import annotations

from typing import List

from .features import FEATURE_SPECS
from .rules import LEVELS

FILE_FORMAT_DOC = """\
## 风洞试验数据文件格式

同一车次由三个同名不同前缀的文件构成（无扩展名，GBK 编码，文件名形如 ca246490）：

### ca —— 原始采集数据
纯数字表格，以 `N5=` 行结束，之后是尾部信息（`M=` 名义马赫数、`N6=` 吹风点数、
`ALPHA=` 输出攻角序列）。每行 16 列，依次为：

| 序号 | 列名 | 含义 | 原始单位 |
|---|---|---|---|
| 0 | ALPHA | 机构攻角 | ° |
| 1-6 | My, Z, Mz, Y, Mx, Q | 天平六分量原始码 | 码 |
| 7 | PL | 左底压 | MPa |
| 8 | P2 | 备用底压 | MPa |
| 9 | PR | 右底压 | MPa |
| 10 | To | 总温 | ℃ |
| 11 | t | 室温 | ℃ |
| 12 | Pa | 大气压 | MPa |
| 13 | P8 | 来流静压 | MPa |
| 14 | P0 | 来流总压 | MPa |
| 15 | Ma | 记录马赫数 | - |

**关键约定**：第一行是吹风前零点(初零)，最后一行是吹风后回零(末零)，中间各行是吹风点。

### pa —— 过程文件
分段的中文报表。主要区段：模型状态 / 天平初末零原始码差量 / 控制参数 / 模型参数
(Sr, L, Lcp, L测, 横直径D) / 天平参数(天平型式、天平弹性角公式、天平系统) /
`============CA文件===` 回显（压力已换算为 kgf/m²，与 mmH2O 等值）/
吹风文件扣除零点的绝对码值 / 弹性角修正过程(ALPHA αe βe γe △αMe △βMe) /
没有插值的姿态角(Am Bm Rm At Bs) / 吹风时天平测量的气动载荷 /
插值后的姿态角 / 天平公式标定矩阵。
含 `L测 =` 表示这是测力试验；否则为铰链力矩试验，多数检查不适用。

### da —— 气动结果(list)文件
第 2 行给出 `行数 列数`，第 3 行为 59 个列名表头，随后是数据。常用列：
ALPHA(攻角)、Bs(侧滑角)、CAF(前体轴向力系数)、CN(法向力系数)、CZ(侧向力系数)、
CAB(底部阻力系数)、MX/MY/MZ(滚转/偏航/俯仰力矩系数)、XCP(压心)、CLF/CDF(升/阻力系数)、
CLCDF(升阻比)、Re(雷诺数)、M(马赫数)，以及 CNa/MZa/CZa 等导数列。
表尾还有来流条件块(Pa P8 Po q8 To1 To2 Re1 Re2)与模型描述行。

### 单位换算（必须遵守）
- 1 mmH2O = 9.80665 Pa（标准重力定义），1 kgf/m² = 1 mmH2O（精确相等）
- MPa → mmH2O：乘以 1e6/9.80665 = 101971.62
- 规则书中所有压力阈值都以 mmH2O 表述
"""

EXTRACTOR_CONTRACT = """\
## 自定义特征算子的编写契约

自定义检查项写成一个标准算法模块，在沙箱中执行，输入是**本车次的长表 DataFrame**：

列：`run_no, table, row, point, alpha, variable, value, unit`

- `table` 取值：`ca`(原始采集,压力已转 mmH2O) / `ca_echo`(pa 中的 CA 回显) /
  `elastic`(弹性角) / `attitude_measured`(实测姿态角) / `attitude_interp`(插值后姿态角) /
  `aero_loads`(天平测得气动载荷) / `da`(气动结果系数)
- `point` 仅对 ca / ca_echo 有值：`zero_start`(初零) / `blow`(吹风点) / `zero_end`(末零)
- `variable` 是该表内的列名，`value` 是数值，`unit` 是单位标签

模块必须包含：

```python
import pandas as pd
import numpy as np

META = {
    "name": "总压波动系数",
    "slug": "total_pressure_cv",
    "category": "custom",
    "description": "吹风段来流总压的变异系数(标准差/均值)，反映流场稳定性。",
    "params_schema": {},
    "returns": "dict",
}

def run(df, **params):
    s = df[(df.table == "ca") & (df.point == "blow") & (df.variable == "P0")]["value"]
    if len(s) < 2:
        raise ValueError("吹风点不足 2 个，无法计算波动系数")
    return {
        "value": float(s.std(ddof=1) / s.mean() * 100.0),  # 必须：单一数值
        "unit": "%",                                        # 必须：单位
        "detail": f"基于 {len(s)} 个吹风点的来流总压",        # 可选：一句话说明
        "extras": {"mean": float(s.mean()), "std": float(s.std(ddof=1))},  # 可选
    }

test_cases = [{"df": pd.DataFrame({
    "run_no": ["t"]*3, "table": ["ca"]*3, "row": [1,2,3], "point": ["blow"]*3,
    "alpha": [0.0,1.0,2.0], "variable": ["P0"]*3, "value": [19013.9,19106.2,19107.1],
    "unit": ["mmH2O"]*3}), "params": {}}]
```

**硬性要求**
1. `run()` 返回 dict，且必须含 `value`(float) 与 `unit`(str)。
2. 数据不足时 `raise ValueError` 并说明原因——绝不能返回 0 冒充“正常”。
3. 只做测量，不做判定：不要在算子里写任何阈值或“正常/异常”结论，那是规则的职责。
4. 只允许 numpy / pandas / scipy / math / statistics 等安全库，禁止文件与网络访问。
"""


def feature_catalog(as_markdown: bool = True) -> str:
    """The live list of measurable quantities a rule can bind to."""
    rows = []
    for k, s in sorted(FEATURE_SPECS.items()):
        rows.append((k, s.name, s.unit, "、".join(s.requires) or "-",
                     "是" if s.needs_prev_run else "否", s.description))
    if not as_markdown:
        return "\n".join(f"{r[0]}\t{r[1]}\t{r[2]}" for r in rows)
    out = ["| feature key | 名称 | 单位 | 依赖文件 | 需上一车次 | 说明 |",
           "| --- | --- | --- | --- | --- | --- |"]
    out += [f"| `{a}` | {b} | {c} | {d} | {e} | {f} |" for a, b, c, d, e, f in rows]
    return "\n".join(out)


RULE_SCHEMA_DOC = f"""\
## 规则的数据结构

规则是**数据**，不是代码。一条规则把一个 feature 绑到若干区间上：

```json
{{
  "rule_id": "rule_custom_total_pressure_cv",
  "name": "来流总压稳定性诊断",
  "feature": "custom:total_pressure_cv",
  "object": "风洞总压控制系统",
  "note": "工程说明：为什么这样判、依据是什么",
  "applies_when_mach": "",
  "refs": ["依据出处 1", "依据出处 2"],
  "bands": [
    {{"level": "critical", "lo": 3.0, "hi": null,
      "verdict": "总压波动系数大于 3%",
      "cause": "原因分析", "impact": "影响评估", "action": "处理建议"}},
    {{"level": "warning", "lo": 1.5, "hi": 3.0, "verdict": "...",
      "cause": "...", "impact": "...", "action": "..."}},
    {{"level": "ok", "lo": null, "hi": 1.5, "verdict": "来流总压稳定"}}
  ]
}}
```

- 区间为半开区间 `[lo, hi)`，`null` 表示该端开放；按顺序匹配，命中即止，
  因此请**从最严重的区间往下写**。
- `level` 取值：{" / ".join(LEVELS)}（ok=正常，notice=引起注意，
  warning=需检查，critical=停止试验）。
- 每个非 ok 区间都必须写清 `verdict`(判定结论)、`cause`(原因分析)、
  `impact`(影响评估)、`action`(处理建议)——报告要直接把这四项列给试验人员。
- `feature` 必须是已有的 feature key，或形如 `custom:<slug>` 引用一个已入库的
  自定义特征算子。**不要发明不存在的 feature key。**
"""


def rule_drafting_context() -> str:
    return "\n\n".join([
        FILE_FORMAT_DOC,
        "## 可用的监测特征（feature key）\n\n" + feature_catalog(),
        RULE_SCHEMA_DOC,
    ])


def extractor_context() -> str:
    return "\n\n".join([FILE_FORMAT_DOC, EXTRACTOR_CONTRACT])


def cite_hint() -> str:
    return (
        "写 refs 时优先引用：甲方规则书 rules/*.md；公开标准 "
        "AIAA S-071A-1999(风洞试验不确定度)、AIAA R-091-2003(内式应变天平校准与使用)、"
        "ASME PTC 19.1(试验不确定度)、GJB 1179A-2012(高速风洞流场品质)、ISO 5725；"
        "经典方法 NIST/SEMATECH e-Handbook(Grubbs/Dixon 离群点检验)、"
        "Nelson(1984) 控制图判异规则、Savitzky-Golay(1964) 平滑。"
        "如果确实没有可引用的出处，就写「用户自定义工程约定，待评审」，不要编造文献。"
    )
