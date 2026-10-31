# Friday

Manchester CS Final Year Project (Zeep): **a single personal agent** that knows you, keeps track of the loose ends in your life, and answers with an opinion.

> **Plan and progress (read this first):** [docs/plan.md](docs/plan.md) · **Engineering log:** [docs/engineering-log.md](docs/engineering-log.md)  
> Success means passing the Tuesday test (would you open it on an ordinary Tuesday?), not a demo score. Expanding the evaluation, merging into `main` and new milestone tags are frozen until the "loved and used" gate is passed.

**Academic route:** Baseline → Application → Evaluation (evidence in [docs/evaluation/](docs/evaluation/), currently frozen)  
**Baseline snapshot:** tag [`baseline-v1`](https://github.com/MOLIYUANQUAN/FinalYearProject/releases/tag/baseline-v1) · [docs/baseline-v1.md](docs/baseline-v1.md)  
**Setup guides:** [Google Calendar](docs/google-calendar-setup.md) · [Gmail](docs/gmail-setup.md) · Google Tasks (`scripts\auth_google_tasks.py`, then set `TASKS_BACKEND=google` in `.env`) · [Cloud + iPhone](docs/cloud-and-iphone.md) · [Tunnel (interim)](docs/phone-access.md) · [Personal](docs/application-personal-v1.md) · [Memory](docs/application-memory-v1.md)

## Success criteria (Baseline)

| # | Criterion | Check |
|---|-----------|-------|
| S1 | A single Personal Assistant agent | Only one agent throughout |
| S2 | Simple input interface | Type in the browser and see the reply |
| S3 | Tools can be called | Calendar and file tools are registered and run |
| S4 | Single tool: tomorrow afternoon | Uses only the calendar and answers correctly |
| S5 | Files: find and summarise the FYP proposal | Based on `data/notes/fyp-proposal.md` |
| S6 | Multi-tool chain: prepare tomorrow's FYP meeting | Calendar → files → meeting brief |
| S7 | Mock/local data | JSON/Markdown under `data/`, no cloud OAuth |

## Tech stack

- Python 3.11+
- [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) (`openai-agents`), including sessions and tool approvals
- The brain: Claude (`claude-opus-5-5`, through the official `anthropic` SDK) when `ANTHROPIC_API_KEY` is set, otherwise GPT-5. Voice transcription and read-aloud stay on OpenAI
- FastAPI + a single static HTML page
- Fly.io for the always-on cloud Friday, with a mounted volume for her state
- Demo data: `data/calendar.json`, `data/notes/*.md`, `data/mail/messages.json`, `data/tasks.json`

## One brain

Friday lives in the cloud (`friday-jimmy.fly.dev`). The phone and the desktop window open the same Friday, with the same memory and the same conversation.

- Everything that changes — memory, conversations, friction list, mistakes, usage log, pending Cursor work — lives in `FRIDAY_STATE_DIR`. On Fly that is a volume mounted at `/state`, so deploys and restarts no longer wipe her memory. Locally it defaults to `data/`.
- There is one conversation, stored on the server, shown as chat bubbles with the time marked when there's a gap. Start on the phone, continue on the desktop; there is no "new chat". Behind it, the model's session restarts after two idle hours or a new day so its context stays short, and each new session starts with the last few lines of the previous one. When you come back after a while she speaks first: a greeting, the one thing that matters now, and today's timeline.
- With `FRIDAY_URL=https://friday-jimmy.fly.dev` in `.env`, Ctrl+Alt+F opens the cloud Friday and no local server is started. Without it, the local server is used (for development).

Switching her to Claude is one command; Fly restarts her with the key and `/api/health` then reports `"model": "claude-opus-5-5"`:

```powershell
flyctl secrets set ANTHROPIC_API_KEY=sk-ant-... -a friday-jimmy
```

Whenever Claude can't answer (no API credit left, a key that doesn't work, rate limits, an Anthropic outage), GPT-5 answers that message instead and she tries Claude again five minutes later; `/api/health` then shows `"model": "gpt-5"` and the reason in `claude_issue`. `FRIDAY_MODEL` names a different model if you ever want one.

Switching to the cloud brain for the first time:

