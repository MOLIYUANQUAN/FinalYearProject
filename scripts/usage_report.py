#!/usr/bin/env python3
"""Tuesday test：最近几天是不是真的在用、等第一个字要多久（读本地使用记录）。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import USAGE_LOG_PATH


def _median(values: list[int]) -> str:
    return str(int(median(values))) if values else "-"


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarise local usage for the Tuesday test")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    if not USAGE_LOG_PATH.is_file():
        print("还没有使用记录：打开 Personal Agent 用几天再来看。")
        return

    by_day: dict[str, list[dict]] = defaultdict(list)
    for line in USAGE_LOG_PATH.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        by_day[str(entry.get("ts", ""))[:10]].append(entry)

    today = date.today()
    days = [(today - timedelta(days=i)).isoformat() for i in range(args.days - 1, -1, -1)]
    print(f"{'date':<12}{'opens':>7}{'chats':>7}{'first_ms':>10}{'total_ms':>10}{'errors':>8}")
    active = 0
    for day in days:
        entries = by_day.get(day, [])
        if entries:
            active += 1
        opens = sum(1 for e in entries if e.get("kind") == "presence")
        chats = sum(1 for e in entries if e.get("kind") == "chat")
        errors = sum(1 for e in entries if not e.get("ok", True))
        first = [e["first_token_ms"] for e in entries if e.get("first_token_ms") is not None]
        total = [e["total_ms"] for e in entries if e.get("total_ms") is not None]
        print(
            f"{day:<12}{opens:>7}{chats:>7}{_median(first):>10}{_median(total):>10}{errors:>8}"
        )
    print(f"\n最近 {args.days} 天里有 {active} 天在用。")


if __name__ == "__main__":
    main()
