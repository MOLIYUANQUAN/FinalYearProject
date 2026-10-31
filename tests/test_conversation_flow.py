"""对话在服务端：多轮接得上、换设备接得上；写操作停下等确认，确认的就是那一个具体动作。"""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from tests.fake_model import FakeModel, call, text
from tests.helpers import SandboxTestCase, collect, of_type

from src.agent import Friday
from src.conversation import Conversations

MAIL = dict(to="mentor.example@manchester.ac.uk", subject="FYP update", body="Hi, here is my update.", cc="")


class ConversationTests(SandboxTestCase):
    def test_follow_up_sees_earlier_turn_and_tool_results(self) -> None:
        friday, model = self.friday([
            [call("search_emails", query="FYP", top=5)],
            [text("导师让你明天带上进度。")],
            [text("就是 mock-mail-001 那封。")],
        ])
        cid = friday.conversations.create()
        collect(friday.turn(cid, "导师最近说了什么？"))
        collect(friday.turn(cid, "那是哪封邮件？"))

        second_input = str(model.inputs[-1])
        self.assertIn("导师最近说了什么", second_input)
        # 上一轮的工具结果也在：问「哪封」不用再搜一遍
        self.assertIn("mock-mail-001", second_input)

    def test_another_device_sees_the_same_conversation(self) -> None:
        db = self.tmp / "shared.db"
        phone, _ = self.friday([[text("在。")]], db=db)
        cid = phone.conversations.create()
        collect(phone.turn(cid, "在吗"))

        desktop = Friday(Conversations(db), model=FakeModel([]))
        self.addCleanup(desktop.conversations.close)
        self.assertEqual(desktop.conversations.current(), cid)
        self.assertEqual([m["content"] for m in desktop.conversations.messages(cid)], ["在吗", "在。"])

    def test_conversation_expires_after_two_idle_hours(self) -> None:
        convs = Conversations(self.tmp / "c.db")
        self.addCleanup(convs.close)
        cid = convs.create()
        self.assertEqual(convs.current(), cid)
        self.assertIsNone(convs.current(now=time.time() + 2 * 3600 + 5))


