# 云上 Friday + iPhone App（整条链路）

目标：电脑关机也能聊；以后若多人用，不会绑在某一台 Windows 上。  
原则：**一个代理、一段关系**；手机和电脑打的是同一套 API。  
产品顺序见 [plan.md](plan.md) 的「五刀」——本页只写刀 1 的工程链路。

## 总览

```text
iPhone App  ──HTTPS + 会话 Cookie──►  Friday API（云上常开）
浏览器/电脑 ───────────────────────►         │
                                             ├─ OpenAI
                                             ├─ Google Calendar / Tasks / Gmail
                                             └─ 每用户自己的记忆与配置（以后）
```

- **现在（FYP）：** 云上先只服务 Jimmy 一个人（单租户做稳）。  
- **以后做大：** 同一套 API 按「用户」隔离数据与 Google 授权；不做成多智能体。

## 分步（按依赖，不要并行摊开）

### A. 云上跑起来（大脑搬家）· 已通

选定 **Fly.io**（伦敦 `lhr`），应用名默认 `friday-jimmy`。仓库里已有：

- `Dockerfile` — 容器里跑 `python -m src.main`（`HOST=0.0.0.0`，`PORT` 由平台注入）  
- `fly.toml` — HTTPS、健康检查 `/api/health`、机器常开  
- `scripts/deploy_fly.py` — 把 `.env` 与 `secrets/*.json` 导入 Fly secrets 并 deploy  
- 云上用环境变量落下密钥：`GOOGLE_CREDENTIALS_JSON`、`GOOGLE_TOKEN_JSON`、`GMAIL_TOKEN_JSON`、`GOOGLE_TASKS_TOKEN_JSON`

**再部署：**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_flyctl.ps1   # 只需一次
flyctl auth login                                                    # 只需一次
.\.venv\Scripts\python.exe scripts\deploy_fly.py
```

打开 `https://friday-jimmy.fly.dev/`（不必再把访问码钉在书签里；登录一次即可）。

若 Google 报 `redirect_uri_mismatch`：在 Google Cloud 给该域名加上授权来源/回调，本机重新 `auth_google_*.py`，再跑一遍 `deploy_fly.py`。

本机 `8765` + 隧道（[phone-access.md](phone-access.md)）只作开发过渡。

### B. 会话登录（证明是你）· 正在做

目标：像产品，不像「贴访问码的工具站」。

1. `POST /api/login` 校验 `FRIDAY_ACCESS_TOKEN`（界面叫密码），写下 httpOnly Cookie。  
2. 之后所有 `/api/*` 认 Cookie；`Authorization: Bearer` 与一次性 `?access=` 仍可用（桌面启动器兑换）。  
3. 电脑浏览器与以后 App 共用同一登录；Safari / WebView 里 `credentials: "include"`。  
4. 有 Apple Developer 后再加 Sign in with Apple；现在不并行摊开。

### C. iPhone App（壳 + 同一套 UI）· 登录稳了接着做

1. 用 Capacitor（或同类）把现有页面打成 iOS 包：图标（白环）、全屏、安全区。  
2. API 指向云域名；装到你的手机（Xcode / TestFlight），不急着公开上架。  
3. 验收：主屏幕点 Friday →（已登录则直接进）→「提醒我明天续借书」→ Tasks 里有。

纯 SwiftUI 重做聊天可以后做；API 稳定比换皮重要。Windows 上先把 Web 与登录做稳；打 iOS 包需要 Mac / Xcode 一步。

### D. 以后才做（有用户再加）

| 能力 | 何时 |
| --- | --- |
| 多用户隔离（每户自己的 token / 记忆） | 第二个真人要用之前 |
| 语音进/出 | 计划里刀 4 |
| 推送（会前轻轻一下） | 你真的会靠它提醒之后 |
| App Store 公开审核 | 自己天天用稳了再说 |

## 多用户时怎么长（现在不实现，只定方向）

- **不要**每人一个「AI 员工」进程。  
- **要**的是：请求带 `user_id`，Google token、记忆、档案按用户分开放。  
- 计费 / 配额以后再加；FYP 阶段不做成平台后台。

## 和「四个绝不」

云上一样：日程邮件待办新闻都不许编；写操作仍先确认（待办可撤销）。  
密钥永不进 Git；日志不记对话正文（沿用现在的 usage 元数据习惯）。
