# 架构图（导师会议用）

| 文件 | 内容 | 用途 |
|------|------|------|
| `architecture.png` | 图 1：系统整体架构（Baseline v1） | 插入 Google Doc |
| `request-flow.png` | 图 2：Demo 3「准备明天 FYP meeting」的请求时序 | 插入 Google Doc |
| `architecture.svg` / `request-flow.svg` | 上面两张图的源文件 | 以后修改用 |

图中文字用英文，方便导师直接阅读；内容与当前代码（`src/`、`data/`、`static/`）一一对应。

## 架构图说明（通俗版，可直接复制到 Google Doc）

### 一句话概括

用户在网页上提问 → 后台把问题交给 AI 助手 → 助手让大模型决定"要查什么" → 程序去查本地的日历和笔记 → 大模型根据查到的内容写出回答 → 回答显示在网页上。

### 打个比方

把整个系统想成一位秘书：

- **网页**：你和秘书说话的窗口
- **FastAPI 服务器**：传话的人，把你的话交给秘书，再把回答带回来
- **Agent（助手）**：秘书本人，负责安排做事的步骤
- **OpenAI 大模型**：秘书的大脑，负责理解问题、决定下一步做什么、最后组织语言
- **三个工具**：秘书会做的三件事：查日历、搜笔记、读笔记
- **data 文件夹**：秘书的文件柜，现在放的是演示用的假数据

### 图 1：整体架构（从上往下看）

1. **蓝色 CLIENT（入口）**：用户使用系统的地方，有两个。一是网页聊天页面，可以打字，也可以点 3 个演示按钮。二是命令行脚本，一次跑完 3 个演示，测试用。它不经过网页，直接找助手，所以图上有一根长箭头从它直通到下面的 Agent。
2. **绿色 WEB SERVER（后台）**：用 FastAPI 写的小网站后台，只做三件事：打开聊天页面、检查 OpenAI key 有没有配置、接收聊天消息并返回回答。
3. **紫色 AGENT（核心）**：程序先给助手写好"工作说明"（要遵守的规则，以及"今天是 2026-10-12"），再把三个工具交给它。然后开始一个循环：问大模型 → 大模型说"我要用某个工具" → 程序执行这个工具 → 把结果告诉大模型 → 再问大模型……直到大模型说"信息够了，可以回答了"。最多循环 8 轮，防止停不下来。最后程序记下用过哪些工具，显示在网页上。
4. **右边虚线框 OpenAI API**：系统里唯一需要联网的部分。大模型（gpt-4.1-mini）运行在 OpenAI 的服务器上，调用时要用 API key（相当于账号密码）。
5. **黄色 TOOLS（工具）**：三个普通的 Python 函数：
   - 查某一天的日程，可以只看上午、下午或晚上
   - 按关键词搜索笔记
   - 读出一篇笔记的全文（只能读 data/notes 文件夹里的文件，读不到电脑上的其他文件）
6. **灰色 LOCAL DATA（数据）**：演示用的假数据：一个日历文件（4 个日程，其中有 10 月 13 日 14:00 的 FYP meeting）和两篇笔记（项目 proposal、会议笔记）。程序只读不改。现在没有数据库，也没有连接真实的日历。
7. **右上 CONFIGURATION（设置）**：API key、用哪个模型、固定的"今天"日期。固定日期是为了让演示时"明天"永远是 10 月 13 日，每次运行结果都一样，方便检查（可复现）。
8. **右下 ROADMAP & SCOPE（计划和范围）**：项目分三个阶段：Baseline（现在）→ Application（接入真实工具，比如真的日历、邮件）→ Evaluation（评测系统效果）。下面列的是现阶段故意不做的东西（长期记忆、数据库、多个 agent 等）。最后一行是想和导师讨论的问题：Application 阶段先接哪个真实工具？

### 图 2：一次请求的完整过程（Demo 3）

用户输入"帮我准备明天的 FYP meeting"后：

1. 网页把这句话发给后台，后台交给助手。
2. **第 1 轮**：大模型看了问题，决定先查明天的日历。程序查日历文件，查到明天 14:00–15:00 在 Kilburn Building 有 FYP meeting。
3. **第 2 轮**：大模型决定找项目 proposal。程序在笔记里搜索，找到 fyp-proposal.md。
4. **第 3 轮**：大模型决定打开这个文件。程序读出全文。
5. **第 4 轮**：大模型觉得信息够了，写出会议准备摘要（时间地点、项目概要、建议讨论点）。
6. 回答和"用过的工具列表"一起返回网页显示。

