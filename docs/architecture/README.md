# 架构图（导师会议用）

| 文件 | 内容 | 用途 |
|------|------|------|
| `architecture.png` | 图 1：系统整体架构 | 插入 Google Doc |
| `request-flow.png` | 图 2：一轮带确认的对话：回一封邮件 | 插入 Google Doc |
| `proactive-flow.png` | 图 3：不经过模型的主动路径：开场、推送、收工 | 插入 Google Doc |
| `*.svg` | 上面三张图的源文件 | 以后修改用 |

图中文字用英文，方便导师直接阅读。内容与 `develop` 上的代码（版本 0.9.0，2026-10-31）一一对应：`src/`、`static/`、`.github/workflows/`、`fly.toml`。

Baseline v1 时期的旧架构图在分支 `claude/pensive-brown-40tnzr`，画的是 10 月 12 日的 3 个工具版本，已被这一版取代。

## 架构图说明（通俗版，可直接复制到 Google Doc）

### 一句话概括

Friday 有两条路。**他开口时**，Agent 把这句话交给大模型，由模型决定查什么、做什么，对外的事先停下来问他。**他没开口时**，服务端按规则从日历、待办和提醒算出该说什么、什么时候说，全程不问模型。两条路写进同一段对话、同一块云上磁盘。

### 打个比方

把 Friday 想成一位只为 Zeep 工作的管家：

- **桌面窗口 / iPhone 主屏幕 / 网页**：和管家说话的地方，三处是同一个 Friday
- **FastAPI 服务器（在 Fly.io 云上常开）**：管家的办公室
- **Agent**：管家本人，听他说话、安排做事的步骤
- **大模型（Claude，备用 GPT-5）**：管家的脑子，负责理解和组织语言
- **24 个工具**：管家能动手做的事。发邮件这类对外的事先问他；只关他自己的事（待办、自己的日程、提醒）直接做，给「撤销」
- **服务端计算**：管家的日程本和闹钟。几点、几件、该不该打扰他，按规则算，不靠脑子猜
- **数据源适配器**：接上他真实的 Google 日历、Gmail、163 邮箱、Google Tasks
- **/state 磁盘**：管家的记事本，部署、重启都不丢

### 图 1：整体架构（从上往下看）

1. **蓝色 CLIENT（入口）**：三个入口用的是同一个网页 `static/index.html`。
   - Windows 桌面窗口：按 Ctrl+Alt+F 叫出来或收起，按住右 Ctrl 直接说话。
   - iPhone 主屏幕 App：在 Safari 里「添加到主屏幕」，能收推送，不上 App Store。
   - 评测脚本：不经过网页，直接调用同一个 Agent。
2. **绿色 WEB SERVER（后台）**：FastAPI 写的后台，用 Docker 跑在 Fly.io 上（伦敦机房，常开）。每个请求先过「门卫」（密码换会话 Cookie），再分到各个接口：开场、对话、语音、推送、资料页、健康检查。`/api/health` 会报出线上跑的是哪一版代码、用的是哪个模型。
3. **左边橙色 SERVER-COMPUTED（服务端计算，不经过模型）**：这是 Friday 和普通聊天机器人最不一样的地方。
   - 打开时的「现在」：一句话加一个动作，下面一条时间线。
   - 准时提醒：「三点提醒我…」到点推送。
   - 每分钟检查一次要不要推送：早上开工、会快到了、今天截止、晚上 9 点收工。规则是一天最多 3 条、22:00–08:00 不打扰、同一件事只说一次。
   - 工程消息：Cursor 改好了、develop 测试红了，只走推送，不占开场画面。

   这些都由代码按规则算，所以快、不花钱、不会说错时间或数目。
