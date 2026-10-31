"""几个邮箱一起看（Gmail + 163……）：一起搜、按时间排在一起；读、改、回信各回各的邮箱。

每封信的编号前面加上是哪个邮箱（gmail:…、163:…），带一个 mailbox 写给她看。一个邮箱读不到，不耽误别的：
读得到的照常给，读不到的写在 problems 里，她能直说「163 这会儿读不到」。
发信不说从哪个发，就用地址 + 授权码的那个（他说重要的信在 163）；回某封信，她填那封信的 mailbox。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from src.mail_providers import label_of

_OLDEST = datetime.min.replace(tzinfo=timezone.utc)


def _key(box: Any, taken: set[str]) -> str:
    if getattr(box, "name", "") == "imap":
        base = box.address.rsplit("@", 1)[-1].split(".")[0].lower() or "mail"
    else:
        base = box.name
    key, n = base, 2
    while key in taken:
        key, n = f"{base}-{n}", n + 1
    return key


def _when(value: Any) -> datetime:
    text = str(value or "").strip()
    for parse in (datetime.fromisoformat, parsedate_to_datetime):
        try:
            when = parse(text)
            return when if when.tzinfo else when.astimezone()
        except (TypeError, ValueError):
            continue
    return _OLDEST


class Mailboxes:
    name = "several"

    def __init__(self, boxes: list[Any]) -> None:
        self.boxes: dict[str, Any] = {}
        for box in boxes:
            self.boxes[_key(box, set(self.boxes))] = box
        self.label = "、".join(label_of(b) for b in self.boxes.values())

    def _tag(self, key: str, message: dict[str, Any]) -> dict[str, Any]:
        when = _when(message.get("received"))
        received = when.astimezone().isoformat(timespec="minutes") if when is not _OLDEST else message.get("received")
        return {**message, "id": f"{key}:{message.get('id')}", "mailbox": label_of(self.boxes[key]), "received": received}

    def _route(self, message_id: str) -> tuple[str, Any, str] | None:
        key, _, inner = (message_id or "").partition(":")
        box = self.boxes.get(key)
        return (key, box, inner) if box is not None and inner else None

    def sender(self, mailbox: str = "") -> tuple[str, Any]:
        """他（或她）说了用哪个就用哪个；没说就用地址 + 授权码的那个，没有就第一个。"""
        wanted = (mailbox or "").strip().lower().replace(" ", "")
        if wanted:
            for key, box in self.boxes.items():
                names = {key, label_of(box).lower().replace(" ", ""), getattr(box, "address", "").lower()}
                if wanted in names or any(wanted in n or n in wanted for n in names if n):
                    return key, box
        for key, box in self.boxes.items():
            if getattr(box, "name", "") == "imap":
                return key, box
        return next(iter(self.boxes.items()))

    # ---- 读 ----

    def search_messages(self, query: str, top: int = 5) -> dict[str, Any]:
        def one(item: tuple[str, Any]) -> tuple[str, dict[str, Any]]:
            key, box = item
            try:
                return key, box.search_messages(query, top)
            except Exception as exc:  # noqa: BLE001
                return key, {"ok": False, "message": str(exc)}

        with ThreadPoolExecutor(max_workers=len(self.boxes)) as pool:
            results = list(pool.map(one, self.boxes.items()))
        found, problems = [], []
        for key, result in results:
            if not result.get("ok"):
                problems.append({"mailbox": label_of(self.boxes[key]),
                                 "message": str(result.get("message") or result.get("error") or "读不到")})
                continue
            found += [self._tag(key, m) for m in result.get("messages") or []]
        found.sort(key=lambda m: _when(m.get("received")), reverse=True)
        out: dict[str, Any] = {"ok": bool(found) or len(problems) < len(results), "source": self.label,
                               "query": query, "messages": found[: max(1, min(int(top or 5), 20))]}
        if problems:
            out["problems"] = problems
            if not out["ok"]:
                out["message"] = "；".join(f"{p['mailbox']}：{p['message']}" for p in problems)
        return out

    def get_message(self, message_id: str) -> dict[str, Any]:
        route = self._route(message_id)
        if route is None:
            return {"ok": False, "source": self.label, "error": "not_found", "message": f"找不到邮件: {message_id}"}
        key, box, inner = route
        result = box.get_message(inner)
        if result.get("ok") and isinstance(result.get("message"), dict):
            result = {**result, "message": self._tag(key, result["message"])}
        return result

    # ---- 写 ----

    def send_message(self, *, to: str, subject: str, body: str, cc: str = "", mailbox: str = "") -> dict[str, Any]:
        _, box = self.sender(mailbox)
        send = getattr(box, "send_message", None)
        if send is None:
            return {"ok": False, "error": "send_not_supported", "source": label_of(box)}
        return {**send(to=to, subject=subject, body=body, cc=cc), "mailbox": label_of(box)}

    def modify_labels(self, *, message_id: str, add_labels: list[str] | None = None,
                      remove_labels: list[str] | None = None) -> dict[str, Any]:
        route = self._route(message_id)
        if route is None:
            return {"ok": False, "source": self.label, "error": "not_found", "message": f"找不到邮件: {message_id}"}
        _, box, inner = route
        modify = getattr(box, "modify_labels", None)
        if modify is None:
            return {"ok": False, "error": "modify_not_supported", "source": label_of(box)}
        return modify(message_id=inner, add_labels=add_labels, remove_labels=remove_labels)
