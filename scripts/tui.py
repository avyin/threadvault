#!/usr/bin/env python3
"""Terminal UI for browsing ThreadVault SQLite data."""

from __future__ import annotations

import argparse
import curses
import json
import sqlite3
import textwrap
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "threadvault.sqlite3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Browse ThreadVault data in the terminal.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path")
    return parser.parse_args()


def fetch_conversations(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                id,
                conversation_id,
                title,
                summary,
                source,
                message_count,
                client_reported_message_count,
                message_content_chars,
                raw_transcript_chars,
                total_transcript_chars,
                approximate_token_estimate,
                request_body_size_bytes,
                created_at
            FROM conversations
            ORDER BY id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def fetch_conversation_payload(db_path: Path, row_id: int) -> dict[str, Any]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT payload_json FROM conversations WHERE id = ?",
            (row_id,),
        ).fetchone()
    if row is None:
        return {"error": f"conversation {row_id} not found"}
    return json.loads(row["payload_json"])


def fetch_ingest_events(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM ingest_events
            ORDER BY id DESC
            LIMIT 200
            """
        ).fetchall()

    events = []
    for row in rows:
        item = dict(row)
        try:
            item["validation_errors"] = json.loads(item.pop("validation_errors_json"))
        except json.JSONDecodeError:
            item["validation_errors"] = [item.pop("validation_errors_json")]
        item["json_parse_succeeded"] = bool(item["json_parse_succeeded"])
        events.append(item)
    return events


def ellipsize(value: Any, width: int) -> str:
    text = "" if value is None else str(value)
    if width <= 1:
        return text[:width]
    return text if len(text) <= width else text[: max(0, width - 3)] + "..."


def add_line(stdscr: curses.window, y: int, x: int, text: str, attr: int = 0) -> None:
    height, width = stdscr.getmaxyx()
    if y < 0 or y >= height or x >= width:
        return
    stdscr.addnstr(y, x, text, max(0, width - x - 1), attr)


def draw_header(stdscr: curses.window, db_path: Path, mode: str) -> int:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    title = f"ThreadVault TUI - {mode}"
    add_line(stdscr, 0, 0, title[: width - 1], curses.A_BOLD)
    add_line(stdscr, 1, 0, f"DB: {db_path}")
    add_line(
        stdscr,
        max(0, height - 1),
        0,
        "up/down move  Enter open  c conversations  e events  r refresh  b back  q quit",
        curses.A_DIM,
    )
    return 3


def draw_missing_db(stdscr: curses.window, db_path: Path) -> None:
    draw_header(stdscr, db_path, "missing database")
    add_line(stdscr, 4, 0, f"Database not found: {db_path}", curses.A_BOLD)
    add_line(stdscr, 6, 0, "Start the server or run: python3 server.py --init-db")
    stdscr.refresh()


def draw_conversations(
    stdscr: curses.window,
    db_path: Path,
    rows: list[dict[str, Any]],
    selected: int,
    top: int,
) -> None:
    start_y = draw_header(stdscr, db_path, f"conversations ({len(rows)})")
    add_line(
        stdscr,
        start_y,
        0,
        "ID   Msgs  Bytes    Chars    Created At             Title",
        curses.A_UNDERLINE,
    )

    height, width = stdscr.getmaxyx()
    visible = max(0, height - start_y - 2)
    for offset, row in enumerate(rows[top : top + visible]):
        index = top + offset
        attr = curses.A_REVERSE if index == selected else 0
        line = (
            f"{row['id']:<4} "
            f"{row['message_count']:<5} "
            f"{row['request_body_size_bytes']:<8} "
            f"{row['total_transcript_chars']:<8} "
            f"{ellipsize(row['created_at'], 22):<22} "
            f"{row['title']}"
        )
        add_line(stdscr, start_y + 1 + offset, 0, ellipsize(line, width - 1), attr)

    if not rows:
        add_line(stdscr, start_y + 2, 0, "No saved conversations yet.")

    stdscr.refresh()


def format_payload_view(metadata: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    lines = [
        f"Row ID: {metadata['id']}",
        f"Conversation ID: {metadata['conversation_id']}",
        f"Title: {metadata['title']}",
        f"Created: {metadata['created_at']}",
        f"Messages: {metadata['message_count']} reported={metadata['client_reported_message_count']}",
        f"Request bytes: {metadata['request_body_size_bytes']}",
        f"Transcript chars: {metadata['total_transcript_chars']}",
        f"Approx tokens: {metadata['approximate_token_estimate']}",
        "",
        "Payload:",
        json.dumps(payload, indent=2, ensure_ascii=False),
    ]
    return "\n".join(lines).splitlines()


def draw_detail(
    stdscr: curses.window,
    db_path: Path,
    metadata: dict[str, Any],
    payload: dict[str, Any],
    scroll: int,
) -> None:
    start_y = draw_header(stdscr, db_path, "conversation detail")
    lines = format_payload_view(metadata, payload)
    height, width = stdscr.getmaxyx()
    visible = max(0, height - start_y - 1)

    rendered: list[str] = []
    for line in lines:
        if not line:
            rendered.append("")
            continue
        rendered.extend(textwrap.wrap(line, width=max(20, width - 2)) or [""])

    for offset, line in enumerate(rendered[scroll : scroll + visible]):
        add_line(stdscr, start_y + offset, 0, line)
    stdscr.refresh()


def draw_events(
    stdscr: curses.window,
    db_path: Path,
    rows: list[dict[str, Any]],
    selected: int,
    top: int,
) -> None:
    start_y = draw_header(stdscr, db_path, f"ingest events ({len(rows)})")
    add_line(
        stdscr,
        start_y,
        0,
        "ID   Conv  JSON  Msgs  Bytes    Created At             Errors",
        curses.A_UNDERLINE,
    )

    height, width = stdscr.getmaxyx()
    visible = max(0, height - start_y - 2)
    for offset, row in enumerate(rows[top : top + visible]):
        index = top + offset
        attr = curses.A_REVERSE if index == selected else 0
        errors = "; ".join(row["validation_errors"])
        line = (
            f"{row['id']:<4} "
            f"{str(row['conversation_row_id'] or '-'): <5} "
            f"{str(row['json_parse_succeeded']):<5} "
            f"{row['message_count']:<5} "
            f"{row['request_body_size_bytes']:<8} "
            f"{ellipsize(row['created_at'], 22):<22} "
            f"{errors or 'ok'}"
        )
        add_line(stdscr, start_y + 1 + offset, 0, ellipsize(line, width - 1), attr)

    if not rows:
        add_line(stdscr, start_y + 2, 0, "No ingest events yet.")

    stdscr.refresh()


def keep_visible(selected: int, top: int, visible: int) -> int:
    if selected < top:
        return selected
    if selected >= top + visible:
        return selected - visible + 1
    return top


def run(stdscr: curses.window, db_path: Path) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)

    mode = "conversations"
    selected = 0
    top = 0
    detail_scroll = 0
    detail_metadata: dict[str, Any] | None = None
    detail_payload: dict[str, Any] | None = None

    conversations: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    def refresh_data() -> None:
        nonlocal conversations, events
        if db_path.exists():
            conversations = fetch_conversations(db_path)
            events = fetch_ingest_events(db_path)

    refresh_data()

    while True:
        if not db_path.exists():
            draw_missing_db(stdscr, db_path)
        elif mode == "conversations":
            visible = max(1, stdscr.getmaxyx()[0] - 5)
            top = keep_visible(selected, top, visible)
            draw_conversations(stdscr, db_path, conversations, selected, top)
        elif mode == "events":
            visible = max(1, stdscr.getmaxyx()[0] - 5)
            top = keep_visible(selected, top, visible)
            draw_events(stdscr, db_path, events, selected, top)
        elif detail_metadata is not None and detail_payload is not None:
            draw_detail(stdscr, db_path, detail_metadata, detail_payload, detail_scroll)

        key = stdscr.getch()
        active_rows = conversations if mode == "conversations" else events

        if key in (ord("q"), 27):
            return
        if key == ord("r"):
            refresh_data()
            selected = min(selected, max(0, len(active_rows) - 1))
            continue
        if key == ord("c"):
            mode = "conversations"
            selected = 0
            top = 0
            detail_scroll = 0
            continue
        if key == ord("e"):
            mode = "events"
            selected = 0
            top = 0
            detail_scroll = 0
            continue
        if key == ord("b"):
            mode = "conversations"
            detail_scroll = 0
            continue

        if mode == "detail":
            if key in (curses.KEY_UP, ord("k")):
                detail_scroll = max(0, detail_scroll - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                detail_scroll += 1
            elif key in (curses.KEY_NPAGE, ord(" ")):
                detail_scroll += max(1, stdscr.getmaxyx()[0] - 5)
            elif key == curses.KEY_PPAGE:
                detail_scroll = max(0, detail_scroll - max(1, stdscr.getmaxyx()[0] - 5))
            continue

        if key in (curses.KEY_UP, ord("k")):
            selected = max(0, selected - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            selected = min(max(0, len(active_rows) - 1), selected + 1)
        elif key in (curses.KEY_ENTER, 10, 13) and mode == "conversations" and conversations:
            detail_metadata = conversations[selected]
            detail_payload = fetch_conversation_payload(db_path, int(detail_metadata["id"]))
            detail_scroll = 0
            mode = "detail"


def main() -> int:
    args = parse_args()
    curses.wrapper(run, Path(args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
