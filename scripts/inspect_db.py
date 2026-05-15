#!/usr/bin/env python3
"""Inspect ThreadVault SQLite data without requiring the sqlite3 CLI."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "threadvault.sqlite3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print ThreadVault SQLite rows as JSON.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path")
    parser.add_argument(
        "--table",
        choices=["conversations", "ingest_events"],
        default="conversations",
    )
    parser.add_argument("--limit", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        print(json.dumps({"ok": False, "error": f"database not found: {db_path}"}))
        return 1

    limit = max(1, min(args.limit, 500))
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT * FROM {args.table} ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    print(
        json.dumps(
            {
                "ok": True,
                "db": str(db_path),
                "table": args.table,
                "count": len(rows),
                "rows": [dict(row) for row in rows],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
