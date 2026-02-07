import asyncio
from typing import Dict, Any, List

from meeting_mcp.core.mcp import MCPTool, MCPToolType
from meeting_mcp.agents.summarization_agent import SummarizationAgent
from meeting_mcp.protocols.a2a import A2AMessage, PartType
import uuid

class SummarizationTool(MCPTool):
    def __init__(self):
        super().__init__(
            tool_id="summarization",
            tool_type=MCPToolType.SUMMARIZATION,
            name="Summarization Tool",
            description="Summarize processed transcript chunks using BART or Mistral.",
            api_endpoint="/mcp/summarize",
            auth_required=False,
            parameters={"processed_transcripts": "list[str]", "mode": "str"}
        )
        self._agent = SummarizationAgent()

    async def execute(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        params = params or {}
        processed: List[str] = params.get("processed_transcripts") or params.get("processed") or []
        mode = params.get("mode") or params.get("summarizer") or None
        loop = asyncio.get_running_loop()

        try:
            # Build A2AMessage for A2A-compliant summarization
            msg = A2AMessage(message_id=str(uuid.uuid4()), role="client")
            msg.add_json_part({"processed_transcripts": processed, "mode": mode})
            # Run the agent's handle_summarize_message in an executor
            resp = await loop.run_in_executor(None, self._agent.handle_summarize_message, msg)
            # Unwrap the JSON part from the response
            for part in getattr(resp, "parts", []):
                if part.content_type == PartType.JSON:
                    content = part.content
                    if isinstance(content, dict) and content.get("status") == "success":
                        return {"status": "success", "summary": content.get("results", {})}
                    return content
            return {"status": "error", "message": "No valid JSON response from summarization agent."}
        except Exception as e:
            return {"status": "error", "message": str(e)}


__all__ = ["SummarizationTool"]
