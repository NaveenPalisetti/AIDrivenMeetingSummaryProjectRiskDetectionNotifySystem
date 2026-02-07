# AI-Driven Meeting Summary & Risk Detection

This repository provides a lightweight, extensible scaffold for processing meeting transcripts: producing concise summaries, extracting action items, detecting risks, and notifying external systems (webhooks or Jira). It implements a minimal MCP-style host to wire `Agent`s and `Tool`s and exposes both an in-process API and an HTTP FastAPI server.

Table of contents
- Features
- Architecture
- Folder structure
- Quick start
- Configuration
- Run locally
- Streamlit UI
- Orchestrator details
- API endpoints
- Example requests (curl)
- Contributing
- License

## Features
- Summarization: local BART summarizer (default) with optional Mistral backend.
- Transcript preprocessing: cleaning, normalization and chunking for long transcripts.
- Action extraction: heuristic NLP extractor that produces structured tasks and decisions.
- Risk detection: heuristic analysis augmented by optional Jira signals.
- Notifications: send results to webhooks (Slack example) or create Jira issues.
- Modes: `InProcessHost` for testing and `MCPHost` + FastAPI for HTTP exposure.

## Architecture
- Flow: Transcript -> Preprocessing -> Summarization -> Task Extraction -> Risk Analysis -> Notification.
- The repo follows an MCP-like pattern: `Host` routes messages to `MCPTool`s which run `Agent`s that implement domain logic.

Example ASCII flow:

Transcript --> `TranscriptTool` --> `TranscriptPreprocessingAgent` --> chunks
chunks --> `SummarizationTool` --> `SummarizationAgent` (BART/Mistral) --> summary + tasks
summary/tasks --> `RiskTool` --> `RiskDetectionAgent` --> risk flags
results --> `NotificationTool` --> webhook / Jira

## Folder structure
- `Log/` — logging helpers. See [Log/logger.py](Log/logger.py).
- `meeting_mcp/` — main package and entry points:
  - `meeting_mcp/system.py` — create and wire `InProcessHost`/`MCPHost` and tools. See [meeting_mcp/system.py](meeting_mcp/system.py).
  - `meeting_mcp/core/mcp.py` — core host and tool primitives. See [meeting_mcp/core/mcp.py](meeting_mcp/core/mcp.py).
  - `meeting_mcp/agents/` — agents implementing business logic (transcript preprocessing, summarization, risk detection, notification, orchestrator).
  - `meeting_mcp/tools/` — tool wrappers that expose agent functionality to the host (transcript, summarization, risk, calendar, jira, notification).
  - `meeting_mcp/server/mcp_api.py` — FastAPI app providing HTTP endpoints. See [meeting_mcp/server/mcp_api.py](meeting_mcp/server/mcp_api.py).
  - `meeting_mcp/config.py` — environment-driven configuration helper. See [meeting_mcp/config.py](meeting_mcp/config.py).
- Notebooks: `ProjectFinal.ipynb`, `meeting_mcp_ngrok.ipynb` — example/demo notebooks.
- Top-level scripts: `run_detect_jira.py`, `run_detect_jira_verbose.py` — quick command-line runs for detecting risks and optionally creating Jira issues.
- `requirements.txt` / `installed.txt` — dependency lists.

