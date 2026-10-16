# Application Personal Layer v1（薄层）

在日历切片之上增加最小 Personal Agent 能力：**个人上下文** + **确认边界**。  
日常开发在 `develop`；打 tag / 合 `main` 需人工确认后再做。

## 增加了什么

| 能力 | 实现 | 说明 |
|------|------|------|
| Personal Context | `data/personal/profile.md` + `get_personal_context` | 本地文件，不是 memory DB |
| Approval | `request_user_confirmation` + `src/approval.py` | 写操作前必须确认 |
| Calendar write | `create_calendar_event`（确认后） | 见 [application-calendar-write-v1.md](application-calendar-write-v1.md) |

## 工具列表

- `get_calendar_events`
- `search_files` / `read_file`
- `get_personal_context`
- `request_user_confirmation`

## 验收示例

1. 「按我的习惯帮我准备明天的会」→ 应调用 `get_personal_context`，再日历/文件  
2. 「帮我明天上午创建一个叫 Test 的日历事件」→ 应调用 `request_user_confirmation`，**不**声称已创建  

## 仍不做

Zep/Letta、完整权限系统、真正写日历/发邮件、多 agent。
