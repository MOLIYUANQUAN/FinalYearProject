# 云上 Friday + iPhone App（整条链路）

目标：电脑关机也能聊；以后若多人用，不会绑在某一台 Windows 上。  
原则：**一个代理、一段关系**；手机和电脑打的是同一套 API。

## 总览

```text
iPhone App  ──HTTPS + 登录──►  Friday API（云上常开）
浏览器/电脑 ─────────────────►         │
                                       ├─ OpenAI
                                       ├─ Google Calendar / Tasks / Gmail
                                       └─ 每用户自己的记忆与配置
```

- **现在（FYP）：** 云上先只服务 Jimmy 一个人（单租户做稳）。  
- **以后做大：** 同一套 API 按「用户」隔离数据与 Google 授权；不做成多智能体。

## 分步（按依赖，不要并行摊开）

### A. 云上跑起来（大脑搬家）· 进行中

选定 **Fly.io**（伦敦 `lhr`），应用名默认 `friday-jimmy`。仓库里已有：

- `Dockerfile` — 容器里跑 `python -m src.main`（`HOST=0.0.0.0`，`PORT` 由平台注入）  
- `fly.toml` — HTTPS、健康检查 `/api/health`  
- `scripts/deploy_fly.py` — 把 `.env` 与 `secrets/*.json` 导入 Fly secrets 并 deploy  
- 云上用环境变量落下密钥：`GOOGLE_CREDENTIALS_JSON`、`GOOGLE_TOKEN_JSON`、`GMAIL_TOKEN_JSON`、`GOOGLE_TASKS_TOKEN_JSON`

**你这台机器上跑一次：**

```powershell
# 1) 安装 flyctl（只需一次）
powershell -ExecutionPolicy Bypass -File scripts\install_flyctl.ps1

# 2) 浏览器登录 Fly（只需一次）
flyctl auth login

# 3) 部署（会读本机 .env 和 secrets/，不会把密钥打进 Git）
.\.venv\Scripts\python.exe scripts\deploy_fly.py
```

脚本结束会打印：`https://friday-jimmy.fly.dev/?access=…`  
iPhone Safari 打开即可；**电脑可关机**。

若 Google 报 `redirect_uri_mismatch`：在 Google Cloud 给该域名加上授权来源/回调，本机重新 `auth_google_*.py`，再跑一遍 `deploy_fly.py`。

本机 `8765` + 隧道（[phone-access.md](phone-access.md)）只作开发过渡。

### B. 登录（证明是你）

1. 所有 `/api/*` 必须带会话（比临时访问码更正式）。  
2. 第一刀：你设的强密码或魔术链接；有 Apple Developer 后再加 Sign in with Apple。  
3. 电脑浏览器与 App 共用同一登录。

### C. iPhone App（壳 + 同一套 UI）

1. 用 Capacitor（或同类）把现有页面打成 iOS 包：图标、全屏、安全区。  
2. API 指向云域名；装到你的手机（Xcode / TestFlight），不急着公开上架。  
3. 验收：主屏幕点 Friday → 登录 → 说「提醒我明天续借书」→ Tasks 里有。

纯 SwiftUI 重做聊天可以后做；API 稳定比换皮重要。

### D. 以后才做（有用户再加）

| 能力 | 何时 |
| --- | --- |
| 多用户隔离（每户自己的 token / 记忆） | 第二个真人要用之前 |
| 语音进/出 | 计划里手机之后的优先级 |
| 推送（会前轻轻一下） | 你真的会靠它提醒之后 |
| App Store 公开审核 | 自己天天用稳了再说 |

## 多用户时怎么长（现在不实现，只定方向）

- **不要**每人一个「AI 员工」进程。  
- **要**的是：请求带 `user_id`，Google token、记忆、档案按用户分开放。  
- 计费 / 配额以后再加；FYP 阶段不做成平台后台。

## 和「四个绝不」

云上一样：日程邮件待办新闻都不许编；写操作仍先确认（待办可撤销）。  
密钥永不进 Git；日志不记对话正文（沿用现在的 usage 元数据习惯）。
