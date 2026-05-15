# ThreadVault

ThreadVault is a minimal local backend for testing whether a custom ChatGPT GPT Action can send a near-complete conversation transcript to a server when the user says goodbye.

This is an experiment, not a production service. The implementation favors observability and simple inspection over a polished API.

## What It Measures

- Whether the GPT Action can send the transcript payload successfully.
- How complete the `messages` array and optional `raw_transcript` are.
- Request body size in bytes.
- Message count reported by the client versus messages received by the server.
- Approximate transcript character count and a rough token estimate.
- JSON parse failures and validation failures.

## Requirements

- Python 3.10 or newer.
- No third-party Python packages are required.
- SQLite is used through Python's standard library.

## Setup

```bash
cp .env.example .env
```

Edit `.env` and set a local API key:

```bash
THREADVAULT_API_KEY=replace-this-with-a-long-random-value
```

The server binds to `127.0.0.1` by default for local safety. You can configure `HOST` and `PORT` in `.env`.

Initialize the database:

```bash
python3 server.py --init-db
```

Run the server:

```bash
python3 server.py
```

By default the API listens at:

```text
http://127.0.0.1:8000
```

For the curl examples below, either replace `$THREADVAULT_API_KEY` with your key or load `.env` into your shell:

```bash
set -a
. ./.env
set +a
```

## API Key

All conversation API endpoints require this header:

```text
X-ThreadVault-Key: your-key-from-env
```

Requests without the key are rejected. The server does not log the API key.

## Endpoints

- `POST /api/conversations/save` saves a transcript payload.
- `GET /api/conversations` lists saved conversation metadata.
- `GET /api/conversations/:id` returns saved metadata and the full payload. `:id` can be the local numeric row id or a `conversation_id`.
- `GET /api/ingest-events` lists recent save attempts, including validation and JSON parse failures.
- `GET /health` returns a basic health response.
- `GET /openapi.yaml` and `GET /openapi.yml` return a generated OpenAPI schema using `PUBLIC_BASE_URL` when set.
- `GET /openapi.json` returns the same generated OpenAPI document as JSON.

## Small Curl Test

```bash
curl -sS \
  -X POST http://127.0.0.1:8000/api/conversations/save \
  -H "Content-Type: application/json" \
  -H "X-ThreadVault-Key: $THREADVAULT_API_KEY" \
  --data-binary @examples/small-transcript.json
```

List saved conversations:

```bash
curl -sS \
  -H "X-ThreadVault-Key: $THREADVAULT_API_KEY" \
  http://127.0.0.1:8000/api/conversations
```

Inspect one saved payload:

```bash
curl -sS \
  -H "X-ThreadVault-Key: $THREADVAULT_API_KEY" \
  http://127.0.0.1:8000/api/conversations/1
```

Check recent ingest failures:

```bash
curl -sS \
  -H "X-ThreadVault-Key: $THREADVAULT_API_KEY" \
  http://127.0.0.1:8000/api/ingest-events
```

When testing through ngrok, use the ngrok host for the same checks:

```bash
curl -sS https://your-ngrok-host/health
curl -sS -H "X-ThreadVault-Key: $THREADVAULT_API_KEY" https://your-ngrok-host/api/ingest-events
```

## Generate Larger Payloads

Create a fake transcript:

```bash
python3 scripts/generate_large_payload.py \
  --messages 100 \
  --chars-per-message 1000 \
  --output /tmp/threadvault-large.json
```

Send it:

```bash
curl -sS \
  -X POST http://127.0.0.1:8000/api/conversations/save \
  -H "Content-Type: application/json" \
  -H "X-ThreadVault-Key: $THREADVAULT_API_KEY" \
  --data-binary @/tmp/threadvault-large.json
```

To test increasing sizes, repeat with larger values:

```bash
python3 scripts/generate_large_payload.py --messages 250 --chars-per-message 2000 --output /tmp/threadvault-250x2000.json
python3 scripts/generate_large_payload.py --messages 500 --chars-per-message 4000 --output /tmp/threadvault-500x4000.json
```

Then send each file and compare:

- `request_body_size_bytes`
- `message_count`
- `client_reported_message_count`
- `total_transcript_chars`
- `approximate_token_estimate`
- HTTP status and any validation errors

## SQLite Inspection

The default database path is:

