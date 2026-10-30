"""Web Push：把一条通知送到他的 iPhone 主屏幕 Friday 和电脑上的 Friday 窗口。

只用 cryptography（pywebpush 依赖的 http_ece 在新 Python 上装不上）：
- 加密：RFC 8291（aes128gcm）
- 身份：RFC 8292（VAPID，ES256 JWT）

VAPID 钥匙第一次用时生成，存在 STATE_DIR/push/vapid.json（云上在磁盘里，部署不变，
订阅就一直有效）。也可以用环境变量 FRIDAY_VAPID_PRIVATE_KEY 指定。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import struct
import time
from typing import Any
from urllib.parse import urlsplit

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.config import STATE_DIR

PUSH_DIR = STATE_DIR / "push"
VAPID_PATH = PUSH_DIR / "vapid.json"
CONTACT = "mailto:friday@friday-jimmy.fly.dev"
RECORD_SIZE = 4096


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _public_bytes(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


# ---- VAPID ----


def _private_from_raw(raw: bytes) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())


def vapid_private_key() -> ec.EllipticCurvePrivateKey:
    env = (os.getenv("FRIDAY_VAPID_PRIVATE_KEY") or "").strip()
    if env:
        return _private_from_raw(b64url_decode(env))
    if VAPID_PATH.is_file():
        return _private_from_raw(b64url_decode(json.loads(VAPID_PATH.read_text(encoding="utf-8"))["private"]))
    key = ec.generate_private_key(ec.SECP256R1())
    raw = key.private_numbers().private_value.to_bytes(32, "big")
    PUSH_DIR.mkdir(parents=True, exist_ok=True)
    VAPID_PATH.write_text(json.dumps({"private": b64url(raw)}), encoding="utf-8")
    return key


def vapid_public_key() -> str:
    """页面订阅时用的 applicationServerKey。"""
    return b64url(_public_bytes(vapid_private_key().public_key()))


def _vapid_header(endpoint: str) -> str:
    parts = urlsplit(endpoint)
    claims = {"aud": f"{parts.scheme}://{parts.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": CONTACT}
    header = {"typ": "JWT", "alg": "ES256"}
    signing_input = f"{b64url(json.dumps(header).encode())}.{b64url(json.dumps(claims).encode())}".encode()
    key = vapid_private_key()
    r, s = decode_dss_signature(key.sign(signing_input, ec.ECDSA(hashes.SHA256())))
    token = signing_input.decode() + "." + b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={token}, k={b64url(_public_bytes(key.public_key()))}"


# ---- 加密（RFC 8291）----


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:length]


def encrypt(payload: bytes, p256dh: str, auth: str, *, salt: bytes | None = None,
            sender: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """按订阅里的 p256dh / auth 加密，返回 aes128gcm 编码的请求体。"""
    ua_public = b64url_decode(p256dh)
    auth_secret = b64url_decode(auth)
    sender = sender or ec.generate_private_key(ec.SECP256R1())
    as_public = _public_bytes(sender.public_key())
    receiver = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    shared = sender.exchange(ec.ECDH(), receiver)

    ikm = _hkdf(auth_secret, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    header = salt + struct.pack("!IB", RECORD_SIZE, len(as_public)) + as_public
    return header + body


# ---- 发送 ----


class Gone(Exception):
    """订阅失效了（卸载、关了通知、换了设备）：调用方把它删掉。"""


def send(subscription: dict[str, Any], message: dict[str, Any], *, urgency: str = "normal", ttl: int = 6 * 3600) -> None:
    keys = subscription.get("keys") or {}
    endpoint = subscription["endpoint"]
    body = encrypt(json.dumps(message, ensure_ascii=False).encode("utf-8"), keys["p256dh"], keys["auth"])
    res = requests.post(
        endpoint,
        data=body,
        headers={
            "Authorization": _vapid_header(endpoint),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(ttl),
            "Urgency": urgency,
        },
        timeout=15,
    )
    if res.status_code in (404, 410):
        raise Gone(endpoint)
    if res.status_code >= 400:
        raise RuntimeError(f"push {res.status_code}: {res.text[:200]}")
