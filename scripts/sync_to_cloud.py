#!/usr/bin/env python3
"""把这台电脑上攒下的记忆和摩擦清单并到云上的 Friday（只合并，不覆盖，重复跑也安全）。

    python scripts/sync_to_cloud.py              # 用 .env 里的 FRIDAY_URL 和 FRIDAY_ACCESS_TOKEN
    python scripts/sync_to_cloud.py --backup     # 另外把云上的整份记忆存一份到 data/backup/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import DATA_DIR, get_access_token, load_env  # noqa: E402

LOCAL_FACTS = DATA_DIR / "memory" / "facts.json"
LOCAL_FRICTION = DATA_DIR / "feedback" / "friction.jsonl"


def _local_state() -> dict:
    facts = []
    if LOCAL_FACTS.is_file():
        facts = json.loads(LOCAL_FACTS.read_text(encoding="utf-8")).get("facts") or []
    friction = []
    if LOCAL_FRICTION.is_file():
        for line in LOCAL_FRICTION.read_text(encoding="utf-8").splitlines():
            try:
                friction.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return {"facts": facts, "friction": friction}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", help="云上地址；默认读 .env 的 FRIDAY_URL")
    parser.add_argument("--backup", action="store_true", help="先把云上的整份记忆备份到 data/backup/")
    args = parser.parse_args()

    load_env()
    url = (args.url or os.getenv("FRIDAY_URL") or "").strip().rstrip("/")
    if not url:
        sys.exit("没设 FRIDAY_URL：在 .env 里加 FRIDAY_URL=https://friday-jimmy.fly.dev")
    headers = {"Authorization": f"Bearer {get_access_token()}"} if get_access_token() else {}

    if args.backup:
        res = requests.get(f"{url}/api/state/export", headers=headers, timeout=30)
        res.raise_for_status()
        out = DATA_DIR / "backup" / f"cloud-state-{datetime.now():%Y%m%d-%H%M%S}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res.json(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"云上备份：{out}")

    state = _local_state()
    print(f"本机：{len(state['facts'])} 条记忆，{len(state['friction'])} 条摩擦")
    res = requests.post(f"{url}/api/state/import", json=state, headers=headers, timeout=60)
    if res.status_code == 401:
        sys.exit("云上说没登录：检查 .env 里的 FRIDAY_ACCESS_TOKEN 和云上是不是同一个。")
    res.raise_for_status()
    data = res.json()
    print(f"记忆：新增 {data['facts']['added']}，更新 {data['facts']['updated']}，云上共 {data['facts']['total']} 条")
    print(f"摩擦：新增 {data['friction']['added']}，更新 {data['friction']['updated']}，云上共 {data['friction']['total']} 条")


if __name__ == "__main__":
    main()
