#!/usr/bin/env python3
"""Minimal local ThreadVault backend."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = ROOT / "data" / "threadvault.sqlite3"
ALLOWED_ROLES = {"user", "assistant", "system", "tool", "unknown"}
REQUIRED_SOURCE = "custom_gpt_action"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_event(event: str, **fields: Any) -> None:
    record = {"event": event, "at": utc_now(), **fields}
    print(json.dumps(record, separators=(",", ":")), flush=True)


def connect_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path) -> None:
    with connect_db(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT,
                source TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                message_count INTEGER NOT NULL,
                client_reported_message_count INTEGER NOT NULL,
                message_content_chars INTEGER NOT NULL,
                raw_transcript_chars INTEGER NOT NULL,
                total_transcript_chars INTEGER NOT NULL,
                approximate_token_estimate INTEGER NOT NULL,
                request_body_size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_conversations_conversation_id
                ON conversations(conversation_id);

            CREATE TABLE IF NOT EXISTS ingest_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_row_id INTEGER,
                request_body_size_bytes INTEGER NOT NULL,
                message_count INTEGER NOT NULL,
                total_transcript_chars INTEGER NOT NULL,
                json_parse_succeeded INTEGER NOT NULL,
                validation_errors_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(conversation_row_id) REFERENCES conversations(id)
            );
            """
        )


def row_to_metadata(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "title": row["title"],
        "summary": row["summary"],
        "source": row["source"],
        "message_count": row["message_count"],
        "client_reported_message_count": row["client_reported_message_count"],
        "message_content_chars": row["message_content_chars"],
        "raw_transcript_chars": row["raw_transcript_chars"],
        "total_transcript_chars": row["total_transcript_chars"],
        "approximate_token_estimate": row["approximate_token_estimate"],
        "request_body_size_bytes": row["request_body_size_bytes"],
        "created_at": row["created_at"],
    }


def validate_payload(payload: Any) -> list[str]:
    errors: list[str] = []

    if not isinstance(payload, dict):
        return ["payload must be a JSON object"]

    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append("title is required and must be a non-empty string")

    conversation_id = payload.get("conversation_id")
    if conversation_id is not None and not isinstance(conversation_id, str):
        errors.append("conversation_id must be a string when provided")

    summary = payload.get("summary")
    if summary is not None and not isinstance(summary, str):
        errors.append("summary must be a string when provided")

    raw_transcript = payload.get("raw_transcript")
    if raw_transcript is not None and not isinstance(raw_transcript, str):
        errors.append("raw_transcript must be a string when provided")

    source = payload.get("source")
    if source is not None and not isinstance(source, str):
        errors.append("source must be a string when provided")

    reported_count = payload.get("client_reported_message_count")
    if not isinstance(reported_count, int) or isinstance(reported_count, bool):
        errors.append("client_reported_message_count is required and must be an integer")

    notes = payload.get("notes_about_completeness")
    if notes is not None and not isinstance(notes, str):
        errors.append("notes_about_completeness must be a string when provided")

    messages = payload.get("messages")
    if not isinstance(messages, list):
        errors.append("messages is required and must be an array")
        return errors

    for pos, message in enumerate(messages):
        if not isinstance(message, dict):
            errors.append(f"messages[{pos}] must be an object")
            continue

        role = message.get("role")
        if role not in ALLOWED_ROLES:
            errors.append(
                f"messages[{pos}].role must be one of: {', '.join(sorted(ALLOWED_ROLES))}"
            )

        content = message.get("content")
        if not isinstance(content, str):
            errors.append(f"messages[{pos}].content is required and must be a string")

        index = message.get("index")
        if index is not None and (not isinstance(index, int) or isinstance(index, bool)):
            errors.append(f"messages[{pos}].index must be an integer when provided")

        approximate_timestamp = message.get("approximate_timestamp")
        if approximate_timestamp is not None and not isinstance(approximate_timestamp, str):
            errors.append(
                f"messages[{pos}].approximate_timestamp must be a string when provided"
            )

    return errors