## Quick start
Prereqs: Python 3.9+. Optional: CUDA GPU for Mistral.

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Create a virtualenv (recommended, Windows PowerShell):

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
```

## Streamlit UI
- Entry: `meeting_mcp/ui/streamlit_agent_client.py`.
- Key behaviors:
  - Creates a runtime via `create_system()` (the code uses a cached runtime helper).
  - Persists a session id in `st.session_state['mcp_session_id']` so the server-hosted session is reused across interactions.
  - UI handlers call `asyncio.run(orchestrator.orchestrate(..., session_id=st.session_state['mcp_session_id']))` to synchronously run the orchestrator from Streamlit's event loop.
  - Renderers in `meeting_mcp/ui/renderers.py` update `st.session_state` with `processed_cache`, `last_action_items`, and `last_jira_result` to display results and keep UI state between interactions.

Quick Streamlit handler example (pseudo):

```python
# inside Streamlit button handler
session_id = st.session_state.get('mcp_session_id')
response = asyncio.run(
    orchestrator.orchestrate(user_prompt, params={'transcripts':[text]}, session_id=session_id)
)
# render response with renderers.render_summary_result(response)
```

## Orchestrator details
- Entry: `meeting_mcp/agents/orchestrator_agent.py` (`OrchestratorAgent`).
- Responsibilities:
  - `detect_intent(text)`: lightweight intent classifier mapping user text to intents like `preprocess`, `summarize`, `risk`, `jira`, `notify`.
  - `route_agents(intent)`: maps an intent to an ordered list of tool IDs (e.g., `['transcript','summarization','risk']`).
  - `orchestrate(user_message, params=None, session_id=None)`: creates/uses an MCP session, iterates the routed tools, calls `host.execute_tool(session_id, tool_id, params)`, and aggregates per-tool results into a single response.

Important implementation notes:
- The orchestrator reuses an MCP session id (see Streamlit UI) so tool state / caches persist across multiple calls.
- Tool execution is synchronous from the orchestrator's perspective but tools may delegate heavy work to thread executors.
- Errors from a tool are caught and returned in the aggregated response so the UI can surface partial results.

## Example end-to-end flow (single meeting)
1) Streamlit sends a user request to orchestrator:

Request (Streamlit -> Orchestrator):

{
  "message": "Summarize meeting and detect risks",
  "params": { "transcripts": ["<full meeting transcript text>"] }
}

2) Orchestrator detects intent `summarize` and routes: `['transcript','summarization','risk']`.

3) Orchestrator -> Transcript tool

Tool call: `host.execute_tool(session_id, 'transcript', { 'transcripts': [...], 'chunk_size':1500 })`

Tool response (example):

{ "processed": ["chunk1...","chunk2..."] }

4) Orchestrator -> Summarization tool

Tool call: `host.execute_tool(session_id, 'summarization', { 'processed_transcripts': [...], 'mode':'bart' })`

Tool response (example):

{
  "summary": "Key points...",
  "tasks": [{"title":"Action item 1","assignee":null}],
  "decisions": ["Decision A"]
}

5) Orchestrator -> Risk tool

Tool call: `host.execute_tool(session_id, 'risk', { 'meeting_id':'m1', 'summary': <summary>, 'tasks': <tasks> })`

Tool response (example):

{ "risks": [{"level":"medium","reason":"deadline at risk"}], "jira_signals": [] }

6) Aggregated response returned to Streamlit:

{
  "processed": [...],
  "summary": {...},
  "tasks": [...],
  "risks": [...]
}

## API endpoints
Base path: `/mcp`

- `POST /mcp/transcript` — preprocess transcript
  - body: `{ "transcripts": ["<text>"], "chunk_size": 1500 }`
  - response: `{ "processed": ["...chunk..."] }`

- `POST /mcp/summarize` — summarize processed chunks
  - body: `{ "processed_transcripts": ["<chunk>"], "mode": "bart" }`
  - response: `{ "summary": "...", "tasks": [{"title":"...","assignee":null}], "decisions": [...] }`

- `POST /mcp/risk` — detect risks
  - body: `{ "meeting_id": "m1", "summary": {...}, "tasks": [...] }`
  - response: `{ "risks": [{"level":"low|medium|high","reason":"..."}], "jira_signals": [...] }`

- `POST /mcp/orchestrate` — intent-based orchestration
  - body: `{ "message": "Summarize and detect risks", "params": {"transcripts":["..."]} }`
  - response: aggregated outputs from requested tools.

## Example requests (curl)

Preprocess transcript:

```bash
curl -X POST http://127.0.0.1:8000/mcp/transcript \\
  -H "Content-Type: application/json" \\
  -d '{"transcripts":["Long meeting text here"], "chunk_size":1500}'
