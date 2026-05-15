# GPT Action Test Prompts

Use these prompts with the Custom GPT after updating the Action schema from:

```text
https://YOUR-NGROK-HOST/openapi.yaml
```

Before testing, add the instruction block from `docs/capture-experiment-runbook.md` to the GPT instructions.

## T1: Short Exactness Test

Start a new GPT conversation and send these prompts one by one:

```text
For this test, remember this exact sentence: ALPHA red square 104.
```

```text
Reply with exactly this sentence: BRAVO blue circle 205.
```

```text
Now tell me one short fact about SQLite.
```

```text
goodbye, save this conversation
```

Check:

- all user prompts are present;
- assistant replies are present;
- exact sentinel strings `ALPHA red square 104` and `BRAVO blue circle 205` are preserved;
- message order is correct.

## T2: Ten-Turn Retention Test

Send ten alternating prompts with numbered sentinels:

```text
Turn 1 sentinel: TV-A001. Reply with one short sentence.
```

```text
Turn 2 sentinel: TV-A002. Reply with one short sentence.
```

Continue through:

```text
Turn 10 sentinel: TV-A010. Reply with one short sentence.
```

Then:

```text
goodbye, save this conversation
```

Check whether all ten user sentinels and assistant replies appear.

## T3: Twenty-Five-Turn Retention Test

Repeat the T2 pattern from `TV-B001` through `TV-B025`, then save:

```text
goodbye, save this conversation
```

Check whether early, middle, and late turns survive.

## T4: Formatting Preservation Test

```text
Create a markdown table with columns Name, Value, and Note. Include rows for Alpha, Beta, and Gamma.
```

```text
Now create a fenced Python code block that prints "threadvault-format-test".
```

```text
save now
```

Check whether tables, code fences, quotes, and line breaks are preserved in `messages` or `raw_transcript`.

## T5: Timestamp Prompt Test

```text
At fake timestamp 2026-05-15T20:00:01Z, I say: timestamp test one.
```

```text
At fake timestamp 2026-05-15T20:00:02Z, I say: timestamp test two.
```

```text
save now
```

Check whether timestamps appear in message content only, or also in `approximate_timestamp`.

## T6: Tool/Action Visibility Test

First force a small save mid-conversation:

```text
Save a checkpoint now with title "Tool visibility checkpoint".
```

Then continue:

```text
After that checkpoint, tell me whether you can see that an action/tool call happened.
```

Finally:

```text
goodbye, save this conversation
```

Check whether the final saved payload includes any tool/action traces, or only normal user/assistant text.

## T7: File/Image Reference Test

If your GPT supports uploads, attach a small text file or image and ask:

```text
Describe the uploaded file or image in one sentence, then save this conversation.
```

Check whether the saved payload contains:

- file name;
- file contents;
- image description;
- attachment metadata;
- only a summary.

Do not use sensitive files for this test.

## T8: Near-Limit Test

Use repeated sentinel prompts until the conversation is large. For example, send batches like:

```text
Large test batch 001. Repeat the token THREADVAULT-LIMIT-001 in your answer and include a paragraph of about 300 words.
```

Increment the batch number. Save periodically:

```text
save now
```

Check:

- `request_body_size_bytes`;
- `percent_of_100k_action_limit` from `scripts/analyze_capture.py`;
- whether early sentinel strings are missing;
- whether the GPT summarizes instead of sending exact text;
- whether the Action call fails near the documented size limit.

## Analysis After Each Test

Run:

```bash
python3 scripts/analyze_capture.py
```

Then inspect a specific row:

```bash
curl -sS \
  -H "X-ThreadVault-Key: $THREADVAULT_API_KEY" \
  http://127.0.0.1:8000/api/conversations/ROW_ID
```

Update `docs/capture-findings.md` with the row IDs and classification.
