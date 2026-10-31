"""Claude 当脑子：放了 key 就换上；流式、工具往返、确认都照旧；思考块只在这一句里原样带回；被拦下有退路。

不联网：用一个按脚本回话的假 Anthropic 客户端，看 Friday 发出去的请求长什么样。
"""

from __future__ import annotations

import copy
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
from anthropic.types.beta import BetaMessage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseReasoningItem

from tests.fake_model import FakeModel, text
from tests.helpers import SandboxTestCase, collect, of_type

import src.agent as agent
from src import claude, config, names
from src.agent import VOICE, Friday
from src.conversation import Conversations

MODEL = "claude-opus-5-5"
MAIL = dict(to="mentor.example@manchester.ac.uk", subject="FYP update", body="Hi, here is my update.", cc="")


def think(signature: str) -> dict:
    return {"type": "thinking", "thinking": "", "signature": signature}


def say(text: str) -> dict:
    return {"type": "text", "text": text}


def use(name: str, ident: str, **arguments) -> dict:
    return {"type": "tool_use", "id": ident, "name": name, "input": arguments}


FALLBACK = {"type": "fallback", "from": {"model": MODEL}, "to": {"model": "claude-opus-5"},
            "trigger": {"type": "refusal", "category": None}}


def reply(*blocks: dict, stop: str = "end_turn", model: str = MODEL) -> BetaMessage:
    return BetaMessage.model_validate({
        "id": "msg_test", "type": "message", "role": "assistant", "model": model, "content": list(blocks),
        "stop_reason": stop, "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 900,
                  "cache_creation_input_tokens": 0},
    })


class FakeStream:
    def __init__(self, message: BetaMessage) -> None:
        self.message = message

    async def __aenter__(self) -> "FakeStream":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def _events(self):
        for block in self.message.content:
            if block.type == "text":
                for i in range(0, len(block.text), 4):
                    yield SimpleNamespace(type="text", text=block.text[i : i + 4])

    def __aiter__(self):
        return self._events()

    async def get_final_message(self) -> BetaMessage:
        return self.message


class FakeClaude:
    """按脚本一条条回话；脚本里放异常就在开流时抛出（像 API 的 400）。"""

    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **params):
        self.requests.append(copy.deepcopy(params))
        if not self.replies:
            raise AssertionError("FakeClaude 脚本已用完")
        nxt = self.replies.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return FakeStream(nxt)


def blocks(request: dict, kind: str) -> list[dict]:
    return [b for m in request["messages"] for b in m["content"] if b.get("type") == kind]


def bad_request(message: str) -> anthropic.BadRequestError:
    return anthropic.BadRequestError(message, response=MagicMock(status_code=400), body=None)


