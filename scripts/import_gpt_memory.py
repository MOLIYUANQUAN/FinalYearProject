"""把 GPT 导出的记忆迁移包装进 Friday（profile + data/memory/facts.json）。

用法：
  .\\.venv\\Scripts\\python.exe scripts\\import_gpt_memory.py "C:\\path\\to\\完整版包"
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import MEMORY_FACTS_PATH, PROFILE_PATH  # noqa: E402

PRIVATE_CATEGORIES = {
    "team",
    "wellbeing_habits",
    "personal_finance",
    "private_relationships",
    "private_health",
}
SENSITIVE = {"personal", "sensitive", "private"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _is_private(row: dict) -> bool:
    sens = (row.get("sensitivity") or "").lower()
    cat = (row.get("category") or "").lower()
    return sens in SENSITIVE or cat in PRIVATE_CATEGORIES or cat.startswith("private_")


def _to_fact(row: dict) -> dict:
    tags = [
        str(row.get("category") or "").strip().lower(),
        str(row.get("memory_type") or "").strip().lower(),
        str(row.get("status") or "").strip().lower(),
    ]
    if _is_private(row):
        tags.append("private")
    tags = [t for t in tags if t]
    content = (row.get("content") or "").strip()
    as_of = (row.get("as_of") or "").strip()
    status = (row.get("status") or "").strip()
    note_bits = []
    if as_of:
        note_bits.append(f"截至 {as_of}")
    if status and status not in {"active"}:
        note_bits.append(f"状态:{status}")
    if note_bits:
        content = f"{content}（{'；'.join(note_bits)}）"
    return {
        "id": f"gpt-{row.get('id') or ''}".rstrip("-"),
        "content": content,
        "tags": sorted(set(tags)),
        "created_at": _now(),
        "updated_at": _now(),
        "sensitivity": row.get("sensitivity") or "normal",
        "source_id": row.get("id"),
        "priority": int(row.get("priority") or 0),
        "imported_from": "gpt_memory_pack_2026-10-19",
    }


def _merge_facts(existing: list[dict], incoming: list[dict]) -> tuple[list[dict], int, int]:
    by_id = {f.get("id"): f for f in existing if f.get("id")}
    by_content = {(f.get("content") or "").strip(): f for f in existing}
    added = 0
    updated = 0
    for fact in incoming:
        fid = fact["id"]
        text = fact["content"]
        if fid in by_id:
            old = by_id[fid]
            old.update(fact)
            updated += 1
            continue
        if text in by_content:
            # 保留旧 id，合并 tags
            old = by_content[text]
            old_tags = set(old.get("tags") or [])
            old["tags"] = sorted(old_tags | set(fact.get("tags") or []))
            old["updated_at"] = _now()
            for k in ("sensitivity", "source_id", "priority", "imported_from"):
                if fact.get(k) and not old.get(k):
                    old[k] = fact[k]
            updated += 1
            continue
        by_id[fid] = fact
        by_content[text] = fact
        added += 1
    # 新导入的按 priority 高、updated 新排前
    merged = list(by_id.values())
    merged.sort(
        key=lambda f: (
            int(f.get("priority") or 0),
            f.get("updated_at") or "",
        ),
        reverse=True,
    )
    return merged, added, updated


PROFILE_TEXT = """# Zeep

## Who he is
- Zeep（Zepeng Jia），曼彻斯特大学计算机科学大三（2026/27）；常用中文，技术语境熟悉英语；英文名用 Zeep，不用 Jimmy
- 综合体：学生 + 程序员 + 早期创业者；Windows 笔记本 + iPhone
- Final Year Project：Personal AI Agent「Friday」；导师 Dr Wang Zhipeng（王志鹏）
- 创业：深圳市宏流创新科技有限公司（深圳南山）；首个产品「留子圈」（微信小程序，运营重心曼彻斯特）

## How he likes answers
- 中文直接沟通，技术词可保留英文；短、先说答案；要求简短时严格控制篇幅
- 高屋建瓴、通俗易懂；一个问题一个问题推进；创业讨论要敢于质疑，不要无条件认同
- 从真实用户需求与体验反推技术；区分事实 / 建议 / 猜想；数字与进展标明日期
- Afternoon = 12:00–17:00；evening 从 17:00 起
- 会面 brief：时间地点、现状一句、三个讨论点（只来自真材料）

## What he is pursuing
- 学业：大三争取 First Class；课程含 AI and Games、NLP、User Experience、Marketing
- Friday：真正有用的管家（盯开环、调工具），不是又一个聊天机器人；FYP 路径 framework→baseline→application→evaluation
- 留子圈：活动主理人付费交易闭环；北极星曾定为「每周成功履约的付费参与人次」（以最新后台为准）
- 生活：希望重新找回阅读、健身与休息，避免把一切都变成绩效压力

## Term
- Modules include COMP34111 AI and Games, COMP33511 User Experience, BMAN30021 Marketing（及 NLP）
- 完整课表以导入的大学日历（`Mr Zepeng Jia`）为准；忙时先课再项目
- 课程截止与评分以学校公告核实，不把历史记忆当实时事实

## Accounts
- Personal Gmail 已接入
- University Outlook 未接入

## Privacy
- 感情、医疗、家庭、财务旧数据：不在普通场景主动提起；他问起再用记忆检索
- 记忆可纠正、可删除；过时数字（DAU、资产、分成协议）必须再核实

## What needs his OK
- 不用先问：读日历/邮件/笔记；记他告诉你的事；起草
- 先问一次：建日程、发邮件、归档/删邮件、删记忆、对外花钱或改生产数据
"""


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python scripts/import_gpt_memory.py <迁移包目录>")
        return 2
    pack = Path(sys.argv[1])
    if not pack.is_dir():
        print(f"目录不存在: {pack}")
        return 1

    core = pack / "memory_core.jsonl"
    private = pack / "memory_private_review.jsonl"
    if not core.is_file():
        print(f"缺少 {core.name}")
        return 1

    rows = _load_jsonl(core)
    priv_n = 0
    if private.is_file():
        priv = _load_jsonl(private)
        priv_n = len(priv)
        rows.extend(priv)

    incoming = [_to_fact(r) for r in rows if (r.get("content") or "").strip()]
    existing: list[dict] = []
    if MEMORY_FACTS_PATH.is_file():
        data = json.loads(MEMORY_FACTS_PATH.read_text(encoding="utf-8"))
        existing = list(data.get("facts") or [])

    merged, added, updated = _merge_facts(existing, incoming)
    MEMORY_FACTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_FACTS_PATH.write_text(
        json.dumps({"facts": merged, "imported_at": _now()}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(PROFILE_TEXT, encoding="utf-8")

    # 项目快照作一条高优先级记忆，便于检索
    project = pack / "project_context.md"
    if project.is_file():
        snap = project.read_text(encoding="utf-8").strip()
        if snap:
            from src import memory_store

            memory_store.remember_fact(
                content="【项目快照 2026-10-19，需核实】\n" + snap[:3500],
                tags="project,fyp,liuziquan,snapshot",
            )

    print(f"OK profile → {PROFILE_PATH}")
    print(f"OK facts → {MEMORY_FACTS_PATH}  total={len(merged)} added={added} updated={updated}")
    print(f"   core={len(_load_jsonl(core))} private={priv_n} (private 默认不进每轮注入，可 search)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
