"""Deterministic transcript parsing — intent + quantities + inventory string matches."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

# Digit token + optional spoken unit chunk; `\b` avoids matching `500ml` quantities.
_QUANT_BODY = (
    r"\b(\d+)\s*"
    r"(packets? of|packets?|pieces? of|pieces?|pcs?\.|pcs\b|qty|units? of|units?\b)?"
)

QUANTITY_PATTERN = re.compile(_QUANT_BODY, re.IGNORECASE)


def _intent_order() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Transactional intents run before greetings (see roadmap Phase 4 table + smoke flows)."""
    return (
        (
            "record_sale",
            re.compile(
                r"\b(?:sold|sell|sells|selling|sale|sales|becha|diya)\b",
                re.I,
            ),
        ),
        (
            "check_inventory",
            re.compile(
                r"(?:"
                r"\bstocks?\b|"
                r"\binventory\b|"
                r"\bremaining\b|"
                r"\brunning\s+low\b|"
                r"\bout\s+of\s+stock\b|"
                r"\bleft\b|"
                r"\bkitna\s+hai\b|"
                r"\bbacha\b"
                r")",
                re.I,
            ),
        ),
        (
            "get_stats",
            re.compile(
                r"(?:"
                r"\bhow\s+much\b|"
                r"\bearnings?\b|"
                r"\brevenue\b|"
                r"\bmade\s+today\b|"
                r"\bprofit\b|"
                r"\bkitna\s+kamaya\b|"
                r"\bmoney\s+i\s+(?:made|earned)\b|"
                r"\btotal\b"
                r")",
                re.I,
            ),
        ),
        (
            "greeting",
            re.compile(
                r"(?:"
                r"(?:^\s*|(?<!\w))(?:h(?:i|ello|ey)|namaste|vanakkam)(?!\w)|"
                r"\bgood\s+(?:morning|afternoon|evening)\b"
                r")",
                re.I,
            ),
        ),
    )


def _greedy_quantities(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in QUANTITY_PATTERN.finditer(text):
        amt = int(m.group(1))
        unit_raw = (m.group(2) or "").strip() or None
        whole = text[m.start() : m.end()]
        out.append(
            {
                "amount": amt,
                "unit": unit_raw,
                "raw": whole,
                "position": m.start(),
                "span": (m.start(), m.end()),
            }
        )
    return out


def _date_placeholders(_text: str) -> list[str]:
    """Reserved — roadmap Phase 4 includes `dates`; empty for MVP."""
    return []


def _needle_variants(name: str) -> list[str]:
    """Full phrase plus substantive tokens (`Maggi` → `Maggi Noodles`)."""
    key = name.lower().strip()
    spaced = key.replace("-", " ").replace("_", " ")
    tokens = [t for t in spaced.split() if t]
    out: list[str] = []

    def add(s: str) -> None:
        if s not in out:
            out.append(s)

    add(key)
    for tok in sorted(tokens, key=len, reverse=True):
        if len(tok) >= 4:
            add(tok)
    hyphenated = spaced.replace(" ", "-")
    if hyphenated != key:
        add(hyphenated)
    return out


def _non_overlapping_product_hits(text: str, product_names: list[str]) -> list[dict[str, Any]]:
    if not text or not product_names:
        return []
    lower_txt = text.lower()

    cand: list[dict[str, Any]] = []
    ordered_names = sorted(set(product_names), key=lambda n: len(n), reverse=True)
    for name in ordered_names:
        for nd in _needle_variants(name):
            ln_needle = nd.lower()
            if len(ln_needle) < 2:
                continue
            idx = 0
            while True:
                hit = lower_txt.find(ln_needle, idx)
                if hit == -1:
                    break
                before = lower_txt[hit - 1] if hit > 0 else " "
                after = (
                    lower_txt[hit + len(ln_needle)]
                    if hit + len(ln_needle) < len(lower_txt)
                    else " "
                )
                if hit > 0 and (before.isalnum() or before == "_"):
                    idx = hit + 1
                    continue
                if hit + len(ln_needle) < len(lower_txt) and (
                    after.isalnum() or after == "_"
                ):
                    idx = hit + 1
                    continue
                cand.append(
                    {
                        "name": name,
                        "position": hit,
                        "end": hit + len(ln_needle),
                        "needle_len": len(ln_needle),
                    }
                )
                idx = hit + len(ln_needle)

    cand.sort(
        key=lambda c: (-c["needle_len"], -len(c["name"]), c["position"]),
    )
    used: list[tuple[int, int]] = []

    def overlaps(a: int, b: int) -> bool:
        for u0, u1 in used:
            if not (b <= u0 or a >= u1):
                return True
        return False

    kept: list[dict[str, Any]] = []
    for h in cand:
        a, b = h["position"], h["end"]
        if overlaps(a, b):
            continue
        used.append((a, b))
        kept.append({"name": h["name"], "position": h["position"], "end": b})
    kept.sort(key=lambda item: item["position"])
    return kept


def _nearest_qty_for_product(
    product_pos: int,
    qty_entries: list[dict[str, Any]],
) -> int | None:
    preceding = [q for q in qty_entries if q["position"] < product_pos]
    if preceding:
        return int(preceding[-1]["amount"])
    following = [q for q in qty_entries if q["position"] >= product_pos]
    if following:
        return int(following[0]["amount"])
    return None


def _matched_sale_items(
    product_hits: list[dict[str, Any]],
    qty_entries: list[dict[str, Any]],
) -> list[dict[str, int]]:
    matched: list[dict[str, int]] = []
    for h in product_hits:
        q = _nearest_qty_for_product(h["position"], qty_entries)
        if q is not None and q > 0:
            matched.append({"name": h["name"], "qty": q})
    return matched


def classify_intent(text: str) -> str:
    t = text.strip()
    if not t:
        return "unknown"
    for label, rx in _intent_order():
        if rx.search(t):
            return label
    return "unknown"


def parse_transcript(text: str, product_names: list[str] | None = None) -> dict[str, Any]:
    """Keys: intent, quantities, matched_items, dates, is_greeting, raw_text, timestamp."""
    raw_text = text or ""
    product_names = product_names or []
    now = datetime.now(timezone.utc).replace(microsecond=0)

    qty_entries = _greedy_quantities(raw_text)
    quantities_compact = [{"amount": q["amount"], "unit": q["unit"]} for q in qty_entries]

    intent = classify_intent(raw_text)

    matched_items: list[dict[str, int]] = []
    if intent == "record_sale":
        hits = _non_overlapping_product_hits(raw_text, product_names)
        matched_items = _matched_sale_items(hits, qty_entries)

    return {
        "intent": intent,
        "quantities": quantities_compact,
        "matched_items": matched_items,
        "dates": _date_placeholders(raw_text),
        "is_greeting": intent == "greeting",
        "raw_text": raw_text,
        "timestamp": now.isoformat(),
    }
