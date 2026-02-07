import sys
import pathlib
import json
import asyncio
import os
import streamlit as st
import logging
import re
import logging
# Ensure project root is importable when Streamlit runs the script.
# This is a small developer convenience (prefer running Streamlit from
# the project root or setting PYTHONPATH in production).
ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Avoid forcing a global DEBUG root level here; let the project's setup_logging
# control file and console handlers. Configure a module logger and call
# setup_logging at INFO level to reduce noisy third-party debug logs (e.g. watchdog).
logger = logging.getLogger("meeting_mcp.ui.streamlit_agent_client")
try:
    from Log.logger import setup_logging
    log_path = setup_logging(level=logging.INFO)
    logger.info(f'Logging configured: {log_path}')
    # Reduce noisy watchdog debug output when running in environments like Colab
    logging.getLogger('watchdog').setLevel(logging.INFO)
    logging.getLogger('watchdog.observers').setLevel(logging.INFO)
    logging.getLogger('watchdog.observers.inotify_buffer').setLevel(logging.INFO)
except Exception as _e:
    # Fallback: ensure console logging at INFO so Streamlit output appears
    logging.basicConfig(level=logging.INFO)
    logger.info("setup_logging() failed in streamlit UI: %s", _e)

from meeting_mcp.system import create_system
from meeting_mcp.ui.renderers import (
    render_css,
    render_chat_messages,
    render_calendar_result,
    render_processed_chunks,
    render_summary_result,
    render_risk_result,
    render_notification_result,
    render_jira_result,
)


# Page config
st.set_page_config(
    page_title="AI-Driven Meeting Summary & Project Risk Management",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)





@st.cache_resource
def create_runtime(mode: str = "hybrid"):
    # Returns: (mcp_host, inproc_host, tools, orchestrator)
    return create_system(mode=mode)


# Runtime selection: in-process (dev) or server-backed (prod)
MCP_MODE = os.environ.get("MCP_MODE", "in_process").lower()
mcp_client = None
if MCP_MODE == "server":
    try:
        from meeting_mcp.client.mcp_client import MCPClient

        mcp_client = MCPClient()
        mcp_host = inproc_host = tools = orchestrator = None
        logger.info("MCP client initialized for server mode: %s", os.environ.get("MCP_SERVER_URL", "http://localhost:8000"))
    except Exception as e:
        logger.exception("Failed to initialize MCPClient, falling back to in-process: %s", e)
        mcp_host, inproc_host, tools, orchestrator = create_runtime()
else:
    # No runtime selector in chat-only UX; use default wiring
    mcp_host, inproc_host, tools, orchestrator = create_runtime()

logger.info(" mode  %s", MCP_MODE)
def run_orchestrate(prompt: str, params: dict, session_id: str = None) -> dict:
    """Adapter to run orchestration either via local orchestrator or MCP server client."""
    if mcp_client:
        return mcp_client.orchestrate(prompt, params or {}, session_id=session_id)
    # local in-process orchestrator
    return asyncio.run(orchestrator.orchestrate(prompt, params or {}, session_id=session_id))

# Create a persistent MCP session for this Streamlit user (UI-managed)
# On startup (or refresh) end any previously active `streamlit-user` sessions
if "mcp_session_id" not in st.session_state:
    try:
        # Safely iterate over a snapshot of sessions
        for sid, meta in list(getattr(mcp_host, "sessions", {}).items()):
            try:
                if meta.get("agent_id") == "streamlit-user" and meta.get("active"):
                    mcp_host.end_session(sid)
                    logger.debug("Ended previous streamlit-user session on startup: %s", sid)
            except Exception:
                logger.exception("Failed to end previous session: %s", sid)
    except Exception as _e:
        logger.debug("Error while checking for existing sessions: %s", _e)

    try:
        st.session_state["mcp_session_id"] = mcp_host.create_session(agent_id="streamlit-user")
        logger.debug("Created persistent MCP session for Streamlit: %s", st.session_state.get("mcp_session_id"))
    except Exception as _e:
        st.session_state["mcp_session_id"] = None
        logger.debug("Failed to create persistent MCP session: %s", _e)


# Initialize message history in session state
if "messages" not in st.session_state:
    st.session_state.messages = []


