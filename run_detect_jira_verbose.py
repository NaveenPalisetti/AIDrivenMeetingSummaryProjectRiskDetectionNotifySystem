import requests
import json
import base64
import logging
from datetime import datetime, timedelta
from Log.logger import setup_logging
from meeting_mcp.agents.risk_detection_agent import RiskDetectionAgent


def sample_query(agent, jql, logger):
    logger.debug('JQL: %s', jql)
    if not agent.jira_url or not agent.jira_user or not agent.jira_token:
        logger.error('Missing credentials for REST API call.')
        return

    # Use the mandatory /search/jql endpoint with POST
    url = f"{agent.jira_url.rstrip('/')}/rest/api/3/search/jql"
    auth_str = base64.b64encode(f"{agent.jira_user}:{agent.jira_token}".encode('utf-8')).decode('ascii')
    headers = {
        'Authorization': f'Basic {auth_str}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    payload = {"jql": jql, "maxResults": 10}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=20)
        response.raise_for_status()
        data = response.json()
        issues = data.get('issues', [])

        logger.info('Found %d issues', len(issues))
        for isu in issues:
            fields = isu.get('fields', {})
            assignee = fields.get('assignee', {})
            assignee_name = assignee.get('displayName') if assignee else 'Unassigned'
            logger.info('- %s | %s | assignee=%s | duedate=%s', isu.get('key'), fields.get('summary'), assignee_name, fields.get('duedate'))
    except Exception as e:
        logger.exception('Query error: %s', e)
        if hasattr(e, 'response') and e.response is not None:
            logger.debug('Response Details: %s', e.response.text)


def main():
    # Configure logging
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info('Initializing RiskDetectionAgent...')
    agent = RiskDetectionAgent()

    if not agent.jira_url:
        logger.error('Jira URL not found. Check environment variables or credentials.json.')
        return

    # Test server connectivity via the library (server_info usually still works)
    if agent.jira:
        try:
            info = agent.jira.server_info()
            logger.info('Connected to: %s', info.get('baseUrl'))
        except Exception:
            logger.warning('Note: Library server_info failed, but will proceed with REST calls.')

    proj = agent.jira_project or ''

    # Standard Queries using the fixed endpoint
    sample_query(agent, f'project="{proj}" ORDER BY created DESC', logger)
    sample_query(agent, f'project="{proj}" AND assignee is EMPTY AND statusCategory != Done', logger)
    sample_query(agent, f'project="{proj}" AND duedate is EMPTY AND statusCategory != Done', logger)
    sample_query(agent, f'project="{proj}" AND duedate <= now() AND statusCategory != Done', logger)

    stale_date = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
    sample_query(agent, f'project="{proj}" AND updated <= "{stale_date}" AND statusCategory != Done', logger)

    logger.info('Verbose run complete.')


if __name__ == '__main__':
    main()