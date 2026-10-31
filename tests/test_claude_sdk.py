"""真的 anthropic SDK，对着本机一个按脚本回话的「Claude」：请求真的走 HTTP，回复真的是 SSE、由 SDK 解析。

假客户端测不到的这里测：参数名和 beta 头、流式事件、思考块签名原样带回、重启后对不上时的重试、
带图的请求、额度用完换备用、被拒的那一句。不联网，只用 127.0.0.1。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import patch

import anthropic

from tests.fake_model import FakeModel, text
from tests.helpers import SandboxTestCase

import src.agent as agent
from src import claude, uploads
from src.agent import VOICE, Friday
from src.conversation import Conversations

MAIL = {"to": "mentor.example@manchester.ac.uk", "subject": "FYP update", "body": "Hi, here is my update.", "cc": ""}
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def message(*blocks: dict, stop: str = "end_turn", model: str = "claude-opus-5-5") -> dict:
    return {"id": "msg_e2e", "type": "message", "role": "assistant", "model": model, "content": list(blocks),
            "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 50, "output_tokens": 10, "cache_read_input_tokens": 3000,
                      "cache_creation_input_tokens": 0}}


def think(sig: str) -> dict:
    return {"type": "thinking", "thinking": "", "signature": sig}


def say(words: str) -> dict:
    return {"type": "text", "text": words}


def use(name: str, ident: str, **arguments: Any) -> dict:
    return {"type": "tool_use", "id": ident, "name": name, "input": arguments}


def sse(msg: dict) -> bytes:
    """一条完整的消息 → Messages API 的 SSE 事件（和真的一样：先开头、一块一块、最后收尾）。"""
    events = [{"type": "message_start", "message": {**msg, "content": [], "stop_reason": None,
                                                     "usage": {**msg["usage"], "output_tokens": 1}}}]
    for i, block in enumerate(msg["content"]):
        if block["type"] == "thinking":
            events += [{"type": "content_block_start", "index": i, "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
                       {"type": "content_block_delta", "index": i, "delta": {"type": "signature_delta", "signature": block["signature"]}}]
        elif block["type"] == "tool_use":
            events += [{"type": "content_block_start", "index": i, "content_block": {**block, "input": {}}},
                       {"type": "content_block_delta", "index": i, "delta": {"type": "input_json_delta",
                                                                             "partial_json": json.dumps(block["input"], ensure_ascii=False)}}]
        else:
            events += [{"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}}]
            for k in range(0, len(block["text"]), 5):
                events.append({"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": block["text"][k:k + 5]}})
        events.append({"type": "content_block_stop", "index": i})
    events += [{"type": "message_delta", "delta": {"stop_reason": msg["stop_reason"], "stop_sequence": None},
                "usage": {"output_tokens": msg["usage"]["output_tokens"]}},
               {"type": "message_stop"}]
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events).encode()


def refused(text_: str) -> tuple[int, dict]:
    return 400, {"type": "error", "error": {"type": "invalid_request_error", "message": text_}}


class StandIn:
    """本机的「Claude」：按脚本一条条回；记下收到的每个请求（路径、头、正文）。"""

    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.seen: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                outer.seen.append({"path": self.path, "headers": dict(self.headers), "body": body})
                reply = outer.replies.pop(0)
                if isinstance(reply, tuple):  # (状态码, 错误正文)
                    status, payload = reply
                    data, kind = json.dumps(payload).encode(), "application/json"
                elif body.get("stream"):
                    status, data, kind = 200, sse(reply), "text/event-stream"
                else:
                    status, data, kind = 200, json.dumps(reply).encode(), "application/json"
                self.send_response(status)
                self.send_header("content-type", kind)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def blocks(request: dict, kind: str) -> list[dict]:
    return [b for m in request["body"]["messages"] for b in m["content"] if b.get("type") == kind]


async def talk(friday: Friday, cid: str, words: str, **kwargs: Any) -> dict:
    events = [e async for e in friday.turn(cid, words, **kwargs)]
    return events[-1]


class RealSdkTests(SandboxTestCase):
    def setUp(self) -> None:
        super().setUp()
        claude._resting = None
        self.addCleanup(setattr, claude, "_resting", None)
        proxy = patch.dict(os.environ, {"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
        proxy.start()
        self.addCleanup(proxy.stop)

    def stand_in(self, replies: list) -> StandIn:
        server = StandIn(replies)
        self.addCleanup(server.close)
        return server

    def friday(self, server: StandIn, backup: FakeModel | None = None, db: str = "c.db") -> Friday:
        client = anthropic.AsyncAnthropic(api_key="sk-ant-test", base_url=server.url, max_retries=0)
        fallback = (backup, agent.model_settings("gpt-5")) if backup else None
        model = claude.ClaudeModel("claude-opus-5-5", stable_prefix=VOICE, client=client, fallback=fallback)
        conversations = Conversations(self.tmp / db)
        self.addCleanup(conversations.close)
        return Friday(conversations, model=model)

    def test_a_tool_round_then_a_follow_up_over_real_http(self) -> None:
        server = self.stand_in([
            message(think("sigA"), use("search_emails", "toolu_1", query="FYP", top=5), stop="tool_use"),
            message(think("sigB"), say("导师让你明天带上进度。\n\n就是周三那封。")),
            message(say("👍")),
        ])
        friday = self.friday(server)

        async def scenario() -> tuple[dict, dict]:
            cid = friday.conversations.create()
            first = await talk(friday, cid, "导师最近说了什么？")
            second = await talk(friday, cid, "好的")
            return first, second

        first, second = asyncio.run(scenario())
        self.assertEqual(first["reply"], "导师让你明天带上进度。\n\n就是周三那封。")
        self.assertEqual((second["reaction"], second["reply"]), ("👍", ""))

        opening, after_tool, next_turn = server.seen
        self.assertEqual(opening["path"], "/v1/messages")
        self.assertEqual(opening["headers"].get("anthropic-beta"), claude.FALLBACK_BETA)
        self.assertEqual(opening["body"]["fallbacks"], "default")
        self.assertTrue(opening["body"]["stream"])
        self.assertEqual(opening["body"]["system"][0]["cache_control"], {"type": "ephemeral"})
        # 同一句里：思考块原样带回，工具结果跟在后面
        self.assertEqual(blocks(after_tool, "thinking"), [think("sigA")])
        self.assertEqual(blocks(after_tool, "tool_use")[0]["input"], {"query": "FYP", "top": 5})
        self.assertEqual(blocks(after_tool, "tool_result")[0]["tool_use_id"], "toolu_1")
        # 下一句：上一句的思考块不带，说过的话都在
        self.assertEqual(blocks(next_turn, "thinking"), [])
        self.assertEqual(next_turn["body"]["messages"][-1]["content"], [{"type": "text", "text": "好的"}])

    def test_confirming_after_a_restart_drops_the_stale_thought_and_sends(self) -> None:
        server = self.stand_in([
            message(think("sigM"), use("send_email", "toolu_m", **MAIL), stop="tool_use"),
            refused("messages.1.content.0: Invalid `signature` in `thinking` block. The block is bound to a different conversation."),
            message(say("发了。")),
        ])

        async def scenario() -> dict:
            before = self.friday(server, db="shared.db")
            cid = before.conversations.create()
            asked = await talk(before, cid, "给导师发个进度")
            self.assertTrue(asked["needs_confirm"])
            after = self.friday(server, db="shared.db")  # 云上重启了
            return await talk(after, cid, "发")

        done = asyncio.run(scenario())
        self.assertEqual(done["reply"], "发了。")
        self.assertEqual(len(self.sent_mail()), 1)
        stale, retried = server.seen[1], server.seen[2]
        self.assertEqual(blocks(stale, "thinking"), [think("sigM")])
        self.assertEqual(blocks(retried, "thinking"), [])
        self.assertEqual(blocks(retried, "tool_result")[0]["tool_use_id"], "toolu_m")

    def test_a_picture_goes_out_as_an_image_block_before_the_words(self) -> None:
        server = self.stand_in([message(say("这是 Lab 3 的截止时间。"))])
        friday = self.friday(server)
        picture = uploads.save(PNG)

        async def scenario() -> dict:
            return await talk(friday, friday.conversations.create(), "这是什么", images=[picture["id"]])

        self.assertEqual(asyncio.run(scenario())["reply"], "这是 Lab 3 的截止时间。")
        his = server.seen[0]["body"]["messages"][0]["content"]
        self.assertEqual([b["type"] for b in his], ["image", "text"])
        self.assertEqual(his[0]["source"]["type"], "base64")
        self.assertEqual(base64.b64decode(his[0]["source"]["data"]), PNG)

    def test_out_of_credit_the_backup_answers_and_claude_is_skipped_for_a_while(self) -> None:
        server = self.stand_in([refused("Your credit balance is too low to access the Anthropic API.")])
        backup = FakeModel([[text("在。")], [text("还在。")]])
        friday = self.friday(server, backup=backup)

        async def scenario() -> tuple[dict, dict]:
            cid = friday.conversations.create()
            return await talk(friday, cid, "在吗"), await talk(friday, cid, "还在吗")

        first, second = asyncio.run(scenario())
        self.assertEqual((first["reply"], second["reply"]), ("在。", "还在。"))
        self.assertEqual(len(server.seen), 1)  # 歇着的这几分钟不再先撞一次 Claude
        self.assertEqual(claude.issue(), "Anthropic API 额度不够")

    def test_a_declined_turn_says_one_plain_line(self) -> None:
        server = self.stand_in([message(stop="refusal")])
        friday = self.friday(server)

        async def scenario() -> dict:
            return await talk(friday, friday.conversations.create(), "随便问一句")

        self.assertEqual(asyncio.run(scenario())["reply"], claude.REFUSED)

    def test_short_names_through_the_real_sdk(self) -> None:
        server = self.stand_in([message(say('{"FYP meeting with mentor": "见导师"}'))])
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test", "ANTHROPIC_BASE_URL": server.url}):
            said = claude.ask("claude-opus-5-5", "起短名")
        self.assertEqual(json.loads(said), {"FYP meeting with mentor": "见导师"})
        self.assertNotIn("stream", server.seen[0]["body"])
        self.assertEqual(server.seen[0]["body"]["fallbacks"], "default")