**重点**：代码里没有规定先用哪个工具、后用哪个，是大模型根据问题和工作说明自己决定的（工作说明里建议了"先查日历，再看文件"）。这就是 Agent 和普通聊天机器人的区别：普通聊天机器人只会直接回答，Agent 会自己决定去查资料、用工具，再回答。

图里的箭头：实线表示"发出请求"，虚线表示"返回结果"。

## 放进 Google Doc

1. 在 Google Doc 中：**插入 → 图片 → 从计算机上传**，选择 `architecture.png`（以及 `request-flow.png`）。Google Docs 不支持 SVG，请用 PNG。
2. 图片宽度拉满页面。PNG 是 2 倍分辨率，放大查看也清楚。
3. 如果想让图更大：选中图片所在段落，**文件 → 页面设置 → 应用于：所选内容 → 横向**，只把这一页改成横向。
4. 下面的英文图注和说明可以直接复制，贴在图片下方。

---

## Paste-ready captions (English)

**Figure 1 — System architecture of the Personal AI Assistant (Baseline v1).**
A single agent built on the OpenAI Agents SDK, exposed through a FastAPI web server and a minimal browser chat page. The agent loop (Runner) calls the OpenAI model; when the model asks for a tool, the Runner executes one of three local tools, which read mock data from `data/`. The OpenAI API is the only cloud dependency.

| Layer | Component | Code | Responsibility |
|-------|-----------|------|----------------|
| Client | Web chat UI | `static/index.html` | Chat page with three demo buttons; shows the reply and the tool-call trace |
| Client | CLI demo runner | `scripts/demo_cli.py` | Runs the three acceptance demos in order, calling the agent directly |
| Web server | FastAPI app | `src/main.py` | `GET /`, `GET /api/health`, `POST /api/chat`; returns 503 if the API key is missing |
| Agent | Personal Assistant agent | `src/agent.py` | Builds the instructions (fixed date 2026-10-12), creates the agent with 3 tools, runs `Runner.run(max_turns=8)`, extracts the tool trace |
| Agent | OpenAI Agents SDK Runner | `openai-agents` | Agent loop: model call → tool call → result → … → final answer |
| External | OpenAI API | — | LLM (default `gpt-4.1-mini`, configurable via `OPENAI_MODEL`) |
| Tools | `get_calendar_events` | `src/tools/calendar.py` | Events for a given day, optionally filtered by morning / afternoon / evening |
| Tools | `search_files`, `read_file` | `src/tools/files.py` | Keyword search over notes; read a note in full (sandboxed to `data/notes/`) |
| Data | Calendar + notes | `data/calendar.json`, `data/notes/*.md` | Local, read-only mock data; no database, no OAuth |
| Config | Settings | `src/config.py`, `.env` | API key, model name, fixed mock date, file paths |

**Figure 2 — Request flow for Demo 3 (“Prepare tomorrow’s FYP meeting”).**
The model chains three tools over four turns: it checks the calendar for 2026-10-13, searches the notes for the FYP proposal, reads it, and then writes a meeting brief. The API returns the brief together with the ordered tool trace, which the UI shows under the reply. The tool calls are chosen by the model at runtime; the figure shows the expected path from the demo script.

**Suggested points for discussion**

- Reproducibility of the Baseline demo: the date is fixed (today = 2026-10-12) and the temperature is 0.2, but the model's tool choices can still vary between runs.
- Application phase: which real tool to connect first (e.g. calendar or email). In this architecture it would replace a local data source and add OAuth.
- Evaluation phase: what to measure (e.g. correct tool sequence, answer quality, number of turns).

---

## 更新架构图

代码结构变了（例如进入 Application 阶段、接入真实日历）时：

1. 修改对应的 `.svg`。SVG 是纯文本，可以直接用编辑器改文字和坐标，也可以用 Inkscape、Figma 打开。
2. 重新导出 PNG（宽度 2400 px），例如用 Inkscape：

```bash
inkscape architecture.svg --export-filename=architecture.png --export-width=2400
```

3. 在 Google Doc 中右键旧图片 → **替换图片 → 上传**。

图中字体为 Inter 与 JetBrains Mono；电脑上没有这两个字体时会自动换成系统字体，排版基本不变。
