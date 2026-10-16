#!/usr/bin/env python3
"""Outlook / Microsoft Graph 设备码授权（只读邮件）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import get_outlook_client_id, load_env
from src.mail_providers.outlook import ensure_outlook_login


def main() -> None:
    load_env()
    client = get_outlook_client_id()
    if not client:
        print("Missing OUTLOOK_CLIENT_ID in .env")
        print("See docs/outlook-mail-setup.md")
        raise SystemExit(1)
    print(f"OUTLOOK_CLIENT_ID={client[:8]}...")
    print("Using device code flow. Sign in with your university Outlook account.")
    msg = ensure_outlook_login()
    print(msg)
    print("Next: set MAIL_BACKEND=outlook in .env and restart the app.")


if __name__ == "__main__":
    main()
