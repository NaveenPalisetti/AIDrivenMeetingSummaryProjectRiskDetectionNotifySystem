import logging
from typing import Optional, Dict, Any, List

from meeting_mcp.core.mcp import MCPHost

logger = logging.getLogger("meeting_mcp.agents.orchestrator")


class OrchestratorAgent:
    """Simple orchestrator / coordinator agent.

    Responsibilities:
    - detect simple intent from a user message
    - route to one or more tool IDs registered on the provided `MCPHost`
    - create a short-lived session and invoke tools via `MCPHost.execute_tool`

    This is a scaffold to extend with richer routing, async workflows,
    retries, and parallel execution.
    """

    def __init__(self, mcp_host: Optional[MCPHost] = None):
        self.mcp_host = mcp_host or MCPHost()
        self.agent_id = "orchestrator"

    def detect_intent(self, text: str) -> str:
        """Very small heuristic intent detector. Extend or replace with an LLM-based intent classifier."""
        t = (text or "").lower()
        # Prioritize explicit preprocessing/transcript commands before generic calendar keywords
        if any(k in t for k in ("preprocess", "pre-processing", "process", "transcript", "transcripts", "clean")):
            return "preprocess"
        # If the user asked for a summary, prefer that before generic calendar keywords
        if "summar" in t or "summary" in t:
            return "summarize"
        if "risk" in t or "detect risk" in t or "risks" in t:
            return "risk"
        # Map obvious calendar-related verbs/words to the calendar intent
        if any(k in t for k in ("calendar", "events", "fetch")):
            return "calendar"
        if "jira" in t or "ticket" in t or "issue" in t:
            return "jira"
        if "notify" in t or "email" in t:
            return "notify"
        return "default"

    async def route_agents(self, intent: str) -> List[str]:
        """Map an intent to one or more tool IDs available in the MCPHost.

        Keep this mapping small and configurable in real systems.
        """
        mapping = {
            "calendar": ["calendar"],
            "preprocess": ["transcript"],
            "summarize": ["summarization"],
            "risk": ["risk"],        
            "jira": ["jira"],
            "notify": ["notification"],
            "default": ["summarization"]
        }
        return mapping.get(intent, ["summarization"])

    async def orchestrate(
        self,
        user_message: str,
        params: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Top-level orchestrate API: detect intent, call routed tools, return aggregated response.

        If `session_id` is provided the orchestrator will reuse it and will not
        create or end the session. If `session_id` is None a short-lived
        session is created and ended around the orchestration call.
        """
        intent = self.detect_intent(user_message)
        tool_ids = await self.route_agents(intent)

        created_session = False
        if session_id is None:
            session_id = self.mcp_host.create_session(agent_id=self.agent_id)
            created_session = True

        aggregated: Dict[str, Any] = {"intent": intent, "results": {}}

        try:
            for tid in tool_ids:
                print(f"OrchestratorAgent calling tool {tid} with params: {params}")
                logger.debug("OrchestratorAgent calling tool %s with params: %s", tid, params)
                try:
                    # Pass through params; tools should document expected params for each action
                    res = await self.mcp_host.execute_tool(session_id, tid, params or {})
                    aggregated["results"][tid] = res
                except Exception as e:
                    logger.exception(f"Tool {tid} failed: {e}")
                    aggregated["results"][tid] = {"status": "error", "message": str(e)}
        finally:
            if created_session:
                self.mcp_host.end_session(session_id)

        return aggregated


if __name__ == "__main__":
    import asyncio
    import json

    # Quick manual test / demo
    host = MCPHost()
    # In real use, register tools with host before orchestrating
    orch = OrchestratorAgent(mcp_host=host)

    async def demo():
        res = await orch.orchestrate("Please fetch my calendar events for next week", params={"action": "fetch", "start": None, "end": None})
        print(json.dumps(res, indent=2))
        logger.debug(json.dumps(res, indent=2))

    asyncio.run(demo())
