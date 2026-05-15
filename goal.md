Build a minimal local prototype for ThreadVault.

ThreadVault is a proof-of-concept backend for a custom ChatGPT GPT Action. The goal is to test whether a custom GPT can send a near-complete conversation transcript to a server when the user says goodbye.

Do not overbuild. Create the smallest working implementation that lets us experiment with payload size, transcript completeness, and failure modes.

Core requirements:

1. Backend server
- Build a small HTTP API.
- Prefer a simple stack suitable for local development.
- Use SQLite for persistence.
- Include clear setup/run instructions.

2. Main endpoint
Create an endpoint like:

POST /api/conversations/save

It should accept JSON containing:
- conversation_id, optional
- title
- summary, optional
- messages array
- raw_transcript, optional
- source: "custom_gpt_action"
- client_reported_message_count
- notes_about_completeness, optional

Each message should support:
- role: "user" | "assistant" | "system" | "tool" | "unknown"
- content
- index, optional
- approximate_timestamp, optional

3. Storage
Persist:
- conversation id
- title
- summary
- full JSON payload
- message count
- approximate character count
- approximate token estimate if easy
- created_at

Keep schema simple but make it easy to inspect saved conversations.

4. Limits experiment
The server should log and store:
- request body size in bytes
- message count
- total transcript characters
- whether JSON parsing succeeded
- any validation errors

Add a simple endpoint:

GET /api/conversations

to list saved records with metadata.

Add:

GET /api/conversations/:id

to inspect a saved payload.

5. OpenAPI schema
Create an OpenAPI 3.1 schema suitable for a GPT Action.
The schema should expose only the save endpoint at minimum.
Make it easy to paste into the GPT Actions editor.

6. Testing
Add at least:
- one curl example with a small transcript
- one script or documented method to generate a large fake transcript payload
- notes on how to test increasing payload sizes

7. Security
This is local/MVP only and will be exposed temporarily through ngrok.

Add a simple API key header:

X-ThreadVault-Key

Reject requests without the key.

Do not implement OAuth yet.

Do not log the API key.

Mention in the README that ngrok exposes the local server to the internet, so the API key is required even for testing.

8. Documentation
Create a README explaining:
- what ThreadVault is
- how to run it locally
- how to configure the GPT Action
- known limitations
- what we are trying to measure

9. Ngrok support
We will expose the local backend to ChatGPT using ngrok.

Update the README with:
- how to start the local server
- how to start ngrok against the server port
- where to find the public HTTPS ngrok URL
- how to update the OpenAPI server URL to use the ngrok HTTPS URL
- how to configure the GPT Action with that URL
- reminder that ngrok URLs may change between sessions unless using a reserved domain

The backend should:
- bind to localhost by default for safety
- allow configuration of host/port via environment variables
- avoid hardcoding the public ngrok URL in source code
- generate or document an OpenAPI schema where the `servers[0].url` can be replaced with the current ngrok URL

Add an `.env.example` with:
- PORT
- THREADVAULT_API_KEY
- PUBLIC_BASE_URL optional, for the ngrok HTTPS URL

Important design principle:
This is an experiment. Prioritize observability and simplicity over a polished app.

Deliverables:
- runnable backend
- SQLite persistence
- OpenAPI schema
- README
- example requests
- clear notes on limits/failure modes discovered locally
