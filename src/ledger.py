"""这个月花了多少钱，资料页上看。

两个来源：
- 账单：放了 ANTHROPIC_ADMIN_KEY，就直接读 Anthropic 账单上的数（cost report，约 5 分钟内更新，整月都有），
  和控制台一模一样，也包括 Friday 以外在同一个账户上的用量。
- 自己记的：每问一次模型，按回复里带回来的 token 数和官方单价算一笔（RunHooks）。Friday 自己用掉的就是这个数，
  只是记账开始之前的、别处用的看不到。GPT-5 顶班走 OpenAI 的账，也只有这一个来源。
只记数字，不记对话内容。
"""

from __future__ import annotations

import calendar
import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

import requests
from agents import RunHooks

from src.config import STATE_DIR

LEDGER_PATH = STATE_DIR / "usage" / "tokens.jsonl"
# 每百万 token 的美元价：输入、输出、缓存读、缓存写（2026-10）
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-opus-5": (5.00, 25.00, 0.50, 6.25),
    "claude-opus-4-8": (5.00, 25.00, 0.50, 6.25),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
    "gpt-5": (1.25, 10.00, 0.125, 1.25),
    "gpt-4.1-mini": (0.40, 1.60, 0.10, 0.40),
}
LABELS = {
    "claude-opus-5-5": "Claude Opus 5.5",
    "claude-opus-5": "Claude Opus 5",
    "claude-opus-4-8": "Claude Opus 4.8",
    "claude-sonnet-5-5": "Claude Sonnet 5.5",
    "claude-haiku-5-5": "Claude Haiku 5.5",
    "gpt-5": "GPT-5",
    "gpt-4.1-mini": "GPT-4.1 mini",
}


def _known(model: str) -> str | None:
    """「gpt-5-2025-08-07」这种带日期的也认作 gpt-5：取最长的前缀。"""
    hits = [name for name in PRICES if model == name or model.startswith(name + "-")]
    return max(hits, key=len) if hits else None


def label(model: str) -> str:
    known = _known(model or "")
    return LABELS[known] if known else (model or "")


def cost(model: str, inputs: int, outputs: int, cached: int = 0, written: int = 0) -> float:
    """inputs 是全部输入（含缓存读、缓存写的那部分）。不认识的型号算 0。"""
    known = _known(model or "")
    if not known:
        return 0.0
    p_in, p_out, p_read, p_write = PRICES[known]
    fresh = max(0, inputs - cached - written)
    return (fresh * p_in + cached * p_read + written * p_write + outputs * p_out) / 1_000_000


def record(model: str, inputs: int, outputs: int, cached: int = 0, written: int = 0) -> None:
    row = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "model": model,
        "in": inputs,
        "out": outputs,
        "cached": cached,
        "written": written,
        "usd": round(cost(model, inputs, outputs, cached, written), 6),
    }
    try:
        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass


def record_usage(model: str, usage: Any) -> None:
    """Agents SDK / OpenAI 的 usage 对象（input_tokens_details 里有缓存读、缓存写）。"""
    details = getattr(usage, "input_tokens_details", None)
    record(
        model,
        int(getattr(usage, "input_tokens", 0) or 0),
        int(getattr(usage, "output_tokens", 0) or 0),
        int(getattr(details, "cached_tokens", 0) or 0),
        int(getattr(details, "cache_write_tokens", 0) or 0),
    )


class Ledger(RunHooks):
    """每问一次模型记一笔。哪个模型答的：Claude 那边被拦下换了模型、或者备用的顶上了，以实际答的为准。"""

    async def on_llm_end(self, context: Any, agent: Any, response: Any) -> None:
        model = getattr(agent.model, "served", None) or getattr(agent.model, "name", None) or agent.model
        record_usage(str(model), response.usage)


LEDGER = Ledger()


