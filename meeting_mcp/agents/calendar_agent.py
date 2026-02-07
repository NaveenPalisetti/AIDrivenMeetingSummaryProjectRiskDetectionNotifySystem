import uuid
import logging
from typing import Dict, Any, List

from ..protocols.a2a import (
    AgentCard, AgentCapability, A2AMessage, A2ATask, PartType
)

logger = logging.getLogger("meeting_mcp.agents.calendar")


class CalendarAgent:
    """Simple Calendar Agent (scaffold)

    - Provides `create_event` and `list_events` methods.
    - Includes A2A wrapper helpers for interoperability with other agents.
    """

    def __init__(self):
        self.agent_card = AgentCard(
            agent_id="calendar-agent",
            name="Calendar Agent",
            description="Handles calendar event creation and retrieval (scaffold).",
            version="0.1.0",
            base_url="",
            capabilities=[
                AgentCapability(
                    name="create_event",
                    description="Create a calendar event",
                    parameters={"event_data": "dict"}
                ),
                AgentCapability(
                    name="list_events",
                    description="List recent calendar events",
                    parameters={"time_range": "str"}
                )
            ]
        )

        # Simple in-memory events store for scaffold/demo
        self._events: Dict[str, Dict[str, Any]] = {}

    def get_agent_card(self) -> Dict[str, Any]:
        return self.agent_card.to_dict()

    # Core functionality (placeholders)
    def create_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create an event (scaffolded implementation).

        event_data should include fields like `summary`, `start`, `end`, `attendees`.
        """
        event_id = str(uuid.uuid4())
        event = {"id": event_id, **event_data}
        self._events[event_id] = event
        logger.info(f"Created calendar event: {event_id}")
        return {"status": "success", "result": event}

    def list_events(self, time_range: str = "7d") -> Dict[str, Any]:
        # time_range is ignored in scaffold; return all events
        events = list(self._events.values())
        return {"status": "success", "events": events}

    # A2A wrappers
    def handle_create_event_message(self, message: A2AMessage) -> A2AMessage:
        # Expect JSON part with event_data
        event_data = None
        for part in message.parts:
            if part.content_type == PartType.JSON:
                event_data = part.content
                break

        if not event_data:
            resp = A2AMessage(message_id=str(uuid.uuid4()), role="agent")
            resp.add_text_part("Missing event_data in message")
            return resp

        result = self.create_event(event_data)
        resp = A2AMessage(message_id=str(uuid.uuid4()), role="agent")
        resp.add_json_part(result)
        return resp

    def handle_list_events_message(self, message: A2AMessage) -> A2AMessage:
        # Optional JSON part with time_range
        time_range = None
        for part in message.parts:
            if part.content_type == PartType.JSON:
                time_range = part.content.get("time_range")
                break

        result = self.list_events(time_range or "7d")
        resp = A2AMessage(message_id=str(uuid.uuid4()), role="agent")
        resp.add_json_part(result)
        return resp