def add_message(role: str, content: str):
    # Central debug logging for every add_message call (truncated content)
    try:
        safe_content = (content[:200] + '...') if isinstance(content, str) and len(content) > 200 else content
        logger.debug("add_message called: role=%s content=%s", role, safe_content)
    except Exception:
        pass

    # Avoid storing empty messages or immediate duplicates (prevents empty avatar bubbles
    # and duplicate user entries when actions trigger multiple handlers).
    try:
        if not content:
            return
        if "messages" not in st.session_state:
            st.session_state.messages = []
        if st.session_state.messages:
            last = st.session_state.messages[-1]
            if last.get("role") == role and last.get("content") == content:
                return
        logger.debug("Appending message: role=%s content=%s", role, content)
        st.session_state.messages.append({"role": role, "content": content})
    except Exception:
        # Fallback: ensure at least we append to messages
        try:
            logger.debug("Fallback append message: role=%s", role  )
            st.session_state.messages.append({"role": role, "content": content})
        except Exception:
            pass


def credentials_status() -> str:
    # Check env var or repo config path
    env_path = os.environ.get("MCP_SERVICE_ACCOUNT_FILE")
    if env_path and os.path.exists(env_path):
        return f"Using {env_path} (MCP_SERVICE_ACCOUNT_FILE)"
    fallback = os.path.join(os.path.dirname(__file__), "../config/credentials.json")
    fallback = os.path.abspath(fallback)
    if os.path.exists(fallback):
        return f"Using {fallback} (meeting_mcp/config/credentials.json)"
    return "No credentials found — set MCP_SERVICE_ACCOUNT_FILE or place credentials.json in meeting_mcp/config/"


