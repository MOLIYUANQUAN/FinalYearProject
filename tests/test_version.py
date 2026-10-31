"""版本号只写在 src/version.py 一处：CHANGELOG 最上面那一版、/api/health、资料页都得跟它一致。"""

from __future__ import annotations

import os
import re
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.helpers import SandboxTestCase

from src import about
from src.config import ROOT_DIR
from src.version import VERSION

SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
HEADING = re.compile(r"^## (\d+\.\d+\.\d+) — (\d{4}-\d{2}-\d{2})", re.MULTILINE)


def changelog() -> list[tuple[str, str]]:
    return HEADING.findall((ROOT_DIR / "CHANGELOG.md").read_text(encoding="utf-8"))


def parts(version: str) -> tuple[int, int, int]:
    match = SEMVER.match(version)
    assert match, version
    return tuple(int(n) for n in match.groups())  # type: ignore[return-value]


class VersionTests(unittest.TestCase):
    def test_version_is_major_minor_patch(self) -> None:
        self.assertRegex(VERSION, SEMVER)

    def test_changelog_starts_with_this_version(self) -> None:
        entries = changelog()
        self.assertTrue(entries, "CHANGELOG.md 里没有找到「## x.y.z — YYYY-MM-DD」这样的版本标题")
        self.assertEqual(entries[0][0], VERSION, "改了 VERSION 就在 CHANGELOG.md 最上面加这一版（反过来也一样）")

    def test_changelog_goes_newest_first_without_repeats(self) -> None:
        versions = [parts(v) for v, _date in changelog()]
        self.assertEqual(versions, sorted(versions, reverse=True))
        self.assertEqual(len(versions), len(set(versions)))
        dates = [d for _v, d in changelog()]
        self.assertEqual(dates, sorted(dates, reverse=True))


class VersionIsShown(SandboxTestCase):
    def test_health_reports_the_version(self) -> None:
        import src.main as main

        self.assertEqual(main.app.version, VERSION)
        self.assertEqual(TestClient(main.app).get("/api/health").json()["version"], VERSION)

    def test_profile_page_shows_version_and_build(self) -> None:
        app = FastAPI()
        app.include_router(about.router)
        with patch.dict(os.environ, {"FRIDAY_GIT_SHA": "8437d4d60c757b9aa9819dc124c7e7b601d9b95f"}):
            me = TestClient(app).get("/api/me").json()
        self.assertEqual(me["version"], VERSION)
        self.assertEqual(me["build"], "8437d4d")


if __name__ == "__main__":
    unittest.main()
