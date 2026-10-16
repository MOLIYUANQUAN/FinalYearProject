# Application：确认后创建日历事件

在 Personal Approval 薄层之上，打通真实写路径：

1. Agent 调用 `request_user_confirmation`
2. 用户在同一对话中回复「确认」
3. Agent 调用 `create_calendar_event(..., user_confirmed=True)`
4. Google：写入 **primary** 日历；mock：写入 `data/calendar.json`

## 多轮对话

Web UI / API 现在会携带 `history`，确认闭环才能成立。

## 重新授权（必须）

权限从 `calendar.readonly` 升级为 `calendar`。若仍是旧 token，运行：

```bash
python scripts/auth_google_calendar.py
```

浏览器中同意「查看和编辑日历事件」类权限。

## 网页自测

1. 「帮我在明天 16:00-16:30 创建一个叫 Agent Write Test 的日程」
2. 看到确认请求后回复：`确认`
3. 打开 Google 日历主日历，应出现该事件