4. **中间紫色 AGENT（核心）**：每一轮对话，程序先重新写一遍「工作说明」：人设、此刻时间、今天到下周日的日历、待办、提醒、档案、记忆、他嫌弃过的做法。然后进入循环：问模型 → 模型说要用某个工具 → 执行工具 → 把结果告诉模型 → …… 最多 12 次。
   - 对外或删除类的工具（发邮件、归档、忘掉记忆、让 Cursor 改代码、上线）会让这一轮**停下来**，停下的状态存到磁盘，等他明确说「发 / 确认」才继续。这一条写在代码里，模型绕不过去。
   - 下面的「模型适配器」把 Agents SDK 的请求翻译成 Anthropic 的格式。Claude 用不了（没额度、限流、故障）时，这一句交给 GPT-5 答，接下来 5 分钟都先用 GPT-5。
5. **黄色 TOOLS（24 个工具）**：按类分组：日历、邮件、待办、提醒、记忆、笔记、产品反馈与工程。红色 `approval` 表示要他点头才执行；绿色 `undo` 表示直接执行、页面给「撤销」；没标的是只读。
6. **蓝绿色 DATA-SOURCE ADAPTERS（数据源适配器）**：同一套工具可以接演示数据，也可以接真实账户，在 `.env` 里选。几个邮箱一起看（Gmail + 163……），回信从那封信所在的邮箱发出。
7. **右边虚线 EXTERNAL SERVICES（外部服务）**：系统里需要联网的部分。
   - AI 模型：Claude、GPT-5、语音转写和朗读。
   - 工程工具：Cursor 云端 Agent、GitHub。
   - 他的账户：Google 日历、Tasks、Gmail，Outlook，163/QQ 邮箱。
8. **灰色 STATE（状态）**：所有会变的东西都在 `FRIDAY_STATE_DIR`。云上它是挂载的磁盘 `/state`，部署、重启都不丢。里面有：
   - 对话：SQLite，一份给模型看，一份给页面显示。
   - 等确认的那一步。
   - 记忆、提醒、关掉的事、推送设备、用量。
9. **右下 BUILD & DEPLOY（构建和部署）**：
   - 每次推送 `develop`，GitHub Actions 先跑 200 多个离线测试（用脚本化的假模型，不花钱、不需要 key）。
   - 测试通过才部署到 Fly.io，部署完核对线上版本号，对不上就算失败。
   - `main` 只放里程碑。
10. **左边的虚线箭头（Web Push）**：服务端主动把消息推到他的 iPhone 和电脑上，这就是「她来找他」。

### 图 2：一轮带确认的对话（回一封邮件）

他说：「回一下 John，说我明天下午两点能到。」

**第一轮：起草，停在发送之前**

1. 网页把这句话发给后台，后台交给 Agent。Agent 先把这句话存进对话，再写好这一轮的工作说明（日历和待办同时读，谁也不等谁）。
2. 模型先要搜邮件 → 工具在他接上的所有邮箱里搜 → 找到 John 的邮件（标明在哪个邮箱）。
3. 模型再要读这封信 → 工具读出整封信。
4. 模型要发邮件 `send_email(...)`。这个工具标了 `needs_approval`，所以**这一步不会执行**：这一轮在这里停下，停下的状态存到磁盘。
5. 页面上出现她的气泡和确认卡片：发给谁、从哪个邮箱发、主题、正文，最后问「发吗？」。卡片上的字由服务端照原样拼出来，不是模型写的，所以他看到的就是将要发出去的。主题和正文可以在卡片里直接改。

**第二轮：他说「发」**

6. 后台从磁盘读回停下的那一步，判断他的回答：
   - 只有「发 / 好 / 确认 / ok」这类明确的同意才算同意；
   - 「不发 / 取消 / 算了」就作罢；
   - 他说了别的事，就当他换了话题，邮件不发。
7. 同意后，恢复运行，邮件从原来那个邮箱发出去，同时在「关掉的事」里记一笔，晚上 9 点的收工推送会数到它。
8. 模型说一句「发了。」，存进对话，显示在页面上。

**重点**：先查什么、再查什么由模型自己决定，但「对外的事必须他点头」是代码里的硬规则，不靠模型自觉。

### 图 3：主动路径（不经过模型）

