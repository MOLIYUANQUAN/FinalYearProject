#!/usr/bin/env python3
"""Google Tasks OAuth（复用 secrets/credentials.json，token 单独存，不动日历和 Gmail 的授权）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import GOOGLE_CREDENTIALS_PATH, GOOGLE_TASKS_TOKEN_PATH, load_env
from src.tasks_providers.google_tasks import ensure_tasks_login


def main() -> None:
    load_env()
    print(f"credentials: {GOOGLE_CREDENTIALS_PATH}")
    print(f"token will be saved to: {GOOGLE_TASKS_TOKEN_PATH}")
    print("Scope: tasks (read/write your Google Tasks)")
    print("Make sure the Google Tasks API is enabled in the same Google Cloud project.")
    print(ensure_tasks_login())
    print("Next: set TASKS_BACKEND=google in .env; Friday picks it up on the next Ctrl+Alt+F.")


if __name__ == "__main__":
    main()
