#!/usr/bin/env python3
"""Summarize what data was captured in saved ThreadVault conversations."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "threadvault.sqlite3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze saved ThreadVault capture payloads.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path")
    parser.add_argument("--id", type=int, default=None, help="analyze one local row id")
    parser.add_argument("--limit", type=int, default=20, help="maximum rows to analyze")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    return parser.parse_args()


def load_rows(db_path: Path, row_id: int | None, limit: int) -> list[sqlite3.Row]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if row_id is not None:
            return conn.execute(
                "SELECT * FROM conversations WHERE id = ?",
                (row_id,),
            ).fetchall()

        return conn.execute(
            """
            SELECT *
            FROM conversations
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 500)),),
        ).fetchall()


def message_role_counts(messages: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for message in messages:
        if not isinstance(message, dict):
            role = "invalid"
        else:
            role = str(message.get("role", "missing"))
        counts[role] = counts.get(role, 0) + 1
    return counts


def count_messages_with_field(messages: list[Any], field: str) -> int:
    return sum(
        1
        for message in messages
        if isinstance(message, dict) and message.get(field) not in (None, "")
    )


def analyze_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(row["payload_json"])
    messages = payload.get("messages")
    if not isinstance(messages, list):
        messages = []

    capture_report = payload.get("capture_report")
    if not isinstance(capture_report, dict):
        capture_report = {}

    raw_transcript = payload.get("raw_transcript")
    notes = payload.get("notes_about_completeness")

    role_counts = message_role_counts(messages)
    fields_present = {
        "conversation_id": bool(payload.get("conversation_id")),
        "title": bool(payload.get("title")),
        "summary": bool(payload.get("summary")),
        "messages": bool(messages),
        "raw_transcript": isinstance(raw_transcript, str) and bool(raw_transcript),
        "source": bool(payload.get("source")),
        "client_reported_message_count": isinstance(
            payload.get("client_reported_message_count"), int
        ),
        "notes_about_completeness": isinstance(notes, str) and bool(notes),
        "capture_report": bool(capture_report),
    }

    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "request_body_size_bytes": row["request_body_size_bytes"],
        "message_count": row["message_count"],
        "client_reported_message_count": row["client_reported_message_count"],
        "message_role_counts": role_counts,
        "messages_with_index": count_messages_with_field(messages, "index"),
        "messages_with_approximate_timestamp": count_messages_with_field(
            messages, "approximate_timestamp"
        ),
        "message_content_chars": row["message_content_chars"],
        "raw_transcript_chars": row["raw_transcript_chars"],
        "total_transcript_chars": row["total_transcript_chars"],
        "approximate_token_estimate": row["approximate_token_estimate"],
        "percent_of_100k_action_limit": round(
            (row["request_body_size_bytes"] / 100000) * 100,
            2,
        ),
        "fields_present": fields_present,
        "capture_report": capture_report,
        "notes_about_completeness": notes,
    }


def print_human(items: list[dict[str, Any]]) -> None:
    if not items:
        print("No saved conversations found.")
        return

    for item in items:
        print(f"#{item['id']} {item['title']}")
        print(f"  conversation_id: {item['conversation_id']}")
        print(f"  created_at: {item['created_at']}")
        print(
            "  size: "
            f"{item['request_body_size_bytes']} bytes "
            f"({item['percent_of_100k_action_limit']}% of 100k Action limit)"
        )
        print(
            "  messages: "
            f"{item['message_count']} saved, "
            f"{item['client_reported_message_count']} client-reported, "
            f"roles={item['message_role_counts']}"
        )
        print(
            "  transcript chars: "
            f"messages={item['message_content_chars']} "
            f"raw={item['raw_transcript_chars']} "
            f"total={item['total_transcript_chars']} "
            f"tokens~={item['approximate_token_estimate']}"
        )
        print(
            "  message fields: "
            f"index={item['messages_with_index']} "
            f"approx_timestamp={item['messages_with_approximate_timestamp']}"
        )
        present = ", ".join(
            name for name, exists in item["fields_present"].items() if exists
        )
        missing = ", ".join(
            name for name, exists in item["fields_present"].items() if not exists
        )
        print(f"  present fields: {present or 'none'}")
        print(f"  missing fields: {missing or 'none'}")
        if item["capture_report"]:
            print("  capture_report:")
            for key, value in item["capture_report"].items():
                print(f"    {key}: {value}")
        if item["notes_about_completeness"]:
            print(f"  notes: {item['notes_about_completeness']}")
        print()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return 1

    rows = load_rows(db_path, args.id, args.limit)
    items = [analyze_row(row) for row in rows]
    if args.json:
        print(json.dumps({"ok": True, "count": len(items), "items": items}, indent=2))
    else:
        print_human(items)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
