import uuid
import datetime
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Any

logger = logging.getLogger("meeting_mcp.mcp")


class MCPToolType(Enum):
    CALENDAR = "calendar"
    DATAPREPROCESSING = "data_preprocessing"
    SUMMARIZATION = "summarization"
    NOTIFICATION = "notification"
    RISK_DETECTION = "risk_detection"
    JIRA = "jira"
    OTHER = "other"


@dataclass
class MCPTool:
    tool_id: str
    tool_type: MCPToolType
    name: str
    description: str
    api_endpoint: str = ""
    auth_required: bool = False
    parameters: Dict[str, Any] = field(default_factory=dict)

    async def execute(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        logger.info(f"Executing MCP tool base: {self.name}")
        return {"status": "error", "message": "Not implemented"}


class MCPHost:
    def __init__(self):
        self.tools: Dict[str, MCPTool] = {}
        self.sessions: Dict[str, Dict[str, Any]] = {}
        logger.info("meeting_mcp MCPHost initialized")

    def register_tool(self, tool: MCPTool):
        self.tools[tool.tool_id] = tool
        logger.info(f"Tool registered: {tool.name} ({tool.tool_id})")

    def create_session(self, agent_id: str) -> str:
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = {
            "agent_id": agent_id,
            "created_at": datetime.datetime.now().isoformat(),
            "active": True,
            "context": {}
        }
        logger.info(f"Session created: {session_id} for agent {agent_id}")
        return session_id

    async def execute_tool(self, session_id: str, tool_id: str, parameters: Dict[str, Any] = None) -> Dict[str, Any]:
        if session_id not in self.sessions:
            return {"status": "error", "message": "Invalid session ID"}
        if not self.sessions[session_id]["active"]:
            return {"status": "error", "message": "Session not active"}
        if tool_id not in self.tools:
            return {"status": "error", "message": "Tool not found"}

        tool = self.tools[tool_id]
        try:
            result = await tool.execute(parameters or {})
            return result
        except Exception as e:
            logger.exception(f"Error executing tool {tool_id}: {e}")
            return {"status": "error", "message": str(e)}

    def get_available_tools(self, session_id: str) -> List[Dict[str, Any]]:
        if session_id not in self.sessions or not self.sessions[session_id]["active"]:
            return []
        return [
            {
                "tool_id": t.tool_id,
                "name": t.name,
                "description": t.description,
                "tool_type": t.tool_type.value,
                "parameters": t.parameters
            }
            for t in self.tools.values()
        ]

    def end_session(self, session_id: str) -> bool:
        if session_id not in self.sessions:
            return False
        self.sessions[session_id]["active"] = False
        logger.info(f"Session ended: {session_id}")
        return True