- **打开时**：服务端读最多 1 分钟前的日历、待办和提醒，挑出此刻最要紧的一件，顺序是：
  1. 3 小时内的要紧会议
  2. 过了截止的
  3. 今天截止的
  4. 都没有就说一句日历上的安排

  然后配一个动作和一条时间线，一起推到页面上，大约 0.7 秒。这句话也存进对话，他接着问时模型知道自己刚说过什么。
- **来找他**：定时器每分钟检查一次（只在云上跑，免得本机和云上各发一遍）。
  - 他亲口交代的提醒到点就发，不受名额和安静时段限制。
  - 其余的（早上开工、会快到了、今天截止、晚上收工、Cursor/CI 消息）按规则筛：一天最多 3 条、夜里不打扰、一件事只说一次。
  - 推送也写进对话，点开就在那一条上。
- **闭环**：划掉的待办、发出的邮件、上线的改动都记进 `closed.jsonl`。晚上 9 点的收工说今天关掉了几件，周日再说这周关掉了几件。这个数就是产品计划里的长期指标：替他关掉了多少件事。

## 和 Baseline v1 比，变了什么

| | Baseline v1（10 月 12 日，`main`） | 现在（`develop`） |
|---|---|---|
| 入口 | 本机网页 | 桌面窗口 + iPhone 主屏幕，云上同一个 Friday |
| 大脑 | gpt-4.1-mini | Claude Opus 5.5，备用 GPT-5 |
| 工具 | 3 个，只读演示数据 | 24 个，接真实日历、邮件、待办；对外的事硬确认，自己的事可撤销 |
| 对话 | 一问一答，不保存 | 存在服务端，换设备接着聊 |
| 主动 | 无 | 开场、准时提醒、每天最多 3 条推送、晚上收工 |
| 工程 | 手动运行 | 200 多个离线测试；推送 develop 自动测试、部署、核对线上版本 |

---

## Paste-ready captions (English)

**Figure 1: System architecture of Friday 0.9.0 (develop, 31 Oct 2026).**
Friday is a single personal agent served by a FastAPI app on Fly.io and used through one web page: a Windows desktop window, an iPhone home-screen app, or evaluation scripts. A message takes the *reactive path*: the agent (OpenAI Agents SDK) rebuilds its instructions from live data every turn and loops between the model and 24 tools. Outward or destructive tools pause the run until the user explicitly approves; the user's own to-dos, events and reminders run directly with an Undo. Without a message, the *server-computed path* derives the opener, reminders and push notifications from the calendar and to-dos by rule, with no model involved. Both paths share data-source adapters (Google, IMAP, mock) and one state directory on a persistent volume.

| Layer | Component | Code | Responsibility |
|-------|-----------|------|----------------|
| Client | Desktop window | `scripts/open_agent.py`, `src/desktop.py` | Resident launcher; Ctrl+Alt+F shows/hides the app window; hold Right Ctrl to talk |
| Client | iPhone home-screen app | `static/manifest.json`, `static/sw.js` | Same page added to the home screen; service worker shows Web Push |
| Client | Single-page UI | `static/index.html` | Chat bubbles, reactions, images, editable confirm cards, Undo, voice, profile page |
| Web server | FastAPI app | `src/main.py`, `src/access.py` | Session-cookie gate; opener, chat, voice, push, profile and health endpoints; SSE streaming |
| Agent | Friday | `src/agent.py` | Per-turn instructions, `Runner.run_streamed` (≤ 12 model calls), SQLite session, approval pause/resume, Undo, context roll-over |
| Agent | Model adapter | `src/claude.py` | Claude via the Anthropic Messages API with prompt caching; per-call fallback to GPT-5 |
| Tools | 24 function tools | `src/tools/` | Calendar, mail, to-dos, reminders, memory and profile, notes, product feedback and engineering |
| Server-computed | Opener, reminders, nudges | `src/presence.py`, `agenda.py`, `todos.py`, `reminders.py`, `nudges.py`, `push_api.py`, `webpush.py` | Rule-based opener and push notifications (≤ 3 a day, quiet hours), VAPID Web Push |
| Server-computed | Bookkeeping | `src/closed.py`, `ledger.py`, `usage_log.py`, `workbench.py`, `engineering.py` | Closed loops, exact token cost, usage metadata, tap actions, CI/Cursor status |
| Adapters | Data sources | `src/calendar_providers/`, `mail_providers/`, `tasks_providers/` | Google Calendar / Tasks / Gmail, Outlook (read-only), IMAP + SMTP, mock data |
| State | `FRIDAY_STATE_DIR` | Fly volume `/state` | Conversations (SQLite), paused approvals, memory, reminders, closed loops, push devices, usage |
| External | Models and services | — | Anthropic (Claude Opus 5.5), OpenAI (GPT-5, transcription, TTS), ElevenLabs, Cursor Cloud Agents, GitHub, Google, Microsoft Graph |
| Deploy | CI/CD | `.github/workflows/`, `fly.toml`, `Dockerfile` | 200+ offline tests on every push; on `develop`: test → `flyctl deploy` → verify the live `git_sha` |