class ClaudeConversationTests(SandboxTestCase):
    def setUp(self) -> None:
        super().setUp()
        claude._resting = None
        self.addCleanup(setattr, claude, "_resting", None)

    def claude_friday(self, replies: list, db=None, backup: FakeModel | None = None) -> tuple[Friday, FakeClaude]:
        fake = FakeClaude(replies)
        conversations = Conversations(db or self.tmp / "conversations.db")
        self.addCleanup(conversations.close)
        fallback = (backup, agent.model_settings("gpt-5")) if backup else None
        model = claude.ClaudeModel(MODEL, stable_prefix=VOICE, client=fake, fallback=fallback)
        return Friday(conversations, model=model), fake

    def test_out_of_credit_she_still_answers_and_tries_claude_again_later(self) -> None:
        broke = bad_request("Error code: 400 - Your credit balance is too low to access the Anthropic API.")
        backup = FakeModel([[text("在。")], [text("还在。")], [text("这句又是 Claude 之前的备用。")]])
        friday, fake = self.claude_friday([reply(think("s1"), say("好。")), broke, reply(say("回来了。"))], backup=backup)
        cid = friday.conversations.create()
        self.assertEqual(collect(friday.turn(cid, "早"))[-1]["reply"], "好。")

        done = collect(friday.turn(cid, "在吗"))[-1]
        self.assertEqual(done["reply"], "在。")  # 不再是一条红色的报错
        self.assertEqual(claude.issue(), "Anthropic API 额度不够")
        with patch.object(agent, "_active_model", MODEL):
            self.assertEqual(agent.answering_model(), "gpt-5")
        # 备用的看不到 Claude 的思考块
        self.assertNotIn("anthropic", str(backup.inputs[-1]))

        # 歇着的这几分钟不再先撞一次 Claude
        self.assertEqual(collect(friday.turn(cid, "还在吗"))[-1]["reply"], "还在。")
        self.assertEqual(len(fake.requests), 2)

        claude._resting = None  # 几分钟过去了
        self.assertEqual(collect(friday.turn(cid, "现在呢"))[-1]["reply"], "回来了。")
        self.assertEqual(len(fake.requests), 3)

    def test_without_a_backup_the_problem_is_not_hidden(self) -> None:
        friday, _ = self.claude_friday([bad_request("Your credit balance is too low to access the Anthropic API.")])
        cid = friday.conversations.create()
        with self.assertRaises(anthropic.BadRequestError):
            collect(friday.turn(cid, "在吗"))

    def test_a_plain_answer_streams_and_the_request_is_cache_friendly(self) -> None:
        friday, fake = self.claude_friday([reply(think("s1"), say("在。今天下午三点见导师。"))])
        cid = friday.conversations.create()
        events = collect(friday.turn(cid, "在吗"))

        self.assertEqual("".join(e["text"] for e in of_type(events, "delta")), "在。今天下午三点见导师。")
        self.assertEqual(events[-1]["reply"], "在。今天下午三点见导师。")
        request = fake.requests[0]
        self.assertEqual(request["model"], MODEL)
        self.assertEqual(request["thinking"], {"type": "adaptive"})
        self.assertEqual(request["output_config"], {"effort": "low"})
        self.assertEqual(request["cache_control"], {"type": "ephemeral"})
        self.assertEqual((request["betas"], request["fallbacks"]), ([claude.FALLBACK_BETA], "default"))
        self.assertNotIn("temperature", request)
        # 她的性格那段单独一块、打了缓存点；每句都变的时间日历跟在后面
        self.assertEqual(request["system"][0], {"type": "text", "text": VOICE, "cache_control": {"type": "ephemeral"}})
        self.assertNotIn("cache_control", request["system"][1])
        self.assertIn("send_email", [t["name"] for t in request["tools"]])
        self.assertEqual(request["messages"], [{"role": "user", "content": [{"type": "text", "text": "在吗"}]}])

    def test_thinking_comes_back_unchanged_within_the_sentence_and_not_after(self) -> None:
        friday, fake = self.claude_friday([
            reply(think("s1"), use("search_emails", "toolu_1", query="FYP", top=5), stop="tool_use"),
            reply(think("s2"), say("导师让你明天带上进度。")),
            reply(say("就是 mock-mail-001 那封。")),
        ])
        cid = friday.conversations.create()
        collect(friday.turn(cid, "导师最近说了什么？"))

        second = fake.requests[1]
        assistant, results = second["messages"][1], second["messages"][2]
        self.assertEqual(assistant, {"role": "assistant", "content": [
            think("s1"), use("search_emails", "toolu_1", query="FYP", top=5)]})
        self.assertEqual(results["content"][0]["tool_use_id"], "toolu_1")
        self.assertIn("mock-mail-001", results["content"][0]["content"])

        collect(friday.turn(cid, "那是哪封邮件？"))
        third = fake.requests[2]
        # 上一句的思考块是在另一份系统提示下想的：不带；说过的话和工具结果都在
        self.assertEqual(blocks(third, "thinking"), [])
        self.assertEqual([b["id"] for b in blocks(third, "tool_use")], ["toolu_1"])
        self.assertEqual(third["messages"][-1], {"role": "user", "content": [{"type": "text", "text": "那是哪封邮件？"}]})
        self.assertIn(say("导师让你明天带上进度。"), third["messages"][-2]["content"])

    def test_confirming_continues_the_same_thought(self) -> None:
        friday, fake = self.claude_friday([
            reply(think("s1"), use("send_email", "toolu_m", **MAIL), stop="tool_use"),
            reply(say("发了。")),
        ])
        cid = friday.conversations.create()
        self.assertTrue(collect(friday.turn(cid, "给导师发个进度邮件"))[-1]["needs_confirm"])
        self.assertEqual(self.sent_mail(), [])

        done = collect(friday.turn(cid, "确认"))[-1]
        self.assertEqual(done["reply"], "发了。")
        self.assertEqual(len(self.sent_mail()), 1)
        self.assertEqual(blocks(fake.requests[1], "thinking"), [think("s1")])
        self.assertEqual(blocks(fake.requests[1], "tool_result")[0]["tool_use_id"], "toolu_m")

    def test_after_a_restart_a_stale_thought_is_dropped_and_asked_again(self) -> None:
        db = self.tmp / "restart.db"
        before, _ = self.claude_friday([reply(think("s1"), use("send_email", "toolu_m", **MAIL), stop="tool_use")], db)
        cid = before.conversations.create()
        collect(before.turn(cid, "发邮件"))

        stale = bad_request("messages.1.content.0: Invalid `signature` in `thinking` block. "
                            "The block is bound to a different conversation.")
        after, fake = self.claude_friday([stale, reply(say("发了。"))], db)
        done = collect(after.turn(cid, "确认"))[-1]

        self.assertEqual(done["reply"], "发了。")
        self.assertEqual(len(self.sent_mail()), 1)
        self.assertEqual(blocks(fake.requests[0], "thinking"), [think("s1")])  # 存盘再读回来还是原样
        self.assertEqual(blocks(fake.requests[1], "thinking"), [])
        self.assertEqual([b["id"] for b in blocks(fake.requests[1], "tool_use")], ["toolu_m"])

    def test_a_bug_in_the_request_is_not_papered_over(self) -> None:
        friday, fake = self.claude_friday([bad_request("max_tokens: too large")], backup=FakeModel([]))
        cid = friday.conversations.create()
        with self.assertRaises(anthropic.BadRequestError):
            collect(friday.turn(cid, "在吗"))
        self.assertEqual(len(fake.requests), 1)


