"""用邮箱地址 + 授权码读写的邮箱（IMAP 收、SMTP 发）：163、126、QQ 这类。

放了 MAIL_ADDRESS 和 MAIL_PASSWORD（授权码，不是登录密码）就和 Gmail 一起看。服务器按域名认，不用他填。
163 有个规矩：登录后先报一下自己是谁（IMAP ID），不然一选收件箱就回「Unsafe Login」。

邮件编号是「文件夹:UID」（inbox:1234、sent:56）。读邮件不会把它标成已读。
发出去的信再放一份到「已发送」，以后才看得到「他发了、对方还没回」。
"""

from __future__ import annotations

import base64
import imaplib
import os
import re
import smtplib
import time
from contextlib import contextmanager
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.utils import formatdate, make_msgid, parsedate_to_datetime
from typing import Any, Iterator

from src.config import load_env

# 域名 → (收信服务器, 发信服务器, 页面上怎么叫它)
HOSTS = {
    "163.com": ("imap.163.com", "smtp.163.com", "163 邮箱"),
    "126.com": ("imap.126.com", "smtp.126.com", "126 邮箱"),
    "yeah.net": ("imap.yeah.net", "smtp.yeah.net", "yeah.net 邮箱"),
    "qq.com": ("imap.qq.com", "smtp.qq.com", "QQ 邮箱"),
    "foxmail.com": ("imap.qq.com", "smtp.qq.com", "QQ 邮箱"),
}
SCAN = 300  # 按关键词找时，看最近这么多封的标题和发件人
PREVIEW_BYTES = 20_000
FULL_BYTES = 400_000
TIMEOUT_S = 15
# 文件夹：特殊用途标记，和服务器上可能的名字（第一个是给他看的叫法）
FOLDERS = {
    "inbox": ("\\Inbox", ("收件箱", "INBOX")),
    "sent": ("\\Sent", ("已发送", "Sent", "Sent Messages", "Sent Items")),
    "trash": ("\\Trash", ("已删除", "Trash", "Deleted Messages", "Deleted Items")),
}
LOGIN_HELP = "邮箱登录不上：要用授权码（不是登录密码），并在网页版邮箱的设置里开启 IMAP/SMTP 服务"
_FETCHED = re.compile(rb"UID (\d+)")
_LISTED = re.compile(r'\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)$')


def accounts() -> list[tuple[str, str]]:
    """放了地址和授权码的邮箱：MAIL_ADDRESS / MAIL_PASSWORD，再多的就 MAIL_ADDRESS_2 / MAIL_PASSWORD_2 ……"""
    load_env()
    found = []
    for suffix in ("", "_2", "_3", "_4", "_5"):
        address = (os.getenv(f"MAIL_ADDRESS{suffix}") or "").strip()
        password = (os.getenv(f"MAIL_PASSWORD{suffix}") or "").replace(" ", "").strip()
        if address and password:
            found.append((address, password))
    return found


def account() -> tuple[str, str]:
    return (accounts() or [("", "")])[0]


def servers(address: str) -> tuple[str, str, str]:
    domain = address.rsplit("@", 1)[-1].lower()
    imap_host, smtp_host, name = HOSTS.get(domain, (f"imap.{domain}", f"smtp.{domain}", f"{domain} 邮箱"))
    return os.getenv("MAIL_IMAP_HOST") or imap_host, os.getenv("MAIL_SMTP_HOST") or smtp_host, name


# ---- 文字 ----

def _charset(name: str | None) -> str:
    name = (name or "utf-8").lower()
    # 国内邮件常标 gb2312 却用了 gbk 的字；gb18030 都认
    return "gb18030" if name in ("gb2312", "gbk", "gb_2312-80", "x-gbk") else name


