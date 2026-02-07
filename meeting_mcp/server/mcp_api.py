from typing import Any, Optional, List, Dict
import os

from fastapi import FastAPI, Request, Header, HTTPException, Depends, status
from pydantic import BaseModel

from meeting_mcp.core.mcp import MCPHost
from meeting_mcp.tools.calendar_tool import CalendarTool
from meeting_mcp.tools.transcript_tool import TranscriptTool
from meeting_mcp.tools.summarization_tool import SummarizationTool
from meeting_mcp.tools.jira_tool import JiraTool
from meeting_mcp.tools.risk_tool import RiskTool
from meeting_mcp.agents.orchestrator_agent import OrchestratorAgent
from meeting_mcp.system import create_system

from Log.logger import setup_logging
import logging


app = FastAPI(title="meeting_mcp API")

# configure file logging (creates Log/meeting_mcp.log in repo)
try:
    setup_logging()
    logging.getLogger(__name__).info("File logging enabled")
except Exception:
    logging.getLogger(__name__).exception("Failed to setup file logging")

# Note: CORS middleware removed per request (if needed, re-add carefully)


_MCP_API_KEY = os.environ.get("MCP_API_KEY")


def _verify_api_key(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    """Simple API-key check: prefer Bearer token in Authorization, fall back to X-Api-Key header.

    If `_MCP_API_KEY` is not set, authentication is a no-op (dev-friendly).
    """
    if not _MCP_API_KEY:
        return True

    token = None
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
    if not token and x_api_key:
        token = x_api_key

    if token != _MCP_API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")

    return True


# Bootstrap MCP runtime using existing factory to ensure tools/orchestrator wiring
try:
    mcp_host, inproc_host, tools, orchestrator = create_system()
    logging.getLogger(__name__).info("Bootstrapped MCP runtime via create_system()")
except Exception:
    logging.getLogger(__name__).exception("Failed to bootstrap runtime via create_system(); falling back to manual wiring")
    # Fallback: manual wiring (legacy behavior)
    mcp_host = MCPHost()
    calendar_tool = CalendarTool()
    mcp_host.register_tool(calendar_tool)
    transcript_tool = TranscriptTool()
    mcp_host.register_tool(transcript_tool)
    summarization_tool = SummarizationTool()
    mcp_host.register_tool(summarization_tool)
    jira_tool = JiraTool()
    mcp_host.register_tool(jira_tool)
    risk_tool = RiskTool()
    mcp_host.register_tool(risk_tool)
    orchestrator = OrchestratorAgent(mcp_host=mcp_host)


class CalendarRequest(BaseModel):
    action: str
    start: Optional[Any] = None
    end: Optional[Any] = None
    calendar_id: Optional[str] = None
    event_data: Optional[dict] = None
    time_min: Optional[str] = None
    time_max: Optional[str] = None


class TranscriptRequest(BaseModel):
    transcripts: Optional[List[str]] = None
    chunk_size: Optional[int] = None
    # keep compatibility with orchestrator params
    data: Optional[Any] = None

""" 
@app.post("/mcp/calendar")
async def call_calendar(req: CalendarRequest):
    # create a short-lived session for this HTTP call
    session_id = mcp_host.create_session(agent_id="http-client")
    params = req.dict(exclude_none=True)
    result = await mcp_host.execute_tool(session_id, "calendar", params)
    mcp_host.end_session(session_id)
    return result """


@app.post("/mcp/transcript")
async def call_transcript(req: TranscriptRequest):
    session_id = mcp_host.create_session(agent_id="http-client")
    params = req.dict(exclude_none=True)
    # allow `data` to alias `transcripts` for flexibility
    if "data" in params and "transcripts" not in params:
        params["transcripts"] = params.pop("data")
    result = await mcp_host.execute_tool(session_id, "transcript", params)
    mcp_host.end_session(session_id)
    return result


@app.post("/session/create")
async def create_session_endpoint(agent_id: Optional[str] = "http-client"):
    try:
        sid = mcp_host.create_session(agent_id=agent_id)
        return {"session_id": sid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/session/{session_id}/end")
async def end_session_endpoint(session_id: str):
    try:
        mcp_host.end_session(session_id)
        return {"ended": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    # simple readiness probe: runtime present
    ready = mcp_host is not None
    return {"ready": bool(ready)}


class OrchestrateRequest(BaseModel):
    # accept either `prompt` (client) or `message` (legacy) for flexibility
    prompt: Optional[str] = None
    message: Optional[str] = None
    params: Optional[dict] = None
    session_id: Optional[str] = None


class SummarizeRequest(BaseModel):
    processed_transcripts: Optional[List[str]] = None
    mode: Optional[str] = None


class JiraRequest(BaseModel):
    action_items: Optional[List[Dict[str, Any]]] = None
    user: Optional[str] = None
    date: Optional[str] = None


class RiskRequest(BaseModel):
    meeting_id: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None
    tasks: Optional[List[Dict[str, Any]]] = None
    progress: Optional[Dict[str, Any]] = None


@app.post("/mcp/orchestrate")
async def call_orchestrate(req: OrchestrateRequest):
    # support both `prompt` and `message` keys
    prompt = req.prompt or req.message or ""
    # If a session_id was provided, delegate to mcp_host to run the intent in that session
    if req.session_id:
        # Use in-session execution if supported
        try:
            result = await mcp_host.execute_intent(req.session_id, prompt, req.params or {})
            return result
        except Exception:
            # Fallback to orchestrator which will create its own session
            pass

    result = await orchestrator.orchestrate(prompt, req.params or {})
    return result


@app.post("/mcp/summarize")
async def call_summarize(req: SummarizeRequest):
    session_id = mcp_host.create_session(agent_id="http-client")
    params = req.dict(exclude_none=True)
    # normalize parameter name to match tool expectations
    if "processed_transcripts" in params and "processed" not in params:
        params["processed"] = params.get("processed_transcripts")
    result = await mcp_host.execute_tool(session_id, "summarization", params)
    mcp_host.end_session(session_id)
    return result


@app.post("/mcp/jira")
async def call_jira(req: JiraRequest):
    session_id = mcp_host.create_session(agent_id="http-client")
    params = req.dict(exclude_none=True)
    # allow alternate key names
    if "items" in params and "action_items" not in params:
        params["action_items"] = params.pop("items")
    result = await mcp_host.execute_tool(session_id, "jira", params)
    mcp_host.end_session(session_id)
    return result


@app.post("/mcp/risk")
async def call_risk(req: RiskRequest):
    session_id = mcp_host.create_session(agent_id="http-client")
    params = req.dict(exclude_none=True)
    # allow flexibility in parameter names
    if "meeting_id" not in params and "meeting" in params:
        params["meeting_id"] = params.pop("meeting")
    result = await mcp_host.execute_tool(session_id, "risk", params)
    mcp_host.end_session(session_id)
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
