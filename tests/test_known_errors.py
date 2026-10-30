"""工程记录里出现过的 7 类说错，和「绝不没经过你就动手」：每一类一条护栏，改代码时不许改回去。

日子、星期、数目、时区都由服务端算好写进数据，模型只照着说；这里测的就是这些算出来的东西。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import unittest
from unittest.mock import patch

from tests.helpers import SandboxTestCase

from src import agenda, presence
from src.agent import build_instructions
from src.tools import ALL_TOOLS, TASK_TOOLS

WRITE_TOOLS = {
    "send_email",
    "modify_email",
    "forget_fact",
    "fix_friction_with_cursor",
    "ship_pending_fix",
}


class AgendaFacts(SandboxTestCase):
    """演示模式下「此刻」固定在 2026-10-12 周一 09:00。"""

    def setUp(self) -> None:
        super().setUp()
        agenda.forget()
        self.addCleanup(agenda.forget)

    def add_event(self, title: str, start: str, end: str) -> None:
        data = json.loads(self.calendar_path.read_text(encoding="utf-8"))
        data["events"].append({"id": f"t-{title}", "title": title, "start": start, "end": end, "location": None})
        self.calendar_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        agenda.forget()

    def test_1_7_each_day_lists_exactly_its_events_with_the_count(self) -> None:
        """#1 编造「明天有课和实验」、#7 数错几节课：每天几项由服务端写好，只列真有的。"""
        block = agenda.chat_block()
        tomorrow = block.split("明天 10月13日 周二：")[1].split("\n10月14日")[0]
        self.assertTrue(tomorrow.startswith("2 项"))
        self.assertIn("Comp30291 lecture", tomorrow)
        self.assertIn("FYP meeting with mentor", tomorrow)
        self.assertNotIn("Lab", tomorrow)
        self.assertIn("【这周，到 10月18日 周日：还有 4 项】", block)

    def test_2_opener_says_tomorrow_for_tomorrows_meeting(self) -> None:
        """#2 开场把明天的会说成今天。"""
        _card, say = asyncio.run(presence.presence_input())
        self.assertIn("明天下午 2 点", say.replace(" ", " "))
        self.assertNotIn("今天下午 2 点", say.replace(" ", " "))

    def test_4_weekdays_are_right(self) -> None:
        """#4 把「周一」算成周二。"""
        block = agenda.chat_block()
        self.assertIn("今天 10月12日 周一", block)
        self.assertIn("10月16日 周五", block)

    def test_5_next_weeks_class_is_not_this_week(self) -> None:
        """#5 把下周的课说成这周。"""
        self.add_event("COMP34111 Lecture", "2026-10-20T10:00:00", "2026-10-20T11:00:00")
        block = agenda.chat_block()
        this_week, next_week = block.split("【下周")
        self.assertNotIn("COMP34111", this_week)
        self.assertIn("COMP34111", next_week)
        self.assertIn("10月20日 下周二：1 项", next_week)


class TimezoneTests(unittest.TestCase):
    def test_3_utc_calendar_times_become_london_time(self) -> None:
        """#3 课表时间早一小时：导入的课表给的是 UTC，一律先换成伦敦本地钟点（云上也要设 TZ）。"""
        if not hasattr(time, "tzset"):
            self.skipTest("time.tzset 只在 Unix 上有")
        old = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/London"
        time.tzset()
        try:
            self.assertEqual(agenda.local_time("2026-10-13T13:00:00Z").hour, 14)  # 夏令时
            self.assertEqual(agenda.local_time("2026-11-03T13:00:00Z").hour, 13)  # 冬令时
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()

    def test_cloud_runs_on_london_time(self) -> None:
        from src.config import ROOT_DIR

        self.assertIn('TZ = "Europe/London"', (ROOT_DIR / "fly.toml").read_text(encoding="utf-8"))


class PromptGuards(unittest.TestCase):
    """模型那边的护栏写在提示词里：这些规则删了就会回到以前的错。"""

    def test_6_and_honesty_rules_stay_in_the_prompt(self) -> None:
        instructions = build_instructions()
        for rule in (
            "只说你这次真查过的：没调用过 search_emails，就不能说邮件里没有。",  # 6 没搜邮件就说没有
            "绝不编造时间、地点、人名或邮件内容",
            "日程、邮件、文件内容只能来自工具结果或下面给出的数据",
        ):
            self.assertIn(rule, instructions)

    def test_prompt_does_not_ask_for_text_confirmation(self) -> None:
        """确认由系统做；提示词里不能再让模型自己问「要不要」或传 user_confirmed。"""
        instructions = build_instructions()
        self.assertNotIn("user_confirmed", instructions)
        self.assertNotIn("request_user_confirmation", instructions)


class WriteGuards(unittest.TestCase):
    def test_every_write_tool_needs_approval(self) -> None:
        tools = {t.name: t for t in ALL_TOOLS + TASK_TOOLS}
        self.assertTrue(WRITE_TOOLS <= set(tools), WRITE_TOOLS - set(tools))
        for name in WRITE_TOOLS:
            self.assertTrue(tools[name].needs_approval, f"{name} 必须先经过他确认")

    def test_no_tool_takes_a_user_confirmed_flag(self) -> None:
        for tool in ALL_TOOLS + TASK_TOOLS:
            self.assertNotIn("user_confirmed", json.dumps(tool.params_json_schema), tool.name)

    def test_only_tasks_and_memory_write_without_asking(self) -> None:
        """记待办 / 记住一件事直接做（给撤销或能纠正）；别的写操作都要先问。"""
        # 只给他自己的：直接做、给撤销（待办、自己的日程），或说一句就能纠正（记忆、摩擦）
        unguarded_writes = {
            "add_task", "complete_task", "create_calendar_event", "remind_me", "cancel_reminder",
            "remember_fact", "note_friction", "note_mistake", "resolve_friction",
        }
        for tool in ALL_TOOLS + TASK_TOOLS:
            if tool.name in unguarded_writes or tool.name in WRITE_TOOLS:
                continue
            self.assertTrue(
                tool.name.startswith(("get_", "search_", "read_", "list_", "check_", "preview_")),
                f"{tool.name} 是新工具：它会写东西吗？会的话加进 WRITE_TOOLS 并设 needs_approval",
            )


if __name__ == "__main__":
    unittest.main()
