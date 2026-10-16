#!/usr/bin/env python3
"""Gmail 只读 OAuth（复用 secrets/credentials.json）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import GOOGLE_CREDENTIALS_PATH, GMAIL_TOKEN_PATH, load_env
from src.mail_providers.gmail import ensure_gmail_login


def main() -> None:
    load_env()
    print(f"credentials: {GOOGLE_CREDENTIALS_PATH}")
    print(f"token will be saved to: {GMAIL_TOKEN_PATH}")
    print("Scope: gmail.readonly")
    print("Make sure Gmail API is enabled in the same Google Cloud project.")
    msg = ensure_gmail_login()
    print(msg)
    print("Next: set MAIL_BACKEND=gmail in .env and restart the app.")


if __name__ == "__main__":
    main()
