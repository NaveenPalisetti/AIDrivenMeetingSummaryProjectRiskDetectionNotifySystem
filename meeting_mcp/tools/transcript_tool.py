import asyncio
from typing import Dict, Any, List

from meeting_mcp.core.mcp import MCPTool, MCPToolType
from meeting_mcp.agents.transcript_preprocessing_agent import TranscriptPreprocessingAgent


class TranscriptTool(MCPTool):
    def __init__(self):
        super().__init__(
            tool_id="transcript",
            tool_type=MCPToolType.DATAPREPROCESSING,
            name="Transcript Preprocessing Tool",
            description="Preprocess meeting transcripts (cleaning, chunking).",
            api_endpoint="/mcp/transcript",
            auth_required=False,
            parameters={"transcripts": "list[str]", "chunk_size": "int"}
        )
        self._agent = TranscriptPreprocessingAgent()

    async def execute(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        params = params or {}
        transcripts: List[str] = params.get("transcripts") or params.get("data") or []
        chunk_size = int(params.get("chunk_size") or 1500)
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, self._agent.process, transcripts, chunk_size)
            processed = result.get("processed") if isinstance(result, dict) else []
            debug = result.get("debug") if isinstance(result, dict) else None
            resp: Dict[str, Any] = {"status": "success", "processed": processed}
            if debug is not None:
                resp["debug"] = debug
            return resp
        except Exception as e:
            return {"status": "error", "message": str(e)}


__all__ = ["TranscriptTool"]
