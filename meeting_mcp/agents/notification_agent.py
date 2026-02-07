from ..protocols.a2a import AgentCard, AgentCapability, A2AMessage, PartType
import os
import json
import uuid
from datetime import datetime
import logging
try:
    import requests
except Exception:
    requests = None

logger = logging.getLogger(__name__)


def _load_creds():
    """Load credentials from meeting_mcp/config/credentials.json if present.

    Returns an empty dict on any failure so callers can safely fallback to env vars.
    """
    try:
        base = os.path.dirname(os.path.dirname(__file__))
        cred_path = os.path.join(base, 'config', 'credentials.json')
        if os.path.exists(cred_path):
            with open(cred_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}



class NotificationAgent:
    AGENT_CARD = AgentCard(
        agent_id="notification_agent",
        name="NotificationAgent",
        description="Sends meeting summary, tasks, and risks to external notification channels via A2A protocol.",
        version="1.0",
        capabilities=[
            AgentCapability(
                name="notify",
                description="Send meeting summary, tasks, and risks to notification channels."
            ),
        ],
    )

    def __init__(self):
        creds = _load_creds()
        # Prefer environment variables, fall back to credentials file keys.
        self.slack_webhook = os.environ.get('SLACK_WEBHOOK_URL') or creds.get('SLACK_WEBHOOK_URL') or creds.get('slack_webhook')
        # Optional UI link to the workspace
        self.slack_url = os.environ.get('SLACK_URL') or creds.get('SLACK_URL') or creds.get('slack_url')

    def notify(self, meeting_id: str, summary: dict, tasks: list, risks: list):
        payload = {
            'meeting_id': meeting_id,
            'summary': summary.get('summary_text') if isinstance(summary, dict) else str(summary),
            'num_tasks': len(tasks) if isinstance(tasks, list) else 0,
            'risks': risks,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }
        print('=== Notification ===')
        logger.debug('=== Notification ===')
        print(json.dumps(payload, indent=2))
        logger.debug(json.dumps(payload, indent=2))
        print('====================', self.slack_webhook)
        logger.debug('==================== %s', self.slack_webhook)
        if self.slack_webhook and requests:
            print('Sending Slack notification...')
            logger.debug('Sending Slack notification...')
            try:
                # Send a human-friendly text plus the full payload as a JSON code block
                text = f"Meeting {meeting_id} summary: {payload['summary']}\n\nFull payload:\n```json\n{json.dumps(payload, indent=2)}\n```"
                # Post as JSON; Slack will render the code block for readability
                print('Posting to Slack text:', text)
                logger.debug('Posting to Slack text: %s', text)
                r = requests.post(self.slack_webhook, json={"text": text}, timeout=15)
                try:
                    print('Slack response:', r.status_code, r.text)
                    logger.debug('Slack response: %s %s', r.status_code, r.text)
                except Exception:
                    pass
            except Exception as e:
                print('Slack notify failed:', e)
                logger.debug('Slack notify failed: %s', e)
        return True

    @staticmethod
    def handle_notify_message(msg: A2AMessage) -> A2AMessage:
        """Handle A2A notify messages."""
        meeting_id = None
        summary = None
        tasks = []
        risks = []
        for part in msg.parts:
            ptype = part.get("type")
            if ptype in (PartType.MEETING_ID, "meeting_id"):
                meeting_id = part.get("content")
            elif ptype in (PartType.SUMMARY, "summary"):
                summary = part.get("content")
            elif ptype in (PartType.TASK, PartType.ACTION_ITEM, "task", "action_item"):
                tasks.append(part.get("content"))
            elif ptype in (PartType.RISK, "risk"):
                risks.append(part.get("content"))
        if not meeting_id:
            meeting_id = "unknown"
        if summary is None:
            summary = ""
        agent = NotificationAgent()
        notified = agent.notify(meeting_id, summary, tasks, risks)
        return A2AMessage(message_id=str(uuid.uuid4()), role="agent", parts=[
            {
                "type": PartType.RESULT,
                "content": {"notified": bool(notified)}
            }
        ])


__all__ = ["NotificationAgent"]
