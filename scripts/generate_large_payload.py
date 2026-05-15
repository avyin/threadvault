#!/usr/bin/env python3
"""Generate a fake ThreadVault transcript payload."""

from __future__ import annotations

import argparse
import json
import sys
import uuid


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write a fake ThreadVault conversation payload to stdout."
    )
    parser.add_argument("--messages", type=int, default=100, help="number of messages")
    parser.add_argument(
        "--chars-per-message",
        type=int,
        default=1000,
        help="approximate content characters per message",
    )
    parser.add_argument("--title", default="Large fake transcript")
    parser.add_argument("--conversation-id", default=None)
    parser.add_argument(
        "--output",
        default="-",
        help='output path, or "-" for stdout',
    )
    parser.add_argument(
        "--include-raw-transcript",
        action="store_true",
        help="also include a raw_transcript string built from all messages",
    )
    return parser.parse_args()


def repeated_text(target_chars: int, seed: int) -> str:
    base = (
        f"Message {seed}: This is synthetic transcript text for payload limit testing. "
        "It intentionally repeats predictable words so size is easy to control. "
    )
    repeats = (target_chars // len(base)) + 1
    return (base * repeats)[:target_chars]


def main() -> int:
    args = parse_args()
    if args.messages < 0:
        print("--messages must be non-negative", file=sys.stderr)
        return 2
    if args.chars_per_message < 0:
        print("--chars-per-message must be non-negative", file=sys.stderr)
        return 2

    messages = []
    for index in range(args.messages):
        role = "user" if index % 2 == 0 else "assistant"
        messages.append(
            {
                "role": role,
                "content": repeated_text(args.chars_per_message, index),
                "index": index,
            }
        )

    payload = {
        "conversation_id": args.conversation_id or f"fake-{uuid.uuid4()}",
        "title": args.title,
        "summary": "Synthetic transcript generated for ThreadVault limit testing.",
        "messages": messages,
        "source": "custom_gpt_action",
        "client_reported_message_count": len(messages),
        "notes_about_completeness": (
            "Generated locally. Increase --messages or --chars-per-message to test larger bodies."
        ),
    }

    if args.include_raw_transcript:
        payload["raw_transcript"] = "\n\n".join(
            f"{message['role']}: {message['content']}" for message in messages
        )

    if args.output == "-":
        json.dump(payload, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
