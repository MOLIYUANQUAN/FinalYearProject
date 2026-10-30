#!/usr/bin/env python3
"""Tuesday test：最近几天是不是真的在用、等第一个字要多久（读本地使用记录）。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import USAGE_LOG_PATH, get_access_token, load_env


def _median(values: list[int]) -> str:
    return str(int(median(values))) if values else "-"


def _load(days: int, *, remote: bool) -> list[dict] | None:
    """大脑在云上（.env 有 FRIDAY_URL）就读云上的记录，否则读本机文件。"""
    load_env()
    url = (os.getenv("FRIDAY_URL") or "").strip().rstrip("/")
    if remote and url:
        import requests

        token = get_access_token()
        res = requests.get(
            f"{url}/api/usage/events",
            params={"days": days},
            headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=30,
        )
        res.raise_for_status()
        return res.json().get("events") or []
    if not USAGE_LOG_PATH.is_file():
        return None
    entries = []
    for line in USAGE_LOG_PATH.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarise local usage for the Tuesday test")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--local", action="store_true", help="只看本机记录（默认：设了 FRIDAY_URL 就看云上的）")
    args = parser.parse_args()

    entries = _load(args.days, remote=not args.local)
    if entries is None:
        print("还没有使用记录：用 Friday 几天再来看。")
        return

    by_day: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        by_day[str(entry.get("ts", ""))[:10]].append(entry)

    today = date.today()
    days = [(today - timedelta(days=i)).isoformat() for i in range(args.days - 1, -1, -1)]
    print(f"{'date':<12}{'opens':>7}{'chats':>7}{'first_ms':>10}{'total_ms':>10}{'errors':>8}{'wrong':>7}{'closed':>8}")
    active = 0
    for day in days:
        entries = by_day.get(day, [])
        if entries:
            active += 1
        opens = sum(1 for e in entries if e.get("kind") == "presence")
        chats = sum(1 for e in entries if e.get("kind") == "chat")
        errors = sum(1 for e in entries if not e.get("ok", True))
        # 他点了「说错了」的次数：目标是 0
        wrong = sum(1 for e in entries if e.get("kind") == "wrong")
        # 替他关掉了几件：KPI
        done = sum(1 for e in entries if e.get("kind") == "closed")
        first = [e["first_token_ms"] for e in entries if e.get("first_token_ms") is not None]
        total = [e["total_ms"] for e in entries if e.get("total_ms") is not None]
        print(
            f"{day:<12}{opens:>7}{chats:>7}{_median(first):>10}{_median(total):>10}{errors:>8}{wrong:>7}{done:>8}"
        )
    print(f"\n最近 {args.days} 天里有 {active} 天在用。")


if __name__ == "__main__":
    main()
