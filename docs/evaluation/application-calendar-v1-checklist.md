# Application Calendar v1 — 验收清单

记录日期：2026-10-16  
Git 引用：`application-calendar-v1`  
配置：`CALENDAR_BACKEND=google`，`GOOGLE_CALENDAR_ID=selected`

## 验收

| 项 | Pass? | 备注 |
|----|-------|------|
| 能查询 Google 日历 | Pass | OAuth readonly |
| 导入课表日历可见 | Pass | `Mr Zepeng Jia` 等 selected 日历 |
| Demo：明天安排 | 见 runs JSON | 含真实事件 |
| Demo：FYP proposal | 见 runs JSON | 仍用本地文件 |
| Demo：会议 brief 多工具 | 见 runs JSON | 日历 + 文件 |
| mock fallback 仍可用 | Pass | `CALENDAR_BACKEND=mock` |

机器证据：`application-calendar-v1-runs.json`