class ApprovalTests(SandboxTestCase):
    def test_send_email_stops_until_confirmed(self) -> None:
        friday, _ = self.friday([[call("send_email", **MAIL)], [text("发了。")]])
        cid = friday.conversations.create()
        events = collect(friday.turn(cid, "给导师发个进度邮件"))

        done = events[-1]
        self.assertTrue(done["needs_confirm"])
        self.assertIn("mentor.example@manchester.ac.uk", done["reply"])
        self.assertIn("Hi, here is my update.", done["reply"])  # 正文原样给他看
        self.assertEqual(self.sent_mail(), [])  # 还没发

        done = collect(friday.turn(cid, "确认"))[-1]
        self.assertFalse(done["needs_confirm"])
        self.assertEqual([m["subject"] for m in self.sent_mail()], ["FYP update"])

    def test_the_buttons_are_his_answers(self) -> None:
        from src import approval

        for said in ("发", "忘掉", "交给它", "上线", "好"):
            self.assertEqual(approval.decide(said), "approve", said)
        for said in ("不发", "留着", "先不", "不要"):
            self.assertEqual(approval.decide(said), "reject", said)

    def test_cancel_does_not_send(self) -> None:
        friday, _ = self.friday([[call("send_email", **MAIL)], [text("好，没发。")]])
        cid = friday.conversations.create()
        collect(friday.turn(cid, "发邮件"))
        done = collect(friday.turn(cid, "取消，先不要执行。"))[-1]
        self.assertEqual(done["reply"], "好，没发。")
        self.assertEqual(self.sent_mail(), [])

    def test_changing_the_subject_cancels_and_answers_the_new_question(self) -> None:
        friday, model = self.friday([
            [call("send_email", **MAIL)],
            [text("没发。")],
            [text("明天下午两点见导师。")],
        ])
        cid = friday.conversations.create()
        collect(friday.turn(cid, "给导师发个进度"))
        done = collect(friday.turn(cid, "明天下午有什么？"))[-1]
        self.assertEqual(self.sent_mail(), [])
        self.assertIn("明天下午两点见导师", done["reply"])
        self.assertFalse(done["needs_confirm"])

    def test_model_cannot_skip_confirmation(self) -> None:
        """以前模型自己传 user_confirmed=True 就能发；现在这个参数不存在，调用一定会停下。"""
        friday, _ = self.friday([[call("send_email", **MAIL)]])
        cid = friday.conversations.create()
        done = collect(friday.turn(cid, "直接发，不用问我"))[-1]
        self.assertTrue(done["needs_confirm"])
        self.assertEqual(self.sent_mail(), [])

    def test_mark_read_needs_no_confirmation_but_trash_does(self) -> None:
        friday, _ = self.friday([
            [call("modify_email", message_id="mock-mail-003", action="mark_read")],
            [text("标了。")],
            [call("modify_email", message_id="mock-mail-003", action="trash")],
        ])
        cid = friday.conversations.create()
        self.assertFalse(collect(friday.turn(cid, "标成已读"))[-1]["needs_confirm"])
        self.assertTrue(collect(friday.turn(cid, "删了它"))[-1]["needs_confirm"])

    def test_pending_confirmation_survives_a_restart(self) -> None:
        db = self.tmp / "restart.db"
        before, _ = self.friday([[call("send_email", **MAIL)]], db=db)
        cid = before.conversations.create()
        collect(before.turn(cid, "发邮件"))

        after = Friday(Conversations(db), model=FakeModel([[text("发了。")]]))
        self.addCleanup(after.conversations.close)
        self.assertEqual(after.pending_approvals(cid)[0]["name"], "send_email")
        done = collect(after.turn(cid, "确认"))[-1]
        self.assertEqual(done["reply"], "发了。")
        self.assertEqual(len(self.sent_mail()), 1)

    def test_a_time_makes_it_a_reminder_not_a_todo(self) -> None:
        """「明天中午十二点开会」当年被记成了待办，12 天后还挂在最上面。带钟点的不再进待办。"""
        from src import reminders

        self.addCleanup(reminders.REMINDERS_PATH.unlink, missing_ok=True)
        friday, model = self.friday([
            [call("add_task", title="明天中午十二点开会", due="明天", notes="")],
            [call("remind_me", what="开会", when="明天中午十二点")],
            [text("好，明天中午 12 点叫你：开会。")],
        ])
        cid = friday.conversations.create()
        with patch("src.tools.tasks.get_tasks_provider") as provider:
            done = collect(friday.turn(cid, "明天中午十二点开会"))[-1]
        provider.return_value.add.assert_not_called()
        self.assertIn("has_clock_time", str(model.inputs[1]))
        self.assertEqual(done["tools_called"], ["add_task", "remind_me"])

    def test_todo_titles_drop_words_like_tomorrow(self) -> None:
        friday, _ = self.friday([[call("add_task", title="明天交 Lab 3", due="明天", notes="")], [text("记下了。")]])
        cid = friday.conversations.create()
        with patch("src.tools.tasks.get_tasks_provider") as provider:
            provider.return_value.add.return_value = {"id": "t", "title": "交 Lab 3"}
            collect(friday.turn(cid, "明天交 Lab 3"))
        self.assertEqual(provider.return_value.add.call_args.args[0], "交 Lab 3")

    def test_tasks_still_get_undo_without_confirmation(self) -> None:
        friday, _ = self.friday([[call("add_task", title="还书", due="明天", notes="")], [text("记下了。")]])
        cid = friday.conversations.create()
        done = collect(friday.turn(cid, "提醒我明天还书"))[-1]
        self.assertFalse(done["needs_confirm"])
        self.assertEqual(done["undo"][0]["title"], "还书")