def transcript_metrics(payload: Any) -> tuple[int, int, int, int]:
    if not isinstance(payload, dict):
        return 0, 0, 0, 0

    messages = payload.get("messages")
    if not isinstance(messages, list):
        messages = []

    message_count = len(messages)
    message_content_chars = 0
    for message in messages:
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            message_content_chars += len(message["content"])

    raw_transcript = payload.get("raw_transcript")
    raw_transcript_chars = len(raw_transcript) if isinstance(raw_transcript, str) else 0
    total_transcript_chars = message_content_chars + raw_transcript_chars
    return message_count, message_content_chars, raw_transcript_chars, total_transcript_chars


def insert_ingest_event(
    db_path: Path,
    *,
    conversation_row_id: int | None,
    request_body_size_bytes: int,
    message_count: int,
    total_transcript_chars: int,
    json_parse_succeeded: bool,
    validation_errors: list[str],
) -> None:
    with connect_db(db_path) as conn:
        conn.execute(
            """
            INSERT INTO ingest_events (
                conversation_row_id,
                request_body_size_bytes,
                message_count,
                total_transcript_chars,
                json_parse_succeeded,
                validation_errors_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_row_id,
                request_body_size_bytes,
                message_count,
                total_transcript_chars,
                1 if json_parse_succeeded else 0,
                json.dumps(validation_errors),
                utc_now(),
            ),
        )


def save_conversation(
    db_path: Path,
    payload: dict[str, Any],
    request_body_size_bytes: int,
) -> tuple[int, dict[str, Any]]:
    message_count, message_chars, raw_chars, total_chars = transcript_metrics(payload)
    token_estimate = ((total_chars + 3) // 4) if total_chars else 0
    conversation_id = payload.get("conversation_id") or f"local-{uuid.uuid4()}"
    source = payload.get("source")
    if not isinstance(source, str) or not source.strip():
        source = REQUIRED_SOURCE
    created_at = utc_now()

    with connect_db(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO conversations (
                conversation_id,
                title,
                summary,
                source,
                payload_json,
                message_count,
                client_reported_message_count,
                message_content_chars,
                raw_transcript_chars,
                total_transcript_chars,
                approximate_token_estimate,
                request_body_size_bytes,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                payload["title"],
                payload.get("summary"),
                source,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                message_count,
                payload["client_reported_message_count"],
                message_chars,
                raw_chars,
                total_chars,
                token_estimate,
                request_body_size_bytes,
                created_at,
            ),
        )
        row_id = int(cursor.lastrowid)

    return row_id, {
        "id": row_id,
        "conversation_id": conversation_id,
        "message_count": message_count,
        "message_content_chars": message_chars,
        "raw_transcript_chars": raw_chars,
        "total_transcript_chars": total_chars,
        "approximate_token_estimate": token_estimate,
        "request_body_size_bytes": request_body_size_bytes,
        "created_at": created_at,
    }


def build_openapi_document(public_base_url: str) -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "ThreadVault Local Action API",
            "version": "0.1.0",
            "description": "Minimal API for saving a custom GPT conversation transcript.",
        },
        "servers": [{"url": public_base_url}],
        "paths": {
            "/api/conversations/save": {
                "post": {
                    "operationId": "saveConversationTranscript",
                    "summary": "Save a conversation transcript",
                    "security": [{"ThreadVaultKey": []}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ConversationSaveRequest"}
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Conversation saved",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "ok": {"type": "boolean"},
                                            "id": {"type": "integer"},
                                            "conversation_id": {"type": "string"},
                                            "message_count": {"type": "integer"},
                                            "total_transcript_chars": {"type": "integer"},
                                            "approximate_token_estimate": {"type": "integer"},
                                            "request_body_size_bytes": {"type": "integer"},
                                        },
                                    }
                                }
                            },
                        },
                        "401": {"description": "Missing or invalid API key"},
                        "422": {"description": "Validation failed"},
                    },
                }
            }
        },
        "components": {
            "securitySchemes": {
                "ThreadVaultKey": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-ThreadVault-Key",
                }
            },
            "schemas": {
                "ConversationMessage": {
                    "type": "object",
                    "required": ["role", "content"],
                    "properties": {
                        "role": {
                            "type": "string",
                            "enum": ["user", "assistant", "system", "tool", "unknown"],
                        },
                        "content": {"type": "string"},
                        "index": {"type": "integer"},
                        "approximate_timestamp": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
                "ConversationSaveRequest": {
                    "type": "object",
                    "required": [
                        "title",
                        "messages",
                        "client_reported_message_count",
                    ],
                    "properties": {
                        "conversation_id": {"type": "string"},
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "messages": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/ConversationMessage"},
                        },
                        "raw_transcript": {"type": "string"},
                        "source": {
                            "type": "string",
                            "default": REQUIRED_SOURCE,
                            "description": (
                                "Optional source marker. The server defaults this to "
                                "custom_gpt_action when omitted."
                            ),
                        },
                        "client_reported_message_count": {"type": "integer"},
                        "notes_about_completeness": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
            },
        },
    }


def build_openapi_yaml(public_base_url: str) -> str:
    return f"""openapi: 3.1.0
info:
  title: ThreadVault Local Action API
  version: 0.1.0
  description: Minimal API for saving a custom GPT conversation transcript.
servers:
  - url: {public_base_url}
paths:
  /api/conversations/save:
    post:
      operationId: saveConversationTranscript
      summary: Save a conversation transcript
      security:
        - ThreadVaultKey: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/ConversationSaveRequest"
      responses:
        "200":
          description: Conversation saved
          content:
            application/json:
              schema:
                type: object
                properties:
                  ok:
                    type: boolean
                  id:
                    type: integer
                  conversation_id:
                    type: string
                  message_count:
                    type: integer
                  total_transcript_chars:
                    type: integer
                  approximate_token_estimate:
                    type: integer
                  request_body_size_bytes:
                    type: integer
        "401":
          description: Missing or invalid API key
        "422":
          description: Validation failed
components:
  securitySchemes:
    ThreadVaultKey:
      type: apiKey
      in: header
      name: X-ThreadVault-Key
  schemas:
    ConversationMessage:
      type: object
      required:
        - role
        - content
      properties:
        role:
          type: string
          enum:
            - user
            - assistant
            - system
            - tool
            - unknown
        content:
          type: string
        index:
          type: integer
        approximate_timestamp:
          type: string
      additionalProperties: true
    ConversationSaveRequest:
      type: object
      required:
        - title
        - messages
        - client_reported_message_count
      properties:
        conversation_id:
          type: string
        title:
          type: string
        summary:
          type: string
        messages:
          type: array
          items:
            $ref: "#/components/schemas/ConversationMessage"
        raw_transcript:
          type: string
        source:
          type: string
          default: custom_gpt_action
          description: Optional source marker. The server defaults this to custom_gpt_action when omitted.
        client_reported_message_count:
          type: integer
        notes_about_completeness:
          type: string
      additionalProperties: true
"""


class ThreadVaultHandler(BaseHTTPRequestHandler):
    server_version = "ThreadVault/0.1"

    @property
    def db_path(self) -> Path:
        return self.server.db_path  # type: ignore[attr-defined]

    @property
    def api_key(self) -> str:
        return self.server.api_key  # type: ignore[attr-defined]

    @property
    def public_base_url(self) -> str:
        return self.server.public_base_url  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/health":
            self.send_json(HTTPStatus.OK, {"ok": True})
            return

        if parsed.path == "/openapi.json":
            self.send_json(HTTPStatus.OK, build_openapi_document(self.public_base_url))
            return

        if parsed.path in {"/openapi.yaml", "/openapi.yml"}:
            self.send_text(
                HTTPStatus.OK,
                build_openapi_yaml(self.public_base_url),
                "application/yaml; charset=utf-8",
            )
            return

        if not self.authorized():
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "missing or invalid API key"})
            return

        if parsed.path == "/api/conversations":
            self.list_conversations(parsed.query)
            return

        prefix = "/api/conversations/"
        if parsed.path.startswith(prefix):
            conversation_ref = parsed.path[len(prefix) :].strip("/")
            if conversation_ref:
                self.get_conversation(conversation_ref)
                return

        self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/conversations/save":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        if not self.authorized():
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "missing or invalid API key"})
            return

        body = self.read_body()
        if body is None:
            return

        request_body_size = len(body)
        try:
            payload = json.loads(body.decode("utf-8"))
            json_parse_succeeded = True
            parse_error = None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            payload = None
            json_parse_succeeded = False
            parse_error = f"invalid JSON: {exc}"

        message_count, _, _, total_chars = transcript_metrics(payload)
        validation_errors = [parse_error] if parse_error else validate_payload(payload)

        if validation_errors:
            insert_ingest_event(
                self.db_path,
                conversation_row_id=None,
                request_body_size_bytes=request_body_size,
                message_count=message_count,
                total_transcript_chars=total_chars,
                json_parse_succeeded=json_parse_succeeded,
                validation_errors=validation_errors,
            )
            log_event(
                "conversation_save_rejected",
                request_body_size_bytes=request_body_size,
                message_count=message_count,
                total_transcript_chars=total_chars,
                json_parse_succeeded=json_parse_succeeded,
                validation_error_count=len(validation_errors),
            )
            status = HTTPStatus.BAD_REQUEST if not json_parse_succeeded else HTTPStatus.UNPROCESSABLE_ENTITY
            self.send_json(status, {"ok": False, "validation_errors": validation_errors})
            return

        assert isinstance(payload, dict)
        row_id, metadata = save_conversation(self.db_path, payload, request_body_size)
        insert_ingest_event(
            self.db_path,
            conversation_row_id=row_id,
            request_body_size_bytes=request_body_size,
            message_count=metadata["message_count"],
            total_transcript_chars=metadata["total_transcript_chars"],
            json_parse_succeeded=True,
            validation_errors=[],
        )
        log_event("conversation_saved", **metadata)
        self.send_json(HTTPStatus.OK, {"ok": True, **metadata})

    def read_body(self) -> bytes | None:
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            self.send_json(HTTPStatus.LENGTH_REQUIRED, {"error": "Content-Length is required"})
            return None

        try:
            length = int(content_length)
        except ValueError:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Content-Length must be an integer"})
            return None

        if length < 0:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Content-Length must be non-negative"})
            return None

        return self.rfile.read(length)

    def authorized(self) -> bool:
        supplied = self.headers.get("X-ThreadVault-Key")
        return supplied == self.api_key

    def list_conversations(self, query: str) -> None:
        params = parse_qs(query)
        try:
            limit = int(params.get("limit", ["50"])[0])
        except ValueError:
            limit = 50
        limit = max(1, min(limit, 500))

        with connect_db(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM conversations
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        self.send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "count": len(rows),
                "conversations": [row_to_metadata(row) for row in rows],
            },
        )

    def get_conversation(self, conversation_ref: str) -> None:
        with connect_db(self.db_path) as conn:
            if conversation_ref.isdigit():
                row = conn.execute(
                    "SELECT * FROM conversations WHERE id = ?",
                    (int(conversation_ref),),
                ).fetchone()
                if row is None:
                    row = conn.execute(
                        """
                        SELECT *
                        FROM conversations
                        WHERE conversation_id = ?
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (conversation_ref,),
                    ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT *
                    FROM conversations
                    WHERE conversation_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (conversation_ref,),
                ).fetchone()

        if row is None:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "conversation not found"})
            return

        self.send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "conversation": row_to_metadata(row),
                "payload": json.loads(row["payload_json"]),
            },
        )

    def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, status: HTTPStatus, text: str, content_type: str) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        log_event(
            "http_request",
            client=self.client_address[0],
            request=fmt % args,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local ThreadVault backend.")
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="initialize the SQLite database and exit",
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = parse_args()

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    api_key = os.environ.get("THREADVAULT_API_KEY", "")
    public_base_url = os.environ.get("PUBLIC_BASE_URL") or f"http://{host}:{port}"
    db_path = Path(os.environ.get("THREADVAULT_DB_PATH", str(DEFAULT_DB_PATH))).expanduser()

    if not api_key:
        print(
            "THREADVAULT_API_KEY is required. Copy .env.example to .env or set it in the shell.",
            file=sys.stderr,
        )
        return 2

    init_db(db_path)
    if args.init_db:
        print(f"Initialized SQLite database at {db_path}")
        return 0

    server = ThreadingHTTPServer((host, port), ThreadVaultHandler)
    server.db_path = db_path  # type: ignore[attr-defined]
    server.api_key = api_key  # type: ignore[attr-defined]
    server.public_base_url = public_base_url.rstrip("/")  # type: ignore[attr-defined]

    log_event("server_started", host=host, port=port, db_path=str(db_path))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log_event("server_stopped")
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
