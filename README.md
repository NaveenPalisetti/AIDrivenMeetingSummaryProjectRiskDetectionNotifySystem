# AI-Driven Meeting Summary & Risk Detection (meeting_mcp)

This repository provides a lightweight, extensible scaffold for processing meeting transcripts, producing concise meeting summaries, extracting action items, detecting risks, and optionally notifying external channels or creating Jira issues. It implements a minimal MCP-like (Modular Connector/Provider) host and a set of tools/agents that demonstrate an end-to-end meeting-processing flow.

Core features
- Summarization: BART-based local summarizer with optional Mistral-based alternative.
- Transcript preprocessing: cleaning, normalization and chunking for long transcripts.
- Action-item extraction: heuristic NLP extractor to produce structured tasks.
- Risk detection: heuristic analysis plus optional Jira signals.
- Notification: sample Slack/webhook notifier and a notification tool wrapper.
- In-process & HTTP host: `MCPHost` and `InProcessHost` for local UI/testing and a FastAPI server for HTTP exposure.

Project layout (important files)
- `meeting_mcp/` — main package containing agents, tools, wiring and local configs.
	- `core/mcp.py` — `MCPHost`, `MCPTool` and session management.
	- `system.py` — `create_system()` helper to wire `InProcessHost`/`MCPHost`, tools and `OrchestratorAgent`.
	- `agents/` — implementations of:
		- `transcript_preprocessing_agent.py` — cleaning & chunking
		- `summarization_agent.py` — orchestrates BART/Mistral summarizers
		- `bart_summarizer.py`, `mistral_summarizer.py` — summarizer backends
		- `risk_detection_agent.py` — heuristic risk detection and Jira integration
		- `notification_agent.py` — webhook/Slack notifier
		- `orchestrator_agent.py` — simple intent detection and routing into tools
	- `tools/` — MCPTool wrappers exposed to the host (`transcript`, `summarization`, `risk`, `calendar`, `jira`, `notification`)
	- `server/mcp_api.py` — FastAPI microservice exposing `/mcp/*` endpoints (optional HTTP mode)
	- `config.py` — environment-driven configuration helpers (model paths, API keys)
	- `models/` — local BART model folder (optional, referenced by default pipelines)

How it works (high level)
- A client (UI or API) provides meeting transcript text.
- `TranscriptTool` runs the `TranscriptPreprocessingAgent` to clean and chunk text.
- `SummarizationTool` runs `SummarizationAgent` which loads BART (or Mistral when enabled) and generates a summary, action items, decisions and risks.
- `RiskTool` analyzes the summary and tasks heuristically and optionally queries Jira for additional signals.
- `NotificationTool` can send results to external webhooks (Slack example present).
- `OrchestratorAgent` provides a convenient intent-based routing layer to call one or more tools in sequence and return aggregated results.

Quick start (development)
Prerequisites
- Python 3.9+ (tested with CPython 3.9/3.10)
- Optional: GPU for Mistral; BART runs on CPU but may require significant RAM for larger models.
- Install dependencies from `requirements.txt` (some dependencies are optional and guarded by try/except in code):

```powershell
python -m pip install -r requirements.txt
```

Environment variables (common)
- `MCP_API_KEY` — API key for FastAPI endpoints (optional for local dev).
- `MCP_SERVICE_ACCOUNT_FILE` — Google service account JSON for calendar operations (optional).
- `MCP_CALENDAR_ID` — calendar id/email to use.
- `BART_MODEL_PATH` — path to BART model folder or HF id (optional; default is `meeting_mcp/models/bart_finetuned_meeting_summary`).
- `MISTRAL_ENABLED` and `MISTRAL_MODEL_PATH` — enable and point to Mistral model (requires GPU + transformers configuration).
- `SLACK_WEBHOOK_URL` — optional webhook for notifications.
- Jira-related env vars: `JIRA_URL`, `JIRA_USER`, `JIRA_TOKEN`, `JIRA_PROJECT` (optional).

Running the FastAPI server (HTTP exposure)
- Start the API (development):

```powershell
cd meeting_mcp
python -m meeting_mcp.server.mcp_api
# or: uvicorn meeting_mcp.server.mcp_api:app --reload --host 127.0.0.1 --port 8000
```

API endpoints (examples)
- `POST /mcp/transcript` — preprocess transcript
	- body: `{ "transcripts": ["<text>"], "chunk_size": 1500 }`
- `POST /mcp/summarize` — summarize processed chunks
	- body: `{ "processed_transcripts": ["<chunk>"], "mode": "bart" }`
- `POST /mcp/risk` — detect risks
	- body: `{ "meeting_id": "m1", "summary": {...}, "tasks": [...] }`
- `POST /mcp/orchestrate` — intent-based orchestration
	- body: `{ "message": "Please summarize and detect risks", "params": { ... } }`

Python usage (in-process helper)
```python
from meeting_mcp.system import create_system

mcp_host, inproc, tools, orchestrator = create_system(mode="in_process")
# Use orchestrator to detect intent and run tools
result = await orchestrator.orchestrate("Please summarize this meeting transcript", params={"processed": [transcript]})
```

Models and resource notes
- BART summarizer: expects a local model under `meeting_mcp/models/bart_finetuned_meeting_summary` by default or set `BART_MODEL_PATH`.
- Mistral summarizer: disabled by default — enable via `MISTRAL_ENABLED=1` and set `MISTRAL_MODEL_PATH`; Mistral requires a CUDA GPU and appropriate transformers support.

Testing & development tips
- The `system.create_system()` helper provides an `InProcessHost` ideal for unit tests and local UI development.
- Tools run heavy work in thread executors to avoid blocking the asyncio loop — keep that in mind when adding CPU-bound steps.
- Logging: file logging is configured in `meeting_mcp/server/mcp_api.py` using `Log/logger.py` (adjust for your needs).

Extending the project
- Add or replace summarizers in `meeting_mcp/agents/`.
- Add new `MCPTool` wrappers in `meeting_mcp/tools/` and register them in `system.create_system()`.
- Replace the heuristic extractors (`tools/nlp_task_extraction.py`, `risk_detection_agent.py`) with LLM-based or ML-based classifiers as needed.

Contributing
- Open issues or PRs in this workspace. Keep changes focused and add tests for new behaviors.

Acknowledgements
- This scaffold is intended as a flexible starting point to experiment with meeting summarization, task extraction and lightweight risk detection. Treat it as a developer-oriented prototype, not a production-ready system.

License
- No license file included. Add one if you intend to open-source this project.

---

If you'd like, I can also:
- add example curl commands with concrete payloads,
- create a small `examples/` notebook demonstrating a full pipeline run,
- or add unit tests for the core `tools/` behavior.

