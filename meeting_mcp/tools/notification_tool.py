import asyncio
from typing import Dict, Any

from meeting_mcp.core.mcp import MCPTool, MCPToolType
from meeting_mcp.agents.notification_agent import NotificationAgent
from meeting_mcp.protocols.a2a import A2AMessage, PartType
import uuid


class NotificationTool(MCPTool):
    def __init__(self):
        super().__init__(
            tool_id="notification",
            tool_type=MCPToolType.NOTIFICATION,
            name="Notification Tool",
            description="Send meeting summary/risks/tasks to external notification channels.",
            api_endpoint="/mcp/notify",
            auth_required=False,
            parameters={"meeting_id": "str", "summary": "dict", "tasks": "list", "risks": "list"}
        )
        self._agent = NotificationAgent()

    async def execute(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        params = params or {}
        meeting_id = params.get("meeting_id", "ui_session")
        summary = params.get("summary", {})
        tasks = params.get("tasks", [])
        risks = params.get("risks", [])

        loop = asyncio.get_running_loop()
        try:
            # Build A2A message for notification
            parts = [
                {"type": PartType.MEETING_ID, "content": meeting_id},
                {"type": PartType.SUMMARY, "content": summary},
            ]
            for t in tasks:
                parts.append({"type": PartType.TASK, "content": t})
            for r in risks:
                parts.append({"type": PartType.RISK, "content": r})
            msg = A2AMessage(message_id=str(uuid.uuid4()), role="client", parts=parts)
            # Call the agent handler in a thread pool
            result_msg = await loop.run_in_executor(None, NotificationAgent.handle_notify_message, msg)
            notified = result_msg.parts[0]["content"].get("notified") if result_msg.parts else False
            return {"status": "success", "notified": notified}
        except Exception as e:
            return {"status": "error", "message": str(e)}


__all__ = ["NotificationTool"]
