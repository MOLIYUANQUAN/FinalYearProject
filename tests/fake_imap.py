"""测试用的本机 IMAP 服务器：够 Python 的 imaplib 真的走一遍协议（字面量、UID、文件夹名的 modified UTF-7）。

学 163：不先发 ID 就选文件夹，回「Unsafe Login」。uid_last=True 时把 UID、FLAGS 放在内容后面（有的服务器这样）。
"""

from __future__ import annotations

import re
import socketserver
import threading
from typing import Any

SENT = "&XfJT0ZAB-"  # 已发送
TRASH = "&XfJSIJZk-"  # 已删除


def tokens(text: str) -> list[str]:
    """按空格切，但引号里的、括号里的算一个。"""
    out, cur, depth, quoted, i = [], "", 0, False, 0
    while i < len(text):
        c = text[i]
        if quoted:
            cur += c
            if c == "\\" and i + 1 < len(text):
                cur += text[i + 1]
                i += 1
            elif c == '"':
                quoted = False
        elif c == '"':
            quoted, cur = True, cur + c
        elif c in "([":
            depth, cur = depth + 1, cur + c
        elif c in ")]":
            depth, cur = depth - 1, cur + c
        elif c == " " and depth == 0:
            if cur:
                out.append(cur)
            cur = ""
        else:
            cur += c
        i += 1
    if cur:
        out.append(cur)
    return out


def unquote(value: str) -> str:
    return value[1:-1].replace('\\"', '"').replace("\\\\", "\\") if value.startswith('"') else value


def headers_of(raw: bytes, names: list[str]) -> bytes:
    head = raw.split(b"\r\n\r\n", 1)[0].split(b"\n\n", 1)[0]
    lines, keep = [], False
    for line in head.replace(b"\r\n", b"\n").split(b"\n"):
        if line[:1] in (b" ", b"\t"):
            if keep:
                lines.append(line)
            continue
        keep = line.split(b":", 1)[0].decode(errors="replace").strip().upper() in names
        if keep:
            lines.append(line)
    return b"\r\n".join(lines) + b"\r\n\r\n"


