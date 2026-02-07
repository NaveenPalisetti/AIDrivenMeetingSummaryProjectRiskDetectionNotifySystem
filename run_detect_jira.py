import pprint
import os
import logging

from Log.logger import setup_logging
from meeting_mcp.agents.risk_detection_agent import RiskDetectionAgent


def main():
    # Configure logging (creates Log/meeting_mcp.log by default)
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("Using credentials from meeting_mcp/config/credentials.json or environment variables.")
    agent = RiskDetectionAgent()
    if not agent.jira and not agent.jira_url:
        logger.error("Jira client not initialized. Check JIRA_URL, JIRA_USER, JIRA_TOKEN or meeting_mcp/config/credentials.json.")
        return

    risks = agent.detect_jira_risks(days_stale=7)
    pprint.pprint(risks)
    logger.info("Found %d risk(s)", len(risks))


if __name__ == '__main__':
    main()
