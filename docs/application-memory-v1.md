# Application：薄长期记忆 v1

本地 JSON 事实库，**不是** Zep/Letta。目标：跨对话记住用户明确说过的事实。

## 存储

`data/memory/facts.json`

每条：`id` / `content` / `tags` / `created_at` / `updated_at`

## 工具

| 工具 | 作用 | 确认 |
|------|------|------|
| `remember_fact` | 写入/更新事实 | 否（用户主动说记住） |
| `search_memory` | 关键词检索 | 否 |
| `forget_fact` | 删除 | 是 |

## 与 profile 的分工

- `get_personal_context` → 相对稳定的 `data/personal/profile.md`
- `search_memory` → 运行中不断积累的动态事实

## 验收

1. 「记住我的 FYP 导师邮箱是 mentor@example.com」→ `remember_fact`  
2. 新开一轮问：「我导师邮箱是什么？」→ `search_memory` 能答出  
3. 删除须先确认  

## 以后可升级

检索效果不够时，再考虑 embeddings 或 Zep/Letta；接口尽量仍是 remember/search/forget。
