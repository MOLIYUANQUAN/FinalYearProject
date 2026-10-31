"""他在资料页里能改的几样：每天最多几条推送、安静时段。存在 STATE_DIR/settings.json，推送直接读，不用重新部署。"""

from __future__ import annotations

import json
import os
import re
from datetime import time
from typing import Any

from src.config import STATE_DIR

SETTINGS_PATH = STATE_DIR / "settings.json"
_CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _defaults() -> dict[str, Any]:
    try:
        daily = max(0, int(os.getenv("FRIDAY_PUSH_DAILY_MAX") or 3))
    except ValueError:
        daily = 3
    return {"daily_max": daily, "quiet_from": "22:00", "quiet_until": "08:00"}


def get() -> dict[str, Any]:
    saved: dict[str, Any] = {}
    try:
        if SETTINGS_PATH.is_file():
            saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        saved = {}
    return {**_defaults(), **{k: v for k, v in saved.items() if k in _defaults()}}


def update(changes: dict[str, Any]) -> dict[str, Any]:
    """只收认得的几样、合理的值；不合理的报错，不悄悄改成别的。"""
    current = get()
    if "daily_max" in changes and changes["daily_max"] is not None:
        daily = int(changes["daily_max"])
        if not 0 <= daily <= 10:
            raise ValueError("每天最多 0 到 10 条。")
        current["daily_max"] = daily
    for key in ("quiet_from", "quiet_until"):
        value = changes.get(key)
        if value is not None:
            if not _CLOCK.match(str(value)):
                raise ValueError("时间写成 22:00 这样。")
            current[key] = str(value)
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return current


def clock(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))
