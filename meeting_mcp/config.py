"""Configuration helpers for meeting_mcp.

This module provides lightweight helpers to load configuration from environment
variables (and `.env` during development). Secrets such as service account file
paths and API keys should be provided via environment variables.

Recommended env vars:
- MCP_SERVICE_ACCOUNT_FILE: path to Google service account JSON
- MCP_CALENDAR_ID: calendar id/email
- MCP_API_KEY: API key for FastAPI endpoints (see server)
- MCP_ALLOWED_ORIGINS: comma-separated allowed origins for CORS

For local development create a `.env` file and use python-dotenv to load it.
"""
import os
from typing import Dict, Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # python-dotenv is optional; environment variables still work.
    pass


def get_config() -> Dict[str, Any]:
    return {
        "service_account_file": os.environ.get("MCP_SERVICE_ACCOUNT_FILE"),
        "calendar_id": os.environ.get("MCP_CALENDAR_ID") or "naveenaitam@gmail.com",
        "api_key": os.environ.get("MCP_API_KEY"),
        "allowed_origins": os.environ.get("MCP_ALLOWED_ORIGINS"),
    }


def require_env(var_name: str):
    val = os.environ.get(var_name)
    if not val:
        raise EnvironmentError(f"Required environment variable {var_name} not set")
    return val


def get_bart_model_path() -> str:
    """Return BART model path or HF id.

    Resolution order:
    1. `BART_MODEL_PATH` environment variable
    2. One-line file at `meeting_mcp/config/bart_model_path.txt`
    3. None (caller may fall back to project-local default)
    """
    val = os.environ.get("BART_MODEL_PATH")
    if val:
        return val
    # Fallback to a small one-line text file next to this module
    try:
        here = os.path.abspath(os.path.join(os.path.dirname(__file__), "config", "bart_model_path.txt"))
        if os.path.exists(here):
            with open(here, "r", encoding="utf-8") as fh:
                v = fh.read().strip()
                return v or None
    except Exception:
        pass
    return None


def get_mistral_model_path() -> str:
    """Return Mistral model path.

    Resolution order:
    1. `MISTRAL_MODEL_PATH` environment variable
    2. One-line file at `meeting_mcp/config/mistral_model_path.txt`
    3. None (caller may fall back to project-local default)
    """
    val = os.environ.get("MISTRAL_MODEL_PATH")
    if val:
        return val
    try:
        here = os.path.abspath(os.path.join(os.path.dirname(__file__), "config", "mistral_model_path.txt"))
        if os.path.exists(here):
            with open(here, "r", encoding="utf-8") as fh:
                v = fh.read().strip()
                return v or None
    except Exception:
        pass
    return None
