import asyncio
import uuid
from typing import Dict, Any

from meeting_mcp.core.mcp import MCPTool, MCPToolType
from meeting_mcp.protocols.a2a import A2AMessage, PartType
# Use the meeting-local Google Calendar agent wrapper so calendar functionality
# can be treated as an agent while still exposing an MCP Tool surface.
from meeting_mcp.agents.google_calendar_agent import MeetingMCPGoogleCalendarAgent as MCPGoogleCalendar


class CalendarTool(MCPTool):
    def __init__(self):
        super().__init__(
            tool_id="calendar",
            tool_type=MCPToolType.CALENDAR,
            name="Calendar Tool",
            description="MCP Tool wrapper around Google Calendar client",
            api_endpoint="/mcp/calendar",
            auth_required=False,
            parameters={"action": "create|fetch|list|availability", "event_data": "dict", "start": "datetime|ISO", "end": "datetime|ISO"}
        )
        # Instantiate the agent wrapper (holds the adapter internally)
        self._gcal = MCPGoogleCalendar()

    async def execute(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        params = params or {}
        action = params.get("action", "fetch")
        loop = asyncio.get_running_loop()

        try:
            # Allow overriding calendar per-call (useful when service-account vs user calendars differ)
            calendar_id = params.get("calendar_id")
            client = self._gcal
            if calendar_id:
                # Create a short-lived client tied to the requested calendar id
                client = MCPGoogleCalendar(calendar_id=calendar_id)

            if action == "create":
                event_data = params.get("event_data", {})
                # Build A2A message and call agent handler in executor
                msg = A2AMessage(message_id=str(uuid.uuid4()), role="client")
                msg.add_json_part({"event_data": event_data})
                resp = await loop.run_in_executor(None, client.handle_create_message, msg)
                # unwrap JSON part from response
                for part in resp.parts:
                    if part.content_type == PartType.JSON:
                        return part.content
                return {"status": "error", "message": "No JSON part in agent response"}

            if action == "availability":
                time_min = params.get("time_min")
                time_max = params.get("time_max")
                msg = A2AMessage(message_id=str(uuid.uuid4()), role="client")
                msg.add_json_part({"time_min": time_min, "time_max": time_max})
                resp = await loop.run_in_executor(None, client.handle_availability_message, msg)
                for part in resp.parts:
                    if part.content_type == PartType.JSON:
                        return part.content
                return {"status": "error", "message": "No JSON part in agent response"}

            if action in ("fetch", "list"):
                start = params.get("start")
                end = params.get("end")
                msg = A2AMessage(message_id=str(uuid.uuid4()), role="client")
                msg.add_json_part({"start": start, "end": end})
                resp = await loop.run_in_executor(None, client.handle_fetch_message, msg)
                for part in resp.parts:
                    if part.content_type == PartType.JSON:
                        return part.content
                return {"status": "error", "message": "No JSON part in agent response"}

            return {"status": "error", "message": f"Unknown action: {action}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
