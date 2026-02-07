import asyncio
import uuid
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

from meeting_mcp.core.mcp import MCPTool, MCPToolType
from meeting_mcp.agents.jira_agent import JiraAgent
from meeting_mcp.protocols.a2a import A2AMessage, PartType


class JiraTool(MCPTool):
    def __init__(self):
        print("JiraTool initialized")
        logger.debug("JiraTool initialized")
        super().__init__(
            tool_id="jira",
            tool_type=MCPToolType.JIRA,
            name="Jira Tool",
            description="Create Jira issues from action items extracted from meetings.",
            api_endpoint="/mcp/jira",
            auth_required=False,
            parameters={"action_items": "list[dict]", "action_items_list": "list[dict]", "task": "str", "owner": "str", "deadline": "str", "user": "str", "date": "str"}
        )

    async def execute(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        print("JiraTool.execute called",params)
        logger.debug("JiraTool.execute called %s", params)
        params = params or {}
        # Accept multiple aliases for action items and single-task shortcuts
        action_items: List[Dict[str, Any]] = params.get("action_items") or params.get("action_items_list") or params.get("items") or params.get("tasks") or []
        user = params.get("user")
        date = params.get("date")

        # If caller passed single task via 'task'/'owner'/'deadline', convert to action_items
        if not action_items and (params.get("task") or params.get("owner") or params.get("deadline") or params.get("due") or params.get("due_date")):
            single = {
                "summary": params.get("task") or params.get("title") or params.get("summary"),
                "owner": params.get("owner") or params.get("assignee") or params.get("user"),
                "due": params.get("deadline") or params.get("due") or params.get("due_date")
            }
            action_items = [single]

        logger.debug("JiraTool.execute called with params keys: %s", list(params.keys()))
        logger.debug("Resolved action_items count: %d", len(action_items))
        loop = asyncio.get_running_loop()
        try:
            # Build A2A message for Jira agent with a single JSON part
            msg = A2AMessage(message_id=str(uuid.uuid4()), role="client")
            msg.add_json_part({"action_items": action_items, "user": user, "date": date})
            # Call the agent handler in a thread pool
            result_msg = await loop.run_in_executor(None, JiraAgent.handle_create_jira_message, msg)
            # Unwrap JSON part from response
            for part in result_msg.parts:
                if getattr(part, "content_type", None) == PartType.JSON:
                    return {"status": "success", "results": part.content}
            return {"status": "error", "message": "No JSON part in agent response"}
        except Exception as e:
            return {"status": "error", "message": str(e)}


__all__ = ["JiraTool"]