```powershell
.\.venv\Scripts\python.exe scripts\deploy_fly.py              # creates the friday_state volume if missing
# add FRIDAY_URL=https://friday-jimmy.fly.dev to .env
.\.venv\Scripts\python.exe scripts\sync_to_cloud.py --backup  # merge local memory and friction into the cloud (safe to repeat)
.\.venv\Scripts\python.exe scripts\open_agent.py --stop       # stop the local server, then press Ctrl+Alt+F
```

## Tools

| Tool | What it does | Needs your confirmation |
|------|--------------|-------------------------|
| `get_calendar_events` | Read the calendar (including the imported university timetable) | |
| `create_calendar_event` | Add an event to his own calendar | no — done directly with "Undo" |
| `search_emails` / `read_email` | Search and read Gmail | |
| `send_email` | Send an email (subject/body editable in the card) | yes |
| `modify_email` | Mark read/unread (direct) or archive/trash (confirmed) | archive / trash |
| `search_files` / `read_file` | Local notes | |
| `get_personal_context` | Static profile | |
| `remember_fact` / `search_memory` | Long-term memory | |
| `forget_fact` | Delete a memory | yes |
| `add_task` / `complete_task` | Google Tasks; done directly with an "Undo" button | |
| `note_friction` / `list_friction` / `resolve_friction` | Things you dislike about Friday | |
| `fix_friction_with_cursor` | Ask a Cursor agent to change Friday's code | yes |
| `check_cursor_fix` / `preview_pending_ship` | Progress and diff of the Cursor change | |
| `ship_pending_fix` | Merge into `develop` and deploy | yes |

## The workbench

Opening Friday shows today's work, not a blank chat:

- **现在 (now)** is one sentence in large type with one action: the single thing that matters most right now. The order is: an important meeting within three hours ("帮我准备"), then a to-do past its due date, then an engineering decision (a ready change to ship, a red `develop`), then what is due today. If none of these apply, the line is her judgement of the calendar.
- **Below it is a quiet timeline** for today and tomorrow: classes, meetings, reminders and deadlines in time order. There are no section headers such as "需要你" or "待办".
- **Every row can be tapped.** Important meetings offer "帮我准备" (Friday prepares the brief). To-dos offer "做完了" and "明天再说"; these run directly, come with "Undo", and are recorded in the conversation.

## Friday comes to find you

Web Push reaches the iPhone home-screen app and the desktop Friday window. When and what to say is computed on the server from the calendar and to-dos, without the model:

| When | What |
|------|------|
| The exact minute he asked for ("下午三点提醒我给妈妈打电话", "20 分钟后叫我") | The reminder, in her words. The time is parsed on the server from his own words; it ignores the daily limit and quiet hours, and can be undone |
| Weekdays after 08:30, weekends after 10:00, before noon | Morning brief: today's items and what is due (skipped on an empty day) |
| 20 min – 2 h before an important meeting | "下午 2 点：FYP meeting… 点开，我把要点备好" — tapping it opens Friday and prepares the brief |
| After 17:00 | What is due today and still not done |
| 21:00 | Wrap-up: what she closed for you today, what is still open, tomorrow's first thing and tomorrow's deadlines. On Sunday it adds "这周替你关掉了 N 件". Nothing is moved to tomorrow behind your back: a deadline that has passed is reported as passed |

- At most three a day (`FRIDAY_PUSH_DAILY_MAX`), never between 22:00 and 08:00, and each thing only once. Reminders he asked for are outside these rules.
- The scheduler runs only on Fly (`FLY_APP_NAME` + Google calendar), so the desktop and the cloud never both send. Override it with `FRIDAY_NUDGES=on/off`.
- Encryption (RFC 8291) and VAPID (RFC 8292) are implemented with `cryptography`; the keys live in `FRIDAY_STATE_DIR/push/`.

Turning it on:

- **iPhone:** in Safari, Share → Add to Home Screen. Open Friday from the home screen, log in once, then tap "打开提醒" under the opening card.
- **Desktop:** tap "打开提醒" in the Friday window. Notifications arrive while the window's browser is running (after the first Ctrl+Alt+F since boot).

Opening a notification is counted in the usage log, so `usage_report.py` shows whether nudges are worth it.

## Engineering line (kept out of the daily screen)

Cursor fixes and CI belong to the workshop, not the living room, so they never appear on the opening card. Friday only pushes:

