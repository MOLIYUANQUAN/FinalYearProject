"""她的资料页：花费按 token 和价格表在服务端算、每问一次模型记一笔；推送设置改了马上生效；记得的事能看、能删、能撤销。"""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.fake_model import text
from tests.helpers import SandboxTestCase, collect

from src import about, ledger, memory_store, nudges, settings


def fresh_files() -> None:
    for path in (ledger.LEDGER_PATH, settings.SETTINGS_PATH):
        path.unlink(missing_ok=True)


class LedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        fresh_files()
        self.addCleanup(fresh_files)

    def test_cost_counts_cache_reads_and_writes_at_their_own_price(self) -> None:
        # Opus 5.5：1M 输入里 80 万是缓存读、10 万是缓存写，另有 1 万输出
        usd = ledger.cost("claude-opus-5-5", 1_000_000, 10_000, cached=800_000, written=100_000)
        self.assertAlmostEqual(usd, 0.1 * 4 + 0.8 * 0.2 + 0.1 * 5 + 0.01 * 20)
        self.assertAlmostEqual(ledger.cost("gpt-5-2025-08-07", 1_000_000, 0), 1.25)  # 带日期的也认得
        self.assertEqual(ledger.cost("some-new-model", 1_000_000, 1_000_000), 0.0)
        self.assertEqual(ledger.label("gpt-5-2025-08-07"), "GPT-5")

    def test_the_month_adds_up_and_projects_to_month_end(self) -> None:
        ledger.record("claude-opus-5-5", 100_000, 2_000)
        ledger.record("gpt-5", 100_000, 2_000)
        day_11 = datetime.now().replace(day=11, hour=0, minute=0)
        month = ledger.month(day_11)
        self.assertEqual(month["calls"], 2)
        self.assertEqual([m["model"] for m in month["by_model"]], ["Claude Opus 5.5", "GPT-5"])
        days = __import__("calendar").monthrange(day_11.year, day_11.month)[1]
        self.assertAlmostEqual(month["projected"], month["spent"] / 10 * days, delta=0.02)


class EveryCallIsRecorded(SandboxTestCase):
    def setUp(self) -> None:
        super().setUp()
        fresh_files()
        self.addCleanup(fresh_files)

    def test_a_turn_leaves_one_line_per_model_call(self) -> None:
        friday, _ = self.friday([[text("在。")]])
        collect(friday.turn(friday.conversations.create(), "在吗"))
        self.assertEqual(ledger.month()["calls"], 1)


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        fresh_files()
        self.addCleanup(fresh_files)

    def test_push_follows_what_he_set(self) -> None:
        self.assertEqual(nudges.daily_max(), 3)
        self.assertTrue(nudges.quiet(datetime(2026, 10, 13, 23, 0)))
        settings.update({"daily_max": 1, "quiet_from": "23:30", "quiet_until": "07:00"})
        self.assertEqual(nudges.daily_max(), 1)
        self.assertFalse(nudges.quiet(datetime(2026, 10, 13, 23, 0)))
        self.assertTrue(nudges.quiet(datetime(2026, 10, 14, 6, 30)))
        with self.assertRaises(ValueError):
            settings.update({"quiet_from": "25:00"})
        with self.assertRaises(ValueError):
            settings.update({"daily_max": 99})


class AboutApi(SandboxTestCase):
    def setUp(self) -> None:
        super().setUp()
        fresh_files()
        self.addCleanup(fresh_files)
        app = FastAPI()
        app.include_router(about.router)
        self.client = TestClient(app)

    def test_one_call_gives_the_whole_page(self) -> None:
        ledger.record("gpt-5", 10_000, 500)
        me = self.client.get("/api/me").json()
        self.assertEqual(me["model"], "GPT-5")
        self.assertEqual(me["usage"]["budget"], 200)
        self.assertGreater(me["usage"]["spent"], 0)
        self.assertEqual(me["push"]["daily_max"], 3)
        self.assertTrue(all({"name", "ok", "note"} <= set(c) for c in me["connections"]))

    def test_settings_are_checked(self) -> None:
        self.assertEqual(self.client.post("/api/settings", json={"daily_max": 2}).json()["daily_max"], 2)
        self.assertEqual(self.client.post("/api/settings", json={"quiet_until": "9am"}).status_code, 400)

    def test_he_can_delete_a_memory_and_take_it_back(self) -> None:
        saved = memory_store.remember_fact("他周三下午有网球课")
        fact_id = saved.get("id") or saved.get("fact", {}).get("id")
        self.addCleanup(memory_store.forget_fact, fact_id)
        listed = self.client.get("/api/memory").json()
        mine = next(m for m in listed if m["id"] == fact_id)
        gone = self.client.delete(f"/api/memory/{fact_id}").json()
        self.assertNotIn(fact_id, [f["id"] for f in memory_store.all_facts()])
        self.client.post("/api/memory/restore", json={"fact": gone["fact"]})
        self.assertIn(fact_id, [f["id"] for f in memory_store.all_facts()])
        self.assertEqual(mine["content"], "他周三下午有网球课")
        self.assertEqual(self.client.delete("/api/memory/nope").status_code, 404)


class ClaudeBackupIsBilledToTheRightModel(SandboxTestCase):
    def test_served_model_follows_who_answered(self) -> None:
        import anthropic

        from tests.fake_model import FakeModel
        from tests.test_claude import FakeClaude, bad_request
        from src import claude
        from src.agent import VOICE, Friday
        from src.conversation import Conversations

        claude._resting = None
        self.addCleanup(setattr, claude, "_resting", None)
        fresh_files()
        self.addCleanup(fresh_files)
        backup = FakeModel([[text("在。")]])
        backup.model = "gpt-5"
        model = claude.ClaudeModel("claude-opus-5-5", stable_prefix=VOICE,
                                   client=FakeClaude([bad_request("Your credit balance is too low")]),
                                   fallback=(backup, None))
        friday = Friday(Conversations(self.tmp / "c.db"), model=model)
        self.addCleanup(friday.conversations.close)
        collect(friday.turn(friday.conversations.create(), "在吗"))
        self.assertEqual([m["model"] for m in ledger.month()["by_model"]], ["GPT-5"])
        self.assertIsInstance(anthropic.BadRequestError, type)


if __name__ == "__main__":
    unittest.main()