def _load_local_credentials():
    try:
        cred_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../config/credentials.json"))
        if os.path.exists(cred_path):
            with open(cred_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


render_css()

# Page heading similar to orchestrator_streamlit_client
st.title("🤖 AI-Driven Meeting Summary & Project Risk Management")
st.caption("A lightweight UI to run the orchestrator and inspect results.")


# Sidebar: summarizer/model selector (BART / Mistral)
with st.sidebar:
    st.header("🧠 Summarizer Model")
    if 'summarizer_model' not in st.session_state:
        st.session_state['summarizer_model'] = 'BART'
    model_choice = st.radio("Choose a summarizer:", ["BART", "Mistral"], key="summarizer_model")
    # (Risk detection is handled via chat commands and per-event buttons,
    # not via the sidebar. Use "detect risk" or the calendar event actions.)
    st.markdown("---")
    st.header("Quick Links")
    # Display clickable quick links (read from session state, env, or credentials file)
    creds = st.session_state.get('credentials_cache')
    if creds is None:
        creds = _load_local_credentials()
        st.session_state['credentials_cache'] = creds

    # Accept multiple common credential key variants to be resilient to naming
    def _pick(*keys, default=''):
        for k in keys:
            # check session override first
            if k == 'jira_url' and st.session_state.get('jira_url'):
                return st.session_state.get('jira_url')
            if k == 'slack_url' and st.session_state.get('slack_url'):
                return st.session_state.get('slack_url')
            if k == 'calendar_url' and st.session_state.get('calendar_url'):
                return st.session_state.get('calendar_url')
            # then environment
            v = os.environ.get(k)
            if v:
                return v
            # then credentials file (various casings)
            if creds:
                for variant in (k, k.upper(), k.lower()):
                    try:
                        v = creds.get(variant)
                    except Exception:
                        v = None
                    if v:
                        return v
        return default

    jira_url = _pick('JIRA_DASHBOARD_URL', 'JIRA_URL', 'jira_url')
    slack_url = _pick('SLACK_URL', 'slack_url')
    calendar_url = _pick('CALENDAR_URL', 'calendar_url')

    if jira_url:
        st.markdown(f"- [Open Jira dashboard]({jira_url})")
    else:
        st.markdown("- Jira dashboard: **Not configured**")

    if slack_url:
        st.markdown(f"- [Open Slack]({slack_url})")
    else:
        st.markdown("- Slack: **Not configured**")

    if calendar_url:
        st.markdown(f"- [Open Calendar]({calendar_url})")
    else:
        st.markdown("- Calendar: **Not configured**")

    st.markdown("---")
    st.header("MCP Session")
    sid = st.session_state.get("mcp_session_id")
    if sid:
        st.write(f"Session: {sid}")
        if st.button("End MCP Session"):
            try:
                mcp_host.end_session(sid)
                st.session_state.pop("mcp_session_id", None)
                st.success("MCP session ended")
            except Exception as e:
                st.error(f"Failed to end MCP session: {e}")
    else:
        if st.button("Start MCP Session"):
            try:
                st.session_state["mcp_session_id"] = mcp_host.create_session(agent_id="streamlit-user")
                st.success("MCP session started")
            except Exception as e:
                st.error(f"Failed to start MCP session: {e}")

col1 = st.container()

    # Chat-only message area using Streamlit's chat components
render_chat_messages(st.session_state.messages)

# Chat input: submit with Enter — runs the orchestrator by default
if prompt := st.chat_input("Describe your request (press Enter to send)"):
    add_message("user", prompt)
    with st.chat_message("user"):
        st.markdown(prompt)

    # Run orchestrator (chat-only UX; no params textarea)
    try:
        # Check for chat command that references last fetched events (e.g. "preprocess this <title>")
        handled = False
        # Ensure `result` is always defined to avoid NameError in downstream handling
        result = {"intent": "", "results": {}}
        lower = (prompt or "").lower()
        # Local greeting handler: intercept simple greetings and return a short canned reply
        try:
            greeting_re = r"^\s*(hi|hello|hey|good morning|good afternoon|good evening|how are you|how can you help|what can you do)\b"
            if re.search(greeting_re, lower):
                print("Greeting detected in prompt")
                logger.debug("Greeting detected in prompt")
                canned = (
                    "AI Orchestrator Help:\n\n"
                    "Calendar / Fetch:\n"
                    "- Commands: 'fetch calendar', 'get calendar events', or free-form like 'show my calendar for next 7 days'\n"
                    "- Result: events are displayed in the calendar renderer with per-event actions.\n\n"
                    "Preprocess (chat or per-event button):\n"
                    "- Chat examples:\n"
                    "  * 'preprocess this meeting' (uses last fetched events)\n"
                    "  * 'preprocess transcripts for Project Sync'\n"
                    "- Per-event: click 'Preprocess this meeting' inside an event expander.\n\n"
                    "Summarize (chat or per-event button):\n"
                    "- Chat examples:\n"
                    "  * 'summarize this meeting'\n"
                    "  * 'summarize \"Project Sync Jan 20 2026\"'\n"
                    "  * 'summarize meeting: \"Weekly Standup\"'\n"
                    "- Per-event: click 'Summarize this meeting'.\n\n"
                    "Create Jira (chat or per-action):\n"
                    "- Chat examples:\n"
                    "  * 'create jira: Fix the payment bug'\n"
                    "  * 'create jira for \"Update deployment pipeline\"'\n"
                    "  * 'create jira 1' (refers to indexed last action items)\n"
                    "- Per-action: click 'Create Jira' inside an action-item expander.\n\n"
                    "Detect Risks (chat or per-event):\n"
                    "- Chat examples:\n"
                    "  * 'detect risk for \"Project Sync Jan 20 2026\"'\n"
                    "  * 'detect risks for this meeting'\n"
                    "- Per-event: click 'Detect Risks for this meeting'.\n\n"
                    "Notify (chat or per-event):\n"
                    "- Chat examples:\n"
                    "  * 'notify team for \"Project Sync Jan 20 2026\"'\n"
                    "  * 'send notification for this meeting'\n"
                    "- Per-event: click 'Notify team for this meeting'.\n\n"
                    "Flow (example sequence):\n"
                    "1) 'preprocess \"Meeting Title\"' or click Preprocess.\n"
                    "2) 'summarize \"Meeting Title\"' or click Summarize.\n"
                    "3) 'detect risks for \"Meeting Title\"' or click Detect Risks.\n"
                    "4) 'notify team for \"Meeting Title\"' or click Notify.\n\n"
                    "Use the sidebar to switch summarizers (BART / Mistral) and open Quick Links for Jira/Slack/Calendar."
                )
                add_message("assistant", canned)
                with st.chat_message("assistant"):
                    st.markdown(canned)
                handled = True
        except Exception:
            # If greeting handler fails, fall back to normal flow
            handled = False
        # Summarize command: if user asks to summarize a previously preprocessed meeting
        if "summarize" in lower and st.session_state.get("last_events"):
            import re

            title = None
            mq = re.search(r'["\u201c\u201d](?P<tq>[^"\u201c\u201d]+)["\u201c\u201d]', prompt)
            if mq:
                title = mq.group("tq").strip()
            else:
                m = re.search(r'summarize(?: this)?(?: meeting)?(?: for|:)?\s*(?P<tu>.+?)(?:$|\s{2,}|["\'])', prompt, flags=re.I)
                if m:
                    title = (m.group("tu") or "").strip()

            if title:
                title = re.split(r"\s{2,}|(?i:\sbut\s)|(?i:\sand\s)|[\"']", title)[0].strip()

            matched = None
            if not title:
                for ev in st.session_state.get("last_events", []):
                    summary = (ev.get("summary") or "")
                    if summary and summary.lower() in prompt.lower():
                        matched = ev
                        break
            if title and not matched:
                best_score = 0
                for ev in st.session_state.get("last_events", []):
                    summary = (ev.get("summary") or "")
                    if not summary:
                        continue
                    s_words = re.findall(r"\w+", summary.lower())
                    if not s_words:
                        continue
                    score = sum(1 for w in set(s_words) if w in title.lower())
                    if score > best_score:
                        best_score = score
                        matched = ev
            if not matched and title:
                for ev in st.session_state.get("last_events", []):
                    summary = (ev.get("summary") or "")
                    if title.lower() in summary.lower() or summary.lower() in title.lower():
                        matched = ev
                        break

            if matched:
                meeting_title = matched.get('summary')
                # Try to find cached processed chunks for this meeting
                cache = st.session_state.get('processed_cache', {})
                processed = cache.get(meeting_title)
                

                try:
                    logger.debug("Orchestrator preprocess call: meeting=%s", matched.get('summary'))
                    if not processed:
                        # If not preprocessed, trigger preprocess first
                        preprocess_text = matched.get("description") or matched.get("summary") or ""
                        params = {"transcripts": [preprocess_text], "chunk_size": 1500}
                        logger.debug("Preprocess params: %s", {k: (str(v)[:200] + '...' if isinstance(v, (str, list, dict)) and len(str(v))>200 else v) for k,v in params.items()})
                        proc_result = run_orchestrate(f"preprocess transcripts for {meeting_title}", params, session_id=st.session_state.get("mcp_session_id"))
                        logger.debug("Preprocess result (truncated): %s", str(proc_result)[:1000])
                        proc_summary = proc_result.get("results", {}).get("transcript") or proc_result.get("results")
                        if isinstance(proc_summary, dict) and proc_summary.get("status") == "success":
                            processed = proc_summary.get("processed")
                            # cache it for reuse
                            try:
                                if "processed_cache" not in st.session_state:
                                    st.session_state["processed_cache"] = {}
                                st.session_state["processed_cache"][meeting_title] = processed
                            except Exception:
                                pass

                    # Now call summarization tool via orchestrator
                    mode = st.session_state.get('summarizer_model', 'BART')
                    mode_param = 'bart' if mode.lower().startswith('b') else 'mistral'
                    logger.debug("Orchestrator summarize call: meeting=%s, mode=%s", meeting_title, mode_param)
                    params = {"processed_transcripts": processed or [], "mode": mode_param}
                    logger.debug("Summarize params: processed_count=%d", len(params.get("processed_transcripts", [])))
                    sum_result = run_orchestrate(f"summarize meeting {meeting_title}", params, session_id=st.session_state.get("mcp_session_id"))
                    logger.debug("Summarize result (truncated): %s", str(sum_result)[:2000])
                    sum_block = sum_result.get('results', {}).get('summarization') or sum_result.get('results')
                    if isinstance(sum_block, dict) and sum_block.get('status') == 'success':
                        summary_obj = sum_block.get('summary')
                    else:
                        # Tool-level fallback
                        summary_obj = sum_block

                    # Ensure `result` is defined for downstream handling
                    try:
                        result = {"intent": "summarize", "results": {"summarization": sum_block}}
                    except Exception:
                        result = {"intent": "summarize", "results": {"summarization": summary_obj}}

                    # Render summary and action items
                    #add_message("assistant", f"Summary for {meeting_title} ready.")
                    with st.chat_message("assistant"):
                        render_summary_result(summary_obj, meeting_title, add_message, orchestrator, run_orchestrate=run_orchestrate)
                        try:
                            st.session_state['suppress_calendar_render'] = True
                        except Exception:
                            pass
                except Exception as e:
                    add_message("system", f"Error: {e}")
                    with st.chat_message("assistant"):
                        st.markdown(f"Error: {e}")

                handled = True
        # Detect risk command: mirror summarize flow but call orchestrator with risk intent        
        if ("detect risk" in lower or "risk" in lower) and st.session_state.get("last_events"):
            print("Risk detection command detected in chat")
            logger.debug("Risk detection command detected in chat")
            title = None
            mq = re.search(r'["\u201c\u201d](?P<tq>[^"\u201c\u201d]+)["\u201c\u201d]', prompt)
            if mq:
                title = mq.group("tq").strip()
            else:
                m = re.search(r'detect\s*risks?(?: for|:)?\s*(?P<tu>.+?)(?:$|\s{2,}|["\'])', prompt, flags=re.I)
                if m:
                    title = (m.group("tu") or "").strip()

            if title:
                title = re.split(r"\s{2,}|(?i:\sbut\s)|(?i:\sand\s)|[\"']", title)[0].strip()

            matched = None
            if not title:
                for ev in st.session_state.get("last_events", []):
                    summary = (ev.get("summary") or "")
                    if summary and summary.lower() in prompt.lower():
                        matched = ev
                        break

            if title and not matched:
                best_score = 0
                for ev in st.session_state.get("last_events", []):
                    summary = (ev.get("summary") or "")
                    if not summary:
                        continue
                    s_words = re.findall(r"\w+", summary.lower())
                    if not s_words:
                        continue
                    score = sum(1 for w in set(s_words) if w in title.lower())
                    if score > best_score:
                        best_score = score
                        matched = ev

            if not matched and title:
                for ev in st.session_state.get("last_events", []):
                    summary = (ev.get("summary") or "")
                    if title.lower() in summary.lower() or summary.lower() in title.lower():
                        matched = ev
                        break
            # Additional fallbacks when the initial heuristics don't match:
            # 1) Compare prompt word-overlap against event summaries (robust fuzzy match)
            # 2) If still no match, pick the most-recent event as a reasonable default
            if not matched:
                try:
                    prompt_words = set(re.findall(r"\w+", prompt.lower()))
                    best = None
                    best_score = 0
                    for ev in st.session_state.get("last_events", []):
                        summary = (ev.get("summary") or "")
                        if not summary:
                            continue
                        s_words = set(re.findall(r"\w+", summary.lower()))
                        score = sum(1 for w in s_words if w in prompt_words)
                        if score > best_score:
                            best_score = score
                            best = ev
                    if best_score > 0:
                        matched = best
                except Exception:
                    matched = None

            if not matched:
                try:
                    events = list(st.session_state.get("last_events", []))
                    if events:
                        # pick most-recent by start datetime as a sensible default
                        def _start_key(ev):
                            sd = ev.get('start', {}).get('dateTime') or ev.get('start', {}).get('date') or ''
                            return sd
                        events_sorted = sorted(events, key=_start_key, reverse=True)
                        matched = events_sorted[0]
                except Exception:
                    matched = None

            print("Risk detection matched event: ", matched)
            logger.debug("Risk detection matched event: %s", matched)
            if matched:
                meeting_title = matched.get('summary') or matched.get('id')
                # Build params similar to event-based detect
                params = {"meeting_id": meeting_title, "summary": {"summary_text": matched.get('description') or matched.get('summary')}}
                if st.session_state.get('last_action_items'):
                    params['tasks'] = st.session_state.get('last_action_items')

                try:
                    logger.debug("Orchestrator risk call (chat): %s", meeting_title)
                    risk_result = run_orchestrate(f"detect risk for {meeting_title}", params, session_id=st.session_state.get("mcp_session_id"))
                    logger.debug("Risk result (chat): %s", str(risk_result)[:1000])
                    add_message("assistant", f"Risk detection for {meeting_title} completed.")
                    with st.chat_message("assistant"):
                        render_risk_result(risk_result, meeting_title if 'meeting_title' in locals() else None, add_message)
                        try:
                            st.session_state['suppress_calendar_render'] = True
                        except Exception:
                            pass
                    
                
                except Exception as e:
                    add_message("system", f"Error running risk detection: {e}")
                    with st.chat_message("assistant"):
                        st.markdown(f"Error running risk detection: {e}")

                handled = True
        # Create Jira command: allow user to type "create jira: <task>" or "create jira for <task>"
        if ("create jira" in lower or "createissue" in lower) and st.session_state.get('last_action_items'):
            
            try:
                import re
                # Extract quoted title first
                title = None
                mq = re.search(r'["\u201c\u201d](?P<tq>[^"\u201c\u201d]+)["\u201c\u201d]', prompt)
                if mq:
                    title = mq.group('tq').strip()
                else:
                    m = re.search(r'create\s*jira(?:\s*for|:)?\s*(?P<tu>.+)$', prompt, flags=re.I)
                    if m:
                        title = (m.group('tu') or '').strip()

                matched = None
                items = st.session_state.get('last_action_items', [])
                logger.debug("Create Jira command: title=%s, items_count=%d, items = %s", title, len(items),items)   
                if title:
                    # try numeric index
                    if title.isdigit():
                        idx = int(title) - 1
                        if 0 <= idx < len(items):
                            matched = items[idx]
                    if not matched:
                        best = None
                        best_score = 0
                        for it in items:
                            text = (it.get('summary') or it.get('task') or it.get('title') or '')
                            if not text:
                                continue
                            score = sum(1 for w in set(re.findall(r"\w+", text.lower())) if w in title.lower())
                            if score > best_score:
                                best_score = score
                                best = it
                        if best_score > 0:
                            matched = best

                # If matched, call orchestrator's jira tool
                if matched:
                    task = matched.get('summary') or matched.get('task') or matched.get('title') or ''
                    owner = matched.get('assignee') or matched.get('owner') or matched.get('assigned_to') or None
                    due = matched.get('due') or matched.get('deadline') or matched.get('due_date') or None
                    
                    # Build params for orchestrator and also include `action_items` list
                    action_item = {"summary": task, "assignee": owner, "due_date": due}
                    params = {"task": task, "owner": owner, "deadline": due, "action_items": [action_item], "action_items_list": [action_item]}
                    # Debug: log the matched item and the params in full (truncated for long fields)
                    logger.debug("Matched action item for Jira: %s", matched)
                    logger.debug("Orchestrator jira call: task=%s", (task or '')[:200])
                    logger.debug("Jira params: %s", {k: (str(v)[:200] + '...' if isinstance(v, (str, list, dict)) and len(str(v))>200 else v) for k,v in params.items()})
                    print("Jira params: %s" % {k: (str(v)[:200] + '...' if isinstance(v, (str, list, dict)) and len(str(v))>200 else v) for k,v in params.items()})
                    logger.debug("Jira params: %s", {k: (str(v)[:200] + '...' if isinstance(v, (str, list, dict)) and len(str(v))>200 else v) for k,v in params.items()})
                    try:
                        jira_result = run_orchestrate(f"create jira for {task}", params, session_id=st.session_state.get("mcp_session_id"))
                        logger.debug("Jira result: %s", str(jira_result)[:1000])
                        # Persist the orchestrator result so the UI shows the correct intent later
                        try:
                            result = {"intent": "create_jira", "results": jira_result}
                        except Exception:
                            result = {"intent": "create_jira", "results": {}}
                        add_message('assistant', f"Jira creation result: {jira_result.get('results', {})}")
                        with st.chat_message('assistant'):
                            render_jira_result(jira_result, title=task, add_message=add_message)
                        try:
                            st.session_state['suppress_calendar_render'] = True
                        except Exception:
                            pass   
                    except Exception as e:
                        add_message('system', f"Error creating Jira: {e}")
                        with st.chat_message('assistant'):
                            st.markdown(f"Error creating Jira: {e}")
                    handled = True
            except Exception as e:
                logger.exception("Failed to handle create jira command: %s", e)
        # Notify command: allow user to type "notify <meeting>" or "send notification for <meeting>"
        if ("notify" in lower or "send notification" in lower or "notify team" in lower) and st.session_state.get('last_events'):
            print("Notify command detected in chat",st.session_state.get('last_events'))
            logger.debug("Notify command detected in chat: %s", st.session_state.get('last_events'))
            try:
                import re
                title = None
                mq = re.search(r'["\u201c\u201d](?P<tq>[^"\u201c\u201d]+)["\u201c\u201d]', prompt)
                if mq:
                    title = mq.group('tq').strip()
                else:
                    m = re.search(r'notify(?:\s+team)?(?:\s+for|:)?\s*(?P<tu>.+)$', prompt, flags=re.I)
                    if m:
                        title = (m.group('tu') or '').strip()

                matched = None
                items = st.session_state.get('last_events', [])
                if not title:
                    for ev in items:
                        summary = (ev.get('summary') or '')
                        if summary and summary.lower() in prompt.lower():
                            matched = ev
                            break

                if title and not matched:
                    best = None
                    best_score = 0
                    for ev in items:
                        text = (ev.get('summary') or ev.get('description') or '')
                        if not text:
                            continue
                        score = sum(1 for w in set(re.findall(r"\w+", text.lower())) if w in title.lower())
                        if score > best_score:
                            best_score = score
                            best = ev
                    if best_score > 0:
                        matched = best
                # Additional fallbacks when no exact/title match found:
                if not matched:
                    try:
                        prompt_words = set(re.findall(r"\w+", prompt.lower()))
                        best = None
                        best_score = 0
                        for ev in items:
                            text = (ev.get('summary') or ev.get('description') or '')
                            if not text:
                                continue
                            s_words = set(re.findall(r"\w+", text.lower()))
                            score = sum(1 for w in s_words if w in prompt_words)
                            if score > best_score:
                                best_score = score
                                best = ev
                        if best_score > 0:
                            matched = best
                    except Exception:
                        matched = None

                if not matched:
                    try:
                        events = list(items)
                        if events:
                            def _start_key(ev):
                                sd = ev.get('start', {}).get('dateTime') or ev.get('start', {}).get('date') or ''
                                return sd
                            events_sorted = sorted(events, key=_start_key, reverse=True)
                            matched = events_sorted[0]
                    except Exception:
                        matched = None

                print("Notify matched event: ", matched)
                logger.debug("Notify matched event: %s", matched)
                if matched:
                    meeting_title = matched.get('summary') or matched.get('id')
                    params = {"meeting_id": meeting_title, "summary": {"summary_text": matched.get('description') or matched.get('summary')}}
                    if st.session_state.get('last_action_items'):
                        params['tasks'] = st.session_state.get('last_action_items')
                    if st.session_state.get('last_risks_details'):
                        params['risks'] = st.session_state.get('last_risks')

                    print("Notify matched event: ", matched)
                    logger.debug("Notify matched event: %s", matched)
                    try:
                        logger.debug("Orchestrator notify call: %s", params)
                        notify_result = run_orchestrate(f"notify for {meeting_title}", params, session_id=st.session_state.get("mcp_session_id"))
                        logger.debug("Notify result: %s", str(notify_result)[:1000])
                        add_message('assistant', f"Notification result for {meeting_title}: {notify_result.get('results', {})}")
                        with st.chat_message('assistant'):
                            try:
                                render_notification_result(notify_result, meeting_title, add_message)
                                try:
                                    st.session_state['suppress_calendar_render'] = True
                                except Exception:
                                    pass
                            except Exception:
                                st.markdown(f"Notification result:\n\n```json\n{json.dumps(notify_result, indent=2)}\n```")
                    except Exception as e:
                        add_message('system', f"Error sending notification: {e}")
                        with st.chat_message('assistant'):
                            st.markdown(f"Error sending notification: {e}")

                    handled = True
            except Exception as e:
                logger.exception("Failed to handle notify command: %s", e)
        if "preprocess" in lower and st.session_state.get("last_events"):
            import re

            # Robust title extraction:
            # 1. Prefer the first quoted string if present
            # 2. Else try to capture text immediately following the preprocess phrase
            # 3. Fallback to fuzzy/overlap matching against cached `last_events`
            title = None
            mq = re.search(r'["\u201c\u201d](?P<tq>[^"\u201c\u201d]+)["\u201c\u201d]', prompt)
            if mq:
                title = mq.group("tq").strip()
            else:
                m = re.search(r'preprocess(?: this)?(?: meeting)?(?: for|:)?\s*(?P<tu>.+?)(?:$|\s{2,}|["\'])', prompt, flags=re.I)
                if m:
                    title = (m.group("tu") or "").strip()

            if title:
                # Heuristic clean: stop at obvious separators or trailing commentary
                title = re.split(r"\s{2,}|(?i:\sbut\s)|(?i:\sand\s)|[\"']", title)[0].strip()

            matched = None
            # If we didn't get a clean title, try substring match first
            if not title:
                for ev in st.session_state.get("last_events", []):
                    summary = (ev.get("summary") or "")
                    if summary and summary.lower() in prompt.lower():
                        matched = ev
                        break

            # If we got a title, pick the best event by word-overlap score
            if title and not matched:
                best_score = 0
                for ev in st.session_state.get("last_events", []):
                    summary = (ev.get("summary") or "")
                    if not summary:
                        continue
                    s_words = re.findall(r"\w+", summary.lower())
                    if not s_words:
                        continue
                    score = sum(1 for w in set(s_words) if w in title.lower())
                    if score > best_score:
                        best_score = score
                        matched = ev

            # final fallback: simple contains checks
            if not matched and title:
                for ev in st.session_state.get("last_events", []):
                    summary = (ev.get("summary") or "")
                    if title.lower() in summary.lower() or summary.lower() in title.lower():
                        matched = ev
                        break

            if matched:
                preprocess_text = matched.get("description") or matched.get("summary") or ""
                
                
                try:
                    params = {"transcripts": [preprocess_text], "chunk_size": 1500}
                    logger.debug("Orchestrator preprocess call (explicit): meeting=%s", matched.get('summary'))
                    logger.debug("Preprocess params: %s", {k: (str(v)[:200] + '...' if isinstance(v, (str, list, dict)) and len(str(v))>200 else v) for k,v in params.items()})
                    proc_result = run_orchestrate(f"preprocess transcripts for {matched.get('summary')}", params, session_id=st.session_state.get("mcp_session_id"))
                    logger.debug("Preprocess result (truncated): %s", str(proc_result)[:1000])
                    # ensure downstream code that expects `result` has a value
                    result = proc_result
                    proc_summary = proc_result.get("results", {}).get("transcript") or proc_result.get("results")
                    if isinstance(proc_summary, dict) and proc_summary.get("status") == "success":
                        processed = proc_summary.get("processed", []) if isinstance(proc_summary, dict) else None
                        if isinstance(processed, list):
                            assistant_md = f"Preprocessed {len(processed)} chunk(s) for {matched.get('summary')}."
                        else:
                            assistant_md = "Preprocessing completed."
                    else:
                        assistant_md = f"Preprocessing result: {proc_result}"

                    # Only persist and display assistant output when preprocess succeeded
                    if isinstance(proc_summary, dict) and proc_summary.get("status") == "success":
                        processed = proc_summary.get("processed")
                        debug = proc_summary.get("debug") if isinstance(proc_summary, dict) else None
                        if processed:
                            assistant_text = assistant_md if assistant_md and str(assistant_md).strip() else None
                            if assistant_text:
                                add_message("assistant", assistant_text)
                                with st.chat_message("assistant"):
                                    st.markdown(assistant_text)
                                    render_processed_chunks(processed, matched.get('summary'), add_message, debug)
                                    try:
                                        st.session_state['suppress_calendar_render'] = True
                                    except Exception:
                                        pass
                except Exception as e:
                    add_message("system", f"Error: {e}")
                    with st.chat_message("assistant"):
                        st.markdown(f"Error: {e}")

                handled = True

        if not handled:
            logger.debug("Orchestrator free-form call: prompt=%s", (prompt or '')[:500])
            result = run_orchestrate(prompt, {}, session_id=st.session_state.get("mcp_session_id"))
            logger.debug("Orchestrator free-form result (truncated): %s", str(result)[:2000])

        # Add a compact system entry for history (keeps messages small)
        logger.debug("Orchestrator result intent: %s", result.get("intent", ""))
        short_summary = result.get("intent", "")
        add_message("system", f"intent: {short_summary}")
        # If a preprocess action just ran and requested suppression, avoid re-rendering calendar/JSON
        suppress = st.session_state.pop('suppress_calendar_render', False)


        # Prepare assistant content to persist in session history
        calendar_block = None if suppress else (result.get("results", {}).get("calendar") if isinstance(result, dict) else None)
        if calendar_block and calendar_block.get("status") == "success":
            events = calendar_block.get("events", [])
            # persist most recent fetched events so chat commands can reference them
            st.session_state['last_events'] = events
            
            # Build a concise markdown summary for session history
            if not events:
                assistant_md = "No calendar events found for the requested range."
            else:
                lines = [f"**Calendar:** {len(events)} event(s) returned"]
                for ev in events[:10]:
                    when = ev.get('start', {}).get('dateTime') or ev.get('start', {}).get('date')
                    lines.append(f"- {when} — {ev.get('summary')}")
                if len(events) > 10:
                    lines.append(f"...and {len(events)-10} more events")
                assistant_md = "\n".join(lines)
        else:
            # Fallback: short textual summary
            assistant_md = f"Result: intent={result.get('intent')}"

        # Persist and render assistant summary only when there is meaningful content.
        # If a successful calendar_block with events is present, show the calendar renderer
        # and persist the assistant summary; otherwise only show the JSON fallback when
        # rendering is not suppressed and we have a non-empty assistant_md.
        if calendar_block and calendar_block.get("status") == "success":
            events = calendar_block.get("events", [])
            if events:
                assistant_text = assistant_md if assistant_md and str(assistant_md).strip() else None
                if assistant_text:
                    add_message("assistant", assistant_text)
                    with st.chat_message("assistant"):
                        render_calendar_result(calendar_block, orchestrator, add_message, run_orchestrate=run_orchestrate)
            else:
                # No events -> skip creating an assistant bubble
                pass
        else:
            # Fallback: only show JSON result when rendering not suppressed
            if not suppress and assistant_md and str(assistant_md).strip():
                logger.debug("Rendering fallback assistant_md and JSON result")
                add_message("assistant", assistant_md)
                with st.chat_message("assistant"):
                    st.markdown("Result:\n\n" + "```json\n" + json.dumps(result, indent=2) + "\n```")
    except Exception as e:
        add_message("system", f"Error: {e}")
        with st.chat_message("assistant"):
            st.markdown(f"Error: {e}")

# Status & Tools hidden in chat-only mode per user request
