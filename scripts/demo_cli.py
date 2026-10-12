#!/usr/bin/env python3
"""可选 CLI：按顺序跑三条 Baseline Demo（需 OPENAI_API_KEY）。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import run_assistant
from src.config import MOCK_TODAY, MOCK_TOMORROW, require_openai_api_key

DEMOS = [
    "我明天下午有什么安排？",
    "找到我的 FYP proposal，告诉我项目在做什么。",
    "帮我准备明天的 FYP meeting。",
]


async def main() -> None:
    require_openai_api_key()
    print(f"演示今天={MOCK_TODAY}，明天={MOCK_TOMORROW}\n")
    for i, q in enumerate(DEMOS, 1):
        print("=" * 60)
        print(f"Demo {i}: {q}")
        print("-" * 60)
        result = await run_assistant(q)
        print("工具:", " → ".join(result["tools_called"]) or "（无）")
        print(result["reply"])
        print()


if __name__ == "__main__":
    asyncio.run(main())
