"""Append-only conversation log for Kirana AI (CSV)."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = _ROOT / "data"
CSV_PATH = DATA_DIR / "conversations.csv"

FIELDNAMES = (
    "timestamp",
    "user_transcript",
    "ai_response",
    "detected_intent",
    "session_id",
)


def init_csv() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if CSV_PATH.exists():
        return
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(FIELDNAMES))
        writer.writeheader()


def log_turn(
    user_transcript: str,
    ai_response: str,
    detected_intent: str,
    session_id: str,
) -> None:
    init_csv()
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    row = {
        "timestamp": timestamp,
        "user_transcript": user_transcript,
        "ai_response": ai_response,
        "detected_intent": detected_intent,
        "session_id": session_id,
    }
    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(FIELDNAMES))
        writer.writerow(row)


def get_recent_turns(session_id: str, n: int = 5) -> list[dict[str, str]]:
    if not CSV_PATH.exists() or n <= 0:
        return []
    with CSV_PATH.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return []
    session_rows = [r for r in rows if r.get("session_id") == session_id]
    session_rows.sort(key=lambda r: r.get("timestamp", ""))
    return session_rows[-n:]
