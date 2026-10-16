# Personal Agent

Manchester CS FYP（Jimmy）：**单一 Personal Agent** — 认识你、盯住生活碎片、带主见回应。

> **产品北星（先读这个）：** [docs/product-north-star.md](docs/product-north-star.md)  
> 成功标准是 Tuesday test（普通周二愿不愿意打开），不是 Demo 分数。评测扩写 / 合 `main` / 新 tag 在爱用门禁通过前冻结。

**学术路线：** Baseline → Application → Evaluation（证据见 [docs/evaluation/](docs/evaluation/)，当前冻结）  
**Baseline 快照：** tag [`baseline-v1`](https://github.com/MOLIYUANQUAN/FinalYearProject/releases/tag/baseline-v1) · [docs/baseline-v1.md](docs/baseline-v1.md)  
**接入说明：** [Google Calendar](docs/google-calendar-setup.md) · [Gmail](docs/gmail-setup.md) · [Personal](docs/application-personal-v1.md) · [Memory](docs/application-memory-v1.md)

## 成功标准

| # | 标准 | 判定 |
|---|------|------|
| S1 | 单一 Personal Assistant Agent | 全程只有一个 agent |
| S2 | 简单输入界面 | 浏览器可输入并看到回复 |
| S3 | 工具可被调用 | calendar + files 已注册并可执行 |
| S4 | 单工具：明天下午安排 | 只走日历，回答正确 |
| S5 | 文件：找 FYP proposal 并概括 | 基于 `data/notes/fyp-proposal.md` |
| S6 | 多工具链：准备明天 FYP meeting | 日历 → 文件 → meeting brief |
| S7 | Mock/本地数据 | `data/` 下 JSON/Markdown，无云端 OAuth |

## 技术栈

- Python 3.11+
- [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/)（`openai-agents`）
- FastAPI + 单页静态 HTML
- 本地数据：`data/calendar.json`、`data/notes/*.md`

## 工具

1. `get_calendar_events` / `create_calendar_event` — 日历（创建须确认）  
2. `search_emails` / `read_email` / `send_email` / `modify_email` — Gmail（发送/归档需确认）  
3. `search_files` / `read_file` — 本地笔记  
4. `get_personal_context` — 静态个人偏好  
5. `remember_fact` / `search_memory` / `forget_fact` — 本地长期记忆  
6. `request_user_confirmation` — 写操作前请求确认  

Web 聊天支持多轮 `history`（确认 → 创建）。见 [docs/application-calendar-write-v1.md](docs/application-calendar-write-v1.md)。

## 「明天」如何解析（重要）

演示使用**固定的模拟「今天」**，不依赖你机器上的真实日期：

| 概念 | 值 |
|------|-----|
| 模拟今天 `MOCK_TODAY` | `2026-10-12` |
| 「明天」 | `2026-10-13` |

- Agent 的 instructions 会告知模型：今天 = `2026-10-12`，明天 = `2026-10-13`。  
- 调用 `get_calendar_events` 时，`date` 必须是 `YYYY-MM-DD`（例如明天 → `2026-10-13`）。  
- Mock 日历里 **FYP meeting** 安排在 `2026-10-13T14:00–15:00`（Kilburn Building），因此「明天下午」会命中该会议。  

修改演示日期：编辑 `src/config.py` 中的 `MOCK_TODAY` / `MOCK_TOMORROW`，并同步更新 `data/calendar.json` 中的事件日期。

## 如何运行

### 1. 环境

```bash
cd FinalYearProject
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. API Key

```bash
cp .env.example .env
# 编辑 .env，填入：
# OPENAI_API_KEY=sk-...
```

若未配置 `OPENAI_API_KEY`：

- 启动时终端会打印明确警告；
- 页面健康检查显示「缺少 OPENAI_API_KEY」；
- `/api/chat` 返回 **503** 与中文错误说明。

### 3. 启动

```powershell
# Windows 一键
.\scripts\start.ps1

# 或
.\.venv\Scripts\python.exe -m src.main
```

浏览器打开：<http://127.0.0.1:8765> — 应直接看到个人态势（认识你 + 今天），无 Demo 按钮墙。

### 4. 可选 CLI 三条 Demo

```bash
python scripts/demo_cli.py
# 同时写入 Evaluation 证据 JSON：
python scripts/demo_cli.py --save
```

### 5. 从 tag 复现 Baseline（报告用）

```bash
git fetch --tags
git checkout baseline-v1
```

然后按上面「环境 → API Key → 启动」步骤操作。详细说明见 [docs/baseline-v1.md](docs/baseline-v1.md)。

## 分支约定

| 引用 | 用途 |
|------|------|
| `develop` | 日常开发 |
| `main` | 重大里程碑 |
| tag `baseline-v1` | 报告复现 Baseline |

## Demo 脚本（验收）

1. **明天下午安排**  
   输入：`我明天下午有什么安排？`  
   期望：调用 `get_calendar_events`（date=`2026-10-13`, afternoon），提到 FYP meeting（14:00、Kilburn Building）。

2. **FYP proposal**  
   输入：`找到我的 FYP proposal，告诉我项目在做什么。`  
   期望：`search_files` → `read_file`，概括个人 AI 助手 / Baseline 目标（内容来自文件）。

3. **准备明天 FYP meeting（硬验收）**  
   输入：`帮我准备明天的 FYP meeting。`  
   期望：先日历、后文件（两类工具都出现），输出 meeting brief（时间地点、项目摘要、讨论点等）。

页面回复下方会显示本轮「工具调用」序列，便于对照验收。

## 仓库结构

```
├── README.md
├── requirements.txt
├── .env.example
├── docs/
│   ├── baseline-v1.md              # 复现与验收
│   └── evaluation/                 # 报告对照证据
├── src/
│   ├── main.py          # FastAPI 入口
│   ├── agent.py         # Personal Assistant + 工具绑定
│   ├── config.py        # MOCK_TODAY、路径、API Key
│   └── tools/
│       ├── calendar.py
│       └── files.py
├── data/
│   ├── calendar.json
│   └── notes/
│       ├── fyp-proposal.md
│       └── meeting-notes.md
├── static/
│   └── index.html
└── scripts/
    └── demo_cli.py
```

## Out of scope（Baseline）

为避免过度设计，**本阶段明确不做**（与 preliminary outline 一致）：

- Mobile App
- Long-term memory（含 Zep / Letta）
- Database
- Multi-agent
- Browser / Computer Use / Cloud sandbox
- Voice
- Gmail / Drive（日历可选 Google 只读，见 docs/google-calendar-setup.md）
- Proactive notifications
- 复杂权限系统
- Production-level UI / 网页搜索
- MCP 作为运行时依赖（可调研，Baseline 不接入）

## 许可与署名

学术项目代码。Git 提交作者应为学生身份（`MOLIYUANQUAN`）。
