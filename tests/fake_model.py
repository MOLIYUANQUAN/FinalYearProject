"""测试用假模型：按脚本依次返回文字或工具调用，不访问网络、不需要 API Key。

整个 Friday 的对话流程（会话、确认、撤销）都能离线跑。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from agents import Model, ModelResponse, Usage
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseTextDeltaEvent,
)


def text(content: str) -> tuple[str, str]:
    return ("text", content)


def call(name: str, **arguments: Any) -> tuple[str, str, dict[str, Any]]:
    return ("call", name, arguments)


class FakeModel(Model):
    """`turns` 中每一项是模型一次回复的输出列表，例如 `[call("search_files", query="FYP")]`。"""

    def __init__(self, turns: list[list[tuple]]) -> None:
        self.turns = list(turns)
        self.inputs: list[Any] = []

    def _next_output(self, input: Any) -> list[Any]:
        self.inputs.append(input)
        if not self.turns:
            raise AssertionError("FakeModel 脚本已用完")
        output = []
        for spec in self.turns.pop(0):
            if spec[0] == "text":
                output.append(
                    ResponseOutputMessage(
                        id=f"msg_{uuid.uuid4().hex[:8]}",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[ResponseOutputText(type="output_text", text=spec[1], annotations=[])],
                    )
                )
            else:
                output.append(
                    ResponseFunctionToolCall(
                        id=f"fc_{uuid.uuid4().hex[:8]}",
                        call_id=f"call_{uuid.uuid4().hex[:8]}",
                        type="function_call",
                        name=spec[1],
                        arguments=json.dumps(spec[2], ensure_ascii=False),
                        status="completed",
                    )
                )
        return output

    async def get_response(self, system_instructions, input, model_settings, tools, output_schema,
                           handoffs, tracing, **kwargs) -> ModelResponse:
        return ModelResponse(output=self._next_output(input), usage=Usage(), response_id=None)

    async def stream_response(self, system_instructions, input, model_settings, tools, output_schema,
                              handoffs, tracing, **kwargs) -> AsyncIterator[Any]:
        output = self._next_output(input)
        seq = 0
        for item in output:
            if isinstance(item, ResponseOutputMessage):
                for chunk in (item.content[0].text[i : i + 8] for i in range(0, len(item.content[0].text), 8)):
                    yield ResponseTextDeltaEvent.model_construct(
                        type="response.output_text.delta", delta=chunk, item_id=item.id,
                        output_index=0, content_index=0, sequence_number=seq, logprobs=[],
                    )
                    seq += 1
        response = Response.model_construct(
            id=f"resp_{uuid.uuid4().hex[:8]}", object="response", created_at=0, model="fake",
            output=output, usage=None, tools=[], tool_choice="auto", parallel_tool_calls=True,
        )
        yield ResponseCompletedEvent.model_construct(type="response.completed", response=response, sequence_number=seq)