**Figure 2: Request flow for an outward action (“Reply to John: I can make it tomorrow at 2”).**
In the first turn the model chains `search_emails` → `read_email` → `send_email`. Because `send_email` is declared with `needs_approval`, the SDK interrupts the run before the tool executes; the paused `RunState` is saved to disk and the server, not the model, renders the confirm card from the exact arguments. In the second turn an explicit yes resumes that exact call, the mail is sent from the mailbox it came to, and the closed loop is recorded. Any other reply cancels the action.

**Figure 3: The proactive path (no model).**
The opener and push notifications are computed by rule from the calendar, to-dos and reminders: the opener picks one focus (important meeting within 3 hours → overdue → due today), and a 60-second scheduler sends at most three pushes a day outside quiet hours, plus any reminder the user set. Both are written into the conversation so the agent knows what was said. Every loop Friday closes is logged and counted in the 21:00 wrap-up, the product's long-term measure.

**Suggested points for discussion**

- Evaluation: the existing task-set evidence is frozen until the “Tuesday test” (opened on an ordinary working day) passes. Candidate measures are loops closed per week, wrong statements (target 0) and unconfirmed outward actions (target 0).
- Rule-based vs model-based judgement of when to interrupt: rules are predictable and free, but miss nuance.
- The approval boundary: which actions should stay confirm-first, and which can run directly with an Undo.

---

## 放进 Google Doc

1. 在 Google Doc 中：**插入 → 图片 → 从计算机上传**，选 PNG。Google Docs 不支持 SVG。
2. 图片宽度拉满页面。PNG 是 2 倍分辨率，放大看也清楚。图 1 和图 2 比较长，建议各占一页。
3. 想让图更大：选中图片所在段落，**文件 → 页面设置 → 应用于：所选内容 → 横向**，只把这一页改成横向。
4. 上面的英文图注和组件表可以直接复制，贴在图片下方。

## 更新架构图

代码结构变了（新工具、新入口、新的外部服务）时：

1. 改对应的 `.svg`。SVG 是纯文本，可以直接改文字和坐标，也可以用 Inkscape、Figma 打开。
2. 重新导出 PNG（2 倍宽度），例如用 Inkscape：

```bash
inkscape architecture.svg --export-filename=architecture.png --export-width=3200
```

```bash
inkscape request-flow.svg --export-filename=request-flow.png --export-width=2800
```

```bash
inkscape proactive-flow.svg --export-filename=proactive-flow.png --export-width=2800
```

3. 在 Google Doc 中右键旧图片 → **替换图片 → 上传**。

图中字体为 Inter 与 JetBrains Mono，中文用系统自带的中文字体。电脑上没有这两个字体时会换成系统字体，文字宽度可能略有变化。PNG 是用这两个字体导出的，以 PNG 为准。