class TranslationTests(unittest.TestCase):
    def test_a_declined_turn_says_so_plainly(self) -> None:
        out = claude.to_output(reply(say("我先"), stop="refusal"))
        self.assertEqual([o.content[0].text for o in out], [claude.REFUSED])

    def test_after_a_fallback_only_text_from_before_the_switch_is_kept(self) -> None:
        out = claude.to_output(reply(
            say("我先看"), think("s1"), use("search_emails", "toolu_9", query="x"), FALLBACK,
            think("s2"), say("导师让你明天带上进度。"), model="claude-opus-5",
        ))
        self.assertEqual([type(o) for o in out], [ResponseOutputMessage, ResponseReasoningItem, ResponseOutputMessage])
        self.assertEqual(claude.thinking_block(out[1].model_dump()), think("s2"))

    def test_a_tool_call_cut_off_by_max_tokens_is_not_run(self) -> None:
        out = claude.to_output(reply(use("send_email", "toolu_x", to="a"), stop="max_tokens"))
        self.assertFalse(any(isinstance(o, ResponseFunctionToolCall) for o in out))
        self.assertEqual(out[-1].content[0].text, claude.CUT_OFF)

    def test_history_is_made_valid_without_dropping_what_he_said(self) -> None:
        messages = claude.to_messages([
            {"role": "assistant", "content": "早。今天两件事。"},  # 开场那句：她先开口
            {"role": "user", "content": "好"},
            {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "gAAAA-openai"},
            {"type": "function_call", "call_id": "toolu_lost", "name": "send_email", "arguments": "{}"},
            {"role": "user", "content": "算了"},
        ])
        self.assertEqual(messages[0], {"role": "user", "content": [{"type": "text", "text": claude.OPENED}]})
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[2], {"role": "user", "content": [{"type": "text", "text": "好"}]})
        self.assertEqual(messages[3]["content"], [{"type": "tool_use", "id": "toolu_lost", "name": "send_email", "input": {}}])
        lost, said = messages[4]["content"]
        self.assertEqual((lost["tool_use_id"], lost["is_error"]), ("toolu_lost", True))
        self.assertEqual(said, {"type": "text", "text": "算了"})

    def test_openai_never_sees_what_claude_left_behind(self) -> None:
        thought = claude.to_output(reply(think("s1"), say("好")))
        items = [o.model_dump() for o in thought] + [{"role": "user", "content": "嗯"}]
        cleaned = claude.for_openai(items)
        self.assertEqual(len(cleaned), 2)
        self.assertNotIn("id", cleaned[0])
        self.assertIsNone(claude.for_openai([{"role": "user", "content": "嗯"}]))


