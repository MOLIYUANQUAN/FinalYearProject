#!/usr/bin/env python3
"""一次性：把 GitHub 和云上的 Friday 互相接上。之后推到 develop 就自动测试、自动部署、自动核对线上版本。

    .\\.venv\\Scripts\\python.exe scripts\\connect_github_fly.py

做两件事：
1. 生成一把 Fly 部署令牌，放进 GitHub 仓库的 Secrets（FLY_API_TOKEN）：GitHub 才能替你部署。
2. 把一把 GitHub 令牌放进云上 Friday（GITHUB_TOKEN）：Friday 才看得见 CI、PR，能在手机上一键合并上线。

装了 GitHub CLI（gh，并且 gh auth login 过）就全自动；没装就带你在网页上粘贴两次。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from deploy_fly import APP, _fly, _run  # noqa: E402

REPO = "MOLIYUANQUAN/FinalYearProject"
SECRETS_PAGE = f"https://github.com/{REPO}/settings/secrets/actions/new"
TOKEN_PAGE = "https://github.com/settings/personal-access-tokens/new"


def _gh() -> str | None:
    gh = shutil.which("gh")
    if not gh:
        return None
    ok = subprocess.run([gh, "auth", "status"], capture_output=True, text=True, check=False)
    return gh if ok.returncode == 0 else None


def _copy(text: str) -> bool:
    try:
        subprocess.run(["clip"], input=text, text=True, check=True)  # Windows
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _fly_token(fly: str) -> str:
    out = _run(fly, "tokens", "create", "deploy", "--app", APP, "--expiry", "8760h", check=False)
    lines = [line.strip() for line in (out.stdout or "").splitlines() if line.strip()]
    token = next((line for line in reversed(lines) if line.startswith("FlyV1 ")), "")
    if not token:
        print(out.stderr or out.stdout)
        sys.exit("没拿到 Fly 令牌：先 flyctl auth login，再跑一次。")
    return token


def main() -> None:
    fly = _fly()
    gh = _gh()

    print("1/2 GitHub 替你部署：生成 Fly 部署令牌…")
    fly_token = _fly_token(fly)
    if gh:
        subprocess.run([gh, "secret", "set", "FLY_API_TOKEN", "-R", REPO], input=fly_token, text=True, check=True)
        print("    已放进 GitHub Secrets：FLY_API_TOKEN")
    else:
        copied = _copy(fly_token)
        webbrowser.open(SECRETS_PAGE)
        print("    浏览器里打开了 GitHub 的 New secret 页面：")
        print("    Name 填 FLY_API_TOKEN；Secret " + ("直接粘贴（令牌已复制到剪贴板）" if copied else f"填下面这行：\n    {fly_token}"))
        input("    保存好以后按回车继续…")

    print("2/2 Friday 看得见 GitHub：")
    if gh:
        github_token = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
    else:
        webbrowser.open(TOKEN_PAGE)
        print("    浏览器里打开了「新建令牌」：Repository access 选 FinalYearProject；")
        print("    Permissions 给 Contents、Pull requests 读写，Actions、Checks 只读；生成后复制。")
        github_token = input("    把令牌粘贴到这里，回车：").strip()
    if not github_token:
        sys.exit("没有 GitHub 令牌，第 2 步没做。")
    imp = subprocess.run([fly, "secrets", "import", "--app", APP], input=f"GITHUB_TOKEN={github_token}\n",
                         text=True, cwd=ROOT, check=False)
    if imp.returncode != 0:
        sys.exit("放进云上没成功：flyctl secrets import 出错了。")
    print("    已放进云上 Friday：GITHUB_TOKEN")

    if gh:
        subprocess.run([gh, "workflow", "run", "deploy-friday.yml", "-R", REPO, "--ref", "develop"], check=False)
        print("\n好了。已经让 GitHub 部署一次最新的 develop；以后推上去就自动测试、部署、核对线上版本。")
    else:
        print("\n好了。下次推到 develop 就会自动测试、部署、核对线上版本。")
        print(f"想现在就部署一次：打开 https://github.com/{REPO}/actions/workflows/deploy-friday.yml 点 Run workflow。")


if __name__ == "__main__":
    main()
