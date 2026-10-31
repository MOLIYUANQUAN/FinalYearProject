# 架构图（导师会议用）

| 文件 | 内容 | 用途 |
|------|------|------|
| `architecture.png` | 图 1：系统整体架构（Baseline v1） | 插入 Google Doc |
| `request-flow.png` | 图 2：Demo 3「准备明天 FYP meeting」的请求时序 | 插入 Google Doc |
| `architecture.svg` / `request-flow.svg` | 上面两张图的源文件 | 以后修改用 |

图中文字用英文，方便导师直接阅读；内容与当前代码（`src/`、`data/`、`static/`）一一对应。

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
