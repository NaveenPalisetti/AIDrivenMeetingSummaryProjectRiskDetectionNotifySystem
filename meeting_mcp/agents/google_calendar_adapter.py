"""Local adapter for Google Calendar used by `meeting_mcp`.

This adapter lives entirely under `meeting_mcp` so we do not modify the
existing `mcp` package. It reads configuration from `meeting_mcp.config` and
exposes a small subset of the MCPGoogleCalendar API used by our tools.
"""
from __future__ import annotations

import datetime
import os
from datetime import timezone
from typing import List, Dict, Any, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
import logging

logger = logging.getLogger("meeting_mcp.agents.google_calendar")

from meeting_mcp.config import get_config

# Optional helper for robust ISO parsing
try:
    from dateutil import parser as dateutil_parser  # type: ignore
except Exception:
    dateutil_parser = None


SCOPES = ["https://www.googleapis.com/auth/calendar"]


class MeetingMCPGoogleCalendar:
    def __init__(self, service_account_file: Optional[str] = None, calendar_id: Optional[str] = None):
        cfg = get_config()
        # prefer explicit arg, then env/.env via meeting_mcp.config, then repo path fallback
        self.service_account_file = service_account_file or cfg.get("service_account_file")
        if not self.service_account_file:
            repo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../config/credentials.json"))
            if os.path.exists(repo_path):
                self.service_account_file = repo_path

        if not self.service_account_file or not os.path.exists(self.service_account_file):
            raise FileNotFoundError(
                "Service account file not found. Set MCP_SERVICE_ACCOUNT_FILE in environment or place credentials.json in meeting_mcp/config/"
            )

        self.calendar_id = calendar_id or cfg.get("calendar_id") or "naveenaitam@gmail.com"
        creds = service_account.Credentials.from_service_account_file(self.service_account_file, scopes=SCOPES)
        self.service = build("calendar", "v3", credentials=creds)

    def create_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        # Remove attendees to avoid sending invites from service account
        event_data = dict(event_data)
        event_data.pop("attendees", None)
        created = self.service.events().insert(calendarId=self.calendar_id, body=event_data).execute()
        return created

    def fetch_events(self, start_time: Optional[datetime.datetime], end_time: Optional[datetime.datetime]) -> List[Dict[str, Any]]:
        # Accept either datetimes or ISO strings; default to last 30 days when absent
        if start_time is None:
            start_time = datetime.datetime.utcnow().replace(tzinfo=timezone.utc) - datetime.timedelta(days=30)
        if end_time is None:
            end_time = datetime.datetime.utcnow().replace(tzinfo=timezone.utc)

        # If strings provided convert to aware datetimes (UTC)
        def _parse_iso(s: str) -> datetime.datetime:
            if dateutil_parser:
                dt = dateutil_parser.isoparse(s)
            else:
                s2 = s.replace("Z", "+00:00") if s.endswith("Z") else s
                dt = datetime.datetime.fromisoformat(s2)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)

        if isinstance(start_time, str):
            start_time = _parse_iso(start_time)
        if isinstance(end_time, str):
            end_time = _parse_iso(end_time)        
        # Helper to format RFC3339 timestamps expected by Google API
        def _to_rfc3339(dt: datetime.datetime) -> str:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            s = dt.isoformat()
            if s.endswith('+00:00'):
                s = s[:-6] + 'Z'
            return s

        time_min = _to_rfc3339(start_time)
        time_max = _to_rfc3339(end_time)

        # Page through results to ensure we return all events
        events: List[Dict[str, Any]] = []
        page_token = None
        page_num = 0
        logger.debug("Fetching events time_min=%s time_max=%s calendar=%s", time_min, time_max, self.calendar_id)
        while True:
            params = {
                'calendarId': self.calendar_id,
                'timeMin': time_min,
                'timeMax': time_max,
                'singleEvents': True,
                'orderBy': 'startTime',
            }
            if page_token:
                params['pageToken'] = page_token

            events_result = self.service.events().list(**params).execute()
            items = events_result.get('items', [])
            page_num += 1
            logger.debug("Fetched page %d: %d items, nextPageToken=%s", page_num, len(items), events_result.get('nextPageToken'))
            events.extend(items)
            page_token = events_result.get('nextPageToken')
            if not page_token:
                break
        
        return events

    def get_availability(self, time_min: str, time_max: str) -> List[Dict[str, Any]]:
        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": self.calendar_id}],
        }
        result = self.service.freebusy().query(body=body).execute()
        busy = result.get("calendars", {}).get(self.calendar_id, {}).get("busy", [])
        return busy


__all__ = ["MeetingMCPGoogleCalendar"]