def _rows() -> list[dict[str, Any]]:
    if not LEDGER_PATH.is_file():
        return []
    rows = []
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def budget() -> float:
    """每月的 API 额度（Ultra 订阅附带 $200）。"""
    try:
        return float(os.getenv("FRIDAY_MONTHLY_BUDGET") or 200)
    except ValueError:
        return 200.0


BILLING_URL = "https://api.anthropic.com/v1/organizations/cost_report"
BILLING_FRESH_S = 5 * 60  # 账单本身约 5 分钟才更新一次
_billing_lock = threading.Lock()
_billing: tuple[float, str, float | None] | None = None  # (读到的时刻, 哪个月, 美元；读不到是 None)


def billed(now: datetime | None = None) -> float | None:
    """Anthropic 账单上这个月（UTC 自然月）的花费，美元。没放管理员 key 或者读不到就是 None。"""
    global _billing
    key = (os.getenv("ANTHROPIC_ADMIN_KEY") or "").strip()
    if not key:
        return None
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    month_key = now.strftime("%Y-%m")
    with _billing_lock:
        if _billing and _billing[1] == month_key and time.monotonic() - _billing[0] < BILLING_FRESH_S:
            return _billing[2]
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    params: dict[str, Any] = {"starting_at": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "limit": 31}
    cents = 0.0
    try:
        for _ in range(5):
            res = requests.get(BILLING_URL, params=params, timeout=8,
                               headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
            res.raise_for_status()
            data = res.json()
            cents += sum(float(r.get("amount") or 0) for bucket in data.get("data", []) for r in bucket.get("results", []))
            if not data.get("has_more") or not data.get("next_page"):
                break
            params["page"] = data["next_page"]
    except (requests.RequestException, ValueError) as exc:
        print(f"[WARN] billing: could not read the cost report: {exc}")
        # 读不到也记 5 分钟：不让每次打开资料页都再等一轮
        with _billing_lock:
            _billing = (time.monotonic(), month_key, None)
        return None
    dollars = round(cents / 100, 2)  # 账单金额是「分」
    with _billing_lock:
        _billing = (time.monotonic(), month_key, dollars)
    return dollars


def month(now: datetime | None = None) -> dict[str, Any]:
    """这个月（自然月，按真实时间，不跟演示日期走）花了多少、照这个速度月底大约多少、按模型分、token 和缓存命中。"""
    now = now or datetime.now()
    prefix = now.strftime("%Y-%m")
    rows = [r for r in _rows() if str(r.get("ts", "")).startswith(prefix)]
    spent = sum(float(r.get("usd") or 0) for r in rows)
    days = calendar.monthrange(now.year, now.month)[1]
    elapsed = max(1.0, now.day - 1 + now.hour / 24)
    by_model: dict[str, float] = {}
    for r in rows:
        name = label(str(r.get("model", "")))
        by_model[name] = by_model.get(name, 0.0) + float(r.get("usd") or 0)
    inputs = sum(int(r.get("in") or 0) for r in rows)
    cached = sum(int(r.get("cached") or 0) for r in rows)
    counted = round(spent, 2)
    # 有账单就以账单为准；GPT-5 顶班那部分走 OpenAI，账单里没有，加上自己记的
    openai = sum(float(r.get("usd") or 0) for r in rows if not str(r.get("model", "")).startswith("claude"))
    bill = billed()
    if bill is not None:
        spent = bill + openai
    return {
        "month": f"{now.month}月",
        "spent": round(spent, 2),
        "source": "bill" if bill is not None else "counted",
        "counted": counted,
        "projected": round(spent / elapsed * days, 2) if rows or bill else 0.0,
        "budget": budget(),
        "calls": len(rows),
        "by_model": [{"model": k, "usd": round(v, 2)} for k, v in sorted(by_model.items(), key=lambda kv: -kv[1])],
        "tokens": {
            "in": inputs,
            "out": sum(int(r.get("out") or 0) for r in rows),
            "cached": cached,
            "cache_hit": round(cached / inputs, 2) if inputs else 0.0,
        },
        "since": rows[0]["ts"][:10] if rows else "",
    }