```

Summarize:

```bash
curl -X POST http://127.0.0.1:8000/mcp/summarize \\
  -H "Content-Type: application/json" \\
  -d '{"processed_transcripts":["<chunk>"], "mode":"bart"}'
```

Detect risks:

```bash
curl -X POST http://127.0.0.1:8000/mcp/risk \\
  -H "Content-Type: application/json" \\
  -d '{"meeting_id":"m1","summary":{},"tasks":[]}'
```

Orchestrate (intent):

```bash
curl -X POST http://127.0.0.1:8000/mcp/orchestrate \\
  -H "Content-Type: application/json" \\
  -d '{"message":"Summarize and detect risks","params":{"transcripts":["..."]}}'
```

## Contributing
- Fork the repo, create a feature branch, add tests, and open a PR.
- Keep changes focused. Add unit tests for new behaviors and update this README if you add new public endpoints or env vars.

## License
No `LICENSE` file is included in this workspace. If you plan to publish, add a license (for example, MIT) in a `LICENSE` file.

---

## Code references
- **Streamlit UI:** [meeting_mcp/ui/streamlit_agent_client.py](meeting_mcp/ui/streamlit_agent_client.py) — UI entry, session handling, and orchestrator calls.
- **Renderers:** [meeting_mcp/ui/renderers.py](meeting_mcp/ui/renderers.py) — UI rendering helpers and `st.session_state` management.
- **Orchestrator agent:** [meeting_mcp/agents/orchestrator_agent.py](meeting_mcp/agents/orchestrator_agent.py) — `detect_intent`, `route_agents`, `orchestrate()` and routing logic.
- **MCP host & tools:** [meeting_mcp/core/mcp.py](meeting_mcp/core/mcp.py) — `MCPHost`, `MCPTool` and session lifecycle; [meeting_mcp/system.py](meeting_mcp/system.py) — wiring and `InProcessHost` helper.
- **A2A protocol:** [meeting_mcp/protocols/a2a.py](meeting_mcp/protocols/a2a.py) — `A2AMessage`, `MessagePart`, `A2ATask` and semantic part types.
- **HTTP server:** [meeting_mcp/server/mcp_api.py](meeting_mcp/server/mcp_api.py) — FastAPI endpoints that create sessions and call `execute_tool()`.

Notes:
- Streamlit UI: see `meeting_mcp/ui/streamlit_agent_client.py` and `meeting_mcp/ui/renderers.py` for exact rendering helpers and session handling.
- Orchestrator: see `meeting_mcp/agents/orchestrator_agent.py` for `detect_intent`, `route_agents`, and `orchestrate()` implementations.
- If you want, I can add a small `examples/meeting_flow_trace.json` file with the sample payloads above.
# AI-Driven Meeting Summary & Risk Detection

This repository provides a lightweight, extensible scaffold for processing meeting transcripts: producing concise summaries, extracting action items, detecting risks, and notifying external systems (webhooks or Jira). It implements a minimal MCP-style host to wire `Agent`s and `Tool`s and exposes both an in-process API and an HTTP FastAPI server.

Table of contents
- Features
- Architecture
- Folder structure
- Quick start
- Configuration
- Run locally
- API endpoints
- Example requests (curl)
- Contributing
- License

## Features
- Summarization: local BART summarizer (default) with optional Mistral backend.
- Transcript preprocessing: cleaning, normalization and chunking for long transcripts.
- Action extraction: heuristic NLP extractor that produces structured tasks and decisions.
- Risk detection: heuristic analysis augmented by optional Jira signals.
- Notifications: send results to webhooks (Slack example) or create Jira issues.
- Modes: `InProcessHost` for testing and `MCPHost` + FastAPI for HTTP exposure.

## Architecture
- Flow: Transcript -> Preprocessing -> Summarization -> Task Extraction -> Risk Analysis -> Notification.
- The repo follows an MCP-like pattern: `Host` routes messages to `MCPTool`s which run `Agent`s that implement domain logic.

Example ASCII flow:

Transcript --> `TranscriptTool` --> `TranscriptPreprocessingAgent` --> chunks
chunks --> `SummarizationTool` --> `SummarizationAgent` (BART/Mistral) --> summary + tasks
summary/tasks --> `RiskTool` --> `RiskDetectionAgent` --> risk flags
results --> `NotificationTool` --> webhook / Jira

## Folder structure
- `Log/` — logging helpers. See [Log/logger.py](Log/logger.py).
- `meeting_mcp/` — main package and entry points:
  - `meeting_mcp/system.py` — create and wire `InProcessHost`/`MCPHost` and tools. See [meeting_mcp/system.py](meeting_mcp/system.py).
  - `meeting_mcp/core/mcp.py` — core host and tool primitives. See [meeting_mcp/core/mcp.py](meeting_mcp/core/mcp.py).
  - `meeting_mcp/agents/` — agents implementing business logic (transcript preprocessing, summarization, risk detection, notification, orchestrator).
  - `meeting_mcp/tools/` — tool wrappers that expose agent functionality to the host (transcript, summarization, risk, calendar, jira, notification).
  - `meeting_mcp/server/mcp_api.py` — FastAPI app providing HTTP endpoints. See [meeting_mcp/server/mcp_api.py](meeting_mcp/server/mcp_api.py).
  - `meeting_mcp/config.py` — environment-driven configuration helper. See [meeting_mcp/config.py](meeting_mcp/config.py).
- Notebooks: `ProjectFinal.ipynb`, `meeting_mcp_ngrok.ipynb` — example/demo notebooks.
- Top-level scripts: `run_detect_jira.py`, `run_detect_jira_verbose.py` — quick command-line runs for detecting risks and optionally creating Jira issues.
- `requirements.txt` / `installed.txt` — dependency lists.

## Quick start
Prereqs: Python 3.9+. Optional: CUDA GPU for Mistral.

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Create a virtualenv (recommended, Windows PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Configuration
Place credentials and secrets safely. See `meeting_mcp/.env.example` for defaults.

Important environment variables:
- `MCP_API_KEY` — optional API key for the HTTP server. If set, include `X-Api-Key: <key>` header in requests.
- `MCP_SERVICE_ACCOUNT_FILE` — Google service account JSON for calendar features.
- `MCP_CALENDAR_ID` — calendar id/email.
- `BART_MODEL_PATH` — path or HF id for BART model (default: `meeting_mcp/models/bart_finetuned_meeting_summary`).
- `MISTRAL_ENABLED` — `1` to enable Mistral (requires GPU).
- `MISTRAL_MODEL_PATH` — Mistral model id/path.
- `SLACK_WEBHOOK_URL` — webhook for notifications.
- `JIRA_URL`, `JIRA_USER`, `JIRA_TOKEN`, `JIRA_PROJECT` — Jira integration.

For local dev prefer: place `meeting_mcp/config/credentials.json` and point `MCP_SERVICE_ACCOUNT_FILE` to it (see [meeting_mcp/.env.example](meeting_mcp/.env.example)).

## Run locally
Start the FastAPI server (development):

```powershell
cd meeting_mcp
python -m meeting_mcp.server.mcp_api
# or with uvicorn for reloads:
uvicorn meeting_mcp.server.mcp_api:app --reload --host 127.0.0.1 --port 8000
```

Run the notebooks for quick demos: open `ProjectFinal.ipynb` or `meeting_mcp_ngrok.ipynb`.

In-process example (async):

```python
from meeting_mcp.system import create_system

