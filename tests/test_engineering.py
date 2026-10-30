"""工程线：改好了 / 测试红了进「需要你」，在跑的单独一块；改好了、上线了、红了会主动告诉他；卡片上点两下就上线。"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.helpers import SandboxTestCase

from src import engineering, nudges, presence

PENDING = {
    "branch": "cursor/fix-x",
    "summary": "开场卡片不再催明天的事\n细节…",
    "files": [{"path": "a", "additions": 1, "deletions": 0}, {"path": "b", "additions": 2, "deletions": 1}],
}
NOW = datetime(2026, 10, 13, 9, 0)
RECENT = datetime.now(timezone.utc).isoformat()


def gh(tests="passed", deploy="passed", prs=()) -> dict:
    def run(status):
        return {"status": status, "sha": "abc1234def", "message": "Fix opener", "url": "https://gh/run", "at": RECENT}

    return {"connected": True, "tests": run(tests), "deploy": run(deploy), "prs": list(prs)}


class WorkshopStaysOutOfTheLivingRoom(unittest.TestCase):
    def test_the_daily_card_never_shows_engineering(self) -> None:
        """Cursor 改好了、测试红了：只推送，不进开工画面。"""
        import inspect

        self.assertNotIn("engineering", inspect.getsource(presence.presence_input))
        self.assertFalse(hasattr(engineering, "card"))

    def test_pushes_open_a_question_for_her(self) -> None:
        job = {"status": "done", "agent_id": "a1", "what": "去掉细节"}
        with patch.object(engineering.cursor_fix, "_load_job", return_value=job), patch.object(
            engineering.cursor_fix, "refresh_job", return_value=job
        ), patch.object(engineering.ship, "load_pending", return_value=PENDING):
            found = engineering.events(NOW, gh(tests="failed"))
        urls = {e["kind"]: e["url"] for e in found}
        self.assertIn("do=ask", urls["cursor"])
        self.assertIn("do=ask", urls["ci"])


class EventTests(SandboxTestCase):
    def setUp(self) -> None:
        super().setUp()
        engineering.SHIPPED_PATH.unlink(missing_ok=True)
        nudges.SENT_PATH.unlink(missing_ok=True)
        self.addCleanup(nudges.SENT_PATH.unlink, missing_ok=True)

    def events(self, job=None, pending=None, github=None):
        with patch.object(engineering.cursor_fix, "_load_job", return_value=job), patch.object(
            engineering.cursor_fix, "refresh_job", return_value=job
        ), patch.object(engineering.ship, "load_pending", return_value=pending):
            return engineering.events(NOW, github or gh())

    def test_cursor_done_is_announced(self) -> None:
        found = self.events({"status": "done", "agent_id": "a1", "what": "去掉细节"}, PENDING)
        self.assertEqual([(e["kind"], e["title"]) for e in found], [("cursor", "Cursor 改好了")])

    def test_live_is_announced_once_the_new_version_runs(self) -> None:
        with patch.dict(os.environ, {"FRIDAY_GIT_SHA": "old"}):
            engineering.record_shipped("开场卡片不再催明天的事")
            self.assertEqual(self.events(), [])  # 还是旧版本在跑
        with patch.dict(os.environ, {"FRIDAY_GIT_SHA": "new"}):
            found = self.events()
        self.assertEqual(found[0]["title"], "上线了")
        self.assertIn("开场卡片不再催明天的事", found[0]["body"])
        self.assertFalse(engineering.SHIPPED_PATH.exists())

    def test_red_develop_is_announced(self) -> None:
        self.assertEqual([e["kind"] for e in self.events(github=gh(tests="failed"))], ["ci"])

    def test_engineering_news_does_not_use_the_daily_quota(self) -> None:
        work = [{"kind": "cursor", "key": "cursor:a1", "title": "t", "body": "b", "url": "/"}]
        night = datetime(2026, 10, 13, 23, 30)
        self.assertEqual([n["key"] for n in nudges.due_now(night, [], [], work)], ["cursor:a1"])  # 他刚让改的，晚上也说
        ci = [{"kind": "ci", "key": "ci:x", "title": "t", "body": "b", "url": "/"}]
        self.assertEqual(nudges.due_now(night, [], [], ci), [])  # 红了等白天


class GithubReadTests(unittest.TestCase):
    def test_reads_latest_runs_and_prs(self) -> None:
        runs = {"workflow_runs": [
            {"name": "Deploy Friday", "status": "in_progress", "head_sha": "s2", "head_commit": {"message": "B"}},
            {"name": "Tests", "status": "completed", "conclusion": "failure", "head_sha": "s2", "head_commit": {"message": "B\\nbody"}},
            {"name": "Tests", "status": "completed", "conclusion": "success", "head_sha": "s1"},
        ]}
        pulls = [{"number": 3, "title": "X", "html_url": "u", "draft": False, "head": {"ref": "b"}}]

        def get(url, **kwargs):
            return MagicMock(json=MagicMock(return_value=runs if url.endswith("/runs") else pulls))

        engineering.forget()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "t", "FRIDAY_GITHUB_OFFLINE": ""}), patch.object(
            engineering.requests, "get", side_effect=get
        ):
            state = engineering.github()
        engineering.forget()
        self.assertEqual((state["tests"]["status"], state["tests"]["message"]), ("failed", "B\\nbody".splitlines()[0]))
        self.assertEqual(state["deploy"]["status"], "running")
        self.assertEqual(state["prs"][0]["number"], 3)


if __name__ == "__main__":
    unittest.main()
