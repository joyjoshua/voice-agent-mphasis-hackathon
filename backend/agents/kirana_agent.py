"""Kirana NLU + Paytm-backed voice reply shaping (offline-capable fallback)."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from dotenv import load_dotenv

from db.database import get_inventory
from logger.csv_logger import get_recent_turns, log_turn
from parser.regex_patterns import parse_transcript
from tools import inventory as inventory_tool
from tools import sales as sales_tool

load_dotenv()

# --- Layer 1 canned copy (guardrails.md: TTS-safe, no markdown) ---
CANNED_OFF_TOPIC = (
    "I'm your store assistant. "
    "I can help with sales, inventory, and today's earnings. "
    "Try saying: sold two Parle-G, how much did I make today, or what's running low."
)
PRODUCT_UNCLEAR = (
    "I couldn't identify the product. Try saying the item name clearly."
)
BAD_QUANTITY = "That quantity doesn't seem right — can you repeat?"
SALE_FAILED_PREFIX = "I couldn't finish that sale."

_GUARD_L2_BLOCK = """STRICT RULES — never break these:
- You only answer questions about: recording sales, checking stock levels, and store earnings.
- If asked about anything else (weather, news, sports, personal advice, general knowledge, coding):
  respond exactly: "I'm your store assistant. Ask me about sales, stock, or today's earnings."
