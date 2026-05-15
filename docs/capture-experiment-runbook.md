# Capture Experiment Runbook

Date: 2026-05-15

## Objective

Measure which conversation data a Custom GPT can actually send to ThreadVault through a GPT Action.

This follows the recommendation in `docs/conversation-capture-research.md`: treat GPT Action transcript saving as an empirical capability test, not as a guaranteed authoritative export.

## What To Capture

For each test conversation, record whether the saved payload includes:

- user messages;
- assistant messages;
- system/developer-style messages, if any are visible to the GPT;
- tool/action messages, if any are visible to the GPT;
- message order/indexes;
- timestamps or approximate timestamps;
- attached file references;
- image references or descriptions;
- raw transcript text;
- summary;
- the beginning of the conversation;
- the end of the conversation;
- model-reported omissions or inaccessible content.

## GPT Instructions To Add

Add this to the Custom GPT instructions while testing:

```text
When the user says goodbye, calls "save", or asks you to preserve the conversation, call saveConversationTranscript.

Include every visible user and assistant message you can access in chronological order.

For each message, include:
- role
- exact content if visible
- index starting at 0
- approximate_timestamp if you know one

Also include raw_transcript when possible.

Include capture_report with:
- visible_message_count
- included_message_count
- visible_user_message_count
- visible_assistant_message_count
- included_roles
- included_system_messages
- included_tool_messages
- included_timestamps
- included_files_or_images
- included_raw_transcript
- conversation_start_visible
- conversation_end_visible
- capture_confidence: high, medium, low, or unknown
- known_omissions
- inaccessible_content_notes

If you cannot access exact text, say so in notes_about_completeness and capture_report.known_omissions.
```

## Setup

Start ThreadVault:

```bash
python3 server.py
```

Expose it with ngrok:

```bash
ngrok http 8000
```

Set `PUBLIC_BASE_URL` in `.env` to the ngrok HTTPS URL and restart the server:

```bash
PUBLIC_BASE_URL=https://YOUR-NGROK-HOST
```

Import this schema URL in the GPT Action editor:

```text
https://YOUR-NGROK-HOST/openapi.yaml
```

Configure authentication:

- Type: API key
- Location: custom header
- Header name: `X-ThreadVault-Key`
- Value: your `THREADVAULT_API_KEY`

Verify the live server:

```bash
curl -sS https://YOUR-NGROK-HOST/health
```

Expected:

```json
{
  "ok": true,
  "version": "0.2.0",
  "source_validation": "optional"
}
```

## Test Matrix

Run these as separate conversations with the Custom GPT:

| Test | Conversation Shape | Goodbye Prompt | What To Check |
| --- | --- | --- | --- |
| T1 | 2 user turns, 2 assistant turns | `goodbye, save this conversation` | Exact user/assistant text and order |
| T2 | 10 alternating turns | `goodbye, save this conversation` | Whether all prior turns are included |
| T3 | 25 alternating turns | `goodbye, save this conversation` | Where omission or summarization starts |
| T4 | Ask for a table/code block, then save | `save now` | Formatting preservation |
| T5 | Mention a fake timestamp in each prompt | `save now` | Whether timestamps are preserved or inferred |
| T6 | Use the GPT Action once mid-conversation, then save | `goodbye, save this conversation` | Whether tool/action messages are visible |
| T7 | Upload/mention a file if the GPT supports it | `save now` | Whether file details or references appear |
| T8 | Long conversation approaching 100k characters | `save now` | Payload size limit and truncation behavior |

## Analysis Commands

Open the terminal browser:

```bash
python3 scripts/tui.py
```

Summarize recent captures:

```bash
python3 scripts/analyze_capture.py
```

Analyze one saved row:

```bash
python3 scripts/analyze_capture.py --id 1
```

Get JSON for a spreadsheet or later processing:

```bash
python3 scripts/analyze_capture.py --json > /tmp/threadvault-capture-analysis.json
```

Inspect failures:

```bash
python3 scripts/inspect_db.py --table ingest_events
```

## How To Decide What Data Is Obtainable

For each saved row, use `scripts/analyze_capture.py` and manually compare the saved payload against the visible ChatGPT conversation.

Classify each data type:

- `available_exact`: present and text/order match the visible conversation.
- `available_approximate`: present but paraphrased, summarized, inferred, or missing formatting.
- `not_available`: absent or explicitly reported inaccessible.
- `unknown`: not tested or impossible to verify from the saved payload.

Use `request_body_size_bytes` and `percent_of_100k_action_limit` to determine how close the payload came to the documented GPT Actions request limit.

## Result Template

Copy this table into a notes file after testing:

| Data Type | Classification | Evidence Row IDs | Notes |
| --- | --- | --- | --- |
| User message text | unknown | | |
| Assistant message text | unknown | | |
| Message order | unknown | | |
| System/developer messages | unknown | | |
| Tool/action messages | unknown | | |
| Timestamps | unknown | | |
| Files/images | unknown | | |
| Raw transcript | unknown | | |
| Beginning of long conversation | unknown | | |
| End of long conversation | unknown | | |
| Payload near 100k chars | unknown | | |

## Expected Interpretation

If ThreadVault receives only a model-produced `messages` array, then the result is evidence of what the GPT could package into an Action request. It is not proof that the Action had access to an authoritative hidden transcript.

If the GPT omits fields, summarizes older turns, or reports low confidence, treat that data as not reliably obtainable through GPT Actions.
