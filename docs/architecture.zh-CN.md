# Numetrix — 技术架构

## 技术栈一览

| 层 | 选型 | 理由 |
|---|---|---|
| 前端 | Next.js 15（app router）+ Tailwind + TypeScript | 开发期通过 rewrite 实现同源 API；standalone 输出便于打成极小的生产容器 |
| 后端 | FastAPI + SQLAlchemy 2（async）+ Pydantic v2 | 快、强类型、原生 async、易于 Docker 化 |
| 数据库 | SQLite（默认）—— 通过 `DATABASE_URL` 可平滑升级到 Postgres | V1 单文件即可；零运维负担 |
| 对象存储 | 本地磁盘（`UPLOAD_DIR`）—— 可平滑升级到 S3/OSS | V1 一个 volume 搞定 |
| LLM | DeepSeek（OpenAI 兼容协议）—— 默认；用户可 BYOK 到任意兼容端点 | 同档可信模型里最便宜，代码生成能力强；对中国友好 |
| 沙箱 | `python -I` 子进程 + AST 白名单 + 墙钟超时 + 受限 builtins + 尽力而为的 socket 拦截 | 跨平台（Windows / POSIX），不需要 Docker-in-Docker |
| 认证 | Bcrypt + JWT（HS256） | 标准方案、依赖少 |
| 反向代理 | Nginx（包含在 compose 中） | 对 SSE 聊天流式输出友好；加 TLS 时也方便在它前面终止 |

## 请求生命周期

### A. 用户上传数据集

```
浏览器 ─POST /api/datasets─► Nginx ─► Next.js（透传）─► FastAPI
                                                          │
                                                          ▼
                                            pandas 读取 csv/xlsx/parquet
                                                          │
                                                          ▼
                                       以 parquet 形式写入 /data/uploads/user_<id>/
                                                          │
                                                          ▼
                                              插入 Dataset 行 + schema 预览
```

### B. 用户运行内置算法

```
浏览器 ─POST /api/algorithms/run─► FastAPI ─► registry.execute_builtin(slug, df, params)
                                                            │
                                                            ▼
                                              进程内 numpy/pandas/scipy
                                                            │
                                                            ▼
                                       结果 → parquet → /data/uploads/results/
                                                            │
                                                            ▼
                                                 插入 Run 行，返回摘要
```

### C. 用户运行用户/AI 算法

```
浏览器 ─POST /api/algorithms/run─► FastAPI ─► registry.execute_code(code, df, params)
                                                            │
                                                            ▼
                                       sandbox/validator.py（AST 白名单 + 导入检查）
                                                            │
                                                            ▼
                                       subprocess.run(python -I app/sandbox/runner_worker.py)
                                                            │
                                                            ▼
                                       worker：从临时目录读取输入 parquet
                                                            │
                                                            ▼
                                       在受限 builtins 命名空间下 exec(code)
                                                            │
                                                            ▼
                                       写出输出 parquet + JSON 结果分隔行
                                                            │
                                                            ▼
                                       父进程读取 __SANDBOX_RESULT__ 分隔行
                                                            │
                                                            ▼
                                                           数据库
```

### D. 聊天 Agent 一轮对话

```
浏览器 ─POST /api/chat/.../send─► FastAPI ─► chat_agent.run_turn(...)
                                                       │
                                                       ▼
                                  while step < MAX_STEPS:
                                       1. LLM 返回 {thought, action, args}
                                       2. 分派 action：
                                            - list_tools  → registry 索引
                                            - describe    → 算法规格
                                            - run_tool    → 执行内置算法或进入沙箱
                                            - generate    → 代码生成 + 沙箱测试
                                            - answer      → 跳出循环
                                       3. 通过 SSE 把每一步流式推送到浏览器
```

每一个事件（thought、tool_call、tool_result、final）都会持久化到 `Message.meta.events`，以便事后完整重建审计轨迹。

## 沙箱威胁模型