class ChoosingTheBrainTests(unittest.TestCase):
    def tearDown(self) -> None:
        agent._active_model = agent.DEFAULT_MODEL

    def test_putting_the_key_in_is_all_it_takes(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-x", "FRIDAY_MODEL": ""}):
            self.assertEqual(config.default_model(), "claude-opus-5-5")
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-x", "FRIDAY_MODEL": "claude-sonnet-5-5"}):
            self.assertEqual(config.default_model(), "claude-sonnet-5-5")
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "FRIDAY_MODEL": "", "OPENAI_MODEL": "gpt-5"}):
            self.assertEqual(config.default_model(), "gpt-5")

    def test_claude_gets_effort_and_her_voice_is_the_cached_part(self) -> None:
        brain = agent.brain("claude-opus-5-5")
        self.assertIsInstance(brain, claude.ClaudeModel)
        self.assertEqual(brain.stable_prefix, VOICE)
        backup, backup_settings = brain.fallback  # GPT-5 随时顶上
        self.assertEqual(backup.model, "gpt-5")
        self.assertEqual(backup_settings.verbosity, "low")
        settings = agent.model_settings("claude-opus-5-5")
        self.assertEqual(settings.reasoning.effort, agent.REASONING_EFFORT)
        self.assertIsNone(settings.temperature)

    def test_a_key_that_does_not_work_falls_back_to_gpt5(self) -> None:
        client = MagicMock()
        client.models.retrieve.side_effect = anthropic.AuthenticationError(
            "invalid x-api-key", response=MagicMock(status_code=401), body=None)
        with patch.object(agent, "DEFAULT_MODEL", "claude-opus-5-5"), \
                patch.object(agent, "_active_model", "claude-opus-5-5"), \
                patch.object(anthropic, "Anthropic", return_value=client):
            self.assertEqual(agent.verify_model(), agent.CLAUDE_FALLBACK)

    def test_network_trouble_keeps_claude(self) -> None:
        client = MagicMock()
        client.models.retrieve.side_effect = RuntimeError("offline")
        with patch.object(agent, "DEFAULT_MODEL", "claude-opus-5-5"), \
                patch.object(agent, "_active_model", "claude-opus-5-5"), \
                patch.object(anthropic, "Anthropic", return_value=client):
            self.assertEqual(agent.verify_model(), "claude-opus-5-5")

    def test_short_names_come_from_the_same_brain(self) -> None:
        with patch.object(agent, "_active_model", "claude-opus-5-5"), \
                patch.object(claude, "ask", return_value='好的：{"FYP meeting with mentor": "见导师"}') as ask:
            self.assertEqual(names.name_batch(["FYP meeting with mentor"]), {"FYP meeting with mentor": "见导师"})
        self.assertEqual(ask.call_args.args[0], "claude-opus-5-5")

    def test_a_declined_naming_request_names_nothing(self) -> None:
        client = MagicMock()
        client.beta.messages.create.return_value = reply(stop="refusal")
        with patch.object(anthropic, "Anthropic", return_value=client):
            self.assertEqual(claude.ask("claude-opus-5-5", "x"), "")
        sent = client.beta.messages.create.call_args.kwargs
        self.assertEqual((sent["betas"], sent["fallbacks"]), ([claude.FALLBACK_BETA], "default"))


if __name__ == "__main__":
    unittest.main()