mcp_host, inproc, tools, orchestrator = create_system(mode="in_process")
result = await orchestrator.orchestrate("Summarize this meeting", params={"transcripts":["..."]})
```

## API endpoints
Base path: `/mcp`

- `POST /mcp/transcript` — preprocess transcript
  - body: `{ "transcripts": ["<text>"], "chunk_size": 1500 }`
  - response: `{ "processed": ["...chunk..."] }`

- `POST /mcp/summarize` — summarize processed chunks
  - body: `{ "processed_transcripts": ["<chunk>"], "mode": "bart" }`
  - response: `{ "summary": "...", "tasks": [{"title":"...","assignee":null}], "decisions": [...] }`

- `POST /mcp/risk` — detect risks
  - body: `{ "meeting_id": "m1", "summary": {...}, "tasks": [...] }`
  - response: `{ "risks": [{"level":"low|medium|high","reason":"..."}], "jira_signals": [...] }`

- `POST /mcp/orchestrate` — intent-based orchestration
  - body: `{ "message": "Summarize and detect risks", "params": {"transcripts":["..."]} }`
  - response: aggregated outputs from requested tools.

# AI-Driven Meeting Summary & Risk Detection

This repository provides a lightweight, extensible scaffold for processing meeting transcripts: producing concise summaries, extracting action items, detecting risks, and notifying external systems (webhooks or Jira). It implements a minimal MCP-style host to wire `Agent`s and `Tool`s and exposes both an in-process API and an HTTP FastAPI server.

Table of contents
- Features
- Architecture
- Folder structure
- Quick start
- Configuration
- Run locally
- API endpoints
- Example requests (curl)
- Contributing
- License

## Features
- Summarization: local BART summarizer (default) with optional Mistral backend.
- Transcript preprocessing: cleaning, normalization and chunking for long transcripts.
- Action extraction: heuristic NLP extractor that produces structured tasks and decisions.
- Risk detection: heuristic analysis augmented by optional Jira signals.
- Notifications: send results to webhooks (Slack example) or create Jira issues.
- Modes: `InProcessHost` for testing and `MCPHost` + FastAPI for HTTP exposure.

## Architecture
- Flow: Transcript -> Preprocessing -> Summarization -> Task Extraction -> Risk Analysis -> Notification.
- The repo follows an MCP-like pattern: `Host` routes messages to `MCPTool`s which run `Agent`s that implement domain logic.

Example ASCII flow:

Transcript --> `TranscriptTool` --> `TranscriptPreprocessingAgent` --> chunks
chunks --> `SummarizationTool` --> `SummarizationAgent` (BART/Mistral) --> summary + tasks
summary/tasks --> `RiskTool` --> `RiskDetectionAgent` --> risk flags
results --> `NotificationTool` --> webhook / Jira

## Folder structure
- `Log/` — logging helpers. See [Log/logger.py](Log/logger.py).
- `meeting_mcp/` — main package and entry points:
  - `meeting_mcp/system.py` — create and wire `InProcessHost`/`MCPHost` and tools. See [meeting_mcp/system.py](meeting_mcp/system.py).
  - `meeting_mcp/core/mcp.py` — core host and tool primitives. See [meeting_mcp/core/mcp.py](meeting_mcp/core/mcp.py).
  - `meeting_mcp/agents/` — agents implementing business logic (transcript preprocessing, summarization, risk detection, notification, orchestrator).
  - `meeting_mcp/tools/` — tool wrappers that expose agent functionality to the host (transcript, summarization, risk, calendar, jira, notification).
  - `meeting_mcp/server/mcp_api.py` — FastAPI app providing HTTP endpoints. See [meeting_mcp/server/mcp_api.py](meeting_mcp/server/mcp_api.py).
  - `meeting_mcp/config.py` — environment-driven configuration helper. See [meeting_mcp/config.py](meeting_mcp/config.py).
- Notebooks: `ProjectFinal.ipynb`, `meeting_mcp_ngrok.ipynb` — example/demo notebooks.
- Top-level scripts: `run_detect_jira.py`, `run_detect_jira_verbose.py` — quick command-line runs for detecting risks and optionally creating Jira issues.
- `requirements.txt` / `installed.txt` — dependency lists.

## Quick start
Prereqs: Python 3.9+. Optional: CUDA GPU for Mistral.

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Create a virtualenv (recommended, Windows PowerShell):

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
```