class FakeImap:
    def __init__(self, folders: dict[str, list[tuple[bytes, set[str]]]], *, password: str = "CODE",
                 uid_last: bool = False, special_use: bool = False) -> None:
        self.password = password
        self.uid_last = uid_last
        self.special_use = special_use
        self.boxes: dict[str, list[dict[str, Any]]] = {}
        self.next_uid: dict[str, int] = {}
        for name, messages in folders.items():
            self.boxes[name] = []
            self.next_uid[name] = 101
            for raw, flags in messages:
                self.add(name, raw, flags)
        self.commands: list[str] = []
        self.searched: list[bytes] = []
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:  # noqa: C901
                outer.session(self)

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def add(self, box: str, raw: bytes, flags: set[str]) -> int:
        uid = self.next_uid[box]
        self.next_uid[box] += 1
        self.boxes[box].append({"uid": uid, "raw": raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"), "flags": set(flags)})
        return uid

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    # ---- 一次连接 ----

    def session(self, h: socketserver.StreamRequestHandler) -> None:  # noqa: C901
        write = h.wfile.write
        write(b"* OK [CAPABILITY IMAP4rev1 ID UIDPLUS LITERAL+] fake imap ready\r\n")
        state = {"user": None, "id": False, "box": None}
        while True:
            line = h.rfile.readline()
            if not line:
                return
            literal = b""
            text = line.rstrip(b"\r\n")
            hit = re.search(rb"\{(\d+)\}$", text)
            if hit:
                write(b"+ go ahead\r\n")
                h.wfile.flush()
                literal = h.rfile.read(int(hit.group(1)))
                rest = h.rfile.readline().rstrip(b"\r\n")
                text = text[: hit.start()] + rest
            tag, _, rest = text.decode("utf-8", errors="replace").partition(" ")
            command, _, args = rest.partition(" ")
            command = command.upper()
            self.commands.append(command if command != "UID" else "UID " + args.split(" ", 1)[0].upper())
            reply = self.run(state, command, args, literal)
            if reply is None:
                write(f"* BYE\r\n{tag} OK LOGOUT completed\r\n".encode())
                h.wfile.flush()
                return
            untagged, status = reply
            write(untagged + f"{tag} {status}\r\n".encode())
            h.wfile.flush()

    def run(self, state: dict, command: str, args: str, literal: bytes) -> tuple[bytes, str] | None:  # noqa: C901
        parts = tokens(args)
        if command == "CAPABILITY":
            return b"* CAPABILITY IMAP4rev1 ID UIDPLUS LITERAL+\r\n", "OK CAPABILITY completed"
        if command == "LOGIN":
            if unquote(parts[1]) != self.password:
                return b"", "NO [AUTHENTICATIONFAILED] LOGIN Login error user suspended"
            state["user"] = unquote(parts[0])
            return b"", "OK LOGIN completed"
        if command == "LOGOUT":
            return None
        if command == "NOOP":
            return b"", "OK NOOP completed"
        if command == "ID":
            state["id"] = True
            return b'* ID ("name" "fake")\r\n', "OK ID completed"
        if command == "LIST":
            rows = []
            for name in self.boxes:
                flag = ""
                if self.special_use and name == SENT:
                    flag = " \\Sent"
                if self.special_use and name == TRASH:
                    flag = " \\Trash"
                rows.append(f'* LIST (\\HasNoChildren{flag}) "/" "{name}"\r\n')
            return "".join(rows).encode(), "OK LIST completed"
        if command in ("SELECT", "EXAMINE"):
            if not state["id"]:
                return b"", f"NO {command} Unsafe Login. Please contact kefu@188.com for help"
            name = unquote(parts[0])
            if name not in self.boxes:
                return b"", f"NO {command} no such folder"
            state["box"] = name
            mode = "READ-ONLY" if command == "EXAMINE" else "READ-WRITE"
            return (f"* {len(self.boxes[name])} EXISTS\r\n* OK [UIDVALIDITY 1] ok\r\n").encode(), f"OK [{mode}] done"
        if command == "APPEND":
            name = unquote(parts[0])
            flags = set(re.findall(r"\\\w+", parts[1])) if len(parts) > 1 and parts[1].startswith("(") else set()
            uid = self.add(name, literal, flags)
            return b"", f"OK [APPENDUID 1 {uid}] APPEND completed"
        if command == "EXPUNGE":
            box = self.boxes[state["box"]]
            box[:] = [m for m in box if "\\Deleted" not in m["flags"]]
            return b"", "OK EXPUNGE completed"
        if command == "UID":
            return self.uid(state, parts[0].upper(), parts[1:], literal)
        return b"", f"BAD unknown command {command}"

    def _pick(self, state: dict, spec: str) -> list[tuple[int, dict]]:
        box = self.boxes[state["box"]]
        wanted: set[int] = set()
        for piece in spec.split(","):
            if ":" in piece:
                a, b = piece.split(":")
                hi = max(m["uid"] for m in box) if box and b == "*" else int(b) if b != "*" else 0
                wanted.update(range(int(a), hi + 1))
            else:
                wanted.add(int(piece))
        return [(i + 1, m) for i, m in enumerate(box) if m["uid"] in wanted]

    def uid(self, state: dict, sub: str, parts: list[str], literal: bytes) -> tuple[bytes, str]:  # noqa: C901
        box = self.boxes[state["box"]]
        if sub == "SEARCH":
            words = [p.upper() for p in parts]
            hits = list(box)
            if "UNSEEN" in words:
                hits = [m for m in hits if "\\Seen" not in m["flags"]]
            if "TEXT" in words:
                self.searched.append(literal)
                hits = [m for m in hits if literal and literal in m["raw"]]
            return ("* SEARCH " + " ".join(str(m["uid"]) for m in hits) + "\r\n").encode(), "OK SEARCH completed"
        if sub == "FETCH":
            items = parts[1].strip("()")
            out = b""
            for seq, m in self._pick(state, parts[0]):
                fields, payload = [], None
                if "FLAGS" in items.split():
                    fields.append(f"FLAGS ({' '.join(sorted(m['flags']))})")
                head = re.search(r"BODY\.PEEK\[HEADER\.FIELDS \(([^)]*)\)\]", items)
                if head:
                    payload = (f"BODY[HEADER.FIELDS ({head.group(1)})]", headers_of(m["raw"], head.group(1).upper().split()))
                whole = re.search(r"BODY\.PEEK\[\]<0\.(\d+)>", items)
                if whole:
                    payload = ("BODY[]<0>", m["raw"][: int(whole.group(1))])
                uid_part = f"UID {m['uid']}"
                if payload and self.uid_last:
                    tail = " ".join([uid_part, *fields])
                    out += f"* {seq} FETCH ({payload[0]} {{{len(payload[1])}}}\r\n".encode() + payload[1] + f" {tail})\r\n".encode()
                elif payload:
                    lead = " ".join([uid_part, *fields])
                    out += f"* {seq} FETCH ({lead} {payload[0]} {{{len(payload[1])}}}\r\n".encode() + payload[1] + b")\r\n"
                else:
                    out += f"* {seq} FETCH ({' '.join([uid_part, *fields])})\r\n".encode()
            return out, "OK FETCH completed"
        if sub == "STORE":
            flags = set(re.findall(r"\\\w+", parts[2]))
            out = b""
            for seq, m in self._pick(state, parts[0]):
                if parts[1].startswith("+"):
                    m["flags"] |= flags
                else:
                    m["flags"] -= flags
                out += f"* {seq} FETCH (UID {m['uid']} FLAGS ({' '.join(sorted(m['flags']))}))\r\n".encode()
            return out, "OK STORE completed"
        if sub == "COPY":
            target = unquote(parts[1])
            for _, m in self._pick(state, parts[0]):
                self.add(target, m["raw"], set(m["flags"]))
            return b"", "OK COPY completed"
        if sub == "EXPUNGE":
            uids = {m["uid"] for _, m in self._pick(state, parts[0])}
            box[:] = [m for m in box if not (m["uid"] in uids and "\\Deleted" in m["flags"])]
            return b"", "OK EXPUNGE completed"
        return b"", f"BAD unknown UID {sub}"


class FakeSmtp:
    """smtplib.SMTP_SSL 的替身：记下登录和发出去的信。"""

    sent: list[Any] = []
    logins: list[tuple[str, str]] = []
    password = "CODE"

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host, self.port = host, port

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def login(self, user: str, password: str) -> None:
        import smtplib

        if password != FakeSmtp.password:
            raise smtplib.SMTPAuthenticationError(535, b"Error: authentication failed")
        FakeSmtp.logins.append((user, self.host))

    def send_message(self, msg: Any) -> dict:
        FakeSmtp.sent.append(msg)
        return {}
