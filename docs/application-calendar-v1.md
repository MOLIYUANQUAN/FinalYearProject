# Application Calendar v1

对应 Git tag：`application-calendar-v1`。

在 Baseline 之上完成 **Google Calendar 只读**，并保留 mock 可复现演示。

## 相对 Baseline 的增量

| 项 | Baseline (`baseline-v1`) | Application Calendar |
|----|--------------------------|----------------------|
| 日历数据 | `data/calendar.json` | Google Calendar API（只读） |
| 多日历 | 无 | `GOOGLE_CALENDAR_ID=selected` 读取网页勾选日历（含导入课表） |
| 「今天/明天」 | 固定 `2026-10-12/13` | 系统本地日期 |
| 文件工具 | 本地 notes | 不变 |

## 切换方式

```env
CALENDAR_BACKEND=google
GOOGLE_CALENDAR_ID=selected
```

Setup：见 [google-calendar-setup.md](google-calendar-setup.md)。

切回可复现 Demo：

```env
CALENDAR_BACKEND=mock
```

## 证据

```bash
# 需已授权 Google，且 .env 为 google
python scripts/demo_cli.py --save --tag application-calendar-v1
```

产物：[evaluation/application-calendar-v1-runs.json](evaluation/application-calendar-v1-runs.json)

## Out of scope（本切片仍不做）

Gmail、写日历、长期 memory、Approval 层、MCP 运行时依赖。
