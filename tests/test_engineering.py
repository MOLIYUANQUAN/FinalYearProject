"""工程线：改好了 / 测试红了进「需要你」，在跑的单独一块；改好了、上线了、红了会主动告诉他；卡片上点两下就上线。"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.helpers import SandboxTestCase

import src.workbench as workbench
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


class CardTests(unittest.TestCase):
    def setUp(self) -> None:
        for p in (
            patch.object(engineering.ship, "load_pending", return_value=None),
            patch.object(engineering.cursor_fix, "_load_job", return_value=None),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_quiet_when_nothing_is_going_on(self) -> None:
        self.assertEqual(engineering.card(gh()), ([], None))

    def test_ready_change_needs_a_decision(self) -> None:
        with patch.object(engineering.ship, "load_pending", return_value=PENDING):
            decisions, running = engineering.card(gh())
        row = decisions[0]
        self.assertEqual((row["time"], row["title"], row["where"]), ("改好了", "开场卡片不再催明天的事", "Cursor · 2 个文件"))
        self.assertEqual([a["id"] for a in row["actions"]], ["ship", "preview"])
        self.assertEqual(row["actions"][0]["confirm"], "确认上线")
        self.assertIsNone(running)

    def test_red_develop_offers_cursor(self) -> None:
        decisions, _ = engineering.card(gh(tests="failed"))
        self.assertEqual(decisions[0]["time"], "测试红了")
        self.assertIn("用 Cursor 修", decisions[0]["actions"][0]["ask"])

    def test_running_things_have_their_own_section(self) -> None:
        job = {"status": "running", "what": "去掉细节"}
        prs = [{"number": 7, "title": "Add X", "url": "u", "draft": False, "branch": "b"},
               {"number": 8, "title": "WIP", "url": "u", "draft": True, "branch": "c"}]
        with patch.object(engineering.cursor_fix, "_load_job", return_value=job), patch.object(
            engineering.cursor_fix, "refresh_job", return_value=job
        ), patch.dict(os.environ, {"FRIDAY_GIT_SHA": "1234567890"}):
            _, running = engineering.card(gh(deploy="running", prs=prs))
        self.assertEqual([r["time"] for r in running["rows"]], ["在改", "上线中", "PR #7"])  # 草稿 PR 不占地方
        self.assertEqual(running["meta"], "线上 1234567")

    def test_decisions_go_on_top_of_needs_you(self) -> None:
        sections = [{"label": "今天", "rows": []}]
        presence._add_engineering(sections, [{"time": "改好了"}], {"label": "在跑的", "rows": [{}]})
        self.assertEqual([s["label"] for s in sections], ["需要你", "今天", "在跑的"])


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


class ShipFromCardTests(SandboxTestCase):
    def setUp(self) -> None:
        super().setUp()
        friday, _ = self.friday([])
        engineering.SHIPPED_PATH.unlink(missing_ok=True)
        for p in (
            patch.object(workbench, "friday", friday),
            patch.object(workbench.ship, "load_or_recover_pending", return_value=PENDING),
        ):
            p.start()
            self.addCleanup(p.stop)
        app = FastAPI()
        app.include_router(workbench.router)
        self.client = TestClient(app)

    def test_preview_shows_the_change(self) -> None:
        with patch.object(workbench.ship, "compare", return_value={"ok": False}):
            data = self.client.post("/api/items/act", json={"key": "ship:pending", "action": "preview"}).json()
        self.assertIn("Cursor 改完了", data["say"])

    def test_ship_merges_and_remembers_to_announce(self) -> None:
        result = {"ok": True, "merged": True, "say": "已合进 develop，GitHub 正在自动部署。"}
        with patch.object(workbench.ship, "ship", return_value=result) as shipped:
            data = self.client.post("/api/items/act", json={"key": "ship:pending", "action": "ship"}).json()
        shipped.assert_called_once_with(user_confirmed=True)
        self.assertEqual(data["say"], result["say"])
        self.assertTrue(engineering.SHIPPED_PATH.exists())

    def test_failed_tests_block_and_nothing_is_announced(self) -> None:
        blocked = {"ok": False, "error": "tests_failed", "say": "Cursor 这版没过测试，我没合并、也没部署。"}
        with patch.object(workbench.ship, "ship", return_value=blocked):
            data = self.client.post("/api/items/act", json={"key": "ship:pending", "action": "ship"}).json()
        self.assertIn("没过测试", data["say"])
        self.assertFalse(engineering.SHIPPED_PATH.exists())


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
