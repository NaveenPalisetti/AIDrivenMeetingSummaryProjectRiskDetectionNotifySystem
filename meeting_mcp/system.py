"""System wiring helper for meeting_mcp.

Provides a simple hybrid wiring: an in-process host for local direct calls
and an MCPHost for registered tools (HTTP exposure). The `create_system`
factory returns both hosts, a tools map and an `OrchestratorAgent` ready to
be used by the UI or server startup code.

Usage:
    host, inproc, tools, orchestrator = create_system(mode="hybrid")

Modes:
 - "hybrid": register tools on a real `MCPHost` (for HTTP) and also
   populate an `InProcessHost` for UI tests.
 - "in_process": do not use `MCPHost`; register tools on `InProcessHost`
   only and wire the `OrchestratorAgent` to use the in-process host.
 - "hosted": same as hybrid but intended to emphasize server-only usage.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Dict, Any, Optional, Tuple

from meeting_mcp.core.mcp import MCPHost
from meeting_mcp.tools.calendar_tool import CalendarTool
from meeting_mcp.tools.transcript_tool import TranscriptTool
from meeting_mcp.tools.summarization_tool import SummarizationTool
from meeting_mcp.tools.jira_tool import JiraTool
from meeting_mcp.tools.risk_tool import RiskTool
from meeting_mcp.tools.notification_tool import NotificationTool
from meeting_mcp.agents.orchestrator_agent import OrchestratorAgent



class InProcessHost:
    """A tiny, in-process host that mimics the minimal MCPHost API used
    by `OrchestratorAgent` for local development and testing.
    """

    def __init__(self):
        self._tools: Dict[str, Any] = {}
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def register_tool(self, tool):
        self._tools[tool.tool_id] = tool

    def create_session(self, agent_id: str) -> str:
        sid = str(uuid.uuid4())
        self._sessions[sid] = {"agent_id": agent_id}
        return sid

    async def execute_tool(self, session_id: str, tool_id: str, params: Optional[Dict[str, Any]] = None):
        if session_id not in self._sessions:
            raise RuntimeError("Invalid session")
        tool = self._tools.get(tool_id)
        if not tool:
            raise RuntimeError(f"Tool not registered: {tool_id}")
        # Most tools implement async `execute`; await directly.
        return await tool.execute(params or {})

    def end_session(self, session_id: str):
        self._sessions.pop(session_id, None)


def create_system(mode: str = "hybrid") -> Tuple[Any, InProcessHost, Dict[str, Any], OrchestratorAgent]:
    """Create and wire system components based on `mode`.

    Returns: (mcp_host, inproc_host, tools_map, orchestrator)
    """
    mode = (mode or "hybrid").lower()

    # No in-process host: always use an external MCPHost for tool execution.
    inproc = None

    # Create tools/adapters
    calendar_tool = CalendarTool()
    transcript_tool = TranscriptTool()
    summarization_tool = SummarizationTool()
    jira_tool = JiraTool()
    risk_tool = RiskTool()
    notification_tool = NotificationTool()

    tools = {
        "calendar": calendar_tool,
        "transcript": transcript_tool,
        "summarization": summarization_tool,
        "jira": jira_tool,
        "risk": risk_tool
        ,"notification": notification_tool
    }

    # Always create a real MCPHost and register tools there.
    mcp_host = MCPHost()
    mcp_host.register_tool(calendar_tool)
    mcp_host.register_tool(transcript_tool)
    mcp_host.register_tool(summarization_tool)
    mcp_host.register_tool(jira_tool)
    mcp_host.register_tool(risk_tool)
    mcp_host.register_tool(notification_tool)

    # Build a minimal agents registry (used by OrchestratorAgent to call
    # agents via A2A handlers). Keyed by the tool id used in routing.
    
    # Orchestrator wired to whichever host we consider the authoritative
    # execution surface. Provide the agents registry so orchestrations
    # can use A2A when appropriate, falling back to MCP tools.
    orchestrator = OrchestratorAgent(mcp_host=mcp_host)

    return mcp_host, inproc, tools, orchestrator


__all__ = ["InProcessHost", "create_system"]
