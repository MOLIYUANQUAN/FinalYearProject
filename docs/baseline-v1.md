# Baseline v1 — 复现与验收说明

本文件固定 **Baseline 阶段** 的复现方式与验收标准。对应 Git tag：`baseline-v1`。

> 阶段定位：验证 *single-agent + tool use*，不是完整 Personal AI 产品。  
> 路线：Baseline → Application → Evaluation。

## 从 tag 复现

```bash
git fetch --tags
git checkout baseline-v1
python3 -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填入 OPENAI_API_KEY
python -m src.main     # http://127.0.0.1:8765
```

或跑 CLI（并保存 Evaluation 对照证据）：

```bash
python scripts/demo_cli.py --save
```

证据写入：[evaluation/baseline-v1-runs.json](evaluation/baseline-v1-runs.json)。

## 演示约定（必须一致）

| 概念 | 值 |
|------|-----|
| 模拟今天 `MOCK_TODAY` | `2026-10-12` |
| 「明天」 | `2026-10-13` |
| FYP meeting | `2026-10-13T14:00–15:00`，Kilburn Building |

相对日期由 Agent instructions + `src/config.py` 固定，不依赖本机系统时钟。

## 三条验收 Demo

| # | 输入 | 期望工具（至少） | 期望内容 |
|---|------|------------------|----------|
| 1 | 我明天下午有什么安排？ | `get_calendar_events` | FYP meeting，14:00，Kilburn |
| 2 | 找到我的 FYP proposal，告诉我项目在做什么。 | `search_files` → `read_file` | 基于 `data/notes/fyp-proposal.md` |
| 3 | 帮我准备明天的 FYP meeting。 | 日历 + 文件类工具都出现 | meeting brief（时间地点、摘要、讨论点） |

Demo 3 是硬验收：证明 Agent 能自主连续调用多个工具。

## 成功标准（S1–S7）

见仓库根目录 [README.md](../README.md) 中的成功标准表。Baseline 视为通过的前提是 S1–S7 均可人工验收。

## 仓库分支约定

| 引用 | 用途 |
|------|------|
| tag `baseline-v1` | 报告 / 导师复现 Baseline 快照 |
| 分支 `develop` | 日常开发（Application 等） |
| 分支 `main` | 重大里程碑合入 |

报告中引用 Baseline 时，写明 tag `baseline-v1`，不要依赖 `develop` 最新提交。

## Out of scope（Baseline 明确不做）

以下能力留到 Application 及以后，**本 tag 不包含**：

- Mobile App
- Long-term memory / Zep / Letta
- Database
- Multi-agent
- Browser / Computer Use / Cloud sandbox
- Voice
- Gmail / Drive 等真实云端集成（含 OAuth）
- 真实日历默认关闭（可选 Google 只读，见 google-calendar-setup.md；复现 Baseline 请保持 mock）
- Proactive notifications
- 复杂权限系统
- Production-level UI
- MCP 工具接入（调研可以，Baseline 代码不依赖）

## 下一步（不在本文件范围内）

1. Application：真实 Calendar 只读 + mock fallback  
2. Application：薄 Personal Context + Approval  
3. Evaluation：与本文件证据对照，写对比结果  
