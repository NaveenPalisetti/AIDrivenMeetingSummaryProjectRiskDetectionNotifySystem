import asyncio
import logging
from typing import Dict, Any

from meeting_mcp.core.mcp import MCPTool, MCPToolType
from meeting_mcp.agents.risk_detection_agent import RiskDetectionAgent
from meeting_mcp.protocols.a2a import A2AMessage, PartType
import uuid


class RiskTool(MCPTool):
    def __init__(self):
        super().__init__(
            tool_id="risk",
            tool_type=MCPToolType.RISK_DETECTION,
            name="Risk Detection Tool",
            description="Detect risks from meeting summary and tasks.",
            api_endpoint="/mcp/risk",
            auth_required=False,
            parameters={"meeting_id": "str", "summary": "dict", "tasks": "list"}
        )
        self._agent = RiskDetectionAgent()

    async def execute(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        print("RiskTool.execute called")
        logger = logging.getLogger(__name__)
        logger.debug("RiskTool.execute called")
        params = params or {}
        meeting_id = params.get("meeting_id", "ui_session")
        summary = params.get("summary", {})
        tasks = params.get("tasks", [])
        progress = params.get("progress", {})

        loop = asyncio.get_running_loop()
        try:
            # Build A2A message for risk detection
            parts = [
                {"type": PartType.MEETING_ID, "content": meeting_id},
                {"type": PartType.SUMMARY, "content": summary},
            ]
            for t in tasks:
                parts.append({"type": PartType.TASK, "content": t})
            if progress:
                parts.append({"type": PartType.PROGRESS, "content": progress})
            msg = A2AMessage(message_id=str(uuid.uuid4()), role="client", parts=parts)
            # Call the agent handler in a thread pool
            print("RiskDetectionAgent.detect_jira_risks  ",msg)
            logging.getLogger(__name__).debug("RiskDetectionAgent.detect_jira_risks %s", msg)
            result_msg = await loop.run_in_executor(None, RiskDetectionAgent.handle_detect_risk_message, msg)
            risks = result_msg.parts[0]["content"].get("risks") if result_msg.parts else []

            # Optionally, still include Jira-based risks if requested
            include_jira_param = params.get("include_jira", None)
            include_jira = include_jira_param if include_jira_param is not None else bool(self._agent.jira)
            jira_risks = []
            if include_jira and self._agent.jira:
                jira_risks = await loop.run_in_executor(None, self._agent.detect_jira_risks)
                risks = (risks or []) + (jira_risks or [])

            return {
                "status": "success",
                "risks": risks,
                "summary_risks": risks,
                "jira_risks": jira_risks,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}


__all__ = ["RiskTool"]
