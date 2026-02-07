import os
import requests
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("meeting_mcp.client.mcp_client")


class MCPClient:
    """Thin HTTP client for the MCP server.

    Env vars:
    - MCP_SERVER_URL (default: http://localhost:8000)
    - MCP_API_KEY (optional)
    """

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, timeout: int = 30):
        self.base_url = base_url or os.environ.get("MCP_SERVER_URL", "http://localhost:8000").rstrip("/")
        self.api_key = api_key or os.environ.get("MCP_API_KEY")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def create_session(self, agent_id: str = "streamlit-user") -> Optional[str]:
        url = f"{self.base_url}/session/create"
        try:
            r = requests.post(url, json={"agent_id": agent_id}, headers=self._headers(), timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            return data.get("session_id") or data.get("id")
        except Exception as e:
            logger.exception("Failed to create session: %s", e)
            return None

    def end_session(self, session_id: str) -> bool:
        url = f"{self.base_url}/session/{session_id}/end"
        try:
            r = requests.post(url, headers=self._headers(), timeout=self.timeout)
            r.raise_for_status()
            return True
        except Exception:
            logger.exception("Failed to end session %s", session_id)
            return False

    def orchestrate(self, prompt: str, params: Dict[str, Any], session_id: Optional[str] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/orchestrate"
        payload = {"prompt": prompt, "params": params}
        if session_id:
            payload["session_id"] = session_id
        try:
            r = requests.post(url, json=payload, headers=self._headers(), timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.exception("Orchestrate call failed: %s", e)
            return {"intent": "error", "results": {"error": str(e)}}
