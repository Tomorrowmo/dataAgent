# RLab Cortex on DeepSeek Harness

把 DataAgent 的能力搬到 dsh 插件架构上的实现。这一层**在 dsh 仓库之外**，不 fork 它——dsh 自己声明处于开发者预览、会有破坏性变更，树外插件加 patch 叠加让升级只需重跑构建，而不是每次解合并冲突。

## 现在能干什么

一个跑在 dsh 上的数据分析 agent，具备：

- **数据集**：列出、预览，识别源数据与派生数据及其血缘
- **算法**：列出内置算法目录、查参数 schema、在数据集上执行，结果落为**带血缘的派生数据集**
- **风洞质量检查**：列批次、执行检查、看逐条判定（含原因分析/影响评估/处理建议）、出报告与跟班记录
- 以及 dsh 白送的：会话持久化与 fork、上下文自动压缩（没有步数上限）、子 agent、审批门禁、计划模式、技能体系、MCP、后台任务

## 架构

```
浏览器 / CLI
    │
  dsh 实例（Node）
    ├── @rlab/dsh-tool-dataagent      ← 19 个模型可见工具 + /rlab/api 只读桥接
    ├── @rlab/dsh-client-ui-dataagent ← 工具视图 + RLab 工作台
    └── dsh 自带的 agent loop / 会话 / UI
    │  内部 HTTP（回环）
    ▼
计算面 sidecar（Python, :8078）
    算法执行 · AST 沙箱 · 风洞 15 模块 · 解析 · parquet · 导出
```

科学计算栈**不迁移**：算法与风洞模块建在 pandas/scipy/sklearn 上，且由 `backend/wt_golden.json` 的客户对齐数字钉死。重写它们等于把那份可信度作废。

## 跑起来

### 1. 计算面 sidecar

```powershell
cd backend
$env:BACKEND_LOG_FILE = "..\tmp\sidecar.log"
.\.venv\Scripts\python.exe -u -m uvicorn app.sidecar:app --host 127.0.0.1 --port 8078
```

首次启动会慢（Windows 杀毒冷扫 pandas/sklearn，可能几分钟）。它先绑端口再加载，所以 `/api/health` 立刻可答，数据路由在就绪前返回可重试的 503。

**必须只绑回环**。sidecar 没有认证——认证归网关。插件加载时会拒绝非回环的 `baseUrl`。

### 2. 构建插件

```powershell
cd dsh
pnpm install
pnpm run build
```

依赖用 `link:` 指向本地 dsh checkout（`d:\Git\GitBubProj\DeepseekHarness`）。见下方「已知问题」里的版本偏差说明。

### 3. 装进 profile

编辑 `%USERPROFILE%\.dsh\profiles\<profile>\package.json`，加一行依赖后 `pnpm install`：

```json
"dependencies": {
  "@rlab/dsh-tool-dataagent": "link:D:/Git/Personal/DataAgent/dsh/packages/tool-dataagent"
}
```

（`dsh plugin --profile <name> add` 在 Windows 跨盘符时会把路径拼坏，所以直接改 package.json。）

### 4. 启动

Web 界面（工具 + 浏览器视图）：

```powershell
$env:DEEPSEEK_API_KEY = "<你的 key>"
node <dsh>\apps\cli\lib\bin.js --profile web `
  --patch ...\rlab.patch.yml `
  --patch ...\rlab-web.patch.yml `
  --patch ...\dev-llm.patch.yml
# → http://127.0.0.1:3080
```

单次任务（命令行，只要工具）：

```powershell
node <dsh>\apps\cli\lib\bin.js --profile headless `
  --patch ...\rlab.patch.yml --patch ...\dev-llm.patch.yml `
  "列出数据集，用 savgol 滤一下带噪信号那份"