- "Cursor 改好了": tapping it opens Friday asking "Cursor 改了什么". She shows the change, and shipping goes through the usual confirmation card, which lists the changed files.
- "上线了": sent once the new commit is actually serving.
- "develop 测试红了": tapping it asks why and offers to hand the fix to Cursor.

Shipping still goes through the test gate: a change whose tests fail is not merged.

## Talking to Friday

Like WeChat: tap "说" and the input bar becomes "按住 说话".

- Hold to record, release to send, slide up to cancel. A press that is too short says so.
- The mic opens once and stays open while Friday is in front, so every press records instantly. The iPhone does not keep asking for permission; the mic closes when Friday goes to the background.
- Your bubble appears the moment you let go and turns into text once transcribed.
- She answers in text, as if you had typed. She reads aloud only when you ask ("念给我听", "听听你的声音").
- You can talk while she is speaking: she stops and listens.
- "打字" switches back. The last mode is remembered.

There is deliberately no Siri Shortcut or share-sheet setup. Friday is one tap from the home screen and listens as soon as you hold the mic. A second assistant in front of her, plus a hand-built Shortcut, would only add steps.

## Automatic test and deploy

Run this once:

```powershell
.\.venv\Scripts\python.exe scripts\connect_github_fly.py
```

It puts a Fly deploy token into GitHub Secrets (`FLY_API_TOKEN`) and a GitHub token onto Fly (`GITHUB_TOKEN`). It is fully automatic with the GitHub CLI; without it, you paste twice.

After that, every push to `develop`:

1. runs the offline tests;
2. deploys to Fly;
3. waits until `/api/health` reports exactly that commit (`git_sha`).

**Confirmation is enforced in code, not in the prompt.** Outward or destructive tools are registered with the Agents SDK's `needs_approval`, so the run pauses before they execute. The server writes out exactly what will happen (recipient, subject, body, time, changed files), and only an explicit yes ("确认", "好的", "发吧", the Confirm button…) resumes that exact action. "取消" or anything else cancels it. The paused step is saved to disk, so a restart in between does not lose it. For mail, "改一下" lets him edit the subject and body in the card. Friday must re-issue the call with exactly the edited text before it is sent; if anything differs, he is asked again.

When she gets something wrong, just say "不对". She corrects it and records the mistake (`note_mistake` → `mistakes.jsonl`), and `usage_report.py` counts mistakes per day. The target is zero. There is no button for it.

## How "tomorrow" is resolved

With `CALENDAR_BACKEND=mock`, the demo uses a **fixed "today"** so it does not depend on your machine's date:

| Concept | Value |
|---------|-------|
| Mock today `MOCK_TODAY` | `2026-10-12` (Monday, 09:00) |
| "Tomorrow" | `2026-10-13` |

- Every turn, the server writes the current time, today-to-next-Sunday's calendar (split into this week / next week, with dates, weekdays and counts), open to-dos, the profile and memories into the agent's instructions. The model does not work out dates or counts itself.
- `get_calendar_events` takes `date` as `YYYY-MM-DD` (e.g. tomorrow → `2026-10-13`).
- The mock calendar has the **FYP meeting** at `2026-10-13T14:00–15:00` (Kilburn Building), so "tomorrow afternoon" finds it.
- With `CALENDAR_BACKEND=google`, the real local date is used. Calendar times are always converted to London time; on Fly, `TZ=Europe/London` is set in `fly.toml`.

To change the demo date, edit `MOCK_TODAY` / `MOCK_TOMORROW` in `src/config.py` and update the event dates in `data/calendar.json`.

## Running it

### 1. Environment