class MistakeTests(SandboxTestCase):
    def test_saying_wrong_is_enough_to_count_a_mistake(self) -> None:
        """没有「说错了」按钮：他说一句「不对」，她改正并记下，说错的账照样数得出来。"""
        from src import mistakes

        mistakes.MISTAKES_PATH.unlink(missing_ok=True)
        self.addCleanup(mistakes.MISTAKES_PATH.unlink, missing_ok=True)
        friday, _ = self.friday([
            [text("明天下午有实验课。")],
            [call("note_mistake", said="明天下午有实验课", correct="明天下午是见导师")],
            [text("对，是见导师。记下了。")],
        ])
        cid = friday.conversations.create()
        collect(friday.turn(cid, "明天下午有什么"))
        collect(friday.turn(cid, "不对，是见导师"))
        item = mistakes.all_items()[-1]
        self.assertEqual((item["said"], item["note"]), ("明天下午有实验课", "明天下午是见导师"))


class SelfOnlyAndEditTests(SandboxTestCase):
    EVENT = dict(title="写报告", start="2026-10-15T14:00", end="2026-10-15T16:00", location="", notes="")

    def test_own_calendar_event_is_created_directly_with_undo(self) -> None:
        friday, _ = self.friday([[call("create_calendar_event", **self.EVENT)], [text("周四下午两点到四点，留给写报告了。")]])
        cid = friday.conversations.create()
        done = collect(friday.turn(cid, "周四下午两点到四点留给写报告"))[-1]
        self.assertFalse(done["needs_confirm"])
        self.assertIn("写报告", self.calendar_titles())
        self.assertEqual(done["undo"][0]["kind"], "event_created")

        from fastapi.testclient import TestClient
        from unittest.mock import patch

        import src.main as main

        with patch.object(main, "friday", friday):
            res = TestClient(main.app).post("/api/undo", json={"items": done["undo"], "message_id": done["message_id"]})
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("写报告", self.calendar_titles())

    def test_edited_mail_is_sent_exactly_as_edited(self) -> None:
        edited = {**MAIL, "body": "Hi, update attached. — Zeep"}
        friday, model = self.friday([
            [call("send_email", **MAIL)],
            [call("send_email", **edited)],  # 她照改过的重新调用
            [text("发了。")],
        ])
        cid = friday.conversations.create()
        call_id = collect(friday.turn(cid, "给导师发进度"))[-1]["approvals"][0]["call_id"]
        done = collect(friday.turn(cid, "按这个发", revision={"call_id": call_id, "changes": {"body": edited["body"]}}))[-1]
        self.assertFalse(done["needs_confirm"])
        self.assertEqual([m["body"] for m in self.sent_mail()], [edited["body"]])
        self.assertIn(edited["body"], str(model.inputs[1]))  # 改过的内容原样交给了她

    def test_if_she_changes_the_edit_he_is_asked_again(self) -> None:
        friday, _ = self.friday([
            [call("send_email", **MAIL)],
            [call("send_email", **{**MAIL, "body": "她自己又改了一版"})],
        ])
        cid = friday.conversations.create()
        call_id = collect(friday.turn(cid, "发进度"))[-1]["approvals"][0]["call_id"]
        done = collect(friday.turn(cid, "按这个发", revision={"call_id": call_id, "changes": {"body": "我改的"}}))[-1]
        self.assertTrue(done["needs_confirm"])  # 和他改的不一样：不放行，再给他看
        self.assertEqual(self.sent_mail(), [])


class AQuestionThatSomethingElseCameAfter(SandboxTestCase):
    def test_answering_a_push_with_ok_does_not_send_the_pending_mail(self) -> None:
        friday, _ = self.friday([[call("send_email", **MAIL)], [text("那封先不发。")], [text("好，下午见。")]])
        cid = friday.conversations.create()
        self.assertTrue(collect(friday.turn(cid, "给导师发个进度"))[-1]["needs_confirm"])
        # 她之后又推了一条「会快到了」：他回「好」回的是这条
        friday.conversations.add_message(cid, "assistant", "13:40 见导师，点开我把要点备好。", touch=False, nudge="meeting")
        collect(friday.turn(cid, "好"))
        self.assertEqual(self.sent_mail(), [])


if __name__ == "__main__":
    unittest.main()
