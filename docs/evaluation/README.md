# Evaluation 证据目录

本目录存放各阶段可复现的运行证据，供报告对比使用。

| 文件 | 阶段 | 说明 |
|------|------|------|
| [baseline-v1-runs.json](baseline-v1-runs.json) | Baseline | mock 日历 Demo 1–3 |
| [baseline-v1-checklist.md](baseline-v1-checklist.md) | Baseline | 人工验收清单 |
| [application-calendar-v1-runs.json](application-calendar-v1-runs.json) | Application | Google 日历 Demo 轨迹 |
| [application-calendar-v1-checklist.md](application-calendar-v1-checklist.md) | Application | Google 日历验收 |
| [application-layer-v1-runs.json](application-layer-v1-runs.json) | Application | T4–T6（+邮件）轨迹 |
| [application-layer-v1-checklist.md](application-layer-v1-checklist.md) | Application | Personal / 确认 / 记忆验收 |
| [task-set-and-rubric.md](task-set-and-rubric.md) | Evaluation | 固定任务集与评分维度 |

```bash
# Baseline（建议 CALENDAR_BACKEND=mock）
python scripts/demo_cli.py --save --tag baseline-v1

# Application Calendar（需 CALENDAR_BACKEND=google 且已授权）
python scripts/demo_cli.py --save --tag application-calendar-v1

# Application Layer：T4 个人上下文 / T5 确认 / T6 记忆
python scripts/eval_application_cli.py --save --tag application-layer-v1
```
