"""他的设备：iPhone 主屏幕上的 Friday、电脑上的 Friday 窗口。订阅存在 STATE_DIR/push/。"""

from __future__ import annotations

import json
import time
from typing import Any

from src import webpush
from src.webpush import PUSH_DIR

SUBS_PATH = PUSH_DIR / "subscriptions.json"


def _load() -> list[dict[str, Any]]:
    if not SUBS_PATH.is_file():
        return []
    try:
        return list(json.loads(SUBS_PATH.read_text(encoding="utf-8")).get("subscriptions") or [])
    except (OSError, json.JSONDecodeError):
        return []


def _save(subs: list[dict[str, Any]]) -> None:
    PUSH_DIR.mkdir(parents=True, exist_ok=True)
    SUBS_PATH.write_text(json.dumps({"subscriptions": subs}, ensure_ascii=False, indent=2), encoding="utf-8")


def devices() -> list[dict[str, Any]]:
    return _load()


def subscribe(subscription: dict[str, Any], device: str = "") -> int:
    """同一个 endpoint 只留一份；返回现在一共几台设备。"""
    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("订阅缺少 endpoint 或 keys")
    subs = [s for s in _load() if s.get("endpoint") != endpoint]
    subs.append({"endpoint": endpoint, "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]},
                 "device": device[:80], "added_at": int(time.time())})
    _save(subs)
    return len(subs)


def unsubscribe(endpoint: str) -> None:
    _save([s for s in _load() if s.get("endpoint") != endpoint])


def deliver(message: dict[str, Any], *, urgency: str = "normal") -> int:
    """发给他所有的设备；失效的订阅顺手删掉。返回送到了几台。"""
    delivered = 0
    alive = []
    for sub in _load():
        try:
            webpush.send(sub, message, urgency=urgency)
            delivered += 1
            alive.append(sub)
        except webpush.Gone:
            continue
        except Exception as exc:  # noqa: BLE001 — 一台设备出错不影响别的
            print(f"[WARN] push to {sub.get('device') or 'device'} failed: {exc}")
            alive.append(sub)
    if len(alive) != len(_load()):
        _save(alive)
    return delivered