```bash
cd FinalYearProject
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. API key

```bash
cp .env.example .env
# edit .env and set:
# OPENAI_API_KEY=sk-...
```

If `OPENAI_API_KEY` is missing:

- the terminal prints a clear warning on startup;
- the page says the key is missing;
- `/api/chat` returns **503** with an explanation.

### 3. Open

Run this once; Friday then appears on the desktop and in the Start menu, and is ready in the background after boot:

```powershell
.\.venv\Scripts\python.exe scripts\install_shortcuts.py
```

After that, press **Ctrl+Alt+F**. Friday appears in her own window and opens with the one thing you most need to know right now; press it again while she is in front to hide her. You can also click Friday on the desktop or double-click `Friday.cmd` in the repo. The window uses its own browser profile (`data/browser/`, not in Git) without your main browser's extensions.

```powershell
.\.venv\Scripts\python.exe scripts\install_shortcuts.py --remove  # remove shortcuts and the startup entry
.\.venv\Scripts\python.exe scripts\open_agent.py --restart        # force-restart the local server
.\.venv\Scripts\python.exe scripts\open_agent.py --stop           # stop the local server and the hotkey
.\.venv\Scripts\python.exe scripts\usage_report.py                # Tuesday test: days used, first-token time, mistakes (cloud log when FRIDAY_URL is set)
```

### 4. Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

The tests use a scripted fake model, so they run offline, cost nothing and need no keys. They cover:

- the seven kinds of mistakes from real use, one guard each;
- the confirmation boundary (no write tool can run without approval);
- server-side conversations (follow-ups, switching devices, expiry);
- the HTTP API;
- the ship gate.

GitHub runs them on every push and pull request (`.github/workflows/tests.yml`). Shipping a Cursor change refuses to merge if they fail, and the deploy workflow tests before deploying.

### 5. Optional CLI demos

```bash
python scripts/demo_cli.py
# also save Evaluation evidence JSON:
python scripts/demo_cli.py --save
```

### 6. Reproducing the Baseline from the tag (for the report)

```bash
git fetch --tags
git checkout baseline-v1
```

Then follow Environment → API key → Open above. Details in [docs/baseline-v1.md](docs/baseline-v1.md).

## Branches

| Ref | Purpose |
|-----|---------|
| `develop` | Day-to-day development (pushing it runs tests, then deploys to Fly) |
| `main` | Major milestones |
| tag `baseline-v1` | Reproducing the Baseline for the report |

## Demo script (acceptance)

1. **Tomorrow afternoon**  
   Input: `我明天下午有什么安排？`  
   Expected: answered from the calendar; mentions the FYP meeting (14:00, Kilburn Building).

2. **FYP proposal**  
   Input: `找到我的 FYP proposal，告诉我项目在做什么。`  
   Expected: `search_files` → `read_file`; summarises the personal AI assistant / Baseline goals from the file.

3. **Prepare tomorrow's FYP meeting (hard acceptance)**  
   Input: `帮我准备明天的 FYP meeting。`  
   Expected: calendar first, then files; outputs a meeting brief (time and place, project summary, discussion points).


## Repository layout

```
├── README.md
├── requirements.txt
├── .env.example
├── fly.toml / Dockerfile          # cloud Friday (volume at /state, TZ=Europe/London)
├── docs/
│   ├── plan.md                    # direction and standards
│   ├── engineering-log.md         # how things were built and why
│   ├── baseline-v1.md             # reproduction and acceptance
│   └── evaluation/                # evidence for the report (frozen)
├── src/
│   ├── main.py                    # FastAPI: page, streaming chat, opener, undo
│   ├── agent.py                   # Friday: voice, instructions, one turn with sessions and approvals
│   ├── conversation.py            # server-side conversations (SQLite)
│   ├── approval.py                # what needs confirmation, and how it is shown
│   ├── presence.py / agenda.py    # opener card and the one line, computed without the model
│   ├── todos.py                   # to-dos
│   ├── memory_store.py            # long-term memory
│   ├── friction.py / mistakes.py  # what you dislike / what she got wrong
│   ├── reminders.py / closed.py   # on-time reminders / what she closed for you
│   ├── cursor_fix.py / ship.py    # Cursor fixes, preview, test gate, merge and deploy
│   ├── state_sync.py              # import/export state, cloud usage log
│   ├── config.py                  # paths, FRIDAY_STATE_DIR, demo date, backends
│   └── tools/                     # tools the agent can call
├── static/index.html
├── scripts/                       # open_agent, deploy_fly, sync_to_cloud, usage_report, demos…
├── tests/                         # offline tests (fake model)
└── data/                          # demo data and the profile (state lives in FRIDAY_STATE_DIR)
```

## Out of scope

To avoid over-engineering, these are deliberately not built:

- App Store app / native iPhone shell (Safari "Add to Home Screen" instead)
- Multi-agent, "AI employees"
- Memory admin UI, dashboards for their own sake
- Browser / computer use
- Dozens of notifications a day or fake "proactive" noise
- General news reader, unattended trading or posting

## License and attribution

Academic project code. Git commits are authored under the student's identity (`MOLIYUANQUAN`).