```

**两个叠加层必须分开用**：loader 会 import 每个条目的 Node 半，不管当前组合有没有前端。在 headless 上叠 `rlab-web.patch.yml` 会直接启动失败（那个包没装进 headless profile）。

浏览器半需要先单独打 bundle（tsc 只出类型，不出 bundle）：

```powershell
cd dsh\packages\client-ui-dataagent
& <dsh>\node_modules\.bin\tsdown.CMD --env.DSH_BUILD_FACE client
```

## 目录内容

| 文件 | 作用 |
|---|---|
| `packages/tool-dataagent/src/index.ts` | 数据集与算法工具，插件入口 |
| `packages/tool-dataagent/src/webroutes.ts` | `/rlab/api` 同源只读桥接 |
| `packages/client-ui-dataagent/` | 浏览器半：工具视图 + RLab 工作台 |
| `verify_ui.py` | 无头浏览器验证工作台真的渲染并显示真实数据 |
| `packages/tool-dataagent/src/windtunnel.ts` | 风洞质量检查工具 |
| `packages/tool-dataagent/src/sidecar.ts` | 计算面 HTTP 客户端，回环校验 |
| `rlab.patch.yml` | 把插件插进任意 profile 的叠加层 |
| `dev-llm.patch.yml` | 开发用 LLM 叠加层（OpenAI 兼容端点，不含密钥） |
| `seed_demo_dataset.py` | 造一份带噪正弦演示数据 |
| `verify_phase2.py` | 独立核实端到端结果，含降噪的数值判据 |

## 工具清单

| 工具 | 作用 |
|---|---|
| `dataset_list` | 列出数据集，含血缘 |
| `dataset_preview` | 预览行与列名（上限 200 行） |
| `algo_list` | 算法目录，可按分类过滤 |
| `algo_describe` | 单个算法的参数 schema 与来源 |
| `algo_run` | 执行算法 → 落带血缘的派生数据集 |
| `wt_batch_list` | 列出风洞批次 |
| `wt_check` | 执行批次质量检查 |
| `wt_findings` | 单车次逐条判定 + 未评定项 |
| `wt_report` | 生成质量检查报告 / 跟班记录 |
| `algo_test` | 在 AST 沙箱里测试模型写的 Python 算法 |
| `algo_save` | 入库成永久可调用工具（有门禁，见下） |
| `dataset_ingest` | 把磁盘上的数据文件导入成数据集 |
| `flow_save` | 把一串分析步骤存成可复用的流程模板 |
| `flow_list` | 列出流程模板 |
| `flow_replay` | 在新数据集上重放模板，逐步落带血缘的中间结果 |
| `parser_save` | 为平台不认识的格式写解析器并注册成格式适配器 |
| `dataset_clean` | 写一段整理代码产出干净的新数据集（原始不动） |
| `mapping_list` | 列出列名 → 角色映射规则 |
| `mapping_save` | 记录某个列名的固定含义（如 `U(V)` → `voltage`） |

两条领域规矩写进了系统提示词，不是靠模型自觉：**未评定不等于合格**，以及**四段判定直接引用、不得自行改写**。

### 自扩展的门禁是真的

`algo_save` 不是"提示模型要先测试"，是**强制**的：

1. `algo_test` 记录通过沙箱的代码的 SHA-256 指纹；
2. `algo_save` 拒绝指纹不在集合里的代码——跳过测试不行，**测完再改一个字也不行**，指纹覆盖的是实际跑过的字节；
3. 有 UI 时（web profile），再经 `ctx.userQuestions` 停下来等人批准。

「没有人可问」和「问了人说不」被严格区分：headless 没有 UI，走沙箱门禁并把结果标为 `humanApproved: false`；用户真的否决则整个调用失败。把这两件事合并，会让无人值守的运行看起来像被批准过。

## 工作台（浏览器界面）

dsh 的外壳是刻意以对话为中心的：`sidebar` 和 `conversation` 都是**单占位**插槽，注册进去是整列替换而不是添加。唯一被文档标为可加的整框架座位是 `shell.overlay`，所以 RLab 自己的视图挂在那里——右下角一个「工作台」按钮，点开是全框架面板，Esc 关闭。关闭时该层是点击穿透的，底下的对话完全不受影响。

目前两个视图：

- **数据集** —— 血缘树而不是列表。源数据是根，派生数据集缩进嵌套在父节点下，每条边标注产生它的算法。右侧是选中数据集的预览表。
- **算法库** —— 按来源区分内置 / 用户上传 / AI 生成，未通过沙箱测试的明确标红。这个区分是产品前提（「经过验证的经典算法优先」）的可视化，不该藏进详情页。

### 视图为什么是只读的

浏览器读数据走 `/rlab/api/...`——由 host 插件代理到计算面的**同源只读**桥接。三条理由：

1. 页面不该直连 sidecar：它没有认证，而且将来浏览器只能看见网关；
2. 同源路径在网关架构下不用改，动的是 harness 不是页面；
3. **写操作一律走工具调用**，这样才会进会话日志、可回放可审计。一个按钮在模型背后悄悄改了数据，产品的可追溯性就破了。桥接对非 GET/HEAD 直接拒绝并说明理由。

## 验证

```powershell
# 契约：79 项，对 sidecar 与原后端都适用
cd backend
$env:WT_API="http://127.0.0.1:8078/api"; $env:WT_NO_AUTH="1"
.\.venv\Scripts\python.exe wt_contract_test.py

