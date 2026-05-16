"""SQLite persistence for Kirana AI (inventory + sales)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Literal

_Period = Literal["today", "this_week", "this_month"]

_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = _ROOT / "data"
DB_PATH = DATA_DIR / "kirana.db"

_SEED_ROWS: tuple[tuple[str, int, int, int, str], ...] = (
    ("Parle-G", 10, 20, 5, "Biscuits"),
    ("Good Day Biscuit", 30, 18, 5, "Biscuits"),
    ("Maggi Noodles", 14, 15, 5, "Instant food"),
    ("Amul Butter", 55, 8, 3, "Dairy"),
    ("Milk 500ml", 30, 14, 5, "Dairy"),
    ("Amul Cheese Slice", 65, 6, 2, "Dairy"),
    ("Tata Salt", 20, 12, 4, "Staples"),
    ("Aashirvaad Atta 1kg", 60, 10, 3, "Staples"),
    ("Fortune Sunflower Oil 1L", 180, 6, 2, "Staples"),
    ("Lays Classic", 20, 25, 8, "Snacks"),
    ("Kurkure Masala", 20, 22, 8, "Snacks"),
    ("Colgate 100g", 55, 10, 3, "Personal care"),
    ("Dettol Soap", 45, 12, 4, "Personal care"),
    ("Clinic Plus Shampoo", 3, 30, 10, "Personal care"),
    ("Thums Up 750ml", 45, 18, 5, "Beverages"),
)


def get_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            price INTEGER NOT NULL,
            stock_qty INTEGER NOT NULL,
            low_stock_threshold INTEGER NOT NULL,
            category TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            product_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price INTEGER NOT NULL,
            line_total INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_sales_timestamp ON sales (timestamp);
        CREATE INDEX IF NOT EXISTS idx_sales_batch ON sales (batch_id);
        """
    )


def _seed_inventory(conn: sqlite3.Connection) -> None:
    cur = conn.execute("SELECT COUNT(*) AS c FROM inventory")
    if cur.fetchone()["c"] > 0:
        return
    conn.executemany(
        """
        INSERT INTO inventory (name, price, stock_qty, low_stock_threshold, category)
        VALUES (?, ?, ?, ?, ?)
        """,
        _SEED_ROWS,
    )


def init_db() -> None:
    with get_conn() as conn:
        _ensure_schema(conn)
        _seed_inventory(conn)
        conn.commit()


def get_inventory() -> list[dict]:
    with get_conn() as conn:
        cur = conn.execute(
            """
            SELECT id, name, price, stock_qty, low_stock_threshold, category
            FROM inventory
            ORDER BY category, name
            """
        )
        return [dict(row) for row in cur.fetchall()]


def get_product(name: str) -> dict | None:
    with get_conn() as conn:
        cur = conn.execute(
            """
            SELECT id, name, price, stock_qty, low_stock_threshold, category
            FROM inventory
            WHERE name = ? COLLATE NOCASE
            """,
            (name.strip(),),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def decrement_stock(product_name: str, quantity: int) -> int:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    with get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE inventory
            SET stock_qty = stock_qty - ?
            WHERE name = ? COLLATE NOCASE AND stock_qty >= ?
            """,
            (quantity, product_name.strip(), quantity),
        )
        if cur.rowcount == 0:
            row = conn.execute(
                "SELECT id FROM inventory WHERE name = ? COLLATE NOCASE",
                (product_name.strip(),),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown product: {product_name!r}")
            raise ValueError(f"Insufficient stock for {product_name!r}")
        cur2 = conn.execute(
            """
            SELECT stock_qty FROM inventory WHERE name = ? COLLATE NOCASE
            """,
            (product_name.strip(),),
        )
        new_qty = int(cur2.fetchone()["stock_qty"])
        conn.commit()
        return new_qty


def get_low_stock() -> list[dict]:
    with get_conn() as conn:
        cur = conn.execute(
            """
            SELECT id, name, price, stock_qty, low_stock_threshold, category
            FROM inventory
            WHERE stock_qty <= low_stock_threshold
            ORDER BY stock_qty ASC, name
            """
        )
        return [dict(row) for row in cur.fetchall()]


def insert_sale(
    *,
    batch_id: str,
    timestamp: str,
    product_name: str,
    quantity: int,
    unit_price: int,
    line_total: int,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO sales (batch_id, timestamp, product_name, quantity, unit_price, line_total)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (batch_id, timestamp, product_name.strip(), quantity, unit_price, line_total),
        )
        conn.commit()


def get_sales_summary(period: _Period) -> dict[str, float | int]:
    if period == "today":
        where = "date(timestamp) = date('now', 'localtime')"
    elif period == "this_week":
        where = (
            "strftime('%G-%V', timestamp) = strftime('%G-%V', 'now', 'localtime')"
        )
    elif period == "this_month":
        where = (
            "strftime('%Y-%m', timestamp) = strftime('%Y-%m', 'now', 'localtime')"
        )
    else:
        raise ValueError(f"Unsupported period: {period!r}")

    sql = f"""
        SELECT
            COALESCE(SUM(line_total), 0) AS revenue,
            COUNT(DISTINCT batch_id) AS transaction_count
        FROM sales
        WHERE {where}
    """
    with get_conn() as conn:
        row = conn.execute(sql).fetchone()
        return {
            "revenue": int(row["revenue"]),
            "transaction_count": int(row["transaction_count"]),
        }
