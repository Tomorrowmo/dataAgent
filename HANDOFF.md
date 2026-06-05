# Numetrix — Handoff Note

> ⬇️ 顶部为 **2026-06-03 会话最新交接**;再下面的「What's built / Deploy…」是初版构建会话的历史记录(部分已过时,如"20 algorithms"现为 13 内置 + AI 生成)。

---

# 🆕 2026-06-03 会话交接

## 核心方法论(本会话确立)
**数据是血缘 DAG,不是列表。** 节点 = 数据制品(`source`/`derived`,带 `derived_from`+`lineage`),边 = 一次变换(算法+参数=可复用配方)。三层:**源数据 / 产出(留存) / 中间结果(默认临时、折叠)**;名字只给短标签,血缘用树/面包屑展示;流程=DAG 可编辑配方,数据=DAG 节点,共享同一张图。

## 本会话建成(全部已上线)
- **数据集页 = 血缘树**(源为根、派生折叠、面包屑、留存);**对话顶部 = 紧凑搜索下拉**(只列源数据)。
- **流程模板 = 可编辑画布**(算法库「流程模板」Tab):节点改参(列选/枚举/AI 调)、增删/上下排序/改名、保存修改 / 保存并回放;回放逐步喂入下一步并落为带血缘派生数据集。
- **算法面板(纯手动,不依赖 AI)**:原始数据预览(可多看行)→ 填参(或 **AI 推荐参数**)→ 执行 → **解读结果** / 报错**人话解释** / **导出 CSV·Excel**。
- **对话流水线**:一轮内串联 + 逐步**物化派生数据集**(中间结果可在数据集页查看)。
- 多 sheet Excel 拆分;**AI 整理脏数据**;**generate_viz**(AI 写图);多数据集**叠加对比**;工具枚举防猜错+报错自愈;`max_steps=8`。
- 修复:新会话竞态、spinner 不停、JSON 自愈、语言混用、FFT 死循环、流水线 KeyError 等。

## 三条 codegen(自扩展)
解析器(未知格式)· 算法(`generate_tool` 测试通过即注册)· 可视化(`generate_viz`);外加 AI 整理脏数据。

## Backlog(未做)
- **Pillar 4:把流程/结果发布成可独立运行的小程序。**
- 派生数据集自动回收;「产出」层未独立建模(暂用 promote→`kind=source`);流程画布未做 React-Flow 自由拖拽;跨轮流水线状态(`working` 每轮重置)。

## 运维 / 启动(踩过的坑)
- 后端 :8077。venv python 启:`cd backend; $env:BACKEND_LOG_FILE='..\tmp\backend.log'; .\.venv\Scripts\python.exe -u -m uvicorn app.main:app --host 127.0.0.1 --port 8077 --log-level info`。前端 :3000,改完**硬刷新**。
- **冷导入坑**:首次 import pandas/sklearn 被杀毒扫,缓存凉时 10–20 分钟;热后秒级。(用户不用 Defender 排除项,就耐心等,别反复杀进程。)
- **旧实例坑**:残留 uvicorn 占 :8077 跑旧代码 → 新实例绑不上、新路由返回 **405**。按端口找真正 LISTENING 的 PID(`netstat -ano | findstr :8077`)杀掉,再起一个,用「新路由返 401 而非 405」验证。

## 下个会话开局输入(粘贴)
> 继续 Numetrix(d:\Git\Personal\DataAgent)。先 `curl http://127.0.0.1:8077/api/health` 确认后端;没起就 venv python 跑 uvicorn(见运维段),冷导入要等几分钟。前端 :3000 硬刷新。这次想做:**【填:如 Pillar 4 发布小程序 / 派生数据集自动回收 / 流程画布升级可拖拽】**。背景见本文件 + 项目记忆(血缘 DAG / 可编辑流程 / 算法面板),保留纯计算不依赖 AI 的手动路径。

---

# 📜 初版构建会话记录(历史,部分过时)

## What's built

**A full, working product**, not a prototype.

- **Backend:** FastAPI + SQLAlchemy + sandboxed Python executor + 20 built-in algorithms + DeepSeek LLM client + ReAct chat agent + auth + dataset/algo/run REST API.
- **Frontend:** Next.js 15 + Tailwind landing page, login/signup, full chat workspace with dataset upload + algorithm library browser + user-code upload (sandbox-tested) + AI codegen panel + settings (BYOK).
- **Docker stack:** multi-stage backend + frontend images, nginx reverse proxy, Docker volume for persistent data, one-shot `deploy.sh` and `deploy.ps1`.
- **Docs:**  `README.md`, `docs/positioning.md`, `docs/business-plan.md`, `docs/architecture.md`.

## Live right now on your laptop

