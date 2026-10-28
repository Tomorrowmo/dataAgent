# damos —— OIDC 接入演示日记本

一个**完全自包含**的 Flask 小应用，演示产品如何接入统一认证中心（标准 OIDC）：
**登录 / 登出 / 进入自动跳转 / 获取用户信息**，业务是一个按用户隔离的日记本（标题 + 内容）。

整目录可拷走单独运行，不依赖任何外部代码。OIDC 逻辑见 `app.py`。

## 三步跑起来

### 1. 登记客户端，拿 client_id / secret
用管理员账号登录 `https://auth.romtekcae.com:5000/admin` →「OAuth 客户端」→ 新建：
- 名称：`damos 日记本`
- 回调：`http://localhost:5005/auth/callback`（必须一字不差）

记下返回的 `client_id` 和 `client_secret`。

### 2. 配置
```bash
cp .env.example .env
```
编辑 `.env`，填入 `OIDC_CLIENT_ID`、`OIDC_CLIENT_SECRET`，并把 `APP_SECRET_KEY` 改成任意随机串。

### 3. 安装并运行
```bash
pip install -r requirements.txt
python run.py
```
浏览器访问 http://localhost:5005 —— 未登录会自动跳认证中心，登录后即可写日记。

## 演示要点对应代码

| 需求 | 实现位置（`app.py`） |
|---|---|
| 进入自动跳转 | `login_required` 未登录 → `redirect(url_for("login"))` |
| 登录 | `/auth/login` → `authorize_redirect`；`/auth/callback` 换 token 建 session |
| 获取用户信息 | 回调取 `sub/email/name/is_admin` 存 session，首页展示 |
| 登出（单点登出） | `/logout` 清 session → 跳 discovery 的 `end_session_endpoint` |
| 业务按用户隔离 | 日记表 `owner_sub == current_user().id`（OIDC `sub`） |

## 文件

- `app.py` —— Flask 工厂 + OIDC 客户端 + 日记 CRUD 路由
- `db.py` —— SQLite 数据层（标准库）
- `templates/` —— 极简内联样式页面
- `run.py` —— 启动入口（端口 5005）

> 本地用 Flask 开发服务器在 http localhost 跑即可；生产反代/HTTPS 部署要点见
> `../docs/产品接入认证中心指南.md`。
