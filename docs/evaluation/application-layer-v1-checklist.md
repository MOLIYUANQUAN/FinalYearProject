# Application Layer v1 — 验收清单

记录时间（UTC）：2026-10-16T16:53:26.791449+00:00  
Tag：`application-layer-v1`  
Git：见同次 commit（`develop`）  
配置：`CALENDAR_BACKEND=google`，`MAIL_BACKEND=gmail`

## 任务结果

| ID | Pass? | 工具 | 备注 |
|----|-------|------|------|
| T4 | Pass | `get_personal_context → search_memory → get_calendar_events → search_emails` | get_personal_context required |
| T5a | Pass | `request_user_confirmation` | confirm gate; no false completion |
| T5b | Skip | `—` | skipped on google |
| T6a | Pass | `remember_fact` | remember_fact |
| T6b | Pass | `get_personal_context → search_memory` | fresh-session recall |
| T6c | Pass | `get_personal_context → search_memory` | Chinese mentor recall |
| T-mail | Pass | `search_emails` | readonly search |

汇总：6/6（Skip 不计分）

机器证据：`application-layer-v1-runs.json`

## 覆盖

- T4 个人上下文
- T5 确认边界（google 下仅 T5a，避免写入真实日历）
- T6 记忆写入/跨会话回忆 + 中文导师查询
- T-mail 只读搜索（若邮件后端已启用）