```text
data/threadvault.sqlite3
```

Inspect saved conversations:

```bash
python3 scripts/inspect_db.py --table conversations
```

Inspect ingest attempts, including parse or validation failures:

```bash
python3 scripts/inspect_db.py --table ingest_events
```

If you have the `sqlite3` CLI installed, you can also query the database directly:

```bash
sqlite3 data/threadvault.sqlite3 "select id, conversation_id, title, message_count, request_body_size_bytes, total_transcript_chars, created_at from conversations order by id desc;"
```

```bash
sqlite3 data/threadvault.sqlite3 "select id, conversation_row_id, request_body_size_bytes, message_count, json_parse_succeeded, validation_errors_json, created_at from ingest_events order by id desc;"
```

## OpenAPI And GPT Action Setup

The paste-ready schema is in `openapi.yaml`. The running server also exposes a live schema URL:

```text
http://127.0.0.1:8000/openapi.yaml
```

When using ngrok, use:

```text
https://your-ngrok-host/openapi.yaml
```

The schema exposes the save endpoint and the `X-ThreadVault-Key` API key security scheme.

For local-only testing, the server URL can stay:

```yaml
servers:
  - url: http://localhost:8000
```

For GPT Actions through ngrok, replace `servers[0].url` with the current public ngrok HTTPS URL.

In the GPT Actions editor:

1. Import the schema from `https://your-ngrok-host/openapi.yaml`, or paste `openapi.yaml`.
2. Confirm the server URL is the ngrok HTTPS URL.
3. Configure authentication as an API key.
4. Use header name `X-ThreadVault-Key`.
5. Use the same value as `THREADVAULT_API_KEY`.

## Ngrok

Start the local server first:

```bash
python3 server.py
```

In another terminal, expose the local port:

```bash
ngrok http 8000
```

Ngrok prints a public HTTPS forwarding URL, for example:

```text
https://example.ngrok-free.app
```

Set that URL in `.env` if you want `/openapi.yaml`, `/openapi.yml`, and `/openapi.json` to include it:

```bash
PUBLIC_BASE_URL=https://example.ngrok-free.app
```

Restart the server after changing `.env`.

Update `openapi.yaml` before pasting into the GPT Actions editor:

```yaml
servers:
  - url: https://example.ngrok-free.app
```

Ngrok exposes your local server to the internet. Keep `X-ThreadVault-Key` enabled even for testing. Free ngrok URLs may change between sessions unless you use a reserved domain.

## Payload Shape

`POST /api/conversations/save` accepts:

```json
{
  "conversation_id": "optional-client-id",
  "title": "Conversation title",
  "summary": "Optional summary",
  "messages": [
    {
      "role": "user",
      "content": "Message text",
      "index": 0,
      "approximate_timestamp": "2026-05-15T00:00:00Z"
    }
  ],
  "raw_transcript": "Optional plain transcript text",
  "source": "custom_gpt_action",
  "client_reported_message_count": 1,
  "notes_about_completeness": "Optional notes from the GPT"
}
```

Allowed message roles are `user`, `assistant`, `system`, `tool`, and `unknown`.

`source` is optional in practice. If the GPT Action omits it or sends a blank value, the server stores `custom_gpt_action`. If it sends another string, the server accepts and stores that string so source-format issues do not block transcript experiments.

## Known Limitations

- Local MVP only. No OAuth, user accounts, rate limits, or production hardening.
- The token estimate is approximate and uses `total_transcript_chars / 4`.
- There is no explicit server body-size limit. Practical limits will come from ChatGPT Actions, ngrok, local memory, and request timeouts.
- The server stores the full payload JSON in SQLite. Do not send secrets or private data unless you are comfortable saving it locally.
- Validation is intentionally simple. Unknown extra fields are preserved in `payload_json`.
- `raw_transcript` and message content are both counted in `total_transcript_chars`; if they contain duplicate text, the count reflects payload transcript text rather than unique conversation text.

## Expected Failure Modes To Test

- Missing or wrong `X-ThreadVault-Key` returns `401`.
- Invalid JSON returns `400` and creates an `ingest_events` row with `json_parse_succeeded = 0`.
- Missing required fields or invalid roles return `422` and create an `ingest_events` row with validation errors.
- Very large payloads may fail before reaching the server if ChatGPT Actions or ngrok applies a limit.