# 端到端：agent 落下的派生数据集是否真的降了噪
.\.venv\Scripts\python.exe ..\dsh\verify_phase2.py
```

`verify_phase2.py` 不看 agent 说了什么，只看计算面里的事实——包括滤波后对真值的 RMSE 是否真的下降。HTTP 200 证明不了算法跑对了。

## 数据整理的可信度：一个没有完全解决的问题

`dataset_clean` 加了两道护栏，因为实测暴露了真实风险：

- **静默丢行**。第一次实测，清洗把 50 行变成 5 行、接口返回 200、模型报告"成功"。**丢了 90% 的数据，没有任何东西发现**。现在工具在清洗前先读源行数，把 `50 → 5` 和丢失比例摆在输出里，超过 30% 明确告警。
- **列坍缩**。加了行数护栏后重测，模型这次保住了 50 行——但把表压成 1 列、内容全是重复的 `"充电"`。**它满足了我新加的指标，在另一个维度上失真了**。所以又加了列数检查。

结论要说清楚：**这两道护栏能发现明显的结构性损坏，但保证不了内容正确。** 行数对上不等于数据对了。真正的判断仍然要人看一眼新数据集，工具能做的是让"该看一眼"这件事无法被忽略。

根因还在更上游：那份脏 CSV 在**导入时**就被解析坏了——标题噪声被当成表头，整个文件塌成一列，清洗是在一个已经损坏的表示上做重建。要根治得在导入环节做表头探测，这一项没做。

## 已知问题与未完成

- **版本偏差**：npm 上的 `@deepseek-ai/dsh-*` 是 `0.0.1-rc.1`，本地 checkout 构建的是 `0.1.0-rc.5`。profile 自举装的是 npm 版，插件用 `link:` 指向本地版。目前能工作（`defineTool` 是纯 helper），但这是真实的偏差风险。等 npm 与仓库版本对齐后应改为版本号依赖。
- **工作台目前两个视图**：数据集血缘树与算法库已完成。流程画布、风洞三视图、3D 网格查看器尚未做，见迁移蓝图第 4 阶段。
- **未迁移的能力**：图表生成（`generate_viz`）、图像解析。
- **导入不做表头探测**：首行是标题噪声的 CSV 会整体塌成一列，见上一节。

### 迁移中修掉的两个既有缺陷

都在自扩展的关键路径上，都是先前没被触发过的真实崩溃。

**一、META 的 `returns` 不是字符串时 500。** 对象被直接绑到 `String(32)` 列。AI 写的 META 很自然会用对象描述输出结构，功能一启用就必然撞上。现按指名字段的 400 拒绝，且不做静默改写——把 dict 悄悄换成 `"dataframe"` 会让入库结果与源码自相矛盾。

**二、同一个 slug 存第三次就 500。** 保存是**插入新行**（版本递增），但 13 处按 slug 的查询写的是 `scalar_one_or_none()`，读到第二行即抛 `MultipleResultsFound`。更要命的是**运行路径上也是同一个写法**——一个改过两次的算法之后再被调用同样会崩。迭代算法是最正常的行为，所以这个缺陷让自扩展实际不可用。

修法是统一语义：新增 `app/algorithms/lookup.py::latest_algorithm()`，把「按 slug 查 = 拿当前版本」固定下来，13 处调用点全部改走它。契约测试第 7 段锁住保存 4 次和多版本调用两条。

被改动的既有文件：`app/api/algorithms.py`、`app/api/templates.py`、`app/api/windtunnel.py`、`app/services/chat_agent.py`。

### 其余未完成

- **多用户尚未做**：现在是单实例单用户。网关与实例管理器是第 5 阶段。
- **`dev-llm.patch.yml` 是开发件**，指向一个 OpenAI 兼容端点并把 `maxTokens` 压到 8192（qwen-plus 的上限是 32768，而适配器默认 256000）。正式部署应换成自己的模型配置。
- **Windows 开发有限制**：dsh 的 Python SDK 只支持 Linux/macOS，持久 PTY 需要 POSIX 终端。这两项能力在 Windows 上不可用，正式部署走 Linux 容器。
