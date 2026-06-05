# 提案：算法即 Skill —— 统一 schema + 数据→工具线索表

> 借鉴隔壁 `sim-cli` 的 `sim-skills`（每个 solver 一个 SKILL.md，frontmatter 触发式描述 + 渐进披露）
> 和 `sim-knowledge`（声明式 YAML 知识 + `domain_inference.yaml` 线索表路由）。
>
> 一句话：**把 `AlgorithmSpec` 和「skill」统一成一个 schema，区别只在挂多少参考内容；
> 用线索表做数据→工具的路由/分组。** 同时解决 Q4（平铺列表）、归不进去、给 Pillar 4 一个发布格式。
>
> 现状锚点：`backend/app/algorithms/registry.py::AlgorithmSpec`、`web/lib/algoMeta.ts::CAT_ZH`
> 状态：**待审核拍板**（文末「待你判断」列了关键取舍）

---

## Part 1 · 统一 Schema（algo = skill）

每个工具——不管是十行的内置滤波，还是专家发布的整套多物理场映射小程序——都用同一套元数据描述。
下表标注**哪些你已经有**（✅）、**哪些要新增**（🆕）。

| 字段 | 状态 | 说明 | 借鉴自 |
|---|---|---|---|
| `slug` | ✅ | 唯一 id | — |
| `name` | ✅ | 展示名 | SKILL.md `name` |
| `description` | ✅ 但要改写 | **改成「Use when…」触发式**：描述*什么时候用*，不是数学定义 | SKILL.md `description` |
| `params_schema` | ✅ | 参数定义 | — |
| `returns` | ✅ | 返回类型 | — |
| `tags` | ✅ | 多标签 = 真相来源；分组只是它的视图 | sim-knowledge 多域 |
| `examples` | ✅ | 自然语言例子，喂搜索面板 | — |
| `aliases` | ✅ | LLM 近义猜名，自愈 | — |
| `intent` | 🆕 | 通用动作轴：`clean/smooth/feature/fit/reduce/map/verify` | 改法 A 的意图分组 |
| `domain` | 🆕 | 领域包：`general / multiphysics / battery / robotics …` | sim-skills 每 solver 一包 |
| `use_when` | 🆕 | 一句人话「什么场景点我」（比 description 更口语，给非专家看） | SKILL.md「Use when」 |
| `must_verify` | 🆕(可选) | 用完**必须校验什么**（如场映射→守恒）；空=无强约束 | SKILL.md hard constraints |
| `known_issues` | 🆕(可选) | 坑 + 绕过；轻量工具可空，重型工具链到 `.md` | `known_issues.md` |
| `reference` | ✅ 字段在/语义扩展 | 重型工具的参考文档路径，**按需读不内联**（渐进披露） | SKILL.md File index |

**关键改动只有两类**：
1. `description` 从「功能罗列」→「触发式」。例：
   - 旧：`median_filter` = "滑动中值滤波，对会拉偏均值的离群尖峰更稳健"
   - 新 `use_when` = "**用在**信号里有偶发尖峰毛刺、又不想让均值被拉偏时"
2. 加 `intent` + `domain` 两个软标签 —— 分组/路由全靠它们算，不再写死 `CAT_ZH`。

---

## Part 2 · 两档目录结构（按工具重量缩放，别一刀切）

> sim-skills 给每个 solver 配整套文档，是因为 CFX/Abaqus 本身重。
> 你的 `butterworth_filter` 不配开文件夹。所以分两档，**共用同一 frontmatter**。

### 轻档：内置原语 —— 不开文件夹，只补字段

```python
# backend/app/algorithms/builtins_filter.py（现有文件，加字段）
AlgorithmSpec(
    slug="median_filter", name="中值滤波",
    intent="smooth", domain="general",
    use_when="信号里有偶发尖峰毛刺、又不想让均值被拉偏",
    tags=["滤波", "去噪", "鲁棒"],
    examples=["去掉温度里的尖峰毛刺"],
    # must_verify / known_issues / reference 留空
    ...
)
```

### 重档：领域工具 / Pillar 4 发布的小程序 —— 开 skill 文件夹

```
backend/app/skills/field-mapping/
├── SKILL.md                    # frontmatter（同一 schema）+ 何时用 + 协议
├── known_issues.md             # 守恒不闭合、曲界面振荡、缝隙/重叠处理
├── reference/
│   ├── mapping_methods.md      # 最近邻 / RBF / 守恒映射 对比
│   └── conservation_check.md   # 守恒校验怎么算、阈值多少
└── algo.py                     # 实现（沙箱执行）
```

`SKILL.md` frontmatter 样例（和轻档同字段，只是多挂了内容）：

```yaml
---
slug: field-mapping
name: 多物理场场映射
intent: map
domain: multiphysics
use_when: "把一套网格上的场（如流场压力）传到另一套不协调网格（如结构网格）上时"
must_verify:
  - "总载荷守恒：∑映射前 ≈ ∑映射后，相对误差给出数值"
  - "界面误差分布可视化，定位曲界面/缝隙处的偏差"
tags: [空间映射, 网格, 守恒, FSI, 多物理场]
examples: ["把流场压力映射到结构网格", "FSI 界面载荷传递"]
reference:
  - reference/mapping_methods.md
  - reference/conservation_check.md
known_issues: known_issues.md
---
```

> 两档对线索表、搜索面板、agent 选工具**完全一视同仁**——因为 frontmatter 一样。

---

## Part 3 · 数据→工具线索表（仿 `domain_inference.yaml`）

