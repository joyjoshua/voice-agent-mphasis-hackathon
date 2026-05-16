"""Sales-facing tool wrappers (delegates to `db.database`)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from db.database import (
    decrement_stock as _db_decrement_stock,
    get_product as _db_get_product,
    get_sales_summary as _db_get_sales_summary,
    insert_sale as _db_insert_sale,
)


def get_today_sales() -> dict[str, int]:
    """Today's revenue (`revenue`) and distinct checkout count (`transaction_count`)."""
    return dict(_db_get_sales_summary("today"))


def record_sale(items: list[dict]) -> dict:
    """Persist line items (`name`, `qty`) under one checkout batch then decrement inventory.

    Returns per-line detail plus `batch_id`, `timestamp`, and `total` (sum of line totals).
    Raises `ValueError` for unknown products or insufficient stock.
    """
    if not items:
        raise ValueError("no sale items")

    batch_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    lines_out: list[dict] = []
    total = 0

    for raw in items:
        name = (raw.get("name") if isinstance(raw, dict) else None) or ""
        qty = raw.get("qty") if isinstance(raw, dict) else None
        if qty is None or not isinstance(qty, int):
            raise ValueError("each sale line needs integer qty")
        if qty <= 0:
            raise ValueError(f"quantity must be positive for {name!r}")

        row = _db_get_product(name)
        if row is None:
            raise ValueError(f"Unknown product: {name!r}")

        price = int(row["price"])
        line_total = price * qty
        canonical = row["name"]

        _db_insert_sale(
            batch_id=batch_id,
            timestamp=ts,
            product_name=canonical,
            quantity=qty,
            unit_price=price,
            line_total=line_total,
        )
        remaining = _db_decrement_stock(canonical, qty)
        lines_out.append(
            {
                "name": canonical,
                "qty": qty,
                "unit_price": price,
                "line_total": line_total,
                "remaining_stock": remaining,
            }
        )
        total += line_total

    return {
        "batch_id": batch_id,
        "timestamp": ts,
        "items": lines_out,
        "total": total,
    }
