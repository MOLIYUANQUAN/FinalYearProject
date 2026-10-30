"""一个大脑：会变的状态都在 FRIDAY_STATE_DIR；本机记忆能并到云上，重复并也不出错。"""

from __future__ import annotations

import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from tests import STATE_DIR

from src import config, friction, memory_store
from src.main import app


class StateDirTests(unittest.TestCase):
    def test_writable_state_lives_in_state_dir(self) -> None:
        root = Path(STATE_DIR)
        for path in (config.MEMORY_FACTS_PATH, config.USAGE_LOG_PATH, config.CONVERSATIONS_DB, friction.FRICTION_PATH):
            self.assertTrue(path.is_relative_to(root), path)

    def test_demo_data_stays_in_repo(self) -> None:
        self.assertEqual(config.PROFILE_PATH.parent.parent, config.ROOT_DIR / "data")


class ImportTests(unittest.TestCase):
    def setUp(self) -> None:
        config.MEMORY_FACTS_PATH.unlink(missing_ok=True)
        friction.FRICTION_PATH.unlink(missing_ok=True)
        self.client = TestClient(app)

    def test_import_merges_and_is_idempotent(self) -> None:
        memory_store.remember_fact("导师是 Dr. Smith")
        payload = {
            "facts": [
                {"id": "mem-a", "content": "喜欢早上写代码", "tags": [], "updated_at": "2026-10-01T00:00:00+00:00"},
                {"id": "mem-b", "content": "", "tags": []},  # 空的不要
            ],
            "friction": [{"id": "fr-1", "what": "别催明天的事", "status": "open"}],
        }
        first = self.client.post("/api/state/import", json=payload).json()
        self.assertEqual((first["facts"]["added"], first["facts"]["total"]), (1, 2))
        self.assertEqual(first["friction"]["added"], 1)

        again = self.client.post("/api/state/import", json=payload).json()
        self.assertEqual((again["facts"]["added"], again["facts"]["updated"]), (0, 0))

        contents = {f["content"] for f in self.client.get("/api/state/export").json()["facts"]}
        self.assertEqual(contents, {"导师是 Dr. Smith", "喜欢早上写代码"})

    def test_newer_fact_wins_and_resolved_friction_stays_resolved(self) -> None:
        memory_store.merge_facts([{"id": "mem-x", "content": "旧", "updated_at": "2026-10-01"}])
        memory_store.merge_facts([{"id": "mem-x", "content": "新", "updated_at": "2026-10-02"}])
        memory_store.merge_facts([{"id": "mem-x", "content": "更旧", "updated_at": "2026-09-01"}])
        self.assertEqual([f["content"] for f in memory_store.all_facts()], ["新"])

        friction.merge_items([{"id": "fr-2", "what": "x", "status": "open"}])
        friction.merge_items([{"id": "fr-2", "what": "x", "status": "resolved", "resolved_at": "t"}])
        self.assertEqual(friction.open_items(), [])


if __name__ == "__main__":
    unittest.main()
