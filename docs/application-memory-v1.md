# Application：薄长期记忆 v1

本地 JSON 事实库，**不是** Zep/Letta。目标：他说一次，就一直记得。

## 存储

`data/memory/facts.json` — 只在本机，不进 Git（个人数据）。新克隆的仓库从空记忆开始。

每条：`id` / `content` / `tags` / `created_at` / `updated_at`

## 怎么被用上

- 每一轮对话，最近更新的 40 条记忆连同档案（`data/personal/profile.md`）和此刻时间直接放进 Agent 的上下文，不依赖模型主动去查。
- 更早的记忆用 `search_memory` 关键词检索（中英别名，如「导师」→ mentor/supervisor）。

## 工具

| 工具 | 作用 | 确认 |
|------|------|------|
| `remember_fact` | 写入事实；`replaces=<旧 id>` 时替换旧事实 | 否 |
| `search_memory` | 检索更早的事实 | 否 |
| `forget_fact` | 删除 | 是 |

写入时机：他说「记住…」，或顺带说出关于自己的长期事实/偏好（回复末尾会说「记下了。」）。  
他纠正一条记忆时直接替换，不需要确认；主动删除才需要确认。

## 验收

1. 顺口说「我周四下午一般在图书馆写代码」→ `remember_fact`，回复末尾「记下了。」  
2. 新对话问「我周四下午一般干嘛？」→ 直接答出，无需检索  
3. 说「不对，是周三下午」→ `remember_fact(replaces=...)`，旧事实消失  
4. 删除须先确认  

## 以后可升级

记忆多到注入放不下、关键词检索不够准时，再考虑 embeddings 或 Zep/Letta；接口尽量仍是 remember/search/forget。