## Configuration
Place credentials and secrets safely. See `meeting_mcp/.env.example` for defaults.

Important environment variables:
- `MCP_API_KEY` — optional API key for the HTTP server. If set, include `X-Api-Key: <key>` header in requests.
- `MCP_SERVICE_ACCOUNT_FILE` — Google service account JSON for calendar features.
- `MCP_CALENDAR_ID` — calendar id/email.
- `BART_MODEL_PATH` — path or HF id for BART model (default: `meeting_mcp/models/bart_finetuned_meeting_summary`).
- `MISTRAL_ENABLED` — `1` to enable Mistral (requires GPU).
- `MISTRAL_MODEL_PATH` — Mistral model id/path.
- `SLACK_WEBHOOK_URL` — webhook for notifications.
- `JIRA_URL`, `JIRA_USER`, `JIRA_TOKEN`, `JIRA_PROJECT` — Jira integration.

For local dev prefer: place `meeting_mcp/config/credentials.json` and point `MCP_SERVICE_ACCOUNT_FILE` to it (see [meeting_mcp/.env.example](meeting_mcp/.env.example)).

## Run locally
Start the FastAPI server (development):

```powershell
cd meeting_mcp
python -m meeting_mcp.server.mcp_api
# or with uvicorn for reloads:
uvicorn meeting_mcp.server.mcp_api:app --reload --host 127.0.0.1 --port 8000
```

