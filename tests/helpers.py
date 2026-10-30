"""测试小工具：演示日历 / 邮箱的临时拷贝、跑完一个异步事件流、用假模型的 Friday。"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.fake_model import FakeModel

from src.agent import Friday
from src.config import CALENDAR_PATH, MAIL_MOCK_PATH
from src.conversation import Conversations


def collect(agen) -> list[dict]:
    async def _run() -> list[dict]:
        return [event async for event in agen]

    return asyncio.run(_run())


def of_type(events: list[dict], kind: str) -> list[dict]:
    return [e for e in events if e["type"] == kind]


class SandboxTestCase(unittest.TestCase):
    """每个测试用一份演示日历和邮箱的拷贝：写操作不会改到仓库里的 data/。"""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="friday-test-"))
        calendar = self.tmp / "calendar.json"
        mail = self.tmp / "messages.json"
        shutil.copy(CALENDAR_PATH, calendar)
        shutil.copy(MAIL_MOCK_PATH, mail)
        for target, value in (
            ("src.calendar_providers.mock.CALENDAR_PATH", calendar),
            ("src.mail_providers.mock.MAIL_MOCK_PATH", mail),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.calendar_path = calendar
        self.mail_path = mail

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def friday(self, turns: list[list[tuple]], db: Path | None = None) -> tuple[Friday, FakeModel]:
        model = FakeModel(turns)
        conversations = Conversations(db or self.tmp / "conversations.db")
        self.addCleanup(conversations.close)
        return Friday(conversations, model=model), model

    def sent_mail(self) -> list[dict]:
        import json

        data = json.loads(self.mail_path.read_text(encoding="utf-8"))
        return [m for m in data["messages"] if "SENT" in (m.get("label_ids") or [])]

    def calendar_titles(self) -> list[str]:
        import json

        return [e["title"] for e in json.loads(self.calendar_path.read_text(encoding="utf-8"))["events"]]
