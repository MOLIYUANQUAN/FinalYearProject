#!/usr/bin/env python3
"""一次性 Google Calendar OAuth 授权（Desktop 流程）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.calendar_providers.google_cal import ensure_google_login
from src.config import GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH, load_env


def main() -> None:
    load_env()
    print(f"credentials: {GOOGLE_CREDENTIALS_PATH}")
    print(f"token will be saved to: {GOOGLE_TOKEN_PATH}")
    print("Requested scope: calendar (read calendars + create/edit events)")
    msg = ensure_google_login()
    print(msg)
    print("Next: set CALENDAR_BACKEND=google in .env and restart the app.")


if __name__ == "__main__":
    main()
