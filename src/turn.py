"""一轮对话里工具留给页面的东西：比如刚记下的待办，页面据此给他「撤销」。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Turn:
    undo: list[dict[str, Any]] = field(default_factory=list)
