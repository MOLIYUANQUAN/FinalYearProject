"""Claude 当 Friday 的脑子：对话、工具、确认、撤销还是 Agents SDK 那一套，这里只把「问模型」这一步翻成
Anthropic Messages API（官方 anthropic SDK）。

- 文字边生成边给页面；这一步要调的工具在结尾一次交回给 Agents SDK。
- 思考块原样带回，但只带「他这一句」里的：系统提示每句都重算（时间、日历、待办、记忆），
  更早那几句的思考块是在另一份系统提示下想的，带回去 API 会当成改过历史拒掉。
- 缓存：工具和她的性格（VOICE）几乎不变，打一个缓存点；这一句里的工具往返交给自动缓存。
- 安全分类器误拦：服务端按类别换个模型重答（fallbacks: "default"）；整条链都拒了就照实说一句。
- Claude 这会儿用不了（额度用完、key 失效、超限、Anthropic 出故障）：这一句交给备用的脑子（GPT-5）答，
  接下来几分钟都先用它，过后再试 Claude——不把报错甩给他。
- 工具参数不开 eager_input_streaming：页面从不显示生成中的参数，开了只会少掉服务端的校验。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import anthropic
from agents import FunctionTool, Model, ModelResponse, ModelSettings, Usage
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseReasoningItem,
    ResponseTextDeltaEvent,
    ResponseUsage,
)
from openai.types.responses.response_usage import InputTokensDetails, OutputTokensDetails

MAX_TOKENS = 64000
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# 被安全分类器拦下时服务端换模型重答；"default" 只有这几个型号收
FALLBACK_BETA = "server-side-fallback-2026-07-01"
WITH_FALLBACKS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-fable-5", "claude-sonnet-5-5"}
REFUSED = "这句我这边答不了。换个说法再说一次。"
CUT_OFF = "说到一半断了，再说一次。"
# 开场那句是她先说的（存成助手消息）；Messages API 要第一条是他说的
OPENED = "（他打开了 Friday）"
UNANSWERED = "这一步没做。"
THINKING = {"thinking", "redacted_thinking"}
# 思考块装在 reasoning 项里走完这一句：encrypted_content = {"anthropic": 原样的块}
_KEY = "anthropic"
MESSAGE_ID = "msg_claude_"
# 每句都新建一个 ClaudeModel；连接（TLS）在同一个事件循环里共用
_shared: tuple[int, Any] | None = None
# Claude 用不了时歇多久再试；歇着的时候直接让备用的答，不每句先撞一次墙
REST_S = 300
_resting: tuple[float, str] | None = None


def issue() -> str | None:
    """Claude 正歇着的原因（/api/health 里看得到）；好好的就是 None。"""
    return _resting[1] if _resting and time.monotonic() < _resting[0] else None


def _unavailable(exc: Exception) -> str | None:
    """是不是「Claude 这边暂时用不了」：是就说个原因；不是（那是代码的错）返回 None，照常抛出。"""
    if isinstance(exc, anthropic.BadRequestError):
        text = str(exc)
        if "credit balance" in text:
            return "Anthropic API 额度不够"
        if "usage limits" in text:
            return "到了 Anthropic 的用量上限"
        return None
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return "Anthropic key 不能用"
    if isinstance(exc, anthropic.NotFoundError):
        return "这个 Claude 型号用不了"
    if isinstance(exc, anthropic.RateLimitError):
        return "超了 Anthropic 的速率或额度上限"
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500:
        return "Anthropic 那边出故障了"
    if isinstance(exc, anthropic.APIConnectionError):
        return "连不上 Anthropic"
    return None


def _get(item: Any, key: str, default: Any = None) -> Any:
    return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)


def thinking_block(item: Any) -> dict[str, Any] | None:
    """这一项是 Claude 的思考块就还原成原样的块；OpenAI 的推理项、别的项都返回 None。"""
    if _get(item, "type") != "reasoning":
        return None
    raw = _get(item, "encrypted_content")
    try:
        data = json.loads(raw) if isinstance(raw, str) else None
    except json.JSONDecodeError:
        return None
    block = data.get(_KEY) if isinstance(data, dict) else None
    return block if isinstance(block, dict) and block.get("type") in THINKING else None


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for part in content or []:
        kind = _get(part, "type")
        if kind in {"input_text", "output_text", "text"}:
            parts.append(_get(part, "text") or "")
        elif kind == "refusal":
            parts.append(_get(part, "refusal") or "")
    return "".join(parts)


def _is_user(item: Any) -> bool:
    return (_get(item, "type") or "message") == "message" and _get(item, "role") == "user"


# ---- Agents SDK 的输入项 → messages ----


def to_messages(items: str | list[Any]) -> list[dict[str, Any]]:
    """顺序不变，相邻同一方的合成一条；思考块只留他最后一句之后的。"""
    if isinstance(items, str):
        items = [{"role": "user", "content": items}]
    items = list(items)
    turn = max((i for i, item in enumerate(items) if _is_user(item)), default=-1)
    messages: list[dict[str, Any]] = []

    def add(role: str, block: dict[str, Any]) -> None:
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"].append(block)
        else:
            messages.append({"role": role, "content": [block]})

    for index, item in enumerate(items):
        kind = _get(item, "type") or "message"
        if kind == "message":
            text = _text(_get(item, "content"))
            if text.strip():
                add("assistant" if _get(item, "role") == "assistant" else "user", {"type": "text", "text": text})
        elif kind == "reasoning":
            block = thinking_block(item)
            if block and index > turn:
                add("assistant", block)
        elif kind == "function_call":
            try:
                args = json.loads(_get(item, "arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            add("assistant", {"type": "tool_use", "id": _get(item, "call_id"), "name": _get(item, "name"),
                              "input": args if isinstance(args, dict) else {}})
        elif kind == "function_call_output":
            output = _get(item, "output")
            text = output if isinstance(output, str) else _text(output) if isinstance(output, list) else json.dumps(
                output, ensure_ascii=False)
            result: dict[str, Any] = {"type": "tool_result", "tool_use_id": _get(item, "call_id")}
            if text:
                result["content"] = text
            add("user", result)
    return _repair(messages)


def _merge(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        if not message["content"]:
            continue
        if out and out[-1]["role"] == message["role"]:
            out[-1] = {"role": message["role"], "content": out[-1]["content"] + message["content"]}
        else:
            out.append({"role": message["role"], "content": list(message["content"])})
    return out


def _repair(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """让历史合 API 的规矩：每个工具调用后面紧跟它的结果、结果排在他那条话的最前面、第一条是他说的。

    只补不删他说过的话；同一份历史每次补得一模一样，不会让前缀变了。
    """
    out: list[dict[str, Any]] = []
    asked: list[str] = []  # 上一条助手消息里调了、还没交结果的
    for message in _merge(messages):
        if message["role"] == "assistant":
            if asked:
                out.append(_answers(asked))
            asked = [b["id"] for b in message["content"] if b.get("type") == "tool_use"]
            out.append(message)
            continue
        results = [b for b in message["content"] if b.get("type") == "tool_result" and b.get("tool_use_id") in asked]
        rest = [b for b in message["content"] if b.get("type") != "tool_result"]
        answered = {b["tool_use_id"] for b in results}
        missing = [i for i in asked if i not in answered]
        asked = []
        content = results + _answers(missing)["content"] + rest
        if content:
            out.append({"role": "user", "content": content})
    if asked:
        out.append(_answers(asked))
    out = _merge(out)
    if out and out[0]["role"] == "assistant":
        out.insert(0, {"role": "user", "content": [{"type": "text", "text": OPENED}]})
    return out


def _answers(ids: list[str]) -> dict[str, Any]:
    return {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": i, "content": UNANSWERED, "is_error": True} for i in ids
    ]}


def without_thinking(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _merge([
        {"role": m["role"], "content": [b for b in m["content"] if b.get("type") not in THINKING]} for m in messages
    ])


def to_system(instructions: str | None, stable: str = "") -> list[dict[str, Any]]:
    """系统提示分两块：不变的那段（她的性格）打缓存点；每句都变的（时间、日历、待办）跟在后面。"""
    if not instructions:
        return []
    rest = instructions[len(stable):].strip() if stable and instructions.startswith(stable) else ""
    if rest:
        return [{"type": "text", "text": stable, "cache_control": {"type": "ephemeral"}}, {"type": "text", "text": rest}]
    return [{"type": "text", "text": instructions, "cache_control": {"type": "ephemeral"}}]


def to_tools(tools: list[Any]) -> list[dict[str, Any]]:
    specs = []
    for tool in tools or []:
        if not isinstance(tool, FunctionTool):
            print(f"[WARN] claude: skipping non-function tool {getattr(tool, 'name', tool)!r}")
            continue
        spec: dict[str, Any] = {"name": tool.name, "input_schema": tool.params_json_schema}
        if tool.description:
            spec["description"] = tool.description
        specs.append(spec)
    return specs


def _effort(settings: ModelSettings) -> str:
    wanted = getattr(getattr(settings, "reasoning", None), "effort", None)
    return wanted if wanted in EFFORTS else "low"


# ---- 回复 → Agents SDK 的输出项 ----


def _message(text: str) -> ResponseOutputMessage:
    return ResponseOutputMessage(
        id=f"{MESSAGE_ID}{uuid.uuid4().hex[:12]}", type="message", role="assistant", status="completed",
        content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
    )


def to_output(message: Any) -> list[Any]:
    """思考块 → reasoning 项（原样装着），文字 → 消息，工具调用 → function_call。

    中途被拦下换了模型：换之前那段只留文字（官方的回传规矩），换模型的标记本身不要。
    """
    if message.stop_reason == "refusal":
        return [_message(REFUSED)]
    blocks = list(message.content)
    switch = max((i for i, b in enumerate(blocks) if b.type == "fallback"), default=-1)
    out: list[Any] = []
    for index, block in enumerate(blocks):
        if block.type == "fallback" or (index < switch and block.type != "text"):
            continue
        if block.type in THINKING:
            out.append(ResponseReasoningItem(
                id=f"rs_claude_{uuid.uuid4().hex[:12]}", type="reasoning", summary=[],
                encrypted_content=json.dumps({_KEY: block.to_dict()}, ensure_ascii=False),
            ))
        elif block.type == "text" and block.text.strip():
            out.append(_message(block.text))
        elif block.type == "tool_use" and message.stop_reason != "max_tokens":
            # 写到一半被截断的调用不能跑
            out.append(ResponseFunctionToolCall(
                id=f"fc_{block.id}", call_id=block.id, type="function_call", name=block.name,
                arguments=json.dumps(block.input, ensure_ascii=False), status="completed",
            ))
    if message.stop_reason == "max_tokens" and not any(isinstance(o, ResponseOutputMessage) for o in out):
        out.append(_message(CUT_OFF))
    return out


def to_usage(usage: Any) -> ResponseUsage:
    read = getattr(usage, "cache_read_input_tokens", None) or 0
    written = getattr(usage, "cache_creation_input_tokens", None) or 0
    inputs = (usage.input_tokens or 0) + read + written
    outputs = usage.output_tokens or 0
    return ResponseUsage(
        input_tokens=inputs, output_tokens=outputs, total_tokens=inputs + outputs,
        input_tokens_details=InputTokensDetails(cached_tokens=read, cache_write_tokens=written),
        output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
    )


def _bound_elsewhere(exc: anthropic.BadRequestError) -> bool:
    text = str(exc)
    return "thinking" in text and ("signature" in text or "bound to a different conversation" in text)


class ClaudeModel(Model):
    """Agents SDK 的 Model：流式问 Claude，把结果翻回 Responses 的样子。

    fallback = (备用的 Model, 它的 ModelSettings)：Claude 用不了时由它来答。
    """

    def __init__(self, name: str, *, stable_prefix: str = "", client: Any = None,
                 fallback: tuple[Model, ModelSettings] | None = None) -> None:
        self.name = name
        self.stable_prefix = stable_prefix
        self._client = client
        self.fallback = fallback

    @property
    def client(self) -> Any:
        global _shared
        if self._client is not None:
            return self._client
        loop = id(asyncio.get_running_loop())
        if _shared is None or _shared[0] != loop:
            _shared = (loop, anthropic.AsyncAnthropic())
        return _shared[1]

    def request(self, instructions: str | None, input: Any, settings: ModelSettings, tools: list[Any]) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.name,
            "max_tokens": settings.max_tokens or MAX_TOKENS,
            "messages": to_messages(input),
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": _effort(settings)},
            "cache_control": {"type": "ephemeral"},
        }
        system = to_system(instructions, self.stable_prefix)
        if system:
            params["system"] = system
        specs = to_tools(tools)
        if specs:
            params["tools"] = specs
        if self.name in WITH_FALLBACKS:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    async def stream_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs,
                              tracing, **kwargs) -> AsyncIterator[Any]:
        global _resting
        args = (system_instructions, input, tools, output_schema, handoffs, tracing)
        if self.fallback and issue():
            async for event in self._backup(*args, **kwargs):
                yield event
            return
        try:
            async for event in self._claude(system_instructions, input, model_settings, tools):
                yield event
        except Exception as exc:  # noqa: BLE001 — 只接「Claude 暂时用不了」，别的照常抛
            reason = _unavailable(exc) if self.fallback else None
            if reason is None:
                raise
            _resting = (time.monotonic() + REST_S, reason)
            print(f"[WARN] claude unavailable ({reason}): {exc}; answering with the backup for {REST_S // 60} min")
            async for event in self._backup(*args, **kwargs):
                yield event

    async def _backup(self, system_instructions, input, tools, output_schema, handoffs, tracing,
                      **kwargs) -> AsyncIterator[Any]:
        model, settings = self.fallback
        items = input if isinstance(input, str) else (for_openai(input) or input)
        async for event in model.stream_response(system_instructions, items, settings, tools, output_schema,
                                                 handoffs, tracing, **kwargs):
            yield event

    async def _claude(self, system_instructions, input, model_settings, tools) -> AsyncIterator[Any]:
        params = self.request(system_instructions, input, model_settings, tools)
        seq = 0
        message = None
        for attempt in (1, 2):
            try:
                async with self.client.beta.messages.stream(**params) as stream:
                    async for event in stream:
                        if event.type == "text" and event.text:
                            yield ResponseTextDeltaEvent.model_construct(
                                type="response.output_text.delta", delta=event.text, item_id="", output_index=0,
                                content_index=0, sequence_number=seq, logprobs=[],
                            )
                            seq += 1
                    message = await stream.get_final_message()
                break
            except anthropic.BadRequestError as exc:
                # 思考块对不上这份对话（比如重启后才点确认，系统提示已经重算）：官方的恢复办法是去掉思考块再问一次
                if attempt == 1 and _bound_elsewhere(exc):
                    print(f"[WARN] claude: thinking blocks no longer match, retrying without them: {exc}")
                    params["messages"] = without_thinking(params["messages"])
                    continue
                raise
        if message.model != self.name:
            print(f"[INFO] claude: {self.name} declined; answered by {message.model}")
        response = Response.model_construct(
            id=message.id, object="response", created_at=time.time(), model=message.model,
            output=to_output(message), usage=to_usage(message.usage), tools=[], tool_choice="auto",
            parallel_tool_calls=True,
        )
        yield ResponseCompletedEvent.model_construct(type="response.completed", response=response, sequence_number=seq)

    async def get_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs,
                           tracing, **kwargs) -> ModelResponse:
        response = None
        async for event in self.stream_response(system_instructions, input, model_settings, tools, output_schema,
                                                handoffs, tracing, **kwargs):
            if isinstance(event, ResponseCompletedEvent):
                response = event.response
        usage = response.usage
        return ModelResponse(
            output=response.output,
            usage=Usage(requests=1, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                        total_tokens=usage.total_tokens, input_tokens_details=usage.input_tokens_details,
                        output_tokens_details=usage.output_tokens_details),
            response_id=response.id,
        )


def ask(model: str, prompt: str) -> str:
    """一问一答的小事（给日历标题起短名）：只要文字，被拦下就当没答。"""
    extra: dict[str, Any] = {"betas": [FALLBACK_BETA], "fallbacks": "default"} if model in WITH_FALLBACKS else {}
    message = anthropic.Anthropic().beta.messages.create(
        model=model, max_tokens=16000, output_config={"effort": "low"},
        messages=[{"role": "user", "content": prompt}], **extra,
    )
    if message.stop_reason == "refusal":
        return ""
    return "".join(block.text for block in message.content if block.type == "text")


def for_openai(items: list[Any]) -> list[Any] | None:
    """又换回 OpenAI 时：Claude 的思考块它读不懂，去掉；Claude 那边起的 id 也不带过去。没什么要改就返回 None。"""
    out, changed = [], False
    for item in items:
        if thinking_block(item) is not None:
            changed = True
            continue
        ident = item.get("id") if isinstance(item, dict) else None
        if isinstance(ident, str) and ident.startswith((MESSAGE_ID, "fc_toolu_")):
            item = {k: v for k, v in item.items() if k != "id"}
            changed = True
        out.append(item)
    return out if changed else None
