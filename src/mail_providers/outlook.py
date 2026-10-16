"""Microsoft Graph Outlook 邮件只读。"""

from __future__ import annotations

from typing import Any

import requests

from src.config import (
    OUTLOOK_TOKEN_PATH,
    get_outlook_client_id,
    get_outlook_tenant,
)

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["User.Read", "Mail.Read"]


class OutlookMailProvider:
    name = "outlook"

    def search_messages(self, query: str, top: int = 5) -> dict[str, Any]:
        token = _get_access_token()
        top = max(1, min(int(top), 20))
        headers = {"Authorization": f"Bearer {token}"}

        q = (query or "").strip()
        if q:
            # Graph $search 需要 ConsistencyLevel；对学校租户更稳妥用 $filter 或 search
            url = f"{GRAPH}/me/messages"
            params = {
                "$top": str(top),
                "$select": "id,subject,from,receivedDateTime,bodyPreview",
                "$orderby": "receivedDateTime DESC",
                "$search": f'"{q}"',
            }
            headers["ConsistencyLevel"] = "eventual"
        else:
            url = f"{GRAPH}/me/messages"
            params = {
                "$top": str(top),
                "$select": "id,subject,from,receivedDateTime,bodyPreview",
                "$orderby": "receivedDateTime DESC",
            }

        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code >= 400:
            return {
                "ok": False,
                "source": self.name,
                "error": "graph_error",
                "status": resp.status_code,
                "message": resp.text[:500],
                "messages": [],
            }

        raw = resp.json().get("value") or []
        messages = [_summarize(m) for m in raw]
        return {
            "ok": True,
            "source": self.name,
            "query": query,
            "messages": messages,
        }

    def get_message(self, message_id: str) -> dict[str, Any]:
        token = _get_access_token()
        url = f"{GRAPH}/me/messages/{message_id}"
        params = {"$select": "id,subject,from,receivedDateTime,bodyPreview,body"}
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=30,
        )
        if resp.status_code >= 400:
            return {
                "ok": False,
                "source": self.name,
                "error": "graph_error",
                "status": resp.status_code,
                "message": resp.text[:500],
            }
        m = resp.json()
        body = m.get("body") or {}
        content = body.get("content") or ""
        # HTML 过长时截断
        if len(content) > 4000:
            content = content[:4000] + "\n...[truncated]"
        return {
            "ok": True,
            "source": self.name,
            "message": {
                "id": m.get("id"),
                "subject": m.get("subject"),
                "from": _from_address(m.get("from")),
                "received": m.get("receivedDateTime"),
                "body_preview": m.get("bodyPreview"),
                "body": content,
                "body_type": body.get("contentType"),
            },
        }


def _summarize(m: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": m.get("id"),
        "subject": m.get("subject"),
        "from": _from_address(m.get("from")),
        "received": m.get("receivedDateTime"),
        "body_preview": m.get("bodyPreview"),
    }


def _from_address(from_obj: Any) -> str:
    if not isinstance(from_obj, dict):
        return ""
    email = (from_obj.get("emailAddress") or {}) if from_obj else {}
    name = email.get("name") or ""
    addr = email.get("address") or ""
    if name and addr:
        return f"{name} <{addr}>"
    return addr or name


def _build_msal_app():
    import msal

    client_id = get_outlook_client_id()
    if not client_id:
        raise RuntimeError(
            "缺少 OUTLOOK_CLIENT_ID。请按 docs/outlook-mail-setup.md 在 Azure 注册应用并写入 .env。"
        )
    tenant = get_outlook_tenant()
    authority = f"https://login.microsoftonline.com/{tenant}"
    cache = _load_cache()
    app = msal.PublicClientApplication(
        client_id,
        authority=authority,
        token_cache=cache,
    )
    return app, cache


def _load_cache():
    import msal

    cache = msal.SerializableTokenCache()
    if OUTLOOK_TOKEN_PATH.is_file():
        cache.deserialize(OUTLOOK_TOKEN_PATH.read_text(encoding="utf-8"))
    return cache


def _save_cache(cache) -> None:
    if cache.has_state_changed:
        OUTLOOK_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTLOOK_TOKEN_PATH.write_text(cache.serialize(), encoding="utf-8")


def _get_access_token() -> str:
    app, cache = _build_msal_app()
    accounts = app.get_accounts()
    result = None
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
    if not result:
        raise RuntimeError(
            "Outlook 未登录或 token 已失效。请运行: python scripts/auth_outlook.py"
        )
    _save_cache(cache)
    token = result.get("access_token")
    if not token:
        raise RuntimeError(f"获取 Outlook token 失败: {result}")
    return token


def ensure_outlook_login() -> str:
    """设备码登录（适合学校账号）。"""
    app, cache = _build_msal_app()
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"无法启动设备码登录: {flow}")
    print(flow["message"])  # 含网址与代码
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(f"Outlook 授权失败: {result}")
    _save_cache(cache)
    return f"Outlook authorized. Token cache saved to {OUTLOOK_TOKEN_PATH}"