def _header(value: Any) -> str:
    if value is None:
        return ""
    try:
        parts = decode_header(str(value))
        return "".join(
            (text.decode(_charset(charset), errors="replace") if isinstance(text, bytes) else text)
            for text, charset in parts
        ).strip()
    except (LookupError, ValueError):
        try:
            return str(make_header(decode_header(str(value))))
        except Exception:  # noqa: BLE001
            return str(value)


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _decoded(part: Message) -> str:
    payload = part.get_payload(decode=True) or b""
    try:
        return payload.decode(_charset(part.get_content_charset()), errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def body_of(msg: Message) -> str:
    """正文：先找纯文本，没有就把 HTML 去掉标签。附件不算。"""
    plain, html = "", ""
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        kind = part.get_content_type()
        if kind == "text/plain" and not plain:
            plain = _decoded(part)
        elif kind == "text/html" and not html:
            html = _decoded(part)
    return (plain.strip() or _strip_html(html)).strip()


def attachments_of(msg: Message) -> list[str]:
    return [_header(p.get_filename()) for p in msg.walk() if p.get_content_disposition() == "attachment" and p.get_filename()]


def _when(value: str) -> str:
    try:
        return parsedate_to_datetime(value).astimezone().isoformat(timespec="minutes")
    except (TypeError, ValueError):
        return value or ""


# ---- 文件夹名（IMAP 的 modified UTF-7） ----

def folder_name(raw: str) -> str:
    try:
        return _utf7(raw)
    except (ValueError, UnicodeDecodeError):
        return raw


def _utf7(raw: str) -> str:
    out, i = [], 0
    while i < len(raw):
        if raw[i] == "&":
            j = raw.index("-", i)
            if j == i + 1:
                out.append("&")
            else:
                chunk = raw[i + 1 : j].replace(",", "/")
                out.append(base64.b64decode(chunk + "=" * (-len(chunk) % 4)).decode("utf-16-be"))
            i = j + 1
        else:
            out.append(raw[i])
            i += 1
    return "".join(out)


def _quoted(raw: str) -> str:
    return raw if raw.startswith('"') else f'"{raw}"'


# ---- 他说的话 → 怎么找 ----

def parse_query(query: str) -> dict[str, Any]:
    """「in:sent」「is:unread」「from:导师」照 Gmail 的写法认；剩下的词都要在标题或发件人里出现。"""
    want: dict[str, Any] = {"folder": "inbox", "unread": False, "from": [], "words": []}
    for token in (query or "").split():
        low = token.lower()
        if low in ("in:inbox", "label:inbox"):
            want["folder"] = "inbox"
        elif low in ("in:sent", "label:sent", "is:sent"):
            want["folder"] = "sent"
        elif low == "is:unread":
            want["unread"] = True
        elif low.startswith("from:") and len(token) > 5:
            want["from"].append(token[5:].lower())
        elif ":" in low and low.split(":", 1)[0] in ("in", "is", "label", "newer_than", "older_than", "category"):
            continue  # 其他 Gmail 写法这里不认，不当关键词
        else:
            want["words"].append(low)
    return want


def _matches(head: dict[str, str], want: dict[str, Any]) -> bool:
    who = f"{head['from']} {head['to']}".lower()
    text = f"{head['subject']} {who}".lower()
    return all(f in who for f in want["from"]) and all(w in text for w in want["words"])


class ImapMailProvider:
    name = "imap"

    def __init__(self, address: str = "", password: str = "") -> None:
        self.address, self.password = (address, password) if address else account()
        self.imap_host, self.smtp_host, self.label = servers(self.address)

    # ---- 连接 ----

    @contextmanager
    def _imap(self) -> Iterator[imaplib.IMAP4]:
        if not self.address or not self.password:
            raise RuntimeError("没放邮箱地址和授权码（MAIL_ADDRESS、MAIL_PASSWORD）")
        conn = imaplib.IMAP4_SSL(self.imap_host, 993, timeout=TIMEOUT_S)
        try:
            try:
                conn.login(self.address, self.password)
            except imaplib.IMAP4.error as exc:
                raise RuntimeError(LOGIN_HELP) from exc
            try:
                conn.xatom("ID", '("name" "Friday" "version" "1.0" "vendor" "Friday")')
            except imaplib.IMAP4.error:
                pass  # 不认 ID 的服务器也不要求它
            yield conn
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass

    def _folders(self, conn: imaplib.IMAP4) -> dict[str, str]:
        """inbox / sent / trash → 服务器上的原名。先认特殊用途标记，没有再认中文名。"""
        found: dict[str, str] = {"inbox": "INBOX"}
        typ, rows = conn.list()
        listed = []
        for row in rows or []:
            hit = _LISTED.match(row.decode("utf-8", errors="replace") if isinstance(row, bytes) else str(row))
            if hit:
                listed.append((hit["flags"], hit["name"].strip()))
        for key, (flag, names) in FOLDERS.items():
            if key == "inbox":
                continue
            by_flag = next((name for flags, name in listed if flag.lower() in flags.lower()), None)
            by_name = next((name for flags, name in listed if folder_name(name.strip('"')) in names), None)
            if by_flag or by_name:
                found[key] = by_flag or by_name
        return found

    def _open(self, conn: imaplib.IMAP4, key: str, *, readonly: bool = True) -> None:
        name = self._folders(conn).get(key)
        if not name:
            raise RuntimeError(f"邮箱里没找到「{FOLDERS[key][1][0]}」")
        typ, data = conn.select(_quoted(name), readonly=readonly)
        if typ != "OK":
            raise RuntimeError(f"打不开「{FOLDERS[key][1][0]}」：{(data or [b''])[0]!r}")

    @staticmethod
    def _fetch(conn: imaplib.IMAP4, uids: list[bytes], what: str) -> dict[bytes, tuple[bytes, bytes]]:
        """UID FETCH → {uid: (那一行的说明, 内容)}。"""
        if not uids:
            return {}
        typ, data = conn.uid("FETCH", b",".join(uids).decode(), what)
        items, out = list(data or []), {}
        i = 0
        while i < len(items):
            item = items[i]
            if isinstance(item, tuple):
                meta, content = item[0], item[1]
                # 有的服务器把 UID、FLAGS 放在内容后面那一小段里
                if i + 1 < len(items) and isinstance(items[i + 1], bytes):
                    meta += items[i + 1]
                    i += 1
            elif isinstance(item, bytes):
                meta, content = item, b""
            else:
                i += 1
                continue
            hit = _FETCHED.search(meta)
            if hit:
                out[hit.group(1)] = (meta, content)
            i += 1
        return out

    # ---- 读 ----

    def search_messages(self, query: str, top: int = 5) -> dict[str, Any]:
        top = max(1, min(int(top or 5), 20))
        want = parse_query(query)
        try:
            with self._imap() as conn:
                self._open(conn, want["folder"])
                typ, data = conn.uid("SEARCH", None, "UNSEEN" if want["unread"] else "ALL")
                recent = (data[0] or b"").split()[-SCAN:] if data else []
                if want["words"] or want["from"]:
                    heads = {uid: self._head(raw) for uid, (_, raw) in self._fetch(
                        conn, recent, "(UID BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE)])").items()}
                    hits = [uid for uid in reversed(recent) if uid in heads and _matches(heads[uid], want)]
                    if not hits and want["words"]:
                        hits = self._search_text(conn, max(want["words"], key=len), want["unread"])
                else:
                    hits = list(reversed(recent))
                chosen = hits[:top]
                flags = {uid: meta for uid, (meta, _) in self._fetch(conn, chosen, "(UID FLAGS)").items()}
                bodies = self._fetch(conn, chosen, f"(UID BODY.PEEK[]<0.{PREVIEW_BYTES}>)")
                messages = []
                for uid in chosen:
                    if uid not in bodies:
                        continue
                    msg = message_from_bytes(bodies[uid][1])
                    messages.append({
                        "id": f"{want['folder']}:{uid.decode()}",
                        "subject": _header(msg["Subject"]) or "(无主题)",
                        "from": _header(msg["From"]),
                        "to": _header(msg["To"]),
                        "received": _when(msg["Date"] or ""),
                        "body_preview": re.sub(r"\s+", " ", body_of(msg))[:240],
                        "unread": b"\\Seen" not in flags.get(uid, b""),
                        "folder": want["folder"],
                    })
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "source": self.label, "error": "mail_search_failed", "message": str(exc), "messages": []}
        return {"ok": True, "source": self.label, "query": query, "messages": messages}

    @staticmethod
    def _head(raw: bytes) -> dict[str, str]:
        msg = message_from_bytes(raw or b"")
        return {"subject": _header(msg["Subject"]), "from": _header(msg["From"]),
                "to": f"{_header(msg['To'])} {_header(msg['Cc'])}", "date": msg["Date"] or ""}

    @staticmethod
    def _search_text(conn: imaplib.IMAP4, word: str, unread: bool) -> list[bytes]:
        """标题和发件人里没有，再让服务器在正文里找（中文要按 UTF-8 发）。"""
        try:
            conn.literal = word.encode("utf-8")
            args = ["CHARSET", "UTF-8"] + (["UNSEEN"] if unread else []) + ["TEXT"]
            typ, data = conn.uid("SEARCH", *args)
            return list(reversed((data[0] or b"").split()))[:SCAN] if typ == "OK" and data else []
        except imaplib.IMAP4.error:
            return []

    def get_message(self, message_id: str) -> dict[str, Any]:
        key, _, uid = (message_id or "").partition(":")
        if key not in ("inbox", "sent") or not uid.isdigit():
            return {"ok": False, "source": self.label, "error": "not_found", "message": f"找不到邮件: {message_id}"}
        try:
            with self._imap() as conn:
                self._open(conn, key)
                got = self._fetch(conn, [uid.encode()], f"(UID FLAGS BODY.PEEK[]<0.{FULL_BYTES}>)")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "source": self.label, "error": "mail_get_failed", "message": str(exc)}
        if uid.encode() not in got:
            return {"ok": False, "source": self.label, "error": "not_found", "message": f"找不到邮件: {message_id}"}
        meta, raw = got[uid.encode()]
        msg = message_from_bytes(raw)
        body = body_of(msg)
        if len(body) > 4000:
            body = body[:4000] + "\n...[truncated]"
        return {
            "ok": True,
            "source": self.label,
            "message": {
                "id": message_id,
                "subject": _header(msg["Subject"]) or "(无主题)",
                "from": _header(msg["From"]),
                "to": _header(msg["To"]),
                "cc": _header(msg["Cc"]),
                "received": _when(msg["Date"] or ""),
                "body": body,
                "attachments": attachments_of(msg),
                "unread": b"\\Seen" not in meta,
                "message_id": (msg["Message-ID"] or "").strip(),
            },
        }

    # ---- 写 ----

    def send_message(self, *, to: str, subject: str, body: str, cc: str = "") -> dict[str, Any]:
        msg = EmailMessage()
        msg["From"] = self.address
        msg["To"] = to
        if cc:
            msg["Cc"] = cc
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=self.address.rsplit("@", 1)[-1] or None)
        msg.set_content(body)
        try:
            with smtplib.SMTP_SSL(self.smtp_host, 465, timeout=TIMEOUT_S) as smtp:
                smtp.login(self.address, self.password)
                smtp.send_message(msg)
        except smtplib.SMTPAuthenticationError:
            return {"ok": False, "source": self.label, "error": "mail_send_failed", "message": LOGIN_HELP}
        except (smtplib.SMTPException, OSError) as exc:
            return {"ok": False, "source": self.label, "error": "mail_send_failed", "message": str(exc)}
        kept = True
        try:
            with self._imap() as conn:
                sent = self._folders(conn).get("sent")
                if sent:
                    conn.append(_quoted(sent), "(\\Seen)", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
                else:
                    kept = False
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] mail: sent, but could not keep a copy in 已发送: {exc}")
            kept = False
        return {"ok": True, "source": self.label, "id": msg["Message-ID"], "to": to, "subject": subject,
                "kept_in_sent": kept}

    def modify_labels(self, *, message_id: str, add_labels: list[str] | None = None,
                      remove_labels: list[str] | None = None) -> dict[str, Any]:
        """Gmail 的说法 → 这里：去掉 UNREAD 是标已读，加上是标未读，加 TRASH 是挪到「已删除」。这类邮箱没有「归档」。"""
        add, remove = set(add_labels or []), set(remove_labels or [])
        key, _, uid = (message_id or "").partition(":")
        if key not in ("inbox", "sent") or not uid.isdigit():
            return {"ok": False, "source": self.label, "error": "not_found", "message": f"找不到邮件: {message_id}"}
        if "TRASH" not in add and "INBOX" in remove:
            return {"ok": False, "source": self.label, "error": "archive_not_supported",
                    "message": f"{self.label}没有归档：可以标成已读，或者删到「已删除」"}
        try:
            with self._imap() as conn:
                self._open(conn, key, readonly=False)
                if "UNREAD" in remove:
                    conn.uid("STORE", uid, "+FLAGS", "(\\Seen)")
                if "UNREAD" in add:
                    conn.uid("STORE", uid, "-FLAGS", "(\\Seen)")
                if "TRASH" in add:
                    trash = self._folders(conn).get("trash")
                    if not trash:
                        raise RuntimeError("邮箱里没找到「已删除」")
                    typ, _ = conn.uid("COPY", uid, _quoted(trash))
                    if typ != "OK":
                        raise RuntimeError("没能挪到「已删除」")
                    conn.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
                    if "UIDPLUS" in conn.capabilities:
                        conn.uid("EXPUNGE", uid)
                    else:
                        conn.expunge()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "source": self.label, "error": "mail_modify_failed", "message": str(exc)}
        return {"ok": True, "source": self.label, "id": message_id}
