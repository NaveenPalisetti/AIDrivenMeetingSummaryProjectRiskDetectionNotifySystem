from ..protocols.a2a import AgentCard, AgentCapability, A2AMessage, PartType

import logging
import os
import json
import uuid
from typing import List, Dict, Any
from datetime import date, datetime

logger = logging.getLogger("meeting_mcp.agents.jira_agent")

try:
    from jira import JIRA
except Exception:
    JIRA = None

class JiraAgent:
    print("JiraAgent loaded")
    logger.debug("JiraAgent loaded")
    AGENT_CARD = AgentCard(
        agent_id="jira_agent",
        name="JiraAgent",
        description="Handles Jira ticket creation and management via A2A protocol.",
        version="1.0",
        capabilities=[
            AgentCapability(
                name="create_jira",
                description="Create Jira issues from action items or user requests."
            ),
        ],
    )

    def __init__(self, mcp_host: object = None):
        self.mcp_host = mcp_host
        self.mcp_session_id = None
        if mcp_host is not None:
            try:
                self.mcp_session_id = mcp_host.create_session(self.AGENT_CARD.agent_id)
            except Exception:
                self.mcp_session_id = None

    @staticmethod
    def handle_create_jira_message(msg: A2AMessage) -> A2AMessage:
        print("JiraAgent loaded handle_create_jira_message ",msg)
        logger.debug("JiraAgent loaded handle_create_jira_message %s", msg)
        """Handle A2A create_jira messages."""
        # Extract action items from JSON parts (align with calendar agent pattern)
        action_items = None
        user = None
        date = None
        # Look for JSON part and accept multiple key aliases
        for part in msg.parts:
            if getattr(part, "content_type", None) == PartType.JSON:
                content = getattr(part, "content", None)
                if isinstance(content, dict):
                    # Prefer explicit action_items/arrays
                    if "action_items" in content:
                        action_items = content["action_items"]
                    elif "action_items_list" in content:
                        action_items = content["action_items_list"]
                    elif "items" in content:
                        action_items = content["items"]
                    elif "tasks" in content:
                        action_items = content["tasks"]
                    # Single-task aliases
                    elif "task" in content or "title" in content or "summary" in content:
                        # Build single action item
                        single = {
                            "summary": content.get("task") or content.get("title") or content.get("summary"),
                            "owner": content.get("owner") or content.get("assignee") or content.get("user"),
                            "due": content.get("deadline") or content.get("due") or content.get("due_date"),
                            "issue_type": content.get("issue_type") or content.get("issuetype") or content.get("type"),
                            "meeting_title": content.get("meeting_title") or content.get("meeting") or ""
                        }
                        action_items = [single]
                    if "user" in content:
                        user = content.get("user") or content.get("owner")
                    if "date" in content:
                        date = content.get("date")
                    # Keep searching other parts for more info (do not break immediately)
        logger.debug("JiraAgent.handle_create_jira_message: raw resolved action_items=%s user=%s date=%s", action_items, user, date)

        # Normalize action item entries to expected keys: `summary`, `owner`, `due`
        def _normalize_action_item(it):
            if not isinstance(it, dict):
                return {"summary": str(it), "owner": None, "due": None}
            summary = it.get("summary") or it.get("title") or it.get("task") or it.get("text") or None
            owner = it.get("owner") or it.get("assignee") or it.get("assigned_to") or it.get("user") or None
            due = it.get("due") or it.get("due_date") or it.get("deadline") or it.get("duedate") or None
            issue_type = it.get("issue_type") or it.get("issuetype") or it.get("type") or None
            meeting_title = it.get("meeting_title") or it.get("meeting") or ""
            # preserve other fields as-is (non-conflicting)
            normalized = {**{k: v for k, v in it.items() if k not in ("summary", "title", "task", "text", "owner", "assignee", "assigned_to", "user", "due", "due_date", "deadline", "duedate", "issue_type", "issuetype", "type", "meeting_title", "meeting")}}
            normalized.update({"summary": summary, "owner": owner, "due": due, "issue_type": issue_type, "meeting_title": meeting_title})
            return normalized

        try:
            if action_items:
                action_items = [_normalize_action_item(it) for it in action_items]
        except Exception:
            logger.exception("Failed to normalize action_items")
        logger.debug("JiraAgent.handle_create_jira_message: normalized action_items=%s", action_items)

        if not action_items:
            # Fallback: aggregate any JSON/text parts into action_items list
            collected = []
            for part in msg.parts:
                cont = getattr(part, "content", None)
                if isinstance(cont, dict):
                    # If dict contains single-task keys, normalize them
                    if any(k in cont for k in ("task", "title", "summary", "assignee", "due_date")):
                        collected.append(_normalize_action_item(cont))
                    else:
                        collected.append(cont)
                elif isinstance(cont, str):
                    collected.append({"summary": cont, "owner": None, "due": None})
            action_items = collected

        # Call the existing Jira creation logic
        result = JiraAgent.create_jira_issues(action_items or [], user=user, date=date)
        resp = A2AMessage(message_id=str(uuid.uuid4()), role="agent")
        resp.add_json_part(result)
        return resp
    
    @staticmethod
    def create_jira_issues(action_items: List[Dict[str, Any]], user: str = None, date: str = None) -> Dict[str, Any]:
        """Create Jira issues from a list of action items.

        This is a lightweight implementation that attempts to read Jira
        credentials from environment variables (`JIRA_URL`, `JIRA_USER`,
        `JIRA_TOKEN`, `JIRA_PROJECT`) or from `meeting_mcp/config/credentials.json`.
        If credentials or the `jira` package are missing, the function returns
        a result describing the skipped operations.
        """
        # Load credentials from meeting_mcp/config/credentials.json if present

        print("JiraAgent.create_jira_issues called with action_items:", action_items)
        logger.debug("JiraAgent.create_jira_issues called with action_items: %s", action_items)
        cred_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "credentials.json"))
        creds = {}
        try:
            if os.path.exists(cred_path):
                with open(cred_path, "r", encoding="utf-8") as fh:
                    creds = json.load(fh) or {}
        except Exception:
            creds = {}

        jira_cfg = creds.get("jira", {})
        JIRA_URL = os.environ.get("JIRA_URL") or jira_cfg.get("base_url")
        JIRA_USER = os.environ.get("JIRA_USER") or jira_cfg.get("user")
        JIRA_TOKEN = os.environ.get("JIRA_TOKEN") or jira_cfg.get("token")
        JIRA_PROJECT = os.environ.get("JIRA_PROJECT") or jira_cfg.get("project") or "PROJ"

        created = []
        if not JIRA or not JIRA_URL or not JIRA_USER or not JIRA_TOKEN:
            # Return informative result when Jira can't be used
            for item in action_items:
                title = item.get("summary") or item.get("title") or str(item)
                created.append({
                    "title": title,
                    "owner": item.get("owner"),
                    "due": item.get("due"),
                    "issue_type": item.get("issue_type"),
                    "jira_issue_key": None,
                    "status": "skipped",
                    "reason": "jira package or credentials missing"
                })
            return {"status": "skipped", "created_tasks": created}

        try:
            jira_client = JIRA(server=JIRA_URL, basic_auth=(JIRA_USER, JIRA_TOKEN))
        except Exception as e:
            for item in action_items:
                title = item.get("summary") or item.get("title") or str(item)
                created.append({
                    "title": title,
                    "owner": item.get("owner"),
                    "due": item.get("due"),
                    "issue_type": item.get("issue_type"),
                    "jira_issue_key": None,
                    "status": "error",
                    "reason": str(e)
                })
            return {"status": "error", "created_tasks": created}

        for item in action_items:
            title = item.get("summary") or item.get("title") or str(item)
            owner = item.get("owner")
            due = item.get("due")
            issue_type = item.get("issue_type") or item.get("issuetype") or item.get("type") or 'Task'
            meeting_title = item.get("meeting_title") or item.get("meeting") or ""
            # Normalize due date into Jira `duedate` (YYYY-MM-DD). If parsing fails, use today's date.         

            norm_due = _normalize_duedate(due)
            issue_fields = {
                "project": {"key": JIRA_PROJECT},
                "summary": title.replace("\n", " "),
                "description": f"Created from meeting {meeting_title}. Owner: {owner or 'Unassigned'}\nDue: {norm_due or 'Unspecified'}",
                "issuetype": {"name": issue_type or "Task"}
            }
            if norm_due:
                issue_fields["duedate"] = norm_due
            logger.debug("Creating Jira issue with fields: %s", issue_fields)
            try:
                issue = jira_client.create_issue(fields=issue_fields)
                created.append({
                    "title": title,
                    "owner": owner,
                    "due": due,
                    "issue_type": issue_type,
                    "jira_issue_key": getattr(issue, 'key', None),
                    "status": "created"
                })
            except Exception as e:
                created.append({
                    "title": title,
                    "owner": owner,
                    "due": due,
                    "issue_type": issue_type,
                    "jira_issue_key": None,
                    "status": "error",
                    "reason": str(e)
                })

        return {"status": "success", "created_tasks": created}




def _normalize_duedate(val):
    if not val:
        return None
    s = str(val).strip()
    # try ISO format first
    try:
        dt = datetime.fromisoformat(s)
        return dt.date().isoformat()
    except Exception:
        pass
    # try dateutil if available for flexible parsing
    try:
        from dateutil import parser as dateutil_parser
        dt = dateutil_parser.parse(s, dayfirst=False)
        return dt.date().isoformat()
    except Exception:
        pass
    # try common formats
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%b %d, %Y", "%d %b %Y", "%B %d, %Y", "%d %B %Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.date().isoformat()
        except Exception:
            continue
    # fallback: use today's date
    return date.today().isoformat()

    
__all__ = ["JiraAgent"]