A Docker stack is currently running on this machine (assuming you don't reboot before reading):

- http://localhost:8088  ← nginx, full app
- http://localhost:8077  ← legacy host-side dev backend (also running)
- http://localhost:3000  ← legacy host-side dev frontend

To stop everything:

```bash
cd d:\Git\Personal\DataAgent
docker compose -f deploy/docker-compose.yml down
# and kill the two host-side dev processes from the Background section of your shell
```

To restart the Docker stack later:

```bash
cd d:\Git\Personal\DataAgent
REGISTRY=docker.m.daocloud.io/ PUBLIC_PORT=8088 PUBLIC_ORIGIN=http://localhost:8088 \
  docker compose -f deploy/docker-compose.yml up -d
```

## Tested end-to-end

1. ✅ `python smoke_test.py` — all 8 smoke tests pass (algorithm registry · linear regression · Savgol · Dixon outlier · sensitivity ranking · user code in sandbox · AST rejects malicious code · timeout kills infinite loop)
2. ✅ `npm run build` — 0 TypeScript errors, all 5 routes prerendered (landing / login / signup / app / 404)
3. ✅ Host-side HTTP smoke: signup → 20 algorithms listed → upload 500-row CSV → run savgol → 500 rows back in 482 ms
4. ✅ Containerised HTTP smoke through nginx (port 8088): signup → 20 algorithms → upload CSV → savgol → 500 rows in 1162 ms

The **only** thing not tested end-to-end is the chat/AI-codegen path against a real DeepSeek API key — because you said you'd configure it later. The orchestration code, JSON action protocol, sandboxed code test, and approve-then-save flow are all wired up and waiting for a key. Drop a key into `backend/.env` (`DEEPSEEK_API_KEY=sk-…`) or into the app's Settings (BYOK) and the chat agent + the "Generate with AI" tab light up.

## Deploy to Aliyun / Tencent Cloud — three steps

1. Provision a small ECS / CVM (2 vCPU / 4 GB RAM / 40 GB SSD; Ubuntu 22.04 or 24.04). Open port 80 inbound in the security group.
2. `scp -r d:\Git\Personal\DataAgent root@<your-ip>:/opt/numetrix` (or `git clone` if you push to a repo first).
3. `ssh root@<your-ip>` and run:

```bash
cd /opt/numetrix
DEEPSEEK_API_KEY=sk-...   PUBLIC_PORT=80   PUBLIC_ORIGIN=http://<your-ip> \
  bash deploy/deploy.sh
```

That's it. The script installs Docker if missing, auto-detects China network and switches to the daocloud mirror, generates a fresh JWT secret, builds the two images, brings the compose stack up, and prints the public URL.

To later upgrade: `git pull && bash deploy/deploy.sh` — Docker volume persists user data across rebuilds.

## What to do in your first hour back

1. **Verify the running stack still serves traffic.** Open http://localhost:8088 — landing page should load; click "Start free", create an account, navigate to Algorithm library to see all 20 built-in tools.
2. **Drop your DeepSeek key in Settings.** Then go to Chat, pick a dataset, ask "smooth voltage_v with a Savgol filter and tell me how much noise was removed".
3. **Stand up the cloud deployment.** Follow the three steps above. Aliyun ECS preemptible (~¥0.3/hr) is enough for the demo.
4. **Read `docs/business-plan.md`.** Sections 3 (GTM) and 8 (the next 30 days) are the actionable parts.
5. **Cold-DM 5 battery test engineers on LinkedIn** with the public demo URL. Goal: 1 reply this week.

## What's deliberately NOT built (and what to do about it)

| Missing | Why | When to add |
|---|---|---|
| Postgres | sqlite is fine for V1 | When DAU > ~200 |
| S3/OSS upload | local disk via Docker volume is fine | Same trigger |
| Stripe / billing | premature without paying customers | When the first design partner says yes |
| Email verification | UX friction during demos | Before public marketing launch |
| Password reset | same | Same |
| Marketing analytics (Plausible) | quick to drop in | Day 1 of public launch — paste a snippet in `web/app/layout.tsx` |
| Battery / CAE algorithm packs | the vertical content moat | Q3 / Q4 2026 per business plan |
| Seccomp-isolated sandbox | Python subprocess + AST + rlimit is OK for trusted-team use | Before opening sandbox to fully untrusted users |
| Real OAuth (Google / GitHub) | not needed for design-partner phase | Q4 2026 |

## Where the source of truth lives

| Question | Read |
|---|---|
| "What is this product?" | `README.md` |
| "Why this product, why now, who's it for?" | `docs/positioning.md` |
| "How does it make money, what's the GTM?" | `docs/business-plan.md` |
| "How does it work under the hood?" | `docs/architecture.md` |
| "What's the algorithm catalog?" | `README.md` § Built-in catalog, or hit `/api/algorithms` |
| "How safe is the sandbox?" | `docs/architecture.md` § Sandbox threat model |
| "How do I deploy?" | `README.md` § Quick start (cloud), or this file § Deploy |

## One-line summary

You now have a verifiable data-analysis agent positioned for engineers and scientists (V1 wedge = battery test), with a working algorithm sandbox, an AI-codegen pipeline gated by sandboxed tests, a real production-shaped UI, and a one-command path to live on Aliyun/Tencent ECS. Ship it.
