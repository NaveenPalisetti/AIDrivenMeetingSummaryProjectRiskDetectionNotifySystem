
from ..protocols.a2a import AgentCard, AgentCapability, A2AMessage, PartType

import os
import json
import uuid
import base64
from typing import List, Dict, Any
import logging

try:
    import requests
except ImportError:
    requests = None

try:
    from jira import JIRA
except ImportError:
    JIRA = None

logger = logging.getLogger(__name__)


class RiskDetectionAgent:
    """Detects risks from meeting summaries and Jira using the updated v3 JQL API."""
    
    AGENT_CARD = AgentCard(
        agent_id="risk_detection_agent",
        name="RiskDetectionAgent",
        description="Detects risks from meeting summaries, tasks, and Jira via A2A protocol.",
        version="1.0",
        capabilities=[
            AgentCapability(
                name="detect_risk",
                description="Detect risks from meeting summary, tasks, and Jira."
            ),
        ],
    )

    @staticmethod
    def handle_detect_risk_message(msg: A2AMessage) -> A2AMessage:
        """Handle A2A detect_risk messages."""
        meeting_id = next((p.get("content") for p in msg.parts if p.get("type") in (PartType.MEETING_ID, "meeting_id")), "unknown")
        summary = next((p.get("content") for p in msg.parts if p.get("type") in (PartType.SUMMARY, "summary")), "")
        tasks = [p.get("content") for p in msg.parts if p.get("type") in (PartType.TASK, PartType.ACTION_ITEM, "task", "action_item")]
        progress = next((p.get("content") for p in msg.parts if p.get("type") in (PartType.PROGRESS, "progress")), {})

        agent = RiskDetectionAgent()
        risks = agent.detect(meeting_id, summary, tasks, progress)
        return A2AMessage(message_id=str(uuid.uuid4()), role="agent", parts=[
            {"type": PartType.RESULT, "content": {"risks": risks}}
        ])

    def __init__(self, mcp_host: object = None):
        self.jira_project = os.environ.get("JIRA_PROJECT")
        self.jira_url = os.environ.get('JIRA_URL')
        self.jira_user = os.environ.get('JIRA_USER')
        self.jira_token = os.environ.get('JIRA_TOKEN')

        cred_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'credentials.json')
        if os.path.exists(cred_path):
            try:
                with open(cred_path, 'r', encoding='utf-8') as fh:
                    creds = json.load(fh).get('jira', {})
                    self.jira_url = self.jira_url or creds.get('base_url')
                    self.jira_user = self.jira_user or creds.get('user')
                    self.jira_token = self.jira_token or creds.get('token')
                    self.jira_project = self.jira_project or creds.get('project')
            except Exception:
                pass

        self.jira = None
        if JIRA and self.jira_url and self.jira_user and self.jira_token:
            try:
                self.jira = JIRA(server=self.jira_url, basic_auth=(self.jira_user, self.jira_token), options={"rest_api_version": "3"})
            except Exception:
                pass

    def _search_jql_with_rest(self, jql: str, maxResults: int = 50) -> List[Dict[str, Any]]:
        """Bypasses deprecated search methods to use the mandatory /search/jql endpoint."""
        if not (requests and self.jira_url and self.jira_user and self.jira_token):
            return []

        url = f"{self.jira_url.rstrip('/')}/rest/api/3/search/jql"
        auth_str = base64.b64encode(f"{self.jira_user}:{self.jira_token}".encode('utf-8')).decode('ascii')
        
        headers = {
            'Authorization': f'Basic {auth_str}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        # Request specific fields to ensure 'key' and useful fields are returned.
        payload = {
            "jql": jql,
            "maxResults": maxResults,
            "fields": ["summary", "assignee", "duedate", "comment", "priority"],
            "fieldsByKeys": False
        }

        try:
            r = requests.post(url, json=payload, headers=headers, timeout=30)
            r.raise_for_status()
            return r.json().get('issues', [])
        except Exception as e:
            logger.exception("Jira API Error while executing JQL: %s", jql)
            return []

    def _get_issue_by_id(self, issue_id_or_key: str) -> Dict[str, Any]:
        """Fetch a full issue by id or key to obtain `key` and `fields` when JQL returns minimal items."""
        if not (requests and self.jira_url and self.jira_user and self.jira_token and issue_id_or_key):
            return {}
        url = f"{self.jira_url.rstrip('/')}/rest/api/3/issue/{issue_id_or_key}"
        auth_str = base64.b64encode(f"{self.jira_user}:{self.jira_token}".encode('utf-8')).decode('ascii')
        headers = {
            'Authorization': f'Basic {auth_str}',
            'Accept': 'application/json'
        }
        try:
            r = requests.get(url, headers=headers, timeout=20)
            r.raise_for_status()
            return r.json()
        except Exception:
            logger.exception("Failed to fetch issue details for %s", issue_id_or_key)
            return {}

    def detect(self, meeting_id: str, summary: Any, tasks: List[Any], progress: Any) -> List[Dict[str, Any]]:
        """Heuristic detection for text-based risks."""
        risks = []
        summary_text = summary.get("summary_text", "") if isinstance(summary, dict) else str(summary)
        
        # Check for explicit blockers
        if isinstance(summary, dict) and summary.get("blockers"):
            for b in summary["blockers"]:
                risks.append({"id": f"risk_{uuid.uuid4().hex[:6]}", "description": str(b), "severity": "high", "source": "summary"})

        # Heuristic keywords
        if any(term in summary_text.lower() for term in ["delay", "blocked", "risk", "concern"]):
            risks.append({"id": f"risk_{uuid.uuid4().hex[:6]}", "description": "Potential risk detected in meeting content.", "severity": "medium", "source": "summary"})

        return risks or [{"id": "none", "description": "No immediate risks detected.", "severity": "low", "source": "analysis"}]


    def detect_jira_risks(self, days_stale: int = 7) -> List[Dict[str, Any]]:
        """Scans Jira and clubs risks by Task ID, keeping the highest severity."""
        # Mapping to compare severity levels
        severity_rank = {"high": 3, "medium": 2, "low": 1}
        grouped_risks = {} # Key: task_id, Value: risk_entry_dict

        if not self.jira_url: return []

        queries = {
            "unassigned": f'project="{self.jira_project}" AND assignee is EMPTY AND statusCategory != Done',
            "overdue": f'project="{self.jira_project}" AND duedate <= now() AND statusCategory != Done',
            "blocked": f'project="{self.jira_project}" AND (flagged = Impediment OR status = Blocked) AND statusCategory != Done',
            "stale": f'project="{self.jira_project}" AND updated <= "-{days_stale}d" AND statusCategory != Done',
            "high_priority_open": f'project="{self.jira_project}" AND priority in (Highest, High) AND statusCategory != Done',
            "missing_estimate": f'project="{self.jira_project}" AND "Story Points" is EMPTY AND issuetype = Story AND statusCategory != Done',
            "recent_scope_addition": f'project="{self.jira_project}" AND created >= "-24h"'
        }
        
        for r_type, jql in queries.items():
            issues = self._search_jql_with_rest(jql)
            for isu in issues:
                if not isinstance(isu, dict): continue
                if 'fields' not in isu or 'key' not in isu:
                    full = self._get_issue_by_id(isu.get('id') or isu.get('key'))
                    if full: isu = full

                fields = isu.get('fields', {})
                task_id = isu.get('key')
                task_summary = fields.get('summary')
                
                # Determine severity for this specific risk type
                current_severity = 'medium'
                if r_type in ["overdue", "blocked", "high_priority_open"]:
                    current_severity = 'high'
                elif r_type == "unassigned" and fields.get('priority') in ['Highest', 'High']:
                    current_severity = 'high'

                # Clubbing Logic
                if task_id in grouped_risks:
                    # 1. Update Severity if current is higher
                    existing_sev = grouped_risks[task_id]['severity']
                    if severity_rank[current_severity] > severity_rank[existing_sev]:
                        grouped_risks[task_id]['severity'] = current_severity
                    
                    # 2. Append to description
                    if r_type not in grouped_risks[task_id]['detected_types']:
                        grouped_risks[task_id]['description'] += f" | Also flagged as {r_type}."
                        grouped_risks[task_id]['detected_types'].add(r_type)
                else:
                    # New entry for this task
                    grouped_risks[task_id] = {
                        'type': r_type, # Primary type
                        'key': task_id,
                        'summary': task_summary,
                        'severity': current_severity,
                        'source': 'jira',
                        'description': f"Jira {r_type} risk detected for {task_id}.",
                        'detected_types': {r_type} # Helper to avoid duplicate descriptions
                    }

        # Convert dictionary back to list and remove helper field
        final_risks = []
        for risk in grouped_risks.values():
            del risk['detected_types']
            final_risks.append(risk)

        return final_risks
    def detect_jira_risks1(self, days_stale: int = 7) -> List[Dict[str, Any]]:
        """Scans Jira for an expanded set of risk signals including unassigned and high-activity tasks."""
        risks = []
        if not self.jira_url: return risks

        # Define specialized JQL queries for risk detection
        queries = {
            # 1. Ownership Risk
            "unassigned": f'project="{self.jira_project}" AND assignee is EMPTY AND statusCategory != Done',
            
            # 2. Schedule Risk
            "overdue": f'project="{self.jira_project}" AND duedate <= now() AND statusCategory != Done',
            
            # 3. Dependency Risk
            "blocked": f'project="{self.jira_project}" AND (flagged = Impediment OR status = Blocked) AND statusCategory != Done',
            
            # 4. Momentum Risk
            "stale": f'project="{self.jira_project}" AND updated <= "-{days_stale}d" AND statusCategory != Done',
            
            # 5. Prioritization Risk
            "high_priority_open": f'project="{self.jira_project}" AND priority in (Highest, High) AND statusCategory != Done',
            
            # 6. Planning Risk (Missing estimates for stories)
            "missing_estimate": f'project="{self.jira_project}" AND "Story Points" is EMPTY AND issuetype = Story AND statusCategory != Done',
            
            # 7. Scope Creep (Excessive tasks created recently)
            "recent_scope_addition": f'project="{self.jira_project}" AND created >= "-24h"'
        }
        logger.info("Running Jira risk detection with queries: %s", queries)
        
        for r_type, jql in queries.items():
            issues = self._search_jql_with_rest(jql)
            print("Jira risk detection query:", jql, "found", len(issues), "issues")
            logger.debug("Jira risk detection query: %s found %d issues", jql, len(issues))
            print("Jira risk detection query: ", issues)
            logger.debug("Jira risk detection issues: %s", issues)
            for isu in issues:
                # If the JQL response contains only minimal objects (e.g. {'id': '10695'}),
                # fetch the full issue to obtain 'key' and 'fields'.
                if not isinstance(isu, dict):
                    continue
                if 'fields' not in isu or 'key' not in isu:
                    full = self._get_issue_by_id(isu.get('id') or isu.get('key'))
                    print("Jira risk detection full : ", full)
                    logger.debug("Jira risk detection full issue fetched: %s", full)
                    if full:
                        isu = full

                fields = isu.get('fields', {})
                # 2. Extract specific ID (key) and Summary
                task_id = isu.get('key')  # e.g., MLPRJCTSCR-10
                task_summary = fields.get('summary')  # e.g., "Implement Login API"
               
                
                # Check for high communication volume (Sign of confusion or requirement instability)
                comment_total = fields.get('comment', {}).get('total', 0)
                
                risk_entry = {
                    'type': r_type,                    
                    'key': task_id,           # Now populating the Task ID
                    'summary': task_summary,   # Now populating the Summary                    
                    'severity': 'medium',
                    'description': f"Jira {r_type} risk detected for {task_id}."
                }

                # --- Severity Overrides ---
                if r_type in ["overdue", "blocked", "high_priority_open"]:
                    risk_entry['severity'] = 'high'
                
                if r_type == "unassigned":
                    risk_entry['description'] = "Task has no owner; high risk of being missed."
                    risk_entry['severity'] = 'high' if fields.get('priority') in ['Highest', 'High'] else 'medium'

                if comment_total > 10:
                    risk_entry['description'] += f" | Warning: High discussion volume ({comment_total} comments)."
                    risk_entry['severity'] = 'high' if risk_entry['severity'] == 'high' else 'medium'

                risks.append(risk_entry)
        logger.info("Detected Jira risks: %d entries", len(risks))
        return risks

__all__ = ["RiskDetectionAgent"]    