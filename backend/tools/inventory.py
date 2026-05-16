"""Inventory-facing tool wrappers (delegates to `db.database`)."""

from __future__ import annotations

from db.database import (
    decrement_stock as _db_decrement_stock,
    get_inventory as _db_get_inventory,
    get_low_stock as _db_get_low_stock,
    get_product as _db_get_product,
)


def get_inventory() -> list[dict]:
    return _db_get_inventory()


def get_low_stock() -> list[dict]:
    return _db_get_low_stock()


def decrement_stock(product_name: str, quantity: int) -> dict:
    """Decrement stock by name (case-insensitive). Returns updated inventory row as dict."""
    remaining = _db_decrement_stock(product_name, quantity)
    row = _db_get_product(product_name)
    if row is None:
        raise ValueError(f"Unknown product after update: {product_name!r}")
    out = dict(row)
    out["stock_qty"] = remaining
    return out
