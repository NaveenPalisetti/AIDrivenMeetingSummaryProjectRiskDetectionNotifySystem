import uuid
import logging
from typing import Dict, Any, List, Optional

from ..protocols.a2a import AgentCard, AgentCapability, A2AMessage, PartType
from .google_calendar_adapter import MeetingMCPGoogleCalendar

logger = logging.getLogger("meeting_mcp.agents.google_calendar_agent")


class MeetingMCPGoogleCalendarAgent:
    """Agent wrapper around the local Google Calendar adapter.

    Provides an `AgentCard` and simple A2A JSON handlers so other agents
    can call calendar operations via the A2A protocol. Internally it uses
    `MeetingMCPGoogleCalendar` for the real API calls.
    """

    def __init__(self, service_account_file: Optional[str] = None, calendar_id: Optional[str] = None):
        self.agent_card = AgentCard(
            agent_id="mcp-google-calendar",
            name="MCP Google Calendar Agent",
            description="Agent wrapper for Google Calendar client",
            version="0.1.0",
            base_url="",
            capabilities=[
                AgentCapability(name="fetch_events", description="Fetch events", parameters={"start": "iso", "end": "iso"}),
                AgentCapability(name="create_event", description="Create an event", parameters={"event_data": "dict"}),
                AgentCapability(name="get_availability", description="Query freebusy", parameters={"time_min": "iso", "time_max": "iso"}),
            ],
        )

        self._gcal = MeetingMCPGoogleCalendar(service_account_file=service_account_file, calendar_id=calendar_id)

    def get_agent_card(self) -> Dict[str, Any]:
        return self.agent_card.to_dict()

    # Synchronous wrappers (adapter is blocking)
    def create_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        return self._gcal.create_event(event_data)

    def fetch_events(self, start: Optional[Any] = None, end: Optional[Any] = None) -> List[Dict[str, Any]]:
        """Return the raw list of events from the adapter (keeps compatibility
        with callers that expect the adapter signature).
        """
        events = self._gcal.fetch_events(start, end)
        return events

    def get_availability(self, time_min: str, time_max: str) -> List[Dict[str, Any]]:
        """Return the raw busy list from the adapter."""
        busy = self._gcal.get_availability(time_min, time_max)
        return busy

    # A2A message handlers
    def handle_fetch_message(self, message: A2AMessage) -> A2AMessage:
        start = None
        end = None
        for part in message.parts:
            if part.content_type == PartType.JSON:
                start = part.content.get("start")
                end = part.content.get("end")
                break
        events = self.fetch_events(start, end)
        resp = A2AMessage(message_id=str(uuid.uuid4()), role="agent")
        resp.add_json_part({"status": "success", "events": events})
        return resp

    def handle_create_message(self, message: A2AMessage) -> A2AMessage:
        event_data = None
        for part in message.parts:
            if part.content_type == PartType.JSON:
                event_data = part.content.get("event_data") or part.content
                break

        if not event_data:
            resp = A2AMessage(message_id=str(uuid.uuid4()), role="agent")
            resp.add_text_part("Missing event_data in message")
            return resp

        created = self.create_event(event_data)
        resp = A2AMessage(message_id=str(uuid.uuid4()), role="agent")
        resp.add_json_part({"status": "success", "event": created})
        return resp

    def handle_availability_message(self, message: A2AMessage) -> A2AMessage:
        time_min = None
        time_max = None
        for part in message.parts:
            if part.content_type == PartType.JSON:
                time_min = part.content.get("time_min") or part.content.get("timeMin")
                time_max = part.content.get("time_max") or part.content.get("timeMax")
                break

        busy = self.get_availability(time_min, time_max)
        resp = A2AMessage(message_id=str(uuid.uuid4()), role="agent")
        resp.add_json_part({"status": "success", "busy": busy})
        return resp


__all__ = ["MeetingMCPGoogleCalendarAgent"]