| 威胁 | 缓解措施 |
|---|---|
| 任意代码执行 | 只在子进程中执行 —— 绝不在 API 进程中 `exec` 用户代码 |
| 在临时目录外读写 | `subprocess` 设置 `cwd=workdir`（临时目录），不走 shell，AST 拒绝 `open()`、`__import__`、`eval`、`exec`、双下划线属性访问 |
| 白名单外的 import | 提交时由 AST 校验器拦截；运行时使用受限 builtins |
| 网络访问（数据外泄、SSRF） | AST 拒绝 `socket`、`urllib`、`requests` 等；运行时 monkey-patch `socket.socket` 与 `socket.create_connection` 使其抛错 |
| 死循环 / CPU 耗尽 | 父进程通过 `subprocess.run(timeout=...)` 强制墙钟超时。POSIX 上额外叠加 RLIMIT_CPU + RLIMIT_AS |
| 内存耗尽 | POSIX 上用 RLIMIT_AS。Windows：只能尽力而为地依赖超时 —— 推荐把后端部署在 Linux 容器中（`deploy.sh` 默认就是这么做的） |
| 子进程 fork 炸弹 | POSIX 上设 RLIMIT_NPROC=0（worker 无法 spawn 任何东西） |
| `MemoryError` 拖垮 API | 子进程隔离 —— 子进程挂掉，父进程上报 `status: error` |
| 输出炸弹（`print` 1 TB） | 输出按 `SANDBOX_MAX_OUTPUT_BYTES` 截断；worker 在 200 KB 处截断日志 |
| 长 token / 模型密钥泄漏 | LLM key 永远不发送到用户代码子进程；沙箱无法访问 `DEEPSEEK_API_KEY` 环境变量（worker 通过 `python -I` 启动，等效于 `env.pop("DEEPSEEK_API_KEY")`） |

**当前尚未覆盖（V2 工作项）：** seccomp / cgroups 隔离、eBPF 系统调用过滤、每次执行一容器。对更高保障级别的部署，我们会在下一层引入 Firecracker 风格的 microVM（冷启动约 50 ms）。

## 性能特征（本地 Windows、单笔记本）

| 操作 | p50 延迟 |
|---|---|
| 内置 `linear_regression`（200 样本 × 2 特征） | <20 ms |
| 内置 `savgol_filter`（500 行） | 30–50 ms |
| 用户代码沙箱热路径（500 行） | 400–500 ms（Python 子进程启动开销占主导） |
| LLM 代码生成 + 沙箱测试 | 2–5 s（DeepSeek 调用占主导） |
| 数据集上传 + 写 parquet（10 MB CSV） | <500 ms |

## 扩容方案

| 规模 | 改动 |
|---|---|
| 今日：SQLite + 单 uvicorn worker | 默认 |
| 100 个活跃用户 | 提到 `--workers 4`；仍用 SQLite（<50 写/秒下依然 OK） |
| 1k 个活跃用户 | 把 `DATABASE_URL` 切到 Postgres；把 `/data/uploads` 迁到 S3/OSS；后端容器保持不变 |
| 10k 个活跃用户 | 把沙箱执行拆成单独的微服务 —— Modal / Fly Machines / 自建 Firecracker 池。API 保持不变。 |
| 重度企业级 | 自托管 Kubernetes Helm chart（从这套 compose 派生大约 30 行 values 即可） |

## 为什么在这些地方选了它们，而不是显而易见的替代

- **FastAPI vs Flask**：原生 async（SSE 聊天流式输出必须用），Pydantic v2 的 schema 同时充当请求校验和 OpenAPI 生成。
- **SQLite vs Postgres**：V1 = 零运维。需要时把 `DATABASE_URL` 切到 Postgres 是一行配置改动。
- **子进程沙箱 vs 每次执行一容器 vs Pyodide**：子进程在可移植性（Windows 开发 + Linux 生产共用一套代码）、启动延迟（~400 ms vs Docker 的 ~2–4 s）和运维简洁性上都赢。浏览器端 Pyodide 一度很诱人，但 2026 年仍没法稳定跑 scipy/pandas 的 wheel。
- **Next.js standalone 输出 vs 静态资源 + 独立 API**：standalone 让生产容器很小（~120 MB），并允许我们在同一个 nginx 上游对里提供全部服务。
- **DeepSeek vs OpenAI/Anthropic**：2026 年 5 月，DeepSeek 是 OpenAI 兼容协议这一档里最便宜的可信代码生成器。对中国也友好。BYOK 让企业客户可以选他们想要的任何模型。
- **Bcrypt + JWT vs OAuth2/Session**：单人创始人的取舍。等团队里有一个人的岗位描述里包含「认证」时再加 OAuth2（Google / GitHub）。

## 失败模式与已知限制

- 单租户 SQLite：在切到 Postgres 之前没法横向扩展。如果 V1 继续用 SQLite，不要把 uvicorn worker 数量调到大于 1（设 `--workers 1`）。
- 沙箱没有 seccomp 隔离。在没加 seccomp 之前，不要把它直接暴露到公网上服务完全不可信的人群（V2 工作项）。
- 结果 parquet 文件会永久占据 volume。在累计到百万次运行之前，加一个周期性清理任务。
- 聊天 Agent 没有 tool-call 格式协商 —— 它依赖模型返回合法 JSON。DeepSeek 和现代的 Claude/GPT 都很可靠；更老 / 更小的开源模型可能漂移。修法：加一个 JSON 修复重试循环，或者迁移到原生 tool-calling 协议。