- Never provide general knowledge, opinions, or answers outside the store domain.
- Never make up product prices or stock levels — only use the tool result provided to you.
- Keep all responses under 2 sentences. This is voice — no lists, no markdown."""


def _inventory_plain(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        lines.append(
            f"- {r['name']}: ₹{r['price']}, "
            f"stock {r['stock_qty']}, low-stock at {r['low_stock_threshold']}"
        )
    return "\n".join(lines)


def build_system_prompt(inventory_snapshot: str | list[dict]) -> str:
    """Persona + Layer‑2 guardrails + LIVE inventory snippet as plain text."""
    if isinstance(inventory_snapshot, str):
        snapshot = inventory_snapshot.strip()
    else:
        snapshot = _inventory_plain(inventory_snapshot)
    persona = (
        "You are Kirana AI, a concise polite voice assistant helping a kirana/SMB keeper. "
        "You relay tool facts only; speak in ₹ rupees spelled naturally for speech."
    )
    return (
        persona
        + "\n\n"
        + snapshot
        + "\n\n"
        + _GUARD_L2_BLOCK
    )


def build_context_block(parsed: dict[str, Any], tool_result: Any) -> str:
    """Structured situation summary for one turn (readable text, never JSON blobs)."""
    intent = parsed.get("intent", "unknown")
    lines = [f"Intent detected: {intent}"]
    if intent == "record_sale":
        items = parsed.get("matched_items") or []
        if items:
            pretty = ", ".join(f'{m.get("name", "?")} x{m.get("qty", "?")}' for m in items)
            lines.append(f"Items parsed: {pretty}")
        else:
            lines.append("Items parsed: (none)")
    qs = parsed.get("quantities")
    if isinstance(qs, list) and qs:
        parts = []
        for q in qs:
            if isinstance(q, dict):
                u = q.get("unit") or ""
                parts.append(f"{q.get('amount')}{(' ' + u) if u else ''}".strip())
        if parts:
            lines.append(f"Detected quantity tokens (preliminary): {'; '.join(parts)}.")
    if tool_result is None:
        lines.append("Tool result: (none — shopper likely greeted)")
    elif isinstance(tool_result, dict):
        if "batch_id" in tool_result:
            ib = []
            for it in tool_result.get("items") or []:
                ib.append(
                    f'{it["name"]} qty {it["qty"]}: line ₹{it["line_total"]}, '
                    f'stock now {it["remaining_stock"]}'
                )
            lines.append("Tool result: SALE")
            lines.append(f"Checkout total ₹{tool_result['total']}. Lines: {'; '.join(ib)}.")
        elif "transaction_count" in tool_result and "revenue" in tool_result:
            rev = tool_result["revenue"]
            tc = tool_result["transaction_count"]
            lines.append(
                "Tool result: TODAY_STATS "
                f"revenue ₹{rev}, checkout count {tc}."
            )
        else:
            lines.append(f"Tool result summary:\n{_tool_fallback_text(tool_result)}")
    elif isinstance(tool_result, list):
        lines.append("Tool result: LOW_STOCK_INVENTORY_LOOKUP")
        if not tool_result:
            lines.append("No products are flagged low/out right now.")
        else:
            for row in tool_result:
                nm = row.get("name")
                qty = row.get("stock_qty")
                th = row.get("low_stock_threshold")
                lines.append(f"- {nm}: units left {qty}, low threshold {th}")
    else:
        lines.append(f"Tool result: {tool_result}")
    return "\n".join(lines)


def _tool_fallback_text(d: dict) -> str:
    try:
        return json.dumps(d, ensure_ascii=False)[:1800]
    except Exception:
        return str(d)[:1800]


def _csv_detected(intent: str) -> str:
    return "off_topic" if intent == "unknown" else intent


async def _post_paytm(messages: list[dict[str, Any]]) -> str | None:
    key = os.getenv("PAYTM_API_KEY") or ""
    base = os.getenv("PAYTM_BASE_URL") or ""
    model = os.getenv("PAYTM_MODEL") or ""
    if not (key.strip() and base.strip() and model.strip()):
        return None
    path = os.getenv("PAYTM_CHAT_PATH", "").strip() or "/v1/chat/completions"
    url = base.rstrip("/") + (path if path.startswith("/") else "/" + path)
    headers = {
        "Authorization": f"Bearer {key.strip()}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model.strip(),
        "messages": messages,
        "max_tokens": min(int(os.getenv("PAYTM_MAX_TOKENS", "256")), 512),
        "temperature": float(os.getenv("PAYTM_TEMPERATURE", "0.2")),
    }
    timeout = float(os.getenv("PAYTM_TIMEOUT_SEC", "30"))
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return _extract_completion_text(data)


def _extract_completion_text(data: dict) -> str | None:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        if isinstance(data.get("output_text"), str):
            out = data["output_text"].strip()
            return out if out else None
        return None
    ch0 = choices[0]
    msg = ch0.get("message")
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, str):
            ct = content.strip()
            return ct if ct else None
        if isinstance(content, list):
            parts = []
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    t = blk.get("text") or ""
                    if isinstance(t, str):
                        parts.append(t)
            joined = "".join(parts).strip()
            return joined if joined else None
    if isinstance(ch0.get("text"), str):
        t = ch0["text"].strip()
        return t if t else None
    return None


def _threshold_map() -> dict[str, int]:
    return {
        row["name"]: int(row["low_stock_threshold"]) for row in get_inventory()
    }


def offline_voice_reply(
    *,
    transcript: str,
    parsed: dict[str, Any],
    tool_result: Any,
) -> str:
    """Deterministic narration when PAYTM_* is unavailable or POST fails."""
    intent = parsed.get("intent") or ""
    if intent == "greeting":
        return "Namaste — I'm Kirana AI. Say a sale anytime, ask today's earnings, or ask what's running low."
    if tool_result is None:
        return "How can I help with today's sales or stock?"
    if isinstance(tool_result, dict) and tool_result.get("batch_id"):
        total = tool_result["total"]
        thresh = _threshold_map()
        low_notes: list[str] = []
        for it in tool_result.get("items") or []:
            nm = it["name"]
            rem = it["remaining_stock"]
            thr = thresh.get(nm, 0)
            if rem <= thr:
                low_notes.append(nm)
        base = f"Sale recorded — total ₹{total}."
        if low_notes:
            base += (
                " Low stock warning on "
                + ", ".join(low_notes)
                + " — reorder soon."
            )
        else:
            base += " Stocks look fine."
        return base.replace("\n", " ")
    if isinstance(tool_result, dict) and (
        "revenue" in tool_result or "transaction_count" in tool_result
    ):
        rev = tool_result.get("revenue", 0)
        tc = tool_result.get("transaction_count", 0)
        return f"Today's revenue ₹{rev} rupees across {tc} checkout{'s' if tc != 1 else ''}."
    if isinstance(tool_result, list):
        if not tool_result:
            return "You're not low on anything right now."
        names = []
        for r in tool_result:
            qty = int(r["stock_qty"])
            label = (
                r["name"] + ", out of stock" if qty == 0 else f"{r['name']}, down to {qty} units"
            )
            names.append(label)
        return "Low-stock watch: " + "; ".join(names) + "."
    return offline_voice_reply(
        transcript=transcript,
        parsed={**parsed, "intent": "greeting"},
        tool_result=None,
    )


async def get_llm_response(
    transcript: str,
    parsed: dict[str, Any],
    tool_result: Any,
    session_id: str,
) -> str:
    history = get_recent_turns(session_id)
    inventory_rows = list(get_inventory())
    system_prompt = build_system_prompt(inventory_rows)

    msgs: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for row in history:
        u = row.get("user_transcript") or ""
        a = row.get("ai_response") or ""
        if u.strip():
            msgs.append({"role": "user", "content": u.strip()})
        if a.strip():
            msgs.append({"role": "assistant", "content": a.strip()})

    merged_user = (
        build_context_block(parsed, tool_result)
        + "\n\nThe shopper just said aloud (speech-to-text transcript):\n"
        + transcript
    )
    msgs.append({"role": "user", "content": merged_user})

    nl = await _post_paytm(msgs)
    if nl:
        out = nl.replace("\r", "").strip().replace("**", "")
        limit = os.getenv("PAYTM_HARD_CAP_CHARS")
        cap = int(limit) if (limit or "").strip().isdigit() else None
        if cap and len(out) > cap:
            return out[: cap - 3] + "…"
        return out
    return offline_voice_reply(
        transcript=transcript,
        parsed=parsed,
        tool_result=tool_result,
    )


async def route_and_respond(
    transcript: str,
    session_id: str,
    product_names: list[str],
) -> str:
    """Full turn: deterministic guardrails → tools → LLM → CSV log."""
    parsed = parse_transcript(transcript, product_names)

    intent = parsed.get("intent") or "unknown"
    matched = parsed.get("matched_items") or []

    def log_and_reply(reply: str, detected: str | None = None) -> str:
        tag = detected if detected is not None else _csv_detect(intent)
        log_turn(
            user_transcript=transcript.strip(),
            ai_response=reply,
            detected_intent=tag,
            session_id=session_id,
        )
        return reply

    # --- Guardrail Layer 1 ---
    if intent == "unknown":
        return log_and_reply(CANNED_OFF_TOPIC, "off_topic")

    if intent == "record_sale":
        if not matched:
            return log_and_reply(PRODUCT_UNCLEAR)
        if any((not isinstance(m.get("qty"), int)) or m.get("qty", 0) <= 0 for m in matched):
            return log_and_reply(BAD_QUANTITY)

    tool_result: Any = None

    try:
        if intent == "greeting":
            tool_result = None
        elif intent == "record_sale":
            tool_result = sales_tool.record_sale(parsed["matched_items"])
        elif intent == "get_stats":
            tool_result = sales_tool.get_today_sales()
        elif intent == "check_inventory":
            tool_result = inventory_tool.get_low_stock()
        else:
            return log_and_reply(CANNED_OFF_TOPIC, "off_topic")
    except ValueError as exc:
        err = (SALE_FAILED_PREFIX + " " + str(exc)).strip()
        return log_and_reply(err, _csv_detect(intent))

    llm_txt = await get_llm_response(
        transcript=transcript.strip(),
        parsed=parsed,
        tool_result=tool_result,
        session_id=session_id,
    )
    log_turn(transcript.strip(), llm_txt, intent, session_id)
    return llm_txt
