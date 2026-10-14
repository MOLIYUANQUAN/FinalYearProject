# Baseline v1 — 人工验收清单

记录日期：2026-10-14  
运行环境：CLI（`python scripts/demo_cli.py --save`）  
Git 引用：`develop` @ Phase 0 证据采集（功能对齐 tag `baseline-v1`）

## 环境

- [x] `OPENAI_API_KEY` 已配置，健康检查通过  
- [x] `MOCK_TODAY=2026-10-12`，`MOCK_TOMORROW=2026-10-13`  

## Demo 验收

| Demo | Pass? | 实际工具序列 | 备注 |
|------|-------|--------------|------|
| 1 明天下午安排 | Pass | `get_calendar_events` | FYP meeting，14:00–15:00，Kilburn Building |
| 2 FYP proposal | Pass | `search_files` → `read_file` | 概括本地 proposal 内容 |
| 3 会议 brief | Pass | `get_calendar_events` → `search_files` → `read_file` | 多工具链 + brief |

## S1–S7（总览）

| # | 标准 | Pass? |
|---|------|-------|
| S1 | 单一 Agent | Pass |
| S2 | 简单输入界面可用 | Pass（Web UI 此前已验证） |
| S3 | 三个工具可被调用 | Pass |
| S4 | Demo 1 | Pass |
| S5 | Demo 2 | Pass |
| S6 | Demo 3 多工具链 | Pass |
| S7 | 仅 mock/本地数据 | Pass |

## 机器可读证据

机器跑出的轨迹见同目录 `baseline-v1-runs.json`（由 `python scripts/demo_cli.py --save` 生成）。

签名 / 笔记：Phase 0 机器复跑通过；完整回复见 JSON。
