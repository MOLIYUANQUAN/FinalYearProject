# Final Year Project Proposal

**学生**：Jia jimmy  
**项目**：Personal AI Assistant（个人 AI 助手）  
**学校**：University of Manchester，Computer Science Y3

## 项目目标

构建一个面向个人日常任务的单 Agent 助手：理解用户目标，在需要时调用工具（日历、本地文件等），并可串联多次工具调用以完成任务（例如准备会议 brief）。

## 方法简述

- 使用现成 LLM API（不训练模型）
- 以 OpenAI Agents SDK 作为 agent loop / tool calling 运行时
- Baseline 阶段：本地 mock 日历与笔记 + 极简 Web UI，证明单工具与多工具链式调用
- 后续 Application 阶段再接入真实日历/邮件等；Evaluation 阶段再做系统评测

## 当前范围（Baseline）

工具仅限：`get_calendar_events`、`search_files`、`read_file`。无数据库、无长期记忆、无多 Agent。

## 预期演示

1. 查询明天下午安排（日历）
2. 找到本提案并概括项目在做什么（文件）
3. 准备明天的 FYP meeting：先查日历再读提案，生成 meeting brief（多工具链）
