#!/usr/bin/env python3
"""Deploy Friday to Fly.io (app: friday-jimmy, region lhr).

Installs nothing by itself — needs flyctl on PATH (or %LOCALAPPDATA%\\fly\\bin).
First time: flyctl auth login (browser).
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = "friday-jimmy"
REGION = "lhr"
VOLUME = "friday_state"
ENV_PATH = ROOT / ".env"


def _fail(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(1)


def _fly() -> str:
    found = shutil.which("flyctl") or shutil.which("fly")
    if found:
        return found
    home = Path.home()
    for candidate in (
        home / ".fly" / "bin" / "flyctl.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "fly" / "bin" / "flyctl.exe",
    ):
        if candidate.is_file():
            return str(candidate)
    _fail(
        "flyctl not found. In PowerShell:\n"
        "  powershell -ExecutionPolicy Bypass -File scripts\\install_flyctl.ps1\n"
        "Then: flyctl auth login\n"
        "Then: .venv\\Scripts\\python.exe scripts\\deploy_fly.py"
    )


def _run(
    fly: str,
    *args: str,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [fly, *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
        check=check,
    )


def _env_map() -> dict[str, str]:
    if not ENV_PATH.is_file():
        _fail(f"Missing {ENV_PATH}")
    out: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def _ensure_access_token(env: dict[str, str]) -> str:
    token = (env.get("FRIDAY_ACCESS_TOKEN") or "").strip()
    if token:
        return token
    token = secrets.token_urlsafe(18)
    with ENV_PATH.open("a", encoding="utf-8") as f:
        f.write(f"\n# Cloud / phone access\nFRIDAY_ACCESS_TOKEN={token}\n")
    print("Generated FRIDAY_ACCESS_TOKEN and appended to .env")
    return token


def _file_json(path: Path) -> str | None:
    if not path.is_file():
        return None
    # one line so fly secrets CLI stays happy
    return json.dumps(json.loads(path.read_text(encoding="utf-8")), ensure_ascii=False, separators=(",", ":"))


def _ensure_volume(fly: str) -> None:
    """fly.toml 把 friday_state 挂到 /state：记忆和对话放在上面。没有就建一个 1GB 的。"""
    listed = _run(fly, "volumes", "list", "--app", APP, "--json", check=False)
    try:
        volumes = json.loads(listed.stdout or "[]") if listed.returncode == 0 else []
    except json.JSONDecodeError:
        volumes = []
    if any((v.get("name") or v.get("Name")) == VOLUME for v in volumes if isinstance(v, dict)):
        return
    print(f"Creating volume {VOLUME} (1GB, {REGION})…")
    created = _run(fly, "volumes", "create", VOLUME, "--app", APP, "--region", REGION, "--size", "1", "--yes", check=False)
    if created.returncode != 0:
        print(created.stderr or created.stdout or "")
        _fail(f"Could not create volume. Run: flyctl volumes create {VOLUME} -a {APP} -r {REGION} -s 1")


def main() -> None:
    fly = _fly()
    print(f"Using {fly}")
    who = _run(fly, "auth", "whoami", check=False)
    if who.returncode != 0:
        print("Log in to Fly (browser)…")
        _run(fly, "auth", "login")

    env = _env_map()
    openai = (env.get("OPENAI_API_KEY") or "").strip()
    if not openai:
        _fail("OPENAI_API_KEY missing in .env")
    token = _ensure_access_token(env)

    apps = _run(fly, "apps", "list", "--json", check=False)
    names: list[str] = []
    raw_apps = (apps.stdout or "").strip()
    if apps.returncode == 0 and raw_apps:
        try:
            parsed = json.loads(raw_apps)
            if isinstance(parsed, list):
                names = [str(a.get("Name") or a.get("name") or "") for a in parsed]
        except json.JSONDecodeError:
            names = []
    if APP not in names:
        print(f"Creating app {APP}…")
        created = _run(fly, "apps", "create", APP, "--org", "personal", check=False)
        if created.returncode != 0:
            # org 名因账号而异：不带 --org 再试一次
            created = _run(fly, "apps", "create", APP, check=False)
            if created.returncode != 0:
                print(created.stderr or created.stdout or "")
                _fail("Could not create Fly app. Run: flyctl apps create friday-jimmy")

    pairs = {
        "OPENAI_API_KEY": openai,
        "FRIDAY_ACCESS_TOKEN": token,
        "CALENDAR_BACKEND": env.get("CALENDAR_BACKEND") or "google",
        "MAIL_BACKEND": env.get("MAIL_BACKEND") or "gmail",
        "TASKS_BACKEND": env.get("TASKS_BACKEND") or "google",
        "GOOGLE_CALENDAR_ID": env.get("GOOGLE_CALENDAR_ID") or "selected",
        "HOST": "0.0.0.0",
    }
    # 有 ElevenLabs / Cursor key 就上云；没有则跳过
    for name in (
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_VOICE_ID",
        "ELEVENLABS_MODEL",
        "CURSOR_API_KEY",
        "CURSOR_AGENT_RUNTIME",
        "CURSOR_REPO_URL",
        "CURSOR_REPO_REF",
        "CURSOR_MODEL",
        "GITHUB_TOKEN",
        "GH_TOKEN",
    ):
        value = (env.get(name) or "").strip()
        if value:
            pairs[name] = value


    for env_name, path in [
        ("GOOGLE_CREDENTIALS_JSON", ROOT / "secrets" / "credentials.json"),
        ("GOOGLE_TOKEN_JSON", ROOT / "secrets" / "google_token.json"),
        ("GMAIL_TOKEN_JSON", ROOT / "secrets" / "gmail_token.json"),
        ("GOOGLE_TASKS_TOKEN_JSON", ROOT / "secrets" / "google_tasks_token.json"),
    ]:
        blob = _file_json(path)
        if blob:
            pairs[env_name] = blob
        else:
            print(f"[warn] missing {path.name} — that Google API will not work on cloud until you add it")

    print("Setting Fly secrets (values not printed)…")
    # stdin import avoids shell escaping issues with JSON
    payload = "\n".join(f"{k}={v}" for k, v in pairs.items()) + "\n"
    imp = subprocess.run(
        [fly, "secrets", "import", "--app", APP],
        input=payload,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        check=False,
    )
    if imp.returncode != 0:
        print(imp.stderr or imp.stdout)
        _fail("fly secrets import failed")

    _ensure_volume(fly)

    print("Deploying…")
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False).stdout.strip()
    extra = ["--env", f"FRIDAY_GIT_SHA={sha}"] if sha else []
    _run(fly, "deploy", "--app", APP, "--ha=false", *extra, capture=False)

    # hostname
    status = _run(fly, "status", "--app", APP, "--json", check=False)
    host = f"{APP}.fly.dev"
    if status.returncode == 0 and status.stdout.strip():
        try:
            data = json.loads(status.stdout)
            hostname = data.get("Hostname") or data.get("hostname")
            if hostname:
                host = hostname
        except json.JSONDecodeError:
            pass

    print()
    print("=" * 60)
    print("Friday on the cloud:")
    print(f"https://{host}/")
    print()
    print("Open in Safari; enter FRIDAY_ACCESS_TOKEN once (then Cookie remembers).")
    print("One-shot link (optional):")
    print(f"https://{host}/?access={token}")
    print("PC can be off. Do not share the one-shot link.")
    print()
    print("If Google says redirect_uri_mismatch: add")
    print(f"  https://{host}")
    print("to OAuth client authorized origins / redirect URIs, re-auth locally, re-run this script.")
    print("=" * 60)


if __name__ == "__main__":
    main()