Run the notebooks for quick demos: open `ProjectFinal.ipynb` or `meeting_mcp_ngrok.ipynb`.

In-process example (async):

```python
from meeting_mcp.system import create_system

mcp_host, inproc, tools, orchestrator = create_system(mode="in_process")
result = await orchestrator.orchestrate("Summarize this meeting", params={"transcripts":["..."]})
```

## API endpoints
Base path: `/mcp`

- `POST /mcp/transcript` — preprocess transcript
  - body: `{ "transcripts": ["<text>"], "chunk_size": 1500 }`
  - response: `{ "processed": ["...chunk..."] }`

- `POST /mcp/summarize` — summarize processed chunks
  - body: `{ "processed_transcripts": ["<chunk>"], "mode": "bart" }`
  - response: `{ "summary": "...", "tasks": [{"title":"...","assignee":null}], "decisions": [...] }`

- `POST /mcp/risk` — detect risks
  - body: `{ "meeting_id": "m1", "summary": {...}, "tasks": [...] }`
  - response: `{ "risks": [{"level":"low|medium|high","reason":"..."}], "jira_signals": [...] }`

- `POST /mcp/orchestrate` — intent-based orchestration
  - body: `{ "message": "Summarize and detect risks", "params": {"transcripts":["..."]} }`
  - response: aggregated outputs from requested tools.

If `MCP_API_KEY` is set, include header `X-Api-Key: <value>`.

## Example requests (curl)

Preprocess transcript:

```bash
curl -X POST http://127.0.0.1:8000/mcp/transcript \\
  -H "Content-Type: application/json" \\
  -d '{"transcripts":["Long meeting text here"], "chunk_size":1500}'
```

Summarize:

```bash
curl -X POST http://127.0.0.1:8000/mcp/summarize \\
  -H "Content-Type: application/json" \\
  -d '{"processed_transcripts":["<chunk>"], "mode":"bart"}'
```

Detect risks:

```bash
curl -X POST http://127.0.0.1:8000/mcp/risk \\
  -H "Content-Type: application/json" \\
  -d '{"meeting_id":"m1","summary":{},"tasks":[]}'
```

Orchestrate (intent):

```bash
curl -X POST http://127.0.0.1:8000/mcp/orchestrate \\
  -H "Content-Type: application/json" \\
  -d '{"message":"Summarize and detect risks","params":{"transcripts":["..."]}}'
```

## Contributing
- Fork the repo, create a feature branch, add tests, and open a PR.
- Keep changes focused. Add unit tests for new behaviors and update this README if you add new public endpoints or env vars.

## License
No `LICENSE` file is included in this workspace. If you plan to publish, add a license (for example, MIT) in a `LICENSE` file.

---

Notes:
- I inspected the included PDF for additional details and the repo notebooks; the primary implementation details live under [meeting_mcp/](meeting_mcp).
