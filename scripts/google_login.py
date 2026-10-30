#!/usr/bin/env python3
"""Google 登录，一条命令全搞定：日历、待办、Gmail 一次授权，并直接带到云上的 Friday。

    .\\.venv\\Scripts\\python.exe scripts\\google_login.py

第一次跑会先打开 Google 控制台的 OAuth consent screen：点一下「Publish app」（转成 In production）。
不点的话 Google 会把这个应用当「测试中」，登录 7 天就作废，Friday 每周都会让你重新登录。
"""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from src.config import (  # noqa: E402
    DATA_DIR,
    GMAIL_TOKEN_PATH,
    GOOGLE_CREDENTIALS_PATH,
    GOOGLE_TASKS_TOKEN_PATH,
    GOOGLE_TOKEN_PATH,
    get_mail_backend,
    get_tasks_backend,
)

CONSENT_PAGE = "https://console.cloud.google.com/apis/credentials/consent"
PUBLISHED_MARK = DATA_DIR / "logs" / "google_app_published"


def _scopes() -> list[tuple[Path, list[str]]]:
    from src.calendar_providers.google_cal import SCOPES as CALENDAR

    wanted = [(GOOGLE_TOKEN_PATH, CALENDAR)]
    if get_tasks_backend() == "google":
        from src.tasks_providers.google_tasks import SCOPES as TASKS

        wanted.append((GOOGLE_TASKS_TOKEN_PATH, TASKS))
    if get_mail_backend() == "gmail":
        from src.mail_providers.gmail import SCOPES as GMAIL

        wanted.append((GMAIL_TOKEN_PATH, GMAIL))
    return wanted


def main() -> None:
    if not GOOGLE_CREDENTIALS_PATH.is_file():
        sys.exit(f"缺少 {GOOGLE_CREDENTIALS_PATH}：先按 docs/google-calendar-setup.md 放好 credentials.json。")

    if not PUBLISHED_MARK.is_file():
        print("第 1 步（只做一次）：浏览器里打开了 Google 的 OAuth consent screen。")
        print("  点「Publish app」→ 确认（转成 In production）。这样登录就不会 7 天作废。")
        webbrowser.open(CONSENT_PAGE)
        input("  点好了按回车…")
        PUBLISHED_MARK.parent.mkdir(parents=True, exist_ok=True)
        PUBLISHED_MARK.write_text("1", encoding="utf-8")

    from google_auth_oauthlib.flow import InstalledAppFlow

    wanted = _scopes()
    scopes = sorted({s for _, group in wanted for s in group})
    print("第 2 步：浏览器里登录 Google，点「允许」（日历" + ("、待办" if len(wanted) > 1 else "") + ("、Gmail" if any(p == GMAIL_TOKEN_PATH for p, _ in wanted) else "") + " 一次授权）。")
    print("  如果看到「此应用未经 Google 验证」：点「高级」→「继续」。这是你自己的应用。")
    flow = InstalledAppFlow.from_client_secrets_file(str(GOOGLE_CREDENTIALS_PATH), scopes)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    for path, _ in wanted:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(creds.to_json(), encoding="utf-8")
    print("  本机登录好了。")

    print("第 3 步：带到云上的 Friday…")
    from deploy_fly import APP, _file_json, _fly

    import subprocess

    names = {GOOGLE_TOKEN_PATH: "GOOGLE_TOKEN_JSON", GOOGLE_TASKS_TOKEN_PATH: "GOOGLE_TASKS_TOKEN_JSON", GMAIL_TOKEN_PATH: "GMAIL_TOKEN_JSON"}
    payload = "".join(f"{names[path]}={_file_json(path)}\n" for path, _ in wanted)
    done = subprocess.run([_fly(), "secrets", "import", "--app", APP], input=payload, text=True, encoding="utf-8", cwd=ROOT, check=False)
    if done.returncode != 0:
        sys.exit("云上没更新成功（flyctl secrets import 出错）。本机已经好了；可以稍后再跑一次这条命令。")
    print("\n好了。云上的 Friday 半分钟后重启就能读到日历和待办。以后不会再 7 天过期。")


if __name__ == "__main__":
    main()