> 这是「改法 C 上下文推荐」的声明式实现，也是「归不进去」的兜底机制。
> **输出是候选排序，不是唯一标签**——匹配不到不报错，只是不在上下文冒泡（搜索仍可达）。

`backend/app/algorithms/data_clues.yaml`（新文件，agent + 前端共读）：

```yaml
# 给一份数据集的表面信号（列名 / 列类型 / 有无时间列 / 数值列数）
# → 排名候选 intent + 候选工具。仿 sim-knowledge/physics/domain_inference.yaml。
# 这不是硬判断；多条可同时命中，消费者按 confidence + 命中数排序。

schema:
  if_has_time_col:   true|false        # 存在被识别为时间/单调递增的列
  if_n_numeric_gte:  <int>             # 数值列数 ≥ N
  if_col_name_any:   [".."]            # 任一列名（小写、模糊）命中
  if_has_missing:    true|false        # 存在缺失值

clues:
  - id: timeseries-smoothing
    intent: smooth
    confidence: strong
    description: "有时间列 → 可按采样率做滤波/平滑"
    if_has_time_col: true
    suggest: [butterworth_filter, savgol_filter, moving_average, median_filter]

  - id: missing-first
    intent: clean
    confidence: strong
    description: "存在缺失值 → 先补缺/清洗，置顶"
    if_has_missing: true
    suggest: [fill_missing, data_prep]

  - id: multi-numeric-structure
    intent: reduce
    confidence: moderate
    description: "≥3 数值列 → 可看两两相关 / 降维看结构"
    if_n_numeric_gte: 3
    suggest: [correlation, pca]

  - id: spike-cleanup
    intent: feature
    confidence: moderate
    description: "数值列里疑似离群尖峰 → 异常检测 / 中值滤波"
    if_n_numeric_gte: 1
    suggest: [outlier_detect, median_filter]

  - id: mesh-field-present          # 重型领域工具也走同一张表
    intent: map
    confidence: strong
    description: "数据带网格/场结构（多文件 + 坐标场）→ 多物理场映射"
    if_col_name_any: [x, y, z, pressure, nodeid, cellid]
    suggest: [field-mapping]
```

**消费方式**（和 domain_inference 一样）：
1. 从数据集抽信号：`has_time_col / n_numeric / has_missing / col_names`。
2. 逐条评估 `if_*`，全部满足才命中（空条件视为恒真）。
3. 收集命中 → 按 `confidence`(strong>moderate>weak) + 命中数排序。
4. 前端「✨ 适用于这份数据」区按排序展示；agent 选工具时同表当 prior。
5. **没命中任何线索的工具**：不进上下文区，但仍在搜索面板 + 完整列表里 → 永不丢失。

---

## Part 4 · 它怎么一次解决三件事

| 问题 | 解法 |
|---|---|
| **Q4 工具一大串** | 不再按算法家族平铺；按 `intent` 分段 + 搜索面板 + 线索表上下文推荐 |
| **归不进去** | 没有写死的固定桶可「不匹配」；分组是 `tags`/线索表算出的**视图**，候选排序兜底 |
| **Pillar 4 发布格式** | 专家发布 = 提交一个 skill 文件夹（SKILL.md + known_issues + reference + algo）；零平台改动 = 自我扩展 |
| **北极星** | `SKILL.md` 本身就是「专家关于某工具的经验，写下来让非专家的 agent 正确用它」——`must_verify`/`known_issues` 即被蒸馏的专家经验 |

---

## Part 5 · 落地顺序（增量、不破坏现有）

1. **加字段，不动执行层**：`AlgorithmSpec` 加 `intent`/`domain`/`use_when`（可选，默认从 `category` 推）。`registry.py` 不动逻辑。✅ 向后兼容。
2. **前端按 intent 分段**：`algoMeta.ts` 加 `category→intent` 映射，LibraryView 改分段渲染（= redesign 改法 A）。
3. **线索表上线**：加 `data_clues.yaml` + 一个评估器，前端「✨ 适用于这份数据」区消费（= 改法 C）。
4. **搜索面板**：复用 `use_when`/`examples`/`aliases`（= 改法 B）。
5. **重档样板**：把「多物理场场映射」做成第一个 skill 文件夹，验证发布格式（= Pillar 4 旗舰 demo）。

每步都能独立上线、独立回滚。

---

## 待你判断（审核要点）

1. **`intent` 词表定几个、怎么命名**？建议 `clean/smooth/feature/fit/reduce/map/verify` 7 个——`map` 和 `verify` 是现在缺的两类（`interpolate` 其实该从「找特征」挪到 `map`；`verify` 暂时空着当提醒）。要不要这套？
2. **线索表放 YAML 还是直接进 `AlgorithmSpec`**？YAML 的好处是 agent 可读、专家可改、和代码解耦（sim-knowledge 的选择）；进 spec 的好处是少一个文件。倾向 YAML，但听你的。
3. **重档 skill 文件夹放后端 `backend/app/skills/` 还是独立仓**（像 sim-skills 那样可单独 clone / 被多项目复用）？现在建议先放后端，跑通再谈拆仓。
4. **`description` 触发式改写**要不要全量做？13 个内置算法改写工作量小；但要确认「触发式」是你想要的语气（给非专家看）。
5. **`must_verify` 的执行力度**：只是展示给用户的提示，还是真的在 flow 里挂一个校验步？前者轻、后者才真正兑现「可验证」。这条最值得拍。
